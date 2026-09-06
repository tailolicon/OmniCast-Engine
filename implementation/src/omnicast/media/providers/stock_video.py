"""Stock Video Search and Downloader Service for OmniCast Engine.

Searches stock video sites (Pexels, Pixabay) and falls back to YouTube (via yt-dlp)
to find B-roll footage, storing them in a local video cache.
"""

from __future__ import annotations

import os
import re
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


# Grammatical stopwords only — content words (night, footprint, kitchen) all count.
_QUERY_STOPWORDS = frozenset(
    "a an the of in on at to for with and or by from into over under".split())


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", text.lower())
            if len(t) >= 3 and t not in _QUERY_STOPWORDS}


# Boilerplate words in stock slugs/tags that describe the FORMAT, not the
# subject — they must never earn relevance credit ('footage' prefix-matched
# 'footprints' and let a burned-wood clip stand in for footprints, live).
_GENERIC_SLUG_TOKENS = frozenset(
    "footage video clip stock close closeup view shot slow motion".split())

# Season words encode the STORYBOARD's intent (season lock), not something a
# stock search or a single frame can verify — 'summer kitchen wall landline'
# missed every Pexels result and the vision gate vetoed 45 good clips for not
# proving 'summer' (live, v9). Strip them before searching and judging.
_SEASON_WORDS = frozenset("summer winter autumn fall spring".split())


def _searchable_query(query: str) -> str:
    kept = [w for w in query.split() if w.lower() not in _SEASON_WORDS]
    return " ".join(kept) or query


def _match_score(query: str, candidate_text: str) -> int:
    """How many of the query's content words the candidate describes.
    Prefix-match at 5+ chars bridges morphology (footprint/footprints)
    without cross-word hits (footage != footprint)."""
    q = _content_tokens(query)
    c = _content_tokens(candidate_text) - _GENERIC_SLUG_TOKENS
    score = 0
    for qt in q:
        if qt in c or any(ct.startswith(qt[:5]) and len(qt) >= 5 for ct in c):
            score += 1
    return score


# A negative term names an IDEA; slugs use sibling nouns for it. 'people'
# never appears in "a-person-in-a-hoodie-walking-at-night" — expand the common
# world-breaker terms to the words slugs actually use (live: a hooded figure
# shipped as the threat under a 'people, faces' negative).
_NEGATIVE_SYNONYMS = {
    "people": ("person", "man", "woman", "girl", "boy", "guy", "figure",
               "silhouette", "hooded", "crowd", "couple"),
    "faces": ("face", "portrait", "closeup of a man", "closeup of a woman"),
    "actor": ("person", "man", "woman", "model", "posing"),
    "text": ("sign", "signage", "billboard", "lettering", "writing"),
    "daylight": ("sunny", "sunshine", "daytime", "midday", "afternoon"),
    "urban": ("city", "downtown", "skyscraper", "apartment", "street"),
}


def _hits_negative(candidate_text: str, negative_terms: list[str] | None) -> str | None:
    """First storyboard negative term the candidate's descriptor matches, if any.
    The storyboard's negative_prompt names this story's world-breakers (snow in
    a summer story, daylight after nightfall, actors in first-person beats) —
    a candidate that matches one is wrong even when it matches the query too
    (live: 'flower bed dirt footprint night' → a snowbound cabin with tracks)."""
    if not negative_terms:
        return None
    c = _content_tokens(candidate_text)
    for term in negative_terms:
        words = list(_content_tokens(term))
        for nt in list(words):
            words.extend(_NEGATIVE_SYNONYMS.get(nt, ()))
        for nt in words:
            for w in _content_tokens(nt) or {nt}:
                if w in c or any(ct.startswith(w[:4]) and len(w) >= 4 for ct in c):
                    return term
    return None


_OCR_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ocr_frame.ps1"


def _clip_dims(video_path: Path) -> tuple[int, int] | None:
    """(width, height) of the clip's video stream; None if unreadable."""
    import subprocess
    try:
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             str(video_path)],
            capture_output=True, text=True, timeout=15)
        w, h = pr.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return None


