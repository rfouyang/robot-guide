from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from util.slam_helper import SLAM


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"


class GuideMapBuilder:
    """Own the Guide workflow for building and saving a map."""

    def __init__(self, slam: SLAM, output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
        self.output_dir = Path(output_dir)
        self.slam = slam

    def get_output_path(self, filename: str) -> Path:
        name = Path(filename).name
        if Path(name).suffix.lower() != ".stcm":
            raise ValueError("Map filename must use the .stcm extension")
        return self.output_dir / name

    def get_map_view(self, session: dict | None = None, pois=None) -> dict:
        status = self.get_status(session)
        map_info = self.slam.map_client.explore_map(status["pose"])
        map_info["start_pose"] = (session or {}).get("start_pose")
        map_info["home_dock"] = status.get("home_dock") or (session or {}).get("home_dock")
        map_info["pois"] = pois or []
        return {
            "image": self.slam.renderer.render_explore_map(map_info),
            "status": status,
        }

    def save_map(self, filename: str, **kwargs: Any) -> Path:
        return self.slam.map_client.save_map(
            filename=filename,
            overwrite=kwargs.get("overwrite", False),
        )

    def upload_map(self, map_path: Path, **kwargs: Any):
        response = self.slam.map_client.upload_map(map_path)
        self.slam.map_client.reload_map(**kwargs)
        return response

    def preflight(self, filename: str = "office2.stcm", **kwargs: Any) -> dict:
        output_path = self.get_output_path(filename)
        if output_path.exists() and not kwargs.get("overwrite", False):
            raise FileExistsError(f"Map already exists: {output_path}")
        if self.slam.mapping.is_enabled():
            raise RuntimeError("Mapping is already active")

        health = self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if current_action is not None:
            raise RuntimeError(
                f"Robot has an active action: {current_action.get('action_id')}"
            )

        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        return {
            "health": health,
            "power": power,
            "output_path": str(output_path),
        }

    def start(self, filename: str = "office2.stcm", **kwargs: Any) -> dict:
        dock_name = kwargs.get("dock_name", "office2_charger").strip()
        if not dock_name:
            raise ValueError("Charging dock name cannot be empty")

        preflight = self.preflight(filename, **kwargs)
        mapping_started = False
        self.slam.mapping.clear_map()
        try:
            self.slam.mapping.start()
            mapping_started = True
            self.slam.mapping.wait_enabled(True)
            if kwargs.get("enable_loop_closure", True):
                self.slam.mapping.set_loop_closure(True)

            settle_time = kwargs.get("settle_time", 1.0)
            if settle_time > 0:
                time.sleep(settle_time)

            start_pose = self.slam.localization.get_robot_pose()
            home_dock = self.slam.home_dock.register_home_dock(
                dock_name,
                require_charging=False,
            )
            home_pose = home_dock.get("pose")
            if home_pose:
                self.slam.home_dock.set_home_pose(home_pose)

            session = {
                "active": True,
                "filename": Path(filename).name,
                "output_path": preflight["output_path"],
                "start_pose": start_pose,
                "home_dock": home_dock,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(
                f"Started map build: filename={session['filename']}, "
                f"dock_id={home_dock.get('id')}"
            )
            return session
        except Exception:
            if mapping_started:
                try:
                    self.slam.mapping.stop()
                except Exception:
                    logger.exception("Failed to stop mapping after start error")
            raise

    def finish(self, session: dict, **kwargs: Any) -> dict:
        if not session or not session.get("active"):
            raise RuntimeError("No active map-building session")

        self.slam.mapping.stop()
        self.slam.mapping.wait_enabled(False)
        final_pose = self.slam.localization.get_robot_pose()

        dock_id = session.get("home_dock", {}).get("id")
        home_dock = self.slam.home_dock.find_home_dock(dock_id) if dock_id else None
        if home_dock is None:
            raise RuntimeError("Registered home dock is missing from the completed map")

        output_path = self.slam.map_client.save_map(
            filename=session["filename"],
            overwrite=kwargs.get("overwrite", False),
        )
        result = {
            **session,
            "active": False,
            "home_dock": home_dock,
            "final_pose": final_pose,
            "output_path": str(output_path),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"Finished map build: {output_path}")
        return result

    def get_status(self, session: dict | None = None, **kwargs: Any) -> dict:
        dock_id = (session or {}).get("home_dock", {}).get("id")
        return {
            "mapping": self.slam.mapping.is_enabled(),
            "pose": self.slam.localization.get_robot_pose(),
            "power": self.slam.power.get_status(),
            "home_dock": (
                self.slam.home_dock.find_home_dock(dock_id) if dock_id else None
            ),
        }


def demo_map_build_preflight():
    """Run only non-destructive map-building preflight checks."""
    return GuideMapBuilder(SLAM()).preflight(overwrite=True)


def main():
    print(demo_map_build_preflight())


if __name__ == "__main__":
    main()
