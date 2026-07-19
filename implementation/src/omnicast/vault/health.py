"""Health check engine — re-scan evidence channels + find competitors via YouTube API."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from omnicast.discovery.key_rotator import YouTubeKeyRotator, youtube_get
from omnicast.discovery.youtube_scanner import YOUTUBE_API_BASE
from omnicast.vault.models import HealthCheckResult, NicheRecord, NicheStatus
from omnicast.vault.scoring import calculate_health_score, derive_status

logger = structlog.get_logger()

_LOOKBACK_DAYS = 21               # window for "new video" detection (21d = silence is serious signal)
_COMPETITOR_SUBS_MIN = 50_000     # threshold for "real competitor"
_COMPETITOR_DEDICATED_MIN = 3     # ≥ N dedicated channels = crowded
_MICRO_OUTLIER_SUBS_MAX = 10_000  # Tier 1: channel size for micro-outlier
_MICRO_OUTLIER_RATIO_MIN = 10.0   # outlier_x threshold for micro-outlier
_MICRO_OUTLIER_MIN_VIEWS = 50_000 # video must have ≥50k views to count as micro-outlier
_MICRO_OUTLIER_TOP_K = 10         # only check top-K results (ordered by viewCount)
_SHORTS_MIN_SECONDS = 120         # filter out videos < 2 min (Shorts inflate VPD) signal
# Tiered breakout: larger channels need higher view bars to qualify as starvation signal
_BREAKOUT_T2_SUBS_MAX = 50_000    # Tier 2: <50k subs + ≥100k views
_BREAKOUT_T2_MIN_VIEWS = 100_000
_BREAKOUT_T3_SUBS_MAX = 100_000   # Tier 3: <100k subs + ≥500k views (top-5 only)
_BREAKOUT_T3_MIN_VIEWS = 500_000
_BREAKOUT_T3_TOP_K = 5            # Tier 3 only counts if in absolute top-5


async def check_niche(
    record: NicheRecord,
    rotator: YouTubeKeyRotator,
    http: httpx.AsyncClient,
) -> HealthCheckResult:
    """Run health check for one niche. Returns result (does NOT write to DB)."""

    cutoff = (datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).isoformat()

    # ── 1. Check evidence channels ──────────────────────────────────────────
    new_videos_total = 0
    vpd_samples: list[float] = []

    for channel_id in record.evidence_channel_ids[:2]:  # top 2 only (quota)
        try:
            new_vids, vpds = await _fetch_recent_videos(channel_id, cutoff, rotator, http)
            new_videos_total += new_vids
            vpd_samples.extend(vpds)
        except Exception as exc:
            logger.warning("Evidence channel fetch failed",
                           channel_id=channel_id, error=str(exc))

    avg_new_vpd = sum(vpd_samples) / len(vpd_samples) if vpd_samples else 0.0

    # ── 2. Competitor search ────────────────────────────────────────────────
    search_query = _build_search_query(record)
    dedicated_competitors = 0
    micro_outlier_found = False
    try:
        dedicated_competitors, micro_outlier_found = await _search_competitors(
            search_query, cutoff, rotator, http
        )
    except Exception as exc:
        logger.warning("Competitor search failed",
                       niche_id=record.niche_id, error=str(exc))

    # ── 3. Scoring ──────────────────────────────────────────────────────────
    saved_dt = datetime.fromisoformat(record.saved_at.replace("Z", "+00:00"))
    days_since_save = max(0, (datetime.now(timezone.utc) - saved_dt).days)

    original_vpd = _extract_original_vpd(record)

    new_health = calculate_health_score(
        original_score=record.original_score,
        days_since_save=days_since_save,
        new_videos_count=new_videos_total,
        avg_new_vpd=avg_new_vpd,
        original_vpd=original_vpd,
        dedicated_competitors=dedicated_competitors,
        micro_outlier_found=micro_outlier_found,
    )

    new_status = derive_status(
        health_score=new_health,
        micro_outlier_found=micro_outlier_found,
        dedicated_competitors=dedicated_competitors,
        current_status=record.status,
    )

    delta = new_health - record.current_health
    notes: list[str] = []
    if micro_outlier_found:
        notes.append("⚡ Micro-outlier detected — content starvation signal")
    if dedicated_competitors >= _COMPETITOR_DEDICATED_MIN:
        notes.append(f"⚠ {dedicated_competitors} dedicated competitors found")
    if new_videos_total == 0:
        notes.append("Evidence channels: no new uploads in 14 days")

    return HealthCheckResult(
        niche_id=record.niche_id,
        old_status=record.status,
        new_status=new_status,
        old_score=record.current_health,
        new_score=new_health,
        score_delta=delta,
        new_videos_count=new_videos_total,
        avg_new_vpd=avg_new_vpd,
        dedicated_competitors=dedicated_competitors,
        micro_outlier_found=micro_outlier_found,
        notes=notes,
    )


async def check_all(
    records: list[NicheRecord],
    rotator: YouTubeKeyRotator,
    concurrency: int = 2,
) -> list[HealthCheckResult]:
    """Check multiple niches with limited concurrency (quota protection)."""
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=30.0) as http:
        async def _guarded(rec: NicheRecord) -> HealthCheckResult:
            async with sem:
                return await check_niche(rec, rotator, http)

        tasks = [_guarded(r) for r in records]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _yt_get(
    endpoint: str,
    params: dict,
    rotator: YouTubeKeyRotator,
    http: httpx.AsyncClient,
) -> dict:
    """Wrapper: call youtube_get with full URL, return parsed JSON dict."""
    url = f"{YOUTUBE_API_BASE}/{endpoint}"
    resp = await youtube_get(http, url, params, rotator)
    return resp.json()


def _parse_duration_seconds(iso_duration: str) -> int:
    """Parse ISO 8601 duration (PT1H2M30S) to total seconds. Returns 0 on failure."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    return h * 3600 + mins * 60 + secs


