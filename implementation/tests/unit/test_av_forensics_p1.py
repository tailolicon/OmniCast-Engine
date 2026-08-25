"""P1 §15/§5 — audiovisual forensics, on real files.

The review calls §5 the largest gap: the system could read what a competitor
SAID and had never looked at how the video was CUT.

These tests render small videos with ffmpeg and measure them, rather than
asserting on hand-built dicts. A forensics module tested only against fixtures
would pass while measuring nothing — which is precisely the failure mode
`video_intel` shipped with for two sessions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from omnicast.analytics import av_forensics as avf

pytestmark = pytest.mark.skipif(
    not avf.ffmpeg_available(), reason="ffmpeg/ffprobe not on PATH")


def _render(path: Path, filter_complex: str, inputs: list[str], *,
            fps: int = 24, audio: str | None = None) -> Path:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for source in inputs:
        cmd += ["-f", "lavfi", "-i", source]
    if audio:
        cmd += ["-f", "lavfi", "-i", audio]
    cmd += ["-filter_complex", filter_complex, "-map", "[v]"]
    if audio:
        cmd += ["-map", f"{len(inputs)}:a", "-c:a", "aac", "-shortest"]
    cmd += ["-r", str(fps), "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, capture_output=True, timeout=120, check=True)
    return path


@pytest.fixture(scope="module")
def three_shots(tmp_path_factory) -> Path:
    """Three 3-second shots: static red, moving pattern, static blue."""
    out = tmp_path_factory.mktemp("avf") / "three_shots.mp4"
    return _render(
        out,
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        ["color=c=0x902808:s=320x180:d=3,format=yuv420p",
         "testsrc2=s=320x180:d=3,format=yuv420p",
         "color=c=0x081060:s=320x180:d=3,format=yuv420p"],
    )


@pytest.fixture(scope="module")
def one_warm_shot(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("avf") / "warm.mp4"
    return _render(out, "[0:v]copy[v]",
                   ["color=c=0x902808:s=320x180:d=4,format=yuv420p"],
                   audio="sine=f=300:d=4")


# ── shot rhythm ─────────────────────────────────────────────────────────────

def test_it_finds_the_shots_that_are_actually_there(three_shots):
    report = avf.analyse_video(three_shots)
    assert report.field_status["shots"] == avf.MEASURED
    assert report.shot_count == 3
    assert report.median_shot_seconds == pytest.approx(3.0, abs=0.4)
    assert report.cuts_per_minute == pytest.approx(13.3, abs=2.0)


def test_shot_boundaries_line_up_with_where_the_cuts_are(three_shots):
    report = avf.analyse_video(three_shots)
    starts = [round(s.start) for s in report.shots]
    assert starts == [0, 3, 6]


def test_a_single_take_is_one_shot_not_a_pile_of_false_positives(one_warm_shot):
    report = avf.analyse_video(one_warm_shot)
    assert report.shot_count == 1
    assert report.transition_mix == {}


# ── motion ──────────────────────────────────────────────────────────────────

def test_a_locked_off_shot_is_not_reported_as_dynamic(three_shots):
    """The bug this test exists for: the cut itself is the largest frame
    difference in the video, so leaving it inside the OUTGOING shot made a
    three-second static colour card measure as `dynamic`."""
    report = avf.analyse_video(three_shots)
    by_index = {s.index: s for s in report.shots}
    assert by_index[0].motion == "static"
    assert by_index[2].motion == "static"
    assert by_index[1].motion == "dynamic"


def test_the_motion_mix_is_weighted_by_runtime_not_by_shot_count(three_shots):
    """One long locked-off shot and forty whip pans are opposite grammars;
    counting shots would call the first one 97% dynamic."""
    report = avf.analyse_video(three_shots)
    mix = report.motion_mix
    assert mix["static"] == pytest.approx(0.67, abs=0.1)
    assert sum(mix.values()) == pytest.approx(1.0, abs=0.01)


# ── colour ──────────────────────────────────────────────────────────────────

def test_colour_mood_is_measured_from_the_pixels(one_warm_shot):
    report = avf.analyse_video(one_warm_shot)
    assert report.field_status["colour"] == avf.MEASURED
    assert report.colour_mood == "warm"
    assert report.colour_metrics["warmth"] > 0


def test_a_cold_frame_reads_cold(tmp_path):
    cold = _render(tmp_path / "cold.mp4", "[0:v]copy[v]",
                   ["color=c=0x081060:s=320x180:d=2,format=yuv420p"])
    assert avf.analyse_video(cold).colour_mood == "cold"


# ── audio ───────────────────────────────────────────────────────────────────

def test_loudness_is_measured_and_named_for_what_it_actually_is(one_warm_shot):
    """ebur128 is missing or broken in some builds and prints a full summary of
    0.0 anyway, then exits 0. A confident "0.0 LUFS" would flag every video as
    clipping. The fallback is a DIFFERENT measurement under a different name."""
    report = avf.analyse_video(one_warm_shot)
    assert report.field_status["loudness"] == avf.MEASURED
    assert report.integrated_lufs != 0.0
    if report.integrated_lufs is None:
        assert report.mean_volume_dbfs is not None
        assert any("NOT LUFS" in n for n in report.notes)


def test_a_video_with_no_audio_stream_says_so_rather_than_reporting_silence(
        three_shots):
    report = avf.analyse_video(three_shots)
    assert report.silence_ratio is None or report.field_status["silence"] == avf.MEASURED


# ── honesty about what it cannot do ─────────────────────────────────────────

def test_the_review_items_it_cannot_measure_are_listed_as_missing(three_shots):
    report = avf.analyse_video(three_shots)
    for name in ("kinetic_typography", "character_consistency", "camera_framing",
                 "talking_head_vs_broll", "thumbnail_promise_payoff"):
        assert report.field_status[name] == avf.MISSING
        assert avf.NOT_MEASURABLE_HERE[name]


def test_the_text_overlay_proxy_is_labelled_inferred_not_measured(three_shots):
    """Edge density is not text. It cannot tell a burned-in caption from a busy
    shop front, so it never becomes the blueprint's `text_overlay_freq`."""
    report = avf.analyse_video(three_shots)
    assert report.field_status["text_overlay_proxy"] == avf.INFERRED


