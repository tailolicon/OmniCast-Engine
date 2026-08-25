"""Pydantic models for Media Pipeline. All frozen, inherit OmnicastSchema."""

from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from pydantic import Field
from omnicast.models.schemas import OmnicastSchema


class TTSEngine(StrEnum):
    KOKORO = "kokoro"
    EDGE = "edge"
    XTTSV2 = "xttsv2"
    F5TTS = "f5tts"


class ImageGenBackend(StrEnum):
    SDXL = "sdxl"
    FLUX = "flux"


class VideoGenBackend(StrEnum):
    WAN21 = "wan21"
    KEN_BURNS = "ken_burns"


class MusicSource(StrEnum):
    YT_AUDIO_LIB = "yt_audio_lib"
    ROYALTY_FREE = "royalty_free"
    ACE_STEP = "ace_step"
    MUSICGEN = "musicgen"


class MediaStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TTSRequest(OmnicastSchema):
    """Input for TTS module.

    voice_profile accepts the spec form 'provider:voice_id'
    (e.g. 'kokoro:af_heart', 'edge:ko-KR-SunHiNeural'). Legacy ids
    ('kokoro_en_us_v1') are auto-mapped. voice_fallback is tried in order
    when the primary fails — there is NO robotic last resort by design.
    """
    text: str
    voice_profile: str = "kokoro:af_heart"
    voice_fallback: list[str] = Field(default_factory=list)
    voice_clone: str | None = None
    engine: TTSEngine = TTSEngine.KOKORO  # legacy hint; spec provider wins
    output_path: str = ""
    target_lufs: float = -14.0
    #: Strip stage directions / emoji and spell out symbols before synthesis.
    #: Off only when the caller has already conditioned the text itself.
    normalize: bool = True
    #: Speaking-rate hint for duration estimates; auto-detected when unset.
    language: str | None = None
    #: Per-channel delivery knobs, applied only where the chosen provider
    #: supports them: Edge takes rate/pitch/volume ("+8%", "-2Hz"), Kokoro
    #: takes a numeric speed. Unsupported keys are dropped, never fatal.
    prosody: dict[str, str | float] = Field(default_factory=dict)


class TTSResult(OmnicastSchema):
    audio_path: str = ""
    duration_seconds: float = 0.0
    engine_used: TTSEngine = TTSEngine.KOKORO
    sample_rate: int = 24000
    status: MediaStatus = MediaStatus.DONE


class ImageGenRequest(OmnicastSchema):
    prompt: str
    negative_prompt: str = ""
    backend: ImageGenBackend = ImageGenBackend.SDXL
    width: int = 1920
    height: int = 1080
    output_path: str = ""
    reference_image: str | None = None
    ip_adapter_weight: float = Field(default=0.6, ge=0.0, le=1.0)


class ImageGenResult(OmnicastSchema):
    image_path: str = ""
    backend_used: ImageGenBackend = ImageGenBackend.SDXL
    seed: int = 0
    status: MediaStatus = MediaStatus.DONE


class VideoGenRequest(OmnicastSchema):
    prompt: str
    backend: VideoGenBackend = VideoGenBackend.WAN21
    source_image: str | None = None
    duration_seconds: float = Field(default=5.0, ge=1.0, le=10.0)
    output_path: str = ""


class VideoGenResult(OmnicastSchema):
    video_path: str = ""
    duration_seconds: float = 0.0
    backend_used: VideoGenBackend = VideoGenBackend.WAN21
    status: MediaStatus = MediaStatus.DONE


class MusicRequest(OmnicastSchema):
    mood: str = "cinematic"
    genre: str = ""
    duration_seconds: float = 60.0
    bpm_range: tuple[int, int] = (120, 140)
    source_priority: list[MusicSource] = Field(
        default_factory=lambda: [MusicSource.YT_AUDIO_LIB, MusicSource.ROYALTY_FREE, MusicSource.ACE_STEP]
    )
    output_path: str = ""


class MusicResult(OmnicastSchema):
    audio_path: str = ""
    source_used: MusicSource = MusicSource.YT_AUDIO_LIB
    duration_seconds: float = 0.0
    bpm: int = 0
    license_info: str = ""
    attribution: str = ""
    status: MediaStatus = MediaStatus.DONE


