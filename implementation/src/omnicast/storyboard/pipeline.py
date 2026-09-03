"""Storyboard pipeline — script in, approved board out, with a human in it.

THE BARRIER IS THE POINT. Stage 2 ends at `CAST_PENDING` and stops. Nothing
generates a frame until a person has looked at the cast and its reference
sheets and pressed approve. That is not caution for its own sake: a wrong
reference image is wrong in EVERY frame that attaches it, so the cast screen is
the one place where a few seconds of human attention prevents a whole video's
worth of drift. Every other check in this package is a machine catching a
machine; this is the one place a person is cheaper than a gate.

STAGES, each persisted so a crash or a restart resumes rather than re-buys:

    start_board      script → cast + shots                     → DRAFT
    prepare_cast     reference sheets per entity               → CAST_PENDING
    ── human approves in the UI ──
    approve_cast     verify every used entity is ready         → CAST_APPROVED
    build_frames     prompts + token bindings                  → FRAMES_READY
    render_frames    images, references attached                 (unchanged)
    finalize         continuity gate                           → APPROVED|BLOCKED

RESUME IS BY SCRIPT HASH. Re-running the same script finds the existing board
instead of extracting a new one, and because entity ids are content-derived the
operator's approvals still line up.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog

from omnicast.storyboard import store
from omnicast.storyboard.continuity import ContinuityReport, check_continuity
from omnicast.storyboard.extract import (
    StoryboardExtractorAgent,
    reconcile_draft,
    script_hash,
)
from omnicast.storyboard.frames import (
    FramePromptAgent,
    build_all_frames,
    generate_frame_image,
)
from omnicast.storyboard.merge import StoryboardMergerAgent, apply_merges
from omnicast.storyboard.models import BoardStatus, Storyboard
from omnicast.storyboard.refsheet import build_all_sheets, sheet_dir

logger = structlog.get_logger()

_IMPL_ROOT = Path(__file__).resolve().parents[3]

#: Defaults for a channel that switches the storyboard on without tuning it.
DEFAULTS: dict = {
    "enabled": False,
    "image_provider": "gemini",
    "max_refs_per_frame": 6,
    "view_count": 3,
    "auto_approve_cast": False,
    "target_shots": 0,
    "operator_images": {},
    #: Shorts channels set this true: every frame is staged clear of the
    #: top/bottom fifths (YouTube UI + captions) and survives later crops.
    "vertical_safe": False,
}


def config_for(channel: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update((channel or {}).get("storyboard") or {})
    return cfg


def load_channel(channel_id: str, impl_root: Path | None = None) -> dict:
    import json
    root = impl_root or _IMPL_ROOT
    p = root / "channels" / f"{channel_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Channel config not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _style_of(channel: dict) -> tuple[str, str]:
    """Art direction for every image on this board.

    Reuses the channel fields the image path already honours
    (`image_style_prompt`/`image_style_negative`) so a channel does not have to
    describe its look twice and cannot describe it two different ways.
    """
    return (str(channel.get("image_style_prompt") or "").strip(),
            str(channel.get("image_style_negative") or "").strip())


# --------------------------------------------------------------------------
# Stage 1 — extract
# --------------------------------------------------------------------------

async def start_board(
    *,
    script_text: str,
    channel_id: str,
    channel: dict | None = None,
    title: str = "",
    product_slug: str = "",
    extractor: StoryboardExtractorAgent | None = None,
    merger: StoryboardMergerAgent | None = None,
    db_path: Path | None = None,
    reuse: bool = True,
) -> Storyboard:
    """Script → persisted draft board. Resumes an existing board by default."""
    channel = channel if channel is not None else load_channel(channel_id)
    cfg = config_for(channel)
    digest = script_hash(script_text)

    if reuse:
        existing_id = store.find_board_by_script(channel_id, digest, db_path)
        if existing_id:
            board = store.load_board(existing_id, db_path)
            if board is not None:
                logger.info("storyboard resumed", board=board.board_id,
                            status=board.status.value)
                return board

    if extractor is None:
        raise ValueError(
            "start_board needs an extractor agent (or an existing board to "
            "resume) — refusing to invent a cast without one")

    style_prompt, negative = _style_of(channel)
    draft = await extractor.execute(
        script_text,
        channel_brief=str(channel.get("brand_voice") or ""),
        target_shots=int(cfg.get("target_shots") or 0),
        visual_style=style_prompt or str(channel.get("visual_style") or ""),
    )
    board_id = f"sb_{uuid.uuid4().hex[:12]}"
    board = reconcile_draft(
        draft, board_id=board_id, channel_id=channel_id, title=title,
        product_slug=product_slug, style_prompt=style_prompt,
        negative_prompt=negative, source_script=script_text)

    if merger is not None:
        try:
            result = await merger.execute(board, script_text=script_text)
            board = apply_merges(board, result, source_script=script_text)
        except Exception as exc:  # noqa: BLE001
            # A failed merge leaves duplicates, which an operator sees and can
            # fix. Failing the whole extraction would lose the shot list too.
            board = board.model_copy(update={
                "notes": [*board.notes,
                          f"entity merge did not run ({str(exc)[:120]}) — the "
                          f"cast may contain the same person twice"]})

    store.save_board(board, db_path)
    logger.info("storyboard created", board=board.board_id,
                entities=len(board.entities), shots=len(board.shots))
    return board


# --------------------------------------------------------------------------
# Stage 2 — reference sheets, then STOP
# --------------------------------------------------------------------------

async def prepare_cast(
    board_id: str,
    *,
    channel: dict | None = None,
    provider=None,
    db_path: Path | None = None,
) -> Storyboard:
    """Build every reference sheet, then park the board for human approval."""
    board = _require(board_id, db_path)
    channel = channel if channel is not None else load_channel(board.channel_id)
    cfg = config_for(channel)

    if provider is None:
        provider = resolve_provider(cfg.get("image_provider"))

    # Operator files are keyed by NAME in channel config, because entity ids
    # are content hashes no human would type.
    by_id: dict[str, list[str]] = {}
    for name, paths in (cfg.get("operator_images") or {}).items():
        entity = board.by_name(str(name))
        if entity is None:
            board = board.model_copy(update={
                "notes": [*board.notes,
                          f"operator_images names '{name}', which is not in "
                          f"this board's cast — ignored"]})
            continue
        by_id[entity.entity_id] = list(paths or [])

    view_count = int(cfg.get("view_count") or 3)
    board = board.model_copy(update={
        "entities": [e.model_copy(update={"view_count": view_count})
                     for e in board.entities]})

    board = await build_all_sheets(
        board, provider, operator_images=by_id,
        auto_approve=bool(cfg.get("auto_approve_cast")))

    board = board.model_copy(update={"status": BoardStatus.CAST_PENDING})
    store.save_board(board, db_path)
    logger.info("cast prepared, awaiting approval", board=board_id,
                unready=[e.name for e in board.unready_entities()])
    return board


def approve_cast(board_id: str, db_path: Path | None = None) -> Storyboard:
    """Move past the barrier — only if the cast can actually hold together.

    Raises rather than warning. This function exists to be the gate; an
    "approved" board with an unreferenced character is the exact state the
    whole package is built to make impossible.
    """
    board = _require(board_id, db_path)
    unready = board.unready_entities()
    if unready:
        reasons = []
        for e in unready:
            if e.conflicts:
                reasons.append(f"{e.name}: unresolved conflict "
                               f"({e.conflicts[0][:80]})")
            else:
                reasons.append(f"{e.name}: no approved reference image")
        raise ValueError(
            "cast is not ready — " + "; ".join(reasons)
            + ". Approve an image for each, or resolve the conflict, first.")

    board = board.model_copy(update={"status": BoardStatus.CAST_APPROVED})
    store.save_board(board, db_path)
    logger.info("cast approved", board=board_id)
    return board


# --------------------------------------------------------------------------
# Stage 3 — frames
# --------------------------------------------------------------------------

async def build_frames(
    board_id: str,
    *,
    channel: dict | None = None,
    agent: FramePromptAgent | None = None,
    db_path: Path | None = None,
    require_approval: bool = True,
) -> Storyboard:
    """Frame prompts and token bindings for the whole board."""
    board = _require(board_id, db_path)
    if require_approval and board.status not in (BoardStatus.CAST_APPROVED,
                                                 BoardStatus.FRAMES_READY,
                                                 BoardStatus.BLOCKED,
                                                 BoardStatus.APPROVED):
        raise ValueError(
            f"board {board_id} is '{board.status.value}' — frames are built "
            f"after the cast is approved, so that every frame binds to a "
            f"reference a human has seen")

    channel = channel if channel is not None else load_channel(board.channel_id)
    cfg = config_for(channel)
    board = await build_all_frames(
        board, agent, max_refs=int(cfg.get("max_refs_per_frame") or 6),
        vertical_safe=bool(cfg.get("vertical_safe")))
    board = board.model_copy(update={"status": BoardStatus.FRAMES_READY})
    store.save_board(board, db_path)
    return board


async def render_frames(
    board_id: str,
    *,
    channel: dict | None = None,
    provider=None,
    resolution: tuple[int, int] | None = (1920, 1080),
    only_missing: bool = True,
    db_path: Path | None = None,
) -> Storyboard:
    """Generate the still for every frame, references attached."""
    board = _require(board_id, db_path)
    channel = channel if channel is not None else load_channel(board.channel_id)
    cfg = config_for(channel)
    if provider is None:
        provider = resolve_provider(cfg.get("image_provider"))

    out_dir = sheet_dir(board.board_id, "_frames")
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    notes = list(board.notes)
    for frame in board.frames:
        if only_missing and frame.image_path and Path(frame.image_path).exists():
            frames.append(frame)
            continue
        shot = board.shot(frame.shot_id)
        stem = f"{(shot.index if shot else 0):03d}_{frame.frame_type.value}.png"
        updated, note = await generate_frame_image(
            frame, provider, str(out_dir / stem), resolution=resolution)
        frames.append(updated)
        if note:
            notes.append(note)

    board = board.model_copy(update={"frames": frames, "notes": notes})
    store.save_board(board, db_path)
    logger.info("frames rendered", board=board_id,
                done=sum(1 for f in frames if f.image_path))
    return board


# --------------------------------------------------------------------------
# Stage 4 — gate
# --------------------------------------------------------------------------

def finalize(board_id: str, db_path: Path | None = None
             ) -> tuple[Storyboard, ContinuityReport]:
    """Run the continuity gate and set the board's terminal status."""
    board = _require(board_id, db_path)
    report = check_continuity(board)
    status = BoardStatus.BLOCKED if report.blocked else BoardStatus.APPROVED
    board = board.model_copy(update={"status": status})
    store.save_board(board, db_path)
    logger.info("storyboard finalized", board=board_id, status=status.value,
                hard=len(report.hard), warn=len(report.warnings))
    return board, report


# --------------------------------------------------------------------------

def _require(board_id: str, db_path: Path | None) -> Storyboard:
    board = store.load_board(board_id, db_path)
    if board is None:
        raise ValueError(f"storyboard '{board_id}' not found")
    return board


def resolve_provider(provider_id: str | None):
    """Image provider by id, or None with a logged reason.

    Returning None rather than raising keeps the cast stage usable offline —
    the board still gets built and the missing sheets are reported.
    """
    if not provider_id:
        return None
    try:
        from omnicast.media.providers.registry import get_image_provider
        return get_image_provider(str(provider_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("image provider unavailable", provider=provider_id,
                       error=str(exc)[:160])
        return None
