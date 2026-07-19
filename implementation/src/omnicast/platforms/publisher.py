"""Destination planning and multi-platform publish orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from omnicast.config.channel import ChannelProfile
from omnicast.platforms.models import (
    Destination,
    PlatformId,
    PlatformStatus,
    PublishRequest,
    PublishResult,
)
from omnicast.platforms.registry import PlatformRegistry


def destinations_for_channel(channel: ChannelProfile) -> list[Destination]:
    """Return configured destinations or a backward-compatible YouTube target."""
    if channel.destinations:
        return channel.destinations
    return [
        Destination(
            destination_id=f"{channel.channel_id}_youtube",
            platform_id=PlatformId.YOUTUBE,
            account_id=channel.youtube_channel_id or channel.channel_id,
            format_variant="youtube_16x9",
            enabled=True,
            approval_required=False,
            market=channel.market.value if hasattr(channel.market, "value") else str(channel.market),
        )
    ]


@dataclass(frozen=True)
class DestinationPublishOutcome:
    destination: Destination
    result: PublishResult
    skipped_reason: str = ""


class MultiPlatformPublisher:
    """Fan out one rendered asset to every enabled destination."""

    def __init__(self, registry: PlatformRegistry) -> None:
        self.registry = registry

    async def publish(
        self,
        channel: ChannelProfile,
        request: PublishRequest,
        *,
        require_approval: bool = True,
    ) -> list[DestinationPublishOutcome]:
        outcomes: list[DestinationPublishOutcome] = []
        for destination in destinations_for_channel(channel):
            if not destination.enabled:
                outcomes.append(self._skipped(destination, request, "destination disabled"))
                continue

            destination_request = request.model_copy(update={
                "account_id": destination.account_id,
                "format_variant": destination.format_variant,
            })

            if require_approval and destination.approval_required:
                outcomes.append(DestinationPublishOutcome(
                    destination=destination,
                    result=PublishResult(
                        platform_id=destination.platform_id,
                        account_id=destination.account_id,
                        status=PlatformStatus.WAITING_APPROVAL,
                        raw={"destination_id": destination.destination_id},
                    ),
                ))
                continue

            platform = self.registry.get(destination.platform_id.value)
            result = await platform.publish(destination_request)
            outcomes.append(DestinationPublishOutcome(destination=destination, result=result))
        return outcomes

    @staticmethod
    def _skipped(
        destination: Destination,
        request: PublishRequest,
        reason: str,
    ) -> DestinationPublishOutcome:
        return DestinationPublishOutcome(
            destination=destination,
            skipped_reason=reason,
            result=PublishResult(
                platform_id=destination.platform_id,
                account_id=destination.account_id,
                status=PlatformStatus.SKIPPED,
                error=reason,
                raw={"video_id": request.video_id, "destination_id": destination.destination_id},
            ),
        )
