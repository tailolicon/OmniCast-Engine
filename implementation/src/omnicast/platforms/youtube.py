"""YouTube platform adapter around the existing upload pipeline."""

from __future__ import annotations

import asyncio

import structlog

from omnicast.platforms.analytics_store import PlatformAnalyticsStore
from omnicast.platforms.models import (
    AuthState,
    FormatSpec,
    PlatformId,
    PlatformStatus,
    PolicyIssue,
    PolicySeverity,
    PostStats,
    PublishMetadata,
    PublishRequest,
    PublishResult,
    QuotaInfo,
)
from omnicast.upload.compliance import ComplianceChecker
from omnicast.upload.models import UploadMetadata, UploadRequest, UploadStatus
from omnicast.upload.oauth import OAuth2Manager
from omnicast.upload.youtube_api import YouTubeUploader

logger = structlog.get_logger()

# commentThreads.list / comments.list cost 1 quota unit per call, and each call
# returns up to 100 items. The cap below therefore bounds both quota and the
# time a feedback sweep can take on a video with 40k comments.
MAX_COMMENTS_DEFAULT = 200
COMMENTS_PAGE_SIZE = 100


class CommentFetch(list):
    """The comments, plus why there are that many of them.

    Subclasses `list` so every existing caller — `len()`, iteration, `if not
    comments` — keeps working unchanged, while callers that care can read
    `.status` ("ok", "comments_disabled", "quota_exceeded", …) and
    `.credential`. Returning the outcome instead of parking it on the adapter
    is what makes concurrent fetches safe."""

    def __init__(self, comments, *, status: str = "ok", credential: str = "") -> None:
        super().__init__(comments)
        self.status = status
        self.credential = credential

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _to_upload_metadata(metadata: PublishMetadata) -> UploadMetadata:
    return UploadMetadata(
        title=metadata.title,
        description=metadata.description,
        tags=metadata.tags,
        language=metadata.language,
        ai_disclosure=metadata.ai_disclosure,
        privacy_status=metadata.privacy_status,
        publish_at=metadata.publish_at,
        made_for_kids=metadata.made_for_kids,
    )


def _to_upload_request(request: PublishRequest) -> UploadRequest:
    return UploadRequest(
        video_id=request.video_id,
        channel_id=request.account_id,
        video_path=request.video_path,
        thumbnail_paths=request.thumbnail_paths,
        metadata=_to_upload_metadata(request.metadata),
    )


