"""Reddit scanner using PRAW.

Finds trending posts: score > 500 AND comments > 50.
"""

from __future__ import annotations

import asyncio

import structlog

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource, Market

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
        if not self._reddit:
            raise RuntimeError("Reddit client not provided. Inject praw.Reddit instance.")

        all_topics = []
        subreddits = self.config.subreddits if self.config.subreddits else []
        market = self.config.markets[0] if self.config.markets else Market.US
        subreddits_scanned = 0
        subreddits_failed = 0

        for subreddit_name in subreddits:
            try:
                posts = await asyncio.to_thread(
                    self._fetch_subreddit_posts, subreddit_name, market
                )
                all_topics.extend(posts)
                subreddits_scanned += 1

            except Exception as exc:
                subreddits_failed += 1
                logger.warning(
                    "Failed to scan subreddit",
                    subreddit=subreddit_name,
                    error=str(exc),
                )
                continue

        # If all subreddits failed, raise an exception so BaseScanner wraps it in error result
        if subreddits_failed > 0 and subreddits_scanned == 0:
            raise RuntimeError(f"All {subreddits_failed} subreddits failed to scan")

        return all_topics

    def _fetch_subreddit_posts(self, subreddit_name: str, market: Market) -> list[TopicRawData]:
        """Synchronous PRAW call (run in thread).

        Fetch top posts for the week.
        Filter by MIN_SCORE and MIN_COMMENTS.
        Return list of TopicRawData.
        """
        subreddit = self._reddit.subreddit(subreddit_name)
        top_posts = subreddit.top(time_filter="week", limit=50)

        topics = []
        for post in top_posts:
            if self._post_qualifies(post.score, post.num_comments):
                topic = TopicRawData(
                    title=post.title,
                    description=post.selftext[:500] if hasattr(post, "selftext") else "",
                    source=TopicSource.REDDIT,
                    niche=self.config.niche,
                    market=market,
                    source_url=post.url,
                    raw_metrics={
                        "score": post.score,
                        "comments": post.num_comments,
                        "upvote_ratio": post.upvote_ratio,
                        "subreddit": subreddit_name,
                        "post_id": post.id,
                    },
                )
                topics.append(topic)

        return topics

    @staticmethod
    def _post_qualifies(score: int, num_comments: int) -> bool:
        """Check if post meets engagement thresholds."""
        return score >= MIN_SCORE and num_comments >= MIN_COMMENTS
