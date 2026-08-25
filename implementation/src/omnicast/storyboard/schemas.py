"""Wire schemas for the LLM stages — draft shapes, not the stored model.

Kept separate from `models.py` on purpose. The stored model carries ids,
approval state and reference bindings; the LLM never sees or invents any of
those. It works purely in NAMES, and `extract.reconcile_draft` is what turns
names into a registry with stable ids. Letting a model emit `entity_id` was
Jellyfish's explicit prohibition and it is worth keeping: an id the model made
up is an id nothing else in the system can resolve.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

#: Keys a model reaches for instead of `index`. Observed live on the first
#: paid run: DeepSeek returned `shot_number` for every shot and the whole
#: extraction failed validation — nine identical "Field required" errors after
#: the call was already paid for.
_INDEX_ALIASES = ("index", "shot_number", "shot_index", "number", "n", "order",
                  "idx", "id")

#: Likewise for the kind of a cast member.
_KIND_ALIASES = ("kind", "type", "entity_type", "category", "role")

#: Fields that are structure, not physical description. Everything else on an
#: entity record gets folded into `description` when none was supplied.
_NOT_A_TRAIT = frozenset({
    "name", "kind", "type", "entity_type", "category", "role", "description",
    "aliases", "costume_name", "owner_name", "id", "entity_id", "tags",
    "prompt_template_id", "view_count", "shots", "appearances",
})

#: Prose the model writes instead of a screen-direction token, mapped to one.
#: Observed live: `"screen_direction": "Minh faces right (toward window)"`.
#: Order matters — the first phrase that matches wins, so the more specific
#: two-word forms are listed before the bare ones.
_DIRECTION_PHRASES: tuple[tuple[str, str], ...] = (
    ("left_to_right", "left_to_right"),
    ("right_to_left", "right_to_left"),
    ("left to right", "left_to_right"),
    ("right to left", "right_to_left"),
    ("toward camera", "toward_camera"),
    ("towards camera", "toward_camera"),
    ("into camera", "toward_camera"),
    ("away from camera", "away_from_camera"),
    ("toward_camera", "toward_camera"),
    ("away_from_camera", "away_from_camera"),
    ("faces right", "left_to_right"),
    ("facing right", "left_to_right"),
    ("moves right", "left_to_right"),
    ("screen right", "left_to_right"),
    ("faces left", "right_to_left"),
    ("facing left", "right_to_left"),
    ("moves left", "right_to_left"),
    ("screen left", "right_to_left"),
    ("neutral", "neutral"),
    ("static", "neutral"),
)


def _direction_token(raw: Any) -> str:
    """A `ScreenDirection` value from whatever the model wrote.

    Returns "unset" rather than guessing when nothing matches: an axis the
    system invented is worse than an axis it admits it does not know, because
    the 180-degree check would then fire on fiction.
    """
    text = str(raw or "").strip().lower()
    if not text:
        return "unset"
    for phrase, token in _DIRECTION_PHRASES:
        if phrase in text:
            return token
    return "unset"


def _first_key(data: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _as_entries(value: Any, name_key: str = "name") -> Any:
    """Accept a mapping of name→fields where a list of records was specified.

    A model that has just been told "output a global dictionary of entities"
    quite reasonably emits a JSON object keyed by name. Rejecting that costs a
    paid call and returns nothing; folding the key back in as the name costs
    nothing and preserves the model's intent exactly.
    """
    if not isinstance(value, dict):
        return value
    out = []
    for key, fields in value.items():
        if isinstance(fields, dict):
            record = dict(fields)
            record.setdefault(name_key, key)
            out.append(record)
        else:
            out.append({name_key: key})
    return out


class DraftEntity(BaseModel):
    """A cast member as the extractor names it."""

    name: str = Field(description="Exact name as written in the script. Never normalized.")
    kind: str = Field(description="character | location | prop | costume")
    description: str = Field(
        default="",
        description="Physical description sufficient to draw it consistently: "
                    "build, age read, hair, defining features. Not personality.")
    aliases: list[str] = Field(
        default_factory=list,
        description="Other ways the script refers to this same entity "
                    "('the driver', 'her brother'). Only add one when you are "
                    "certain it is the SAME entity.")
    costume_name: str | None = Field(
        default=None, description="For characters: name of their costume entity.")
    owner_name: str | None = Field(
        default=None, description="For props: name of the character who owns it.")

    @model_validator(mode="before")
    @classmethod
    def _accept_kind_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        record = dict(data)
        if not record.get("kind"):
            alias = _first_key(record, _KIND_ALIASES)
            if alias is not None:
                record["kind"] = alias

        # Compose a description from loose trait fields when the model split
        # the physical description across its own keys instead of writing one
        # string. Observed live: entities came back as
        # {type, approx_age, build, hair, face, defining_marks} with no
        # `description` at all — which would have produced reference sheets
        # generated from a bare name, i.e. a different person every view.
        if not str(record.get("description") or "").strip():
            traits = []
            for key, value in record.items():
                if key in _NOT_A_TRAIT or value in (None, "", [], {}):
                    continue
                if isinstance(value, (list, tuple)):
                    value = ", ".join(str(v) for v in value if str(v).strip())
                if not isinstance(value, (str, int, float)) or not str(value).strip():
                    continue
                traits.append(f"{str(key).replace('_', ' ')}: {value}")
            if traits:
                record["description"] = "; ".join(traits)
        return record


class DraftShot(BaseModel):
    """One camera setup as the extractor plans it."""

    index: int
    title: str = Field(description="One line describing the picture, not the scene name.")
    script_excerpt: str = Field(default="", description="The lines this shot covers.")
    voiceover: str = Field(default="", description="Narration spoken over this shot.")
    location_name: str | None = Field(
        default=None, description="Must be a name from the location entities.")
    character_names: list[str] = Field(default_factory=list)
    prop_names: list[str] = Field(default_factory=list)
    costume_names: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(
        default_factory=list,
        description="Everything visible in this shot, if you did not split it "
                    "by kind. Each name is routed to its kind by looking it up "
                    "in the cast, so it must still be a cast name.")
    camera_shot: str = Field(default="MS", description="ECU|CU|MCU|MS|MLS|LS|ELS")
    angle: str = Field(
        default="EYE_LEVEL",
        description="EYE_LEVEL|HIGH_ANGLE|LOW_ANGLE|BIRD_EYE|DUTCH|OVER_SHOULDER")
    movement: str = Field(
        default="STATIC",
        description="STATIC|PAN|TILT|DOLLY_IN|DOLLY_OUT|TRACK|CRANE|HANDHELD|"
                    "STEADICAM|ZOOM_IN|ZOOM_OUT")
    duration_s: float = Field(default=0.0)
    action_beats: list[str] = Field(
        default_factory=list,
        description="2-4 beats in time order. One action or state change each.")
    mood: str = Field(default="")
    transition: str = Field(default="cut")
    screen_direction: str = Field(
        default="unset",
        description="left_to_right | right_to_left | toward_camera | "
                    "away_from_camera | neutral. Which way the subject travels "
                    "across frame. Keep it stable within one location: "
                    "reversing it reads as the subject turning around.")
    eyeline: str = Field(
        default="", description="Where the subject looks, so reverse shots match.")
    light_key: str = Field(
        default="", description="Key light direction and practical sources.")
    time_of_day: str = Field(default="")
    motion_vector: str = Field(
        default="", description="Motion still running as the shot ends. The "
                                "next shot must inherit it or the movement "
                                "stops dead on the cut.")
    sound_state: str = Field(default="")
    planned_start_state: str = Field(
        default="", description="The state this shot opens in, inherited from "
                                "the previous shot's ending.")
    observed_end_state: str = Field(
        default="", description="The state this shot leaves the story in.")
    beats_completed: list[str] = Field(
        default_factory=list,
        description="Beats an EARLIER shot already performed. This shot must "
                    "not replay them.")
    beats_reserved: list[str] = Field(
        default_factory=list,
        description="Beats belonging to a LATER shot. This shot must not "
                    "perform them, even if they explain motivation.")

    @model_validator(mode="before")
    @classmethod
    def _accept_shot_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        record = dict(data)

        if record.get("index") is None:
            alias = _first_key(record, _INDEX_ALIASES)
            try:
                record["index"] = int(alias)
            except (TypeError, ValueError):
                # `_ordinal` is stamped by ExtractionDraft from array position.
                # Falling back to 0 for every shot — as an earlier version did
                # — collapsed a nine-shot board onto one index and the
                # renumbering notes were the only trace.
                record["index"] = int(record.get("_ordinal") or 0)
        record.pop("_ordinal", None)

        record["screen_direction"] = _direction_token(
            record.get("screen_direction"))

        # A combined visible-elements list under any of its usual names.
        if not record.get("subjects"):
            combined = _first_key(record, ("subjects", "entities", "elements",
                                           "visible", "cast"))
            if isinstance(combined, list):
                record["subjects"] = [str(v) for v in combined if str(v).strip()]

        if not record.get("script_excerpt"):
            summary = _first_key(record, ("script_excerpt", "action_summary",
                                          "action", "summary", "description"))
            if isinstance(summary, str):
                record["script_excerpt"] = summary

        if not record.get("action_beats"):
            beats = _first_key(record, ("action_beats", "beats", "actions"))
            if isinstance(beats, list):
                record["action_beats"] = [str(b) for b in beats if str(b).strip()]
        return record
    declared_changes: list[str] = Field(
        default_factory=list,
        description="Continuity changes made ON PURPOSE ('she takes the coat "
                    "off'). Anything not declared here is treated as drift.")


class ExtractionDraft(BaseModel):
    """Global cast plus the shot list that references it, by name only."""

    entities: list[DraftEntity] = Field(default_factory=list)
    shots: list[DraftShot] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_mapping_shapes(cls, data: Any) -> Any:
        """Fold the shapes a model actually emits into the one specified.

        Deliberately permissive at the envelope and strict everywhere after.
        Rejecting a well-reasoned extraction because it arrived as an object
        instead of an array throws away a paid call and gains nothing: the
        content is right, only the container differs. What must NOT be
        forgiving is anything downstream of here — a name that does not resolve
        or a beat that leaks is still a hard failure.
        """
        if not isinstance(data, dict):
            return data
        record = dict(data)
        for key, name_key in (("entities", "name"), ("characters", "name"),
                              ("shots", "title")):
            if key in record:
                record[key] = _as_entries(record[key], name_key)
        # Some replies split the cast by kind instead of tagging each entry.
        buckets = {"characters": "character", "locations": "location",
                   "scenes": "location", "props": "prop", "costumes": "costume"}
        collected: list = list(record.get("entities") or [])
        for bucket, kind in buckets.items():
            entries = record.pop(bucket, None)
            if not entries:
                continue
            for entry in _as_entries(entries, "name") or []:
                if isinstance(entry, dict):
                    entry = dict(entry)
                    entry.setdefault("kind", kind)
                    collected.append(entry)
        if collected:
            record["entities"] = collected

        # Array position is the shot order the model actually intended when it
        # omitted an index entirely — which is what it does most of the time,
        # because a JSON array already carries order.
        shots = record.get("shots")
        if isinstance(shots, list):
            record["shots"] = [
                {**s, "_ordinal": i} if isinstance(s, dict) else s
                for i, s in enumerate(shots)
            ]
        return record


class MergeProposal(BaseModel):
    """One claim that several names denote the same entity."""

    canonical_name: str = Field(description="The name to keep, exactly as spelled.")
    duplicate_names: list[str] = Field(
        default_factory=list, description="Names that denote the same entity.")
    kind: str = Field(default="character")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = Field(
        default="",
        description="The line that makes this identification certain. Required "
                    "— a merge without evidence is a guess that silently "
                    "deletes a character.")


class MergeResult(BaseModel):
    merges: list[MergeProposal] = Field(default_factory=list)
    conflicts: list[str] = Field(
        default_factory=list,
        description="Cases you could NOT decide. Prefer this over guessing.")
