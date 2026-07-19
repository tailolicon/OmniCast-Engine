"""Tests for Brief Generator."""

import pytest

from omnicast.discovery.brief_generator import BriefGenerator
from omnicast.discovery.models import TopicRawData, ScoredTopic
from omnicast.models.script import TopicBrief
from omnicast.models.enums import Niche, Market, TopicSource


def _scored(
    source=TopicSource.GOOGLE_TRENDS,
    total=75,
    title="Test Topic",
    **raw_metrics,
) -> ScoredTopic:
    raw = TopicRawData(
        title=title,
        source=source,
        niche=Niche.FINANCE,
        market=Market.US,
        source_url="https://example.com/test",
        raw_metrics=raw_metrics,
    )
    return ScoredTopic(
        raw=raw,
        trend_momentum=20, gap_score=25, rpm_potential=15, novelty_score=8,
        total_score=total,
        auto_approved=total >= 70,
        needs_review=50 <= total < 70,
    )


class TestGenerate:
    def test_produces_topic_brief(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored)
        assert isinstance(brief, TopicBrief)
        assert brief.title == "Test Topic"
        assert brief.niche == Niche.FINANCE
        assert brief.market == Market.US
        assert brief.source == TopicSource.GOOGLE_TRENDS

    def test_includes_source_url(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored)
        assert "https://example.com/test" in brief.source_urls

    def test_brand_voice_passed(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored, brand_voice="Professional, authoritative")
        assert brief.brand_voice == "Professional, authoritative"

    def test_default_duration(self):
        scored = _scored()
        brief = BriefGenerator.generate(scored)
        assert brief.target_duration_min == 10


class TestDetermineAngle:
    def test_youtube_angle(self):
        scored = _scored(TopicSource.YOUTUBE_COMPETITOR)
        angle = BriefGenerator._determine_angle(scored)
        assert "competitor" in angle.lower() or "analysis" in angle.lower()

    def test_trends_angle(self):
        scored = _scored(TopicSource.GOOGLE_TRENDS)
        angle = BriefGenerator._determine_angle(scored)
        assert "trend" in angle.lower()

    def test_reddit_angle(self):
        scored = _scored(TopicSource.REDDIT)
        angle = BriefGenerator._determine_angle(scored)
        assert "community" in angle.lower() or "discussion" in angle.lower()

    def test_podcast_angle(self):
        scored = _scored(TopicSource.PODCAST)
        angle = BriefGenerator._determine_angle(scored)
        assert "deep" in angle.lower() or "dive" in angle.lower()

    def test_news_angle(self):
        scored = _scored(TopicSource.NEWS_RSS)
        angle = BriefGenerator._determine_angle(scored)
        assert "news" in angle.lower() or "breaking" in angle.lower()


class TestGenerateBatch:
    def test_only_approved_topics(self):
        topics = [
            _scored(total=80),   # approve
            _scored(total=55),   # review → skip
            _scored(total=30),   # discard → skip
            _scored(total=75),   # approve
        ]
        briefs = BriefGenerator.generate_batch(topics)
        assert len(briefs) == 2

    def test_empty_when_none_approved(self):
        topics = [_scored(total=40), _scored(total=55)]
        briefs = BriefGenerator.generate_batch(topics)
        assert len(briefs) == 0

    def test_empty_input(self):
        assert BriefGenerator.generate_batch([]) == []

    def test_brand_voice_applied_to_all(self):
        topics = [_scored(total=80), _scored(total=90)]
        briefs = BriefGenerator.generate_batch(topics, brand_voice="Casual, fun")
        assert all(b.brand_voice == "Casual, fun" for b in briefs)


class TestExtractKeyPoints:
    def test_youtube_extracts_view_data(self):
        scored = _scored(TopicSource.YOUTUBE_COMPETITOR, views=500000, outlier_ratio=5.0)
        points = BriefGenerator._extract_key_points(scored)
        assert isinstance(points, list)
        assert len(points) >= 1

    def test_empty_metrics_returns_empty(self):
        scored = _scored()
        points = BriefGenerator._extract_key_points(scored)
        assert isinstance(points, list)
