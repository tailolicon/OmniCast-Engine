"""YouTube competitor channel scanner.

Finds outlier videos (views > 3x channel median) from competitor channels.
Uses YouTube Data API v3 via httpx.

Supports both @handles (resolved at scan time) and raw channel IDs.
Also extracts audience signals: engagement rate, title patterns, optimal length.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter

import httpx
import structlog

from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import TopicRawData, DiscoveryConfig
from omnicast.models.enums import TopicSource, Niche, Market
from omnicast.shared.errors import DiscoveryError

logger = structlog.get_logger()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
OUTLIER_MULTIPLIER = 2.5   # lowered from 3.0 — find more candidates
MAX_VIDEOS_PER_CHANNEL = 50


class YouTubeScanner(BaseScanner):
    """Scan competitor channels for high-performing videos.

    Algorithm:
    1. Resolve @handles → channel IDs (if needed)
    2. For each channel: fetch recent uploads (max 50)
    3. Batch fetch video stats (views, likes, comments, duration)
    4. Find outliers: views > OUTLIER_MULTIPLIER * channel median
    5. Return TopicRawData with rich metrics:
       - views, engagement_rate, outlier_ratio
       - title_pattern tags (number, question, listicle, how_to)
       - estimated_duration_minutes
       - audience_signal: what made this video pop
    """

    source = TopicSource.YOUTUBE_COMPETITOR

    def __init__(
        self,
        config: DiscoveryConfig,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(config)
        self.api_key = api_key
        self._http = http_client or httpx.AsyncClient(timeout=30)

    async def _scan(self) -> list[TopicRawData]:
        """Scan all competitor channels, return outlier topics."""
        # Combine handles + raw IDs
        all_channel_ids = list(self.config.competitor_channel_ids)

        # Resolve @handles → channel IDs
        for handle in self.config.competitor_handles:
            try:
                channel_id = await self._resolve_handle(handle)
                all_channel_ids.append(channel_id)
                logger.debug("Resolved handle", handle=handle, channel_id=channel_id)
            except Exception as exc:
                logger.warning("Failed to resolve handle", handle=handle, error=str(exc))

        if not all_channel_ids:
            logger.warning("No YouTube channels to scan")
            return []

        all_outliers: list[TopicRawData] = []
        channels_scanned = 0
        channels_failed = 0

        for channel_id in all_channel_ids:
            try:
                playlist_id = await self._get_channel_uploads_playlist_id(channel_id)
                video_ids = await self._get_recent_video_ids(playlist_id, max_results=MAX_VIDEOS_PER_CHANNEL)

                if not video_ids:
                    channels_scanned += 1
                    continue

                videos = await self._get_video_stats(video_ids)
                market = self.config.markets[0] if self.config.markets else Market.US
                outliers = self._find_outliers(videos, channel_id, self.config.niche, market)
                all_outliers.extend(outliers)
                channels_scanned += 1
                logger.info(
                    "Channel scanned",
                    channel_id=channel_id,
                    videos=len(videos),
                    outliers=len(outliers),
                )

            except DiscoveryError:
                raise
            except Exception as exc:
                channels_failed += 1
                logger.warning("Failed to scan channel", channel_id=channel_id, error=str(exc))
                continue

        if channels_failed > 0 and channels_scanned == 0:
            raise DiscoveryError(f"All {channels_failed} channels failed to scan")

        return all_outliers

    async def _resolve_handle(self, handle: str) -> str:
        """Resolve YouTube @handle to channel ID.

        GET channels?part=id&forHandle={handle}
        """
        # Strip leading @ if present
        clean_handle = handle.lstrip("@")
        url = f"{YOUTUBE_API_BASE}/channels"
        params = {
            "part": "id,snippet",
            "forHandle": clean_handle,
            "key": self.api_key,
        }
        response = await self._http.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            raise DiscoveryError(f"Handle not found: {handle}")

        channel_id = data["items"][0]["id"]
        return channel_id

    async def _get_channel_uploads_playlist_id(self, channel_id: str) -> str:
        """GET channels?part=contentDetails&id={channel_id}"""
        url = f"{YOUTUBE_API_BASE}/channels"
        params = {
            "part": "contentDetails",
            "id": channel_id,
            "key": self.api_key,
        }
        response = await self._http.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            raise DiscoveryError(f"Channel not found: {channel_id}")

        return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    async def _get_recent_video_ids(self, playlist_id: str, max_results: int = 50) -> list[str]:
        """GET playlistItems?part=contentDetails&playlistId={id}&maxResults={n}"""
        url = f"{YOUTUBE_API_BASE}/playlistItems"
        params = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": max_results,
            "key": self.api_key,
        }
        response = await self._http.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return [item["contentDetails"]["videoId"] for item in data.get("items", [])]

    async def _get_video_stats(self, video_ids: list[str]) -> list[dict]:
        """Batch fetch video stats + content details (duration).

        GET videos?part=statistics,snippet,contentDetails&id={ids}
        Returns rich video data including engagement rate and duration.
        """
        url = f"{YOUTUBE_API_BASE}/videos"
        params = {
            "part": "statistics,snippet,contentDetails",
            "id": ",".join(video_ids),
            "key": self.api_key,
        }
        response = await self._http.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        videos = []
        for item in data.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})

            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))

            # Parse ISO 8601 duration → minutes
            duration_str = content.get("duration", "PT0S")
            duration_minutes = _parse_duration_minutes(duration_str)

            # Engagement rate = (likes + comments) / views
            engagement_rate = (likes + comments) / views if views > 0 else 0.0

            thumbs = snippet.get("thumbnails", {})
            thumb_url = (thumbs.get("maxres") or thumbs.get("high")
                         or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
            videos.append({
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "description": snippet.get("description", "")[:500],
                "thumbnail_url": thumb_url,
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement_rate": round(engagement_rate, 4),
                "duration_minutes": duration_minutes,
                "published_at": snippet.get("publishedAt", ""),
                "tags": snippet.get("tags", []),
            })

        return videos

    @staticmethod
    def _find_outliers(
        videos: list[dict],
        channel_id: str,
        niche: Niche,
        market: Market,
    ) -> list[TopicRawData]:
        """Filter videos with views > OUTLIER_MULTIPLIER * median.

        Enriches each outlier with audience signals:
        - title_pattern: what structure the title uses
        - audience_signal: why this video likely performed well
        """
        if len(videos) < 3:
            return []

        view_counts = [v["views"] for v in videos]
        median_views = statistics.median(view_counts)

        # Channel avg engagement rate (for comparison)
        avg_engagement = statistics.mean(v["engagement_rate"] for v in videos)

        outliers = []
        for video in videos:
            if median_views == 0:
                continue
            outlier_ratio = video["views"] / median_views

            if outlier_ratio >= OUTLIER_MULTIPLIER:
                title_patterns = _classify_title(video["title"])
                audience_signal = _infer_audience_signal(
                    video, outlier_ratio, avg_engagement
                )

                topic = TopicRawData(
                    title=video["title"],
                    description=video["description"],
                    source=TopicSource.YOUTUBE_COMPETITOR,
                    niche=niche,
                    market=market,
                    source_url=f"https://www.youtube.com/watch?v={video['video_id']}",
                    raw_metrics={
                        "views": video["views"],
                        "likes": video["likes"],
                        "comments": video["comments"],
                        "engagement_rate": video["engagement_rate"],
                        "channel_avg_engagement": round(avg_engagement, 4),
                        "channel_median_views": median_views,
                        "outlier_ratio": round(outlier_ratio, 2),
                        "duration_minutes": video["duration_minutes"],
                        "title_patterns": title_patterns,
                        "audience_signal": audience_signal,
                        "channel_id": channel_id,
                        "video_id": video["video_id"],
                        "published_at": video["published_at"],
                    },
                )
                outliers.append(topic)

        # Sort by outlier ratio descending
        outliers.sort(key=lambda t: t.raw_metrics["outlier_ratio"], reverse=True)
        return outliers


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_duration_minutes(iso_duration: str) -> float:
    """Parse ISO 8601 duration string (PT1H2M30S) → float minutes."""
    pattern = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
    match = pattern.match(iso_duration)
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return round(hours * 60 + minutes + seconds / 60, 1)


def _classify_title(title: str) -> list[str]:
    """Tag title structure — used to learn what formats win in this niche."""
    patterns = []
    if re.search(r"\b\d+\b", title):
        patterns.append("number")          # "5 Mistakes", "10 Foods"
    if re.search(r"\?", title):
        patterns.append("question")        # "Why is X..."
    if re.search(r"\b(how to|how i)\b", title, re.I):
        patterns.append("how_to")          # "How to..."
    if re.search(r"\b(you|your)\b", title, re.I):
        patterns.append("second_person")   # "You're doing X wrong"
    if re.search(r"\b(stop|never|don't|avoid|mistake|wrong)\b", title, re.I):
        patterns.append("warning")         # "Stop doing X"
    if re.search(r"\b(secret|truth|real|hidden|nobody|they won't)\b", title, re.I):
        patterns.append("insider")         # "The truth about X"
    if not patterns:
        patterns.append("statement")
    return patterns


def _infer_audience_signal(video: dict, outlier_ratio: float, avg_engagement: float) -> str:
    """Generate a human-readable signal explaining why this video outperformed."""
    signals = []

    if outlier_ratio >= 10:
        signals.append(f"viral ({outlier_ratio:.0f}x median)")
    elif outlier_ratio >= 5:
        signals.append(f"strong outlier ({outlier_ratio:.0f}x median)")
    else:
        signals.append(f"outlier ({outlier_ratio:.1f}x median)")

    if video["engagement_rate"] > avg_engagement * 1.5:
        signals.append("high comments+likes ratio = strong opinion trigger")
    elif video["engagement_rate"] > avg_engagement:
        signals.append("above-avg engagement")

    dur = video["duration_minutes"]
    if 8 <= dur <= 15:
        signals.append(f"ideal length ({dur:.0f}min)")
    elif dur > 20:
        signals.append(f"long-form ({dur:.0f}min) — niche audience commits")
    elif dur < 5:
        signals.append(f"short ({dur:.0f}min) — hook-driven")

    return " | ".join(signals)
