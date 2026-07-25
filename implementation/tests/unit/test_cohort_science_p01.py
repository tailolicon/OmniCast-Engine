"""P0.1 group 2 — cohort science (docs/HANDOFF_MASTER.md §5).

Five changes were handed over as "must not be done halfway", and each of these
tests fails if its change is reverted INDEPENDENTLY. That property is the point:
the most expensive bug of the previous session was a rule that no test could
falsify, so an audit reverted both halves of it with the suite still green.

  1. winner selection on views/day — AND the median in the same unit
  2. comparability per pair, not per cohort
  3. a cap on winners per channel
  4. the winner->control mapping survives into the prompt
  5. title format is controlled for, via the existing deterministic classifier
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from omnicast.analytics import competitor_intel as ci
from omnicast.analytics.cohort import (
    MIN_SETTLED_AGE_DAYS,
    select_cohort,
)
from omnicast.shared.title_patterns import classify_title, formats_match

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _v(vid, views, age, *, minutes=15.0, title=None, published=None):
    """A video `age` days old. Age is explicit because every rule here is
    about age-normalisation, and a hard-coded date string hides that."""
    if published is None:
        published = (NOW - timedelta(days=age)).isoformat().replace("+00:00", "Z")
    return {
        "video_id": vid,
        "title": title or f"title {vid}",
        "views": views,
        "duration_minutes": minutes,
        "published_at": published,
        "engagement_rate": 0.03,
        "thumbnail_url": f"https://img/{vid}.jpg",
    }


# ── 1. velocity on BOTH sides of the ratio ───────────────────────────────────

def test_winner_selection_uses_velocity_on_both_sides_of_the_ratio():
    """The old giant loses; the recent breakout wins.

    Two failure modes are pinned at once:

      * volume on both sides (the original bug) would elect `old_giant`, whose
        million views are two years of accumulation, and reject `recent_break`;
      * velocity in the numerator against a VOLUME median (the tempting half
        migration) divides a per-day rate by a lifetime total, so every ratio
        collapses towards zero and NOBODY is a winner.

    Only a consistently per-day ratio produces exactly one winner here.
    """
    cohort = select_cohort(
        {
            "c": [
                _v("old_giant", 1_000_000, 730),    # 1_370/day
                _v("steady_a", 100_000, 181),       #   552/day
                _v("steady_b", 90_000, 150),        #   600/day
                _v("recent_break", 90_000, 30),     # 3_000/day
            ]
        },
        now=NOW,
    )
    assert [w.video_id for w in cohort.winners] == ["recent_break"]
    # And the ratio is dimensionless again: ~3x the channel's median velocity,
    # not the ~0.03 a mixed-unit division would produce.
    assert cohort.winners[0].outlier_ratio > 2.0


def test_a_video_too_young_to_have_settled_cannot_be_a_winner():
    """Velocity's own bias, fenced.

    Days 0-2 of a video's life are its recommendation surge: views/day is at its
    lifetime maximum for reasons that have nothing to do with the title or the
    thumbnail. Without the fence, migrating to velocity would have quietly
    redefined "winner" as "newest", which is a different bias, not fewer."""
    cohort = select_cohort(
        {
            "c": [
                _v("s1", 10_000, 100),
                _v("s2", 12_000, 110),
                _v("s3", 11_000, 120),
                _v("fresh", 5_000, 2),  # 2_500/day — would dominate every median
            ]
        },
        now=NOW,
    )
    assert cohort.winners == []
    assert any("younger than" in n for n in cohort.notes)
    assert MIN_SETTLED_AGE_DAYS >= 1.0


def test_a_video_with_no_usable_timestamp_is_dropped_not_treated_as_new():
    """`_age_days` used to return 0.0 for an unparseable date, and the velocity
    floor then turned that into "published today" — the single most flattering
    reading available."""
    cohort = select_cohort(
        {
            "c": [
                _v("s1", 10_000, 100),
                _v("s2", 12_000, 110),
                _v("s3", 11_000, 120),
                _v("undated", 900_000, 0, published=""),
            ]
        },
        now=NOW,
    )
    assert "undated" not in [w.video_id for w in cohort.winners]
    assert any("timestamp" in n for n in cohort.notes)


# ── 2. comparability is a property of a pair ─────────────────────────────────

def _partially_controlled_cohort():
    """Two winners on one channel; only the 15-minute one can be matched.

    The 60-minute winner has no sibling within the duration window, which is
    exactly how partial coverage arises in real competitor sets."""
    return select_cohort(
        {
            "c": [
                _v("w_short", 100_000, 85, minutes=15),
                _v("w_long", 95_000, 83, minutes=60),
                _v("ctl", 12_000, 81, minutes=14),
                _v("s1", 10_000, 90, minutes=15),
                _v("s2", 9_000, 95, minutes=16),
                _v("filler", 8_000, 100, minutes=15),
            ]
        },
        now=NOW,
    )


def test_one_control_across_many_winners_is_not_a_controlled_cohort():
    """The reported bug: 12 winners + 1 control still read `is_comparable=True`,
    so eleven uncontrolled observations reached the writer as verified rules."""
    cohort = _partially_controlled_cohort()
    assert len(cohort.winners) == 2
    assert len(cohort.controls) == 1
    assert cohort.is_comparable is False
    assert cohort.comparability == "partial"
    assert cohort.control_coverage == pytest.approx(0.5)
    assert [w.video_id for w in cohort.matched_winners] == ["w_short"]
    assert [w.video_id for w in cohort.unmatched_winners] == ["w_long"]
    assert len(cohort.matched_pairs) == 1


def test_full_coverage_still_reads_as_comparable():
    cohort = select_cohort(
        {"c": [_v("win", 50_000, 24), _v("a", 10_000, 24), _v("b", 10_000, 25)]},
        now=NOW,
    )
    assert cohort.comparability == "full"
    assert cohort.is_comparable is True
    assert cohort.control_coverage == pytest.approx(1.0)


def test_packet_reports_coverage_not_just_a_boolean():
    packet = _partially_controlled_cohort().as_packet()
    assert packet["comparability"] == "partial"
    assert packet["control_coverage"] == pytest.approx(0.5)
    assert packet["unmatched_winner_ids"] == ["w_long"]
    assert packet["selection"]["ratio_basis"] == "views_per_day"


# ── 3. no channel may own the cohort ─────────────────────────────────────────

def test_a_single_channel_cannot_supply_the_whole_cohort():
    """Five breakouts on one channel, capped at three.

    Uncapped, one prolific channel's house style becomes "the playbook" — the
    same survivorship failure the control group exists to prevent, re-entering
    through sampling instead of through scoring."""
    videos = [_v(f"big{i}", 200_000, 100 + i) for i in range(5)]
    videos += [_v(f"small{i}", 10_000, 100 + i) for i in range(9)]
    cohort = select_cohort({"c": videos}, now=NOW, max_winners=12)
    assert len(cohort.winners) == 3
    assert any("strongest" in n and "house style" in n for n in cohort.notes)


def test_the_cap_is_per_channel_not_global():
    """Three channels, three winners each — the global budget is untouched."""
    channels = {
        f"c{c}": [_v(f"c{c}big{i}", 200_000, 100 + i) for i in range(5)]
        + [_v(f"c{c}small{i}", 10_000, 100 + i) for i in range(9)]
        for c in range(3)
    }
    cohort = select_cohort(channels, now=NOW, max_winners=12)
    assert len(cohort.winners) == 9
    per_channel = {}
    for w in cohort.winners:
        per_channel[w.channel_id] = per_channel.get(w.channel_id, 0) + 1
    assert set(per_channel.values()) == {3}


# ── 5. title format is controlled for ────────────────────────────────────────

def test_title_classifier_moved_without_changing_its_answers():
    """The taxonomy moved out of youtube_scanner so cohort could use it; the
    scanner's own behaviour must be byte-identical."""
    from omnicast.discovery import youtube_scanner

    assert youtube_scanner._classify_title is classify_title
    assert classify_title("5 Mistakes You Should Avoid") == [
        "number", "second_person", "warning"]
    assert classify_title("A quiet market update") == ["statement"]


