"""Demo: one animated Short (9:16) with a locked cast, end to end.

WHAT THIS PROVES. The WS1 claim is that the storyboard machinery — cast
registry, reference binding, scene-only frames, clip chains that land on the
approved last still — holds one face and one room steady across every shot.
This script runs that machinery on a HAND-AUTHORED board: no LLM anywhere, so
it spends zero Claude quota and the only spend is image/video generation.

DRY-RUN IS THE DEFAULT. Run it bare and it plans everything, prints every
prompt it would send and every clip it would buy, writes plan.json with the
signed billable count — and generates NOTHING. That is Orkas gate C as a CLI
default: the operator sees the exact bill before any of it is spent.

    python scripts/demo_anim_short.py            # plan + prompts + bill, free
    python scripts/demo_anim_short.py --go       # generate stills + clips
    python scripts/demo_anim_short.py --go --skip-video   # stills only

The fixture is original IP (a paper fox in a lantern workshop) in a
hand-painted 2D style described by physical properties, never by studio names
— the seedance copyright rewrite rules, applied at authoring time.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

_IMPL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_IMPL / "src"))

from omnicast.pipeline import edl                                    # noqa: E402
from omnicast.storyboard import store                                # noqa: E402
from omnicast.storyboard.clips import plan_shot_chain, render_shot_chain  # noqa: E402
from omnicast.storyboard.frames import (                             # noqa: E402
    FramePromptSet,
    build_frames_for_shot,
    generate_frame_image,
)
from omnicast.storyboard.models import (                             # noqa: E402
    Angle,
    BoardStatus,
    CameraShot,
    Entity,
    EntityImage,
    EntityKind,
    FrameType,
    ImageSource,
    Movement,
    RefRole,
    ScreenDirection,
    Shot,
    ShotEntityRef,
    Storyboard,
)
from omnicast.storyboard.refsheet import build_all_sheets            # noqa: E402

BOARD_ID = "sb_demo_miko_lantern"
SLUG = "miko_lantern_ep1"
OUT_DIR = _IMPL / "output" / "products" / "anim_demo" / SLUG
VERTICAL = (1080, 1920)

STYLE = ("hand-painted 2D animation, visible watercolor paper grain, soft "
         "rounded character silhouettes, warm amber palette with deep blue "
         "shadows, gentle painted light")
NEGATIVE = "photorealistic, 3D render, live action"


# --------------------------------------------------------------------------
# Fixture board — authored, not extracted
# --------------------------------------------------------------------------

def build_board() -> Storyboard:
    hero = Entity(
        entity_id="e_miko", board_id=BOARD_ID, kind=EntityKind.CHARACTER,
        name="Miko", aliases=["the paper fox"],
        description=("a small fox folded from cream washi paper, visible fold "
                     "lines along the back, round amber eyes, a torn left ear, "
                     "wears a stitched indigo scarf"),
        view_count=3)
    workshop = Entity(
        entity_id="e_workshop", board_id=BOARD_ID, kind=EntityKind.LOCATION,
        name="the lantern workshop",
        description=("a cramped wooden workshop at night, one low workbench, "
                     "shelves of unlit paper lanterns, a single hanging bulb, "
                     "moonlight through one round window"),
        view_count=2)
    lantern = Entity(
        entity_id="e_lantern", board_id=BOARD_ID, kind=EntityKind.PROP,
        name="the unfinished lantern",
        description=("a half-folded red paper lantern with a bamboo rib "
                     "showing through a gap, no light inside"),
        view_count=1)

    shots = [
        Shot(shot_id="s1", board_id=BOARD_ID, index=0,
             title="Miko finds the unfinished lantern",
             voiceover="In a workshop that smelled of paper and glue, "
                       "someone small was still awake.",
             location_id="e_workshop",
             cast=[ShotEntityRef(entity_id="e_miko", index=0),
                   ShotEntityRef(entity_id="e_lantern", index=1)],
             camera_shot=CameraShot.LS, angle=Angle.EYE_LEVEL,
             movement=Movement.DOLLY_IN, duration_s=6.0,
             action_beats=["Miko pads across the workbench toward the "
                           "unfinished lantern"],
             screen_direction=ScreenDirection.LEFT_TO_RIGHT,
             light_key="single hanging bulb from above, moonlight rim from "
                       "the round window",
             time_of_day="night",
             planned_start_state="Miko at the left edge of the workbench, "
                                 "lantern at the right",
             observed_end_state="Miko sits before the unfinished lantern",
             beats_reserved=["the lantern lights up"]),
        Shot(shot_id="s2", board_id=BOARD_ID, index=1,
             title="Paper paws try to close the fold",
             voiceover="The last fold was always the hardest.",
             location_id="e_workshop",
             cast=[ShotEntityRef(entity_id="e_miko", index=0),
                   ShotEntityRef(entity_id="e_lantern", index=1)],
             camera_shot=CameraShot.CU, angle=Angle.HIGH_ANGLE,
             movement=Movement.STATIC, duration_s=6.0,
             action_beats=["Miko presses the loose paper fold flat with both "
                           "front paws, and it springs back open"],
             screen_direction=ScreenDirection.NEUTRAL,
             light_key="bulb light pooled on the workbench",
             time_of_day="night",
             parent_shot_id="s1",
             planned_start_state="Miko seated before the lantern, paws "
                                 "raised toward the open fold",
             observed_end_state="the fold springs open; Miko's ears drop",
             beats_completed=["Miko crossed the workbench to the lantern"],
             beats_reserved=["the lantern lights up"]),
        Shot(shot_id="s3", board_id=BOARD_ID, index=2,
             title="The torn ear trick",
             voiceover="But a paper fox knows what paper wants.",
             location_id="e_workshop",
             cast=[ShotEntityRef(entity_id="e_miko", index=0),
                   ShotEntityRef(entity_id="e_lantern", index=1)],
             camera_shot=CameraShot.MCU, angle=Angle.EYE_LEVEL,
             movement=Movement.STATIC, duration_s=12.0,
             action_beats=[
                 "Miko tilts his head, studying the gap in the lantern",
                 "he folds his own torn left ear forward, mirroring the "
                 "crease the lantern needs"],
             screen_direction=ScreenDirection.NEUTRAL,
             light_key="bulb light from above, face half in warm light",
             time_of_day="night",
             parent_shot_id="s2",
             planned_start_state="Miko close to the lantern, ears low, the "
                                 "fold open between his paws",
             observed_end_state="Miko holds his folded ear beside the "
                                "lantern's gap, eyes steady",
             beats_completed=["the fold sprang back open"],
             beats_reserved=["the lantern lights up"]),
        Shot(shot_id="s4", board_id=BOARD_ID, index=3,
             title="The lantern lights",
             voiceover="And this time, the fold held.",
             location_id="e_workshop",
             cast=[ShotEntityRef(entity_id="e_miko", index=0),
                   ShotEntityRef(entity_id="e_lantern", index=1)],
             camera_shot=CameraShot.MS, angle=Angle.EYE_LEVEL,
             movement=Movement.DOLLY_OUT, duration_s=6.0,
             action_beats=["the closed lantern glows warm red from inside, "
                           "light spreading across Miko's paper fur"],
             screen_direction=ScreenDirection.NEUTRAL,
             light_key="the lit lantern becomes the key light, bulb now dim",
             time_of_day="night",
             parent_shot_id="s3",
             planned_start_state="the lantern closed and dark, Miko's paws "
                                 "resting on it",
             observed_end_state="Miko lit warm red beside the glowing "
                                "lantern, workshop dark around them",
             beats_completed=["Miko folded the last crease flat"],
             declared_changes=["the lantern is now lit — the key light "
                               "changes to warm red from the lantern"]),
    ]

    return Storyboard(
        board_id=BOARD_ID, channel_id="anim_demo", product_slug=SLUG,
        title="Miko and the Unfinished Lantern",
        status=BoardStatus.DRAFT, style_prompt=STYLE,
        negative_prompt=NEGATIVE,
        entities=[hero, workshop, lantern], shots=shots)


#: Handwritten picture descriptions — what the FramePromptAgent would write in
#: production, authored here so the demo is deterministic and LLM-free. Every
#: line follows the frame agent's own rules: visible facts, exact names, no
#: evaluators, no camera words (camera is appended from the shot record).
PROMPTS: dict[str, FramePromptSet] = {
    "s1": FramePromptSet(
        first="Miko stands at the left edge of the workbench in the lantern "
              "workshop, body low, looking across at the unfinished lantern "
              "on the right, shelves of unlit lanterns behind.",
        last="Miko sits on his haunches directly before the unfinished "
             "lantern on the workbench, tail curled around his paws, the "
             "round window bright behind them."),
    "s2": FramePromptSet(
        first="Seen from above, Miko's cream paper paws press against the "
              "open red fold of the unfinished lantern on the workbench.",
        last="The red paper fold stands sprung open between Miko's paws, "
             "his ears folded flat against his head."),
    "s3": FramePromptSet(
        first="Miko leans close to the unfinished lantern, nose near its "
              "open gap, ears low, the bamboo rib visible through the paper.",
        last="Miko holds his torn left ear folded forward beside the "
             "lantern's gap, the two creases matching, his amber eyes "
             "steady on it."),
    "s4": FramePromptSet(
        first="The lantern sits closed and dark on the workbench, complete, "
              "Miko's paws resting on its top seam.",
        last="The closed lantern glows warm red from inside, red light "
             "across Miko's paper fur and the workbench, the hanging bulb "
             "dim, the workshop dark beyond."),
}


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------

async def stage_sheets(board: Storyboard, provider, go: bool) -> Storyboard:
    if not go:
        print(f"[dry] would generate reference sheets for "
              f"{len(board.entities)} entities "
              f"({sum(e.view_count for e in board.entities)} stills)")
        return board
    board = await build_all_sheets(board, provider, auto_approve=True)
    board = board.model_copy(update={"status": BoardStatus.CAST_APPROVED})
    return board


def stage_frames(board: Storyboard) -> Storyboard:
    frames, notes = [], list(board.notes)
    for shot in sorted(board.shots, key=lambda s: s.index):
        shot_frames, shot_notes = build_frames_for_shot(
            shot, board, PROMPTS[shot.shot_id], vertical_safe=True)
        frames.extend(shot_frames)
        notes.extend(shot_notes)
    return board.model_copy(update={"frames": frames, "notes": notes,
                                    "status": BoardStatus.FRAMES_READY})


async def stage_render_frames(board: Storyboard, provider, go: bool
                              ) -> Storyboard:
    out = OUT_DIR / "frames"
    frames, notes = [], list(board.notes)
    for frame in board.frames:
        if not go:
            frames.append(frame)
            continue
        shot = board.shot(frame.shot_id)
        dst = out / f"{shot.index:03d}_{frame.frame_type.value}.png"
        updated, note = await generate_frame_image(
            frame, provider, str(dst), resolution=VERTICAL)
        updated = updated.model_copy(update={"approved": bool(updated.image_path)})
        frames.append(updated)
        if note:
            notes.append(note)
    return board.model_copy(update={"frames": frames, "notes": notes})


def _frame_path(shot: Shot, frame) -> str:
    """The still's real path, or where it WILL land — so a dry-run plans the
    same chain (including first→last clips) the paid run executes."""
    if frame is None:
        return ""
    if frame.image_path:
        return frame.image_path
    return str(OUT_DIR / "frames"
               / f"{shot.index:03d}_{frame.frame_type.value}.png")


def make_plan(board: Storyboard) -> tuple[edl.VideoPlan, dict[str, list]]:
    """Every shot → its clip chain; every clip → one generate segment."""
    segments: list[edl.Segment] = []
    chains: dict[str, list] = {}
    order = 0
    for shot in sorted(board.shots, key=lambda s: s.index):
        first = next((f for f in board.frames_for(shot.shot_id)
                      if f.frame_type in (FrameType.FIRST, FrameType.KEY)), None)
        last = next((f for f in board.frames_for(shot.shot_id)
                     if f.frame_type is FrameType.LAST), None)
        plans = plan_shot_chain(
            shot, shot.duration_s or 6.0,
            _frame_path(shot, first),
            end_anchor=_frame_path(shot, last))
        chains[shot.shot_id] = plans
        for plan in plans:
            segments.append(edl.Segment(
                segment_id=f"{shot.shot_id}_c{plan.ordinal}", order=order,
                role=edl.SegmentRole.HOOK if shot.index == 0
                else edl.SegmentRole.BODY,
                source=edl.SegmentSource.GENERATE,
                target_sec=float(plan.seconds),
                spec={"prompt": plan.prompt, "start_frame": plan.start_frame,
                      "end_frame": plan.end_frame, "shot_id": shot.shot_id,
                      "ordinal": plan.ordinal}))
            order += 1

    narration = [edl.NarrationLine(line_id=f"n_{s.shot_id}", text=s.voiceover,
                                   target_sec=s.duration_s)
                 for s in sorted(board.shots, key=lambda s: s.index)]
    plan = edl.VideoPlan(
        plan_id=f"plan_{uuid.uuid4().hex[:8]}", channel_id=board.channel_id,
        aspect="9:16",
        total_target_sec=sum(s.duration_s for s in board.shots),
        delivery_promise=edl.DeliveryPromise(type=edl.PromiseType.MOTION_LED),
        segments=segments,
        tracks=edl.Tracks(narration=narration),
        billable_generations=len(segments))
    return plan, chains


async def stage_video(board: Storyboard, plan: edl.VideoPlan, go: bool
                      ) -> edl.VideoPlan:
    if not go:
        return plan
    from omnicast.media.providers.video_gemini import GeminiVideoProvider
    provider = GeminiVideoProvider()
    for shot in sorted(board.shots, key=lambda s: s.index):
        first = next((f for f in board.frames_for(shot.shot_id)
                      if f.frame_type in (FrameType.FIRST, FrameType.KEY)), None)
        last = next((f for f in board.frames_for(shot.shot_id)
                     if f.frame_type is FrameType.LAST), None)
        if first is None or not first.image_path:
            plan = plan.model_copy(update={"notes": [
                *plan.notes, f"shot {shot.index}: no first still — skipped"]})
            continue
        result = await render_shot_chain(
            shot, shot.duration_s or 6.0, first.image_path, provider,
            OUT_DIR / "clips",
            end_anchor=(last.image_path if last else ""),
            resolution=VERTICAL)
        for clip in result.clips:
            if clip.path:
                plan = plan.with_produced(
                    f"{shot.shot_id}_c{clip.ordinal}", clip.path)
        plan = plan.model_copy(update={"notes": [*plan.notes, *result.notes]})
    return plan


# --------------------------------------------------------------------------

async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--go", action="store_true",
                    help="actually generate (bills image + video credits)")
    ap.add_argument("--skip-video", action="store_true",
                    help="with --go: stills only, no Veo clips")
    args = ap.parse_args()
    go = args.go

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    board = build_board()

    provider = None
    if go:
        from omnicast.media.providers.registry import get_image_provider
        provider = get_image_provider("gemini")

    board = await stage_sheets(board, provider, go)
    board = stage_frames(board)
    board = await stage_render_frames(board, provider, go)
    store.save_board(board)

    plan, chains = make_plan(board)
    issues = edl.validate_plan(plan)
    if issues:
        print("PLAN ISSUES (blocking):")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    if go and not args.skip_video:
        plan = await stage_video(board, plan, go)
    edl.save_plan(plan, OUT_DIR)

    # ---- The bill, and the proof ----------------------------------------
    stills = sum(e.view_count for e in board.entities) + len(board.frames)
    print(f"\nBoard {board.board_id}: {len(board.entities)} cast, "
          f"{len(board.shots)} shots, {len(board.frames)} frames")
    print(f"plan.json: {len(plan.segments)} clip segments, "
          f"billable_generations={plan.billable_generations}, "
          f"~{stills} stills")
    delivery = edl.assess_delivery(plan)
    print(f"promise: motion_ratio={delivery['motion_ratio']} "
          f"floor={delivery['floor']} ok={delivery['ok']}")
    if not go:
        print("\n[dry-run] Nothing was generated. Prompts that WOULD be sent:")
        for shot_id, plans in chains.items():
            for p in plans:
                flf = " [first->last]" if p.end_frame else ""
                print(f"\n--- {shot_id} clip {p.ordinal}{flf} ---")
                print(p.prompt)
        print(f"\nRun with --go to generate. Artifacts land in {OUT_DIR}")
    else:
        print(f"\nArtifacts in {OUT_DIR}")
        for note in plan.notes:
            print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
