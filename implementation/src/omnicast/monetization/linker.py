"""Metadata monetization helpers.

This layer is deliberately pure and additive: it prepares publish metadata with
a trackable short link, while the existing upload/publish pipeline remains in
control of when content is actually posted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from omnicast.monetization.affiliate import AffiliateService
from omnicast.platforms.models import PlatformId, PublishMetadata
from omnicast.vault.models import PlacementRecord


@dataclass(frozen=True)
class MonetizeResult:
    metadata: PublishMetadata
    placement: PlacementRecord | None = None
    short_url: str = ""
    skipped_reason: str = ""

    @property
    def monetized(self) -> bool:
        return self.placement is not None


class MonetizationLinker:
    """Choose an offer and append compliant CTA/disclosure to publish metadata."""

    def __init__(self, db_path: Path | None = None, public_base_url: str = "http://127.0.0.1:8767") -> None:
        self.service = AffiliateService(db_path)
        self.public_base_url = public_base_url.rstrip("/") + "/"

    def monetize_metadata(
        self,
        metadata: PublishMetadata,
        *,
        niche: str,
        video_id: str,
        channel_id: str,
        platform_id: str | PlatformId,
        cta_text: str | None = None,
        enabled: bool = True,
    ) -> MonetizeResult:
        if not enabled:
            return MonetizeResult(metadata=metadata, skipped_reason="monetization_disabled")

        offer = self.service.choose_offer(niche)
        if offer is None:
            return MonetizeResult(metadata=metadata, skipped_reason="no_active_offer")

        platform = platform_id.value if isinstance(platform_id, PlatformId) else str(platform_id)
        placement = self.service.create_placement(
            offer=offer,
            video_id=video_id,
            channel_id=channel_id,
            platform_id=platform,
            cta_text=cta_text or f"Recommended resource: {offer.name}",
        )
        short_url = urljoin(self.public_base_url, f"r/{placement.placement_id}")
        description = self._append_block(
            metadata.description,
            [placement.cta_text, short_url, placement.disclosure],
        )
        extra = dict(metadata.extra)
        extra["monetization"] = {
            "offer_id": offer.offer_id,
            "placement_id": placement.placement_id,
            "short_url": short_url,
        }
        return MonetizeResult(
            metadata=metadata.model_copy(update={"description": description, "extra": extra}),
            placement=placement,
            short_url=short_url,
        )

    @staticmethod
    def _append_block(description: str, lines: list[str]) -> str:
        base = description.rstrip()
        block = "\n".join(line.strip() for line in lines if line and line.strip())
        return f"{base}\n\n{block}".strip()
