"""Fetch a single Douyin video (no watermark) as an OmniCast asset.

Wiring mirrors the upstream CLI path (`cli/main.py` -> `DownloaderFactory`), so
behaviour stays identical to the tool the vendored code came from: short-link
resolution first, then URL typing, then a per-type downloader.

Two upstream behaviours are deliberately turned off here:

* its SQLite bookkeeping — OmniCast's SSOT is `output/vault.db`, and a second
  download database next to the media would be a competing source of truth;
* its OpenAI transcription step — the reup pipeline runs its own ASR, and
  paying twice for the same audio helps nobody.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from omnicast.ingest.douyin._vendor.auth import CookieManager
from omnicast.ingest.douyin._vendor.config import ConfigLoader
from omnicast.ingest.douyin._vendor.control import QueueManager, RateLimiter, RetryHandler
from omnicast.ingest.douyin._vendor.core import (
    DouyinAPIClient,
    DownloaderFactory,
    URLParser,
)
from omnicast.ingest.douyin._vendor.storage import FileManager
from omnicast.ingest.douyin._vendor.utils.validators import is_short_url, normalize_short_url

MANIFEST_NAME = "download_manifest.jsonl"

# 1080p, not "highest". "highest" probes the uploader's original, which on a
# measured post was 2560x1440 / 20 Mbps / 1.48 GB — three minutes of extra
# download and a much heavier render, for a source we deliver at 1080p anyway.
# Pass video_quality="highest" explicitly when the original is genuinely wanted.
DEFAULT_VIDEO_QUALITY = "1080p"


class DouyinIngestError(RuntimeError):
    """Raised when a Douyin URL cannot be resolved or downloaded."""


@dataclass(slots=True)
class DouyinIngestConfig:
    """Per-fetch settings.

    Leaving `cookies` empty does NOT mean anonymous access works: Douyin answers
    an uncookied detail call with an empty HTTP 200 (its anti-bot reply). When
    `auto_cookies` is on, a browser visit mints the anonymous `ttwid` bundle
    that makes public videos readable — see `cookie_bootstrap`. Private posts
    and collections still need a real `sessionid` passed in explicitly.
    """

    output_dir: Path
    cookies: dict[str, str] = field(default_factory=dict)
    auto_cookies: bool = True
    proxy: str = ""
    # Upstream default. Douyin starts returning empty-200 anti-bot responses
    # when pushed much past this.
    rate_limit: float = 2.0
    retry_times: int = 3
    threads: int = 5
    video_quality: str = DEFAULT_VIDEO_QUALITY


@dataclass(slots=True)
class DouyinAsset:
    """A downloaded Douyin video plus the metadata worth keeping."""

    aweme_id: str
    source_url: str
    video_path: Path
    title: str
    author_name: str
    media_type: str
    tags: list[str] = field(default_factory=list)
    create_time: int | None = None
    publish_date: str = ""
    save_dir: Path | None = None
    # The source's own cover, when the download produced one. Optional: a
    # missing thumbnail must never fail a dub.
    cover_path: Path | None = None

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


def _build_config(settings: DouyinIngestConfig) -> ConfigLoader:
    config = ConfigLoader(None)
    config.update(
        path=str(settings.output_dir),
        proxy=settings.proxy,
        rate_limit=settings.rate_limit,
        retry_times=settings.retry_times,
        thread=settings.threads,
        video_quality=settings.video_quality,
        video=True,
        # The cover is the source's own thumbnail: the cheapest starting point
        # for a Vietnamese thumbnail, and free to fetch while we are here.
        cover=True,
        # Keep the raw aweme JSON — the reup pipeline reads the original
        # Chinese title/description for translation context.
        json=True,
        # See module docstring.
        database=False,
        transcript={"enabled": False},
    )
    return config


def _read_manifest_entry(base_path: Path, aweme_id: str) -> dict[str, Any] | None:
    """Return the manifest row for `aweme_id`.

    The downloader reports only counts, so the manifest it appends is the one
    place the actual output filenames surface. Last match wins: a re-download
    appends a fresh row rather than rewriting the old one.
    """
    manifest_path = base_path / MANIFEST_NAME
    if not manifest_path.is_file():
        return None

    found: dict[str, Any] | None = None
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(record.get("aweme_id")) == str(aweme_id):
            found = record
    return found


def _pick_video_file(base_path: Path, record: dict[str, Any]) -> Path | None:
    for relative in record.get("file_paths") or []:
        candidate = base_path / relative
        if candidate.suffix.lower() == ".mp4" and candidate.is_file():
            return candidate
    return None


def _pick_cover_file(base_path: Path, record: dict[str, Any], video_path: Path) -> Path | None:
    """The `_cover.jpg` the downloader saved beside the video, if any."""
    for relative in record.get("file_paths") or []:
        candidate = base_path / relative
        if candidate.stem.lower().endswith("_cover") and candidate.is_file():
            return candidate
    # Older manifest rows predate covers being enabled; look next to the video.
    beside = video_path.with_name(f"{video_path.stem}_cover.jpg")
    return beside if beside.is_file() else None


async def fetch_video(url: str, settings: DouyinIngestConfig) -> DouyinAsset:
    """Download one Douyin video and return it as a `DouyinAsset`.

    Raises `DouyinIngestError` on unresolvable links, unsupported URL types,
    and downloads that report zero successes.
    """
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    cookies = dict(settings.cookies)
    if not cookies and settings.auto_cookies:
        from omnicast.ingest.douyin.cookie_bootstrap import ensure_cookies

        # Cached beside the workspace, not the media: the handshake is per
        # machine, not per download.
        cookies = ensure_cookies(settings.output_dir.parent / "_douyin_cookies.json")

    # The vendor caches its "already downloaded" index for the life of the
    # process. Delete a file to force a re-download and the cache still claims
    # it is there, so the job skips and then dies looking for a manifest row
    # that no longer exists. A rescan per job is a cheap rglob.
    from omnicast.ingest.douyin._vendor.core.downloader_base import _LOCAL_AWEME_INDEX_CACHE

    _LOCAL_AWEME_INDEX_CACHE.clear()

    config = _build_config(settings)
    cookie_manager = CookieManager(cookie_file=str(settings.output_dir / ".cookies.json"))
    if cookies:
        cookie_manager.set_cookies(cookies)

    file_manager = FileManager(config.get("path"))
    rate_limiter = RateLimiter(max_per_second=float(config.get("rate_limit", 2) or 2))
    retry_handler = RetryHandler(max_retries=config.get("retry_times", 3))
    queue_manager = QueueManager(max_workers=int(config.get("thread", 5) or 5))

    source_url = url

    async with DouyinAPIClient(
        cookie_manager.get_cookies(),
        proxy=config.get("proxy"),
    ) as api_client:
        # Share links from the Douyin app are always short links, and the
        # dispatcher refuses to type them, so this has to happen first.
        if is_short_url(url):
            resolved = await api_client.resolve_short_url(normalize_short_url(url))
            if not resolved:
                raise DouyinIngestError(f"Could not resolve Douyin short link: {url}")
            url = resolved

        parsed = URLParser.parse(url)
        if not parsed:
            raise DouyinIngestError(f"Unrecognised Douyin URL: {url}")

        url_type = parsed.get("type")
        if url_type not in {"video", "gallery"}:
            raise DouyinIngestError(
                f"URL type {url_type!r} is not a single post; reup expects one video per job."
            )

        downloader = DownloaderFactory.create(
            url_type,
            config=config,
            api_client=api_client,
            file_manager=file_manager,
            cookie_manager=cookie_manager,
            database=None,
            rate_limiter=rate_limiter,
            retry_handler=retry_handler,
            queue_manager=queue_manager,
        )
        if downloader is None:
            raise DouyinIngestError(f"No downloader available for URL type {url_type!r}")

        result = await downloader.download(parsed)

    # A skip means the file is already on disk from an earlier run — the
    # downloader's way of saying "nothing to do", not a failure. Treating it as
    # one made every re-run of a video we already had die at the download
    # stage, which is exactly when someone is retrying a job.
    already_have = bool(result and getattr(result, "skipped", 0) >= 1)
    if not result or (result.success < 1 and not already_have):
        raise DouyinIngestError(
            f"Download reported no successes for {source_url} ({result})"
        )

    aweme_id = str(parsed.get("aweme_id") or "")
    base_path = Path(config.get("path"))
    record = _read_manifest_entry(base_path, aweme_id)
    if record is None:
        raise DouyinIngestError(
            f"Download reported {'skip (already have it)' if already_have else 'success'} "
            f"but there is no manifest row for aweme {aweme_id} in {base_path} — "
            f"the media was likely deleted by hand; clear the row too, or re-run."
        )

    video_path = _pick_video_file(base_path, record)
    if video_path is None:
        raise DouyinIngestError(
            f"Manifest for aweme {aweme_id} lists no readable .mp4: {record.get('file_paths')}"
        )

    return DouyinAsset(
        aweme_id=aweme_id,
        source_url=source_url,
        video_path=video_path,
        title=str(record.get("desc") or ""),
        author_name=str(record.get("author_name") or ""),
        media_type=str(record.get("media_type") or "video"),
        tags=list(record.get("tags") or []),
        create_time=record.get("publish_timestamp"),
        publish_date=str(record.get("date") or ""),
        save_dir=video_path.parent,
        cover_path=_pick_cover_file(base_path, record, video_path),
    )


def fetch_video_sync(url: str, settings: DouyinIngestConfig) -> DouyinAsset:
    """Blocking wrapper for callers outside an event loop (CLI, pipeline steps)."""
    return asyncio.run(fetch_video(url, settings))
