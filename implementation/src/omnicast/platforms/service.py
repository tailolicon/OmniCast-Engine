"""Production-facing helpers for platform publish flows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omnicast.config.channel import ChannelProfile, ChannelProfileLoader
from omnicast.config.settings import Settings, get_settings
from omnicast.monetization.linker import MonetizationLinker
from omnicast.platforms.models import PlatformId, PlatformStatus, PublishMetadata, PublishRequest
from omnicast.platforms.registry import PlatformRegistry
from omnicast.platforms.tiktok import TikTokPlatform
from omnicast.platforms.youtube import YouTubePlatform
from omnicast.upload.oauth import OAuth2Manager
from omnicast.upload.youtube_api import YouTubeUploader


def build_platform_registry(
    *,
    settings: Settings | None = None,
    impl_root: str | Path | None = None,
    tiktok_tokens: dict[str, str] | None = None,
) -> PlatformRegistry:
    """Build the platform registry used by approval/API publish paths."""
    settings = settings or get_settings()
    root = Path(impl_root) if impl_root else None
    token_dir = Path(settings.youtube_token_dir)
    if root and not token_dir.is_absolute():
        token_dir = root / token_dir

    youtube_oauth = OAuth2Manager(
        token_dir=str(token_dir),
        encryption_key=settings.youtube_token_key or None,
    )
    registry = PlatformRegistry()
    registry.register(YouTubePlatform(
        uploader=YouTubeUploader(youtube_oauth),
        oauth=youtube_oauth,
    ))
    registry.register(TikTokPlatform(access_tokens=tiktok_tokens or {}))
    return registry


async def publish_approval_row(
    row: dict[str, Any],
    *,
    channels_dir: str | Path,
    output_dir: str | Path,
    impl_root: str | Path | None = None,
    registry: PlatformRegistry | None = None,
) -> dict[str, Any]:
    """Publish one approved queue row via the registered platform adapter."""
    raw = _raw_dict(row.get("raw"))
    channel_id = str(row.get("channel_id") or raw.get("channel_id") or "")
    video_path = str(row.get("video_path") or raw.get("video_path") or "")
    platform_id = str(row.get("platform_id") or raw.get("platform_id") or PlatformId.YOUTUBE.value)
    account_id = str(raw.get("account_id") or raw.get("destination_account_id") or channel_id)
    video_id = str(row.get("video_id") or raw.get("video_id") or Path(video_path).stem)

    if not channel_id or not video_path:
        return {"publish_error": "missing channel_id or video_path on approval row"}
    vpath = Path(video_path)
    if not vpath.exists():
        return {"publish_error": f"video file not found: {video_path}"}

    channel = await _load_channel(channels_dir, channel_id)
    metadata = _metadata_from_approval(row, raw, vpath)
    metadata = _maybe_monetize_metadata(
        metadata,
        raw=raw,
        channel=channel,
        channel_id=channel_id,
        video_id=video_id,
        platform_id=platform_id,
        output_dir=Path(output_dir),
    )
    request = PublishRequest(
        video_id=video_id,
        channel_id=channel_id,
        account_id=account_id,
        video_path=str(vpath.resolve()),
        thumbnail_paths=_thumbnail_candidates(vpath, raw),
        metadata=metadata,
        format_variant=str(raw.get("format_variant") or "youtube_16x9"),
        dry_run=bool(raw.get("dry_run", platform_id != PlatformId.YOUTUBE.value)),
    )

    registry = registry or build_platform_registry(impl_root=impl_root)
    try:
        platform = registry.get(platform_id)
    except KeyError as exc:
        return {"publish_error": str(exc), "platform_id": platform_id, "account_id": account_id}

    try:
        request = await _maybe_export_variant(request, platform)
    except Exception as exc:  # variant export failure shouldn't wipe the queue row
        return {"publish_error": f"variant export failed: {exc}", "platform_id": platform_id,
                "account_id": account_id}

    result = await platform.publish(request)
    outcome = {
        "platform_id": result.platform_id.value if hasattr(result.platform_id, "value") else str(result.platform_id),
        "account_id": result.account_id,
        "platform_post_id": result.post_id,
        "publish_status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "url": result.url,
        "thumbnail_set": result.thumbnail_set,
        "privacy_status": metadata.privacy_status,
        "raw_platform_result": result.raw,
    }
    if result.error or result.status == PlatformStatus.FAILED:
        outcome["publish_error"] = result.error or "platform publish failed"
        return outcome

    if result.platform_id == PlatformId.YOUTUBE:
        outcome["youtube_video_id"] = result.post_id
    if result.status == PlatformStatus.PUBLISHED:
        _record_published(output_dir, channel_id=channel_id, video_id=video_id,
                          title=metadata.title, result=outcome)
    return outcome


async def _maybe_export_variant(request: PublishRequest, platform: Any) -> PublishRequest:
    """Export a platform-specific aspect-ratio variant from the 16:9 master when the
    target platform needs one (e.g. TikTok/Reels 9:16). Returns the request pointing at
    the variant file; a no-op for 16:9 targets and for dry-runs (which need no real file)."""
    spec = getattr(platform, "format_spec", None)
    if spec is None or spec.aspect_ratio == "16:9" or request.dry_run:
        return request
    src = Path(request.video_path)
    out = src.parent / "_variants" / f"{src.stem}_{spec.variant}.mp4"
    if not out.exists():
        from omnicast.media.variants import RenderVariantExporter
        await RenderVariantExporter().export(str(src), str(out), spec)
    return request.model_copy(update={"video_path": str(out.resolve()),
                                      "format_variant": spec.variant})


def _metadata_from_approval(row: dict[str, Any], raw: dict[str, Any], vpath: Path) -> PublishMetadata:
    title = str(row.get("title") or raw.get("title") or vpath.stem)[:100]
    description = str(raw.get("description") or row.get("summary") or "").strip()
    if not description:
        description = f"{title}\n\nMade with AI (AI-generated narration & visuals)."
    privacy_status = str(raw.get("privacy_status") or "private")
    if privacy_status not in {"private", "unlisted", "public"}:
        privacy_status = "private"
    extra = dict(raw.get("extra") or {})
    return PublishMetadata(
        title=title,
        description=description,
        tags=list(raw.get("tags") or []),
        privacy_status=privacy_status,
        ai_disclosure=bool(raw.get("ai_disclosure", True)),
        made_for_kids=bool(raw.get("made_for_kids", False)),
        extra=extra,
    )


def _maybe_monetize_metadata(
    metadata: PublishMetadata,
    *,
    raw: dict[str, Any],
    channel: ChannelProfile | None,
    channel_id: str,
    video_id: str,
    platform_id: str,
    output_dir: Path,
) -> PublishMetadata:
    if raw.get("monetization_enabled") is False:
        return metadata
    niche = ""
    if channel is not None:
        niche = channel.niche.value if hasattr(channel.niche, "value") else str(channel.niche)
    niche = str(raw.get("niche") or niche or "").strip()
    if not niche:
        return metadata
    result = MonetizationLinker(output_dir / "vault.db").monetize_metadata(
        metadata,
        niche=niche,
        video_id=video_id,
        channel_id=channel_id,
        platform_id=platform_id,
        enabled=True,
    )
    return result.metadata


def _thumbnail_candidates(vpath: Path, raw: dict[str, Any]) -> list[str]:
    candidates = [str(p) for p in raw.get("thumbnail_paths") or [] if str(p).strip()]
    if not candidates:
        sibling = vpath.with_name(vpath.stem + "_thumb.png")
        if sibling.exists():
            candidates.append(str(sibling.resolve()))
    return candidates


async def _load_channel(channels_dir: str | Path, channel_id: str) -> ChannelProfile | None:
    try:
        return await ChannelProfileLoader(channels_dir).load(channel_id)
    except Exception:
        return None


def _raw_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _record_published(
    output_dir: str | Path,
    *,
    channel_id: str,
    video_id: str,
    title: str,
    result: dict[str, Any],
) -> None:
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import PublishedVideo

    db_path = Path(output_dir) / "vault.db"
    try:
        vault_db.init_db(db_path)
        vault_db.record_published(PublishedVideo(
            video_id=f"{channel_id}:{video_id}",
            channel_id=channel_id,
            title=title,
            youtube_video_id=str(result.get("youtube_video_id") or ""),
            published_at=datetime.now(timezone.utc).isoformat(),
            status="uploaded",
        ), db_path)
    except Exception:
        pass
