"""Dynamic Seed Query Generator — Step 0 of niche discovery pipeline.

Replaces hardcoded SEED_QUERIES with real-time market signal.
5 techniques — first 2 run in parallel for enrichment, rest are fallback chain:

0. REDDIT PAIN-POINT HIJACK — r/personalfinance r/DIY r/psychology etc. top posts
   → extract real pain points people are asking about RIGHT NOW (no API key needed)
1. TRENDING HIJACK — YouTube chart=mostPopular today → LLM extracts niches
   + CATEGORY-FILTERED TRENDING — YouTube trending filtered to category 26/27/28
2. BROAD-TO-SPECIFIC — 5 generic terms → 500 recent videos → LLM deconstructs
3. GOOGLE TRENDS BREAKOUT — pytrends "breakout" keywords → seeds
4. FALLBACK — static SEED_QUERIES (last resort)

Multi-market: US, UK, AU, CA, JP, KR
Each market has region code + language + broad anchor terms.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import httpx
import structlog

from omnicast.discovery.youtube_scanner import YOUTUBE_API_BASE
from omnicast.discovery.key_rotator import YouTubeKeyRotator, youtube_get

logger = structlog.get_logger()

# ─── Market config ────────────────────────────────────────────────────────────

class MarketConfig(NamedTuple):
    region_code: str          # YouTube regionCode
    language: str             # relevanceLanguage
    broad_terms: list[str]    # Technique 2 anchor terms (in target language)
    trends_geo: str           # Google Trends geo code


MARKETS: dict[str, MarketConfig] = {
    "US": MarketConfig(
        region_code="US", language="en",
        broad_terms=["how to", "tips explained", "best ways", "why you should", "mistakes avoid"],
        trends_geo="US",
    ),
    "UK": MarketConfig(
        region_code="GB", language="en",
        broad_terms=["how to", "tips explained", "best ways", "why you should", "mistakes avoid"],
        trends_geo="GB",
    ),
    "AU": MarketConfig(
        region_code="AU", language="en",
        broad_terms=["how to", "tips explained", "best ways", "why you should", "mistakes avoid"],
        trends_geo="AU",
    ),
    "CA": MarketConfig(
        region_code="CA", language="en",
        broad_terms=["how to", "tips explained", "best ways", "why you should", "mistakes avoid"],
        trends_geo="CA",
    ),
    "JP": MarketConfig(
        region_code="JP", language="ja",
        broad_terms=["やり方", "解説", "おすすめ", "チャレンジ", "初心者向け"],
        trends_geo="JP",
    ),
    "KR": MarketConfig(
        region_code="KR", language="ko",
        broad_terms=["방법", "추천", "리뷰", "브이로그", "초보자"],
        trends_geo="KR",
    ),
}

# Reddit subreddits with high-RPM pain points (no API key, public JSON)
REDDIT_PAIN_SUBREDDITS = [
    "personalfinance",    # finance — high CPM ~$12-20
    "financialindependence",
    "DIY",                # home improvement — high CPM ~$8-15
    "homeimprovement",
    "psychology",         # mental health — high CPM ~$10-18
    "relationship_advice",
    "Dogtraining",        # pets — high CPM ~$6-12
    "Parenting",
    "selfimprovement",    # productivity/lifestyle
    "nutrition",          # health
]

# High-RPM YouTube categories for category-filtered trending (chart=mostPopular)
# 26=Howto&Style, 28=Science&Technology
# NOTE: cat 27=Education returns 404 on chart=mostPopular (not supported by YouTube API)
HIGH_RPM_CATEGORY_IDS = ["26", "28"]

# T5 Category Sweep — search.list (NOT chart=mostPopular, so all categories work)
# Sweeps by viewCount + publishedAfter, NO seed query needed → catches supernova blind spots
T5_SWEEP_CATEGORIES: dict[str, str] = {
    "26": "How-to & Style",           # DIY, cooking, lifestyle. RPM $10-15
    "27": "Education",                # Finance, investing, psychology. RPM $15-25+
    "28": "Science & Technology",     # AI, coding, tech review. RPM $12-20
    "19": "Travel & Events",          # Digital nomad, travel tips. RPM high (airlines/credit cards)
    "22": "People & Blogs",           # Hidden finance/psychology creators who leave default category
}

# YouTube video category IDs to KEEP (informational, not pure entertainment)
# Exclude: 10=Music, 20=Gaming, 24=Entertainment, 29=Nonprofits
KEEP_CATEGORY_IDS = {
    "1",   # Film & Animation (documentaries)
    "15",  # Pets & Animals
    "22",  # People & Blogs (lifestyle)
    "23",  # Comedy (some educational)
    "25",  # News & Politics
    "26",  # Howto & Style
    "27",  # Education
    "28",  # Science & Technology
    "17",  # Sports (fitness niches)
}

# Fallback if all techniques fail
FALLBACK_SEEDS = [
    "retirement income social security mistakes",
    "gut health microbiome repair diet",
    "perimenopause symptoms weight loss",
    "narcissist recovery relationship healing",
    "Roman Empire daily life ordinary people",
    "longevity medicine biohacking science",
    "ADHD adult diagnosis management",
    "dividend investing portfolio income",
    "homesteading self sufficiency beginners",
    "zone 2 cardio longevity protocol",
    "stoicism philosophy daily practice",
    "cold war untold spy stories",
    "HSA triple tax advantage investing",
    "autoimmune disease healing diet",
    "AI productivity workflow automation",
    "debt payoff strategies motivational",
    "trauma nervous system healing",
    "real estate cash flow rental property",
    "sleep optimization insomnia science",
    "ancient civilization collapse reasons",
]


class SeedQueryGenerator:
    """Generate fresh seed queries for a market at runtime."""

    def __init__(
        self,
        youtube_api_key: str | None = None,
        llm_client = None,             # omnicast.llm.client.LLMClient
        http_client: httpx.AsyncClient | None = None,
        rotator: YouTubeKeyRotator | None = None,
    ) -> None:
        if rotator is not None:
            self._rotator = rotator
        elif youtube_api_key:
            self._rotator = YouTubeKeyRotator([youtube_api_key])
        else:
            raise ValueError("SeedQueryGenerator requires youtube_api_key or rotator")
        self._llm = llm_client
        self._http = http_client or httpx.AsyncClient(timeout=30)

    async def generate(
        self,
        market: str = "US",
        target_count: int = 40,
    ) -> list[str]:
        """Generate seed queries for market. Returns list of search query strings."""
        cfg = MARKETS.get(market, MARKETS["US"])

        logger.info("Generating seeds", market=market, target=target_count)

        # Technique 0 + 1: Run Reddit pain-point hijack AND trending hijack in parallel
        # These are our best real-time signals — combine them for richer seed pool
        reddit_task = asyncio.create_task(self._reddit_pain_points(cfg, target_count // 2))
        trending_task = asyncio.create_task(self._trending_hijack(cfg, target_count))
        cat_trending_task = asyncio.create_task(
            self._category_filtered_trending(cfg, target_count // 2)
        )
        reddit_seeds, trending_seeds, cat_seeds = await asyncio.gather(
            reddit_task, trending_task, cat_trending_task, return_exceptions=True
        )
        reddit_seeds = reddit_seeds if isinstance(reddit_seeds, list) else []
        trending_seeds = trending_seeds if isinstance(trending_seeds, list) else []
        cat_seeds = cat_seeds if isinstance(cat_seeds, list) else []

        # Merge: category-filtered + Reddit seeds first (highest quality signal)
        # then trending, deduplicated
        combined: list[str] = []
        seen: set[str] = set()
        for seed_list in [cat_seeds, reddit_seeds, trending_seeds]:
            for s in seed_list:
                key = s.lower().strip()
                if key not in seen and len(key) >= 5:
                    seen.add(key)
                    combined.append(s)

        if len(combined) >= target_count // 2:
            logger.info(
                "Seeds via parallel enrichment",
                reddit=len(reddit_seeds),
                trending=len(trending_seeds),
                category=len(cat_seeds),
                combined=len(combined),
            )
            return combined[:target_count]

        # Technique 2: Broad-to-Specific
        seeds = await self._broad_to_specific(cfg, target_count)
        if seeds:
            logger.info("Seeds via broad-to-specific", count=len(seeds))
            return seeds

        # Technique 3: Google Trends Breakout
        seeds = await self._google_trends_breakout(cfg, target_count)
        if seeds:
            logger.info("Seeds via google trends", count=len(seeds))
            return seeds

        # Fallback
        logger.warning("All seed techniques failed, using fallback", market=market)
        return FALLBACK_SEEDS[:target_count]

    # ─── Technique 1: Trending Hijack ────────────────────────────────────────

    async def _trending_hijack(self, cfg: MarketConfig, target_count: int) -> list[str]:
        """Fetch YouTube trending videos → LLM extracts informational niches."""
        try:
            videos = await self._fetch_trending_videos(cfg.region_code, max_results=200)
            if len(videos) < 20:
                logger.warning("Trending returned too few videos", count=len(videos))
                return []

            # Filter to informational categories
            info_videos = [
                v for v in videos
                if v.get("category_id", "") in KEEP_CATEGORY_IDS
            ]
            # If filtering removes too many, use all
            if len(info_videos) < 15:
                info_videos = videos

            logger.info(
                "Trending videos fetched",
                total=len(videos),
                informational=len(info_videos),
                region=cfg.region_code,
            )

            seeds = await self._llm_extract_seeds_from_trending(
                info_videos, cfg, target_count
            )
            return seeds

        except Exception as exc:
            logger.warning("Trending hijack failed", error=str(exc))
            return []

    async def _fetch_trending_videos(
        self, region_code: str, max_results: int = 200
    ) -> list[dict]:
        """Fetch chart=mostPopular videos for region.

        Note: chart=mostPopular does NOT support publishedAfter —
        the endpoint returns today's trending list by definition (real-time).
        publishedAfter is irrelevant here; recency is guaranteed by the chart itself.
        """
        videos: list[dict] = []
        page_token: str | None = None
        pages_fetched = 0
        max_pages = max_results // 50 + 1

        while pages_fetched < max_pages and len(videos) < max_results:
            params: dict = {
                "chart": "mostPopular",
                "regionCode": region_code,
                "maxResults": 50,
                "part": "snippet",
            }
            if page_token:
                params["pageToken"] = page_token

            resp = await youtube_get(self._http, f"{YOUTUBE_API_BASE}/videos", params, self._rotator)
            data = resp.json()

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                cat_id = snippet.get("categoryId", "")
                title = snippet.get("title", "")
                tags = snippet.get("tags", [])[:10]
                channel = snippet.get("channelTitle", "")
                if title:
                    videos.append({
                        "title": title,
                        "tags": tags,
                        "channel": channel,
                        "category_id": cat_id,
                    })

            page_token = data.get("nextPageToken")
            pages_fetched += 1
            if not page_token:
                break

        return videos

    async def _llm_extract_seeds_from_trending(
        self,
        videos: list[dict],
        cfg: MarketConfig,
        target_count: int,
    ) -> list[str]:
        """LLM: from trending titles → extract informational niche seed queries."""
        # Compact format: just titles + tags
        video_lines = []
        for v in videos[:150]:
            tags_str = ", ".join(v.get("tags", [])[:5])
            line = v["title"]
            if tags_str:
                line += f" [{tags_str}]"
            video_lines.append(line)

        prompt = f"""These {len(video_lines)} videos are trending on YouTube in {cfg.region_code} TODAY.

