"""Execute a rate-alignment plan: retime video, voice and subtitles together.

`audio.rate_align` decides *what* each line's audio speed and video stretch
should be. This module carries it out with ffmpeg and — critically — rebuilds
the subtitle timeline to match. Stretching the video without moving the
subtitles would desynchronise every line after the first stretch.

Everything is cut and reassembled per planned segment:

* video — `-ss/-t` the source slot, `setpts` it to the target length, no audio
* voice — the synthesized clip at its capped `atempo`, padded to the target
* subtitles — new start/end derived from the cumulative target timeline

Segments are concatenated in batches; a 362-line video is 362 inputs, which is
past what a single ffmpeg command line takes comfortably.
"""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from omnicast.reup.audio.rate_align import AlignPlan, AlignedSegment, build_setpts_filter
from omnicast.reup.core.jobs import JobCancelledError, JobContext

# ffmpeg needs every cut point to be a keyframe for frame-accurate segment
# boundaries; upstream (pyvideotrans) forces this with -g 1.
_GOP = "1"
_CRF = "20"
_PRESET = "veryfast"


def _cut_workers() -> int:
    """How many segment cuts to run at once.

    Each cut is a short ffmpeg process that never fills the machine on its own.
    Half the cores keeps the box responsive and stops the encoders thrashing
    each other; `OMNICAST_REUP_CUT_WORKERS` overrides for tuning.
    """
    override = os.environ.get("OMNICAST_REUP_CUT_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return max(2, min(8, (os.cpu_count() or 4) // 2))

# How many segment files to feed one concat pass.
_CONCAT_BATCH = 60


@dataclass(slots=True)
class RetimedSegment:
    segment_index: int
    video_path: Path
    audio_path: Path
    start_ms: int
    end_ms: int


@dataclass(slots=True)
class RetimeResult:
    video_path: Path
    voice_track_path: Path
    duration_ms: int
    segments: list[RetimedSegment] = field(default_factory=list)
    original_bed_path: Path | None = None

    def timeline(self) -> list[tuple[int, int, int]]:
        """(segment_index, new_start_ms, new_end_ms) on the stretched timeline."""
        return [(s.segment_index, s.start_ms, s.end_ms) for s in self.segments]


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-4:]
        raise RuntimeError(f"ffmpeg failed: {' | '.join(tail)}")


def _probe_duration_ms(*, ffmpeg: str, path: Path) -> int:
    """Duration in ms, or 0 when ffprobe is unavailable or the file is unreadable."""
    ffprobe = str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return int(float(result.stdout.strip()) * 1000)
    except (TypeError, ValueError):
        return 0


def _atempo_chain(speed: float) -> str:
    """atempo only accepts 0.5–2.0 per instance; chain for anything beyond."""
    remaining = speed
    parts: list[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.5f}")
    return ",".join(parts)


def _cut_video_segment(
    *, ffmpeg: str, source: Path, segment: AlignedSegment, out_path: Path
) -> None:
    source_dur = segment.slot_ms / 1000.0
    target_dur = segment.target_ms / 1000.0
    _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{segment.source_start_ms / 1000.0:.6f}",
        "-t", f"{source_dur:.6f}",
        "-i", str(source),
        "-an",
        "-vf", build_setpts_filter(segment.video_pts),
        "-fps_mode", "vfr",
        "-c:v", "libx264", "-g", _GOP, "-preset", _PRESET, "-crf", _CRF,
        "-pix_fmt", "yuv420p",
        "-t", f"{target_dur:.6f}",
        str(out_path),
    ])


def _fit_audio_segment(
    *, ffmpeg: str, clip: Path | None, segment: AlignedSegment, out_path: Path
) -> None:
    target_dur = segment.target_ms / 1000.0
    if clip is None or not clip.is_file():
        # A line with no synthesized clip still owns its slot; fill it with
        # silence so the voice track stays aligned with the video.
        _run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{target_dur:.6f}",
            "-c:a", "pcm_s16le", str(out_path),
        ])
        return

    filters = ["aresample=48000"]
    if segment.audio_speed > 1.001:
        filters.append(_atempo_chain(segment.audio_speed))
    # Pad first, then trim: the clip is now at most `target`, and padding gives
    # ffmpeg something to trim to an exact length.
    filters.append(f"apad=pad_dur={target_dur:.3f}")
    filters.append(f"atrim=end={target_dur:.3f}")
    _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(clip),
        "-af", ",".join(filters),
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le",
        str(out_path),
    ])


