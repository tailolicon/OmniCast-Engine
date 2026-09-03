"""Defects found in two review rounds over the P1/P2 work, pinned.

Round one was an adversarial subagent told to falsify by running code; round two
was an external reviewer who rejected the commit. Between them they found the
same class of thing twice: a module that measures correctly in isolation and is
wired so that its answer changes nothing.

The three that mattered most, and now cannot come back silently:

  * the quality gates ran AFTER the audit sidecar was written and never fed
    their verdict back, so a FAILED gate shipped;
  * `is_ymyl` was never inferred anywhere, so every finance and health video
    passed the human gate reporting "not YMYL";
  * the crossfade detector was tuned to one fade length and one contrast, so it
    missed almost every real dissolve while still publishing `shots: measured`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from omnicast.analytics import av_forensics as avf
from omnicast.animation import (
    ease,
    load_bible,
    squash_and_stretch,
    visemes_for_transcript,
)
from omnicast.animation.bible import check_continuity
from omnicast.animation.timing import OVERSHOOT_AMOUNT, Keyframe, interpolate
from omnicast.quality.benchmark import compare_to_reference
from omnicast.quality.gates import NEEDS_HUMAN, UNKNOWN, run_gates
from omnicast.strategy import portfolio_drift, review_architecture

ffmpeg = pytest.mark.skipif(not avf.ffmpeg_available(), reason="ffmpeg absent")


# ── the gate must actually gate ─────────────────────────────────────────────

def _product(tmp_path: Path, channel: dict | None = None) -> Path:
    product = tmp_path / "product"
    product.mkdir()
    (product / "meta.json").write_text(json.dumps({"channel": "ch"}), encoding="utf-8")
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "ch.json").write_text(
        json.dumps(channel or {"channel_id": "ch", "niche": "finance"}),
        encoding="utf-8")
    return product


def test_a_failed_gate_becomes_an_audit_issue_and_blocks_the_render(tmp_path):
    """It used to be appended to a sidecar that had already been written, and
    `passed` never saw it — so the video went to the approval queue."""
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path)
    auditor = OutputQualityAuditor(channels_dir=tmp_path / "channels")
    audit = {"issues": [], "pacing": {"metrics": {"std_over_mean": 0.01}},
             "visual_relevance": {"passed": True}}
    quality = auditor.run_quality_gates(product, audit, {}, {})
    assert "sound_design" in quality["failed"]
    assert quality["releasable"] is False


def test_the_gate_report_lands_in_the_sidecar_not_after_it(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path)
    video = product / "out.mp4"
    video.write_bytes(b"not a video")
    auditor = OutputQualityAuditor(channels_dir=tmp_path / "channels",
                                   measure_loudness=False)
    auditor.inspect_product(video, product)
    sidecar = json.loads((product / "_output_audit.json").read_text(encoding="utf-8"))
    assert "quality_gates" in sidecar
    assert "benchmark" in sidecar


def test_a_lost_gate_report_is_not_mistaken_for_a_clean_one(tmp_path, monkeypatch):
    from omnicast.media.output_audit import OutputQualityAuditor
    from omnicast.quality import gates as gates_module

    def _boom(evidence):
        raise RuntimeError("gate engine down")

    monkeypatch.setattr(gates_module, "run_gates", _boom)
    result = OutputQualityAuditor(channels_dir=tmp_path / "channels").run_quality_gates(
        _product(tmp_path), {"issues": []}, {}, {})
    assert result["needs_human"] == ["human_review"]
    assert "skipped" in result


# ── YMYL must be inferred, and unknown must not read as "no" ────────────────

@pytest.mark.parametrize("niche", ["finance", "health"])
def test_a_finance_or_health_channel_is_inferred_as_ymyl(tmp_path, niche):
    """Nothing upstream ever set `is_ymyl`, so it defaulted to False and every
    one of these passed the human gate reporting "not YMYL"."""
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {"channel_id": "ch", "niche": niche})
    quality = OutputQualityAuditor(channels_dir=tmp_path / "channels").run_quality_gates(
        product, {"issues": []}, {}, {})
    assert quality["needs_human"] == ["human_review"]


def test_a_non_ymyl_niche_is_not_routed_to_a_human(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {"channel_id": "ch", "niche": "mythology"})
    quality = OutputQualityAuditor(channels_dir=tmp_path / "channels").run_quality_gates(
        product, {"issues": []}, {}, {})
    assert quality["needs_human"] == []


def test_an_undeterminable_risk_class_is_unknown_not_a_pass():
    outcome = run_gates({}).get("human_review")
    assert outcome.status == UNKNOWN
    assert "not a finding that the video is low risk" in outcome.reason


def test_an_explicit_flag_still_wins_over_the_inferred_one(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {"channel_id": "ch", "niche": "finance",
                                  "is_ymyl": False})
    quality = OutputQualityAuditor(channels_dir=tmp_path / "channels").run_quality_gates(
        product, {"issues": []}, {}, {})
    assert quality["needs_human"] == []


# ── benchmark has a production caller ───────────────────────────────────────

def test_the_render_audit_compares_against_a_declared_golden_reference(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {
        "channel_id": "ch", "niche": "mythology",
        "benchmark_reference": {"reference_id": "gold_1",
                                "blind_human_comparison": True,
                                "median_shot_seconds": 4.0,
                                "colour_warmth": 10.0,
                                "words_per_minute": 150,
                                "caption_density": 0.3,
                                "transition_mix": {"cut": 0.9, "dissolve": 0.1}},
    })
    grammar = {"median_shot_seconds": 4.0, "colour_metrics": {"warmth": 10.0},
               "transition_mix": {"cut": 0.9, "dissolve": 0.1},
               "text_overlay_proxy": 0.3}
    pacing = {"metrics": {"syllable_rate_mean": 150}}
    report = OutputQualityAuditor(
        channels_dir=tmp_path / "channels").compare_against_golden(
            product, grammar, pacing)
    assert report["reference_id"] == "gold_1"
    # Every dimension the render audit CAN measure matches the reference...
    for name in ("shot_duration_distribution", "colour_treatment"[1:] and
                 "color_treatment", "voice_pacing", "caption_typography",
                 "transition_grammar"):
        scored = next(d for d in report["dimensions"] if d["dimension"] == name)
        assert scored["status"] == "measured"
        assert scored["similarity"] == pytest.approx(1.0)
    # ...and the headline is STILL withheld, naming the ones nothing measures
    # yet. §8 forbids the overall claim until every dimension is covered, and
    # SFX placement and the music energy curve have no analyser at all.
    assert report["headline_similarity"] is None
    blocked = "; ".join(report["headline_blocked_by"])
    assert "sfx_placement" in blocked and "music_energy_curve" in blocked


def test_no_declared_reference_means_no_headline_not_a_default(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    report = OutputQualityAuditor(
        channels_dir=tmp_path / "channels").compare_against_golden(
            _product(tmp_path), {}, {})
    assert report["headline_similarity"] is None
    assert report["headline_blocked_by"]


def test_a_string_precondition_of_no_does_not_publish_a_headline():
    """`bool("no")` is True, and this is the precondition the whole module
    exists to enforce."""
    ours = {"beat_count": 5}
    comparison = compare_to_reference(
        ours, {**ours, "reference_id": "g", "blind_human_comparison": "no"})
    assert comparison.blind_human_comparison is False
    assert comparison.headline is None


# ── the crossfade detector ──────────────────────────────────────────────────

def _clip(path: Path, spec: str, *, rate: int = 24) -> Path:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    *spec.split("\x00"), "-r", str(rate), "-pix_fmt", "yuv420p",
                    str(path)], check=True, capture_output=True, timeout=120)
    return path


@ffmpeg
@pytest.mark.parametrize("fade", ["0.3", "0.5", "1", "2"])
def test_a_crossfade_of_any_length_is_detected_as_a_dissolve(tmp_path, fade):
    """The first detector had a fixed window and absolute thresholds, so the
    arithmetic pinned it to fades of 0.75-1.5s with a luma change of 25-60 of
    255. Everything else — including this project's own 0.5s house default —
    was invisible while the file was still published as one measured shot."""
    out = _clip(tmp_path / f"x{fade}.mp4",
                "-f\x00lavfi\x00-i\x00color=c=0x902808:s=320x180:d=5\x00"
                "-f\x00lavfi\x00-i\x00color=c=0x081060:s=320x180:d=5\x00"
                f"-filter_complex\x00[0:v][1:v]xfade=transition=fade:"
                f"duration={fade}:offset=4[v]\x00-map\x00[v]")
    report = avf.analyse_video(out)
    assert report.transition_mix.get("dissolve") == 1
    assert report.shot_count == 2


@ffmpeg
def test_a_hard_cut_is_still_a_cut(tmp_path):
    out = _clip(tmp_path / "cut.mp4",
                "-f\x00lavfi\x00-i\x00color=c=0x902808:s=320x180:d=4\x00"
                "-f\x00lavfi\x00-i\x00color=c=0x081060:s=320x180:d=4\x00"
                "-filter_complex\x00[0:v][1:v]concat=n=2:v=1:a=0[v]\x00-map\x00[v]")
    report = avf.analyse_video(out)
    assert report.transition_mix == {"cut": 1}


@ffmpeg
def test_moving_footage_does_not_invent_shots_or_dissolves(tmp_path):
    """The obvious way to catch dissolves — lower the scene threshold — puts a
    false boundary inside every animated shot."""
    out = _clip(tmp_path / "anim.mp4",
                "-f\x00lavfi\x00-i\x00testsrc2=s=320x180:d=8\x00"
                "-filter_complex\x00[0:v]copy[v]\x00-map\x00[v]")
    report = avf.analyse_video(out)
    assert report.shot_count == 1
    assert report.transition_mix == {}


# ── av_forensics degradation ────────────────────────────────────────────────

def test_a_probe_timeout_is_not_reported_as_an_unreadable_file(monkeypatch,
                                                               tmp_path):
    monkeypatch.setattr(avf, "_run", lambda *a, **kw: avf._TIMED_OUT)
    report = avf.analyse_video(tmp_path / "big.mp4")
    assert any("timed out" in n for n in report.notes)
    assert not any("could not read a duration" in n for n in report.notes)


def test_a_timeout_inside_the_stream_probe_does_not_raise(monkeypatch, tmp_path):
    """`has_stream` was the one unguarded consumer of the timeout sentinel, and
    it turned a slow probe into an AttributeError out of a module whose whole
    contract is that a failed probe costs its own field."""
    monkeypatch.setattr(avf, "_run", lambda *a, **kw: avf._TIMED_OUT)
    avf.has_stream("anything.mp4", "v")   # must not raise


def test_a_junk_cue_timing_costs_its_own_cue(tmp_path):
    class _Segment:
        start = "n/a"
        duration = "n/a"
        text = "hello"

    class _Transcript:
        segments = (_Segment(),)

    assert avf._cue_spans(_Transcript()) == []


# ── strategy and animation, from the same rounds ────────────────────────────

def test_a_string_is_not_a_list_of_published_titles():
    channel = type("C", (), {"content_pillars": [
        {"id": "a", "keywords": ["annuity"]}]})()
    architecture = review_architecture(channel, "annuity basics")
    assert architecture.total_published == 1


def test_an_unusable_portfolio_target_keeps_its_lane_visible():
    """Dropping the lane removed it from `drift` and `out_of_band` entirely, so
    a 100%-proven slate stopped reporting `proven` as skewed."""
    portfolio = portfolio_drift(["proven"] * 10,
                                target={"proven": "lots", "adjacent": 0.2,
                                        "asymmetric": 0.1})
    assert "proven" in portfolio.drift
    assert "proven" in portfolio.out_of_band


def test_squash_and_stretch_preserves_volume_at_every_scale():
    for factor in (1e-6, 1e-5, 0.5, 1.0, 2.0, 2e4, 1e6):
        x, y = squash_and_stretch(factor)
        assert x * y == pytest.approx(1.0, rel=1e-6)
        assert x > 0 and y > 0
    assert squash_and_stretch(1e-320) == (1.0, 1.0)


def test_the_overshoot_constant_delivers_what_it_says():
    """It used to deliver a hundredth of its nominal value, because the bump was
    multiplied by a term that is ~0 exactly where the bump peaks."""
    peak = max(ease("overshoot", t / 2000) for t in range(2001))
    assert peak == pytest.approx(1.0 + OVERSHOOT_AMOUNT, abs=0.01)


def test_a_nan_keyframe_cannot_leak_a_value_from_outside_the_range():
    assert interpolate([Keyframe(float("nan"), 99.0)], 12345) is None
    assert interpolate([Keyframe(0.0, 0.0), Keyframe(1.0, 5.0),
                        Keyframe(float("nan"), 99.0)], 50) == 5.0


@pytest.mark.parametrize("raw", [{"poses": 5}, {"poses": {"id": "p"}},
                                 {"expressions": "x"},
                                 {"poses": [{"id": "p", "tags": 5}]},
                                 {"palette": "abc"}])
def test_a_scalar_where_a_list_belongs_does_not_raise(raw):
    bible = load_bible(raw)
    assert isinstance(bible.poses, list)


def test_a_nan_intensity_never_reaches_the_serialised_bible():
    bible = load_bible({"expressions": [{"id": "e", "intensity": float("nan")}]})
    value = bible.expressions[0].intensity
    assert value == value            # not NaN


def test_check_continuity_without_a_bible_says_so_rather_than_raising():
    issues = check_continuity([{"pose": "x"}], None)
    assert [i.kind for i in issues] == ["no_bible"]


def test_a_viseme_track_never_runs_backwards():
    """Segments out of order, or overlapping, are a normal transcript-merge
    artefact. `_merge` used to collapse a run across the discontinuity into a
    cue whose `end` was before its `start`."""
    class _Segment:
        def __init__(self, start, duration, text):
            self.start, self.duration, self.text = start, duration, text

    class _Transcript:
        segments = (_Segment(5.0, 1.0, "world"), _Segment(0.0, 1.0, "hello"),
                    _Segment(0.5, 2.0, "overlapping"))

    track = visemes_for_transcript(_Transcript())
    assert track
    for cue in track:
        assert cue.end >= cue.start
    for previous, following in zip(track, track[1:]):
        assert following.start >= previous.start


def test_a_non_latin_line_is_speech_not_silence():
    """A whole Korean line yielded one `rest` cue — a character who never opens
    their mouth — and the repo ships Korean voice config."""
    from omnicast.animation import text_to_visemes

    cues = text_to_visemes("안녕하세요 여러분", 0.0, 2.0)
    assert [c.viseme for c in cues] != ["rest"]
    assert all(c.source == "unmapped_script" for c in cues)


def test_the_calibration_module_uses_the_shared_number_coercion():
    """It carried its own, and diverged in exactly the two ways the shared one
    exists to stop: `"1e400"` became `inf` and reached the report, and `10**400`
    raised `OverflowError` out of `summarize`."""
    from omnicast.discovery.scoring_calibration import _num as calibration_num
    from omnicast.shared.numbers import num as shared_num

    assert calibration_num is shared_num
    for value in ("1e400", 10 ** 400, float("inf"), float("nan"), True):
        assert calibration_num(value) is None


# ── review round 3: the approval lifecycle must be reachable ────────────────

def test_needs_human_flags_the_product_instead_of_failing_the_render(tmp_path):
    """THE DEADLOCK. `needs_human` became an audit issue, `passed` went False,
    the render raised — and it raised BEFORE the step that queues the video for
    approval. The flag blocked the only route to the review that clears it, and
    nothing else writes `human_reviewed`. Finance and health could never be
    produced at all."""
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {"channel_id": "ch", "niche": "finance"})
    video = product / "out.mp4"
    video.write_bytes(b"x" * 1024)
    auditor = OutputQualityAuditor(channels_dir=tmp_path / "channels",
                                   measure_loudness=False)
    result = auditor.inspect_product(video, product)

    assert result["requires_human_review"] is True
    assert result["human_review_gates"] == ["human_review"]
    # ...and the flag is NOT one of the things that failed the audit.
    # (Checked by PREFIX: `tmp_path` is named after the test, so a substring
    # search for "needs_human" matches the ffprobe error's own file path.)
    assert not any(str(i).startswith("quality_gate_needs_human")
                   for i in result["issues"])


def test_a_real_failure_still_fails_the_audit(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {"channel_id": "ch", "niche": "mythology"})
    (product / "storyboard.json").write_text(
        json.dumps([{"image_prompt": "same"} for _ in range(8)]), encoding="utf-8")
    video = product / "out.mp4"
    video.write_bytes(b"x" * 1024)
    result = OutputQualityAuditor(channels_dir=tmp_path / "channels",
                                  measure_loudness=False).inspect_product(video, product)
    assert any(str(i).startswith("quality_gate:continuity") for i in result["issues"])


def test_a_review_must_name_a_reviewer_a_time_and_the_exact_cut(tmp_path):
    """Without the hash, an approval survives a re-render: the reviewer approved
    one video and a different one publishes under the same approval."""
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path)
    video = product / "out.mp4"
    video.write_bytes(b"first cut")
    digest = OutputQualityAuditor.artifact_hash(video)
    assert digest

    meta = json.loads((product / "meta.json").read_text(encoding="utf-8"))
    for bad in ({"reviewer": "op"},
                {"reviewer": "op", "reviewed_at": "now"},
                {"reviewed_at": "now", "artifact_sha256": digest}):
        meta["human_review"] = bad
        (product / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        assert OutputQualityAuditor._human_review_recorded(product, video) is False

    meta["human_review"] = {"reviewer": "op", "reviewed_at": "now",
                            "artifact_sha256": digest}
    (product / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert OutputQualityAuditor._human_review_recorded(product, video) is True

    # Re-render: the approval no longer covers what is on disk.
    video.write_bytes(b"second cut")
    assert OutputQualityAuditor._human_review_recorded(product, video) is False


def test_a_recorded_review_clears_the_flag_end_to_end(tmp_path):
    from omnicast.media.output_audit import OutputQualityAuditor

    product = _product(tmp_path, {"channel_id": "ch", "niche": "finance"})
    video = product / "out.mp4"
    video.write_bytes(b"x" * 1024)
    auditor = OutputQualityAuditor(channels_dir=tmp_path / "channels",
                                   measure_loudness=False)
    assert auditor.inspect_product(video, product)["requires_human_review"] is True

    meta = json.loads((product / "meta.json").read_text(encoding="utf-8"))
    meta["human_review"] = {"reviewer": "operator", "reviewed_at": "2026-07-26T00:00:00Z",
                            "artifact_sha256": OutputQualityAuditor.artifact_hash(video)}
    (product / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert auditor.inspect_product(video, product)["requires_human_review"] is False


# ── the router must fail closed without a renderer ──────────────────────────

def test_a_config_string_does_not_make_animation_routable():
    """It returned `mode=animation, was_substituted=False` for a pipeline with
    nothing able to draw a frame — and the scene then fell through to a
    generated image. That is the thing the review rejects, wearing the label of
    the thing it is not."""
    from omnicast.media.production_router import (
        ANIMATION,
        animation_renderer_available,
        capabilities_from_channel,
        route_scene,
    )

    assert animation_renderer_available() is False
    channel = type("C", (), {"supported_production": ["character_animation"]})()
    route = route_scene(0, "Our character leaps across the gap",
                        capabilities=capabilities_from_channel(channel))
    assert route.mode != ANIMATION


# ── the strategy endpoint reads the analytics the vault already holds ───────

def test_daily_metrics_feed_the_stage_gates():
    """The endpoint claimed impressions, CTR and AVD were "not collected yet"
    while `channel_metrics_daily` had been storing them all along."""
    from omnicast.strategy import evaluate_gates

    results = evaluate_gates({
        "scored_topics": 40, "approved_topics": 9,
        "published_videos": 6, "audit_pass_rate": 0.9,
        "impressions": 50_000, "ctr": 0.06, "avd_percent": 0.42,
    })
    reached = [r.gate for r in results]
    assert "packaging" in reached and "retention" in reached
    assert results[reached.index("packaging")].status == "pass"
