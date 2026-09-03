"""Storyboard types — the cast, the shots, and the reference bindings.

WHY THIS EXISTS. Before this package a scene was a flat record: one free-text
`image_prompt` and, at best, a channel-wide anchor set attached to every call
(`media/character_anchor.py`). That buys one thing — "this channel has a face" —
and cannot express the three facts a drawn scene actually needs:

  1. WHO/WHAT is in this shot (a cast, per shot, by stable id);
  2. WHICH reference image speaks for each of them (per entity, not per channel);
  3. WHAT that reference is allowed to control (identity only? environment only?).

(3) is the one people skip. Attaching a portrait and a location photo to the same
call without saying which does what lets the portrait's lighting and background
bleed into the scene — the model has no way to know the face image was about the
face. `RefRole` + the "controls X only; ignore Y" clause in `binding.py` is the
fix, and it is why `EntityImage` carries a role at all.

NAMES ARE VERBATIM. `Entity.name` is never normalized, translated, or
re-spaced. `normalized_name` exists ONLY as a lookup key for merge/dedup. The
failure this prevents: a shot says "Bà Tư (già)" while the cast says "Bà Tư
(gia)" and the binder silently fails to substitute, so the prompt ships an
unbound name and the reference image points at nothing.

Everything here is frozen (house style, `OmnicastSchema`): stages return new
objects via `model_copy(update=…)` so a gate can always diff what a repair
changed.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from omnicast.models.schemas import OmnicastSchema


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

class EntityKind(str, Enum):
    """What a cast member is.

    Split deliberately. A character's FACE and a character's CLOTHES drift
    independently — the same person in a different coat is still the same
    person, and conflating them means one reference image has to carry both
    and does neither well. Locations and props get their own entries for the
    same reason: a recurring kitchen should be the same kitchen in shot 12.
    """

    CHARACTER = "character"
    LOCATION = "location"
    PROP = "prop"
    COSTUME = "costume"


class RefRole(str, Enum):
    """What a reference image is allowed to control.

    From seedance-2.0's reference-transfer contract (MIT): every reference is
    bound to exactly one role, and the prompt states what must NOT transfer.
    Without this, an identity portrait donates its background and its lighting.
    """

    IDENTITY = "identity"        # face, build, hair — who this is
    WARDROBE = "wardrobe"        # garment cut/colour, worn by a character
    PROP = "prop"                # object geometry and markings
    ENVIRONMENT = "environment"  # place, architecture, set dressing
    STYLE = "style"              # rendering look only — never subject matter
    POSE = "pose"                # body arrangement only — never identity


#: What each role must NOT leak into the frame. Read by `binding.py` to write
#: the ignore-clause. Keep every role represented: a role with no ignore list
#: silently degrades to "reference controls everything".
ROLE_IGNORES: dict[RefRole, tuple[str, ...]] = {
    RefRole.IDENTITY: ("background", "environment", "lighting", "camera framing", "pose"),
    RefRole.WARDROBE: ("face", "identity", "background", "lighting", "pose"),
    RefRole.PROP: ("background", "environment", "lighting", "any person"),
    RefRole.ENVIRONMENT: ("any person", "identity", "wardrobe", "props in frame"),
    RefRole.STYLE: ("subject matter", "identity", "composition", "environment"),
    RefRole.POSE: ("identity", "face", "wardrobe", "background", "lighting"),
}

#: Default role per entity kind — what the entity's own reference sheet is for.
DEFAULT_ROLE: dict[EntityKind, RefRole] = {
    EntityKind.CHARACTER: RefRole.IDENTITY,
    EntityKind.COSTUME: RefRole.WARDROBE,
    EntityKind.PROP: RefRole.PROP,
    EntityKind.LOCATION: RefRole.ENVIRONMENT,
}


class CameraShot(str, Enum):
    """Shot size. A closed vocabulary, not prose.

    Free text ("a close shot of her face, fairly tight") gives the image model
    a different framing every call. An enum gives the SAME framing every call
    and lets a gate check that a 12-shot sequence is not 12 medium shots.
    """

    ECU = "ECU"    # extreme close-up
    CU = "CU"      # close-up
    MCU = "MCU"    # medium close-up
    MS = "MS"      # medium shot
    MLS = "MLS"    # medium long shot
    LS = "LS"      # long shot
    ELS = "ELS"    # extreme long shot


class Angle(str, Enum):
    EYE_LEVEL = "EYE_LEVEL"
    HIGH_ANGLE = "HIGH_ANGLE"
    LOW_ANGLE = "LOW_ANGLE"
    BIRD_EYE = "BIRD_EYE"
    DUTCH = "DUTCH"
    OVER_SHOULDER = "OVER_SHOULDER"


class Movement(str, Enum):
    STATIC = "STATIC"
    PAN = "PAN"
    TILT = "TILT"
    DOLLY_IN = "DOLLY_IN"
    DOLLY_OUT = "DOLLY_OUT"
    TRACK = "TRACK"
    CRANE = "CRANE"
    HANDHELD = "HANDHELD"
    STEADICAM = "STEADICAM"
    ZOOM_IN = "ZOOM_IN"
    ZOOM_OUT = "ZOOM_OUT"


#: Human-readable expansion injected into prompts. The enum is the contract;
#: this is what the image model actually reads.
SHOT_GLOSS: dict[CameraShot, str] = {
    CameraShot.ECU: "extreme close-up, detail fills the frame",
    CameraShot.CU: "close-up, head and shoulders",
    CameraShot.MCU: "medium close-up, chest up",
    CameraShot.MS: "medium shot, waist up",
    CameraShot.MLS: "medium long shot, knees up",
    CameraShot.LS: "long shot, full figure with surroundings",
    CameraShot.ELS: "extreme long shot, figure small within the landscape",
}

ANGLE_GLOSS: dict[Angle, str] = {
    Angle.EYE_LEVEL: "eye-level camera",
    Angle.HIGH_ANGLE: "high angle looking down",
    Angle.LOW_ANGLE: "low angle looking up",
    Angle.BIRD_EYE: "overhead bird's-eye view",
    Angle.DUTCH: "tilted dutch angle",
    Angle.OVER_SHOULDER: "over-the-shoulder framing",
}

MOVEMENT_GLOSS: dict[Movement, str] = {
    Movement.STATIC: "locked-off static camera",
    Movement.PAN: "horizontal pan",
    Movement.TILT: "vertical tilt",
    Movement.DOLLY_IN: "dolly pushing in",
    Movement.DOLLY_OUT: "dolly pulling out",
    Movement.TRACK: "tracking alongside the subject",
    Movement.CRANE: "craning camera move",
    Movement.HANDHELD: "handheld, slight instability",
    Movement.STEADICAM: "smooth steadicam glide",
    Movement.ZOOM_IN: "lens zooming in",
    Movement.ZOOM_OUT: "lens zooming out",
}


class ScreenDirection(str, Enum):
    """Which way the subject travels across frame — the 180-degree rule.

    The single most visible continuity error in cut film: a character walking
    left-to-right in one shot and right-to-left in the next reads to a viewer
    as turning around, even when nothing in the story says so. It is also the
    error a text-to-image model makes constantly, because nothing in a
    per-shot prompt carries the axis from the previous shot.

    Listed in seedance's failure atlas as "Screen direction flips → state
    screen direction or declare axis reset".
    """

    LEFT_TO_RIGHT = "left_to_right"
    RIGHT_TO_LEFT = "right_to_left"
    TOWARD_CAMERA = "toward_camera"
    AWAY_FROM_CAMERA = "away_from_camera"
    NEUTRAL = "neutral"          # static subject, no axis to break
    UNSET = "unset"              # nobody declared one — reported, not assumed


#: Pairs that read as a flipped axis when they sit next to each other in the
#: same place. Toward/away is a legitimate cut on the same axis, so it is not
#: here; only the lateral reversal is.
OPPOSITE_DIRECTIONS: dict[ScreenDirection, ScreenDirection] = {
    ScreenDirection.LEFT_TO_RIGHT: ScreenDirection.RIGHT_TO_LEFT,
    ScreenDirection.RIGHT_TO_LEFT: ScreenDirection.LEFT_TO_RIGHT,
}


class FrameType(str, Enum):
    """Which moment of the shot a still depicts.

    FIRST and LAST are not decoration — they are what an image-to-video model
    interpolates between, and what the next shot inherits its opening state
    from (`Shot.planned_start_state`). KEY is for shots rendered as a single
    still.
    """

    FIRST = "first"
    KEY = "key"
    LAST = "last"


class ImageSource(str, Enum):
    OPERATOR = "operator"      # a human supplied this file — highest authority
    GENERATED = "generated"    # produced from the entity's description
    CACHED = "cached"          # reused from an earlier run of this entity


class BoardStatus(str, Enum):
    """Where a storyboard is in the approval flow.

    CAST_PENDING is the barrier the operator chose: nothing downstream spends
    image credit until a human has confirmed the cast and its reference sheet,
    because a wrong reference image is wrong in every single frame.
    """

    DRAFT = "draft"                  # extracted, not yet merged/validated
    CAST_PENDING = "cast_pending"    # waiting on human approval of cast + refs
    CAST_APPROVED = "cast_approved"  # refs locked; frame generation may run
    FRAMES_READY = "frames_ready"    # frames generated, gate not yet run
    BLOCKED = "blocked"              # continuity gate found hard failures
    APPROVED = "approved"            # cleared for render
    RENDERED = "rendered"


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Lookup key for merge/dedup. NEVER a replacement for `Entity.name`.

    Folds the drift that makes two spellings of one character look like two
    characters: case, full-width/half-width brackets, and runs of whitespace.
    Jellyfish's extractor prompt has to beg the model not to produce these;
    doing it deterministically here means we do not have to trust that.
    """
    text = (name or "").strip().lower()
    for wide, narrow in (("（", "("), ("）", ")"), ("［", "["), ("］", "]"),
                         ("　", " "), ("，", ","), ("、", ",")):
        text = text.replace(wide, narrow)
    return " ".join(text.split())


