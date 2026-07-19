"""Channel profile configuration - single source of truth for channel identity."""

from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
import json
from pydantic import BaseModel, Field, field_validator

from omnicast.models.enums import Niche, Market, ChannelType
from omnicast.platforms.models import Destination

if TYPE_CHECKING:
    from omnicast.models.schemas import BrandConfig
    from omnicast.discovery.models import DiscoveryConfig


class ChannelProfile(BaseModel):
    """Complete channel configuration. Single source of truth."""

    # Identity
    channel_id: str  # "fin_retirement_us", "health_nutrition_us"
    name: str  # "Smart Retirement"
    niche: Niche
    sub_niche: str = ""  # "retirement", "crypto", "stocks"
    # A channel may cover several vault niches (operator assigns a same-theme niche
    # to an existing channel instead of spawning a new one). Each entry:
    # {"niche_id": str, "niche_name": str, "assigned_at": ISO8601}. The primary
    # niche/sub_niche above stay set for backward compatibility.
    niches: list[dict] = []
    youtube_channel_id: str = ""  # real YouTube UC... id (stats + analytics mapping)
    market: Market = Market.US
    language: str = "en"
    channel_type: ChannelType = ChannelType.HUB
    destinations: list[Destination] = Field(default_factory=list)
    # M1: multi-platform targets. Empty keeps legacy YouTube-only behavior.

    # Brand / Visual Style (moved from BrandConfig)
    visual_style: str = "dark_cinematic"  # key into STYLE_PRESETS
    channel_style: str = "auto"  # visual SOURCING policy: footage|storytelling|horror_real|auto
    #   (config/channel_styles.py) — footage=stock B-roll, storytelling=AI images,
    #   horror_real=real photos only (AI art banned), auto=storyboard LLM decides.
    voice_profile: str = "kokoro_en_us_v1"
    voice_clone: str | None = None
    color_palette: list[str] = ["#1A1A2E", "#E94560", "#FFFFFF"]
    font: str = "Montserrat Bold"
    transition_style: str = "zoom_in_0.3s"
    intro_template: str | None = None
    outro_template: str | None = None
    music_bpm_range: tuple[int, int] = (120, 140)
    thumbnail_style: str = "dark_contrast"
    image_gen_mode: str = "sdxl"
    use_video_gen: bool = False
    target_duration_min: int = 10

    # Content Style (drives Writer + Critic)
    niche_config_key: str = ""  # override key into NICHE_CONFIGS; defaults to niche.value
    script_profile: str = ""  # immutable named strategy in config.narrative_quality
    brand_voice: str = ""  # "authoritative", "conversational", "provocative"
    tone: str = "direct"  # "direct", "empathetic", "dramatic"
    hook_format: str = ""  # opening 15-second formula (from ChannelBuilderAgent)
    ref_channels: list[str] = []  # legacy field, kept for backward compat
    forbidden_words: list[str] = []  # per-channel banned words

    # Visual Branding (drives thumbnail + video overlay)
    brand_color_hex: str = "#1A1A2E"   # primary hex color; finance=dark blue, health=green
    font_vibe: str = "sans_modern"     # "serif_classic"|"sans_modern"|"slab_bold"|"handwritten_warm"

    # Voice / TTS
    voice_persona: str = "neutral_adult"  # e.g. "authoritative_50yo_male", "calm_female_doctor"
    #   Maps to TTS voice library at render time. voice_profile = actual Kokoro/ElevenLabs key.

    # Lifecycle
    channel_created_at: str | None = None  # ISO8601; set after YouTube channel registration
    #   ChannelGuard uses this: None → treat as young (safe default, max velocity = 3/week)

    # Audience Profile — drives Writer content targeting
    audience: dict = {}
    # Format:
    # {
    #   "age_range": "45-65",
    #   "gender_skew": "slight male",
    #   "income_level": "middle class",
    #   "pain_points": ["fear of outliving savings", ...],
    #   "content_triggers": ["specific dollar amounts", ...],
    #   "preferred_video_length_min": 12,
    #   "engagement_drivers": ["fear of shortage", ...]
    # }

    # Discovery Config
    competitor_handles: list[str] = []   # YouTube @handles — resolved to IDs at scan time
    competitor_channel_ids: list[str] = []  # legacy: raw YouTube channel IDs
    subreddits: list[str] = []
    rss_feeds: list[str] = []
    podcast_keywords: list[str] = []
    trends_keywords: list[str] = []
    rpm_floor: float = 7.0

    # Schedule
    upload_cadence: str = "3x_weekly"  # "daily", "3x_weekly", "weekly"
    prime_time_hours: list[int] = [9, 12, 17]  # UTC hours

    @field_validator("script_profile")
    @classmethod
    def _known_script_profile(cls, value: str) -> str:
        profile_id = (value or "").strip()
        if profile_id:
            from omnicast.config.narrative_quality import resolve_script_profile

            resolve_script_profile(profile_id)
        return profile_id

    def to_brand_config(self) -> "BrandConfig":
        """Extract media-pipeline-compatible BrandConfig."""
        # Import here to avoid circular dependency
        from omnicast.models.schemas import BrandConfig

        return BrandConfig(
            channel_id=self.channel_id,
            voice_profile=self.voice_profile,
            voice_clone=self.voice_clone,
            color_palette=self.color_palette,
            font=self.font,
            transition_style=self.transition_style,
            intro_template=self.intro_template,
            outro_template=self.outro_template,
            music_bpm_range=self.music_bpm_range,
            thumbnail_style=self.thumbnail_style,
            image_gen_mode=self.image_gen_mode,
            use_video_gen=self.use_video_gen,
        )

    def to_discovery_config(self) -> "DiscoveryConfig":
        """Extract discovery-compatible config."""
        # Import here to avoid circular dependency
        from omnicast.discovery.models import DiscoveryConfig

        return DiscoveryConfig(
            niche=self.niche,
            markets=[self.market],
            competitor_handles=self.competitor_handles,
            competitor_channel_ids=self.competitor_channel_ids,
            subreddits=self.subreddits,
            rss_feeds=self.rss_feeds,
            podcast_keywords=self.podcast_keywords,
            trends_keywords=self.trends_keywords,
            rpm_floor=self.rpm_floor,
        )


class ChannelProfileLoader:
    """Load ChannelProfile from JSON files on disk.

    Directory structure:
        channels/
        ├── fin_retirement_us.json
        ├── fin_crypto_us.json
        ├── health_nutrition_us.json
        └── myth_greek_us.json
    """

    def __init__(self, config_dir: str | Path) -> None:
        self.config_dir = Path(config_dir)
        self._cache: dict[str, ChannelProfile] = {}

    async def load(self, channel_id: str) -> ChannelProfile:
        """Load a single channel profile by ID."""
        if channel_id in self._cache:
            return self._cache[channel_id]

        file_path = self.config_dir / f"{channel_id}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Channel profile not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        profile = ChannelProfile(**data)
        self._cache[channel_id] = profile
        return profile

    async def load_all(self) -> dict[str, ChannelProfile]:
        """Load all channel profiles from config directory."""
        profiles = {}
        for file_path in self.config_dir.glob("*.json"):
            channel_id = file_path.stem
            try:
                profile = await self.load(channel_id)
                profiles[channel_id] = profile
            except Exception as e:
                print(f"Failed to load {channel_id}: {e}")
        return profiles

    async def save(self, profile: ChannelProfile) -> None:
        """Save a channel profile to disk."""
        file_path = self.config_dir / f"{profile.channel_id}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(profile.model_dump(mode="json"), f, indent=2)

        self._cache[profile.channel_id] = profile
