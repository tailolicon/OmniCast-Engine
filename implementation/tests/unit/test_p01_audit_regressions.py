"""Regressions for defects found by the adversarial audit of P0.1 group 1.

Every test here corresponds to a concrete way the containment work was shown to
be breakable by executing it. They are grouped by the claim that was broken."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from omnicast.analytics import competitor_intel as ci
from omnicast.analytics import transcript as tr
from omnicast.analytics.intel_gate import (
    STATUS_LEGACY,
    STATUS_STALE,
    STATUS_UNCONTROLLED,
    evaluate,
)
from omnicast.discovery.models import TopicRawData
from omnicast.discovery.scorer import StackProfile, TopicScorer
from omnicast.discovery.youtube_scanner import _parse_duration_minutes
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.models.script import TopicBrief

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _raw(source=TopicSource.YOUTUBE_COMPETITOR, title="T", **metrics):
    return TopicRawData(title=title, source=source, niche=Niche.FINANCE,
                        market=Market.US, raw_metrics=metrics)


class _Row:
    def __init__(self, script_playbook="", cohort_meta="", updated_at=""):
        self.script_playbook = script_playbook
        self.cohort_meta = cohort_meta
        self.updated_at = updated_at


# ── A weak signal must score zero, not abort the run ─────────────────────────

@pytest.mark.parametrize("source,metrics", [
    (TopicSource.PODCAST, {"listen_score": 20}),        # below median → was -18
    (TopicSource.REDDIT, {"score": -450}),              # downvoted → was -4.5
    (TopicSource.GOOGLE_TRENDS, {"growth_pct": -300}),
    # The YouTube branch was the one `_clamp` initially missed — and the branch
    # the first version of this test forgot to cover.
    (TopicSource.YOUTUBE_COMPETITOR, {"outlier_ratio": -4.0}),
])
async def test_one_weak_topic_cannot_kill_the_whole_discovery_run(source, metrics):
    """`min(x, 30)` capped the top but not the bottom, so a negative momentum
    hit `ScoredTopic`'s ge=0 and raised — inside `score_batch`, which has no
    guard. One downvoted Reddit post aborted the entire run."""
    scorer = TopicScorer(scoring_mode="shadow")
    scored = await scorer.score_batch([_raw(source, **metrics)])
    assert scored[0].trend_momentum == 0.0


# ── An unrecognised scoring mode must not activate the uncalibrated one ──────

@pytest.mark.parametrize("mode", ["SHADOW", "shadow ", "off", "V2", "v3"])
def test_bad_scoring_mode_is_rejected_not_silently_promoted(mode):
    """The else-branch made every typo mean "v2 decides" — the exact opposite of
    the containment this setting exists for."""
    with pytest.raises(ValueError):
        TopicScorer(scoring_mode=mode)


@pytest.mark.parametrize("metrics", [
    {"outlier_ratio": None},
    {"outlier_ratio": float("nan")},
    {"channel_median_views": ""},
    {"channel_median_views": "unknown"},
    {"engagement_rate": "", "channel_avg_engagement": 0.04},
    {"similar_competitor_videos": "many"},
    {"score": "500"},
    {"duration_minutes": "n/a"},
])
async def test_unparseable_metrics_are_unknown_not_a_crash(metrics):
    """The `is not None` fix turned a silent mis-score into a ValueError out of
    score_batch — one malformed JSON field aborting the whole run. Unparseable
    has to mean UNKNOWN."""
    scorer = TopicScorer(scoring_mode="shadow")
    scored = await scorer.score_batch([_raw(**metrics)])
    assert 0 <= scored[0].trend_momentum <= 30
    assert 0 <= scored[0].gap_score <= 25


def test_open_ended_band_on_either_side_still_checks_runtime():
    """(0, 20) means "up to 20"; (10, 0) means "at least 10". The first fix only
    handled the first shape, so (10, 0) silently disabled the check again."""
    scorer = TopicScorer(stack_profile=StackProfile(duration_minutes=(10.0, 0.0)),
                         scoring_mode="v2")
    short, notes = scorer._calc_stack_fit(_raw(duration_minutes=1.0))
    fine, fine_notes = scorer._calc_stack_fit(_raw(duration_minutes=30.0))
    assert short < fine
    assert any("outside" in n for n in notes)
    assert fine_notes == []


def test_blocked_keyword_with_punctuation_still_vetoes():
    """`\\b` after a '+' requires a word character, so "c++" became
    unmatchable — a veto that silently stops vetoing is worse than none."""
    scorer = TopicScorer(stack_profile=StackProfile(blocked_keywords={"c++"}),
                         scoring_mode="v2")
    blocked, notes = scorer._calc_stack_fit(_raw(title="Why c++ is dying in 2026"))
    assert blocked == 0.0
    assert "blocked keyword" in notes[0]


# ── "Unknown" must not be scored as a measured value ─────────────────────────

def test_measured_zero_engagement_is_not_treated_as_no_data():
    unknown = TopicScorer._calc_gap_score(_raw())
    measured_zero = TopicScorer._calc_gap_score(
        _raw(engagement_rate=0.0, channel_avg_engagement=0.04))
    assert measured_zero < unknown


def test_measured_zero_median_is_not_treated_as_no_data():
    unknown = TopicScorer._calc_gap_score(_raw())
    tiny = TopicScorer._calc_gap_score(_raw(channel_median_views=0))
    assert tiny > unknown  # 0 median is a real (very small) incumbent


def test_duration_band_starting_at_zero_still_applies():
    """`if low and high` disabled the runtime dimension entirely for a (0, 20)
    band, so a 240-minute topic scored the same as an unknown one."""
    profile = StackProfile(niches={Niche.FINANCE}, duration_minutes=(0.0, 20.0))
    scorer = TopicScorer(stack_profile=profile, scoring_mode="v2")
    inside, _ = scorer._calc_stack_fit(_raw(duration_minutes=10.0))
    outside, notes = scorer._calc_stack_fit(_raw(duration_minutes=240.0))
    assert inside > outside
    assert any("outside" in n for n in notes)


def test_blocked_keyword_needs_a_word_boundary():
    """`"gun" in "begun"` was zeroing legitimate topics."""
    scorer = TopicScorer(stack_profile=StackProfile(blocked_keywords={"gun"}),
                         scoring_mode="v2")
    innocent, notes = scorer._calc_stack_fit(_raw(title="Begun: the retirement crisis"))
    guilty, guilty_notes = scorer._calc_stack_fit(_raw(title="Best gun stocks 2026"))
    assert innocent > 0 and notes == []
    assert guilty == 0.0 and "blocked keyword" in guilty_notes[0]


# ── Provenance must never be inherited from the current run ──────────────────

def test_carried_forward_artifact_with_no_known_provenance_is_refused():
    """When the previous row carried no readable provenance, `_merge_run` wrote
    an empty dict — and the gate then fell through to the ROW's metadata, which
    is this run's. A 500-day-old playbook came back `usable=True, age=0`."""
    previous = _Row(script_playbook="ancient playbook", cohort_meta="")
    artifacts, meta = ci._merge_run(
        previous, {"script_playbook": ""},
        {"research_run_id": "run_new", "generated_at": NOW.isoformat(),
         "is_comparable": True, "winner_count": 9, "control_count": 9})

    assert artifacts["script_playbook"] == "ancient playbook"
    assert meta["artifacts"]["script_playbook"]["research_run_id"] != "run_new"

    row = _Row(script_playbook=artifacts["script_playbook"],
               cohort_meta=json.dumps({**meta, "research_run_id": "run_new",
                                       "is_comparable": True,
                                       "generated_at": NOW.isoformat()}),
               updated_at=NOW.isoformat())
    decision = evaluate(row, now=NOW)
    assert decision.usable is False
    assert decision.status in {STATUS_STALE, STATUS_UNCONTROLLED, STATUS_LEGACY}


