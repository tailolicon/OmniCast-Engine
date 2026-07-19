import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from omnicast.upload.models import (
    UploadStatus, TokenStatus,
    ComplianceResult, UploadMetadata, UploadRequest, UploadResult,
    ScheduleSlot, TokenHealth, UploadPipelineState,
)


class TestUploadStatus:
    def test_values(self):
        assert UploadStatus.PENDING == "pending"
        assert UploadStatus.REJECTED == "rejected"
        assert UploadStatus.PUBLISHED == "published"


class TestComplianceResult:
    def test_passed(self):
        c = ComplianceResult(passed=True, checks={"ai_disclosure": True, "no_copyright_music": True})
        assert c.passed
        assert c.violation_count == 0

    def test_failed(self):
        c = ComplianceResult(passed=False, violations=["Missing AI disclosure", "Copyright music detected"])
        assert not c.passed
        assert c.violation_count == 2

    def test_frozen(self):
        c = ComplianceResult()
        with pytest.raises(ValidationError):
            c.passed = True


class TestUploadMetadata:
    def test_defaults(self):
        m = UploadMetadata(title="Top 10 Tips", description="A great video")
        assert m.category_id == "22"
        assert m.ai_disclosure is True
        assert m.privacy_status == "private"
        assert m.made_for_kids is False

    def test_with_schedule(self):
        dt = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)
        m = UploadMetadata(title="X", description="Y", publish_at=dt)
        assert m.publish_at is not None


class TestUploadRequest:
    def test_create(self):
        meta = UploadMetadata(title="X", description="Y")
        r = UploadRequest(video_id="v1", channel_id="ch1", video_path="/tmp/final.mp4", metadata=meta)
        assert r.video_path == "/tmp/final.mp4"
        assert r.compliance is None
        assert r.thumbnail_paths == []


class TestUploadResult:
    def test_success(self):
        r = UploadResult(youtube_video_id="yt_abc123", channel_id="ch1", url="https://youtu.be/abc123")
        assert r.status == UploadStatus.PUBLISHED

    def test_failure(self):
        r = UploadResult(status=UploadStatus.FAILED, error="Quota exceeded")
        assert r.error is not None


class TestScheduleSlot:
    def test_create(self):
        dt = datetime(2025, 6, 1, 14, 0, tzinfo=timezone.utc)
        s = ScheduleSlot(channel_id="ch1", scheduled_at=dt, market="US")
        assert s.is_prime_time


class TestTokenHealth:
    def test_valid(self):
        t = TokenHealth(channel_id="ch1", status=TokenStatus.VALID, scopes=["youtube.upload"])
        assert t.status == TokenStatus.VALID

    def test_expired(self):
        t = TokenHealth(channel_id="ch1", status=TokenStatus.EXPIRED, error="Token revoked by user")
        assert t.error is not None


class TestUploadPipelineState:
    def test_initial(self):
        s = UploadPipelineState(video_id="v1", channel_id="ch1")
        assert not s.all_done
        assert not s.has_failure

    def test_all_done(self):
        s = UploadPipelineState(
            video_id="v1", channel_id="ch1",
            compliance=UploadStatus.PUBLISHED,
            scheduling=UploadStatus.SCHEDULED,
            upload=UploadStatus.PUBLISHED,
            thumbnail=UploadStatus.PUBLISHED,
        )
        assert s.all_done

    def test_rejected(self):
        s = UploadPipelineState(
            video_id="v1", channel_id="ch1",
            compliance=UploadStatus.REJECTED,
        )
        assert s.has_failure

    def test_frozen(self):
        s = UploadPipelineState(video_id="v1", channel_id="ch1")
        with pytest.raises(ValidationError):
            s.video_id = "v2"