def test_a_missing_file_costs_every_field_and_explains_itself(tmp_path):
    report = avf.analyse_video(tmp_path / "nope.mp4")
    assert report.field_status["duration"] == avf.MISSING
    assert report.shots == []
    assert any("unreadable" in n for n in report.notes)


def test_no_ffmpeg_is_reported_rather_than_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(avf, "ffmpeg_available", lambda: False)
    report = avf.analyse_video(tmp_path / "anything.mp4")
    assert set(report.field_status.values()) == {avf.MISSING}
    assert any("not on PATH" in n for n in report.notes)


def test_non_speech_audio_needs_a_transcript_and_says_so(one_warm_shot):
    report = avf.analyse_video(one_warm_shot)
    assert report.field_status["non_speech_audio"] == avf.MISSING
    assert any("no transcript cue timings" in n for n in report.notes)


def test_a_transcript_lets_the_music_bed_be_separated(one_warm_shot):
    from omnicast.analytics.transcript import Segment, Transcript

    transcript = Transcript(video_id="v", text="hello", source="test",
                            segments=(Segment(0.0, "hello", 1.0),))
    report = avf.analyse_video(one_warm_shot, transcript=transcript)
    assert report.field_status["non_speech_audio"] == avf.MEASURED
    assert any(s.kind == "non_speech_audio" for s in report.audio_spans)


# ── it reaches the blueprint ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forensics_gives_the_blueprint_real_pacing_and_colour(three_shots):
    from omnicast.analytics.video_intel import UNKNOWN, VideoIntelligenceAnalyzer

    analyzer = VideoIntelligenceAnalyzer()
    visual = await analyzer.analyze_forensics(three_shots)
    assert visual["measured"] is True
    assert visual["scene_count"] == 3

    blueprint = await analyzer.build_blueprint("finance", [
        {"title": "5 things", "duration_minutes": 9 / 60,
         "structure": {"measured": True, "segment_count": 3, "intro_length": 2,
                       "avg_segment_duration": 3},
         "visual": visual},
    ])
    low, high = blueprint.pacing_scene_duration
    assert low < 3.0 < high            # centred on the measured shot length
    assert any("detected shot" in n for n in blueprint.notes)
    # ...and it still refuses to invent the fields frames alone cannot support.
    assert blueprint.art_style == UNKNOWN
    assert {"art_style", "b_roll_ratio", "text_overlay_freq"} <= set(
        blueprint.assumed_fields)
    assert "color_mood" not in blueprint.assumed_fields


# ── it has a production caller (the mistake this repo has already paid for) ──

def test_the_render_audit_measures_production_grammar_on_every_product(one_warm_shot):
    """A module with no production caller is dead code with tests. `video_intel`
    shipped that way for two sessions; forensics runs on every render."""
    from omnicast.media.output_audit import OutputQualityAuditor

    grammar = OutputQualityAuditor().inspect_production_grammar(one_warm_shot)
    assert grammar["field_status"]["duration"] == avf.MEASURED
    assert grammar["shot_count"] >= 1
    assert grammar["colour_mood"] == "warm"


def test_a_forensics_failure_never_fails_the_render_audit(tmp_path, monkeypatch):
    from omnicast.analytics import av_forensics as module
    from omnicast.media.output_audit import OutputQualityAuditor

    def _boom(*a, **kw):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(module, "analyse_video", _boom)
    grammar = OutputQualityAuditor().inspect_production_grammar(tmp_path / "x.mp4")
    assert "skipped" in grammar