TRENDING VIDEOS:
{chr(10).join(f"{i+1}. {l}" for i, l in enumerate(video_lines))}

TASK: Extract {target_count} specific INFORMATIONAL niche search queries from these trending topics.

RULES:
- ONLY generate queries for: finance, health, psychology, education, history, science, lifestyle, self-improvement
- HARD EXCLUDE (do NOT generate queries about): video games, gaming, Minecraft, Roblox, GTA, survival games, music, celebrity gossip, sports scores, movie/TV reviews, challenge videos, prank videos, vlogs without educational value
- If a trending video is about a video game (even survival/strategy games) → SKIP IT entirely
- Each query must be a specific search phrase someone would type on YouTube (3-7 words)
- Queries must reflect genuine demand for information/education in {cfg.region_code}
- Be specific: "perimenopause weight loss over 45" not "health tips"
- Language: English (translate/adapt non-English trending topics to English queries)
- Minimum quality bar: would this topic support a monetizable YouTube channel about education/information?

Return JSON only:
{{"seeds": ["query 1", "query 2", ..., "query {target_count}"]}}"""

        resp = await self._llm.complete(
            system="You are a YouTube niche analyst. Return valid JSON only. No markdown.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )
        return self._parse_seeds(resp.content, target_count)

    # ─── Technique 2: Broad-to-Specific ──────────────────────────────────────

    async def _broad_to_specific(self, cfg: MarketConfig, target_count: int) -> list[str]:
        """5 broad terms → 500 recent video titles → LLM deconstructs into niches."""
        try:
            published_after = (
                datetime.now(timezone.utc) - timedelta(days=30)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            all_titles: list[str] = []
            for term in cfg.broad_terms:
                titles = await self._search_titles(
                    term, cfg.region_code, cfg.language,
                    published_after=published_after,
                    max_results=100,
                )
                all_titles.extend(titles)
                if len(all_titles) >= 500:
                    break

            if len(all_titles) < 30:
                return []

            logger.info("Broad-to-specific titles collected", count=len(all_titles))

            seeds = await self._llm_deconstruct_titles(all_titles, cfg, target_count)
            return seeds

        except Exception as exc:
            logger.warning("Broad-to-specific failed", error=str(exc))
            return []

    async def _search_titles(
        self,
        query: str,
        region_code: str,
        language: str,
        published_after: str,
        max_results: int = 100,
    ) -> list[str]:
        """Search YouTube → collect video titles."""
        titles: list[str] = []
        page_token: str | None = None
        fetched = 0

        while fetched < max_results:
            batch = min(50, max_results - fetched)
            params: dict = {
                "q": query,
                "type": "video",
                "order": "viewCount",
                "maxResults": batch,
                "part": "snippet",
                "publishedAfter": published_after,
                "relevanceLanguage": language,
                "regionCode": region_code,
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                resp = await youtube_get(self._http, f"{YOUTUBE_API_BASE}/search", params, self._rotator)
                data = resp.json()
                for item in data.get("items", []):
                    title = item.get("snippet", {}).get("title", "")
                    if title:
                        titles.append(title)
                page_token = data.get("nextPageToken")
                fetched += batch
                if not page_token:
                    break
            except Exception:
                break

        return titles

    async def _llm_deconstruct_titles(
        self,
        titles: list[str],
        cfg: MarketConfig,
        target_count: int,
    ) -> list[str]:
        """LLM: deconstruct 500 recent video titles → specific niche seed queries."""
        sample = titles[:400]
        prompt = f"""These {len(sample)} video titles were recently published (last 30 days) in {cfg.region_code}.
