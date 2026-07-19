"""Channel-level opt-out of the flat-delivery pacing gate (deadpan genres)."""

import json

from omnicast.media.output_audit import OutputQualityAuditor


def _setup(tmp_path, *, flag: bool, channel: str = "dread_test"):
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / f"{channel}.json").write_text(
        json.dumps({"channel_id": channel, "pacing_flat_ok": flag}),
        encoding="utf-8")
    product = tmp_path / "product"
    product.mkdir()
    (product / "meta.json").write_text(
        json.dumps({"channel": channel}), encoding="utf-8")
    return OutputQualityAuditor(channels_dir=channels), product


def test_flag_true_allows_flat(tmp_path):
    auditor, product = _setup(tmp_path, flag=True)
    assert auditor._channel_allows_flat(product)


def test_flag_false_keeps_gate(tmp_path):
    auditor, product = _setup(tmp_path, flag=False)
    assert not auditor._channel_allows_flat(product)


def test_missing_meta_keeps_gate(tmp_path):
    auditor, _ = _setup(tmp_path, flag=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not auditor._channel_allows_flat(empty)


def test_missing_channel_config_keeps_gate(tmp_path):
    auditor, product = _setup(tmp_path, flag=True)
    (product / "meta.json").write_text(
        json.dumps({"channel": "no_such_channel"}), encoding="utf-8")
    assert not auditor._channel_allows_flat(product)


def test_inspect_product_downgrades_only_flat(tmp_path, monkeypatch):
    """pacing_flat_delivery dropped for opted-out channel; other issues stay."""
    auditor, product = _setup(tmp_path, flag=True)
    video = product / "video.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(auditor, "inspect", lambda p: {
        "path": str(p), "exists": True, "passed": True, "issues": [],
        "metadata": {}})
    monkeypatch.setattr(auditor, "inspect_visual_relevance",
                        lambda pd, topic=None: {"passed": True, "issues": [],
                                                "metadata": {}})
    monkeypatch.setattr(auditor, "inspect_pacing", lambda p: {
        "passed": False,
        "issues": ["pacing_flat_delivery", "pacing_no_dramatic_pauses"],
        "metrics": {"std_over_mean": 0.079}})
    rep = auditor.inspect_product(video, product, write_sidecar=False)
    assert "pacing_flat_delivery" not in rep["issues"]
    assert "pacing_no_dramatic_pauses" in rep["issues"]  # other gates intact
    assert rep["pacing"]["metrics"]["warning_flat_delivery_genre_ok"] is True
    assert not rep["passed"]  # still fails on the remaining issue
