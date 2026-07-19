"""Free stock images from Wikimedia Commons — no API key, no cost.

Ported from profesor-gato's wikimedia_fetcher. Searches Commons for real
historical/encyclopedic images and downloads thumbnails (1200px, which Commons
serves without rate-limiting the original). Useful as a fallback background
source when Flow/credits are unavailable, or for history/documentary channels
that want real photographs instead of generated art.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

_API = "https://commons.wikimedia.org/w/api.php"
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_MIN_WIDTH = 800
_THUMB_WIDTH = 1200
_DELAY = 0.5
_UA = "OmniCastBot/1.0 (https://github.com/omnicast)"


def _search_titles(query: str, limit: int = 15) -> list[str]:
    params = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query,
        "srnamespace": 6, "srlimit": limit, "format": "json",
    })
    req = urllib.request.Request(f"{_API}?{params}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return [item["title"] for item in data.get("query", {}).get("search", [])]


def _get_urls(titles: list[str]) -> list[dict]:
    """Return [{url, mime, width}] from thumbnail URLs (avoids Commons 429)."""
    if not titles:
        return []
    params = urllib.parse.urlencode({
        "action": "query", "titles": "|".join(titles[:15]),
        "prop": "imageinfo", "iiprop": "url|mime|size",
        "iiurlwidth": _THUMB_WIDTH, "format": "json",
    })
    req = urllib.request.Request(f"{_API}?{params}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    out = []
    for page in data.get("query", {}).get("pages", {}).values():
        for info in page.get("imageinfo") or []:
            mime = info.get("mime", "")
            thumb = info.get("thumburl") or info.get("url", "")
            width = info.get("thumbwidth") or info.get("width", 0)
            if mime in _ALLOWED_MIME and thumb and width >= _MIN_WIDTH:
                out.append({"url": thumb, "mime": mime, "width": width})
    return out


def fetch_images(topic: str, n: int = 6, folder: Path | None = None) -> list[Path]:
    """Download up to `n` Commons images for `topic`. Returns downloaded Paths
    (may be < n). Tries the full topic, then the first words, then an English
    '... history' fallback for broader coverage."""
    folder = folder or (Path("output") / "_wikimedia")
    folder.mkdir(parents=True, exist_ok=True)

    titles: list[str] = []
    for q in (topic, " ".join(topic.split()[:3])):
        titles = _search_titles(q, limit=20)
        if len(titles) >= n:
            break
    cands = _get_urls(titles)
    cands.sort(key=lambda c: c["width"], reverse=True)

    if len(titles) < n:
        en = _search_titles(" ".join(topic.split()[:4]) + " history", limit=15)
        titles = list(dict.fromkeys(titles + en))
        cands = _get_urls(titles)
        cands.sort(key=lambda c: c["width"], reverse=True)

    saved: list[Path] = []
    for i, c in enumerate(cands):
        if len(saved) >= n:
            break
        ext = ".jpg" if "jpeg" in c["mime"] else ".png"
        dest = folder / f"wiki_{i:02d}{ext}"
        if dest.exists():
            saved.append(dest)
            continue
        try:
            req = urllib.request.Request(c["url"], headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                dest.write_bytes(r.read())
            saved.append(dest)
            time.sleep(_DELAY)
        except Exception as e:
            print(f"      [warn] wikimedia fetch failed {c['url'][:60]}: {e}")
    print(f"      wikimedia: {len(saved)}/{n} images for '{topic[:40]}'")
    return saved


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "Roman Colosseum"
    print([str(p) for p in fetch_images(q, 3)])
