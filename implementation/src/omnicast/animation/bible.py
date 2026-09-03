"""Character bible and continuity (strategic review §7.1).

A character bible is what makes a drawn character the SAME character in shot 40
as in shot 2. §7.1 lists it first for a reason: without one, every downstream
piece — pose library, expression set, rigging, lip sync — has nothing to be
consistent with, and "character consistency" becomes a thing you hope for rather
than a thing you check.

DECLARED, LIKE THE CHANNEL THESIS. A bible an image model invents per scene is
the failure being described: it will happily produce a plausible character each
time, and none of them will match. So a bible is configuration, `readiness`
reports what is missing, and `check_continuity` compares a storyboard against
the bible and names every violation instead of returning a score.

WHAT IS DELIBERATELY ABSENT: a renderer. Rigging, keyframe interpolation onto
actual artwork, and drawing are not here. `readiness` says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omnicast.shared.numbers import num as _num


def _entries(value) -> list:
    """A list of mapping entries from config. Scalars and dicts are not that.

    `raw` itself was guarded and its sub-fields were not, so `{"poses": 5}`
    raised `TypeError: 'int' object is not iterable` while reading a channel
    JSON, and `{"poses": {"id": "p"}}` iterated the dict's KEYS and silently
    yielded nothing."""
    if isinstance(value, dict) or isinstance(value, (str, bytes)):
        return []
    try:
        return [v for v in value if isinstance(v, dict)]
    except TypeError:
        return []


def _strings(value) -> list[str]:
    """A list of strings. A bare string is one entry, not its characters."""
    if isinstance(value, (str, bytes)):
        text = value.decode() if isinstance(value, bytes) else value
        return [text] if text.strip() else []
    try:
        return [str(v) for v in value if str(v).strip()]
    except TypeError:
        return []

MEASURED = "measured"
MISSING = "missing"

# The §7.1 inventory. Each entry is a capability, and each says whether this
# package can deliver it or only specify it.
SUBSYSTEM_PARTS: dict[str, str] = {
    "character_bible": "declared here",
    "pose_library": "declared here",
    "expression_library": "declared here",
    "lip_sync": "computed here (viseme timing); needs mouth artwork to render",
    "keyframes_and_easing": "computed here as curves; needs a renderer to apply",
    "squash_and_stretch": "computed here as a transform; needs a renderer",
    "anticipation": "computed here as timing; needs a renderer",
    "comic_timing": "measurable here from beat spacing",
    "rigging": "NOT HERE — needs a rig format and a renderer that reads it",
    "prop_interaction": "NOT HERE — needs scene graph and collision semantics",
    "camera_choreography": "NOT HERE — needs a virtual camera in a renderer",
    "drawing": "NOT HERE — this package renders nothing",
}
# The parts that exist only as a specification. Named so `readiness` cannot be
# read as "animation is done".
UNBUILT_PARTS = tuple(
    name for name, detail in SUBSYSTEM_PARTS.items() if detail.startswith("NOT HERE"))


@dataclass(frozen=True)
class Pose:
    pose_id: str
    description: str = ""
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"pose_id": self.pose_id, "description": self.description,
                "tags": list(self.tags)}


@dataclass(frozen=True)
class Expression:
    expression_id: str
    description: str = ""
    intensity: float = 0.5

    def as_dict(self) -> dict:
        return {"expression_id": self.expression_id,
                "description": self.description, "intensity": self.intensity}


@dataclass
class CharacterBible:
    character_id: str = ""
    name: str = ""
    identity: dict = field(default_factory=dict)
    poses: list[Pose] = field(default_factory=list)
    expressions: list[Expression] = field(default_factory=list)
    palette: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # Identity traits a bible must pin for a character to survive a cut.
    REQUIRED_IDENTITY = ("silhouette", "hair", "outfit", "age_read", "line_style")

    @property
    def pose_ids(self) -> set[str]:
        return {p.pose_id for p in self.poses}

    @property
    def expression_ids(self) -> set[str]:
        return {e.expression_id for e in self.expressions}

    @property
    def missing_identity(self) -> list[str]:
        return [key for key in self.REQUIRED_IDENTITY
                if not str(self.identity.get(key, "")).strip()]

    @property
    def is_usable(self) -> bool:
        """Enough to hold a character together across shots."""
        return bool(self.character_id) and not self.missing_identity \
            and bool(self.poses) and bool(self.expressions)

    def as_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "identity": dict(self.identity),
            "missing_identity": self.missing_identity,
            "poses": [p.as_dict() for p in self.poses],
            "expressions": [e.as_dict() for e in self.expressions],
            "palette": list(self.palette),
            "forbidden": list(self.forbidden),
            "is_usable": self.is_usable,
            "notes": list(self.notes),
        }


def load_bible(raw: dict | None) -> CharacterBible:
    """Read a bible from channel configuration. Never invents one."""
    raw = raw if isinstance(raw, dict) else {}
    bible = CharacterBible(
        character_id=str(raw.get("character_id") or raw.get("id") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        identity={k: str(v or "").strip()
                  for k, v in (raw.get("identity") or {}).items()}
        if isinstance(raw.get("identity"), dict) else {},
        palette=_strings(raw.get("palette")),
        forbidden=[f.strip().lower() for f in _strings(raw.get("forbidden"))],
    )

    seen_poses: set[str] = set()
    for entry in _entries(raw.get("poses")):
        pose_id = str(entry.get("id") or entry.get("pose_id") or "").strip()
        if not pose_id or pose_id in seen_poses:
            if pose_id:
                bible.notes.append(f"pose '{pose_id}' declared more than once")
            continue
        seen_poses.add(pose_id)
        bible.poses.append(Pose(
            pose_id=pose_id, description=str(entry.get("description") or ""),
            tags=tuple(tag.strip().lower() for tag in _strings(entry.get("tags")))))

    seen_expressions: set[str] = set()
    for entry in _entries(raw.get("expressions")):
        expression_id = str(entry.get("id") or entry.get("expression_id") or "").strip()
        if not expression_id or expression_id in seen_expressions:
            if expression_id:
                bible.notes.append(
                    f"expression '{expression_id}' declared more than once")
            continue
        seen_expressions.add(expression_id)
        # `_num`, not `float`: `min(max(nan, 0.0), 1.0)` is `nan`, and a NaN
        # intensity reached `as_dict()` and broke strict JSON.
        intensity = _num(entry.get("intensity"))
        intensity = 0.5 if intensity is None else intensity
        bible.expressions.append(Expression(
            expression_id=expression_id,
            description=str(entry.get("description") or ""),
            intensity=min(max(intensity, 0.0), 1.0)))

    if not bible.character_id:
        bible.notes.append(
            "no character_id — a bible without one cannot be referenced by a "
            "scene, so continuity cannot be checked at all")
    if bible.missing_identity:
        bible.notes.append(
            "identity traits not pinned: " + ", ".join(bible.missing_identity)
            + ". These are what make the character the same character after a cut")
    return bible


@dataclass
class ContinuityIssue:
    scene_index: int
    kind: str
    detail: str

    def as_dict(self) -> dict:
        return {"scene_index": self.scene_index, "kind": self.kind,
                "detail": self.detail}


def check_continuity(scenes: list[dict], bible: CharacterBible
                     ) -> list[ContinuityIssue]:
    """Name every place a storyboard leaves the bible.

    Issues, not a score. "Continuity: 0.83" tells an operator nothing they can
    act on; "scene 12 asks for a pose that does not exist" tells them exactly
    what to draw or rewrite."""
    issues: list[ContinuityIssue] = []
    if bible is None:
        return [ContinuityIssue(-1, "no_bible", "no character bible was supplied")]
    if not bible.is_usable:
        return [ContinuityIssue(
            -1, "no_usable_bible",
            "the character bible is incomplete, so nothing can be checked "
            "against it: " + (", ".join(bible.missing_identity) or "no poses or "
                              "expressions declared"))]

    for index, scene in enumerate(scenes or []):
        if not isinstance(scene, dict):
            issues.append(ContinuityIssue(index, "unreadable_scene",
                                          "scene is not a mapping"))
            continue
        character = str(scene.get("character_id") or "").strip()
        if character and character != bible.character_id:
            issues.append(ContinuityIssue(
                index, "wrong_character",
                f"scene names character '{character}', bible describes "
                f"'{bible.character_id}'"))
        pose = str(scene.get("pose") or "").strip()
        if pose and pose not in bible.pose_ids:
            issues.append(ContinuityIssue(
                index, "unknown_pose",
                f"pose '{pose}' is not in the library "
                f"({', '.join(sorted(bible.pose_ids)) or 'empty'})"))
        expression = str(scene.get("expression") or "").strip()
        if expression and expression not in bible.expression_ids:
            issues.append(ContinuityIssue(
                index, "unknown_expression",
                f"expression '{expression}' is not in the library"))
        text = " ".join(str(scene.get(k) or "") for k in
                        ("narration", "visual", "image_prompt")).lower()
        for banned in bible.forbidden:
            if banned and banned in text:
                issues.append(ContinuityIssue(
                    index, "forbidden_element",
                    f"scene mentions '{banned}', which the bible forbids"))
    return issues


def readiness() -> dict:
    """What this package can and cannot do — in the system's own vocabulary.

    Published so nobody reads `omnicast.animation` as a working animation
    pipeline. §7.1 asked for a subsystem; this is its specification plus the
    computable parts, and the parts that need a renderer say so."""
    return {
        "parts": dict(SUBSYSTEM_PARTS),
        "unbuilt": list(UNBUILT_PARTS),
        "renders_frames": False,
        "status": MISSING if UNBUILT_PARTS else MEASURED,
        "note": (
            "Generating AI images and crossfading them is not animation — the "
            "review says so explicitly. This package specifies the subsystem and "
            "implements the parts that are pure computation. Until a renderer "
            "exists, `production_router` continues to refuse ANIMATION for any "
            "channel that has not declared the capability, and to record the "
            "substitution it made instead."
        ),
    }
