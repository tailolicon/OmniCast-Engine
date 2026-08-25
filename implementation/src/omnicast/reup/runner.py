"""Headless Douyin → Vietnamese reup pipeline.

Chains the ingest layer onto the ported reup stages in the same order the
upstream desktop app runs them:

    download → probe → extract audio → ASR (zh) → contextual translate (zh→vi)
    → subtitles → TTS → voice track → mixdown → export

Storage note: each job gets its own `project.db` inside its workspace, because
the ported data layer assumes one project per database — `ProjectDatabase.
get_project()` is a bare `SELECT * FROM projects LIMIT 1`, so several projects
sharing one file would silently read each other's rows. `output/vault.db` stays
the SSOT for anything with a lifecycle: the job is registered there (see
`omnicast.reup.vault_link`) and the per-job database is working state, in the
same category as the stage caches beside it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from omnicast.ingest.douyin import DouyinAsset, DouyinIngestConfig, fetch_video_sync
from omnicast.reup import vault_link
from omnicast.reup.asr.faster_whisper_engine import FasterWhisperEngine
from omnicast.reup.asr.models import TranscriptionOptions
from omnicast.reup.asr.persistence import (
    build_asr_stage_hash,
    persist_transcription_result,
)
from omnicast.reup.audio.mixdown import mix_audio_tracks
from omnicast.reup.audio.rate_align import DEFAULT_MAX_AUDIO_SPEED, build_align_plan
from omnicast.reup.audio.voiceover_track import build_voice_track
from omnicast.reup.core.jobs import CancellationToken, JobContext
from omnicast.reup.core.settings import AppSettings, DependencyPaths
from omnicast.reup.media.extract_audio import extract_audio_artifacts
from omnicast.reup.media.ffprobe_service import attach_source_video_to_project, probe_media
from omnicast.reup.media.overlay import (
    SubtitleStyle,
    channel_file_for,
    load_channel_defaults,
    save_config as save_overlay_config,
)
from omnicast.reup.media.retime import retime_to_plan, shift_subtitle_rows
from omnicast.reup.project.bootstrap import (
    bootstrap_project,
    open_project,
    sync_project_snapshot,
)
from omnicast.reup.project.database import ProjectDatabase
from omnicast.reup.publish import publish_reup_product
from omnicast.reup.project.models import ProjectInitRequest
from omnicast.reup.project.profiles import (
    load_project_profile_state,
    resolve_project_profile_mix_defaults,
)
from omnicast.reup.subtitle.export import export_subtitles
from omnicast.reup.subtitle.hardsub import export_hardsub_video
from omnicast.reup.translate.contextual_checkpoint import (
    clear_contextual_translation_checkpoint,
    load_contextual_translation_checkpoint,
    persist_contextual_translation_checkpoint,
)
from omnicast.reup.translate.contextual_pipeline import (
    build_contextual_translation_stage_hash,
    load_cached_contextual_translation,
    persist_contextual_translation_result,
    restore_cached_contextual_translation,
)
from omnicast.reup.translate.contextual_runtime import run_contextual_translation
from omnicast.reup.translate.llm_backends import build_translation_engine
from omnicast.reup.translate.presets import load_prompt_template
from omnicast.reup.translate.title import translate_title
from omnicast.reup.tts.base import build_tts_stage_hash
from omnicast.reup.tts.factory import create_tts_engine
from omnicast.reup.tts.pipeline import synthesize_segments
from omnicast.reup.tts.presets import list_voice_presets, save_voice_preset

# zh→vi narration with VieNeu — the profile the upstream project tuned its
# speed/subtitle/mix defaults against.
DEFAULT_PROJECT_PROFILE = "zh-vi-narration-fast-v2-vieneu"
DEFAULT_VOICE_PRESET = "vieneu-default-vi"
# The preset ships `voice_id="default"`, and VieNeu's own default is "Minh Đức"
# — a male news voice. A reup channel that asked for nothing in particular got
# a man reading every line without anything in the logs saying so. Name the
# voice explicitly instead of inheriting an engine default.
DEFAULT_VOICE_ID = "Mai Anh"
DEFAULT_EXPORT_PRESET = "youtube-16x9"


class ReupError(RuntimeError):
    """Raised when a reup stage cannot proceed."""


@dataclass(slots=True)
class ReupJobResult:
    project_id: str
    project_root: Path
    asset: DouyinAsset
    source_video: Path
    segment_count: int = 0
    subtitle_paths: list[Path] = field(default_factory=list)
    voice_track: Path | None = None
    mixed_audio: Path | None = None
    exported_video: Path | None = None
    review_pending: int = 0
    title_vi: str = ""
    tags_vi: list[str] = field(default_factory=list)
    stages_run: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.review_pending > 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _asset_from_project(workspace, database: ProjectDatabase, url: str) -> DouyinAsset:
    """Rebuild a `DouyinAsset` for a project already on disk.

    Resuming must not re-download, so the source video comes back out of
    `media_assets` rather than from Douyin.
    """
    row = database.get_primary_video_asset(workspace.project_id)
    if row is None:
        raise ReupError(f"Project {workspace.project_id} has no source video recorded")
    video_path = Path(str(row["path"]))
    if not video_path.is_file():
        raise ReupError(f"Recorded source video is gone: {video_path}")
    return DouyinAsset(
        aweme_id=workspace.root_dir.name,
        source_url=url,
        video_path=video_path,
        title=workspace.name,
        author_name="",
        media_type="video",
        save_dir=video_path.parent,
    )


def _job_context(stage: str) -> JobContext:
    """A progress sink for stages run outside the JobManager pool."""
    return JobContext(
        job_id=f"reup-{stage}",
        logger_name=f"omnicast.reup.{stage}",
        cancellation_token=CancellationToken(),
        progress_callback=lambda value, message: None,
    )


def build_reup_settings(
    *,
    openai_api_key: str | None = None,
    asr_model: str = "small",
    translation_model: str = "gpt-4.1-mini",
) -> AppSettings:
    """Build reup's settings object from OmniCast's, in memory.

    Upstream reads `%APPDATA%/ReupVideo/settings.json` and DPAPI-decrypts the
    API key from it. OmniCast already owns both the binary paths and the key, so
    the file is bypassed entirely rather than kept in sync.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ReupError("ffmpeg/ffprobe not found on PATH — required by every reup stage")

    if openai_api_key is None:
        try:
            from omnicast.config.settings import get_settings

            openai_api_key = get_settings().openai_api_key
        except Exception:  # settings are optional in bare test environments
            openai_api_key = ""

    settings = AppSettings(
        dependency_paths=DependencyPaths(ffmpeg_path=ffmpeg, ffprobe_path=ffprobe),
        default_asr_model=asr_model,
        default_translation_model=translation_model,
    )
    # The key lives in a PrivateAttr that the file loader normally populates.
    settings._openai_api_key = openai_api_key or ""
    return settings


