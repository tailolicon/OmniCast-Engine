from __future__ import annotations

import json
import os
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from sqlite3 import Row

from omnicast.reup.core.jobs import JobContext
from omnicast.reup.project.models import ProjectWorkspace

from omnicast.reup.audio.trim_silence import trim_silence

from .base import TTSEngine, build_tts_clip_hash, build_tts_stage_hash
from .models import SynthesizedSegmentArtifact, SynthesizedSegmentsResult, VoicePreset


def _segment_tts_text(row: Row, *, allow_source_fallback: bool = True) -> str:
    if allow_source_fallback:
        return (row["tts_text"] or row["subtitle_text"] or row["translated_text"] or row["source_text"] or "").strip()
    return (row["tts_text"] or row["subtitle_text"] or row["translated_text"] or "").strip()


def _load_cached_artifact_metadata(manifest_path: Path) -> dict[str, dict[str, object]]:
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata_by_segment_id: dict[str, dict[str, object]] = {}
    for item in payload.get("artifacts", []):
        segment_id = str(item.get("segment_id") or "").strip()
        if segment_id:
            metadata_by_segment_id[segment_id] = item
    return metadata_by_segment_id


def _load_json_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _probe_wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frame_rate = handle.getframerate()
        frame_count = handle.getnframes()
    if frame_rate <= 0:
        return 0
    return max(0, int(round(frame_count * 1000 / frame_rate)))