def test_artifact_provenance_is_used_as_a_unit_not_field_by_field():
    """Taking run_id from the artifact but age from the row let a 400-day-old
    artifact read as fresh."""
    meta = json.dumps({
        "research_run_id": "run_new", "is_comparable": True,
        "generated_at": NOW.isoformat(),
        "artifacts": {"script_playbook": {"research_run_id": "run_old",
                                          "is_comparable": True}},
    })
    decision = evaluate(_Row("playbook", meta, updated_at=NOW.isoformat()), now=NOW)
    assert decision.status == STATUS_STALE       # no timestamp on the artifact
    assert decision.research_run_id == "run_old"


def test_unknown_age_is_not_fresh():
    decision = evaluate(_Row("playbook", json.dumps({"artifacts": {
        "script_playbook": {"research_run_id": "r1", "is_comparable": True,
                            "generated_at": "2019/01/01"}}})), now=NOW)
    assert decision.status == STATUS_STALE
    assert decision.usable is False


def test_non_string_timestamp_does_not_escape_as_an_exception():
    """`_age_days` caught only ValueError; a datetime or ORM value raised
    TypeError straight out of the one call path this module exists to make
    explicit."""
    row = _Row("playbook", json.dumps({"artifacts": {"script_playbook": {
        "research_run_id": "r1", "is_comparable": True,
        "generated_at": (NOW - timedelta(days=1)).isoformat()}}}),
        updated_at=NOW - timedelta(days=1))
    decision = evaluate(row, now=NOW)
    assert decision.usable is True               # handled, not raised


