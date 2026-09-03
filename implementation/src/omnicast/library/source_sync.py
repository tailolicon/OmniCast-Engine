"""Sync a series against its source — Douyin 合集 or Bilibili (合集/分P).

"Thiếu tập so với nguồn" needs the source's own episode list. A series links
to a source URL; syncing pulls the full episode list and plans an episode row
for every entry the library does not have yet — the missing episodes become
`planned` rows, each carrying the exact source URL to paste into a new reup
job (and the job later snaps back onto its row by source-id equality).

Two listers, one apply loop:
  * Douyin: vendored douyin-downloader client (a_bogus signing, anonymous
    ttwid via cookie_bootstrap) paginating `/mix/aweme/`.
  * Bilibili: `ingest.bilibili.fetch_series_entries` — a video of a 合集
    (season episodes), a multi-part video (分P), or a space collection URL.
Both produce entries `{sid, title, url, position}`; `_apply_entries` upserts
them with the same conflict rules regardless of platform.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from omnicast.ingest.detect import detect_source_platform
from omnicast.library import store
from omnicast.library.titles import parse_episode
from omnicast.storage.products import OUTPUT_DIR

# Same jar the reup jobs use (client.py: settings.output_dir.parent / "_douyin_cookies.json")
COOKIE_CACHE = OUTPUT_DIR / "reup" / "_douyin_cookies.json"

_PAGE_SIZE = 20
_MAX_ITEMS = 2000


class SourceSyncError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── shared apply loop ───────────────────────────────────────────────────────

def _apply_entries(
    series_id: str, entries: list[dict], *, path: Path | None = None
) -> dict:
    """Upsert source entries into episodes. Fill-don't-blank, conflicts reported.

    Entry: {sid, title, url, position}. Episode number = parsed from the title
    (第N集 / Tập N / …) else the list position — sources order their episodes.
    """
    existing = store.list_episodes(series_id, path=path)
    by_sid = {e["source_aweme_id"]: e for e in existing if e["source_aweme_id"]}
    by_ep = {e["ep_no"]: e for e in existing}

    created = updated = 0
    conflicts: list[dict] = []
    max_ep_seen = 0
    for entry in entries:
        sid = str(entry.get("sid") or "")
        title = str(entry.get("title") or "")
        url = str(entry.get("url") or "")
        position = int(entry.get("position") or 0) or 1
        _, parsed_ep = parse_episode(title)
        ep_no = parsed_ep or position
        max_ep_seen = max(max_ep_seen, ep_no)

        if sid and sid in by_sid:
            holder = by_sid[sid]
            store.upsert_episode(
                series_id, holder["ep_no"], title=title, source_url=url, path=path,
            )
            updated += 1
            continue
        holder = by_ep.get(ep_no)
        if holder is None:
            row = store.upsert_episode(
                series_id, ep_no,
                title=title, source_aweme_id=sid, source_url=url, path=path,
            )
            by_ep[ep_no] = row
            if sid:
                by_sid[sid] = row
            created += 1
        elif not holder.get("source_aweme_id"):
            row = store.upsert_episode(
                series_id, ep_no,
                title=title, source_aweme_id=sid, source_url=url, path=path,
            )
            if sid:
                by_sid[sid] = row
            updated += 1
        else:
            conflicts.append({
                "ep_no": ep_no, "sid": sid, "title": title,
                "holder_sid": holder["source_aweme_id"],
            })
    return {
        "created": created, "updated": updated,
        "conflicts": conflicts, "max_ep_seen": max_ep_seen,
    }


# ── douyin lister ───────────────────────────────────────────────────────────

def _strip_query_param(url: str, param: str) -> str:
    """Drop one query param — a resolved 合集 share link often carries
    `modal_id`, and URLParser types any URL with modal_id as a single video."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != param]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _unwrap_aweme(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    if item.get("aweme_id"):
        return item
    for key in ("aweme", "aweme_info", "aweme_detail"):
        inner = item.get(key)
        if isinstance(inner, dict) and inner.get("aweme_id"):
            return inner
    return None


