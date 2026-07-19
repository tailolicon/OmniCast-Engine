"""Harvest CC0 (public-domain) BGM from FreePD into assets/music/<mood>/.

FreePD tracks are Kevin MacLeod-adjacent but CC0 — NO attribution required, so
they're the safest possible library for monetized videos (project rule: only
AI-generated or royalty-free music). Downloads up to N tracks per mood from
category pages, skipping files that already exist.

Run on the host (needs open internet):  .venv\\Scripts\\python.exe harvest_freepd.py
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "assets" / "music"
UA = {"User-Agent": "Mozilla/5.0 (OmniCast music harvester)"}
PER_MOOD = 6

# FreePD category page -> our mood folder(s).
CATEGORY_TO_MOOD = {
    "https://freepd.com/ambient.php": ["ambient"],
    "https://freepd.com/scoring.php": ["cinematic", "tense"],
    "https://freepd.com/epic.php": ["epic", "dramatic"],
    "https://freepd.com/electronic.php": ["ambient"],
    "https://freepd.com/horror.php": ["tense"],
    "https://freepd.com/upbeat.php": ["uplifting"],
    "https://freepd.com/romantic.php": ["calm"],
    "https://freepd.com/misc.php": ["corporate"],
}

MP3_RE = re.compile(r'href="([^"]+\.mp3)"', re.IGNORECASE)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    added = 0
    for page, moods in CATEGORY_TO_MOOD.items():
        try:
            html = fetch(page).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"[skip] {page}: {e}")
            continue
        links = MP3_RE.findall(html)
        # de-dup, absolutize
        seen: list[str] = []
        for l in links:
            u = urllib.parse.urljoin(page, l)
            if u not in seen:
                seen.append(u)
        for mood in moods:
            dest_dir = MUSIC / mood
            dest_dir.mkdir(parents=True, exist_ok=True)
            have = {p.name.lower() for p in dest_dir.iterdir() if p.is_file()}
            got = 0
            for u in seen:
                if got >= PER_MOOD:
                    break
                name = urllib.parse.unquote(u.rsplit("/", 1)[-1])
                if name.lower() in have:
                    got += 1  # already present counts toward quota
                    continue
                try:
                    data = fetch(u)
                    if len(data) < 200_000:  # skip previews/broken files
                        continue
                    (dest_dir / name).write_bytes(data)
                    print(f"[ok] {mood}/{name} ({len(data)//1024} KB)")
                    added += 1
                    got += 1
                except Exception as e:
                    print(f"[err] {u}: {e}")
    print(f"done — {added} new tracks (CC0, no attribution needed)")


if __name__ == "__main__":
    sys.exit(main())
