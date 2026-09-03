"""P0 brief §15/§3.1 — the rest of the niche opportunity model.

    demand + supply weakness + audience fit + stack-fit + monetization
    + repeatability - production/legal/YMYL risk

Demand, supply weakness, monetization and stack fit existed. These tests cover
the three that did not, plus the containment that stops a changed scoring
function from being calibrated against a corpus scored by the old one.
"""

from __future__ import annotations

import pytest

from omnicast.analytics.pillars import load_pillars
from omnicast.discovery.models import TopicRawData
from omnicast.discovery.opportunity import (
    AudienceProfile,
    audience_fit,
    repeatability,
    risk_penalty,
)
from omnicast.discovery.scorer import SCORING_V2_REVISION, TopicScorer
from omnicast.models.enums import Market, Niche, TopicSource

AUDIENCE = {
    "age_range": "55-70",
    "pain_points": ["fear of outliving savings", "confusing pension rules"],
    "content_triggers": ["specific dollar amounts"],
    "preferred_video_length_min": 12,
}

PILLARS = load_pillars([
    {"id": "annuities", "name": "Annuities", "keywords": ["annuity", "annuities"]},
])


def _topic(title, *, niche=Niche.FINANCE, source=TopicSource.YOUTUBE_COMPETITOR,
           description="", **metrics) -> TopicRawData:
    return TopicRawData(title=title, description=description, source=source,
                        niche=niche, market=Market.US, raw_metrics=metrics)


# ── audience fit ────────────────────────────────────────────────────────────

def test_an_unconfigured_audience_scores_neutral_not_zero():
    """"We never asked who this channel is for" and "this is wrong for them"
    are different facts. Scoring them alike is how an unresearched channel gets
    every topic marked down."""
    result = audience_fit(_topic("anything"), AudienceProfile())
    assert result.score == 5.0
    assert any("we never asked" in n for n in result.notes)


def test_a_topic_with_no_text_is_neutral_not_a_measured_mismatch():
    """Found by adversarial review: a configured profile plus an EMPTY topic
    scored 2.0 — bit-identical to a measured "does not fit", and three points
    below this dimension's own declared neutral. The note even asserted a
    measurement ("no pain point appears") that never happened."""
    profile = AudienceProfile.from_channel(type("C", (), {"audience": AUDIENCE})())
    blank = audience_fit(_topic(""), profile)
    measured_miss = audience_fit(_topic("The best gaming laptop"), profile)
    assert blank.score == 5.0
    assert measured_miss.score < blank.score
    assert any("no title or description" in n for n in blank.notes)


def test_a_topic_hitting_a_configured_pain_point_scores_higher_than_one_that_does_not():
    profile = AudienceProfile.from_channel(type("C", (), {"audience": AUDIENCE})())
    on_target = audience_fit(
        _topic("Will your savings outlive you?", duration_minutes=12), profile)
    off_target = audience_fit(
        _topic("The best gaming laptop", duration_minutes=12), profile)
    assert on_target.score > off_target.score
    assert on_target.evidence


def test_a_single_common_word_does_not_count_as_a_pain_point_match():
    """"fear of outliving savings" must not be matched by the word "savings",
    which appears in every finance title ever written."""
    profile = AudienceProfile.from_channel(type("C", (), {"audience": AUDIENCE})())
    result = audience_fit(_topic("Best savings accounts of 2026",
                                 duration_minutes=12), profile)
    assert "fear of outliving savings" not in result.evidence


def test_runtime_belongs_to_stack_fit_and_is_not_scored_twice():
    """Found by adversarial review: runtime moved BOTH stack_fit and
    audience_fit, and both bands derive from the same channel number — one
    duration change was worth 7.2 points of the total through two dimensions.
    Audience fit answers "whose topic is this"; runtime is stack fit's."""
    profile = AudienceProfile.from_channel(type("C", (), {"audience": AUDIENCE})())
    short = audience_fit(_topic("Will your savings outlive you?",
                                duration_minutes=12), profile)
    long = audience_fit(_topic("Will your savings outlive you?",
                               duration_minutes=90), profile)
    assert short.score == long.score


