"""Shots → frame prompts → reference-conditioned images.

THE DIVISION OF LABOUR. The model writes ONE thing: a picture description in
plain entity NAMES ("Minh sets the keys down in the kitchen"). It never writes
`[IMAGE 1]`, never picks which file to attach, and never decides how many
references fit. All of that is `binding.py`, deterministically, from the
registry — because those are the decisions that must be identical in shot 2 and
shot 40, and a model asked to repeat itself forty times will not.

FIRST/KEY/LAST. A static shot needs one image. A shot with camera or subject
movement needs the two ends an image-to-video model interpolates between, and
`veo_pipeline.py` already knows how to consume them. `plan_frame_types` decides
from the shot's own declared movement rather than from a global switch, so a
board mixes stills and motion the way an edit actually does.

NEIGHBOUR CONTEXT IS PASSED IN, NOT INFERRED. Each shot's prompt call receives
the previous shot's ending and the next shot's opening. Without it every shot
opens like a new scene and the cut reads as a slideshow — the same defect the
continuity gate flags structurally, addressed here at the point it is created.
"""

from __future__ import annotations

import re

import structlog
from pydantic import BaseModel, Field

from omnicast.agents.base import BaseAgent
from omnicast.storyboard import binding, slop
from omnicast.storyboard.models import (
    ANGLE_GLOSS,
    MOVEMENT_GLOSS,
    SHOT_GLOSS,
    Frame,
    FrameType,
    Movement,
    ScreenDirection,
    Shot,
    Storyboard,
)

logger = structlog.get_logger()

#: A base prompt must not contain tokens — those are assigned later, and a
#: hand-written "[IMAGE 2]" would point at whatever happens to land in slot 2.
_TOKEN_LEAK = re.compile(r"\[\s*IMAGE\s*\d+\s*\]", re.IGNORECASE)


class FramePromptSet(BaseModel):
    """Picture descriptions for one shot, in entity names."""

    first: str = Field(default="", description="The moment the shot opens on.")
    key: str = Field(default="", description="The single most telling moment.")
    last: str = Field(default="", description="The state the shot settles into.")


def plan_frame_types(shot: Shot) -> list[FrameType]:
    """Which stills this shot needs.

    FIRST+LAST when anything MOVES — the camera, or the subject. The first
    cut of this function checked only the camera, so a locked-off shot whose
    action visibly changes the scene ("the fold springs open") got a single
    KEY still: no end state to interpolate toward, no canonical frame for the
    chain to land on, and the successor's opening had nothing to match. A
    declared action beat is subject movement by definition.
    """
    if shot.movement is Movement.STATIC and not shot.action_beats:
        return [FrameType.KEY]
    return [FrameType.FIRST, FrameType.LAST]


def frame_id_for(shot_id: str, frame_type: FrameType) -> str:
    return f"f_{shot_id}_{frame_type.value}"


