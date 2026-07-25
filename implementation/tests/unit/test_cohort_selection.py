"""Winner + matched-control cohort selection (strategic review §4.1, §4.8).

The review's falsifiable claim — verified in code — was that competitor_intel
learned from `sort(views)[:N]`, so playbooks came from big/old channels rather
than genuine breakouts, with no control group to separate "what won" from "what
this channel always does". These tests pin the replacement behaviour."""

from __future__ import annotations

from datetime import datetime, timezone

from omnicast.analytics.cohort import (
    CONTROL_MAX_DAYS_APART,
    Cohort,
    select_cohort,
    views_per_day,
)

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _v(vid, views, *, day="2026-07-01", minutes=15.0, title=None, channel_hint=""):
    return {
        "video_id": vid,
        "title": title or f"video {vid}",
        "views": views,
        "duration_minutes": minutes,
        "published_at": f"{day}T00:00:00Z",
        "engagement_rate": 0.03,
        "channel_hint": channel_hint,
    }


def test_small_channel_breakout_beats_big_channel_baseline():
    """The core fix: a 60k-view video on a 10k-median channel is a winner; a
    900k-view video on a 1M-median channel is not. Absolute-views sorting had
    this exactly backwards."""
    cohort = select_cohort(
        {
            "small": [_v("s1", 60_000), _v("s2", 10_000), _v("s3", 9_000), _v("s4", 11_000)],
            "big": [_v("b1", 900_000), _v("b2", 1_000_000), _v("b3", 1_100_000)],
        },
        now=NOW,
    )
    winner_ids = [w.video_id for w in cohort.winners]
    assert "s1" in winner_ids
    assert "b1" not in winner_ids
    assert all(w.outlier_ratio >= 2.0 for w in cohort.winners)


def test_every_winner_gets_a_matched_control_from_its_own_channel():
    cohort = select_cohort(
        {"c": [_v("win", 50_000), _v("ctl_a", 10_000), _v("ctl_b", 9_500), _v("ctl_c", 10_500)]},
        now=NOW,
    )
    assert len(cohort.winners) == 1
    assert len(cohort.controls) == 1
    control = cohort.controls[0]
    assert control.matched_to == "win"
    assert control.channel_id == "c"
    assert control.role == "control"
    assert cohort.is_comparable is True


def test_controls_must_be_ordinary_near_in_time_and_similar_length():
    """A near-breakout, a video from a different era, or a radically different
    runtime would each blur the contrast the cohort exists to measure."""
    cohort = select_cohort(
        {
            "c": [
                _v("win", 50_000, day="2026-07-01", minutes=15),
                _v("near_breakout", 14_000, day="2026-07-02", minutes=15),  # ratio too high
                _v("ancient", 10_000, day="2024-01-01", minutes=15),        # too far apart
                _v("short", 10_000, day="2026-07-03", minutes=2),           # wrong format length
                _v("good_ctl", 10_000, day="2026-07-05", minutes=14),
                _v("filler", 11_000, day="2026-06-20", minutes=16),
            ]
        },
        now=NOW,
    )
    picked = [c.video_id for c in cohort.controls]
    assert picked == ["good_ctl"]  # closest in time among valid candidates


def test_winner_without_a_valid_control_is_reported_not_hidden():
    """Silent truncation reads as coverage. A winner-only cohort must say so —
    downstream confidence depends on knowing there was nothing to compare."""
    cohort = select_cohort(
        {"c": [_v("win", 90_000, day="2026-07-01"), _v("a", 10_000, day="2020-01-01"),
               _v("b", 10_000, day="2020-02-01")]},
        now=NOW,
    )
    assert len(cohort.winners) == 1
    assert cohort.controls == []
    assert cohort.is_comparable is False
    assert any("no matched control" in n for n in cohort.notes)


def test_thin_channel_is_skipped_with_a_reason():
    cohort = select_cohort({"tiny": [_v("x", 100), _v("y", 50)]}, now=NOW)
    assert cohort.winners == []
    assert any("at least 3" in n for n in cohort.notes)


def test_views_per_day_normalises_age():
    """Age normalisation is the second half of the fix: an old giant and a
    fresh breakout are no longer the same evidence."""
    old = _v("old", 1_000_000, day="2024-07-25")
    fresh = _v("fresh", 100_000, day="2026-07-20")
    assert views_per_day(fresh, NOW) > views_per_day(old, NOW)


def test_a_control_is_never_reused_across_winners():
    cohort = select_cohort(
        {"c": [_v("w1", 50_000, day="2026-07-01"), _v("w2", 48_000, day="2026-07-02"),
               _v("c1", 10_000, day="2026-07-03"), _v("c2", 10_000, day="2026-07-04"),
               _v("c3", 9_000, day="2026-07-05")]},
        now=NOW,
    )
    ids = [c.video_id for c in cohort.controls]
    assert len(ids) == len(set(ids)) == 2


def test_packet_is_self_describing():
    cohort = select_cohort(
        {"c": [_v("win", 50_000), _v("a", 10_000), _v("b", 10_000)]}, now=NOW
    )
    packet = cohort.as_packet()
    assert packet["winner_count"] == 1
    assert packet["selection"]["winner_multiplier"] == 2.0
    assert packet["selection"]["control_max_days_apart"] == CONTROL_MAX_DAYS_APART
    assert "is_comparable" in packet


def test_empty_input_is_honest_not_silent():
    cohort: Cohort = select_cohort({}, now=NOW)
    assert cohort.winners == []
    assert any("no winner" in n for n in cohort.notes)
