"""Round six of external review — the two gates that were still only writing.

Both findings are the same defect the previous five rounds kept producing: the
READER was built and the WRITER was not, or the FLAG was set and nothing read
it. So these tests deliberately run the production path end to end rather than
the module in isolation — a unit test of `publish_blockers()` would have passed
happily while both HTTP routes ignored it.
"""

from __future__ import annotations

import json

import pytest

from omnicast.storage import products as products_mod


# ── 1. the pillar SSOT is actually WRITTEN ──────────────────────────────────

def test_the_script_step_writes_the_briefs_pillar_into_product_metadata(tmp_path,
                                                                        monkeypatch):
    """`render_real_video` reads `meta.json["pillar_id"]` to scope packaging.
    Nothing wrote it, so in production the read always came back empty and
    packaging fell through to re-classifying the script text — the exact bug
    round six was supposed to close, closed on the reading side only.

    Rather than run the whole debate (twenty LLM calls), this drives the write
    the way `_step_script` does and then asserts through the same reader the
    renderer uses.
    """
    from omnicast.models.enums import Market, Niche
    from omnicast.models.script import TopicBrief, TopicSource

    channel = type("C", (), {
        "channel_id": "ch", "niche": Niche.FINANCE, "market": Market.US,
        "intel_archetype": "explainer", "audience_segment": "retirees",
        "content_format": "longform",
        "content_pillars": [{"id": "annuities", "keywords": ["annuity", "annuities"]},
                            {"id": "social_security", "keywords": ["medicare"]}],
    })()
    brief = TopicBrief(
        title="Are annuities worth it after 65?", niche=Niche.FINANCE,
        market=Market.US, source=TopicSource.MANUAL,
        **TopicBrief.scope_fields_from_channel(
            channel, title="Are annuities worth it after 65?"))
    assert brief.pillar_id == "annuities", "fixture is not exercising the scope path"

    product_dir = tmp_path / "20260726_annuities"
    product_dir.mkdir()
    products_mod.write_meta(
        product_dir, channel="ch", topic=brief.title, slug=product_dir.name,
        pillar_id=brief.pillar_id,
        intel_archetype=brief.intel_archetype,
        audience_segment=brief.audience_segment,
        content_format=brief.content_format,
        stage="script")

    assert products_mod.read_meta(product_dir)["pillar_id"] == "annuities"


def test_the_script_step_source_carries_the_pillar_to_the_write(monkeypatch):
    """The call above is only honest if `_step_script` performs it. Checked at
    the source because reaching that write means running the debate."""
    from pathlib import Path

    import omnicast.pipeline.steps as steps

    source = Path(steps.__file__).read_text(encoding="utf-8")
    write = source.index("_products.write_meta(\n        product_dir, channel=channel_id")
    block = source[write:write + 1200]
    assert "pillar_id=" in block, "the script step still does not write pillar_id"
    assert "brief" in block


# ── 2. `publishable=False` is a GATE, not a note ────────────────────────────

def _blocked_product(tmp_path, *, channel="ch"):
    pd = tmp_path / "products" / channel / "20260726_blocked"
    pd.mkdir(parents=True)
    video = pd / "video.mp4"
    video.write_bytes(b"\x00" * 64)
    products_mod.write_meta(
        pd, channel=channel, slug=pd.name, stage="render", video=video.name,
        packaging_blocked="competitor intel required but unusable: stale corpus",
        publishable=False)
    return pd, video


def test_a_blocked_product_reports_its_blockers(tmp_path):
    pd, video = _blocked_product(tmp_path)
    blockers = products_mod.publish_blockers(pd)
    assert "marked_unpublishable" in blockers
    assert any("packaging_blocked" in b for b in blockers)
    assert products_mod.publish_blockers_for_video(video) == blockers


def test_a_normal_product_is_not_blocked(tmp_path):
    pd = tmp_path / "ok"
    pd.mkdir()
    products_mod.write_meta(pd, channel="ch", stage="render")
    assert products_mod.publish_blockers(pd) == []


def test_the_render_gate_does_not_read_the_publish_flag(tmp_path):
    """DELIBERATE SEPARATION, and it gets a test so nobody "tidies" it later.
    A re-render is how a blocked product gets unblocked. Putting this flag in
    `release_issues()` would block the only route that clears it — the same
    deadlock this project already shipped once with `needs_human`."""
    pd, _video = _blocked_product(tmp_path)
    products_mod.write_meta(pd, release_gate_version=1, script_approved=True,
                            content_locked=True, production_ready=False)
    issues = products_mod.release_issues(pd)
    assert not any("publish" in i or "packag" in i for i in issues)


@pytest.mark.asyncio
async def test_queue_publish_refuses_a_blocked_product(tmp_path, monkeypatch):
    from fastapi import HTTPException

    import omnicast.api.server as server

    pd, video = _blocked_product(tmp_path)
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "ch.json").write_text(json.dumps({"channel_id": "ch", "name": "C"}),
                                      encoding="utf-8")
    monkeypatch.setattr(server, "CHANNELS_DIR", channels)

    queued: list = []
    monkeypatch.setattr(server, "create_approval",
                        lambda payload: queued.append(payload))

    with pytest.raises(HTTPException) as exc:
        await server.queue_channel_publish("ch", {"video_path": str(video)})
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "not_publishable"
    assert not queued, "an approval row was created for an unpublishable video"


