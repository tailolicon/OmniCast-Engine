"""Storyboard API — cast approval, frame bindings, continuity gate.

Mounted by `server.py` alongside the render routes. The UI this serves is the
approval barrier: `omnicast/storyboard/pipeline.py` deliberately stops at
`cast_pending` and waits for a human, and these endpoints are how that human
answers.

LONG WORK RUNS IN THE BACKGROUND. Building reference sheets is tens of image
generations; rendering frames is more. Both would blow any sane HTTP timeout,
so they return immediately and the client polls `GET /api/storyboards/{id}`,
whose `status` already models the flow. `_IN_FLIGHT` prevents the same board
being worked twice concurrently — two sheet builds racing on one entity would
each write `front.png` and the winner would be whichever finished last.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from fastapi.responses import JSONResponse

from omnicast.storyboard import pipeline, store
from omnicast.storyboard.continuity import check_continuity
from omnicast.storyboard.frames import rebind_frame
from omnicast.storyboard.models import (
    BoardStatus,
    EntityImage,
    ImageSource,
    Storyboard,
)
from omnicast.storyboard.refsheet import SHEET_DIR, generate_sheet, sheet_dir

storyboard_router = APIRouter(prefix="/api/storyboards", tags=["storyboard"])

#: Boards currently being worked on by a background task.
_IN_FLIGHT: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _board_or_404(board_id: str) -> Storyboard:
    board = store.load_board(board_id)
    if board is None:
        raise HTTPException(404, f"storyboard '{board_id}' not found")
    return board


def _url_for(path: str) -> str:
    """Filesystem path → `/sbmedia/...` URL, or "" if it is not servable.

    The browser cannot open `E:\\...\\output\\_storyboard\\...`, and a broken
    <img> in the cast screen is indistinguishable from a missing reference —
    which is precisely the state a human is here to judge.
    """
    if not path:
        return ""
    try:
        rel = Path(path).resolve().relative_to(SHEET_DIR.resolve())
    except (ValueError, OSError):
        return ""
    return "/sbmedia/" + "/".join(rel.parts)


def _with_urls(board_json: dict) -> dict:
    for entity in board_json.get("entities", []):
        for image in entity.get("images", []):
            image["url"] = _url_for(image.get("path", ""))
    for frame in board_json.get("frames", []):
        frame["url"] = _url_for(frame.get("image_path", ""))
        for mapping in frame.get("mappings", []):
            mapping["url"] = _url_for(mapping.get("path", ""))
    return board_json


def _serialize(board: Storyboard) -> dict:
    """Board as the UI needs it: the graph plus the derived state it renders.

    `cast_ready`, `unready` and the continuity report are computed here rather
    than in the client so the browser and the gate can never disagree about
    whether a board may proceed.
    """
    report = check_continuity(board) if board.frames else None
    used = {eid for s in board.shots for eid in s.entity_ids()}
    return {
        "board": _with_urls(board.model_dump(mode="json")),
        "derived": {
            "cast_ready": board.cast_ready,
            "unready": [
                {"entity_id": e.entity_id, "name": e.name,
                 "reason": (e.conflicts[0] if e.conflicts
                            else "no approved reference image")}
                for e in board.unready_entities()
            ],
            "used_entity_ids": sorted(used),
            "working": board.board_id in _IN_FLIGHT,
            "continuity": report.as_dict() if report else None,
        },
    }


# --------------------------------------------------------------------------
# Boards
# --------------------------------------------------------------------------

@storyboard_router.get("")
async def list_storyboards(channel_id: str | None = None,
                           status: str | None = None) -> JSONResponse:
    try:
        parsed = BoardStatus(status) if status else None
    except ValueError:
        raise HTTPException(400, f"unknown status '{status}'")
    rows = store.list_boards(channel_id, parsed)
    for row in rows:
        row["working"] = row["board_id"] in _IN_FLIGHT
    return JSONResponse({"boards": rows})


@storyboard_router.get("/{board_id}")
async def get_storyboard(board_id: str) -> JSONResponse:
    return JSONResponse(_serialize(_board_or_404(board_id)))


@storyboard_router.post("")
async def create_storyboard(payload: dict = Body(...)) -> JSONResponse:
    """Script → cast + shots. Synchronous: this is two LLM calls, not hundreds."""
    channel_id = str(payload.get("channel_id") or "").strip()
    script_text = str(payload.get("script_text") or "").strip()
    if not channel_id or not script_text:
        raise HTTPException(400, "channel_id and script_text are required")

    try:
        channel = pipeline.load_channel(channel_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))

    cfg = pipeline.config_for(channel)
    if not cfg.get("enabled"):
        raise HTTPException(
            400,
            f"channel '{channel_id}' has no storyboard block enabled. Add "
            f'"storyboard": {{"enabled": true}} to its config first — building '
            f"a cast for a channel that renders stock footage would spend "
            f"credit on images nothing attaches.")

    from omnicast.capabilities.llm_factory import create_llm
    from omnicast.storyboard.extract import StoryboardExtractorAgent
    from omnicast.storyboard.merge import StoryboardMergerAgent

    llm = create_llm("deepseek", role="storyboard")
    try:
        board = await pipeline.start_board(
            script_text=script_text, channel_id=channel_id, channel=channel,
            title=str(payload.get("title") or ""),
            product_slug=str(payload.get("product_slug") or ""),
            extractor=StoryboardExtractorAgent(llm),
            merger=StoryboardMergerAgent(llm),
            reuse=bool(payload.get("reuse", True)),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"extraction failed: {exc}")
    return JSONResponse(_serialize(board))


@storyboard_router.delete("/{board_id}")
async def delete_storyboard(board_id: str) -> JSONResponse:
    _board_or_404(board_id)
    if board_id in _IN_FLIGHT:
        raise HTTPException(409, "board is being worked on — try again shortly")
    store.delete_board(board_id)
    return JSONResponse({"deleted": board_id})


# --------------------------------------------------------------------------
# Cast + reference sheets
# --------------------------------------------------------------------------

async def _run_prepare_cast(board_id: str) -> None:
    try:
        board = store.load_board(board_id)
        if board is None:
            return
        await pipeline.prepare_cast(board_id,
                                    channel=pipeline.load_channel(board.channel_id))
    except Exception as exc:  # noqa: BLE001 — surface on the board, never crash
        board = store.load_board(board_id)
        if board is not None:
            store.save_board(board.model_copy(update={
                "notes": [*board.notes, f"reference sheet build failed: {exc}"]}))
    finally:
        _IN_FLIGHT.discard(board_id)


@storyboard_router.post("/{board_id}/cast/prepare")
async def prepare_cast(board_id: str, background: BackgroundTasks) -> JSONResponse:
    _board_or_404(board_id)
    if board_id in _IN_FLIGHT:
        raise HTTPException(409, "reference sheets are already being built")
    _IN_FLIGHT.add(board_id)
    background.add_task(_run_prepare_cast, board_id)
    return JSONResponse({"started": True, "board_id": board_id})


@storyboard_router.post("/{board_id}/images/{image_id}/approve")
async def approve_image(board_id: str, image_id: str,
                        payload: dict = Body(default={})) -> JSONResponse:
    _board_or_404(board_id)
    store.set_image_approved(image_id, bool(payload.get("approved", True)))
    return JSONResponse(_serialize(_board_or_404(board_id)))


#: Accepted upload types, by the magic bytes rather than by the filename — a
#: caller-supplied extension is a claim, not evidence.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"RIFF", ".webp"),
    (b"GIF8", ".gif"),
)


@storyboard_router.post("/{board_id}/entities/{entity_id}/upload")
async def upload_reference(board_id: str, entity_id: str,
                           payload: dict = Body(...)) -> JSONResponse:
    """Attach an operator image. Approved on arrival and never outvoted.

    Takes base64 (`data` may be a bare payload or a `data:` URL) rather than
    multipart. Multipart would pull in `python-multipart`, and adding a
    dependency to accept a file the browser can just as easily send as a data
    URL is not a trade worth making — especially since the import failure mode
    is silent router loss at startup.
    """
    board = _board_or_404(board_id)
    entity = board.entity(entity_id)
    if entity is None:
        raise HTTPException(404, f"entity '{entity_id}' not on this board")

    raw = str(payload.get("data") or "")
    if "," in raw and raw.strip().lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    if not raw.strip():
        raise HTTPException(400, "no image data supplied")
    import base64
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(400, "image data is not valid base64")
    if not blob:
        raise HTTPException(400, "uploaded file was empty")

    suffix = next((ext for magic, ext in _MAGIC if blob.startswith(magic)), "")
    if not suffix:
        raise HTTPException(
            400, "unrecognised image format — send a PNG, JPEG, WebP or GIF")

    target = sheet_dir(board_id, entity_id)
    target.mkdir(parents=True, exist_ok=True)
    dst = target / f"operator_{uuid.uuid4().hex[:8]}{suffix}"
    dst.write_bytes(blob)

    store.add_entity_image(EntityImage(
        image_id=f"{entity_id}_op_{uuid.uuid4().hex[:8]}",
        entity_id=entity_id, path=str(dst), view="operator",
        role=entity.default_role, source=ImageSource.OPERATOR,
        approved=True, created_at=_now()))
    return JSONResponse(_serialize(_board_or_404(board_id)))


@storyboard_router.post("/{board_id}/entities/{entity_id}/regenerate")
async def regenerate_views(board_id: str, entity_id: str,
                           payload: dict = Body(default={})) -> JSONResponse:
    """Re-roll this entity's generated views. Operator uploads are kept."""
    board = _board_or_404(board_id)
    entity = board.entity(entity_id)
    if entity is None:
        raise HTTPException(404, f"entity '{entity_id}' not on this board")
    if board_id in _IN_FLIGHT:
        raise HTTPException(409, "board is being worked on")

    channel = pipeline.load_channel(board.channel_id)
    cfg = pipeline.config_for(channel)
    provider = pipeline.resolve_provider(cfg.get("image_provider"))
    if provider is None:
        raise HTTPException(503, f"image provider "
                                 f"'{cfg.get('image_provider')}' unavailable")

    kept = [im for im in entity.images if im.source is ImageSource.OPERATOR]
    for im in entity.images:
        if im.source is not ImageSource.OPERATOR:
            Path(im.path).unlink(missing_ok=True)

    description = str(payload.get("description") or entity.description)
    stripped = entity.model_copy(update={"images": kept,
                                         "description": description})
    filled, notes = await generate_sheet(
        stripped, provider, board_id=board_id, style_prompt=board.style_prompt,
        negative_prompt=board.negative_prompt, auto_approve=False)

    entities = [filled if e.entity_id == entity_id else e for e in board.entities]
    store.save_board(board.model_copy(update={"entities": entities,
                                              "notes": [*board.notes, *notes]}))
    return JSONResponse(_serialize(_board_or_404(board_id)))


