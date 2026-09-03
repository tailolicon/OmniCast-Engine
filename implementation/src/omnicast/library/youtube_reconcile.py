"""Reconcile a YouTube account's real uploads with library episodes.

Backfill for the distribution side: the operator already posted dozens of
episodes before the library existed. This lists the channel's uploads via the
Data API (API key — the stored OAuth tokens only carry the upload scope) and
ticks episode_posts for every upload whose title resolves to a known
(series, episode). Anything ambiguous is REPORTED, never guessed: a wrong
tick is worse than a missing one, because nobody re-checks a green cell.
"""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from omnicast.library import store
from omnicast.library.titles import base_title, normalize_key, parse_episode
from omnicast.storage.products import IMPL_ROOT

_MATCH_THRESHOLD = 0.6


class ReconcileError(RuntimeError):
    pass


def _api_key() -> str:
    try:
        from omnicast.config.settings import get_settings

        settings = get_settings()
        pool = list(getattr(settings, "youtube_key_pool", None) or [])
        key = (settings.youtube_api_key or "").strip()
        if not key and pool:
            key = str(pool[0]).strip()
        return key
    except Exception:
        return ""


def _resolve_external_id(account: dict) -> str:
    """UC… id from the account row, falling back to the channel's config file."""
    ext = str(account.get("external_id") or "").strip()
    if ext:
        return ext
    channel_id = str(account.get("channel_id") or "").strip()
    if channel_id:
        cfg_path = IMPL_ROOT / "channels" / f"{channel_id}.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                return str(cfg.get("youtube_channel_id") or "").strip()
            except Exception:
                pass
    return ""


def list_uploads(external_id: str, api_key: str, *, limit: int = 500) -> list[dict]:
    """All uploads of a channel: channels → uploads playlist → playlistItems."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise ReconcileError(
            "google-api-python-client chưa cài — cần cho đối soát YouTube"
        ) from exc

    yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    resp = yt.channels().list(part="contentDetails", id=external_id).execute()
    items = resp.get("items") or []
    if not items:
        raise ReconcileError(f"Không tìm thấy kênh YouTube id={external_id}")
    playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    out: list[dict] = []
    token = None
    while len(out) < limit:
        resp = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist,
            maxResults=50,
            pageToken=token,
        ).execute()
        for item in resp.get("items") or []:
            snippet = item.get("snippet") or {}
            details = item.get("contentDetails") or {}
            video_id = details.get("videoId") or (
                (snippet.get("resourceId") or {}).get("videoId")
            )
            if not video_id:
                continue
            out.append({
                "video_id": video_id,
                "title": str(snippet.get("title") or ""),
                "published_at": str(
                    details.get("videoPublishedAt") or snippet.get("publishedAt") or ""
                ),
            })
        token = resp.get("nextPageToken")
        if not token:
            break
    return out[:limit]


def _match_series(title_key: str, candidates: list[dict]) -> tuple[dict | None, float]:
    best, best_score = None, 0.0
    for series in candidates:
        for name in (series.get("title"), series.get("title_source")):
            key = normalize_key(base_title(str(name or "")))
            if not key:
                continue
            shorter = min(len(key), len(title_key))
            if shorter >= 4 and (key in title_key or title_key in key):
                return series, 1.0
            score = SequenceMatcher(None, key, title_key).ratio()
            if score > best_score:
                best, best_score = series, score
    if best_score >= _MATCH_THRESHOLD:
        return best, best_score
    return None, best_score


def reconcile_youtube_account(
    account_id: str, *,
    limit: int = 500,
    apply: bool = True,
    path: Path | None = None,
) -> dict:
    account = store.get_account(account_id, path=path)
    if account is None:
        raise KeyError(f"account {account_id} not found")
    if account.get("platform") != "youtube":
        raise ReconcileError(f"Tài khoản {account_id} không phải YouTube")

    external_id = _resolve_external_id(account)
    if not external_id:
        raise ReconcileError(
            "Tài khoản chưa có YouTube channel id (UC…) — điền external_id "
            "hoặc gắn vào channel có youtube_channel_id trong channels/*.json."
        )
    api_key = _api_key()
    if not api_key:
        raise ReconcileError("Chưa có YouTube API key (settings.youtube_api_key).")

    # Prefer series of the same logical channel; fall back to every series.
    candidates = []
    if account.get("channel_id"):
        candidates = store.list_series(channel_id=account["channel_id"], path=path)
    if not candidates:
        candidates = store.list_series(path=path)

    episodes_cache: dict[str, dict[int, dict]] = {}

    def _episode(series_id: str, ep_no: int) -> dict | None:
        if series_id not in episodes_cache:
            episodes_cache[series_id] = {
                e["ep_no"]: e for e in store.list_episodes(series_id, path=path)
            }
        return episodes_cache[series_id].get(ep_no)

    uploads = list_uploads(external_id, api_key, limit=limit)
    matched: list[dict] = []
    unmatched: list[dict] = []
    written = 0

    for upload in uploads:
        _, ep_no = parse_episode(upload["title"])
        title_key = normalize_key(base_title(upload["title"]))
        series, score = (_match_series(title_key, candidates) if title_key else (None, 0.0))
        episode = None
        if series is not None and ep_no is not None:
            episode = _episode(series["series_id"], ep_no)
        if episode is not None:
            if apply:
                store.set_post(
                    episode["episode_id"], account_id,
                    status="posted",
                    post_url=f"https://www.youtube.com/watch?v={upload['video_id']}",
                    external_post_id=upload["video_id"],
                    posted_at=upload["published_at"],
                    source="youtube_api",
                    path=path,
                )
                written += 1
            matched.append({
                "video_id": upload["video_id"], "title": upload["title"],
                "series_id": series["series_id"], "ep_no": ep_no,
                "score": round(score, 2),
            })
        else:
            unmatched.append({
                "video_id": upload["video_id"], "title": upload["title"],
                "guessed_ep": ep_no,
                "series_id": series["series_id"] if series else None,
                "score": round(score, 2),
            })

    return {
        "account_id": account_id,
        "external_id": external_id,
        "uploads_scanned": len(uploads),
        "matched": len(matched),
        "posts_written": written,
        "matched_detail": matched[:200],
        "unmatched": unmatched[:200],
    }
