"""Vault data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NicheStatus(str, Enum):
    WATCHING = "watching"
    HOT      = "hot"
    ACTIVE   = "active"
    STALE    = "stale"
    ARCHIVED = "archived"


@dataclass
class NicheRecord:
    niche_id: str
    niche_name: str
    market: str
    status: NicheStatus
    original_score: int
    current_health: int
    saved_at: str               # ISO date string
    last_checked: str | None
    evidence_channel_ids: list[str]   # YouTube channel IDs
    seed_queries: list[str]           # for competitor search
    niche_data: dict                  # full niche JSON blob


@dataclass
class HealthLog:
    log_id: int | None
    niche_id: str
    scan_date: str
    new_videos_count: int        # evidence channels: videos published last 14 days
    avg_new_vpd: float           # avg vpd of those new videos
    dedicated_competitors: int   # channels ≥5 videos on topic, subs >50k
    micro_outlier_found: bool    # kênh <10k subs nổ outlier mới
    health_score: int
    status_change: str | None    # e.g. "watching→hot"
    notes: str


class ScriptStatus(str, Enum):
    DRAFT    = "draft"
    TTS_DONE = "tts_done"
    RENDERED = "rendered"
    UPLOADED = "uploaded"


@dataclass
class ScriptRecord:
    script_id: str          # channel_id + "_" + timestamp, e.g. fin_retirement_us_20260525_155034
    run_id: str             # fin_retirement_us/20260525_155034
    channel_id: str
    language: str           # en, ja, ko, vi ...
    topic: str
    score: int
    approved: bool
    status: ScriptStatus
    script_content: str     # full narration text (evolved/best variant)
    cost_usd: float
    created_at: str         # ISO datetime
    updated_at: str         # ISO datetime
    youtube_video_id: str | None = None


class TopicStatus(str, Enum):
    QUEUED  = "queued"    # discovered, available for scripting
    USED    = "used"      # a script/video was produced from it
    SKIPPED = "skipped"   # operator dismissed it


@dataclass
class TopicRecord:
    """A discovered content topic, persisted so automation can pull the next
    unused one regardless of pipeline-event churn."""
    topic_id: str          # stable hash of channel_id + normalized title
    channel_id: str
    title: str
    score: int
    status: TopicStatus
    discovered_at: str     # ISO datetime
    rank: int = 0
    audience_segment: str = ""
    pain_point: str = ""
    content_angle: str = ""
    source_url: str = ""
    used_at: str | None = None
    used_video_id: str | None = None


@dataclass
class CompetitorIntel:
    """Learned playbooks distilled from competitors' breakout (outlier) videos —
    how the winners NAME titles and design THUMBNAILS, per niche. Fed into the
    title + thumbnail generators so our output mirrors what already works."""
    niche: str                     # PK (broad niche/category key)
    title_playbook: str = ""       # title formulas/power-words/structure (text)
    thumbnail_playbook: str = ""   # thumbnail visual recipe (layout/color/text/emotion)
    script_playbook: str = ""      # hook/structure/pacing distilled from competitor transcripts
    sample_titles: list[str] = field(default_factory=list)
    sample_count: int = 0          # how many WINNERS it was distilled from
    # JSON: winner/control counts, is_comparable, the selection thresholds, and
    # notes for every video that dropped out. A playbook learned without a
    # control group is an observation, not a finding — a reader has to be able
    # to tell which one they are holding.
    cohort_meta: str = ""
    updated_at: str = ""


@dataclass
class PublishedVideo:
    """A video actually produced/published in the system — the dedup ledger that
    guards against re-using the same topic (YouTube 'reused content' risk),
    especially across different channels."""
    video_id: str          # internal stem / id (PK)
    channel_id: str
    title: str
    youtube_video_id: str = ""   # set once uploaded; empty = produced not yet up
    published_at: str = ""       # ISO datetime
    status: str = "produced"     # produced | uploaded


@dataclass
class ChannelStats:
    """Cached per-channel YouTube stats (refreshed from Data API)."""
    channel_id: str                 # internal id (channels/<id>.json)
    youtube_channel_id: str = ""    # real YouTube UC... id (mapping for Data API)
    title: str = ""
    avatar_url: str = ""
    subscribers: int = 0
    total_views: int = 0
    video_count: int = 0
    est_revenue_usd: float = 0.0    # total_views/1000 * rpm
    health: int = 0                 # 0-100 operator health score
    fetched_at: str | None = None


@dataclass
class CredentialRecord:
    credential_id: str
    provider: str
    account_id: str
    label: str
    secret_ref: str
    scopes: list[str] = field(default_factory=list)
    status: str = "active"
    priority: int = 100
    cooldown_until: str | None = None
    last_used_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ProviderRecord:
    provider_id: str
    name: str
    capability: str
    status: str = "active"
    priority: int = 100
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ModelRecord:
    model_id: str
    provider_id: str
    capability: str
    runtime: str = "remote"
    cost_per_unit: float = 0.0
    min_vram_mb: int = 0
    fallback: list[str] = field(default_factory=list)
    status: str = "active"
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class UsageRecord:
    usage_id: str
    provider_id: str
    credential_id: str
    capability: str
    scope: str
    scope_id: str
    units: float
    cost_usd: float
    status: str
    created_at: str
    raw: dict = field(default_factory=dict)


@dataclass
class BudgetRecord:
    budget_id: str
    scope: str
    scope_id: str
    limit_usd: float
    spent_usd: float = 0.0
    reset_at: str | None = None
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PostMetricRecord:
    platform_id: str
    account_id: str
    post_id: str
    channel_id: str
    fetched_at: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    watch_time_seconds: float = 0.0
    revenue: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class OfferRecord:
    offer_id: str
    name: str
    network: str
    url: str
    niches: list[str] = field(default_factory=list)
    commission_type: str = "unknown"
    commission_value: float = 0.0
    disclosure: str = "As an affiliate, we may earn from qualifying purchases."
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PlacementRecord:
    placement_id: str
    offer_id: str
    video_id: str
    channel_id: str
    platform_id: str
    destination_url: str
    cta_text: str
    disclosure: str
    created_at: str


@dataclass
class ClickRecord:
    click_id: str
    placement_id: str
    occurred_at: str
    referrer: str = ""
    user_agent: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ConversionRecord:
    conversion_id: str
    placement_id: str
    amount: float
    currency: str
    occurred_at: str
    raw: dict = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """Output of one niche health check pass."""
    niche_id: str
    old_status: NicheStatus
    new_status: NicheStatus
    old_score: int
    new_score: int
    score_delta: int
    new_videos_count: int
    avg_new_vpd: float
    dedicated_competitors: int
    micro_outlier_found: bool
    notes: list[str] = field(default_factory=list)
