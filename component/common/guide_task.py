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
class GuideStop:
    poi_id: str
    poi_name: str
    content: str

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
        return cls(poi_id, poi_name, content)

    def to_dict(self) -> dict:
        return {
            "poi_id": self.poi_id,
            "poi_name": self.poi_name,
            "content": self.content,
        }


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