@pytest.mark.parametrize("value", [0, "false", "no", "0"])
def test_falsy_comparability_flags_are_honoured(value):
    """`comparable is False` was an identity test: JSON 0 and "false" passed."""
    decision = evaluate(_Row("playbook", json.dumps({"artifacts": {
        "script_playbook": {"research_run_id": "r1", "is_comparable": value,
                            "generated_at": NOW.isoformat()}}})), now=NOW)
    assert decision.status == STATUS_UNCONTROLLED


def test_missing_comparability_is_not_treated_as_verified():
    decision = evaluate(_Row("playbook", json.dumps({"artifacts": {
        "script_playbook": {"research_run_id": "r1",
                            "generated_at": NOW.isoformat()}}})), now=NOW)
    assert decision.usable is False


# ── The fail-closed policy has to be reachable ───────────────────────────────

def test_competitor_intel_required_is_a_real_field():
    """It was read with getattr() off a frozen pydantic model that drops extras,
    so it was always False and the fail-closed branch was dead code."""
    brief = TopicBrief(title="t", niche=Niche.FINANCE, market=Market.US,
                       competitor_intel_required=True)
    assert brief.competitor_intel_required is True
    assert TopicBrief(title="t", niche=Niche.FINANCE,
                      market=Market.US).competitor_intel_required is False


# ── ASR budget cannot be bypassed by an unknown duration ─────────────────────

@pytest.mark.parametrize("iso,minutes", [
    ("PT6H12M", 372.0),
    ("P1DT2H", 1560.0),      # multi-day livestream — used to parse as 0.0
    ("P0D", 0.0),            # premiere
    ("PT1H2M30S", 62.5),
])
def test_iso_duration_handles_the_day_component(iso, minutes):
    assert _parse_duration_minutes(iso) == minutes


def test_unknown_duration_probes_instead_of_waving_the_video_through(monkeypatch):
    """`if duration_minutes and ...` let 0.0 skip the budget — and 0.0 is
    exactly what a livestream or premiere reported."""
    monkeypatch.setattr(tr, "probe_media", lambda vid: (600.0, False, ""))
    out = tr.transcribe_with_asr("v", duration_minutes=0.0, max_minutes=45.0)
    assert out.ok is False
    assert "exceeds" in out.note


def test_live_streams_are_declined_outright(monkeypatch):
    monkeypatch.setattr(tr, "probe_media", lambda vid: (0.0, True, ""))
    out = tr.transcribe_with_asr("v", duration_minutes=0.0)
    assert out.ok is False
    assert "live" in out.note


def test_unprobeable_duration_is_declined_not_attempted(monkeypatch):
    downloaded = []
    monkeypatch.setattr(tr, "probe_media", lambda vid: (0.0, False, "probe failed: X"))
    monkeypatch.setattr(tr, "_download_audio",
                        lambda vid, wd: downloaded.append(vid) or "")
    out = tr.transcribe_with_asr("v", duration_minutes=0.0)
    assert out.ok is False
    assert downloaded == []


