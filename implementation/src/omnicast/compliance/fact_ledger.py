"""Fact-citation ledger for YMYL explainer scripts (flagship Phase B).

THE GAP THIS CLOSES: `output_audit.py` counts "claims" and bare URLs but admits
in its own comment that a real claim→source binding "needs the writer to emit
one, which nothing does yet". For a retirement-finance channel every number IS
the product, so the binding is now a first-class artifact with a fail-closed
gate:

  1. An LLM pass (FactLedgerAgent) extracts every load-bearing claim from the
     approved script and attributes each to a named source + as-of date.
  2. THIS module then validates deterministically — the LLM never grades itself:
       * COVERAGE — every numeric token the typed extractor finds in the script
         must be matched by some ledger entry (fail-closed: numbers with no
         ledger at all = blocked). Tokens carry a KIND (money/percent/age/year/
         day/plain) and a decimal VALUE, so "$6.2" never covers "age 62" and
         "30%" never covers "$30" (codex audit 2026-07-26, finding 2);
       * COMPLETENESS — every entry needs source_name + as_of;
       * RECENCY — year-sensitive figures must cite EXACTLY the current rule
         year (not past, not future); year-sensitivity is ALSO inferred
         deterministically from the claim text, so the model cannot wave it
         off (finding 3);
       * CONSISTENCY — an entry's claimed value must actually appear in the
         script (a ledger for a different draft is worthless).
  3. `render_precheck` + `audit_chart_spec` re-verify at RENDER time: the
     ledger must exist, have PASSED, and be SHA-bound to the exact script being
     rendered; every number a chart displays (values, labels, title, source)
     must be ledger-covered (findings 1 and 6).

KNOWN EXTRACTION LIMITS (stated, not hidden): spelled-out numbers beyond the
common "<word> percent" forms, unicode fractions (73½), and non-USD currencies
are not extracted — such figures are invisible to the coverage gate. The LLM
critic's accuracy_trust dimension and the mandatory human YMYL review remain
the layers for those.

HONESTY BOUNDARY (stated on the artifact itself): this gate proves every claim
is *attributed and dated*, not that it is *true*. Truth is what the mandatory
YMYL human review checks — the ledger's job is to make that review tractable
(one table, every number, its source) and to make unsourced claims impossible
to ship.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

# Exit code render paths use for a fact/chart audit failure. Distinct from a
# generic crash so the render step can refuse to retry/degrade on it — a
# compliance failure must never be "fixed" by falling back to --all-stock.
AUDIT_EXIT_CODE = 86

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
            "script_sha256": script_sha256(script_text),
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


def script_sha256(script_text: str) -> str:
    return hashlib.sha256(script_text.encode("utf-8")).hexdigest()


# ── Typed numeric extraction ─────────────────────────────────────────────────
# A token is (kind, value, raw). KINDS keep distinct claims distinct: "$62",
# "6.2%", "age 62" and "1962" are four different facts. `plain` (a bare or
# comma-grouped number) may match any kind of the same value — chart values and
# ledger `value` fields are often written unitless.

_WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}

_SCALE = {"k": 1_000.0, "thousand": 1_000.0, "million": 1_000_000.0,
          "billion": 1_000_000_000.0, "trillion": 1_000_000_000_000.0}


def _to_float(num: str) -> float:
    return float(num.replace(",", ""))


@dataclass(frozen=True)
class NumericToken:
    kind: str   # money | percent | age | year | day | plain
    value: float
    raw: str

    @property
    def key(self) -> tuple[str, float]:
        return (self.kind, self.value)


# Ordered: earlier patterns consume their span so "$23,400" is money, not also
# a plain comma-number, and "6.2%" is percent, not also a plain decimal.
_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("money", re.compile(
        r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million|billion|trillion)?\b",
        re.IGNORECASE)),
    # No trailing \b after "%": the symbol is non-word, so a boundary there
    # never matches and "30%" would be silently skipped.
    ("percent", re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s?(?:%|percent(?:age\s+points?)?\b)",
                           re.IGNORECASE)),
    ("percent_word", re.compile(
        r"\b(" + "|".join(_WORD_NUM) + r")\s+percent\b", re.IGNORECASE)),
    ("age", re.compile(
        r"\b(?:age|at|until|to|or|by|and|turn(?:s|ing)?|instead of|versus|vs\.?)"
        r"\s+(5[5-9]|6[0-9]|7[0-5])(?:\s?(?:½|and a half))?\b", re.IGNORECASE)),
    ("year", re.compile(r"\b((?:19|20)\d{2})\b")),
    ("day", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")),
    ("plain", re.compile(r"\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)\b")),
)


def numeric_tokens(text: str) -> list[NumericToken]:
    """All load-bearing numeric tokens, typed, deduplicated by (kind, value),
    original order kept. Small bare integers without a unit are structure
    ("3 steps"), not facts — deliberately excluded."""
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, NumericToken]] = []
    for kind, pat in _TOKEN_PATTERNS:
        for m in pat.finditer(text):
            span = m.span()
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue
            raw = m.group(0).strip()
            try:
                if kind == "percent_word":
                    tok = NumericToken("percent", float(_WORD_NUM[m.group(1).lower()]), raw)
                elif kind == "money":
                    scale = _SCALE.get((m.group(2) or "").lower(), 1.0)
                    tok = NumericToken("money", _to_float(m.group(1)) * scale, raw)
                else:
                    tok = NumericToken(kind, _to_float(m.group(1)), raw)
            except (TypeError, ValueError):
                continue
            taken.append(span)
            found.append((span[0], tok))
    found.sort(key=lambda t: t[0])
    seen: set[tuple[str, float]] = set()
    out: list[NumericToken] = []
    for _, tok in found:
        if tok.key in seen:
            continue
        seen.add(tok.key)
        out.append(tok)
    return out


def extract_numeric_claims(text: str) -> list[str]:
    """Raw display forms of the typed tokens (compat helper for prompts/UI)."""
    return [t.raw for t in numeric_tokens(text)]


def _matches(token: NumericToken, entry_tokens: set[tuple[str, float]],
             *, chart_side: bool = False) -> bool:
    """A script token is covered by an entry token of the same value when the
    kinds agree, with a limited unitless-`plain` bridge.

    The bridge is asymmetric on purpose (codex verify 2026-07-26): a ledger
    entry whose only token is a bare "30" must NOT cover a spoken "30%" or
    "age 62" — percent and age claims need an explicitly typed entry token
    (the claim text almost always carries the unit). Money/year/day may still
    interop with plain, because ledger `value` fields are routinely written
    unitless ("23,400"). On the CHART side the full bridge stays: chart_spec
    values are bare floats by schema, and each must equal a sourced figure of
    any kind — the value itself is what was sourced."""
    if token.key in entry_tokens:
        return True
    strict_kinds = () if chart_side else ("percent", "age")
    for kind, value in entry_tokens:
        if value != token.value:
            continue
        if kind == "plain" and token.kind in strict_kinds:
            continue
        if kind == "plain" or token.kind == "plain":
            return True
    return False


def uncovered_figures(text: str, ledger_data: dict) -> list[str]:
    """Figures in `text` with no sourced ledger entry (raw display forms).

    Used at render time to audit text the script-step gate never saw — the
    script.json sidecar narration and kinetic stat overlays — against the same
    ledger. Year tokens may be covered by entry as_of/source years (spoken
    attribution)."""
    entries = (ledger_data.get("ledger") or {}).get("entries") or []
    entry_tokens: set[tuple[str, float]] = set()
    attribution_years: set[float] = set()
    for e in entries:
        for tok in numeric_tokens(f"{e.get('value', '')} {e.get('claim', '')}"):
            entry_tokens.add(tok.key)
        for tok in numeric_tokens(f"{e.get('as_of', '')} {e.get('source_name', '')}"):
            if 1900 <= tok.value <= 2099:
                attribution_years.add(tok.value)
    out: list[str] = []
    for tok in numeric_tokens(text):
        if _matches(tok, entry_tokens):
            continue
        if tok.kind == "year" and tok.value in attribution_years:
            continue
        out.append(tok.raw)
    return out


# Claims whose figures change with the rule year — year-sensitivity is inferred
# from the TEXT, not trusted from the model (codex finding 3).
_YEAR_SENSITIVE_RE = re.compile(
    r"\b(limit|threshold|bracket|premium|deductible|contribution|cap|"
    r"rmd|required minimum|irmaa|cola|earnings test|exempt amount|"
    r"standard deduction|wage base)\b", re.IGNORECASE)


def _entry_year_sensitive(e: FactEntry) -> bool:
    return bool(e.year_sensitive
                or _YEAR_SENSITIVE_RE.search(f"{e.claim} {e.source_name}"))


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

    claims = numeric_tokens(script_text)
    report.claim_count = len(claims)
    if not claims:
        # A finance script with no numbers is its own (different) problem — the
        # rubric's accuracy_trust handles it; the ledger gate has nothing to do.
        report.passed = True
        report.notes.append("no numeric claims found in script — ledger gate not applicable")
        return report

    if not ledger.entries:
        report.uncovered = [t.raw for t in claims]
        report.notes.append(
            f"script contains {len(claims)} numeric claims but the ledger is empty — "
            "fail-closed: every figure needs a source before release")
        return report

    entry_tokens: set[tuple[str, float]] = set()
    # Attribution years get their own, YEAR-ONLY coverage channel: a spoken
    # "SSA's 2026 fact sheet" is covered by an entry dated 2026, but as_of can
    # never cover a money/percent value (codex finding 2: "$2,026" masking).
    attribution_years: set[float] = set()
    script_lower = script_text.lower()
    script_keys = {t.key for t in claims}

    for i, e in enumerate(ledger.entries):
        label = f"entry {i + 1}: {e.claim[:60]}"
        for tok in numeric_tokens(f"{e.value} {e.claim}"):
            entry_tokens.add(tok.key)
        for tok in numeric_tokens(f"{e.as_of} {e.source_name}"):
            if tok.kind in ("year", "plain") and 1900 <= tok.value <= 2099:
                attribution_years.add(tok.value)

        if not e.source_name.strip():
            report.invalid_entries.append(f"{label} — missing source_name")
        if not e.as_of.strip():
            report.invalid_entries.append(f"{label} — missing as_of date")
        else:
            m = re.search(r"(19|20)\d{2}", e.as_of)
            if not m:
                report.invalid_entries.append(f"{label} — as_of has no parseable year: '{e.as_of}'")
            else:
                as_of_year = int(m.group(0))
                if as_of_year > year:
                    report.invalid_entries.append(
                        f"{label} — as_of {as_of_year} is in the future (current year {year})")
                elif (_entry_year_sensitive(e) and as_of_year != year
                      and str(as_of_year) not in e.claim):
                    # A claim that NAMES its own as_of year ("the 2025 figures
                    # won't match…", "built in 1939") is a self-consistent
                    # historical reference, not a stale current-rule figure —
                    # the keyword heuristic false-flagged exactly those two
                    # (live 27/07). A current-rule figure quoted from an old
                    # year still fails, because its claim names no year or a
                    # different one.
                    report.stale_entries.append(
                        f"{label} — year-sensitive figure dated {as_of_year}, current rule "
                        f"year is {year} (must cite the CURRENT year's figure)")

        # CONSISTENCY: the entry must be about THIS script. An entry whose value
        # never appears in the text is an orphan (stale ledger / hallucinated row).
        e_tokens = numeric_tokens(e.value) or numeric_tokens(e.claim)
        # Rate-shorthand exemption: an entry describing "$1 per $2/$3" mechanics
        # carries tiny money tokens the SPOKEN script renders as words ("one
        # dollar per two") — for all-tiny-token entries the claim-text check is
        # the meaningful one (live orphan class 27/07).
        if e_tokens and not all(t.value <= 3 for t in e_tokens):
            if not any(_matches(t, script_keys) for t in e_tokens):
                report.orphan_entries.append(
                    f"{label} — its figure never appears in the script")
        elif e.claim.strip().lower()[:40] not in script_lower:
            report.orphan_entries.append(f"{label} — claim text not found in script")

    uncovered: list[str] = []
    for tok in claims:
        if _matches(tok, entry_tokens):
            continue
        if tok.kind == "year" and tok.value in attribution_years:
            continue
        uncovered.append(tok.raw)
    report.uncovered = uncovered
    report.covered_count = report.claim_count - len(uncovered)

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


# ── Render-time checks (codex findings 1, 6, 7) ──────────────────────────────


def render_precheck(ledger_path: Path, script_text: str) -> tuple[bool, str]:
    """Whether a finance-rubric script may be RENDERED at all.

    The ledger must exist, be gate-PASSED, and be SHA-bound to exactly this
    script text — otherwise any manual/legacy/--all-stock render path could
    ship a video whose numbers nobody sourced."""
    if not ledger_path.exists():
        return False, ("fact_ledger.json missing — a finance-rubric script cannot "
                       "render without a passed fact ledger")
    try:
        import json as _json
        data = _json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"fact_ledger.json unreadable: {exc}"
    if not (data.get("gate") or {}).get("passed"):
        return False, "fact ledger gate did not pass — fix citations, re-run the script step"
    want = (data.get("ledger") or {}).get("script_sha256", "")
    have = script_sha256(script_text)
    if not want or want != have:
        return False, (f"fact ledger is bound to a different script "
                       f"(ledger sha {want[:12]}…, script sha {have[:12]}…)")
    return True, ""


def audit_chart_spec(spec: dict, ledger_data: dict, script_text: str) -> list[str]:
    """Failures preventing a chart cell from rendering. Empty list = clean.

    EVERYTHING the chart displays is audited — values, labels, title and the
    source line — because an unsourced number in a label misleads exactly as
    much as one in a bar (codex finding 6)."""
    failures: list[str] = []
    gate = ledger_data.get("gate") or {}
    if not gate.get("passed"):
        failures.append("fact ledger gate not passed")
    ledger = ledger_data.get("ledger") or {}
    if ledger.get("script_sha256") != script_sha256(script_text):
        failures.append("fact ledger bound to a different script (sha mismatch)")

    entry_tokens: set[tuple[str, float]] = set()
    real_tokens: set[tuple[str, float]] = set()
    hypo_tokens: set[tuple[str, float]] = set()
    attribution_years: set[float] = set()
    for e in ledger.get("entries") or []:
        _src = str(e.get("source_name", "")).lower()
        _is_example = "hypothetical" in _src or "worked example" in _src
        for tok in numeric_tokens(f"{e.get('value', '')} {e.get('claim', '')}"):
            entry_tokens.add(tok.key)
            (hypo_tokens if _is_example else real_tokens).add(tok.key)
        for tok in numeric_tokens(f"{e.get('as_of', '')} {e.get('source_name', '')}"):
            if 1900 <= tok.value <= 2099:
                attribution_years.add(tok.value)

    values = spec.get("values") or []
    example_only_values: list = []
    collision_values: list = []
    real_only_present = False
    for v in values:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            failures.append(f"non-numeric chart value: {v!r}")
            continue
        # No abs(): a negative bar is a different figure from its positive —
        # a ledger entry for 62 must not authorise -62 (codex verify).
        tok = NumericToken("plain", fv, str(v))
        if not _matches(tok, entry_tokens, chart_side=True):
            failures.append(f"chart value {v} has no ledger entry")
            continue
        in_real = _matches(tok, real_tokens, chart_side=True)
        in_hypo = _matches(tok, hypo_tokens, chart_side=True)
        if in_real and in_hypo:
            collision_values.append(v)
        elif in_real:
            real_only_present = True
        else:
            example_only_values.append(v)

    # SOURCE ATTRIBUTION (codex render audit): a chart whose values include a
    # figure covered ONLY by worked-example entries must SAY so in its source
    # line — crediting an authority ("SSA 2026") over hypothetical numbers is
    # a misattribution on a YMYL video. COLLISION values ($2,040 is BOTH the
    # real monthly limit AND the example benefit) cannot prove real context by
    # themselves: without at least one real-only anchor value in the same
    # chart, the example must be declared too (codex verify round).
    _needs_example = bool(example_only_values) or (
        bool(collision_values) and not real_only_present)
    if _needs_example:
        _src_text = str(spec.get("source") or "").lower()
        if not any(w in _src_text for w in ("example", "hypothetical", "illustrative")):
            _vals = example_only_values or collision_values
            failures.append(
                f"chart values {_vals} are worked-example figures (or ambiguous "
                "real/example collisions with no real-only anchor) — the source "
                "line must declare the example (e.g. 'Worked example'), not "
                "credit an authority")

    # Attribution years may cover the SOURCE line only ("SSA 2026") — a year in
    # a label or the title is a displayed claim and needs a typed entry token
    # (codex verify: globally pooled years covered unrelated chart text).
    label_title_text = " | ".join(
        [str(x) for x in (spec.get("labels") or [])] + [str(spec.get("title") or "")])
    for tok in numeric_tokens(label_title_text):
        if _matches(tok, entry_tokens):
            continue
        failures.append(f"chart text figure '{tok.raw}' has no ledger entry")
    for tok in numeric_tokens(str(spec.get("source") or "")):
        if _matches(tok, entry_tokens):
            continue
        if tok.kind in ("year", "plain") and tok.value in attribution_years:
            continue
        failures.append(f"chart source figure '{tok.raw}' has no ledger entry")
    return failures


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
            f"| {src.replace('|', '/')} | {e.as_of} | "
            f"{'YES' if _entry_year_sensitive(e) else ''} |")
    if report is not None:
        lines += ["", f"**Gate: {'PASSED' if report.passed else 'FAILED'}** — "
                      f"{report.covered_count}/{report.claim_count} numeric tokens covered "
                      "(entries may outnumber tokens: prose claims and multi-entry figures)"]
        for group, items in (("uncovered", report.uncovered),
                             ("invalid", report.invalid_entries),
                             ("stale", report.stale_entries),
                             ("orphan", report.orphan_entries)):
            for it in items:
                lines.append(f"- {group}: {it}")
    return "\n".join(lines) + "\n"
