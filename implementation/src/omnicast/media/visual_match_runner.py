"""Run frame-level VO-to-visual quality control for channels that require it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from omnicast.media.output_audit import OutputQualityAuditor


async def run_visual_match_qc(
    product_dir: str | Path,
    video_path: str | Path,
    channel_config: dict,
    qc_script: str | Path,
) -> dict:
    """Run the vision grader and fail closed when a required check is weak.

    The grader's report is subsequently validated against the exact MP4 hash,
    so a successful report from an older render cannot release a new cut.
    """
    required = bool((channel_config or {}).get("visual_match_qc_required"))
    if not required:
        return {"required": False, "ran": False}

    product = Path(product_dir)
    video = Path(video_path)
    script = Path(qc_script)
    if not script.exists():
        raise RuntimeError(f"visual match QC script missing: {script}")
    if not video.exists():
        raise RuntimeError(f"visual match QC video missing: {video}")

    threshold = int((channel_config or {}).get(
        "visual_match_qc_threshold", 5))
    argv = [
        sys.executable,
        "-X",
        "utf8",
        str(script),
        str(product),
        "--threshold",
        str(threshold),
    ]
    limit = (channel_config or {}).get("visual_match_qc_limit")
    if limit is not None:
        argv.extend(["--limit", str(max(1, int(limit)))])

    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    diagnostic = (
        (stdout or b"").decode("utf-8", errors="replace")
        + "\n"
        + (stderr or b"").decode("utf-8", errors="replace")
    ).strip()
    if process.returncode != 0:
        raise RuntimeError(
            "visual match QC failed: " + (diagnostic[-1200:] or
                                           f"exit {process.returncode}"))

    verdict = OutputQualityAuditor(measure_loudness=False).inspect_visual_match(
        product, video, required=True)
    if not verdict.get("passed"):
        issues = ", ".join(verdict.get("issues") or ["invalid QC report"])
        raise RuntimeError(f"visual match QC failed validation: {issues}")
    return {**verdict, "ran": True}
