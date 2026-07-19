"""Stock Video Search and Downloader Service for OmniCast Engine.

Searches stock video sites (Pexels, Pixabay) and falls back to YouTube (via yt-dlp)
to find B-roll footage, storing them in a local video cache.
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import urllib.parse
import urllib.request
import time
from pathlib import Path
import structlog

logger = structlog.get_logger()

_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # implementation/
_VIDEO_CACHE_DIR = _ROOT / "output" / "_video_cache"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _api_key(name: str) -> str | None:
    """Resolve an API key from os.environ first, then the pydantic Settings (which
    loads .env). Subprocesses spawned by the API server inherit os.environ but
    pydantic-settings does NOT export vars to os.environ, so env-only lookups miss."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        from omnicast.config.settings import get_settings
        return getattr(get_settings(), name.lower(), "") or None
    except Exception:
        return None


def _download_file(url: str, dest: Path) -> bool:
    """Download url to dest using urllib with desktop User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        logger.warn("stock_video.download_failed", url=url[:60], error=str(e))
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        return False


def fetch_pexels_video(query: str, orientation: str = "landscape") -> str | None:
    """Search Pexels Videos API and return the best direct download URL."""
    api_key = _api_key("PEXELS_API_KEY")
    if not api_key:
        return None

    logger.info("stock_video.pexels_search_start", query=query)
    params = urllib.parse.urlencode({
        "query": query,
        "per_page": 5,
        "orientation": orientation
    })
    url = f"https://api.pexels.com/videos/search?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": api_key,
        "User-Agent": _UA
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        
        videos = data.get("videos", [])
        if not videos:
            logger.info("stock_video.pexels_no_results", query=query)
            return None

        # Pick the first video, find HD file
        video = videos[0]
        files = video.get("video_files", [])
        
        # Look for HD files first
        hd_files = [f for f in files if f.get("quality") == "hd"]
        best_files = hd_files if hd_files else files
        
        if best_files:
            # Sort by resolution, pick closest to HD (1920x1080)
            best_files.sort(key=lambda x: abs((x.get("width") or 0) - 1920) + abs((x.get("height") or 0) - 1080))
            best_url = best_files[0].get("link")
            if best_url:
                logger.info("stock_video.pexels_match_found", url=best_url[:60])
                return best_url

    except Exception as e:
        logger.warn("stock_video.pexels_api_error", query=query, error=str(e))
    
    return None


def fetch_pixabay_video(query: str) -> str | None:
    """Search Pixabay Video API and return the best direct download URL."""
    api_key = _api_key("PIXABAY_API_KEY")
    if not api_key:
        return None

    logger.info("stock_video.pixabay_search_start", query=query)
    params = urllib.parse.urlencode({
        "key": api_key,
        "q": query,
        "per_page": 5
    })
    url = f"https://pixabay.com/api/videos/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        
        hits = data.get("hits", [])
        if not hits:
            logger.info("stock_video.pixabay_no_results", query=query)
            return None

        # Pick the first match, and look for large/medium video size
        hit = hits[0]
        videos = hit.get("videos", {})
        
        # Check order of preference: medium, large, small
        for size in ("medium", "large", "small"):
            v_info = videos.get(size)
            if v_info and v_info.get("url"):
                logger.info("stock_video.pixabay_match_found", size=size, url=v_info["url"][:60])
                return v_info["url"]

    except Exception as e:
        logger.warn("stock_video.pixabay_api_error", query=query, error=str(e))
        
    return None


# Title/uploader tokens that signal an irrelevant or branded clip (Twitch streams,
# gaming, anime/AMV, reactions, vlogs, trailers, watermarked compilations). yt-dlp
# scrapes raw YouTube, so without a curated source (Pexels) we reject these by name.
_JUNK_TOKENS = (
    "twitch", "stream", "gameplay", "gaming", "game play", "speedrun", "anime",
    "amv", "react", "reaction", "vlog", "trailer", "lyric", "mukbang", "podcast",
    "highlight", "montage", "edit", "tiktok compilation", "minecraft", "roblox",
    "fortnite", "valorant", "vtuber", "asmr", " ost", "music video",
    # Animals / pets — break the tone of a medical/nutrition film
    "cat", "kitten", "dog", "puppy", "pet", "kitty", "hamster", "rabbit",
    "parrot", "aquarium", "wildlife", "funny animal",
    # Apparel / fashion — wrong sense of words like "quality"/"material"
    "clothing", "fashion", "outfit", "try on", "tryon", "haul", "wardrobe",
    "apparel", "sneaker", "shoe review", "ready to wear",
)


def _reject_junk(info: dict, *, incomplete=False) -> str | None:
    """yt-dlp match_filter callable: accept (None) or reject (reason string).
    Drops live/long/tiny clips and anything whose title/uploader looks like a
    stream/gaming/anime/branded upload rather than usable B-roll."""
    if info.get("is_live"):
        return "live stream"
    dur = info.get("duration") or 0
    if dur and (dur < 2 or dur > 360):
        return f"duration {dur}s out of range"
    hay = ((info.get("title") or "") + " " + (info.get("uploader") or "")
           + " " + (info.get("channel") or "")).lower()
    import re as _re
    for tok in _JUNK_TOKENS:
        # Word-boundary match so short tokens (cat/dog/pet) don't fire inside
        # 'education'/'dogma'/'carpet'. Multiword tokens match as a phrase.
        if _re.search(r"\b" + _re.escape(tok) + r"\b", hay):
            return f"junk token: {tok}"
    return None


def fetch_ytdlp_video(query: str, dest: Path, max_seconds: int = 15) -> bool:
    """Download a SHORT B-roll segment from YouTube via yt-dlp.

    Downloads only the first ``max_seconds`` (download_sections) of a video-only
    stream (narration replaces audio) and recodes to a real MP4 container. The
    render compositor loops/trims this to the exact narration duration, so a short
    clean segment is all we need — no full-video downloads, no .mkv mislabeling.
    """
    logger.info("stock_video.ytdlp_search_start", query=query)
    try:
        import yt_dlp
        from yt_dlp.utils import download_range_func

        # Clean any prior partials/outputs at this stem.
        stem = dest.with_suffix("")
        for p in dest.parent.glob(stem.name + ".*"):
            try:
                p.unlink()
            except Exception:
                pass

        ydl_opts = {
            # Video-only (no audio — narration replaces it); cap at 1080p.
            'format': 'bv*[height<=1080]/best[height<=1080]/best',
            'outtmpl': str(stem) + '.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            # Reject irrelevant junk by title/uploader + duration (see _reject_junk).
            'match_filter': _reject_junk,
            # Grab only the first N seconds, snapping to keyframes.
            'download_ranges': download_range_func(None, [(0, max_seconds)]),
            'force_keyframes_at_cuts': True,
            # Stop after the FIRST result that passes the filter + downloads OK.
            'max_downloads': 1,
            # Always end up with a real .mp4 container.
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
            'merge_output_format': 'mp4',
        }

        # ytsearch5 + match_filter: scan the top 5 results and download the FIRST
        # that passes (short, not-live) — ytsearch1 would grab whatever ranks #1,
        # often an unrelated long stream.
        search_query = f"ytsearch5:{query}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([search_query])
            except yt_dlp.utils.MaxDownloadsReached:
                pass  # expected: one good clip grabbed, stop scanning

        # Resolve whatever file landed (postproc should yield .mp4).
        produced = None
        if dest.exists() and dest.stat().st_size > 0:
            produced = dest
        else:
            for cand in sorted(dest.parent.glob(stem.name + ".*")):
                if cand.suffix.lower() in (".mp4", ".mkv", ".webm") and cand.stat().st_size > 0:
                    produced = cand
                    break

        if produced is None:
            logger.warn("stock_video.ytdlp_download_failed", query=query)
            return False

        if produced != dest:
            if produced.suffix.lower() == ".mp4":
                if dest.exists():
                    dest.unlink()
                produced.rename(dest)
            else:
                # Non-mp4 container slipped through → transcode (don't just rename).
                import subprocess
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(produced), "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-an", str(dest)],
                    check=True, capture_output=True,
                )
                try:
                    produced.unlink()
                except Exception:
                    pass

        ok = dest.exists() and dest.stat().st_size > 0
        if ok:
            logger.info("stock_video.ytdlp_download_success", path=str(dest))
        return ok

    except Exception as e:
        logger.error("stock_video.ytdlp_api_error", query=query, error=str(e))
        return False


def _video_cache_path(query: str) -> Path:
    """Generate cache file path for a query."""
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:32]
    return _VIDEO_CACHE_DIR / f"video_{key}.mp4"


def download_best_stock_video(query: str, dest: Path, target_w: int = 1920, target_h: int = 1080,
                              max_seconds: int = 15) -> bool:
    """Search for query, download first match (Pexels -> Pixabay -> YouTube) and cache it."""
    _VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache_file = _video_cache_path(query)

    # 1. Check Cache
    if cache_file.exists() and cache_file.stat().st_size > 0:
        try:
            logger.info("stock_video.cache_hit", query=query)
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(cache_file, dest)
            return True
        except Exception as e:
            logger.warn("stock_video.cache_copy_failed", error=str(e))

    # Determine orientation for Pexels search
    orientation = "portrait" if target_h > target_w else "landscape"

    # 2. Try Pexels (curated, no watermark, always relevant) — full query first,
    # then progressively simpler queries, since Pexels' library is smaller and a
    # long specific query often returns 0. Maximizing Pexels hits avoids the
    # watermark/junk risk of the yt-dlp fallback.
    # Drop trailing modifiers but keep ≥3 leading words so the disambiguating noun
    # survives. Shortening to 2 words pulls the wrong domain — e.g.
    # 'person reading nutrition label' -> 'person reading' -> clothing-tag footage.
    # Pexels results can't be content-filtered, so a too-generic query is dangerous;
    # let anything shorter fall through to the junk-filtered yt-dlp path instead.
    words = query.split()
    pexels_queries = [query]
    if len(words) > 3:
        pexels_queries.append(" ".join(words[:3]))
    for pq in dict.fromkeys(pexels_queries):  # dedupe, keep order
        pexels_url = fetch_pexels_video(pq, orientation)
        if pexels_url and _download_file(pexels_url, cache_file):
            import shutil
            shutil.copyfile(cache_file, dest)
            logger.info("stock_video.resolved_via_pexels", query=query, used=pq)
            return True

    # 3. Try Pixabay Video API
    pixabay_url = fetch_pixabay_video(query)
    if pixabay_url:
        if _download_file(pixabay_url, cache_file):
            import shutil
            shutil.copyfile(cache_file, dest)
            logger.info("stock_video.resolved_via_pixabay", query=query)
            return True

    # 4. Try yt-dlp YouTube Search
    # Append b-roll qualifiers if it does not contain NASA/specific terms and is short on keywords
    refined_query = query
    if "b-roll" not in query.lower() and "timelapse" not in query.lower() and "footage" not in query.lower():
        refined_query = f"{query} b-roll stock footage"

    if fetch_ytdlp_video(refined_query, cache_file, max_seconds=max_seconds):
        import shutil
        shutil.copyfile(cache_file, dest)
        logger.info("stock_video.resolved_via_ytdlp", query=query)
        return True

    logger.error("stock_video.all_sources_failed", query=query)
    return False


if __name__ == "__main__":
    # Test execution
    q = sys.argv[1] if len(sys.argv) > 1 else "glacier melting"
    out = Path("output/test_stock.mp4")
    print(f"Downloading stock video for query: '{q}'...")
    if download_best_stock_video(q, out):
        print(f"Success! Saved to {out}")
    else:
        print("Failed to download stock video.")