async def _douyin_listing(
    source_url: str, mix_id: str,
    cookies: dict[str, str] | None, proxy: str,
) -> dict:
    """{'mix_id','title','author','entries':[…]} from a Douyin 合集."""
    from omnicast.ingest.douyin._vendor.core import DouyinAPIClient, URLParser
    from omnicast.ingest.douyin._vendor.utils.validators import (
        is_short_url,
        normalize_short_url,
    )
    from omnicast.ingest.douyin.cookie_bootstrap import ensure_cookies

    jar = dict(cookies or {})
    if not jar:
        jar = ensure_cookies(COOKIE_CACHE)

    async with DouyinAPIClient(jar, proxy=proxy or None) as client:
        if not mix_id:
            url = source_url
            if is_short_url(url):
                resolved = await client.resolve_short_url(normalize_short_url(url))
                if resolved:
                    url = resolved
            url = _strip_query_param(url, "modal_id")
            parsed = URLParser.parse(url)
            if parsed.get("type") != "collection" or not parsed.get("mix_id"):
                raise SourceSyncError(
                    "Link Douyin không phải hợp tập (合集). Dán link dạng "
                    "douyin.com/collection/<id> hoặc link share của hợp tập "
                    f"(đã nhận: type={parsed.get('type')!r})."
                )
            mix_id = str(parsed["mix_id"])
        detail = await client.get_mix_detail(mix_id) or {}

        items: list[dict] = []
        cursor = 0
        while len(items) < _MAX_ITEMS:
            page = await client.get_mix_aweme(mix_id, cursor=cursor, count=_PAGE_SIZE)
            raw_items = page.get("items") or page.get("aweme_list") or []
            for item in raw_items:
                aweme = _unwrap_aweme(item)
                if aweme:
                    items.append(aweme)
            has_more = bool(page.get("has_more"))
            next_cursor = page.get("max_cursor")
            if not raw_items or not has_more:
                break
            if next_cursor in (None, cursor):  # cursor stall — same guard as MixDownloader
                break
            cursor = next_cursor

    entries = [{
        "sid": str(a.get("aweme_id")),
        "title": str(a.get("desc") or ""),
        "url": f"https://www.douyin.com/video/{a.get('aweme_id')}",
        "position": i,
    } for i, a in enumerate(items, start=1)]
    return {
        "mix_id": mix_id,
        "title": str(detail.get("mix_name") or detail.get("title") or ""),
        "author": str(((detail.get("author") or {}).get("nickname")) or ""),
        "entries": entries,
    }


# ── entry point ─────────────────────────────────────────────────────────────

async def sync_series_source(
    series_id: str, *,
    cookies: dict[str, str] | None = None,
    proxy: str = "",
    path: Path | None = None,
) -> dict:
    series = store.get_series(series_id, path=path)
    if series is None:
        raise KeyError(f"series {series_id} not found")
    source_url = str(series.get("source_url") or "").strip()
    mix_id = str(series.get("source_mix_id") or "").strip()
    if not source_url and not mix_id:
        raise SourceSyncError(
            "Series chưa có link nguồn — thêm link hợp tập Douyin hoặc "
            "video/hợp tập Bilibili trước."
        )

    platform = (
        detect_source_platform(source_url)
        if source_url
        else str(series.get("source_platform") or "douyin")
    )

    if platform == "bilibili":
        from omnicast.ingest.bilibili import BilibiliIngestError, fetch_series_entries

        try:
            listing = await asyncio.to_thread(
                fetch_series_entries, source_url, cookies=cookies, proxy=proxy
            )
        except BilibiliIngestError as exc:
            raise SourceSyncError(str(exc)) from exc
        listing["mix_id"] = ""
    else:
        listing = await _douyin_listing(source_url, mix_id, cookies, proxy)

    entries = listing.get("entries") or []
    if not entries:
        raise SourceSyncError(
            "Nguồn trả về 0 tập — link sai, nội dung private, hoặc bị chặn."
        )

    applied = _apply_entries(series_id, entries, path=path)

    source_count = max(len(entries), applied["max_ep_seen"])
    updates: dict = {
        "source_platform": platform,
        "source_episode_count": source_count,
        "source_synced_at": _now(),
    }
    if listing.get("mix_id"):
        updates["source_mix_id"] = str(listing["mix_id"])
        if not source_url:
            updates["source_url"] = f"https://www.douyin.com/collection/{listing['mix_id']}"
    if listing.get("title") and not str(series.get("title_source") or "").strip():
        updates["title_source"] = str(listing["title"])
    if listing.get("author") and not str(series.get("source_author") or "").strip():
        updates["source_author"] = str(listing["author"])
    store.update_series(series_id, path=path, **updates)

    return {
        "series_id": series_id,
        "platform": platform,
        "mix_id": str(listing.get("mix_id") or ""),
        "mix_name": str(listing.get("title") or ""),
        "source_count": source_count,
        "episodes_created": applied["created"],
        "episodes_updated": applied["updated"],
        "conflicts": applied["conflicts"],
    }


def sync_series_source_sync(series_id: str, **kwargs) -> dict:
    """Blocking wrapper for CLI / thread-pool callers."""
    return asyncio.run(sync_series_source(series_id, **kwargs))
