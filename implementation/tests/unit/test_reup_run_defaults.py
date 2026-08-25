"""Defaults on the run request must not quietly override the project."""

from omnicast.api.reup_routes import ReupRunRequest
from omnicast.ingest.douyin.client import DEFAULT_VIDEO_QUALITY, DouyinIngestConfig, _build_config


def test_omitting_the_voice_keeps_the_project_preset():
    # It used to default to "Mai Anh", so a caller that never mentioned a voice
    # got VieNeu even with a CapCut preset configured — a whole video dubbed in
    # the wrong voice, with nothing in the request to explain it.
    assert ReupRunRequest(url="https://x").voice_id is None


def test_asking_for_a_voice_still_works():
    assert ReupRunRequest(url="https://x", voice_id="capcut:BV074_streaming").voice_id == (
        "capcut:BV074_streaming"
    )


def test_the_default_download_is_1080p_not_the_uploaders_original(tmp_path):
    # "highest" probes the original: 2560x1440 / 20 Mbps / 1.48 GB on a measured
    # post, for a source delivered at 1080p anyway.
    assert DEFAULT_VIDEO_QUALITY == "1080p"
    assert DouyinIngestConfig(output_dir=tmp_path).video_quality == "1080p"


def test_the_cover_is_fetched_with_the_video(tmp_path):
    config = _build_config(DouyinIngestConfig(output_dir=tmp_path))
    assert config.get("cover") is True, "the source thumbnail comes for free with the download"


def test_the_original_is_still_reachable_on_request(tmp_path):
    assert DouyinIngestConfig(output_dir=tmp_path, video_quality="highest").video_quality == (
        "highest"
    )


def _health(**backends):
    return {"backends": backends, "checks": {"ffmpeg": {"ok": True}}}


def test_a_backend_with_no_key_is_refused_before_any_work():
    """The job used to download and transcribe for fifteen minutes, then die at
    the translate stage on a missing key — an answer already available upfront."""
    import pytest
    from fastapi import HTTPException

    from omnicast.api.reup_routes import _preflight_backend

    with pytest.raises(HTTPException) as excinfo:
        _preflight_backend("groq", _health(groq=False, **{"claude-cli": True}))
    assert excinfo.value.status_code == 409
    assert "claude-cli" in excinfo.value.detail, "say what still works"


def test_a_usable_backend_passes():
    from omnicast.api.reup_routes import _preflight_backend

    _preflight_backend("groq", _health(groq=True))


def test_backend_aliases_resolve():
    from omnicast.api.reup_routes import _preflight_backend

    _preflight_backend("claude", _health(**{"claude-cli": True}))


def test_an_unknown_backend_is_left_to_the_runner():
    # Not our call to make here; the engine factory raises a clearer error.
    from omnicast.api.reup_routes import _preflight_backend

    _preflight_backend("something-new", _health(groq=False))
