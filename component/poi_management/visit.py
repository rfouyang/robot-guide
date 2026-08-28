from __future__ import annotations

import math
import time
from typing import Any

from loguru import logger

from util.slam_helper import SLAM

if __package__:
    from ..common.docking import DockingService
else:
    from component.common.docking import DockingService


class GuidePoiVisit:
    """Run the Guide workflow for one named POI and return to the dock."""

    def __init__(self, slam=None) -> None:
        self.slam = slam or SLAM()
        self.docking = DockingService(self.slam)

    def preflight(self, poi_name: str, **kwargs: Any) -> dict:
        map_status = self.slam.map_client.get_map_status()
        if map_status.get("map_load_status") != "LOADED":
            raise RuntimeError(f"Map is not loaded: {map_status}")

        self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if current_action is not None and current_action.get("state", {}).get("status") != 4:
            raise RuntimeError(
                f"Robot has an active action: {current_action.get('action_id')}"
            )

        quality = self.slam.localization.get_localization_quality()
        min_quality = kwargs.get("min_quality", 50)
        if quality < min_quality:
            raise RuntimeError(
                f"Localization quality is too low: {quality} < {min_quality}"
            )

        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        return {
            "poi": self.slam.poi.require_by_name(poi_name),
            "home_dock": self.slam.home_dock.require_bound_home_dock(),
            "localization_quality": quality,
            "power": power,
        }

    def return_home(self, **kwargs: Any):
        logger.info("Returning to the charging dock")
        result = self.docking.return_home(
            home_timeout=kwargs.get("home_timeout", 300),
            poll_interval=kwargs.get("poll_interval", 1),
            charging_retry_count=kwargs.get("charging_retry_count", 3),
            charging_timeout=kwargs.get("charging_timeout", 60),
        )
        return result["action"], result["power"]

    def recover_home(self, mission_error, **kwargs: Any):
        logger.error(
            f"Outbound mission failed; attempting to return home: {mission_error}"
        )
        current_action = self.slam.motion.get_current_action()
        if current_action is not None and current_action.get("state", {}).get("status") != 4:
            self.slam.motion.cancel_current_action()

        try:
            self.return_home(**kwargs)
        except Exception as recovery_error:
            raise RuntimeError(
                f"Mission failed ({mission_error}) and return-home recovery "
                f"also failed ({recovery_error})"
            ) from recovery_error

        raise RuntimeError(
            f"Mission failed, but the robot returned to the charging dock: "
            f"{mission_error}"
        ) from mission_error

    def wait_for_power(self, **kwargs: Any):
        expected_dock = kwargs.get("on_dock")
        expected_charging = kwargs.get("charging")
        timeout = kwargs.get("timeout", 30)
        poll_interval = kwargs.get("poll_interval", 0.5)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            status = self.slam.power.get_status()
            on_dock = status.get("dockingStatus") == "on_dock"
            charging = bool(status.get("isCharging"))
            if (
                (expected_dock is None or on_dock is expected_dock)
                and (expected_charging is None or charging is expected_charging)
            ):
                return status
            time.sleep(poll_interval)

        raise TimeoutError(
            "Power state did not reach the expected dock state; make sure "
            "remote-controller navigation mode is off"
        )

    def release_dock(self, **kwargs: Any):
        return self.docking.undock(
            distance=kwargs.get("manual_undock_distance", 0.3),
            max_distance=kwargs.get("max_manual_undock_distance", 0.6),
            max_pulses=kwargs.get("max_undock_pulses", 30),
            pulse_ms=kwargs.get("undock_pulse_ms", 100),
        )

    def visit_poi_and_return(self, poi_name: str, **kwargs: Any) -> dict:
        preflight = self.preflight(poi_name, **kwargs)
        poi = preflight["poi"]
        target = poi["pose"]

        try:
            logger.info(f"Leaving dock for POI: {poi_name}")
            undock = self.release_dock(**kwargs)
            settle_time = kwargs.get("planner_settle_time", 1)
            if settle_time > 0:
                time.sleep(settle_time)

            logger.info(f"Navigating to POI: {poi_name}")
            outbound = self.slam.motion.move_to_action(
                target["x"],
                target["y"],
                target.get("yaw", 0),
                wait=True,
                timeout=kwargs.get("move_timeout", 300),
                poll_interval=kwargs.get("poll_interval", 1),
                acceptable_precision=kwargs.get("acceptable_precision", 0.2),
                fail_retry_count=kwargs.get("fail_retry_count", 2),
                speed_ratio=kwargs.get("speed_ratio", 0.5),
            )
            self.slam.require_action_success(outbound, f"Navigate to {poi_name}")

            arrival_pose = self.slam.localization.get_robot_pose()
            arrival_error = math.hypot(
                arrival_pose["x"] - target["x"],
                arrival_pose["y"] - target["y"],
            )
            arrival_tolerance = kwargs.get("arrival_tolerance", 0.4)
            if arrival_error > arrival_tolerance:
                raise RuntimeError(
                    f"Robot stopped {arrival_error:.3f} m from {poi_name}; "
                    f"allowed {arrival_tolerance:.3f} m"
                )
        except Exception as mission_error:
            self.recover_home(mission_error, **kwargs)

        dwell_seconds = kwargs.get("dwell_seconds", 2)
        if dwell_seconds > 0:
            time.sleep(dwell_seconds)

        home, final_power = self.return_home(**kwargs)
        return {
            "poi": poi,
            "undock_action": undock,
            "outbound_action": outbound,
            "arrival_pose": arrival_pose,
            "arrival_error": arrival_error,
            "home_action": home,
            "final_power": final_power,
        }


def demo_poi_visit():
    return GuidePoiVisit().visit_poi_and_return("Demo Table")


def main():
    print(demo_poi_visit())


if __name__ == "__main__":
    main()
