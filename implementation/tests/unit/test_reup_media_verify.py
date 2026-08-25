"""`exists()` is not the same question as "is this file usable"."""

import json
import subprocess

import pytest

from omnicast.reup.media import verify


def _probe_returns(monkeypatch, *, rc=0, payload=None, stderr=""):
    out = json.dumps(payload or {}) if payload is not None else ""
    monkeypatch.setattr(verify.shutil, "which", lambda n: "ffprobe")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": rc, "stdout": out, "stderr": stderr})(),
    )


def _file(tmp_path, size=50_000):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\0" * size)
    return p


GOOD = {
    "format": {"duration": "600.0"},
    "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
}


def test_a_playable_file_passes(tmp_path, monkeypatch):
    _probe_returns(monkeypatch, payload=GOOD)
    ok, why = verify.is_usable_output(_file(tmp_path), need_video=True, need_audio=True)
    assert ok and why == ""


def test_a_full_size_file_that_ffprobe_rejects_fails(tmp_path, monkeypatch):
    # The delivered 178 MB video with garbage NAL units: exists() said yes,
    # size said yes, only a probe caught it.
    _probe_returns(monkeypatch, rc=1, stderr="Invalid NAL unit size (0 > 34660).")
    ok, why = verify.is_usable_output(_file(tmp_path, 178_000_000))
    assert not ok and "ffprobe" in why


def test_a_truncated_encode_is_caught_by_duration(tmp_path, monkeypatch):
    # Parses fine, but stops a third of the way in.
    _probe_returns(monkeypatch, payload={
        "format": {"duration": "200.0"}, "streams": [{"codec_type": "video"}],
    })
    ok, why = verify.is_usable_output(_file(tmp_path), expected_duration_ms=600_000)
    assert not ok and "lệch" in why


def test_small_drift_is_tolerated(tmp_path, monkeypatch):
    # Rate-aligned exports never land on the exact millisecond.
    _probe_returns(monkeypatch, payload={
        "format": {"duration": "598.0"}, "streams": [{"codec_type": "video"}],
    })
    ok, _ = verify.is_usable_output(_file(tmp_path), expected_duration_ms=600_000)
    assert ok


def test_a_video_with_no_audio_is_caught_when_audio_was_promised(tmp_path, monkeypatch):
    _probe_returns(monkeypatch, payload={
        "format": {"duration": "600.0"}, "streams": [{"codec_type": "video"}],
    })
    ok, why = verify.is_usable_output(_file(tmp_path), need_audio=True)
    assert not ok and "tiếng" in why


def test_a_zero_duration_container_fails(tmp_path, monkeypatch):
    _probe_returns(monkeypatch, payload={"format": {}, "streams": [{"codec_type": "video"}]})
    ok, why = verify.is_usable_output(_file(tmp_path))
    assert not ok and "thời lượng" in why


def test_a_stub_file_never_reaches_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(verify.shutil, "which", lambda n: "ffprobe")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("should not probe"))
    ok, why = verify.is_usable_output(_file(tmp_path, 10))
    assert not ok and "byte" in why


def test_a_missing_file_says_so(tmp_path):
    ok, why = verify.is_usable_output(tmp_path / "gone.mp4")
    assert not ok and "không có file" in why


def test_no_ffprobe_means_unverified_not_assumed_good(tmp_path, monkeypatch):
    monkeypatch.setattr(verify.shutil, "which", lambda n: None)
    ok, why = verify.is_usable_output(_file(tmp_path))
    assert not ok and "ffprobe" in why
