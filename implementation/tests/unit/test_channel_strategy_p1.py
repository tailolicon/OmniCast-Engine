"""P1 §15/§11 — the long-term channel operator layer.

The review's charge: OmniCast behaves as `find topic -> make video -> upload ->
count views`, and an experienced operator does something else. These tests pin
the three things that make this layer worth having rather than decorative:

  * it DECLARES and never generates — a thesis an LLM wrote would agree with
    whatever the channel already does, so it could never show drift;
  * unknown is not failure — a gate with no data returns `unknown`, because
    killing an experiment over a number nobody collected is how a system kills
    its own best bets;
  * a metric it cannot compute is named, with what would unblock it, rather
    than quietly dropped from the list.
"""

from __future__ import annotations

import pytest

from omnicast.config.channel import ChannelProfile
from omnicast.models.enums import Market, Niche
from omnicast.strategy import (
    classify_journey_stage,
    evaluate_gates,
    load_thesis,
    measure_long_term,
    portfolio_drift,
    review_architecture,
    shorts_to_long_funnel,
)
from omnicast.strategy.metrics import MEASURED, METRIC_REQUIREMENTS, MISSING
from omnicast.strategy.stage_gate import (
    DEFAULT_PORTFOLIO,
    FAIL,
    GATES,
    PASS,
    UNKNOWN,
    decide,
)
from omnicast.strategy.thesis import CORE, THESIS_QUESTIONS, UNDECLARED

PILLARS = [
    {"id": "annuities", "name": "Annuities", "keywords": ["annuity", "annuities"],
     "role": "core"},
    {"id": "medicare", "name": "Medicare", "keywords": ["medicare"],
     "role": "supporting"},
    {"id": "crypto", "name": "Crypto", "keywords": ["crypto", "bitcoin"],
     "role": "experimental"},
]


def _channel(**overrides) -> ChannelProfile:
    data = dict(channel_id="fin_retirement_us", name="Smart Retirement",
                niche=Niche.FINANCE, market=Market.US, content_pillars=PILLARS)
    data.update(overrides)
    return ChannelProfile(**data)


# ── §11.1 thesis ────────────────────────────────────────────────────────────

def test_an_undeclared_thesis_is_missing_not_generated():
    """An LLM writes a plausible thesis for any channel in four seconds, and it
    agrees with whatever that channel already does — which makes it worthless as
    evidence of drift. Blank stays blank."""
    thesis = load_thesis(_channel())
    assert thesis.is_declared is False
    assert set(thesis.missing) == set(THESIS_QUESTIONS)
    assert thesis.completeness == 0.0
    assert all(v == "" for v in thesis.as_dict()["answers"].values())


def test_a_partial_thesis_reports_exactly_which_questions_are_open():
    thesis = load_thesis(_channel(channel_thesis={
        "audience": "55-70, worried about outliving savings",
        "promise": "the arithmetic nobody shows you",
    }))
    assert thesis.completeness == pytest.approx(0.4)
    assert set(thesis.missing) == {"return_reason", "moat", "owned_format"}


def test_a_complete_thesis_reads_as_declared():
    thesis = load_thesis(_channel(channel_thesis={k: "answered" for k in THESIS_QUESTIONS}))
    assert thesis.is_declared is True
    assert thesis.missing == []


# ── §11.2 content architecture ──────────────────────────────────────────────

def test_the_architecture_is_measured_against_what_was_actually_published():
    architecture = review_architecture(_channel(), [
        "Annuity payouts explained", "Annuity fees to avoid",
        "Medicare traps at 65", "Why bitcoin is not a pension",
    ])
    assert architecture.published_by_pillar["annuities"] == 2
    assert architecture.published_by_pillar["medicare"] == 1
    assert architecture.published_by_pillar["crypto"] == 1
    assert architecture.share_by_role[CORE] == pytest.approx(0.5)


def test_a_declared_pillar_with_nothing_published_is_flagged_as_dormant():
    """An architecture that exists only on paper is not an architecture."""
    architecture = review_architecture(_channel(), ["Annuity payouts explained"])
    assert "medicare" in architecture.dormant_pillars
    assert any("never been published to" in n for n in architecture.notes)


def test_videos_matching_no_pillar_are_counted_as_drift_not_ignored():
    architecture = review_architecture(
        _channel(), ["Annuity payouts explained", "The best gaming laptop"])
    assert architecture.unclassified_videos == 1
    assert any("match no declared pillar" in n for n in architecture.notes)


def test_no_pillars_declared_means_no_drift_can_be_measured():
    architecture = review_architecture(_channel(content_pillars=[]),
                                       ["anything", "at all"])
    assert architecture.unclassified_videos == 2
    assert any("no content pillars declared" in n for n in architecture.notes)


