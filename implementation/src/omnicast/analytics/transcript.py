"""Full competitor transcripts, with an ASR fallback when captions are absent.

WHY THIS EXISTS (strategic review §4, P0 item 3):

`competitor_intel._fetch_transcript` returned `" ".join(parts)[:3500]` — roughly
the first four minutes of a twenty-minute video. Everything the script playbook
claimed about STRUCTURE, PACING, RETENTION TACTICS and CTA PLACEMENT was
therefore inferred from the opening act alone. The mid-roll re-hooks and the
payoff — the parts that actually separate a breakout from its channel's
baseline — were never in the model's context, and nothing said so. A playbook
built that way is confidently wrong about the second half of every video.

Two fixes live here:

  1. NO SILENT TRUNCATION. The full transcript is fetched. When a caller does
     need to bound context, it asks for `chunks()` or `head_chars()` and gets a
     `truncated` flag plus a note it can print — the cut is declared, not hidden.
  2. ASR FALLBACK. Roughly a third of channels disable community captions and
     have no auto-captions in the requested language. Those videos silently
     dropped out of the sample before — and they are not a random third, they
     skew towards smaller and non-English-first channels, which is precisely
     the population the cohort work is trying to stop under-sampling. When
     captions are missing we pull the audio (yt-dlp) and transcribe locally
     (faster-whisper, else openai-whisper).

Segment timings are preserved, so downstream code can measure real pacing
(words-per-minute) and read the true first-30-seconds hook instead of guessing.
Every network/heavy import is lazy: importing this module costs nothing and the
pure helpers stay unit-testable without yt-dlp or whisper installed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# Captions we accept, in preference order.
DEFAULT_LANGUAGES = ("en", "en-US", "en-GB")
# ASR is minutes of CPU per video. Above this we decline and say so rather than
# stalling a learning run on one three-hour livestream VOD.
ASR_MAX_MINUTES = 45.0
ASR_MODEL_SIZE = os.getenv("OMNICAST_ASR_MODEL", "base")
# The minute budget bounds how much AUDIO we accept, not how long transcription
# takes, and `_transcribe_file` cannot be interrupted once inside the model. A
# bigger model is several times slower per audio-minute, so the audio budget has
# to shrink with it or "45 minutes of audio" becomes hours of one of two
# research threads.
ASR_MODEL_BUDGET_FACTOR = {
    "tiny": 2.0, "base": 1.0, "small": 0.6, "medium": 0.3,
    "large": 0.15, "large-v2": 0.15, "large-v3": 0.15,
}


def asr_budget_minutes(model_size: str = "", base: float = ASR_MAX_MINUTES) -> float:
    factor = ASR_MODEL_BUDGET_FACTOR.get((model_size or ASR_MODEL_SIZE).lower(), 0.3)
    return round(base * factor, 1)
# yt-dlp defaults to the socket default (infinite). A stalled CDN would hang a
# worker thread forever, and `to_thread` cannot be cancelled.
ASR_SOCKET_TIMEOUT = 30
# Hard ceiling on the downloaded audio. A multi-hour stream that slipped the
# minute budget still cannot fill the disk.
ASR_MAX_FILESIZE_BYTES = 300 * 1024 * 1024


@dataclass(frozen=True)
class Segment:
    """One caption/ASR cue. `start` is seconds from video start."""

    start: float
    text: str
    duration: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True)
class Transcript:
    """A transcript plus the provenance needed to judge how much to trust it."""

    video_id: str
    text: str = ""
    source: str = ""  # "captions" | "asr" | "" (nothing available)
    language: str = ""
    segments: tuple[Segment, ...] = field(default_factory=tuple)
    note: str = ""  # why it is empty / degraded — never leave a caller guessing

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def covered_seconds(self) -> float:
        """How much of the video the segments actually span (0 if unknown)."""
        if not self.segments:
            return 0.0
        return max(seg.end for seg in self.segments)

    def window(self, start: float, end: float) -> str:
        """Text spoken between `start` and `end` seconds.

        Used for the real first-15/30-second hook instead of 'the first N
        characters', which drifts badly on fast or slow talkers."""
        if not self.segments:
            return ""
        picked = [s.text for s in self.segments if s.start < end and s.end > start]
        return " ".join(t.strip() for t in picked if t.strip()).strip()

    def head_chars(self, max_chars: int) -> tuple[str, bool]:
        """First `max_chars` characters and whether anything was dropped.

        The bool is the point: the old code returned only the string."""
        if max_chars <= 0 or len(self.text) <= max_chars:
            return self.text, False
        return self.text[:max_chars], True

    def chunks(self, max_chars: int = 12_000, overlap: int = 400) -> list[str]:
        """Split the FULL transcript into overlapping windows.

        Overlap keeps a beat that straddles a boundary readable in at least one
        chunk. Callers map over the chunks and reduce — that is how the whole
        video reaches the model within a context budget, instead of the first
        3,500 characters standing in for all of it."""
        text = self.text.strip()
        if not text:
            return []
        if max_chars <= 0 or len(text) <= max_chars:
            return [text]
        step = max(max_chars - max(overlap, 0), 1)
        out: list[str] = []
        for start in range(0, len(text), step):
            piece = text[start:start + max_chars]
            if piece.strip():
                out.append(piece)
            if start + max_chars >= len(text):
                break
        return out

    def describe(self) -> str:
        """One line a human or an LLM prompt can carry as provenance."""
        if not self.ok:
            return f"{self.video_id}: no transcript ({self.note or 'unavailable'})"
        minutes = self.covered_seconds / 60.0
        span = f", covers {minutes:.1f} min" if minutes > 0 else ""
        return (
            f"{self.video_id}: {self.word_count} words via {self.source}"
            f"{(' [' + self.language + ']') if self.language else ''}{span}"
        )