They were found by searching broad generic terms.

VIDEO TITLES:
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(sample))}

TASK: Deconstruct these titles to find {target_count} SPECIFIC niche search queries.

METHOD:
- Look for recurring themes, topics, audience types
- Each theme → convert to a specific YouTube search query (3-7 words)
- If you see "vlog as stay-at-home mom", generate: "stay at home mom daily routine"
- If you see many fitness-over-40 videos, generate: "strength training over 40 beginners"
- Prioritize: finance, health, psychology, education, history, science, lifestyle
- Exclude: pure music, gaming, celebrity drama

Return JSON only:
{{"seeds": ["query 1", ..., "query {target_count}"]}}"""

        resp = await self._llm.complete(
            system="You are a YouTube niche analyst. Return valid JSON only. No markdown.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )
        return self._parse_seeds(resp.content, target_count)

    # ─── Technique 3: Google Trends Breakout ─────────────────────────────────

    async def _google_trends_breakout(
        self, cfg: MarketConfig, target_count: int
    ) -> list[str]:
        """Fetch breakout keywords from Google Trends → use as seeds."""
        try:
            from pytrends.request import TrendReq  # type: ignore

            pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))

            # Get related queries that are "breakout" (>5000% rise)
            # Use broad anchor terms to get related breakouts
            breakout_terms: list[str] = []

            for anchor in ["finance tips", "health advice", "life improvement"][:2]:
                try:
                    pytrends.build_payload(
                        [anchor],
                        cat=0,
                        timeframe="today 1-m",
                        geo=cfg.trends_geo,
                    )
                    related = pytrends.related_queries()
                    top = related.get(anchor, {}).get("rising")
                    if top is not None and not top.empty:
                        breakouts = top[top["value"] == 0]["query"].tolist()  # value=0 means "Breakout"
                        breakout_terms.extend(breakouts[:10])
                except Exception:
                    continue

            if not breakout_terms:
                return []

            logger.info("Google Trends breakout terms", count=len(breakout_terms))

            # Convert breakout terms → YouTube search queries via LLM
            prompt = f"""These keywords are BREAKING OUT on Google Trends in {cfg.trends_geo} right now (past 30 days):

