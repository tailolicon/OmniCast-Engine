"""YouTube Data API v3 uploader. videos.insert + thumbnails.set + videos.update."""

from __future__ import annotations
import asyncio
import time
from pathlib import Path
import structlog
from omnicast.upload.models import (
    UploadRequest, UploadResult, UploadMetadata, UploadStatus,
)
from omnicast.upload.oauth import OAuth2Manager
from omnicast.config.settings import get_settings
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

YOUTUBE_API_QUOTA_COST = {
    "videos.insert": 1600,
    "thumbnails.set": 50,
    "videos.update": 50,
    "videos.list": 1,
}


class YouTubeUploader:
    """Upload video via YouTube Data API v3."""

    def __init__(self, oauth_manager: OAuth2Manager) -> None:
        self.oauth = oauth_manager

    async def upload(self, request: UploadRequest) -> UploadResult:
        """Full upload flow. Steps:
        1. Get OAuth2 credentials for channel
        2. Build video resource (title, description, tags, privacy, schedule)
        3. Call videos.insert with resumable upload
        4. Set thumbnail if paths provided
        5. Return UploadResult with youtube_video_id + url
        Dry-run: return mock UploadResult without API call.
        """
        settings = get_settings()
        if settings.is_dry_run:
            return self._dry_run_result(request)

        try:
            credentials = await self.oauth.get_credentials(request.channel_id)
            service = self._build_service(credentials)
            youtube_id = await self._insert_video(service, request)
            thumbnail_set = False
            if request.thumbnail_paths:
                thumbnail_set = await self._set_thumbnail(
                    service, youtube_id, request.thumbnail_paths[0]
                )
            url = f"https://youtu.be/{youtube_id}"
            logger.info("Upload complete", video_id=request.video_id,
                        youtube_id=youtube_id, channel_id=request.channel_id)
            return UploadResult(
                youtube_video_id=youtube_id,
                channel_id=request.channel_id,
                status=UploadStatus.PUBLISHED,
                url=url,
                thumbnail_set=thumbnail_set,
            )
        except Exception as exc:
            logger.error("Upload failed", video_id=request.video_id, error=str(exc))
            return UploadResult(
                channel_id=request.channel_id,
                status=UploadStatus.FAILED,
                error=str(exc),
            )

    def _build_service(self, credentials):
        """Build the YouTube Data API v3 service via google-api-python-client."""
        from googleapiclient.discovery import build
        return build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def _build_body(self, request: UploadRequest) -> dict:
        m = request.metadata
        snippet = {
            "title": m.title[:100],
            "description": m.description[:5000],
            "tags": m.tags[:500],
            "categoryId": m.category_id,
        }
        if m.language:
            snippet["defaultLanguage"] = m.language
            snippet["defaultAudioLanguage"] = m.language
        status = {
            "privacyStatus": m.privacy_status,
            "selfDeclaredMadeForKids": bool(m.made_for_kids),
        }
        # The altered/synthetic-content disclosure. ai_disclosure existed on the
        # model since day one but was silently dropped here — the exact
        # "feature on the diagram, no real capability" failure the 2026-07-23
        # strategic review warns about. Realistic AI imagery (found-photo
        # stills, historical reconstruction) REQUIRES this label under the 2026
        # policy; omitting it risks demotion + strikes. Only asserted when
        # True — never explicitly claim a video is synthetic-free.
        if m.ai_disclosure:
            status["containsSyntheticMedia"] = True
        # Scheduled publish requires privacyStatus=private + RFC3339 publishAt.
        if m.publish_at is not None:
            status["privacyStatus"] = "private"
            status["publishAt"] = m.publish_at.isoformat()
        return {"snippet": snippet, "status": status}

    def _insert_video_sync(self, service, request: UploadRequest) -> str:
        """Blocking resumable upload. Retries transient 5xx. Returns video id."""
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        path = Path(request.video_path)
        if not path.exists():
            raise UploadPipelineError(f"Video file not found: {request.video_path}")
        media = MediaFileUpload(
            str(path), chunksize=256 * 1024, resumable=True, mimetype="video/*"
        )
        req = service.videos().insert(
            part="snippet,status", body=self._build_body(request), media_body=media
        )
        response = None
        retries = 0
        while response is None:
            try:
                _status, response = req.next_chunk()
            except HttpError as exc:
                if getattr(exc, "resp", None) is not None and exc.resp.status in (500, 502, 503, 504) and retries < 3:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise
        return response["id"]

    async def _insert_video(self, service, request: UploadRequest) -> str:
        """Run the blocking resumable upload off the event loop."""
        return await asyncio.to_thread(self._insert_video_sync, service, request)

    def _set_thumbnail_sync(self, service, youtube_video_id: str,
                            thumbnail_path: str) -> bool:
        from googleapiclient.http import MediaFileUpload
        if not Path(thumbnail_path).exists():
            return False
        service.thumbnails().set(
            videoId=youtube_video_id,
            media_body=MediaFileUpload(thumbnail_path),
        ).execute()
        return True

    async def _set_thumbnail(self, service, youtube_video_id: str,
                              thumbnail_path: str) -> bool:
        """Call thumbnails.set. Returns True on success, False if missing/failed."""
        try:
            return await asyncio.to_thread(
                self._set_thumbnail_sync, service, youtube_video_id, thumbnail_path
            )
        except Exception as exc:
            logger.warning("Thumbnail set failed", youtube_id=youtube_video_id, error=str(exc))
            return False

    async def update_metadata(self, channel_id: str, youtube_video_id: str,
                                metadata: UploadMetadata) -> bool:
        """Call videos.update to change title/description/tags post-upload."""
        try:
            credentials = await self.oauth.get_credentials(channel_id)
            service = self._build_service(credentials)
            body = {
                "id": youtube_video_id,
                "snippet": {
                    "title": metadata.title[:100],
                    "description": metadata.description[:5000],
                    "tags": metadata.tags[:500],
                    "categoryId": metadata.category_id,
                },
            }
            await asyncio.to_thread(
                lambda: service.videos().update(part="snippet", body=body).execute()
            )
            return True
        except Exception as exc:
            logger.error("Metadata update failed", youtube_id=youtube_video_id, error=str(exc))
            return False

    def _dry_run_result(self, request: UploadRequest) -> UploadResult:
        return UploadResult(
            youtube_video_id=f"dry_run_{request.video_id}",
            channel_id=request.channel_id,
            status=UploadStatus.PUBLISHED,
            url=f"https://youtu.be/dry_run_{request.video_id}",
            thumbnail_set=bool(request.thumbnail_paths),
        )

    @staticmethod
    def estimate_quota_cost(has_thumbnail: bool = True) -> int:
        """Estimate quota cost for one upload."""
        cost = YOUTUBE_API_QUOTA_COST["videos.insert"]
        if has_thumbnail:
            cost += YOUTUBE_API_QUOTA_COST["thumbnails.set"]
        return cost
