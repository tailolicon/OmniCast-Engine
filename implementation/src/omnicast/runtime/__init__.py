"""Runtime routing for local, remote, and browser backends."""

from omnicast.runtime.probe import ResourceProbe
from omnicast.runtime.router import ResolvedTarget, RuntimeRouter

__all__ = ["ResolvedTarget", "ResourceProbe", "RuntimeRouter"]
