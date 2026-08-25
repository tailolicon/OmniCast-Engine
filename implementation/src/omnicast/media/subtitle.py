"""Captions built from real timings — word boundaries first, ASR only if needed.

WHAT THIS REPLACED. This module used to return two hard-coded cues, "Hello
world" and "How are you", for every input. It looked implemented — it wrote a
valid SRT, reported a word count, and passed through the pipeline without an
error — which is the worst failure mode available: a caption track that is
confidently wrong. Anything that cannot produce honest timings now raises.

THE SOURCE LADDER. Timings come from the cheapest trustworthy source available:

1. **Word boundaries** from the `.words.json` sidecar that `tts_edge` already
   writes next to its audio. These are the synthesiser's own word timings —
   exact by construction, free, and immune to the mistake ASR makes on numbers
   and proper nouns ("2026" heard as "twenty twenty six", a channel name
   spelled three ways across one video).
2. **WhisperX** forced alignment, when installed. Needed for voices that emit
   no boundaries (Kokoro, cloned voices) and for any audio not synthesised here.
3. **Proportional split** of the known script across the measured duration,
   weighted by syllables rather than characters. An estimate, and labelled as
   one in `SubtitleResult.timing_source` — usable for a rough burn-in, not for
   a deliverable.

LINE LENGTH IS PER SCRIPT, NOT PER CHARACTER COUNT. A 40-character latin line
and a 40-character Chinese line are not the same amount of reading: CJK packs
far more meaning per glyph and takes longer per glyph to read. pyvideotrans
splits at 15 characters for CJK and 40 otherwise
(`videotrans/configure/config.py:446-447`); those are the defaults here, with
`max_line_chars` overriding when a channel wants tighter lines.

CUES BREAK ON MEANING, NOT ONLY ON WIDTH. A cue also ends at a sentence
terminator, at a silence longer than `_GAP_SPLIT_SECONDS`, and before it
outstays `_MAX_CUE_SECONDS`. Cues shorter than `_MIN_CUE_SECONDS` are merged
forward: a caption that flashes for a third of a second is noise on screen.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from omnicast.media.base import BaseMediaModule
from omnicast.media.models import MediaStatus, SubtitleRequest, SubtitleResult
from omnicast.media.tts import measure_duration
from omnicast.media.tts_normalize import (
    count_syllables,
    detect_lang,
    split_sentences,
)
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()

#: Characters per caption line, by script (pyvideotrans defaults).
_CJK_LINE_CHARS = 15
_OTHER_LINE_CHARS = 40

#: A cue never exceeds this many characters regardless of line width.
_HARD_CUE_CHARS = 150

_MIN_CUE_SECONDS = 1.0
_MAX_CUE_SECONDS = 7.0
#: Silence longer than this is a beat: the cue ends there even mid-sentence.
_GAP_SPLIT_SECONDS = 0.7

_SENTENCE_TAIL = tuple(".。．!！?？۔।॥")


class SubtitleModule(BaseMediaModule):
    name = "subtitle"

    async def _process(self, request: SubtitleRequest) -> SubtitleResult:
        words = self._load_word_timings(request)
        timing_source = "word_boundaries"

        if not words:
            words = await self._align_with_whisperx(request)
            timing_source = "whisperx"

        if not words:
            words = await self._estimate_from_script(request)
            timing_source = "estimated"

        if not words:
            raise MediaError(
                "No caption timings available: no .words.json sidecar next to "
                f"{request.audio_path}, WhisperX not installed, and no script "
                "text supplied. Refusing to emit placeholder captions."
            )

        segments = pack_captions(
            words,
            max_line_chars=request.max_line_chars or None,
            language=request.language,
        )
        output_path = request.output_path or "subtitle_output.srt"
        word_count = self._write_srt(segments, output_path)

        logger.info(
            "captions written",
            path=output_path, cues=len(segments),
            words=word_count, source=timing_source,
        )
        return SubtitleResult(
            srt_path=output_path,
            word_count=word_count,
            duration_seconds=segments[-1]["end"] if segments else 0.0,
            timing_source=timing_source,
            status=MediaStatus.DONE,
        )

    # ------------------------------------------------------------- sources

    def _load_word_timings(self, request: SubtitleRequest) -> list[dict]:
        """Read the `.words.json` sidecar written by a boundary-aware provider."""
        candidate = (
            Path(request.words_path) if request.words_path
            else Path(request.audio_path).with_suffix(".words.json")
        )
        if not candidate.exists():
            return []
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("word sidecar unreadable", path=str(candidate), error=str(exc))
            return []

        words = [
            {"start": float(w["start"]), "end": float(w["end"]), "text": str(w["text"]).strip()}
            for w in raw
            if isinstance(w, dict) and str(w.get("text", "")).strip()
        ]
        # A sidecar whose clock runs backwards is corrupt, not merely untidy.
        if any(b["start"] < a["start"] for a, b in zip(words, words[1:])):
            logger.warning("word sidecar not monotonic — ignoring", path=str(candidate))
            return []
        return words

    async def _align_with_whisperx(self, request: SubtitleRequest) -> list[dict]:
        """Forced alignment. Absent WhisperX this returns nothing and the ladder
        falls through — an optional heavy dependency must not be a hard import."""
        try:
            import whisperx  # noqa: F401
        except ImportError:
            return []

        def _run() -> list[dict]:
            import whisperx

            audio = whisperx.load_audio(request.audio_path)
            model = whisperx.load_model("small", device="cpu", compute_type="int8")
            result = model.transcribe(audio, language=request.language or None)
            align_model, meta = whisperx.load_align_model(
                language_code=result["language"], device="cpu"
            )
            aligned = whisperx.align(
                result["segments"], align_model, meta, audio, "cpu",
                return_char_alignments=False,
            )
            return [
                {"start": float(w["start"]), "end": float(w["end"]),
                 "text": str(w.get("word", "")).strip()}
                for seg in aligned.get("segments", [])
                for w in seg.get("words", [])
                if w.get("start") is not None and str(w.get("word", "")).strip()
            ]

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:  # model download, bad audio, OOM
            logger.warning("whisperx alignment failed", error=str(exc))
            return []

    async def _estimate_from_script(self, request: SubtitleRequest) -> list[dict]:
        """Spread the known script over the measured duration by syllable weight.

        Each sentence becomes one pseudo-word so packing keeps sentences whole —
        with no real word timings, splitting inside a sentence would invent
        precision the estimate does not have.
        """
        if not request.text.strip():
            return []
        total = await asyncio.to_thread(measure_duration, request.audio_path)
        if total <= 0.0:
            logger.warning("cannot probe audio duration — no estimated captions",
                           path=request.audio_path)
            return []

        sentences = split_sentences(request.text)
        weights = [max(1, count_syllables(s)) for s in sentences]
        span = sum(weights)
        if not span:
            return []

        cursor, words = 0.0, []
        for sentence, weight in zip(sentences, weights):
            length = total * weight / span
            words.append({"start": cursor, "end": cursor + length, "text": sentence})
            cursor += length
        return words

    # -------------------------------------------------------------- output

    def _write_srt(self, segments: list[dict], output_path: str) -> int:
        """Write SRT. Returns the word count actually captioned."""
        path = Path(output_path)
        if path.parent != Path(""):
            path.parent.mkdir(parents=True, exist_ok=True)

        lines, word_count = [], 0
        for index, seg in enumerate(segments, 1):
            lines.append(str(index))
            lines.append(
                f"{self._format_time(seg['start'])} --> {self._format_time(seg['end'])}"
            )
            lines.append(seg["text"])
            lines.append("")
            word_count += len(seg["text"].split())
        path.write_text("\n".join(lines), encoding="utf-8")
        return word_count

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds to SRT timestamp (HH:MM:SS,mmm)."""
        seconds = max(0.0, seconds)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis == 1000:  # rounding carried into the next second
            secs, millis = secs + 1, 0
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _dry_run_result(self, request: SubtitleRequest) -> SubtitleResult:
        return SubtitleResult(
            srt_path=request.output_path or "dry_run_subtitle.srt",
            word_count=0,
            duration_seconds=0.0,
            timing_source="dry_run",
            status=MediaStatus.DONE,
        )


