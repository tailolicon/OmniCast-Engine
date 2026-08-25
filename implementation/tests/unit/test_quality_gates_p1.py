"""P1 §15/§8/§9 — quality gates and benchmark similarity.

§9's criticism is aimed partly at this repo's own tests: `video_intel`'s suite
mocked the very methods under test, so green proved nothing. The tests here
therefore assert on BEHAVIOUR UNDER REAL INPUTS, and specifically on the three
outcomes that are easy to confuse and expensive to confuse:

    pass   — measured, and it met the bar
    fail   — measured, and it did not
    unknown— did not run, which is neither of the above and the one that hides
"""

from __future__ import annotations

import pytest

from omnicast.quality.benchmark import (
    DO_NOT_COPY,
    SIMILARITY_DIMENSIONS,
    compare_to_reference,
)
from omnicast.quality.gates import (
    FAIL,
    GATE_ORDER,
    NEEDS_HUMAN,
    PASS,
    SLOP_SIGNALS_NOT_DETECTABLE,
    UNKNOWN,
    WARN,
    run_gates,
)


def _good_evidence(**overrides) -> dict:
    evidence = {
        "claim_count": 10, "sourced_claim_count": 8,
        "citations": [{"url": "https://example.org/a"}],
        "proof_points_per_minute": 1.2,
        "audience_fit_score": 7.0,
        "visual_relevance_passed": True,
        "repeated_shot_ratio": 0.05,
        "motion_mix": {"static": 0.5, "drift": 0.5},
        "transition_mix": {"cut": 18, "dissolve": 2},
        "voice_rate_std_over_mean": 0.18,
        "caption_density": 0.4,
        "hook_overpromises": False,
        "compliance_passed": True,
        "benchmark_headline": 0.86,
        "is_ymyl": False, "is_flagship": False,
    }
    evidence.update(overrides)
    return evidence


# ── the three outcomes must stay distinguishable ────────────────────────────

def test_a_gate_with_no_input_is_unknown_not_a_pass():
    """§9's complaint about fixed scores: a module that returns a number
    regardless of input has not checked anything."""
    report = run_gates({})
    assert set(report.unknown) >= {
        "research_accuracy", "source_provenance", "script_editorial",
        "audience_fit", "visual_relevance", "continuity", "motion_quality",
        "sound_design", "packaging_trust", "ymyl_compliance"}
    assert report.failed == []
    for gate in report.unknown:
        assert report.get(gate).missing_inputs


def test_an_unknown_gate_is_not_a_failure_either():
    report = run_gates({})
    assert report.releasable is True
    assert report.coverage < 1.0
    assert "does NOT mean the video was checked" in report.as_dict()["note"]


def test_an_undeterminable_risk_class_is_unknown_not_a_pass():
    """Found in review: nothing upstream ever set `is_ymyl`, so it defaulted to
    False and every finance and health video passed the human gate reporting
    "not YMYL"."""
    outcome = run_gates({}).get("human_review")
    assert outcome.status == UNKNOWN
    assert "not a finding that the video is low risk" in outcome.reason


def test_an_inferred_ymyl_flag_routes_to_a_human():
    report = run_gates({"is_ymyl": True, "ymyl_source": "inferred from niche 'finance'"})
    outcome = report.get("human_review")
    assert outcome.status == NEEDS_HUMAN
    assert "finance" in outcome.evidence["ymyl_source"]
    assert report.releasable is False


@pytest.mark.parametrize("value", ["no", "false", "0", "", "off"])
def test_a_gate_does_not_read_the_string_no_as_true(value):
    """`bool("no")` is True, and these are safety gates."""
    assert run_gates({**_good_evidence(), "compliance_passed": value}
                     ).get("ymyl_compliance").status == FAIL
    assert run_gates({**_good_evidence(), "visual_relevance_passed": value}
                     ).get("visual_relevance").status == FAIL


@pytest.mark.parametrize("mix", [{"cut": -10, "dissolve": 5},
                                 {"cut": -5, "dissolve": 5}])
def test_a_negative_transition_count_is_unknown_not_a_verdict(mix):
    outcome = run_gates({**_good_evidence(), "transition_mix": mix}
                        ).get("motion_quality")
    assert outcome.status == UNKNOWN