class EntityImage(OmnicastSchema):
    """One reference image for one entity, bound to one role.

    `view` is free text ("front", "three-quarter", "full body", "interior wide")
    because useful views differ by kind — a prop has no three-quarter portrait.
    `approved` is what the cast barrier actually gates on.
    """

    image_id: str
    entity_id: str
    path: str
    view: str = ""
    role: RefRole = RefRole.IDENTITY
    source: ImageSource = ImageSource.GENERATED
    approved: bool = False
    prompt_used: str = ""
    created_at: str = ""


class Entity(OmnicastSchema):
    """A cast member: a character, place, prop, or costume.

    `aliases` is how the same person survives being called "the driver" in one
    shot and "Minh" in another — the merger folds both into one entity and the
    binder can substitute either spelling.
    """

    entity_id: str
    board_id: str
    kind: EntityKind
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    traits: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    # Characters may pin a costume; props may be owned by a character. Both are
    # entity ids, both optional — a location owns neither.
    costume_id: str | None = None
    owner_id: str | None = None
    view_count: int = Field(default=3, ge=1, le=8)
    images: list[EntityImage] = Field(default_factory=list)
    #: Set by the merger when two extractions disagree about this entity.
    #: A non-empty list blocks the cast barrier — an operator must resolve it.
    conflicts: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        # A blank name cannot be bound to a token, so it can never reach an
        # image. Fail at construction rather than shipping a silent no-op.
        if not (v or "").strip():
            raise ValueError("entity name must not be blank")
        return v

    @property
    def normalized(self) -> str:
        return normalize_name(self.name)

    @property
    def approved_images(self) -> list[EntityImage]:
        return [im for im in self.images if im.approved]

    @property
    def default_role(self) -> RefRole:
        return DEFAULT_ROLE.get(self.kind, RefRole.IDENTITY)

    @property
    def is_ready(self) -> bool:
        """Enough to hold this entity together across shots."""
        return bool(self.approved_images) and not self.conflicts

    def all_spellings(self) -> list[str]:
        """Every string that should be substituted for this entity's token.

        Longest first — see `binding.py`: replacing "Minh" before "Minh Anh"
        turns "Minh Anh" into "[IMAGE 1] Anh".
        """
        out = [self.name, *[a for a in self.aliases if a.strip()]]
        seen: set[str] = set()
        uniq: list[str] = []
        for s in out:
            key = normalize_name(s)
            if key and key not in seen:
                seen.add(key)
                uniq.append(s)
        return sorted(uniq, key=len, reverse=True)


