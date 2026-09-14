from .docking import DockingService
from .execution_checkpoint import GuideExecutionCheckpoint
from .errors import GuideTaskCancelled
from .execution_options import GuideExecutionOptions
from .guide_task import GuideBodyAction, GuideStop, GuideTask
from .navigation import NavigationService
from .speech import SpeechService

__all__ = [
    "BodyActionClient",
    "DockingService",
    "GuideExecutionCheckpoint",
    "GuideExecutionOptions",
    "GuideBodyAction",
    "GuideStop",
    "GuideTask",
    "GuideTaskCancelled",
    "NavigationService",
    "SpeechService",
]


def __getattr__(name: str):
    """Keep the public body-action import without eagerly importing ROS code."""
    if name == "BodyActionClient":
        from .body_action import BodyActionClient

        return BodyActionClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