# ── The model cache must not load N copies under concurrency ─────────────────

def test_asr_model_cache_loads_once_under_concurrent_threads(monkeypatch):
    """Check-then-act on a plain dict loaded six models for eight callers, five
    of them orphaned but still resident. At large-v3 that is multi-GB."""
    monkeypatch.setattr(tr, "_ASR_MODELS", {})
    loads = []

    def _slow_build():
        time.sleep(0.05)
        loads.append(1)
        return object()

    results = []
    barrier = threading.Barrier(8)

    def _worker():
        barrier.wait()
        results.append(tr._cached_model("k", _slow_build))

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(loads) == 1
    assert len({id(r) for r in results}) == 1


# ── Long research work must not starve unrelated to_thread callers ───────────

async def test_transcript_work_runs_off_the_shared_default_executor():
    """A 45-minute ASR job on the default executor made an unrelated 10ms
    `to_thread` call wait seconds. Research work gets its own bounded pool.

    Proven by SYNCHRONISATION, not by timing: an earlier version asserted
    `elapsed < 0.04` and failed ~3 runs in 10 on a loaded machine, because a
    scheduler-dependent threshold is a coin flip, not a proof."""
    started = threading.Event()
    release = threading.Event()
    seen: list[str] = []

    def _blocking(video_id, duration_minutes=0.0):
        seen.append(threading.current_thread().name)
        started.set()
        release.wait(timeout=5)
        return tr.Transcript(video_id=video_id, text="x", source="asr")

    import omnicast.analytics.competitor_intel as mod

    original = mod._fetch_transcript
    mod._fetch_transcript = _blocking
    try:
        # Fill every research thread and hold them there.
        jobs = [asyncio.ensure_future(mod._fetch_transcript_async(f"v{i}"))
                for i in range(mod.RESEARCH_POOL_SIZE)]
        await asyncio.to_thread(started.wait, 5)
        assert started.is_set(), "research jobs never started"

        # With the research pool fully occupied, an unrelated default-executor
        # call must still complete — that is the isolation, and it holds
        # regardless of how loaded the machine is.
        assert await asyncio.to_thread(lambda: "done") == "done"
    finally:
        release.set()
        await asyncio.gather(*jobs, return_exceptions=True)
        mod._fetch_transcript = original

    assert seen and all(name.startswith("omnicast-research") for name in seen)


def test_research_pool_is_bounded():
    assert ci._RESEARCH_EXECUTOR._max_workers == ci.RESEARCH_POOL_SIZE


# ── Thumbnail downloads have a real deadline and a size cap ──────────────────

def test_thumbnail_fetch_stops_at_the_wall_clock_deadline(monkeypatch):
    """`timeout=15` bounds each socket operation, not the transfer: a peer
    dripping one byte every two seconds held a single request open for 40s."""
    monkeypatch.setattr(ci, "THUMB_TOTAL_DEADLINE_SECONDS", 0.05)

    class _Resp:
        def __enter__(self):
            time.sleep(0.03)
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=None):
            return b"x"

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    out = ci._fetch_thumbs([f"http://x/{i}.jpg" for i in range(10)], limit=10)
    assert len(out) < 10


def test_oversized_thumbnail_is_skipped(monkeypatch):
    monkeypatch.setattr(ci, "THUMB_MAX_BYTES", 10)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=None):
            return b"y" * 1000

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert ci._fetch_thumbs(["http://x/1.jpg"]) == []


# ── Round 4: provenance you cannot follow is not provenance ─────────────────

def test_artifact_without_a_research_run_id_is_refused():
    """A record with a valid timestamp and is_comparable=True but no run id
    satisfied every other check and came back `usable=True`, breaking the one
    invariant this module exists to hold."""
    meta = json.dumps({"artifacts": {"script_playbook": {
        "generated_at": NOW.isoformat(), "is_comparable": True}}})
    decision = evaluate(_Row("playbook", meta), now=NOW)
    assert decision.status == STATUS_LEGACY
    assert decision.usable is False
    assert "research_run_id" in decision.reason
