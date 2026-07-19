"""Learn from competitors' breakout videos — HOW winners name titles and design
thumbnails — and distill reusable playbooks per niche.

Pipeline:
  1. Scan the channel's competitor handles (reuse YouTubeScanner) → recent videos.
  2. Take the top-N by views (the proven winners).
  3. title_playbook  ← DeepSeek distills title formulas / power-words / structure.
  4. thumbnail_playbook ← Gemini vision reads the top thumbnails → common visual recipe.
  5. Persist to vault.competitor_intel (keyed by niche) → fed into the title +
     thumbnail generators (clickbait.py).

Best-effort: needs youtube_api_key + competitor handles + (vision) GOOGLE_API_KEY.
Skips gracefully when missing.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()

_TITLE_SYS = (
    "You are a YouTube title strategist. Given real high-performing competitor "
    "titles in a niche, distill a concise PLAYBOOK another creator can copy: the "
    "recurring formulas, power words, emotional triggers, number/bracket usage, "
    "ideal length, and 3 fill-in-the-blank title templates. Be specific and terse "
    "(<=180 words). Output plain text, no preamble."
)
_SCRIPT_SYS = (
    "You are a YouTube retention strategist. From real transcripts of high-"
    "performing competitor videos in a niche, reverse-engineer a SCRIPT PLAYBOOK "
    "a creator can copy:\n"
    "1. HOOK — the first-15-seconds formula (what they open with: stat/question/"
    "pain/promise); give the pattern, not the exact words.\n"
    "2. STRUCTURE — how the video is segmented (problem→stakes→proof→payoff→CTA), "
    "typical # of beats, where open-loops are planted.\n"
    "3. PACING — sentence length, how often a new idea/number lands, energy shifts.\n"
    "4. RETENTION TACTICS — open loops, pattern interrupts, re-hooks, CTA placement.\n"
    "5. TONE & LANGUAGE — vocabulary level, direct-address, recurring phrasings.\n"
    "End with a copyable 5-beat outline template. Specific + terse (<=220 words). "
    "Plain text, no preamble."
)
_THUMB_SYS = (
    "You are a senior YouTube thumbnail art director reverse-engineering a CTR "
    "playbook from high-performing competitor thumbnails. Distill a concise, "
    "copyable PLAYBOOK across 5 layers:\n"
    "1. FOCAL POINT — what grabs the eye first (face/expression, object, big text)?\n"
    "2. LAYOUT & COMPOSITION — rule-of-thirds/symmetry/size-contrast; elements placed "
    "so the bottom-right timestamp never covers them.\n"
    "3. COLOR & CONTRAST — dominant palette + accent (e.g. dark navy bg + neon-yellow "
    "text); strong enough to pop on YouTube dark mode?\n"
    "4. CTR PSYCHOLOGY — emotion triggered (fear/curiosity/greed/shock) + how it pairs "
    "with the title to form a curiosity loop.\n"
    "5. TYPOGRAPHY — word count, font class (bold sans/serif), color+outline, mobile size.\n"
    "End with 3 fill-in-the-blank thumbnail RECIPES to copy. Specific + terse "
    "(<=220 words). Plain text, no preamble."
)


async def _top_competitor_videos(channel, api_key: str, top_n: int = 12) -> list[dict]:
    """Reuse YouTubeScanner to fetch competitor videos, return top-N by views."""
    from omnicast.discovery.youtube_scanner import YouTubeScanner
    scanner = YouTubeScanner(config=channel, api_key=api_key)
    ids = list(getattr(channel, "competitor_channel_ids", []) or [])
    for handle in getattr(channel, "competitor_handles", []) or []:
        try:
            ids.append(await scanner._resolve_handle(handle))
        except Exception:
            pass
    vids: list[dict] = []
    for cid in ids:
        try:
            pl = await scanner._get_channel_uploads_playlist_id(cid)
            vid_ids = await scanner._get_recent_video_ids(pl, max_results=30)
            vids.extend(await scanner._get_video_stats(vid_ids))
        except Exception as exc:
            logger.warning("competitor scan failed", channel=cid, error=str(exc))
    vids.sort(key=lambda v: v.get("views", 0), reverse=True)
    return vids[:top_n]


async def _learn_titles(llm, titles: list[str]) -> str:
    if not titles:
        return ""
    user = "High-performing titles:\n" + "\n".join(f"- {t}" for t in titles)
    try:
        resp = await llm.complete(system=_TITLE_SYS,
                                  messages=[{"role": "user", "content": user}],
                                  max_tokens=600, temperature=0.4)
        return (resp.content or "").strip()
    except Exception as exc:
        logger.warning("title playbook failed", error=str(exc))
        return ""


def _fetch_thumbs(thumb_urls: list[str], limit: int = 8) -> list[bytes]:
    import urllib.request
    out = []
    for u in [x for x in thumb_urls if x][:limit]:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                out.append(r.read())
        except Exception:
            continue
    return out


def _learn_thumbnails(thumb_urls: list[str], google_key: str = "",
                      claude_key: str = "", claude_model: str = "claude-sonnet-5") -> str:
    """Vision analysis of top competitor thumbnails → CTR design playbook.
    Prefers Gemini 2.5-flash (cheap), falls back to Claude vision. '' if no key/images."""
    if not (claude_key or google_key):
        return ""
    imgs = _fetch_thumbs(thumb_urls)
    if not imgs:
        return ""

    # 1) Gemini 2.5-flash (cheap, default).
    if google_key:
        try:
            from google import genai
            from google.genai import types
            parts = [types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in imgs]
            client = genai.Client(api_key=google_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash", contents=[*parts, _THUMB_SYS])
            txt = (resp.candidates[0].content.parts[0].text or "").strip()
            if txt:
                logger.info("thumbnail playbook via Gemini", n=len(imgs))
                return txt
        except Exception as exc:
            logger.warning("gemini thumbnail analysis failed", error=str(exc))

    # 2) Claude vision fallback (when no Google key).
    if claude_key:
        try:
            import base64
            import anthropic
            blocks = [{"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(b).decode()}} for b in imgs]
            blocks.append({"type": "text",
                           "text": "Analyze these competitor thumbnails per your brief."})
            client = anthropic.Anthropic(api_key=claude_key)
            msg = client.messages.create(
                model=claude_model, max_tokens=900, system=_THUMB_SYS,
                messages=[{"role": "user", "content": blocks}])
            txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
            if txt:
                logger.info("thumbnail playbook via Claude", n=len(imgs))
                return txt
        except Exception as exc:
            logger.warning("claude thumbnail analysis failed", error=str(exc))
    return ""


def _fetch_transcript(video_id: str, max_chars: int = 3500) -> str:
    """Fetch a video's transcript (first ~max_chars). '' if none/unavailable."""
    if not video_id:
        return ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        try:
            fetched = api.fetch(video_id, languages=["en", "en-US"])
        except TypeError:
            fetched = api.fetch(video_id)
        parts = []
        for s in fetched:
            t = getattr(s, "text", None) or (s.get("text") if isinstance(s, dict) else "")
            if t:
                parts.append(t)
        return " ".join(parts)[:max_chars]
    except Exception:
        return ""


