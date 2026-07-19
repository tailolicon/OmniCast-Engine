"""Broad YouTube niche discovery scanner.

Fixes applied (per Gemini critique):
1. publishedAfter=90d — no stale 2019 viral videos polluting signal
2. MIN_SUBSCRIBERS=1000 — catch "supernova" channels: 500 subs, 200k views
3. Shorts filter — duration < 60s excluded before computing outlier_ratio
4. views_per_day — velocity metric: 500k/5days >> 1M/5years

Signal philosophy:
- SUPERNOVA: subs < 10k, outlier > 10x → algorithm hungry, niche untapped
- EMERGING: subs < 300k, outlier > 5x → demand proven, no dominant channel yet
- SATURATED: subs > 1M dominating → skip

LLM hallucination fix:
- Each video assigned ID "C{i}_V{j}"
- LLM returns evidence_ids only, Python maps back to real data
"""

from __future__ import annotations

import asyncio
import re
import statistics
import time
from collections import Counter
from typing import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import structlog

try:
    from langdetect import detect_langs as _detect_langs
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False

from omnicast.discovery.youtube_scanner import YOUTUBE_API_BASE
from omnicast.discovery.key_rotator import YouTubeKeyRotator, QuotaExhaustedError, youtube_get

logger = structlog.get_logger()

def _safe_log(s: str) -> str:
    """Safely encode strings for Windows console to prevent UnicodeEncodeError."""
    if not isinstance(s, str): return str(s)
    return s.encode("ascii", "replace").decode("ascii")

SEED_QUERIES = [
    # Finance — specific pain points
    "retirement income social security mistakes",
    "401k rollover rules avoid penalties",
    "dividend investing portfolio income",
    "real estate cash flow rental property",
    "tax reduction strategies self employed",
    "FIRE movement early retirement math",
    "HSA triple tax advantage investing",
    "I bonds inflation beating explained",
    "debt payoff strategies motivational",
    "frugal living money saving extreme",
    # Health — specific conditions + demographics
    "perimenopause symptoms weight loss",
    "gut health microbiome repair diet",
    "zone 2 cardio longevity protocol",
    "autoimmune disease healing diet",
    "sleep optimization insomnia science",
    "strength training over 50 benefits",
    "inflammation chronic disease reverse",
    "carnivore diet results transformation",
    "hormone replacement therapy explained",
    "red light therapy peptides research",
    # Psychology / Mental health
    "narcissist recovery relationship healing",
    "ADHD adult diagnosis management",
    "trauma nervous system healing",
    "anxious attachment style relationship",
    "stoicism philosophy daily practice",
    # History — specific eras, not generic
    "Roman Empire daily life ordinary people",
    "Cold War untold spy stories",
    "medieval peasant life explained",
    "ancient civilization collapse reasons",
    "forgotten history events never taught",
    # Science / Tech — emerging
    "longevity medicine biohacking science",
    "AI productivity workflow automation",
    "quantum biology explained simply",
    "neuroscience habit formation brain",
    "nuclear energy future explained",
    # Lifestyle — specific communities
    "homesteading self sufficiency beginners",
    "van life remote work reality check",
    "expat retirement abroad cheap",
    "prepper practical skills emergency",
    "Japanese minimalism philosophy wabi sabi",
]

MAX_RESULTS_PER_QUERY = 8
MAX_CHANNELS_TOTAL = 120
VIDEOS_PER_CHANNEL = 30
MIN_SUBSCRIBERS = 1_000        # FIX 2: was 10k — supernova channels start here
MAX_SUBSCRIBERS = 5_000_000
PUBLISHED_AFTER_DAYS = 90      # FIX 1: only recent videos
MIN_DURATION_SECONDS = 61      # FIX 3: filter Shorts (<= 60s)

OUTLIER_SUPERNOVA = 10.0       # subs < 10k + outlier > 10x = untapped niche signal
OUTLIER_HIGH = 5.0             # emerging channel viral proof
OUTLIER_MED = 2.5