def test_releasable_can_never_be_read_as_checked():
    report = run_gates({})
    data = report.as_dict()
    assert data["releasable"] is True
    assert data["coverage"] < 1.0
    assert "human_review" in data["unknown"]


def test_every_gate_the_review_lists_is_present():
    report = run_gates(_good_evidence())
    assert {o.gate for o in report.outcomes} == set(GATE_ORDER)


# ── gates that actually fail on real signals ────────────────────────────────

def test_unsourced_claims_fail_research_accuracy():
    report = run_gates(_good_evidence(claim_count=10, sourced_claim_count=2))
    outcome = report.get("research_accuracy")
    assert outcome.status == FAIL
    assert outcome.evidence["sourced_ratio"] == pytest.approx(0.2)


def test_a_script_with_no_checkable_claim_is_warned_not_silently_passed():
    report = run_gates(_good_evidence(claim_count=0, sourced_claim_count=0))
    assert report.get("research_accuracy").status == WARN


def test_no_citations_at_all_is_unknown_not_a_provenance_failure():
    """Whether a script SHOULD cite something is research_accuracy's question.
    Failing here as well punished one fact twice and blocked every script that
    legitimately cites nothing."""
    outcome = run_gates(_good_evidence(citations=[])).get("source_provenance")
    assert outcome.status == UNKNOWN


def test_a_citation_without_a_url_fails_provenance():
    report = run_gates(_good_evidence(citations=[{"title": "a study"}]))
    outcome = report.get("source_provenance")
    assert outcome.status == FAIL
    assert outcome.evidence["traceable"] == 0


def test_repeated_shots_fail_continuity():
    report = run_gates(_good_evidence(repeated_shot_ratio=0.6))
    assert report.get("continuity").status == FAIL


def test_a_wall_of_dissolves_fails_motion_quality():
    report = run_gates(_good_evidence(transition_mix={"cut": 2, "dissolve": 18}))
    outcome = report.get("motion_quality")
    assert outcome.status == FAIL
    assert outcome.evidence["dissolve_share"] == pytest.approx(0.9)


def test_a_flat_voice_fails_sound_design():
    report = run_gates(_good_evidence(voice_rate_std_over_mean=0.02))
    assert report.get("sound_design").status == FAIL


def test_an_overpromising_hook_fails_packaging_trust():
    report = run_gates(_good_evidence(hook_overpromises=True))
    outcome = report.get("packaging_trust")
    assert outcome.status == FAIL
    assert "promises more" in outcome.reason


def test_a_caption_wall_fails_packaging_trust():
    report = run_gates(_good_evidence(caption_density=0.95))
    assert report.get("packaging_trust").status == FAIL


def test_a_clean_video_passes_and_is_releasable():
    report = run_gates(_good_evidence())
    assert report.failed == []
    assert report.releasable is True
    assert report.coverage == 1.0


# ── the human route ─────────────────────────────────────────────────────────

def test_a_ymyl_video_without_a_recorded_review_blocks_release():
    """The system does not mark its own homework where being wrong costs
    someone money or health."""
    report = run_gates(_good_evidence(is_ymyl=True))
    assert report.get("human_review").status == NEEDS_HUMAN
    assert report.releasable is False


def test_a_flagship_video_takes_the_same_route():
    report = run_gates(_good_evidence(is_flagship=True))
    assert report.needs_human == ["human_review"]


def test_a_recorded_review_releases_it():
    report = run_gates(_good_evidence(is_ymyl=True, human_reviewed=True,
                                      human_reviewer="operator"))
    assert report.get("human_review").status == PASS
    assert report.releasable is True


def test_an_ordinary_video_needs_no_human_gate():
    report = run_gates(_good_evidence())
    assert report.get("human_review").status == PASS
    assert report.needs_human == []


def test_the_slop_signals_it_cannot_detect_are_named():
    report = run_gates(_good_evidence())
    listed = report.as_dict()["undetectable_slop_signals"]
    assert "no_editorial_taste" in listed
    assert set(listed) == set(SLOP_SIGNALS_NOT_DETECTABLE)


# ── §8 benchmark similarity ─────────────────────────────────────────────────