def _stretch_original_bed(
    *, ffmpeg: str, source_audio: Path, segment: AlignedSegment, out_path: Path
) -> None:
    """Slow the source audio for one segment so it tracks the stretched picture.

    Without this the ambience keeps the original pacing while the image is
    slowed, and the two slide apart a little further at every stretch. atempo
    preserves pitch, so slowing music does not detune it.
    """
    target_dur = segment.target_ms / 1000.0
    filters = ["aresample=48000"]
    if segment.video_pts > 1.001:
        filters.append(_atempo_chain(1.0 / segment.video_pts))
    filters.append(f"apad=pad_dur={target_dur:.3f}")
    filters.append(f"atrim=end={target_dur:.3f}")
    _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{segment.source_start_ms / 1000.0:.6f}",
        "-t", f"{segment.slot_ms / 1000.0:.6f}",
        "-i", str(source_audio),
        "-af", ",".join(filters),
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le",
        str(out_path),
    ])


def _concat(*, ffmpeg: str, parts: list[Path], out_path: Path, copy: bool) -> None:
    """Concatenate with the demuxer, in batches, then concatenate the batches."""
    if not parts:
        raise RuntimeError("nothing to concatenate")
    if len(parts) == 1:
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-i", str(parts[0]), "-c", "copy", str(out_path)])
        return

    work = out_path.parent
    batches: list[Path] = []
    for index in range(0, len(parts), _CONCAT_BATCH):
        chunk = parts[index : index + _CONCAT_BATCH]
        listing = work / f"_concat_{index:05d}.txt"
        listing.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in chunk), encoding="utf-8"
        )
        batch_out = work / f"_batch_{index:05d}{out_path.suffix}"
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-f", "concat", "-safe", "0", "-i", str(listing),
              "-c", "copy", str(batch_out)])
        batches.append(batch_out)

    if len(batches) == 1:
        batches[0].replace(out_path)
        return

    final_list = work / "_concat_final.txt"
    final_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in batches), encoding="utf-8"
    )
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-f", "concat", "-safe", "0", "-i", str(final_list),
          "-c", "copy", str(out_path)])


