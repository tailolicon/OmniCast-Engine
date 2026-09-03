"""Channel profile configuration - single source of truth for channel identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from omnicast.models.enums import ChannelType, Market, Niche
from omnicast.platforms.models import Destination

if TYPE_CHECKING:
    from omnicast.discovery.models import DiscoveryConfig
    from omnicast.discovery.scorer import StackProfile
    from omnicast.models.schemas import BrandConfig


# Capabilities NO OmniCast channel has, because the engine has no camera, no
# crew and no presenter: it renders TTS narration over generated or licensed
# visuals. This is a property of the pipeline, not an operator preference, which
# is why it is a module constant rather than a per-channel default that someone
# would eventually have to re-type for every channel file.
# Vocabulary: omnicast.shared.production_signals.ALL_TAGS.
PIPELINE_UNSUPPORTED_PRODUCTION: frozenset[str] = frozenset({
    "face_cam", "interview", "on_location", "live_footage", "in_person_demo",
    # `screen_capture` belongs here for the same reason as the rest: there is no
    # screen-recording step in the render pipeline, which
    # `production_router.APPROXIMATED_MODES` says in its own words. The router
    # was fixed to stop granting it, but the TOPIC SCORER does not go through
    # the router — it reads this set — so a software tutorial still looked
    # producible at the moment the system decides what to make.
    "screen_capture",
})

# Band around `target_duration_min` that counts as "the runtime we produce".
# Half to double: a 5-minute cut of a 10-minute format is still our format;
# a 40-minute reference video is a different one.
DURATION_BAND_FACTOR: tuple[float, float] = (0.5, 2.0)


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
    # Fail-closed policy for competitor intelligence. False (default): when the
    # learned playbook is uncontrolled, stale, legacy or unreadable, the writer
    # skips it and logs why. True: this channel would rather stop than write
    # from patterns never verified against a control group.
    # Lives HERE, not only on TopicBrief: the flag was previously declared on
    # the brief alone, and no production brief builder set it — so the
    # fail-closed branch was unreachable outside hand-built unit tests.
    competitor_intel_required: bool = False

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

    # Production capability — feeds TopicScorer's stack_fit dimension.
    # Before these existed, `TopicScorer()` was constructed with no profile on
    # every production path, so stack fit returned the neutral 7.5 for every
    # topic on every run: a scored dimension that could not move.
    #
    # Empty/None means "derive it" (see `to_stack_profile`), not "disable".
    production_duration_band_min: tuple[float, float] | None = None
    #   Runtime band we actually produce well, in minutes. None derives a band
    #   around `target_duration_min`.
    unsupported_production: list[str] = []
    #   EXTRA capabilities this channel lacks, on top of the engine-wide set in
    #   `PIPELINE_UNSUPPORTED_PRODUCTION`. Vocabulary: shared.production_signals.
    supported_production: list[str] = []
    #   Escape hatch: capabilities from the engine-wide set this channel CAN in
    #   fact deliver (e.g. a channel with a licensed stock-interview library).
    proven_title_patterns: list[str] = []
    #   Title shapes we have shipped successfully. Vocabulary:
    #   shared.title_patterns. Empty = unknown, scored as half credit.
    blocked_topic_keywords: list[str] = []
    #   Topics we refuse regardless of demand — a HARD zero on stack fit.
    #   Deliberately NOT `forbidden_words`: that list is about wording inside a
    #   script ("guys", "crazy"), and vetoing a whole topic because its title
    #   contains a word we avoid saying would be a different, much blunter rule.

    # Competitor-intelligence scope (strategic review §4.2). Playbooks used to
    # be keyed by `niche` alone, so every finance channel in the system shared —
    # and overwrote — one thumbnail playbook. Empty means "not declared", which
    # widens the key rather than narrowing it wrongly.
    intel_archetype: str = ""      # defaults to channel_id: whose playbook is this
    audience_segment: str = ""     # "55plus_preretiree", "25_35_beginner", ...
    content_format: str = ""       # "longform_narration", "shorts", "explainer", ...
    content_pillars: list[dict] = []
    #   [{"id": "annuities", "name": "Annuities", "keywords": ["annuity", ...],
    #     "role": "core"}]   role: core | supporting | experimental (§11.2)
    #   See analytics.pillars — declared, never auto-discovered.

    # Channel thesis (§11.1). Five questions an experienced operator can answer
    # about their channel and this system never could. DECLARED, never generated:
    # an LLM would write a plausible thesis for any channel in four seconds, and
    # it would agree with whatever the channel already does — which is exactly
    # what makes it useless as evidence of drift.
    #   {"audience": ..., "promise": ..., "return_reason": ..., "moat": ...,
    #    "owned_format": ...}
    channel_thesis: dict = {}
    # Which experiment lane this channel occupies: proven | adjacent |
    # asymmetric (§11.5). Empty means undeclared, which spends the proven lane's
    # budget without saying so.
    experiment_lane: str = ""

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

    def to_stack_profile(self) -> "StackProfile":
        """What this channel can actually produce — for TopicScorer.stack_fit.

        Every value is derived from configuration that already exists, so an
        untouched channel file yields a REAL profile rather than the neutral
        7.5 that made the dimension inert. The derivations:

        * niches   — the primary niche plus any same-theme niches assigned to
          this channel. Unknown niche ids are skipped, not guessed.
        * markets  — the channel's market.
        * runtime  — `production_duration_band_min` if set, else a band around
          `target_duration_min` (see `DURATION_BAND_FACTOR`). "The runtime we
          are tuned for" is precisely what `target_duration_min` states; a
          reference video at 4x our target is a different format, not a longer
          version of ours.
        * unsupported — the engine-wide set (OmniCast has no camera, no crew and
          no presenter, on any channel) plus per-channel additions, minus any
          the channel explicitly declares it can deliver.
        """
        from omnicast.discovery.scorer import StackProfile

        niches = {self.niche}
        for entry in self.niches or []:
            raw = (entry or {}).get("niche_id") or (entry or {}).get("niche")
            if not raw:
                continue
            try:
                niches.add(Niche(raw))
            except ValueError:
                # An unrecognised niche id is a config error to surface, not a
                # reason to silently widen or narrow what we claim to cover.
                continue

        if self.production_duration_band_min:
            band = (float(self.production_duration_band_min[0]),
                    float(self.production_duration_band_min[1]))
        elif self.target_duration_min:
            low, high = DURATION_BAND_FACTOR
            band = (round(self.target_duration_min * low, 1),
                    round(self.target_duration_min * high, 1))
        else:
            band = (0.0, 0.0)

        unsupported = (set(PIPELINE_UNSUPPORTED_PRODUCTION)
                       | {str(x).strip() for x in self.unsupported_production if str(x).strip()})
        unsupported -= {str(x).strip() for x in self.supported_production if str(x).strip()}

        return StackProfile(
            niches=niches,
            markets={self.market},
            duration_minutes=band,
            proven_title_patterns={str(p).strip() for p in self.proven_title_patterns
                                   if str(p).strip()},
            unsupported_requirements=unsupported,
            blocked_keywords={str(k).strip() for k in self.blocked_topic_keywords
                              if str(k).strip()},
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
