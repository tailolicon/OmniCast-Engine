"""Defects found by an adversarial pass over this session's work, pinned.

The pass was told to falsify claims by RUNNING code, not by reading it. It
reproduced nine defects across the new modules. Every one of them is a test
here, because the most expensive lesson on this project is that a rule no test
can fail is not a rule — an earlier audit reverted both halves of the writer's
intel gate with the whole suite still green.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from omnicast.agents import writer as writer_mod
from omnicast.analytics.cohort import select_cohort
from omnicast.analytics.comment_intel import analyse_comments
from omnicast.analytics.intel_scope import fallback_chain, scope_key
from omnicast.analytics.schedule import analyse_schedule
from omnicast.config.channel import ChannelProfile
from omnicast.discovery.scorer import _num
from omnicast.discovery.scoring_calibration import summarize
from omnicast.models.enums import Market, Niche
from omnicast.models.script import TopicBrief
from omnicast.shared.production_signals import infer_production_requirements
from omnicast.shared.title_patterns import classify_title
from omnicast.shared.topic_coverage import content_tokens

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _v(vid, *, age=30, views=10_000, minutes=15.0, title=None, published=None):
    if published is None:
        published = (NOW - timedelta(days=age)).isoformat().replace("+00:00", "Z")
    return {"video_id": vid, "title": title or f"title {vid}", "views": views,
            "duration_minutes": minutes, "published_at": published}


# ── 1a. the cohort must not depend on the order the API returned pages in ───

def test_the_cohort_is_a_function_of_the_data_not_of_the_page_order():
    """Reproduced: 30 shuffles of one video set produced 29 different cohorts,
    because both sorts broke ties on input order. The cohort feeds the persisted
    playbook, so two runs over identical API responses produced two playbooks —
    while the module docstring advertised a pure function."""
    videos = ([_v(f"w{i}", views=300_000) for i in range(1, 6)]
              + [_v(f"c{i}", views=10_000) for i in range(1, 11)])
    seen = set()
    for trial in range(20):
        shuffled = list(videos)
        random.Random(trial).shuffle(shuffled)
        cohort = select_cohort({"ch": shuffled}, now=NOW)
        seen.add((tuple(w.video_id for w in cohort.winners),
                  tuple((c.matched_to, c.video_id) for c in cohort.controls)))
    assert len(seen) == 1


# ── 1b. one malformed row must not abort the whole cohort ───────────────────

@pytest.mark.parametrize("bad", [
    {"published_at": 12345},
    {"views": "lots"},
    {"views": float("nan")},
    {"views": 10 ** 400},
    {"duration_minutes": "ten"},
    {"engagement_rate": "n/a"},
    {"title": 999},
])
def test_a_malformed_field_costs_one_row_not_the_whole_cohort(bad):
    """`analytics.schedule` already survived every one of these rows; the cohort
    raised. Same repo, same data, two answers."""
    videos = [dict(_v("bad", views=500_000), **bad),
              _v("a"), _v("b"), _v("c")]
    cohort = select_cohort({"ch": videos}, now=NOW)   # must not raise
    assert isinstance(cohort.notes, list)


def test_a_none_entry_in_the_video_list_is_skipped():
    cohort = select_cohort({"ch": [None, _v("a"), _v("b"), _v("c")]}, now=NOW)
    assert isinstance(cohort.notes, list)


def test_a_duplicate_video_id_is_counted_once():
    """A repeated id produced two identical winner rows and inflated
    `winner_count`, which is the number a reader uses to judge sample size."""
    dup = _v("w", views=500_000)
    cohort = select_cohort({"ch": [dup, dict(dup), _v("a"), _v("b"), _v("c")]},
                           now=NOW)
    ids = [w.video_id for w in cohort.winners]
    assert len(ids) == len(set(ids))


# ── 4. comment intel must not depend on the API's return order ──────────────

def _comment(text, *, likes=0, cid="c", thread=None):
    return {"comment_id": cid, "thread_id": thread or cid, "text": text,
            "like_count": likes, "is_reply": False, "reply_count": 0}


def test_comment_intel_is_stable_when_the_api_returns_the_same_comments_reordered():
    """Reproduced: 40 shuffles gave 40 different "top timestamps" and 6
    different vocabularies. Ties are the normal case on a small sample, so which
    terms survived the cut was decided by paging order."""
    terms = ["annuity", "medicare", "pension", "roth", "bonds", "reits"]
    rows = [_comment(f"good point about {t} at {i}:0{i}", cid=f"{t}{i}")
            for t in terms for i in range(1, 4)]
    outputs = set()
    for trial in range(20):
        shuffled = list(rows)
        random.Random(trial).shuffle(shuffled)
        intel = analyse_comments(shuffled, vocabulary_size=3)
        outputs.add(json.dumps({
            "vocab": intel.audience_vocabulary,
            "stamps": intel.referenced_timestamps,
            "questions": intel.unanswered_questions,
        }, sort_keys=True))
    assert len(outputs) == 1


@pytest.mark.parametrize("rows", [
    [None],
    [{"text": "?", "like_count": "x"}],
    [{"text": 12345}],
    [{"text": "I don't understand", "like_count": None, "reply_count": "n/a"}],
])
def test_comment_intel_survives_malformed_rows(rows):
    analyse_comments(rows)   # must not raise


# ── 5a. `_num` promised that one bad field cannot abort a run ───────────────

def test_a_huge_integer_is_unknown_not_an_exception():
    """`float(10**400)` raises OverflowError, which was outside the caught
    exceptions — so a valid-JSON scanner field aborted `score_batch`, the exact
    failure `_num`'s docstring says it exists to prevent."""
    assert _num(10 ** 400) is None
    assert _num("1e400") is None
    assert _num(float("nan")) is None
    assert _num(True) is None


