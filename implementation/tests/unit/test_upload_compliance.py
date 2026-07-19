import pytest
from omnicast.upload.compliance import ComplianceChecker, REQUIRED_CHECKS
from omnicast.upload.models import UploadRequest, UploadMetadata, ComplianceResult


def _make_request(**kwargs) -> UploadRequest:
    meta_kwargs = {
        "title": "Top 10 Finance Tips",
        "description": "Great video about finance. This video was made with AI assistance.",
    }
    meta_kwargs.update(kwargs.pop("meta", {}))
    defaults = {
        "video_id": "v1",
        "channel_id": "ch1",
        "video_path": "/tmp/final.mp4",
        "metadata": UploadMetadata(**meta_kwargs),
    }
    defaults.update(kwargs)
    return UploadRequest(**defaults)


class TestComplianceAllPass:
    def test_valid_request_passes(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request())
        assert result.passed
        assert result.violation_count == 0
        assert all(v for v in result.checks.values())

    def test_all_required_checks_present(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request())
        for check_name in REQUIRED_CHECKS:
            assert check_name in result.checks


class TestAIDisclosure:
    def test_missing_disclosure_fails(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(meta={"description": "No disclosure here"}))
        assert not result.checks["ai_disclosure"]
        assert not result.passed

    def test_disclosure_present_passes(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(
            meta={"description": "This video was made with AI assistance."}
        ))
        assert result.checks["ai_disclosure"]

    def test_disclosure_case_insensitive(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(
            meta={"description": "Made With AI tools for this content."}
        ))
        assert result.checks["ai_disclosure"]

    def test_ai_disclosure_flag_false(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(
            meta={"description": "Made with AI", "ai_disclosure": False}
        ))
        assert not result.checks["ai_disclosure"]


class TestNotChildren:
    def test_not_for_kids_passes(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(meta={"made_for_kids": False}))
        assert result.checks["not_targeting_children"]

    def test_for_kids_fails(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(meta={"made_for_kids": True}))
        assert not result.checks["not_targeting_children"]
        assert not result.passed


class TestYMYLHealthSafety:
    def test_health_upload_requires_medical_disclaimer(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(
            meta={
                "title": "Beat GLP-1 Nausea Naturally",
                "description": "This video was made with AI assistance.",
            }
        ))
        assert not result.checks["ymyl_health_safety"]
        assert not result.passed

    def test_health_upload_passes_with_disclaimer_and_source(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(
            meta={
                "title": "Beat GLP-1 Nausea Naturally",
                "description": (
                    "This video was made with AI assistance. Not medical advice; "
                    "consult your healthcare provider. Source: https://www.nih.gov/"
                ),
            }
        ))
        assert result.checks["ymyl_health_safety"]

    def test_script_time_blocks_unverified_medical_citation(self):
        violations = ComplianceChecker.check_text(
            "GLP-1 Nausea Fix",
            (
                "NIH 2024 review found 72% of patients are deficient after six months. "
                "This is not medical advice; consult your healthcare provider."
            ),
        )
        assert any("unverifiable medical citation" in v for v in violations)

    def test_script_time_allows_sourced_health_claim_with_disclaimer(self):
        violations = ComplianceChecker.check_text(
            "GLP-1 Nausea Tips",
            (
                "A clinical review discusses nausea management. Source: https://www.nih.gov/ "
                "This is not medical advice; talk to your doctor."
            ),
        )
        assert not [v for v in violations if v.startswith("health/YMYL")]


class TestComplianceResult:
    def test_multiple_violations(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request(
            meta={"description": "No disclosure", "made_for_kids": True}
        ))
        assert not result.passed
        assert result.violation_count >= 2

    def test_returns_compliance_result_type(self):
        checker = ComplianceChecker()
        result = checker.check(_make_request())
        assert isinstance(result, ComplianceResult)

    def test_check_never_raises(self):
        checker = ComplianceChecker()
        # Even with minimal/bad data, should return result not raise
        result = checker.check(_make_request(meta={"title": "", "description": ""}))
        assert isinstance(result, ComplianceResult)
