"""Global application settings loaded from environment variables.

Usage:
    settings = get_settings()
    print(settings.database_url)
    print(settings.is_production)

Singleton pattern — load once, reuse everywhere.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file: src/omnicast/config/ -> up 3 levels -> implementation/
_ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"


class Settings(BaseSettings):
    """All settings from .env file or environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # === Database ===
    database_url: str = Field(description="PostgreSQL connection string")

    # === RabbitMQ ===
    rabbitmq_url: str = Field(description="AMQP connection string")

    # === Redis ===
    redis_url: str = Field(default="redis://localhost:6379/0")

    # === Telegram ===
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # === Claude API ===
    claude_api_key: str = Field(default="")
    # Sonnet 5: same list price as sonnet-4-6, materially better long-form
    # writing — the writer's AI-slop tells (uniform staccato rhythm, verification
    # cosplay) were the main quality complaint on the horror channel.
    claude_model: str = Field(default="claude-sonnet-5")
    claude_rpm_limit: int = Field(default=50, description="Requests per minute")
    # "cli" = route Claude calls through `claude -p` (subscription billing, $0
    # marginal). Requires one-time `claude /login` on this machine.
    omnicast_claude_backend: str = Field(default="")
    # TEMPORARY OPERATIONAL SWITCH (2026-07-17): "1" makes the unit_first
    # narrative flow use Claude CLI for EVERY role and issue zero DeepSeek calls —
    # not a health probe, not a first primary attempt — while the DeepSeek quota is
    # exhausted. Unset/"0" restores the normal DeepSeek-first routing with no code
    # change. These live on Settings and not only in os.environ because .env is
    # read by pydantic-settings into THIS model; it only reaches os.environ on the
    # API-server path (server.py load_dotenv), so a CLI/step run would silently
    # ignore a .env-only switch.
    omnicast_narrative_claude_only: str = Field(default="")
    omnicast_narrative_max_quality: str = Field(default="")

    # === Google AI (Imagen 4 / Gemini) ===
    google_api_key: str = Field(default="", description="Google AI Studio API key for Imagen 4")
    
    # === Media Pipeline ===
    media_image_provider: str = Field(default="gemini", description="Default image generation provider")
    media_video_provider: str = Field(default="gemini", description="Default video generation provider")
    media_image_model: str = Field(default="gemini-2.5-flash-image-preview", description="Default image model")
    media_video_model: str = Field(default="veo-3.0-generate-001", description="Default video model")

    # === Google Flow (labs.google/fx) — browser-automation provider ===
    # No public API; drives the Flow web UI via Playwright + a logged-in profile
    # so generations consume the user's paid Flow plan credits.
    flow_project_url: str = Field(default="", description="Flow project URL used by FlowProvider")
    flow_profile_dir: str = Field(default=".flow_profile", description="Persistent browser profile dir (logged-in Flow session)")
    flow_image_model: str = Field(
        default="nano-banana-pro",
        description="Flow image model (all free on Pro plan): 'nano-banana-pro' "
                    "(default — best detail/text/charts; needs single-frame prompt, "
                    "avoid 'series'/'montage' wording), 'imagen4' (photoreal), "
                    "'nano-banana' (fastest).",
    )

    # === DeepSeek API ===
    deepseek_api_key: str = Field(default="")
    deepseek_pro_model: str = Field(default="deepseek-v4-pro")
    deepseek_flash_model: str = Field(default="deepseek-v4-flash")
    # deepseek-chat/reasoner aliases are deprecated after 2026-07-24.
    # DeepSeekClient explicitly disables V4 thinking for routine JSON work.
    deepseek_chat_model: str = Field(default="deepseek-v4-flash")

    # === Local / OpenAI-compatible LLM (Ollama, Groq, OpenAI, vLLM, LM Studio) ===
    ollama_base_url: str = Field(default="http://localhost:11434/v1", description="Ollama OpenAI-compatible endpoint")
    ollama_model: str = Field(default="llama3.1:70b", description="Default Ollama model tag")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")

    # === Stock media (B-roll footage) ===
    pexels_api_key: str = Field(default="", description="Pexels API key for stock video/photo")
    pixabay_api_key: str = Field(default="", description="Pixabay API key for stock video/photo")

    # === YouTube ===
    youtube_api_key: str = Field(default="", description="YouTube Data API v3 key (primary)")
    youtube_api_keys: str = Field(
        default="",
        description="Extra YouTube API keys, comma-separated. Combined with youtube_api_key for rotation.",
    )
    youtube_quota_daily: int = Field(default=10000, description="Units per day per project")
    youtube_oauth_client_secret: str = Field(
        default="",
        description="Path to the Google OAuth client_secret.json (Desktop app) used "
                    "for the one-time upload-consent flow per channel.",
    )
    youtube_token_dir: str = Field(
        default="output/_yt_tokens",
        description="Directory holding per-channel OAuth refresh tokens (<channel_id>.json).",
    )
    youtube_token_key: str = Field(
        default="",
        description="Optional Fernet key to encrypt stored OAuth tokens at rest.",
    )

    # === OmniCast credential vault ===
    omnicast_credential_fernet_key: str = Field(
        default="",
        description="Optional Fernet key to encrypt provider/platform credentials at rest.",
    )

    @property
    def youtube_key_pool(self) -> list[str]:
        """All YouTube API keys as ordered list, deduped, primary first."""
        seen: set[str] = set()
        pool: list[str] = []
        for raw in [self.youtube_api_key] + self.youtube_api_keys.split(","):
            key = raw.strip()
            if key and key not in seen:
                seen.add(key)
                pool.append(key)
        return pool

    # === Mode ===
    omnicast_mode: str = Field(default="dry_run", description="production | dry_run | staging")

    # === Topic scoring ===
    # Which scoring generation DECIDES auto_approved/needs_review.
    #   v1     — the original weights (trend 30 / gap 40 / rpm 20 / novelty 10)
    #   shadow — v2 is computed and recorded on every topic, but v1 still decides.
    #            DEFAULT, and deliberately so: v2 removed a double-count that was
    #            inflating YouTube-sourced topics by ~15 points, which moves the
    #            approve/review boundary. Flipping that on before calibrating
    #            against labelled topics would silently change what gets made.
    #   v2     — v2 decides. Only switch after the shadow corpus says the new
    #            thresholds are right (see discovery.scoring_calibration).
    omnicast_scoring_mode: str = Field(
        default="shadow", description="v1 | shadow | v2")

    # Which component decides WHICH TOPICS GET MADE.
    #   scorer_gate     — DEFAULT. TopicScorer's discard lane is binding; the
    #                     Channel Architect ranks only what the scorer admits.
    #   architect_only  — legacy: the Architect sees every raw topic and the
    #                     scorer's verdict is ignored on this path.
    # The two production paths disagreed: the orchestrator path already honoured
    # the scorer's lanes (BriefGenerator only briefs 'approve'), while the API
    # path handed the Architect `all_raw` and threw the scoring away. That
    # inconsistency — not a policy choice — is what this setting resolves.
    omnicast_topic_router: str = Field(
        default="scorer_gate", description="scorer_gate | architect_only")

    # === NAS ===
    nas_mount_path: str = Field(default="/Volumes/NAS")
    nas_fallback_path: str = Field(default="/tmp/omnicast_local")

    # === Worker ===
    worker_id: str = Field(default="master", description="Unique worker identifier")
    heartbeat_interval: int = Field(default=30, description="Seconds between heartbeats")

    # === Alerts ===
    quiet_hours_start: str = Field(default="23:00")
    quiet_hours_end: str = Field(default="07:00")
    quiet_hours_timezone: str = Field(default="Asia/Ho_Chi_Minh")

    # === Budget ===
    daily_llm_budget_usd: float = Field(default=10.0, description="Max daily LLM spend")

    # === Computed properties ===
    @property
    def is_production(self) -> bool:
        return self.omnicast_mode == "production"

    @property
    def is_dry_run(self) -> bool:
        return self.omnicast_mode == "dry_run"

    # === Validators ===
    @field_validator("omnicast_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        allowed = {"production", "dry_run", "staging"}
        if v not in allowed:
            raise ValueError(f"omnicast_mode must be one of {allowed}, got '{v}'")
        return v

    @field_validator("omnicast_scoring_mode")
    @classmethod
    def validate_scoring_mode(cls, v: str) -> str:
        allowed = {"v1", "shadow", "v2"}
        if v not in allowed:
            raise ValueError(f"omnicast_scoring_mode must be one of {allowed}, got '{v}'")
        return v

    @field_validator("omnicast_topic_router")
    @classmethod
    def validate_topic_router(cls, v: str) -> str:
        allowed = {"scorer_gate", "architect_only"}
        if v not in allowed:
            raise ValueError(f"omnicast_topic_router must be one of {allowed}, got '{v}'")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("database_url must start with 'postgresql'")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton.

    First call loads from .env / environment.
    Subsequent calls return cached instance.
    """
    return Settings()


def reset_settings() -> None:
    """Clear settings cache. For testing only."""
    get_settings.cache_clear()
