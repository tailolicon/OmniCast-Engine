"""Public YouTube channel stats via Data API v3 (API key, no OAuth).

channels.list with part=snippet,statistics returns public counts (subscribers
unless hidden, total views, video count) + the channel avatar. Cheap (1 unit)
and needs only an API key + the channel's UC... id. Estimated revenue =
total_views/1000 * channel RPM.

Used by the Channels overview tab. Results cached in vault.db channel_stats.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_API = "https://www.googleapis.com/youtube/v3"


def _get(endpoint: str, params: dict) -> dict:
    url = f"{_API}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())


def resolve_channel_id(handle_or_url: str, api_key: str) -> str | None:
    """Resolve a @handle (or handle URL) to a UC... channel id (public)."""
    handle = handle_or_url.strip().rstrip("/").split("/")[-1]
    if not handle.startswith("@"):
        handle = "@" + handle
    try:
        data = _get("channels", {"part": "id", "forHandle": handle, "key": api_key})
        items = data.get("items") or []
        return items[0]["id"] if items else None
    except Exception:
        return None


def fetch_channel_stats(youtube_channel_id: str, api_key: str) -> dict | None:
    """Public snippet+statistics for a UC... id. None on failure."""
    try:
        data = _get("channels", {
            "part": "snippet,statistics", "id": youtube_channel_id, "key": api_key,
        })
    except Exception:
        return None
    items = data.get("items") or []
    if not items:
        return None
    it = items[0]
    sn = it.get("snippet", {})
    st = it.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    avatar = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
    return {
        "title": sn.get("title", ""),
        "avatar_url": avatar,
        "subscribers": int(st.get("subscriberCount", 0) or 0),
        "total_views": int(st.get("viewCount", 0) or 0),
        "video_count": int(st.get("videoCount", 0) or 0),
    }


def compute_health(subscribers: int, total_views: int, video_count: int) -> int:
    """Rough 0-100 operator health: blend of scale + per-video efficiency.
    Heuristic, not analytics — meant as an at-a-glance signal."""
    if video_count <= 0:
        return 0
    vpv = total_views / video_count  # avg views/video
    import math
    scale = min(40, 8 * math.log10(max(subscribers, 1) + 1))      # 0..~40
    output = min(25, video_count * 1.5)                            # 0..25
    efficiency = min(35, 7 * math.log10(max(vpv, 1) + 1))          # 0..~35
    return int(round(scale + output + efficiency))


def refresh_channel_stats(channel_cfg: dict, api_key: str, vault_db_path) -> dict:
    """Fetch + cache stats for one channel into vault.db channel_stats.
    Resolves youtube_channel_id from config (or handle) when possible. Returns a
    plain dict for the API (also returns {authorized:False}-style hints)."""
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import ChannelStats

    cid = channel_cfg.get("channel_id", "")
    yt_id = channel_cfg.get("youtube_channel_id", "").strip()
    if not yt_id:
        handles = channel_cfg.get("competitor_handles") or []
        # NOTE: only resolve an explicit own-handle field, never competitor handles.
        own = channel_cfg.get("youtube_handle") or ""
        if own and api_key:
            yt_id = resolve_channel_id(own, api_key) or ""
    if not yt_id or not api_key:
        return {"channel_id": cid, "linked": False,
                "hint": "Set youtube_channel_id in the channel config to pull stats."}

    raw = fetch_channel_stats(yt_id, api_key)
    if not raw:
        return {"channel_id": cid, "linked": False, "youtube_channel_id": yt_id,
                "hint": "channels.list returned nothing (check id / API key / quota)."}

    rpm = float(channel_cfg.get("rpm_floor", 7.0) or 7.0)
    est_rev = round(raw["total_views"] / 1000.0 * rpm, 2)
    health = compute_health(raw["subscribers"], raw["total_views"], raw["video_count"])
    stats = ChannelStats(
        channel_id=cid, youtube_channel_id=yt_id, title=raw["title"],
        avatar_url=raw["avatar_url"], subscribers=raw["subscribers"],
        total_views=raw["total_views"], video_count=raw["video_count"],
        est_revenue_usd=est_rev, health=health,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    vault_db.upsert_channel_stats(stats, vault_db_path)
    return {
        "channel_id": cid, "linked": True, "youtube_channel_id": yt_id,
        "title": raw["title"], "avatar_url": raw["avatar_url"],
        "subscribers": raw["subscribers"], "total_views": raw["total_views"],
        "video_count": raw["video_count"], "est_revenue_usd": est_rev,
        "health": health, "fetched_at": stats.fetched_at,
    }
