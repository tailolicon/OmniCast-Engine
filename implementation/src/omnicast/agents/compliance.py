"""Compliance Checker — gate before upload."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft
from omnicast.models.enums import Niche
from omnicast.shared.errors import ComplianceError

logger = structlog.get_logger()

# YMYL niches that need extra compliance
YMYL_NICHES = {Niche.FINANCE, Niche.HEALTH}

# Required compliance checks
COMPLIANCE_CHECKS = [
    "ai_disclosure",
    "no_copyright_content",
    "ftc_disclosure",
    "no_coppa_violation",
    "no_misleading_claims",
    "cross_channel_unique",
]


class ComplianceChecker(BaseAgent):
    """Gate agent — checks script compliance before upload.

    Returns (passed: bool, violations: list[str]).
    Any violation = script blocked from upload.
    """

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    @property
    def name(self) -> str:
        return "compliance"

    @property
    def system_prompt(self) -> str:
        """Prompt: strict compliance auditor. Augments base rules with active DB rules."""
        base = (
            "You are a strict YouTube compliance auditor. "
            "Check scripts for: AI disclosure, copyright issues, "
            "FTC disclosures, COPPA violations, misleading claims. "
            "Return 'PASS' if compliant, or list specific violations."
        )
        try:
            from omnicast.vault.db import get_active_rules
            active = get_active_rules()
            if active:
                rule_lines = "\n".join(f"- {r['rule_text']}" for r in active)
                base += (
                    f"\n\nADDITIONAL ACTIVE POLICY RULES (updated {len(active)} rules):\n"
                    f"{rule_lines}\n"
                    "Apply ALL rules above strictly."
                )
        except Exception:
            pass  # DB unavailable → use base prompt only
        return base

    async def execute(
        self,
        draft: ScriptDraft,
        *,
        niche: Niche = Niche.TECH,
    ) -> tuple[bool, list[str]]:
        """Check script compliance."""
        violations = []

        # Rule-based checks
        ai_violation = self._check_ai_disclosure(draft)
        if ai_violation:
            violations.append(ai_violation)

        coppa_violation = self._check_coppa(draft)
        if coppa_violation:
            violations.append(coppa_violation)

        # LLM-based checks for YMYL niches. Prompt is niche-specific — a script about
        # health content must be checked for medical-misinformation risks, not asked
        # a finance-worded question it will trivially "PASS" regardless of content.
        if self._is_ymyl(niche):
            if niche == Niche.HEALTH:
                from omnicast.upload.compliance import ComplianceChecker as UploadComplianceChecker

                full_text = draft.hook + "\n" + "\n".join(s.content for s in draft.segments) + "\n" + draft.outro
                violations.extend(
                    UploadComplianceChecker._check_ymyl_health_text(
                        draft.brief_title,
                        f"{full_text}\n{draft.description_template}",
                    )
                )

            if niche == Niche.HEALTH:
                ymyl_prompt = (
                    "You are a medical-content compliance auditor. Carefully check this "
                    "health script for:\n"
                    "1. FABRICATED CITATIONS — any specific study, journal name, year, or "
                    "statistic (e.g. '2022 study in Diabetes Care found a 60% higher rate...') "
                    "that cannot be verified as a real, accurately-cited publication. Scripts "
                    "routinely invent plausible-sounding journal names + precise percentages "
                    "that do not correspond to any real paper — treat any specific numeric "
                    "study citation you cannot confirm as fabricated.\n"
                    "2. Dangerous or medically unsound advice (e.g. telling people to stop "
                    "prescribed medication, unsafe dosing, treating a serious symptom as minor).\n"
                    "3. Guaranteed-cure or guaranteed-outcome claims.\n\n"
                    "Reply with ONLY 'PASS' if compliant, or 'FAIL: <reason>' if not — list "
                    "every fabricated-looking citation you find in the reason.\n\n"
                    f"Script:\n{{full_text}}"
                )
                default_reason = "misleading or unverifiable medical claims"
            else:
                ymyl_prompt = (
                    "You are a compliance auditor. Does this finance script contain "
                    "any guaranteed return promises, false earnings claims, or "
                    "materially misleading financial advice?\n\n"
                    "Reply with ONLY 'PASS' if compliant, or 'FAIL: <reason>' if not.\n\n"
                    f"Script:\n{{full_text}}"
                )
                default_reason = "misleading financial claims"
            try:
                full_text = draft.hook + "\n" + "\n".join(s.content for s in draft.segments) + "\n" + draft.outro
                response = await self.call_llm(
                    [{"role": "user", "content": ymyl_prompt.format(full_text=full_text)}],
                    temperature=0.1,
                )
                verdict = response.content.strip().upper()
                if verdict.startswith("FAIL"):
                    reason = response.content.strip()[5:].strip(" :")
                    violations.append(f"YMYL violation: {reason or default_reason}")
            except Exception as exc:
                raise ComplianceError(f"LLM compliance check failed: {exc}") from exc

        passed = len(violations) == 0
        logger.info(
            "Compliance check completed",
            passed=passed,
            violations_count=len(violations),
            niche=niche.value,
        )
        return passed, violations

    def _check_ai_disclosure(self, draft: ScriptDraft) -> str | None:
        """Return violation string if AI disclosure missing in description, else None.

        AI disclosure belongs in video description (added at upload time), not script body.
        Only flag if description_template explicitly set and missing disclosure.
        """
        desc = draft.description_template or ""
        if desc and "ai" not in desc.lower() and "artificial intelligence" not in desc.lower():
            return "Missing AI disclosure in description_template"
        return None  # No description set = will be added at upload time

    def _check_coppa(self, draft: ScriptDraft) -> str | None:
        """Return violation if child-targeting detected, else None."""
        child_keywords = ["kids", "children", "toddlers", "baby", "under 13"]
        full_text = (draft.hook + " " + " ".join(s.content for s in draft.segments)).lower()
        if any(kw in full_text for kw in child_keywords):
            return "Potential COPPA violation - child-targeting content"
        return None

    def _is_ymyl(self, niche: Niche) -> bool:
        """Check if niche is YMYL (Your Money Your Life)."""
        return niche in YMYL_NICHES
