"""Fetch transcripts for the flagship research cohort (Phase A step 2).

Reads output/research/<channel>/cohort_packet.json and downloads English
auto-captions for every winner + control via yt_dlp (no OAuth needed), then
flattens the VTT into plain text with a provenance header. Transcripts feed
the competitor dossier and the scoring-v2 calibration corpus.

Usage:
    .venv/Scripts/python.exe scripts/fetch_transcripts.py [--channel senior_wealth_us]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_TAG_RE = re.compile(r"<[^>]+>")
_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> ")


def vtt_to_text(vtt: str) -> str:
    """Flatten a (possibly rolling-caption) VTT into deduplicated plain text."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
            or _TIMESTAMP_RE.match(line)
            or line.isdigit()
        ):
            continue
        text = _TAG_RE.sub("", line).strip()
        # Rolling auto-captions repeat the previous cue line — drop consecutive dupes.
        if text and (not lines or lines[-1] != text):
            lines.append(text)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="senior_wealth_us")
    args = parser.parse_args()

    import yt_dlp

    research_dir = ROOT / "output" / "research" / args.channel
    packet = json.loads(
        (research_dir / "cohort_packet.json").read_text(encoding="utf-8")
    )
    videos = packet["winners"] + packet["controls"]

    out_dir = research_dir / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = research_dir / "_vtt_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-orig"],
        "subtitlesformat": "vtt",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    ok, failed = 0, []
    for video in videos:
        vid = video["video_id"]
        dest = out_dir / f"{video['role']}_{vid}.txt"
        if dest.exists():
            ok += 1
            print(f"SKIP {vid} (already fetched)")
            continue
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            vtt_files = sorted(tmp_dir.glob(f"{vid}*.vtt"))
            if not vtt_files:
                raise RuntimeError("no captions available")
            text = vtt_to_text(vtt_files[0].read_text(encoding="utf-8"))
            if len(text) < 500:
                raise RuntimeError(f"transcript suspiciously short ({len(text)} chars)")
            header = (
                f"# video_id: {vid}\n"
                f"# channel: {video['channel_id']}\n"
                f"# title: {video['title']}\n"
                f"# role: {video['role']} | outlier_ratio: {video['outlier_ratio']}\n"
                f"# duration_min: {video['duration_minutes']} | views: {video['views']}\n"
                f"# source: youtube auto-captions via yt_dlp\n"
                f"# fetched_at: {datetime.now(timezone.utc).isoformat()}\n\n"
            )
            dest.write_text(header + text, encoding="utf-8")
            ok += 1
            print(f"OK   {vid} {video['role']:7s} {len(text):>6d} chars  {video['title'][:55]}")
        except Exception as exc:  # noqa: BLE001 — record and continue
            failed.append({"video_id": vid, "error": str(exc)[:200]})
            print(f"FAIL {vid}: {str(exc)[:120]}")
        time.sleep(2)  # politeness gap

    manifest = {
        "fetched": ok,
        "failed": failed,
        "total": len(videos),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nTRANSCRIPTS: {ok}/{len(videos)} fetched, {len(failed)} failed -> {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