class YouTubePlatform:
    """Official YouTube Data API v3 adapter."""

    id = PlatformId.YOUTUBE.value
    format_spec = FormatSpec(
        variant="youtube_16x9",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        caption_max_length=5000,
        supports_scheduling=True,
        supports_thumbnail=True,
    )

    def __init__(
        self,
        uploader: YouTubeUploader,
        oauth: OAuth2Manager | None = None,
        compliance: ComplianceChecker | None = None,
        analytics_store: PlatformAnalyticsStore | None = None,
    ) -> None:
        self.uploader = uploader
        self.oauth = oauth
        self.compliance = compliance or ComplianceChecker()
        self.analytics_store = analytics_store

    async def authenticate(self, account_id: str) -> AuthState:
        if not self.oauth:
            return AuthState(
                platform_id=PlatformId.YOUTUBE,
                account_id=account_id,
                authenticated=False,
                error="OAuth2Manager not configured",
            )
        health = await self.oauth.check_health(account_id)
        return AuthState(
            platform_id=PlatformId.YOUTUBE,
            account_id=account_id,
            authenticated=health.error is None,
            scopes=health.scopes,
            expires_at=health.expires_at,
            error=health.error,
        )

    async def quota(self, account_id: str) -> QuotaInfo:
        return QuotaInfo(
            platform_id=PlatformId.YOUTUBE,
            account_id=account_id,
            remaining=None,
            unit="quota_units",
            details={"upload_cost_with_thumbnail": self.uploader.estimate_quota_cost(True)},
        )

    async def validate(self, request: PublishRequest) -> list[PolicyIssue]:
        result = self.compliance.check(_to_upload_request(request))
        return [
            PolicyIssue(
                code="youtube_compliance",
                message=violation,
                severity=PolicySeverity.BLOCKING,
            )
            for violation in result.violations
        ]

    async def publish(self, request: PublishRequest) -> PublishResult:
        issues = await self.validate(request)
        blocking = [issue for issue in issues if issue.severity == PolicySeverity.BLOCKING]
        if blocking:
            return PublishResult(
                platform_id=PlatformId.YOUTUBE,
                account_id=request.account_id,
                status=PlatformStatus.FAILED,
                error="; ".join(issue.message for issue in blocking),
            )

        result = await self.uploader.upload(_to_upload_request(request))
        status = (
            PlatformStatus.FAILED
            if result.status == UploadStatus.FAILED
            else PlatformStatus.PUBLISHED
        )
        return PublishResult(
            platform_id=PlatformId.YOUTUBE,
            account_id=request.account_id,
            post_id=result.youtube_video_id,
            status=status,
            url=result.url,
            published_at=result.published_at,
            thumbnail_set=result.thumbnail_set,
            error=result.error,
        )

    async def fetch_analytics(self, post_id: str, account_id: str) -> PostStats:
        if self.analytics_store:
            stats = self.analytics_store.latest(self.id, post_id)
            if stats:
                return stats
        return PostStats(
            platform_id=PlatformId.YOUTUBE,
            account_id=account_id,
            post_id=post_id,
            raw={"source": "youtube_platform_adapter", "ingested": False},
        )

    # ── Comments ─────────────────────────────────────────────────────────────
    #
    # This returned `[]` unconditionally, which is worse than not existing: an
    # audience-feedback loop reading it could not tell "this video has no
    # comments" from "nobody implemented this", so a silent empty list looked
    # like a real signal. Now it either returns real comments or says why it
    # could not, on the RESULT object (`CommentFetch.status`), so callers read
    # the reason instead of inferring it from emptiness.

    def _build_api_key_service(self):
        """Read-only client from the API key. Enough for public comment threads."""
        from omnicast.config.settings import get_settings

        api_key = getattr(get_settings(), "youtube_api_key", "")
        if not api_key:
            raise RuntimeError("no usable credentials: no OAuth and no youtube_api_key")
        from googleapiclient.discovery import build

        return build("youtube", "v3", developerKey=api_key, cache_discovery=False)

    def _resolve_oauth_credentials(self, account_id: str):
        """Blocking credential resolution, called from a worker thread.

        `OAuth2Manager.get_credentials` is declared `async def` but its body is
        entirely synchronous — a disk read plus `creds.refresh()`, a blocking
        HTTPS POST with google-auth's 120s default. Awaiting it directly froze
        the FastAPI worker for as long as Google took to answer.

        This calls the SYNC entry point rather than driving the coroutine on a
        private loop with `asyncio.run`. The private-loop version worked today
        but would deadlock silently the moment anything inside OAuth2Manager
        became genuinely async (an `asyncio.Lock` around token refresh is the
        obvious next change) — and it would deadlock as a hang, not an error,
        so tests with no contention would keep passing."""
        resolve = getattr(self.oauth, "get_credentials_sync", None)
        if callable(resolve):
            return resolve(account_id)
        # Older manager without the sync entry point.
        import asyncio as _asyncio

        return _asyncio.run(self.oauth.get_credentials(account_id))

    def _fetch_comments_blocking(self, post_id: str, account_id: str,
                                 max_comments: int, order: str) -> tuple[list[dict], str]:
        """Credentials + client build + paging, all in ONE worker thread.

        `googleapiclient.discovery.build` alone measured ~200ms of loop stall
        cold, on every call, and it was running on the loop in both branches."""
        if self.oauth:
            try:
                credentials = self._resolve_oauth_credentials(account_id)
                service = self.uploader._build_service(credentials)
                credential = "oauth"
            except Exception as exc:
                # A revoked or expired token must not be reported as "this video
                # has no comments" — public threads are readable with the key.
                logger.warning("OAuth unusable for comment read, falling back to API key",
                               account_id=account_id, error=str(exc)[:200])
                service = self._build_api_key_service()
                credential = "api_key_after_oauth_failure"
        else:
            service = self._build_api_key_service()
            credential = "api_key"
        return self._list_comment_threads(service, post_id, max_comments, order), credential

    @staticmethod
    def _normalize_thread(item: dict) -> list[dict]:
        """Flatten one commentThread into top-level comment + replies."""
        out: list[dict] = []
        thread_id = item.get("id", "")
        snippet = item.get("snippet", {}) or {}
        top = (snippet.get("topLevelComment") or {}).get("snippet", {}) or {}
        if top:
            out.append({
                "comment_id": (snippet.get("topLevelComment") or {}).get("id", thread_id),
                "thread_id": thread_id,
                "video_id": snippet.get("videoId", ""),
                "author": top.get("authorDisplayName", ""),
                "author_channel_id": (top.get("authorChannelId") or {}).get("value", ""),
                "text": top.get("textOriginal") or top.get("textDisplay", "") or "",
                "like_count": int(top.get("likeCount", 0) or 0),
                "published_at": top.get("publishedAt", ""),
                "updated_at": top.get("updatedAt", ""),
                "reply_count": int(snippet.get("totalReplyCount", 0) or 0),
                "is_reply": False,
                "parent_id": "",
            })
        for reply in (item.get("replies", {}) or {}).get("comments", []) or []:
            r = reply.get("snippet", {}) or {}
            out.append({
                "comment_id": reply.get("id", ""),
                "thread_id": thread_id,
                "video_id": r.get("videoId", ""),
                "author": r.get("authorDisplayName", ""),
                "author_channel_id": (r.get("authorChannelId") or {}).get("value", ""),
                "text": r.get("textOriginal") or r.get("textDisplay", "") or "",
                "like_count": int(r.get("likeCount", 0) or 0),
                "published_at": r.get("publishedAt", ""),
                "updated_at": r.get("updatedAt", ""),
                "reply_count": 0,
                "is_reply": True,
                "parent_id": r.get("parentId", ""),
            })
        return out

    def _list_comment_threads(self, service, post_id: str, max_comments: int,
                              order: str) -> list[dict]:
        """Blocking paging loop — always called from a worker thread."""
        collected: list[dict] = []
        page_token = ""
        while len(collected) < max_comments:
            request = service.commentThreads().list(
                part="snippet,replies",
                videoId=post_id,
                maxResults=min(COMMENTS_PAGE_SIZE, max_comments - len(collected)),
                order=order,
                textFormat="plainText",
                pageToken=page_token or None,
            )
            response = request.execute() or {}
            for item in response.get("items", []):
                collected.extend(self._normalize_thread(item))
            page_token = response.get("nextPageToken", "")
            if not page_token:
                break
        return collected[:max_comments]

    async def fetch_comments(
        self,
        post_id: str,
        account_id: str,
        *,
        max_comments: int = MAX_COMMENTS_DEFAULT,
        order: str = "relevance",
    ) -> CommentFetch:
        """Real commentThreads.list read, paged and normalized.

        Returns a `CommentFetch` — a list of comments that also carries `status`
        and `credential`. The outcome lives on the RESULT, never on the adapter:
        an instance field was being overwritten by whichever concurrent fetch
        finished last, so a successful call could read another call's failure."""
        if not post_id:
            return _comment_failure("no post_id", post_id)

        from omnicast.config.settings import get_settings

        if getattr(get_settings(), "is_dry_run", False):
            return _comment_failure("dry_run", post_id, quiet=True)

        try:
            comments, credential = await asyncio.to_thread(
                self._fetch_comments_blocking, post_id, account_id,
                max(1, max_comments), order)
        except Exception as exc:
            return _comment_failure(_comment_error_reason(exc), post_id, exc=exc)

        logger.info("comments fetched", post_id=post_id, count=len(comments),
                    credential=credential)
        return CommentFetch(comments, status="ok", credential=credential)


def _comment_failure(reason: str, post_id: str, *, exc: Exception | None = None,
                     quiet: bool = False) -> CommentFetch:
    """Module-level on purpose: a failure record must not touch adapter state."""
    if not quiet:
        # Comments being switched off is a normal channel setting, not an
        # incident; a quota wall is.
        log = logger.info if reason == "comments_disabled" else logger.warning
        log("comment fetch returned nothing", post_id=post_id, reason=reason,
            error=str(exc)[:200] if exc else "")
    return CommentFetch([], status=reason)


def _comment_error_reason(exc: Exception) -> str:
    """Map a Google API error onto a short, checkable reason string."""
    detail = str(exc)
    status = getattr(getattr(exc, "resp", None), "status", None)
    if "commentsDisabled" in detail or "disabled comments" in detail:
        return "comments_disabled"
    if "quotaExceeded" in detail or "rateLimitExceeded" in detail or status == 429:
        return "quota_exceeded"
    if "videoNotFound" in detail or status == 404:
        return "video_not_found"
    if status == 403:
        return "forbidden"
    if "youtube_api_key" in detail or "OAuth" in detail:
        return "no_credentials"
    return type(exc).__name__