def pack_captions(
    words: list[dict],
    *,
    max_line_chars: int | None = None,
    language: str | None = None,
    hard_cue_chars: int = _HARD_CUE_CHARS,
    min_cue_seconds: float = _MIN_CUE_SECONDS,
    max_cue_seconds: float = _MAX_CUE_SECONDS,
    gap_split_seconds: float = _GAP_SPLIT_SECONDS,
) -> list[dict]:
    """Group word timings into readable cues.

    Pure function of its inputs — the packing rules are the part worth testing,
    so they do not touch the filesystem or a model.
    """
    if not words:
        return []

    if max_line_chars is None:
        sample = " ".join(w["text"] for w in words[:40])
        max_line_chars = (
            _CJK_LINE_CHARS if (language or detect_lang(sample)) in {"zh", "ja", "ko"}
            else _OTHER_LINE_CHARS
        )

    cues: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        if not current:
            return
        cues.append({
            "start": current[0]["start"],
            "end": current[-1]["end"],
            "text": _join(current),
        })
        current.clear()

    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            width = len(_join(current + [word]))
            span = word["end"] - current[0]["start"]
            if (
                gap > gap_split_seconds
                or width > max_line_chars
                or width > hard_cue_chars
                or span > max_cue_seconds
                or current[-1]["text"].endswith(_SENTENCE_TAIL)
            ):
                flush()
        current.append(word)
    flush()

    return _merge_flashes(cues, min_cue_seconds, hard_cue_chars, max_cue_seconds)


def _join(words: list[dict]) -> str:
    """Join words, respecting scripts that do not put spaces between them."""
    out = ""
    for word in words:
        text = word["text"]
        if out and not (detect_lang(text) in {"zh", "ja"} and detect_lang(out[-1]) in {"zh", "ja"}):
            out += " "
        out += text
    return out.strip()


def _merge_flashes(
    cues: list[dict], min_seconds: float, hard_chars: int, max_seconds: float
) -> list[dict]:
    """Fold sub-`min_seconds` cues into their neighbour when the merge still fits."""
    merged: list[dict] = []
    for cue in cues:
        if merged:
            previous = merged[-1]
            too_short = cue["end"] - cue["start"] < min_seconds
            fits = (
                len(previous["text"]) + len(cue["text"]) + 1 <= hard_chars
                and cue["end"] - previous["start"] <= max_seconds
            )
            if too_short and fits:
                previous["end"] = cue["end"]
                previous["text"] = f"{previous['text']} {cue['text']}".strip()
                continue
        merged.append(dict(cue))
    return merged
