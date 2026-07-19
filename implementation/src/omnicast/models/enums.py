from enum import StrEnum


class ChannelType(StrEnum):
    HUB = "hub"
    SPOKE = "spoke"


class ChannelStatus(StrEnum):
    SETUP = "setup"  # Đang cấu hình
    WARMING = "warming"  # Shadow warm-up
    ACTIVE = "active"  # Đang production
    PAUSED = "paused"  # Tạm dừng (manual hoặc auto)
    SHADOWBAN = "shadowban"  # Nghi bị shadowban
    TOKEN_EXPIRED = "token_expired"
    DEAD = "dead"  # Bị terminate hoặc bỏ


class VideoStatus(StrEnum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    SCRIPTING = "scripting"
    DEBATING = "debating"  # Writer ↔ Critic loop
    RENDERING = "rendering"
    QUALITY_CHECK = "quality_check"
    COMPLIANCE_CHECK = "compliance_check"
    READY_TO_UPLOAD = "ready_to_upload"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"
    DLQ = "dlq"  # Dead letter queue
    KILLED = "killed"  # Operator killed


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class Niche(StrEnum):
    FINANCE = "finance"
    HEALTH = "health"
    MYTHOLOGY = "mythology"
    PSYCHOLOGY = "psychology"
    TECH = "tech"
    JP_CULTURE = "jp_culture"
    KR_CULTURE = "kr_culture"


class Market(StrEnum):
    US = "US"
    UK = "UK"
    AU = "AU"
    CA = "CA"
    JP = "JP"
    KR = "KR"


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    WARNING = "warning"
    INFO = "info"


class AssetType(StrEnum):
    MUSIC_YT_LIBRARY = "music_yt_library"
    MUSIC_ROYALTY_FREE = "music_royalty_free"
    MUSIC_AI_GENERATED = "music_ai_generated"
    SFX = "sfx"
    BROLL = "broll"
    INTRO = "intro"
    OUTRO = "outro"
    OVERLAY = "overlay"
    FONT = "font"


class MusicMood(StrEnum):
    CINEMATIC = "cinematic"
    LOFI = "lofi"
    EPIC = "epic"
    CALM = "calm"
    DRAMATIC = "dramatic"
    UPBEAT = "upbeat"
    DARK = "dark"
    INSPIRATIONAL = "inspirational"


class TopicSource(StrEnum):
    YOUTUBE_COMPETITOR = "youtube_competitor"
    GOOGLE_TRENDS = "google_trends"
    REDDIT = "reddit"
    PODCAST = "podcast"
    NEWS_RSS = "news_rss"
    MANUAL = "manual"  # Operator tạo thủ công
    COMMUNITY_POLL = "community_poll"


class LearningPath(StrEnum):
    PATH_1_AUTO = "path_1_auto"  # Silent Skill Optimization
    PATH_2_HUMAN = "path_2_human"  # Structured Learning + Human Gate
    PATH_3_CONTEXT = "path_3_context"  # Context Expansion