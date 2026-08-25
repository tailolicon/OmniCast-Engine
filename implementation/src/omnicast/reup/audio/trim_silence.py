"""Trim the dead air a TTS engine leaves at both ends of a clip.

Engines pad their output: a beat of silence before the first phoneme and a
longer one after the last. The planner treats the whole clip as speech, so that
padding eats the slot — the voice starts late against its shot, and a line that
would have fitted gets sped up to make room for silence.

Constants follow `pyvideotrans/util/help_ffmpeg.py:633` (`remove_silence_wav`),
including the asymmetric padding: 80 ms kept at the head, 200 ms at the tail,
because trailing vowels ring on and clipping them sounds abrupt.

Stdlib only — the pipeline already reads these WAVs with `wave`, and pulling in
pydub for a peak-scan would be a dependency for arithmetic.
"""

from __future__ import annotations

import audioop
import wave
from pathlib import Path

# Silence is measured relative to the clip's own loudness, not an absolute
# floor: TTS output level varies per engine and per voice.
RELATIVE_THRESHOLD_DB = 20.0
MIN_SILENCE_MS = 100
HEAD_PADDING_MS = 80
TAIL_PADDING_MS = 200
_FRAME_MS = 10


def _rms_db(frame: bytes, width: int, reference: float) -> float:
    rms = audioop.rms(frame, width)
    if rms <= 0 or reference <= 0:
        return -120.0
    import math

    return 20.0 * math.log10(rms / reference)


def trim_silence(path: Path, *, keep_head_ms: int = HEAD_PADDING_MS,
                 keep_tail_ms: int = TAIL_PADDING_MS) -> int:
    """Trim `path` in place. Returns the new duration in ms (0 if untouched).

    Silence-only or unreadable clips are left exactly as they are: a clip that
    is all padding is still holding a slot, and shortening it to nothing would
    shift every line after it.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error):
        return 0
    if not frames or rate <= 0 or width <= 0:
        return 0

    bytes_per_frame = width * channels
    step = max(1, int(rate * _FRAME_MS / 1000)) * bytes_per_frame
    peak = audioop.max(frames, width)
    if peak <= 0:
        return 0
    threshold_db = -RELATIVE_THRESHOLD_DB

    loud: list[int] = []
    for offset in range(0, len(frames) - bytes_per_frame + 1, step):
        chunk = frames[offset:offset + step]
        if len(chunk) < bytes_per_frame:
            break
        if _rms_db(chunk, width, peak) > threshold_db:
            loud.append(offset)
    if not loud:
        return 0

    min_silence_bytes = int(rate * MIN_SILENCE_MS / 1000) * bytes_per_frame
    head = max(0, loud[0] - int(rate * keep_head_ms / 1000) * bytes_per_frame)
    tail = min(len(frames), loud[-1] + step + int(rate * keep_tail_ms / 1000) * bytes_per_frame)
    # Not worth rewriting the file to shave off a few milliseconds.
    if head < min_silence_bytes and (len(frames) - tail) < min_silence_bytes:
        return int(len(frames) / bytes_per_frame / rate * 1000)

    head -= head % bytes_per_frame
    tail -= tail % bytes_per_frame
    trimmed = frames[head:tail]
    if not trimmed:
        return 0

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(trimmed)
    return int(len(trimmed) / bytes_per_frame / rate * 1000)
