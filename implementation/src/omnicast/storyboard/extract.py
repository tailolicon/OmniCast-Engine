"""Script → cast registry + shot list.

TWO LAYERS, AND THE SECOND ONE IS THE PRODUCT.

The LLM proposes (`StoryboardExtractorAgent`). Then `reconcile_draft` — pure,
deterministic, no model — turns the proposal into something the rest of the
system can trust:

  * every name a shot references EXISTS in the registry (auto-created if the
    model forgot, never silently dropped);
  * duplicate spellings collapse to one entity;
  * camera vocabulary is coerced into the enums or reported;
  * ids are derived from content, not invented.

Jellyfish's extractor prompt spends a dozen lines pleading with the model to do
these things ("禁止…禁止…必须补齐"). Pleading works most of the time, which is
the problem: the failure is rare, silent, and produces a prompt naming a
character that has no reference image — exactly the drift this package exists
to stop. So the prompt still asks, and the code still checks.

STABLE IDS ARE A FEATURE. `entity_id` is a hash of (board, kind, folded name),
so re-extracting the same script yields the same ids — an operator's approved
reference images survive a re-run instead of being orphaned by fresh uuids.
"""

from __future__ import annotations

import hashlib
import json

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.storyboard.models import (
    Angle,
    BoardStatus,
    CameraShot,
    Entity,
    EntityKind,
    Movement,
    ScreenDirection,
    Shot,
    ShotEntityRef,
    Storyboard,
    normalize_name,
)
from omnicast.storyboard.schemas import DraftShot, ExtractionDraft

logger = structlog.get_logger()


