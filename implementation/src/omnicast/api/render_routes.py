"""Render-video API routes (isolated router, included by server.py).

Adds the full-video render pipeline to the dashboard backend:
  POST /api/render/{channel_id}     — start a real render (render_real_video.py)
  GET  /api/render/status           — live render status (status.json)
  GET  /api/render/latest           — latest output {video, thumbnail, title}
  GET  /api/credits                 — Flow credit balance
  /media/*                          — static serve of output/real (mp4, png)

These surface the OmniCast video pipeline (storyboard → Flow images → Ken Burns
+ subtitles → concat → clickbait title/thumbnail) the dashboard triggers/monitors.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# implementation/ root (this file: src/omnicast/api/render_routes.py).
IMPL_ROOT = Path(__file__).resolve().parents[3]
RENDER_SCRIPT = IMPL_ROOT / "render_real_video.py"
OUT_DIR = IMPL_ROOT / "output" / "real"          # legacy webui render tree (fallback)
STATUS_PATH = OUT_DIR / "_status" / "status.json"
SCRIPTS_DIR = IMPL_ROOT / "output" / "scripts"   # legacy script tree (fallback)

sys.path.insert(0, str(IMPL_ROOT / "src"))
from omnicast.storage import products as _products  # noqa: E402  (SSOT for product paths)

# On Windows, spawning ffmpeg/render pops a console window each time. CREATE_NO_WINDOW
# suppresses it (mirrors the pattern in media/output_audit.py + runtime/probe.py).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

render_router = APIRouter()
_proc: dict[str, subprocess.Popen] = {}  # channel_id -> running render process
_render_job_engine = None


def _get_render_job_engine():
    """Local JobEngine singleton for render jobs; status is persisted in vault.db."""
    global _render_job_engine
    if _render_job_engine is not None:
        return _render_job_engine

    from omnicast.jobengine import JobEngine
    from omnicast.jobengine import store as job_store

    db_path = IMPL_ROOT / "output" / "vault.db"
    job_store.init_jobengine_schema(db_path)
    engine = JobEngine(db_path=db_path)

    async def _render_handler(ctx):
        payload = dict(ctx.payload or {})
        channel_id = str(payload["channel_id"])
        cmd = [str(x) for x in payload["cmd"]]
        out_mp4 = str(payload["out"])
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in dict(payload.get("env_overrides") or {}).items()})

        ctx.progress(1, 3, "render", "starting")
        proc = subprocess.Popen(cmd, cwd=str(IMPL_ROOT), env=env, creationflags=_NO_WINDOW)
        _proc[channel_id] = proc
        try:
            from omnicast.api import state as _state
            _state.set_active_job(channel_id, "render")
            _state.write_pipeline_event(channel_id, "render", "started",
                                        extra={"job_id": ctx.job_id})
        except Exception:
            pass

        ctx.progress(2, 3, "render", "running")
        while proc.poll() is None:
            await asyncio.sleep(1)

        rc = int(proc.returncode or 0)
        try:
            from omnicast.api import state as _state
            _state.clear_active_job(channel_id)
            _state.write_pipeline_event(channel_id, "render",
                                        "completed" if rc == 0 else "failed",
                                        extra={"job_id": ctx.job_id, "returncode": rc})
        except Exception:
            pass
        _proc.pop(channel_id, None)
        ctx.progress(3, 3, "render", "success" if rc == 0 else "failed")
        if rc != 0:
            raise RuntimeError(f"render_real_video exited with code {rc}")
        return {"channel_id": channel_id, "out": out_mp4, "returncode": rc}

    engine.register("render", _render_handler)
    _render_job_engine = engine
    return engine


def cancel_render(channel_id: str) -> bool:
    """Terminate the active rendering process for the channel if it is running."""
    proc = _proc.pop(channel_id, None)
    if proc:
        try:
            proc.kill()
            return True
        except Exception:
            pass
    return False


def _find_script(channel_id: str, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        # Try relative to SCRIPTS_DIR
        cand = SCRIPTS_DIR / explicit
        if cand.exists():
            return cand
        cand = SCRIPTS_DIR / channel_id / explicit
        if cand.exists():
            return cand
        # Search recursively for the filename in products/ then legacy scripts/.
        cand_list = list((_products.PRODUCTS_DIR / channel_id).glob(f"**/{explicit}")) \
            + list((SCRIPTS_DIR / channel_id).glob(f"**/{explicit}"))
        if cand_list:
            return cand_list[0]
        return None
    # Preferred: newest product's script.txt (products/<channel>/<run>/script.txt).
    latest = _products.latest_script(channel_id)
    if latest:
        return latest
    # Legacy fallback: scripts/<channel>/<topic_slug>/variant_*scoreNN.txt.
    cand = list(SCRIPTS_DIR.glob(f"{channel_id}/**/*.txt"))
    if not cand:
        cand = list(SCRIPTS_DIR.glob(f"{channel_id}/*.txt"))
    if not cand:
        return None
    # newest topic dir (by mtime of its files)
    newest_dir = max((p.parent for p in cand), key=lambda d: d.stat().st_mtime)
    in_dir = list(newest_dir.glob("*.txt")) or cand

    def _score(p: Path) -> int:
        import re as _re
        m = _re.search(r"score(\d+)", p.name)
        return int(m.group(1)) if m else 0
    return max(in_dir, key=_score)


def _script_compliance(script_path: Path) -> list[str]:
    """Read the _compliance.json sidecar (written at script-gen time) for this
    script's topic folder. Returns violation list ([] = clean or no sidecar)."""
    sc = script_path.parent / "_compliance.json"
    if not sc.exists():
        return []
    try:
        return json.loads(sc.read_text(encoding="utf-8")).get("violations", []) or []
    except Exception:
        return []


