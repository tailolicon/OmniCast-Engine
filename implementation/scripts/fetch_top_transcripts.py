# -*- coding: utf-8 -*-
"""Fetch top-video transcripts for the 7 senior_wealth_us competitor channels.

Per channel: top 4 all-time by views + top 3 from the last 18 months (dedup),
long-form only (>= 6 min). Saved as JSON + TXT under
implementation/output/competitor_scripts/senior_wealth_us/ (gitignored).
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, r"E:\Project\OmniCast Engine\implementation\src")
from omnicast.config.settings import get_settings  # noqa: E402
from omnicast.analytics.transcript import fetch_transcript  # noqa: E402

HANDLES = [
    "@HolySchmidt",
    "@DevinCarroll",
    "@foundryfinancial",
    "@RootFP",
    "@AzulWells",
    "@joekuhnlovesretirement",
    "@rob_berger",
]
OUT = Path(r"E:\Project\OmniCast Engine\implementation\output\competitor_scripts\senior_wealth_us")
OUT.mkdir(parents=True, exist_ok=True)
API = "https://www.googleapis.com/youtube/v3"
KEY = get_settings().youtube_api_key
MIN_MINUTES = 6.0
RECENT_CUTOFF = "2025-02-01T00:00:00Z"  # ~18 months back from 2026-08


def yt(path: str, **params):
    params.update(key=KEY)
    r = httpx.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def iso_minutes(dur: str) -> float:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0.0
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 60 + mi + s / 60


def top_videos(channel_id: str, published_after: str | None, want: int) -> list[dict]:
    params = dict(
        part="id", channelId=channel_id, type="video", order="viewCount",
        maxResults=25,
    )
    if published_after:
        params["publishedAfter"] = published_after
    ids = [i["id"]["videoId"] for i in yt("search", **params).get("items", [])]
    if not ids:
        return []
    rows = yt(
        "videos", part="snippet,statistics,contentDetails", id=",".join(ids)
    ).get("items", [])
    out = []
    for v in rows:
        minutes = iso_minutes(v["contentDetails"]["duration"])
        if minutes < MIN_MINUTES:
            continue
        out.append({
            "video_id": v["id"],
            "title": v["snippet"]["title"],
            "published": v["snippet"]["publishedAt"],
            "views": int(v["statistics"].get("viewCount", 0)),
            "minutes": round(minutes, 1),
        })
    out.sort(key=lambda r: -r["views"])
    return out[:want]


def main():
    manifest = []
    for handle in HANDLES:
        ch = yt("channels", part="id,snippet,statistics", forHandle=handle.lstrip("@"))
        items = ch.get("items", [])
        if not items:
            print(f"!! {handle}: channel not found")
            continue
        cid = items[0]["id"]
        subs = items[0]["statistics"].get("subscriberCount", "?")
        picks = top_videos(cid, None, 4)
        seen = {p["video_id"] for p in picks}
        for r in top_videos(cid, RECENT_CUTOFF, 6):
            if r["video_id"] not in seen and len(picks) < 7:
                picks.append(r)
                seen.add(r["video_id"])
        print(f"== {handle} ({subs} subs): {len(picks)} videos")
        for p in picks:
            slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower())[:60].strip("-")
            base = OUT / f"{handle.lstrip('@')}__{p['video_id']}"
            txt_path = base.with_suffix(".txt")
            if txt_path.exists() and txt_path.stat().st_size > 500:
                print(f"   skip (cached) {p['title'][:60]}")
                p.update(handle=handle, ok=True, note="cached")
                manifest.append(p)
                continue
            t = fetch_transcript(p["video_id"], duration_minutes=p["minutes"])
            p.update(handle=handle, ok=t.ok, note=t.note, slug=slug)
            if t.ok:
                txt_path.write_text(t.text, encoding="utf-8")
                base.with_suffix(".json").write_text(
                    json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
                wpm = len(t.text.split()) / p["minutes"] if p["minutes"] else 0
                print(f"   ok   {p['title'][:60]}  ({p['views']:,} views, {p['minutes']}m, {wpm:.0f} wpm)")
            else:
                print(f"   FAIL {p['title'][:60]}  ({t.note})")
            manifest.append(p)
            time.sleep(0.5)
    (OUT / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for m in manifest if m.get("ok"))
    print(f"\nDONE: {ok}/{len(manifest)} transcripts -> {OUT}")


if __name__ == "__main__":
    main()
