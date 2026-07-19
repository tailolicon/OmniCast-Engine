from datetime import datetime, timedelta, timezone

import pytest

from omnicast.capabilities import Capability, CapabilityBus, CapabilityRegistry, ResolvePolicy
from omnicast.credentials import BudgetGuard, CredentialVault, KeyPool
from omnicast.monetization.affiliate import AffiliateService
from omnicast.monetization.redirect import RedirectService
from omnicast.runtime import ResourceProbe, RuntimeRouter
from omnicast.shared.errors import NotFoundError, QuotaExhausted, QuotaExceeded
from omnicast.vault import db as vault_db
from omnicast.vault.models import OfferRecord


def test_m2_vault_schema_and_provider_model_crud(tmp_path):
    db_path = tmp_path / "vault.db"
    registry = CapabilityRegistry(db_path)

    registry.register(Capability(
        capability_id="text:local:test",
        kind="text",
        provider_id="local-test",
        model_id="tiny",
        runtime="local",
        cost_per_unit=0.01,
        metadata={"name": "Local Test"},
    ))

    providers = vault_db.list_providers(path=db_path)
    models = vault_db.list_models(path=db_path)
    assert providers[0].provider_id == "local-test"
    assert models[0].model_id == "tiny"
    assert registry.list_capabilities("text")[0].provider_id == "local-test"


def test_m2_keypool_cools_down_429_and_rotates_to_next_key(tmp_path):
    db_path = tmp_path / "vault.db"
    vault = CredentialVault(db_path=db_path)
    first = vault.store_secret(provider="flow", account_id="a", secret="one", priority=10)
    second = vault.store_secret(provider="flow", account_id="b", secret="two", priority=20)
    pool = KeyPool(db_path, cooldown_seconds=60)

    acquired = pool.acquire("flow")
    assert acquired.credential_id == first.credential_id

    pool.report(acquired, status="429", capability="image", used=1)
    rotated = pool.acquire("flow")

    assert rotated.credential_id == second.credential_id
    cooled = vault_db.get_credential(first.credential_id, db_path)
    assert cooled is not None
    assert cooled.cooldown_until is not None
    assert datetime.fromisoformat(cooled.cooldown_until) > datetime.now(timezone.utc)


def test_m2_keypool_raises_when_all_keys_in_cooldown(tmp_path):
    db_path = tmp_path / "vault.db"
    vault = CredentialVault(db_path=db_path)
    cred = vault.store_secret(provider="gemini", account_id="a", secret="one")
    cred.cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    vault_db.upsert_credential(cred, db_path)

    with pytest.raises(QuotaExhausted):
        KeyPool(db_path).acquire("gemini")


def test_m2_budget_guard_persists_and_blocks_over_limit(tmp_path):
    db_path = tmp_path / "vault.db"
    guard = BudgetGuard(db_path)

    guard.set_budget(scope="channel", scope_id="ch1", limit_usd=1.0)
    guard.record("channel", "ch1", 0.4, provider_id="deepseek", capability="text")

    same_db_guard = BudgetGuard(db_path)
    same_db_guard.check("channel", "ch1", 0.6)
    with pytest.raises(QuotaExceeded):
        same_db_guard.check("channel", "ch1", 0.61)
    assert vault_db.sum_usage_cost("channel", "ch1", db_path) == 0.4


@pytest.mark.asyncio
async def test_m2_capability_bus_records_budget_usage(tmp_path):
    db_path = tmp_path / "vault.db"
    registry = CapabilityRegistry(db_path)

    async def handler(request):
        return {"echo": request["text"]}

    registry.register(
        Capability(
            capability_id="text:test:tiny",
            kind="text",
            provider_id="test",
            model_id="tiny",
            cost_per_unit=0.25,
        ),
        handler,
    )
    BudgetGuard(db_path).set_budget(scope="campaign", scope_id="camp1", limit_usd=1.0)
    result = await CapabilityBus(registry, db_path=db_path).run(
        "text",
        {"text": "hello"},
        policy=ResolvePolicy(scope="campaign", scope_id="camp1"),
    )

    assert result.value == {"echo": "hello"}
    assert vault_db.sum_usage_cost("campaign", "camp1", db_path) == 0.25