{chr(10).join(f"- {t}" for t in breakout_terms[:30])}

Convert each breakout keyword into a specific YouTube search query (3-7 words) focused on:
finance, health, psychology, education, history, science, lifestyle.
Exclude: sports scores, celebrity news, music releases.

Return up to {target_count} queries as JSON:
{{"seeds": ["query 1", ..., "query N"]}}"""

            resp = await self._llm.complete(
                system="You are a YouTube niche analyst. Return valid JSON only. No markdown.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.2,
            )
            seeds = self._parse_seeds(resp.content, target_count)
            return seeds

        except ImportError:
            logger.warning("pytrends not installed, skipping Google Trends technique")
            return []
        except Exception as exc:
            logger.warning("Google Trends technique failed", error=str(exc))
            return []

    # ─── Technique 0: Reddit Pain-Point Hijack ───────────────────────────────

    async def _reddit_pain_points(self, cfg: MarketConfig, target_count: int) -> list[str]:
        """Scrape Reddit hot/top posts from high-RPM subreddits.

        No API key needed — uses Reddit's public JSON endpoint.
        Extracts pain points, questions, and topics from post titles.
        """
        if cfg.language != "en":
            return []  # Reddit pain-point technique is English-only

        try:
            titles: list[str] = []
            headers = {"User-Agent": "OmniCast/1.0 (niche research bot)"}

            for subreddit in REDDIT_PAIN_SUBREDDITS[:6]:  # top 6 subs, quota conscious
                try:
                    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=50"
                    resp = await self._http.get(url, headers=headers, follow_redirects=True)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    posts = data.get("data", {}).get("children", [])
                    for post in posts:
                        title = post.get("data", {}).get("title", "")
                        score = post.get("data", {}).get("score", 0)
                        # Only high-engagement posts signal real demand
                        if title and score >= 100 and len(title) >= 10:
                            titles.append(title)
                except Exception as e:
                    logger.debug("Reddit subreddit failed", sub=subreddit, error=str(e))
                    continue

            if len(titles) < 10:
                return []

            logger.info("Reddit pain points collected", count=len(titles))

            # LLM: convert Reddit pain point titles → YouTube search queries
            prompt = f"""These are top Reddit posts from personal finance, DIY, psychology, pet care, and self-improvement communities.