# ── repeatability ───────────────────────────────────────────────────────────

def test_a_time_bound_topic_cannot_become_a_library():
    spike = repeatability(_topic("Breaking: the pension bill just passed"),
                          pillars_configured=False)
    evergreen = repeatability(_topic("Pension rules explained"),
                              pillars_configured=False)
    assert evergreen.score > spike.score
    assert any("spike" in n for n in spike.notes)


def test_belonging_to_a_declared_pillar_makes_a_topic_repeatable():
    inside = repeatability(_topic("How annuities really work"),
                           pillar_id="annuities", pillars_configured=True)
    outside = repeatability(_topic("How mortgages really work"),
                            pillar_id="", pillars_configured=True)
    assert inside.score > outside.score
    assert "pillar:annuities" in inside.evidence


def test_no_pillars_configured_is_half_credit_not_a_penalty():
    result = repeatability(_topic("Pension rules explained"),
                           pillars_configured=False)
    assert any("no content pillars configured" in n for n in result.notes)
    assert result.score >= 5.0


def test_the_scanner_that_found_a_topic_is_not_scored_twice():
    """Found by adversarial review: `SOURCE_GAP` already ranks news lowest, and
    repeatability docked NEWS_RSS again — 11 points of the total moving on the
    single fact "which scanner found it". An evergreen topic is evergreen
    whichever feed surfaced it; time-bound PHRASING is what disqualifies it."""
    news = repeatability(_topic("Pension rules explained", source=TopicSource.NEWS_RSS),
                         pillars_configured=False)
    evergreen = repeatability(_topic("Pension rules explained"),
                              pillars_configured=False)
    assert news.score == evergreen.score

    spike = repeatability(_topic("Breaking: pension rules change",
                                 source=TopicSource.NEWS_RSS),
                          pillars_configured=False)
    assert spike.score < news.score


def test_a_topic_with_no_title_is_neutral_not_a_proven_evergreen():
    """Found by adversarial review: both branches awarded their credit for the
    ABSENCE of a marker, so an empty title scored 7.0 — above this dimension's
    own neutral and one point off a real evergreen."""
    blank = repeatability(_topic(""), pillars_configured=False)
    evergreen = repeatability(_topic("Pension rules explained"),
                              pillars_configured=False)
    assert blank.score == 5.0
    assert evergreen.score > blank.score


def test_one_phrase_may_not_move_both_risk_and_repeatability():
    """`do this today or...` fired the YMYL urgency penalty AND the spike
    marker; `reacting to` fired a hard stack-fit zero AND the spike marker."""
    urgent = _topic("Do this today or lose your pension", niche=Niche.FINANCE)
    assert risk_penalty(urgent).score > 0
    assert repeatability(urgent, pillars_configured=False).score == \
        repeatability(_topic("Protect your pension"), pillars_configured=False).score


# ── risk ────────────────────────────────────────────────────────────────────

def test_the_penalty_attaches_to_the_claim_not_to_the_niche():
    """Penalising "finance" would dock every topic on a finance channel by the
    same amount — a constant offset, which discriminates nothing."""
    ordinary = risk_penalty(_topic("How index funds work", niche=Niche.FINANCE))
    assert ordinary.score == 0.0


def test_a_guaranteed_return_claim_in_a_ymyl_niche_is_penalised_with_evidence():
    result = risk_penalty(_topic("The risk-free way to double your money",
                                 niche=Niche.FINANCE))
    assert result.score >= 10.0
    assert any("ymyl" in e for e in result.evidence)
    assert result.notes


def test_the_same_phrasing_outside_a_ymyl_niche_is_not_ymyl_penalised():
    finance = risk_penalty(_topic("A guaranteed way to win", niche=Niche.FINANCE))
    history = risk_penalty(_topic("A guaranteed way to win", niche=Niche.MYTHOLOGY))
    assert finance.score > history.score