class ShotEntityRef(OmnicastSchema):
    """An entity appearing in a shot, with the role its reference plays there.

    `role` overrides the entity's default: a character normally donates
    IDENTITY, but a shot that reuses a character sheet purely for a pose match
    says POSE and the ignore-clause changes accordingly.
    """

    entity_id: str
    index: int = 0
    role: RefRole | None = None
    note: str = ""


class Shot(OmnicastSchema):
    """One camera setup.

    The continuity chain (`parent_shot_id`, `planned_start_state`,
    `observed_end_state`) is seedance's boundary contract: a successor's
    opening state must be justified by its predecessor's observed ending, not
    by whatever the model felt like. `veo_pipeline.py` already carries a tail
    frame forward blindly; these fields are what make that carry checkable.
    """

    shot_id: str
    board_id: str
    index: int
    title: str = ""
    script_excerpt: str = ""
    voiceover: str = ""
    location_id: str | None = None
    cast: list[ShotEntityRef] = Field(default_factory=list)
    camera_shot: CameraShot = CameraShot.MS
    angle: Angle = Angle.EYE_LEVEL
    movement: Movement = Movement.STATIC
    duration_s: float = 0.0
    action_beats: list[str] = Field(default_factory=list)
    mood: str = ""
    transition: str = "cut"
    # --- Continuity anchors -------------------------------------------
    # Everything below is an anchor the failure atlas names as a top cause of
    # incoherent consecutive shots. They exist as FIELDS rather than as prose
    # inside the prompt because a gate can only compare what it can read: an
    # axis buried in a sentence is an axis nothing can check.
    screen_direction: ScreenDirection = ScreenDirection.UNSET
    eyeline: str = ""            # where the subject looks, for reverse matching
    light_key: str = ""          # key direction + practical sources
    time_of_day: str = ""
    #: Motion still running when the shot ends. A successor that drops it makes
    #: the movement stop dead on the cut ("Open motion stops" in the atlas).
    motion_vector: str = ""
    sound_state: str = ""

    # Continuity chain
    parent_shot_id: str | None = None
    planned_start_state: str = ""
    observed_end_state: str = ""
    # --- Event density (scope firewall) --------------------------------
    #: Beats already performed by an earlier shot. Replaying one is the
    #: "Action restarts" failure; naming them lets the gate catch it.
    beats_completed: list[str] = Field(default_factory=list)
    #: Beats belonging to a LATER shot. Story context may inform this shot's
    #: mood, but performing a reserved beat early spoils the sequence — the
    #: "Future event appears early" failure.
    beats_reserved: list[str] = Field(default_factory=list)
    #: Changes the writer/director declared on purpose. The continuity gate
    #: warns about drift UNLESS an axis is named here — "the coat is gone
    #: because she took it off" is continuity, not a defect.
    declared_changes: list[str] = Field(default_factory=list)

    def entity_ids(self) -> list[str]:
        ids = [c.entity_id for c in sorted(self.cast, key=lambda c: c.index)]
        if self.location_id and self.location_id not in ids:
            ids.append(self.location_id)
        return ids


