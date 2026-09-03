"""plan.json — the video as a plan you can read, diff, and re-render by part.

WHY AN IR AT ALL. Until now a video existed only as the render that produced
it: change one narration line or one bad clip and the only lever was "run the
whole thing again", which re-bought every segment that was already right.
Orkas-VideoStudio (MIT) ships the counter-design this file re-implements in
OmniCast idiom: the video is a list of SEGMENTS with a `produced_path` written
back per segment, so a re-render walks the plan and re-produces ONLY the nodes
whose inputs changed — the checkpoint is the plan itself.

THE PROMISE IS A NUMBER. The second Orkas idea worth stealing whole: a
`delivery_promise` with a `motion_min_ratio` floor, checked by arithmetic and
not by judgment. An "AI video" assembled from stills with Ken Burns drift is a
slideshow; a channel that promised motion must fail its own gate when the
motion is not there. Compose cards (title cards, stat cards) never count as
motion no matter how animated their CSS is.

TRACKS ARE DATA. Narration lines and caption lines live in the plan as text
with timings, not as pixels baked into segments. Fixing a typo is editing one
line and re-burning; the picture is untouched. Narration is mixed EXACTLY once
at assemble — a segment that carries its own voice AND a narration track is
the double-voice defect, and validate() treats it as such.

File location: `output/products/{channel}/{slug}/plan.json`, beside the
`meta.json` the QC manifest already writes. SQLite stays the SSOT for
lifecycle data; the plan is a per-product ARTIFACT, like the video it builds.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import Field

from omnicast.models.schemas import OmnicastSchema

PLAN_FILENAME = "plan.json"


class PromiseType(str, Enum):
    """What kind of picture the audience was promised."""

    MOTION_LED = "motion_led"      # generated/edited motion carries the video
    SOURCE_LED = "source_led"      # user/source footage carries it
    COMPOSE_LED = "compose_led"    # cards and overlays are the point
    HYBRID = "hybrid"


#: Minimum share of produced primary-track seconds that must be real motion.
#: Orkas `assessDelivery` defaults, kept verbatim — they were tuned on shipped
#: shorts, and inventing new numbers here would un-tune them.
PROMISE_FLOORS: dict[PromiseType, float] = {
    PromiseType.MOTION_LED: 0.7,
    PromiseType.SOURCE_LED: 0.3,
    PromiseType.HYBRID: 0.2,
    PromiseType.COMPOSE_LED: 0.0,
}


class SegmentRole(str, Enum):
    HOOK = "hook"
    BODY = "body"
    PROOF = "proof"
    CTA = "cta"
    TRANSITION = "transition"
    CHAPTER = "chapter"


class SegmentLayer(str, Enum):
    PRIMARY = "primary"
    OVERLAY = "overlay"
    BG = "bg"


class SegmentSource(str, Enum):
    GENERATE = "generate"    # paid model output (Veo/Flow/image chain)
    EDIT = "edit"            # cut from existing footage
    COMPOSE = "compose"      # rendered card/overlay — never counts as motion
    PROVIDED = "provided"    # operator-supplied asset


#: spec keys a segment must carry, per source. Checked by `validate_plan` so a
#: malformed plan dies at plan time, before anything is billed — the same
#: reason Orkas validates before its paid gate.
_REQUIRED_SPEC: dict[SegmentSource, tuple[str, ...]] = {
    SegmentSource.GENERATE: ("prompt",),
    SegmentSource.EDIT: ("input_id", "in_sec", "out_sec"),
    SegmentSource.COMPOSE: ("kind",),
    SegmentSource.PROVIDED: ("asset_id",),
}


class DeliveryPromise(OmnicastSchema):
    type: PromiseType = PromiseType.MOTION_LED
    source_required: bool = False
    #: Override the type's default floor; None means "use the default".
    motion_min_ratio: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def floor(self) -> float:
        if self.motion_min_ratio is not None:
            return self.motion_min_ratio
        return PROMISE_FLOORS[self.type]


class NarrationLine(OmnicastSchema):
    line_id: str
    text: str
    start_sec: float | None = None
    target_sec: float = 0.0
    produced_path: str = ""      # per-line TTS artifact — re-voice one line


class CaptionLine(OmnicastSchema):
    caption_id: str
    text: str
    start_sec: float
    end_sec: float


class Tracks(OmnicastSchema):
    narration: list[NarrationLine] = Field(default_factory=list)
    music: dict = Field(default_factory=dict)     # {"mood": …, "path": …}
    captions: list[CaptionLine] = Field(default_factory=list)


class Segment(OmnicastSchema):
    segment_id: str
    order: int
    role: SegmentRole = SegmentRole.BODY
    layer: SegmentLayer = SegmentLayer.PRIMARY
    source: SegmentSource
    target_sec: float = Field(gt=0.0)
    #: Overlay/bg segments sit over a primary segment by id.
    over: str | None = None
    spec: dict = Field(default_factory=dict)
    status: str = "planned"
    produced_path: str = ""
    evidence: dict = Field(default_factory=dict)

    @property
    def produced(self) -> bool:
        return bool(self.produced_path) and Path(self.produced_path).exists()

    @property
    def is_motion(self) -> bool:
        """Compose never counts, whatever its animation does."""
        return (self.layer is SegmentLayer.PRIMARY
                and self.source is not SegmentSource.COMPOSE)


class VideoPlan(OmnicastSchema):
    plan_id: str
    channel_id: str = ""
    aspect: str = "9:16"
    total_target_sec: float = Field(gt=0.0)
    language: str = "en"
    delivery_promise: DeliveryPromise = Field(default_factory=DeliveryPromise)
    segments: list[Segment] = Field(default_factory=list)
    tracks: Tracks = Field(default_factory=Tracks)
    #: Signed off before generation: exactly how many billable generations
    #: this plan performs. Orkas gate C — the count the operator agreed to.
    billable_generations: int = 0
    notes: list[str] = Field(default_factory=list)

    # -- lookups ------------------------------------------------------------

    def segment(self, segment_id: str) -> Segment | None:
        for s in self.segments:
            if s.segment_id == segment_id:
                return s
        return None

    def ordered(self) -> list[Segment]:
        return sorted(self.segments, key=lambda s: s.order)

    # -- write-back ---------------------------------------------------------

    def with_produced(self, segment_id: str, path: str,
                      status: str = "produced") -> "VideoPlan":
        """Record one produced segment. The plan is frozen; the update is a
        copy — which is exactly what makes a diff of before/after readable."""
        updated = [
            s.model_copy(update={"produced_path": path, "status": status})
            if s.segment_id == segment_id else s
            for s in self.segments
        ]
        return self.model_copy(update={"segments": updated})

    def pending(self) -> list[Segment]:
        """What a resume actually needs to produce — everything else is paid
        for and on disk."""
        return [s for s in self.ordered() if not s.produced]


# --------------------------------------------------------------------------
# Validation — dies at plan time, not at bill time
# --------------------------------------------------------------------------

def validate_plan(plan: VideoPlan) -> list[str]:
    """Every way this plan could waste money or assemble wrong, as strings.

    Returns issues rather than raising: the caller decides whether an issue
    blocks (runner) or renders as a warning list (UI).
    """
    issues: list[str] = []

    orders = [s.order for s in plan.segments]
    if len(set(orders)) != len(orders):
        issues.append("segment orders are not unique — assemble order is "
                      "ambiguous")

    ids = [s.segment_id for s in plan.segments]
    if len(set(ids)) != len(ids):
        issues.append("segment ids are not unique — write-back would update "
                      "the wrong node")

    primary_ids = {s.segment_id for s in plan.segments
                   if s.layer is SegmentLayer.PRIMARY}
    if not primary_ids:
        issues.append("no primary-layer segments — there is no picture")

    for s in plan.segments:
        for key in _REQUIRED_SPEC[s.source]:
            if key not in s.spec:
                issues.append(f"segment {s.segment_id}: source '{s.source.value}'"
                              f" requires spec['{key}']")
        if s.layer is not SegmentLayer.PRIMARY:
            if not s.over:
                issues.append(f"segment {s.segment_id}: {s.layer.value} layer "
                              f"must name the primary segment it sits over")
            elif s.over not in primary_ids:
                issues.append(f"segment {s.segment_id}: over='{s.over}' is not "
                              f"a primary segment")
        # Double-voice: a segment carrying its own narration while the plan
        # also has a narration track is the defect Orkas guards with
        # `--on-existing-audio reject`.
        if plan.tracks.narration and s.spec.get("narration"):
            issues.append(f"segment {s.segment_id}: carries its own narration "
                          f"while the plan has a narration track — voice would "
                          f"be mixed twice")

    billable = sum(1 for s in plan.segments
                   if s.source is SegmentSource.GENERATE)
    if plan.billable_generations != billable:
        issues.append(f"billable_generations says {plan.billable_generations} "
                      f"but the plan contains {billable} generate segments — "
                      f"the signed cost and the real cost disagree")

    if plan.delivery_promise.source_required and not any(
            s.source in (SegmentSource.EDIT, SegmentSource.PROVIDED)
            for s in plan.segments):
        issues.append("promise requires source footage but no edit/provided "
                      "segment exists")

    target = sum(s.target_sec for s in plan.segments
                 if s.layer is SegmentLayer.PRIMARY)
    if target and abs(target - plan.total_target_sec) > max(
            2.0, plan.total_target_sec * 0.2):
        issues.append(f"primary segments target {target:.1f}s but the plan "
                      f"promises {plan.total_target_sec:.1f}s — one of them "
                      f"is wrong")

    return issues


# --------------------------------------------------------------------------
# Promise check — slideshow is a hard fail by NUMBERS, not judgment
# --------------------------------------------------------------------------

def assess_delivery(plan: VideoPlan) -> dict:
    """Motion arithmetic over the PRODUCED primary track.

    `ok=False` means the assembled video would break the channel's promise —
    the same class of gate as `validate_video`, applied before assemble
    instead of after.
    """
    produced = [s for s in plan.ordered()
                if s.layer is SegmentLayer.PRIMARY and s.produced]
    total = sum(s.target_sec for s in produced)
    motion = sum(s.target_sec for s in produced if s.is_motion)
    ratio = (motion / total) if total else 0.0
    floor = plan.delivery_promise.floor

    warnings: list[str] = []
    run = 0
    last_key = None
    for s in produced:
        key = (s.source.value, str(s.spec.get("prompt") or
                                   s.spec.get("input_id") or ""))
        run = run + 1 if key == last_key else 1
        last_key = key
        if run == 3:
            warnings.append(f"three consecutive segments share the same "
                            f"source/spec around {s.segment_id} — reads as a "
                            f"loop")

    return {
        "motion_seconds": motion,
        "produced_seconds": total,
        "motion_ratio": round(ratio, 3),
        "floor": floor,
        "ok": (not total and not plan.segments) or ratio >= floor,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# Persistence — beside meta.json, and nowhere else
# --------------------------------------------------------------------------

def save_plan(plan: VideoPlan, product_dir: str | Path) -> Path:
    out = Path(product_dir) / PLAN_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return out


def load_plan(product_dir: str | Path) -> VideoPlan | None:
    src = Path(product_dir) / PLAN_FILENAME
    if not src.exists():
        return None
    return VideoPlan.model_validate(json.loads(src.read_text(encoding="utf-8")))
