from __future__ import annotations

from pathlib import Path

from util.slam_helper import SLAM

from .map_building.service import GuideMapBuilder
from .poi_management.service import PoiManager
from .task_design.service import DEFAULT_CONFIG_PATH, TaskDesigner
from .task_execution.executor import GuideTaskExecutor


class GuideApplication:
    """Assemble the four business areas of the Guide application."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        self.slam = SLAM()
        self.map_building = GuideMapBuilder(self.slam)
        self.poi_management = PoiManager(self.slam)
        self.task_design = TaskDesigner(config_path, self.slam)
        self.task_execution = GuideTaskExecutor(
            self.task_design,
            self.slam,
        )

__all__ = ["GuideApplication"]
