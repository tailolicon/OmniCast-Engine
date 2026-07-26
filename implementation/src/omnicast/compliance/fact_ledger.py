"""Fact-citation ledger for YMYL explainer scripts (flagship Phase B).

THE GAP THIS CLOSES: `output_audit.py` counts "claims" and bare URLs but admits
in its own comment that a real claim→source binding "needs the writer to emit
one, which nothing does yet". For a retirement-finance channel every number IS
the product, so the binding is now a first-class artifact with a fail-closed
gate:

  1. An LLM pass (FactLedgerAgent) extracts every load-bearing claim from the
     approved script and attributes each to a named source + as-of date.
  2. THIS module then validates deterministically — the LLM never grades itself:
       * COVERAGE — every numeric token the regex extractor finds in the script
         must be matched by some ledger entry (fail-closed: numbers with no
         ledger at all = blocked);
       * COMPLETENESS — every entry needs source_name + as_of; year-sensitive
         entries (tax thresholds, SS rules, limits) must carry the CURRENT year;
       * CONSISTENCY — an entry's claimed value must actually appear in the
         script (a ledger for a different draft is worthless).

HONESTY BOUNDARY (stated on the artifact itself): this gate proves every claim
is *attributed and dated*, not that it is *true*. Truth is what the mandatory
YMYL human review checks — the ledger's job is to make that review tractable
(one table, every number, its source) and to make unsourced claims impossible
to ship. Provenance: entries carry the extraction model + script SHA-256.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

# ── Models ────────────────────────────────────────────────────────────────────


class FactEntry(BaseModel):
    """One claim → source binding."""

    claim: str = Field(..., min_length=1, description="The claim as spoken in the script")
    value: str = Field("", description="The load-bearing number/threshold, verbatim")
    source_name: str = Field("", description="e.g. 'SSA 2026 fact sheet', 'IRS Rev. Proc. 2025-32'")
    source_url: str = Field("", description="Official URL when known; empty is allowed but flagged")
    as_of: str = Field("", description="Year or ISO date the figure is valid for, e.g. '2026'")
    year_sensitive: bool = Field(
        False,
        description="True for figures that change by rule-year (tax brackets, SS limits, RMD ages)")
    section: str = Field("", description="Script section/heading the claim appears in")


class FactLedger(BaseModel):
    entries: list[FactEntry] = Field(default_factory=list)
    script_sha256: str = ""
    extracted_by: str = ""
    extracted_at: str = ""

    def stamp(self, script_text: str, model: str) -> "FactLedger":
        return self.model_copy(update={
            "script_sha256": hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
            "extracted_by": model,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        })


class FactGateReport(BaseModel):
    passed: bool
    claim_count: int = 0
    covered_count: int = 0
    uncovered: list[str] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)
    stale_entries: list[str] = Field(default_factory=list)
    orphan_entries: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ── Deterministic claim extraction ───────────────────────────────────────────
# What counts as a load-bearing numeric claim in a finance script:
#   $1,234 / $1.2 million   dollar amounts
#   6.2% / 0.9%             percentages
#   12,300 / 168,600        comma-grouped figures (limits, thresholds)
#   age 62 / at 67          rule ages
#   2026 / 1983             years quoted as rule/source years
# Small bare integers ("three steps", "one form") are structure, not facts —
# excluded to keep the gate about figures someone could misquote.

_CLAIM_PATTERNS = [
    re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|k)\b)?", re.IGNORECASE),
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?%"),
    re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"),
    re.compile(r"\b(?:age|at|until|to|or|by|turn(?:s|ing)?|instead of|versus|vs\.?)"
               r"\s+(5[5-9]|6[0-9]|7[0-5])\b", re.IGNORECASE),
    re.compile(r"\b(19\d{2}|20\d{2})\b"),
]


def _digit_core(token: str) -> str:
    return re.sub(r"\D", "", token)


def extract_numeric_claims(text: str) -> list[str]:
    """All load-bearing numeric tokens in the script, deduplicated by digit core
    (\"$23,400\" and \"23,400\" are the same figure), original order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for pat in _CLAIM_PATTERNS:
        for m in pat.finditer(text):
            token = m.group(0).strip()
            core = _digit_core(token)
            if not core or core in seen:
                continue
            seen.add(core)
            out.append(token)
    return out


# ── Gate ─────────────────────────────────────────────────────────────────────


def gate_fact_ledger(
    script_text: str,
    ledger: FactLedger,
    *,
    current_year: int | None = None,
) -> FactGateReport:
    """Deterministic fail-closed validation of a ledger against ITS script."""
    year = current_year or datetime.now(timezone.utc).year
    report = FactGateReport(passed=False)

    claims = extract_numeric_claims(script_text)
    report.claim_count = len(claims)
    if not claims:
        # A finance script with no numbers is its own (different) problem — the
        # rubric's accuracy_trust handles it; the ledger gate has nothing to do.
        report.passed = True
        report.notes.append("no numeric claims found in script — ledger gate not applicable")
        return report

    if not ledger.entries:
        report.uncovered = claims
        report.notes.append(
            f"script contains {len(claims)} numeric claims but the ledger is empty — "
            "fail-closed: every figure needs a source before release")
        return report

    # Entry-side digit cores (from value first, claim text as fallback).
    entry_cores: set[str] = set()
    script_lower = script_text.lower()
    for i, e in enumerate(ledger.entries):
        label = f"entry {i + 1}: {e.claim[:60]}"
        # as_of + source_name join the coverage side so a spoken attribution
        # year ("SSA's 2026 fact sheet") is covered by the entry that carries
        # that date — an attribution year is not a separate claim to source.
        for tok in extract_numeric_claims(f"{e.value} {e.claim} {e.as_of} {e.source_name}"):
            entry_cores.add(_digit_core(tok))

        if not e.source_name.strip():
            report.invalid_entries.append(f"{label} — missing source_name")
        if not e.as_of.strip():
            report.invalid_entries.append(f"{label} — missing as_of date")
        else:
            m = re.search(r"(19|20)\d{2}", e.as_of)
            if not m:
                report.invalid_entries.append(f"{label} — as_of has no parseable year: '{e.as_of}'")
            elif e.year_sensitive and int(m.group(0)) < year:
                report.stale_entries.append(
                    f"{label} — year-sensitive figure dated {m.group(0)}, current rule year is {year}")

        # CONSISTENCY: the entry must be about THIS script. An entry whose value
        # never appears in the text is an orphan (stale ledger / hallucinated row).
        e_tokens = extract_numeric_claims(e.value) or extract_numeric_claims(e.claim)
        if e_tokens:
            script_cores = {_digit_core(t) for t in extract_numeric_claims(script_text)}
            if not any(_digit_core(t) in script_cores for t in e_tokens):
                report.orphan_entries.append(
                    f"{label} — its figure never appears in the script")
        elif e.claim.strip().lower()[:40] not in script_lower:
            report.orphan_entries.append(f"{label} — claim text not found in script")

    report.uncovered = [c for c in claims if _digit_core(c) not in entry_cores]
    report.covered_count = len(claims) - len(report.uncovered)

    report.passed = not (report.uncovered or report.invalid_entries
                         or report.stale_entries or report.orphan_entries)
    if report.uncovered:
        report.notes.append(
            f"{len(report.uncovered)} numeric claims have no ledger entry: "
            + ", ".join(report.uncovered[:8]))
    if report.stale_entries:
        report.notes.append("year-sensitive figures must cite the CURRENT rule year "
                            "(recency gate — brief §Phase B step 4)")
    return report


def render_markdown(ledger: FactLedger, report: FactGateReport | None = None) -> str:
    """Human-review table — one row per claim, its source, its date."""
    lines = [
        "# Fact ledger",
        "",
        f"- script_sha256: `{ledger.script_sha256}`",
        f"- extracted_by: {ledger.extracted_by} at {ledger.extracted_at}",
        "- This table proves ATTRIBUTION + RECENCY, not truth. Human YMYL review",
        "  must verify each figure against its source before upload.",
        "",
        "| # | Claim | Value | Source | As of | Year-sensitive |",
        "|---|---|---|---|---|---|",
    ]
    for i, e in enumerate(ledger.entries, 1):
        src = f"[{e.source_name}]({e.source_url})" if e.source_url else e.source_name
        lines.append(
            f"| {i} | {e.claim.replace('|', '/')} | {e.value.replace('|', '/')} "
            f"| {src.replace('|', '/')} | {e.as_of} | {'YES' if e.year_sensitive else ''} |")
    if report is not None:
        lines += ["", f"**Gate: {'PASSED' if report.passed else 'FAILED'}** — "
                      f"{report.covered_count}/{report.claim_count} claims covered"]
        for group, items in (("uncovered", report.uncovered),
                             ("invalid", report.invalid_entries),
                             ("stale", report.stale_entries),
                             ("orphan", report.orphan_entries)):
            for it in items:
                lines.append(f"- {group}: {it}")
    return "\n".join(lines) + "\n"
