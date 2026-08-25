from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from omnicast.reup.core.hashing import build_stage_hash, fingerprint_path
from omnicast.reup.core.jobs import JobCancelledError, JobContext
from omnicast.reup.media.verify import is_usable_output
from omnicast.reup.media.overlay import (
    OverlayConfig,
    load_config,
    build_cover_filters,
    build_logo_filters,
    build_roaming_filters,
)
from omnicast.reup.exporting.models import ExportPreset
from omnicast.reup.exporting.presets import get_export_preset
from omnicast.reup.project.models import ProjectWorkspace

DEFAULT_EXPORT_PRESET = ExportPreset(
    export_preset_id="youtube-16x9",
    name="YouTube 16:9",
    container="mp4",
    video_codec="h264",
    audio_codec="aac",
    resolution_mode="keep",
    target_aspect="16:9",
    target_width=1920,
    target_height=1080,
    crf=18,
    burn_subtitles=True,
)

VIDEO_CODEC_MAP = {
    "h264": "libx264",
    "h265": "libx265",
    "h264_nvenc": "h264_nvenc",
    "copy": "copy",
}

# NVENC rejects -crf and libx264's preset names. cq 25 was measured against
# libx264 -crf 18 on a 9-minute 1080p export: 75s vs 189s, and slightly smaller
# (175.9 MB vs 182.3 MB), so it is the default when the GPU path is asked for.
NVENC_CQ = "25"
NVENC_PRESET = "p5"


def gpu_encoder_available(ffmpeg_executable: str | None = None) -> bool:
    """Whether this ffmpeg build exposes NVENC h.264."""
    ffmpeg = ffmpeg_executable or shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        listing = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "h264_nvenc" in (listing.stdout or "")

AUDIO_CODEC_MAP = {"aac": "aac", "copy": "copy"}
SUBTITLE_CODEC_BY_CONTAINER = {
    "mp4": "mov_text",
    "m4v": "mov_text",
    "mov": "mov_text",
    "mkv": "srt",
    "webm": "webvtt",
}


@dataclass(slots=True)
class VisualBaseResult:
    stage_hash: str
    cache_dir: Path
    visual_base_path: Path
    manifest_path: Path


@dataclass(slots=True)
class FinalMuxResult:
    stage_hash: str
    cache_dir: Path
    output_path: Path
    manifest_path: Path


def load_export_preset(project_root: Path, preset_id: str | None = None) -> ExportPreset:
    return get_export_preset(project_root, preset_id) or DEFAULT_EXPORT_PRESET


def build_hardsub_stage_hash(
    *,
    source_video_path: Path,
    subtitle_path: Path,
    export_preset: ExportPreset,
    replacement_audio_path: Path | None = None,
    watermark_override_path: Path | None = None,
    overlays: "OverlayConfig | None" = None,
) -> str:
    payload = {
        "stage": "hardsub",
        "source_video": fingerprint_path(source_video_path),
        "subtitle_file": fingerprint_path(subtitle_path),
        "replacement_audio": fingerprint_path(replacement_audio_path)
        if replacement_audio_path and replacement_audio_path.exists()
        else None,
        "watermark_override": fingerprint_path(watermark_override_path)
        if watermark_override_path and watermark_override_path.exists()
        else None,
        "preset": export_preset.model_dump(mode="json"),
        "version": 1,
    }
    # Cover regions, logo and roaming mark change the picture, so they have to
    # change the key: without this, moving a cover box and re-exporting hands
    # back the cached video from before the box existed, instantly and silently.
    # Added conditionally so jobs that never used overlays keep their cache.
    fingerprint = overlays.render_fingerprint() if overlays is not None else None
    if fingerprint is not None:
        payload["overlays"] = fingerprint
    return build_stage_hash(payload)


