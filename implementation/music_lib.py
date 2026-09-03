"""Royalty-free background-music library + mixer (no AI, reusable tracks).

Drop royalty-free .mp3/.m4a/.wav files into assets/music/<mood>/ once; every
render reuses them. A channel's niche maps to a mood, the mixer picks a track,
loops/trims it to the video length, ducks it well under the narration, and adds
fade in/out. Free sources to seed the folders (download once, reuse forever):
  - YouTube Audio Library (studio.youtube.com → Audio Library) — free, mostly no
    attribution.
  - Pixabay Music (pixabay.com/music) — free, no attribution.
  - Incompetech / Kevin MacLeod — CC-BY (credit in video description).
"""

from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUSIC_DIR = ROOT / "assets" / "music"
_EXTS = (".mp3", ".m4a", ".wav", ".ogg", ".flac")

# Niche / channel style → music mood (folder under assets/music/).
_NICHE_MOOD = {
    "finance": "corporate", "dark_finance": "tense", "crypto": "tense",
    "history": "cinematic", "documentary": "cinematic", "mythology": "epic",
    # Health/nutrition here is WARNING/mechanism content (vfact-style "ambient
    # science" bed) — "uplifting/Carefree" reads as elevator music under a
    # nausea-warning VO (operator feedback 2026-07-09).
    "psychology": "ambient", "health": "ambient", "nutrition": "ambient",
    "stoic": "calm", "philosophy": "calm",
}
_STYLE_MOOD = {
    "editorial": "corporate", "watercolor": "calm",
    "documentary": "cinematic", "dark_finance": "tense",
}
_DEFAULT_MOOD = "ambient"
# Moods we expect to have folders for (seed these).
MOODS = ["cinematic", "dramatic", "ambient", "corporate", "uplifting",
         "tense", "calm", "epic", "horror"]


def resolve_mood(niche: str = "", style: str = "", explicit: str = "") -> str:
    if explicit:
        return explicit.lower().strip()
    n = (niche or "").lower().strip()
    if n in _NICHE_MOOD:
        return _NICHE_MOOD[n]
    s = (style or "").lower().strip()
    if s in _STYLE_MOOD:
        return _STYLE_MOOD[s]
    return _DEFAULT_MOOD


def _tracks(mood: str) -> list[Path]:
    d = MUSIC_DIR / mood
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() in _EXTS)


def pick_track(mood: str, *, seed: str | None = None) -> Path | None:
    """Pick a track for a mood. Falls back to any available track if the mood
    folder is empty. `seed` (e.g. channel_id) keeps a channel's pick stable-ish
    while still varying across moods. None if no music at all."""
    pool = _tracks(mood)
    if not pool:
        # fall back to any track in the library
        for m in MOODS:
            pool = _tracks(m)
            if pool:
                break
    if not pool:
        for sub in (MUSIC_DIR.iterdir() if MUSIC_DIR.exists() else []):
            if sub.is_dir():
                pool = [p for p in sub.iterdir() if p.suffix.lower() in _EXTS]
                if pool:
                    break
    if not pool:
        return None
    rng = random.Random(seed) if seed else random
    return rng.choice(pool)


def available() -> bool:
    return bool(shutil.which("ffmpeg")) and any(_tracks(m) for m in MOODS) \
        or (MUSIC_DIR.exists() and any(
            p.suffix.lower() in _EXTS for p in MUSIC_DIR.rglob("*")))


def mix_bgm(video: Path, track: Path, *, volume: float = 0.10,
            fade_out_s: float = 3.0) -> bool:
    """Mix `track` under the video's existing narration: loop/trim to video
    length, fade in 2s / out `fade_out_s`, duck to `volume` (~-20 dB). Replaces
    `video` in place. Returns True on success."""
    fm = shutil.which("ffmpeg")
    if not fm or not video.exists() or not track.exists():
        return False
    try:
        dur = _probe_dur(video)
        if dur <= 0:
            return False
        out = video.with_name(video.stem + "_bgm.mp4")
        st_out = max(0.0, dur - fade_out_s)
        filt = (
            f"[1:a]volume={volume * 1.6},afade=t=in:st=0:d=2,"
            f"afade=t=out:st={st_out:.2f}:d={fade_out_s}[bg];"
            f"[bg][0:a]sidechaincompress=threshold=0.12:ratio=5:attack=80:release=500[bg_duck];"
            f"[0:a][bg_duck]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
        proc = subprocess.run(
            [fm, "-y", "-i", str(video.resolve()),
             "-stream_loop", "-1", "-i", str(track.resolve()),
             "-filter_complex", filt,
             "-map", "0:v", "-map", "[a]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", str(out.resolve())],
            capture_output=True, text=True, timeout=1800,
        )
        if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            return False
        import os, time
        # The target is often LOCKED by a media player previewing the fresh
        # render (WinError 5) — retry briefly instead of silently dropping BGM.
        for _try in range(6):
            try:
                os.replace(out, video)
                return True
            except PermissionError:
                if _try == 0:
                    print("      [bgm] video.mp4 locked (player open?) — retrying...")
                time.sleep(5)
        print("      [bgm] target still locked — close the video player and re-run")
        return False
    except Exception as exc:
        print(f"      [warn] bgm mix failed: {exc}")
        return False


def _probe_dur(mp4: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(mp4)],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def apply_to_video(video: Path, *, niche: str = "", style: str = "",
                   mood: str = "", channel_id: str = "", volume: float = 0.10) -> str | None:
    """Pick a mood-matched track and mix it into `video`. Returns the track name
    used, or None if no music available / mix failed."""
    if not shutil.which("ffmpeg"):
        return None
    m = resolve_mood(niche, style, mood)
    track = pick_track(m, seed=channel_id or None)
    if not track:
        return None
    ok = mix_bgm(video, track, volume=volume)
    return f"{m}/{track.name}" if ok else None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        v = Path(sys.argv[1])
        niche = sys.argv[2] if len(sys.argv) > 2 else ""
        print(apply_to_video(v, niche=niche) or "no music / failed")
    else:
        print("moods present:", {m: len(_tracks(m)) for m in MOODS})