@render_router.post("/api/render/{channel_id}")
async def start_render(channel_id: str, script: str | None = None, beat_words: int = 18,
                       force: bool = False, shorts: bool = False,
                       style: str | None = None, voice: str | None = None,
                       voice_rate: str | None = None, voice_pitch: str | None = None,
                       music: bool = True, music_volume: float | None = None,
                       music_mood: str | None = None):
    """Start a full video render for a channel (background). Uses the channel's
    style/voice/subtitle via --channel, Flow images, a fresh Flow project.
    Optional query params override per-render: style, voice (+rate/pitch),
    beat_words, shorts, music (on/off), music_volume, music_mood. Anything omitted
    falls back to the channel config defaults.
    Refuses to render a script flagged non-compliant at script-gen time."""
    if _proc.get(channel_id) and _proc[channel_id].poll() is None:
        raise HTTPException(409, "A render is already running for this channel")
    script_path = _find_script(channel_id, script)
    if not script_path:
        raise HTTPException(404, f"No script .txt found for {channel_id}. Generate a script first.")
    release_issues = _products.release_issues_for_script(script_path)
    if release_issues and not force:
        return JSONResponse(
            {"status": "quality_blocked", "violations": release_issues,
             "message": "Script has not passed the content and production release gates."},
            status_code=409,
        )
    # Policy gate BEFORE render — don't waste Flow images/TTS on unusable content.
    violations = _script_compliance(script_path)
    if violations and not force:
        return JSONResponse(
            {"status": "policy_blocked", "violations": violations,
             "message": "Script vi phạm policy YouTube — không render để tránh phí. "
                        "Tạo lại script hoặc gửi force=true."},
            status_code=409)

    # Render into the script's product folder (video.mp4 next to script.txt +
    # meta.json). If the script isn't in a product folder (legacy), make one so the
    # output is still self-contained. Shorts get their own product folder.
    owning_product = _products.product_dir_for_asset(script_path)
    canonical_script = _products.script_path(owning_product)
    if (script_path.resolve() == canonical_script.resolve()
            and _products.is_product_dir(owning_product) and not shorts):
        product_dir = owning_product
    else:
        _slug = script_path.parent.name if script_path.parent.name != channel_id else script_path.stem
        product_dir = _products.new_product_dir(channel_id, _slug + ("_shorts" if shorts else ""))
        # carry the script in so the folder is self-contained
        try:
            _products.script_path(product_dir).write_text(
                script_path.read_text(encoding="utf-8"), encoding="utf-8")
            script_path = _products.script_path(product_dir)
        except Exception:
            pass
    out_mp4 = _products.video_path(product_dir)
    cmd = [
        sys.executable, "-X", "utf8", str(RENDER_SCRIPT),
        "--script", str(script_path),
        "--channel", channel_id,
        "--images", "flow",
        "--beat-words", str(beat_words),
        "--subtitles",  # clean word-synced captions, no title-card/scene frame
        "--out", str(out_mp4),
    ]
    if shorts:
        cmd.append("--shorts")
    # Optional per-render overrides (omit → render_real_video uses channel defaults)
    if style:
        cmd += ["--style", str(style)]
    if voice:
        cmd += ["--voice", str(voice)]
    if voice_rate:
        cmd += ["--voice-rate", str(voice_rate)]
    if voice_pitch:
        cmd += ["--voice-pitch", str(voice_pitch)]
    if not music:
        cmd.append("--no-music")
    else:
        if music_volume is not None:
            cmd += ["--music-volume", str(music_volume)]
        if music_mood:
            cmd += ["--music-mood", str(music_mood)]
    env_overrides = {"FLOW_NEW_PROJECT": "1"}  # fresh project per video
    # Per-channel image model override (Imagen 4 / Nano Banana / Nano Banana Pro).
    cfg_path = IMPL_ROOT / "channels" / f"{channel_id}.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if cfg.get("flow_image_model"):
                env_overrides["FLOW_IMAGE_MODEL"] = str(cfg["flow_image_model"])
        except Exception:
            pass
    if os.environ.get("OMNICAST_JOBENGINE", "1") != "0":
        from omnicast.jobengine.models import JobSpec, ResourceClass

        job_id = f"render_{channel_id}_{uuid.uuid4().hex[:12]}"
        spec = JobSpec(
            job_id=job_id,
            type="render",
            resource_class=ResourceClass.GPU,
            priority=3,
            payload={
                "channel_id": channel_id,
                "cmd": cmd,
                "out": str(out_mp4),
                "env_overrides": env_overrides,
            },
        )
        await _get_render_job_engine().submit(spec)
        return {
            "status": "started",
            "channel_id": channel_id,
            "script": str(script_path),
            "out": str(out_mp4),
            "job_id": job_id,
            "job_status_url": f"/jobengine/api/v1/jobs/{job_id}",
        }

    env = dict(os.environ)
    env.update(env_overrides)
    _proc[channel_id] = subprocess.Popen(cmd, cwd=str(IMPL_ROOT), env=env, creationflags=_NO_WINDOW)
    # Register as an active pipeline job so the dashboard "Đang chạy" + pipeline
    # panel show the render (a detached subprocess otherwise stays invisible).
    try:
        from omnicast.api import state as _state
        _state.set_active_job(channel_id, "render")
        _state.write_pipeline_event(channel_id, "render", "started")
    except Exception:
        pass
    return {"status": "started", "channel_id": channel_id,
            "script": str(script_path), "out": str(out_mp4)}


def _reconcile_render_jobs() -> None:
    """Clear the pipeline active_job for any render whose subprocess has exited
    (so the dashboard 'Đang chạy' count drops back when a render finishes)."""
    try:
        from omnicast.api import state as _state
        for cid, proc in list(_proc.items()):
            if proc.poll() is not None:  # exited
                rc = proc.returncode
                _state.clear_active_job(cid)
                _state.write_pipeline_event(cid, "render",
                                            "completed" if rc == 0 else "failed")
                _proc.pop(cid, None)
    except Exception:
        pass


def _all_status_files() -> list[Path]:
    """Every render status.json: per-channel output/real/<ch>/_status/status.json
    + legacy output/real/_status/status.json."""
    out = list(OUT_DIR.glob("*/_status/status.json"))
    if STATUS_PATH.exists():
        out.append(STATUS_PATH)
    return out


@render_router.get("/api/render/status")
async def render_status(channel_id: str | None = None):
    """Live render status. Per-channel status.json (output/real/<ch>/_status/);
    `channel_id` reads that channel, else returns the most recently updated."""
    _reconcile_render_jobs()
    sp = None
    if channel_id:
        cand = OUT_DIR / channel_id / "_status" / "status.json"
        sp = cand if cand.exists() else None
    else:
        files = _all_status_files()
        sp = max(files, key=lambda p: p.stat().st_mtime) if files else None
    if not sp or not sp.exists():
        return {"stage": "idle", "stages": {}, "shots": [], "log": []}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return {"stage": "unknown", "stages": {}, "shots": [], "log": []}


def _media_rel(p: Path) -> str:
    """Path relative to OUT_DIR as a /media URL (handles per-channel subdirs)."""
    try:
        rel = p.relative_to(OUT_DIR).as_posix()
    except ValueError:
        rel = p.name
    return f"/media/{rel}"


