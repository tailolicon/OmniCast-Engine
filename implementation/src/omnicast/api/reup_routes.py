"""Douyin reup API routes (isolated router, included by server.py).

  POST /api/reup/run        — start a job (background); returns job_id immediately
  GET  /api/reup/jobs       — list jobs from vault.db
  GET  /api/reup/jobs/{id}  — one job, full row
  GET  /api/reup/voices     — available Vietnamese voices
  GET  /api/reup/health     — dependency preflight (ffmpeg, vieneu, API key)

A job takes minutes (ASR + LLM + TTS + two ffmpeg passes), so `run` hands off to
a worker thread and the caller polls `jobs/{id}`. Progress lives in vault.db
rather than in memory, so it survives a backend restart.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from omnicast.reup import vault_link
from omnicast.reup.queue import QueuedJob, ReupQueue

IMPL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(IMPL_ROOT / "src"))

WORKSPACE_ROOT = IMPL_ROOT / "output" / "reup"
# Finished dubs are published here, same as every other producer's output.
PRODUCTS_DIR = IMPL_ROOT / "output" / "products"


def media_url(path: Path | str | None) -> str | None:
    """Serving URL for a reup file, or None if it is not under a served root.

    Two roots: the reup workspace holds working artifacts, the products tree
    holds delivered videos. The browser must never derive this itself — it used
    to split the filesystem path on `/reup/`, which silently produced a link to
    `C:\\...` once the product moved out of that directory.
    """
    if not path:
        return None
    candidate = Path(str(path))
    for root_dir, mount in ((WORKSPACE_ROOT, "/reupmedia"), (PRODUCTS_DIR, "/pmedia")):
        try:
            relative = candidate.relative_to(root_dir).as_posix()
        except ValueError:
            continue
        # Export filenames come from the Douyin title, which routinely carries
        # '#' (hashtags) and Chinese characters. Unencoded, '#' truncates the
        # URL at the fragment and the download 404s.
        return f"{mount}/" + quote(relative)
    return None

reup_router = APIRouter(prefix="/api/reup", tags=["reup"])


def _preflight_backend(backend: str, health: dict) -> None:
    """Refuse a job whose translation backend has no credentials.

    A job with an unusable backend still downloads, transcribes and only then
    dies at the translate stage — fifteen minutes in, with nothing to show. The
    answer is already in `health` before any of that work starts.
    """
    name = (backend or "").strip().lower()
    alias = {"claude": "claude-cli", "sonnet": "claude-cli"}.get(name, name)
    available = health.get("backends") or {}
    if alias in available and not available[alias]:
        usable = [key for key, ok in available.items() if ok]
        raise HTTPException(
            status_code=409,
            detail=(
                f"Engine dịch '{backend}' chưa có key/CLI. "
                f"Đang dùng được: {', '.join(usable) or 'không có cái nào'}."
            ),
        )

# "download" leads: the runner has always announced it, but it was missing from
# this tuple, so the UI lit no chip at all while a 5-minute download ran and the
# job looked frozen before it had even started.
STAGES = (
    "download", "bootstrap", "probe", "extract_audio", "asr", "translate",
    "subtitles", "tts", "voice_track", "mixdown", "export",
)


class ReupRunRequest(BaseModel):
    url: str = Field(
        ...,
        description=(
            "Douyin share link / www.douyin.com/video/<id>, or Bilibili "
            "(bilibili.com/video/BV…, av…, b23.tv/…, ?p=N for multi-part)"
        ),
    )
    voice_preset_id: str = "vieneu-default-vi"
    # None means "use the project preset", which is the CapCut voice the
    # operator configured. This defaulted to "Mai Anh", so any caller that
    # simply omitted the field silently overrode that preset and got VieNeu —
    # a whole video dubbed in the wrong voice with nothing in the request
    # saying so. A voice must be asked for, never assumed.
    voice_id: str | None = None
    export_preset_id: str = "youtube-16x9"
    stop_after: str | None = Field(
        None, description=f"halt after one of: {', '.join(STAGES)}"
    )
    asr_model: str = "small"
    # claude-cli rides the operator's Claude subscription, so it is the default:
    # a video fans out to dozens of scene calls and per-token billing adds up.
    translation_backend: str = "claude-cli"
    translation_model: str | None = None
    groq_api_key: str | None = None
    allow_pending_review: bool = Field(
        False, description="dub/export even with lines still awaiting review"
    )
    cookies: dict[str, str] = Field(default_factory=dict)
    proxy: str = ""
    channel_id: str | None = None
    # Library link: which series/episode this dub IS. Both optional — with only
    # series_id the episode number is parsed from the source title (or matched
    # by aweme_id against source-synced rows) once the download names the video.
    series_id: str | None = None
    episode_no: int | None = Field(None, ge=1)


@reup_router.get("/health")
def reup_health() -> dict:
    """Everything a job needs, checked before the user waits five minutes for a failure."""
    import importlib.util

    checks: dict[str, dict] = {}
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    checks["ffmpeg"] = {"ok": bool(ffmpeg and ffprobe), "detail": ffmpeg or "not on PATH"}
    checks["vieneu"] = {
        "ok": importlib.util.find_spec("vieneu") is not None,
        "detail": "local Vietnamese TTS",
    }
    checks["faster_whisper"] = {
        "ok": importlib.util.find_spec("faster_whisper") is not None,
        "detail": "zh ASR",
    }
    # Translation needs exactly one working backend, not all three. Reporting
    # the OpenAI key as a hard requirement made `ready` false on a machine that
    # was perfectly able to translate through the Claude CLI.
    # Through the resolver, so a key saved on the Providers screen counts. It
    # used to check os.environ only, and reported groq: false with the key
    # sitting in the vault.
    from omnicast.config.credentials import has_api_key

    has_openai = has_api_key("openai")
    has_claude_cli = shutil.which("claude") is not None
    has_groq = has_api_key("groq")

    checks["translate_backend"] = {
        "ok": has_claude_cli or has_openai or has_groq,
        "detail": ", ".join(
            name
            for name, present in (
                ("claude-cli", has_claude_cli),
                ("openai", has_openai),
                ("groq", has_groq),
            )
            if present
        )
        or "none available — install Claude CLI, or set an OpenAI/Groq key",
    }
    return {
        "ready": all(c["ok"] for c in checks.values()),
        "backends": {
            "claude-cli": has_claude_cli,
            "openai": has_openai,
            "groq": has_groq,
        },
        "checks": checks,
    }


# VieNeu first because it is the default dub engine, then the two ByteDance
# families (CapCut's own voices and the seed-tts-2.0 catalogue behind them),
# then the rest. Order drives the dropdown, so the useful ones sit on top.
_VOICE_PROVIDER_ORDER = (
    "vieneu", "capcut", "volcengine", "edge", "kokoro", "piper",
    "xttsv2", "f5tts", "chatterbox",
)


_VOICE_CATALOGUE: dict | None = None
_VOICE_CATALOGUE_LOCK = threading.Lock()


@reup_router.get("/voices")
def reup_voices() -> dict:
    """Every TTS voice reachable from a dub job, grouped by provider.

    This used to hand back VieNeu's 14 voices only, so CapCut's 129 and
    Volcengine's 102 were unreachable from the UI even though the runner
    accepts a full `provider:voice_id` spec and switches engine on it.

    Cached: building it imports every TTS backend, which measured ~9s cold and
    over 30s on a loaded server — long enough that the dropdown renders empty
    and looks broken. The catalogue is static for the life of the process.
    """
    global _VOICE_CATALOGUE
    if _VOICE_CATALOGUE is not None:
        return _VOICE_CATALOGUE
    with _VOICE_CATALOGUE_LOCK:
        if _VOICE_CATALOGUE is None:
            _VOICE_CATALOGUE = _build_voice_catalogue()
        return _VOICE_CATALOGUE


def _build_voice_catalogue() -> dict:
    from omnicast.media.providers.registry import _TTS_PROVIDER_FACTORIES, get_tts_provider

    known = list(_TTS_PROVIDER_FACTORIES)
    ordered = [p for p in _VOICE_PROVIDER_ORDER if p in known]
    ordered += [p for p in known if p not in ordered]

    groups, flat = [], []
    for provider_id in ordered:
        try:
            provider = get_tts_provider(provider_id)
        except Exception as exc:  # a provider that cannot load must not blank the list
            groups.append({"provider": provider_id, "name": provider_id, "error": str(exc)[:200], "voices": []})
            continue
        voices = [
            {
                "spec": f"{provider.id}:{model.id}",
                "id": model.id,
                "description": model.description,
                "provider": provider.id,
            }
            for model in provider.models
        ]
        groups.append({"provider": provider.id, "name": provider.name, "voices": voices})
        flat.extend(voices)

    # `voices` stays flat for the existing dropdown; `groups` is the richer shape.
    return {"provider": "all", "name": "Tất cả engine TTS", "groups": groups, "voices": flat}


@reup_router.get("/jobs")
def reup_jobs(status: str | None = None, limit: int = 25) -> dict:
    from omnicast.reup import vault_link

    # ReupJobRow is a slots dataclass, so it has no __dict__ to serialise.
    from dataclasses import asdict

    jobs = []
    for row in vault_link.list_jobs(status=status, limit=limit):
        item = asdict(row)
        # Served here, not derived in the browser: the UI used to split the
        # filesystem path on "/reup/", which broke the moment the finished
        # video moved into the products tree.
        item["video_url"] = media_url(item.get("exported_video_path"))
        jobs.append(item)
    return {"jobs": jobs}


@reup_router.get("/jobs/{job_id}")
def reup_job(job_id: str) -> dict:
    from omnicast.reup import vault_link

    row = vault_link.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No reup job {job_id}")
    return {**row, "video_url": media_url(row.get("exported_video_path"))}


def _open_job_db(job_id: str):
    """Return (ProjectDatabase, project_id) for a job, or 404."""
    from omnicast.reup import vault_link
    from omnicast.reup.project.database import ProjectDatabase

    row = vault_link.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No reup job {job_id}")
    root = row.get("project_root")
    project_id = row.get("project_id")
    if not root or not project_id:
        raise HTTPException(
            status_code=409,
            detail="Job has no project yet — it has not got past bootstrap.",
        )
    db_path = Path(str(root)) / "project.db"
    if not db_path.is_file():
        raise HTTPException(status_code=410, detail=f"Project database missing: {db_path}")
    return ProjectDatabase(db_path), str(project_id)


@reup_router.get("/jobs/{job_id}/segments")
def reup_segments(job_id: str, only_review: bool = False) -> dict:
    """Chinese source next to the Vietnamese result, line by line.

    This is the surface the operator actually judges the job on — the counts in
    the job list say a translation happened, not whether it is any good.
    """
    database, project_id = _open_job_db(job_id)

    analyses = {
        str(row["segment_id"]): row for row in database.list_segment_analyses(project_id)
    }
    items = []
    for seg in database.list_segments(project_id):
        segment_id = str(seg["segment_id"])
        analysis = analyses.get(segment_id)
        needs_review = bool(analysis["needs_human_review"]) if analysis else False
        if only_review and not needs_review:
            continue
        speaker = {}
        reasons: list[str] = []
        if analysis is not None:
            try:
                speaker = json.loads(analysis["speaker_json"] or "{}")
                reasons = json.loads(analysis["review_reason_codes_json"] or "[]")
            except (TypeError, ValueError):
                pass
        items.append(
            {
                "segment_id": segment_id,
                "index": seg["segment_index"],
                "start_ms": seg["start_ms"],
                "end_ms": seg["end_ms"],
                "source_text": seg["source_text"],
                "subtitle_text": seg["subtitle_text"],
                "tts_text": seg["tts_text"],
                "speaker": speaker.get("name") or speaker.get("speaker_key") or "",
                "needs_review": needs_review,
                "review_status": analysis["review_status"] if analysis else "draft",
                "review_reason_codes": reasons,
                "review_question": analysis["review_question"] if analysis else "",
            }
        )
    return {
        "job_id": job_id,
        "total": len(items),
        "pending_review": database.count_pending_segment_reviews(project_id),
        "segments": items,
    }


@reup_router.get("/jobs/{job_id}/context")
def reup_context(job_id: str) -> dict:
    """Scenes, characters and relationships the translator inferred.

    Contextual V2 builds this to keep Vietnamese pronouns consistent — getting
    anh/em/tôi/cậu right needs to know who is speaking to whom. Surfacing it
    lets the operator catch a wrong relationship early, which is cheaper than
    re-reading every line it distorted.
    """
    database, project_id = _open_job_db(job_id)

    def _name(row, *keys: str) -> str:
        for key in keys:
            try:
                value = row[key]
            except (IndexError, KeyError):
                continue
            if value:
                return str(value)
        return ""

    scenes = [
        {
            "scene_id": r["scene_id"],
            "index": r["scene_index"],
            "summary": _name(r, "short_scene_summary"),
        }
        for r in database.list_scene_memories(project_id)
    ]
    characters = [
        {
            "character_key": _name(r, "character_key", "character_id"),
            "display_name": _name(r, "display_name", "name"),
            "notes": _name(r, "notes", "description"),
        }
        for r in database.list_character_profiles(project_id)
    ]
    relationships = [
        {
            "speaker": _name(r, "speaker_key", "from_character_key"),
            "listener": _name(r, "listener_key", "to_character_key"),
            "relation_type": _name(r, "relation_type"),
            "speaker_pronoun": _name(r, "speaker_self_term", "speaker_pronoun"),
            "listener_pronoun": _name(r, "listener_address_term", "listener_pronoun"),
        }
        for r in database.list_relationship_profiles(project_id)
    ]
    return {
        "scenes": scenes,
        "characters": characters,
        "relationships": relationships,
    }


@reup_router.get("/jobs/{job_id}/artifacts")
def reup_artifacts(job_id: str) -> dict:
    """Files this job has actually produced, as browser-reachable URLs."""
    from omnicast.reup import vault_link

    row = vault_link.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No reup job {job_id}")
    root_raw = row.get("project_root")
    if not root_raw:
        return {"artifacts": []}
    root = Path(str(root_raw))

    # Subtitle/audio artifacts live under stage-hash cache dirs, not in
    # exports/ — only the final render lands there.
    artifacts = []
    for label, pattern in (
        ("Phụ đề SRT", "cache/subs/*/track.srt"),
        ("Phụ đề ASS", "cache/subs/*/track.ass"),
        # Named explicitly: a bare cache/mix/*/*.wav glob returns both the
        # voice-only track and the final mix, which look identical in a list.
        ("Track giọng", "cache/mix/*/voice_track.wav"),
        ("Audio đã trộn", "cache/mix/*/mixed_audio.wav"),
        ("Video xuất (thư mục làm việc)", "exports/*.mp4"),
    ):
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            artifacts.append(
                {
                    "label": label,
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                    "url": media_url(path),
                }
            )

    # The delivered product goes first: it is the copy with a Vietnamese name,
    # sitting next to its script and meta, and the one the operator wants.
    delivered = _published_product(job_id, root)
    if delivered is not None:
        artifacts.insert(
            0,
            {
                "label": "Video hoàn chỉnh (theo kênh)",
                "name": f"{delivered.parent.parent.name}/{delivered.parent.name}",
                "size_bytes": delivered.stat().st_size,
                "url": media_url(delivered),
            },
        )
    return {"artifacts": artifacts}


def _published_product(job_id: str, project_root: Path) -> Path | None:
    """The published `video.mp4` for this job, if it has been exported."""
    from omnicast.reup import vault_link
    from omnicast.reup.publish import resolve_product_dir

    row = vault_link.get_job(job_id) or {}
    recorded = str(row.get("exported_video_path") or "")
    if recorded.endswith("video.mp4") and Path(recorded).is_file():
        return Path(recorded)
    channel_id, _ = _job_channel_file(job_id)
    candidate = resolve_product_dir(
        channel_id, str(row.get("aweme_id") or project_root.name), ""
    ) / "video.mp4"
    return candidate if candidate.is_file() else None


@reup_router.post("/jobs/{job_id}/open")
def reup_open_result(job_id: str, target: str = "file") -> dict:
    """Open the finished video, or its folder, on the machine running the API.

    Streaming a 178 MB file into a webview tab is a poor way to watch it — the
    operator wants their own player, or Explorer. The backend is local, so it
    can just ask the desktop to open it.

    The path is resolved here from the job row and then checked to be inside a
    known output root: a path arriving from the client, or a poisoned database
    value, must never become something this hands to the shell.
    """
    import os
    import subprocess

    if target not in {"file", "folder"}:
        raise HTTPException(status_code=400, detail="target must be 'file' or 'folder'")

    root = _job_root(job_id)
    video = _published_product(job_id, root)
    if video is None:
        # Fall back to the working copy for jobs exported before publishing existed.
        video = next(iter(sorted((root / "exports").glob("*.mp4"))), None)
    if video is None or not video.is_file():
        raise HTTPException(status_code=409, detail="Job chưa có video xuất")

    resolved = video.resolve()
    if not any(
        resolved.is_relative_to(allowed.resolve())
        for allowed in (PRODUCTS_DIR, WORKSPACE_ROOT)
    ):
        raise HTTPException(status_code=400, detail="Refusing to open a path outside the output roots")

    try:
        if sys.platform == "win32":
            if target == "folder":
                # /select highlights the file instead of just listing the folder.
                subprocess.Popen(["explorer", "/select,", str(resolved)])
            else:
                os.startfile(str(resolved))  # noqa: S606 — local desktop, vetted path
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if target == "folder" else str(resolved)]
                             + ([str(resolved)] if target == "folder" else []))
        else:
            subprocess.Popen(["xdg-open", str(resolved.parent if target == "folder" else resolved)])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Không mở được: {exc}") from exc

    return {"opened": target, "path": str(resolved)}


class SegmentReviewPatch(BaseModel):
    approved_subtitle_text: str | None = None
    approved_tts_text: str | None = None
    approve: bool = Field(False, description="clear the review flag for this line")


@reup_router.post("/jobs/{job_id}/segments/{segment_id}/review")
def reup_review_segment(job_id: str, segment_id: str, patch: SegmentReviewPatch) -> dict:
    """Edit a flagged line and optionally clear its review flag.

    Clearing the flag is what unblocks TTS/export — the pipeline treats pending
    review as a hard gate, which is the point of translating a language the
    operator does not read.
    """
    database, project_id = _open_job_db(job_id)
    if database.get_segment_analysis(project_id, segment_id) is None:
        raise HTTPException(status_code=404, detail=f"No analysis for segment {segment_id}")

    database.update_segment_analysis_review(
        project_id,
        segment_id,
        approved_subtitle_text=patch.approved_subtitle_text,
        approved_tts_text=patch.approved_tts_text,
        needs_human_review=False if patch.approve else None,
        review_status="approved" if patch.approve else None,
    )
    if patch.approve:
        # Push approved text back into the canonical segments + subtitle track,
        # otherwise downstream stages keep reading the pre-review wording.
        database.apply_segment_analysis_outputs(project_id)

    return {
        "segment_id": segment_id,
        "pending_review": database.count_pending_segment_reviews(project_id),
    }


@reup_router.post("/run")
def reup_run(request: ReupRunRequest) -> dict:
    from omnicast.reup import vault_link

    if request.stop_after and request.stop_after not in STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"stop_after must be one of {list(STAGES)}",
        )

    health = reup_health()
    if not health["checks"]["ffmpeg"]["ok"]:
        raise HTTPException(status_code=503, detail="ffmpeg/ffprobe not available")
    _preflight_backend(request.translation_backend, health)

    # Validate the series BEFORE registering anything — a typo'd series_id
    # must fail the request, not orphan a queued job.
    series_row = None
    if request.series_id:
        from omnicast.library import store as library_store

        series_row = library_store.get_series(request.series_id)
        if series_row is None:
            raise HTTPException(
                status_code=404, detail=f"Không có series {request.series_id}"
            )

    job_id = f"reup-{uuid4().hex[:12]}"
    vault_link.register_job(
        job_id,
        request.url,
        channel_id=request.channel_id,
        voice_preset_id=request.voice_preset_id,
    )
    if series_row is not None:
        from omnicast.library import store as library_store

        if request.episode_no:
            library_store.attach_job_to_episode(
                job_id, request.series_id, int(request.episode_no),
                source_url=request.url,
            )
        elif str(series_row.get("kind") or "series") == "single":
            # Bucket video lẻ: số tập chỉ là thứ tự nội bộ — nhận slot kế tiếp
            # ngay lúc xếp hàng, người dùng không phải đánh số.
            library_store.attach_job_to_episode(
                job_id, request.series_id, None, source_url=request.url,
            )

    # Queued, not spawned: five pasted links used to start five dubs at once,
    # all fighting over the same CPU, GPU and Douyin rate limit.
    _queue().submit(QueuedJob(job_id=job_id, url=request.url, options=request.model_dump()))
    return {"job_id": job_id, "status": "queued", "poll": f"/api/reup/jobs/{job_id}"}


_REUP_QUEUE = None
_QUEUE_LOCK = threading.Lock()


def _library_sync(job_id: str, options: dict | None = None) -> None:
    """Push a job's outcome into its library episode (best effort).

    Order of resolution: episode already linked by job_id → episode holding the
    same aweme_id (source-synced rows snap in automatically) → a series hint
    from the request plus an episode number parsed from the source title.
    Never raises: bookkeeping must not fail a dub that already succeeded.
    """
    try:
        from omnicast.library import store as library_store

        episode = library_store.sync_episode_from_job(job_id)
        if episode is None and options and options.get("series_id"):
            from omnicast.library.titles import parse_episode
            from omnicast.reup import vault_link as _vl

            job = _vl.get_job(job_id) or {}
            ep_no = options.get("episode_no")
            if not ep_no:
                _, ep_no = parse_episode(str(job.get("title") or ""))
            if not ep_no:
                _, ep_no = parse_episode(str(job.get("title_vi") or ""))
            if not ep_no:
                # Video lẻ không có số tập trong tiêu đề — bucket 'single' tự
                # nhận slot kế tiếp thay vì để job mồ côi.
                series = library_store.get_series(str(options["series_id"]))
                if series and str(series.get("kind") or "series") == "single":
                    library_store.attach_job_to_episode(
                        job_id, str(options["series_id"]), None,
                        source_url=str(job.get("source_url") or ""),
                    )
                    library_store.sync_episode_from_job(job_id)
            else:
                library_store.attach_job_to_episode(
                    job_id, str(options["series_id"]), int(ep_no),
                    source_url=str(job.get("source_url") or ""),
                )
                library_store.sync_episode_from_job(job_id)
    except Exception as exc:
        print(f"[library] job {job_id} → episode sync failed: {type(exc).__name__}: {exc}")


def _run_queued_job(job) -> None:
    """Execute one queued job; raising here is what triggers a retry."""
    from omnicast.reup.runner import build_reup_settings, run_reup_job

    options = dict(job.options or {})
    root = str((vault_link.get_job(job.job_id) or {}).get("project_root") or "")
    try:
        run_reup_job(
            job.url,
            workspace_root=WORKSPACE_ROOT,
            cookies=options.get("cookies") or {},
            proxy=options.get("proxy") or "",
            settings=build_reup_settings(asr_model=options.get("asr_model") or "small"),
            voice_preset_id=options.get("voice_preset_id") or "vieneu-default-vi",
            voice_id=options.get("voice_id"),
            export_preset_id=options.get("export_preset_id") or "youtube-16x9",
            stop_after=options.get("stop_after"),
            channel_id=options.get("channel_id"),
            job_id=job.job_id,
            translation_backend=options.get("translation_backend") or "claude-cli",
            translation_model=options.get("translation_model"),
            groq_api_key=options.get("groq_api_key"),
            allow_pending_review=bool(options.get("allow_pending_review")),
            # A retry resumes: the caches make it skip everything already done.
            resume_project_root=Path(root) if job.attempts > 1 and Path(root or ".").is_dir() else None,
        )
    finally:
        # Success, review-stop or failure — the episode row mirrors all three.
        _library_sync(job.job_id, options)


def _queue():
    global _REUP_QUEUE
    if _REUP_QUEUE is None:
        with _QUEUE_LOCK:
            if _REUP_QUEUE is None:
                _REUP_QUEUE = ReupQueue(_run_queued_job)
                _REUP_QUEUE.start()
    return _REUP_QUEUE


class ReupQueueRequest(BaseModel):
    """A batch of links sharing one set of options."""

    urls: list[str] = Field(..., description="one Douyin link per entry")
    voice_preset_id: str = "vieneu-default-vi"
    voice_id: str | None = None
    export_preset_id: str = "youtube-16x9"
    stop_after: str | None = None
    asr_model: str = "small"
    translation_backend: str = "claude-cli"
    translation_model: str | None = None
    allow_pending_review: bool = False
    channel_id: str | None = None
    # One series for the whole batch; episode numbers come from each video's
    # title (or aweme match against source-synced rows) after download.
    series_id: str | None = None


@reup_router.post("/queue")
def reup_enqueue(request: ReupQueueRequest) -> dict:
    """Queue several links at once; they run one after another."""
    urls = [u.strip() for u in request.urls if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Chưa có link nào")
    if request.stop_after and request.stop_after not in STAGES:
        raise HTTPException(status_code=400, detail=f"stop_after must be one of {list(STAGES)}")
    if request.series_id:
        from omnicast.library import store as library_store

        if library_store.get_series(request.series_id) is None:
            raise HTTPException(
                status_code=404, detail=f"Không có series {request.series_id}"
            )

    options = request.model_dump(exclude={"urls"})
    accepted = []
    for url in urls:
        job_id = f"reup-{uuid4().hex[:12]}"
        vault_link.register_job(
            job_id, url,
            channel_id=request.channel_id,
            voice_preset_id=request.voice_preset_id,
        )
        _queue().submit(QueuedJob(job_id=job_id, url=url, options={**options, "url": url}))
        accepted.append({"job_id": job_id, "url": url})
    return {"queued": len(accepted), "jobs": accepted, "queue": _queue().snapshot()}


@reup_router.get("/queue")
def reup_queue_state() -> dict:
    return _queue().snapshot()


class ReupResumeRequest(BaseModel):
    """Overrides for a resumed run. Everything else comes off the job row."""

    translation_backend: str | None = None
    translation_model: str | None = None
    stop_after: str | None = None
    voice_id: str | None = None
    export_preset_id: str | None = None
    allow_pending_review: bool = False
    asr_model: str = "small"


@reup_router.post("/jobs/{job_id}/resume")
def reup_resume(job_id: str, request: ReupResumeRequest | None = None) -> dict:
    """Re-run a job against its existing workspace, skipping finished work.

    Every stage is keyed by a content hash, so a resume walks past the download,
    the ASR and the translation already on disk and picks up where it stopped.
    That matters: a job that died at `translate` for a missing API key had
    already spent five minutes downloading and six transcribing, and starting
    over threw all of it away.
    """
    from omnicast.reup import vault_link

    request = request or ReupResumeRequest()
    row = vault_link.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No reup job {job_id}")
    if row.get("status") == "running":
        raise HTTPException(status_code=409, detail="Job đang chạy rồi")
    project_root = str(row.get("project_root") or "")
    if not project_root or not Path(project_root).is_dir():
        raise HTTPException(
            status_code=409,
            detail="Job chưa có workspace để chạy tiếp — tạo job mới với cùng link.",
        )
    if request.stop_after and request.stop_after not in STAGES:
        raise HTTPException(status_code=400, detail=f"stop_after must be one of {list(STAGES)}")

    def _work() -> None:
        from omnicast.reup.runner import build_reup_settings, run_reup_job

        try:
            run_reup_job(
                str(row.get("source_url") or ""),
                workspace_root=WORKSPACE_ROOT,
                settings=build_reup_settings(asr_model=request.asr_model),
                voice_preset_id=str(row.get("voice_preset_id") or "vieneu-default-vi"),
                voice_id=request.voice_id,
                export_preset_id=request.export_preset_id or "youtube-16x9",
                stop_after=request.stop_after,
                channel_id=row.get("channel_id"),
                job_id=job_id,
                translation_backend=request.translation_backend or "claude-cli",
                translation_model=request.translation_model,
                allow_pending_review=request.allow_pending_review,
                resume_project_root=Path(project_root),
            )
        except Exception as exc:  # the runner already recorded the failure
            print(f"[reup] resume {job_id} failed: {type(exc).__name__}: {exc}")
        finally:
            _library_sync(job_id)

    vault_link.update_job(job_id, status="running", error="")
    threading.Thread(target=_work, name=f"reup-resume-{job_id}", daemon=True).start()
    return {"job_id": job_id, "status": "running", "resumed_from": project_root}


# ─── Overlay editor ─────────────────────────────────────────────────────────
# Cover regions, channel logo and the roaming watermark are positioned by hand
# against a real frame, so the editor needs a still to draw on and somewhere to
# persist what was drawn. Geometry is fractions of the frame, so the same boxes
# hold whether the export is 16:9 or a 9:16 short.


def _job_root(job_id: str) -> Path:
    from omnicast.reup import vault_link

    row = vault_link.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No reup job {job_id}")
    root = row.get("project_root")
    if not root:
        raise HTTPException(status_code=409, detail="Job has no project yet")
    return Path(str(root))


@reup_router.get("/jobs/{job_id}/frame")
def reup_frame(job_id: str, t: float = 5.0) -> Response:
    """A single still from the source, for the overlay editor to draw on."""
    import subprocess

    root = _job_root(job_id)
    database, project_id = _open_job_db(job_id)
    row = database.get_primary_video_asset(project_id)
    if row is None:
        raise HTTPException(status_code=409, detail="Project has no source video")

    frame_path = root / "cache" / "frames" / f"t{max(0.0, float(t)):.1f}.jpg"
    if not frame_path.is_file():
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise HTTPException(status_code=503, detail="ffmpeg not on PATH")
        result = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{max(0.0, float(t)):.3f}",
             "-i", str(row["path"]), "-frames:v", "1", "-q:v", "3", str(frame_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not frame_path.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"frame grab failed: {(result.stderr or '')[-200:]}",
            )
    return Response(content=frame_path.read_bytes(), media_type="image/jpeg")


def _job_channel_file(job_id: str) -> tuple[str | None, Path | None]:
    """(channel_id, channel config path) for a job — either may be None."""
    from omnicast.reup import vault_link
    from omnicast.reup.media.overlay import channel_file_for

    row = vault_link.get_job(job_id) or {}
    channel_id = row.get("channel_id")
    return channel_id, channel_file_for(channel_id)


@reup_router.get("/jobs/{job_id}/overlays")
def reup_get_overlays(job_id: str) -> dict:
    from omnicast.reup.media.overlay import load_config

    root = _job_root(job_id)
    database, project_id = _open_job_db(job_id)
    row = database.get_primary_video_asset(project_id)
    channel_id, channel_file = _job_channel_file(job_id)
    return {
        # A job that predates its channel's defaults, or that was never opened
        # in the editor, still gets the channel's branding.
        "overlays": load_config(root, channel_file).to_dict(),
        "channel_id": channel_id,
        "channel_has_defaults": channel_file is not None,
        # The editor needs the real aspect ratio to place its canvas.
        "video": {
            "width": int(row["width"] or 0) if row else 0,
            "height": int(row["height"] or 0) if row else 0,
            "duration_ms": int(row["duration_ms"] or 0) if row else 0,
        },
    }


@reup_router.put("/jobs/{job_id}/overlays")
def reup_put_overlays(job_id: str, payload: dict) -> dict:
    from omnicast.reup.media.overlay import OverlayConfig, save_channel_defaults, save_config

    root = _job_root(job_id)
    try:
        config = OverlayConfig.from_dict(payload.get("overlays") or payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"bad overlay config: {exc}") from exc
    save_config(root, config)

    # Promoting to the channel is explicit: the boxes are usually specific to
    # this video, so silently overwriting the channel default would be wrong.
    saved_to_channel = False
    if payload.get("as_channel_default"):
        channel_id, channel_file = _job_channel_file(job_id)
        if channel_file is None:
            raise HTTPException(
                status_code=409,
                detail=f"Job is not bound to a channel config ({channel_id or 'none'})",
            )
        save_channel_defaults(channel_file, config)
        saved_to_channel = True
    return {"saved": True, "saved_to_channel": saved_to_channel, "overlays": config.to_dict()}


def _latest(root: Path, pattern: str) -> Path | None:
    """Newest file matching a cache glob, or None."""
    found = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


@reup_router.post("/jobs/{job_id}/export")
def reup_reexport(job_id: str, gpu: bool = False) -> dict:
    """Re-run only the export stage against the saved overlays.

    Saving in the editor writes overlays.json and nothing else — the video on
    disk is whatever the last export produced. This is the step that turns saved
    boxes into a finished file, without re-downloading, re-translating or
    re-voicing. The subtitle track is regenerated first so a font size or
    position chosen in the editor actually reaches the burn-in.
    """
    from omnicast.reup.core.jobs import CancellationToken, JobContext
    from omnicast.reup.media.retime import load_timeline, shift_rows_to_timeline
    from omnicast.reup.project.bootstrap import open_project
    from omnicast.reup.publish import publish_reup_product
    from omnicast.reup.subtitle.export import export_subtitles, restyle_ass
    from omnicast.reup.subtitle.hardsub import (
        export_hardsub_video,
        gpu_encoder_available,
        load_export_preset,
    )
    from omnicast.reup import vault_link

    # Two exports on one project write the same output and the same `.partial`
    # staging file, which is how a delivered video ends up with garbage NAL
    # units. The pipeline runs its own export at the end of a job, so a manual
    # one on top of a running job is exactly that collision.
    if (vault_link.get_job(job_id) or {}).get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Job đang chạy — đợi nó xuất xong rồi hãy xuất lại.",
        )

    root = _job_root(job_id)
    database, project_id = _open_job_db(job_id)
    asset = database.get_primary_video_asset(project_id)
    if asset is None:
        raise HTTPException(status_code=409, detail="Project has no source video")
    track = database.get_active_subtitle_track(project_id)
    if track is None:
        raise HTTPException(status_code=409, detail="Job has no subtitle track yet")
    # Subtitle EVENTS, not raw segments: the events carry the timings the run
    # settled on, and the two diverge as soon as the video is rate-aligned.
    rows = [dict(r) for r in database.list_subtitle_events(project_id, track_id=str(track["track_id"]))]
    if not rows:
        raise HTTPException(status_code=409, detail="Job has no subtitle rows yet")

    # Prefer the rate-aligned cut: that is what the mixed voice track lines up
    # with. A job that never needed retiming exports the original.
    retime_dir = root / "cache" / "retime"
    retimed = retime_dir / "retimed_video.mp4"
    was_retimed = retimed.is_file()
    source = retimed if was_retimed else Path(str(asset["path"]))
    mixed = _latest(root, "cache/mix/*/mixed_audio.wav")
    if mixed is None:
        raise HTTPException(status_code=409, detail="Job has no mixed audio; run the dub first")

    # A retimed video needs subtitles on the stretched timeline. Newer runs
    # record it; for older ones the only trustworthy copy is the .ass the run
    # itself produced, which we re-skin rather than rebuild.
    timeline = load_timeline(retime_dir) if was_retimed else {}
    previous_ass: Path | None = None
    if was_retimed and not timeline:
        extra = vault_link.get_job(job_id) or {}
        raw = extra.get("extra_json")
        try:
            recorded = json.loads(raw).get("subtitle_paths", []) if isinstance(raw, str) else []
        except ValueError:
            recorded = []
        previous_ass = next(
            (p for p in (Path(s) for s in recorded) if p.suffix == ".ass" and p.is_file()), None
        )
        if previous_ass is None:
            raise HTTPException(
                status_code=409,
                detail="Video này đã bị giãn thời gian nhưng không còn bản phụ đề khớp; "
                       "chạy lại job để dựng lại timeline trước khi xuất.",
            )

    workspace = open_project(root)
    channel_id, _ = _job_channel_file(job_id)
    export_preset = None
    if gpu:
        if not gpu_encoder_available():
            raise HTTPException(status_code=409, detail="Máy này không có h264_nvenc")
        export_preset = load_export_preset(root).model_copy(
            update={"video_codec": "h264_nvenc"}
        )

    def _work() -> None:
        try:
            vault_link.update_job(job_id, status="running", last_stage="export")
            if previous_ass is not None:
                subtitle = restyle_ass(workspace, previous_ass)
            else:
                subtitle = export_subtitles(
                    workspace,
                    segments=shift_rows_to_timeline(rows, timeline) if timeline else rows,
                    format_name="ass",
                    # The runner exports with this off; leaving it on would put
                    # the Chinese source back on any line without a translation.
                    allow_source_fallback=False,
                )
            output = export_hardsub_video(
                JobContext(
                    job_id=job_id,
                    logger_name="omnicast.reup.export",
                    cancellation_token=CancellationToken(),
                    progress_callback=lambda value, message: None,
                ),
                workspace=workspace,
                source_video_path=source,
                subtitle_path=subtitle,
                ffmpeg_path=shutil.which("ffmpeg"),
                duration_ms=int(asset["duration_ms"] or 0) or None,
                replacement_audio_path=mixed,
                export_preset=export_preset,
            )
            job_row = vault_link.get_job(job_id) or {}
            product_dir = publish_reup_product(
                channel=channel_id,
                aweme_id=str(job_row.get("aweme_id") or root.name),
                exported_video=output,
                title=str(job_row.get("title_vi") or workspace.name),
                source_url=str(job_row.get("source_url") or ""),
                subtitle_paths=[subtitle],
                script_lines=[str(r.get("subtitle_text") or "") for r in rows],
                segment_count=len(rows),
                job_id=job_id,
                encoder="h264_nvenc" if gpu else "libx264",
            )
            vault_link.update_job(
                job_id, status="done", last_stage="export",
                exported_video=product_dir / "video.mp4",
            )
            _library_sync(job_id)
        except Exception as exc:
            vault_link.update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
            print(f"[reup] re-export {job_id} failed: {type(exc).__name__}: {exc}")

    threading.Thread(target=_work, name=f"reup-export-{job_id}", daemon=True).start()
    return {"job_id": job_id, "status": "running", "poll": f"/api/reup/jobs/{job_id}"}


def _preview_subtitle(root: Path, config, at: float) -> Path | None:
    """A one-cue .ass for the preview: real text, the editor's current style.

    Two reasons not to burn the project's own track. It only carries a line
    where the speaker happens to be talking, so most previewed frames showed no
    subtitle at all — nothing to size against. And its style comes from the last
    save, so dragging the font-size slider changed nothing on screen, which is
    exactly the calibration the preview exists for.

    The text is the cue nearest the previewed instant, held open across the
    whole frame, styled from the payload rather than from disk.
    """
    import pysubs2

    tracks = sorted(
        (root / "cache" / "subs").glob("*/track.ass"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not tracks:
        return None
    try:
        source = pysubs2.load(str(tracks[0]), encoding="utf-8")
    except Exception:
        return None
    if not source.events:
        return None

    at_ms = max(0.0, at) * 1000
    nearest = min(
        source.events,
        key=lambda e: 0 if e.start <= at_ms <= e.end else min(abs(e.start - at_ms), abs(e.end - at_ms)),
    )

    style = source.styles.get("Default") or pysubs2.SSAStyle()
    subtitle = config.subtitle
    style.fontname = subtitle.font_name or style.fontname
    style.fontsize = subtitle.font_size
    style.outline = subtitle.outline
    style.shadow = subtitle.shadow
    style.alignment = pysubs2.Alignment(subtitle.alignment)
    style.marginl, style.marginr, style.marginv = (
        subtitle.margin_l, subtitle.margin_r, subtitle.margin_v,
    )

    preview = pysubs2.SSAFile()
    preview.styles["Default"] = style
    preview.append(pysubs2.SSAEvent(start=0, end=6 * 60 * 60 * 1000, text=nearest.text))
    out = root / "cache" / "frames" / "preview.ass"
    out.parent.mkdir(parents=True, exist_ok=True)
    preview.save(str(out))
    return out


@reup_router.post("/jobs/{job_id}/overlays/preview")
def reup_overlay_preview(job_id: str, payload: dict) -> Response:
    """Render one frame with the given overlays, so changes can be judged."""
    import subprocess

    from omnicast.reup.media.overlay import OverlayConfig
    from omnicast.reup.subtitle.hardsub import build_video_filter_graph, load_export_preset

    root = _job_root(job_id)
    database, project_id = _open_job_db(job_id)
    row = database.get_primary_video_asset(project_id)
    if row is None:
        raise HTTPException(status_code=409, detail="Project has no source video")

    config = OverlayConfig.from_dict(payload.get("overlays") or {})
    at = float(payload.get("t") or 5.0)
    preset = load_export_preset(root, payload.get("export_preset_id") or None)
    subtitle = _preview_subtitle(root, config, at)
    if subtitle is None:
        preset = preset.model_copy(update={"burn_subtitles": False})
        subtitle = root / "missing.ass"

    graph, label = build_video_filter_graph(
        subtitle_path=subtitle, export_preset=preset, overlays=config
    )
    out = root / "cache" / "frames" / "preview.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    result = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{max(0.0, at):.3f}",
         "-i", str(row["path"]), "-filter_complex", graph, "-map", label,
         "-frames:v", "1", "-q:v", "3", str(out)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not out.is_file():
        raise HTTPException(
            status_code=500, detail=f"preview failed: {(result.stderr or '')[-300:]}"
        )
    return Response(content=out.read_bytes(), media_type="image/jpeg")
