import math
import time

import numpy as np
from loguru import logger

from .reflector import Reflector


class Landmark:
    """Reflector landmark detector built on the raw-laser-scan pipeline.

    The onboard ``laser-landmarks`` REST API proved unreliable, so detection is
    integrated here instead: pull a laser scan over SDP (port 1445), keep the
    high-intensity returns that come from retro-reflective strips, cluster them
    and estimate each reflector's world-frame centre and surface normal (yaw).
    Detections are accumulated over several frames and merged, then each is
    matched to an ``initial_guess`` by nearest distance so callers get a stable
    ``{id: {"x", "y", "yaw"}}`` mapping.

    Method
    ------
    1. keep valid points whose quality exceeds ``intensity_threshold``
       (reflectors return far more energy: background ~60, reflectors ~150-252),
    2. transform them into the world frame using the scan pose,
    3. cluster neighbouring returns (angular + euclidean adjacency),
    4. for each cluster estimate centre, physical width and a surface normal
       (PCA, flipped to face the robot) -> yaw,
    5. keep clusters whose width is compatible with ``strip_width``.
    """

    def __init__(self, initial_guess=None, match_range=1.0,
                 host="192.168.11.1", sdp_port=1445,
                 num_frames=10, frame_interval=0.1, merge_distance=0.30,
                 min_support=1,
                 intensity_threshold=150.0, strip_width=0.20,
                 width_tolerance=0.15, min_width=0.10, cluster_gap=0.20,
                 max_angle_gap_deg=2.5, min_points=1):
        self.host = host
        self.sdp_port = sdp_port

        # multi-frame accumulation: single scans miss reflectors (occlusion,
        # grazing angle, range); detections are in the world frame so they
        # line up across frames and can be merged.
        self.num_frames = num_frames          # scans to collect per detection
        self.frame_interval = frame_interval  # seconds between scans
        self.merge_distance = merge_distance  # centres within this (m) = same
        self.min_support = min_support        # drop merges seen in fewer frames

        # per-scan detection tuning
        self.intensity_threshold = intensity_threshold
        self.strip_width = strip_width
        self.width_tolerance = width_tolerance
        self.min_width = min_width
        self.cluster_gap = cluster_gap
        self.max_angle_gap_deg = max_angle_gap_deg
        self.min_points = min_points

        # {id: {"x": float, "y": float}} expected positions used to match detections
        self.initial_guess = initial_guess if initial_guess is not None else {}
        # max distance (meters) between a guess and a detection to count as a match
        self.match_range = match_range
        # {id: {"x": float, "y": float, "yaw": float}} detections matched to each guess
        self.detected_landmark = {}

    # -- detection pipeline -------------------------------------------------

    def detect(self):
        """Accumulate scans over SDP and return a merged list[Reflector]."""
        from ..slamware_sdp import SlamwareSDP

        all_refs = []
        with SlamwareSDP(self.host, self.sdp_port) as sdp:
            for i in range(self.num_frames):
                points, pose = sdp.get_laser_scan()
                all_refs.extend(self._detect_one(points, pose))
                if self.frame_interval and i < self.num_frames - 1:
                    time.sleep(self.frame_interval)

        reflectors = self._merge(all_refs)
        logger.info(f"Detected {len(reflectors)} reflector(s) from laser scan")
        return reflectors

    def _detect_one(self, points, pose):
        """Detect reflective strips in one laser scan. Returns list[Reflector].

        points : iterable of (angle_rad, distance_m, quality, valid) in the
                 laser frame (as returned by SlamwareSDP.get_laser_scan).
        pose   : (x, y, yaw) of the laser in the world/map frame.
        """
        rx, ry, ryaw = pose
        cR, sR = math.cos(ryaw), math.sin(ryaw)

        # --- gather high-intensity valid returns, sorted by angle ---------- #
        sel = [(a, d, q) for (a, d, q, v) in points
               if v and q > self.intensity_threshold and d > 0]
        if not sel:
            return []
        sel.sort(key=lambda t: t[0])
        ang = np.array([t[0] for t in sel])
        dist = np.array([t[1] for t in sel])

        # laser-frame -> world-frame
        xl = dist * np.cos(ang)
        yl = dist * np.sin(ang)
        xs = rx + cR * xl - sR * yl
        ys = ry + sR * xl + cR * yl
        pts = np.column_stack((xs, ys))

        # --- cluster by angular + euclidean adjacency ---------------------- #
        max_ang_gap = math.radians(self.max_angle_gap_deg)
        clusters = []
        cur = [0]
        for k in range(1, len(sel)):
            ang_gap = ang[k] - ang[k - 1]
            euc = float(np.hypot(*(pts[k] - pts[k - 1])))
            if ang_gap <= max_ang_gap and euc <= self.cluster_gap:
                cur.append(k)
            else:
                clusters.append(cur)
                cur = [k]
        clusters.append(cur)

        # --- build reflectors ---------------------------------------------- #
        out = []
        for c in clusters:
            if len(c) < self.min_points:
                continue
            cp = pts[c]
            center = cp.mean(axis=0)
            rng = float(np.hypot(center[0] - rx, center[1] - ry))
            width = float(np.hypot(*(cp[0] - cp[-1]))) if len(c) >= 2 else 0.0

            # drop spurious narrow clusters (and single-point noise)
            if self.min_width > 0 and width < self.min_width:
                continue

            # distance-aware width gate: a strip subtends fewer beams when far,
            # so only trust the measured width when we have the resolution.
            if len(c) >= 2:
                beam = abs(ang[c[-1]] - ang[c[0]]) / max(len(c) - 1, 1)
                exp_pts = self.strip_width / (beam * max(rng, 1e-3)) if beam > 0 else 99
            else:
                exp_pts = 0
            if exp_pts >= 3.0:
                if not (self.strip_width - self.width_tolerance <= width
                        <= self.strip_width + self.width_tolerance):
                    continue
            else:
                if width > self.strip_width + self.width_tolerance:
                    continue

            nx, ny = self._normal_toward(cp, center, rx, ry)
            out.append(Reflector(
                x=float(center[0]), y=float(center[1]), range=rng,
                width=width, num_points=len(c), normal=(nx, ny),
                yaw=math.atan2(ny, nx)))
        return out

    def _merge(self, refs):
        """Greedily merge reflectors that are close in world coordinates.

        Averages position/width/range, takes the circular mean of the yaw, and
        sets ``support`` to the number of merged detections."""
        groups = []  # list of list[Reflector]
        for r in refs:
            for g in groups:
                cx = sum(o.x for o in g) / len(g)
                cy = sum(o.y for o in g) / len(g)
                if math.hypot(r.x - cx, r.y - cy) <= self.merge_distance:
                    g.append(r)
                    break
            else:
                groups.append([r])

        out = []
        for g in groups:
            if len(g) < self.min_support:
                continue
            x = sum(o.x for o in g) / len(g)
            y = sum(o.y for o in g) / len(g)
            rng = sum(o.range for o in g) / len(g)
            width = sum(o.width for o in g) / len(g)
            npts = round(sum(o.num_points for o in g) / len(g))
            yaw = math.atan2(sum(math.sin(o.yaw) for o in g),
                             sum(math.cos(o.yaw) for o in g))
            out.append(Reflector(
                x=x, y=y, range=rng, width=width, num_points=npts,
                normal=(math.cos(yaw), math.sin(yaw)), yaw=yaw, support=len(g)))
        out.sort(key=lambda r: -r.support)
        return out

    @staticmethod
    def _normal_toward(cp, center, rx, ry):
        """Unit surface normal of the strip, flipped to face the robot."""
        to_robot = np.array([rx - center[0], ry - center[1]])
        nrm = float(np.hypot(*to_robot))
        to_robot = to_robot / nrm if nrm > 1e-9 else np.array([1.0, 0.0])
        if len(cp) >= 2:
            d = cp - center
            evals, evecs = np.linalg.eigh(d.T @ d)
            tangent = evecs[:, int(np.argmax(evals))]
            normal = np.array([-tangent[1], tangent[0]])
            if float(np.dot(normal, to_robot)) < 0:
                normal = -normal
            return float(normal[0]), float(normal[1])
        # single point: best guess is the line of sight back to the sensor
        return float(to_robot[0]), float(to_robot[1])

    # -- matching -----------------------------------------------------------

    def update(self):
        reflectors = self.detect()

        for landmark_id, guess in self.initial_guess.items():
            guess_x = guess["x"]
            guess_y = guess["y"]

            best = None
            best_distance = self.match_range
            for reflector in reflectors:
                distance = math.hypot(reflector.x - guess_x, reflector.y - guess_y)
                if distance <= best_distance:
                    best_distance = distance
                    best = reflector

            if best is not None:
                self.detected_landmark[landmark_id] = {
                    "x": float(best.x),
                    "y": float(best.y),
                    "yaw": float(best.yaw),
                }
                logger.info(
                    f"Matched landmark {landmark_id}: "
                    f"({best.x:.3f}, {best.y:.3f}, yaw={best.yaw:.3f}) "
                    f"dist={best_distance:.3f}"
                )
            else:
                detected_str = ", ".join(
                    f"({r.x:.3f}, {r.y:.3f}, yaw={r.yaw:.3f})" for r in reflectors
                ) or "none"
                logger.warning(
                    f"No match for landmark {landmark_id} within "
                    f"{self.match_range}m; {len(reflectors)} reflector(s) "
                    f"detected: {detected_str}"
                )
                self.detected_landmark[landmark_id] = None

        return self.detected_landmark

    def get_detected(self):
        return self.detected_landmark
