from __future__ import annotations

from pathlib import Path

from util.slam_helper import SLAM

from ..common.guide_task import GuideTask
from .repository import GuideTaskRepository

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "task.json"


class TaskDesigner:
    """Task CRUD and resolution against the currently loaded POIs."""

    def __init__(
        self,
        path: Path = DEFAULT_CONFIG_PATH,
        slam: SLAM | None = None,
        body_actions=None,
    ) -> None:
        self.repository = GuideTaskRepository(path)
        self.slam = slam or SLAM()
        self.body_actions = body_actions

    def list_tasks(self):
        return [task.to_dict() for task in self.repository.list()]

    def get_task(self, task_id):
        return self.repository.get(task_id).to_dict()

    def save_task(self, name, stops, task_id=None):
        self._validate_stop_actions(stops)
        return self.repository.save(name, stops, task_id).to_dict()

    def _validate_stop_actions(self, stops) -> None:
        if not isinstance(stops, list):
            return

        def actions_for(stop):
            if not isinstance(stop, dict):
                return []
            actions = stop.get("actions")
            if actions is None:
                legacy_action = stop.get("action")
                return [] if legacy_action is None else [legacy_action]
            return actions if isinstance(actions, list) else []

        action_ids = {
            str(action.get("action_id") or "").strip()
            for stop in stops
            for action in actions_for(stop)
            if isinstance(action, dict)
        }
        if "" in action_ids:
            raise ValueError("Tianyi arm action IDs cannot be empty")
        if self.body_actions is None:
            return
        available = {
            str(action["action_id"])
            for action in self.body_actions.list_actions()
            if action.get("ready", True) is True
        }
        unavailable = sorted(action_ids - available)
        if unavailable:
            raise ValueError(
                "Unavailable Tianyi arm actions: " + ", ".join(unavailable)
            )

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

    def available_actions(self):
        if self.body_actions is None:
            return []
        return sorted(
            self.body_actions.list_actions(),
            key=lambda item: str(item.get("label") or item.get("action_id")).casefold(),
        )

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
