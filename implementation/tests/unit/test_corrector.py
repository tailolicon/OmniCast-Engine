import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from omnicast.analytics.corrector import AutoCorrector
from omnicast.analytics.models import (
    Diagnosis, DiagnosisItem, CorrectionAction, ABTestResult,
)


@pytest.fixture
def corrector():
    return AutoCorrector()


class TestMapActions:
    def test_thumbnail_weak(self, corrector):
        diagnosis = Diagnosis(
            channel_id="ch1", funnel_bottleneck="ctr",
            items=[DiagnosisItem(
                cause="THUMBNAIL_WEAK", confidence=0.85,
                evidence=["low contrast"], suggested_action="change style",
            )],
            generated_at=datetime.now(timezone.utc),
        )
        actions = corrector.map_actions(diagnosis)
        assert len(actions) >= 1
        assert isinstance(actions[0], CorrectionAction)

    def test_multiple_causes(self, corrector):
        diagnosis = Diagnosis(
            channel_id="ch1", funnel_bottleneck="avd",
            items=[
                DiagnosisItem(cause="SCRIPT_BORING", confidence=0.7,
                              evidence=["weak hook"], suggested_action="update hook"),
                DiagnosisItem(cause="TTS_ROBOTIC", confidence=0.5,
                              evidence=["low naturalness"], suggested_action="switch voice"),
            ],
            generated_at=datetime.now(timezone.utc),
        )
        actions = corrector.map_actions(diagnosis)
        assert len(actions) >= 2

    def test_low_confidence_manual(self, corrector):
        diagnosis = Diagnosis(
            channel_id="ch1", funnel_bottleneck="ctr",
            items=[DiagnosisItem(
                cause="UNKNOWN", confidence=0.3,
                evidence=["unclear"], suggested_action="investigate",
            )],
            generated_at=datetime.now(timezone.utc),
        )
        actions = corrector.map_actions(diagnosis)
        for a in actions:
            assert a.action_type == "manual"


class TestABTest:
    @pytest.mark.asyncio
    async def test_returns_result(self, corrector):
        with patch.object(corrector, "run_ab_test",
                          new_callable=AsyncMock,
                          return_value=ABTestResult(
                              variable="thumbnail_style",
                              variants=["dark", "bright"],
                              sample_sizes=[10, 10],
                              metrics={"ctr": [3.2, 5.1]},
                              winner="bright", p_value=0.03, significant=True,
                          )):
            result = await corrector.run_ab_test("ch1", "thumbnail_style", ["dark", "bright"])
            assert isinstance(result, ABTestResult)
            assert result.significant
