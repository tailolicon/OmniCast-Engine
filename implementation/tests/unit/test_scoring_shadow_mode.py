"""Scoring v2 is contained until it is calibrated (P0.1 containment).

The risk being contained: v2 removed a double-count that was inflating
YouTube-sourced topics, and the size of the correction depends on the
competitor channel's median views. At outlier ratio 8 the same topic scores
59.5 with a 2M-median incumbent and 75.5 with a 20k-median one — approve or
review, decided by a dimension nobody has calibrated. So v1 keeps deciding
until the shadow corpus says otherwise."""

from __future__ import annotations

import pytest

from omnicast.discovery.models import TopicRawData
from omnicast.discovery.scorer import TopicScorer
from omnicast.discovery.scoring_calibration import (
    DECOUPLING_CORR_LIMIT,
    MIN_ROWS_FOR_VERDICT,
    action_of,
    pearson,
    shadow_row,
    summarize,
)
from omnicast.models.enums import Market, Niche, TopicSource


def _raw(source=TopicSource.YOUTUBE_COMPETITOR, market=Market.US, **metrics):
    return TopicRawData(title="T", source=source, niche=Niche.FINANCE,
                        market=market, raw_metrics=metrics)


# ── Containment ──────────────────────────────────────────────────────────────

async def test_shadow_is_the_default_and_v1_decides():
    """Nothing changes what gets produced until somebody looks at the numbers."""
    scorer = TopicScorer(scoring_mode="shadow")
    result = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=2_000_000))
    # v1: 24 trend + 35 gap + 15 rpm + 5 novelty = 79 → approve
    #
    # v2 REVISION 2 (brief §3.1) completed the opportunity formula, so the
    # dimensions were rescaled into a budget that also holds audience fit and
    # repeatability, and a risk penalty is subtracted:
    #   24*(25/30) + 8*(20/25) + 15*(15/20) + 5*(8/10) + 7.5*(12/15)
    #   + 5 audience (unconfigured → neutral) + 5 repeatability - 0 risk
    #   = 59.65 → review
    # The verdict is the same as under revision 1 (59.5); only the arithmetic
    # behind it changed.
    assert result.total_score_v1 == 79.0
    assert result.total_score_v2 == 59.65
    assert result.scoring_version == "v1"
    assert result.auto_approved is True          # v1 decided
    assert result.total_score == 79.0            # and total_score agrees with the flag


async def test_both_scores_ride_along_on_every_topic():
    """Same outlier ratio, two competitor sizes, two different verdicts from v2 —
    which is exactly why v2 is not allowed to decide yet."""
    scorer = TopicScorer(scoring_mode="shadow")
    small = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=20_000))
    big = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=2_000_000))

    assert small.total_score_v2 == 69.25          # v2 revision 2 budget
    assert small.shadow_delta == round(69.25 - 79.0, 2)

    assert big.total_score_v2 == 59.65
    assert big.shadow_disagrees is True          # approve under v1, review under v2

    # REVISION 2 MOVED THIS ONE. Under revision 1 the small-channel topic scored
    # 71.5 and agreed with v1; the rescale that made room for audience fit and
    # repeatability puts it at 69.25 — a quarter of a point under the approve
    # line. Nothing about the topic changed.
    #
    # That is not a bug in either generation, it is the evidence for the warning
    # already on the record: the 70/50 thresholds were set for v1's scale and
    # have never been recalibrated. Do not "fix" this by nudging a weight until
    # the number goes back over 70 — that is fitting the scorer to one test
    # fixture. It gets fixed by calibrating the boundary on the shadow corpus.
    assert small.shadow_disagrees is True
    assert 69.0 < small.total_score_v2 < 70.0
    # v1 cannot tell these two topics apart at all — that is the bug v2 fixes.
    assert small.total_score_v1 == big.total_score_v1


async def test_promoting_v2_makes_v2_decide():
    scorer = TopicScorer(scoring_mode="v2")
    result = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=2_000_000))
    assert result.scoring_version == "v2"
    assert result.total_score == 59.65
    assert result.auto_approved is False
    assert result.needs_review is True


async def test_v1_mode_never_computes_a_v2_decision():
    scorer = TopicScorer(scoring_mode="v1")
    result = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=20_000))
    assert result.scoring_version == "v1"
    assert result.total_score == result.total_score_v1
    # v2 is still recorded — containment is not the same as blindness.
    assert result.total_score_v2 > 0


async def test_shadow_note_is_visible_on_the_topic():
    scorer = TopicScorer(scoring_mode="shadow")
    result = await scorer.score(_raw(outlier_ratio=8.0))
    assert any("v1 is deciding" in n for n in result.score_notes)