@pytest.mark.asyncio
async def test_c4_capability_bus_falls_back_to_second_provider(tmp_path):
    db_path = tmp_path / "vault.db"
    registry = CapabilityRegistry(db_path)

    async def broken(_request):
        raise RuntimeError("primary down")

    async def working(request):
        return {"provider": "backup", "text": request["text"]}

    registry.register(
        Capability("text:primary:tiny", "text", "primary", "primary-tiny", cost_per_unit=0.1),
        broken,
    )
    registry.register(
        Capability("text:backup:tiny", "text", "backup", "backup-tiny", cost_per_unit=0.2),
        working,
    )

    result = await CapabilityBus(registry, db_path=db_path).run_with_fallback(
        "text",
        {"text": "hello"},
        policy=ResolvePolicy(fallback_chain=["primary", "backup"]),
    )

    assert result.value == {"provider": "backup", "text": "hello"}
    assert result.capability.provider_id == "backup"
    assert result.raw["fallback_errors"][0]["capability_id"] == "text:primary:primary-tiny"


def test_m3_runtime_router_prefers_local_and_gates_vram(tmp_path):
    db_path = tmp_path / "vault.db"
    registry = CapabilityRegistry(db_path)
    registry.register(Capability(
        capability_id="image:local:heavy",
        kind="image",
        provider_id="local",
        model_id="heavy",
        runtime="local",
        min_vram_mb=24000,
    ))
    registry.register(Capability(
        capability_id="image:remote:gemini",
        kind="image",
        provider_id="gemini",
        model_id="imagen",
        runtime="remote",
    ))

    class FakeProbe(ResourceProbe):
        def gpu_free_mb(self) -> int:
            return 1000

    chain = RuntimeRouter(registry, probe=FakeProbe()).resolve(
        "image",
        ResolvePolicy(prefer_runtime="local"),
    )

    assert chain[0].provider_id == "gemini"
    assert any(item["capability_id"] == "image:local:heavy" for item in chain[0].skipped)
    assert any(item["reason"] == "insufficient_vram" for item in chain[0].skipped)


def test_c3_provider_manifest_surfaces_media_capabilities():
    from omnicast.media.providers.registry import list_providers

    providers = list_providers()
    by_key = {(p["category"], p["id"]): p for p in providers}

    assert ("image", "flow") in by_key
    assert ("tts", "kokoro") in by_key
    assert by_key[("image", "local-sd")]["runtime"] == "local"
    assert by_key[("image", "local-sd")]["min_vram_mb"] >= 8000
    assert "config_schema" in by_key[("image", "gemini")]


def test_m4_redirect_records_click_and_missing_placement_404s(tmp_path):
    db_path = tmp_path / "vault.db"
    svc = AffiliateService(db_path)
    now = datetime.now(timezone.utc).isoformat()
    offer = OfferRecord(
        offer_id="offer1",
        name="Offer One",
        network="direct",
        url="https://example.com/product",
        niches=["finance"],
        created_at=now,
        updated_at=now,
    )
    svc.upsert_offer(offer)
    placement = svc.create_placement(
        offer=offer,
        video_id="vid1",
        channel_id="ch1",
        platform_id="youtube",
    )
    redirect = RedirectService(db_path)

    url = redirect.track_click(placement.placement_id, referrer="https://youtu.be/x")

    assert url == placement.destination_url
    assert len(vault_db.list_clicks(placement.placement_id, db_path)) == 1
    with pytest.raises(NotFoundError):
        redirect.track_click("missing")


def test_m2_m6_api_surfaces_are_available():
    from fastapi.testclient import TestClient
    from omnicast.api.server import app

    client = TestClient(app)
    for path in ["/api/capabilities", "/api/budgets", "/api/usage"]:
        response = client.get(path)
        assert response.status_code == 200
    readiness = client.get("/api/monetization/readiness").json()
    check_names = {c["name"] for c in readiness["checks"]}
    assert {"capability_registry", "budget_guard", "runtime_router"} <= check_names