class SubtitleRequest(OmnicastSchema):
    audio_path: str
    language: str = "en"
    output_path: str = ""
    #: Spoken script. With it the module can align without an ASR pass; without
    #: it, captions must come from word timings or transcription.
    text: str = ""
    #: `.words.json` sidecar (Edge-TTS word boundaries). Defaults to the one
    #: sitting next to `audio_path` when present.
    words_path: str | None = None
    #: Characters per caption line. 0 picks by script: 15 for CJK, 40 otherwise.
    max_line_chars: int = 0


class SubtitleResult(OmnicastSchema):
    srt_path: str = ""
    word_count: int = 0
    duration_seconds: float = 0.0
    #: How the timings were obtained: 'word_boundaries' (exact, from the TTS
    #: provider), 'whisperx' (forced alignment) or 'estimated' (proportional
    #: split — good enough to preview, not to ship).
    timing_source: str = ""
    status: MediaStatus = MediaStatus.DONE


class ThumbnailRequest(OmnicastSchema):
    title: str
    style: str = "dark_contrast"
    source_image: str | None = None
    color_palette: list[str] = Field(default_factory=lambda: ["#1A1A2E", "#E94560", "#FFFFFF"])
    font: str = "Montserrat Bold"
    output_dir: str = ""
    variants: int = Field(default=3, ge=1, le=5)


class ThumbnailResult(OmnicastSchema):
    paths: list[str] = Field(default_factory=list)
    selected_variant: str = ""
    status: MediaStatus = MediaStatus.DONE


class RenderLayer(OmnicastSchema):
    """One layer in FFmpeg render."""
    layer_type: str  # video, voiceover, music, subtitle, intro_outro
    file_path: str
    volume_db: float = 0.0
    start_offset: float = 0.0


class RenderJob(OmnicastSchema):
    """Full FFmpeg render specification."""
    job_id: str
    channel_id: str
    layers: list[RenderLayer] = Field(default_factory=list)
    output_path: str = ""
    resolution: str = "1920x1080"
    codec: str = "h264"
    audio_codec: str = "aac"
    crossfade_seconds: float = 0.5
    music_duck_db: float = -20.0
    transition_primary: str = "glitch"  # Style preset transition
    transition_secondary: str = "whip-pan"  # Style preset secondary transition


class RenderResult(OmnicastSchema):
    output_path: str = ""
    duration_seconds: float = 0.0
    file_size_mb: float = 0.0
    status: MediaStatus = MediaStatus.DONE


class ContentFingerprint(OmnicastSchema):
    """Uniqueness fingerprint for duplicate detection."""
    video_id: str
    script_hash: str = ""
    visual_hashes: list[str] = Field(default_factory=list)
    audio_fingerprint: str = ""
    music_fingerprint: str = ""
    structure_signature: str = ""

    def similarity_score(self, other: ContentFingerprint) -> float:
        """Compare two fingerprints. >0.7 = too similar."""
        matches = 0
        total = 5
        if self.script_hash and self.script_hash == other.script_hash:
            matches += 1
        if self.visual_hashes and other.visual_hashes:
            overlap = len(set(self.visual_hashes) & set(other.visual_hashes))
            max_len = max(len(self.visual_hashes), len(other.visual_hashes))
            matches += (overlap / max_len) if max_len > 0 else 0
        if self.audio_fingerprint and self.audio_fingerprint == other.audio_fingerprint:
            matches += 1
        if self.music_fingerprint and self.music_fingerprint == other.music_fingerprint:
            matches += 1
        if self.structure_signature and self.structure_signature == other.structure_signature:
            matches += 1
        return matches / total


class MediaPipelineState(OmnicastSchema):
    """Tracks overall pipeline progress for one video."""
    video_id: str
    channel_id: str
    tts: MediaStatus = MediaStatus.PENDING
    images: MediaStatus = MediaStatus.PENDING
    video_gen: MediaStatus = MediaStatus.PENDING
    music: MediaStatus = MediaStatus.PENDING
    subtitle: MediaStatus = MediaStatus.PENDING
    thumbnail: MediaStatus = MediaStatus.PENDING
    render: MediaStatus = MediaStatus.PENDING
    fingerprint: MediaStatus = MediaStatus.PENDING

    @property
    def all_done(self) -> bool:
        return all(
            s in (MediaStatus.DONE, MediaStatus.SKIPPED)
            for s in [self.tts, self.images, self.video_gen, self.music,
                       self.subtitle, self.thumbnail, self.render, self.fingerprint]
        )

    @property
    def has_failure(self) -> bool:
        return any(
            s == MediaStatus.FAILED
            for s in [self.tts, self.images, self.video_gen, self.music,
                       self.subtitle, self.thumbnail, self.render, self.fingerprint]
        )