@render_router.get("/api/render/latest")
async def render_latest(channel_id: str | None = None):
    """Latest render outputs (relative to /media): video, thumbnail, title.
    Searches per-channel subdirs recursively; `channel_id` scopes to one channel."""
    v = _products.latest_video(channel_id) if channel_id else None
    if v is None:
        # legacy fallback: output/real/<channel>/**/*.mp4
        base = (OUT_DIR / channel_id) if channel_id else OUT_DIR
        vids = sorted(base.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        vids = [x for x in vids if "_assets" not in x.parts]
        if vids:
            v = vids[0]
    if v is None:
        return {"video": None, "thumbnail": None, "title": None}
    thumb = v.with_name(v.stem + "_thumb.png")
    title = v.with_name(v.stem + "_title.txt")
    return {
        "video": _media_rel(v),
        "thumbnail": _media_rel(thumb) if thumb.exists() else None,
        "title": title.read_text(encoding="utf-8") if title.exists() else None,
    }


def _enrich_product_meta(pd, meta) -> dict:
    # Expose the script content dynamically
    script_file = _products.script_path(pd)
    if script_file.exists():
        try:
            meta["script"] = script_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            meta["script"] = ""
    else:
        meta["script"] = ""

    # Map video/thumbnail bare filenames (e.g. "video.mp4") to URLs. Products live
    # under output/products, served at /pmedia — NOT /media (= output/real). Using
    # _media_rel() here computed a path relative to the WRONG root and silently fell
    # back to a bogus "/media/<filename>" that always 404s (defect S1/S2 root cause).
    if meta.get("video") and not str(meta["video"]).startswith(("/media/", "/pmedia/")):
        meta["video"] = f"/pmedia/{pd.parent.name}/{pd.name}/{meta['video']}"
    if meta.get("thumbnail") and not str(meta["thumbnail"]).startswith(("/media/", "/pmedia/")):
        meta["thumbnail"] = f"/pmedia/{pd.parent.name}/{pd.name}/{meta['thumbnail']}"

    # Expose video probe parameters at top level for the UI
    probe = meta.get("video_probe") or {}
    if isinstance(probe, dict):
        meta.setdefault("width", probe.get("width"))
        meta.setdefault("height", probe.get("height"))
        meta.setdefault("fps", probe.get("fps"))

    # Bridge created_at field name
    if "created" in meta:
        meta["created_at"] = meta["created"]

    return meta


@render_router.get("/api/product/meta")
async def product_meta(channel_id: str, slug: str, rebuild: bool = False):
    """Full QC manifest for one product. `rebuild=true` re-consolidates from disk
    (variants/QA/timeline/voice/ffprobe) before returning."""
    pd = _products.PRODUCTS_DIR / channel_id / slug
    if not pd.is_dir():
        raise HTTPException(404, f"product not found: {channel_id}/{slug}")
    if rebuild:
        meta = _products.build_manifest(pd)
    else:
        meta = _products.read_meta(pd)
    return _enrich_product_meta(pd, meta)


@render_router.get("/api/products")
async def list_products(channel_id: str | None = None, limit: int = 50):
    """Product list (newest first) with their QC manifests — the quality dashboard feed."""
    pds = _products.iter_products(channel_id)[:limit]
    products_list = []
    for pd in pds:
        meta = _products.read_meta(pd)
        products_list.append({
            "channel": pd.parent.name,
            "slug": pd.name,
            **_enrich_product_meta(pd, meta)
        })
    return {"products": products_list, "count": len(pds)}


@render_router.post("/api/products/rebuild-meta")
async def rebuild_meta(channel_id: str | None = None):
    """Backfill the full QC manifest for all products (or one channel). One-off after
    upgrading the manifest schema, or to enrich older videos."""
    done, failed = [], []
    for pd in _products.iter_products(channel_id):
        try:
            _products.build_manifest(pd)
            done.append(pd.name)
        except Exception as e:
            failed.append({"slug": pd.name, "error": str(e)[:120]})
    return {"rebuilt": len(done), "failed": failed}


def _yt_oauth():
    sys.path.insert(0, str(IMPL_ROOT / "src"))
    from omnicast.config.settings import get_settings
    from omnicast.upload.oauth import OAuth2Manager
    s = get_settings()
    return OAuth2Manager(token_dir=str(IMPL_ROOT / s.youtube_token_dir),
                         encryption_key=s.youtube_token_key or None)


@render_router.get("/api/upload/status/{channel_id}")
async def upload_status(channel_id: str):
    """Whether this channel is authorized to auto-upload (token present + valid)."""
    try:
        mgr = _yt_oauth()
        if not mgr.has_token(channel_id):
            return {"channel_id": channel_id, "authorized": False,
                    "hint": f"Run scripts/youtube_authorize.py --channel {channel_id}"}
        health = await mgr.check_health(channel_id)
        return {"channel_id": channel_id,
                "authorized": health.status.value in ("valid", "expiring_soon"),
                "token_status": health.status.value, "error": health.error}
    except Exception as e:
        return {"channel_id": channel_id, "authorized": False, "error": str(e)[:160]}


@render_router.post("/api/upload/{channel_id}")
async def upload_video(channel_id: str, video: str | None = None,
                       privacy: str = "private", tags: str = "", force: bool = False):
    """Auto-upload a rendered video to the channel's YouTube. Defaults to the
    latest render for the channel and privacy=private (operator reviews before
    going public). Title/description come from the render's *_title.txt sidecar.
    Requires a prior one-time consent (scripts/youtube_authorize.py)."""
    sys.path.insert(0, str(IMPL_ROOT / "src"))
    from omnicast.upload.youtube_api import YouTubeUploader
    from omnicast.upload.models import UploadRequest, UploadMetadata

    # Resolve the video: explicit path, else this channel's NEWEST render
    # (output/real/<channel>/*.mp4), else legacy flat output/real/<channel>.mp4.
    if video:
        vpath = Path(video)
    else:
        vpath = _products.latest_video(channel_id)
        if vpath is None:
            base = OUT_DIR / channel_id
            vids = sorted(base.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if base.exists() else []
            vids = [v for v in vids if "_assets" not in v.parts]
            vpath = vids[0] if vids else (OUT_DIR / f"{channel_id}.mp4")  # legacy fallback
    if not vpath.exists():
        raise HTTPException(404, f"No rendered video found for {channel_id}")

    mgr = _yt_oauth()
    if not mgr.has_token(channel_id):
        raise HTTPException(
            412, f"Channel '{channel_id}' not authorized. Run "
                 f"scripts/youtube_authorize.py --channel {channel_id} once.")

    title_f = vpath.with_name(vpath.stem + "_title.txt")
    thumb_f = vpath.with_name(vpath.stem + "_thumb.png")
    title = (title_f.read_text(encoding="utf-8").strip()[:100]
             if title_f.exists() else vpath.stem)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    # Affiliate block (optional, per-channel) — channels/<id>.json:
    #   "affiliate_links": [{"label": "Tool I use", "url": "https://amzn.to/xxx"}]
    # Appended to description with an FTC #ad disclosure (compliance requires it).
    affiliate_block = ""
    try:
        cfg_path = IMPL_ROOT / "channels" / f"{channel_id}.json"
        ccfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        links = ccfg.get("affiliate_links") or []
        if links:
            lines = "\n".join(f"▸ {l.get('label', 'Link')}: {l.get('url', '')}"
                              for l in links if l.get("url"))
            if lines:
                affiliate_block = ("\n\n#ad — As an affiliate I may earn from qualifying "
                                   "purchases (paid promotion / affiliate links):\n" + lines)
    except Exception:
        pass
    meta = UploadMetadata(
        title=title,
        description=(title + "\n\nMade with AI (AI-generated narration & visuals)."
                     "\n\nMusic: Kevin MacLeod (incompetech.com) — "
                     "Creative Commons: By Attribution 4.0 License "
                     "(https://creativecommons.org/licenses/by/4.0/)." + affiliate_block),
        tags=tag_list, privacy_status=privacy if privacy in ("private", "unlisted", "public") else "private",
    )
    req = UploadRequest(
        video_id=vpath.stem, channel_id=channel_id, video_path=str(vpath.resolve()),
        thumbnail_paths=[str(thumb_f.resolve())] if thumb_f.exists() else [],
        metadata=meta,
    )
    # Compliance gate — block likely YouTube policy violations BEFORE publishing
    # (misleading/scam metadata, demonetization triggers, missing FTC disclosure,
    # cross-channel reused content, AI disclosure). force=true overrides.
    from omnicast.upload.compliance import ComplianceChecker
    comp = ComplianceChecker().check(req)
    if not comp.passed and not force:
        return JSONResponse(
            {"status": "compliance_blocked", "violations": comp.violations,
             "checks": comp.checks,
             "message": "Chặn trước khi đăng — vi phạm chính sách YouTube tiềm ẩn. "
                        "Sửa metadata hoặc gửi lại với force=true."},
            status_code=409)
    result = await YouTubeUploader(mgr).upload(req)
    if result.status.value == "failed":
        raise HTTPException(502, f"Upload failed: {result.error}")
    # Record into the dedup ledger so this topic can't be silently re-published
    # (here or on another channel) and trigger YouTube reused-content flags.
    try:
        from omnicast.vault import db as vault_db
        from omnicast.vault.models import PublishedVideo
        from datetime import datetime, timezone
        VAULT_DB = IMPL_ROOT / "output" / "vault.db"
        vault_db.init_db(VAULT_DB)
        vault_db.record_published(PublishedVideo(
            video_id=f"{channel_id}:{vpath.stem}", channel_id=channel_id, title=title,
            youtube_video_id=result.youtube_video_id,
            published_at=datetime.now(timezone.utc).isoformat(), status="uploaded",
        ), VAULT_DB)
    except Exception:
        pass
    return {"status": result.status.value, "youtube_video_id": result.youtube_video_id,
            "url": result.url, "thumbnail_set": result.thumbnail_set,
            "privacy": meta.privacy_status}


import time as _time
_CRED_CACHE = {"ts": 0.0, "balance": None}
_FLOW_HOME = "https://labs.google/fx/vi/tools/flow"


@render_router.get("/api/credits")
async def get_credits(refresh: bool = False):
    """Flow credit balance. Reading it launches a real Chrome session, so the
    result is cached for 5 min and a fresh read does NOT create a new project
    (it reads the balance on the Flow home page). Pass ?refresh=1 to force."""
    now = _time.time()
    if not refresh and _CRED_CACHE["balance"] is not None and (now - _CRED_CACHE["ts"] < 300):
        return {"provider": "flow", "balance": _CRED_CACHE["balance"], "cached": True}
    try:
        sys.path.insert(0, str(IMPL_ROOT / "src"))
        from omnicast.media.providers.flow_browser import FlowProvider
        # Force: no new project, read balance on the Flow home page.
        p = FlowProvider(project_url=_FLOW_HOME)
        p._create_new = False
        bal = await p.credits()
        p.close()
        if bal is not None:
            _CRED_CACHE["balance"] = bal
            _CRED_CACHE["ts"] = now
        return {"provider": "flow", "balance": bal}
    except Exception as e:
        return {"provider": "flow", "balance": _CRED_CACHE["balance"], "error": str(e)[:120]}


# ── Voice picker: list voices, preview a sample, set a channel's voice ─────────
_PREVIEW_TEXT = ("Struggling with nausea on Ozempic? Here's the one simple change "
                 "most doctors never tell you about.")

# Kokoro-82M voices (no list API → canonical ids). First char = language, second =
# gender. Full set so the library is complete, not a shortlist.
_KOKORO_LANG = {"a": "en-US", "b": "en-GB", "e": "es-ES", "f": "fr-FR", "h": "hi-IN",
                "i": "it-IT", "j": "ja-JP", "p": "pt-BR", "z": "zh-CN"}
_KOKORO_IDS = (
    "af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova "
    "af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam am_michael "
    "am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily bm_daniel "
    "bm_fable bm_george bm_lewis ef_dora em_alex em_santa ff_siwis hf_alpha hf_beta "
    "hm_omega hm_psi if_sara im_nicola jf_alpha jf_gongitsune jf_nezumi jf_tebukuro "
    "jm_kumo pf_dora pm_alex pm_santa zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi "
    "zm_yunjian zm_yunxi zm_yunxia zm_yunyang"
).split()


# Curated character notes for the English Kokoro voices (the ones channels use most)
# so the picker reads like ElevenLabs, not a bare id list.
_KOKORO_DESC = {
    "af_heart": "Warm, empathetic, conversational — great for health/story ⭐",
    "af_bella": "Bright, energetic, expressive",
    "af_aoede": "Smooth, balanced narration",
    "af_alloy": "Neutral, clear, all-purpose",
    "af_jessica": "Youthful, casual, upbeat",
    "af_kore": "Calm, measured, documentary",
    "af_nicole": "Soft, intimate, close-mic (ASMR-ish)",
    "af_nova": "Crisp, modern, news",
    "af_river": "Gentle, soothing, calm",
    "af_sarah": "Calm, professional, trustworthy",
    "af_sky": "Light, friendly, bubbly",
    "am_adam": "Deep, authoritative male",
    "am_michael": "Steady, trustworthy male narrator",
    "am_echo": "Clear, neutral male",
    "am_eric": "Mature, grounded male",
    "am_fenrir": "Strong, dramatic male",
    "am_liam": "Young, friendly male",
    "am_onyx": "Smooth, rich male",
    "am_puck": "Playful, expressive male",
    "am_santa": "Jolly, characterful male",
    "bf_emma": "Warm UK female, reassuring",
    "bf_alice": "Refined UK female",
    "bf_isabella": "Elegant UK female",
    "bf_lily": "Soft young UK female",
    "bm_george": "Classic UK male narrator",
    "bm_daniel": "Polished UK male",
    "bm_fable": "Storyteller UK male",
    "bm_lewis": "Deep UK male",
}


# ── Facet inference (age / pitch / accent / use-case) so cards are filterable ──
# accent derives from the locale; use_case from description keywords. Curated
# English Kokoro voices get precise age/pitch/use_case overrides below.
_ACCENT_BY_LOCALE = {
    "en-US": "american", "en-GB": "british", "en-AU": "australian",
    "en-CA": "canadian", "en-IN": "indian", "en-IE": "irish", "en-NZ": "new zealand",
    "en-ZA": "south african", "en-GB-scotland": "scottish",
}
_USE_CASE_KEYWORDS = [
    ("news", ("news", "anchor", "broadcast", "report")),
    ("narration", ("narrat", "documentary", "story", "audiobook", "narrator")),
    ("character", ("character", "playful", "jolly", "dramatic", "villain", "cartoon", "expressive")),
    ("conversational", ("conversational", "casual", "friendly", "warm", "empathetic", "intimate", "chat")),
    ("social", ("shorts", "promo", "energetic", "bubbly", "upbeat", "podcast", "social")),
    ("advertisement", ("advert", "commercial", "promo", "sell")),
    ("informative", ("educational", "explainer", "tutorial", "professional", "clear", "trustworthy")),
]


def _accent_from_lang(lang: str) -> str:
    if not lang:
        return ""
    return _ACCENT_BY_LOCALE.get(lang, _ACCENT_BY_LOCALE.get(lang.split("-")[0] + "-US", ""))


def _use_case_from_text(*texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for uc, kws in _USE_CASE_KEYWORDS:
        if any(k in blob for k in kws):
            return uc
    return "informative"


# Precise facets for the curated English Kokoro voices (age, pitch, use_case).
# Accent is derived from locale; gender from the id. Keep keys ⊆ _KOKORO_DESC.
_KOKORO_FACETS = {
    "af_heart": ("adult", "moderate", "conversational"),
    "af_bella": ("young adult", "high", "social"),
    "af_aoede": ("adult", "moderate", "narration"),
    "af_alloy": ("adult", "moderate", "informative"),
    "af_jessica": ("young adult", "high", "social"),
    "af_kore": ("adult", "low", "narration"),
    "af_nicole": ("adult", "low", "conversational"),
    "af_nova": ("adult", "moderate", "news"),
    "af_river": ("adult", "low", "conversational"),
    "af_sarah": ("adult", "moderate", "informative"),
    "af_sky": ("young adult", "high", "social"),
    "am_adam": ("adult", "low", "narration"),
    "am_michael": ("adult", "moderate", "informative"),
    "am_echo": ("adult", "moderate", "informative"),
    "am_eric": ("middle-aged", "low", "narration"),
    "am_fenrir": ("adult", "low", "character"),
    "am_liam": ("young adult", "moderate", "conversational"),
    "am_onyx": ("adult", "low", "narration"),
    "am_puck": ("young adult", "high", "character"),
    "am_santa": ("elderly", "low", "character"),
    "bf_emma": ("adult", "moderate", "conversational"),
    "bf_alice": ("adult", "moderate", "informative"),
    "bf_isabella": ("adult", "moderate", "narration"),
    "bf_lily": ("young adult", "high", "conversational"),
    "bm_george": ("middle-aged", "low", "narration"),
    "bm_daniel": ("adult", "moderate", "informative"),
    "bm_fable": ("adult", "moderate", "narration"),
    "bm_lewis": ("adult", "low", "narration"),
}


def _kokoro_catalog() -> list[dict]:
    out = []
    for vid in _KOKORO_IDS:
        lang = _KOKORO_LANG.get(vid[0], "en-US")
        gender = "female" if vid[1] == "f" else "male"
        name = vid.split("_", 1)[1].capitalize()
        desc = _KOKORO_DESC.get(vid, "Kokoro neural voice")
        age, pitch, use_case = _KOKORO_FACETS.get(vid, ("", "", _use_case_from_text(desc)))
        out.append({"spec": f"kokoro:{vid}", "label": name, "gender": gender,
                    "lang": lang, "provider": "kokoro", "desc": desc,
                    "age": age, "pitch": pitch, "accent": _accent_from_lang(lang),
                    "use_case": use_case})
    return out


def _piper_voices_json() -> dict:
    """Load (and cache) the Piper voices.json catalog metadata (~160 models).
    Downloaded once to output/_models/piper/voices.json."""
    import urllib.request
    vj = IMPL_ROOT / "output" / "_models" / "piper" / "voices.json"
    if not vj.exists():
        vj.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json",
                str(vj))
        except Exception:
            return {}
    try:
        return json.loads(vj.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _piper_catalog() -> list[dict]:
    """All Piper models as catalog entries (downloaded on first preview/use).
    Multi-speaker models are surfaced as one entry; append #<sid> to target a
    specific speaker."""
    cat = _piper_voices_json()
    out = []
    for key, v in cat.items():
        ln = v.get("language", {}) or {}
        lang = ln.get("code", "").replace("_", "-")
        en = ln.get("name_english", "")
        country = ln.get("country_english", "")
        nspk = v.get("num_speakers", 1) or 1
        qual = v.get("quality", "")
        name = (v.get("name", key) or key).replace("_", " ").title()
        multi = f" · {nspk} speakers" if nspk > 1 else ""
        desc = f"Piper {en} ({country}) · {qual}{multi}".strip(" ·")
        out.append({"spec": f"piper:{key}", "label": name, "gender": "",
                    "lang": lang, "provider": "piper", "desc": desc,
                    "age": "", "pitch": "", "accent": _accent_from_lang(lang),
                    "use_case": _use_case_from_text(desc), "num_speakers": nspk,
                    "needs_download": True})
    return out


async def _edge_catalog() -> list[dict]:
    try:
        import edge_tts
        vs = await edge_tts.list_voices()
    except Exception:
        return []
    out = []
    for v in vs:
        sn = v.get("ShortName", "")
        if not sn:
            continue
        # FriendlyName e.g. "Microsoft Aria Online (Natural) - English (United States)"
        nm = (v.get("FriendlyName", "") or sn).replace("Microsoft ", "").split(" Online")[0]
        tag = v.get("VoiceTag") or {}
        pers = ", ".join(tag.get("VoicePersonalities", []) or [])
        cats = ", ".join(tag.get("ContentCategories", []) or [])
        desc = " · ".join([p for p in (pers, cats) if p]) or "Microsoft neural voice"
        loc = v.get("Locale", "")
        out.append({"spec": f"edge:{sn}", "label": nm or sn,
                    "gender": (v.get("Gender", "") or "").lower(),
                    "lang": loc, "provider": "edge", "desc": desc,
                    "age": "", "pitch": "", "accent": _accent_from_lang(loc),
                    "use_case": _use_case_from_text(desc, cats)})
    return out


@render_router.get("/api/voices")
async def list_voices(lang: str | None = None):
    """FULL voice catalog: all Kokoro voices (local) + all Edge voices (cloud, ~320).
    Optional ?lang=en filters by locale prefix. Marks installed providers."""
    import importlib.util
    avail = {"kokoro": importlib.util.find_spec("kokoro") is not None,
             "edge": importlib.util.find_spec("edge_tts") is not None,
             "piper": importlib.util.find_spec("sherpa_onnx") is not None}
    voices: list[dict] = []
    if avail["kokoro"]:
        voices += _kokoro_catalog()
    if avail["edge"]:
        voices += await _edge_catalog()
    if avail["piper"]:
        voices += _piper_catalog()
    if lang:
        voices = [v for v in voices if v["lang"].lower().startswith(lang.lower())]
    langs = sorted({v["lang"] for v in voices if v["lang"]})
    use_cases = sorted({v.get("use_case") for v in voices if v.get("use_case")})
    accents = sorted({v.get("accent") for v in voices if v.get("accent")})
    return {"voices": voices, "providers": avail, "langs": langs,
            "use_cases": use_cases, "accents": accents, "count": len(voices)}


@render_router.post("/api/voice/preview")
async def voice_preview(spec: str, text: str | None = None):
    """Synthesize a short sample for `spec` (provider:voice_id) → /media URL.
    Cached per spec so re-previewing the same voice is instant."""
    import re as _re
    slug = _re.sub(r"[^a-zA-Z0-9]+", "_", spec).strip("_")[:60]
    prev_dir = OUT_DIR / "_voicepreview"
    prev_dir.mkdir(parents=True, exist_ok=True)
    out = prev_dir / f"{slug}.wav"
    if not (text and text.strip()) and out.exists():
        return {"spec": spec, "url": _media_rel(out), "cached": True}
    sys.path.insert(0, str(IMPL_ROOT / "src"))
    from omnicast.media.voice_router import VoiceRouter, VoiceSpec
    try:
        res = await VoiceRouter().synthesize(
            (text or _PREVIEW_TEXT)[:300], [VoiceSpec.parse(spec)], str(out))
        _trim_preview_cache(prev_dir, keep=300)
        return {"spec": spec, "url": _media_rel(Path(res.audio_path)),
                "used": str(res.spec)}
    except Exception as e:
        raise HTTPException(500, f"voice preview failed: {str(e)[:160]}")


def _trim_preview_cache(prev_dir: Path, keep: int = 300) -> None:
    """Keep only the newest `keep` preview wavs (LRU by mtime). Each is tiny
    (~100-300 KB), but auditioning the whole 539-voice catalog would still add up."""
    try:
        wavs = sorted(prev_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in wavs[keep:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


@render_router.post("/api/channel/{channel_id}/voice")
async def set_channel_voice(channel_id: str, spec: str):
    """Persist the chosen voice as the channel's voice_profile (channels/<id>.json)."""
    cfg_path = IMPL_ROOT / "channels" / f"{channel_id}.json"
    if not cfg_path.exists():
        raise HTTPException(404, f"channel {channel_id} not found")
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["voice_profile"] = spec
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"channel_id": channel_id, "voice_profile": spec, "saved": True}
    except Exception as e:
        raise HTTPException(500, f"save failed: {str(e)[:160]}")


@render_router.get("/voices")
async def voices_page():
    """Self-contained voice picker page: list → preview (listen) → save to channel.
    Vanilla JS (no build step), kept separate from the main React dashboard."""
    from fastapi.responses import HTMLResponse
    chans = []
    cdir = IMPL_ROOT / "channels"
    if cdir.exists():
        chans = [p.stem for p in cdir.glob("*.json")]
    opts = "".join(f'<option value="{c}">{c}</option>' for c in chans)
    html = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Voice Library — OmniCast</title><style>
*{box-sizing:border-box}
body{font-family:Inter,Segoe UI,Arial,sans-serif;background:#0a0a0b;color:#ededed;margin:0;padding:0}
.wrap{max-width:1120px;margin:0 auto;padding:24px 20px 120px}
h1{font-size:24px;font-weight:700;margin:4px 0 2px}.sub{color:#8b8b8f;font-size:13px;margin-bottom:16px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
input,select{background:#161617;color:#ededed;border:1px solid #2a2a2c;border-radius:10px;padding:10px 13px;font-size:14px;outline:none}
input:focus,select:focus{border-color:#5b5bd6}
#q{flex:1;min-width:220px}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:18px}
.chip{font-size:12px;padding:6px 13px;border-radius:20px;background:#161617;border:1px solid #2a2a2c;color:#a8a8ad;cursor:pointer;transition:.12s;text-transform:capitalize}
.chip:hover{border-color:#3a3a3d;color:#ededed}
.chip.on{background:#5b5bd6;border-color:#5b5bd6;color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.card{background:#161617;border:1px solid #242426;border-radius:14px;padding:14px;display:flex;gap:13px;align-items:center;transition:.15s;cursor:pointer}
.card:hover{border-color:#3a3a3d;background:#1b1b1d}
.card.sel{border-color:#5b5bd6;box-shadow:0 0 0 1px #5b5bd6}
.play{flex:none;width:46px;height:46px;border-radius:50%;border:none;background:#ededed;color:#0a0a0b;font-size:17px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.15s}
.play:hover{transform:scale(1.06)}
.play.playing{background:#5b5bd6;color:#fff}
.play.loading{background:#2a2a2c;color:#8b8b8f}
.meta{flex:1;min-width:0}
.nm{font-weight:600;font-size:15px;margin-bottom:4px;display:flex;align-items:center;gap:7px}
.wave{display:flex;align-items:center;gap:2px;height:18px;margin-bottom:6px}
.wave i{display:block;width:2px;border-radius:2px;background:#3a3a44}
.card.sel .wave i,.play.playing ~ .meta .wave i{background:#5b5bd6}
.desc{font-size:12px;color:#9a9aa0;line-height:1.3;margin-bottom:7px}
.pills{display:flex;gap:6px;flex-wrap:wrap}
.pill{font-size:11px;padding:2px 9px;border-radius:20px;background:#242426;color:#a8a8ad;text-transform:capitalize}
.pill.pv{background:#1e2a4a;color:#8fb0ff}.pill.pv.kokoro{background:#163a2e;color:#6ee7b7}.pill.pv.piper{background:#3a2a16;color:#f0b878}
.pill.dl{background:#2a1e3a;color:#c79bff}
.acts{flex:none;display:flex;flex-direction:column;gap:8px;align-items:center}
.tick{width:22px;height:22px;border-radius:50%;border:2px solid #3a3a3d;display:flex;align-items:center;justify-content:center;font-size:12px;color:transparent}
.card.sel .tick{background:#5b5bd6;border-color:#5b5bd6;color:#fff}
.cmp{width:22px;height:22px;border-radius:6px;border:1px solid #3a3a3d;background:transparent;color:#8b8b8f;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.cmp.on{background:#a855f7;border-color:#a855f7;color:#fff}
.dock{position:fixed;left:0;right:0;bottom:0;background:#111113;border-top:1px solid #242426;padding:14px 20px}
.dock .inner{max-width:1120px;margin:0 auto;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.btn{background:#5b5bd6;color:#fff;border:none;border-radius:10px;padding:11px 18px;font-size:14px;font-weight:600;cursor:pointer}
.btn.alt{background:#a855f7}
.btn:disabled{background:#2a2a2c;color:#6b6b6f;cursor:not-allowed}
#msg{color:#6ee7b7;font-size:13px;flex:1;min-width:140px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.7);display:none;align-items:center;justify-content:center;z-index:50}
.modal.open{display:flex}
.sheet{background:#161617;border:1px solid #2a2a2c;border-radius:16px;padding:22px;max-width:760px;width:92%;max-height:86vh;overflow:auto}
.sheet h2{margin:0 0 4px;font-size:18px}.sheet .x{float:right;cursor:pointer;color:#8b8b8f;font-size:20px}
.cmpgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:14px}
.cmpcard{background:#1b1b1d;border:1px solid #2a2a2c;border-radius:12px;padding:14px;text-align:center}
.cmpcard .nm{justify-content:center}
</style></head><body><div class=wrap>
<h1>Voice Library</h1>
<div class=sub>Bấm ▶ để nghe thử ngay. Lọc theo mục đích/accent, chọn ⚖ để so sánh, rồi lưu giọng cho kênh. <b id=cnt></b></div>
<div class=bar>
  <input id=q placeholder="🔍 Tìm giọng (tên, accent, mô tả)…">
  <select id=fl><option value="">Mọi ngôn ngữ</option></select>
  <select id=fa><option value="">Mọi accent</option></select>
  <select id=fg><option value="">Mọi giới tính</option><option value=female>Nữ</option><option value=male>Nam</option></select>
  <select id=fp><option value="">Mọi nguồn</option><option value=kokoro>kokoro</option><option value=edge>edge</option><option value=piper>piper</option></select>
  <input id=text placeholder="Câu nghe thử riêng (tùy chọn)" style="flex:1;min-width:200px">
</div>
<div id=chips class=chips></div>
<div id=grid class=grid>Đang tải giọng…</div>
</div>
<div class=dock><div class=inner>
  <label style="color:#8b8b8f;font-size:13px">Kênh:</label>
  <select id=ch>__OPTS__</select>
  <span id=msg>Chưa chọn giọng nào.</span>
  <button class=btn alt id=cmpBtn disabled onclick=openCmp()>⚖ So sánh (0)</button>
  <button class=btn id=saveBtn disabled onclick=save()>✓ Lưu giọng đã chọn</button>
</div></div>
<div class=modal id=modal><div class=sheet>
  <span class=x onclick=closeCmp()>✕</span>
  <h2>So sánh giọng (A/B)</h2>
  <div style="color:#8b8b8f;font-size:13px">Cùng một câu, nghe lần lượt rồi chọn giọng ưng nhất.</div>
  <input id=cmptext placeholder="Câu nghe thử chung (tùy chọn)" style="width:100%;margin-top:12px">
  <div id=cmpgrid class=cmpgrid></div>
</div></div>
<audio id=player></audio>
<script>
const API=location.origin;
let VOICES=[], selected=null, playing=null, useCase='', compare=[];
const audio=document.getElementById('player');
audio.onended=()=>{ if(playing){setBtn(playing,'▶','play');playing=null;} };
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
// deterministic mini-waveform bars from the spec string (no audio analysis)
function bars(spec){let h=0;for(let i=0;i<spec.length;i++)h=(h*31+spec.charCodeAt(i))>>>0;
  let out='';for(let i=0;i<22;i++){h=(h*1103515245+12345)>>>0;const ht=4+(h%14);out+=`<i style="height:${ht}px"></i>`;}return out;}
function setBtn(spec,txt,cls){
  document.querySelectorAll('[data-play="'+CSS.escape(spec)+'"]').forEach(b=>{b.textContent=txt;b.className=b.className.replace(/\bplay [a-z]*$/,'').trim();b.classList.add('play');if(cls)b.classList.add(cls);});
}
async function previewUrl(spec,custom){
  const t=(custom!==undefined?custom:document.getElementById('text').value).trim();
  const u=API+'/api/voice/preview?spec='+encodeURIComponent(spec)+(t?'&text='+encodeURIComponent(t):'');
  const r=await fetch(u,{method:'POST'});const d=await r.json();
  if(!r.ok) throw new Error(d.detail||'lỗi');return API+d.url+'?t='+Date.now();
}
async function play(spec,ev,custom){
  if(ev) ev.stopPropagation();
  if(playing===spec){audio.pause();setBtn(spec,'▶','play');playing=null;return;}
  if(playing) setBtn(playing,'▶','play');
  setBtn(spec,'…','loading');
  const v=VOICES.find(x=>x.spec===spec);
  if(v&&v.needs_download) msg('Lần đầu nghe Piper sẽ tải model (~30-110MB), chờ chút…');
  try{
    audio.src=await previewUrl(spec,custom);await audio.play();
    setBtn(spec,'⏸','playing');playing=spec;
  }catch(e){setBtn(spec,'▶','play');msg('Lỗi nghe thử: '+e.message,1);}
}
function pick(spec){
  selected=spec;
  document.querySelectorAll('.card').forEach(c=>c.classList.toggle('sel',c.dataset.spec===spec));
  document.getElementById('saveBtn').disabled=false;
  msg('Đã chọn: '+spec);
}
function toggleCmp(spec,ev){
  ev.stopPropagation();
  const i=compare.indexOf(spec);
  if(i>=0)compare.splice(i,1); else {if(compare.length>=3){msg('Tối đa 3 giọng để so sánh',1);return;}compare.push(spec);}
  document.querySelectorAll('.cmp').forEach(b=>b.classList.toggle('on',compare.includes(b.dataset.cmp)));
  const cb=document.getElementById('cmpBtn');cb.textContent='⚖ So sánh ('+compare.length+')';cb.disabled=compare.length<2;
}
function openCmp(){
  if(compare.length<2)return;
  const g=document.getElementById('cmpgrid');g.innerHTML='';
  compare.forEach(spec=>{const v=VOICES.find(x=>x.spec===spec)||{spec,label:spec};
    const c=document.createElement('div');c.className='cmpcard';
    c.innerHTML=`<div class=nm>${esc(v.label)}</div><div class=desc>${esc(v.desc||'')}</div>
      <button class="play" data-play="${esc(spec)}" style="margin:8px auto" onclick="play('${esc(spec)}',event,document.getElementById('cmptext').value)">▶</button>
      <button class=btn style="width:100%;margin-top:6px" onclick="pick('${esc(spec)}');closeCmp()">Chọn giọng này</button>`;
    g.appendChild(c);});
  document.getElementById('modal').classList.add('open');
}
function closeCmp(){document.getElementById('modal').classList.remove('open');if(playing){audio.pause();setBtn(playing,'▶','play');playing=null;}}
function msg(t,err){const m=document.getElementById('msg');m.style.color=err?'#f87171':'#6ee7b7';m.textContent=t;}
async function save(){
  if(!selected) return;
  const ch=document.getElementById('ch').value;
  const r=await fetch(API+'/api/channel/'+ch+'/voice?spec='+encodeURIComponent(selected),{method:'POST'});
  const d=await r.json();
  if(r.ok) msg('✓ Đã lưu '+selected+' cho kênh '+ch); else msg('Lưu lỗi: '+(d.detail||''),1);
}
function render(){
  const q=document.getElementById('q').value.toLowerCase();
  const fg=document.getElementById('fg').value, fp=document.getElementById('fp').value;
  const fl=document.getElementById('fl').value.toLowerCase(), fa=document.getElementById('fa').value;
  const list=VOICES.filter(v=>(!fg||v.gender===fg)&&(!fp||v.provider===fp)&&
     (!fl||v.lang.toLowerCase().startsWith(fl))&&(!fa||v.accent===fa)&&
     (!useCase||v.use_case===useCase)&&
     (!q||(v.label+' '+v.spec+' '+v.lang+' '+(v.desc||'')+' '+(v.accent||'')).toLowerCase().includes(q)));
  const g=document.getElementById('grid');
  document.getElementById('cnt').textContent=list.length+' / '+VOICES.length+' giọng';
  if(!list.length){g.innerHTML='<div style=color:#8b8b8f>Không có giọng khớp.</div>';return;}
  g.innerHTML='';
  list.slice(0,400).forEach(v=>{
    const c=document.createElement('div');c.className='card'+(selected===v.spec?' sel':'');c.dataset.spec=v.spec;
    c.onclick=()=>pick(v.spec);
    const facets=[v.use_case,v.accent,v.age,v.pitch,v.gender].filter(Boolean)
       .map(f=>`<span class=pill>${esc(f)}</span>`).join('');
    const dl=v.needs_download?'<span class="pill dl">⬇ tải khi dùng</span>':'';
    c.innerHTML=`<button class="play play" data-play="${esc(v.spec)}" onclick="play('${esc(v.spec)}',event)">▶</button>
      <div class=meta><div class=nm>${esc(v.label)}</div>
      <div class=wave>${bars(v.spec)}</div>
      <div class=desc>${esc(v.desc||'')}</div>
      <div class=pills><span class="pill pv ${v.provider}">${v.provider}</span>
        <span class=pill>${esc(v.lang)}</span>${facets}${dl}</div></div>
      <div class=acts>
        <button class="cmp${compare.includes(v.spec)?' on':''}" data-cmp="${esc(v.spec)}" title="Thêm vào so sánh" onclick="toggleCmp('${esc(v.spec)}',event)">⚖</button>
        <div class=tick>✓</div></div>`;
    g.appendChild(c);
  });
}
function buildChips(ucs){
  const wrap=document.getElementById('chips');wrap.innerHTML='';
  const all=document.createElement('div');all.className='chip on';all.textContent='Tất cả';
  all.onclick=()=>{useCase='';document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));all.classList.add('on');render();};
  wrap.appendChild(all);
  ucs.forEach(uc=>{const ch=document.createElement('div');ch.className='chip';ch.textContent=uc;
    ch.onclick=()=>{useCase=uc;document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));ch.classList.add('on');render();};
    wrap.appendChild(ch);});
}
async function load(){
  const qp=new URLSearchParams(location.search).get('channel');
  if(qp){const ch=document.getElementById('ch');if([...ch.options].some(o=>o.value===qp))ch.value=qp;}
  const r=await fetch(API+'/api/voices');const d=await r.json();
  VOICES=d.voices||[];
  const fl=document.getElementById('fl');
  const en=document.createElement('option');en.value='en';en.textContent='English (tất cả)';fl.appendChild(en);
  (d.langs||[]).forEach(l=>{const o=document.createElement('option');o.value=l;o.textContent=l;fl.appendChild(o);});
  fl.value='en';
  const fa=document.getElementById('fa');
  (d.accents||[]).forEach(a=>{const o=document.createElement('option');o.value=a;o.textContent=a;fa.appendChild(o);});
  buildChips(d.use_cases||[]);
  render();
  ['q','fg','fp','fl','fa'].forEach(id=>document.getElementById(id).addEventListener('input',render));
}
load();
</script></body></html>"""
    return HTMLResponse(html.replace("__OPTS__", opts))