OURS = {
    "beat_count": 5, "median_shot_seconds": 4.0, "words_per_minute": 150,
    "caption_density": 0.4, "colour_warmth": 10.0, "thumbnail_text_words": 4,
    "visual_source_mix": {"stock": 0.5, "generated": 0.5},
    "transition_mix": {"cut": 0.9, "dissolve": 0.1},
    "sfx_placement": {"early": 0.5, "late": 0.5},
    "music_energy_curve": {"low": 0.3, "high": 0.7},
}


def _reference(**overrides) -> dict:
    reference = dict(OURS)
    reference["reference_id"] = "golden_001"
    reference.update(overrides)
    return reference


def test_no_headline_similarity_without_a_golden_reference():
    """The claim §8 exists to stop: "95% similar to the benchmark", with nothing
    behind the number."""
    comparison = compare_to_reference(OURS, dict(OURS))   # no reference_id
    assert comparison.headline is None
    assert any("golden reference" in b for b in comparison.blockers)


def test_no_headline_similarity_without_a_blind_human_comparison():
    comparison = compare_to_reference(OURS, _reference())
    assert comparison.headline is None
    assert any("blind human comparison" in b for b in comparison.blockers)


def test_no_headline_similarity_while_a_dimension_is_unmeasured():
    """Averaging four measured dimensions and seven unmeasured ones produces a
    number about nothing that looks exactly like a real one."""
    thin = {"beat_count": 5}
    comparison = compare_to_reference(
        thin, _reference(blind_human_comparison=True))
    assert comparison.headline is None
    assert any("not measured" in b for b in comparison.blockers)


def test_an_identical_video_with_every_precondition_met_gets_its_headline():
    """Found by adversarial review: `perceived_quality` is not comparable BY
    DEFINITION, so counting it among the unmeasured made `headline` unreachable
    for every possible input — §8's pass/fail threshold could never fire, and
    the gate that reads it was permanently `unknown`. The human comparison is
    still required; it is required as itself."""
    comparison = compare_to_reference(OURS, _reference(blind_human_comparison=True))
    assert comparison.get("perceived_quality").status == "unknown"
    assert comparison.unmeasured_comparable == []
    assert comparison.blockers == []
    assert comparison.headline == pytest.approx(1.0)

    structure = comparison.get("script_structure")
    assert structure.similarity == pytest.approx(1.0)
    assert structure.matches is True


def test_the_headline_still_requires_the_human_comparison():
    comparison = compare_to_reference(OURS, _reference())
    assert comparison.unmeasured_comparable == []
    assert comparison.headline is None
    assert any("blind human comparison" in b for b in comparison.blockers)


def test_a_dimension_missing_on_one_side_is_unknown_not_zero():
    comparison = compare_to_reference(
        {k: v for k, v in OURS.items() if k != "words_per_minute"}, _reference())
    voice = comparison.get("voice_pacing")
    assert voice.status == "unknown"
    assert voice.similarity is None
    assert voice.matches is None


def test_a_different_shot_rhythm_scores_lower_than_a_matching_one():
    same = compare_to_reference(OURS, _reference()).get("shot_duration_distribution")
    different = compare_to_reference(
        dict(OURS, median_shot_seconds=12.0), _reference()
    ).get("shot_duration_distribution")
    assert same.similarity > different.similarity
    assert different.matches is False


def test_perceived_quality_is_never_computed_here():
    comparison = compare_to_reference(OURS, _reference())
    perceived = comparison.get("perceived_quality")
    assert perceived.status == "unknown"
    assert "invented" in perceived.detail


def test_what_must_not_be_copied_is_reported_and_never_scored():
    """§8 asks for it explicitly, and it is the half everyone forgets: scoring
    these would reward getting closer to material we cannot ship."""
    comparison = compare_to_reference(OURS, _reference())
    data = comparison.as_dict()
    assert set(data["do_not_copy"]) == set(DO_NOT_COPY)
    scored = {d["dimension"] for d in data["dimensions"]}
    assert scored.isdisjoint(DO_NOT_COPY)


def test_every_dimension_the_review_lists_is_present():
    comparison = compare_to_reference(OURS, _reference())
    assert {d.name for d in comparison.dimensions} == {
        name for name, _comparable, _detail in SIMILARITY_DIMENSIONS}
