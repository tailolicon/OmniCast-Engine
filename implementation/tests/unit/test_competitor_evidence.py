"""Pins for the evidence validator (Native Research Engine, layer 2 of 4).

The validator's whole job is refusing LLM-synthesized findings whose evidence
does not check out in code: fake pairs, quotes not in transcripts, frequencies
that don't recompute, rules that copy a competitor's sentences.
"""

from __future__ import annotations

from omnicast.analytics.competitor_evidence import (
    CohortFinding,
    PairEvidence,
    excerpt_in_transcript,
    rule_copies_transcript,
    validate_findings,
)

TRANSCRIPTS = {
    "win1": "The earnings limit is twenty three thousand four hundred dollars. "
            "Claiming early costs you every single month for life.",
    "ctl1": "Today we talk about several retirement topics and some numbers.",
    "win2": "There is a new proposal nobody is talking about this week.",
    "ctl2": "Let us review the usual claiming strategies calmly.",
    "win3": "One form filed by July tenth gets your refund back.",
    "ctl3": "Some thoughts about taxes in general, nothing urgent.",
}
PAIRS = {"win1": "ctl1", "win2": "ctl2", "win3": "ctl3"}


def _pair(w, c, we="", ce=""):
    return PairEvidence(winner_id=w, control_id=c,
                        winner_excerpt=we, control_excerpt=ce)


def _finding(**kw) -> CohortFinding:
    base = dict(
        finding_id="hook_consequence_first",
        hypothesis="Winners state a concrete consequence before context.",
        matched_pairs_examined=3,
        supporting_pairs=[
            _pair("win1", "ctl1", "claiming early costs you", "several retirement topics"),
            _pair("win2", "ctl2", "new proposal nobody is talking", "usual claiming strategies"),
            _pair("win3", "ctl3", "one form filed by July", "taxes in general"),
        ],
        alternative_explanations=["winners may simply cover newsier topics"],
        reusable_rule="State the monetary consequence before any background context.",
        research_run_id="run1", model="test-model", prompt_version="v1",
    )
    base.update(kw)
    return CohortFinding(**base)


class TestValidatorAccepts:
    def test_clean_finding_accepted_with_recomputed_frequencies(self):
        report = validate_findings([_finding()], matched_pairs=PAIRS,
                                   transcripts=TRANSCRIPTS)
        assert report.accepted == ["hook_consequence_first"], report.verdicts
        v = report.verdicts[0]
        assert v.recomputed_winner_frequency == 1.0
        assert v.recomputed_control_frequency == 0.0


class TestValidatorRejects:
    def _only_verdict(self, finding):
        report = validate_findings([finding], matched_pairs=PAIRS,
                                   transcripts=TRANSCRIPTS)
        assert report.rejected, "expected rejection"
        return report.verdicts[0]

    def test_fake_pair_rejected(self):
        f = _finding(supporting_pairs=[
            _pair("win1", "ctl2", "claiming early costs you", "usual claiming"),
            _pair("win2", "ctl2", "new proposal nobody is talking", "usual claiming strategies"),
            _pair("win3", "ctl3", "one form filed by July", "taxes in general"),
        ])
        v = self._only_verdict(f)
        assert any("not a legal matched pair" in r for r in v.reasons)

    def test_hallucinated_excerpt_rejected(self):
        f = _finding(supporting_pairs=[
            _pair("win1", "ctl1", "guaranteed riches await you", "several retirement topics"),
            _pair("win2", "ctl2", "new proposal nobody is talking", "usual claiming strategies"),
            _pair("win3", "ctl3", "one form filed by July", "taxes in general"),
        ])
        v = self._only_verdict(f)
        assert any("not found in transcript" in r for r in v.reasons)

    def test_unknown_video_id_rejected(self):
        f = _finding(supporting_pairs=[
            _pair("ghost", "ctl1", "anything", "anything"),
            _pair("win2", "ctl2", "new proposal nobody is talking", "usual claiming strategies"),
            _pair("win3", "ctl3", "one form filed by July", "taxes in general"),
        ])
        v = self._only_verdict(f)
        assert any("not in corpus manifest" in r for r in v.reasons)

    def test_too_few_pairs_rejected(self):
        f = _finding(matched_pairs_examined=2, supporting_pairs=[
            _pair("win1", "ctl1", "claiming early costs you", "several retirement topics"),
            _pair("win2", "ctl2", "new proposal nobody is talking", "usual claiming strategies"),
        ][:2])
        v = self._only_verdict(f)
        assert any("weak_signals" in r for r in v.reasons)

    def test_llm_frequencies_ignored_gap_recomputed(self):
        # LLM claims a huge gap, but two counterexamples erase it in recompute.
        f = _finding(winner_frequency=0.9, control_frequency=0.1,
                     counterexample_pairs=[
                         _pair("win1", "ctl1"), _pair("win2", "ctl2"),
                         _pair("win3", "ctl3")])
        report = validate_findings([f], matched_pairs=PAIRS, transcripts=TRANSCRIPTS)
        v = report.verdicts[0]
        assert not v.accepted
        assert any("frequency gap" in r for r in v.reasons)

    def test_rule_copying_transcript_rejected(self):
        f = _finding(reusable_rule=(
            "The earnings limit is twenty three thousand four hundred dollars today"))
        v = self._only_verdict(f)
        assert any("copying a competitor" in r for r in v.reasons)

    def test_missing_provenance_rejected(self):
        v = self._only_verdict(_finding(model=""))
        assert any("provenance" in r for r in v.reasons)

    def test_non_correlational_rejected(self):
        v = self._only_verdict(_finding(finding_type="causal"))
        assert any("correlational" in r for r in v.reasons)

    def test_one_sided_evidence_rejected(self):
        f = _finding(supporting_pairs=[
            _pair("win1", "ctl1", "claiming early costs you", ""),
            _pair("win2", "ctl2", "new proposal nobody is talking", "usual claiming strategies"),
            _pair("win3", "ctl3", "one form filed by July", "taxes in general"),
        ])
        v = self._only_verdict(f)
        assert any("BOTH sides" in r for r in v.reasons)


class TestHelpers:
    def test_excerpt_matching_is_punctuation_insensitive(self):
        assert excerpt_in_transcript("Claiming early, costs you!",
                                     TRANSCRIPTS["win1"])

    def test_ngram_copy_detector(self):
        assert rule_copies_transcript(
            "the earnings limit is twenty three thousand four hundred dollars",
            TRANSCRIPTS) == "win1"
        assert rule_copies_transcript(
            "state the consequence before the context", TRANSCRIPTS) == ""