class RefMapping(OmnicastSchema):
    """One row of the image-content table shipped with a frame prompt.

    This is the artifact that makes reference conditioning auditable: it says
    exactly which file was attached as `[IMAGE 2]` and which entity it stood
    for. When a face comes out wrong, this is what you read first.
    """

    token: str
    entity_id: str
    name: str
    kind: EntityKind
    role: RefRole
    path: str


class Frame(OmnicastSchema):
    """A still to be generated for a shot.

    Both prompts are kept. `base_prompt` is written in ENTITY NAMES and is what
    a human reads and edits; `rendered_prompt` is the token-substituted text
    actually sent to the model. Keeping only the rendered form would make the
    board unreadable; keeping only the base would make the failure unauditable.
    """

    frame_id: str
    shot_id: str
    frame_type: FrameType
    base_prompt: str = ""
    rendered_prompt: str = ""
    negative_prompt: str = ""
    mappings: list[RefMapping] = Field(default_factory=list)
    image_path: str = ""
    approved: bool = False
    attempts: int = 0

    @property
    def reference_paths(self) -> list[str]:
        """Files to attach, in token order. Order is the binding — a shuffled
        list silently re-points every token in the prompt."""
        return [m.path for m in self.mappings]


class Storyboard(OmnicastSchema):
    """A script turned into a cast plus an ordered shot list."""

    board_id: str
    channel_id: str
    product_slug: str = ""
    title: str = ""
    status: BoardStatus = BoardStatus.DRAFT
    script_hash: str = ""
    style_prompt: str = ""
    negative_prompt: str = ""
    entities: list[Entity] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)
    frames: list[Frame] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: str = ""
    approved_at: str = ""

    def entity(self, entity_id: str) -> Entity | None:
        for e in self.entities:
            if e.entity_id == entity_id:
                return e
        return None

    def by_name(self, name: str) -> Entity | None:
        key = normalize_name(name)
        for e in self.entities:
            if e.normalized == key or key in {normalize_name(a) for a in e.aliases}:
                return e
        return None

    def shot(self, shot_id: str) -> Shot | None:
        for s in self.shots:
            if s.shot_id == shot_id:
                return s
        return None

    def frames_for(self, shot_id: str) -> list[Frame]:
        return [f for f in self.frames if f.shot_id == shot_id]

    @property
    def cast_ready(self) -> bool:
        """Every entity that any shot references has an approved image.

        Entities nobody uses do not block — an over-eager extractor inventing a
        prop that never appears should not stall a render.
        """
        used = {eid for s in self.shots for eid in s.entity_ids()}
        if not used:
            return False
        for eid in used:
            e = self.entity(eid)
            if e is None or not e.is_ready:
                return False
        return True

    def unready_entities(self) -> list[Entity]:
        used = {eid for s in self.shots for eid in s.entity_ids()}
        return [e for e in self.entities if e.entity_id in used and not e.is_ready]