async def _fetch_recent_videos(
    channel_id: str,
    cutoff_iso: str,
    rotator: YouTubeKeyRotator,
    http: httpx.AsyncClient,
) -> tuple[int, list[float]]:
    """Return (long_form_video_count, [vpd, ...]) for non-Shorts published after cutoff.

    Shorts (< _SHORTS_MIN_SECONDS) are excluded from count and VPD to prevent
    competitors spamming Shorts from inflating the health signal.
    API cost: 3 units (channels + playlistItems + videos with contentDetails+statistics).
    """

    # Step 1: get uploads playlist ID (1 unit)
    ch_data = await _yt_get("channels", {
        "part": "contentDetails",
        "id": channel_id,
        "maxResults": "1",
    }, rotator, http)
    items = ch_data.get("items", [])
    if not items:
        return 0, []
    uploads_playlist = (
        items[0].get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads", "")
    )
    if not uploads_playlist:
        return 0, []

    # Step 2: list recent playlist items (1 unit)
    pl_data = await _yt_get("playlistItems", {
        "part": "snippet",
        "playlistId": uploads_playlist,
        "maxResults": "15",  # fetch more to compensate for Shorts being filtered out
    }, rotator, http)
    pl_items = pl_data.get("items", [])

    new_video_ids: list[tuple[str, str]] = []
    for item in pl_items:
        published = item.get("snippet", {}).get("publishedAt", "")
        vid_id = item.get("snippet", {}).get("resourceId", {}).get("videoId", "")
        if published >= cutoff_iso and vid_id:
            new_video_ids.append((vid_id, published))

    if not new_video_ids:
        return 0, []

    # Step 3: get duration + view counts in ONE call (1 unit)
    # contentDetails → duration (to filter Shorts), statistics → viewCount
    ids_str = ",".join(v[0] for v in new_video_ids)
    vid_data = await _yt_get("videos", {
        "part": "contentDetails,statistics,snippet",
        "id": ids_str,
    }, rotator, http)

    vpds: list[float] = []
    long_form_count = 0
    now = datetime.now(timezone.utc)

    for v in vid_data.get("items", []):
        duration_iso = v.get("contentDetails", {}).get("duration", "")
        duration_secs = _parse_duration_seconds(duration_iso)

        # Skip Shorts — they inflate VPD and don't reflect long-form content health
        if duration_secs < _SHORTS_MIN_SECONDS:
            continue

        long_form_count += 1
        views = int(v.get("statistics", {}).get("viewCount", 0))
        pub = v.get("snippet", {}).get("publishedAt", "")
        if pub:
            age_days = max(1.0, (now - datetime.fromisoformat(
                pub.replace("Z", "+00:00")
            )).total_seconds() / 86400)
            vpds.append(views / age_days)

    return long_form_count, vpds


