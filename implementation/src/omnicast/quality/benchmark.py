"""Benchmark similarity, split into the dimensions §8 asks for.

THE CLAIM THIS MODULE EXISTS TO STOP: "95% similar to the benchmark".

§8 is explicit that the figure has no definition behind it, and equally explicit
about what would have to exist before anyone may state it:

    a golden reference · a per-dimension metric · blind human comparison ·
    a pass/fail threshold · a report of what cannot or should not be copied

So `compare_to_reference` measures each dimension it can, and `headline` is
withheld — not estimated, not averaged from a partial set — until the
preconditions are satisfied. An average over four measured dimensions and seven
unmeasured ones is a number about nothing, and it would be indistinguishable
from a real one on a dashboard.

WHAT SHOULD NOT BE COPIED IS PART OF THE OUTPUT. §8 asks for it explicitly, and
it is the half everyone forgets: a reference video's on-screen presenter, its
licensed music, its archival footage and its brand marks are not ours to
reproduce. Scoring similarity on those dimensions would reward getting closer to
something we must not ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MEASURED = "measured"
UNKNOWN = "unknown"

# The eleven dimensions from §8, in its order. `comparable` marks the ones it is
# legitimate to try to match at all.
SIMILARITY_DIMENSIONS: tuple[tuple[str, bool, str], ...] = (
    ("script_structure", True, "beat count and where the beats fall"),
    ("visual_source_mix", True, "stock / generated / screen / archival split"),
    ("shot_duration_distribution", True, "median shot length and its spread"),
    ("caption_typography", True, "caption density and style"),
    ("transition_grammar", True, "cut vs dissolve mix"),
    ("sfx_placement", True, "where effects land relative to beats"),
    ("music_energy_curve", True, "energy over time"),
    ("voice_pacing", True, "words per minute and its variance"),
    ("color_treatment", True, "colour mood and contrast"),
    ("thumbnail_packaging", True, "composition and text load"),
    ("perceived_quality", False, "needs blind human comparison — not a metric"),
)

# Dimensions where matching the reference more closely would mean reproducing
# something that is not ours. Reported, never scored.
DO_NOT_COPY: dict[str, str] = {
    "presenter_likeness": "the reference's on-camera presenter is a real person",
    "licensed_music": "their music is licensed to them, not to us",
    "archival_footage": "their archival clips carry their licence, not a transferable one",
    "brand_marks": "logos, lower thirds and channel identity are theirs",
    "voice_identity": "cloning the narrator's voice impersonates a specific person",
}

# Below this, a dimension is too far from the reference to call a match. Named,
# and deliberately NOT applied as an overall pass/fail — see `headline`.
DIMENSION_MATCH_THRESHOLD = 0.80


@dataclass
class DimensionScore:
    name: str
    similarity: float | None = None
    status: str = UNKNOWN
    detail: str = ""

    @property
    def matches(self) -> bool | None:
        if self.similarity is None:
            return None
        return self.similarity >= DIMENSION_MATCH_THRESHOLD

    def as_dict(self) -> dict:
        return {"dimension": self.name, "similarity": self.similarity,
                "status": self.status, "matches": self.matches,
                "detail": self.detail}


@dataclass
class BenchmarkComparison:
    reference_id: str = ""
    dimensions: list[DimensionScore] = field(default_factory=list)
    blind_human_comparison: bool = False
    notes: list[str] = field(default_factory=list)

    def get(self, name: str) -> DimensionScore | None:
        return next((d for d in self.dimensions if d.name == name), None)

    @property
    def measured(self) -> list[DimensionScore]:
        return [d for d in self.dimensions if d.status == MEASURED]

    @property
    def unmeasured(self) -> list[str]:
        return [d.name for d in self.dimensions if d.status != MEASURED]

    @property
    def unmeasured_comparable(self) -> list[str]:
        """Comparable dimensions with no score.

        `perceived_quality` is excluded because it is not comparable BY
        DEFINITION — it is what the blind human comparison is for. Counting it
        as unmeasured made `headline` unreachable for every possible input, so
        §8's pass/fail threshold could never fire and the gate that reads it was
        permanently `unknown`. The human comparison is still required; it is
        just required as itself, under `blind_human_comparison`."""
        comparable = {name for name, ok, _d in SIMILARITY_DIMENSIONS if ok}
        return [name for name in self.unmeasured if name in comparable]

    @property
    def blockers(self) -> list[str]:
        """Why a headline similarity figure may not be stated (§8's own list)."""
        problems: list[str] = []
        if not self.reference_id:
            problems.append("no golden reference was supplied")
        if self.unmeasured_comparable:
            problems.append(
                "these dimensions were not measured: "
                + ", ".join(self.unmeasured_comparable))
        if not self.blind_human_comparison:
            problems.append(
                "no blind human comparison has been recorded — §8 lists it as a "
                "precondition, and perceived quality is not a metric")
        return problems

    @property
    def headline(self) -> float | None:
        """The overall similarity figure, or None with the reasons.

        Averaging four measured dimensions and calling it "95% similar" is the
        exact claim §8 rejects: on a dashboard it is indistinguishable from a
        figure that means something."""
        if self.blockers:
            return None
        scores = [d.similarity for d in self.measured if d.similarity is not None]
        return round(sum(scores) / len(scores), 3) if scores else None

    def as_dict(self) -> dict:
        return {
            "reference_id": self.reference_id,
            "dimensions": [d.as_dict() for d in self.dimensions],
            "measured_count": len(self.measured),
            "unmeasured": self.unmeasured,
            "unmeasured_comparable": self.unmeasured_comparable,
            "blind_human_comparison": self.blind_human_comparison,
            "headline_similarity": self.headline,
            "headline_blocked_by": self.blockers,
            "do_not_copy": dict(DO_NOT_COPY),
            "dimension_match_threshold": DIMENSION_MATCH_THRESHOLD,
            "notes": list(self.notes),
        }


from omnicast.shared.numbers import flag as _flag  # noqa: E402
from omnicast.shared.numbers import num as _number  # noqa: E402


def _ratio_similarity(ours, theirs) -> float | None:
    """1.0 when identical, falling off with relative distance."""
    mine, yours = _number(ours), _number(theirs)
    if mine is None or yours is None:
        return None
    if yours == 0:
        return 1.0 if mine == 0 else 0.0
    return round(max(0.0, min(1.0, 1.0 - abs(mine - yours) / abs(yours))), 3)


def _mix_similarity(ours: dict | None, theirs: dict | None) -> float | None:
    """Overlap between two proportion maps (1 - half the L1 distance)."""
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return None
    if not ours or not theirs:
        return None
    keys = set(ours) | set(theirs)
    distance = 0.0
    for key in keys:
        # Coerced, not cast. `transition_mix` is exactly the dict av_forensics
        # and the pipeline pass around, and a `None` inside it used to raise all
        # the way out of `compare_to_reference`.
        mine, yours = _number(ours.get(key)), _number(theirs.get(key))
        if mine is None or yours is None:
            return None
        distance += abs(mine - yours)
    return round(max(0.0, min(1.0, 1.0 - distance / 2.0)), 3)


def compare_to_reference(ours: dict, reference: dict) -> BenchmarkComparison:
    """Per-dimension similarity between our render and a golden reference.

    Both sides are the shape `analytics.av_forensics` and `video_intel` already
    produce, so this compares MEASUREMENTS rather than descriptions. A dimension
    missing on either side is `unknown`; it never falls back to a default that
    would read as agreement."""
    ours = ours if isinstance(ours, dict) else {}
    reference = reference if isinstance(reference, dict) else {}
    comparison = BenchmarkComparison(
        reference_id=str(reference.get("reference_id") or ""),
        # `_flag`, not `bool`: `bool("no")` is True, and this is the
        # precondition the entire module exists to enforce.
        blind_human_comparison=_flag(reference.get("blind_human_comparison")),
    )

    computed: dict[str, float | None] = {
        "script_structure": _ratio_similarity(
            ours.get("beat_count"), reference.get("beat_count")),
        "visual_source_mix": _mix_similarity(
            ours.get("visual_source_mix"), reference.get("visual_source_mix")),
        "shot_duration_distribution": _ratio_similarity(
            ours.get("median_shot_seconds"), reference.get("median_shot_seconds")),
        "caption_typography": _ratio_similarity(
            ours.get("caption_density"), reference.get("caption_density")),
        "transition_grammar": _mix_similarity(
            ours.get("transition_mix"), reference.get("transition_mix")),
        "sfx_placement": _mix_similarity(
            ours.get("sfx_placement"), reference.get("sfx_placement")),
        "music_energy_curve": _mix_similarity(
            ours.get("music_energy_curve"), reference.get("music_energy_curve")),
        "voice_pacing": _ratio_similarity(
            ours.get("words_per_minute"), reference.get("words_per_minute")),
        "color_treatment": _ratio_similarity(
            ours.get("colour_warmth"), reference.get("colour_warmth")),
        "thumbnail_packaging": _ratio_similarity(
            ours.get("thumbnail_text_words"), reference.get("thumbnail_text_words")),
        "perceived_quality": None,   # never computable here, by definition
    }

    for name, comparable, description in SIMILARITY_DIMENSIONS:
        value = computed.get(name)
        if not comparable:
            comparison.dimensions.append(DimensionScore(
                name=name, status=UNKNOWN,
                detail=f"{description} — a number here would be invented"))
            continue
        if value is None:
            comparison.dimensions.append(DimensionScore(
                name=name, status=UNKNOWN,
                detail=f"{description}: not present on both sides"))
            continue
        comparison.dimensions.append(DimensionScore(
            name=name, similarity=value, status=MEASURED, detail=description))

    if not comparison.reference_id:
        comparison.notes.append(
            "no golden reference id — §8 lists a golden reference as the first "
            "precondition for any similarity claim")
    comparison.notes.append(
        "dimensions in `do_not_copy` are deliberately unscored: scoring them "
        "would reward getting closer to material we are not permitted to ship")
    return comparison
