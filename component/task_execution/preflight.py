from __future__ import annotations

from util.slam_helper import SLAM


class GuideExecutionPreflight:
    """Validate that the Guide execution environment is ready."""

    def __init__(self, task_designer, slam: SLAM) -> None:
        self.task_designer = task_designer
        self.slam = slam

    def _check_environment(self, **kwargs):
        map_status = self.slam.map_client.get_map_status()
        if map_status.get("map_load_status") != "LOADED":
            raise RuntimeError(f"Map is not loaded: {map_status}")
        if self.slam.mapping.is_enabled():
            raise RuntimeError("A task cannot run while map building is active")

        self.slam.system_status.require_healthy()
        current_action = self.slam.motion.get_current_action()
        if (
            current_action is not None
            and current_action.get("state", {}).get("status") != 4
        ):
            raise RuntimeError(
                f"Robot has an active action: {current_action.get('action_id')}"
            )

        quality = self.slam.localization.get_localization_quality()
        min_quality = kwargs.get("min_quality", 50)
        return map_status, quality, min_quality

    def check(self, task, **kwargs):
        map_status, quality, min_quality = self._check_environment(**kwargs)
        if quality < min_quality:
            raise RuntimeError(
                f"Localization quality is too low: {quality} < {min_quality}"
            )

        power = self.slam.home_dock.require_on_dock()
        self.slam.power.require_charging(status=power)
        home_dock = self.slam.home_dock.require_bound_home_dock()
        return {
            "task": self.task_designer.resolve_task(task),
            "map": map_status,
            "localization_quality": quality,
            "power": power,
            "home_dock": home_dock,
        }

    def check_resume(self, task, **kwargs):
        """Validate a resume without requiring the robot to be on the dock."""
        map_status, quality, _ = self._check_environment(**kwargs)
        return {
            "task": self.task_designer.resolve_task(task),
            "map": map_status,
            "localization_quality": quality,
        }
