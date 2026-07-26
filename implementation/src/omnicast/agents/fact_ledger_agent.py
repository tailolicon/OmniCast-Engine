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
from pydantic import BaseModel, Field

from omnicast.agents.base import BaseAgent
from omnicast.compliance.fact_ledger import FactEntry, FactLedger, extract_numeric_claims

logger = structlog.get_logger()


class _LedgerDraft(BaseModel):
    entries: list[FactEntry] = Field(default_factory=list)
    needs_verification: list[str] = Field(
        default_factory=list,
        description="Claims the model could NOT attribute to a real source")


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
        prompt = (
            "Build the fact ledger for this script.\n\n"
            f"RULE YEAR: {current_year}. Preferred source families: {sources}.\n\n"
            "For EVERY load-bearing claim — every dollar amount, percentage, "
            "threshold, rule age, deadline, and every stated rule/law — emit one "
            "entry: {claim (as spoken), value (the figure verbatim), source_name "
            "(the real document, with its year, e.g. 'SSA 2026 Fact Sheet'), "
            "source_url (official page if known, else empty), as_of (the year the "
            "figure is valid for), year_sensitive (true for anything that changes "
            "by rule year: tax brackets, earnings limits, contribution limits, RMD "
            "ages, premium amounts), section (the script heading it appears in)}.\n\n"
            "The deterministic extractor found these numeric tokens — your entries "
            f"must cover ALL of them: {', '.join(numeric) if numeric else '(none)'}\n\n"
            "If you cannot attribute a figure to a REAL source you are confident "
            "exists, put the claim in needs_verification instead of inventing one.\n\n"
            "═══ SCRIPT ═══\n" + script_text
        )
        _, draft = await self.call_llm_structured(
            [{"role": "system", "content": self.system_prompt},
             {"role": "user", "content": prompt}],
            output_schema=_LedgerDraft,
            max_tokens=16000,
            temperature=0.1,
        )
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