async def _search_competitors(
    query: str,
    cutoff_iso: str,
    rotator: YouTubeKeyRotator,
    http: httpx.AsyncClient,
) -> tuple[int, bool]:
    """Search for recent videos on niche topic.

    Returns (dedicated_competitor_count, micro_outlier_found).
    dedicated  = channel with subs > 50k, appeared ≥2 times in top 20 results.
    micro_outlier = small channel (subs < 10k) with a high-view video (≥50k views)
                    in top-10 results — genuine content-starvation signal.
    """
    # search.list — 100 units (ordered by viewCount = highest views first)
    search_data = await _yt_get("search", {
        "part": "snippet",
        "q": query,
        "type": "video",
        "publishedAfter": cutoff_iso,
        "maxResults": "20",
        "order": "viewCount",
        "relevanceLanguage": "en",
    }, rotator, http)
    items = search_data.get("items", [])
    if not items:
        return 0, False

    # Collect unique channel IDs from all results
    channel_ids = list({
        item["snippet"]["channelId"]
        for item in items
        if item.get("snippet", {}).get("channelId")
    })
    if not channel_ids:
        return 0, False

    # Get subscriber counts (1 unit for up to 50 channels)
    ch_data = await _yt_get("channels", {
        "part": "statistics",
        "id": ",".join(channel_ids[:50]),
    }, rotator, http)

    # Map channel_id → subs
    subs_map: dict[str, int] = {}
    for ch in ch_data.get("items", []):
        cid = ch["id"]
        subs = int(ch.get("statistics", {}).get("subscriberCount", 0))
        subs_map[cid] = subs

    # Fetch view counts for top-K videos (micro-outlier check needs views)
    top_k_items = items[:_MICRO_OUTLIER_TOP_K]
    top_k_video_ids = [
        item["id"]["videoId"]
        for item in top_k_items
        if item.get("id", {}).get("videoId")
    ]
    video_views: dict[str, int] = {}
    if top_k_video_ids:
        try:
            vid_data = await _yt_get("videos", {
                "part": "statistics",
                "id": ",".join(top_k_video_ids),
            }, rotator, http)
            for v in vid_data.get("items", []):
                vid_views = int(v.get("statistics", {}).get("viewCount", 0))
                video_views[v["id"]] = vid_views
        except Exception:
            pass  # view count fetch failure → micro_outlier stays False

    dedicated = 0
    micro_outlier = False

    # Count appearances per channel across all 20 results (dedicated detection)
    channel_appearances: dict[str, int] = {}
    for item in items:
        cid = item["snippet"]["channelId"]
        channel_appearances[cid] = channel_appearances.get(cid, 0) + 1

    for cid, count in channel_appearances.items():
        subs = subs_map.get(cid, 0)
        if subs >= _COMPETITOR_SUBS_MIN and count >= 2:
            dedicated += 1

    # Tiered breakout: content starvation signal — small channel, big views
    # Tier 1: <10k subs + ≥50k views in top-K (strongest signal)
    # Tier 2: <50k subs + ≥100k views in top-K (medium channel punching up)
    # Tier 3: <100k subs + ≥500k views in absolute top-5 (bigger channel, harder bar)
    top3_items = items[:_BREAKOUT_T3_TOP_K]
    for idx, item in enumerate(top_k_items):
        cid = item["snippet"]["channelId"]
        vid_id = item.get("id", {}).get("videoId", "")
        subs = subs_map.get(cid, 0)
        views = video_views.get(vid_id, 0)
        if subs <= _MICRO_OUTLIER_SUBS_MAX and views >= _MICRO_OUTLIER_MIN_VIEWS:
            # Tier 1
            micro_outlier = True
            break
        if subs <= _BREAKOUT_T2_SUBS_MAX and views >= _BREAKOUT_T2_MIN_VIEWS:
            # Tier 2
            micro_outlier = True
            break
        if item in top3_items and subs <= _BREAKOUT_T3_SUBS_MAX and views >= _BREAKOUT_T3_MIN_VIEWS:
            # Tier 3 — only absolute top-5
            micro_outlier = True
            break

    return dedicated, micro_outlier


def _build_search_query(record: NicheRecord) -> str:
    """Build YouTube search query from niche data."""
    # Use niche_name + first seed query for better signal
    name = record.niche_name
    seeds = record.seed_queries
    if seeds:
        return f"{seeds[0]}"
    return name


def _extract_original_vpd(record: NicheRecord) -> float:
    """Get best VPD from saved evidence for comparison baseline."""
    evidence = record.niche_data.get("evidence", [])
    vpds = [e.get("views_per_day", 0) for e in evidence if e.get("views_per_day")]
    return max(vpds, default=1.0)