def test_rights_risk_is_penalised_in_any_niche():
    result = risk_penalty(_topic("Full movie: the whole thing free download",
                                 niche=Niche.MYTHOLOGY))
    assert result.score > 0
    assert any("rights_risk" in e for e in result.evidence)


def test_risk_does_not_re_penalise_what_stack_fit_already_zeroed():
    """Scoring one fact twice is the exact bug that cost the previous session
    its gap_score rewrite."""
    result = risk_penalty(_topic("Interview with a fund manager",
                                 niche=Niche.FINANCE))
    assert result.score == 0.0


# ── the dimensions reach the score ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_new_dimensions_change_v2_and_are_recorded_on_the_topic():
    profile = AudienceProfile.from_channel(type("C", (), {"audience": AUDIENCE})())
    scorer = TopicScorer(scoring_mode="shadow", audience_profile=profile,
                         pillars=PILLARS)

    fits = await scorer.score(_topic("How annuities protect savings you may outlive",
                                     duration_minutes=12, outlier_ratio=4.0))
    misfits = await scorer.score(_topic("Breaking: the risk-free way to double "
                                        "your money before it's too late",
                                        duration_minutes=90, outlier_ratio=4.0))

    assert fits.audience_fit > misfits.audience_fit
    assert fits.repeatability > misfits.repeatability
    assert misfits.risk_penalty > 0
    assert fits.total_score_v2 > misfits.total_score_v2
    # ...and v1, which knows none of this, cannot tell them apart.
    assert fits.total_score_v1 == misfits.total_score_v1


@pytest.mark.asyncio
async def test_the_new_dimensions_still_do_not_decide_anything():
    """Containment is unchanged: shadow is the default and v1 decides."""
    scorer = TopicScorer(scoring_mode="shadow")
    result = await scorer.score(_topic("Guaranteed risk-free returns",
                                       outlier_ratio=8.0))
    assert result.scoring_version == "v1"
    assert result.total_score == result.total_score_v1
    assert result.risk_penalty > 0          # measured, recorded, not applied


@pytest.mark.asyncio
async def test_every_topic_carries_the_v2_revision_that_scored_it():
    result = await TopicScorer().score(_topic("anything"))
    assert result.scoring_v2_revision == SCORING_V2_REVISION == 2


# ── calibration refuses a mixed corpus ──────────────────────────────────────

def _row(v1, v2, *, revision, source="youtube_competitor", trend=10.0,
         gap_v1=30.0, gap=12.0):
    return {"total_v1": v1, "total_v2": v2, "v2_revision": revision,
            "source": source, "trend_momentum": trend, "gap_score_v1": gap_v1,
            "gap_score": gap}


def test_a_corpus_spanning_two_v2_revisions_can_never_promote():
    """Blending two scoring functions produces statistics about a scorer that
    never ran — and the resulting green light would be for nothing."""
    from omnicast.discovery.scoring_calibration import summarize

    rows = ([_row(70 + i * 0.1, 60 + i * 0.1, revision=1) for i in range(40)]
            + [_row(70 + i * 0.1, 59 + i * 0.1, revision=2) for i in range(40)])
    report = summarize(rows)
    assert report.v2_revisions == {1, 2}
    assert report.single_revision is False
    assert report.migration_is_stable is False
    assert report.ready_to_promote is False
    assert any("different scoring functions" in n for n in report.notes)


def test_rows_predating_the_revision_field_count_as_revision_one():
    from omnicast.discovery.scoring_calibration import summarize

    rows = [{"total_v1": 70.0, "total_v2": 60.0, "source": "youtube_competitor",
             "trend_momentum": 10.0, "gap_score_v1": 30.0, "gap_score": 12.0}]
    assert summarize(rows).v2_revisions == {1}