def synthesize_segments(
    context: JobContext,
    *,
    workspace: ProjectWorkspace,
    segments: list[Row],
    preset: VoicePreset,
    engine: TTSEngine,
    allow_source_fallback: bool = True,
    segment_voice_presets: dict[str, VoicePreset] | None = None,
    segment_speaker_keys: dict[str, str] | None = None,
) -> SynthesizedSegmentsResult:
    voice_preset_assignments = {
        str(segment_id): item.voice_preset_id
        for segment_id, item in (segment_voice_presets or {}).items()
        if item.voice_preset_id
    }
    stage_hash = build_tts_stage_hash(
        segments,
        preset,
        allow_source_fallback=allow_source_fallback,
        segment_voice_preset_ids=voice_preset_assignments,
        segment_voice_presets=segment_voice_presets,
    )
    cache_dir = workspace.cache_dir / "tts" / stage_hash
    raw_dir = cache_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    clip_cache_root = workspace.cache_dir / "tts" / "clips"
    manifest_path = cache_dir / "manifest.json"
    cached_metadata_by_segment_id = _load_cached_artifact_metadata(manifest_path)

    artifacts: list[SynthesizedSegmentArtifact | None] = []
    pending: list[_PendingClip] = []
    engine_cache: dict[str, TTSEngine] = {preset.voice_preset_id: engine}
    total = max(1, len(segments))
    for index, row in enumerate(segments, start=1):
        text = _segment_tts_text(row, allow_source_fallback=allow_source_fallback)
        if not text:
            continue
        segment_id = str(row["segment_id"])
        active_preset = (segment_voice_presets or {}).get(segment_id, preset)
        active_engine = engine_cache.get(active_preset.voice_preset_id)
        if active_engine is None:
            from .factory import create_tts_engine

            active_engine = create_tts_engine(active_preset, project_root=workspace.root_dir)
            engine_cache[active_preset.voice_preset_id] = active_engine
        legacy_output_path = raw_dir / f"{row['segment_index']:04d}_{row['segment_id']}.wav"
        cached_metadata = cached_metadata_by_segment_id.get(segment_id, {})
        cached_output_raw = str(cached_metadata.get("raw_wav_path") or "").strip()
        cached_output_path = Path(cached_output_raw) if cached_output_raw else None
        clip_hash = build_tts_clip_hash(text=text, preset=active_preset)
        clip_cache_dir = clip_cache_root / clip_hash
        shared_output_path = clip_cache_dir / "clip.wav"
        clip_manifest_path = clip_cache_dir / "manifest.json"
        output_path = next(
            (
                candidate
                for candidate in (cached_output_path, shared_output_path, legacy_output_path)
                if candidate is not None and candidate.exists() and candidate.stat().st_size > 44
            ),
            shared_output_path,
        )
        if output_path.exists() and output_path.stat().st_size > 44:
            clip_metadata = _load_json_payload(clip_manifest_path)
            metadata_source = (
                cached_metadata
                if cached_output_path is not None and output_path == cached_output_path and cached_metadata
                else clip_metadata
            )
            cached_duration_ms = int(metadata_source.get("duration_ms") or 0)
            if cached_duration_ms <= 0:
                cached_duration_ms = _probe_wav_duration_ms(output_path)
            artifact = SynthesizedSegmentArtifact(
                segment_id=segment_id,
                segment_index=int(row["segment_index"]),
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
                text=text,
                raw_wav_path=output_path,
                duration_ms=cached_duration_ms,
                sample_rate=int(metadata_source.get("sample_rate") or active_preset.sample_rate),
                voice_id=str(metadata_source.get("voice_id") or active_preset.voice_id),
                voice_preset_id=active_preset.voice_preset_id,
                speaker_key=(segment_speaker_keys or {}).get(segment_id),
                voice_speed=active_preset.speed,
                voice_volume=active_preset.volume,
                voice_pitch=active_preset.pitch,
            )
        else:
            # Deferred: synthesis is the slow part and the only part worth
            # running concurrently, so it happens after this resolution pass.
            pending.append(
                _PendingClip(
                    slot=len(artifacts),
                    row=row,
                    text=text,
                    engine=active_engine,
                    preset=active_preset,
                    output_path=output_path,
                    clip_cache_dir=clip_cache_dir,
                    clip_manifest_path=clip_manifest_path,
                    clip_hash=clip_hash,
                    speaker_key=(segment_speaker_keys or {}).get(segment_id),
                )
            )
            artifacts.append(None)
            continue
        artifacts.append(artifact)

    _synthesize_pending(context, pending, artifacts, total=total)
    artifacts = [a for a in artifacts if a is not None]

    payload = {
        "stage_hash": stage_hash,
        "voice_preset": preset.model_dump(mode="json"),
        "artifacts": [
            {
                "segment_id": item.segment_id,
                "segment_index": item.segment_index,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "text": item.text,
                "raw_wav_path": str(item.raw_wav_path),
                "duration_ms": item.duration_ms,
                "sample_rate": item.sample_rate,
                "voice_id": item.voice_id,
                "voice_preset_id": item.voice_preset_id,
                "speaker_key": item.speaker_key,
                "voice_speed": item.voice_speed,
                "voice_volume": item.voice_volume,
                "voice_pitch": item.voice_pitch,
            }
            for item in artifacts
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    context.report_progress(100, "Da tao TTS clips")
    return SynthesizedSegmentsResult(
        stage_hash=stage_hash,
        cache_dir=cache_dir,
        manifest_path=manifest_path,
        artifacts=artifacts,
    )


@dataclass(slots=True)
class _PendingClip:
    slot: int
    row: Row
    text: str
    engine: TTSEngine
    preset: VoicePreset
    output_path: Path
    clip_cache_dir: Path
    clip_manifest_path: Path
    clip_hash: str
    speaker_key: str | None


# Local models already saturate the CPU — a thread pool over VieNeu measured
# 1.14x on six lines, which is noise. Network engines are the opposite: each
# call is mostly waiting on ByteDance, so they run several at a time. Kept
# deliberately low because Edge-TTS has rate-limited us mid-job even running
# one at a time (it died at clip 255), and a 429 storm costs more than it saves.
_NETWORK_TTS_ENGINES = {"capcut", "volcengine", "edge", "chatterbox"}
_DEFAULT_NETWORK_WORKERS = 4


def tts_workers(engine_name: str) -> int:
    override = os.environ.get("OMNICAST_REUP_TTS_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return _DEFAULT_NETWORK_WORKERS if engine_name.lower() in _NETWORK_TTS_ENGINES else 1


# An engine that chokes on one line used to take the whole job with it: 547 of
# 719 clips were already on disk when a single 508-character line killed the
# run. Long lines come from ASR segments that ran unbounded (now capped), but
# the dub must survive whatever the transcript hands it.
_LONG_LINE_CHARS = 220


def _concat_wavs(parts: list[Path], destination: Path) -> int:
    """Join same-format clips end to end. Returns duration in ms."""
    frames = bytearray()
    params = None
    for part in parts:
        with wave.open(str(part), "rb") as handle:
            if params is None:
                params = handle.getparams()
            frames += handle.readframes(handle.getnframes())
    if params is None or not frames:
        return 0
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(params.nchannels)
        handle.setsampwidth(params.sampwidth)
        handle.setframerate(params.framerate)
        handle.writeframes(bytes(frames))
    per_frame = params.sampwidth * params.nchannels
    return int(len(frames) / per_frame / params.framerate * 1000)


def _synthesize_resilient(job: "_PendingClip"):
    """Synthesize one line, splitting it rather than failing the job.

    Order: the whole line; then sentence by sentence, concatenated — the words
    survive, which silence would not. Only if every piece fails does the caller
    see the error.
    """
    from omnicast.media.tts_normalize import split_sentences

    try:
        return job.engine.synthesize(
            text=job.text, output_path=job.output_path, preset=job.preset
        )
    except Exception as whole_line_error:
        pieces = [p for p in split_sentences(job.text) if p.strip()]
        if len(pieces) < 2:
            raise
        rendered: list[Path] = []
        for index, piece in enumerate(pieces):
            part_path = job.output_path.with_name(f"{job.output_path.stem}.part{index}.wav")
            try:
                job.engine.synthesize(text=piece, output_path=part_path, preset=job.preset)
            except Exception:
                continue
            rendered.append(part_path)
        if not rendered:
            raise whole_line_error
        duration_ms = _concat_wavs(rendered, job.output_path)
        for part in rendered:
            part.unlink(missing_ok=True)
        if duration_ms <= 0:
            raise whole_line_error
        from .models import SynthesisResult

        with wave.open(str(job.output_path), "rb") as handle:
            sample_rate = handle.getframerate()
        return SynthesisResult(
            wav_path=job.output_path,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            voice_id=None if job.preset.voice_id == "default" else job.preset.voice_id,
        )


def _synthesize_pending(
    context: JobContext,
    pending: list["_PendingClip"],
    artifacts: list["SynthesizedSegmentArtifact | None"],
    *,
    total: int,
) -> None:
    if not pending:
        return
    workers = min(tts_workers(pending[0].preset.engine), len(pending))
    done = [len(artifacts) - len(pending)]

    def _one(job: "_PendingClip") -> None:
        context.cancellation_token.raise_if_canceled()
        job.clip_cache_dir.mkdir(parents=True, exist_ok=True)
        result = _synthesize_resilient(job)
        # Engines pad both ends with silence. The planner counts that padding as
        # speech, so the voice starts late against its shot and lines get sped
        # up to make room for nothing.
        trimmed_ms = trim_silence(Path(result.wav_path))
        if trimmed_ms > 0:
            result = replace(result, duration_ms=trimmed_ms)
        job.clip_manifest_path.write_text(
            json.dumps(
                {
                    "clip_hash": job.clip_hash,
                    "text": job.text,
                    "raw_wav_path": str(result.wav_path),
                    "duration_ms": result.duration_ms,
                    "sample_rate": result.sample_rate,
                    "voice_id": result.voice_id,
                    "voice_preset": job.preset.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        artifacts[job.slot] = SynthesizedSegmentArtifact(
            segment_id=str(job.row["segment_id"]),
            segment_index=int(job.row["segment_index"]),
            start_ms=int(job.row["start_ms"]),
            end_ms=int(job.row["end_ms"]),
            text=job.text,
            raw_wav_path=result.wav_path,
            duration_ms=result.duration_ms,
            sample_rate=result.sample_rate,
            voice_id=result.voice_id,
            voice_preset_id=job.preset.voice_preset_id,
            speaker_key=job.speaker_key,
            voice_speed=job.preset.speed,
            voice_volume=job.preset.volume,
            voice_pitch=job.preset.pitch,
        )
        done[0] += 1
        context.report_progress(min(85, int(done[0] * 85 / max(1, total))), f"TTS {done[0]}/{total}")

    if workers <= 1:
        for job in pending:
            _one(job)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # list() so the first failure propagates instead of leaving a hole that
        # only shows up as a missing clip much later, on the timeline.
        list(pool.map(_one, pending))


def load_synthesized_segments(workspace: ProjectWorkspace, stage_hash: str) -> SynthesizedSegmentsResult | None:
    manifest_path = workspace.cache_dir / "tts" / stage_hash / "manifest.json"
    if not manifest_path.exists():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = [
        SynthesizedSegmentArtifact(
            segment_id=item["segment_id"],
            segment_index=int(item["segment_index"]),
            start_ms=int(item["start_ms"]),
            end_ms=int(item["end_ms"]),
            text=item["text"],
            raw_wav_path=Path(item["raw_wav_path"]),
            duration_ms=int(item.get("duration_ms", 0)),
            sample_rate=int(item.get("sample_rate", 0)),
            voice_id=item.get("voice_id"),
            voice_preset_id=item.get("voice_preset_id"),
            speaker_key=item.get("speaker_key"),
            voice_speed=item.get("voice_speed"),
            voice_volume=item.get("voice_volume"),
            voice_pitch=item.get("voice_pitch"),
        )
        for item in payload.get("artifacts", [])
    ]
    return SynthesizedSegmentsResult(
        stage_hash=payload["stage_hash"],
        cache_dir=manifest_path.parent,
        manifest_path=manifest_path,
        artifacts=artifacts,
    )