def _clip_hash(video_path: Path) -> str:
    """Content hash of a clip, for per-render dedup. Full-file md5 (clips are a
    few MB); '' if unreadable."""
    import hashlib
    try:
        return hashlib.md5(video_path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _frame_brightness(video_path: Path) -> float | None:
    """Mean luma (0-255) of the clip, via ffmpeg signalstats YAVG. None if it
    cannot be measured. A nocturnal channel (overnight horror) must not open on
    a bright daylight clip — the on-frame subject gates never looked at
    time-of-day, so a sunny drone shot of the truck stop shipped as the first
    thing the viewer saw (live 2026-09-04)."""
    import subprocess, re as _re
    try:
        # metadata=print emits YAVG lines at INFO level — "-v error" hides them.
        pr = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video_path),
             "-vf", "signalstats,metadata=print", "-frames:v", "20",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        vals = [float(m) for m in _re.findall(
            r"lavfi\.signalstats\.YAVG=([0-9.]+)", pr.stderr)]
        return sum(vals) / len(vals) if vals else None
    except Exception:
        return None


def _frame_text(video_path: Path) -> str:
    """Readable text found in the clip's frames (Windows WinRT OCR, local, free).
    Samples two frames; returns the concatenated recognized text ('' = clean or
    OCR unavailable). Slug/tag scoring cannot see lettering INSIDE the frame —
    a '153' number plaque shipped twice in a story whose plot turns on a number."""
    import subprocess, tempfile
    if not _OCR_SCRIPT.exists() or os.name != "nt":
        return ""
    texts = []
    try:
        dur = 0.0
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=30)
        try:
            dur = float((pr.stdout or "0").strip() or 0)
        except ValueError:
            pass
        # 3 samples: 25/75% missed a payphone's lettering when the pan spent
        # those moments on glass glare (live, v6) — the midpoint catches it.
        marks = [dur * 0.1, dur * 0.5, dur * 0.9] if dur > 1 else [0.0]
        for t in marks:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                jpg = Path(f.name)
            try:
                r = subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                     "-i", str(video_path), "-frames:v", "1", "-q:v", "3", str(jpg)],
                    capture_output=True, timeout=60)
                if r.returncode == 0 and jpg.exists() and jpg.stat().st_size > 0:
                    o = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", str(_OCR_SCRIPT), str(jpg)],
                        capture_output=True, text=True, timeout=90)
                    texts.append((o.stdout or "").strip())
            finally:
                try:
                    jpg.unlink()
                except Exception:
                    pass
    except Exception as e:
        logger.warn("stock_video.ocr_check_failed", error=str(e))
        return ""
    combined = " ".join(t for t in texts if t)
    # Only count REAL lettering: 2+ consecutive alphanumerics (single stray
    # glyphs are OCR noise on texture).
    return combined if re.search(r"[A-Za-z0-9]{2,}", combined) else ""


