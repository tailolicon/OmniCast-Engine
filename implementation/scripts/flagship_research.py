"""Phase A research runner for the flagship senior-finance channel.

FLAGSHIP_SeniorFinance_Channel.md steps 1-2: scan the channel's competitor
handles with the REAL YouTube Data API, build a winner/matched-control cohort
(the first production caller of `analytics.cohort`), and persist a research
packet with provenance. The same packet doubles as the scoring-v2 calibration
corpus and, later, the NotebookLM input.

Usage:
    .venv/Scripts/python.exe scripts/flagship_research.py \
        [--channel senior_wealth_us] [--per-channel 40]

Output: output/research/<channel_id>/cohort_packet.json (+ raw_videos.json).
Read-only against YouTube; costs Data API units (~5/channel), no LLM calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="senior_wealth_us")
    parser.add_argument("--per-channel", type=int, default=40)
    args = parser.parse_args()

    from omnicast.analytics.cohort import select_cohort
    from omnicast.config.settings import get_settings
    from omnicast.discovery.youtube_scanner import YouTubeScanner

    settings = get_settings()
    api_key = getattr(settings, "youtube_api_key", "")
    if not api_key:
        print("REJECTED: youtube_api_key missing in settings")
        return 1

    cfg_path = ROOT / "channels" / f"{args.channel}.json"
    channel = json.loads(cfg_path.read_text(encoding="utf-8"))
    handles = channel.get("competitor_handles", [])
    if not handles:
        print("REJECTED: channel config has no competitor_handles")
        return 1

    # The scanner only reads a handful of config attrs; a namespace keeps this
    # script decoupled from the full Channel model.
    scan_cfg = SimpleNamespace(
        competitor_channel_ids=[], competitor_handles=handles,
        niche=channel.get("niche", "finance"), markets=[],
    )
    scanner = YouTubeScanner(config=scan_cfg, api_key=api_key)

    videos_by_channel: dict[str, list[dict]] = {}
    notes: list[str] = []
    for handle in handles:
        try:
            cid = await scanner._resolve_handle(handle)
            playlist = await scanner._get_channel_uploads_playlist_id(cid)
            vid_ids = await scanner._get_recent_video_ids(
                playlist, max_results=args.per_channel
            )
            stats = await scanner._get_video_stats(vid_ids)
            videos_by_channel[handle] = stats
            print(f"OK  {handle}: {len(stats)} videos")
        except Exception as exc:  # noqa: BLE001 — one dead handle must not kill the scan
            notes.append(f"{handle}: scan failed — {str(exc)[:160]}")
            print(f"ERR {handle}: {str(exc)[:120]}")

    if not videos_by_channel:
        print("REJECTED: no competitor channel could be scanned")
        return 1

    cohort = select_cohort(videos_by_channel)
    packet = cohort.as_packet()
    packet["scan_notes"] = notes
    packet["scanned_at"] = datetime.now(timezone.utc).isoformat()
    packet["channel_id"] = args.channel
    packet["source_handles"] = handles

    out_dir = ROOT / "output" / "research" / args.channel
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cohort_packet.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out_dir / "raw_videos.json").write_text(
        json.dumps(videos_by_channel, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(
        f"\nCOHORT: {packet['winner_count']} winners / {packet['control_count']} "
        f"controls | coverage {packet.get('control_coverage', 'n/a')} | "
        f"notes {len(packet['notes'])} | saved to {out_dir}"
    )
    for w in packet["winners"][:10]:
        print(f"  WIN  x{w['outlier_ratio']:>5}  {w['title'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