def run_reup_job(
    url: str,
    *,
    workspace_root: Path,
    project_name: str | None = None,
    cookies: dict[str, str] | None = None,
    proxy: str = "",
    settings: AppSettings | None = None,
    project_profile_id: str = DEFAULT_PROJECT_PROFILE,
    voice_preset_id: str = DEFAULT_VOICE_PRESET,
    voice_id: str | None = DEFAULT_VOICE_ID,
    export_preset_id: str = DEFAULT_EXPORT_PRESET,
    source_language: str = "zh",
    target_language: str = "vi",
    stop_after: str | None = None,
    on_stage: Callable[[str, str], None] | None = None,
    job_id: str | None = None,
    channel_id: str | None = None,
    translation_backend: str = "claude-cli",
    translation_model: str | None = None,
    groq_api_key: str | None = None,
    resume_project_root: Path | None = None,
    allow_pending_review: bool = False,
    max_audio_speed: float | None = DEFAULT_MAX_AUDIO_SPEED,
) -> ReupJobResult:
    """Run the whole chain for one Douyin URL.

    `stop_after` halts once the named stage completes — useful for inspecting
    the translation before paying for TTS. Stage names are the strings reported
    through `on_stage` and collected in `ReupJobResult.stages_run`.
    """
    settings = settings or build_reup_settings()
    workspace_root = workspace_root.expanduser().resolve()
    job_id = job_id or f"reup-{uuid4().hex[:12]}"

    vault_link.register_job(
        job_id, url, channel_id=channel_id, voice_preset_id=voice_preset_id
    )

    def _announce(stage: str, detail: str = "") -> None:
        # "done" is the terminal sentinel, not a stage being entered. Writing
        # status="running" for it undid the done/review status `_done` had just
        # set, which is why finished jobs sat in the list as "running" forever
        # with every stage chip green.
        if stage != "done":
            vault_link.update_job(job_id, status="running", last_stage=stage)
        if on_stage:
            on_stage(stage, detail)

    def _done(stage: str, result: ReupJobResult) -> bool:
        result.stages_run.append(stage)
        finished = stop_after == stage or stage == "export"
        vault_link.update_job(
            job_id,
            status="review" if (finished and result.needs_review) else ("done" if finished else "running"),
            last_stage=stage,
            result=result,
        )
        return stop_after == stage

    try:
        # ── 1. download (or pick the existing project back up) ───────────────────
        # Every stage below is keyed by a content stage-hash, so re-entering a
        # finished project skips straight past the work already on disk. Without
        # this, inspecting a translation meant re-downloading the source — 309 MB
        # for a single 8-minute video.
        if resume_project_root is not None:
            project_root = resume_project_root.expanduser().resolve()
            if not (project_root / "project.db").is_file():
                raise ReupError(f"No project to resume at {project_root}")
            workspace = open_project(project_root)
            database = ProjectDatabase(workspace.database_path)
            asset = _asset_from_project(workspace, database, url)
            _announce("download", f"resume {project_root.name} — {asset.title[:60]}")
        else:
            _announce("download", url)
            downloads_dir = workspace_root / "_downloads"
            from omnicast.ingest.detect import detect_source_platform

            if detect_source_platform(url) == "bilibili":
                # Same shape as the douyin path: the asset mirrors DouyinAsset's
                # fields, so everything below download never learns the platform.
                from omnicast.ingest.bilibili import BilibiliIngestConfig
                from omnicast.ingest.bilibili import fetch_video as fetch_bilibili

                asset = fetch_bilibili(
                    url,
                    BilibiliIngestConfig(
                        output_dir=downloads_dir, cookies=cookies or {}, proxy=proxy
                    ),
                )
            else:
                asset = fetch_video_sync(
                    url,
                    DouyinIngestConfig(
                        output_dir=downloads_dir, cookies=cookies or {}, proxy=proxy
                    ),
                )
            _announce("download", f"{asset.video_path.name} — {asset.title[:60]}")

            # ── 2. project bootstrap ─────────────────────────────────────────────
            project_root = workspace_root / f"{asset.aweme_id}"
            # A finished bootstrap for this same video is not a conflict, it is
            # work already done: every stage below is keyed by a content hash,
            # so adopting the workspace skips straight past what is on disk.
            # Refusing here meant re-running a video you already had died at the
            # download stage instead of picking up where it left off.
            if (project_root / "project.json").is_file() and (project_root / "project.db").is_file():
                _announce("bootstrap", f"dùng lại workspace sẵn có: {project_root.name}")
                workspace = open_project(project_root)
                database = ProjectDatabase(workspace.database_path)
            elif project_root.exists() and any(project_root.iterdir()):
                # Half-written: no project.json/db to reopen, so adopting it
                # would build on rubble.
                raise ReupError(
                    f"Project folder has partial data with no project.json/project.db: "
                    f"{project_root} — delete it or pass resume_project_root."
                )
            else:
                workspace = bootstrap_project(
                    ProjectInitRequest(
                        name=project_name or (asset.title[:60] or f"douyin-{asset.aweme_id}"),
                        root_dir=project_root,
                        source_language=source_language,
                        target_language=target_language,
                        source_video_path=asset.video_path,
                        project_profile_id=project_profile_id,
                    )
                )
                database = ProjectDatabase(workspace.database_path)

            # Seed the job's overlays from the channel so branding (logo,
            # roaming mark, subtitle style) carries across every video on that
            # channel. Everything downstream reads the project copy, so the
            # operator can still adjust the boxes for this one video.
            if channel_id:
                seed = load_channel_defaults(channel_file_for(channel_id))
                if seed.render_fingerprint() is not None or seed.subtitle != SubtitleStyle():
                    save_overlay_config(workspace.root_dir, seed)

        presets = {p.voice_preset_id: p for p in list_voice_presets(workspace.root_dir)}
        if voice_preset_id not in presets:
            raise ReupError(
                f"Voice preset {voice_preset_id!r} not in project presets: {sorted(presets)}"
            )
        # Picking one of VieNeu's 14 shipped voices is choosing a `voice_id`, not
        # a whole preset — the project only ever ships `vieneu-default-vi` and a
        # clone template. Write the choice into the preset so speed/volume and
        # the TTS stage hash both follow it.
        if voice_id:
            # A bare name keeps the preset's engine ("Mai Anh" -> vieneu); a
            # full spec switches engine too ("capcut:BV074_streaming"), which
            # is how any OmniCast provider becomes reachable from a dub job.
            preset = presets[voice_preset_id]
            if ":" in voice_id:
                engine, _, resolved_voice = voice_id.partition(":")
            else:
                engine, resolved_voice = preset.engine, voice_id
            if (preset.voice_id, preset.engine) != (resolved_voice, engine):
                save_voice_preset(
                    workspace.root_dir,
                    preset.model_copy(
                        update={"voice_id": resolved_voice, "engine": engine}
                    ),
                )
            _announce("bootstrap", f"giọng: {engine}:{resolved_voice}")
        database.set_active_voice_preset_id(workspace.project_id, voice_preset_id)
        database.set_active_export_preset_id(workspace.project_id, export_preset_id)
        database.set_active_watermark_profile_id(workspace.project_id, "watermark-none")
        sync_project_snapshot(workspace)

        result = ReupJobResult(
            project_id=workspace.project_id,
            project_root=project_root,
            asset=asset,
            source_video=asset.video_path,
        )
        if _done("bootstrap", result):
            return result

        # ── 3. probe + extract audio ─────────────────────────────────────────────
        _announce("probe", asset.video_path.name)
        metadata = probe_media(
            asset.video_path, ffprobe_path=settings.dependency_paths.ffprobe_path
        )
        attach_source_video_to_project(workspace, metadata)
        if _done("probe", result):
            return result

        _announce("extract_audio", "16 kHz for ASR, 48 kHz for mixdown")
        extracted_audio = extract_audio_artifacts(
            _job_context("extract_audio"),
            workspace=workspace,
            metadata=metadata,
            ffmpeg_path=settings.dependency_paths.ffmpeg_path,
        )
        if _done("extract_audio", result):
            return result

        # ── 4. ASR ───────────────────────────────────────────────────────────────
        _announce("asr", f"faster-whisper {settings.default_asr_model}")
        asr_options = TranscriptionOptions(
            model_name=settings.default_asr_model,
            language=source_language,
            vad_filter=True,
            word_timestamps=True,
        )
        # Transcription is the most expensive CPU stage (minutes of Whisper for
        # minutes of audio) and unlike the other stages it has no built-in cache
        # check — upstream always recomputed it. Resuming a project to run a
        # later stage should not pay for it twice.
        asr_stage_hash = build_asr_stage_hash(extracted_audio.audio_16k_path, asr_options)
        asr_cached = (workspace.cache_dir / "asr" / asr_stage_hash / "segments.json").is_file()
        if asr_cached and database.count_segments(workspace.project_id) > 0:
            _announce("asr", "dùng cache")
        else:
            asr_result = FasterWhisperEngine(settings).transcribe(
                _job_context("asr"),
                audio_path=str(extracted_audio.audio_16k_path),
                options=asr_options,
                duration_ms=metadata.duration_ms,
            )
            persist_transcription_result(workspace, result=asr_result, options=asr_options)
        segments = database.list_segments(workspace.project_id)
        result.segment_count = len(segments)
        _announce("asr", f"{len(segments)} segments")
        if not segments:
            raise ReupError("ASR produced no segments — the source may have no speech")
        if _done("asr", result):
            return result

        # ── 5. contextual translation zh→vi ──────────────────────────────────────
        # Only the OpenAI backend needs a key in settings; claude-cli rides the
        # operator's subscription and groq carries its own.
        if translation_backend == "openai" and not settings.openai_api_key:
            raise ReupError(
                "No OpenAI API key — contextual translation cannot run. Either set one, "
                "or use translation_backend='claude-cli' (no API cost) / 'groq'."
            )

        profile_state = load_project_profile_state(project_root)
        prompt_template_id = (
            profile_state.recommended_prompt_template_id if profile_state is not None else None
        ) or "contextual_cartoon_fun_adaptation"
        selected_template = load_prompt_template(project_root, prompt_template_id)
        detected_source = segments[0]["source_lang"] or source_language
        engine = build_translation_engine(
            translation_backend,
            settings,
            model=translation_model,
            groq_api_key=groq_api_key,
        )
        # The stage hash keys the translation cache, so it has to name the model
        # actually used — otherwise a backend switch silently reuses old output.
        model = translation_model or (
            settings.default_translation_model
            if translation_backend == "openai"
            else f"{translation_backend}:default"
        )

        _announce("translate", f"{detected_source}→{target_language} via {translation_backend} ({model})")
        stage_hash = build_contextual_translation_stage_hash(
            segments=segments,
            template=selected_template,
            project_root=project_root,
            model=model,
            source_language=detected_source,
            target_language=target_language,
        )
        # A finished translation is cached under the same stage hash. Resuming
        # to run TTS should not re-translate 362 lines — that is a second
        # sixteen-minute run and a second bill for identical output.
        cached_translation = load_cached_contextual_translation(workspace, stage_hash)
        if cached_translation is not None:
            restore_cached_contextual_translation(
                workspace,
                database=database,
                payload=cached_translation,
                target_language=target_language,
            )
            _announce("translate", "dùng cache")
        else:
            # Checkpointing matters more here than upstream assumed. A 362-line
            # video is dozens of scenes and tens of minutes; without this, one
            # network blip or a bad batch throws away the whole run and the next
            # attempt restarts at scene 0.
            checkpoint_state = load_contextual_translation_checkpoint(
                workspace, stage_hash=stage_hash
            )
            if checkpoint_state is not None:
                _announce(
                    "translate",
                    f"tiếp tục từ checkpoint: "
                    f"{len(checkpoint_state.completed_scene_ids)} cảnh đã xong",
                )

            def _write_checkpoint(
                scenes, characters, relationships, analyses,
                route_decisions, term_sheets, metrics,
                completed_scene_ids, total_scene_count,
            ) -> None:
                persist_contextual_translation_checkpoint(
                    workspace,
                    stage_hash=stage_hash,
                    selected_template=selected_template,
                    scenes=scenes,
                    character_profiles=characters,
                    relationship_profiles=relationships,
                    analyses=analyses,
                    route_decisions=route_decisions,
                    term_entity_sheets=term_sheets,
                    metrics=metrics,
                    completed_scene_ids=completed_scene_ids,
                    total_scene_count=total_scene_count,
                )
                _announce(
                    "translate", f"cảnh {len(completed_scene_ids)}/{total_scene_count}"
                )

            contextual = run_contextual_translation(
                _job_context("translate"),
                workspace=workspace,
                database=database,
                engine=engine,
                segments=segments,
                selected_template=selected_template,
                source_language=detected_source,
                target_language=target_language,
                model=model,
                checkpoint_state=checkpoint_state,
                checkpoint_writer=_write_checkpoint,
            )
            persist_contextual_translation_result(
                workspace,
                database=database,
                stage_hash=stage_hash,
                selected_template=selected_template,
                target_language=target_language,
                scenes=contextual["scenes"],
                character_profiles=contextual["character_profiles"],
                relationship_profiles=contextual["relationship_profiles"],
                analyses=contextual["segment_analyses"],
                route_decisions=contextual.get("route_decisions"),
                metrics=contextual.get("metrics"),
                term_entity_sheets=contextual.get("term_entity_sheets"),
            )
            # Results are in the database now; a stale partial would otherwise
            # make the next run resume from a half-finished state.
            clear_contextual_translation_checkpoint(workspace, stage_hash=stage_hash)

        result.review_pending = database.count_pending_segment_reviews(workspace.project_id)
        _announce("translate", f"{result.review_pending} segments flagged for review")

        # The Douyin title is Chinese too, and a channel cannot publish
        # without one. Reuses the engine that just did the body, so a
        # zero-cost translation stays zero-cost.
        title = translate_title(
            engine=engine,
            model=model,
            source_title=asset.title,
            sample_lines=[str(row["subtitle_text"] or row["source_text"])
                          for row in database.list_segments(workspace.project_id)[:8]],
        )
        result.title_vi, result.tags_vi = title.title_vi, title.tags_vi

        # A run that died mid-translation leaves a partial result in the cache,
        # and a later resume restores it as though it were complete. Observed:
        # 165 of 719 lines never translated, the pipeline carried on, and the
        # job finally died four stages later inside the TTS engine with
        # "VieNeu synth that bai" — a message that says nothing about the real
        # cause. `subtitle_text`/`tts_text` are seeded with the source at ASR
        # time, so they are never empty; `translated_text` is the honest signal.
        untranslated = [
            int(row["segment_index"])
            for row in database.list_segments(workspace.project_id)
            if not str(row["translated_text"] or "").strip()
        ]
        if untranslated:
            raise ReupError(
                f"Bước dịch bỏ sót {len(untranslated)}/{result.segment_count} câu "
                f"(từ câu {untranslated[0]} tới {untranslated[-1]}). "
                f"Xoá cache dịch của project rồi chạy lại — chạy tiếp sẽ khôi phục "
                f"đúng bản dở này."
            )
        _announce("translate", f"tiêu đề: {title.title_vi or '(giữ nguyên bản gốc)'}")
        if _done("translate", result):
            return result

        # ── 6. subtitles ─────────────────────────────────────────────────────────
        active_track = database.get_active_subtitle_track(workspace.project_id)
        if active_track is None:
            raise ReupError("No active subtitle track after translation")
        track_id = str(active_track["track_id"])
        subtitle_rows = database.list_subtitle_events(workspace.project_id, track_id=track_id)

        _announce("subtitles", f"SRT + ASS from {len(subtitle_rows)} rows")
        for fmt in ("srt", "ass"):
            result.subtitle_paths.append(
                export_subtitles(
                    workspace,
                    segments=subtitle_rows,
                    format_name=fmt,
                    allow_source_fallback=False,
                )
            )
        if _done("subtitles", result):
            return result

        # ── 7. TTS ───────────────────────────────────────────────────────────────
        # Review gate. The operator does not read Chinese, so a line the
        # translator itself flagged as unproven must not reach a published
        # video by default — and re-dubbing after the fact means redoing TTS,
        # the voice track and both ffmpeg passes.
        pending = database.count_pending_segment_reviews(workspace.project_id)
        if pending and not allow_pending_review:
            raise ReupError(
                f"{pending} câu đang chờ duyệt — duyệt trong tab Reup (hoặc chạy với "
                f"allow_pending_review=True) trước khi lồng tiếng."
            )
        if pending:
            _announce("tts", f"CẢNH BÁO: bỏ qua cổng duyệt, {pending} câu chưa kiểm")

        voice_preset = next(
            preset
            for preset in list_voice_presets(workspace.root_dir)
            if preset.voice_preset_id == voice_preset_id
        )
        _announce("tts", f"{voice_preset.engine}:{voice_preset.voice_id} × {len(subtitle_rows)} lines")
        tts_result = synthesize_segments(
            _job_context("tts"),
            workspace=workspace,
            segments=subtitle_rows,
            preset=voice_preset,
            engine=create_tts_engine(voice_preset, project_root=workspace.root_dir),
            allow_source_fallback=False,
        )
        database.apply_subtitle_event_audio_paths(
            workspace.project_id,
            track_id,
            [
                {
                    "segment_id": item.segment_id,
                    "audio_path": str(item.raw_wav_path),
                    "status": "tts_ready",
                }
                for item in tts_result.artifacts
            ],
        )
        if _done("tts", result):
            return result

        # ── 8. voice track + mixdown ─────────────────────────────────────────────
        total_duration_ms = metadata.duration_ms or max(int(r["end_ms"]) for r in subtitle_rows)
        render_video = asset.video_path
        retimed = None

        if max_audio_speed:
            # Rate-aligned path: hold the voice at a steady speed and let the
            # video stretch. Without it, Vietnamese running ~1.5x longer than
            # the Chinese source forces a different atempo on almost every
            # line, which is what makes the delivery lurch.
            plan = build_align_plan(
                [
                    (a.segment_index, a.start_ms, a.end_ms, a.duration_ms)
                    for a in tts_result.artifacts
                ],
                video_duration_ms=total_duration_ms,
                max_audio_speed=max_audio_speed,
            )
            info = plan.summary()
            _announce(
                "voice_track",
                f"căn tốc độ ≤{max_audio_speed}x — giãn video {info['video_stretched']} câu, "
                f"{info['source_seconds']}s → {info['output_seconds']}s",
            )
            retimed = retime_to_plan(
                _job_context("voice_track"),
                plan=plan,
                source_video=asset.video_path,
                clips_by_index={
                    a.segment_index: a.raw_wav_path for a in tts_result.artifacts
                },
                work_dir=workspace.cache_dir / "retime",
                ffmpeg_path=settings.dependency_paths.ffmpeg_path,
                # Stretch the Chinese bed by the same factor as the picture
                # so ambience keeps tracking the image under the dub.
                original_audio=extracted_audio.audio_48k_path,
            )
            render_video = retimed.video_path
            total_duration_ms = retimed.duration_ms
            result.voice_track = retimed.voice_track_path

            # Subtitles were timed against the original video; stretching moves
            # every line after the first stretch, so they must be re-exported.
            shifted_rows = shift_subtitle_rows(
                [dict(row) for row in subtitle_rows], retimed
            )
            result.subtitle_paths = [
                export_subtitles(
                    workspace,
                    segments=shifted_rows,
                    format_name=fmt,
                    allow_source_fallback=False,
                )
                for fmt in ("srt", "ass")
            ]
        else:
            _announce("voice_track", f"{len(tts_result.artifacts)} clips onto the timeline")
            voice_track = build_voice_track(
                _job_context("voice_track"),
                workspace=workspace,
                artifacts=tts_result.artifacts,
                ffmpeg_path=settings.dependency_paths.ffmpeg_path,
                total_duration_ms=total_duration_ms,
            )
            result.voice_track = voice_track.voice_track_path

        if _done("voice_track", result):
            return result

        # Passing None lets the project profile supply its tuned values (the zh→vi
        # narration profiles drop the original track to ~0.07 under the voice).
        original_volume, voice_volume, _ = resolve_project_profile_mix_defaults(
            workspace.root_dir, original_volume=None, voice_volume=None
        )
        # On the rate-aligned path the bed was stretched alongside the picture,
        # so it can be mixed in exactly like the untouched original would be.
        bed_path = (
            retimed.original_bed_path
            if retimed is not None and retimed.original_bed_path is not None
            else extracted_audio.audio_48k_path
        )
        _announce("mixdown", f"original={original_volume} voice={voice_volume}")
        mixed = mix_audio_tracks(
            _job_context("mixdown"),
            workspace=workspace,
            voice_track_path=result.voice_track,
            original_audio_path=bed_path,
            ffmpeg_path=settings.dependency_paths.ffmpeg_path,
            original_volume=original_volume,
            voice_volume=voice_volume,
        )
        result.mixed_audio = mixed.mixed_audio_path
        if _done("mixdown", result):
            return result

        # ── 9. export ────────────────────────────────────────────────────────────
        _announce("export", export_preset_id)
        ass_subtitle = next(
            (p for p in result.subtitle_paths if p.suffix.lower() == ".ass"),
            result.subtitle_paths[0] if result.subtitle_paths else None,
        )
        if ass_subtitle is None:
            raise ReupError("No subtitle file to burn in")
        result.exported_video = export_hardsub_video(
            _job_context("export"),
            workspace=workspace,
            source_video_path=render_video,
            subtitle_path=ass_subtitle,
            ffmpeg_path=settings.dependency_paths.ffmpeg_path,
            duration_ms=metadata.duration_ms,
            replacement_audio_path=result.mixed_audio,
            export_preset_id=export_preset_id,
        )
        # Land it in the channel's product folder, where every other producer
        # in OmniCast delivers — the reup workspace is a scratch area.
        product_dir = publish_reup_product(
            channel=channel_id,
            aweme_id=asset.aweme_id,
            exported_video=result.exported_video,
            title=result.title_vi or workspace.name,
            source_url=url,
            subtitle_paths=list(result.subtitle_paths),
            script_lines=[
                str(row["subtitle_text"] or "")
                for row in database.list_segments(workspace.project_id)
            ],
            cover_path=asset.cover_path,
            tags=list(result.tags_vi or []),
            segment_count=result.segment_count,
            review_pending=result.review_pending,
            voice_preset_id=voice_preset_id,
            voice_id=voice_id,
            job_id=job_id,
        )
        # Point the job row at the delivered product, not the scratch copy in
        # the workspace — that is the path the UI links and the operator opens.
        result.exported_video = product_dir / "video.mp4"
        _announce("export", f"đã lưu vào {product_dir}")
        _done("export", result)
        # Mirror the outcome into the content library (series/episode row) —
        # here rather than only in the API layer, so CLI runs are covered too.
        if job_id:
            try:
                from omnicast.library.store import sync_episode_from_job

                sync_episode_from_job(job_id)
            except Exception:
                pass  # bookkeeping must never fail a finished dub
        _announce("done", str(result.exported_video or project_root))
        return result
    except Exception as exc:
        vault_link.update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise

