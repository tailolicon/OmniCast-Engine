"""Cross-shot entity merging — one person, one entry, one face.

THE PROBLEM. A script calls someone "the driver" in shot 2 and "Minh" in shot
9. The extractor, reading honestly, produces two cast members. Two cast members
get two reference sheets, and the video has two men where the story has one.

THE RISK OF FIXING IT. Merging is destructive and asymmetric: a wrong merge
DELETES a character (two people collapse into one face and the story stops
making sense), while a missed merge only costs a duplicate sheet an operator
can spot in the cast screen. Jellyfish's own prompt says as much — rather split
than rename. So this module is biased hard toward not merging.

HOW THAT BIAS IS ENFORCED. The model proposes; `apply_merges` decides, and it
only applies a proposal that clears every deterministic check — same kind, both
names real, confidence above the floor, and a non-empty evidence quote that
actually occurs in the script. Anything it refuses becomes a `conflict` on the
entity, and a conflict BLOCKS the cast approval barrier. The operator resolves
it in the UI, which is the one place a human is already looking.
"""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.storyboard.models import (
    Entity,
    EntityKind,
    Shot,
    ShotEntityRef,
    Storyboard,
    normalize_name,
)
from omnicast.storyboard.schemas import MergeResult

logger = structlog.get_logger()

#: Below this, a proposal is recorded as a conflict for a human instead of
#: being applied. Deliberately high: the cost of a wrong merge is a deleted
#: character, the cost of a refusal is one click.
CONFIDENCE_FLOOR = 0.75


def _rewrite_ref(entity_id: str, remap: dict[str, str]) -> str:
    return remap.get(entity_id, entity_id)


def _rewrite_shot(shot: Shot, remap: dict[str, str]) -> Shot:
    cast: list[ShotEntityRef] = []
    seen: set[str] = set()
    for ref in sorted(shot.cast, key=lambda c: c.index):
        target = _rewrite_ref(ref.entity_id, remap)
        if target in seen:
            # The same person named twice in one shot collapses to one slot;
            # keeping both would attach the same reference image twice and
            # spend two of a six-image budget on one face.
            continue
        seen.add(target)
        cast.append(ref.model_copy(update={"entity_id": target,
                                           "index": len(cast)}))
    location_id = _rewrite_ref(shot.location_id, remap) if shot.location_id else None
    return shot.model_copy(update={"cast": cast, "location_id": location_id})


def apply_merges(
    board: Storyboard,
    result: MergeResult,
    *,
    source_script: str = "",
    confidence_floor: float = CONFIDENCE_FLOOR,
) -> Storyboard:
    """Apply the proposals that survive scrutiny; record the rest as conflicts.

    Pure function. Returns a new board — the caller decides whether to persist
    it, so a rejected merge run costs nothing.
    """
    notes = list(board.notes)
    remap: dict[str, str] = {}          # duplicate id -> canonical id
    conflicts: dict[str, list[str]] = {}  # entity id -> reasons
    folded_aliases: dict[str, list[str]] = {}
    script_blob = (source_script or "").lower()

    def _flag(entity: Entity | None, reason: str) -> None:
        if entity is None:
            notes.append(f"unresolved merge claim: {reason}")
            return
        conflicts.setdefault(entity.entity_id, []).append(reason)

    for proposal in result.merges:
        kind = None
        try:
            kind = EntityKind((proposal.kind or "character").lower())
        except ValueError:
            kind = EntityKind.CHARACTER

        canonical = board.by_name(proposal.canonical_name)
        if canonical is None or canonical.kind is not kind:
            notes.append(
                f"merge claim names canonical '{proposal.canonical_name}' which "
                f"is not a {kind.value} in this registry — ignored")
            continue

        for dup_name in proposal.duplicate_names:
            duplicate = board.by_name(dup_name)
            reason_prefix = f"'{dup_name}' → '{canonical.name}'"

            if duplicate is None:
                notes.append(f"merge claim {reason_prefix}: '{dup_name}' is not "
                             f"in the registry — ignored")
                continue
            if duplicate.entity_id == canonical.entity_id:
                continue
            if duplicate.kind is not canonical.kind:
                _flag(duplicate,
                      f"{reason_prefix} rejected: a {duplicate.kind.value} and "
                      f"a {canonical.kind.value} cannot be the same entity")
                continue
            if proposal.confidence < confidence_floor:
                _flag(duplicate,
                      f"{reason_prefix} proposed at confidence "
                      f"{proposal.confidence:.2f}, below the {confidence_floor} "
                      f"floor — merging on a guess deletes a character")
                continue
            if not proposal.evidence.strip():
                _flag(duplicate,
                      f"{reason_prefix} proposed with no evidence quote")
                continue
            if script_blob and proposal.evidence.strip().lower() not in script_blob:
                # The same trick the narrative gates use: an unquotable
                # justification is a justification the model composed.
                _flag(duplicate,
                      f"{reason_prefix} rejected: the evidence quote does not "
                      f'occur in the script - "{proposal.evidence.strip()[:80]}"')
                continue
            if duplicate.entity_id in remap and remap[duplicate.entity_id] != canonical.entity_id:
                _flag(duplicate,
                      f"{reason_prefix} conflicts with an earlier claim that it "
                      f"is a different entity")
                continue

            remap[duplicate.entity_id] = canonical.entity_id
            folded_aliases.setdefault(canonical.entity_id, []).extend(
                [duplicate.name, *duplicate.aliases])
            notes.append(f"merged {reason_prefix} (confidence "
                         f"{proposal.confidence:.2f})")

    # Claims the model itself could not settle. Attach to the named entity when
    # one can be identified so the operator sees it next to the face.
    for raw in result.conflicts:
        matched = None
        for entity in board.entities:
            if entity.normalized and entity.normalized in normalize_name(raw):
                matched = entity
                break
        _flag(matched, raw)

    # Collapse chains (a→b, b→c ⇒ a→c) so a two-hop claim cannot leave a
    # dangling id pointing at an entity that is itself about to disappear.
    for _ in range(len(remap)):
        changed = False
        for src, dst in list(remap.items()):
            if dst in remap and remap[dst] != dst:
                remap[src] = remap[dst]
                changed = True
        if not changed:
            break

    entities: list[Entity] = []
    for entity in board.entities:
        if entity.entity_id in remap:
            continue  # folded away
        extra = folded_aliases.get(entity.entity_id, [])
        aliases = list(entity.aliases)
        for alias in extra:
            if alias.strip() and normalize_name(alias) != entity.normalized \
                    and alias not in aliases:
                aliases.append(alias)
        update: dict = {}
        if aliases != entity.aliases:
            update["aliases"] = aliases
        if entity.entity_id in conflicts:
            update["conflicts"] = [*entity.conflicts, *conflicts[entity.entity_id]]
        if entity.costume_id and entity.costume_id in remap:
            update["costume_id"] = remap[entity.costume_id]
        if entity.owner_id and entity.owner_id in remap:
            update["owner_id"] = remap[entity.owner_id]
        entities.append(entity.model_copy(update=update) if update else entity)

    # A conflict recorded against an entity that was itself merged away would
    # vanish silently; re-home it onto the survivor.
    for dead_id, reasons in conflicts.items():
        if dead_id not in remap:
            continue
        survivor_id = remap[dead_id]
        for i, entity in enumerate(entities):
            if entity.entity_id == survivor_id:
                entities[i] = entity.model_copy(update={
                    "conflicts": [*entity.conflicts, *reasons]})
                break

    shots = [_rewrite_shot(s, remap) for s in board.shots]
    logger.info("storyboard merge applied", merged=len(remap),
                conflicts=sum(len(v) for v in conflicts.values()))
    return board.model_copy(update={"entities": entities, "shots": shots,
                                    "notes": notes})


_SYSTEM = """You identify when two names in a cast list denote the SAME entity.

You are the last guard against a video in which one person has two faces. You \
are also the thing most likely to delete a character by merging two people who \
merely sound alike. Because of that asymmetry:

- Propose a merge ONLY when the script makes the identification certain.
- Every merge needs `evidence`: a quote COPIED VERBATIM from the script that \
  proves it. The quote is checked against the script mechanically; a \
  paraphrase or a composed line is rejected and your merge is discarded.
- `confidence` is what you actually believe. Below 0.75 the merge is not \
  applied, so an honest low number routes the case to a human instead of \
  quietly changing the cast.
- Anything you cannot settle goes in `conflicts` as a plain sentence. That is \
  a SUCCESSFUL outcome, not a failure — a human resolves it in one click.

Never merge across kinds. Never merge two characters just because they share a \
role ("a nurse" and "another nurse"), an age, or a description. Family terms \
are not identities: "her brother" and "Minh" merge only if the script says so.

Output JSON only."""


class StoryboardMergerAgent(BaseAgent):
    """Cast list → `MergeResult` of alias claims and undecidable cases."""

    @property
    def name(self) -> str:
        return "storyboard_merger"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    async def execute(self, board: Storyboard, *, script_text: str = "") -> MergeResult:
        roster = []
        for entity in board.entities:
            appears = sorted(s.index for s in board.shots
                             if entity.entity_id in s.entity_ids())
            roster.append(
                f"- [{entity.kind.value}] {entity.name}"
                + (f" (aliases: {', '.join(entity.aliases)})" if entity.aliases else "")
                + f" — shots {appears or 'none'}"
                + (f" — {entity.description[:160]}" if entity.description else ""))

        prompt = (
            "## Cast as extracted\n" + "\n".join(roster)
            + "\n\n## Script\n" + (script_text or "").strip()
            + "\n\n## Output\nJSON with `merges` and `conflicts`. Return empty "
              "lists if every entry is already distinct — that is the common case."
        )
        _resp, parsed = await self.call_llm_structured(
            [{"role": "user", "content": prompt}],
            MergeResult,
            max_tokens=4000,
            temperature=0.1,
        )
        return parsed if isinstance(parsed, MergeResult) else \
            MergeResult.model_validate(parsed)
