"""Lip sync — phoneme groups to viseme cues (strategic review §7.1).

A viseme is a mouth SHAPE. Several phonemes share one: you cannot see the
difference between /p/, /b/ and /m/, which is why the classic animation sets
collapse dozens of phonemes into about a dozen shapes.

WHAT THIS DOES AND DOES NOT DO

It turns text with cue timings — which `analytics.transcript` already produces
for every video the system touches — into a timed viseme track. That is the half
of lip sync that is computation.

It does NOT draw a mouth. Mapping a viseme onto artwork needs the mouth shapes
from the character bible and a renderer, and `animation.bible.readiness()` says
so. A viseme track with no artwork is a plan, not a performance.

IT IS GRAPHEME-BASED, AND SAYS SO. Real phoneme timing needs a forced aligner
(Montreal Forced Aligner, Gentle, or an ASR with phone output). This distributes
visemes across a cue's own duration by letter groups, which is right for open
and closed mouth shapes and wrong for anything that hangs on true phone
boundaries. `source="grapheme_estimate"` is on every cue so a renderer — or a
reviewer — can tell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from omnicast.shared.numbers import num as _num

# Preston Blair-style set, the one hand-drawn channels actually use.
VISEMES: tuple[str, ...] = (
    "rest",   # closed, neutral
    "MBP",    # m, b, p — lips together
    "FV",     # f, v — lip to teeth
    "TH",     # th
    "L",      # l
    "WQ",     # w, q, oo — rounded and small
    "E",      # e, i — wide
    "AI",     # a, i — open
    "O",      # o — rounded and open
    "U",      # u — rounded, tighter
    "etc",    # everything else: c, d, g, k, n, r, s, t, y, z
)

_LETTER_VISEME: dict[str, str] = {
    "m": "MBP", "b": "MBP", "p": "MBP",
    "f": "FV", "v": "FV",
    "l": "L",
    "w": "WQ", "q": "WQ",
    "e": "E", "i": "E",
    "a": "AI",
    "o": "O",
    "u": "U",
}
# Silence long enough to close the mouth. Shorter gaps read as one continuous
# phrase, and closing on them produces the chattering mouth of bad lip sync.
REST_GAP_SECONDS = 0.18
# A viseme held shorter than this cannot be perceived at 24fps; consecutive
# identical shapes are merged instead.
MIN_VISEME_SECONDS = 1.0 / 24.0

_WORD = re.compile(r"[a-zA-Z']+")
# Any letter in any script, so a Korean or Cyrillic line is recognised as speech
# even though the Latin viseme map cannot name its shapes.
_ANY_LETTER = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True)
class VisemeCue:
    start: float
    end: float
    viseme: str
    source: str = "grapheme_estimate"

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def as_dict(self) -> dict:
        return {"start": round(self.start, 3), "end": round(self.end, 3),
                "viseme": self.viseme, "source": self.source}


def _viseme_for(letter: str) -> str:
    return _LETTER_VISEME.get(letter.lower(), "etc")


def text_to_visemes(text: str, start: float, duration: float) -> list[VisemeCue]:
    """Spread visemes for `text` evenly across its own cue window.

    Even spreading is the honest approximation: without a forced aligner we know
    WHEN the line was said and not when each sound inside it landed. Weighting
    by letter count would imply a precision that is not there."""
    begin = _num(start)
    span = _num(duration)
    if begin is None or span is None or span <= 0:
        return []

    body = str(text or "")
    letters = "".join(_WORD.findall(body))
    if not letters:
        # A Korean or Cyrillic line is SPEECH with shapes this Latin map cannot
        # name — not silence. Returning `rest` for its whole duration gave a
        # character who never opens their mouth, and the repo ships Korean voice
        # config. `unmapped_script` says so instead of lying either way.
        if _ANY_LETTER.search(body):
            return [VisemeCue(begin, begin + span, "etc",
                              source="unmapped_script")]
        return [VisemeCue(begin, begin + span, "rest")]

    step = span / len(letters)
    cues: list[VisemeCue] = []
    for index, letter in enumerate(letters):
        cues.append(VisemeCue(begin + index * step,
                              begin + (index + 1) * step,
                              _viseme_for(letter)))
    return _merge(cues)


def _merge(cues: list[VisemeCue]) -> list[VisemeCue]:
    """Collapse runs of the same shape, and anything too brief to be seen.

    A mouth that changes shape every 12ms is not lip sync; it is noise that a
    renderer would faithfully reproduce as chatter."""
    merged: list[VisemeCue] = []
    for cue in cues:
        if merged and merged[-1].viseme == cue.viseme:
            previous = merged[-1]
            merged[-1] = VisemeCue(previous.start, cue.end, cue.viseme, cue.source)
            continue
        if merged and cue.duration < MIN_VISEME_SECONDS:
            previous = merged[-1]
            merged[-1] = VisemeCue(previous.start, cue.end, previous.viseme,
                                   previous.source)
            continue
        merged.append(cue)
    return merged


def visemes_for_transcript(transcript) -> list[VisemeCue]:
    """A viseme track for a whole transcript, with rests in the gaps.

    Uses the cue timings `analytics.transcript` already carries, so this costs
    nothing extra on any video the system has already transcribed."""
    segments = tuple(getattr(transcript, "segments", ()) or ())
    if not segments:
        return []

    # SORTED, and overlaps trimmed. A transcript merge can hand back segments
    # out of order or overlapping; `_merge` then collapsed a same-shape run
    # across the discontinuity into a cue whose `end` was BEFORE its `start`,
    # and the track ran backwards from there. A renderer would follow it.
    ordered = sorted(
        (s for s in segments if _num(getattr(s, "start", None)) is not None),
        key=lambda s: _num(getattr(s, "start", None)))

    track: list[VisemeCue] = []
    previous_end: float | None = None
    for segment in ordered:
        start = _num(getattr(segment, "start", None))
        duration = _num(getattr(segment, "duration", None))
        text = getattr(segment, "text", "") or ""
        if start is None or duration is None or duration <= 0:
            continue
        if previous_end is not None and start < previous_end:
            # Overlapping cues: trim the new one rather than rewind the track.
            duration -= (previous_end - start)
            start = previous_end
            if duration <= 0:
                continue
        if previous_end is not None and start - previous_end >= REST_GAP_SECONDS:
            track.append(VisemeCue(previous_end, start, "rest"))
        track.extend(text_to_visemes(text, start, duration))
        previous_end = start + duration
    return _merge(track)
