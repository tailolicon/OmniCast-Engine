# TASK_D: Reddit Scanner

## Model: sonnet
## Estimated time: 30 minutes
## Dependencies: TASK_A

## Overview

Scan subreddits for trending posts using PRAW (Python Reddit API Wrapper).
Filter: score > 500 AND comments > 50. Extract post titles as topic candidates.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/discovery/reddit_scanner.py` | ~130 | RedditScanner |
| `tests/unit/test_reddit_scanner.py` | ~180 | Pre-written tests |

## Context Files

- `src/omnicast/discovery/base.py` — BaseScanner
- `src/omnicast/discovery/models.py` — TopicRawData, DiscoveryConfig
- `src/omnicast/models/enums.py` — TopicSource.REDDIT

## Interface Definition

### src/omnicast/discovery/reddit_scanner.py

```python
"""Reddit scanner using PRAW.

Finds trending posts: score > 500 AND comments > 50.
"""

from __future__ import annotations

import asyncio

import structlog

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource

logger = structlog.get_logger()

MIN_SCORE = 500
MIN_COMMENTS = 50


class RedditScanner(BaseScanner):
    """Scan configured subreddits for trending posts.

    Algorithm:
    1. For each subreddit in config.subreddits:
       a. Fetch top posts from "week" time_filter (limit=50)
       b. Filter: score >= MIN_SCORE AND num_comments >= MIN_COMMENTS
       c. Convert to TopicRawData with raw_metrics:
          {"score": int, "comments": int, "upvote_ratio": float,
           "subreddit": str, "post_id": str, "url": str}
    2. Return all qualifying posts.
    """

    source = TopicSource.REDDIT

    def __init__(
        self,
        config: DiscoveryConfig,
        reddit_client=None,
    ) -> None:
        """
        reddit_client: praw.Reddit instance, injectable for testing.
        If None, caller must set up PRAW credentials externally.
        """
        super().__init__(config)
        self._reddit = reddit_client

    async def _scan(self) -> list[TopicRawData]:
        """Scan all configured subreddits."""
        ...

    def _fetch_subreddit_posts(self, subreddit_name: str) -> list[TopicRawData]:
        """Synchronous PRAW call (run in thread).

        Fetch top posts for the week.
        Filter by MIN_SCORE and MIN_COMMENTS.
        Return list of TopicRawData.
        """
        ...

    @staticmethod
    def _post_qualifies(score: int, num_comments: int) -> bool:
        """Check if post meets engagement thresholds."""
        return score >= MIN_SCORE and num_comments >= MIN_COMMENTS
```

## DO NOT

- Do NOT create praw.Reddit internally — always inject via constructor
- Do NOT fetch post content/comments — titles + metadata only
- Do NOT add NSFW filtering here — that's the Input Sanitizer Agent's job
- Do NOT use pushshift or other Reddit archive APIs

## Tests

### tests/unit/test_reddit_scanner.py

```python
"""Tests for Reddit Scanner."""

import pytest
from unittest.mock import MagicMock, PropertyMock

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
        posts = scanner._fetch_subreddit_posts("psychology")
        assert len(posts) == 2
        titles = [p.title for p in posts]
        assert "Good Post" in titles
        assert "Another Good" in titles
        assert "Bad Post" not in titles

    def test_empty_subreddit(self, config):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.return_value.top.return_value = []
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        posts = scanner._fetch_subreddit_posts("emptysubreddit")
        assert posts == []

    def test_raw_metrics_populated(self, config):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.return_value.top.return_value = [
            _mock_submission("Hot Topic", 1200, 200, upvote_ratio=0.95, post_id="xyz"),
        ]
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        posts = scanner._fetch_subreddit_posts("psychology")
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
        posts = scanner._fetch_subreddit_posts("psychology")
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
        assert "PRAW auth failed" in result.error

    @pytest.mark.asyncio
    async def test_scan_empty_config(self):
        config = DiscoveryConfig(niche=Niche.TECH, subreddits=[])
        mock_reddit = MagicMock()
        scanner = RedditScanner(config, reddit_client=mock_reddit)
        result = await scanner.scan()
        assert result.success
        assert result.count == 0
```