def test_an_unknown_pillar_role_is_rejected_rather_than_trusted():
    channel = _channel(content_pillars=[
        {"id": "annuities", "keywords": ["annuity"], "role": "flagship"}])
    architecture = review_architecture(channel, ["Annuity payouts explained"])
    assert architecture.roles[0].role == UNDECLARED
    assert any("not one of" in n for n in architecture.notes)


def test_the_strategy_layer_classifies_pillars_the_same_way_the_scorer_does():
    """Two components disagreeing about a video's pillar would mean the strategy
    report describes a library that does not exist."""
    from omnicast.analytics.pillars import classify_pillar, load_pillars

    title = "Annuity payouts explained"
    direct = classify_pillar(title, "", load_pillars(PILLARS)).pillar_id
    architecture = review_architecture(_channel(), [title])
    assert list(architecture.published_by_pillar) == [direct]


# ── §11.5 stage gates ───────────────────────────────────────────────────────

def test_a_gate_with_no_data_returns_unknown_not_failure():
    """Killing an experiment for a number nobody has collected is how a system
    kills its own best bets."""
    results = evaluate_gates({})
    assert results[0].status == UNKNOWN
    assert results[0].missing_inputs
    assert "Unknown is not failure" in results[0].reason
    assert decide(results)["decision"] == "keep_measuring"


def test_the_gates_stop_at_the_first_unproven_stage():
    """A channel whose packaging is unproven has no meaningful retention number:
    measuring it would describe people who never arrived."""
    results = evaluate_gates({
        "scored_topics": 40, "approved_topics": 9,
        "published_videos": 6, "audit_pass_rate": 0.9,
        "impressions": 50_000, "ctr": 0.01,      # fails packaging
        "avd_percent": 0.9, "returning_viewer_rate": 0.9,
    })
    assert [r.gate for r in results] == ["niche", "format", "packaging"]
    assert results[-1].status == FAIL
    assert decide(results)["decision"] == "pivot"


def test_a_thin_impression_count_is_sample_size_not_a_packaging_verdict():
    results = evaluate_gates({
        "scored_topics": 40, "approved_topics": 9,
        "published_videos": 6, "audit_pass_rate": 0.9,
        "impressions": 120, "ctr": 0.005,
    })
    packaging = results[-1]
    assert packaging.gate == "packaging"
    assert packaging.status == UNKNOWN
    assert "sample size" in packaging.reason


def test_failing_the_niche_gate_is_a_kill_and_failing_packaging_is_a_pivot():
    kill = evaluate_gates({"scored_topics": 3, "approved_topics": 1})
    assert decide(kill)["decision"] == "kill"


def test_passing_every_gate_is_the_only_route_to_scale():
    results = evaluate_gates({
        "scored_topics": 40, "approved_topics": 9,
        "published_videos": 6, "audit_pass_rate": 0.95,
        "impressions": 50_000, "ctr": 0.06,
        "avd_percent": 0.45, "returning_viewer_rate": 0.25,
        "rpm": 15.0, "views": 100_000, "production_cost_usd": 100.0,
    })
    assert len(results) == len(GATES)
    assert all(r.status == PASS for r in results)
    assert decide(results)["decision"] == "scale"


def test_monetisation_says_its_revenue_is_estimated():
    """§4.7's rule applies to our own channels too: an RPM-derived figure is not
    a payout report."""
    results = evaluate_gates({
        "scored_topics": 40, "approved_topics": 9,
        "published_videos": 6, "audit_pass_rate": 0.95,
        "impressions": 50_000, "ctr": 0.06,
        "avd_percent": 0.45, "returning_viewer_rate": 0.25,
        "rpm": 15.0, "views": 100_000, "production_cost_usd": 100.0,
    })
    assert "ESTIMATED" in results[-1].reason


# ── §11.5 portfolio ─────────────────────────────────────────────────────────

def test_the_portfolio_reports_drift_and_does_not_claim_the_target_is_right():
    portfolio = portfolio_drift(["proven"] * 7 + ["adjacent"] * 2 + ["asymmetric"])
    assert portfolio.actual["proven"] == pytest.approx(0.7)
    assert portfolio.out_of_band == []
    assert "SUGGESTION" in portfolio.as_dict()["target_note"]
    assert portfolio.target == DEFAULT_PORTFOLIO


def test_a_skewed_slate_is_reported_lane_by_lane():
    portfolio = portfolio_drift(["proven"] * 10)
    assert portfolio.drift["proven"] == pytest.approx(0.30)
    assert portfolio.drift["adjacent"] == pytest.approx(-0.20)
    assert portfolio.drift["asymmetric"] == pytest.approx(-0.10)
    # `asymmetric` is exactly AT the tolerance, not past it, so it is not
    # flagged. A portfolio that never drifts at all is one nobody is running;
    # the band exists so that only real skew is reported.
    assert set(portfolio.out_of_band) == {"proven", "adjacent"}


