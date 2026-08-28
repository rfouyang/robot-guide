from __future__ import annotations

from pathlib import Path

from util.slam_helper import SLAM

from ..common.guide_task import GuideTask
from .repository import GuideTaskRepository

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "task.json"


class TaskDesigner:
    """Task CRUD and resolution against the currently loaded POIs."""

    def __init__(self, path: Path = DEFAULT_CONFIG_PATH, slam: SLAM | None = None) -> None:
        self.repository = GuideTaskRepository(path)
        self.slam = slam or SLAM()

    def list_tasks(self):
        return [task.to_dict() for task in self.repository.list()]

    def get_task(self, task_id):
        return self.repository.get(task_id).to_dict()

    def save_task(self, name, stops, task_id=None):
        return self.repository.save(name, stops, task_id).to_dict()

    def delete_task(self, task_id):
        self.repository.delete(task_id)

    def available_pois(self):
        pois = []
        for poi in self.slam.poi.get_all():
            poi_id = str(poi.get("id") or "").strip()
            name = str(poi.get("metadata", {}).get("display_name") or "").strip()
            if poi_id and name:
                pois.append(
                    {
                        "id": poi_id,
                        "name": name,
                        "type": poi.get("metadata", {}).get("type", ""),
                    }
                )
        return sorted(pois, key=lambda item: item["name"].casefold())

    def resolve_task(self, task):
        task = GuideTask.from_dict(task, require_stops=True).to_dict()
        current_pois = {str(poi.get("id")): poi for poi in self.slam.poi.get_all()}
        resolved_stops = []
        for stop in task["stops"]:
            poi = current_pois.get(stop["poi_id"])
            if poi is None:
                raise LookupError(
                    f"POI '{stop['poi_name']}' is not present in the current map"
                )
            current_name = str(
                poi.get("metadata", {}).get("display_name") or ""
            ).strip()
            if not current_name:
                raise ValueError(f"POI has no display name: {stop['poi_id']}")
            resolved_stops.append({**stop, "poi_name": current_name, "poi": poi})
        return {**task, "stops": resolved_stops}
