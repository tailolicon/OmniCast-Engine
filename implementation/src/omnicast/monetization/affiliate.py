"""Affiliate offer placement and revenue tracking."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from omnicast.vault import db as vault_db
from omnicast.vault.models import ConversionRecord, OfferRecord, PlacementRecord


class AffiliateService:
    """Inject compliant affiliate CTAs and track downstream revenue."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        vault_db.init_db(db_path)

    def upsert_offer(self, offer: OfferRecord) -> None:
        vault_db.upsert_offer(offer, self.db_path)

    def choose_offer(self, niche: str) -> OfferRecord | None:
        niche_key = niche.lower()
        offers = vault_db.list_offers(path=self.db_path)
        for offer in offers:
            if offer.status != "active":
                continue
            if not offer.niches or niche_key in [n.lower() for n in offer.niches]:
                return offer
        return None

    def create_placement(
        self,
        *,
        offer: OfferRecord,
        video_id: str,
        channel_id: str,
        platform_id: str,
        cta_text: str | None = None,
    ) -> PlacementRecord:
        now = datetime.now(timezone.utc).isoformat()
        placement_id = self._placement_id(offer.offer_id, video_id, platform_id)
        destination_url = self._tracking_url(offer.url, placement_id)
        placement = PlacementRecord(
            placement_id=placement_id,
            offer_id=offer.offer_id,
            video_id=video_id,
            channel_id=channel_id,
            platform_id=platform_id,
            destination_url=destination_url,
            cta_text=cta_text or f"Resource mentioned: {offer.name}",
            disclosure=offer.disclosure,
            created_at=now,
        )
        vault_db.insert_placement(placement, self.db_path)
        return placement

    def inject_description(self, description: str, placement: PlacementRecord) -> str:
        blocks = [
            description.rstrip(),
            "",
            placement.cta_text,
            placement.destination_url,
            placement.disclosure,
        ]
        return "\n".join(block for block in blocks if block is not None)

    def record_conversion(
        self,
        *,
        placement_id: str,
        amount: float,
        currency: str = "USD",
        raw: dict | None = None,
    ) -> ConversionRecord:
        now = datetime.now(timezone.utc).isoformat()
        conversion_id = hashlib.sha256(f"{placement_id}:{now}:{amount}".encode()).hexdigest()[:20]
        record = ConversionRecord(
            conversion_id=conversion_id,
            placement_id=placement_id,
            amount=amount,
            currency=currency,
            occurred_at=now,
            raw=raw or {},
        )
        vault_db.insert_conversion(record, self.db_path)
        return record

    @staticmethod
    def _placement_id(offer_id: str, video_id: str, platform_id: str) -> str:
        return hashlib.sha256(f"{offer_id}:{video_id}:{platform_id}".encode()).hexdigest()[:20]

    @staticmethod
    def _tracking_url(url: str, placement_id: str) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}omnicast_pid={placement_id}"
