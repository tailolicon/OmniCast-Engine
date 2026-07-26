"""FactLedgerAgent — builds the claim→source ledger for a YMYL finance script.

Division of labour (deliberate):
  * The LLM proposes the binding (which figures are claims, which official
    source + rule year each belongs to). It is good at attribution and useless
    as its own auditor.
  * `compliance.fact_ledger.gate_fact_ledger` then validates DETERMINISTICALLY —
    coverage of every regex-extracted figure, source+date completeness, current
    rule-year recency, and that the ledger actually describes this script.

The agent must attribute to the sources the niche declares (SSA, IRS, CFPB,
FBI IC3, published fund research). If it cannot name a real source for a claim,
it must say so via needs_verification=true — the gate treats such entries as
invalid (missing source), which blocks release. That is the point: an
unattributable number must not survive to upload.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field, field_validator

from omnicast.agents.base import BaseAgent
from omnicast.compliance.fact_ledger import FactEntry, FactLedger, extract_numeric_claims

logger = structlog.get_logger()


class _LedgerDraft(BaseModel):
    # REQUIRED with min_length=1 on purpose: every field defaulted meant ANY
    # stray {...} blob in the response validated as an empty ledger (live
    # 27/07: 20k tokens of model output parsed to zero entries, silently).
    # A script with no facts never reaches this agent; a draft with no entries
    # is always a parse failure and must raise, not pass.
    entries: list[FactEntry] = Field(..., min_length=1)
    needs_verification: list[str] = Field(
        default_factory=list,
        description="Claims the model could NOT attribute to a real source")

    @field_validator("needs_verification", mode="before")
    @classmethod
    def _coerce_items(cls, v):
        """Models sometimes return rich dicts here ({'claim': …, 'reason': …})
        instead of plain strings — live run 2026-07-27 crashed the whole step
        on that. Coerce instead: the claim text is what the gate needs."""
        if not isinstance(v, list):
            return v
        out = []
        for item in v:
            if isinstance(item, dict):
                out.append(str(item.get("claim") or item.get("text") or item))
            else:
                out.append(str(item))
        return out


class FactLedgerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "fact_ledger"

    @property
    def system_prompt(self) -> str:
        return (
            "You are a meticulous fact-checking editor for a retirement-finance "
            "channel. You bind every load-bearing claim in a script to a named "
            "official source and the year the figure is valid for. You NEVER invent "
            "a source: if you are not certain which real document a figure comes "
            "from, you list that claim under needs_verification instead of guessing. "
            "ALWAYS respond with valid JSON only."
        )

    async def execute(
        self,
        script_text: str,
        *,
        proof_sources: list[str] | None = None,
        current_year: int,
        model_label: str = "",
    ) -> FactLedger:
        numeric = extract_numeric_claims(script_text)
        sources = ", ".join(proof_sources or []) or "SSA (ssa.gov), IRS (irs.gov), CFPB, FBI IC3"
        base_rules = (
            f"RULE YEAR: {current_year}. Preferred source families: {sources}.\n\n"
            "For EVERY load-bearing claim — every dollar amount, percentage, "
            "threshold, rule age, deadline, historical year, and every stated "
            "rule/law — emit one entry with ALL of these fields filled: claim (as "
            "spoken), value (the figure verbatim), source_name (the real document "
            "with its year, e.g. 'SSA 2026 Fact Sheet'), source_url (official page "
            "if known, else empty), as_of (the year the figure is valid for — "
            "REQUIRED, never empty), year_sensitive (true for anything that changes "
            "by rule year: earnings limits, brackets, premiums), section (the "
            "script heading it appears in).\n\n"
            "HYPOTHETICAL WORKED-EXAMPLE figures (an invented income, benefit "
            "amount, or hourly wage used purely for illustration) get "
            f"source_name='worked example (hypothetical)' and as_of='{current_year}' "
            "with year_sensitive=false — they still need their own entries so the "
            "human reviewer can tell example numbers from rule numbers.\n"
            "HISTORICAL years (a law's year, an era) get the act/document as "
            "source_name and that year as as_of.\n\n"
            "If you cannot attribute a REAL figure to a real source you are "
            "confident exists, put the claim in needs_verification instead of "
            "inventing one.\n\n"
        )
        # The client does NOT inject the schema — the model only knows the
        # shape we show it (the critic's reliability comes from exactly this
        # kind of embedded template; live 27/07 the ledger model produced 20k
        # tokens of prose because no template was ever shown).
        json_template = (
            "═══ REQUIRED JSON OUTPUT — respond with ONLY this JSON object, "
            "no prose before or after, no markdown fences ═══\n"
            "{\n"
            '  "entries": [\n'
            '    {"claim": "<the claim as spoken>", "value": "<figure verbatim>", '
            '"source_name": "<document + year>", "source_url": "", '
            '"as_of": "<year>", "year_sensitive": false, "section": "<heading>"}\n'
            "  ],\n"
            '  "needs_verification": ["<claim you could not source>"]\n'
            "}\n"
            "One object in entries per claim. entries must NOT be empty.\n\n"
        )
        prompt = (
            "Build the fact ledger for this script.\n\n" + base_rules +
            "The deterministic extractor found these numeric tokens — your entries "
            f"must cover ALL of them: {', '.join(numeric) if numeric else '(none)'}\n\n"
            + json_template +
            "═══ SCRIPT ═══\n" + script_text
        )
        _, draft = await self.call_llm_structured(
            [{"role": "system", "content": self.system_prompt},
             {"role": "user", "content": prompt}],
            output_schema=_LedgerDraft,
            max_tokens=16000,
            temperature=0.1,
        )

        # ONE deterministic repair round: gate the draft locally and hand the
        # model its exact gaps (live 27/07: first pass covered 7/19 tokens and
        # left source/as_of empty — a generic "cover everything" ask was not
        # enough; an itemised deficiency list is).
        from omnicast.compliance.fact_ledger import gate_fact_ledger
        probe = FactLedger(entries=list(draft.entries))
        report = gate_fact_ledger(script_text, probe, current_year=current_year)
        if not report.passed and (report.uncovered or report.invalid_entries):
            gaps = (
                "Your ledger draft has DEFICIENCIES. Return the COMPLETE corrected "
                "ledger (all previous entries, fixed, plus the missing ones).\n\n"
                + base_rules
                + "UNCOVERED numeric tokens (each needs an entry):\n- "
                + "\n- ".join(report.uncovered[:30] or ["(none)"])
                + "\n\nINVALID entries (fix these fields):\n- "
                + "\n- ".join(report.invalid_entries[:30] or ["(none)"])
                + "\n\n" + json_template
                + "═══ SCRIPT ═══\n" + script_text
            )
            try:
                _, draft2 = await self.call_llm_structured(
                    [{"role": "system", "content": self.system_prompt},
                     {"role": "user", "content": gaps}],
                    output_schema=_LedgerDraft,
                    max_tokens=16000,
                    temperature=0.1,
                )
                if draft2.entries:
                    draft = draft2
            except Exception as exc:  # noqa: BLE001 — keep round-1 draft
                logger.warning("fact_ledger repair round failed", error=str(exc)[:150])
        if draft.needs_verification:
            logger.warning("fact_ledger: unattributable claims",
                           count=len(draft.needs_verification),
                           first=draft.needs_verification[:3])
        # Unattributable claims become explicit invalid entries (empty source) so
        # the gate counts them as blockers instead of them silently vanishing.
        entries = list(draft.entries) + [
            FactEntry(claim=c, value="", source_name="", as_of="",
                      year_sensitive=False, section="NEEDS VERIFICATION")
            for c in draft.needs_verification
        ]
        return FactLedger(entries=entries).stamp(script_text, model_label or "llm")