@pytest.mark.asyncio
async def test_one_poisoned_topic_does_not_abort_the_batch():
    from omnicast.discovery.models import TopicRawData
    from omnicast.discovery.scorer import TopicScorer
    from omnicast.models.enums import TopicSource

    def _topic(**metrics):
        return TopicRawData(title="T", source=TopicSource.YOUTUBE_COMPETITOR,
                            niche=Niche.FINANCE, market=Market.US,
                            raw_metrics=metrics)

    scored = await TopicScorer().score_batch([
        _topic(outlier_ratio=3.0),
        _topic(outlier_ratio=10 ** 400),
        _topic(outlier_ratio=4.0),
    ])
    assert len(scored) == 3


# ── 5c/5d. neighbouring helpers must agree on what they tolerate ────────────

@pytest.mark.parametrize("value", [None, 12345, float("nan"), b"bytes", ["x"]])
def test_the_pure_text_helpers_coerce_rather_than_raise(value):
    classify_title(value)
    content_tokens(value)
    infer_production_requirements(value, value)


def test_schedule_survives_a_non_numeric_view_count():
    profile = analyse_schedule(
        [{"published_at": "2026-05-01T00:00:00Z", "views": "n/a"}, None], now=NOW)
    assert profile.videos_skipped == 1


# ── 7. the writer must be able to rebuild the key the learner writes ────────

def test_the_writers_chain_contains_the_key_the_learner_writes():
    """The defect: `resolve_competitor_playbook` fell back to using the BRIEF as
    the channel, and TopicBrief carried none of the scope fields — so the
    learner's key was unreachable at every level of the chain and the writer
    silently borrowed the niche-wide playbook. That is §4.2's failure, restored
    by a field-name mismatch between the write path and the read path."""
    channel = ChannelProfile(
        channel_id="fin_retirement_us", name="x", niche=Niche.FINANCE,
        market=Market.US, audience_segment="55plus_preretiree",
        content_format="longform_narration")
    brief = TopicBrief(title="T", niche=Niche.FINANCE, market=Market.US,
                       channel_id="fin_retirement_us",
                       **TopicBrief.scope_fields_from_channel(channel))

    written = scope_key(channel)
    assert written in [key for _level, key in fallback_chain(brief)]
    assert fallback_chain(brief)[0][1] == written


def test_two_niches_cannot_collide_on_the_most_specific_key():
    """With `channel_id` unset — which `ChannelArchitectAgent` does — every
    dimension but market fell back to `*`, so finance and health produced the
    identical "exact" key and the borrowed row was reported as an exact match."""
    finance = TopicBrief(title="A", niche=Niche.FINANCE, market=Market.US)
    health = TopicBrief(title="B", niche=Niche.HEALTH, market=Market.US)
    assert scope_key(finance) != scope_key(health)