@storyboard_router.post("/{board_id}/entities/{entity_id}/resolve-conflict")
async def resolve_conflict(board_id: str, entity_id: str) -> JSONResponse:
    """Operator has read the merge conflict and accepts this entity as-is."""
    board = _board_or_404(board_id)
    entity = board.entity(entity_id)
    if entity is None:
        raise HTTPException(404, f"entity '{entity_id}' not on this board")
    entities = [e.model_copy(update={"conflicts": []})
                if e.entity_id == entity_id else e for e in board.entities]
    store.save_board(board.model_copy(update={
        "entities": entities,
        "notes": [*board.notes,
                  f"operator resolved the merge conflict on '{entity.name}'"]}))
    return JSONResponse(_serialize(_board_or_404(board_id)))


@storyboard_router.post("/{board_id}/cast/approve")
async def approve_cast(board_id: str) -> JSONResponse:
    _board_or_404(board_id)
    try:
        pipeline.approve_cast(board_id)
    except ValueError as exc:
        # 409, not 500: the request was well-formed, the board simply is not
        # ready, and the message names every entity that is missing something.
        raise HTTPException(409, str(exc))
    return JSONResponse(_serialize(_board_or_404(board_id)))


# --------------------------------------------------------------------------
# Frames
# --------------------------------------------------------------------------