def _minutes(value) -> float | None:
    """Duration as a real number of minutes, else None (= unknown).

    NaN is the case that matters: `nan <= 0` and `nan > max_minutes` are BOTH
    False, so a NaN duration slipped past the "unknown, go probe" gate and the
    budget gate at once, and went straight to download + transcribe."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _empty(video_id: str, note: str) -> Transcript:
    return Transcript(video_id=video_id, note=note)


def _segments_to_text(segments: list[Segment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text and s.text.strip()).strip()


def fetch_captions(
    video_id: str,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
) -> Transcript:
    """Fetch YouTube captions in full — no character cap.

    Handles both youtube_transcript_api generations (object cues and dict cues)
    the way the previous helper did, but keeps the timing rather than throwing
    it away."""
    if not video_id:
        return _empty(video_id, "no video_id")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as exc:  # pragma: no cover - dependency missing
        return _empty(video_id, f"youtube_transcript_api unavailable: {exc}")

    try:
        api = YouTubeTranscriptApi()
        try:
            fetched = api.fetch(video_id, languages=list(languages))
        except TypeError:
            # Older signature: no languages kwarg.
            fetched = api.fetch(video_id)
    except Exception as exc:
        return _empty(video_id, f"captions unavailable: {type(exc).__name__}")

    language = getattr(fetched, "language_code", "") or ""
    segments: list[Segment] = []
    for cue in fetched:
        if isinstance(cue, dict):
            text = cue.get("text", "")
            start = float(cue.get("start", 0.0) or 0.0)
            duration = float(cue.get("duration", 0.0) or 0.0)
        else:
            text = getattr(cue, "text", "") or ""
            start = float(getattr(cue, "start", 0.0) or 0.0)
            duration = float(getattr(cue, "duration", 0.0) or 0.0)
        if text and text.strip():
            segments.append(Segment(start=start, text=text.strip(), duration=duration))

    if not segments:
        return _empty(video_id, "captions returned no cues")
    return Transcript(
        video_id=video_id,
        text=_segments_to_text(segments),
        source="captions",
        language=language,
        segments=tuple(segments),
    )


def probe_media(video_id: str) -> tuple[float, bool, str]:
    """Ask yt-dlp for the real duration and live status BEFORE downloading.

    The caller-supplied duration cannot be trusted for the exact videos that
    matter: `youtube_scanner._parse_duration_minutes` returns 0.0 for a live
    stream or premiere (`P0D`, `P1DT2H`), i.e. the one class of media the
    minute budget exists to reject reported itself as "unknown". Returns
    (minutes, is_live, error)."""
    try:
        import yt_dlp
    except Exception as exc:  # pragma: no cover - dependency missing
        return 0.0, False, f"yt-dlp unavailable: {exc}"
    try:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "socket_timeout": ASR_SOCKET_TIMEOUT,
                # The probe is a pre-flight check, not the work. Retrying it
                # multiplies an already-unbounded wait inside a 2-thread pool.
                "retries": 0, "extractor_retries": 0}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False) or {}
        is_live = bool(info.get("is_live") or info.get("live_status") in
                       {"is_live", "is_upcoming", "post_live"})
        seconds = float(info.get("duration") or 0.0)
        return seconds / 60.0, is_live, ""
    except Exception as exc:
        return 0.0, False, f"probe failed: {type(exc).__name__}"


def _download_audio(video_id: str, workdir: str) -> str:
    """Pull bestaudio for one video via yt-dlp. Returns the file path, or ''."""
    try:
        import yt_dlp
    except Exception as exc:  # pragma: no cover - dependency missing
        logger.warning("yt-dlp unavailable for ASR", error=str(exc))
        return ""
    target = os.path.join(workdir, f"{video_id}.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": target,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 2,
        "socket_timeout": ASR_SOCKET_TIMEOUT,
        "max_filesize": ASR_MAX_FILESIZE_BYTES,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            path = ydl.prepare_filename(info)
        if path and os.path.exists(path):
            return path
        # Extension may differ post-processing; take whatever landed.
        for name in os.listdir(workdir):
            if name.startswith(video_id):
                return os.path.join(workdir, name)
    except Exception as exc:
        logger.warning("audio download failed", video_id=video_id, error=str(exc))
    return ""


# Loading a Whisper model costs seconds and hundreds of MB. A learning run
# transcribes 8+ videos, so loading per video was paying that cost 8 times over.
# Keyed by model size; process-local by design (a worker owns its model).
_ASR_MODELS: dict[str, object] = {}
# Check-then-act on a plain dict is not atomic across worker threads: eight
# concurrent transcriptions loaded six separate copies of the model, five of
# them orphaned from the dict but still referenced by in-flight work. At
# `large-v3` (~3 GB each) that is a multi-GB spike, not a wasted second.
_ASR_MODELS_LOCK = threading.Lock()


def _cached_model(key: str, build):
    with _ASR_MODELS_LOCK:
        if key not in _ASR_MODELS:
            logger.info("loading ASR model", key=key)
            _ASR_MODELS[key] = build()
        return _ASR_MODELS[key]


def _load_faster_whisper(model_size: str):
    from faster_whisper import WhisperModel

    return _cached_model(
        f"faster:{model_size}",
        lambda: WhisperModel(model_size, device="cpu", compute_type="int8"),
    )


def _load_whisper(model_size: str):
    import whisper

    return _cached_model(f"whisper:{model_size}", lambda: whisper.load_model(model_size))


def _transcribe_file(path: str, model_size: str = ASR_MODEL_SIZE) -> tuple[list[Segment], str]:
    """Transcribe an audio file. Prefers faster-whisper, falls back to whisper.

    BLOCKING and CPU-bound — callers inside an event loop must go through
    `asyncio.to_thread` (see analytics.competitor_intel)."""
    try:
        model = _load_faster_whisper(model_size)
        raw_segments, info = model.transcribe(path, vad_filter=True)
        segments = [
            Segment(start=float(s.start or 0.0), text=(s.text or "").strip(),
                    duration=float((s.end or 0.0) - (s.start or 0.0)))
            for s in raw_segments
            if (s.text or "").strip()
        ]
        return segments, getattr(info, "language", "") or ""
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("faster-whisper failed", error=str(exc))

    try:
        model = _load_whisper(model_size)
        result = model.transcribe(path)
        segments = [
            Segment(start=float(s.get("start", 0.0)), text=str(s.get("text", "")).strip(),
                    duration=float(s.get("end", 0.0)) - float(s.get("start", 0.0)))
            for s in result.get("segments", [])
            if str(s.get("text", "")).strip()
        ]
        return segments, str(result.get("language", "") or "")
    except ImportError:
        logger.info("no local ASR engine installed (faster-whisper / whisper)")
    except Exception as exc:
        logger.warning("whisper failed", error=str(exc))
    return [], ""


def transcribe_with_asr(
    video_id: str,
    *,
    duration_minutes: float = 0.0,
    max_minutes: float | None = None,
    model_size: str = ASR_MODEL_SIZE,
) -> Transcript:
    """Last-resort transcript: download the audio and run local ASR."""
    if max_minutes is None:
        max_minutes = asr_budget_minutes(model_size)
    if not video_id:
        return _empty(video_id, "no video_id")

    # `if duration_minutes and ...` let 0.0 bypass the budget entirely — and 0.0
    # is exactly what the scanner reports for live streams and premieres, whose
    # ISO duration (`P0D`, `P1DT2H`) it cannot parse. So an unknown duration is
    # now resolved against the source rather than waved through.
    minutes = _minutes(duration_minutes)
    if minutes is None or minutes <= 0:
        probed, is_live, probe_error = probe_media(video_id)
        if is_live:
            return _empty(video_id, "ASR skipped: live stream or premiere")
        if probe_error:
            return _empty(video_id, f"ASR skipped: duration unknown ({probe_error})")
        if probed <= 0:
            return _empty(video_id, "ASR skipped: duration still unknown after probe")
        minutes = probed

    if minutes > max_minutes:
        return _empty(
            video_id,
            f"ASR skipped: {minutes:.0f} min exceeds the {max_minutes:.0f} min budget",
        )

    workdir = tempfile.mkdtemp(prefix="omnicast_asr_")
    try:
        audio = _download_audio(video_id, workdir)
        if not audio:
            return _empty(video_id, "ASR skipped: audio download failed")
        segments, language = _transcribe_file(audio, model_size=model_size)
        if not segments:
            return _empty(video_id, "ASR produced no speech")
        logger.info("transcript via ASR", video_id=video_id, segments=len(segments))
        return Transcript(
            video_id=video_id,
            text=_segments_to_text(segments),
            source="asr",
            language=language,
            segments=tuple(segments),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def fetch_transcript(
    video_id: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    allow_asr: bool = True,
    duration_minutes: float = 0.0,
    max_asr_minutes: float = ASR_MAX_MINUTES,
) -> Transcript:
    """Full transcript for a video: captions first, ASR only if they are missing.

    Never truncates and never returns a bare '' — a failed fetch still carries a
    `note` saying which stage failed, so a thin sample is visible rather than
    looking like a video with nothing to say."""
    captions = fetch_captions(video_id, languages=languages)
    if captions.ok:
        return captions
    if not allow_asr:
        return _empty(video_id, captions.note or "no captions; ASR disabled")
    asr = transcribe_with_asr(
        video_id, duration_minutes=duration_minutes, max_minutes=max_asr_minutes
    )
    if asr.ok:
        return asr
    return _empty(video_id, f"{captions.note}; {asr.note}")