def test_an_unassigned_experiment_is_named_as_spending_the_proven_budget():
    portfolio = portfolio_drift(["proven", "", None])
    assert portfolio.counts["unassigned"] == 2
    assert any("without saying so" in n for n in portfolio.notes)


def test_a_custom_target_replaces_the_reviews_suggestion():
    portfolio = portfolio_drift(["proven"] * 9 + ["adjacent"],
                                target={"proven": 0.9, "adjacent": 0.1})
    assert portfolio.out_of_band == []


# ── §11.4 audience journey ──────────────────────────────────────────────────

@pytest.mark.parametrize("signals,expected", [
    ({}, "cold"),
    ({"videos_watched": 1}, "casual"),
    ({"videos_watched": 2, "subscribed": True}, "subscriber"),
    ({"videos_watched": 3, "subscribed": True,
      "returned_without_recommendation": True}, "returning"),
    ({"videos_watched": 15}, "core_fan"),
    ({"videos_watched": 15, "commented": True}, "community"),
])
def test_journey_stages_are_classified_from_the_signals_that_exist(signals, expected):
    stage, why = classify_journey_stage(signals)
    assert stage == expected
    assert why


# ── §11.3 shorts -> long funnel ─────────────────────────────────────────────

def test_the_funnel_refuses_to_infer_a_link_nobody_declared():
    """Guessing the link from timing or topic overlap would turn a coincidence
    into a conversion rate indistinguishable from a real one."""
    result = shorts_to_long_funnel(
        [{"video_id": "s1", "views": 10_000}],
        [{"video_id": "L1", "views": 2_000}])
    assert result["conversion_rate"] is None
    assert result["status"] == MISSING
    assert any("not inferrable" in n for n in result["notes"])


def test_a_declared_link_with_click_data_gives_a_real_conversion_rate():
    result = shorts_to_long_funnel(
        [{"video_id": "s1", "views": 10_000, "targets_video_id": "L1",
          "clicks_to_target": 250}],
        [{"video_id": "L1"}])
    assert result["linked_shorts"] == 1
    assert result["conversion_rate"] == pytest.approx(0.025)
    assert result["status"] == MEASURED


def test_a_declared_link_without_click_data_says_what_is_needed():
    result = shorts_to_long_funnel(
        [{"video_id": "s1", "views": 10_000, "targets_video_id": "L1"}],
        [{"video_id": "L1"}])
    assert result["status"] == MISSING
    assert any("Analytics API" in n for n in result["notes"])


# ── §11.6 long-term metrics ─────────────────────────────────────────────────

def test_every_metric_the_review_lists_is_present_even_when_it_cannot_be_computed():
    """A dashboard showing nine of twelve teaches its reader there are nine."""
    report = measure_long_term()
    names = {m.name for m in report.metrics}
    assert set(METRIC_REQUIREMENTS) <= names


def test_a_missing_metric_names_what_would_unblock_it():
    report = measure_long_term()
    brand_trust = report.get("brand_trust")
    assert brand_trust.status == MISSING
    assert "needs:" in brand_trust.detail


def test_library_compounding_is_computed_from_the_back_catalogue():
    report = measure_long_term(library=[
        {"views": 8_000, "age_days": 400},
        {"views": 1_000, "age_days": 200},
        {"views": 1_000, "age_days": 5},
    ])
    metric = report.get("library_compounding")
    assert metric.status == MEASURED
    assert metric.value == pytest.approx(0.9)


def test_revenue_per_production_hour_is_labelled_inferred_not_measured():
    report = measure_long_term(production={"estimated_revenue_usd": 300.0,
                                           "production_hours": 10.0})
    metric = report.get("revenue_per_production_hour")
    assert metric.value == pytest.approx(30.0)
    assert metric.status == "inferred"
    assert "ESTIMATED" in metric.detail


def test_views_is_deliberately_not_on_the_list():
    report = measure_long_term()
    assert "views" not in {m.name for m in report.metrics}
    assert "not on this list on purpose" in report.as_dict()["note"]


def test_coverage_is_reported_so_a_thin_report_cannot_read_as_a_full_one():
    empty = measure_long_term()
    populated = measure_long_term(
        channel_metrics={"views": 1000, "unique_viewers": 400,
                         "watch_time_minutes": 5000, "returning_viewers": 0.2},
        library=[{"views": 100, "age_days": 400}],
        production={"production_cost_usd": 50.0})
    assert populated.coverage > empty.coverage
    assert empty.coverage < 0.5
    assert any("would unblock them" in n for n in empty.notes)
