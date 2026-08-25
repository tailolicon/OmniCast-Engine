"""Download captions for every video in a channel's competitor corpus.

`fetch_transcripts.py` pulls only the cohort packet — fifteen videos, enough
for a dossier. The skeleton measurement needs the whole corpus: the finance
channel's numbers come from 133 long-form scripts, and a floor computed from
fifteen would be noise wearing a percentile's clothes.

That corpus was originally built by a one-off command that lived nowhere, so
the second channel to need it had nothing to run. This is that command, made
resumable and rate-limit aware — a 280-video run hit YouTube's 429 partway
through and had to be restarted by hand.

Usage:
  python scripts/fetch_corpus_captions.py --channel true_dread_files_us
  python scripts/fetch_corpus_captions.py --channel X --limit 50 --min-minutes 8
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = the whole corpus")
    ap.add_argument("--min-minutes", type=float, default=0.0,
                    help="skip anything shorter (Shorts carry no usable craft)")
    ap.add_argument("--sleep", type=float, default=1.2,
                    help="seconds between requests; the pace that avoids 429")
    args = ap.parse_args()

    import yt_dlp

    res = ROOT / "output" / "research" / args.channel
    raw_file = res / "raw_videos.json"
    if not raw_file.exists():
        print(f"REJECTED: no corpus at {raw_file} — run flagship_research.py first")
        return 1
    raw = json.loads(raw_file.read_text(encoding="utf-8"))

    out = res / "_vtt_corpus"
    out.mkdir(parents=True, exist_ok=True)

    todo: list[tuple[str, str, float]] = []
    for handle, items in raw.items():
        for v in items:
            vid = v.get("video_id")
            if not vid:
                continue
            if float(v.get("duration_minutes") or 0) < args.min_minutes:
                continue
            todo.append((vid, v.get("title", ""), float(v.get("duration_minutes") or 0)))
    if args.limit:
        todo = todo[: args.limit]

    have = {p.name.split(".")[0] for p in out.glob("*.vtt")}
    pending = [t for t in todo if t[0] not in have]
    print(f"corpus {len(todo)} videos | already on disk {len(todo) - len(pending)} "
          f"| to fetch {len(pending)}")

    opts = {
        "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-orig"], "subtitlesformat": "vtt",
        "outtmpl": str(out / "%(id)s.%(ext)s"), "quiet": True, "no_warnings": True,
    }

    ok = none = failed = 0
    for i, (vid, title, mins) in enumerate(pending, start=1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            got = list(out.glob(f"{vid}*.vtt"))
            if got:
                ok += 1
            else:
                none += 1
                print(f"  [{i}/{len(pending)}] {vid} no captions — {title[:52]}")
        except Exception as exc:
            msg = str(exc)
            failed += 1
            print(f"  [{i}/{len(pending)}] {vid} FAILED: {msg[:90]}")
            # STOP ON A RATE LIMIT instead of grinding through the rest and
            # recording hundreds of false "no captions". Re-running resumes.
            if "429" in msg or "Too Many Requests" in msg:
                print("\nRATE LIMITED — stopping. Re-run later; progress is on disk.")
                break
        if i % 25 == 0:
            print(f"  … {i}/{len(pending)}  ok={ok} none={none} failed={failed}")
        time.sleep(args.sleep)

    total = len(list(out.glob("*.vtt")))
    print(f"\nfetched ok={ok} no-captions={none} failed={failed}")
    print(f"corpus now holds {total} caption files in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
