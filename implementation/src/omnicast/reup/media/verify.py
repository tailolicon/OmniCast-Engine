"""Is this media file actually usable?

Every cache hit and every "job done" in the pipeline used to rest on
`Path.exists()`. That is not the same question. A delivered video reached the
operator at full size, 178 MB, with `exists()` perfectly happy — and unplayable,
because ffmpeg had been killed midway through the `+faststart` pass that
rewrites the file in place. Size alone would not have caught it either.

So: ask ffprobe. A file is usable when it parses, reports a duration, and
carries the streams the stage promised. Cheap — a probe is milliseconds against
minutes of re-encoding — and it turns a silent bad deliverable into a failure
at the step that produced it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# A container can parse and still be a stub. Anything this small is not video.
_MIN_PLAUSIBLE_BYTES = 1024


@dataclass(slots=True)
class MediaProbe:
    ok: bool
    reason: str = ""
    duration_ms: int = 0
    has_video: bool = False
    has_audio: bool = False


def probe_media_file(path: Path, *, ffprobe_path: str | None = None) -> MediaProbe:
    """Parse `path` with ffprobe and report what is actually in it."""
    if not path.is_file():
        return MediaProbe(False, f"không có file: {path.name}")
    size = path.stat().st_size
    if size < _MIN_PLAUSIBLE_BYTES:
        return MediaProbe(False, f"file chỉ {size} byte")

    ffprobe = ffprobe_path or shutil.which("ffprobe")
    if not ffprobe:
        # Without a prober we cannot judge; say so rather than pass by default.
        return MediaProbe(False, "không tìm thấy ffprobe")

    result = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        return MediaProbe(False, f"ffprobe từ chối: {detail[-1][:120] if detail else 'lỗi không rõ'}")
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        return MediaProbe(False, "ffprobe trả JSON hỏng")

    streams = payload.get("streams") or []
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    raw_duration = (payload.get("format") or {}).get("duration")
    try:
        duration_ms = int(float(raw_duration) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms <= 0:
        return MediaProbe(False, "không đọc được thời lượng", 0, has_video, has_audio)
    return MediaProbe(True, "", duration_ms, has_video, has_audio)


def is_usable_output(
    path: Path,
    *,
    need_video: bool = True,
    need_audio: bool = False,
    expected_duration_ms: int | None = None,
    tolerance: float = 0.05,
    ffprobe_path: str | None = None,
) -> tuple[bool, str]:
    """Whether a finished artifact may be trusted, and why not when it may not.

    `expected_duration_ms` catches the other half of the problem: a file that
    parses fine but stops early, which is what an interrupted encode leaves
    behind once the container header happens to survive.
    """
    probe = probe_media_file(path, ffprobe_path=ffprobe_path)
    if not probe.ok:
        return False, probe.reason
    if need_video and not probe.has_video:
        return False, "không có luồng hình"
    if need_audio and not probe.has_audio:
        return False, "không có luồng tiếng"
    if expected_duration_ms and expected_duration_ms > 0:
        drift = abs(probe.duration_ms - expected_duration_ms) / expected_duration_ms
        if drift > tolerance:
            return False, (
                f"thời lượng {probe.duration_ms/1000:.1f}s lệch "
                f"{drift*100:.0f}% so với {expected_duration_ms/1000:.1f}s dự kiến"
            )
    return True, ""
