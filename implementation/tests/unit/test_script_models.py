"""Tests for script pipeline models."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from omnicast.models.script import (
    TopicBrief,
    ScriptSegment,
    ScriptDraft,
    CriticDimension,
    CriticFeedback,
    DebateRound,
    TournamentMatch,
    EloRating,
    EngagementPattern,
)
from omnicast.models.enums import Niche, Market, TopicSource


class TestTopicBrief:
    def test_create_minimal(self):
        brief = TopicBrief(
            title="5 Investment Tips",
            niche=Niche.FINANCE,
            market=Market.US,
            source=TopicSource.GOOGLE_TRENDS,
        )
        assert brief.title == "5 Investment Tips"
        assert brief.angle == ""
        assert brief.lessons == []

    def test_create_full(self):
        brief = TopicBrief(
            title="Crypto Regulation 2026",
            niche=Niche.FINANCE,
            market=Market.US,
            source=TopicSource.REDDIT,
            angle="contrarian",
            key_points=["SEC ruling", "DeFi impact"],
            source_urls=["https://reddit.com/r/crypto/123"],
            target_duration_min=12,
            brand_voice="authoritative",
            lessons=["Avoid rhetorical questions in hook"],
        )
        assert len(brief.key_points) == 2
        assert brief.target_duration_min == 12

    def test_frozen(self):
        brief = TopicBrief(
            title="Test", niche=Niche.TECH, market=Market.UK,
            source=TopicSource.MANUAL,
        )
        with pytest.raises(ValidationError):
            brief.title = "Changed"


class TestScriptDraft:
    def test_create_with_segments(self):
        draft = ScriptDraft(
            variant_id="A",
            brief_title="Investment Tips",
            hook="Did you know 90% of traders lose money?",
            segments=[
                ScriptSegment(
                    index=0, heading="Intro", content="...",
                    estimated_duration_seconds=30, has_pattern_interrupt=True,
                ),
                ScriptSegment(
                    index=1, heading="Tip 1", content="...",
                    estimated_duration_seconds=90,
                ),
            ],
            word_count=1500,
            estimated_duration_seconds=600,
        )
        assert len(draft.segments) == 2
        assert draft.segments[0].has_pattern_interrupt is True

    def test_default_version(self):
        draft = ScriptDraft(variant_id="B", brief_title="Test", hook="Hook")
        assert draft.version == 1


class TestCriticFeedback:
    def test_create_approved(self):
        fb = CriticFeedback(
            variant_id="A",
            total_score=85,
            dimensions=[
                CriticDimension(name="hook_quality", score=22, max_score=25),
                CriticDimension(name="anti_ai_cliche", score=18, max_score=20),
            ],
            approved=True,
        )
        assert fb.approved is True
        assert fb.total_score == 85

    def test_create_rejected(self):
        fb = CriticFeedback(
            variant_id="A",
            total_score=55,
            approved=False,
            rejection_reasons=["Hook too generic", "AI cliches detected"],
            specific_fixes=["Replace hook with bold statement"],
        )
        assert fb.approved is False
        assert len(fb.rejection_reasons) == 2

    def test_score_range_validation(self):
        with pytest.raises(ValidationError):
            CriticFeedback(variant_id="A", total_score=101)
        with pytest.raises(ValidationError):
            CriticFeedback(variant_id="A", total_score=-1)


class TestDebateRound:
    def test_create(self):
        draft = ScriptDraft(variant_id="A", brief_title="Test", hook="Hook")
        feedback = CriticFeedback(variant_id="A", total_score=72)
        rnd = DebateRound(
            round_number=1,
            draft=draft,
            feedback=feedback,
            score_delta=0,
        )
        assert rnd.round_number == 1
        assert rnd.feedback.total_score == 72


class TestEloRating:
    def test_default_rating(self):
        rating = EloRating(variant_id="A")
        assert rating.rating == 1000.0
        assert rating.matches_played == 0


class TestEngagementPattern:
    def test_create(self):
        pattern = EngagementPattern(
            pattern_id="EP-2026-0001",
            niche=Niche.FINANCE,
            market=Market.US,
            finding="Numbered lists improve retention by 22%",
            confidence=0.75,
            sample_size=12,
            decay_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        assert pattern.confidence == 0.75

    def test_confidence_range(self):
        with pytest.raises(ValidationError):
            EngagementPattern(
                pattern_id="X", niche=Niche.TECH, market=Market.US,
                finding="test", confidence=1.5, sample_size=1,
                decay_date=datetime.now(timezone.utc),
            )
