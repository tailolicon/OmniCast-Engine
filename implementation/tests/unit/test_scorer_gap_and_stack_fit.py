"""Gap score decoupling + the stack-fit dimension (review §4, P0 item 4).

The verified bug: `outlier_ratio` fed BOTH `_calc_trend_momentum` (min(ratio*3,
30)) and `_calc_gap_score` (tiered 20/28/35). One measurement supplied up to 65
of 100 points, so a single YouTube outlier could auto-approve itself with no
other dimension agreeing — while the two dimensions are meant to answer opposite
questions (is there demand? / is the space already taken?).

These tests pin: gap is blind to outlier_ratio, gap responds to real saturation
evidence, unknown stays neutral, and stack fit can veto a topic we cannot make.
"""

from __future__ import annotations

import pytest

from omnicast.discovery.models import TopicRawData
from omnicast.discovery.scorer import (
    GAP_MAX,
    STACK_FIT_MAX,
    STACK_FIT_NEUTRAL,
    StackProfile,
    TopicScorer,
)
from omnicast.models.enums import Market, Niche, TopicSource


def _raw(source=TopicSource.YOUTUBE_COMPETITOR, market=Market.US,
         niche=Niche.FINANCE, title="Test Topic", **metrics):
    return TopicRawData(
        title=title, source=source, niche=niche, market=market, raw_metrics=metrics
    )


# ── The double-count itself ──────────────────────────────────────────────────

@pytest.mark.parametrize("ratio", [0.0, 2.5, 4.0, 8.0, 50.0])
def test_gap_score_is_blind_to_outlier_ratio(ratio):
    """The core fix. Whatever the outlier ratio, gap must not move — demand is
    trend_momentum's job and counting it twice is what broke the budget."""
    assert TopicScorer._calc_gap_score(_raw(outlier_ratio=ratio)) == 12


def test_outlier_alone_can_no_longer_auto_approve():
    """Before: trend 24 + gap 35 = 59 from ONE signal, plus RPM 15 = 74 → auto
    approved with nothing else agreeing.

    Asserted under scoring_mode="v2" because v2 is deliberately NOT the default
    yet — see test_default_mode_still_lets_v1_decide below."""
    import asyncio

    scorer = TopicScorer(scoring_mode="v2")
    topic = _raw(outlier_ratio=8.0)
    result = asyncio.run(scorer.score(topic))
    assert result.auto_approved is False
    # trend 24 + gap 12 + rpm 15 + novelty 5 + stack 7.5 = 63.5 → review, not approve
    assert result.needs_review is True


def test_default_mode_still_lets_v1_decide():
    """Containment: the v2 weights ship, but they do not get to change what is
    produced until the shadow corpus has been calibrated."""
    import asyncio

    result = asyncio.run(TopicScorer().score(_raw(outlier_ratio=8.0)))
    assert result.scoring_version == "v1"
    assert result.auto_approved is True     # v1's verdict, unchanged
    # v2's verdict, recorded not applied. Revision 2 rescaled the original
    # dimensions into a budget that also carries audience fit and repeatability
    # (both neutral here — nothing is configured) minus a risk penalty of 0.
    assert result.total_score_v2 == 62.85


def test_trend_momentum_still_reads_the_outlier():
    """Decoupling must not delete the demand signal — only stop double-counting."""
    assert TopicScorer._calc_trend_momentum(_raw(outlier_ratio=8.0)) == 24


# ── Gap now measures saturation ──────────────────────────────────────────────

def test_small_incumbent_means_a_bigger_gap_than_a_giant_one():
    small = TopicScorer._calc_gap_score(_raw(channel_median_views=20_000))
    big = TopicScorer._calc_gap_score(_raw(channel_median_views=2_000_000))
    assert small > big


def test_topic_already_covered_across_competitors_scores_lower():
    empty = TopicScorer._calc_gap_score(_raw(similar_competitor_videos=0))
    crowded = TopicScorer._calc_gap_score(_raw(similar_competitor_videos=9))
    assert empty > crowded


def test_unknown_saturation_is_neutral_not_empty():
    """'We never checked' must not score like 'we checked and it's wide open' —
    that conflation makes an unresearched topic look like a discovery."""
    unknown = TopicScorer._calc_gap_score(_raw())
    verified_empty = TopicScorer._calc_gap_score(_raw(similar_competitor_videos=0))
    assert unknown < verified_empty
    assert unknown == 12


def test_engagement_lift_above_the_channel_norm_widens_the_gap():
    hot = TopicScorer._calc_gap_score(_raw(engagement_rate=0.08, channel_avg_engagement=0.04))
    cold = TopicScorer._calc_gap_score(_raw(engagement_rate=0.02, channel_avg_engagement=0.04))
    assert hot > cold