# FIX 5: min velocity for supernova — 45 views/day is NOT a signal
MIN_VPD_SUPERNOVA = 200.0

# Tiered Breakout Signal (Gemini sliding scale)
# A channel with 54k subs + 111x outlier IS a supernova — the 10k cap missed it.
# Tier 1 (Zero-Authority): subs < 10k  AND outlier > 10x  AND max_views > 50k
# Tier 2 (Emerging):       subs < 50k  AND outlier > 15x
# Tier 3 (Growth):         subs < 100k AND outlier > 20x
BREAKOUT_T1_SUBS    = 10_000;  BREAKOUT_T1_OUTLIER = 10.0;  BREAKOUT_T1_VIEWS = 50_000
BREAKOUT_T2_SUBS    = 50_000;  BREAKOUT_T2_OUTLIER = 15.0
BREAKOUT_T3_SUBS    = 100_000; BREAKOUT_T3_OUTLIER = 20.0

# FIX 6: markets where channels must be English
ENGLISH_MARKETS = {"US", "UK", "AU", "CA"}

# Low-RPM country codes — drop when scanning high-RPM English markets
# snippet.country may be unset (empty) → still pass (benefit of doubt)
LOW_RPM_COUNTRIES = frozenset({
    "IN",  # India   (~$1-2 RPM)
    "PK",  # Pakistan
    "BD",  # Bangladesh
    "NG",  # Nigeria (~$1 RPM)
    "PH",  # Philippines
    "VN",  # Vietnam
    "EG",  # Egypt
    "KE",  # Kenya
    "GH",  # Ghana
    "ET",  # Ethiopia
    "ID",  # Indonesia
    "MY",  # Malaysia
    "TH",  # Thailand
    "LK",  # Sri Lanka
    "NP",  # Nepal
})

# FIX 7: gaming channel name keywords — these niches are saturated & wrong audience
# YouTube videoCategoryId values that are off-topic for our faceless-content niches.
# 20 = Gaming, 10 = Music (catches lyrics channels). Authoritative genre signal from
# the API — supersedes brittle channel-name keyword matching.
_OFFTOPIC_CATEGORY_IDS = frozenset({"20", "10"})

GAMING_KEYWORDS = frozenset({
    "gaming", "gamer", "gameplay", "minecraft", "roblox", "fortnite", "gta",
    "warzone", "valorant", "league of legends", "overwatch", "esports",
    "speedrun", "let's play", "lets play", "game review", "assassin's creed",
    "assassins creed", "call of duty", "pokemon", "zelda", "game pass",
    "twitch", "xbox", "playstation", "nintendo", "steam games",
})

# FIX 8: music lyrics channels — not real content niches, no RPM value
LYRICS_KEYWORDS = frozenset({
    "lyrics", "lyric video", "rap lyrics", "song lyrics", "music lyrics",
    "letra", "paroles",
})


@dataclass
class NicheChannelData:
    channel_id: str
    channel_name: str
    subscribers: int
    median_views: float
    top_outlier_ratio: float
    avg_engagement_rate: float
    comment_view_ratio: float
    top_videos: list[dict]          # [{id, title, views, views_per_day, outlier_x}]
    seed_query: str
    is_emerging: bool               # subs < 300k
    is_supernova: bool              # subs < 10k AND outlier > 10x (Tier 1)
    has_viral_proof: bool           # outlier >= OUTLIER_HIGH
    is_breakout: bool = False       # tiered signal: Tier1|2|3 breakout channel
    breakout_tier: int = 0          # 1/2/3 = which tier triggered
    video_count_sampled: int = 0    # long-form only


# Unicode block ranges for non-Latin scripts
# Cyrillic: U+0400-04FF | Devanagari: U+0900-097F | Arabic: U+0600-06FF
# CJK Unified: U+4E00-9FFF | Hebrew: U+0590-05FF | Thai: U+0E00-0E7F
_NON_LATIN_RANGES = (
    (0x0400, 0x04FF),  # Cyrillic
    (0x0600, 0x06FF),  # Arabic
    (0x0900, 0x097F),  # Devanagari (Hindi)
    (0x0E00, 0x0E7F),  # Thai
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0xAC00, 0xD7AF),  # Hangul Syllables
    (0x0590, 0x05FF),  # Hebrew
)


