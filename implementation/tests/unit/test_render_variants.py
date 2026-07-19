import pytest

from omnicast.media.variants import RenderVariantExporter
from omnicast.platforms.models import FormatSpec
from omnicast.shared.errors import MediaError


def test_build_vertical_variant_command_uses_crop():
    exporter = RenderVariantExporter()
    spec = FormatSpec(
        variant="tiktok_9x16",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
    )

    cmd = exporter.build_command("master.mp4", "tiktok.mp4", spec)

    assert cmd[:4] == ["ffmpeg", "-y", "-i", "master.mp4"]
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in vf
    assert "crop=1080:1920" in vf
    assert "omnicast_variant=tiktok_9x16" in cmd


def test_build_widescreen_command_uses_pad():
    exporter = RenderVariantExporter()
    spec = FormatSpec(
        variant="youtube_16x9",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
    )

    cmd = exporter.build_command("master.mp4", "youtube.mp4", spec)

    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf
    assert "pad=1920:1080" in vf


def test_unsupported_aspect_ratio_fails_fast():
    exporter = RenderVariantExporter()
    spec = FormatSpec(variant="wide", aspect_ratio="21:9")

    with pytest.raises(MediaError, match="Unsupported aspect ratio"):
        exporter.build_command("master.mp4", "wide.mp4", spec)
