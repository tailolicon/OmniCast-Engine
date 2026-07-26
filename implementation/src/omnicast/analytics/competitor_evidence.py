"""Evidence validator for three-tier competitor research (Native Research Engine).

THE LAYER THAT WAS MISSING (GPT review 2026-07-26, verified): `intel_gate`
decides whether a COMPILED playbook may reach the Writer (controlled? fresh?
provenance?). Nothing verified the EVIDENCE a finding claims to rest on — an
LLM synthesis stage can name pairs that were never matched, quote lines that
exist in no transcript, report frequencies it never counted, and smuggle a
competitor's signature sentence into a "reusable rule". This module checks all
of that in code, before any compiler runs. The LLM proposes; this validates;
the compiler compiles; intel_gate gates. Four layers, each with one job.

Everything here is pure functions over plain data — no LLM, no network, no DB.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

# ── Schemas (tier C output — what the synthesis stage must emit) ─────────────


class PairEvidence(BaseModel):
    winner_id: str
    control_id: str
    winner_excerpt: str = Field("", description="<=20 words, verbatim from winner transcript")
    control_excerpt: str = Field("", description="<=20 words, verbatim from control transcript")
    winner_timestamp_s: int | None = None
    control_timestamp_s: int | None = None


class CohortFinding(BaseModel):
    finding_id: str
    hypothesis: str
    finding_type: str = "correlational"
    matched_pairs_examined: int = 0
    winner_frequency: float = 0.0   # LLM-reported — recomputed, never trusted
    control_frequency: float = 0.0  # LLM-reported — recomputed, never trusted
    supporting_pairs: list[PairEvidence] = Field(default_factory=list)
    counterexample_pairs: list[PairEvidence] = Field(
        default_factory=list,
        description="Pairs where the winner lacks the trait or the control has it")
    alternative_explanations: list[str] = Field(default_factory=list)
    confidence: str = "low"
    reusable_rule: str = ""
    do_not_copy: list[str] = Field(default_factory=list)
    # Provenance (stamped by the runner, required by the validator)
    research_run_id: str = ""
    model: str = ""
    prompt_version: str = ""


class FindingVerdict(BaseModel):
    finding_id: str
    accepted: bool
    reasons: list[str] = Field(default_factory=list)
    recomputed_winner_frequency: float | None = None
    recomputed_control_frequency: float | None = None


class ValidationReport(BaseModel):
    accepted: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    verdicts: list[FindingVerdict] = Field(default_factory=list)
    validated_at: str = ""


# ── Validation config (thresholds stated openly, arguable, not buried) ───────

MIN_MATCHED_PAIRS = 3          # a pattern seen in fewer pairs is a weak_signal
MIN_FREQUENCY_GAP = 0.25       # winner_freq - control_freq must exceed this
MAX_EXCERPT_WORDS = 20
# A reusable rule sharing this many consecutive words with any transcript is
# copying a competitor's phrasing, not extracting a mechanism.
VERBATIM_NGRAM = 8


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def _norm_ws(text: str) -> str:
    return " ".join(_norm(text).split())


def excerpt_in_transcript(excerpt: str, transcript: str) -> bool:
    """Whitespace/case/punctuation-insensitive containment."""
    e = _norm_ws(excerpt)
    return bool(e) and e in _norm_ws(transcript)


def rule_copies_transcript(rule: str, transcripts: dict[str, str],
                           ngram: int = VERBATIM_NGRAM) -> str:
    """First transcript id whose text shares an `ngram`-word run with the rule,
    else empty string."""
    words = _norm_ws(rule).split()
    if len(words) < ngram:
        return ""
    grams = {" ".join(words[i:i + ngram]) for i in range(len(words) - ngram + 1)}
    for vid, text in transcripts.items():
        t = _norm_ws(text)
        if any(g in t for g in grams):
            return vid
    return ""


def validate_findings(
    findings: list[CohortFinding],
    *,
    matched_pairs: dict[str, str],
    transcripts: dict[str, str],
    durations_s: dict[str, int] | None = None,
    min_pairs: int = MIN_MATCHED_PAIRS,
    min_gap: float = MIN_FREQUENCY_GAP,
) -> ValidationReport:
    """Deterministic accept/reject per finding.

    matched_pairs: winner_id -> control_id (the ONLY legal pairings, from the
    cohort selector). transcripts: video_id -> full transcript text.
    durations_s: video_id -> duration (timestamp bounds; skipped if absent).
    """
    report = ValidationReport(
        validated_at=datetime.now(timezone.utc).isoformat())
    durations = durations_s or {}

    for f in findings:
        reasons: list[str] = []

        if f.finding_type != "correlational":
            reasons.append(f"finding_type must be 'correlational', got '{f.finding_type}'")
        if not (f.research_run_id and f.model and f.prompt_version):
            reasons.append("missing provenance (research_run_id/model/prompt_version)")
        if not f.alternative_explanations:
            reasons.append("no alternative explanation offered")

        valid_support = 0
        for p in f.supporting_pairs + f.counterexample_pairs:
            tag = f"{p.winner_id}/{p.control_id}"
            if p.winner_id not in transcripts:
                reasons.append(f"{tag}: winner_id not in corpus manifest")
                continue
            if matched_pairs.get(p.winner_id) != p.control_id:
                reasons.append(f"{tag}: not a legal matched pair "
                               f"(control of {p.winner_id} is "
                               f"{matched_pairs.get(p.winner_id, 'NONE')})")
                continue
            pair_ok = True
            for side, excerpt, ts in (
                ("winner", p.winner_excerpt, p.winner_timestamp_s),
                ("control", p.control_excerpt, p.control_timestamp_s),
            ):
                vid = p.winner_id if side == "winner" else p.control_id
                if excerpt:
                    if len(excerpt.split()) > MAX_EXCERPT_WORDS:
                        reasons.append(f"{tag}: {side} excerpt over {MAX_EXCERPT_WORDS} words")
                        pair_ok = False
                    elif not excerpt_in_transcript(excerpt, transcripts.get(vid, "")):
                        reasons.append(f"{tag}: {side} excerpt not found in transcript of {vid}")
                        pair_ok = False
                if ts is not None and vid in durations and not (0 <= ts <= durations[vid]):
                    reasons.append(f"{tag}: {side} timestamp {ts}s outside video duration")
                    pair_ok = False
            if pair_ok and p in f.supporting_pairs:
                if not (p.winner_excerpt and p.control_excerpt):
                    reasons.append(f"{tag}: supporting pair needs evidence from BOTH sides")
                else:
                    valid_support += 1

        examined = max(f.matched_pairs_examined,
                       len(f.supporting_pairs) + len(f.counterexample_pairs))
        if examined < min_pairs or valid_support < min_pairs:
            reasons.append(
                f"only {valid_support} validated supporting pairs of {examined} examined "
                f"(need >= {min_pairs}) — goes to weak_signals, not to a rule")

        # Frequencies are RECOMPUTED — the LLM's numbers are never trusted.
        w_freq = (valid_support / examined) if examined else 0.0
        c_freq = (len(f.counterexample_pairs) / examined) if examined else 0.0
        if (w_freq - c_freq) < min_gap:
            reasons.append(
                f"recomputed frequency gap {w_freq - c_freq:.2f} below {min_gap} — "
                "trait does not separate winners from controls")

        src = rule_copies_transcript(f.reusable_rule, transcripts)
        if src:
            reasons.append(
                f"reusable_rule shares a {VERBATIM_NGRAM}-word run with transcript "
                f"{src} — that is copying a competitor's phrasing, not a mechanism")

        verdict = FindingVerdict(
            finding_id=f.finding_id, accepted=not reasons, reasons=reasons,
            recomputed_winner_frequency=round(w_freq, 3),
            recomputed_control_frequency=round(c_freq, 3))
        report.verdicts.append(verdict)
        (report.accepted if verdict.accepted else report.rejected).append(f.finding_id)
    return report