def _vision_verdict(video_path: Path, query: str) -> dict | None:
    """One Sonnet look at the clip's mid frame via the Claude CLI (Read tool).

    Returns {'readable_text','identifiable_person','depicts'} or None when the
    check cannot run (no CLI, parse failure) — the caller treats None as
    fail-open so a network/CLI hiccup never blocks a render. This exists
    because slug/tag scoring and OCR both miss what only eyes catch: a hooded
    FIGURE standing in for the threat, a payphone under a kitchen line, text
    the OCR sampler's two frames happened to miss (all live, v5/v6)."""
    import subprocess, tempfile, shutil as _sh
    exe = _sh.which("claude")
    if not exe:
        return None
    # The bare CLI inherits env/credentials that make the subscription look
    # org-disabled (live: 'organization has disabled Claude subscription
    # access'). claude_cli's isolated config dir + stripped env is the known
    # working invocation — reuse it.
    try:
        from omnicast.llm.claude_cli import _clean_env
        _env = _clean_env()
    except Exception:
        _env = None
    root = Path(__file__).resolve().parents[4]
    tmpdir = root / "output" / "_vision_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    stem = hashlib.sha256(str(video_path).encode()).hexdigest()[:16]
    # Two frames: a single 2s probe let a person who enters mid-clip ship
    # (codex audit R8/R15: figures at 240/360/480 all survived a 1-frame check).
    jpgs = [tmpdir / f"probe_{stem}_a.jpg", tmpdir / f"probe_{stem}_b.jpg"]
    jpg = jpgs[0]
    try:
        dur = 8.0
        try:
            pr = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(video_path)],
                capture_output=True, text=True, timeout=30)
            dur = float((pr.stdout or "8").strip() or 8)
        except Exception:
            pass
        for j, t in zip(jpgs, (dur * 0.2, dur * 0.8)):
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                 "-i", str(video_path),
                 "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "5", str(j)],
                capture_output=True, timeout=60)
        jpgs = [j for j in jpgs if j.exists() and j.stat().st_size > 0]
        if not jpgs:
            return None
        jpg = jpgs[0]
        names = " and ".join(str(j) for j in jpgs)
        prompt = (
            f"Read the image file(s) {names} (frames of ONE video clip) and "
            "answer with ONLY this JSON object, no prose: "
            "{\"readable_text\": bool, \"identifiable_person\": bool, "
            "\"depicts\": bool, \"animated\": bool}. "
            "A property is true if it holds in ANY frame.\n"
            "readable_text: any legible words/numbers/signage in the frame.\n"
            "identifiable_person: a person whose face or full body is visible "
            "(an anonymous fragment like a hand or boot does NOT count).\n"
            f"depicts: the frames plausibly show this SUBJECT: \"{query}\" — "
            "judge the kind of place/object shown; ignore season, weather or "
            "time-of-day qualifiers a frame cannot prove, and accept any "
            "lighting that is not flatly contradictory.\n"
            "animated: the frame is a cartoon, illustration, drawing, anime, "
            "motion-graphic or any other NON-PHOTOGRAPHIC rendering (real "
            "camera footage, however filtered or grainy, is false).")
        text = ""
        p = subprocess.run(
            [exe, "-p", prompt, "--model", "claude-sonnet-5", "--effort", "low",
             "--output-format", "json", "--max-turns", "4",
             "--tools", "Read", "--disable-slash-commands",
             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'],
            capture_output=True, text=True, timeout=180, cwd=str(root),
            env=_env, stdin=subprocess.DEVNULL)
        if p.returncode == 0:
            payload = json.loads(p.stdout)
            text = payload.get("result") or ""
        else:
            logger.warn("stock_video.vision_cli_error", rc=p.returncode,
                        err=(p.stderr or "")[:120])
            # Claude CLI down (live: 403 org-disabled) — Codex CLI takes
            # images directly and runs on a separate quota.
            cx = _sh.which("codex")
            if cx:
                # The positional prompt is swallowed when it follows -i (live,
                # codex 0.145) — feed it via stdin with the '-' sentinel.
                _iargs = []
                for j in jpgs:
                    _iargs += ["-i", str(j)]
                q = subprocess.run(
                    [cx, "exec", "--sandbox", "read-only",
                     "-c", "model_reasoning_effort=low",
                     *_iargs, "-"],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(root), input=prompt)
                if q.returncode == 0:
                    text = q.stdout or ""
                else:
                    logger.warn("stock_video.vision_codex_error",
                                rc=q.returncode, err=(q.stderr or "")[-160:])
        matches = re.findall(r"\{[^{}]*\}", text)
        for raw in reversed(matches):
            try:
                v = json.loads(raw)
            except Exception:
                continue
            if all(k in v for k in
                   ("readable_text", "identifiable_person", "depicts")):
                return v
        return None
    except Exception as e:
        logger.warn("stock_video.vision_check_failed", error=str(e))
        return None
    finally:
        for j in jpgs if isinstance(jpgs, list) else [jpg]:
            try:
                j.unlink()
            except Exception:
                pass


def fetch_pexels_candidates(query: str, orientation: str = "landscape",
                            negative_terms: list[str] | None = None) -> list[str]:
    """Ranked candidate download URLs from Pexels (best first), after the
    negative-term veto. Empty list = no relevant results."""
    api_key = _api_key("PEXELS_API_KEY")
    if not api_key:
        return []

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
            return []

        # The API's own ranking returned a soil TILLER for 'flower bed dirt
        # footprint night' (live, at the video's final beat). Each video's page
        # URL carries a content slug — rank by how many query words it matches,
        # and treat a page of zero-overlap candidates as NO result so the
        # search falls through to the next provider instead of shipping a
        # wrong-subject clip.
        vetoed = []
        for v in list(videos):
            bad = _hits_negative(v.get("url") or "", negative_terms)
            if bad:
                vetoed.append(v)
                logger.info("stock_video.pexels_negative_veto", query=query,
                            term=bad, url=(v.get("url") or "")[:80])
        videos = [v for v in videos if v not in vetoed]
        if not videos:
            return []
        scored = sorted(
            ((_match_score(query, v.get("url") or ""), i, v)
             for i, v in enumerate(videos)),
            key=lambda t: (-t[0], t[1]))
        # A long specific query matching only ONE word is usually the wrong
        # subject wearing a shared noun ('burned wood on muddy ground' under
        # 'footprints in dirt around house') — demand two hits there.
        required = 2 if len(_content_tokens(query)) >= 4 else 1
        scored = [t for t in scored if t[0] >= required]
        if not scored:
            logger.info("stock_video.pexels_no_relevant_match", query=query,
                        top_url=(videos[0].get("url") or "")[:80])
            return []
        out: list[str] = []
        for _score, _i, video in scored:
            files = video.get("video_files", [])
            hd_files = [f for f in files if f.get("quality") == "hd"]
            best_files = hd_files if hd_files else files
            if best_files:
                # Sort by resolution, pick closest to HD (1920x1080)
                best_files.sort(key=lambda x: abs((x.get("width") or 0) - 1920) + abs((x.get("height") or 0) - 1080))
                link = best_files[0].get("link")
                if link:
                    out.append(link)
        if out:
            logger.info("stock_video.pexels_match_found", url=out[0][:60],
                        candidates=len(out))
        return out

    except Exception as e:
        logger.warn("stock_video.pexels_api_error", query=query, error=str(e))

    return []


def fetch_pexels_video(query: str, orientation: str = "landscape",
                       negative_terms: list[str] | None = None) -> str | None:
    """Best single Pexels download URL (back-compat wrapper)."""
    cands = fetch_pexels_candidates(query, orientation, negative_terms)
    return cands[0] if cands else None


def fetch_pixabay_video(query: str,
                        negative_terms: list[str] | None = None) -> str | None:
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

        # Same relevance guard as Pexels: Pixabay hits carry a 'tags' string —
        # rank by query-word overlap, zero overlap everywhere = no result.
        hits = [h for h in hits
                if not _hits_negative(h.get("tags") or "", negative_terms)]
        if not hits:
            logger.info("stock_video.pixabay_all_vetoed", query=query)
            return None
        scored = sorted(
            ((_match_score(query, h.get("tags") or ""), i, h)
             for i, h in enumerate(hits)),
            key=lambda t: (-t[0], t[1]))
        _required = 2 if len(_content_tokens(query)) >= 4 else 1
        if scored[0][0] < _required:
            logger.info("stock_video.pixabay_no_relevant_match", query=query,
                        top_tags=(hits[0].get("tags") or "")[:80])
            return None
        hit = scored[0][2]
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


def _reject_junk(info: dict, *, incomplete=False,
                 negative_terms: list[str] | None = None) -> str | None:
    """yt-dlp match_filter callable: accept (None) or reject (reason string).
    Drops live/long/tiny clips and anything whose title/uploader looks like a
    stream/gaming/anime/branded upload rather than usable B-roll."""
    if info.get("is_live"):
        return "live stream"
    # Storyboard world-breakers apply to the YouTube title too — yt-dlp is the
    # only source with no slug/tag scoring (live: a hooded-figure clip shipped
    # as the threat from this path under a 'people, faces' negative).
    bad = _hits_negative(info.get("title") or "", negative_terms)
    if bad:
        return f"negative term: {bad}"
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


def fetch_ytdlp_video(query: str, dest: Path, max_seconds: int = 15,
                      negative_terms: list[str] | None = None) -> bool:
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
            'match_filter': (lambda info, *, incomplete=False:
                             _reject_junk(info, incomplete=incomplete,
                                          negative_terms=negative_terms)),
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
                              max_seconds: int = 15,
                              negative_terms: list[str] | None = None,
                              forbid_text: bool = False,
                              nocturnal_max_luma: float | None = None,
                              used_hashes: set | None = None) -> bool:
    """Search for query, download first match (Pexels -> Pixabay -> YouTube) and cache it.

    negative_terms: the storyboard cell's world-breaker words; a candidate whose
    descriptor (Pexels slug / Pixabay tags) matches one is vetoed. The cache key
    includes them — a clip cached without the veto may be exactly the asset the
    veto exists to block."""
    _VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache_key = query if not negative_terms else (
        query + " -" + " -".join(sorted(_content_tokens(" ".join(negative_terms)))))
    if forbid_text:
        # A clip cached before the on-frame gates existed may be exactly the
        # asset the gates block — separate keyspace (bumped when gates change).
        cache_key += " +vgate5"
    if nocturnal_max_luma is not None:
        # A bright daytime clip cached before the night gate must not be served
        # from cache — separate keyspace.
        cache_key += f" +night{int(nocturnal_max_luma)}"
    cache_file = _video_cache_path(cache_key)

    # 1. Check Cache — but a cached clip must STILL pass the per-render dedup:
    # the cache is keyed per query, so the same clip cached under several query
    # keys (from earlier renders) was served to many beats without ever hitting
    # the accept-time dedup (live 2026-09-04: a receipt-rack clip repeated even
    # after dedup shipped, because the repeats were cache hits). Brightness/text
    # are already enforced by the cache key suffixes; only dedup is stateful.
    if cache_file.exists() and cache_file.stat().st_size > 0:
        _cdims = _clip_dims(cache_file)
        if _cdims and target_w >= target_h and _cdims[1] > _cdims[0]:
            logger.info("stock_video.frame_veto", query=query, source="cache",
                        reason="portrait_clip", detail=f"{_cdims[0]}x{_cdims[1]}")
            try:
                cache_file.unlink()  # cached before the orientation gate existed
            except Exception:
                pass
            return False
        if used_hashes is not None:
            h = _clip_hash(cache_file)
            if h and h in used_hashes:
                logger.info("stock_video.frame_veto", query=query,
                            source="cache", reason="duplicate_clip", detail=h[:8])
                return False  # fall back to a fresh generated image
        try:
            logger.info("stock_video.cache_hit", query=query)
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(cache_file, dest)
            if used_hashes is not None:
                h = _clip_hash(cache_file)
                if h:
                    used_hashes.add(h)
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
    search_q = _searchable_query(query)
    words = search_q.split()
    pexels_queries = [search_q]
    if len(words) > 3:
        pexels_queries.append(" ".join(words[:3]))
    def _reject(source: str, reason: str, detail: str = "") -> bool:
        logger.info("stock_video.frame_veto", query=query, source=source,
                    reason=reason, detail=detail[:60])
        try:
            cache_file.unlink()
        except Exception:
            pass
        return False

    def _accept(source: str, **extra) -> bool:
        """Downloaded clip sits in cache_file — run the on-frame gates (OCR,
        then one Sonnet look), then hand it to dest. A rejected clip is deleted
        so the cache never pins a bad asset under this key."""
        # Orientation gate: a portrait clip pillarboxed into a 16:9 render reads
        # as a stolen TikTok (live QC 2026-09-05: a 9:16 rescue clip shipped).
        _dims = _clip_dims(cache_file)
        if _dims and target_w >= target_h and _dims[1] > _dims[0]:
            return _reject(source, "portrait_clip", f"{_dims[0]}x{_dims[1]}")
        if nocturnal_max_luma is not None:
            luma = _frame_brightness(cache_file)
            if luma is not None and luma > nocturnal_max_luma:
                return _reject(source, "too_bright_day", f"YAVG={luma:.0f}")
        if used_hashes is not None:
            # One dim stock clip that clears every gate gets returned for many
            # different queries and dominates the video (live 2026-09-04: a
            # receipt-rack clip filled 4 unrelated beats). Reject a clip already
            # used in THIS render so the caller falls back to a fresh generated
            # image instead of repeating footage.
            h = _clip_hash(cache_file)
            if h and h in used_hashes:
                return _reject(source, "duplicate_clip", h[:8])
        if forbid_text:
            txt = _frame_text(cache_file)
            if txt:
                return _reject(source, "ocr_text", txt)
            v = _vision_verdict(cache_file, search_q)
            if v is not None:  # None = check unavailable → fail open
                if v.get("readable_text"):
                    return _reject(source, "vision_text")
                if v.get("identifiable_person"):
                    return _reject(source, "vision_person")
                if not v.get("depicts"):
                    return _reject(source, "vision_off_subject")
                # A real-look channel must never ship cartoon/storytime stock
                # (live 2026-09-06: a bright animated dinner scene opened the
                # final render). forbid_text is the real-look flag here.
                if v.get("animated"):
                    return _reject(source, "vision_animated")
        if used_hashes is not None:
            h = _clip_hash(cache_file)
            if h:
                used_hashes.add(h)
        import shutil
        shutil.copyfile(cache_file, dest)
        logger.info(f"stock_video.resolved_via_{source}", query=query, **extra)
        return True

    for pq in dict.fromkeys(pexels_queries):  # dedupe, keep order
        # Up to 3 ranked candidates: the best-matching clip can still fail the
        # on-frame text gate; the next one is usually clean.
        for cand in fetch_pexels_candidates(pq, orientation, negative_terms)[:3]:
            if _download_file(cand, cache_file) and _accept("pexels", used=pq):
                return True

    # 3. Try Pixabay Video API
    pixabay_url = fetch_pixabay_video(search_q, negative_terms)
    if pixabay_url:
        if _download_file(pixabay_url, cache_file) and _accept("pixabay"):
            return True

    # 4. Try yt-dlp YouTube Search
    # Append b-roll qualifiers if it does not contain NASA/specific terms and is short on keywords
    refined_query = search_q
    if "b-roll" not in search_q.lower() and "timelapse" not in search_q.lower() and "footage" not in search_q.lower():
        refined_query = f"{search_q} b-roll stock footage"

    if fetch_ytdlp_video(refined_query, cache_file, max_seconds=max_seconds,
                         negative_terms=negative_terms) \
            and _accept("ytdlp"):
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
