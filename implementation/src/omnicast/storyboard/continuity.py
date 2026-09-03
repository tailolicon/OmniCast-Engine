"""Continuity gate — name every place the board breaks its own promises.

ISSUES, NOT A SCORE. `animation/bible.py` already argued this and it holds
here: "continuity: 0.83" tells an operator nothing they can act on, while
"shot 12 binds Minh to a different reference file than shot 3" tells them
exactly what to fix. Every issue carries the shot it belongs to and the
evidence that produced it.

TWO SEVERITIES, from seedance-2.0's Continuity QC (MIT):

  HARD — things that must never change silently: who a character is, what
  they are wearing, which place this is, which reference file stands for them,
  and the lineage between shots. A hard issue blocks release.

  WARN — things that change all the time for good reasons: pose, lighting,
  emotion, screen direction. These are only reported when the shot did NOT
  declare them. `Shot.declared_changes` is the escape hatch: "she takes the
  coat off" turns a wardrobe change from a defect into continuity.

WHAT THIS GATE CAN AND CANNOT SEE. It reads the BOARD — the bindings, the
cast, the chain — not the pixels. It catches "this shot was set up to drift",
which is the class of failure that is cheap to fix and expensive to discover
after render. It does not look at a generated frame and judge whether the face
matches; `media/visual_match_runner.py` is the pixel-side check and runs later.
Nothing here should be read as "the images are consistent".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from omnicast.storyboard.models import (
    OPPOSITE_DIRECTIONS,
    EntityKind,
    FrameType,
    RefMapping,
    ScreenDirection,
    Shot,
    Storyboard,
)
from omnicast.storyboard.slop import blocking_findings as blocking_slop
from omnicast.storyboard.slop import lint as lint_slop


class Severity(str, Enum):
    HARD = "hard"
    WARN = "warn"


#: Axis → words that count as declaring a change on it. Matched against
#: `Shot.declared_changes`. Deliberately generous: a director who wrote
#: "she takes the coat off" should not have to also write the word "wardrobe".
_DECLARATION_WORDS: dict[str, tuple[str, ...]] = {
    "wardrobe": ("wardrobe", "costume", "outfit", "clothes", "coat", "jacket",
                 "uniform", "changes into", "takes off", "puts on"),
    "location": ("location", "place", "moves to", "cuts to", "elsewhere",
                 "new scene", "outside", "inside"),
    "prop_ownership": ("prop", "hands", "gives", "drops", "leaves behind",
                       "takes", "picks up", "loses"),
    "lighting": ("lighting", "light", "lamp", "dark", "sunrise", "sunset",
                 "power", "torch", "flashlight"),
    "pose": ("pose", "stands", "sits", "turns", "kneels", "lies"),
    "screen_direction": ("screen direction", "axis", "reverse", "turns around",
                         "other side", "crosses"),
    "chain": ("time skip", "later", "next day", "flashback", "cut to",
              "intentional", "new sequence"),
}

#: How many consecutive identical camera setups before a board reads as a
#: slideshow. Three is where an edit stops looking like coverage.
_MONOTONY_RUN = 3


@dataclass(frozen=True)
class ContinuityIssue:
    shot_index: int          # -1 for board-level issues
    axis: str
    severity: Severity
    detail: str
    evidence: str = ""

    def as_dict(self) -> dict:
        return {
            "shot_index": self.shot_index,
            "axis": self.axis,
            "severity": self.severity.value,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class ContinuityReport:
    issues: list[ContinuityIssue] = field(default_factory=list)

    @property
    def hard(self) -> list[ContinuityIssue]:
        return [i for i in self.issues if i.severity is Severity.HARD]

    @property
    def warnings(self) -> list[ContinuityIssue]:
        return [i for i in self.issues if i.severity is Severity.WARN]

    @property
    def blocked(self) -> bool:
        return bool(self.hard)

    def as_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "hard_count": len(self.hard),
            "warn_count": len(self.warnings),
            "issues": [i.as_dict() for i in self.issues],
        }


def declared(shot: Shot, axis: str) -> bool:
    """Did this shot declare a change on `axis`?

    Matching is on the declaration text, not on a structured field, because
    directors write sentences. An unknown axis is never considered declared —
    a typo in the axis name must not silently disable a hard check.
    """
    words = _DECLARATION_WORDS.get(axis)
    if not words:
        return False
    blob = " ".join(shot.declared_changes).lower()
    if not blob.strip():
        return False
    return any(w in blob for w in words)


#: Words too common to identify a beat. A beat matched on "the" and "a" would
#: fire on every prompt.
_BEAT_STOPWORDS = frozenset(
    "a an the and or but of to in on at by for with from into onto is are was "
    "were be been being it its his her their this that then there here as so "
    "he she they him them we you i not no".split())

#: How much of a beat's ACTION must appear before it counts as performed.
_BEAT_OVERLAP = 2 / 3


def _content_words(text: str) -> set[str]:
    words = re.findall(r"\w+", (text or "").lower())
    return {w for w in words if w not in _BEAT_STOPWORDS and len(w) > 2}


def _beat_present(beat: str, prompt: str, participants: set[str]) -> bool:
    """Does `prompt` PERFORM `beat`?

    THE ACTION IDENTIFIES A BEAT; THE PARTICIPANTS DO NOT. Measured on the
    first paid run: matching on all content words blocked the board with seven
    findings, and most were false. "Minh enters the shophouse" fired against a
    shot of Minh sitting in his van, because that prompt naturally contains
    "Minh" and "shophouse" — two of the beat's three content words. Every shot
    in a scene shares that scene's cast and its location, so participant nouns
    carry no information about which beat is being played.

    So cast and location words are stripped first and only the residue — the
    verbs and objects that make this beat this beat — has to appear. That trades
    recall for precision deliberately: a missed warning costs a note nobody
    reads, while a false block stops a production run on a defect that is not
    there.
    """
    beat_words = _content_words(beat) - participants
    if not beat_words:
        # Nothing left but participants: unjudgeable, so do not guess.
        return False
    hit = beat_words & _content_words(prompt)
    return len(hit) / len(beat_words) >= _BEAT_OVERLAP


def _mappings_by_shot(board: Storyboard) -> dict[str, list[RefMapping]]:
    """What each shot ACTUALLY shipped, read off its frames.

    Frames are the authority, not a recomputation: the gate must judge the
    bindings that were sent to the model, including any an operator hand-edited
    in the UI. A shot whose frames disagree with each other is itself a finding.
    """
    out: dict[str, list[RefMapping]] = {}
    for frame in board.frames:
        out.setdefault(frame.shot_id, [])
        out[frame.shot_id].extend(frame.mappings)
    return out


def check_continuity(board: Storyboard) -> ContinuityReport:
    """Every way this board is set up to drift."""
    issues: list[ContinuityIssue] = []
    shots = sorted(board.shots, key=lambda s: s.index)
    by_id = {s.shot_id: s for s in shots}
    shot_mappings = _mappings_by_shot(board)

    if not shots:
        issues.append(ContinuityIssue(
            -1, "board", Severity.HARD,
            "storyboard has no shots — nothing to render"))
        return ContinuityReport(issues)

    # ---- cast integrity -------------------------------------------------
    for shot in shots:
        for entity_id in shot.entity_ids():
            entity = board.entity(entity_id)
            if entity is None:
                issues.append(ContinuityIssue(
                    shot.index, "cast", Severity.HARD,
                    f"shot references entity '{entity_id}' which is not in the "
                    f"cast registry — it can never be bound to an image",
                    evidence=entity_id))
                continue
            if entity.conflicts:
                issues.append(ContinuityIssue(
                    shot.index, "cast", Severity.HARD,
                    f"'{entity.name}' has unresolved merge conflicts; an "
                    f"operator must pick one reading before it can be drawn",
                    evidence="; ".join(entity.conflicts[:3])))
            elif not entity.approved_images:
                issues.append(ContinuityIssue(
                    shot.index, "identity", Severity.HARD,
                    f"'{entity.name}' appears in this shot with no approved "
                    f"reference image — the model will invent one and it will "
                    f"differ in every shot",
                    evidence=entity.name))

    # ---- reference stability: the same thing, the same file -------------
    # The core identity check. A character bound to anchor_00 in shot 3 and
    # anchor_02 in shot 7 is two characters as far as the model is concerned.
    seen_paths: dict[tuple[str, str], tuple[str, int]] = {}
    for shot in shots:
        for mapping in shot_mappings.get(shot.shot_id, []):
            key = (mapping.entity_id, mapping.role.value)
            prior = seen_paths.get(key)
            if prior is None:
                seen_paths[key] = (mapping.path, shot.index)
                continue
            prior_path, prior_index = prior
            if prior_path != mapping.path:
                axis = ("wardrobe" if mapping.kind is EntityKind.COSTUME
                        else "location" if mapping.kind is EntityKind.LOCATION
                        else "identity")
                # Wardrobe and location may legitimately change on purpose and
                # a declaration clears them. IDENTITY MAY NOT: there is no
                # story reason for the same character, in the same role, to be
                # backed by a different face file, and "the script said so" is
                # exactly the excuse that lets drift ship. `_DECLARATION_WORDS`
                # has no `identity` entry, so this is a closed door by
                # construction rather than by a caller remembering.
                if axis != "identity" and declared(shot, axis):
                    continue
                issues.append(ContinuityIssue(
                    shot.index, axis, Severity.HARD,
                    f"'{mapping.name}' is bound to a different reference file "
                    f"than in shot {prior_index} while playing the same "
                    f"{mapping.role.value} role, and the shot declares no "
                    f"change — it will not look like the same "
                    f"{mapping.kind.value}",
                    evidence=f"shot {prior_index}: {prior_path} | "
                             f"shot {shot.index}: {mapping.path}"))

    # ---- wardrobe: a character's declared costume must be the one present
    for shot in shots:
        present = set(shot.entity_ids())
        for entity_id in list(present):
            entity = board.entity(entity_id)
            if entity is None or entity.kind is not EntityKind.CHARACTER:
                continue
            if not entity.costume_id:
                continue
            worn = [e for e in present
                    if (board.entity(e) or entity).kind is EntityKind.COSTUME]
            if worn and entity.costume_id not in worn and not declared(shot, "wardrobe"):
                names = ", ".join(
                    (board.entity(w).name if board.entity(w) else w) for w in worn)
                issues.append(ContinuityIssue(
                    shot.index, "wardrobe", Severity.HARD,
                    f"'{entity.name}' is pinned to a costume that this shot "
                    f"does not include, while another costume is present "
                    f"({names}), and no wardrobe change is declared",
                    evidence=entity.costume_id))

    # ---- prop ownership --------------------------------------------------
    for shot in shots:
        present = set(shot.entity_ids())
        for entity_id in present:
            entity = board.entity(entity_id)
            if entity is None or entity.kind is not EntityKind.PROP:
                continue
            if entity.owner_id and entity.owner_id not in present \
                    and not declared(shot, "prop_ownership"):
                owner = board.entity(entity.owner_id)
                issues.append(ContinuityIssue(
                    shot.index, "prop_ownership", Severity.WARN,
                    f"prop '{entity.name}' appears without its owner "
                    f"'{owner.name if owner else entity.owner_id}' and the "
                    f"shot does not say how it got there",
                    evidence=entity.name))

    # ---- location anchoring ---------------------------------------------
    for shot in shots:
        if not shot.location_id:
            issues.append(ContinuityIssue(
                shot.index, "location", Severity.WARN,
                "shot has no location entity — the place is unanchored and "
                "each frame may invent a different one"))

    # ---- lineage / chain -------------------------------------------------
    for position, shot in enumerate(shots):
        if shot.parent_shot_id:
            parent = by_id.get(shot.parent_shot_id)
            if parent is None:
                issues.append(ContinuityIssue(
                    shot.index, "chain", Severity.HARD,
                    f"parent_shot_id '{shot.parent_shot_id}' does not exist in "
                    f"this board — the continuity chain is broken",
                    evidence=shot.parent_shot_id))
            elif parent.index >= shot.index:
                issues.append(ContinuityIssue(
                    shot.index, "chain", Severity.HARD,
                    f"parent shot {parent.index} does not precede this shot "
                    f"({shot.index}) — lineage runs backwards",
                    evidence=f"parent index {parent.index}"))
            elif shot.planned_start_state.strip() and \
                    not parent.observed_end_state.strip():
                issues.append(ContinuityIssue(
                    shot.index, "chain", Severity.WARN,
                    f"this shot plans an opening state but shot {parent.index} "
                    f"never recorded how it ended, so the join cannot be "
                    f"verified"))
        elif position > 0 and shot.planned_start_state.strip() \
                and not declared(shot, "chain"):
            issues.append(ContinuityIssue(
                shot.index, "chain", Severity.WARN,
                "shot plans an opening state but names no parent shot — "
                "nothing establishes what it continues from"))

    # ---- frame completeness ---------------------------------------------
    # A shot that will be interpolated needs both ends. A first frame with no
    # last frame silently degrades to a still, which is the failure mode
    # `veo_pipeline` already hits when a clip fails.
    for shot in shots:
        kinds = {f.frame_type for f in board.frames_for(shot.shot_id)}
        if not kinds:
            issues.append(ContinuityIssue(
                shot.index, "frames", Severity.HARD,
                "shot has no frames — nothing to generate"))
        elif FrameType.FIRST in kinds and FrameType.LAST not in kinds \
                and shot.movement is not None and shot.movement.value != "STATIC":
            issues.append(ContinuityIssue(
                shot.index, "frames", Severity.WARN,
                f"shot declares camera movement ({shot.movement.value}) and a "
                f"first frame but no last frame — there is nothing to move "
                f"toward, so it will render as a still"))

    # ---- continuity anchors between neighbouring shots -------------------
    # The top rows of seedance's failure atlas. Each needs a FIELD to compare;
    # before these existed the gate could not see any of them.
    for position in range(1, len(shots)):
        prev, cur = shots[position - 1], shots[position]
        same_place = bool(cur.location_id) and cur.location_id == prev.location_id

        # 180-degree rule. Only meaningful inside one continuous location: a
        # cut to somewhere else resets the axis by definition.
        if same_place and OPPOSITE_DIRECTIONS.get(prev.screen_direction) is \
                cur.screen_direction and not declared(cur, "screen_direction"):
            issues.append(ContinuityIssue(
                cur.index, "screen_direction", Severity.HARD,
                f"subject travels {prev.screen_direction.value} in shot "
                f"{prev.index} and {cur.screen_direction.value} here, in the "
                f"same location, with no axis reset declared — the viewer "
                f"reads this as the subject turning around",
                evidence=f"{prev.screen_direction.value} → "
                         f"{cur.screen_direction.value}"))

        # Open motion must be inherited or explicitly stopped.
        if prev.motion_vector.strip() and not cur.motion_vector.strip() \
                and not cur.declared_changes:
            issues.append(ContinuityIssue(
                cur.index, "motion_vector", Severity.WARN,
                f"shot {prev.index} ends with motion still running "
                f"(\"{prev.motion_vector[:60]}\") but this shot inherits no "
                f"vector — the movement will stop dead on the cut"))

        # Light and time of day are location anchors: changing them inside one
        # place, undeclared, reads as a different room.
        for axis, before, after in (("lighting", prev.light_key, cur.light_key),
                                    ("lighting", prev.time_of_day, cur.time_of_day)):
            if same_place and before.strip() and after.strip() \
                    and before.strip().lower() != after.strip().lower() \
                    and not declared(cur, "lighting"):
                issues.append(ContinuityIssue(
                    cur.index, axis, Severity.HARD,
                    f"light state changes from \"{before[:40]}\" to "
                    f"\"{after[:40]}\" within the same location and nothing "
                    f"declares it — the place will not read as the same place",
                    evidence=f"{before[:40]} → {after[:40]}"))

    # A shot that never declares an axis cannot be checked against its
    # neighbours at all. Worth saying once per board rather than per shot.
    unset = [s.index for s in shots
             if s.screen_direction is ScreenDirection.UNSET]
    if unset:
        issues.append(ContinuityIssue(
            -1, "screen_direction", Severity.WARN,
            f"{len(unset)} shot(s) declare no screen direction "
            f"({unset[:6]}{'…' if len(unset) > 6 else ''}), so the 180-degree "
            f"rule cannot be checked for them"))

    # ---- event density / scope firewall ----------------------------------
    # Story context may inform a shot's mood; it must not make the shot perform
    # a beat that belongs to another one.
    # Every word any cast member answers to. Subtracted from a beat before
    # matching, so a beat is identified by what HAPPENS, not by who is there.
    participants: set[str] = set()
    for entity in board.entities:
        for spelling in entity.all_spellings():
            participants |= _content_words(spelling)

    for frame in board.frames:
        shot = by_id.get(frame.shot_id)
        if shot is None:
            continue
        for beat in shot.beats_completed:
            if _beat_present(beat, frame.base_prompt, participants):
                issues.append(ContinuityIssue(
                    shot.index, "event_density", Severity.HARD,
                    f"{frame.frame_type.value} frame replays a beat already "
                    f"performed earlier — the action will restart on screen",
                    evidence=beat[:90]))
        for beat in shot.beats_reserved:
            if _beat_present(beat, frame.base_prompt, participants):
                issues.append(ContinuityIssue(
                    shot.index, "event_density", Severity.HARD,
                    f"{frame.frame_type.value} frame performs a beat reserved "
                    f"for a later shot — the sequence spoils its own reveal",
                    evidence=beat[:90]))

    # ---- AI slop ---------------------------------------------------------
    # Linted HERE rather than stored on the frame, so an operator who rewrites
    # a prompt in the UI is re-checked automatically. Only `base_prompt` is
    # examined: the rendered form carries the channel style block and the
    # reference table, neither of which this shot's author wrote.
    for frame in board.frames:
        shot = by_id.get(frame.shot_id)
        index = shot.index if shot else -1
        findings = lint_slop(frame.base_prompt)
        blocking = blocking_slop(findings)
        for finding in findings:
            issues.append(ContinuityIssue(
                index, "slop",
                Severity.HARD if finding in blocking else Severity.WARN,
                f"{frame.frame_type.value} frame: {finding.describe()}",
                evidence=finding.text))

    # ---- camera monotony -------------------------------------------------
    run_key = None
    run_len = 0
    run_start = 0
    for shot in shots:
        key = (shot.camera_shot, shot.angle, shot.movement)
        if key == run_key:
            run_len += 1
        else:
            run_key, run_len, run_start = key, 1, shot.index
        if run_len == _MONOTONY_RUN:
            issues.append(ContinuityIssue(
                run_start, "camera", Severity.WARN,
                f"{_MONOTONY_RUN} consecutive shots from {shot.camera_shot.value}"
                f"/{shot.angle.value}/{shot.movement.value} — this reads as a "
                f"slideshow rather than coverage"))

    # ---- board-level sanity ---------------------------------------------
    indexes = [s.index for s in shots]
    duplicates = [i for i, n in Counter(indexes).items() if n > 1]
    if duplicates:
        issues.append(ContinuityIssue(
            -1, "board", Severity.HARD,
            f"shot indexes are not unique ({sorted(duplicates)}) — order is "
            f"ambiguous and the render sequence is undefined"))

    return ContinuityReport(issues)