def _sid(board_id: str, *parts: str) -> str:
    raw = "|".join([board_id, *parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def entity_id_for(board_id: str, kind: EntityKind, name: str) -> str:
    return f"e_{_sid(board_id, kind.value, normalize_name(name))}"


def shot_id_for(board_id: str, index: int) -> str:
    return f"s_{_sid(board_id, 'shot', str(index))}"


def script_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _coerce(enum_cls, raw: str, fallback):
    """Enum or fallback. Never raises — a bad camera token must not throw away
    a whole extraction, but the substitution is reported by the caller.

    Case is tried three ways because this repo's enums disagree on it:
    `CameraShot`/`Angle`/`Movement` hold UPPERCASE values while `EntityKind`
    holds lowercase. An earlier version upper-cased unconditionally, so every
    `costume`/`location`/`prop` silently failed to parse and fell back to
    `character` — the shot pass then re-created each one under its real kind
    and the registry came out with every entity duplicated.
    """
    text = str(raw or "").strip()
    for candidate in (text, text.upper(), text.lower()):
        try:
            return enum_cls(candidate)
        except (ValueError, AttributeError):
            continue
    return fallback


_ARTICLES = ("the ", "a ", "an ")


def _add_bare_noun_aliases(entities: list[Entity], notes: list[str]) -> list[Entity]:
    """Give article-led names an article-free alias so the binder can find them.

    Observed on the first paid run. The extractor named things "The ledger" and
    "The shophouse kitchen"; the frame writer then wrote the sentence a person
    would actually write — "the open ledger", "the kitchen table" — and the
    binder, matching the full name, found neither. The references were attached
    and labelled but no token appeared in the prose, so each one floated in the
    call with nothing anchoring it to a noun.

    Stripping the leading article is enough to close that gap ("ledger" DOES
    occur inside "the open ledger") and is safe because it is deterministic and
    reversible. Collisions are refused rather than resolved: if two cast
    members would end up answering to the same bare noun, neither gets it —
    binding the wrong entity is worse than binding none.
    """
    taken: dict[str, int] = {}
    for entity in entities:
        for spelling in entity.all_spellings():
            key = normalize_name(spelling)
            taken[key] = taken.get(key, 0) + 1

    candidates: dict[str, list[str]] = {}
    for entity in entities:
        lowered = entity.name.strip().lower()
        for article in _ARTICLES:
            if lowered.startswith(article):
                bare = entity.name.strip()[len(article):].strip()
                if bare and normalize_name(bare) != entity.normalized:
                    candidates.setdefault(normalize_name(bare), []).append(
                        entity.entity_id)
                break

    out: list[Entity] = []
    for entity in entities:
        lowered = entity.name.strip().lower()
        bare = ""
        for article in _ARTICLES:
            if lowered.startswith(article):
                bare = entity.name.strip()[len(article):].strip()
                break
        if not bare:
            out.append(entity)
            continue
        key = normalize_name(bare)
        if taken.get(key) or len(candidates.get(key, [])) > 1:
            notes.append(
                f"'{entity.name}' keeps no bare-noun alias: '{bare}' is already "
                f"another cast name or is claimed by more than one entity")
            out.append(entity)
            continue
        out.append(entity.model_copy(update={"aliases": [*entity.aliases, bare]}))
    return out


# --------------------------------------------------------------------------
# Deterministic reconciliation
# --------------------------------------------------------------------------

def reconcile_draft(
    draft: ExtractionDraft,
    *,
    board_id: str,
    channel_id: str,
    title: str = "",
    product_slug: str = "",
    style_prompt: str = "",
    negative_prompt: str = "",
    source_script: str = "",
) -> Storyboard:
    """Turn a name-only draft into a registry-backed board. Pure function."""
    notes: list[str] = []

    # ---- 1. fold the global entity list ---------------------------------
    by_key: dict[tuple[EntityKind, str], Entity] = {}
    pending_costume: dict[str, str] = {}   # entity_id -> costume NAME
    pending_owner: dict[str, str] = {}     # entity_id -> owner NAME

    def _ensure(name: str, kind: EntityKind, *, description: str = "",
                aliases: list[str] | None = None, invented: bool = False) -> Entity:
        clean = (name or "").strip()
        if not clean:
            return None  # type: ignore[return-value]
        key = (kind, normalize_name(clean))
        existing = by_key.get(key)
        if existing is not None:
            # Fold, do not replace: a second mention with a longer description
            # should enrich the entry, and its alternate spelling becomes an
            # alias so the binder can substitute either one.
            merged_aliases = list(existing.aliases)
            for extra in [*(aliases or []), clean]:
                if normalize_name(extra) != existing.normalized and \
                        extra not in merged_aliases and extra.strip():
                    merged_aliases.append(extra)
            by_key[key] = existing.model_copy(update={
                "description": existing.description or description,
                "aliases": merged_aliases,
            })
            return by_key[key]
        eid = entity_id_for(board_id, kind, clean)
        entity = Entity(entity_id=eid, board_id=board_id, kind=kind, name=clean,
                        description=description,
                        aliases=[a for a in (aliases or []) if a.strip()])
        by_key[key] = entity
        if invented:
            notes.append(
                f"auto-created {kind.value} '{clean}': a shot referenced it but "
                f"the extractor never declared it")
        return entity

    for d in draft.entities:
        kind = _coerce(EntityKind, (d.kind or "").lower(), None)
        if kind is None:
            # An unknown kind is not a reason to lose the cast member; a
            # character is the safest default because it is the kind whose
            # absence causes the worst artefact.
            kind = EntityKind.CHARACTER
            notes.append(f"entity '{d.name}': unknown kind '{d.kind}' → character")
        e = _ensure(d.name, kind, description=d.description, aliases=d.aliases)
        if e is None:
            continue
        if d.costume_name:
            pending_costume[e.entity_id] = d.costume_name
        if d.owner_name:
            pending_owner[e.entity_id] = d.owner_name

    # ---- 2. shots, resolving every reference against the registry --------
    shots: list[Shot] = []
    for position, d in enumerate(sorted(draft.shots, key=lambda s: s.index)):
        if d.index != position:
            notes.append(f"shot index {d.index} renumbered to {position} "
                         f"(indexes must be gapless for render order)")
        sid = shot_id_for(board_id, position)

        cam = _coerce(CameraShot, d.camera_shot, CameraShot.MS)
        ang = _coerce(Angle, d.angle, Angle.EYE_LEVEL)
        mov = _coerce(Movement, d.movement, Movement.STATIC)
        for label, raw, got, default in (("camera_shot", d.camera_shot, cam, CameraShot.MS),
                                         ("angle", d.angle, ang, Angle.EYE_LEVEL),
                                         ("movement", d.movement, mov, Movement.STATIC)):
            if got is default and str(raw).strip().upper() != default.value:
                notes.append(f"shot {position}: unknown {label} '{raw}' → "
                             f"{default.value}")

        cast: list[ShotEntityRef] = []
        order = 0
        for names, kind in ((d.character_names, EntityKind.CHARACTER),
                            (d.costume_names, EntityKind.COSTUME),
                            (d.prop_names, EntityKind.PROP)):
            for name in names or []:
                key = (kind, normalize_name(name))
                entity = by_key.get(key)
                if entity is None:
                    entity = _ensure(name, kind, invented=True)
                if entity is None:
                    continue
                if any(c.entity_id == entity.entity_id for c in cast):
                    continue
                cast.append(ShotEntityRef(entity_id=entity.entity_id, index=order))
                order += 1

        location_id = None
        if d.location_name:
            key = (EntityKind.LOCATION, normalize_name(d.location_name))
            loc = by_key.get(key) or _ensure(d.location_name, EntityKind.LOCATION,
                                             invented=True)
            location_id = loc.entity_id if loc else None

        # A combined `subjects` list, routed by looking each name up across
        # every kind. Models very often return one visible-elements list rather
        # than three by-kind lists; the first live run did exactly that, and
        # treating the list as unusable left every character in NO shot, which
        # in turn meant no character got a reference sheet at all.
        for name in d.subjects or []:
            folded = normalize_name(name)
            match = next(((k, e) for (k, n), e in by_key.items() if n == folded),
                         None)
            if match is None:
                # Unknown name: a character is the safest guess, because a
                # person with no sheet is the defect this package exists to
                # prevent, while a mislabelled prop only wastes one sheet.
                entity = _ensure(name, EntityKind.CHARACTER, invented=True)
                if entity is None:
                    continue
                kind = EntityKind.CHARACTER
            else:
                kind, entity = match
            if kind is EntityKind.LOCATION:
                # The place belongs in `location_id`, not the cast — binding it
                # twice would spend two reference slots on one room.
                if location_id is None:
                    location_id = entity.entity_id
                continue
            if any(c.entity_id == entity.entity_id for c in cast):
                continue
            cast.append(ShotEntityRef(entity_id=entity.entity_id, index=order))
            order += 1

        shots.append(Shot(
            shot_id=sid, board_id=board_id, index=position,
            title=d.title, script_excerpt=d.script_excerpt, voiceover=d.voiceover,
            location_id=location_id, cast=cast,
            camera_shot=cam, angle=ang, movement=mov,
            duration_s=max(0.0, d.duration_s or 0.0),
            action_beats=[b for b in (d.action_beats or []) if str(b).strip()],
            mood=d.mood, transition=d.transition or "cut",
            # Lineage is structural, not something the model should invent:
            # shot N continues shot N-1 unless a later pass says otherwise.
            parent_shot_id=shot_id_for(board_id, position - 1) if position else None,
            planned_start_state=d.planned_start_state,
            observed_end_state=d.observed_end_state,
            declared_changes=[c for c in (d.declared_changes or []) if str(c).strip()],
            screen_direction=_coerce(ScreenDirection, d.screen_direction,
                                     ScreenDirection.UNSET),
            eyeline=d.eyeline,
            light_key=d.light_key,
            time_of_day=d.time_of_day,
            motion_vector=d.motion_vector,
            sound_state=d.sound_state,
            beats_completed=[b for b in (d.beats_completed or []) if str(b).strip()],
            beats_reserved=[b for b in (d.beats_reserved or []) if str(b).strip()],
        ))

    # ---- 3. resolve the name-valued cross links --------------------------
    entities = list(by_key.values())
    name_index = {(e.kind, e.normalized): e.entity_id for e in entities}

    def _relink(entity: Entity) -> Entity:
        update: dict = {}
        costume_name = pending_costume.get(entity.entity_id)
        if costume_name:
            target = name_index.get((EntityKind.COSTUME, normalize_name(costume_name)))
            if target:
                update["costume_id"] = target
            else:
                notes.append(f"'{entity.name}' names costume '{costume_name}' "
                             f"which is not in the registry — link dropped")
        owner_name = pending_owner.get(entity.entity_id)
        if owner_name:
            target = name_index.get((EntityKind.CHARACTER, normalize_name(owner_name)))
            if target:
                update["owner_id"] = target
            else:
                notes.append(f"prop '{entity.name}' names owner '{owner_name}' "
                             f"which is not in the registry — link dropped")
        return entity.model_copy(update=update) if update else entity

    entities = [_relink(e) for e in entities]
    entities = _add_bare_noun_aliases(entities, notes)

    # An entity nobody references is dead weight in the approval UI and burns
    # reference-sheet generations. Reported, not deleted: the operator may know
    # it belongs and add it to a shot.
    used = {eid for s in shots for eid in s.entity_ids()}
    for e in entities:
        if e.entity_id not in used:
            notes.append(f"{e.kind.value} '{e.name}' is declared but appears in "
                         f"no shot — it will not get a reference sheet")

    return Storyboard(
        board_id=board_id, channel_id=channel_id, product_slug=product_slug,
        title=title, status=BoardStatus.DRAFT,
        script_hash=script_hash(source_script),
        style_prompt=style_prompt, negative_prompt=negative_prompt,
        entities=entities, shots=shots, frames=[], notes=notes,
    )


# --------------------------------------------------------------------------
# The LLM stage
# --------------------------------------------------------------------------

_SYSTEM = """You are a storyboard supervisor. You turn a finished script into \
two things: a GLOBAL CAST of everything that must look the same across shots, \
and an ordered SHOT LIST that references that cast by name.

THE CAST comes first and is a dictionary. Four kinds:
- character: a person. Describe what must be drawn identically every time —
  approximate age, build, hair, face, defining marks. Not their personality.
- location: a place. Describe the architecture, the light, the dressing.
- prop: an object that recurs or matters. Describe geometry and markings.
- costume: a distinct outfit worn by a character.

HARD RULES — these are checked mechanically and violations are repaired
against you, so following them keeps your intent intact:
1. A shot may ONLY reference names that appear in the cast. If a shot needs
   something, ADD IT TO THE CAST FIRST.
2. Names are verbatim. Never normalize spacing, brackets, accents or case
   between the cast and the shots. "Bà Tư (già)" is not "Ba Tu (gia)".
3. One entity, one entry. If the script calls the same person two things, make
   ONE entry and put the other in `aliases`.
4. When you are NOT sure two names are the same person, create two entries.
   A wrongly merged pair deletes a character; a wrongly split pair is a
   cheap fix later.
5. Group characters ("the neighbours", "a crowd") get a cast entry too.
6. `title` describes the PICTURE, not the scene. `location_name` carries the place.

SHOT LANGUAGE — closed vocabularies, exact tokens only:
- camera_shot: ECU | CU | MCU | MS | MLS | LS | ELS
- angle: EYE_LEVEL | HIGH_ANGLE | LOW_ANGLE | BIRD_EYE | DUTCH | OVER_SHOULDER
- movement: STATIC | PAN | TILT | DOLLY_IN | DOLLY_OUT | TRACK | CRANE |
  HANDHELD | STEADICAM | ZOOM_IN | ZOOM_OUT
Vary them. Ten consecutive medium eye-level statics is a slideshow, not coverage.

CONTINUITY — these are the anchors that make consecutive shots read as one
scene instead of a slideshow. They are checked mechanically:
- `observed_end_state`: where this shot leaves people, objects and light.
- `planned_start_state`: how the next shot opens from that.
- `declared_changes`: anything that changes ON PURPOSE between shots — a coat
  removed, a move to a new room, a time skip, a deliberate axis reset.
  Undeclared changes are treated as defects, so declare the deliberate ones.
- `screen_direction`: which way the subject travels across frame. KEEP IT
  STABLE inside one location. Reversing it without declaring an axis reset
  makes the viewer read the subject as having turned around — the single most
  visible continuity error in cut film.
- `light_key` and `time_of_day`: the same room under different light does not
  read as the same room. Change them only with a declaration.
- `motion_vector`: motion still running as the shot ends. The next shot must
  inherit it, or the movement stops dead on the cut.

EVENT DENSITY — one shot carries ONE visible beat with a changed endpoint:
- `beats_completed`: what an EARLIER shot already performed. Never replay it;
  the action visibly restarts on screen if you do.
- `beats_reserved`: what a LATER shot will perform. Never perform it early,
  even when it would explain motivation — that spoils the sequence's own
  reveal. Story context may inform mood and performance; it must not make this
  shot do another shot's job.
Split a shot when it would need several completed actions, several locations,
or several turns of dialogue.

Do not output ids. Output JSON only."""


class StoryboardExtractorAgent(BaseAgent):
    """Script → `ExtractionDraft`. Names only; ids are assigned downstream."""

    @property
    def name(self) -> str:
        return "storyboard_extractor"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    async def execute(
        self,
        script_text: str,
        *,
        channel_brief: str = "",
        target_shots: int = 0,
        visual_style: str = "",
    ) -> ExtractionDraft:
        guidance = []
        if channel_brief:
            guidance.append(f"## Channel\n{channel_brief}")
        if visual_style:
            guidance.append(f"## Visual style\n{visual_style}")
        if target_shots:
            guidance.append(
                f"## Length\nAim for about {target_shots} shots. Cut on action "
                f"or on a new piece of information, not on a fixed clock.")
        prompt = "\n\n".join([
            *guidance,
            "## Script\n" + (script_text or "").strip(),
            "## Output\nJSON with `entities` then `shots`.",
        ])
        _resp, parsed = await self.call_llm_structured(
            [{"role": "user", "content": prompt}],
            ExtractionDraft,
            max_tokens=16000,
            temperature=0.4,
        )
        draft = parsed if isinstance(parsed, ExtractionDraft) else \
            ExtractionDraft.model_validate(parsed)
        logger.info("storyboard extracted", entities=len(draft.entities),
                    shots=len(draft.shots))
        return draft


def draft_from_scenes(scenes: list[dict]) -> ExtractionDraft:
    """Fallback draft from an existing flat scene list, with NO cast.

    For channels that already have `ScriptScene` records and just want the shot
    spine. It produces zero entities on purpose — inventing a cast from
    b-roll queries would manufacture exactly the confident-and-wrong registry
    this package is meant to replace. Callers get a board that the continuity
    gate will correctly report as unanchored.
    """
    shots = [
        DraftShot(
            index=i,
            title=(s.get("visual_prompt") or "")[:120],
            script_excerpt=s.get("voiceover") or "",
            voiceover=s.get("voiceover") or "",
            duration_s=float(s.get("duration_s") or 0.0),
            transition=s.get("transition") or "cut",
        )
        for i, s in enumerate(scenes or [])
    ]
    return ExtractionDraft(entities=[], shots=shots)


def draft_to_json(draft: ExtractionDraft) -> str:
    return json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2)
