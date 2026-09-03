"""Pull a competitor's VIDEO so §5 forensics can look at frames.

WHY THIS EXISTS

`analytics.av_forensics` measures how a video was cut, and it had exactly one
production caller: our own renders. The competitor pipeline read transcripts and
said so in its own docstring — "CANNOT measure anything visual. No frames are
fetched." So the review's largest gap (§5) was closed for our videos and open
for theirs, which is the half that matters for learning.

This fetches the frames. Three properties make that acceptable:

* OPT-IN AND BOUNDED. Downloading competitor video is bandwidth, disk and time.
  It runs only when `OMNICAST_COMPETITOR_FORENSICS=1`, only for the top few
  winners, at a low resolution cap, with a hard timeout, and the file is deleted
  as soon as it has been measured.
* IT DEGRADES LIKE EVERYTHING ELSE. No yt-dlp, no network, a members-only video:
  each returns "" and the blueprint records visual fields as unmeasured, exactly
  as it does today.
* IT DOES NOT REPUBLISH ANYTHING. Frames are measured and discarded. No
  competitor footage is stored, and none reaches a render — that would be a
  rights problem, not a feature.
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
import tempfile

import structlog

logger = structlog.get_logger()

# Off by default: a learning run must not start pulling video because somebody
# upgraded. The setting is `omnicast_competitor_forensics` in `.env` /
# `config.settings`; the environment variable is the same name upper-cased,
# which is how pydantic-settings reads it. Reading os.environ ALONE was wrong:
# this project configures through Settings, so a `.env` line would have been
# ignored while looking exactly like it worked.
ENV_FLAG = "OMNICAST_COMPETITOR_FORENSICS"
# Shot rhythm, motion and colour are all measurable at low resolution, and 480p
# costs a fraction of the bandwidth.
MAX_HEIGHT = 480
# A HARD wall-clock budget for the whole download, enforced by killing the
# subprocess. Distinct from the per-read socket timeout below, which cannot
# bound total time.
DOWNLOAD_TIMEOUT_SECONDS = 180
SOCKET_TIMEOUT_SECONDS = 30
# Beyond this, a single VOD would dominate a whole learning run.
MAX_DURATION_MINUTES = 40.0


def forensics_enabled() -> bool:
    """Settings first, environment second.

    Settings is the configuration surface this project actually documents; the
    environment fallback keeps the flag usable in a script or a test that has no
    `.env` at all."""
    try:
        from omnicast.config.settings import get_settings

        return bool(get_settings().omnicast_competitor_forensics)
    except Exception:
        return str(os.environ.get(ENV_FLAG, "")).strip().lower() in {
            "1", "true", "yes", "on"}


def download_video(video_id: str, workdir: str) -> str:
    """Path to a downloaded low-res copy, or "" with the reason logged.

    Shelled out to the yt-dlp CLI so the timeout is a REAL WALL CLOCK. The
    in-process API only accepts `socket_timeout`, which bounds a single network
    read: a server dripping one byte at a time, or a very large file on a slow
    link, runs for as long as it likes while every individual read stays inside
    the limit. The docstring claimed a hard timeout; only a subprocess can give
    one, because only a subprocess can be killed."""
    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if executable:
        launcher = [executable]
    else:
        # No console script on PATH, but the package is installed in this
        # interpreter: `python -m yt_dlp` is still a SUBPROCESS, so the
        # wall-clock timeout guarantee this function is built around holds.
        # (The in-process API is what cannot be bounded — not the module.)
        try:
            import yt_dlp  # noqa: F401
        except Exception:
            logger.info("competitor forensics skipped: yt-dlp is neither on PATH "
                        "nor importable in this interpreter")
            return ""
        launcher = [sys.executable, "-m", "yt_dlp"]

    template = os.path.join(workdir, f"{video_id}.%(ext)s")
    command = [
        *launcher,
        "-f", f"bestvideo[height<={MAX_HEIGHT}]+bestaudio/best[height<={MAX_HEIGHT}]",
        "-o", template, "--no-playlist", "--no-warnings", "--quiet",
        "--no-progress", "--retries", "1",
        "--socket-timeout", str(SOCKET_TIMEOUT_SECONDS),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.info("competitor video download exceeded its wall-clock budget",
                    video=video_id, seconds=DOWNLOAD_TIMEOUT_SECONDS)
        return ""
    except OSError as exc:
        logger.info("competitor video download failed to start", video=video_id,
                    error=str(exc)[:200])
        return ""
    if completed.returncode != 0:
        logger.info("competitor video download failed", video=video_id,
                    error=(completed.stderr or "")[:200])
        return ""

    for name in sorted(os.listdir(workdir)):
        if name.startswith(video_id):
            return os.path.join(workdir, name)
    return ""


def measure_competitor_video(video_id: str, *, transcript=None,
                             duration_minutes: float = 0.0) -> dict | None:
    """Forensics for one competitor video, or None with the reason in the log.

    The file is deleted before this returns. Nothing is kept."""
    if not forensics_enabled():
        return None
    if duration_minutes and duration_minutes > MAX_DURATION_MINUTES:
        logger.info("competitor forensics skipped: too long", video=video_id,
                    minutes=duration_minutes, cap=MAX_DURATION_MINUTES)
        return None

    from omnicast.analytics import av_forensics as avf

    if not avf.ffmpeg_available():
        logger.info("competitor forensics skipped: ffmpeg not on PATH")
        return None

    with tempfile.TemporaryDirectory(prefix="omnicast-forensics-") as workdir:
        path = download_video(video_id, workdir)
        if not path or not os.path.exists(path):
            return None
        report = avf.analyse_video(path, transcript=transcript)
        data = report.as_dict()
        # The local path is scaffolding; keeping it in a persisted artifact would
        # point at a file that no longer exists.
        data["path"] = f"youtube:{video_id}"
        return data