def _non_latin_ratio(text: str) -> float:
    """Fraction of characters in text that belong to non-Latin scripts."""
    if not text:
        return 0.0
    non_latin = sum(
        1 for ch in text
        if any(lo <= ord(ch) <= hi for lo, hi in _NON_LATIN_RANGES)
    )
    return non_latin / len(text)


# Non-US market currency symbols in video titles = strong signal of non-US audience.
# ₹ Indian Rupee (U+20B9), ₦ Nigerian Naira (U+20A6), ₱ Philippine Peso (U+20B1),
# ৳ Bangladeshi Taka (U+09F3), ₨ Pakistani Rupee (U+20A8)
_NON_US_CURRENCY = frozenset("₹₦₱৳₨")


def _contains_non_us_currency(title: str) -> bool:
    """Return True if title contains a non-US currency symbol (Indian ₹, etc.)."""
    return any(ch in _NON_US_CURRENCY for ch in title)


def _is_english_by_langdetect(titles: list[str], min_en_prob: float = 0.80) -> bool:
    """Use langdetect to verify majority of titles are English.

    Catches French/Indonesian/Spanish that pass Unicode range check (all Latin script).
    Samples up to 5 titles concatenated to get better detection accuracy.
    Falls back to True (allow) if langdetect unavailable or detection fails.
    """
    if not _LANGDETECT_AVAILABLE or not titles:
        return True
    sample = " ".join(titles[:5])
    if len(sample) < 20:
        return True
    try:
        langs = _detect_langs(sample)
        en_prob = next((l.prob for l in langs if l.lang == "en"), 0.0)
        return en_prob >= min_en_prob
    except Exception:
        return True  # fail-open: don't block on detection error


def _is_english_content(titles: list[str], threshold: float = 0.15) -> bool:
    """Return True if majority of video titles appear to be Latin/English.

    threshold: max allowed fraction of non-Latin chars per title before it
               counts as non-English. A title with >threshold non-Latin chars
               is flagged. If >= half the titles are flagged → not English content.
    Also flags titles containing non-US currency symbols (₹, ₦, ₱, etc.).
    """
    if not titles:
        return True
    flagged = sum(
        1 for t in titles
        if _non_latin_ratio(t) > threshold or _contains_non_us_currency(t)
    )
    return flagged / len(titles) < 0.5