async def _learn_scripts(llm, vids: list[dict], top_n: int = 5) -> str:
    """Distill a script/hook/structure playbook from competitor transcripts."""
    samples = []
    for v in vids[:top_n]:
        t = _fetch_transcript(v.get("video_id", ""))
        if t:
            samples.append(f"### {v.get('title','(untitled)')}\n{t}")
        if len(samples) >= 4:
            break
    if not samples:
        return ""
    user = "Competitor video transcripts (truncated):\n\n" + "\n\n".join(samples)
    try:
        resp = await llm.complete(system=_SCRIPT_SYS,
                                  messages=[{"role": "user", "content": user[:14000]}],
                                  max_tokens=700, temperature=0.4)
        return (resp.content or "").strip()
    except Exception as exc:
        logger.warning("script playbook failed", error=str(exc))
        return ""


async def learn_for_channel(channel, niche_key: str) -> dict | None:
    """Distill + persist competitor title/thumbnail playbooks for a niche.
    Returns a summary dict, or None if nothing learnable."""
    from omnicast.config.settings import get_settings
    from omnicast.capabilities.llm_factory import create_llm
    from omnicast.vault import db as vault_db
    from omnicast.vault.models import CompetitorIntel

    s = get_settings()
    api_key = s.youtube_api_key
    if not api_key:
        return None
    vids = await _top_competitor_videos(channel, api_key)
    if not vids:
        return None
    titles = [v.get("title", "") for v in vids if v.get("title")]
    thumbs = [v.get("thumbnail_url", "") for v in vids]

    llm = create_llm(default_provider="deepseek", model=s.deepseek_flash_model)
    title_pb = await _learn_titles(llm, titles)
    thumb_pb = _learn_thumbnails(thumbs, google_key=s.google_api_key,
                                 claude_key=s.claude_api_key,
                                 claude_model=s.claude_model)
    script_pb = await _learn_scripts(llm, vids)
    if not title_pb and not thumb_pb and not script_pb:
        return None

    from pathlib import Path
    VAULT_DB = Path(__file__).resolve().parents[3] / "output" / "vault.db"
    vault_db.init_db(VAULT_DB)
    vault_db.upsert_competitor_intel(CompetitorIntel(
        niche=niche_key, title_playbook=title_pb, thumbnail_playbook=thumb_pb,
        script_playbook=script_pb, sample_titles=titles[:15], sample_count=len(vids),
        updated_at=datetime.now(timezone.utc).isoformat(),
    ), VAULT_DB)
    logger.info("competitor intel learned", niche=niche_key, samples=len(vids),
                has_title=bool(title_pb), has_thumb=bool(thumb_pb), has_script=bool(script_pb))
    return {"niche": niche_key, "samples": len(vids),
            "title_playbook": bool(title_pb), "thumbnail_playbook": bool(thumb_pb),
            "script_playbook": bool(script_pb)}