def test_gap_stays_inside_its_budget():
    maxed = TopicScorer._calc_gap_score(_raw(
        channel_median_views=1_000, similar_competitor_videos=0,
        engagement_rate=0.5, channel_avg_engagement=0.01))
    floored = TopicScorer._calc_gap_score(_raw(
        channel_median_views=50_000_000, similar_competitor_videos=40,
        engagement_rate=0.001, channel_avg_engagement=0.05))
    assert maxed == GAP_MAX
    assert 0 <= floored <= GAP_MAX


# ── Stack fit ────────────────────────────────────────────────────────────────

FULL_PROFILE = StackProfile(
    niches={Niche.FINANCE},
    markets={Market.US},
    duration_minutes=(8.0, 16.0),
    proven_title_patterns={"listicle", "how_to"},
    unsupported_requirements={"face_cam", "live_footage"},
    blocked_keywords={"gambling"},
)


def test_unconfigured_profile_is_neutral():
    """An operation that has not declared its stack must not have every topic
    silently penalised."""
    fit, notes = TopicScorer()._calc_stack_fit(_raw())
    assert fit == STACK_FIT_NEUTRAL
    assert any("no profile" in n for n in notes)


def test_perfect_fit_scores_the_full_budget():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    fit, notes = scorer._calc_stack_fit(_raw(
        duration_minutes=12.0, title_patterns=["listicle"]))
    assert fit == STACK_FIT_MAX
    assert notes == []


def test_unproducible_requirement_is_a_hard_zero_with_a_reason():
    """Demand for something we cannot shoot is not opportunity."""
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    fit, notes = scorer._calc_stack_fit(_raw(production_requirements=["face_cam"]))
    assert fit == 0.0
    assert "face_cam" in notes[0]


def test_blocked_keyword_is_a_hard_zero():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    fit, notes = scorer._calc_stack_fit(_raw(title="Best Gambling Strategies"))
    assert fit == 0.0
    assert "blocked keyword" in notes[0]


def test_off_niche_topic_loses_the_niche_points_and_says_so():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    fit, notes = scorer._calc_stack_fit(_raw(niche=Niche.MYTHOLOGY, duration_minutes=12.0,
                                             title_patterns=["listicle"]))
    assert fit == STACK_FIT_MAX - 6
    assert any("off-niche" in n for n in notes)


def test_runtime_far_outside_the_band_is_flagged():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    fit, notes = scorer._calc_stack_fit(_raw(duration_minutes=90.0, title_patterns=["listicle"]))
    assert fit < STACK_FIT_MAX
    assert any("far outside" in n for n in notes)


def test_unknown_runtime_is_half_credit_not_a_penalty():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    known, _ = scorer._calc_stack_fit(_raw(duration_minutes=12.0, title_patterns=["listicle"]))
    unknown, _ = scorer._calc_stack_fit(_raw(title_patterns=["listicle"]))
    assert known > unknown > known - 4


# ── The whole score still fits in 100 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_dimensions_still_sum_to_at_most_100():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    result = await scorer.score(_raw(
        market=Market.US, outlier_ratio=50.0, channel_median_views=1_000,
        similar_competitor_videos=0, engagement_rate=0.5,
        channel_avg_engagement=0.01, duration_minutes=12.0,
        title_patterns=["listicle"]))
    # v2 revision 2: the five original dimensions are rescaled into 80 points
    # of the budget, and audience fit + repeatability hold the other 20, with
    # the risk penalty subtracted afterwards. Asserting the composition rather
    # than a literal keeps this test meaningful if a weight is retuned, while
    # still failing if a dimension is dropped or double-counted.
    from omnicast.discovery.scorer import V2_WEIGHTS

    expected = (result.trend_momentum * V2_WEIGHTS["trend"]
                + result.gap_score * V2_WEIGHTS["gap"]
                + result.rpm_potential * V2_WEIGHTS["rpm"]
                + result.novelty_score * V2_WEIGHTS["novelty"]
                + result.stack_fit * V2_WEIGHTS["stack"]
                + result.audience_fit + result.repeatability
                - result.risk_penalty)
    assert expected <= 100
    assert result.total_score_v2 == pytest.approx(min(expected, 100))


@pytest.mark.asyncio
async def test_stack_fit_reasons_reach_the_scored_topic():
    scorer = TopicScorer(stack_profile=FULL_PROFILE)
    result = await scorer.score(_raw(production_requirements=["live_footage"]))
    assert result.stack_fit == 0.0
    assert any("live_footage" in n for n in result.score_notes)
