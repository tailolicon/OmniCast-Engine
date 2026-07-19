"""Harvest the FREE background music competitors credit in their descriptions.

Faceless channels using royalty-free music almost always credit the track
("Music: X by Y", a Pixabay/Incompetech/YouTube-Audio-Library link, etc.). If a
track is genuinely free, ANYONE may use it — so we identify the track from the
competitor's *own credit* and fetch it from its ORIGINAL royalty-free source
(never rip the audio out of their video — wrong quality + unverifiable license).

Flow: top competitor videos → full descriptions → regex music credits + source
URLs → (auto-download known direct sources e.g. Incompetech; list the rest for
manual add) → drop into assets/music/<mood>/.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUSIC_DIR = ROOT / "assets" / "music"
_YT_API = "https://www.googleapis.com/youtube/v3/videos"
_UA = {"User-Agent": "Mozilla/5.0 (OmniCast)"}

# Lines that credit music + the free-source domains we recognize.
_CREDIT_RE = re.compile(
    r"(?im)^(?:.*\b(?:music|song|track|audio|beat|bgm|background music)\b.*)$")
_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_FREE_DOMAINS = (
    "incompetech.com", "pixabay.com", "freemusicarchive.org", "chosic.com",
    "bensound.com", "youtube.com/audiolibrary", "freepd.com", "ccmixter.org",
    "purple-planet.com", "fesliyanstudios.com",
)


def _full_descriptions(video_ids: list[str], api_key: str) -> dict[str, dict]:
    """videos.list snippet (FULL description, not truncated). {vid: {title,desc}}."""
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        params = urllib.parse.urlencode({
            "part": "snippet", "id": ",".join(video_ids[i:i + 50]), "key": api_key})
        try:
            req = urllib.request.Request(f"{_YT_API}?{params}", headers=_UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception:
            continue
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            out[it["id"]] = {"title": sn.get("title", ""),
                             "description": sn.get("description", "")}
    return out


def extract_credits(description: str) -> list[dict]:
    """Pull music-credit lines + any free-source URLs from a description."""
    found = []
    for line in description.splitlines():
        if not _CREDIT_RE.match(line):
            continue
        urls = [u for u in _URL_RE.findall(line)
                if any(d in u.lower() for d in _FREE_DOMAINS)]
        # also grab a URL on the next-ish lines? keep simple: same line only.
        if urls or re.search(r"\bby\b", line, re.I):
            found.append({"credit": line.strip()[:200], "urls": urls})
    return found


def harvest(video_ids: list[str], api_key: str) -> list[dict]:
    """Return harvested free-music credits across competitor videos (deduped)."""
    descs = _full_descriptions(video_ids, api_key)
    seen, out = set(), []
    for vid, d in descs.items():
        for c in extract_credits(d.get("description", "")):
            key = c["credit"].lower()
            if key in seen:
                continue
            seen.add(key)
            c["video_title"] = d.get("title", "")
            out.append(c)
    return out


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < 50_000:  # too small = not audio
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def auto_fetch(credits: list[dict], mood: str = "ambient") -> list[str]:
    """Download tracks from KNOWN direct-download sources (Incompetech .mp3).
    Other sources are returned for manual handling. Returns saved file names."""
    saved = []
    for c in credits:
        for u in c.get("urls", []):
            if "incompetech.com" in u and u.lower().endswith(".mp3"):
                name = urllib.parse.unquote(u.rsplit("/", 1)[-1])
                safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in name)
                if _download(u, MUSIC_DIR / mood / safe):
                    saved.append(f"{mood}/{safe}")
    return saved


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from omnicast.config.settings import get_settings
    vids = sys.argv[1].split(",") if len(sys.argv) > 1 else []
    res = harvest(vids, get_settings().youtube_api_key)
    print(json.dumps(res, ensure_ascii=False, indent=2))
