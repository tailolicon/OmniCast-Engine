"""Cohort labelling — the layer an audit attacks first.

The first pass labelled winners by RAW VIEWS against the channel median, which
rewards age, mixes Shorts with long-form and pairs nothing. These tests pin the
replacement: velocity on settled videos, split by format, matched inside a
channel.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from omnicast.analytics.cohort_labels import (
    MIN_AGE_DAYS,
    cohort_report,
    label_corpus,
    match_pairs,
)

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def _v(vid, views, days_old, minutes=10.0, title=""):
    return {"video_id": vid, "views": views, "title": title or vid,
            "duration_minutes": minutes,
            "published_at": (NOW - timedelta(days=days_old)).isoformat()}


def test_velocity_not_raw_views_decides_the_label():
    """An old video with more total views can still be the slower one."""
    raw = {"@ch": [
        _v("old_big", 100_000, 1000),      # 100/day
        _v("new_fast", 30_000, 30),        # 1000/day
        _v("mid1", 20_000, 100),           # 200/day
        _v("mid2", 18_000, 100),           # 180/day
        _v("slow", 5_000, 100),            # 50/day
    ]}
    rows = {v.video_id: v for v in label_corpus(raw, now=NOW)}
    assert rows["new_fast"].role == "winner"
    assert rows["old_big"].role == "control"   # biggest view count, slowest pace


def test_unsettled_videos_are_not_labelled():
    raw = {"@ch": [_v(f"s{i}", 10_000, 200) for i in range(5)]
           + [_v("fresh", 50, days_old=MIN_AGE_DAYS - 1)]}
    rows = {v.video_id: v for v in label_corpus(raw, now=NOW)}
    assert rows["fresh"].role == ""
    assert "unsettled" in rows["fresh"].note


def test_shorts_and_long_form_are_labelled_in_separate_pools():
    """A 45-second Short must never be a 'control' for a 15-minute explainer."""
    raw = {"@ch": [
        *[_v(f"long{i}", 10_000, 100, minutes=12) for i in range(4)],
        *[_v(f"short{i}", 200_000, 100, minutes=0.75) for i in range(4)],
        _v("long_fast", 60_000, 100, minutes=12),
    ]}
    rows = {v.video_id: v for v in label_corpus(raw, now=NOW)}
    assert rows["long_fast"].role == "winner"          # judged against long-form
    assert rows["long_fast"].fmt == "long"
    assert all(rows[f"short{i}"].fmt == "short" for i in range(4))
    # the huge Shorts velocity must not make every long video a "control"
    assert rows["long0"].role in ("control", "")


def test_matched_pairs_stay_inside_channel_and_format():
    # A pool needs real spread: videos sitting exactly ON the channel median
    # are mid-band by design (neither winner nor control), so a fixture of
    # identical videos produces no pairs — as it should.
    raw = {
        "@a": [_v("a_mid1", 12_000, 100), _v("a_mid2", 11_000, 100),
               _v("a_slow1", 4_000, 100), _v("a_slow2", 3_000, 100),
               _v("a_win", 60_000, 100)],
        "@b": [_v("b_mid1", 12_000, 100), _v("b_mid2", 11_000, 100),
               _v("b_slow1", 4_000, 100), _v("b_slow2", 3_000, 100),
               _v("b_win", 60_000, 100)],
    }
    rows = label_corpus(raw, now=NOW)
    pairs = match_pairs(rows)
    by_id = {v.video_id: v for v in rows}
    assert pairs
    for winner_id, control_id in pairs:
        assert by_id[winner_id].channel == by_id[control_id].channel
        assert by_id[winner_id].fmt == by_id[control_id].fmt


def test_a_control_is_never_reused_across_winners():
    raw = {"@ch": [*[_v(f"w{i}", 90_000, 100) for i in range(3)],
                   *[_v(f"c{i}", 10_000, 100) for i in range(4)]]}
    rows = label_corpus(raw, now=NOW)
    pairs = match_pairs(rows)
    controls = [c for _w, c in pairs]
    assert len(controls) == len(set(controls))


def test_report_exposes_cohort_shape_for_the_auditor():
    raw = {"@ch": [_v("w1", 90_000, 100), _v("w2", 80_000, 100),
                   _v("mid", 12_000, 100),
                   _v("c1", 4_000, 100), _v("c2", 3_000, 100)]}
    rows = label_corpus(raw, now=NOW)
    match_pairs(rows)
    rep = cohort_report(rows)
    assert rep["videos"] == 5
    assert rep["winners"] >= 1 and rep["controls"] >= 1
    assert rep["matched_pairs"] >= 1
    assert rep["labelling"]["metric"] == "views/day"
    assert "@ch" in rep["by_channel"]


def test_tiny_pool_is_left_unlabelled_with_a_reason():
    raw = {"@ch": [_v("only1", 10_000, 100), _v("only2", 20_000, 100)]}
    rows = label_corpus(raw, now=NOW)
    assert all(v.role == "" for v in rows)
    assert all("too small" in v.note for v in rows)


def test_pair_gaps_are_capped_and_bad_matches_are_dropped():
    """Greedy nearest-neighbour once paired a 23-minute winner with a 6-minute
    control (114 days apart) and still called it 'matched'."""
    raw = {"@ch": [
        _v("w_long", 90_000, 100, minutes=23.0),
        _v("c_short", 4_000, 100, minutes=6.0),      # 17 min away — must not pair
        _v("mid", 12_000, 100, minutes=20.0),
        _v("c_far", 3_000, 220, minutes=23.0),       # 120 days away — must not pair
    ]}
    rows = label_corpus(raw, now=NOW)
    report: dict = {}
    pairs = match_pairs(rows, report=report)
    assert pairs == []
    assert report["dropped_winners"]
    assert "no control within" in rows[0].note or any(
        "unpaired" in (r.note or "") for r in rows)


def test_pair_within_the_ceilings_is_kept_with_its_gaps_recorded():
    raw = {"@ch": [
        _v("w", 90_000, 100, minutes=12.0),
        _v("c_ok", 4_000, 110, minutes=13.0),        # 1 min, 10 days
        _v("mid", 12_000, 100, minutes=12.0),
        _v("c_bad", 3_000, 100, minutes=30.0),
    ]}
    rows = label_corpus(raw, now=NOW)
    pairs = match_pairs(rows)
    assert pairs and pairs[0][1] == "c_ok"
    w = next(r for r in rows if r.video_id == "w")
    assert w.pair_duration_gap_min is not None and w.pair_duration_gap_min <= 6.0
    assert w.pair_age_gap_days is not None and w.pair_age_gap_days <= 60.0
    q = cohort_report(rows)["pair_quality"]
    assert q["max_duration_gap_min"] <= 6.0
    assert q["max_age_gap_days"] <= 60.0
