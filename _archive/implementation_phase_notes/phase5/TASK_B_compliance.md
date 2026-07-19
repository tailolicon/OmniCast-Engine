# TASK_B: Compliance Gate

## Model: sonnet | Dependencies: TASK_A complete

Mandatory compliance checks before any upload. Fail = video → DLQ, no upload.

## Interface

### src/omnicast/upload/compliance.py

```python
"""Compliance gate. Must pass ALL checks before upload. Fail → DLQ."""

from __future__ import annotations
import structlog
from omnicast.upload.models import ComplianceResult, UploadRequest
from omnicast.media.models import ContentFingerprint
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

REQUIRED_CHECKS = [
    "ai_disclosure",
    "no_misleading_metadata",
    "no_copyrighted_music",
    "ftc_disclosure",
    "advertiser_friendly",
    "not_targeting_children",
    "cross_channel_unique",
]


class ComplianceChecker:
    """Run all compliance checks. ALL must pass."""

    def __init__(self, existing_fingerprints: list[ContentFingerprint] | None = None) -> None:
        self.existing_fingerprints = existing_fingerprints or []

    def check(self, request: UploadRequest) -> ComplianceResult:
        """Run all checks. Return ComplianceResult with per-check status."""
        checks = {}
        violations = []

        checks["ai_disclosure"] = self._check_ai_disclosure(request)
        if not checks["ai_disclosure"]:
            violations.append("Missing AI disclosure in description")

        checks["no_misleading_metadata"] = self._check_no_misleading(request)
        if not checks["no_misleading_metadata"]:
            violations.append("Title/description may be misleading")

        checks["no_copyrighted_music"] = self._check_no_copyright_music(request)
        if not checks["no_copyrighted_music"]:
            violations.append("Copyrighted music detected")

        checks["ftc_disclosure"] = self._check_ftc_disclosure(request)
        if not checks["ftc_disclosure"]:
            violations.append("Missing FTC affiliate disclosure")

        checks["advertiser_friendly"] = self._check_advertiser_friendly(request)
        if not checks["advertiser_friendly"]:
            violations.append("Content may trigger demonetization")

        checks["not_targeting_children"] = self._check_not_children(request)
        if not checks["not_targeting_children"]:
            violations.append("Content flagged as targeting children without COPPA compliance")

        checks["cross_channel_unique"] = self._check_cross_channel_unique(request)
        if not checks["cross_channel_unique"]:
            violations.append("Duplicate content across channels")

        passed = len(violations) == 0
        result = ComplianceResult(passed=passed, checks=checks, violations=violations)

        if not passed:
            logger.warning("Compliance failed", video_id=request.video_id,
                           violations=violations)
        else:
            logger.info("Compliance passed", video_id=request.video_id)

        return result

    def _check_ai_disclosure(self, request: UploadRequest) -> bool:
        """Description must contain AI disclosure text."""
        if not request.metadata.ai_disclosure:
            return False
        disclosure_phrases = [
            "made with ai",
            "ai assistance",
            "ai-generated",
            "created with ai",
            "ai tools",
        ]
        desc_lower = request.metadata.description.lower()
        return any(phrase in desc_lower for phrase in disclosure_phrases)

    def _check_no_misleading(self, request: UploadRequest) -> bool:
        """Title should not contain misleading clickbait patterns."""
        ...

    def _check_no_copyright_music(self, request: UploadRequest) -> bool:
        """Verify music fingerprint not in ContentID database.
        For now: return True (actual fingerprint check requires external API).
        TODO: integrate with music fingerprint from Phase 4."""
        return True

    def _check_ftc_disclosure(self, request: UploadRequest) -> bool:
        """If description contains affiliate links, must have FTC disclosure."""
        ...

    def _check_advertiser_friendly(self, request: UploadRequest) -> bool:
        """Check title/description for demonetization trigger words."""
        ...

    def _check_not_children(self, request: UploadRequest) -> bool:
        """If made_for_kids=True, verify COPPA compliance. Else pass."""
        return not request.metadata.made_for_kids

    def _check_cross_channel_unique(self, request: UploadRequest) -> bool:
        """Check video not duplicate across channels using fingerprints."""
        ...
```

## DO NOT

- No upload logic — compliance only
- No modifying models.py or oauth.py
- No external API calls — all checks are local/logic-based
- ALL 7 checks must be implemented (can be simple heuristics for now)
- check() must return ComplianceResult, never raise

## Tests

### tests/unit/test_compliance.py

```python
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
```