async def _run_build_frames(board_id: str) -> None:
    try:
        board = store.load_board(board_id)
        if board is None:
            return
        from omnicast.capabilities.llm_factory import create_llm
        from omnicast.storyboard.frames import FramePromptAgent
        agent = FramePromptAgent(create_llm("deepseek", role="storyboard_frames"))
        await pipeline.build_frames(
            board_id, channel=pipeline.load_channel(board.channel_id), agent=agent)
    except Exception as exc:  # noqa: BLE001
        board = store.load_board(board_id)
        if board is not None:
            store.save_board(board.model_copy(update={
                "notes": [*board.notes, f"frame build failed: {exc}"]}))
    finally:
        _IN_FLIGHT.discard(board_id)


@storyboard_router.post("/{board_id}/frames/build")
async def build_frames(board_id: str, background: BackgroundTasks) -> JSONResponse:
    board = _board_or_404(board_id)
    if board.status is BoardStatus.CAST_PENDING:
        raise HTTPException(
            409, "approve the cast first — frames must bind to references a "
                 "human has seen")
    if board_id in _IN_FLIGHT:
        raise HTTPException(409, "board is being worked on")
    _IN_FLIGHT.add(board_id)
    background.add_task(_run_build_frames, board_id)
    return JSONResponse({"started": True, "board_id": board_id})