def build_visual_base_stage_hash(
    *,
    source_video_path: Path,
    subtitle_path: Path,
    export_preset: ExportPreset,
    watermark_override_path: Path | None = None,
) -> str:
    return build_stage_hash(
        {
            "stage": "visual_base",
            "source_video": fingerprint_path(source_video_path),
            "subtitle_file": fingerprint_path(subtitle_path),
            "watermark_override": fingerprint_path(watermark_override_path)
            if watermark_override_path and watermark_override_path.exists()
            else None,
            "preset": export_preset.model_dump(mode="json"),
            "version": 1,
        }
    )


def build_final_mux_stage_hash(
    *,
    visual_base_path: Path,
    final_audio_path: Path,
    export_preset: ExportPreset,
) -> str:
    return build_stage_hash(
        {
            "stage": "final_mux",
            "visual_base": fingerprint_path(visual_base_path),
            "final_audio": fingerprint_path(final_audio_path),
            "container": export_preset.container,
            "audio_codec": export_preset.audio_codec,
            "version": 1,
        }
    )


def escape_ffmpeg_filter_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return (
        value.replace(":", r"\:")
        .replace("'", r"\'")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(",", r"\,")
    )


def _resolution_filter(export_preset: ExportPreset) -> str | None:
    width = export_preset.target_width
    height = export_preset.target_height
    if not width or not height:
        return None

    mode = export_preset.resolution_mode.lower()
    if mode in {"pad", "fit"}:
        return (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    if mode == "crop":
        return (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    if mode == "stretch":
        return f"scale={width}:{height}"
    return None


def _overlay_position_expr(position: str, margin: int) -> tuple[str, str]:
    normalized = position.lower()
    if normalized == "top-left":
        return str(margin), str(margin)
    if normalized == "bottom-left":
        return str(margin), f"main_h-overlay_h-{margin}"
    if normalized == "bottom-right":
        return f"main_w-overlay_w-{margin}", f"main_h-overlay_h-{margin}"
    if normalized == "center":
        return "(main_w-overlay_w)/2", "(main_h-overlay_h)/2"
    return f"main_w-overlay_w-{margin}", str(margin)


def resolve_watermark_path(
    project_root: Path,
    export_preset: ExportPreset,
    watermark_override_path: Path | None = None,
) -> Path | None:
    if watermark_override_path is not None:
        return watermark_override_path.resolve() if watermark_override_path.exists() else None
    configured = export_preset.watermark_path
    if not configured:
        return None
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve() if candidate.exists() else None


def build_video_filter_graph(
    *,
    subtitle_path: Path,
    export_preset: ExportPreset,
    watermark_input_index: int | None = None,
    overlays: "OverlayConfig | None" = None,
    logo_input_index: int | None = None,
    roaming_input_index: int | None = None,
) -> tuple[str, str]:
    current_label = "[0:v]"
    filters: list[str] = []
    step_index = 0

    resolution_filter = _resolution_filter(export_preset)
    if resolution_filter:
        next_label = f"[v{step_index}]"
        filters.append(f"{current_label}{resolution_filter}{next_label}")
        current_label = next_label
        step_index += 1

    # Cover regions go on BEFORE the subtitle burn: the point is to hide the
    # source's own baked-in captions, and blurring after our text would smear
    # the Vietnamese line too.
    if overlays is not None and overlays.covers:
        cover_filters, current_label, step_index = build_cover_filters(
            overlays.covers, in_label=current_label, index=step_index
        )
        filters.extend(cover_filters)

    if export_preset.burn_subtitles:
        next_label = f"[v{step_index}]"
        filters.append(f"{current_label}ass='{escape_ffmpeg_filter_path(subtitle_path)}'{next_label}")
        current_label = next_label
        step_index += 1

    if export_preset.watermark_enabled and watermark_input_index is not None:
        rgba_label = f"[wmrgba{step_index}]"
        wm_label = f"[wm{step_index}]"
        base_label = f"[base{step_index}]"
        filters.append(
            f"[{watermark_input_index}:v]format=rgba,colorchannelmixer=aa={export_preset.watermark_opacity:.3f}{rgba_label}"
        )
        filters.append(
            f"{rgba_label}{current_label}scale2ref=w=main_w*{export_preset.watermark_scale:.4f}:h=ow/mdar{wm_label}{base_label}"
        )
        overlay_x, overlay_y = _overlay_position_expr(
            export_preset.watermark_position,
            export_preset.watermark_margin,
        )
        next_label = "[vout]"
        filters.append(f"{base_label}{wm_label}overlay={overlay_x}:{overlay_y}{next_label}")
        current_label = next_label

    # Branding sits on top of everything, including the subtitle.
    if overlays is not None:
        logo_filters, current_label, step_index = build_logo_filters(
            overlays.logo,
            in_label=current_label,
            logo_input_index=logo_input_index if logo_input_index is not None else -1,
            index=step_index,
        )
        filters.extend(logo_filters)
        roam_filters, current_label, step_index = build_roaming_filters(
            overlays.roaming,
            in_label=current_label,
            image_input_index=roaming_input_index,
            index=step_index,
        )
        filters.extend(roam_filters)

    if current_label != "[vout]":
        filters.append(f"{current_label}null[vout]")
    return ";".join(filters), "[vout]"


def build_hardsub_command(
    *,
    ffmpeg_executable: str,
    source_video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    export_preset: ExportPreset,
    replacement_audio_path: Path | None = None,
    watermark_path: Path | None = None,
    overlays: "OverlayConfig | None" = None,
) -> list[str]:
    effective_preset = export_preset.model_copy(
        update={"watermark_enabled": export_preset.watermark_enabled or watermark_path is not None}
    )
    video_codec = VIDEO_CODEC_MAP.get(effective_preset.video_codec.lower(), "libx264")
    audio_codec = AUDIO_CODEC_MAP.get(effective_preset.audio_codec.lower(), "aac")
    subtitle_codec = SUBTITLE_CODEC_BY_CONTAINER.get(effective_preset.container.lower(), "srt")
    command = [
        ffmpeg_executable,
        "-y",
        "-i",
        str(source_video_path),
    ]
    next_input_index = 1
    audio_map_label = "0:a?"
    if replacement_audio_path is not None:
        command.extend(
            [
                "-i",
                str(replacement_audio_path),
            ]
        )
        audio_map_label = f"{next_input_index}:a:0"
        next_input_index += 1
    subtitle_input_index: int | None = None
    if not effective_preset.burn_subtitles:
        subtitle_input_index = next_input_index
        command.extend(["-i", str(subtitle_path)])
        next_input_index += 1
    watermark_input_index: int | None = None
    if watermark_path is not None:
        watermark_input_index = next_input_index
        command.extend(["-i", str(watermark_path)])
        next_input_index += 1

    # Logo and roaming mark are extra image inputs; only registered when the
    # file actually exists, so a stale path cannot break the whole render.
    logo_input_index: int | None = None
    roaming_input_index: int | None = None
    if overlays is not None:
        if overlays.logo.is_active:
            logo_input_index = next_input_index
            command.extend(["-i", str(overlays.logo.path)])
            next_input_index += 1
        if overlays.roaming.is_active and overlays.roaming.uses_image:
            roaming_input_index = next_input_index
            command.extend(["-i", str(overlays.roaming.path)])
            next_input_index += 1

    video_filter_graph, output_label = build_video_filter_graph(
        subtitle_path=subtitle_path,
        export_preset=effective_preset,
        watermark_input_index=watermark_input_index,
        overlays=overlays,
        logo_input_index=logo_input_index,
        roaming_input_index=roaming_input_index,
    )
    command.extend(["-filter_complex", video_filter_graph, "-map", output_label])
    command.extend(["-map", audio_map_label])
    if subtitle_input_index is not None:
        command.extend(["-map", f"{subtitle_input_index}:0"])
    command.extend(["-c:v", video_codec])
    if video_codec == "h264_nvenc":
        command.extend(["-preset", NVENC_PRESET, "-rc", "vbr", "-cq", NVENC_CQ, "-b:v", "0"])
    elif video_codec != "copy":
        command.extend(["-preset", "medium", "-crf", str(effective_preset.crf)])
    command.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", audio_codec])
    if audio_codec != "copy":
        command.extend(["-b:a", "192k"])
    if subtitle_input_index is not None:
        command.extend(["-c:s", subtitle_codec])
    command.extend(["-progress", "pipe:1", "-nostats", str(output_path)])
    return command


def build_hardsub_output_path(workspace: ProjectWorkspace, export_preset: ExportPreset) -> Path:
    container = export_preset.container.lower() or "mp4"
    safe_name = re.sub(r'[<>:"/\\|?*\s]+', "_", workspace.name).strip("._") or "project"
    safe_preset = re.sub(r'[^a-zA-Z0-9_-]+', "_", export_preset.export_preset_id).strip("._") or "preset"
    mode_suffix = "hardsub" if export_preset.burn_subtitles else "softsub"
    return workspace.exports_dir / f"{safe_name}_{safe_preset}_{mode_suffix}.{container}"


def _progress_percent_from_ffmpeg_line(line: str, *, duration_ms: int | None) -> int | None:
    if not duration_ms or not line.startswith("out_time_ms="):
        return None
    raw_value = line.split("=", 1)[1].strip()
    if not raw_value or raw_value.upper() == "N/A":
        return None
    try:
        processed_us = int(raw_value)
    except ValueError:
        return None
    return min(99, max(20, int(processed_us / (duration_ms * 10))))


def export_visual_base_video(
    context: JobContext,
    *,
    workspace: ProjectWorkspace,
    source_video_path: Path,
    subtitle_path: Path,
    ffmpeg_path: str | None,
    duration_ms: int | None = None,
    export_preset: ExportPreset | None = None,
    export_preset_id: str | None = None,
    watermark_override_path: Path | None = None,
) -> VisualBaseResult:
    ffmpeg_executable = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg_executable:
        raise RuntimeError("Khong tim thay ffmpeg.exe")
    export_preset = export_preset or load_export_preset(workspace.root_dir, export_preset_id)
    watermark_path = resolve_watermark_path(
        workspace.root_dir,
        export_preset,
        watermark_override_path=watermark_override_path,
    )
    effective_preset = export_preset.model_copy(
        update={"watermark_enabled": export_preset.watermark_enabled or watermark_path is not None}
    )
    stage_hash = build_visual_base_stage_hash(
        source_video_path=source_video_path,
        subtitle_path=subtitle_path,
        export_preset=effective_preset,
        watermark_override_path=watermark_path,
    )
    cache_dir = workspace.cache_dir / "export" / "visual_base" / stage_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    visual_base_path = cache_dir / f"visual_base.{effective_preset.container.lower() or 'mp4'}"
    manifest_path = cache_dir / "visual_base_manifest.json"
    if manifest_path.exists() and visual_base_path.exists():
        context.report_progress(100, "Dung cache visual base")
        return VisualBaseResult(stage_hash=stage_hash, cache_dir=cache_dir, visual_base_path=visual_base_path, manifest_path=manifest_path)

    video_codec = VIDEO_CODEC_MAP.get(effective_preset.video_codec.lower(), "libx264")
    command = [ffmpeg_executable, "-y", "-i", str(source_video_path)]
    watermark_input_index: int | None = None
    if watermark_path is not None:
        watermark_input_index = 1
        command.extend(["-i", str(watermark_path)])
    video_filter_graph, output_label = build_video_filter_graph(
        subtitle_path=subtitle_path,
        export_preset=effective_preset,
        watermark_input_index=watermark_input_index,
    )
    command.extend(["-filter_complex", video_filter_graph, "-map", output_label, "-an", "-c:v", video_codec])
    if video_codec != "copy":
        command.extend(["-preset", "medium", "-crf", str(effective_preset.crf)])
    command.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(visual_base_path)])
    context.report_progress(20, "Dang render visual base")
    last_lines: list[str] = []
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                context.cancellation_token.raise_if_canceled()
                line = raw_line.strip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-20:]
                progress = _progress_percent_from_ffmpeg_line(line, duration_ms=duration_ms)
                if progress is not None:
                    context.report_progress(progress, "Dang render visual base")
        return_code = process.wait()
    except JobCancelledError:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    if return_code != 0:
        raise RuntimeError("FFmpeg export visual base that bai:\n" + "\n".join(last_lines[-10:]))
    manifest_path.write_text(
        json.dumps(
            {
                "stage_hash": stage_hash,
                "source_video_path": str(source_video_path),
                "subtitle_path": str(subtitle_path),
                "watermark_path": str(watermark_path) if watermark_path else None,
                "visual_base_path": str(visual_base_path),
                "export_preset": effective_preset.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return VisualBaseResult(stage_hash=stage_hash, cache_dir=cache_dir, visual_base_path=visual_base_path, manifest_path=manifest_path)


def mux_final_video(
    context: JobContext,
    *,
    workspace: ProjectWorkspace,
    visual_base_path: Path,
    final_audio_path: Path,
    ffmpeg_path: str | None,
    export_preset: ExportPreset | None = None,
    export_preset_id: str | None = None,
) -> FinalMuxResult:
    ffmpeg_executable = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg_executable:
        raise RuntimeError("Khong tim thay ffmpeg.exe")
    export_preset = export_preset or load_export_preset(workspace.root_dir, export_preset_id)
    output_path = build_hardsub_output_path(workspace, export_preset)
    stage_hash = build_final_mux_stage_hash(
        visual_base_path=visual_base_path,
        final_audio_path=final_audio_path,
        export_preset=export_preset,
    )
    cache_dir = workspace.cache_dir / "export" / "final_mux" / stage_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "final_mux_manifest.json"
    if manifest_path.exists() and output_path.exists():
        context.report_progress(100, "Dung cache final mux")
        return FinalMuxResult(stage_hash=stage_hash, cache_dir=cache_dir, output_path=output_path, manifest_path=manifest_path)

    audio_codec = AUDIO_CODEC_MAP.get(export_preset.audio_codec.lower(), "aac")
    command = [
        ffmpeg_executable,
        "-y",
        "-i",
        str(visual_base_path),
        "-i",
        str(final_audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        audio_codec,
    ]
    if audio_codec != "copy":
        command.extend(["-b:a", "192k"])
    command.extend(["-movflags", "+faststart", str(output_path)])
    context.report_progress(20, "Dang mux final video")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Final mux that bai").strip())
    manifest_path.write_text(
        json.dumps(
            {
                "stage_hash": stage_hash,
                "visual_base_path": str(visual_base_path),
                "final_audio_path": str(final_audio_path),
                "output_path": str(output_path),
                "export_preset": export_preset.model_dump(mode="json"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return FinalMuxResult(stage_hash=stage_hash, cache_dir=cache_dir, output_path=output_path, manifest_path=manifest_path)


def export_hardsub_video(
    context: JobContext,
    *,
    workspace: ProjectWorkspace,
    source_video_path: Path,
    subtitle_path: Path,
    ffmpeg_path: str | None,
    duration_ms: int | None = None,
    replacement_audio_path: Path | None = None,
    export_preset: ExportPreset | None = None,
    export_preset_id: str | None = None,
    watermark_override_path: Path | None = None,
    overlays: "OverlayConfig | None" = None,
) -> Path:
    ffmpeg_executable = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg_executable:
        raise RuntimeError("Khong tim thay ffmpeg.exe")
    if not source_video_path.exists():
        raise FileNotFoundError(f"Khong tim thay source video: {source_video_path}")
    if not subtitle_path.exists():
        raise FileNotFoundError(f"Khong tim thay subtitle file: {subtitle_path}")

    export_preset = export_preset or load_export_preset(workspace.root_dir, export_preset_id)
    watermark_path = resolve_watermark_path(
        workspace.root_dir,
        export_preset,
        watermark_override_path=watermark_override_path,
    )
    effective_preset = export_preset.model_copy(
        update={"watermark_enabled": export_preset.watermark_enabled or watermark_path is not None}
    )
    if effective_preset.watermark_enabled and watermark_path is None and watermark_override_path is not None:
        raise FileNotFoundError(f"Khong tim thay watermark file: {watermark_override_path}")
    output_path = build_hardsub_output_path(workspace, effective_preset)
    # Read from the project when the caller did not pass any, so the editor's
    # saved regions apply to every export without extra plumbing. Resolved
    # before the hash so the same config keys the cache and draws the frame.
    effective_overlays = overlays if overlays is not None else load_config(workspace.root_dir)
    stage_hash = build_hardsub_stage_hash(
        source_video_path=source_video_path,
        subtitle_path=subtitle_path,
        export_preset=effective_preset,
        replacement_audio_path=replacement_audio_path,
        watermark_override_path=watermark_path,
        overlays=effective_overlays,
    )
    manifest_dir = workspace.cache_dir / "export" / stage_hash
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    if manifest_path.exists() and output_path.exists():
        # `exists()` is not the question. A killed `+faststart` pass leaves a
        # full-size file that parses as garbage, and that is exactly what got
        # delivered once. Probe before trusting the cache.
        usable, why = is_usable_output(
            output_path, need_video=True, expected_duration_ms=duration_ms
        )
        if usable:
            context.report_progress(100, "Dung cache hard-sub")
            return output_path
        context.report_progress(5, f"Bo cache hong ({why}), render lai")
        output_path.unlink(missing_ok=True)

    # Render beside the target, then swap it in. Writing straight to the final
    # name means any interruption — a backend restart, a second export racing
    # this one — leaves a corrupt file under the name everything else trusts.
    # `-movflags +faststart` makes that worse: its second pass rewrites the
    # whole file in place, so a kill mid-pass yields a full-size mp4 whose NAL
    # units are garbage rather than an obviously truncated one.
    # The extension has to stay last: ffmpeg picks its muxer from it, and a
    # trailing ".partial" gets "Unable to choose an output format".
    partial_path = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
    partial_path.unlink(missing_ok=True)
    command = build_hardsub_command(
        ffmpeg_executable=ffmpeg_executable,
        source_video_path=source_video_path,
        subtitle_path=subtitle_path,
        output_path=partial_path,
        export_preset=effective_preset,
        replacement_audio_path=replacement_audio_path,
        watermark_path=watermark_path,
        overlays=effective_overlays,
    )
    export_action_label = "burn-in ASS vao video" if effective_preset.burn_subtitles else "mux subtitle vao video"
    progress_label = "Dang render video hard-sub" if effective_preset.burn_subtitles else "Dang mux video soft-sub"
    context.report_progress(20, f"Dang {export_action_label}")
    last_lines: list[str] = []
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                context.cancellation_token.raise_if_canceled()
                line = raw_line.strip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-20:]
                progress = _progress_percent_from_ffmpeg_line(line, duration_ms=duration_ms)
                if progress is not None:
                    context.report_progress(progress, progress_label)
                elif line == "progress=end":
                    context.report_progress(99, "Dang hoan tat file video")
        return_code = process.wait()
    except JobCancelledError:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        partial_path.unlink(missing_ok=True)
        raise

    if return_code != 0:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg export video that bai:\n" + "\n".join(last_lines[-10:]))

    # Only now does the finished render take the canonical name. os.replace is
    # atomic, so readers see either the previous good file or the new one.
    # ffmpeg exiting 0 is not proof the file is playable — verify before this
    # becomes the deliverable and before a manifest blesses it as a cache hit.
    usable, why = is_usable_output(
        partial_path,
        need_video=True,
        need_audio=replacement_audio_path is not None,
        expected_duration_ms=duration_ms,
    )
    if not usable:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError(f"Export xong nhung file khong dung duoc: {why}")

    os.replace(partial_path, output_path)

    manifest = {
        "stage_hash": stage_hash,
        "source_video_path": str(source_video_path),
        "subtitle_path": str(subtitle_path),
        "replacement_audio_path": str(replacement_audio_path) if replacement_audio_path else None,
        "watermark_path": str(watermark_path) if watermark_path else None,
        "output_path": str(output_path),
        "export_preset": effective_preset.model_dump(mode="json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    context.report_progress(100, "Da xuat video")
    return output_path
