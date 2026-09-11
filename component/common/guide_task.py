from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _uuid(value, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a valid UUID") from exc


@dataclass(frozen=True)
class GuideBodyAction:
    action_id: str
    phase: str = "before_speech"
    required: bool = True

    @classmethod
    def from_dict(cls, value: dict) -> "GuideBodyAction":
        if not isinstance(value, dict):
            raise ValueError("Guide body action must be an object")
        action_id = str(value.get("action_id") or "").strip()
        if not action_id:
            raise ValueError("Guide body action ID is required")
        phase = str(value.get("phase") or "before_speech").strip()
        if phase != "before_speech":
            raise ValueError(f"Unsupported guide body action phase: {phase}")
        required = value.get("required", True)
        if not isinstance(required, bool):
            raise ValueError("Guide body action required flag must be a boolean")
        return cls(action_id=action_id, phase=phase, required=required)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "phase": self.phase,
            "required": self.required,
        }


@dataclass(frozen=True)
class GuideStop:
    poi_id: str
    poi_name: str
    content: str
    action: GuideBodyAction | None = None

    @classmethod
    def from_dict(cls, value: dict) -> "GuideStop":
        if not isinstance(value, dict):
            raise ValueError("Each task stop must be an object")
        poi_id = _uuid(value.get("poi_id"), "POI ID")
        poi_name = str(value.get("poi_name") or "").strip()
        content = str(value.get("content") or "").strip()
        if not poi_name:
            raise ValueError("Each task stop must have a POI name")
        if not content:
            raise ValueError(f"Arrival content is required for POI '{poi_name}'")
        raw_action = value.get("action")
        action = None if raw_action is None else GuideBodyAction.from_dict(raw_action)
        return cls(poi_id, poi_name, content, action)

    def to_dict(self) -> dict:
        value = {
            "poi_id": self.poi_id,
            "poi_name": self.poi_name,
            "content": self.content,
        }
        if self.action is not None:
            value["action"] = self.action.to_dict()
        return value


@dataclass(frozen=True)
class GuideTask:
    id: str
    name: str
    stops: list[GuideStop]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict, *, require_stops: bool = False) -> "GuideTask":
        if not isinstance(value, dict):
            raise ValueError("Each task must be an object")
        task_id = _uuid(value.get("id"), "Task ID")
        name = str(value.get("name") or "").strip()
        if not name:
            raise ValueError("Task name cannot be empty")
        raw_stops = value.get("stops")
        if not isinstance(raw_stops, list):
            raise ValueError(f"Task '{name}' stops must be a list")
        stops = [GuideStop.from_dict(stop) for stop in raw_stops]
        if require_stops and not stops:
            raise ValueError(f"Task '{name}' must contain at least one POI")
        return cls(
            id=task_id,
            name=name,
            stops=stops,
            created_at=str(value.get("created_at") or datetime.now(timezone.utc).isoformat()),
            updated_at=str(value.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "stops": [stop.to_dict() for stop in self.stops],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