They represent REAL pain points people are actively searching for answers to.

REDDIT POSTS:
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(titles[:80]))}

TASK: Convert these Reddit pain points into {target_count} specific YouTube niche search queries.

METHOD:
- Each Reddit post reveals GENUINE DEMAND for educational content
- "My dog barks at everything" → "how to stop dog barking training"
- "Finally paid off $40k debt using..." → "debt payoff strategy snowball method"
- "I'm 45 and just diagnosed with ADHD" → "adult ADHD diagnosis late life management"
- Make each query specific (3-7 words), search-ready for YouTube
- Prioritize: finance, health, psychology, home, pets, self-improvement
- EXCLUDE: posts about politics, sports, entertainment, pure venting without actionable question

Return JSON only:
{{"seeds": ["query 1", ..., "query {target_count}"]}}"""

            resp = await self._llm.complete(
                system="You are a YouTube niche analyst. Return valid JSON only. No markdown.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
                temperature=0.3,
            )
            seeds = self._parse_seeds(resp.content, target_count)
            logger.info("Reddit pain-point seeds extracted", count=len(seeds))
            return seeds

        except Exception as exc:
            logger.warning("Reddit pain-point technique failed", error=str(exc))
            return []

    # ─── Technique 1b: Category-Filtered Trending ────────────────────────────

    async def _category_filtered_trending(
        self, cfg: MarketConfig, target_count: int
    ) -> list[str]:
        """Fetch YouTube trending filtered to high-RPM categories (26/27/28).

        Unlike generic trending (which includes music/gaming), this targets:
        26=Howto&Style, 27=Education, 28=Science&Technology
        — categories with CPM $8-25, exactly the niches we want.
        """
        try:
            all_videos: list[dict] = []
            for cat_id in HIGH_RPM_CATEGORY_IDS:
                try:
                    params = {
                        "chart": "mostPopular",
                        "regionCode": cfg.region_code,
                        "maxResults": "50",
                        "part": "snippet",
                        "videoCategoryId": cat_id,
                    }
                    resp = await youtube_get(
                        self._http, f"{YOUTUBE_API_BASE}/videos", params, self._rotator
                    )
                    data = resp.json()
                    for item in data.get("items", []):
                        snippet = item.get("snippet", {})
                        title = snippet.get("title", "")
                        tags = snippet.get("tags", [])[:5]
                        if title:
                            all_videos.append({
                                "title": title,
                                "tags": tags,
                                "category_id": cat_id,
                            })
                except Exception as e:
                    logger.debug("Category trending failed", cat=cat_id, error=str(e))
                    continue

            if len(all_videos) < 10:
                return []

            logger.info(
                "Category-filtered trending fetched",
                count=len(all_videos),
                region=cfg.region_code,
            )

            # Reuse the LLM extraction (same format as trending hijack)
            seeds = await self._llm_extract_seeds_from_trending(
                all_videos, cfg, target_count
            )
            logger.info("Category-filtered trending seeds", count=len(seeds))
            return seeds

        except Exception as exc:
            logger.warning("Category-filtered trending failed", error=str(exc))
            return []

    # ─── Technique 5: Category Sweeping (Supernova Radar) ────────────────────

    async def sweep_categories(
        self,
        market: str = "US",
        days_back: int = 7,
        videos_per_category: int = 100,
    ) -> list[str]:
        """T5 — Category Sweeping: find supernova channels without seed queries.

        Uses search.list with videoCategoryId + publishedAfter + order=viewCount.
        NO 'q' parameter — sweeps ALL videos in category by recency + views.
        Catches niches that never trend on Reddit/Google (e.g. "vintage scissors restoration").

        Returns: list of YouTube channel IDs (feeds NicheScanner as pre_channel_ids).
        Cost: 100 units × 2 pages × 5 categories = 1,000 units/run.
        """
        cfg = MARKETS.get(market, MARKETS["US"])
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=days_back)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        channel_ids: list[str] = []
        seen: set[str] = set()

        for cat_id, cat_name in T5_SWEEP_CATEGORIES.items():
            try:
                ids = await self._sweep_one_category(
                    cat_id=cat_id,
                    region_code=cfg.region_code,
                    published_after=published_after,
                    max_videos=videos_per_category,
                )
                new = [cid for cid in ids if cid not in seen]
                seen.update(new)
                channel_ids.extend(new)
                logger.info(
                    "T5 category sweep",
                    category=cat_name,
                    cat_id=cat_id,
                    channels_found=len(new),
                )
            except Exception as exc:
                logger.warning("T5 sweep failed for category", cat_id=cat_id, error=str(exc))
                continue

        logger.info("T5 sweep complete", total_channels=len(channel_ids), market=market)
        return channel_ids

    async def _sweep_one_category(
        self,
        cat_id: str,
        region_code: str,
        published_after: str,
        max_videos: int = 100,
    ) -> list[str]:
        """Fetch top-viewed recent videos in a category → extract unique channel IDs.

        API: search.list, type=video, videoCategoryId, order=viewCount.
        'q' intentionally OMITTED — no seed query bias.
        """
        channel_ids: list[str] = []
        seen_cids: set[str] = set()
        page_token: str | None = None
        fetched = 0

        while fetched < max_videos:
            batch = min(50, max_videos - fetched)
            params: dict = {
                "type": "video",
                "videoCategoryId": cat_id,
                "publishedAfter": published_after,
                "order": "viewCount",
                "maxResults": batch,
                "part": "snippet",
                "regionCode": region_code,
                # NO 'q' parameter — sweep by category only
            }
            if page_token:
                params["pageToken"] = page_token

            resp = await youtube_get(
                self._http, f"{YOUTUBE_API_BASE}/search", params, self._rotator
            )
            data = resp.json()

            for item in data.get("items", []):
                cid = item.get("snippet", {}).get("channelId", "")
                if cid and cid not in seen_cids:
                    seen_cids.add(cid)
                    channel_ids.append(cid)

            page_token = data.get("nextPageToken")
            fetched += batch
            if not page_token:
                break

        return channel_ids

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _parse_seeds(self, content: str, target_count: int) -> list[str]:
        """Parse LLM JSON output → list of seed query strings.

        Primary: json.loads on the full response.
        Fallback: regex extraction of quoted strings when JSON is truncated
                  (happens when max_tokens cuts the response mid-array).
        """
        text = content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE)

        # Primary: clean JSON parse
        try:
            data = json.loads(text)
            seeds = data.get("seeds", [])
        except Exception:
            # Fallback: regex — extract all quoted strings from partial JSON
            # Matches "anything between 5-120 chars that looks like a search query"
            seeds = re.findall(r'"([^"]{5,120})"', text)
            # Strip likely JSON key names (short, no spaces)
            seeds = [s for s in seeds if " " in s or len(s) > 20]
            if seeds:
                logger.info("Seed parse fallback (regex)", extracted=len(seeds))
            else:
                logger.warning("Seed parse failed entirely, content snippet",
                               snippet=text[:200])

        # Clean: strip whitespace, deduplicate, min 5 chars
        seen: set[str] = set()
        clean: list[str] = []
        for s in seeds:
            s = str(s).strip()
            if len(s) >= 5 and s.lower() not in seen:
                seen.add(s.lower())
                clean.append(s)
        return clean[:target_count]
