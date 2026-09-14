"""Robot Guide business capabilities."""

from typing import Any

__all__ = ["GuideApplication"]


def __getattr__(name: str) -> Any:
    """Load the application lazily so utility modules have no UI side effects."""
    if name == "GuideApplication":
        from .guide_application import GuideApplication

        return GuideApplication
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
