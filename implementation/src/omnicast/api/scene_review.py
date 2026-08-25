"""Scene Review Studio — per-scene audit BEFORE any full render.

The operator is the final auditor of every stage (REV7). This router exposes
each shot of a product as a reviewable unit: the REAL acquired asset (stock
clip / chart PNG / web-shot), per-scene TTS audio for a continuous rough-cut
preview, and in-place edits that persist as narration-keyed board patches so
they survive storyboard regeneration. Full render happens only after the
operator signs off in the UI.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]  # implementation/
OUTPUT = ROOT / "output"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

router = APIRouter(prefix="/api/scene-review", tags=["scene-review"])


def _product_dir(product: str) -> Path:
    # product = "<channel>/<product_dirname>" (slash-encoded as "~")
    channel, _, name = product.partition("~")
    pd = OUTPUT / "products" / channel / name
    if not pd.exists() or not (pd / "script.json").exists():
        raise HTTPException(404, f"product not found: {channel}/{name}")
    return pd


def _load_shots(pd: Path):
    """Same shot list the renderer uses: sidecar scenes + 18-word fine sync."""
    import render_real_video as rrv

    sc = json.loads((pd / "script.json").read_text(encoding="utf-8"))
    sc_list = sc.get("scenes") if isinstance(sc, dict) else sc
    scenes = rrv._parse_json_script(json.dumps(sc_list))
    return rrv.split_into_shots(scenes, 18)


def _load_board(pd: Path, shots) -> list[dict]:
    """board_final if present (post-mutation truth), else patched cache board."""
    bf = pd / "board_final.json"
    if bf.exists():
        board = json.loads(bf.read_text(encoding="utf-8"))
        if len(board) == len(shots):
            return board
    return [{} for _ in shots]


def _asset_for(pd: Path, i: int) -> tuple[Path | None, str]:
    a = pd / "_assets"
    for name, kind in ((f"scene_{i:02d}_chart.png", "chart"),
                       (f"scene_{i:02d}_stock.mp4", "stock"),
                       (f"scene_{i:02d}_illu.png", "image")):
        p = a / name
        if p.exists() and p.stat().st_size > 0:
            return p, kind
    return None, "missing"


def _section_map(pd: Path, shots) -> list[str]:
    """Section heading (script.txt [Heading] blocks) per shot, so the operator
    always knows WHERE in the video a scene sits."""
    txt = (pd / "script.txt").read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^\s*\[(.+?)\]\s*$", txt)
    sections: list[tuple[str, str]] = []
    for i in range(1, len(blocks) - 1, 2):
        sections.append((blocks[i].strip(), blocks[i + 1]))
    out, cur = [], "Hook"
    for sh in shots:
        probe = re.sub(r"[^a-z0-9 ]", "", sh.narration.lower())[:34]
        for name, body in sections:
            if probe and probe in re.sub(r"[^a-z0-9 ]", "", body.lower()):
                cur = name
                break
        out.append(cur)
    return out


def _durations(pd: Path, n: int) -> list[float]:
    """Per-shot spoken duration from the TTS word timings (already on disk)."""
    durs = []
    for i in range(n):
        wf = pd / "_assets" / f"scene_{i:02d}.words.json"
        d = 0.0
        if wf.exists():
            try:
                words = json.loads(wf.read_text(encoding="utf-8"))
                if words:
                    d = float(words[-1].get("end", 0.0))
            except Exception:
                d = 0.0
        durs.append(d or 4.0)
    return durs


@router.get("/{product}/scenes")
def list_scenes(product: str):
    pd = _product_dir(product)
    shots = _load_shots(pd)
    board = _load_board(pd, shots)
    sections = _section_map(pd, shots)
    durs = _durations(pd, len(shots))
    starts, acc = [], 0.0
    for d in durs:
        starts.append(acc)
        acc += d
    marks_file = pd / "review_marks.json"
    marks = json.loads(marks_file.read_text(encoding="utf-8")) if marks_file.exists() else {}
    out = []
    for i, sh in enumerate(shots):
        cell = board[i] if i < len(board) and isinstance(board[i], dict) else {}
        asset, kind = _asset_for(pd, i)
        out.append({
            "index": i,
            "narration": sh.narration,
            "heading": sh.heading,
            "section": sections[i] if i < len(sections) else "",
            "start_sec": round(starts[i], 2),
            "dur_sec": round(durs[i], 2),
            "timecode": f"{int(starts[i] // 60)}:{int(starts[i] % 60):02d}",
            "pace": getattr(sh, "pace", ""),
            "visual_type": cell.get("visual_type", ""),
            "stock_query": cell.get("stock_query", ""),
            "chart_title": (cell.get("chart_spec") or {}).get("title", ""),
            "chart_source": (cell.get("chart_spec") or {}).get("source", ""),
            "stat_number": cell.get("stat_number", ""),
            "stat_label": cell.get("stat_label", ""),
            "asset_kind": kind,
            "has_asset": asset is not None,
            "mark": marks.get(str(i), ""),
        })
    return {"product": product, "count": len(out), "scenes": out}


@router.get("/{product}/asset/{i}")
def get_asset(product: str, i: int):
    pd = _product_dir(product)
    asset, kind = _asset_for(pd, i)
    if asset is None:
        raise HTTPException(404, "no asset acquired for this scene yet")
    media = "video/mp4" if kind == "stock" else "image/png"
    return FileResponse(asset, media_type=media)


@router.get("/{product}/poster/{i}")
def get_poster(product: str, i: int):
    """Still poster for a scene — a frame from the clip, or the PNG itself.
    Lets any <img> in the Studio timeline show the REAL acquired visual."""
    pd = _product_dir(product)
    asset, kind = _asset_for(pd, i)
    if asset is None:
        raise HTTPException(404, "no asset acquired for this scene yet")
    if kind != "stock":
        return FileResponse(asset, media_type="image/png")
    poster = pd / "_assets" / f"poster_{i:03d}.jpg"
    if not poster.exists() or poster.stat().st_size == 0:
        try:
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.6",
                 "-i", str(asset), "-frames:v", "1", "-vf", "scale=426:-2",
                 str(poster)], check=True, timeout=40,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:
            raise HTTPException(500, f"poster extract failed: {exc}")
    return FileResponse(poster, media_type="image/jpeg")


@router.get("/{product}/tts/{i}")
def get_tts(product: str, i: int):
    """Per-scene narration audio for the rough-cut preview (cached)."""
    pd = _product_dir(product)
    shots = _load_shots(pd)
    if not (0 <= i < len(shots)):
        raise HTTPException(404, "scene index out of range")
    cache = pd / "_assets" / f"review_tts_{i:03d}.mp3"
    if not cache.exists() or cache.stat().st_size == 0:
        try:
            import edge_tts

            channel_id = product.partition("~")[0]
            channel = json.loads(
                (ROOT / "channels" / f"{channel_id}.json").read_text(encoding="utf-8"))
            voice = str(channel.get("voice_profile",
                                    "edge:en-US-AndrewMultilingualNeural")
                        ).split(":", 1)[-1]

            async def _synth():
                tts = edge_tts.Communicate(shots[i].narration, voice)
                await tts.save(str(cache))

            asyncio.run(_synth())
        except Exception as exc:
            raise HTTPException(500, f"tts failed: {exc}")
    return FileResponse(cache, media_type="audio/mpeg")


class VisualEdit(BaseModel):
    stock_query: str


@router.post("/{product}/scene/{i}/visual")
def edit_visual(product: str, i: int, body: VisualEdit):
    """Fetch a new stock clip for this scene and persist the decision as a
    narration-keyed board patch (survives board regeneration)."""
    pd = _product_dir(product)
    shots = _load_shots(pd)
    if not (0 <= i < len(shots)):
        raise HTTPException(404, "scene index out of range")
    q = body.stock_query.strip()
    if not q:
        raise HTTPException(400, "empty stock_query")

    from omnicast.media.providers.stock_video import download_best_stock_video

    dest = pd / "_assets" / f"scene_{i:02d}_stock.mp4"
    ok = download_best_stock_video(q, dest, 1920, 1080, max_seconds=15)
    if not ok or not dest.exists() or dest.stat().st_size == 0:
        raise HTTPException(502, f"no stock result for query: {q}")
    # A chart/image asset would shadow the new clip in _asset_for — remove.
    for stale in (pd / "_assets" / f"scene_{i:02d}_chart.png",
                  pd / "_assets" / f"scene_{i:02d}_illu.png"):
        stale.unlink(missing_ok=True)

    key = re.sub(r"\s+", " ", shots[i].narration.strip())[:60].lower()
    pf = pd / "board_patches.json"
    patches = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else []
    patches = [p for p in patches if p.get("narration_key") != key]
    patches.append({"narration_key": key,
                    "set": {"visual_type": "stock_video", "stock_query": q,
                            "search_query": ""},
                    "why": "operator scene-review edit (in-app)"})
    pf.write_text(json.dumps(patches, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "scene": i, "stock_query": q}


class Mark(BaseModel):
    mark: str  # "ok" | "bad" | ""
    note: str = ""


@router.post("/{product}/scene/{i}/mark")
def mark_scene(product: str, i: int, body: Mark):
    pd = _product_dir(product)
    mf = pd / "review_marks.json"
    marks = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    marks[str(i)] = body.mark
    if body.note:
        marks[f"{i}_note"] = body.note
    mf.write_text(json.dumps(marks, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@router.get("/{product}/page")
def review_page(product: str):
    page = Path(__file__).parent / "scene_review_page.html"
    html = page.read_text(encoding="utf-8").replace("__PRODUCT__", product)
    return HTMLResponse(html)
