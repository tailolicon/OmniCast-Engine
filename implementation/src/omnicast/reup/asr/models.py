from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WordTimestamp:
    start_ms: int
    end_ms: int
    text: str
    probability: float | None = None


@dataclass(slots=True)
class SegmentDraft:
    segment_index: int
    start_ms: int
    end_ms: int
    source_text: str
    language: str | None = None
    words: list[WordTimestamp] = field(default_factory=list)


@dataclass(slots=True)
class TranscriptionOptions:
    model_name: str
    language: str | None = None
    vad_filter: bool = True
    word_timestamps: bool = True
    compute_type: str | None = None
    # faster-whisper defaults to True, which lets one bad segment poison the
    # next: the model drifts, repeats, or drops lines outright. pyvideotrans
    # turns it off for exactly this reason (videotrans/process/stt_fun.py).
    condition_on_previous_text: bool = False
    # Its VAD default is min_silence_duration_ms=2000 — on a 9:44 dub that
    # removed 2:13 of audio, and anything misjudged in there is simply never
    # transcribed. pyvideotrans uses 140ms with threshold 0.5.
    vad_min_silence_ms: int = 140
    vad_threshold: float = 0.5
    no_speech_threshold: float = 0.6
    # Unset, silero lets a "speech" run grow without bound, so one unbroken
    # stretch becomes a single enormous segment — a subtitle line nobody can
    # read and a TTS clip that cannot fit its slot. pyvideotrans caps it.
    vad_max_speech_s: float = 15.0


@dataclass(slots=True)
class TranscriptionResult:
    source_audio_path: Path
    detected_language: str | None
    duration_ms: int | None
    segments: list[SegmentDraft]


@dataclass(slots=True)
class PersistedTranscription:
    stage_hash: str
    cache_dir: Path
    segments_json_path: Path
    segment_count: int