def _parse_duration_seconds(duration: str) -> int:
    """Parse ISO 8601 like PT4M30S → seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mn * 60 + s


def _views_per_day(views: int, published_at: str) -> float:
    """FIX 4: velocity metric. 500k/5days >> 1M/5years."""
    if not published_at:
        return 0.0
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        days = max(1, (datetime.now(timezone.utc) - pub).days)
        return round(views / days, 1)
    except Exception:
        return 0.0


class NicheScanner:
    def __init__(
        self,
        api_key: str | None = None,
        market: str = "US",
        http_client: httpx.AsyncClient | None = None,
        rotator: YouTubeKeyRotator | None = None,
    ) -> None:
        if rotator is not None:
            self._rotator = rotator
        elif api_key:
            self._rotator = YouTubeKeyRotator([api_key])
        else:
            raise ValueError("NicheScanner requires api_key or rotator")
        self._http = http_client or httpx.AsyncClient(timeout=30)
        self._market = market.upper()
        cutoff = datetime.now(timezone.utc) - timedelta(days=PUBLISHED_AFTER_DAYS)
        self._published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Market-aware region + language for search
        from omnicast.discovery.seed_generator import MARKETS
        cfg = MARKETS.get(market, MARKETS["US"])
        self._region_code = cfg.region_code
        self._language = cfg.language

    async def scan(
        self,
        seed_queries: list[str] | None = None,
        pre_channel_ids: list[str] | None = None,
        progress_cb: Callable[[dict], None] | None = None,
    ) -> list[NicheChannelData]:
        """Scan channels for niche signals.

        Args:
            seed_queries:    T0-T4 seed queries → search YouTube → find channels.
            pre_channel_ids: T5 channel IDs from category sweep → bypass search,
                             go directly to stats+sampling. Merged with seed results.
            progress_cb:     optional callback fired with a small dict per sub-step
                             (per query searched, per sample batch) so the operator
                             UI can narrate, in realtime, exactly what the scanner
                             is doing — instead of one coarse "Searching…" line.
        """
        def _p(event: dict) -> None:
            if progress_cb:
                try:
                    progress_cb(event)
                except Exception:
                    pass

        queries = seed_queries or SEED_QUERIES
        t0 = time.monotonic()

        channel_query_map: dict[str, str] = {}

        # Pre-inject T5 channels (category sweep) — label with special seed tag
        if pre_channel_ids:
            for cid in pre_channel_ids:
                if cid not in channel_query_map:
                    channel_query_map[cid] = "t5_category_sweep"
            logger.info("T5 pre-channels injected", count=len(pre_channel_ids))

        for qi, query in enumerate(queries):
            ids = await self._search_channels(query)
            for cid in ids:
                if cid not in channel_query_map:
                    channel_query_map[cid] = query
            _p({"type": "niche_search", "agent": "scanner", "query": query,
                "found": len(ids), "total_channels": len(channel_query_map),
                "q_idx": qi + 1, "q_total": len(queries),
                "elapsed_s": round(time.monotonic() - t0, 1)})
            if len(channel_query_map) >= MAX_CHANNELS_TOTAL * 2:
                break

        channel_stats = await self._fetch_channel_stats(list(channel_query_map.keys()))
        _p({"type": "niche_stats", "agent": "scanner",
            "fetched": len(channel_stats),
            "elapsed_s": round(time.monotonic() - t0, 1)})

        # Filter candidates before sampling
        candidates = []
        for cid, stats in channel_stats.items():
            if len(candidates) >= MAX_CHANNELS_TOTAL:
                break
            subs = stats.get("subscribers", 0)
            if subs < MIN_SUBSCRIBERS or subs > MAX_SUBSCRIBERS:
                continue
            name_lower = stats["name"].lower()
            if any(kw in name_lower for kw in GAMING_KEYWORDS):
                logger.debug("Skipping gaming channel", channel=_safe_log(stats["name"]))
                continue
            if any(kw in name_lower for kw in LYRICS_KEYWORDS):
                logger.debug("Skipping lyrics channel", channel=_safe_log(stats["name"]))
                continue
            candidates.append((cid, stats))

        _p({"type": "niche_filter", "agent": "research",
            "candidates": len(candidates), "from_total": len(channel_stats),
            "elapsed_s": round(time.monotonic() - t0, 1)})

        # Concurrent sampling — 10 at a time to avoid rate-limiting
        CONCURRENCY = 10
        raw_results: list[NicheChannelData | None] = []
        for i in range(0, len(candidates), CONCURRENCY):
            batch = candidates[i:i + CONCURRENCY]
            tasks = [
                self._sample_channel(
                    channel_id=cid,
                    channel_name=stats["name"],
                    subscribers=stats.get("subscribers", 0),
                    seed_query=channel_query_map.get(cid, ""),
                )
                for cid, stats in batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in batch_results:
                if isinstance(r, Exception):
                    logger.debug("Sample channel error", error=str(r)[:100])
                elif r is not None:
                    raw_results.append(r)
            done = min(i + CONCURRENCY, len(candidates))
            # Realtime ETA from measured throughput (avg time per channel so far),
            # not a hardcoded guess — fixes the wrong "≈40s" estimate.
            el = time.monotonic() - t0
            rate = el / done if done else 0
            eta = round(rate * (len(candidates) - done))
            last = raw_results[-1].channel_name if raw_results else ""
            _p({"type": "niche_sample", "agent": "research",
                "done": done, "total": len(candidates), "last_channel": last,
                "elapsed_s": round(el, 1), "eta_s": eta})

        results = [r for r in raw_results if r is not None]

        # Sort: breakout/supernova first, then viral proof, then by outlier ratio
        results.sort(
            key=lambda c: (c.is_breakout, c.is_supernova, c.has_viral_proof, c.is_emerging, c.top_outlier_ratio),
            reverse=True,
        )

        supernova = sum(1 for c in results if c.is_supernova)
        viral = sum(1 for c in results if c.has_viral_proof)
        emerging = sum(1 for c in results if c.is_emerging)
        logger.info(
            "Niche scan complete",
            total=len(results),
            supernova=supernova,
            viral_proof=viral,
            emerging=emerging,
        )
        return results

    async def _search_channels(self, query: str) -> list[str]:
        """FIX 1: publishedAfter ensures only recent content."""
        try:
            resp = await youtube_get(
                self._http,
                f"{YOUTUBE_API_BASE}/search",
                {
                    "q": query,
                    "type": "video",
                    "order": "viewCount",
                    "maxResults": MAX_RESULTS_PER_QUERY,
                    "part": "snippet",
                    "publishedAfter": self._published_after,
                    "videoDuration": "medium",
                    "relevanceLanguage": self._language,
                    "regionCode": self._region_code,
                },
                self._rotator,
            )
            seen: set[str] = set()
            ids: list[str] = []
            for item in resp.json().get("items", []):
                cid = item.get("snippet", {}).get("channelId", "")
                if cid and cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
            return ids
        except Exception as exc:
            logger.warning("Search failed", query=_safe_log(query[:40]), error=str(exc))
            return []

    async def _fetch_channel_stats(self, channel_ids: list[str]) -> dict[str, dict]:
        stats: dict[str, dict] = {}
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i + 50]
            try:
                resp = await youtube_get(
                    self._http,
                    f"{YOUTUBE_API_BASE}/channels",
                    {"id": ",".join(batch), "part": "snippet,statistics,contentDetails"},
                    self._rotator,
                )
                for item in resp.json().get("items", []):
                    cid = item["id"]
                    stat = item.get("statistics", {})
                    snippet = item.get("snippet", {})

                    # FIX 6: language + country filter for English high-RPM markets
                    if self._market in ENGLISH_MARKETS:
                        default_lang = snippet.get("defaultLanguage", "")
                        if default_lang and not default_lang.startswith("en"):
                            logger.debug(
                                "Skipping non-English channel",
                                channel=_safe_log(snippet.get("title", "?")),
                                lang=default_lang,
                            )
                            continue
                        country = snippet.get("country", "")
                        if country and country.upper() in LOW_RPM_COUNTRIES:
                            logger.debug(
                                "Skipping low-RPM country channel",
                                channel=_safe_log(snippet.get("title", "?")),
                                country=country,
                            )
                            continue

                    stats[cid] = {
                        "name": snippet.get("title", ""),
                        "subscribers": int(stat.get("subscriberCount", 0)),
                        "uploads_playlist": (
                            item.get("contentDetails", {})
                            .get("relatedPlaylists", {})
                            .get("uploads", "")
                        ),
                    }
            except Exception as exc:
                logger.warning("Channel stats batch failed", error=str(exc))
        return stats

    async def _sample_channel(
        self,
        channel_id: str,
        channel_name: str,
        subscribers: int,
        seed_query: str,
    ) -> NicheChannelData | None:
        try:
            # Get uploads playlist
            ch_resp = await youtube_get(
                self._http,
                f"{YOUTUBE_API_BASE}/channels",
                {"id": channel_id, "part": "contentDetails"},
                self._rotator,
            )
            ch_items = ch_resp.json().get("items", [])
            if not ch_items:
                return None
            uploads = (
                ch_items[0].get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads", "")
            )
            if not uploads:
                return None

            # Get recent video IDs
            pl_resp = await youtube_get(
                self._http,
                f"{YOUTUBE_API_BASE}/playlistItems",
                {"playlistId": uploads, "maxResults": VIDEOS_PER_CHANNEL, "part": "contentDetails"},
                self._rotator,
            )
            video_ids = [
                item["contentDetails"]["videoId"]
                for item in pl_resp.json().get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            if not video_ids:
                return None

            # FIX 3: contentDetails → duration → filter Shorts
            v_resp = await youtube_get(
                self._http,
                f"{YOUTUBE_API_BASE}/videos",
                {"id": ",".join(video_ids), "part": "statistics,snippet,contentDetails"},
                self._rotator,
            )

            views_list: list[int] = []
            engagement_list: list[float] = []
            comment_rates: list[float] = []
            titled_videos: list[tuple[int, str, float, str, str]] = []  # (views, title, vpd, pub_at, video_id)
            audio_langs: list[str] = []      # video-level defaultAudioLanguage (real audience signal)
            category_ids: list[str] = []     # video-level categoryId (authoritative genre)

            for vitem in v_resp.json().get("items", []):
                # FIX 3: skip Shorts
                duration_str = (
                    vitem.get("contentDetails", {}).get("duration", "")
                )
                duration_s = _parse_duration_seconds(duration_str)
                if duration_s < MIN_DURATION_SECONDS:
                    continue

                stat = vitem.get("statistics", {})
                vsnip = vitem.get("snippet", {})
                v = int(stat.get("viewCount", 0))
                likes = int(stat.get("likeCount", 0))
                comments = int(stat.get("commentCount", 0))
                title = vsnip.get("title", "")
                published_at = vsnip.get("publishedAt", "")

                if v < 100:
                    continue

                # Real audience-language signal: the SPOKEN audio, not the (clickbait)
                # English title. Many low-RPM IN/ID channels write English titles but
                # narrate in a local language — this catches them (Gemini gap #1).
                al = (vsnip.get("defaultAudioLanguage") or "").strip().lower()
                if al:
                    audio_langs.append(al)
                cat_id = str(vsnip.get("categoryId") or "").strip()
                if cat_id:
                    category_ids.append(cat_id)

                # FIX 4: velocity
                vpd = _views_per_day(v, published_at)

                vid_id = vitem.get("id", "")
                views_list.append(v)
                engagement_list.append((likes + comments) / v)
                comment_rates.append(comments / v)
                titled_videos.append((v, title, vpd, published_at, vid_id))

            if len(views_list) < 3:
                return None

            # Genre filter by YouTube categoryId (authoritative) rather than only the
            # brittle channel-name keyword match (Gemini gap #2). A game that isn't in
            # GAMING_KEYWORDS still carries categoryId 20; "Board Gaming Finance" won't
            # be misclassified. Skip when the MAJORITY of a channel's long-form videos
            # sit in an off-topic category (Gaming/Music-lyrics).
            if category_ids:
                dominant_cat, cat_n = Counter(category_ids).most_common(1)[0]
                if cat_n / len(category_ids) >= 0.5 and dominant_cat in _OFFTOPIC_CATEGORY_IDS:
                    logger.info("Skipping off-topic category channel",
                                channel=_safe_log(channel_name),
                                category_id=dominant_cat)
                    return None

            # Language check via video titles — only for English markets
            # Layer 0: real audio language (defaultAudioLanguage) — strongest signal.
            # Layer 1: Unicode range check (catches Cyrillic/Arabic/CJK/Hindi)
            # Layer 2: langdetect (catches French/Indonesian/Spanish Latin script)
            if self._market in ENGLISH_MARKETS:
                # Layer 0: if the channel DECLARES its spoken language on a majority of
                # videos and it isn't English, drop it — beats title-only detection for
                # local-language channels using English clickbait titles (Gemini gap #1).
                if audio_langs:
                    en_audio = sum(1 for a in audio_langs if a.startswith("en"))
                    if en_audio / len(audio_langs) < 0.5:
                        logger.info("Skipping non-English audio channel",
                                    channel=_safe_log(channel_name),
                                    audio_sample=",".join(sorted(set(audio_langs))[:4]))
                        return None
                all_titles = [t for _, t, _, _, _ in titled_videos]
                if not _is_english_content(all_titles):
                    logger.debug(
                        "Skipping non-English content channel",
                        channel=_safe_log(channel_name),
                        sample_title=_safe_log(all_titles[0][:50]) if all_titles else "",
                    )
                    return None
                # langdetect second pass — catches Latin-script non-English
                if _LANGDETECT_AVAILABLE and not _is_english_by_langdetect(all_titles):
                    logger.info(
                        "Skipping non-English channel (langdetect)",
                        channel=_safe_log(channel_name),
                        sample=_safe_log(all_titles[0][:60]) if all_titles else "",
                    )
                    return None

            median_views = statistics.median(views_list)
            if median_views == 0:
                return None

            max_views = max(views_list)
            top_outlier_ratio = round(max_views / median_views, 1)
            avg_engagement = round(sum(engagement_list) / len(engagement_list), 5)
            avg_comment_rate = round(sum(comment_rates) / len(comment_rates), 5)

            # Top 3 videos by views — include views_per_day + video_id for links
            titled_videos.sort(key=lambda x: x[0], reverse=True)
            top_videos = [
                {
                    "title": t[:80],
                    "views": v,
                    "views_per_day": vpd,
                    "outlier_x": round(v / median_views, 1),
                    "video_id": vid_id,
                }
                for v, t, vpd, _, vid_id in titled_videos[:3]
            ]

            is_emerging = subscribers < 300_000
            has_viral_proof = top_outlier_ratio >= OUTLIER_HIGH
            max_vpd = max((vpd for _, _, vpd, _, _ in titled_videos), default=0.0)
            max_views = max(views_list)

            # Supernova: Tier 1 only (original definition, kept for backward compat)
            is_supernova = (
                subscribers < BREAKOUT_T1_SUBS
                and top_outlier_ratio >= OUTLIER_SUPERNOVA
                and max_vpd >= MIN_VPD_SUPERNOVA
            )

            # Tiered Breakout Signal — catches the 3 gold mines that 10k cap missed
            # Tier 1: Zero-Authority — tiny channel nailing it
            # Tier 2: Emerging — mid channel with massive outlier (Aussie Finance, Explains A Lot)
            # Tier 3: Growth — larger channel with extreme outlier (No Fluff Academy)
            breakout_tier = 0
            if subscribers < BREAKOUT_T1_SUBS and top_outlier_ratio >= BREAKOUT_T1_OUTLIER and max_views >= BREAKOUT_T1_VIEWS:
                breakout_tier = 1
            elif subscribers < BREAKOUT_T2_SUBS and top_outlier_ratio >= BREAKOUT_T2_OUTLIER:
                breakout_tier = 2
            elif subscribers < BREAKOUT_T3_SUBS and top_outlier_ratio >= BREAKOUT_T3_OUTLIER:
                breakout_tier = 3
            is_breakout = breakout_tier > 0

            return NicheChannelData(
                channel_id=channel_id,
                channel_name=channel_name,
                subscribers=subscribers,
                median_views=round(median_views),
                top_outlier_ratio=top_outlier_ratio,
                avg_engagement_rate=avg_engagement,
                comment_view_ratio=avg_comment_rate,
                top_videos=top_videos,
                seed_query=seed_query,
                is_emerging=is_emerging,
                is_supernova=is_supernova,
                has_viral_proof=has_viral_proof,
                is_breakout=is_breakout,
                breakout_tier=breakout_tier,
                video_count_sampled=len(views_list),
            )

        except Exception as exc:
            logger.warning("Channel sample failed", channel=_safe_log(channel_name), error=str(exc))
            return None