@pytest.mark.asyncio
async def test_queue_publish_still_works_for_a_clean_product(tmp_path, monkeypatch):
    """The gate must cost nothing when it should not fire — otherwise the next
    round is about a gate that blocks everything."""
    import omnicast.api.server as server

    pd = tmp_path / "products" / "ch" / "20260726_ok"
    pd.mkdir(parents=True)
    video = pd / "video.mp4"
    video.write_bytes(b"\x00" * 64)
    products_mod.write_meta(pd, channel="ch", slug=pd.name, stage="render",
                            video=video.name)
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "ch.json").write_text(json.dumps({"channel_id": "ch", "name": "C"}),
                                      encoding="utf-8")
    monkeypatch.setattr(server, "CHANNELS_DIR", channels)

    async def _fake_approval(payload):
        return {"approval": {"id": 1, **payload}}

    monkeypatch.setattr(server, "create_approval", _fake_approval)
    monkeypatch.setattr(server, "_destinations_for_channel",
                        lambda c: [{"platform_id": "youtube", "enabled": True,
                                    "destination_id": "d1"}])
    result = await server.queue_channel_publish("ch", {"video_path": str(video)})
    assert result["status"] == "waiting_approval"


@pytest.mark.asyncio
async def test_direct_upload_refuses_a_blocked_product(tmp_path, monkeypatch):
    """The SHORTER path to YouTube. Gating only the approval queue would leave
    the door open that the gate exists to close."""
    from fastapi import HTTPException

    import omnicast.api.render_routes as render_routes

    _pd, video = _blocked_product(tmp_path)

    def _boom(*a, **kw):
        raise AssertionError("upload path reached for a blocked product")

    monkeypatch.setattr(render_routes, "_yt_oauth", _boom)

    with pytest.raises(HTTPException) as exc:
        await render_routes.upload_video("ch", video=str(video))
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "not_publishable"


@pytest.mark.asyncio
async def test_force_does_not_override_the_packaging_gate(tmp_path, monkeypatch):
    """`force` exists for COMPLIANCE false positives — a heuristic being wrong.
    This flag is not a heuristic: it records that the operator asked the channel
    to stop rather than ship without verified packaging."""
    from fastapi import HTTPException

    import omnicast.api.render_routes as render_routes

    _pd, video = _blocked_product(tmp_path)
    monkeypatch.setattr(render_routes, "_yt_oauth",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("reached OAuth with force=True")))
    with pytest.raises(HTTPException) as exc:
        await render_routes.upload_video("ch", video=str(video), force=True)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_the_adapter_refuses_an_approval_row_queued_before_the_gate(tmp_path):
    """Rows outlive deployments. The check nearest the network call is the one
    that has to hold."""
    from omnicast.platforms.service import publish_approval_row

    _pd, video = _blocked_product(tmp_path)
    result = await publish_approval_row(
        {"channel_id": "ch", "video_path": str(video), "video_id": "v1", "raw": {}},
        channels_dir=tmp_path / "channels", output_dir=tmp_path / "out")
    assert "not publishable" in str(result.get("publish_error", ""))
    assert result.get("publish_blocked")


def test_successful_packaging_clears_a_previous_publish_block(tmp_path):
    """A re-render is the documented repair path for packaging failures.

    Product metadata is merge-only, so the success transition must explicitly
    replace both fields written by the failure transition.
    """
    pd, _video = _blocked_product(tmp_path)
    assert products_mod.publish_blockers(pd)

    products_mod.mark_packaging_ready(pd)

    meta = products_mod.read_meta(pd)
    assert meta["publishable"] is True
    assert meta["packaging_blocked"] == ""
    assert products_mod.publish_blockers(pd) == []


def test_video_publish_blockers_require_a_review_bound_to_this_cut(tmp_path):
    """Direct upload and old approval rows must enforce the YMYL review gate."""
    import hashlib

    pd = tmp_path / "review_required"
    pd.mkdir()
    video = pd / "video.mp4"
    video.write_bytes(b"reviewed cut")
    products_mod.write_meta(pd, requires_human_review=True)

    assert any("human_review_required" in blocker
               for blocker in products_mod.publish_blockers_for_video(video))

    products_mod.write_meta(
        pd,
        human_review={
            "reviewer": "Operator",
            "reviewed_at": "2026-07-26T12:00:00+00:00",
            "artifact_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        },
    )
    assert products_mod.publish_blockers_for_video(video) == []

    video.write_bytes(b"a different cut")
    assert any("different cut" in blocker
               for blocker in products_mod.publish_blockers_for_video(video))


@pytest.mark.asyncio
async def test_direct_upload_cannot_bypass_required_human_review(tmp_path, monkeypatch):
    from fastapi import HTTPException

    import omnicast.api.render_routes as render_routes

    pd = tmp_path / "review_required"
    pd.mkdir()
    video = pd / "video.mp4"
    video.write_bytes(b"\x00" * 64)
    products_mod.write_meta(pd, requires_human_review=True)
    monkeypatch.setattr(
        render_routes,
        "_yt_oauth",
        lambda: (_ for _ in ()).throw(
            AssertionError("reached OAuth without the required human review")),
    )

    with pytest.raises(HTTPException) as exc:
        await render_routes.upload_video("ch", video=str(video), force=True)
    assert exc.value.status_code == 409
    assert any("human_review_required" in reason
               for reason in exc.value.detail["reasons"])


def test_renderer_marks_packaging_ready_only_on_the_success_path():
    """The state transition must be wired into production, before handlers."""
    from pathlib import Path

    renderer = Path(products_mod.__file__).resolve().parents[3] / "render_real_video.py"
    source = renderer.read_text(encoding="utf-8")
    success = source.index("_products.mark_packaging_ready(out.parent)")
    required_failure = source.index("except CompetitorIntelRequired as exc:")
    generic_failure = source.index("except Exception as exc:", required_failure)

    assert success < required_failure < generic_failure
