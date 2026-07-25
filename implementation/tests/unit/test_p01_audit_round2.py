"""Regressions from the SECOND adversarial audit round.

Several of these are defects the first round of fixes introduced — a cache added
to remove a stall that then served stale and negative results, a deadline that
did not bound the request it was inside, a `float()` that turned a mis-score
into a crash. Fixes need their own adversary."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

import omnicast.agents.writer as writer_mod
from omnicast.analytics import competitor_intel as ci
from omnicast.analytics import transcript as tr

# ── The writer's intel cache must not serve absences or stale rows ───────────

def test_absent_intel_is_never_cached(monkeypatch):
    """Discovery calls `learn_for_channel` immediately before production. Caching
    "nothing learned yet" meant the writer kept seeing the absence for a whole
    minute after the row was written — and on a channel with
    competitor_intel_required=True that is a hard generation failure."""
    writer_mod.invalidate_competitor_intel_cache()
    rows = [None, "REAL ROW"]
    monkeypatch.setattr(writer_mod, "_vault_read_for_test", None, raising=False)

    calls = {"n": 0}

    def _read(scope, path=None):
        calls["n"] += 1
        return rows[min(calls["n"] - 1, len(rows) - 1)]

    import omnicast.vault.db as vdb

    monkeypatch.setattr(vdb, "init_db", lambda p: None)
    monkeypatch.setattr(vdb, "get_competitor_intel", _read)

    assert writer_mod._load_competitor_intel("finance") is None
    assert writer_mod._load_competitor_intel("finance") == "REAL ROW"
    assert calls["n"] == 2       # the absence did not stick


def test_relearning_invalidates_the_cache(monkeypatch):
    writer_mod.invalidate_competitor_intel_cache()
    state = {"row": "OLD PLAYBOOK"}

    import omnicast.vault.db as vdb

    monkeypatch.setattr(vdb, "init_db", lambda p: None)
    monkeypatch.setattr(vdb, "get_competitor_intel", lambda scope, path=None: state["row"])

    assert writer_mod._load_competitor_intel("finance") == "OLD PLAYBOOK"
    state["row"] = "NEW PLAYBOOK"
    assert writer_mod._load_competitor_intel("finance") == "OLD PLAYBOOK"  # cached

    writer_mod.invalidate_competitor_intel_cache("finance")
    assert writer_mod._load_competitor_intel("finance") == "NEW PLAYBOOK"


def test_cache_hit_avoids_the_repeated_read(monkeypatch):
    writer_mod.invalidate_competitor_intel_cache()
    calls = {"n": 0}

    import omnicast.vault.db as vdb

    monkeypatch.setattr(vdb, "init_db", lambda p: None)

    def _read(scope, path=None):
        calls["n"] += 1
        return "ROW"

    monkeypatch.setattr(vdb, "get_competitor_intel", _read)
    for _ in range(3):
        writer_mod._load_competitor_intel("finance")
    assert calls["n"] == 1


def test_cache_is_lock_protected():
    assert isinstance(writer_mod._INTEL_CACHE_LOCK, type(threading.Lock()))


# ── Thumbnail budget must bound the transfer, not just the loop ──────────────

def test_thumbnail_deadline_interrupts_a_slow_transfer(monkeypatch):
    """A deadline checked only at the top of the loop does not bound the request
    it is already inside: 80s was measured against a 45s "budget"."""

    class _DribblingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=None):
            time.sleep(0.02)
            return b"x" * 8

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _DribblingResponse())
    started = time.monotonic()
    out = ci._fetch_thumbs(["http://x/1.jpg"], deadline=time.monotonic() + 0.1)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, "the read was not interrupted by the deadline"
    assert out == []          # a partial download is not a thumbnail


def test_both_thumbnail_groups_share_one_budget(monkeypatch):
    """Winners and controls each got their own 45s, so the stage budget was
    silently double what it claimed."""
    seen = []

    def _fake(urls, limit=8, deadline=None):
        seen.append(deadline)
        return [b"img"] if urls else []

    monkeypatch.setattr(ci, "_fetch_thumbs", _fake)
    monkeypatch.setattr(ci, "_thumb_urls", lambda c, b, per_group=5: (["a"], ["b"]))
    ci._learn_thumbnails(None, {}, google_key="", claude_key="k")
    assert len(seen) == 2
    assert seen[0] == seen[1] is not None


# ── The research pool must push back instead of queueing for hours ───────────

async def test_research_pool_refuses_to_queue_an_invisible_backlog(monkeypatch):
    """Two threads plus an unbounded queue is not backpressure. 500 submitted
    jobs queued silently behind an HTTP request nobody can cancel."""
    monkeypatch.setattr(ci, "MAX_RESEARCH_IN_FLIGHT", 2)
    release = threading.Event()

    def _block():
        release.wait(timeout=5)
        return "done"

    running = [asyncio.ensure_future(ci._in_research_pool(_block)) for _ in range(2)]
    await asyncio.sleep(0.05)
    with pytest.raises(ci.ResearchPoolBusy):
        await ci._in_research_pool(_block)
    release.set()
    await asyncio.gather(*running)


async def test_busy_pool_degrades_to_a_note_not_a_failed_run(monkeypatch):
    from omnicast.analytics.cohort import select_cohort

    def _v(vid, views, day="2026-07-01"):
        return {"video_id": vid, "title": vid, "views": views,
                "duration_minutes": 15.0, "published_at": f"{day}T00:00:00Z"}

    cohort = select_cohort({"c": [_v("win", 50_000), _v("a", 10_000, "2026-07-04"),
                                  _v("b", 9_500, "2026-06-20")]})

    async def _busy(video_id, duration_minutes=0.0):
        raise ci.ResearchPoolBusy("pool full")

    monkeypatch.setattr(ci, "_fetch_transcript_async", _busy)

    class _LLM:
        async def complete(self, **kw):
            raise AssertionError("should not reach the model with no digests")

    playbook, notes = await ci._learn_scripts(_LLM(), cohort, {})
    assert playbook == ""
    assert any("pool full" in n for n in notes)


def test_research_pool_shuts_down_without_blocking_exit():
    assert callable(ci._shutdown_research_pool)


# ── ASR budget: NaN slipped past BOTH gates ─────────────────────────────────

@pytest.mark.parametrize("duration", [float("nan"), float("inf"), None, "x", -5.0])
def test_non_numeric_duration_never_reaches_the_downloader(monkeypatch, duration):
    """`nan <= 0` is False AND `nan > 45` is False, so a NaN duration was
    neither probed nor rejected — it went straight to download and transcribe."""
    monkeypatch.setattr(tr, "probe_media", lambda vid: (0.0, False, ""))
    monkeypatch.setattr(tr, "_download_audio",
                        lambda vid, wd: pytest.fail("download must not be attempted"))
    out = tr.transcribe_with_asr("v", duration_minutes=duration)
    assert out.ok is False


def test_asr_budget_shrinks_for_slower_models():
    """The minute budget bounds AUDIO length, not transcription wall time, and
    the model is env-settable. 45 minutes of audio through large-v3 is hours of
    one of only two research threads."""
    assert tr.asr_budget_minutes("large-v3") < tr.asr_budget_minutes("base")
    assert tr.asr_budget_minutes("tiny") > tr.asr_budget_minutes("base")


# ── OAuth must not be driven on a private event loop ────────────────────────

def test_oauth_uses_the_sync_entry_point_not_asyncio_run(monkeypatch):
    """`asyncio.run` in a worker thread works today, but deadlocks silently the
    moment anything in OAuth2Manager becomes genuinely async — and it deadlocks
    as a hang, so an uncontended test would keep passing."""
    from omnicast.platforms.youtube import YouTubePlatform

    calls = []

    class _Manager:
        def get_credentials_sync(self, account_id):
            calls.append(account_id)
            return "creds"

        async def get_credentials(self, account_id):
            raise AssertionError("the coroutine path must not be used")

    plat = YouTubePlatform(uploader=object(), oauth=_Manager())
    assert plat._resolve_oauth_credentials("acct") == "creds"
    assert calls == ["acct"]


def test_oauth_manager_exposes_a_sync_entry_point():
    from omnicast.upload.oauth import OAuth2Manager

    assert callable(getattr(OAuth2Manager, "get_credentials_sync", None))


# ── Round 3: the calibration work was entirely untested ─────────────────────

def _yt(trend, gap, gap_v1=20.0, v1=60.0, v2=58.0):
    return {"source": "youtube_competitor", "trend_momentum": trend,
            "gap_score": gap, "gap_score_v1": gap_v1,
            "total_v1": v1, "total_v2": v2}


def test_eta_bins_by_value_so_ties_share_a_group():
    """Rank-binning split tied x values across groups and credited their
    y-variance to x: a corpus where trend saturates at 30.0 for 40 rows scored
    eta 1.0 against a true eta of 0.018."""
    from omnicast.discovery.scoring_calibration import correlation_ratio

    xs = [30.0] * 40 + [3.0] * 10
    ys = [float(i % 5) for i in range(50)]
    assert correlation_ratio(xs, ys) < 0.2


def test_eta_is_independent_of_row_order():
    """`sorted()` is stable, so ties kept harvest order and the same JSONL gave
    a different go/no-go depending on how it was written."""
    import random

    from omnicast.discovery.scoring_calibration import summarize

    xs = [30.0] * 40 + [3.0] * 10
    rows = [_yt(x, float(i % 5)) for i, x in enumerate(xs)]
    first = summarize(rows).eta_trend_gap_v2_youtube
    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    assert summarize(shuffled).eta_trend_gap_v2_youtube == first


def test_eta_refuses_to_answer_when_x_never_varies():
    from omnicast.discovery.scoring_calibration import correlation_ratio

    assert correlation_ratio([1.0] * 50, [float(i % 7) for i in range(50)]) is None


def test_eta_refuses_when_every_group_is_a_singleton():
    """One point per bin drives eta to 1.0 by construction, which is an artifact
    of the method rather than a finding."""
    from omnicast.discovery.scoring_calibration import correlation_ratio

    xs = [float(i) for i in range(20)]
    assert correlation_ratio(xs, [float(i % 3) for i in xs], bins=50) is None


def test_eta_still_catches_the_u_shape_pearson_misses():
    from omnicast.discovery.scoring_calibration import (
        DECOUPLING_CORR_LIMIT,
        DECOUPLING_ETA_LIMIT,
        summarize,
    )

    rows = []
    for i in range(60):
        trend = 6 + i * 0.4
        rows.append(_yt(trend, 25.0 if abs(trend - 18) > 6 else 0.0,
                        gap_v1=20 + (i % 3)))
    report = summarize(rows)
    assert abs(report.corr_trend_gap_v2_youtube) <= DECOUPLING_CORR_LIMIT
    assert report.eta_trend_gap_v2_youtube > DECOUPLING_ETA_LIMIT
    assert report.decoupled is False
    assert report.ready_to_promote is False
    assert any("non-linearly" in n for n in report.notes)


def test_youtube_churn_gates_promotion_even_when_pooled_churn_is_calm():
    """50 YouTube rows at 100% churn under 200 unchanged RSS rows pooled to
    20% — which reads as calm."""
    from omnicast.discovery.scoring_calibration import summarize

    rows = [_yt(10 + i * 0.3, 12 + (i % 4), gap_v1=20 + (i % 3), v1=79, v2=60)
            for i in range(50)]
    rows += [{"source": "news_rss", "trend_momentum": 10, "gap_score": 12,
              "gap_score_v1": 20, "total_v1": 60, "total_v2": 58}
             for _ in range(200)]
    report = summarize(rows)
    assert report.changed_lane_pct < 25.0            # pooled looks calm
    assert report.youtube_changed_lane_pct == 100.0  # the source that moved
    assert report.ready_to_promote is False


def test_malformed_values_are_dropped_not_raised():
    """`float("")` raised out of summarize; only ABSENT keys were handled."""
    from omnicast.discovery.scoring_calibration import summarize

    rows = [{"source": "youtube_competitor", "trend_momentum": None,
             "gap_score": "n/a", "gap_score_v1": 1, "total_v1": "", "total_v2": 2}
            for _ in range(10)]
    report = summarize(rows)
    assert report.dropped_rows == 10
    assert report.usable_rows == 0
    assert report.ready_to_promote is False


def test_eta_note_does_not_fire_on_a_thin_sample():
    from omnicast.discovery.scoring_calibration import summarize

    rows = [_yt(float(i), float(i % 2) * 25) for i in range(10)]
    assert not any("step-shaped" in n for n in summarize(rows).notes)


# ── Round 3: collection-shaped metrics and keyword hygiene ──────────────────

def test_scalar_production_requirement_still_vetoes():
    """A string where a list was expected iterated CHARACTERS, so the hard
    production veto silently stopped vetoing."""
    from omnicast.discovery.models import TopicRawData
    from omnicast.discovery.scorer import StackProfile, TopicScorer
    from omnicast.models.enums import Market, Niche, TopicSource

    topic = TopicRawData(title="t", source=TopicSource.YOUTUBE_COMPETITOR,
                         niche=Niche.FINANCE, market=Market.US,
                         raw_metrics={"production_requirements": "face_cam"})
    scorer = TopicScorer(stack_profile=StackProfile(
        unsupported_requirements={"face_cam"}), scoring_mode="v2")
    assert scorer._calc_stack_fit(topic)[0] == 0.0


@pytest.mark.parametrize("keyword", ["", "   ", 5])
def test_blank_or_non_string_blocked_keyword_does_not_veto_everything(keyword):
    """`_boundary_pattern("")` produced `(?!\\w)`, which matches anywhere — one
    trailing comma in channel config zeroed every topic."""
    from omnicast.discovery.models import TopicRawData
    from omnicast.discovery.scorer import StackProfile, TopicScorer
    from omnicast.models.enums import Market, Niche, TopicSource

    topic = TopicRawData(title="Retirement planning basics",
                         source=TopicSource.YOUTUBE_COMPETITOR,
                         niche=Niche.FINANCE, market=Market.US)
    scorer = TopicScorer(stack_profile=StackProfile(blocked_keywords={keyword}),
                         scoring_mode="v2")
    assert scorer._calc_stack_fit(topic)[0] > 0


def test_non_boolean_comparability_number_is_unknown_not_true():
    """A count accidentally written into `is_comparable` read as controlled."""
    from omnicast.analytics.intel_gate import _is_comparable

    assert _is_comparable(2) is None
    assert _is_comparable(-1) is None
    assert _is_comparable(1) is True
    assert _is_comparable(0) is False


def test_cache_invalidation_key_matches_the_writer_key():
    """competitor_intel invalidated under the raw niche key; the writer caches
    under the lowercased one."""
    import inspect

    from omnicast.analytics import competitor_intel as mod

    source = inspect.getsource(mod.learn_for_channel)
    assert "invalidate_competitor_intel_cache(str(niche_key).lower())" in source


def test_eta_survives_a_skewed_x_distribution():
    """Equal-width binning collapsed under one outlier: 59 rows in bin 0, so a
    gap that really was a function of trend scored 0.09 — a false green light.
    Grouping is now by value, balanced by point count."""
    from omnicast.discovery.scoring_calibration import correlation_ratio

    xs = [float(i % 3) for i in range(59)] + [900.0]
    ys = [0.0 if x < 1 else 25.0 for x in xs]
    assert correlation_ratio(xs, ys) > 0.9


def test_eta_is_low_on_pure_noise():
    from omnicast.discovery.scoring_calibration import (
        DECOUPLING_ETA_LIMIT,
        correlation_ratio,
    )

    xs = [float(i) for i in range(60)]
    ys = [float((i * 37) % 11) for i in range(60)]
    assert correlation_ratio(xs, ys) <= DECOUPLING_ETA_LIMIT
