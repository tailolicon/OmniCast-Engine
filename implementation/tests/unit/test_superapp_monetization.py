from datetime import datetime, timezone

from cryptography.fernet import Fernet

from omnicast.monetization.affiliate import AffiliateService
from omnicast.monetization.linker import MonetizationLinker
from omnicast.platforms.analytics_store import PlatformAnalyticsStore
from omnicast.platforms.models import PlatformId, PostStats, PublishMetadata
from omnicast.services.credential_vault import CredentialVault
from omnicast.vault import db as vault_db
from omnicast.vault.models import OfferRecord


def test_credential_vault_hides_plain_secret_in_safe_list(tmp_path):
    db_path = tmp_path / "vault.db"
    vault = CredentialVault(db_path=db_path)

    record = vault.store_secret(
        provider="youtube",
        account_id="UC123",
        secret="refresh-token",
        scopes=["upload"],
    )

    assert vault.get_secret(record.credential_id) == "refresh-token"
    safe = vault.list_safe("youtube")
    assert safe == [
        {
            "credential_id": record.credential_id,
            "provider": "youtube",
            "account_id": "UC123",
            "label": "youtube:UC123",
            "scopes": ["upload"],
            "status": "active",
            "priority": 100,
            "cooldown_until": None,
            "last_used_at": None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "encrypted": False,
        }
    ]
    assert "refresh-token" not in str(safe)


def test_credential_vault_uses_fernet_when_key_configured(tmp_path):
    db_path = tmp_path / "vault.db"
    key = Fernet.generate_key().decode("ascii")
    vault = CredentialVault(db_path=db_path, encryption_key=key)

    record = vault.store_secret(
        provider="tiktok",
        account_id="creator-1",
        secret="oauth-token",
    )

    stored = vault_db.get_credential(record.credential_id, db_path)
    assert stored is not None
    assert stored.secret_ref.startswith("fernet:")
    assert vault.get_secret(record.credential_id) == "oauth-token"
    assert vault.list_safe("tiktok")[0]["encrypted"] is True


def test_platform_analytics_store_round_trips_post_stats(tmp_path):
    db_path = tmp_path / "vault.db"
    store = PlatformAnalyticsStore(db_path)
    fetched_at = datetime(2026, 7, 1, 8, 30, tzinfo=timezone.utc)

    store.record(PostStats(
        platform_id=PlatformId.TIKTOK,
        account_id="creator-1",
        post_id="post-1",
        channel_id="ch-health",
        fetched_at=fetched_at,
        views=1200,
        likes=88,
        comments=7,
        shares=5,
        watch_time_seconds=456.5,
        revenue=12.25,
        raw={"source": "manual"},
    ))

    latest = store.latest("tiktok", "post-1")
    assert latest is not None
    assert latest.fetched_at == fetched_at
    assert latest.views == 1200
    assert latest.raw == {"source": "manual"}
    assert store.list_channel("ch-health")[0].post_id == "post-1"


def test_affiliate_service_places_disclosed_tracking_link_and_records_revenue(tmp_path):
    db_path = tmp_path / "vault.db"
    svc = AffiliateService(db_path)
    now = datetime.now(timezone.utc).isoformat()
    offer = OfferRecord(
        offer_id="glp1-guide",
        name="GLP-1 Meal Guide",
        network="direct",
        url="https://example.com/guide",
        niches=["health"],
        commission_type="cpa",
        commission_value=12.0,
        disclosure="Affiliate disclosure: we may earn a commission.",
        created_at=now,
        updated_at=now,
    )

    svc.upsert_offer(offer)
    chosen = svc.choose_offer("Health")
    assert chosen is not None
    assert chosen.offer_id == "glp1-guide"

    placement = svc.create_placement(
        offer=chosen,
        video_id="video-1",
        channel_id="ch-health",
        platform_id="youtube",
        cta_text="Download the meal guide:",
    )
    description = svc.inject_description("Base description", placement)

    assert "omnicast_pid=" in placement.destination_url
    assert "Affiliate disclosure" in description
    assert vault_db.list_placements("video-1", db_path)[0].placement_id == placement.placement_id

    svc.record_conversion(placement_id=placement.placement_id, amount=12.0, raw={"order": "1"})

    assert vault_db.sum_revenue("ch-health", db_path) == 12.0


def test_monetization_linker_adds_short_link_disclosure_and_extra(tmp_path):
    db_path = tmp_path / "vault.db"
    svc = AffiliateService(db_path)
    now = datetime.now(timezone.utc).isoformat()
    offer = OfferRecord(
        offer_id="retirement-course",
        name="Retirement Course",
        network="direct",
        url="https://example.com/retire",
        niches=["finance"],
        disclosure="Affiliate link: we may earn a commission.",
        created_at=now,
        updated_at=now,
    )
    svc.upsert_offer(offer)

    linker = MonetizationLinker(db_path, public_base_url="https://go.example.com")
    result = linker.monetize_metadata(
        PublishMetadata(title="Plan your retirement", description="Base description"),
        niche="finance",
        video_id="video-99",
        channel_id="ch-finance",
        platform_id=PlatformId.YOUTUBE,
    )

    assert result.monetized is True
    assert result.short_url.startswith("https://go.example.com/r/")
    assert result.short_url in result.metadata.description
    assert "Affiliate link" in result.metadata.description
    assert result.metadata.extra["monetization"]["placement_id"] == result.placement.placement_id
    assert vault_db.list_placements("video-99", db_path)[0].placement_id == result.placement.placement_id


def test_monetization_linker_skips_when_no_active_offer(tmp_path):
    db_path = tmp_path / "vault.db"
    svc = AffiliateService(db_path)
    now = datetime.now(timezone.utc).isoformat()
    svc.upsert_offer(OfferRecord(
        offer_id="paused",
        name="Paused Offer",
        network="direct",
        url="https://example.com/paused",
        niches=["finance"],
        status="paused",
        created_at=now,
        updated_at=now,
    ))

    result = MonetizationLinker(db_path).monetize_metadata(
        PublishMetadata(title="Title", description="Description"),
        niche="finance",
        video_id="video-1",
        channel_id="ch",
        platform_id="youtube",
    )

    assert result.monetized is False
    assert result.skipped_reason == "no_active_offer"
    assert result.metadata.description == "Description"
