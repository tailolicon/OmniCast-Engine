"""Reference sheets — the images that ARE each cast member.

WHAT CHANGED FROM `media/character_anchor.py`. That module generates up to
three anchors for ONE character, per channel, from a text DNA block, and
attaches the same set to every call. It was the right first move and it is
where the pose list here comes from. What it cannot do is give a location, a
prop, or a second character its own reference — a video with two people has
one anchor set, so the second face drifts by construction. Sheets here are
per ENTITY and live under the board.

VIEW 1 IS THE ANCHOR, VIEWS 2..N ARE CONDITIONED ON IT. Generating three views
from the same text description independently produces three plausible people.
The moment a provider can take reference images (`supports_reference_images`),
every view after the first is generated WITH the first attached, so the sheet
is internally consistent before it is ever used to make a frame consistent.
When the provider cannot, we say so in the returned notes rather than
pretending the sheet is anchored.

OPERATOR IMAGES WIN. A human-supplied file is `ImageSource.OPERATOR`, is
approved on arrival, and is never outvoted by a later generation pass. If a
person went to the trouble of uploading a face, that is the face.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import structlog

from omnicast.storyboard.models import (
    Entity,
    EntityImage,
    EntityKind,
    ImageSource,
    RefRole,
    Storyboard,
)

logger = structlog.get_logger()

_IMPL_ROOT = Path(__file__).resolve().parents[3]
SHEET_DIR = _IMPL_ROOT / "output" / "_storyboard"

#: Views per kind, most identity-bearing first. The first entry is the anchor
#: everything else is conditioned on, so it must be the least ambiguous view.
VIEWS: dict[EntityKind, tuple[tuple[str, str], ...]] = {
    EntityKind.CHARACTER: (
        ("front", "front-facing head-and-shoulders portrait, neutral "
                  "expression, plain neutral background, even lighting"),
        ("three_quarter", "three-quarter view upper-body shot, same person, "
                          "plain neutral background"),
        ("full_body", "full-body standing shot, same person, plain neutral "
                      "background"),
    ),
    EntityKind.COSTUME: (
        ("flat", "the garment presented on a plain mannequin, front view, "
                 "plain neutral background, no face visible"),
        ("detail", "close detail of the garment's fabric, fastenings and "
                   "trim, plain neutral background"),
    ),
    EntityKind.PROP: (
        ("three_quarter", "three-quarter product view of the object alone on a "
                          "plain neutral background, even lighting"),
        ("detail", "close detail of the object's distinguishing markings and "
                   "wear, plain neutral background"),
    ),
    EntityKind.LOCATION: (
        ("establishing", "wide establishing view of the empty place, no people "
                         "present, natural lighting"),
        ("secondary", "a second angle of the same place, no people present, "
                      "consistent architecture and dressing"),
    ),
}

#: Appended to every sheet prompt. A reference sheet with a person in the
#: location shot teaches the model that the location contains that person.
#:
#: Phrased POSITIVELY on purpose. The first version read "No text, no
#: watermark, no border, no collage, no split panels" and `slop.py` flagged it
#: the moment that module existed: naming a flaw plants it, so a prompt that
#: says "no watermark" is a prompt asking about watermarks. What must be
#: excluded belongs in the provider's negative field (`board.negative_prompt`),
#: which is a different mechanism; the positive prose locks the positive.
_SHEET_RULES = ("Reference sheet image: the subject alone, centred, filling a "
                "single unbroken frame against a plain seamless backdrop.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sheet_dir(board_id: str, entity_id: str) -> Path:
    return SHEET_DIR / board_id / entity_id


def build_view_prompts(entity: Entity, *, style_prompt: str = "",
                       limit: int = 0) -> list[tuple[str, str]]:
    """`(view_name, prompt)` for one entity, anchor view first."""
    views = VIEWS.get(entity.kind, VIEWS[EntityKind.CHARACTER])
    if limit > 0:
        views = views[:limit]
    subject = (f"{entity.kind.value} named {entity.name}"
               if entity.name else entity.kind.value)
    out: list[tuple[str, str]] = []
    for view_name, pose in views:
        # Style first, then who/what, then the view, matching the ordering
        # `media/character_anchor.py` settled on: art direction sets the frame
        # the subject is described inside, not the other way round.
        parts = [p for p in (style_prompt.strip(),
                             f"{subject}: {pose}",
                             entity.description.strip()) if p]
        out.append((view_name, ". ".join(parts) + ". " + _SHEET_RULES))
    return out


def adopt_operator_images(entity: Entity, paths: list[str]) -> Entity:
    """Attach human-supplied files as approved identity references."""
    images = list(entity.images)
    known = {im.path for im in images}
    for i, raw in enumerate(paths or []):
        p = Path(raw)
        if not p.exists() or p.stat().st_size == 0 or str(p.resolve()) in known:
            continue
        images.append(EntityImage(
            image_id=f"{entity.entity_id}_op{i:02d}",
            entity_id=entity.entity_id,
            path=str(p.resolve()),
            view="operator",
            role=entity.default_role,
            source=ImageSource.OPERATOR,
            approved=True,
        ))
    return entity.model_copy(update={"images": images}) if images != entity.images else entity


async def generate_sheet(
    entity: Entity,
    provider,
    *,
    board_id: str,
    style_prompt: str = "",
    negative_prompt: str = "",
    auto_approve: bool = False,
) -> tuple[Entity, list[str]]:
    """Fill in this entity's reference sheet. Returns `(entity, notes)`.

    Never raises for a provider failure: a partial sheet is still useful and
    the cast barrier will refuse to pass an entity with nothing approved. The
    notes explain what did not happen, so "no reference" is never mistaken for
    "reference was not needed".
    """
    notes: list[str] = []
    if provider is None:
        return entity, ["no image provider configured — no sheet generated"]

    can_condition = bool(getattr(provider, "supports_reference_images", False))
    if not can_condition:
        notes.append(
            f"provider '{getattr(provider, 'id', '?')}' cannot take reference "
            f"images, so views after the first are generated blind and may not "
            f"match each other")

    target = sheet_dir(board_id, entity.entity_id)
    target.mkdir(parents=True, exist_ok=True)

    images = list(entity.images)
    have = {im.view for im in images}
    anchor_path = next((im.path for im in images
                        if im.source is ImageSource.OPERATOR), "")

    wanted = build_view_prompts(entity, style_prompt=style_prompt,
                                limit=entity.view_count)
    for idx, (view_name, prompt) in enumerate(wanted):
        if view_name in have:
            continue
        dst = target / f"{view_name}.png"
        if dst.exists() and dst.stat().st_size > 0:
            # Stable entity ids mean a re-run finds last run's sheet. Reusing
            # it is what lets an operator's approval survive re-extraction.
            images.append(EntityImage(
                image_id=f"{entity.entity_id}_{view_name}",
                entity_id=entity.entity_id, path=str(dst), view=view_name,
                role=entity.default_role, source=ImageSource.CACHED,
                approved=auto_approve, prompt_used=prompt, created_at=_now()))
            anchor_path = anchor_path or str(dst)
            continue

        kwargs: dict = {"negative": negative_prompt, "output_path": str(dst)}
        if can_condition and anchor_path:
            kwargs["reference_images"] = [anchor_path]
            kwargs["reference_labels"] = ["[IMAGE 1]"]
            prompt = (f"[IMAGE 1] is the canonical appearance of this "
                      f"{entity.kind.value}. Keep it identical.\n\n{prompt}")
        try:
            await provider.generate(prompt, **kwargs)
        except Exception as exc:  # noqa: BLE001 — provider failure is data here
            notes.append(f"'{entity.name}' view '{view_name}' failed: "
                         f"{str(exc)[:140]}")
            continue
        if not dst.exists() or dst.stat().st_size == 0:
            notes.append(f"'{entity.name}' view '{view_name}': provider "
                         f"returned without writing a file")
            continue
        images.append(EntityImage(
            image_id=f"{entity.entity_id}_{view_name}",
            entity_id=entity.entity_id, path=str(dst), view=view_name,
            role=entity.default_role, source=ImageSource.GENERATED,
            approved=auto_approve, prompt_used=prompt, created_at=_now()))
        if idx == 0 or not anchor_path:
            anchor_path = str(dst)

    return entity.model_copy(update={"images": images}), notes


async def build_all_sheets(
    board: Storyboard,
    provider,
    *,
    operator_images: dict[str, list[str]] | None = None,
    auto_approve: bool = False,
) -> Storyboard:
    """Reference sheets for every entity a shot actually uses.

    Entities nobody references are skipped — `reconcile_draft` already noted
    them, and generating sheets for them spends real credit on images no frame
    will ever attach.
    """
    used = {eid for s in board.shots for eid in s.entity_ids()}
    operator_images = operator_images or {}
    notes = list(board.notes)
    entities: list[Entity] = []

    for entity in board.entities:
        if entity.entity_id not in used:
            entities.append(entity)
            continue
        seeded = adopt_operator_images(entity, operator_images.get(entity.entity_id, []))
        filled, entity_notes = await generate_sheet(
            seeded, provider, board_id=board.board_id,
            style_prompt=board.style_prompt,
            negative_prompt=board.negative_prompt,
            auto_approve=auto_approve)
        entities.append(filled)
        notes.extend(entity_notes)

    logger.info("reference sheets built", board=board.board_id,
                entities=len(used),
                images=sum(len(e.images) for e in entities))
    return board.model_copy(update={"entities": entities, "notes": notes})
