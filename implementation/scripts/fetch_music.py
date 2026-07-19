"""Seed the royalty-free BGM library (run once).

Downloads a curated set of Kevin MacLeod / Incompetech tracks into
assets/music/<mood>/. These are CC-BY — credit "Music: Kevin MacLeod
(incompetech.com), licensed under Creative Commons: By Attribution 4.0" in each
video description (the auto-uploader can add this automatically).

You can also just drop your own royalty-free .mp3 files into the mood folders
(YouTube Audio Library, Pixabay Music, etc.) — the mixer uses whatever is there.

    python scripts/fetch_music.py
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "music"
_BASE = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
_UA = {"User-Agent": "Mozilla/5.0 (OmniCast music seeder)"}

# mood -> [Kevin MacLeod track names] (verified reachable, CC-BY).
_CURATED = {
    "cinematic": ["The Descent", "Lightless Dawn"],
    "epic": ["Hero Down", "Epic Unease"],
    "dramatic": ["Darkest Child", "Long Note Two"],
    "tense": ["Anxiety", "Lightless Dawn"],
    "ambient": ["Healing", "Bittersweet"],
    "corporate": ["Inspired", "Wallpaper"],
    "uplifting": ["Carefree", "Inspired"],
    "calm": ["Peaceful Desolation", "Lasting Hope"],
}


def _download(name: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    url = _BASE + urllib.parse.quote(name) + ".mp3"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        dest.write_bytes(data)
        print(f"  + {dest.parent.name}/{dest.name} ({len(data)//1024} KB)")
        return True
    except Exception as e:
        print(f"  ! skip {name}: {e}")
        return False


def main() -> int:
    n = 0
    for mood, names in _CURATED.items():
        d = MUSIC_DIR / mood
        d.mkdir(parents=True, exist_ok=True)
        for name in names:
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
            if _download(name, d / f"{safe}.mp3"):
                n += 1
    print(f"\nSeeded {n} tracks into {MUSIC_DIR}")
    print("CC-BY: credit 'Music: Kevin MacLeod (incompetech.com)' in video descriptions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
