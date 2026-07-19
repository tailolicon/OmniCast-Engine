"""Harvest curated Kevin MacLeod (incompetech.com, CC-BY 4.0) BGM per mood.

The existing assets/music library is already MacLeod tracks, so this stays
policy-consistent (royalty-free; attribution line belongs in the YouTube
description — see SPEC note). Downloads direct mp3s; tolerates 404s (names
are curated guesses against incompetech's stable URL scheme); skips existing.

Run on host:  .venv\\Scripts\\python.exe harvest_incompetech.py
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUSIC = ROOT / "assets" / "music"
BASE = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
UA = {"User-Agent": "Mozilla/5.0 (OmniCast music harvester)"}

# Mood -> curated MacLeod track names (documentary/science/tension bed music).
CURATED = {
    "ambient": [
        "Frozen Star", "Ice Flow", "Floating Cities", "Deep Haze",
        "Meditation Impromptu 01", "Meditation Impromptu 02", "Drifting 2",
        "Ghost Story",
    ],
    "tense": [
        "Static Motion", "Ossuary 5 - Rest", "Dark Times", "Echoes of Time",
        "Penumbra", "The House of Leaves", "Awkward Meeting", "Simplex",
    ],
    "cinematic": [
        "Interloper", "Virtutes Instrumenti", "Rynos Theme", "Curse of the Scarab",
        "Blue Feather", "Long Note One", "Long Note Three",
    ],
    "dramatic": [
        "Stormfront", "Volatile Reaction", "Tenebrous Brothers Carnival - Act One",
        "Oppressive Gloom", "Aftermath",
    ],
    "calm": [
        "Wholesome", "Days Past", "Gymnopedie No 1", "Meditation Impromptu 03",
        "Almost in F - Tranquillity",
    ],
    # True-horror narration beds — the slow dark-ambient drones the big creepy
    # channels sit under their VO (not "tense documentary" pulses).
    "horror": [
        "Come Play with Me", "The House of Leaves", "Long Note One",
        "Long Note Two", "Long Note Four", "Anxiety", "Darkling",
        "Night Vigil", "Deep Noise", "Classic Horror 1", "Classic Horror 3",
        "Ossuary 1 - A Beginning", "Ossuary 2 - Turn", "Ossuary 6 - Air",
        "Day of Chaos", "Ice Demon", "Creepy Vibes", "Gathering Darkness",
        "Shadowlands 1 - Horizon", "Shadowlands 4 - Breath",
    ],
}


def main() -> None:
    added = failed = 0
    for mood, names in CURATED.items():
        dest = MUSIC / mood
        dest.mkdir(parents=True, exist_ok=True)
        have = {p.name.lower() for p in dest.iterdir() if p.is_file()}
        for name in names:
            fname = f"{name}.mp3"
            if fname.lower() in have:
                continue
            url = BASE + urllib.parse.quote(fname)
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                if len(data) < 200_000:
                    raise ValueError("too small")
                (dest / fname).write_bytes(data)
                print(f"[ok] {mood}/{fname} ({len(data)//1024} KB)")
                added += 1
            except Exception as e:
                print(f"[miss] {mood}/{fname}: {e}")
                failed += 1
    print(f"done — {added} new tracks, {failed} misses "
          "(CC-BY 4.0 — description must credit: Music by Kevin MacLeod, incompetech.com)")


if __name__ == "__main__":
    main()
