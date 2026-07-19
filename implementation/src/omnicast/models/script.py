"""Pydantic models for the script production pipeline.

All models are frozen (immutable) and inherit from OmnicastSchema.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from omnicast.models.schemas import OmnicastSchema
from omnicast.models.enums import Niche, Market, TopicSource


# ── Spoken-length calibration (shared: Writer floor, Critic length flag, media gate) ──
# Video length is DRIVEN BY the topic/target (8-12+ min), never a hard-coded word
# count. Two anchors: a per-minute spoken rate, and the platform floor below which
# YouTube won't run mid-roll ads. Everything else derives from target_duration_min.
SPOKEN_WPM = 150            # EN spoken words per wall-minute (vfact ~197 syll/min × ~0.75)
MIDROLL_FLOOR_MIN = 8       # YouTube mid-roll-ads minimum — the only hard lower bound


def spoken_word_floor(target_duration_min: int | None) -> int:
    """Word floor for a script of ``target_duration_min`` minutes, never below the
    8-minute mid-roll platform floor. Scales UP with the target (10, 12, 15…) and
    imposes NO upper cap — longer topics are free to run longer."""
    return max(MIDROLL_FLOOR_MIN, int(target_duration_min or 0)) * SPOKEN_WPM



class VisualCueType(str, Enum):
    """4-group visual cue taxonomy (Gemini pattern-interrupt framework)."""
    BROLL      = "broll"       # Group 1: stock video / b-roll
    TEXT_POPUP = "text_popup"  # Group 2: number/text pop-up
    CHART      = "chart"       # Group 2: chart / graph
    ZOOM       = "zoom"        # Group 3: ken-burns / slam zoom
    TRANSITION = "transition"  # Group 3: whip-pan / glitch between segments
    SFX        = "sfx"         # Audio cue (cash-register, whoosh, alarm)
    CAPTION    = "caption"     # Group 4: dynamic caption style


class VisualCue(OmnicastSchema):
    """One structured visual/audio production instruction."""
    type: VisualCueType
    raw: str = ""           # original bracket text — preserved for editors

    # Group 1 — B-roll
    query: str = ""         # search query for stock footage
    source: str = ""        # pexels | storyblocks | archive | ai-generate
    duration_s: float = 0.0

    # Group 2 — Text popup / Chart
    content: str = ""       # text to display
    color: str = ""         # red | gold | white | alarm-red
    animation: str = ""     # zoom-slam | fade | typewriter | bounce
    template: str = ""      # pie | bar-growth | line | comparison | donut
    data: str = ""          # "93%=fail,7%=succeed" or "10k→1.9M over 30y"
    palette: str = ""       # red-dominant | green-dominant | neutral

    # Group 3 — Camera / Transition
    technique: str = ""     # ken-burns | slam | whip-pan | glitch | cut
    direction: str = ""     # in | out | left | right
    speed: str = ""         # slow | fast | instant
    target: str = ""        # current-frame | buffett-frame | number

    # Group 4 / Audio
    sound: str = ""         # cash-register | alarm | whoosh | ting
    timing: str = ""        # "on '$855,800'" | "segment-start" | "number"


class TopicBrief(OmnicastSchema):
    """Input brief for Writer Agent. Created from Topic Discovery."""
    title: str
    niche: Niche
    market: Market
    source: TopicSource = TopicSource.YOUTUBE_COMPETITOR
    angle: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    target_duration_min: int = 10
    brand_voice: str = ""
    lessons: list[str] = Field(default_factory=list)
    channel_id: str = ""
    sub_niche: str = ""
    # Audience intelligence — set by ChannelArchitectAgent
    target_audience: str = ""   # "55-year-old anxious about outliving savings"
    pain_point: str = ""        # "fear of running out of money in retirement"
    content_angle: str = ""     # "show the math competitors missed"
    # Channel content memory — prevents duplicate topics, enables accurate "Next:" teasers
    topics_done: list[str] = Field(default_factory=list)   # titles already published/scripted
    next_topic: str = ""                                    # next queued topic (for outro teaser)


class ScriptScene(OmnicastSchema):
    """One scene = one camera cut. 3-5 seconds of screen time.

    voiceover: MAX 25 words. Spoken naturally. Zero scripting jargon.
    visual_prompt: Concrete description for AI video tools (stock footage query).
    sfx: Optional sound cue name (alarm | cash-register | whoosh | null).
    
    === NEW — AI media gen fields (optional, populated by VisualDirectorAgent) ===
    image_prompt: detailed prompt for image generation
    negative_prompt: what to avoid
    video_prompt: camera/motion for image-to-video
    text_overlay: text to display on scene
    transition: cut | fade | dissolve | whip-pan
    """
    voiceover: str
    visual_prompt: str          # GIỮ NGUYÊN — stock footage query (legacy)
    sfx: str | None = None
    duration_s: float = 0.0   # estimated from word count
    # === Prosody (vfact benchmark — docs/vfact_benchmark.json) ===
    pace: str = "normal"             # slow | normal | fast — per-scene TTS delivery speed
    pause_after_ms: int = 0          # deliberate silence AFTER this scene (dramatic beat)
    emphasis: list[str] = Field(default_factory=list)  # exact words to stress (pitch/volume spike)
    # === MỚI — AI media gen fields (optional, populate by VisualDirectorAgent) ===
    image_prompt: str = ""           # detailed prompt for image generation
    negative_prompt: str = ""        # what to avoid
    video_prompt: str = ""           # camera/motion for image-to-video
    text_overlay: str = ""           # text to display on scene
    transition: str = "cut"          # cut | fade | dissolve | whip-pan


class ScriptSegment(OmnicastSchema):
    """One segment (section) of a script."""
    index: int
    heading: str
    content: str                                           # narration only (joined from scenes)
    estimated_duration_seconds: int
    has_pattern_interrupt: bool = False
    scenes: list[ScriptScene] = Field(default_factory=list)    # machine-readable for AI video
    visual_cues: list[VisualCue] = Field(default_factory=list)  # structured cues (legacy)
    raw_content: str = ""                                  # full dual-column block


class ScriptDraft(OmnicastSchema):
    """Output of Writer Agent. One variant of a script."""
    variant_id: str
    brief_title: str
    hook: str                                              # narration only
    hook_raw: str = ""                                     # full hook block with [VISUAL:]
    hook_scenes: list[ScriptScene] = Field(default_factory=list)
    segments: list[ScriptSegment] = Field(default_factory=list)
    outro: str = ""
    outro_raw: str = ""
    outro_scenes: list[ScriptScene] = Field(default_factory=list)
    raw_content: str = ""                                  # full LLM output preserved
    description_template: str = ""
    tags: list[str] = Field(default_factory=list)
    estimated_duration_seconds: int = 0
    word_count: int = 0
    thinking_notes: str = ""
    version: int = 1


class CriticDimension(OmnicastSchema):
    """Score for one dimension of critic evaluation."""
    name: str
    score: int = Field(ge=0, le=25)
    max_score: int
    feedback: str = ""

    @model_validator(mode="before")
    @classmethod
    def _clamp_to_max(cls, data):
        """A dimension can NEVER score above its own max (the LLM routinely returns
        niche_compliance 8/5 etc., which inflated totals past 100). Clamp before
        the frozen model is built so downstream subtotals are always valid."""
        if isinstance(data, dict):
            try:
                mx = int(data.get("max_score", 25))
                sc = int(data.get("score", 0))
                data["score"] = max(0, min(sc, mx))
            except (TypeError, ValueError):
                pass
        return data


class CriticFeedback(OmnicastSchema):
    """Structured output from Critic Agent.

    Scores split into two independent groups:
      voiceover_score  (0-70): hook, authenticity, retention, editorial, compliance, pacing
      production_score (0-30): visual concreteness, sfx appropriateness
      total_score = voiceover_score + production_score

    Routing:
      vo < VO_PASS (53)            → Writer.revise()         — script needs rework
      vo >= VO_PASS, prod < 23     → VisualDirectorAgent      — lock VO, fix visuals only
      total >= approval_threshold  → approved
    """
    variant_id: str = ""  # injected by CriticAgent after parsing
    total_score: int = Field(ge=0, le=100)
    voiceover_score: int = Field(ge=0, le=70, default=0)    # VO group subtotal
    production_score: int = Field(ge=0, le=30, default=0)   # production group subtotal
    dimensions: list[CriticDimension] = Field(default_factory=list)
    approved: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
    specific_fixes: list[str] = Field(default_factory=list)   # VO fixes → Writer
    visual_fixes: list[str] = Field(default_factory=list)     # production fixes → VisualDirector
    # Structured integrity signals (narrative). continuity_issues NON-EMPTY forces a
    # hard total cap in CriticAgent.execute — a logic hole cannot score well no
    # matter how polished the prose.
    continuity_issues: list[str] = Field(default_factory=list)
    story_shapes: list[str] = Field(default_factory=list)     # ending shape per story (variety check)
    round_number: int = 1


class DebateRound(OmnicastSchema):
    """Record of one debate round (Writer revision + Critic review)."""
    round_number: int
    draft: ScriptDraft
    feedback: CriticFeedback
    thinking_notes: str = ""
    score_delta: int = 0


class TournamentMatch(OmnicastSchema):
    """Record of pairwise comparison in tournament."""
    variant_a: str
    variant_b: str
    winner: str
    reason: str


class EloRating(OmnicastSchema):
    """Elo rating for a script variant."""
    variant_id: str
    rating: float = 1000.0
    matches_played: int = 0


class EngagementPattern(OmnicastSchema):
    """Learned pattern from production data, stored in KB."""
    pattern_id: str
    niche: Niche
    market: Market
    finding: str
    confidence: float = Field(ge=0, le=1)
    sample_size: int
    decay_date: datetime
    source: str = "path_3_context"