def retime_to_plan(
    context: JobContext,
    *,
    plan: AlignPlan,
    source_video: Path,
    clips_by_index: dict[int, Path],
    work_dir: Path,
    ffmpeg_path: str | None = None,
    original_audio: Path | None = None,
) -> RetimeResult:
    """Render a stretched video plus a matching voice track.

    `clips_by_index` maps `segment_index` to the synthesized wav for that line;
    a missing entry becomes silence rather than a hole in the timeline.
    """
    ffmpeg = ffmpeg_path or "ffmpeg"
    segments_dir = work_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    retimed: list[RetimedSegment] = []
    video_parts: list[Path] = []
    audio_parts: list[Path] = []
    bed_parts: list[Path] = []
    cursor_ms = 0
    total = len(plan.segments)

    # Cutting a segment depends on nothing but the segment, and each cut is a
    # separate ffmpeg process — a 362-line video is over a thousand of them, and
    # run one at a time most of the machine sits idle between short bursts.
    # Only the cursor arithmetic below is order-dependent, so it stays serial.
    done = 0

    def _cut(job: tuple[int, AlignedSegment]) -> None:
        nonlocal done
        position, segment = job
        context.cancellation_token.raise_if_canceled()
        _cut_video_segment(
            ffmpeg=ffmpeg, source=source_video, segment=segment,
            out_path=segments_dir / f"v_{position:05d}.mp4",
        )
        _fit_audio_segment(
            ffmpeg=ffmpeg,
            clip=clips_by_index.get(segment.segment_index),
            segment=segment,
            out_path=segments_dir / f"a_{position:05d}.wav",
        )
        if original_audio is not None:
            _stretch_original_bed(
                ffmpeg=ffmpeg, source_audio=original_audio, segment=segment,
                out_path=segments_dir / f"b_{position:05d}.wav",
            )
        done += 1  # GIL-atomic enough for a progress counter
        if done % 20 == 0 or done == total:
            context.report_progress(int(90 * done / max(1, total)), f"retime {done}/{total}")

    with ThreadPoolExecutor(max_workers=_cut_workers()) as pool:
        # list() so an exception in any cut surfaces here, before the concat.
        list(pool.map(_cut, list(enumerate(plan.segments))))

    for position, segment in enumerate(plan.segments):
        video_part = segments_dir / f"v_{position:05d}.mp4"
        audio_part = segments_dir / f"a_{position:05d}.wav"
        if original_audio is not None:
            bed_parts.append(segments_dir / f"b_{position:05d}.wav")
        retimed.append(
            RetimedSegment(
                segment_index=segment.segment_index,
                video_path=video_part,
                audio_path=audio_part,
                start_ms=cursor_ms,
                end_ms=cursor_ms + segment.target_ms,
            )
        )
        cursor_ms += segment.target_ms
        video_parts.append(video_part)
        audio_parts.append(audio_part)

    context.report_progress(92, "ghép video")
    video_out = work_dir / "retimed_video.mp4"
    _concat(ffmpeg=ffmpeg, parts=video_parts, out_path=video_out, copy=True)

    context.report_progress(96, "ghép track giọng")
    voice_out = work_dir / "retimed_voice.wav"
    _concat(ffmpeg=ffmpeg, parts=audio_parts, out_path=voice_out, copy=True)

    bed_out: Path | None = None
    if bed_parts:
        context.report_progress(97, "ghép tiếng nền đã giãn")
        bed_out = work_dir / "retimed_bed.wav"
        _concat(ffmpeg=ffmpeg, parts=bed_parts, out_path=bed_out, copy=True)

    # setpts is not millisecond-exact, so each stretched segment lands slightly
    # short (~0.9% measured over 8 segments). The voice track is sample-exact,
    # so the drift accumulates as video-shorter-than-audio — several seconds
    # across a few hundred lines. Hold the final frame to close the gap, which
    # is what pyvideotrans does at its own mux step.
    actual_ms = _probe_duration_ms(ffmpeg=ffmpeg, path=video_out)
    shortfall_ms = cursor_ms - actual_ms
    if actual_ms and shortfall_ms > 40:
        context.report_progress(98, f"bù {shortfall_ms} ms khung cuối")
        padded = work_dir / "retimed_video_padded.mp4"
        _run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_out),
            "-vf", f"tpad=stop_mode=clone:stop_duration={shortfall_ms / 1000.0:.3f}",
            "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF, "-pix_fmt", "yuv420p",
            "-an", str(padded),
        ])
        padded.replace(video_out)

    result = RetimeResult(
        video_path=video_out,
        voice_track_path=voice_out,
        duration_ms=cursor_ms,
        segments=retimed,
        original_bed_path=bed_out,
    )
    save_timeline(work_dir, result)
    return result


TIMELINE_FILENAME = "timeline.json"


def save_timeline(work_dir: Path, result: RetimeResult) -> Path:
    """Record where each line landed on the stretched timeline.

    Without this on disk, anything that regenerates subtitles later — a
    re-export after changing the style, say — has only the original timings to
    work from, and burns a track that drifts further out of sync with every
    stretch that precedes it.
    """
    path = work_dir / TIMELINE_FILENAME
    path.write_text(
        json.dumps(
            {"duration_ms": result.duration_ms, "segments": result.timeline()},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def load_timeline(work_dir: Path) -> dict[int, tuple[int, int]] | None:
    """segment_index → (start_ms, end_ms), or None if this job never retimed."""
    path = work_dir / TIMELINE_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {int(i): (int(s), int(e)) for i, s, e in payload.get("segments", [])}
    except (OSError, ValueError, TypeError):
        return None


def shift_rows_to_timeline(
    rows: list[dict[str, object]], new_times: dict[int, tuple[int, int]]
) -> list[dict[str, object]]:
    """Move subtitle rows onto a recorded timeline (see `shift_subtitle_rows`)."""
    shifted: list[dict[str, object]] = []
    for row in rows:
        index = int(row.get("segment_index", -1))
        if index not in new_times:
            continue
        start_ms, end_ms = new_times[index]
        shifted.append({**row, "start_ms": start_ms, "end_ms": end_ms})
    return shifted


def shift_subtitle_rows(
    rows: list[dict[str, object]], result: RetimeResult
) -> list[dict[str, object]]:
    """Move subtitle rows onto the stretched timeline.

    Rows whose segment was not part of the plan are dropped rather than left at
    their original time, where they would drift further out of sync with every
    stretch that precedes them.
    """
    return shift_rows_to_timeline(
        rows, {s.segment_index: (s.start_ms, s.end_ms) for s in result.segments}
    )