async def test_flags_always_agree_with_total_score():
    """A topic whose flag says approve but whose score says review is the exact
    kind of quiet inconsistency this whole change is trying to remove."""
    for mode in ("v1", "shadow", "v2"):
        scorer = TopicScorer(scoring_mode=mode)
        for median in (20_000, 2_000_000):
            r = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=median))
            assert r.auto_approved == (r.total_score >= 70)
            assert r.needs_review == (50 <= r.total_score < 70)


def test_v1_gap_is_preserved_verbatim():
    assert TopicScorer._calc_gap_score_v1(_raw(outlier_ratio=8.0)) == 35
    assert TopicScorer._calc_gap_score_v1(_raw(outlier_ratio=4.0)) == 28
    assert TopicScorer._calc_gap_score_v1(_raw(outlier_ratio=2.5)) == 20
    assert TopicScorer._calc_gap_score_v1(_raw(source=TopicSource.PODCAST)) == 35


# ── Calibration report ───────────────────────────────────────────────────────

def _row(trend, gap_v1, gap_v2, v1, v2, source="TopicSource.YOUTUBE_COMPETITOR"):
    # Source matters: the decoupling verdict is judged on youtube_competitor
    # rows alone, because that is the only source where gap ever read the same
    # variable as trend. Pooling other sources in would let a corpus of
    # constant-gap RSS rows dilute a real coupling down under the limit.
    return {"trend_momentum": trend, "gap_score_v1": gap_v1, "gap_score": gap_v2,
            "total_v1": v1, "total_v2": v2, "source": source}


def test_empty_corpus_refuses_to_conclude():
    report = summarize([])
    assert report.rows == 0
    assert report.decoupled is None
    assert report.ready_to_promote is False


def test_thin_corpus_says_unknown_not_no():
    """'Not enough evidence' and 'evidence says no' are different answers."""
    report = summarize([_row(24, 35, 12, 79, 63) for _ in range(5)])
    assert report.decoupled is None
    assert any("need" in n for n in report.notes)


def test_routing_impact_is_counted_in_lanes_not_just_averages():
    rows = [_row(24, 35, 12, 79, 63) for _ in range(30)]      # approve → review
    rows += [_row(10, 20, 12, 55, 52) for _ in range(30)]     # review → review
    report = summarize(rows)
    assert report.transitions["approve"]["review"] == 30
    assert report.transitions["review"]["review"] == 30
    assert report.changed_lane == 30
    assert report.changed_lane_pct == 50.0
    assert any("change lane" in n for n in report.notes)


def test_decoupling_is_proven_by_correlation_not_asserted():
    """v1's gap was a function of the same ratio as trend, so it correlates
    almost perfectly. v2's must not."""
    rows = []
    for i in range(60):
        ratio = 2.5 + i * 0.1
        trend = min(ratio * 3, 30)
        gap_v1 = 35 if ratio >= 8 else 28 if ratio >= 4 else 20
        gap_v2 = 12 + (i % 5) - 2          # unrelated to ratio
        rows.append(_row(trend, gap_v1, gap_v2, trend + gap_v1 + 20,
                         trend + gap_v2 + 27.5))
    report = summarize(rows)
    assert report.corr_trend_gap_v1_youtube > 0.8
    assert abs(report.corr_trend_gap_v2_youtube) <= DECOUPLING_CORR_LIMIT
    assert report.decoupled is True
    assert report.coupling_reduced is True
    # Decoupled is necessary but NOT sufficient: this corpus also moves 26.7% of
    # topics between lanes, which is a content-calendar decision, not a metric.
    assert report.ready_to_promote is False


def test_promotion_needs_decoupling_AND_a_calm_routing_shift():
    rows = []
    for i in range(60):
        ratio = 2.5 + i * 0.1
        trend = min(ratio * 3, 30)
        gap_v1 = 35 if ratio >= 8 else 28 if ratio >= 4 else 20
        gap_v2 = 12 + (i % 5) - 2
        # Same lane under both generations for all but a couple of rows.
        v1 = 55.0 if i % 30 else 72.0
        rows.append(_row(trend, gap_v1, gap_v2, v1, v1 - 1))
    report = summarize(rows)
    assert report.decoupled is True
    assert report.changed_lane_pct < 25.0
    # Stable, but a corpus of pure scores cannot show v2 picks BETTER topics.
    assert report.migration_is_stable is True
    assert report.has_quality_evidence is False
    assert report.ready_to_promote is False
    assert any("not that it chooses" in n for n in report.notes)


