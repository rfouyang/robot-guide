import math
from dataclasses import dataclass


@dataclass
class Reflector:
    """A single detected retro-reflective strip, in the world/map frame."""

    x: float            # world x of strip centre (m)
    y: float            # world y of strip centre (m)
    range: float        # distance from sensor to centre (m)
    width: float        # measured chord width (m); 0 if single-point
    num_points: int     # number of laser returns in the cluster
    normal: tuple       # (nx, ny) unit surface normal, pointing at the robot
    yaw: float          # atan2(ny, nx) in the world frame (rad)
    support: int = 1    # how many frames this (merged) reflector was seen in

    @property
    def yaw_deg(self):
        return math.degrees(self.yaw)