async def _run_render_frames(board_id: str, only_missing: bool) -> None:
    try:
        board = store.load_board(board_id)
        if board is None:
            return
        await pipeline.render_frames(
            board_id, channel=pipeline.load_channel(board.channel_id),
            only_missing=only_missing)
    except Exception as exc:  # noqa: BLE001
        board = store.load_board(board_id)
        if board is not None:
            store.save_board(board.model_copy(update={
                "notes": [*board.notes, f"frame render failed: {exc}"]}))
    finally:
        _IN_FLIGHT.discard(board_id)


@storyboard_router.post("/{board_id}/frames/render")
async def render_frames(board_id: str, background: BackgroundTasks,
                        payload: dict = Body(default={})) -> JSONResponse:
    board = _board_or_404(board_id)
    if not board.frames:
        raise HTTPException(409, "no frames to render — build them first")
    if board_id in _IN_FLIGHT:
        raise HTTPException(409, "board is being worked on")
    _IN_FLIGHT.add(board_id)
    background.add_task(_run_render_frames, board_id,
                        bool(payload.get("only_missing", True)))
    return JSONResponse({"started": True, "board_id": board_id})


@storyboard_router.patch("/{board_id}/frames/{frame_id}")
async def edit_frame(board_id: str, frame_id: str,
                     payload: dict = Body(...)) -> JSONResponse:
    """Edit a frame's picture description and re-bind its tokens.

    Re-binding is not optional: an edited base prompt whose tokens still point
    at the previous reference set is the one way a hand edit can make a board
    worse than leaving it alone.
    """
    board = _board_or_404(board_id)
    frame = next((f for f in board.frames if f.frame_id == frame_id), None)
    if frame is None:
        raise HTTPException(404, f"frame '{frame_id}' not on this board")
    shot = board.shot(frame.shot_id)
    if shot is None:
        raise HTTPException(409, f"frame '{frame_id}' has no shot")

    updated = frame.model_copy(update={
        "base_prompt": str(payload.get("base_prompt", frame.base_prompt)),
        "negative_prompt": str(payload.get("negative_prompt",
                                           frame.negative_prompt)),
    })
    channel = pipeline.load_channel(board.channel_id)
    cfg = pipeline.config_for(channel)
    updated = rebind_frame(updated, shot, board,
                           max_refs=int(cfg.get("max_refs_per_frame") or 6))
    store.update_frame(updated)
    return JSONResponse(_serialize(_board_or_404(board_id)))


@storyboard_router.get("/{board_id}/continuity")
async def continuity(board_id: str) -> JSONResponse:
    return JSONResponse(check_continuity(_board_or_404(board_id)).as_dict())


@storyboard_router.post("/{board_id}/finalize")
async def finalize(board_id: str) -> JSONResponse:
    _board_or_404(board_id)
    board, report = pipeline.finalize(board_id)
    return JSONResponse({**_serialize(board), "continuity": report.as_dict()})
