"""P0 brief §15 — the competitor-intelligence items that were never started.

§4.2 content pillars, §4.4 comment analysis, §4.6 schedule analysis, §4.5 the
unified dossier. Each module's job is as much about REFUSING to answer as about
answering, so the refusals get as many tests as the happy paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from omnicast.analytics import dossier as dossier_mod
from omnicast.analytics.comment_intel import analyse_comments
from omnicast.analytics.dossier import (
    MEASURED,
    MISSING,
    WITHHELD,
    DossierField,
    build_dossier,
)
from omnicast.analytics.pillars import (
    UNCLASSIFIED,
    UNCONFIGURED,
    classify_pillar,
    load_pillars,
    suggest_pillars,
)
from omnicast.analytics.schedule import (
    MIN_VIDEOS_PER_SLOT,
    analyse_schedule,
)

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)

PILLAR_CONFIG = [
    {"id": "retirement", "name": "Retirement", "keywords": ["retirement", "pension", "401k"]},
    {"id": "tax", "name": "Tax", "keywords": ["tax", "irs", "deduction"]},
]


# ── §4.2 content pillars ────────────────────────────────────────────────────

def test_an_unconfigured_channel_gets_unconfigured_not_a_guess():
    """Guessing here is worse than abstaining: the pillar keys the playbook
    store, so a guess routes a channel to somebody else's playbook."""
    match = classify_pillar("Anything at all", "", [])
    assert match.pillar_id == UNCONFIGURED
    assert match.is_classified is False


def test_configured_but_unmatched_is_distinct_from_unconfigured():
    pillars = load_pillars(PILLAR_CONFIG)
    match = classify_pillar("A movie review", "", pillars)
    assert match.pillar_id == UNCLASSIFIED
    assert match.is_classified is False


def test_classification_returns_the_keywords_that_caused_it():
    pillars = load_pillars(PILLAR_CONFIG)
    match = classify_pillar("5 pension mistakes", "about retirement", pillars)
    assert match.pillar_id == "retirement"
    assert "title:pension" in match.evidence
    assert "description:retirement" in match.evidence


def test_a_title_keyword_outweighs_a_description_keyword():
    """A keyword in the description is often boilerplate — a standing channel
    blurb or an affiliate list — while a keyword in the title is the subject."""
    pillars = load_pillars(PILLAR_CONFIG)
    match = classify_pillar(
        "The tax trap nobody explains",
        "Subscribe for retirement and pension content every week",
        pillars,
    )
    assert match.pillar_id == "tax"
    assert "retirement" in match.alternatives


def test_ties_do_not_depend_on_config_file_ordering():
    forward = load_pillars(PILLAR_CONFIG)
    backward = load_pillars(list(reversed(PILLAR_CONFIG)))
    title = "Pension and tax explained"
    assert classify_pillar(title, "", forward).pillar_id == \
        classify_pillar(title, "", backward).pillar_id


def test_suggested_pillars_are_labelled_as_proposals():
    titles = ["retirement basics", "retirement income", "retirement taxes",
              "a one-off video"]
    suggestions = suggest_pillars(titles, min_count=3)
    assert suggestions
    assert all("proposal" in s["status"] for s in suggestions)


# ── §4.6 publishing schedule ────────────────────────────────────────────────

