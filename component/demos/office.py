import sys
from pathlib import Path

from loguru import logger


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output" / "demo_office"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from util.slam_helper import SLAM

if __package__:
    from ..common.docking import DockingService
    from ..common.speech import SpeechService
else:
    from component.common.docking import DockingService
    from component.common.speech import SpeechService


class OfficeDemo:
    POIS = (
        "Welcome Center",
        "Teleoperation",
        "Demo Explain",
        "Demo Table",
    )
    def __init__(self):
        self.slam = SLAM()
        self.speech = SpeechService(audio_dir=OUTPUT_DIR)
        self.docking = DockingService(self.slam)

    def preflight(self, **kwargs):
        map_status = self.slam.map_client.get_map_status()
        if map_status.get("map_load_status") != "LOADED":
            raise RuntimeError(f"Map is not loaded: {map_status}")

        self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if current_action is not None:
            state = current_action.get("state", {})
            if state.get("status") != 4:
                raise RuntimeError(
                    f"Robot has an active action: {current_action.get('action_id')}"
                )

        quality = self.slam.localization.get_localization_quality()
        min_quality = kwargs.get("min_quality", 50)
        if quality < min_quality:
            raise RuntimeError(
                f"Localization quality is too low: {quality} < {min_quality}"
            )

        power = self.slam.power.get_status()
        if power.get("dockingStatus") != "on_dock":
            raise RuntimeError("Robot must start on the charging dock")
        self.slam.power.require_charging(status=power)

        pois = {name: self.slam.poi.require_by_name(name) for name in self.POIS}
        logger.info("Office demo preflight passed")

        return {
            "map": map_status,
            "localization_quality": quality,
            "power": power,
            "pois": pois,
        }

    def speak(self, text, label):
        """Generate and play an announcement without blocking safe recovery."""
        try:
            audio_path = self.speech.speak(text, label)
            logger.info(f"Announcement played: {text}")
            return audio_path
        except Exception as error:
            logger.exception(f"Announcement failed: {error}")
            return None

    def _require_success(self, action, label):
        return self.slam.require_action_success(action, label)

    def return_to_dock(self, **kwargs):
        result = self.docking.return_home(
            home_timeout=kwargs.get("dock_timeout", 300),
            poll_interval=kwargs.get("poll_interval", 1),
            charging_retry_count=kwargs.get("charging_retry_count", 3),
            charging_timeout=kwargs.get("charging_timeout", 60),
        )
        audio = self.speak(
            "I have returned to the docking position.",
            "returned_to_dock",
        )

        return {
            "action": result["action"],
            "power": result["power"],
            "audio": audio,
        }

    def cancel_active_action(self):
        try:
            action = self.slam.motion.get_current_action()
            if action is not None and action.get("state", {}).get("status") != 4:
                self.slam.motion.cancel_current_action()
        except Exception as error:
            logger.warning(f"Could not cancel the active action: {error}")

    def run(self, **kwargs):
        preflight = self.preflight(**kwargs)
        result = {
            "preflight": preflight,
            "undock": None,
            "stops": [],
            "dock": None,
        }
        undock_started = False

        try:
            undock_started = True
            result["undock"] = self.docking.undock(
                distance=kwargs.get("undock_distance", 0.3),
                max_distance=kwargs.get("max_undock_distance", 0.6),
                max_pulses=kwargs.get("max_undock_pulses", 30),
                pulse_ms=kwargs.get("undock_pulse_ms", 100),
            )
            result["departure_audio"] = self.speak(
                "I have departed from the docking position.",
                "departed_from_dock",
            )

            for name in self.POIS:
                pose = preflight["pois"][name]["pose"]
                action = self.slam.motion.move_to_action(
                    pose["x"],
                    pose["y"],
                    pose.get("yaw", 0),
                    wait=True,
                    timeout=kwargs.get("move_timeout", 300),
                    poll_interval=kwargs.get("poll_interval", 1),
                    acceptable_precision=kwargs.get("acceptable_precision", 0.2),
                    fail_retry_count=kwargs.get("fail_retry_count", 2),
                    speed_ratio=kwargs.get("speed_ratio", 0.5),
                )
                self._require_success(action, f"Navigate to {name}")
                audio = self.speak(
                    f"I reach {name} already.",
                    f"reached_{name}",
                )
                result["stops"].append(
                    {
                        "name": name,
                        "action": action,
                        "audio": audio,
                    }
                )

            result["dock"] = self.return_to_dock(**kwargs)
            return result
        except Exception as mission_error:
            self.cancel_active_action()

            needs_recovery = undock_started
            try:
                needs_recovery = (
                    self.slam.power.get_status().get("dockingStatus") != "on_dock"
                )
            except Exception as power_error:
                logger.warning(f"Could not read dock state: {power_error}")

            if not needs_recovery:
                raise

            logger.error(
                f"Office demo failed; returning to dock: {mission_error}"
            )
            try:
                result["dock"] = self.return_to_dock(**kwargs)
            except Exception as recovery_error:
                raise RuntimeError(
                    f"Office demo failed ({mission_error}) and return-to-dock "
                    f"recovery also failed ({recovery_error})"
                ) from recovery_error

            raise RuntimeError(
                f"Office demo failed, but the robot returned to the dock: "
                f"{mission_error}"
            ) from mission_error


def demo_office():
    return OfficeDemo().run()


def main():
    print(demo_office())


if __name__ == "__main__":
    main()
