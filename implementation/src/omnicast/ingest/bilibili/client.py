"""Bilibili (bilibili.com — mainland China) ingest: one link → local mp4 + metadata.

Scope, decided narrow on purpose:
  * UGC videos only — `BV…`/`av…` pages, `b23.tv` share links, multi-part
    videos via `?p=N`. Bangumi (`/bangumi/play/ep…`) is licensed catalogue
    content and is refused with a clear error, as is the international
    bilibili.tv site (different service, different API).
  * Talks to the documented web API directly with httpx (already a project
    dependency) instead of vendoring a downloader: unlike Douyin there is no
    JS-emulation wall here — WBI signing is a fixed md5 recipe (`wbi.py`).
  * playurl is asked for DASH (fnval=4048): video and audio arrive as separate
    .m4s streams and are muxed losslessly with ffmpeg, which every reup stage
    already requires. Old videos may return a single `durl` file instead —
    that path remuxes to mp4 for pipeline consistency.
  * Anonymous sessions are capped by bilibili (~480p). A `SESSDATA` cookie
    (config.cookies or the BILIBILI_SESSDATA env var) unlocks 1080p. The CDN
    rejects requests without a bilibili.com Referer — the shared client
    carries it on every call.

The returned `BilibiliAsset` mirrors the DouyinAsset field names the reup
runner reads (`aweme_id`, `title`, `author_name`, `video_path`, `cover_path`,
`save_dir`, `is_video`), so the pipeline downstream of download does not know
platforms exist. `aweme_id` carries `BV…` (or `BV…_pN` for one part of a
multi-part video) — it is simply "the source's id" everywhere else.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from omnicast.ingest.bilibili.wbi import sign_params

API_BASE = "https://api.bilibili.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_REFERER = "https://www.bilibili.com/"

_SHORT_HOSTS = ("b23.tv", "bili2233.cn")
_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"(?:^|/)av(\d+)", re.IGNORECASE)

# qn ladder (web): 120=4K 116=1080p60 80=1080p 64=720p 32=480p 16=360p
DEFAULT_QUALITY_MAX = 80


class BilibiliIngestError(RuntimeError):
    pass


@dataclass(slots=True)
class BilibiliIngestConfig:
    output_dir: Path
    cookies: dict[str, str] = field(default_factory=dict)
    proxy: str = ""
    quality_max: int = DEFAULT_QUALITY_MAX
    timeout: float = 30.0


@dataclass(slots=True)
class BilibiliAsset:
    """Field-compatible with DouyinAsset for everything the runner touches."""

    aweme_id: str                      # BV… or BV…_pN — the pipeline's source id
    source_url: str
    video_path: Path
    title: str
    author_name: str = ""
    media_type: str = "video"
    tags: list[str] = field(default_factory=list)
    create_time: int | None = None
    publish_date: str = ""
    save_dir: Path | None = None
    cover_path: Path | None = None
    # bilibili specifics, for callers that know what they hold
    bvid: str = ""
    cid: int = 0
    page: int = 1
    quality: int = 0

    @property
    def is_video(self) -> bool:
        return True


# ── URL parsing (pure, unit-tested) ─────────────────────────────────────────

def parse_video_ref(url: str) -> dict:
    """{'bvid' | 'aid', 'page'} from a bilibili.com video URL or bare id.

    Raises for bangumi and for the international bilibili.tv — both look
    similar to a UGC link and failing loudly beats downloading the wrong thing.
    """
    text = (url or "").strip()
    if not text:
        raise BilibiliIngestError("Link Bilibili trống")
    if _BV_RE.fullmatch(text) or re.fullmatch(r"av\d+", text, re.IGNORECASE):
        text = f"https://www.bilibili.com/video/{text}"
    probe = text if "://" in text else f"https://{text}"
    parts = urlsplit(probe)
    host = (parts.hostname or "").lower()
    if host == "bilibili.tv" or host.endswith(".bilibili.tv"):
        raise BilibiliIngestError(
            "Đây là bilibili.tv (bản quốc tế) — chỉ hỗ trợ bilibili.com nội địa Trung."
        )
    if "/bangumi/" in parts.path:
        raise BilibiliIngestError(
            "Link bangumi (phim bản quyền) không hỗ trợ — chỉ nhận video UGC (BV/av)."
        )
    page = 1
    try:
        raw_p = (parse_qs(parts.query).get("p") or ["1"])[0]
        page = max(1, int(raw_p))
    except (TypeError, ValueError):
        page = 1
    m = _BV_RE.search(parts.path) or _BV_RE.search(probe)
    if m:
        return {"bvid": m.group(1), "page": page}
    m = _AV_RE.search(parts.path)
    if m:
        return {"aid": int(m.group(1)), "page": page}
    raise BilibiliIngestError(
        f"Không tìm thấy BV/av id trong link: {url!r} — dán link dạng "
        "bilibili.com/video/BV… hoặc b23.tv/…"
    )


def parse_space_collection(url: str) -> dict | None:
    """{'mid', 'season_id'} for a space collection URL, else None.

    Accepted shapes:
      space.bilibili.com/<mid>/channel/collectiondetail?sid=<id>
      space.bilibili.com/<mid>/lists/<id>?type=season
    """
    probe = (url or "").strip()
    probe = probe if "://" in probe else f"https://{probe}"
    parts = urlsplit(probe)
    host = (parts.hostname or "").lower()
    if host != "space.bilibili.com":
        return None
    m = re.search(r"^/(\d+)", parts.path)
    if not m:
        return None
    mid = int(m.group(1))
    query = parse_qs(parts.query)
    sid = (query.get("sid") or [""])[0]
    if not sid:
        m2 = re.search(r"/lists/(\d+)", parts.path)
        if m2 and (query.get("type") or ["season"])[0] == "season":
            sid = m2.group(1)
    if not sid or not str(sid).isdigit():
        return None
    return {"mid": mid, "season_id": int(sid)}


# ── stream selection (pure, unit-tested) ────────────────────────────────────

def pick_streams(playurl_data: dict, quality_max: int = DEFAULT_QUALITY_MAX) -> dict:
    """Choose what to download from a playurl response.

    DASH: highest qn ≤ cap, avc (codecid 7) preferred over hevc/av1 — every
    consumer downstream is ffmpeg/browser-safe with avc, and re-encoding to fix
    a codec choice would cost more than the bytes saved. Audio: highest
    bandwidth. Old videos ship `durl` (one progressive file) instead.
    """
    dash = playurl_data.get("dash") or {}
    videos = [v for v in (dash.get("video") or []) if v.get("base_url")]
    if videos:
        avc = [v for v in videos if v.get("codecid") == 7] or videos
        under = [v for v in avc if int(v.get("id") or 0) <= quality_max] or avc
        video = max(under, key=lambda v: (int(v.get("id") or 0), int(v.get("bandwidth") or 0)))
        audios = [a for a in (dash.get("audio") or []) if a.get("base_url")]
        audio = max(audios, key=lambda a: int(a.get("bandwidth") or 0)) if audios else None
        return {"mode": "dash", "video": video, "audio": audio, "qn": int(video.get("id") or 0)}
    durl = [d for d in (playurl_data.get("durl") or []) if d.get("url")]
    if durl:
        first = durl[0]
        return {
            "mode": "durl",
            "url": first["url"],
            "backups": list(first.get("backup_url") or []),
            "qn": int(playurl_data.get("quality") or 0),
        }
    raise BilibiliIngestError(
        "playurl không trả stream nào — video bị khoá vùng hoặc cần đăng nhập."
    )


def entries_from_view(info: dict) -> dict:
    """Episode list hiding inside one video's view data.

    Two shapes exist: a video that BELONGS to a 合集 (ugc_season → episodes,
    each its own BV), and a multi-part video (pages → parts of one BV). The
    returned entries use the same source-id convention as `fetch_video`
    (`BV…` / `BV…_pN`), so a queued dub job later snaps onto the planned
    episode by id equality alone.
    """
    season = info.get("ugc_season") or {}
    episodes: list[dict] = []
    for section in season.get("sections") or []:
        for ep in section.get("episodes") or []:
            bvid = str(ep.get("bvid") or "")
            if not bvid:
                continue
            episodes.append({
                "sid": bvid,
                "title": str(ep.get("title") or ""),
                "url": f"https://www.bilibili.com/video/{bvid}",
            })
    if episodes:
        for i, e in enumerate(episodes, start=1):
            e["position"] = i
        return {
            "title": str(season.get("title") or info.get("title") or ""),
            "author": str((info.get("owner") or {}).get("name") or ""),
            "entries": episodes,
        }

    bvid = str(info.get("bvid") or "")
    pages = info.get("pages") or []
    if len(pages) > 1:
        entries = [{
            "sid": f"{bvid}_p{p.get('page', i)}",
            "title": str(p.get("part") or f"P{p.get('page', i)}"),
            "url": f"https://www.bilibili.com/video/{bvid}?p={p.get('page', i)}",
            "position": i,
        } for i, p in enumerate(pages, start=1)]
        return {
            "title": str(info.get("title") or ""),
            "author": str((info.get("owner") or {}).get("name") or ""),
            "entries": entries,
        }

    return {
        "title": str(info.get("title") or ""),
        "author": str((info.get("owner") or {}).get("name") or ""),
        "entries": [{
            "sid": bvid,
            "title": str(info.get("title") or ""),
            "url": f"https://www.bilibili.com/video/{bvid}",
            "position": 1,
        }],
    }


# ── HTTP plumbing ───────────────────────────────────────────────────────────

def _client(cookies: dict[str, str] | None, proxy: str, timeout: float) -> httpx.Client:
    jar = dict(cookies or {})
    if "SESSDATA" not in jar:
        env = (os.environ.get("BILIBILI_SESSDATA") or "").strip()
        if env:
            jar["SESSDATA"] = env
    return httpx.Client(
        headers={"User-Agent": _UA, "Referer": _REFERER},
        cookies=jar,
        proxy=(proxy or None),
        timeout=timeout,
        follow_redirects=True,
    )


def _get_json(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    resp = client.get(API_BASE + path, params=params)
    resp.raise_for_status()
    body = resp.json()
    code = body.get("code")
    if code != 0:
        raise BilibiliIngestError(
            f"Bilibili API {path} trả code={code}: {body.get('message') or ''}".strip()
        )
    return body.get("data") or {}


_WBI_CACHE: dict = {"ts": 0.0, "img": "", "sub": ""}
_WBI_TTL = 3600.0


def _wbi_keys(client: httpx.Client) -> tuple[str, str]:
    """img_key/sub_key of the day, from the nav API.

    NOT via _get_json: for anonymous sessions nav answers code=-101 ("not
    logged in") yet still carries wbi_img — the keys are public.
    """
    now = time.time()
    if _WBI_CACHE["img"] and now - _WBI_CACHE["ts"] < _WBI_TTL:
        return _WBI_CACHE["img"], _WBI_CACHE["sub"]
    resp = client.get(API_BASE + "/x/web-interface/nav")
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    wbi = data.get("wbi_img") or {}

    def _stem(url: str) -> str:
        name = (urlsplit(str(url or "")).path or "").rsplit("/", 1)[-1]
        return name.split(".", 1)[0]

    img, sub = _stem(wbi.get("img_url")), _stem(wbi.get("sub_url"))
    if not img or not sub:
        raise BilibiliIngestError("Không lấy được WBI key từ /x/web-interface/nav")
    _WBI_CACHE.update(ts=now, img=img, sub=sub)
    return img, sub


def _resolve_short(client: httpx.Client, url: str) -> str:
    probe = url if "://" in url else f"https://{url}"
    host = (urlsplit(probe).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _SHORT_HOSTS):
        return url
    resp = client.get(probe)  # follow_redirects=True → final URL
    return str(resp.url)


def _view(client: httpx.Client, ref: dict) -> dict:
    params = {"bvid": ref["bvid"]} if "bvid" in ref else {"aid": ref["aid"]}
    return _get_json(client, "/x/web-interface/view", params)


def _playurl(client: httpx.Client, bvid: str, cid: int, quality_max: int) -> dict:
    params = {
        "bvid": bvid, "cid": cid, "qn": quality_max,
        "fnval": 4048, "fnver": 0, "fourk": 1,
    }
    try:
        img, sub = _wbi_keys(client)
        return _get_json(client, "/x/player/wbi/playurl", sign_params(params, img, sub))
    except BilibiliIngestError:
        # Legacy unsigned endpoint still answers for most UGC; losing quality
        # options beats failing the whole download on a signing hiccup.
        return _get_json(client, "/x/player/playurl", params)


def _download(client: httpx.Client, url: str, dest: Path, *, backups: list[str] | None = None,
              attempts: int = 3) -> Path:
    last: Exception | None = None
    for candidate in [url, *(backups or [])]:
        for attempt in range(attempts):
            try:
                tmp = dest.with_name(dest.name + ".part")
                with client.stream("GET", candidate) as resp:
                    resp.raise_for_status()
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_bytes(1 << 16):
                            fh.write(chunk)
                if tmp.stat().st_size == 0:
                    raise BilibiliIngestError("CDN trả file 0 byte")
                os.replace(tmp, dest)
                return dest
            except Exception as exc:  # noqa: BLE001 — retry across mirrors
                last = exc
                time.sleep(1.5 * (attempt + 1))
    raise BilibiliIngestError(f"Tải stream thất bại sau mọi mirror: {last}")


def _mux(video: Path, audio: Path | None, out: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise BilibiliIngestError("ffmpeg không có trên PATH — cần để ghép DASH m4s")
    args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video)]
    if audio is not None:
        args += ["-i", str(audio)]
    args += ["-c", "copy", "-movflags", "+faststart", str(out)]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0 or not out.is_file():
        raise BilibiliIngestError(f"ffmpeg mux lỗi: {(proc.stderr or '')[-300:]}")
    return out


# ── public API ──────────────────────────────────────────────────────────────

def fetch_video(url: str, settings: BilibiliIngestConfig) -> BilibiliAsset:
    """Download one bilibili video (or one part of a multi-part video)."""
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    with _client(settings.cookies, settings.proxy, settings.timeout) as client:
        real_url = _resolve_short(client, url)
        ref = parse_video_ref(real_url)
        info = _view(client, ref)

        bvid = str(info.get("bvid") or "")
        if not bvid:
            raise BilibiliIngestError("view API không trả bvid — video bị gỡ hoặc private?")
        pages = info.get("pages") or []
        page_no = int(ref.get("page") or 1)
        multi = len(pages) > 1
        if multi and page_no > len(pages):
            raise BilibiliIngestError(
                f"Video chỉ có {len(pages)} phần, link đòi p={page_no}"
            )
        page = pages[page_no - 1] if pages else {"cid": info.get("cid"), "part": ""}
        cid = int(page.get("cid") or info.get("cid") or 0)
        if not cid:
            raise BilibiliIngestError("Không lấy được cid của video")

        source_id = f"{bvid}_p{page_no}" if multi else bvid
        part_name = str(page.get("part") or "")
        title = f"{info.get('title') or ''} {part_name}".strip() if multi else str(info.get("title") or "")
        author = str((info.get("owner") or {}).get("name") or "")
        pubdate = info.get("pubdate")

        save_dir = settings.output_dir / source_id
        save_dir.mkdir(parents=True, exist_ok=True)
        final_mp4 = save_dir / f"{source_id}.mp4"

        quality = 0
        if final_mp4.is_file() and final_mp4.stat().st_size > 0:
            # Same idea as the douyin manifest cache: a re-queued job must not
            # pull hundreds of MB it already has.
            pass
        else:
            play = _playurl(client, bvid, cid, settings.quality_max)
            chosen = pick_streams(play, settings.quality_max)
            quality = int(chosen.get("qn") or 0)
            if chosen["mode"] == "dash":
                v_path = _download(
                    client, chosen["video"]["base_url"], save_dir / "video.m4s",
                    backups=list(chosen["video"].get("backup_url") or []),
                )
                a_path = None
                if chosen.get("audio"):
                    a_path = _download(
                        client, chosen["audio"]["base_url"], save_dir / "audio.m4s",
                        backups=list(chosen["audio"].get("backup_url") or []),
                    )
                _mux(v_path, a_path, final_mp4)
                for scratch in (v_path, a_path):
                    if scratch is not None:
                        try:
                            scratch.unlink()
                        except OSError:
                            pass
            else:
                raw = _download(
                    client, chosen["url"], save_dir / "progressive.bin",
                    backups=list(chosen.get("backups") or []),
                )
                # Remux whatever container the CDN handed over (flv/mp4) into
                # a clean mp4 so every downstream ffprobe sees one shape.
                _mux(raw, None, final_mp4)
                try:
                    raw.unlink()
                except OSError:
                    pass

        cover_path: Path | None = None
        pic = str(info.get("pic") or "")
        if pic:
            try:
                cover_path = _download(client, pic, save_dir / "cover.jpg")
            except Exception:
                cover_path = None  # cover là phụ, không chặn job

        tags = [t for t in [str(info.get("tname") or "")] if t]
        return BilibiliAsset(
            aweme_id=source_id,
            source_url=real_url if "://" in str(real_url) else url,
            video_path=final_mp4,
            title=title or source_id,
            author_name=author,
            tags=tags,
            create_time=int(pubdate) if pubdate else None,
            publish_date=time.strftime("%Y-%m-%d", time.localtime(int(pubdate))) if pubdate else "",
            save_dir=save_dir,
            cover_path=cover_path,
            bvid=bvid,
            cid=cid,
            page=page_no,
            quality=quality,
        )


# The douyin facade exposes fetch_video_sync; keep the twin name so call sites
# read the same regardless of platform.
fetch_video_sync = fetch_video


def fetch_series_entries(
    url: str, *,
    cookies: dict[str, str] | None = None,
    proxy: str = "",
    timeout: float = 30.0,
    max_entries: int = 2000,
) -> dict:
    """{'title','author','entries':[{sid,title,url,position}]} for a bilibili series.

    Accepts: a video of a 合集 (season episodes), a multi-part video (分P),
    a plain single video, or a space collection URL. Listing only — nothing
    is downloaded.
    """
    with _client(cookies, proxy, timeout) as client:
        real_url = _resolve_short(client, url)
        space = parse_space_collection(real_url)
        if space:
            entries: list[dict] = []
            season_name, author = "", ""
            page_num = 1
            while len(entries) < max_entries:
                params = {
                    "mid": space["mid"], "season_id": space["season_id"],
                    "page_num": page_num, "page_size": 30, "sort_reverse": "false",
                }
                try:
                    img, sub = _wbi_keys(client)
                    data = _get_json(
                        client, "/x/polymer/web-space/seasons_archives_list",
                        sign_params(params, img, sub),
                    )
                except BilibiliIngestError:
                    data = _get_json(
                        client, "/x/polymer/web-space/seasons_archives_list", params
                    )
                archives = data.get("archives") or []
                meta = data.get("meta") or {}
                season_name = season_name or str(meta.get("name") or "")
                for arc in archives:
                    bvid = str(arc.get("bvid") or "")
                    if bvid:
                        entries.append({
                            "sid": bvid,
                            "title": str(arc.get("title") or ""),
                            "url": f"https://www.bilibili.com/video/{bvid}",
                        })
                total = int((data.get("page") or {}).get("total") or 0)
                if not archives or (total and len(entries) >= total):
                    break
                page_num += 1
            for i, e in enumerate(entries, start=1):
                e["position"] = i
            return {"title": season_name, "author": author, "entries": entries}

        ref = parse_video_ref(real_url)
        info = _view(client, ref)
        return entries_from_view(info)
