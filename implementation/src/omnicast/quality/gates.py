"""The quality gates §9 says are missing, and the AI-slop signals behind them.

§9's list of gates: research accuracy, source/provenance, script editorial,
audience fit, visual relevance, continuity, motion quality, sound design,
packaging trust, YMYL/compliance, benchmark comparison, human review for
high-risk video.

TWO DESIGN RULES, BOTH FROM §9's OWN CRITICISM.

1. NO FIXED SCORES. §9 objects that some quality modules "return điểm cố định".
   A gate here either measures something or returns `unknown` with the input it
   lacked. `unknown` never counts as a pass, and it never counts as a failure
   either — it counts as a gate that did not run, which is a third thing and the
   one that gets hidden.

2. A GATE MUST BE ABLE TO FAIL FOR A REASON YOU CAN READ. Every outcome carries
   the evidence that produced it. §9 also notes that `video_intel`'s tests
   mocked the methods under test, so a green suite proved nothing — a gate whose
   verdict cannot be traced to an observation has the same defect at runtime.

HUMAN REVIEW IS A ROUTE, NOT A SCORE. YMYL topics and flagship videos are routed
to a person. The system does not get to mark its own homework on the material
where being wrong costs someone money or health.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PASS = "pass"
FAIL = "fail"
WARN = "warn"
UNKNOWN = "unknown"
NEEDS_HUMAN = "needs_human"

# Ordered roughly cheapest-to-most-expensive, so a run can stop early if a
# caller wants it to. Nothing here stops by default: an operator fixing five
# problems at once needs to see all five.
GATE_ORDER: tuple[str, ...] = (
    "research_accuracy", "source_provenance", "script_editorial", "audience_fit",
    "visual_relevance", "continuity", "motion_quality", "sound_design",
    "packaging_trust", "ymyl_compliance", "benchmark_comparison", "human_review",
)

# §9's AI-slop signals that are detectable from data the pipeline already has.
# The rest of its list (b-roll that matches the keyword but not the meaning,
# "AI images that do not clarify the line", missing editorial taste) needs
# comprehension, and is reported as unmeasured rather than approximated.
SLOP_SIGNALS_NOT_DETECTABLE: dict[str, str] = {
    "broll_matches_keyword_not_meaning": "needs comprehension of the line and the shot",
    "image_does_not_clarify_the_line": "needs a vision model reading both",
    "fake_or_meaningless_motion": "needs judgement about whether motion carries meaning",
    "generic_sfx": "needs an SFX classifier and a sense of what is generic here",
    "no_editorial_taste": "not reducible to a metric; this is what human review is for",
}

# Thresholds. Named constants because §9's complaint is precisely that numbers
# like these were buried and uncalibrated; a reader must be able to find them.
MAX_REPEATED_SHOT_RATIO = 0.25       # same visual reused across the video
MAX_TRANSITION_DENSITY = 0.60        # share of cuts that are dissolves/zooms
MIN_PROOF_PER_MINUTE = 0.5           # concrete numbers/citations per minute
MAX_CAPTION_DENSITY = 0.85           # share of runtime carrying burned-in text
MIN_VOICE_VARIANCE = 0.10            # std/mean of speaking rate; flat = robot


@dataclass
class GateOutcome:
    gate: str
    status: str = UNKNOWN
    reason: str = ""
    evidence: dict = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"gate": self.gate, "status": self.status, "reason": self.reason,
                "evidence": dict(self.evidence),
                "missing_inputs": list(self.missing_inputs)}


@dataclass
class QualityReport:
    outcomes: list[GateOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def get(self, gate: str) -> GateOutcome | None:
        return next((o for o in self.outcomes if o.gate == gate), None)

    @property
    def failed(self) -> list[str]:
        return [o.gate for o in self.outcomes if o.status == FAIL]

    @property
    def unknown(self) -> list[str]:
        return [o.gate for o in self.outcomes if o.status == UNKNOWN]

    @property
    def needs_human(self) -> list[str]:
        return [o.gate for o in self.outcomes if o.status == NEEDS_HUMAN]

    @property
    def coverage(self) -> float:
        if not self.outcomes:
            return 0.0
        ran = sum(1 for o in self.outcomes if o.status != UNKNOWN)
        return round(ran / len(self.outcomes), 3)

    @property
    def releasable(self) -> bool:
        """No failure, and nothing waiting on a person.

        An `unknown` gate does NOT block release — blocking on every gate we
        have not built yet would stop the pipeline dead — but `coverage` is
        published beside this so "releasable" can never be read as "checked"."""
        return not self.failed and not self.needs_human

    def as_dict(self) -> dict:
        return {
            "outcomes": [o.as_dict() for o in self.outcomes],
            "failed": self.failed,
            "unknown": self.unknown,
            "needs_human": self.needs_human,
            "coverage": self.coverage,
            "releasable": self.releasable,
            "undetectable_slop_signals": dict(SLOP_SIGNALS_NOT_DETECTABLE),
            "note": (
                "`releasable` means no gate failed and none is waiting on a "
                "person. It does NOT mean the video was checked on every "
                "dimension — read `coverage` and `unknown` for that."
            ),
            "notes": list(self.notes),
        }


from omnicast.shared.numbers import flag as _flag  # noqa: E402
from omnicast.shared.numbers import num as _num  # noqa: E402
from omnicast.shared.numbers import rate as _rate  # noqa: E402
from omnicast.shared.numbers import ratio as _ratio  # noqa: E402


def _numeric_mapping(value) -> dict[str, float] | None:
    """A dict whose values are all real numbers, or None.

    `sum(transition_mix.values())` on a dict holding `None` or `"5"` raised out
    of `run_gates` and took EVERY gate with it — the pipeline's bare except then
    recorded `coverage=None, failed=[]`, which downstream is indistinguishable
    from a clean report."""
    if not isinstance(value, dict):
        return None
    out: dict[str, float] = {}
    for key, raw in value.items():
        number = _num(raw)
        if number is None:
            return None
        out[str(key)] = number
    return out


def _unknown(gate: str, *inputs: str) -> GateOutcome:
    return GateOutcome(
        gate=gate, status=UNKNOWN, missing_inputs=list(inputs),
        reason=(f"did not run: {', '.join(inputs)} not supplied. An unrun gate "
                "is neither a pass nor a failure, and it is the one that gets "
                "hidden"))


def run_gates(evidence: dict) -> QualityReport:
    """Run every §9 gate the supplied evidence can support.

    `evidence` is assembled by the caller from things that already exist:
    the script, the storyboard, `analytics.av_forensics`, `media.output_audit`,
    the compliance checker and the channel profile."""
    evidence = evidence or {}
    report = QualityReport()

    # ── research accuracy & provenance (§6, §9) ──────────────────────────────
    claims = _num(evidence.get("claim_count"))
    sourced = _num(evidence.get("sourced_claim_count"))
    if claims is None or sourced is None:
        report.outcomes.append(_unknown("research_accuracy", "claim_count",
                                        "sourced_claim_count"))
    elif claims <= 0:
        report.outcomes.append(GateOutcome(
            "research_accuracy", WARN,
            "the script makes no checkable claim at all — §9 calls this "
            "'nói nhiều nhưng không có proof'", {"claim_count": 0}))
    else:
        # `high=1.0`: more sourced claims than claims is a counting error, not a
        # 120% pass.
        share = _ratio(sourced, claims, high=1.0)
        if share is None:
            report.outcomes.append(GateOutcome(
                "research_accuracy", UNKNOWN,
                f"{sourced:.0f} sourced of {claims:.0f} claims is not a share — "
                "the two counts do not describe the same set",
                {"claim_count": claims, "sourced_claim_count": sourced},
                missing_inputs=["sourced_claim_count"]))
        else:
            report.outcomes.append(GateOutcome(
                "research_accuracy", PASS if share >= 0.5 else FAIL,
                f"{sourced:.0f} of {claims:.0f} claims carry a source ({share:.0%})",
                {"sourced_ratio": round(share, 3)}))

    citations = evidence.get("citations")
    # A LIST, specifically. Iterating a single citation dict yields its KEYS, so
    # one well-formed citation object was reported as an unsourced failure; an
    # int raised and destroyed the whole report.
    if not isinstance(citations, (list, tuple)):
        report.outcomes.append(_unknown("source_provenance", "citations"))
        if citations is not None:
            report.get("source_provenance").reason += (
                " (a citation LIST is required; a single dict or a count is not one)")
    else:
        citations = list(citations)
        if not citations:
            # NO CITATIONS IS NOT A PROVENANCE FAILURE. This gate asks whether
            # the citations that exist resolve; whether there should have been
            # any is `research_accuracy`'s question, and it already answers it.
            # Failing here too punished one fact twice and blocked every script
            # that legitimately cites nothing.
            report.outcomes.append(GateOutcome(
                "source_provenance", UNKNOWN,
                "the script carries no citations to check — whether it should "
                "have is research_accuracy's question, not this one",
                {"total": 0}, missing_inputs=["citations"]))
        else:
            traceable = [c for c in citations
                         if isinstance(c, dict) and str(c.get("url") or "").strip()]
            report.outcomes.append(GateOutcome(
                "source_provenance",
                PASS if len(traceable) == len(citations) else FAIL,
                f"{len(traceable)} of {len(citations)} citations resolve to a URL "
                "— §9's 'fact có vẻ chính xác nhưng không truy vết được'",
                {"traceable": len(traceable), "total": len(citations)}))

    # ── script editorial ─────────────────────────────────────────────────────
    proof_rate = _num(evidence.get("proof_points_per_minute"))
    if proof_rate is not None and proof_rate < 0:
        proof_rate = None
    if proof_rate is None:
        report.outcomes.append(_unknown("script_editorial",
                                        "proof_points_per_minute"))
    else:
        # WARN, not FAIL. The proof-point floor has never been calibrated, and
        # the detector behind it is a keyword heuristic: a storytelling or
        # horror channel legitimately carries no percentages or citations. This
        # module's own rule is that gating on an uncalibrated number is how a
        # pipeline starts rejecting good work for reasons nobody can defend.
        report.outcomes.append(GateOutcome(
            "script_editorial",
            PASS if proof_rate >= MIN_PROOF_PER_MINUTE else WARN,
            f"{proof_rate:.2f} concrete proof points per minute "
            f"(soft floor {MIN_PROOF_PER_MINUTE}, NOT calibrated — this warns, "
            "it does not block)",
            {"proof_points_per_minute": proof_rate}))

    # ── audience fit ─────────────────────────────────────────────────────────
    fit = _num(evidence.get("audience_fit_score"))
    if fit is not None and not (0.0 <= fit <= 10.0):
        fit = None
    if fit is None:
        report.outcomes.append(_unknown("audience_fit", "audience_fit_score"))
    else:
        report.outcomes.append(GateOutcome(
            "audience_fit", PASS if fit >= 5.0 else WARN,
            f"audience fit {fit:.1f}/10 from the scorer's own dimension",
            {"audience_fit_score": fit}))

    # ── visual relevance & continuity ────────────────────────────────────────
    relevance = evidence.get("visual_relevance_passed")
    if relevance is None:
        report.outcomes.append(_unknown("visual_relevance",
                                        "visual_relevance_passed"))
    else:
        # `_flag`, not truthiness: `bool("no")` is True, and this is a gate.
        relevance = _flag(relevance)
        report.outcomes.append(GateOutcome(
            "visual_relevance", PASS if relevance else FAIL,
            "from media.output_audit.inspect_visual_relevance",
            {"passed": bool(relevance)}))

    # A share of shots outside 0-1 is a unit mistake, not a clean video:
    # `-1` used to PASS while printing "-100% of shots reuse an earlier visual".
    repeated = _rate(evidence.get("repeated_shot_ratio"))
    if repeated is None:
        report.outcomes.append(_unknown("continuity", "repeated_shot_ratio"))
    else:
        report.outcomes.append(GateOutcome(
            "continuity", PASS if repeated <= MAX_REPEATED_SHOT_RATIO else FAIL,
            f"{repeated:.0%} of shots reuse an earlier visual "
            f"(limit {MAX_REPEATED_SHOT_RATIO:.0%}) — §9's 'cảnh lặp lại'",
            {"repeated_shot_ratio": repeated}))

    # ── motion quality ───────────────────────────────────────────────────────
    motion_mix = _numeric_mapping(evidence.get("motion_mix"))
    transition_mix = _numeric_mapping(evidence.get("transition_mix"))
    if motion_mix is None or transition_mix is None or \
            any(v < 0 for v in transition_mix.values()):
        # A negative transition COUNT is a unit or accounting error, not a clean
        # video: `{"cut": -10, "dissolve": 5}` passed with a dissolve share of
        # -100%, and `{"cut": -5, "dissolve": 5}` summed to zero and reported
        # 500%.
        report.outcomes.append(_unknown("motion_quality", "motion_mix",
                                        "transition_mix"))
    else:
        total_transitions = sum(transition_mix.values())
        soft = (transition_mix.get("dissolve", 0.0) / total_transitions
                if total_transitions > 0 else 0.0)
        report.outcomes.append(GateOutcome(
            "motion_quality", PASS if soft <= MAX_TRANSITION_DENSITY else FAIL,
            f"{soft:.0%} of transitions are dissolves "
            f"(limit {MAX_TRANSITION_DENSITY:.0%}) — §9's 'quá nhiều "
            "zoom/crossfade'",
            {"dissolve_share": round(soft, 3), "motion_mix": motion_mix}))

    # ── sound design ─────────────────────────────────────────────────────────
    variance = _num(evidence.get("voice_rate_std_over_mean"))
    if variance is not None and variance < 0:
        variance = None
    if variance is None:
        report.outcomes.append(_unknown("sound_design",
                                        "voice_rate_std_over_mean"))
    else:
        report.outcomes.append(GateOutcome(
            "sound_design", PASS if variance >= MIN_VOICE_VARIANCE else FAIL,
            f"speaking-rate variance {variance:.3f} (floor {MIN_VOICE_VARIANCE}) "
            "— §9's 'voice đều và thiếu chủ ý'",
            {"voice_rate_std_over_mean": variance}))

    # ── packaging trust ──────────────────────────────────────────────────────
    caption_density = _rate(evidence.get("caption_density"))
    overpromise = evidence.get("hook_overpromises")
    if caption_density is None and overpromise is None:
        report.outcomes.append(_unknown("packaging_trust", "caption_density",
                                        "hook_overpromises"))
    else:
        problems = []
        if caption_density is not None and caption_density > MAX_CAPTION_DENSITY:
            problems.append(f"captions cover {caption_density:.0%} of runtime")
        if overpromise:
            problems.append("the hook promises more than the script delivers")
        report.outcomes.append(GateOutcome(
            "packaging_trust", FAIL if problems else PASS,
            "; ".join(problems) or "no overpromise or caption-wall signal",
            {"caption_density": caption_density,
             "hook_overpromises": bool(overpromise)}))

    # ── YMYL / compliance, and the human route ───────────────────────────────
    compliance = evidence.get("compliance_passed")
    if compliance is None:
        report.outcomes.append(_unknown("ymyl_compliance", "compliance_passed"))
    else:
        passed = _flag(compliance)
        report.outcomes.append(GateOutcome(
            "ymyl_compliance", PASS if passed else FAIL,
            "from the ComplianceChecker", {"passed": passed}))

    comparison = evidence.get("benchmark_headline")
    if comparison is None:
        raw_blockers = evidence.get("benchmark_blocked_by")
        # A string is not a list of blockers: iterating it produced
        # `['a', 'b', 'c']`.
        blockers = list(raw_blockers) if isinstance(raw_blockers, (list, tuple)) \
            else ([str(raw_blockers)] if raw_blockers else [])
        report.outcomes.append(GateOutcome(
            "benchmark_comparison", UNKNOWN,
            ("no headline similarity is available: " + "; ".join(blockers))
            if blockers else
            "no benchmark comparison was supplied",
            {"blocked_by": blockers},
            missing_inputs=["benchmark_headline"]))
    else:
        # `_num(...) or 0.0` was the one place in this file where an unparseable
        # input became a number: `"not-a-number"` produced a confident
        # "similarity 0%" WARN and counted as a gate that RAN, inflating coverage
        # precisely because the input was garbage.
        headline = _rate(comparison)
        if headline is None:
            report.outcomes.append(GateOutcome(
                "benchmark_comparison", UNKNOWN,
                f"benchmark_headline={comparison!r} is not a 0-1 similarity",
                {"supplied": repr(comparison)},
                missing_inputs=["benchmark_headline"]))
        else:
            report.outcomes.append(GateOutcome(
                "benchmark_comparison", PASS if headline >= 0.8 else WARN,
                f"similarity {headline:.0%} against the golden reference",
                {"headline": headline}))

    raw_ymyl = evidence.get("is_ymyl")
    is_flagship = _flag(evidence.get("is_flagship"))
    reviewed = _flag(evidence.get("human_reviewed"))

    if raw_ymyl is None and not is_flagship:
        # UNKNOWN IS NOT "NO" — and it is not "yes" either. Nothing upstream
        # ever set this, so it defaulted to False and every finance and health
        # video passed the human gate reporting "not YMYL". The risk class is
        # now INFERRED from the channel's niche at the call site; when even that
        # is unreadable the gate is `unknown`, which is this module's third
        # state and blocks nothing, rather than a pass that claims the video was
        # checked.
        report.outcomes.append(GateOutcome(
            "human_review", UNKNOWN,
            "cannot tell whether this is YMYL — no explicit flag and no niche "
            "to infer one from. This is not a finding that the video is low "
            "risk; it is a gate that did not run",
            {"is_ymyl": None, "ymyl_source": evidence.get("ymyl_source", "")},
            missing_inputs=["is_ymyl"]))
        if report.coverage < 1.0:
            report.notes.append(
                f"{len(report.unknown)} of {len(report.outcomes)} gates did not "
                "run for want of input — `releasable` says nothing about those")
        return report

    is_ymyl = _flag(raw_ymyl)
    if (is_ymyl or is_flagship) and not reviewed:
        report.outcomes.append(GateOutcome(
            "human_review", NEEDS_HUMAN,
            ("YMYL" if is_ymyl else "flagship") + " video without a recorded "
            "human review. The system does not mark its own homework where being "
            "wrong costs someone money or health",
            {"is_ymyl": is_ymyl, "is_flagship": is_flagship,
             "ymyl_source": evidence.get("ymyl_source", "")}))
    elif is_ymyl or is_flagship:
        report.outcomes.append(GateOutcome(
            "human_review", PASS, "human review recorded",
            {"reviewer": str(evidence.get("human_reviewer") or "")}))
    else:
        report.outcomes.append(GateOutcome(
            "human_review", PASS, "not YMYL and not flagship — no human gate",
            {"is_ymyl": False, "is_flagship": False}))

    if report.coverage < 1.0:
        report.notes.append(
            f"{len(report.unknown)} of {len(report.outcomes)} gates did not run "
            "for want of input — `releasable` says nothing about those")
    return report
