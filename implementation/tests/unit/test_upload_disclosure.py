"""Truth-labeling + synthetic-content disclosure (strategic review 2026-07-23 §20).

The 2026 policy requires the altered/synthetic-content label on realistic AI
imagery (found-photo stills, historical reconstruction); omitting it risks
demotion and strikes. UploadMetadata.ai_disclosure existed since day one but
was silently dropped by the request builder — the exact "feature on the
diagram, no real capability" failure mode the review §13 documents."""

from __future__ import annotations

import json
from pathlib import Path

from omnicast.upload.models import UploadMetadata, UploadRequest
from omnicast.upload.youtube_api import YouTubeUploader


def _request(**meta_overrides) -> UploadRequest:
    meta = UploadMetadata(
        title="t", description="d", **meta_overrides,
    )
    return UploadRequest(
        video_id="v1", channel_id="true_dread_files_us",
        video_path="x.mp4", metadata=meta,
    )


def _uploader() -> YouTubeUploader:
    return YouTubeUploader(oauth_manager=object())


def test_ai_disclosure_reaches_the_api_body():
    body = _uploader()._build_body(_request(ai_disclosure=True))
    assert body["status"]["containsSyntheticMedia"] is True


def test_disclosure_never_asserts_synthetic_free():
    """False must OMIT the field, not send containsSyntheticMedia=False — we
    never explicitly certify a video as synthetic-free."""
    body = _uploader()._build_body(_request(ai_disclosure=False))
    assert "containsSyntheticMedia" not in body["status"]


def test_dread_channel_config_uses_dramatized_framing():
    """§20.4: the channel card claimed REAL ACCOUNTS for fictional stories —
    literal-truth assertion, the manipulation/inauthentic risk zone. The
    config is the SSOT for the card subtitle and the description disclaimer
    every upload must carry."""
    cfg = json.loads(
        (Path(__file__).resolve().parents[2] / "channels" / "true_dread_files_us.json")
        .read_text(encoding="utf-8")
    )
    assert "REAL ACCOUNTS" not in cfg["card_intro_subtitle"]
    assert "DRAMATIZED" in cfg["card_intro_subtitle"]
    assert "dramatized" in cfg["description_disclaimer"]
    assert "fictionalized" in cfg["description_disclaimer"]
