"""Cover regions, logo and roaming watermark → ffmpeg filters.

The expressions here are easy to get subtly wrong and only fail at render time,
minutes into a job, so the shapes are pinned: `crop`/`drawbox` read `iw/ih`
while `overlay` only knows `W/H`, and drawtext needs an explicit font file on
the Windows builds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omnicast.reup.media.overlay import (
    CoverRegion,
    LogoOverlay,
    OverlayConfig,
    RoamingWatermark,
    SubtitleStyle,
    build_cover_filters,
    build_logo_filters,
    build_roaming_filters,
    load_config,
    save_config,
)


def _covers(regions, index=0):
    return build_cover_filters(regions, in_label="[0:v]", index=index)


def test_blur_region_crops_treats_and_overlays_back():
    filters, out, _ = _covers([CoverRegion(0.3, 0.85, 0.4, 0.1, "blur", 14)])
    joined = " ".join(filters)
    assert "split" in joined and "boxblur=14" in joined
    assert out.startswith("[cv")


def test_crop_uses_iw_but_overlay_uses_W():
    # overlay's expression context has no iw/ih — using them there fails with
    # "Undefined constant or missing '('".
    filters, _, _ = _covers([CoverRegion(0.25, 0.5, 0.2, 0.2)])
    crop = next(f for f in filters if "crop=" in f)
    overlay = next(f for f in filters if "overlay=" in f)
    assert "iw*" in crop and "ih*" in crop
    assert "W*" in overlay and "H*" in overlay
    assert "iw*" not in overlay.split("overlay=")[1]


def test_box_mode_is_a_single_drawbox():
    filters, _, _ = _covers([CoverRegion(0.8, 0.0, 0.2, 0.1, "box")])
    assert len(filters) == 1
    assert "drawbox=" in filters[0] and "t=fill" in filters[0]


def test_box_opacity_reaches_the_colour():
    filters, _, _ = _covers([CoverRegion(0.8, 0.0, 0.2, 0.1, "box", opacity=0.4)])
    assert "black@0.400" in filters[0]


def test_partially_transparent_patch_is_faded_before_overlay():
    filters, _, _ = _covers([CoverRegion(0.1, 0.1, 0.2, 0.2, "blur", 10, opacity=0.5)])
    assert any("colorchannelmixer=aa=0.500" in f for f in filters)


def test_full_opacity_skips_the_fade_step():
    filters, _, _ = _covers([CoverRegion(0.1, 0.1, 0.2, 0.2, "blur", 10, opacity=1.0)])
    assert not any("colorchannelmixer" in f for f in filters)


def test_pixelate_scales_down_then_up_with_neighbor():
    filters, _, _ = _covers([CoverRegion(0.1, 0.3, 0.15, 0.08, "pixelate", 8)])
    treatment = next(f for f in filters if "crop=" in f)
    assert "scale=iw/8" in treatment and "flags=neighbor" in treatment


def test_regions_chain_so_each_sees_the_previous_result():
    filters, out, index = _covers(
        [CoverRegion(0.1, 0.1, 0.2, 0.2, "box"), CoverRegion(0.5, 0.5, 0.2, 0.2, "box")]
    )
    assert filters[1].startswith("[cv0]"), "second region must read the first's output"
    assert out == "[cv1]"
    assert index == 2


def test_zero_sized_region_is_dropped():
    filters, out, _ = _covers([CoverRegion(0.5, 0.5, 0.0, 0.2)])
    assert filters == [] and out == "[0:v]"


def test_region_is_clamped_inside_the_frame():
    region = CoverRegion(0.9, 0.9, 0.5, 0.5).normalised()
    assert region.x + region.width <= 1.0
    assert region.y + region.height <= 1.0


def test_no_covers_passes_the_label_through():
    filters, out, index = _covers([])
    assert (filters, out, index) == ([], "[0:v]", 0)


def test_logo_without_a_real_file_is_skipped():
    filters, out, _ = build_logo_filters(
        LogoOverlay(path="C:/nope.png"), in_label="[v0]", logo_input_index=1, index=0
    )
    assert filters == [] and out == "[v0]"


def test_roaming_text_carries_an_explicit_font_file():
    # Windows ffmpeg has no fontconfig: drawtext without fontfile dies with
    # "Cannot load default config file".
    mark = RoamingWatermark(text="@Kenh", enabled=True, font_file="C:/Windows/Fonts/arial.ttf")
    filters, _, _ = build_roaming_filters(mark, in_label="[v0]", image_input_index=None, index=0)
    assert "fontfile=" in filters[0]
    assert r"C\:/Windows/Fonts/arial.ttf" in filters[0], "colon must be escaped"


def test_roaming_uses_two_different_periods():
    # Same period on both axes traces a straight line, which is trivial to crop
    # around; different periods sweep the frame.
    mark = RoamingWatermark(text="x", enabled=True, font_file="f.ttf")
    filters, _, _ = build_roaming_filters(mark, in_label="[v0]", image_input_index=None, index=0)
    assert "t/37.0" in filters[0] and "t/53.0" in filters[0]


def test_roaming_text_positions_use_text_dimensions():
    mark = RoamingWatermark(text="x", enabled=True, font_file="f.ttf")
    filters, _, _ = build_roaming_filters(mark, in_label="[v0]", image_input_index=None, index=0)
    assert "text_w" in filters[0] and "text_h" in filters[0]


def test_disabled_roaming_is_skipped():
    filters, out, _ = build_roaming_filters(
        RoamingWatermark(text="x", enabled=False), in_label="[v0]",
        image_input_index=None, index=0,
    )
    assert filters == [] and out == "[v0]"


def test_drawtext_special_characters_are_escaped():
    mark = RoamingWatermark(text="a:b'c%d", enabled=True, font_file="f.ttf")
    filters, _, _ = build_roaming_filters(mark, in_label="[v0]", image_input_index=None, index=0)
    body = filters[0].split("text='")[1].split("'", 1)[0] if "text='" in filters[0] else ""
    assert "\\:" in filters[0] and "\\%" in filters[0]


def test_config_round_trips_through_disk(tmp_path):
    config = OverlayConfig(
        covers=[CoverRegion(0.1, 0.2, 0.3, 0.4, "pixelate", 9, 0.7, "sub")],
        logo=LogoOverlay(path="l.png", position="bottom-left", scale=0.2),
        roaming=RoamingWatermark(text="@x", enabled=True),
        subtitle=SubtitleStyle(font_size=18, margin_v=64),
    )
    save_config(tmp_path, config)
    back = load_config(tmp_path)
    assert back.covers[0].opacity == pytest.approx(0.7)
    assert back.covers[0].label == "sub"
    assert back.logo.position == "bottom-left"
    assert back.roaming.text == "@x"
    assert back.subtitle.font_size == 18


def test_saving_mirrors_the_style_into_the_ass_preset(tmp_path):
    # This file is what subtitle.export reads; without the mirror a font size
    # chosen in the editor would never reach the burned-in subtitle.
    save_config(tmp_path, OverlayConfig(subtitle=SubtitleStyle(font_size=22, margin_v=70)))
    style = json.loads(
        (tmp_path / "presets" / "styles" / "default_ass_style.json").read_text(encoding="utf-8")
    )
    assert style["ass_style_json"]["FontSize"] == 22
    assert style["ass_style_json"]["MarginV"] == 70


def test_corrupt_config_falls_back_to_empty_rather_than_failing(tmp_path):
    (tmp_path / "overlays.json").write_text("{not json", encoding="utf-8")
    config = load_config(tmp_path)
    assert config.covers == [] and not config.roaming.enabled


def test_missing_config_is_an_empty_config(tmp_path):
    assert load_config(tmp_path).covers == []


def test_dropping_at_the_bottom_centre_keeps_the_default_anchor():
    from omnicast.reup.media.overlay import subtitle_anchor_from_fraction

    alignment, _, _, margin_v = subtitle_anchor_from_fraction(0.5, 0.9)
    assert alignment == 2, "bottom-centre is ASS alignment 2"
    assert margin_v == pytest.approx(0.1 * 288, abs=1)


def test_dropping_top_left_maps_to_anchor_seven():
    from omnicast.reup.media.overlay import subtitle_anchor_from_fraction

    alignment, margin_l, _, margin_v = subtitle_anchor_from_fraction(0.18, 0.15)
    assert alignment == 7
    assert margin_l == pytest.approx(0.18 * 384, abs=1)
    # Top anchors measure MarginV down from the top, not up from the bottom.
    assert margin_v == pytest.approx(0.15 * 288, abs=1)


def test_dropping_bottom_right_measures_margin_from_the_right_edge():
    from omnicast.reup.media.overlay import subtitle_anchor_from_fraction

    alignment, _, margin_r, _ = subtitle_anchor_from_fraction(0.85, 0.92)
    assert alignment == 3
    assert margin_r == pytest.approx(0.15 * 384, abs=1)


def test_middle_row_ignores_vertical_margin():
    from omnicast.reup.media.overlay import subtitle_anchor_from_fraction

    alignment, _, _, margin_v = subtitle_anchor_from_fraction(0.5, 0.5)
    assert alignment == 5
    assert margin_v == 0, "libass centres middle anchors; a margin would confuse"


def test_anchor_survives_a_round_trip_through_disk(tmp_path):
    from omnicast.reup.media.overlay import subtitle_anchor_from_fraction

    alignment, ml, mr, mv = subtitle_anchor_from_fraction(0.18, 0.15)
    save_config(tmp_path, OverlayConfig(subtitle=SubtitleStyle(
        alignment=alignment, margin_l=ml, margin_r=mr, margin_v=mv)))
    back = load_config(tmp_path).subtitle
    assert (back.alignment, back.margin_l, back.margin_v) == (alignment, ml, mv)
    style = json.loads(
        (tmp_path / "presets" / "styles" / "default_ass_style.json").read_text(encoding="utf-8")
    )["ass_style_json"]
    assert style["Alignment"] == 7 and style["MarginL"] == ml


def _hash(tmp_path, overlays=None):
    from omnicast.reup.subtitle.hardsub import DEFAULT_EXPORT_PRESET, build_hardsub_stage_hash

    video = tmp_path / "v.mp4"
    subs = tmp_path / "t.ass"
    for f in (video, subs):
        if not f.exists():
            f.write_bytes(b"x")
    return build_hardsub_stage_hash(
        source_video_path=video,
        subtitle_path=subs,
        export_preset=DEFAULT_EXPORT_PRESET,
        overlays=overlays,
    )


def test_moving_a_cover_region_invalidates_the_export_cache(tmp_path):
    # Without the overlays in the key, saving a new region and re-exporting
    # returns the cached video from before the region existed — instantly, and
    # with no covers on it.
    a = _hash(tmp_path, OverlayConfig(covers=[CoverRegion(0.4, 0.45, 0.39, 0.19)]))
    b = _hash(tmp_path, OverlayConfig(covers=[CoverRegion(0.5, 0.45, 0.39, 0.19)]))
    assert a != b


def test_blur_strength_and_opacity_reach_the_cache_key(tmp_path):
    base = CoverRegion(0.4, 0.45, 0.39, 0.19, "blur", 14, 1.0)
    assert _hash(tmp_path, OverlayConfig(covers=[base])) != _hash(
        tmp_path, OverlayConfig(covers=[CoverRegion(0.4, 0.45, 0.39, 0.19, "blur", 30, 1.0)])
    )
    assert _hash(tmp_path, OverlayConfig(covers=[base])) != _hash(
        tmp_path, OverlayConfig(covers=[CoverRegion(0.4, 0.45, 0.39, 0.19, "blur", 14, 0.5)])
    )


def test_enabling_the_roaming_mark_invalidates_the_cache(tmp_path):
    off = _hash(tmp_path, OverlayConfig(roaming=RoamingWatermark(text="@x", enabled=False)))
    on = _hash(tmp_path, OverlayConfig(roaming=RoamingWatermark(text="@x", enabled=True)))
    assert off != on


def test_a_config_that_draws_nothing_keeps_the_old_key(tmp_path):
    # Opening the editor and saving without adding anything must not force a
    # re-render of a video that is already correct.
    bare = _hash(tmp_path, None)
    assert _hash(tmp_path, OverlayConfig()) == bare
    assert _hash(tmp_path, OverlayConfig(covers=[CoverRegion(0.5, 0.5, 0.0, 0.2)])) == bare
    assert _hash(tmp_path, OverlayConfig(logo=LogoOverlay(path="", enabled=True))) == bare


def test_subtitle_style_stays_out_of_the_key(tmp_path):
    # It travels inside the .ass file, which the export already fingerprints;
    # hashing it twice would just churn the cache.
    assert _hash(tmp_path, OverlayConfig(subtitle=SubtitleStyle(font_size=40))) == _hash(tmp_path, None)


def _channel(tmp_path, payload):
    f = tmp_path / "senior_wealth_us.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f


def test_channel_defaults_apply_when_the_job_has_none(tmp_path):
    from omnicast.reup.media.overlay import save_channel_defaults

    channel = _channel(tmp_path, {"channel_id": "senior_wealth_us", "voice_profile": "kokoro:af"})
    save_channel_defaults(channel, OverlayConfig(
        roaming=RoamingWatermark(text="@Kenh", enabled=True),
        subtitle=SubtitleStyle(font_size=22),
    ))
    seeded = load_config(tmp_path / "job", channel)
    assert seeded.roaming.text == "@Kenh"
    assert seeded.subtitle.font_size == 22


def test_the_jobs_own_config_wins_over_the_channel(tmp_path):
    from omnicast.reup.media.overlay import save_channel_defaults

    channel = _channel(tmp_path, {"channel_id": "c"})
    save_channel_defaults(channel, OverlayConfig(subtitle=SubtitleStyle(font_size=22)))
    job = tmp_path / "job"
    save_config(job, OverlayConfig(subtitle=SubtitleStyle(font_size=30)))
    assert load_config(job, channel).subtitle.font_size == 30


def test_saving_defaults_keeps_the_rest_of_the_channel_config(tmp_path):
    from omnicast.reup.media.overlay import save_channel_defaults

    channel = _channel(tmp_path, {"channel_id": "c", "voice_profile": "kokoro:af_heart"})
    save_channel_defaults(channel, OverlayConfig(roaming=RoamingWatermark(text="@x", enabled=True)))
    payload = json.loads(channel.read_text(encoding="utf-8"))
    assert payload["voice_profile"] == "kokoro:af_heart", "must not clobber the channel"
    assert payload["reup_overlays"]["roaming"]["text"] == "@x"


def test_no_channel_is_simply_no_defaults(tmp_path):
    from omnicast.reup.media.overlay import channel_file_for, load_channel_defaults

    assert channel_file_for(None) is None
    assert channel_file_for("does_not_exist_anywhere") is None
    assert load_channel_defaults(None).covers == []
    assert load_channel_defaults(tmp_path / "missing.json").covers == []


def _cmd(codec):
    from omnicast.reup.subtitle.hardsub import DEFAULT_EXPORT_PRESET, build_hardsub_command

    return build_hardsub_command(
        ffmpeg_executable="ffmpeg",
        source_video_path=Path("in.mp4"),
        subtitle_path=Path("t.ass"),
        output_path=Path("out.mp4"),
        export_preset=DEFAULT_EXPORT_PRESET.model_copy(update={"video_codec": codec}),
    )


def test_nvenc_never_gets_crf(tmp_path):
    # NVENC errors out on -crf and on libx264's preset names; sending either
    # fails the export minutes in, after the filter graph is already built.
    cmd = _cmd("h264_nvenc")
    assert "h264_nvenc" in cmd
    assert "-crf" not in cmd
    assert "medium" not in cmd
    assert cmd[cmd.index("-cq") + 1] == "25"


def test_cpu_path_still_uses_crf(tmp_path):
    cmd = _cmd("h264")
    assert "libx264" in cmd and "-crf" in cmd and "-cq" not in cmd


def test_unknown_codec_falls_back_to_libx264(tmp_path):
    assert "libx264" in _cmd("something_else")


def test_export_renders_to_a_partial_name_before_swapping_in(tmp_path, monkeypatch):
    """A killed or racing export must not corrupt the file under the real name.

    `-movflags +faststart` rewrites the whole file in a second pass, so an
    interruption there leaves a full-size mp4 with garbage NAL units — which is
    exactly how a delivered video ended up unplayable.
    """
    import subprocess as sp

    from omnicast.reup.subtitle import hardsub

    seen = {}

    class _FakeProc:
        stdout = iter(())

        def wait(self):
            # Whatever ffmpeg was told to write, it must not be the final name.
            seen["target"] = Path(seen["cmd"][-1])
            seen["target"].write_bytes(b"rendered")
            return 0

    monkeypatch.setattr(hardsub.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(sp, "Popen", lambda cmd, **kw: (seen.__setitem__("cmd", cmd), _FakeProc())[1])
    # This test is about the temp-name swap, not about probing: the fake
    # encoder writes eight bytes, which the real verifier rightly rejects.
    monkeypatch.setattr(hardsub, "is_usable_output", lambda *a, **kw: (True, ""))

    workspace = _workspace(tmp_path)
    source = tmp_path / "in.mp4"; source.write_bytes(b"src")
    subs = tmp_path / "t.ass"; subs.write_text("[Script Info]\n", encoding="utf-8")
    out = hardsub.export_hardsub_video(
        _job_context(), workspace=workspace, source_video_path=source,
        subtitle_path=subs, ffmpeg_path="ffmpeg",
    )
    assert ".partial" in seen["target"].name, "ffmpeg must write a temp name"
    # ffmpeg picks its muxer from the extension, so .mp4 has to stay last.
    assert seen["target"].suffix == ".mp4"
    assert out.exists() and out.read_bytes() == b"rendered"
    assert not seen["target"].exists(), "the temp file must be swapped in, not left behind"


def test_a_failed_export_leaves_no_partial_file(tmp_path, monkeypatch):
    import subprocess as sp

    from omnicast.reup.subtitle import hardsub

    seen = {}

    class _FailProc:
        stdout = iter(())

        def wait(self):
            Path(seen["cmd"][-1]).write_bytes(b"half")
            return 1

    monkeypatch.setattr(hardsub.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(sp, "Popen", lambda cmd, **kw: (seen.__setitem__("cmd", cmd), _FailProc())[1])

    workspace = _workspace(tmp_path)
    source = tmp_path / "in.mp4"; source.write_bytes(b"src")
    subs = tmp_path / "t.ass"; subs.write_text("[Script Info]\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        hardsub.export_hardsub_video(
            _job_context(), workspace=workspace, source_video_path=source,
            subtitle_path=subs, ffmpeg_path="ffmpeg",
        )
    assert not list((tmp_path / "exports").glob("*.partial*"))


def _workspace(tmp_path):
    from omnicast.reup.project.models import ProjectWorkspace

    for sub in ("cache", "exports", "logs"):
        (tmp_path / sub).mkdir(exist_ok=True)
    return ProjectWorkspace(
        project_id="p", name="job", root_dir=tmp_path,
        database_path=tmp_path / "project.db", project_json_path=tmp_path / "project.json",
        logs_dir=tmp_path / "logs", cache_dir=tmp_path / "cache", exports_dir=tmp_path / "exports",
    )


def _job_context():
    from omnicast.reup.core.jobs import CancellationToken, JobContext

    return JobContext(
        job_id="t", logger_name="t", cancellation_token=CancellationToken(),
        progress_callback=lambda value, message: None,
    )
