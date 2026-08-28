from __future__ import annotations

import threading
from pathlib import Path

from loguru import logger

from util.slam_helper import SLAM

if __package__:
    from ..common.docking import DockingService
    from ..common.errors import GuideTaskCancelled
    from ..common.execution_checkpoint import GuideExecutionCheckpoint
    from ..common.execution_options import GuideExecutionOptions
    from ..common.navigation import NavigationService
    from ..common.speech import SpeechService
    from ..task_design.service import TaskDesigner
    from .preflight import GuideExecutionPreflight
else:
    from component.common.docking import DockingService
    from component.common.errors import GuideTaskCancelled
    from component.common.execution_checkpoint import GuideExecutionCheckpoint
    from component.common.execution_options import GuideExecutionOptions
    from component.common.navigation import NavigationService
    from component.common.speech import SpeechService
    from component.task_design.service import TaskDesigner
    from component.task_execution.preflight import GuideExecutionPreflight


BASE_DIR = Path(__file__).resolve().parents[2]
TASK_AUDIO_DIR = BASE_DIR / "output" / "tasks"


class GuideTaskExecutor:
    """Execute one saved Guide task with cancellation and recovery."""

    def __init__(
        self,
        task_designer: TaskDesigner,
        slam: SLAM | None = None,
        options: GuideExecutionOptions | None = None,
        audio_dir: Path = TASK_AUDIO_DIR,
    ) -> None:
        self.task_designer = task_designer
        self.slam = slam or SLAM()
        self.audio_dir = Path(audio_dir)
        self.options = options or GuideExecutionOptions()
        self.preflight_service = GuideExecutionPreflight(
            self.task_designer,
            self.slam,
        )
        self.navigation = NavigationService(self.slam)
        self.speech = SpeechService(audio_dir=self.audio_dir)
        self.docking = DockingService(self.slam)
        self._run_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._stop_requested = threading.Event()
        self._running_event = threading.Event()
        self._active_mode = None
        self._checkpoint = None

    def preflight(self, task, **kwargs):
        return self.preflight_service.check(task, **kwargs)

    def _check_cancelled(self):
        if self._cancel_event.is_set():
            raise GuideTaskCancelled("Task was cancelled by the user")

    def _cancel_active_action(self):
        try:
            action = self.slam.motion.get_current_action()
            if action is not None and action.get("state", {}).get("status") != 4:
                self.slam.motion.cancel_current_action()
                return True
        except Exception as exc:
            logger.warning(f"Could not cancel the active robot action: {exc}")
        return False

    @staticmethod
    def _event(status, message, task, **kwargs):
        return {
            "status": status,
            "message": message,
            "task_id": task["id"],
            "task_name": task["name"],
            "stop_index": kwargs.get("stop_index"),
            "stop_count": len(task["stops"]),
            "poi_name": kwargs.get("poi_name"),
            "error": kwargs.get("error"),
        }

    def _return_home(self, **kwargs):
        return self._perform_return_home(**kwargs)

    def _announce(self, text, label):
        try:
            self.speech.speak(text, label)
        except Exception as exc:
            logger.warning(f"Guide announcement failed ({label}): {exc}")

    def _perform_undock(self, **kwargs):
        options = self.options.with_overrides(**kwargs)
        self._announce(
            "I am leaving the charging dock.",
            "guide_undock_start",
        )
        result = self.docking.undock(
            distance=options.undock_distance,
            max_distance=options.max_undock_distance,
            max_pulses=options.max_undock_pulses,
            pulse_ms=options.undock_pulse_ms,
        )
        self._announce(
            "I have left the charging dock.",
            "guide_undock_complete",
        )
        return result

    def _perform_return_home(self, **kwargs):
        options = self.options.with_overrides(**kwargs)
        self._announce(
            "I am returning to the charging dock.",
            "guide_return_home_start",
        )
        result = self.docking.return_home(
            home_timeout=options.home_timeout,
            poll_interval=options.poll_interval,
            charging_retry_count=options.charging_retry_count,
            charging_timeout=options.charging_timeout,
        )
        self._announce(
            "I have returned to the charging dock and am charging.",
            "guide_return_home_complete",
        )
        return result

    def _run_manual_action(self, action, **kwargs):
        mode = kwargs.pop("_mode", "manual")
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Another Guide robot action is already running")
        try:
            self._cancel_event.clear()
            self._stop_requested.clear()
            self._active_mode = mode
            self._running_event.set()
            return action(**kwargs)
        finally:
            self._active_mode = None
            self._running_event.clear()
            self._run_lock.release()

    def undock(self, **kwargs):
        """Undock the robot and announce the operation aloud."""
        return self._run_manual_action(self._perform_undock, **kwargs)

    def return_home(self, **kwargs):
        """Return the robot to its charging dock and announce the operation."""
        return self._run_manual_action(self._perform_return_home, **kwargs)

    def _set_checkpoint(self, task, next_stop_index):
        self._checkpoint = GuideExecutionCheckpoint(
            task_id=task["id"],
            task_name=task["name"],
            next_stop_index=next_stop_index,
            stop_count=len(task["stops"]),
        )

    def get_resume_checkpoint(self, task_id=None):
        if self._checkpoint is None:
            return None
        if self._checkpoint.next_stop_index >= self._checkpoint.stop_count:
            return None
        if task_id is not None and self._checkpoint.task_id != str(task_id):
            return None
        return self._checkpoint.to_dict()

    def _prepare_resume_position(self, preflight, **kwargs):
        quality = preflight["localization_quality"]
        min_quality = kwargs.get("min_quality", self.options.min_quality)
        if quality < min_quality:
            message = (
                "Localization quality is too low. Please manually return me "
                "to the charging dock, then press Resume."
            )
            self._announce(message, "guide_resume_localization_low")
            raise RuntimeError(
                f"{message} Quality: {quality} < {min_quality}."
            )

        power = self.slam.power.get_status()
        if power.get("dockingStatus") == "on_dock":
            self._check_cancelled()
            self._perform_undock(**kwargs)
        return True

    def _find_poi(self, poi_id):
        expected_id = str(poi_id or "").strip()
        if not expected_id:
            raise ValueError("POI ID is required")
        for poi in self.slam.poi.get_all():
            if str(poi.get("id") or "").strip() == expected_id:
                return poi
        raise LookupError(f"POI is not present in the current map: {expected_id}")

    def _perform_debug_poi(self, poi, content, **kwargs):
        poi_name = str(poi.get("metadata", {}).get("display_name") or "POI")
        self.navigation.navigate(
            {"poi": poi, "poi_name": poi_name},
            move_timeout=kwargs.get("move_timeout", self.options.move_timeout),
            poll_interval=kwargs.get("poll_interval", self.options.poll_interval),
            acceptable_precision=kwargs.get(
                "acceptable_precision", self.options.acceptable_precision
            ),
            fail_retry_count=kwargs.get(
                "fail_retry_count", self.options.fail_retry_count
            ),
            speed_ratio=kwargs.get("speed_ratio", self.options.speed_ratio),
        )
        self._check_cancelled()
        audio_path = self.speech.speak(
            content,
            f"guide_debug_{poi.get('id', poi_name)}",
        )
        return {
            "status": "completed",
            "poi_id": poi.get("id"),
            "poi_name": poi_name,
            "speech": content,
            "audio": str(audio_path),
        }

    def debug_poi(self, poi_id, **kwargs):
        """Navigate to one POI, speak its debug content, and stay there."""
        poi = self._find_poi(poi_id)
        poi_name = str(poi.get("metadata", {}).get("display_name") or "POI")
        options = dict(kwargs)
        content = str(
            options.pop("content", None) or f"You have arrived at {poi_name}."
        ).strip()
        if not content:
            content = f"You have arrived at {poi_name}."

        try:
            return self._run_manual_action(
                self._perform_debug_poi,
                _mode="debug",
                poi=poi,
                content=content,
                **options,
            )
        except Exception as exc:
            if self._stop_requested.is_set():
                return {
                    "status": "stopped",
                    "poi_id": poi_id,
                    "poi_name": poi_name,
                    "message": "Debug navigation stopped; robot remains here.",
                }
            raise

    def stop(self):
        """Stop active robot movement without starting return-home recovery."""
        was_running = self.is_running
        self._stop_requested.set()
        self._cancel_event.set()
        action_stopped = self._cancel_active_action()
        if was_running or action_stopped:
            logger.warning("Guide robot stop requested")
            return True
        self._stop_requested.clear()
        self._cancel_event.clear()
        return False

    @property
    def is_running(self):
        return self._running_event.is_set()

    def cancel(self):
        if not self.is_running or self._active_mode != "task":
            return False
        self._cancel_event.set()
        self._cancel_active_action()
        logger.warning("Task cancellation requested")
        return True

    def run_events(self, task_id, **kwargs):
        yield from self._run_events(task_id, resume=False, **kwargs)

    def resume_events(self, task_id, **kwargs):
        yield from self._run_events(task_id, resume=True, **kwargs)

    def _run_events(self, task_id, resume, **kwargs):
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Another task is already running")

        self._running_event.set()
        self._cancel_event.clear()
        self._stop_requested.clear()
        self._active_mode = "task"
        options = self.options.with_overrides(**kwargs)
        departed = False
        task = None
        start_stop_index = 0
        try:
            task = self.task_designer.get_task(task_id)
            checkpoint = self.get_resume_checkpoint(task_id) if resume else None
            if resume and checkpoint is None:
                raise RuntimeError(
                    "No resumable execution exists for the selected task"
                )
            start_stop_index = (
                checkpoint["next_stop_index"] if checkpoint else 0
            )
            yield self._event(
                "starting",
                (
                    f"Checking resume state for task '{task['name']}'"
                    if resume
                    else f"Checking task '{task['name']}' and robot state"
                ),
                task,
            )
            self._check_cancelled()
            preflight = (
                self.preflight_service.check_resume(task, **kwargs)
                if resume
                else self.preflight(task, **kwargs)
            )
            task = preflight["task"]
            if start_stop_index >= len(task["stops"]):
                raise RuntimeError("The selected task has no remaining POIs")
            if not resume:
                self._set_checkpoint(task, 0)
            self._check_cancelled()

            if resume:
                next_stop = task["stops"][start_stop_index]
                yield self._event(
                    "resuming",
                    f"Resuming with {next_stop['poi_name']}",
                    task,
                    stop_index=start_stop_index + 1,
                    poi_name=next_stop["poi_name"],
                )

            if resume:
                yield self._event(
                    "localization_check",
                    "Checking localization before resuming",
                    task,
                )
                departed = self._prepare_resume_position(preflight, **kwargs)
            self._check_cancelled()

            prepared_audio = []
            for stop_index, stop in enumerate(
                task["stops"][start_stop_index:],
                start=start_stop_index + 1,
            ):
                yield self._event(
                    "preparing",
                    f"Preparing speech for {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )
                self._check_cancelled()
                prepared_audio.append(self.speech.prepare(task, stop, stop_index))
                self._check_cancelled()

            if not resume:
                yield self._event("departing", "Leaving the charging dock", task)
                self._check_cancelled()
                departed = True
                self._perform_undock(**kwargs)
            self._check_cancelled()

            for stop_index, (stop, audio_path) in enumerate(
                zip(task["stops"][start_stop_index:], prepared_audio),
                start=start_stop_index + 1,
            ):
                yield self._event(
                    "navigating",
                    f"Navigating to {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )
                self._check_cancelled()
                self.navigation.navigate(
                    stop,
                    move_timeout=options.move_timeout,
                    poll_interval=options.poll_interval,
                    acceptable_precision=options.acceptable_precision,
                    fail_retry_count=options.fail_retry_count,
                    speed_ratio=options.speed_ratio,
                )
                self._check_cancelled()

                yield self._event(
                    "speaking",
                    f"Speaking at {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )
                self._check_cancelled()
                self.speech.play(audio_path)
                self._check_cancelled()
                self._checkpoint.next_stop_index = stop_index
                yield self._event(
                    "stop_completed",
                    f"Completed {stop['poi_name']}",
                    task,
                    stop_index=stop_index,
                    poi_name=stop["poi_name"],
                )

            yield self._event("returning", "Returning to the charging dock", task)
            self._return_home(**kwargs)
            departed = False
            self._check_cancelled()
            self._checkpoint = None
            yield self._event("completed", f"Task '{task['name']}' completed", task)
        except Exception as exc:
            if self._cancel_event.is_set() and not isinstance(exc, GuideTaskCancelled):
                exc = GuideTaskCancelled("Task was cancelled by the user")
            stopped = self._stop_requested.is_set()
            self._cancel_active_action()
            recovery_error = None
            if departed and task is not None and not stopped:
                yield self._event(
                    "recovering",
                    "Returning to the charging dock after interruption",
                    task,
                    error=str(exc),
                )
                try:
                    self._return_home(**kwargs)
                except Exception as error:
                    recovery_error = error
            if task is None:
                raise

            if isinstance(exc, GuideTaskCancelled):
                message = "Task stopped" if stopped else "Task cancelled"
                if recovery_error:
                    message += f"; return-to-dock failed: {recovery_error}"
                elif departed and not stopped:
                    message += "; robot returned to the dock"
                elif stopped:
                    message += "; robot remains at its current location"
                yield self._event(
                    "cancelled", message, task, error=str(recovery_error or exc)
                )
            else:
                message = f"Task failed: {exc}"
                if recovery_error:
                    message += f"; return-to-dock also failed: {recovery_error}"
                elif departed:
                    message += "; robot returned to the dock"
                yield self._event(
                    "failed", message, task, error=str(recovery_error or exc)
                )
        finally:
            self._active_mode = None
            self._cancel_event.clear()
            self._stop_requested.clear()
            self._running_event.clear()
            self._run_lock.release()


def demo_task_status():
    return TaskDesigner().list_tasks()


def main():
    print(demo_task_status())


if __name__ == "__main__":
    main()
