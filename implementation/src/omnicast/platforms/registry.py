"""Registry for platform adapters."""

from __future__ import annotations

from omnicast.platforms.base import IPlatform


class PlatformRegistry:
    """In-memory adapter registry used by API/jobs before vault-backed config."""

    def __init__(self) -> None:
        self._platforms: dict[str, IPlatform] = {}

    def register(self, platform: IPlatform) -> None:
        self._platforms[platform.id] = platform

    def get(self, platform_id: str) -> IPlatform:
        try:
            return self._platforms[platform_id]
        except KeyError as exc:
            raise KeyError(f"Platform not registered: {platform_id}") from exc

    def list(self) -> list[IPlatform]:
        return list(self._platforms.values())

    def ids(self) -> list[str]:
        return sorted(self._platforms)
