"""Turn A/V forensics of the competition into render-time editing targets.

Craft forensics measures how winners WRITE. This measures how they CUT — the
half of competitor learning that had a module (`av_forensics`) and no data,
because the fetch flag shipped off by default and was never turned on.

Output is a small, honest profile: median shot length, cut cadence, silence
share, loudness, transition mix and motion mix, expressed as targets the
renderer can actually act on. Fields the signal layer cannot measure
(kinetic typography, callout semantics, b-roll vs talking head) stay listed as
unmeasured rather than guessed.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EditProfile:
    winner_count: int = 0
    control_count: int = 0
    median_shot_seconds: float | None = None
    control_median_shot_seconds: float | None = None
    cuts_per_minute: float | None = None
    control_cuts_per_minute: float | None = None
    silence_ratio: float | None = None
    integrated_lufs: float | None = None
    dissolve_share: float | None = None
    motion_mix: dict = field(default_factory=dict)
    text_overlay_proxy: float | None = None
    duration_seconds: float | None = None
    unmeasured: dict = field(default_factory=dict)

    # SUFFICIENCY GATE (operator audit 27/07). This profile reached the
    # renderer off 5 winners and 2 controls forming TWO matched pairs, and its
    # prose asserted things the signal layer never measured. A measurement may
    # describe; only a sufficient measurement may decide.
    MIN_CHANNELS = 3
    MIN_MATCHED_PAIRS = 10

    channels_covered: int = 0
    matched_pairs: int = 0

    @property
    def is_production_grade(self) -> bool:
        return (self.channels_covered >= self.MIN_CHANNELS
                and self.matched_pairs >= self.MIN_MATCHED_PAIRS)

    def sufficiency_note(self) -> str:
        if self.is_production_grade:
            return (f"production-grade: {self.channels_covered} channels, "
                    f"{self.matched_pairs} matched pairs")
        return (f"NOT production-grade: {self.channels_covered}/"
                f"{self.MIN_CHANNELS} channels, {self.matched_pairs}/"
                f"{self.MIN_MATCHED_PAIRS} matched pairs — descriptive only, "
                "must not change render behaviour")

    def as_directives(self) -> list[str]:
        """Observations, phrased to the limit of what was actually measured.

        Every claim here must be traceable to a measured field. The first
        version of this method asserted "winners re-frame twice as often"
        (contradicted by cuts/minute: 2.77 winner vs 3.04 control), "no
        whooshes, no wipes" (SFX are not classified and the detector only
        knows cut vs dissolve) and "pauses are not filled with music swells"
        (non-speech audio is unmeasured). Those were inferences dressed as
        findings."""
        out: list[str] = [f"[{self.sufficiency_note()}]"]
        if self.median_shot_seconds:
            line = (f"Median shot length ≈ {self.median_shot_seconds:.1f}s "
                    "(winner median).")
            if self.control_median_shot_seconds:
                line += (f" Controls: {self.control_median_shot_seconds:.1f}s. "
                         "NOTE: shot LENGTH and cut FREQUENCY disagree in this "
                         "sample — see the cut-cadence line — so this is not "
                         "evidence that winners re-frame more often.")
            out.append(line)
        if self.cuts_per_minute is not None:
            line = f"Cut cadence ≈ {self.cuts_per_minute:.1f} scene changes/minute."
            if self.control_cuts_per_minute is not None:
                line += (f" Controls: {self.control_cuts_per_minute:.1f} — "
                         "effectively the same, or slightly higher for controls.")
            out.append(line)
        if self.dissolve_share is not None:
            out.append(
                f"Of the transitions the detector CAN classify (cut vs dissolve), "
                f"dissolves are {self.dissolve_share:.0%}. Wipes, whooshes and "
                "other SFX-driven transitions are NOT measured — no claim is made "
                "about them.")
        if self.silence_ratio is not None:
            out.append(
                f"Speech-silence ≈ {self.silence_ratio:.0%} of runtime. What fills "
                "that silence (music, room tone, nothing) is NOT measured.")
        if self.integrated_lufs is not None:
            out.append(f"Programme loudness ≈ {self.integrated_lufs:.0f} LUFS in "
                       "this sample (we master to -14 for YouTube).")
        if self.motion_mix:
            drift = self.motion_mix.get("drift")
            static = self.motion_mix.get("static")
            if drift is not None and static is not None:
                out.append(
                    f"Motion mix: {drift:.0%} drift, {static:.0%} static, rest "
                    "dynamic (frame-difference measure, not camera semantics).")
        if self.text_overlay_proxy is not None:
            out.append(
                f"Edge-density text proxy fires on ~{self.text_overlay_proxy:.0%} "
                "of sampled frames. This is a PROXY: no OCR, no reading of what "
                "the text says or whether it tracks the voice.")
        return out


def _med(rows: list[dict], key: str) -> float | None:
    vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.median(vals), 2) if vals else None


def build_profile(forensics: dict) -> EditProfile:
    rows = list(forensics.values())
    win = [r for r in rows if r.get("role") == "winner"]
    ctl = [r for r in rows if r.get("role") == "control"]
    if not win:
        return EditProfile()

    # transition + motion mixes are per-video dicts; average the shares.
    diss: list[float] = []
    motion: dict[str, list[float]] = {}
    for r in win:
        tm = r.get("transition_mix") or {}
        total = sum(v for v in tm.values() if isinstance(v, (int, float)))
        if total:
            diss.append(float(tm.get("dissolve", 0)) / total)
        for k, v in (r.get("motion_mix") or {}).items():
            if isinstance(v, (int, float)):
                motion.setdefault(k, []).append(float(v))

    # Cohort shape decides whether this profile may DECIDE anything.
    channels = {r.get("channel") or r.get("handle") or "" for r in rows}
    channels.discard("")
    pairs = sum(1 for r in win if r.get("matched_control"))

    return EditProfile(
        winner_count=len(win),
        control_count=len(ctl),
        channels_covered=len(channels),
        matched_pairs=pairs,
        median_shot_seconds=_med(win, "median_shot_seconds"),
        control_median_shot_seconds=_med(ctl, "median_shot_seconds"),
        cuts_per_minute=_med(win, "cuts_per_minute"),
        control_cuts_per_minute=_med(ctl, "cuts_per_minute"),
        silence_ratio=_med(win, "silence_ratio"),
        integrated_lufs=_med(win, "integrated_lufs"),
        dissolve_share=(round(statistics.median(diss), 3) if diss else None),
        motion_mix={k: round(statistics.median(v), 3) for k, v in motion.items()},
        text_overlay_proxy=_med(win, "text_overlay_proxy"),
        duration_seconds=_med(win, "duration_seconds"),
        unmeasured=(win[0].get("not_measured") or {}),
    )


def load_and_build(path: Path) -> EditProfile:
    return build_profile(json.loads(Path(path).read_text(encoding="utf-8")))