def test_the_writer_reaches_the_scoped_row_instead_of_the_niche_row(monkeypatch):
    channel = ChannelProfile(
        channel_id="fin_retirement_us", name="x", niche=Niche.FINANCE,
        market=Market.US, audience_segment="55plus_preretiree",
        content_format="longform_narration")
    brief = TopicBrief(title="T", niche=Niche.FINANCE, market=Market.US,
                       channel_id="fin_retirement_us",
                       **TopicBrief.scope_fields_from_channel(channel))
    specific = scope_key(channel)

    class _Row:
        cohort_meta = "{}"

        def __init__(self, text):
            self.title_playbook = self.thumbnail_playbook = self.script_playbook = text

    vault = {specific: _Row("SCOPED"), "finance": _Row("NICHE WIDE")}
    tried: list[str] = []

    def _load(scope, **kw):
        tried.append(scope)
        return vault.get(scope)

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _load)
    writer_mod.resolve_competitor_playbook(brief)
    assert tried == [specific]        # the niche row is never consulted


# ── 9. calibration must not be unblocked by a garbled revision field ────────

def _row(v1, v2, revision, *, source="youtube_competitor"):
    row = {"total_v1": v1, "total_v2": v2, "source": source,
           "trend_momentum": v1 % 30, "gap_score_v1": 30.0, "gap_score": 12.0,
           "labelled": "good"}
    if revision is not _MISSING:
        row["v2_revision"] = revision
    return row


_MISSING = object()


@pytest.mark.parametrize("garbage", ["v2", None, [2], {}, "n/a"])
def test_an_unparseable_revision_costs_the_row_instead_of_reading_as_revision_one(garbage):
    """Reproduced: every shape `_num` rejects collapsed to revision 1, so a
    truncated `v2_revision` on precisely the revision-2 rows turned "do NOT
    promote" into a green light — and, uniquely among fields, emitted no note
    and cost no row."""
    rows = ([_row(70 + i * 0.1, 60 + i * 0.1, 1) for i in range(40)]
            + [_row(70 + i * 0.1, 59 + i * 0.1, garbage) for i in range(40)])
    report = summarize(rows)
    assert report.dropped_rows == 40
    assert report.ready_to_promote is False
    assert any("dropped" in n for n in report.notes)


def test_a_genuinely_absent_revision_field_still_reads_as_revision_one():
    """Rows harvested before the field existed WERE revision 1. That default is
    correct; applying it to garbage was not."""
    rows = [_row(70.0, 60.0, _MISSING)]
    assert summarize(rows).v2_revisions == {1}
    assert summarize(rows).dropped_rows == 0


@pytest.mark.parametrize("shape", [(1, 2), ("1", "2"), (1.0, 2.0)])
def test_a_mixed_revision_corpus_can_never_promote(shape):
    older, newer = shape
    rows = ([_row(70 + i * 0.1, 60 + i * 0.1, older) for i in range(40)]
            + [_row(70 + i * 0.1, 59 + i * 0.1, newer) for i in range(40)])
    report = summarize(rows)
    assert report.single_revision is False
    assert report.ready_to_promote is False


# ── review round 2 (external): three majors, reproduced ─────────────────────

def test_a_malformed_reply_count_on_a_QUESTION_does_not_abort_comment_intel():
    """The first malformed-row test walked past this: `reply_count` is only read
    inside the question branch, and none of its rows was a question. `like_count`
    had been hardened and `reply_count` had not."""
    rows = [{"comment_id": "q", "thread_id": "q", "text": "How do I roll this over?",
             "like_count": 5, "is_reply": False, "reply_count": "n/a"}]
    intel = analyse_comments(rows)          # must not raise
    assert [q["comment_id"] for q in intel.unanswered_questions] == ["q"]


@pytest.mark.parametrize("bad", ["n/a", None, float("inf"), float("nan"), [1], -3])
def test_every_count_on_a_comment_row_is_coerced_the_same_way(bad):
    rows = [{"comment_id": "q", "thread_id": "q", "text": "Why is that?",
             "like_count": bad, "is_reply": False, "reply_count": bad}]
    intel = analyse_comments(rows)
    assert all(q["like_count"] >= 0 for q in intel.unanswered_questions)


def test_an_infinite_view_count_cannot_produce_an_infinite_slot_ranking():
    """`_num` rejected NaN and accepted infinity, so `views="1e400"` produced
    `median_views_per_day = inf` — a slot that out-ranks every real slot
    forever, in the report whose whole job is to say when to publish."""
    videos = [{"published_at": (NOW - timedelta(days=7 * i)).isoformat(),
               "views": "1e400" if i == 1 else 10_000}
              for i in range(1, 9)]
    profile = analyse_schedule(videos, now=NOW)
    for row in profile.slot_performance:
        assert row["median_views_per_day"] == row["median_views_per_day"]   # not NaN
        assert row["median_views_per_day"] not in (float("inf"), float("-inf"))