def _video(days_ago: float, hour: int, views: int = 10_000, title: str = "v"):
    stamp = (NOW - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    return {"title": title, "views": views,
            "published_at": stamp.isoformat().replace("+00:00", "Z")}


def test_schedule_measures_cadence_and_a_heatmap():
    videos = [_video(days_ago=7 * i, hour=14) for i in range(1, 9)]
    profile = analyse_schedule(videos, now=NOW)
    assert profile.videos_analysed == 8
    assert profile.median_gap_days == pytest.approx(7.0)
    assert profile.uploads_per_week == pytest.approx(1.14, abs=0.05)
    assert any(slot.endswith(" 14") for slot in profile.heatmap)


def test_a_slot_with_too_few_videos_is_never_ranked():
    """With 50 videos over 168 weekday-hour cells, the 'best' cell is normally a
    cell containing one lucky video."""
    videos = [_video(days_ago=7 * i, hour=14) for i in range(1, 9)]
    videos.append(_video(days_ago=3, hour=3, views=5_000_000))  # one huge outlier
    profile = analyse_schedule(videos, now=NOW)
    ranked = {row["slot_utc"] for row in profile.slot_performance}
    assert not any(slot.endswith(" 03") for slot in ranked)
    assert any("noise" in n for n in profile.notes)
    assert all(row["videos"] >= MIN_VIDEOS_PER_SLOT for row in profile.slot_performance)


def test_slot_performance_never_claims_causation():
    videos = [_video(days_ago=7 * i, hour=14) for i in range(1, 9)]
    data = analyse_schedule(videos, now=NOW).as_dict()
    assert data["causal"] is False
    assert "correlation only" in data["causal_note"].lower()


def test_hours_are_declared_as_utc_rather_than_quietly_shifted():
    data = analyse_schedule([_video(days_ago=7 * i, hour=14) for i in range(1, 9)],
                            now=NOW).as_dict()
    assert "UTC" in data["timezone_note"]


def test_undated_videos_are_excluded_and_counted():
    videos = [_video(days_ago=7 * i, hour=14) for i in range(1, 9)]
    videos.append({"title": "no date", "views": 1, "published_at": ""})
    profile = analyse_schedule(videos, now=NOW)
    assert profile.videos_skipped == 1
    assert profile.videos_analysed == 8


def test_cadence_is_withheld_on_too_few_videos():
    profile = analyse_schedule([_video(days_ago=7, hour=9),
                                _video(days_ago=14, hour=9)], now=NOW)
    assert profile.median_gap_days is None
    assert any("below the" in n for n in profile.notes)


def test_cadence_is_reported_per_pillar():
    videos = ([_video(days_ago=7 * i, hour=14, title="retirement") for i in range(1, 6)]
              + [_video(days_ago=30 * i, hour=9, title="tax") for i in range(1, 4)])
    profile = analyse_schedule(videos, now=NOW,
                               pillar_of=lambda v: v["title"])
    assert profile.pillar_cadence["retirement"]["videos"] == 5
    assert profile.pillar_cadence["tax"]["median_gap_days"] > \
        profile.pillar_cadence["retirement"]["median_gap_days"]


# ── §4.4 comments ───────────────────────────────────────────────────────────

def _comment(text, *, likes=0, is_reply=False, thread="t1", replies=0, cid="c1"):
    return {"comment_id": cid, "thread_id": thread, "text": text,
            "like_count": likes, "is_reply": is_reply, "reply_count": replies}


def test_signals_come_back_with_the_comment_that_produced_them():
    intel = analyse_comments([
        _comment("I don't understand the withdrawal order", cid="a"),
        _comment("This is misleading, the tax bracket is different", cid="b"),
        _comment("Please make a video about annuities", cid="c"),
    ])
    names = {s.name for s in intel.signals}
    assert {"confusion", "objection", "sequel_request"} <= names
    assert intel.signal("confusion").examples


def test_a_popular_comment_is_not_one_voice():
    """One objection with 400 likes and forty quiet ones are different
    situations; a single count cannot say which you are looking at."""
    intel = analyse_comments([
        _comment("This is wrong", likes=400, cid="a", thread="t1"),
        _comment("I don't understand", likes=0, cid="b", thread="t2"),
    ])
    objection = intel.signal("objection")
    assert objection.comments == 1
    assert objection.weighted == 401


def test_unanswered_questions_are_separated_from_answered_ones():
    intel = analyse_comments([
        _comment("How do I roll this over?", cid="q1", thread="t1", replies=0),
        _comment("What about my spouse?", cid="q2", thread="t2", replies=1),
        _comment("here is the answer", cid="r1", thread="t2", is_reply=True),
    ])
    unanswered = [q["comment_id"] for q in intel.unanswered_questions]
    assert unanswered == ["q1"]


def test_a_failed_fetch_is_not_reported_as_a_quiet_audience():
    class _Fetch(list):
        status = "comments_disabled"

    intel = analyse_comments(_Fetch())
    assert intel.sample["status"] == "comments_disabled"
    assert any("not succeed" in n for n in intel.notes)
    assert intel.signals == []


def test_silence_is_explicitly_not_agreement():
    intel = analyse_comments([_comment("nice"), _comment("👍")])
    assert intel.signals == []
    assert any("NOT evidence of" in n for n in intel.notes)


def test_the_sample_carries_its_own_caveat():
    intel = analyse_comments([_comment("I don't understand")])
    assert "self-selected" in intel.sample["caveat"]


def test_timestamps_viewers_quote_are_surfaced():
    """A timestamp says WHERE in the video something landed — the single most
    actionable thing a comment section contains."""
    intel = analyse_comments([
        _comment("the part at 4:12 finally made it click", likes=20, cid="a"),
        _comment("4:12 is gold", likes=5, cid="b", thread="t2"),
    ])
    assert intel.referenced_timestamps[0]["mm_ss"] == "4:12"


# ── §4.5 the dossier ────────────────────────────────────────────────────────

def test_every_field_declares_measured_inferred_assumed_or_missing():
    dossier = build_dossier(scope={"niche": "finance"})
    assert dossier.fields
    for entry in dossier.fields:
        assert entry.status in dossier_mod.STATUSES


def test_an_unknown_status_is_rejected_rather_than_stored():
    with pytest.raises(ValueError):
        DossierField(name="x", status="probably")


def test_competitor_analytics_we_cannot_have_are_listed_as_missing():
    """§4.7: public metrics must never be dressed up as internal analytics.
    Leaving them out entirely is the same failure — the reader cannot notice an
    absence."""
    dossier = build_dossier(scope={})
    for name in ("impressions", "click_through_rate", "retention_curve",
                 "average_view_duration", "revenue"):
        entry = dossier.get(name)
        assert entry is not None and entry.status == MISSING


def test_a_recommendation_names_the_field_it_rests_on_and_is_graded_on_it():
    dossier = build_dossier(scope={})
    rec = next(r for r in dossier.recommendations if "title formulas" in r.action)
    assert rec.supported_by == ["title_playbook", "cohort"]
    assert rec.strength == "unsupported"
    assert "title_playbook is missing" in rec.rationale


def test_recommendations_strengthen_when_the_evidence_is_there():
    videos = [_video(days_ago=7 * i, hour=14) for i in range(1, 9)]
    schedule = analyse_schedule(videos, now=NOW)
    dossier = build_dossier(scope={}, schedule=schedule)
    rec = next(r for r in dossier.recommendations if "habitual publishing" in r.action)
    assert rec.strength == "supported"


def test_a_thin_sample_is_withheld_not_missing():
    """`missing` is an outage to fix; `withheld` is a sample to grow. Collapsing
    them sends the operator after the wrong problem."""
    videos = [_video(days_ago=7 * i, hour=(i * 3) % 24) for i in range(1, 9)]
    dossier = build_dossier(scope={}, schedule=analyse_schedule(videos, now=NOW))
    assert dossier.get("slot_performance").status == WITHHELD
    assert dossier.get("publishing_schedule").status == MEASURED


def test_coverage_reflects_how_much_was_actually_measured():
    empty = build_dossier(scope={})
    assert empty.coverage == 0.0
    populated = build_dossier(
        scope={},
        schedule=analyse_schedule([_video(days_ago=7 * i, hour=14)
                                   for i in range(1, 9)], now=NOW),
        comments=analyse_comments([_comment("I don't understand")]),
    )
    assert populated.coverage > empty.coverage


def test_an_uncontrolled_playbook_is_recorded_with_low_confidence():
    dossier = build_dossier(scope={}, playbooks={
        "title_playbook": "[UNCONTROLLED — no controls]\n\nUse numbers.",
    })
    entry = dossier.get("title_playbook")
    assert entry.confidence == 0.3
    assert "not verified" in entry.note
