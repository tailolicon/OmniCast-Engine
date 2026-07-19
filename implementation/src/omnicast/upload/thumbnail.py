"""Thumbnail management. Upload variants, A/B swap based on CTR, track performance."""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
import structlog
from omnicast.upload.models import UploadResult
from omnicast.upload.youtube_api import YouTubeUploader
from omnicast.shared.errors import UploadPipelineError
from omnicast.models.schemas import OmnicastSchema
from pydantic import Field

logger = structlog.get_logger()

CTR_THRESHOLD = 4.0       # % — swap if below this after evaluation period
EVALUATION_HOURS = 24     # wait before evaluating CTR
MAX_SWAPS = 2             # max A/B swaps per video


class ThumbnailVariant(OmnicastSchema):
    """One thumbnail variant with performance tracking."""
    variant_id: str        # "A", "B", "C"
    path: str
    is_active: bool = False
    set_at: datetime | None = None
    ctr: float | None = None
    impressions: int = 0


class ThumbnailState(OmnicastSchema):
    """Track A/B testing state for one video."""
    youtube_video_id: str
    channel_id: str
    variants: list[ThumbnailVariant] = Field(default_factory=list)
    swap_count: int = 0
    last_swap_at: datetime | None = None

    @property
    def active_variant(self) -> ThumbnailVariant | None:
        return next((v for v in self.variants if v.is_active), None)

    @property
    def can_swap(self) -> bool:
        return self.swap_count < MAX_SWAPS

    @property
    def needs_evaluation(self) -> bool:
        if not self.last_swap_at:
            return False
        elapsed = datetime.now(timezone.utc) - self.last_swap_at
        return elapsed >= timedelta(hours=EVALUATION_HOURS)


class ThumbnailManager:
    """Manage thumbnail A/B testing via YouTube API."""

    def __init__(self, uploader: YouTubeUploader) -> None:
        self.uploader = uploader
        self._states: dict[str, ThumbnailState] = {}  # youtube_video_id → state

    def register_variants(self, youtube_video_id: str, channel_id: str,
                           paths: list[str]) -> ThumbnailState:
        """Register thumbnail variants for a video. First variant = active."""
        variants = []
        for i, path in enumerate(paths):
            vid = chr(65 + i)  # A, B, C
            variants.append(ThumbnailVariant(
                variant_id=vid, path=path, is_active=(i == 0),
                set_at=datetime.now(timezone.utc) if i == 0 else None,
            ))
        state = ThumbnailState(
            youtube_video_id=youtube_video_id,
            channel_id=channel_id,
            variants=variants,
            last_swap_at=datetime.now(timezone.utc),
        )
        self._states[youtube_video_id] = state
        return state

    async def evaluate_and_swap(self, youtube_video_id: str,
                                  current_ctr: float,
                                  current_impressions: int) -> ThumbnailState | None:
        """Check if swap needed. Steps:
        1. Get current state
        2. Update active variant CTR
        3. If CTR < threshold AND can_swap AND evaluation period passed:
           - Swap to next variant via thumbnails.set API
           - Update state
        4. Return updated state or None if no swap
        """
        state = self._states.get(youtube_video_id)
        if not state:
            return None

        if not state.needs_evaluation:
            return None

        # Update current variant CTR
        active = state.active_variant
        if not active:
            return None

        # Check if swap needed
        if current_ctr >= CTR_THRESHOLD:
            logger.info("CTR above threshold, no swap", youtube_id=youtube_video_id,
                        ctr=current_ctr)
            return None

        if not state.can_swap:
            logger.info("Max swaps reached", youtube_id=youtube_video_id)
            return None

        # Find next variant
        next_variant = self._next_variant(state)
        if not next_variant:
            return None

        # Swap via API
        success = await self.uploader._set_thumbnail(
            self.uploader._build_service(
                await self.uploader.oauth.get_credentials(state.channel_id)
            ),
            youtube_video_id,
            next_variant.path,
        )

        if success:
            now = datetime.now(timezone.utc)
            updated_variants = []
            for v in state.variants:
                if v.variant_id == active.variant_id:
                    updated_variants.append(v.model_copy(update={
                        "is_active": False, "ctr": current_ctr,
                        "impressions": current_impressions,
                    }))
                elif v.variant_id == next_variant.variant_id:
                    updated_variants.append(v.model_copy(update={
                        "is_active": True, "set_at": now,
                    }))
                else:
                    updated_variants.append(v)

            state = state.model_copy(update={
                "variants": updated_variants,
                "swap_count": state.swap_count + 1,
                "last_swap_at": now,
            })
            self._states[youtube_video_id] = state
            logger.info("Thumbnail swapped", youtube_id=youtube_video_id,
                        from_variant=active.variant_id, to_variant=next_variant.variant_id)

        return state

    def _next_variant(self, state: ThumbnailState) -> ThumbnailVariant | None:
        """Get next inactive variant to try."""
        active = state.active_variant
        for v in state.variants:
            if v.variant_id != active.variant_id and v.ctr is None:
                return v
        return None

    def get_state(self, youtube_video_id: str) -> ThumbnailState | None:
        return self._states.get(youtube_video_id)