def test_format_matching_control_is_preferred_over_a_closer_mismatched_one():
    """Pairing a listicle winner against a plain statement control means the
    largest difference between the groups is one WE introduced."""
    cohort = select_cohort(
        {
            "c": [
                _v("win", 100_000, 85, title="5 Mistakes That Kill Your Portfolio"),
                _v("near_plain", 10_000, 84, title="A quiet market update"),
                _v("far_match", 10_000, 70, title="7 Habits You Should Avoid"),
                _v("filler1", 9_000, 90),
                _v("filler2", 8_000, 95),
            ]
        },
        now=NOW,
    )
    assert [c.video_id for c in cohort.controls] == ["far_match"]
    assert cohort.controls[0].format_matched is True


def test_a_mismatched_control_is_still_better_than_none_but_is_labelled():
    """A hard filter would trade a format confound for no control at all on
    almost every winner. The mismatch is recorded instead of hidden."""
    cohort = select_cohort(
        {
            "c": [
                _v("win", 100_000, 85, title="5 Mistakes That Kill Your Portfolio"),
                _v("plain_a", 10_000, 84, title="A quiet market update"),
                _v("plain_b", 9_000, 90, title="Weekly recap"),
                _v("plain_c", 8_000, 95, title="Another recap"),
            ]
        },
        now=NOW,
    )
    assert len(cohort.controls) == 1
    assert cohort.controls[0].format_matched is False
    assert any("different title format" in n for n in cohort.notes)
    assert cohort.controls[0].as_row()["format_matched"] is False


def test_formats_match_rejects_plain_vs_tagged_and_accepts_shared_shape():
    assert formats_match("Weekly recap", "Market update") is True
    assert formats_match("Weekly recap", "5 Mistakes") is False
    assert formats_match("5 Mistakes You Make", "7 Habits You Need") is True


