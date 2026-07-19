"""Cross-video repetition guard.

A single critic sees ONE draft, so it can't know that "Denise", "Biscuit", the
tall-still figure and the same skeleton already appeared in the last five videos.
For a batch-generated channel that sameness is the biggest tell. This keeps a
small rolling fingerprint of recent scripts per channel and flags reuse so the
pipeline can force a rewrite before publishing yet another near-duplicate.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

_STORE = Path(__file__).resolve().parents[3] / "output" / "_script_fingerprints.json"
_KEEP = 20  # rolling window of recent scripts per channel

# Words that look like names but aren't (sentence starts, months, etc.).
_STOP = {
    "The", "That", "This", "Then", "There", "They", "When", "What", "Where", "While",
    "But", "And", "For", "Not", "Now", "One", "Two", "Three", "She", "His", "Her",
    "Him", "Its", "Our", "You", "Your", "My", "We", "It", "In", "On", "At", "As",
    "So", "No", "By", "Up", "If", "Or", "An", "A", "I", "Some", "Every", "Most",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday", "Route", "Room", "Mile", "Level",
}

# Motifs that become a "generator fingerprint" if they recur video after video.
_MOTIFS = {
    "tall and still": r"\btall\b[^.]{0,45}\b(still|motionless)\b|standing (perfectly|completely) still",
    "tree line figure": r"\b(tree ?line|treeline|end of the (hall|aisle|road))\b",
    "old logbook": r"\blog ?book\b",
    "thermos": r"\bthermos\b",
    "brass keys": r"\bbrass\b.{0,15}\bkey",
    "cracked mug": r"\bchipped\b.{0,10}\b(mug|rim)|\bcracked\b.{0,10}\b(handle|mug)",
    "manager who knows": r"\b(manager|owner|coworker|the previous \w+)\b[^.]{0,40}\b(quit|warned|wouldn'?t (say|explain))",
    "signature already there": r"\bsignature\b[^.]{0,40}\b(mine|my (full )?name|before)",
    "I told myself": r"\bi told myself\b",
    "graveyard shift": r"\bgraveyard shift\b",
}


def fingerprint(text: str, *, archetypes: list[str] | None = None) -> dict:
    """Extract recurring proper names + present motifs from a script.

    Names = capitalized words appearing MID-sentence (preceded by a lowercase word
    or comma) at least twice — so sentence-start words ("Nothing", "Cold", "Just")
    are not mistaken for character names.

    archetypes (optional): typed threat/escape signatures for THIS compilation
    (e.g. "lone_stranger/barricade_in_place"), fed forward so the planner varies
    the archetype lineup across videos, not just within one. Empty by default so
    channels that do not supply them keep the exact old fingerprint shape."""
    low = text.lower()
    mid = re.findall(r"(?<=[a-z,]\s)([A-Z][a-z]{2,})\b", text)
    cnt = Counter(mid)
    names = sorted({w for w, c in cnt.items() if c >= 2 and w not in _STOP})
    motifs = sorted(k for k, pat in _MOTIFS.items() if re.search(pat, low))
    fp = {"names": names[:20], "motifs": motifs}
    if archetypes:
        fp["archetypes"] = sorted({a for a in archetypes if a})[:12]
    return fp


def _load(store: Path) -> dict:
    try:
        return json.loads(store.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_reuse(channel_id: str, fp: dict, store: Path = _STORE) -> list[str]:
    """Compare a fingerprint against the channel's recent scripts. Returns human
    flags for reused names / over-used motifs (does NOT record — call record())."""
    recent = _load(store).get(channel_id, [])[-_KEEP:]
    if not recent:
        return []
    flags: list[str] = []
    prev_names: set[str] = set().union(*[set(r.get("names", [])) for r in recent])
    reused = [n for n in fp.get("names", []) if n in prev_names]
    if reused:
        flags.append("reused character names from recent videos: "
                     + ", ".join(reused[:6]) + " — pick fresh names")
    motif_counts = Counter(m for r in recent for m in r.get("motifs", []))
    overused = [m for m in fp.get("motifs", []) if motif_counts[m] >= 3]
    if overused:
        flags.append("motifs over-used across recent videos (banned for the next few): "
                     + ", ".join(overused))
    return flags


def record(channel_id: str, fp: dict, store: Path = _STORE) -> None:
    """Append a fingerprint to the channel's rolling window."""
    data = _load(store)
    lst = data.get(channel_id, [])
    lst.append(fp)
    data[channel_id] = lst[-_KEEP:]
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def recent_avoid(channel_id: str, store: Path = _STORE) -> tuple[list[str], list[str]]:
    """Names + motifs used in this channel's recent scripts, to feed FORWARD into
    the writer prompt so it avoids reusing them (closes the loop — check_reuse only
    flags AFTER the fact). Returns (names, over-used-motifs)."""
    recent = _load(store).get(channel_id, [])[-_KEEP:]
    if not recent:
        return [], []
    names = sorted({n for r in recent for n in r.get("names", [])})
    motif_counts = Counter(m for r in recent for m in r.get("motifs", []))
    motifs = sorted(m for m, c in motif_counts.items() if c >= 2)
    return names[:25], motifs


def recent_archetypes(channel_id: str, store: Path = _STORE) -> list[str]:
    """Typed threat/escape archetypes used in this channel's recent videos, to
    feed FORWARD so the planner varies the archetype lineup across videos (the
    within-video no-two-share gate cannot see prior videos)."""
    recent = _load(store).get(channel_id, [])[-_KEEP:]
    counts = Counter(a for r in recent for a in r.get("archetypes", []))
    # Anything used in the last few videos is worth steering away from; the most
    # recently repeated first.
    return [a for a, _c in counts.most_common(12)]


def check_and_record(
    channel_id: str, text: str, store: Path = _STORE,
    *, archetypes: list[str] | None = None,
) -> list[str]:
    """Convenience: fingerprint `text`, flag reuse vs history, then record it."""
    fp = fingerprint(text, archetypes=archetypes)
    flags = check_reuse(channel_id, fp, store)
    record(channel_id, fp, store)
    return flags
