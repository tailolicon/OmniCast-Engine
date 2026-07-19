"""Word-synced subtitles — transcribe the rendered narration and time the
captions to the actual speech.

Technique ported from profesor-gato (faster-whisper word_timestamps -> chunked
ASS). The old path burned the full narration line statically for a whole shot;
this follows the voice word-by-word so captions land on the spoken word.

Style matches the project's "text only, no background band" rule: white fill,
thick black outline, BorderStyle=1 (outline, no opaque box), bottom-centered.
Free + local (CPU int8 "base" model). Falls back gracefully if faster-whisper
or ffmpeg is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

_WORDS_PER_CHUNK = 6  # was 4 — denser captions felt relentless (operator feedback)


def _safe_replace(src: Path, dst: Path, attempts: int = 8) -> None:
    """os.replace with backoff — Windows transiently locks a freshly written mp4
    (antivirus scan, lingering ffmpeg/probe handle) → WinError 5. Retry instead of
    crashing the whole render at the caption step."""
    last = None
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.5 * (i + 1))
    raise last
_MODEL_CACHE: dict[str, object] = {}


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return bool(shutil.which("ffmpeg"))


def _get_model(size: str = "base"):
    if size not in _MODEL_CACHE:
        from faster_whisper import WhisperModel
        _MODEL_CACHE[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODEL_CACHE[size]


def transcribe_segments(
    audio_path: str, language: str | None = None, words_per_chunk: int = _WORDS_PER_CHUNK
) -> list[dict]:
    """Transcribe audio into {start, end, text} caption chunks (~N words).
    language=None lets whisper auto-detect. [] on failure."""
    try:
        model = _get_model()
        segs, _ = model.transcribe(
            str(audio_path), language=language, word_timestamps=True
        )
        import re as _re
        out: list[dict] = []
        for seg in segs:
            words = list(seg.words or [])
            if not words:
                if (seg.text or "").strip():
                    out.append({"start": seg.start, "end": seg.end,
                                "text": seg.text.strip()})
                continue
            # Smart chunking: break at sentence punctuation or a soft size cap,
            # but NEVER right after a number fragment (token ending in digit/comma)
            # so "$172,000" can't be split into "172" | ",000".
            buf: list = []
            for w in words:
                buf.append(w)
                wt = w.word.strip()
                text = " ".join(x.word.strip() for x in buf).strip()
                ends_sentence = wt.endswith((".", "!", "?", ":"))
                too_long = len(buf) >= 5 or len(text) >= 32  # keep captions to ONE line (steady position)
                mid_number = bool(_re.search(r"[\d,]$", wt))  # likely continues
                if ends_sentence or (too_long and not mid_number):
                    out.append({"start": buf[0].start, "end": buf[-1].end,
                                "text": text})
                    buf = []
            if buf:
                out.append({"start": buf[0].start, "end": buf[-1].end,
                            "text": " ".join(x.word.strip() for x in buf).strip()})
        return out
    except Exception as exc:
        print(f"      [warn] subtitle transcription failed: {exc}")
        return []


def _ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


SUBTITLE_PRESETS = {
    "Classic Vàng": {"PrimaryColour": "&H0000FFFF", "OutlineColour": "&H00000000", "Bold": -1},
    "Neon Hồng": {"PrimaryColour": "&H00EA00FF", "OutlineColour": "&H00FFFFFF", "Bold": -1},
    "Neon Tím": {"PrimaryColour": "&H00FF00BC", "OutlineColour": "&H00000000", "Bold": -1},
    "Neon Đỏ": {"PrimaryColour": "&H000000FF", "OutlineColour": "&H00FFFFFF", "Bold": -1},
    "Neon Xanh": {"PrimaryColour": "&H00FFFF00", "OutlineColour": "&H00000000", "Bold": -1},
    "Bạc Ánh Kim": {"PrimaryColour": "&H00E0E0E0", "OutlineColour": "&H00303030", "Bold": -1},
    "Ngọc Trai": {"PrimaryColour": "&H00F5F5F0", "OutlineColour": "&H00101010", "Bold": -1},
    "Pastel Xanh": {"PrimaryColour": "&H00FFE4B5", "OutlineColour": "&H00101010", "Bold": -1},
    "Pastel Hồng": {"PrimaryColour": "&H00E6E6FA", "OutlineColour": "&H00101010", "Bold": -1},
}

def write_ass(
    segments: list[dict], out_ass: Path, *, width: int = 1920, height: int = 1080,
    fontsize: int = 54, accent: tuple[int, int, int] | None = None,
    channel_meta: dict | None = None,
) -> Path | None:
    """Write an .ass subtitle file. Text-only style with customizable parameters
    from channel_meta or default white fill + thick black outline."""
    if not segments:
        return None

    # Default ASS values
    fontname = "Arial"
    primary_color = "&H00FFFFFF" # White
    outline_color = "&H00000000" # Black
    back_color = "&H00000000"
    bold = -1
    border_style = 1
    outline_size = 1
    shadow_size = 4
    alignment = 2
    margin_v = 90

    # Apply accent color outline if supplied
    if accent:
        r, g, b = accent
        outline_color = f"&H00{b//4:02X}{g//4:02X}{r//4:02X}"

    if channel_meta:
        sub_style = channel_meta.get("subtitle_style", {})
        fontname = sub_style.get("fontname", fontname)
        fontsize = sub_style.get("fontsize", fontsize)
        primary_color = sub_style.get("primary_color", primary_color)
        outline_color = sub_style.get("outline_color", outline_color)
        back_color = sub_style.get("back_color", back_color)
        if "bold" in sub_style:
            bold = -1 if sub_style.get("bold") else 0
        outline_size = sub_style.get("outline_size", outline_size)
        shadow_size = sub_style.get("shadow_size", shadow_size)
        alignment = sub_style.get("alignment", alignment)
        margin_v = sub_style.get("margin_v", margin_v)

        # Apply preset overrides
        preset = sub_style.get("preset")
        if preset in SUBTITLE_PRESETS:
            p = SUBTITLE_PRESETS[preset]
            primary_color = p.get("PrimaryColour", primary_color)
            outline_color = p.get("OutlineColour", outline_color)
            if "Bold" in p:
                bold = p["Bold"]

        # Apply effect overrides
        effect = sub_style.get("effect")
        if effect == "Viền dày":
            outline_size = 3
            shadow_size = 2
        elif effect == "Viền kép":
            outline_size = 3
            shadow_size = 5
        elif effect == "Glow":
            shadow_size = 6
        elif effect == "Shadow":
            outline_size = 1
            shadow_size = 8
        elif effect == "Bóng mềm":
            outline_size = 0
            shadow_size = 4
        elif effect == "Chữ rỗng":
            outline_size = 2
            shadow_size = 0

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{fontname},{fontsize},{primary_color},&H000000FF,{outline_color},"
        f"{back_color},{bold},0,0,0,100,100,1,0,{border_style},{outline_size},{shadow_size},{alignment},"
        f"80,80,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = [header]
    for seg in segments:
        text = (seg.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ts(seg['start'])},{_ts(seg['end'])},Default,,0,0,0,,{text}\n"
        )
    out_ass.write_text("".join(lines), encoding="utf-8")
    return out_ass


def burn(video: Path, ass: Path, out: Path) -> bool:
    """Burn an .ass subtitle onto a video. Runs ffmpeg from the .ass directory so
    the filter sees a bare filename (avoids Windows drive-letter/backslash issues
    in ffmpeg's filtergraph parser). Returns True on success."""
    fm = shutil.which("ffmpeg")
    if not fm:
        return False
    try:
        proc = subprocess.run(
            [fm, "-y", "-i", str(video.resolve()),
             "-vf", f"subtitles={ass.name}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "copy", str(out.resolve())],
            cwd=str(ass.parent), capture_output=True, text=True, timeout=3600,
        )
        return proc.returncode == 0 and out.exists() and out.stat().st_size > 0
    except Exception as exc:
        print(f"      [warn] subtitle burn failed: {exc}")
        return False


def words_to_segments(words: list[dict], words_per_chunk: int = 4) -> list[dict]:
    """Chunk exact edge-tts word timings into caption segments. Same chunking
    rules as the whisper path (break on sentence punctuation or a soft size cap,
    never right after a number fragment so '$172,000' stays whole) but with the
    TTS provider's ground-truth timings — no transcription guesswork."""
    import re as _re
    out: list[dict] = []
    buf: list[dict] = []
    for w in words:
        wt = (w.get("text") or "").strip()
        if not wt:
            continue
        buf.append(w)
        text = " ".join((x.get("text") or "").strip() for x in buf).strip()
        ends_sentence = wt.endswith((".", "!", "?", ":"))
        # 7 words / 42 chars per caption (was 5/32): fewer, calmer switches —
        # operator feedback "phụ đề dày đặc" (captions felt relentless).
        too_long = len(buf) >= 7 or len(text) >= 42
        mid_number = bool(_re.search(r"[\d,]$", wt))
        if ends_sentence or (too_long and not mid_number):
            out.append({"start": buf[0]["start"], "end": buf[-1]["end"], "text": text})
            buf = []
    if buf:
        text = " ".join((x.get("text") or "").strip() for x in buf).strip()
        out.append({"start": buf[0]["start"], "end": buf[-1]["end"], "text": text})
    return out


def apply_words(
    video: Path, work: Path, words: list[dict], *,
    width: int = 1920, height: int = 1080,
    accent: tuple[int, int, int] | None = None,
    channel_meta: dict | None = None,
) -> bool:
    """Burn captions from exact word timings (no whisper). Chunks -> gap-fill ->
    ASS -> burn in place. Returns True on success, False if there's nothing to
    burn (caller can fall back to the whisper path)."""
    segs = words_to_segments(words)
    if not segs:
        return False
    segs = fill_gaps(segs)
    ass = write_ass(segs, work / "captions.ass", width=width, height=height,
                    accent=accent, channel_meta=channel_meta)
    if not ass:
        return False
    tmp = video.with_name(video.stem + "_subbed.mp4")
    if not burn(video, ass, tmp):
        return False
    _safe_replace(tmp, video)
    return True


def fill_gaps(segments: list[dict], max_gap: float = 1.0) -> list[dict]:
    # max_gap 2.5→1.0: only bridge tiny inter-word gaps. Real pauses (the
    # script's deliberate dramatic beats) now CLEAR the screen — constant text
    # made the video feel wall-to-wall dense (operator feedback 2026-07-09).
    """Extend each caption's end toward the next caption's start so short silences
    between sentences don't leave the screen caption-less (word-sync only shows a
    chunk while its words are spoken). Only bridges gaps <= max_gap — a longer gap
    means a real scene/topic break, so the caption is allowed to clear."""
    if not segments:
        return segments
    out = [dict(s) for s in segments]
    for i in range(len(out) - 1):
        gap = out[i + 1]["start"] - out[i]["end"]
        if 0 < gap <= max_gap:
            out[i]["end"] = out[i + 1]["start"] - 0.05
    return out


def apply_to_video(
    video: Path, work: Path, *, language: str | None = None,
    width: int = 1920, height: int = 1080,
    accent: tuple[int, int, int] | None = None,
    channel_meta: dict | None = None,
) -> bool:
    """End-to-end: transcribe `video`'s audio, build an ASS, burn it in place.
    Writes to a temp file then atomically replaces `video`. Returns True if the
    video got captions. No-op (False) if unavailable or transcription empty."""
    if not available():
        return False
    segs = transcribe_segments(str(video), language=language)
    if not segs:
        return False
    segs = fill_gaps(segs)
    ass = write_ass(segs, work / "captions.ass", width=width, height=height,
                    accent=accent, channel_meta=channel_meta)
    if not ass:
        return False
    tmp = video.with_name(video.stem + "_subbed.mp4")
    if not burn(video, ass, tmp):
        return False
    _safe_replace(tmp, video)
    return True


if __name__ == "__main__":
    import sys
    v = Path(sys.argv[1])
    ok = apply_to_video(v, v.parent)
    print("subtitled" if ok else "skipped")
