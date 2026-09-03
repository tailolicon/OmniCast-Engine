"""video_intel measures instead of asserting constants (review §4, P0 item 5).

The verified bug: `analyze_visual_style` returned "cinematic" for every video,
`analyze_audio_pattern` returned 150 wpm without counting a word, and
`analyze_hook` returned hook_type="question" without reading the hook — and all
of it flowed into a ProductionBlueprint carrying confidence up to 0.8, so a
fabricated blueprint looked exactly like a measured one.

These tests pin: real numbers where measurement is possible, "unknown" plus a
note where it is not, and confidence that falls when the inputs were assumed."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from omnicast.analytics.crawler import AnalyticsCrawler
from omnicast.analytics.transcript import Segment, Transcript
from omnicast.analytics.video_intel import UNKNOWN, VideoIntelligenceAnalyzer


@pytest.fixture
def analyzer():
    return VideoIntelligenceAnalyzer(crawler=MagicMock(spec=AnalyticsCrawler))


def _transcript(cues):
    segs = tuple(Segment(start=s, text=t, duration=d) for s, t, d in cues)
    return Transcript(video_id="v1", text=" ".join(s.text for s in segs),
                      source="captions", segments=segs)


# ── Pacing is counted, not assumed ───────────────────────────────────────────

async def test_words_per_minute_is_actually_counted(analyzer):
    """300 words over 2 minutes is 150 wpm — and 600 words over 2 minutes must
    not also be 150 wpm, which is what the constant did."""
    slow = Transcript(video_id="v", text=" ".join(["word"] * 200), source="captions")
    fast = Transcript(video_id="v", text=" ".join(["word"] * 400), source="captions")
    slow_out = await analyzer.analyze_audio_pattern({}, slow, duration_seconds=120)
    fast_out = await analyzer.analyze_audio_pattern({}, fast, duration_seconds=120)
    assert slow_out["words_per_min"] == 100
    assert fast_out["words_per_min"] == 200
    assert slow_out["voice_pacing"] == "slow"
    assert fast_out["voice_pacing"] == "fast"


async def test_pacing_without_a_transcript_is_unknown_not_150(analyzer):
    out = await analyzer.analyze_audio_pattern({})
    assert out["words_per_min"] == 0
    assert out["voice_pacing"] == UNKNOWN
    assert out["measured"] is False
    assert any("not measurable" in n for n in out["notes"])


async def test_music_energy_without_features_is_unknown(analyzer):
    out = await analyzer.analyze_audio_pattern({}, Transcript(video_id="v", text="a b c"),
                                               duration_seconds=60)
    assert out["music_energy"] == UNKNOWN


async def test_music_energy_is_derived_when_features_exist(analyzer):
    loud = await analyzer.analyze_audio_pattern({"rms_mean": 0.2})
    quiet = await analyzer.analyze_audio_pattern({"rms_mean": 0.01})
    assert loud["music_energy"] == "high"
    assert quiet["music_energy"] == "low"


# ── Hook is read, not assumed ────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Why do most investors lose money in their first year?", "question"),
    ("97% of traders blow up their account within 90 days.", "shock_stat"),
    ("In 1943 a clerk in Zurich made a decision that changed banking.", "story"),
    ("Most people make the same mistake with their savings.", "pain"),
    ("In this video I'll show you the three-step system.", "preview"),
    ("Alright. Let me set the scene.", "cold_open"),
])
async def test_hook_type_is_classified_from_the_words(analyzer, text, expected):
    out = await analyzer.analyze_hook(text)
    assert out["hook_type"] == expected


async def test_hook_strength_varies_with_the_devices_present(analyzer):
    """It was the constant 8 for every video, including a video with no hook."""
    rich = await analyzer.analyze_hook(
        "Why did 97% of you lose money? Here's the mistake.")
    bare = await analyzer.analyze_hook("Alright. Let me set the scene.")
    assert rich["hook_strength"] > bare["hook_strength"]
    assert rich["evidence"]


async def test_hook_reads_the_first_thirty_SECONDS_not_characters(analyzer):
    t = _transcript([
        (0.0, "Alright, let me set the scene.", 5.0),
        (60.0, "Why does nobody talk about this?", 5.0),
    ])
    out = await analyzer.analyze_hook(t)
    # The question at 60s is not the hook.
    assert out["hook_type"] == "cold_open"
    assert out["words_in_hook"] == 6


async def test_missing_hook_transcript_is_reported(analyzer):
    out = await analyzer.analyze_hook("")
    assert out["hook_type"] == "cold_open"
    assert out["hook_strength"] == 0
    assert out["notes"]


async def test_cta_in_the_hook_is_detected(analyzer):
    out = await analyzer.analyze_hook("Before we start, subscribe for more.")
    assert out["cta_present"] is True


# ── Visual style is tallied, not "cinematic" ─────────────────────────────────

async def test_visual_style_without_frames_is_unknown(analyzer):
    out = await analyzer.analyze_visual_style([])
    assert out["art_direction"] == UNKNOWN
    assert out["dominant_colors"] == []
    assert out["measured"] is False


async def test_art_direction_follows_the_frames(analyzer):
    anime = await analyzer.analyze_visual_style(
        ["anime character close up", "cel shaded street", "manga panel style"])
    minimal = await analyzer.analyze_visual_style(
        ["minimal white background", "flat design chart", "clean layout with simple icons"])
    assert anime["art_direction"] == "anime"
    assert minimal["art_direction"] in {"minimal", "motion_graphics"}


async def test_overlay_and_face_ratios_are_real_fractions(analyzer):
    out = await analyzer.analyze_visual_style([
        "talking head presenter in studio",
        "b-roll of a city with text overlay",
        "stock footage of a factory",
        "chart with on-screen text",
    ])
    assert out["talking_head_ratio"] == 0.25
    assert out["text_overlay_freq"] == 0.5
    assert out["b_roll_ratio"] == 0.75


# ── Structure is detected from timings ───────────────────────────────────────

async def test_beats_come_from_pauses_and_markers(analyzer):
    t = _transcript([
        (0.0, "Welcome back.", 3.0),
        (3.0, "Today we look at three cases.", 4.0),
        (30.0, "First, the Zurich clerk.", 4.0),   # marker + long pause
        (70.0, "Second, the London desk.", 4.0),   # marker
        (120.0, "So that's the pattern.", 4.0),
    ])
    out = await analyzer.analyze_structure(t, duration_seconds=130)
    assert out["measured"] is True
    assert out["segment_count"] >= 3
    assert out["beat_starts"][0] == 0.0
    assert out["intro_length"] == 30.0


async def test_structure_from_a_bare_string_admits_it_is_an_estimate(analyzer):
    out = await analyzer.analyze_structure("just a string", duration_seconds=600)
    assert out["measured"] is False
    assert any("estimated" in n for n in out["notes"])


async def test_partial_transcript_coverage_is_flagged(analyzer):
    t = _transcript([(0.0, "start", 3.0), (60.0, "still early", 3.0)])
    out = await analyzer.analyze_structure(t, duration_seconds=1200)
    assert any("late-video structure" in n for n in out["notes"])


# ── Blueprint confidence reflects what was measured ──────────────────────────

def _analysis(measured: bool, art="cinematic", hook="question", energy="medium"):
    return {
        "structure": {"intro_length": 20, "segment_count": 6, "measured": measured},
        "visual": {"art_direction": art, "b_roll_ratio": 0.4,
                   "text_overlay_freq": 0.3, "color_mood": "warm", "measured": measured},
        "audio": {"music_energy": energy, "words_per_min": 150, "measured": measured},
        "hook": {"hook_type": hook, "measured": measured},
    }


async def test_measured_blueprint_outranks_an_assumed_one(analyzer):
    measured = await analyzer.build_blueprint("finance", [_analysis(True)] * 5)
    assumed = await analyzer.build_blueprint("finance", [_analysis(False)] * 5)
    assert measured.confidence > assumed.confidence
    assert assumed.confidence > 0  # weak, not absent


async def test_empty_analyses_no_longer_claim_cinematic_and_a_question_hook(analyzer):
    bp = await analyzer.build_blueprint("finance", [])
    assert bp.art_style == UNKNOWN
    assert bp.hook_type == UNKNOWN
    assert bp.music_energy == UNKNOWN
    assert bp.confidence == 0.0


async def test_blueprint_votes_by_majority_not_by_first_sample(analyzer):
    """`visual_analyses[0]` made whichever sample came first the answer."""
    analyses = [
        _analysis(True, art="cinematic", hook="question"),
        _analysis(True, art="minimal", hook="shock_stat"),
        _analysis(True, art="minimal", hook="shock_stat"),
    ]
    bp = await analyzer.build_blueprint("finance", analyses)
    assert bp.art_style == "minimal"
    assert bp.hook_type == "shock_stat"


def test_aggregate_patterns_also_votes(analyzer):
    from datetime import datetime, timezone

    from omnicast.analytics.models import ProductionBlueprint

    def _bp(art, hook):
        return ProductionBlueprint(
            niche="finance", video_format="documentary", art_style=art,
            pacing_scene_duration=(2.0, 5.0), crossfade_seconds=0.5,
            music_energy="medium", text_overlay_freq=0.3, b_roll_ratio=0.4,
            hook_type=hook, intro_duration=20.0, target_duration_minutes=10,
            color_mood="warm", confidence=0.5, sample_size=3,
            generated_at=datetime.now(timezone.utc))

    out = analyzer.aggregate_patterns([_bp("cinematic", "question"),
                                       _bp("minimal", "shock_stat"),
                                       _bp("minimal", "shock_stat")])
    assert out.art_style == "minimal"
    assert out.hook_type == "shock_stat"