# ── 4. the mapping survives into the prompts ─────────────────────────────────

class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, reply="PLAYBOOK"):
        self.reply = reply
        self.calls: list[dict] = []

    async def complete(self, system, messages, **kw):
        self.calls.append({"system": system, "user": messages[0]["content"]})
        return _FakeResponse(self.reply)


def test_title_prompt_keeps_the_pairing_and_the_channel():
    """Two flat lists let the model contrast group means across channels — the
    cross-channel comparison the whole cohort exists to prevent."""
    cohort = _partially_controlled_cohort()
    prompt = ci._labelled_titles(cohort)
    assert "PAIR 1 (channel c)" in prompt
    assert "WINNER" in prompt and "CONTROL" in prompt
    # The unmatched winner must be present but quarantined, not silently mixed
    # into the winner list where it would look like evidence.
    assert "UNCONTROLLED WINNERS" in prompt
    quarantine = prompt.split("UNCONTROLLED WINNERS", 1)[1]
    assert "title w_long" in quarantine
    assert "title w_short" not in quarantine


def test_partial_coverage_gets_its_own_stamp_not_a_silent_pass():
    """`full` and `partial` used to render identically. So did `partial` and
    `none` after comparability was tightened — both are lies, in opposite
    directions."""
    partial = ci._stamp("BODY", _partially_controlled_cohort())
    assert partial.startswith("[PARTIALLY CONTROLLED")
    assert "1 of 2 winners" in partial
    assert partial.endswith("BODY")

    none = select_cohort(
        {"c": [_v("win", 90_000, 24), _v("a", 10_000, 900), _v("b", 10_000, 930)]},
        now=NOW,
    )
    assert none.comparability == "none"
    assert ci._stamp("BODY", none).startswith("[UNCONTROLLED")


def test_thumbnail_urls_are_aligned_pair_by_pair():
    """Winner i and control i must be the same pair. Taking the first 5 of each
    list independently could describe entirely different channels while the
    legend claimed they were comparable."""
    cohort = select_cohort(
        {
            "a": [_v("a_win", 100_000, 85), _v("a_ctl", 10_000, 84),
                  _v("a_f1", 9_000, 90), _v("a_f2", 8_000, 95)],
            "b": [_v("b_win", 100_000, 85), _v("b_ctl", 10_000, 84),
                  _v("b_f1", 9_000, 90), _v("b_f2", 8_000, 95)],
        },
        now=NOW,
    )
    by_id = {v.video_id: {"thumbnail_url": f"https://img/{v.video_id}.jpg"}
             for v in cohort.winners + cohort.controls}
    winners, controls = ci._thumb_urls(cohort, by_id)
    assert len(winners) == len(controls) == 2
    for w_url, c_url in zip(winners, controls):
        assert w_url.split("/")[-1][0] == c_url.split("/")[-1][0]  # same channel


def test_a_pair_with_a_missing_thumbnail_is_dropped_whole():
    """Half a pair would put the two lists out of step, and every later index
    would be mislabelled."""
    cohort = select_cohort(
        {
            "a": [_v("a_win", 100_000, 85), _v("a_ctl", 10_000, 84),
                  _v("a_f1", 9_000, 90), _v("a_f2", 8_000, 95)],
            "b": [_v("b_win", 100_000, 85), _v("b_ctl", 10_000, 84),
                  _v("b_f1", 9_000, 90), _v("b_f2", 8_000, 95)],
        },
        now=NOW,
    )
    by_id = {v.video_id: {"thumbnail_url": f"https://img/{v.video_id}.jpg"}
             for v in cohort.winners + cohort.controls}
    by_id["a_ctl"] = {}  # control lost its thumbnail
    winners, controls = ci._thumb_urls(cohort, by_id)
    assert len(winners) == len(controls) == 1
    assert "b_win" in winners[0] and "b_ctl" in controls[0]


@pytest.mark.asyncio
async def test_script_sample_spends_its_budget_on_matched_winners_first(monkeypatch):
    """With a 1-video budget, sampling `winners[:1]` could burn it on a winner
    with nothing to contrast against and then report a 'contrast'."""
    from omnicast.analytics.transcript import Segment, Transcript

    cohort = _partially_controlled_cohort()
    # Force the uncontrolled winner to the front of `winners` so the old
    # top-of-list slice would pick it.
    cohort.winners.sort(key=lambda w: w.video_id != "w_long")
    assert cohort.winners[0].video_id == "w_long"

    seen: list[str] = []

    async def _fake_transcript(video_id, duration_minutes=0.0):
        seen.append(video_id)
        return Transcript(video_id=video_id, text="hello there", source="test",
                          segments=(Segment(0.0, "hello there", 1.0),))

    monkeypatch.setattr(ci, "_fetch_transcript_async", _fake_transcript)
    llm = _FakeLLM("SCRIPT")
    await ci._learn_scripts(llm, cohort, {}, top_n=1)
    assert "w_short" in seen and "ctl" in seen
    assert "w_long" not in seen