def test_promotion_needs_quality_evidence_not_just_stability():
    rows = []
    for i in range(60):
        ratio = 2.5 + i * 0.1
        trend = min(ratio * 3, 30)
        gap_v1 = 35 if ratio >= 8 else 28 if ratio >= 4 else 20
        v1 = 55.0 if i % 30 else 72.0
        row = _row(trend, gap_v1, 12 + (i % 5) - 2, v1, v1 - 1)
        row["outcome"] = {"views_7d": 1000 + i}   # what the video actually did
        rows.append(row)
    report = summarize(rows)
    assert report.labelled_rows == 60
    assert report.has_quality_evidence is True
    assert report.ready_to_promote is True


def test_double_count_returning_through_channel_size_is_caught():
    """The failure this report exists for: gap no longer reads outlier_ratio,
    but still tracks it because both load on channel size."""
    rows = []
    for i in range(60):
        trend = 6 + i * 0.4
        gap_v2 = 8 + i * 0.25          # rises in lockstep with trend
        rows.append(_row(trend, 20, gap_v2, trend + 20 + 20, trend + gap_v2 + 27.5))
    report = summarize(rows)
    assert report.corr_trend_gap_v2_youtube > DECOUPLING_CORR_LIMIT
    assert report.decoupled is False
    assert report.ready_to_promote is False
    assert any("double-count likely returned" in n for n in report.notes)


def test_constant_dimension_reports_undefined_not_zero():
    rows = [_row(24, 35, 12, 79, 63) for _ in range(MIN_ROWS_FOR_VERDICT + 5)]
    report = summarize(rows)
    assert report.corr_trend_gap_v2 is None
    assert report.corr_trend_gap_v2_youtube is None
    assert report.decoupled is None
    assert any("undefined" in n for n in report.notes)


def test_verdict_cannot_be_diluted_by_other_sources():
    """The attack this guards against: real coupling on YouTube rows, hidden
    under a pile of constant-gap RSS rows, pooling the correlation to ~0."""
    coupled = [_row(6 + i * 0.4, 20, 8 + i * 0.25, 60, 55) for i in range(20)]
    filler = [_row(10, 20, 12, 60, 55, source="TopicSource.NEWS_RSS")
              for _ in range(200)]
    report = summarize(coupled + filler)
    assert report.youtube_rows == 20
    # Pooled correlation looks innocent; the youtube-only one does not.
    assert abs(report.corr_trend_gap_v2) < abs(report.corr_trend_gap_v2_youtube)
    assert report.ready_to_promote is False


def test_rows_without_scores_are_dropped_and_declared():
    """Defaulting a missing total to 0.0 turned a scoreless corpus into
    '0% changed lane, ready to promote'."""
    report = summarize([{"trend_momentum": 1, "gap_score": 2} for _ in range(60)])
    assert report.usable_rows == 0
    assert report.dropped_rows == 60
    assert report.ready_to_promote is False
    assert any("nothing to compare" in n for n in report.notes)


def test_big_routing_shift_blocks_promotion_even_when_decoupled():
    rows = []
    for i in range(60):
        trend = 6 + (i % 7) * 2
        gap_v2 = 12 + (i % 5) - 2
        # Every row crosses the approve/review line.
        rows.append(_row(trend, 35, gap_v2, 79, 60))
    report = summarize(rows)
    assert report.changed_lane_pct == 100.0
    assert report.ready_to_promote is False
    assert any("re-plan" in n for n in report.notes)


def test_delta_spread_is_reported_not_just_the_mean():
    """A mean delta of -8 hides the fact that the change ranges -20..+4."""
    rows = [_row(24, 35, 8, 79, 59) for _ in range(30)]
    rows += [_row(24, 35, 24, 79, 75) for _ in range(30)]
    report = summarize(rows)
    assert report.p10_delta < report.median_delta < report.p90_delta


@pytest.mark.parametrize("total,lane", [(70, "approve"), (69.9, "review"),
                                        (50, "review"), (49.9, "discard")])
def test_lane_boundaries(total, lane):
    assert action_of(total) == lane


def test_pearson_is_none_when_undefined():
    assert pearson([1.0, 2.0], [1.0, 2.0]) is None       # too few points
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None  # constant series


async def test_shadow_row_carries_what_calibration_needs():
    scorer = TopicScorer(scoring_mode="shadow")
    scored = await scorer.score(_raw(outlier_ratio=8.0, channel_median_views=20_000))
    row = shadow_row(scored)
    for key in ("trend_momentum", "gap_score", "gap_score_v1", "total_v1",
                "total_v2", "outlier_ratio", "channel_median_views"):
        assert key in row
    assert row["outlier_ratio"] == 8.0
    assert row["channel_median_views"] == 20_000
