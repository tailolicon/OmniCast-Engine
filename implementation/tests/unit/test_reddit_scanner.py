"""Tests for Reddit Scanner."""

import pytest
from unittest.mock import MagicMock

from omnicast.discovery.reddit_scanner import (
    RedditScanner,
    MIN_SCORE,
    MIN_COMMENTS,
)
from omnicast.discovery.models import DiscoveryConfig, TopicRawData
from omnicast.models.enums import Niche, Market, TopicSource


@pytest.fixture
def config():
    return DiscoveryConfig(
        niche=Niche.PSYCHOLOGY,
        markets=[Market.US],
        subreddits=["psychology", "mentalhealth"],
    )


def _mock_submission(title, score, num_comments, upvote_ratio=0.9, post_id="abc123"):
    """Create a mock PRAW Submission."""
    sub = MagicMock()
    sub.title = title
    sub.score = score
    sub.num_comments = num_comments
    sub.upvote_ratio = upvote_ratio
    sub.id = post_id
    sub.url = f"https://reddit.com/r/test/comments/{post_id}"
    sub.subreddit.display_name = "psychology"
    sub.selftext = ""  # Empty selftext for text posts
    return sub


class TestPostQualifies:
    def test_qualifies_above_both_thresholds(self):
        assert RedditScanner._post_qualifies(600, 60) is True

    def test_fails_low_score(self):
        assert RedditScanner._post_qualifies(400, 100) is False

    def test_fails_low_comments(self):
        assert RedditScanner._post_qualifies(800, 30) is False

    def test_fails_both_low(self):
        assert RedditScanner._post_qualifies(100, 10) is False

    def test_boundary_exact_thresholds(self):
        assert RedditScanner._post_qualifies(MIN_SCORE, MIN_COMMENTS) is True

    def test_boundary_score_minus_one(self):
        assert RedditScanner._post_qualifies(MIN_SCORE - 1, MIN_COMMENTS) is False

    def test_boundary_comments_minus_one(self):
        assert RedditScanner._post_qualifies(MIN_SCORE, MIN_COMMENTS - 1) is False


class TestFetchSubredditPosts:
    def test_returns_qualifying_posts(self, config):
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_subreddit.top.return_value = [
            _mock_submission("Good Post", 800, 100, post_id="p1"),
            _mock_submission("Bad Post", 100, 10, post_id="p2"),
            _mock_submission("Another Good", 600, 80, post_id="p3"),
        ]
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        posts = scanner._fetch_subreddit_posts("psychology", Market.US)
        assert len(posts) == 2
        titles = [p.title for p in posts]
        assert "Good Post" in titles
        assert "Another Good" in titles
        assert "Bad Post" not in titles

    def test_empty_subreddit(self, config):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.return_value.top.return_value = []
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        posts = scanner._fetch_subreddit_posts("emptysubreddit", Market.US)
        assert posts == []

    def test_raw_metrics_populated(self, config):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.return_value.top.return_value = [
            _mock_submission("Hot Topic", 1200, 200, upvote_ratio=0.95, post_id="xyz"),
        ]
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        posts = scanner._fetch_subreddit_posts("psychology", Market.US)
        assert len(posts) == 1
        m = posts[0].raw_metrics
        assert m["score"] == 1200
        assert m["comments"] == 200
        assert m["upvote_ratio"] == 0.95
        assert m["post_id"] == "xyz"

    def test_source_is_reddit(self, config):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.return_value.top.return_value = [
            _mock_submission("Test", 700, 70, post_id="t1"),
        ]
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        posts = scanner._fetch_subreddit_posts("psychology", Market.US)
        assert posts[0].source == TopicSource.REDDIT
        assert posts[0].niche == Niche.PSYCHOLOGY


class TestRedditScannerIntegration:
    @pytest.mark.asyncio
    async def test_scan_multiple_subreddits(self, config):
        mock_reddit = MagicMock()

        def make_subreddit(name):
            sub = MagicMock()
            sub.top.return_value = [
                _mock_submission(f"Trending in {name}", 900, 120, post_id=f"id_{name}"),
            ]
            return sub

        mock_reddit.subreddit.side_effect = lambda name: make_subreddit(name)

        scanner = RedditScanner(config, reddit_client=mock_reddit)
        result = await scanner.scan()
        assert result.success
        assert result.source == TopicSource.REDDIT
        assert result.count == 2  # one from each subreddit

    @pytest.mark.asyncio
    async def test_scan_handles_praw_error(self, config):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.side_effect = Exception("PRAW auth failed")
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        result = await scanner.scan()
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_scan_empty_config(self):
        config = DiscoveryConfig(niche=Niche.TECH, subreddits=[])
        mock_reddit = MagicMock()
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        result = await scanner.scan()
        assert result.success
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_scan_no_client_raises(self, config):
        scanner = RedditScanner(config, reddit_client=None)
        result = await scanner.scan()
        assert result.success is False
        assert "Reddit client not provided" in result.error
