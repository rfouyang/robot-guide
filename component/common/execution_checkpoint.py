from dataclasses import dataclass


@dataclass
class GuideExecutionCheckpoint:
    """In-memory position for resuming one interrupted Guide task."""

    task_id: str
    task_name: str
    next_stop_index: int
    stop_count: int

    @property
    def last_success_index(self):
        return self.next_stop_index - 1

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "next_stop_index": self.next_stop_index,
            "last_success_index": self.last_success_index,
            "stop_count": self.stop_count,
        }