def strip_token_leak(text: str) -> tuple[str, bool]:
    """Remove any `[IMAGE n]` the model emitted. Returns `(clean, leaked)`."""
    cleaned = _TOKEN_LEAK.sub("", text or "")
    leaked = cleaned != (text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip(), leaked


def camera_line(shot: Shot) -> str:
    return (f"{SHOT_GLOSS.get(shot.camera_shot, shot.camera_shot.value)}, "
            f"{ANGLE_GLOSS.get(shot.angle, shot.angle.value)}, "
            f"{MOVEMENT_GLOSS.get(shot.movement, shot.movement.value)}")


#: How a screen-direction token reads to an image model.
_DIRECTION_GLOSS = {
    ScreenDirection.LEFT_TO_RIGHT: "subject oriented and moving toward frame right",
    ScreenDirection.RIGHT_TO_LEFT: "subject oriented and moving toward frame left",
    ScreenDirection.TOWARD_CAMERA: "subject facing toward the camera",
    ScreenDirection.AWAY_FROM_CAMERA: "subject facing away from the camera",
}


def continuity_line(shot: Shot) -> str:
    """The shot's declared anchors, appended verbatim to its prompt.

    THE BUG THIS FIXES, found on the first paid run. Every anchor was being
    extracted, stored, and checked against its neighbours — and never sent to
    the image model. Shot 5 declared `time_of_day=NIGHT`, `light_key=LOW_KEY`,
    and came back in broad daylight with green foliage through the window,
    because nothing in its prompt had ever mentioned night. The gate could not
    catch it either: it compares shots to each OTHER, and every shot agreed it
    was night, so there was no drift to see. A field the renderer never reads
    is a field that only documents an intention.

    Composed deterministically, like `camera_line`, so what the record says and
    what the model is told cannot diverge.
    """
    parts: list[str] = []
    if shot.time_of_day.strip():
        parts.append(shot.time_of_day.strip())
    if shot.light_key.strip():
        parts.append(f"key light {shot.light_key.strip()}")
    gloss = _DIRECTION_GLOSS.get(shot.screen_direction)
    if gloss:
        parts.append(gloss)
    if shot.eyeline.strip():
        parts.append(f"eyeline {shot.eyeline.strip()}")
    return ", ".join(parts)


def _carry_render(new: Frame, previous: Frame | None) -> tuple[Frame, str]:
    """Keep an already-rendered image when the prompt did not change.

    THE BUG THIS FIXES, found while cutting the first animatic. Rebuilding
    frame prompts constructed fresh `Frame` objects with `image_path=""`, so
    every rerun of the frame stage silently threw away every image that had
    already been paid for — and the next render bought them all again. The
    board still looked healthy; only the empty paths in the database showed it.

    When the rendered prompt DID change the image is genuinely stale and is
    dropped, because keeping it would leave a picture on the board that no
    longer matches the words underneath it. That is said out loud rather than
    done quietly, since it is a real cost.
    """
    if previous is None or not previous.image_path:
        return new, ""
    if previous.rendered_prompt == new.rendered_prompt:
        return new.model_copy(update={
            "image_path": previous.image_path,
            "approved": previous.approved,
            "attempts": previous.attempts}), ""
    return new, (f"{new.frame_type.value} frame: prompt changed, so the "
                 f"existing render no longer matches it and was dropped — "
                 f"this frame must be generated again")


#: Appended when a board renders for a vertical (Shorts) canvas. Two jobs in
#: one clause: the top/bottom fifths are where YouTube's own UI and burned
#: captions live, and a centred subject survives a later 3:4 / 1:1 crop for
#: other surfaces — the same frame serves every aspect the channel ships.
_VERTICAL_STAGING = ("Staging: keep the subject and the primary action centred "
                     "in frame, clear of the top and bottom fifths; the outer "
                     "edges stay environment only")


def build_frames_for_shot(
    shot: Shot,
    board: Storyboard,
    prompts: FramePromptSet,
    *,
    max_refs: int = binding.MAX_REFS_DEFAULT,
    vertical_safe: bool = False,
) -> tuple[list[Frame], list[str]]:
    """Bound, ready-to-send frames for one shot. Returns `(frames, notes)`."""
    notes: list[str] = []
    existing = {f.frame_id: f for f in board.frames_for(shot.shot_id)}
    mappings, dropped = binding.build_mappings(shot, board, max_refs=max_refs)
    for item in dropped:
        notes.append(f"shot {shot.index}: reference dropped — {item}")

    frames: list[Frame] = []
    for frame_type in plan_frame_types(shot):
        raw = getattr(prompts, frame_type.value, "") or prompts.key or prompts.first
        base, leaked = strip_token_leak(raw)
        if leaked:
            notes.append(
                f"shot {shot.index} {frame_type.value}: prompt contained an "
                f"[IMAGE n] token written by the model — stripped, because "
                f"tokens are assigned from the registry, not authored")
        if not base:
            notes.append(f"shot {shot.index}: no {frame_type.value} prompt was "
                         f"produced — frame skipped")
            continue

        # Reported at build time for visibility; the continuity gate re-lints
        # at check time so a prompt edited in the UI cannot slip past.
        for finding in slop.lint(base):
            notes.append(f"shot {shot.index} {frame_type.value}: slop — "
                         f"{finding.describe()}")

        # Camera and continuity are appended deterministically rather than
        # trusted to the model, so the record and the prompt cannot disagree.
        base = f"{base}\n\nCamera: {camera_line(shot)}."
        anchors = continuity_line(shot)
        if anchors:
            base = f"{base}\nContinuity: {anchors}."
        if vertical_safe:
            base = f"{base}\n{_VERTICAL_STAGING}."
        rendered = binding.compose_rendered_prompt(
            base_prompt=base, mappings=mappings,
            style_prompt=board.style_prompt, board=board)

        for issue in binding.binding_issues(rendered_prompt=rendered,
                                            mappings=mappings, board=board):
            notes.append(f"shot {shot.index} {frame_type.value}: {issue}")

        frame_id = frame_id_for(shot.shot_id, frame_type)
        built = Frame(
            frame_id=frame_id, shot_id=shot.shot_id, frame_type=frame_type,
            base_prompt=base, rendered_prompt=rendered,
            negative_prompt=board.negative_prompt, mappings=mappings)
        built, carry_note = _carry_render(built, existing.get(frame_id))
        if carry_note:
            notes.append(f"shot {shot.index} {carry_note}")
        frames.append(built)
    return frames, notes


def rebind_frame(frame: Frame, shot: Shot, board: Storyboard,
                 *, max_refs: int = binding.MAX_REFS_DEFAULT) -> Frame:
    """Recompute a frame's tokens after its cast or base prompt was edited.

    The UI needs this: an operator who swaps a reference image or rewrites a
    line must not be left with a rendered prompt whose tokens still point at
    the previous set.
    """
    mappings, _dropped = binding.build_mappings(shot, board, max_refs=max_refs)
    rendered = binding.compose_rendered_prompt(
        base_prompt=frame.base_prompt, mappings=mappings,
        style_prompt=board.style_prompt, board=board)
    return frame.model_copy(update={"mappings": mappings,
                                    "rendered_prompt": rendered})


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

async def generate_frame_image(frame: Frame, provider, output_path: str,
                               *, resolution: tuple[int, int] | None = None
                               ) -> tuple[Frame, str]:
    """Render one frame with its references attached. Returns `(frame, note)`.

    A provider that cannot take references still gets the prompt — the tokens
    read as ordinary nouns and the result is a plausible-but-unanchored image.
    That degradation is REPORTED, never silent, because "we had references" and
    "the references were used" are different claims.
    """
    if provider is None:
        return frame, "no image provider configured"

    kwargs: dict = {"negative": frame.negative_prompt, "output_path": output_path}
    note = ""
    if frame.mappings:
        if getattr(provider, "supports_reference_images", False):
            cap = int(getattr(provider, "max_reference_images", 8) or 8)
            maps = frame.mappings[:cap]
            if len(maps) < len(frame.mappings):
                note = (f"provider accepts {cap} references but the frame has "
                        f"{len(frame.mappings)}; dropped "
                        + ", ".join(m.name for m in frame.mappings[cap:]))
            kwargs["reference_images"] = [m.path for m in maps]
            kwargs["reference_labels"] = [m.token for m in maps]
        else:
            note = (f"provider '{getattr(provider, 'id', '?')}' ignores "
                    f"reference images — this frame's {len(frame.mappings)} "
                    f"reference(s) did NOT condition the result")
    if resolution:
        kwargs["resolution"] = resolution

    try:
        await provider.generate(frame.rendered_prompt, **kwargs)
    except Exception as exc:  # noqa: BLE001 — a failed frame is data, not a crash
        return frame.model_copy(update={"attempts": frame.attempts + 1}), \
            f"frame {frame.frame_id} failed: {str(exc)[:160]}"

    return frame.model_copy(update={"image_path": output_path,
                                    "attempts": frame.attempts + 1}), note


# --------------------------------------------------------------------------
# The LLM stage
# --------------------------------------------------------------------------

_SYSTEM = """You write the picture for one storyboard shot.

WRITE WHAT IS VISIBLE. Concrete subjects, where they are, what they are doing, \
the light, the composition. Not their feelings, not the plot, not what the \
narration says. If it cannot be photographed, it does not belong in the prompt.

USE THE EXACT CAST NAMES you are given, spelled character for character. They \
are substituted mechanically afterwards; a paraphrase ("the man", "the older \
woman") breaks the substitution and the model then invents that person.

NEVER write "[IMAGE 1]", "image 1", or any reference numbering. Those are \
assigned by the system after you. Write names.

NEVER write the camera size, angle or movement — those are appended from the \
shot record so the words and the data cannot disagree.

NO EMPTY EVALUATORS. "Cinematic", "dramatic", "beautiful", "stunning", \
"atmospheric", "moody", "epic" name no camera, no light and no lens — the \
model cannot tell which element to emphasise, so the picture destabilises. \
Write the observable that would have earned the word: not "dramatic lighting" \
but "one bulb above the table, his face half out of it". This is checked \
mechanically and it BLOCKS, hardest in your first clause — never open on an \
evaluator.

NO IMAGE-MODEL TOKENS: "8K", "masterpiece", "highly detailed", "award-winning", \
"trending on artstation", "unreal engine". They are settings or outcomes, \
never prose.

NEVER NEGATE. "No blur, no watermark, no extra fingers" plants exactly what it \
forbids. Lock the positive instead: "hands rest still on the table", "the \
label is clean and unbroken". Exclusions are handled elsewhere.

NO TAG SALAD. Write sentences, not comma-separated keywords. A keyword dump \
gives a video model no action and no time axis.

FRAMES:
- `first`: the moment the shot OPENS on. Trigger or first reaction only, in an \
  unfinished state — not the completed action, not the emotional peak.
- `last`: where the shot SETTLES. The finished gesture, the held look.
- `key`: for a shot rendered as a single still — its most telling instant.
Produce only the frames you are asked for; leave the others empty.

CONTINUE FROM THE PREVIOUS SHOT. You are given how it ended. Keep positions, \
screen direction, light and wardrobe unless the shot declares a change. Do not \
re-establish a place the audience is already standing in.

Output JSON only."""


class FramePromptAgent(BaseAgent):
    """Shot (+ neighbours) → `FramePromptSet` in entity names."""

    @property
    def name(self) -> str:
        return "storyboard_frame_prompt"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    async def execute(self, shot: Shot, board: Storyboard, *,
                      previous: Shot | None = None,
                      following: Shot | None = None) -> FramePromptSet:
        wanted = [t.value for t in plan_frame_types(shot)]

        cast_lines = []
        for entity_id in shot.entity_ids():
            entity = board.entity(entity_id)
            if entity is None:
                continue
            cast_lines.append(
                f"- {entity.name} ({entity.kind.value})"
                + (f": {entity.description[:200]}" if entity.description else ""))

        blocks = [
            f"## Shot {shot.index}: {shot.title}",
            f"Script: {shot.script_excerpt or shot.voiceover}",
            "## Cast present (use these names verbatim)\n"
            + ("\n".join(cast_lines) or "- (none)"),
        ]
        if shot.action_beats:
            blocks.append("## Action beats\n"
                          + "\n".join(f"{i + 1}. {b}"
                                      for i, b in enumerate(shot.action_beats)))
        if shot.mood:
            blocks.append(f"## Mood\n{shot.mood}")
        if previous is not None:
            blocks.append(
                f"## Previous shot ({previous.index})\n{previous.title}\n"
                f"Ended: {previous.observed_end_state or '(not recorded)'}")
        if shot.planned_start_state:
            blocks.append(f"## This shot opens on\n{shot.planned_start_state}")
        if following is not None:
            blocks.append(
                f"## Next shot ({following.index})\n{following.title}\n"
                f"Opens on: {following.planned_start_state or '(not recorded)'}")
        if shot.declared_changes:
            blocks.append("## Deliberate changes in this shot\n"
                          + "\n".join(f"- {c}" for c in shot.declared_changes))
        blocks.append(f"## Frames required\n{', '.join(wanted)}")

        _resp, parsed = await self.call_llm_structured(
            [{"role": "user", "content": "\n\n".join(blocks)}],
            FramePromptSet, max_tokens=1200, temperature=0.4)
        return parsed if isinstance(parsed, FramePromptSet) else \
            FramePromptSet.model_validate(parsed)


async def build_all_frames(board: Storyboard, agent: FramePromptAgent | None,
                           *, max_refs: int = binding.MAX_REFS_DEFAULT,
                           vertical_safe: bool = False
                           ) -> Storyboard:
    """Frame prompts + bindings for every shot on the board."""
    shots = sorted(board.shots, key=lambda s: s.index)
    frames: list[Frame] = []
    notes = list(board.notes)

    for position, shot in enumerate(shots):
        previous = shots[position - 1] if position else None
        following = shots[position + 1] if position + 1 < len(shots) else None
        if agent is None:
            # No agent: fall back to the shot's own words. Weaker, but it keeps
            # the binding path testable and gives a board that renders.
            prompts = FramePromptSet(key=shot.title or shot.script_excerpt,
                                     first=shot.title or shot.script_excerpt,
                                     last=shot.observed_end_state or shot.title)
        else:
            try:
                prompts = await agent.execute(shot, board, previous=previous,
                                              following=following)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"shot {shot.index}: frame prompt failed "
                             f"({str(exc)[:120]}) — using the shot title")
                prompts = FramePromptSet(key=shot.title, first=shot.title,
                                         last=shot.title)
        shot_frames, shot_notes = build_frames_for_shot(
            shot, board, prompts, max_refs=max_refs,
            vertical_safe=vertical_safe)
        frames.extend(shot_frames)
        notes.extend(shot_notes)

    logger.info("frames built", board=board.board_id, frames=len(frames))
    return board.model_copy(update={"frames": frames, "notes": notes})
