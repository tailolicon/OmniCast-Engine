"""Tests for Compliance Checker."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.compliance import (
    ComplianceChecker,
    YMYL_NICHES,
    COMPLIANCE_CHECKS,
)
from omnicast.llm.client import LLMClient, LLMResponse
from omnicast.models.script import ScriptDraft, ScriptSegment
from omnicast.models.enums import Niche
from omnicast.shared.errors import ComplianceError


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock(spec=LLMClient)
    llm.complete.return_value = LLMResponse(
        content="No misleading claims detected.",
        model="claude-haiku-4-5",
        input_tokens=100, output_tokens=20,
        cost_usd=0.0002, stop_reason="end_turn",
    )
    return llm


@pytest.fixture
def compliant_draft() -> ScriptDraft:
    """Draft that passes all compliance checks."""
    return ScriptDraft(
        variant_id="A",
        brief_title="Investment Tips",
        hook="Here are 5 tips for beginners.",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="Welcome to this AI-generated video.",
                          estimated_duration_seconds=25),
        ],
        outro="Not financial advice. Do your own research.",
        description_template="This video was created with AI assistance.",
        word_count=1500,
        estimated_duration_seconds=600,
    )


@pytest.fixture
def non_compliant_draft() -> ScriptDraft:
    """Draft with compliance issues."""
    return ScriptDraft(
        variant_id="B",
        brief_title="Get Rich Quick",
        hook="This ONE trick will make you a millionaire!",
        segments=[
            ScriptSegment(index=0, heading="Intro", content="I guarantee 1000% returns.",
                          estimated_duration_seconds=30),
        ],
        outro="",
        description_template="Great tips for making money!",  # no AI disclosure
        word_count=1000,
        estimated_duration_seconds=400,
    )


class TestComplianceChecker:
    async def test_name(self, mock_llm):
        checker = ComplianceChecker(llm=mock_llm)
        assert checker.name == "compliance"

    async def test_compliant_passes(self, mock_llm, compliant_draft):
        checker = ComplianceChecker(llm=mock_llm)
        passed, violations = await checker.execute(compliant_draft, niche=Niche.TECH)  # Use non-YMYL niche
        assert passed is True
        assert violations == []

    async def test_missing_ai_disclosure(self, mock_llm, non_compliant_draft):
        checker = ComplianceChecker(llm=mock_llm)
        passed, violations = await checker.execute(non_compliant_draft, niche=Niche.TECH)
        assert passed is False
        assert any("ai_disclosure" in v.lower() or "ai" in v.lower() for v in violations)

    async def test_ymyl_niches_defined(self):
        assert Niche.FINANCE in YMYL_NICHES
        assert Niche.HEALTH in YMYL_NICHES
        assert Niche.TECH not in YMYL_NICHES

    async def test_compliance_checks_list(self):
        assert len(COMPLIANCE_CHECKS) >= 5
        assert "ai_disclosure" in COMPLIANCE_CHECKS

    async def test_ymyl_extra_checks(self, mock_llm, compliant_draft):
        checker = ComplianceChecker(llm=mock_llm)
        assert checker._is_ymyl(Niche.FINANCE) is True
        assert checker._is_ymyl(Niche.TECH) is False

    async def test_health_ymyl_missing_disclaimer_fails_even_if_llm_passes(self, mock_llm):
        mock_llm.complete.return_value = LLMResponse(
            content="PASS",
            model="claude-haiku-4-5",
            input_tokens=100, output_tokens=20,
            cost_usd=0.0002, stop_reason="end_turn",
        )
        draft = ScriptDraft(
            variant_id="H",
            brief_title="Beat GLP-1 Nausea Naturally",
            hook="GLP-1 nausea can be managed with simple habits.",
            segments=[
                ScriptSegment(
                    index=0,
                    heading="Tips",
                    content="NIH 2024 review found 72% of patients are deficient after six months.",
                    estimated_duration_seconds=60,
                ),
            ],
            outro="Try these tips.",
            description_template="This video was created with AI assistance.",
            word_count=1500,
            estimated_duration_seconds=600,
        )
        checker = ComplianceChecker(llm=mock_llm)
        passed, violations = await checker.execute(draft, niche=Niche.HEALTH)
        assert passed is False
        assert any("health/YMYL" in v for v in violations)

    async def test_llm_error_raises_compliance_error(self, mock_llm, compliant_draft):
        mock_llm.complete.side_effect = Exception("LLM down")
        checker = ComplianceChecker(llm=mock_llm)
        with pytest.raises(ComplianceError):
            await checker.execute(compliant_draft, niche=Niche.HEALTH)
