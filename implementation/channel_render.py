"""Per-channel render style resolver.

Maps a channel config (channels/<id>.json) to render parameters so each channel
produces videos in its OWN look: art style, narration voice, subtitle vs title
overlay, shot pacing, and motion. An explicit ``render`` block in the channel
JSON always wins; otherwise params are derived from visual_style / tone / niche.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNELS_DIR = ROOT / "channels"

# visual_style (channel JSON) -> STYLE_PREFIXES key in render_real_video.
_STYLE_MAP = {
    "documentary": "documentary",
    "watercolor": "watercolor",
    "storybook": "watercolor",
    "cinematic": "editorial",
    "editorial": "editorial",
    "finance": "dark_finance",
    "news": "dark_finance",
    "clean_educational": "clean_educational",
    "vibrant_3d": "vibrant_3d",
    "whiteboard": "whiteboard_sketch",
}

# voice_profile substring -> edge-tts voice. Multilingual neural voices are the
# most natural (HD prosody) — prefer them over the older *Neural voices.
_VOICE_MAP = [
    ("deep", "en-US-AndrewMultilingualNeural"),
    ("calm", "en-US-BrianMultilingualNeural"),
    ("warm", "en-US-BrianMultilingualNeural"),
    ("female", "en-US-AvaMultilingualNeural"),
    ("aria", "en-US-AvaMultilingualNeural"),
    ("authoritative", "en-US-AndrewMultilingualNeural"),
]

# Niches that read better as narration-only (subtitles, no presenter).
_SUBTITLE_NICHES = {"mythology", "history", "myth", "legend", "religion"}

# Thumbnail accent colour per style (key word colour on the thumbnail).
_ACCENT = {
    "editorial": [255, 209, 71],     # gold
    "dark_finance": [255, 209, 71],  # gold
    "watercolor": [222, 120, 50],    # burnt orange
    "documentary": [232, 72, 72],    # red
    "found_photo": [200, 30, 30],    # blood red (horror)
}


def _derive(channel: dict) -> dict:
    vstyle = (channel.get("visual_style") or "").lower()
    style = _STYLE_MAP.get(vstyle)
    # Horror channels: every generated image must read as a REAL amateur photo
    # (found-footage look) — the illustration styles kill the scares.
    if (channel.get("channel_style") or "").lower() == "horror_real":
        style = "found_photo"
    if not style:
        niche = (channel.get("niche") or "").lower()
        style = "watercolor" if niche in _SUBTITLE_NICHES else "editorial"

    vp = (channel.get("voice_profile") or "").lower() + (channel.get("brand_voice") or "").lower()
    voice = next((v for key, v in _VOICE_MAP if key in vp), "en-US-AndrewMultilingualNeural")

    niche = (channel.get("niche") or "").lower()
    subtitle = niche in _SUBTITLE_NICHES or style in ("watercolor", "documentary")

    return {
        "style": style,
        "voice": voice,
        "subtitle": subtitle,
        "beat_words": 18,
        "motion": "kenburns",
        "accent": _ACCENT.get(style, [255, 209, 71]),
    }


def resolve(channel_id: str) -> dict:
    """Return render params for a channel: {style, voice, subtitle, beat_words, motion}.

    Raises FileNotFoundError if the channel config is missing.
    """
    path = CHANNELS_DIR / f"{channel_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Channel config not found: {path}")
    channel = json.loads(path.read_text(encoding="utf-8"))
    params = _derive(channel)
    # Explicit overrides win.
    override = channel.get("render") or {}
    params.update({k: v for k, v in override.items() if v is not None})
    params["channel_name"] = channel.get("name", channel_id)
    return params


if __name__ == "__main__":  # quick manual check: python channel_render.py
    import sys
    for cid in (sys.argv[1:] or [p.stem for p in CHANNELS_DIR.glob("*.json")]):
        try:
            print(cid, "->", resolve(cid))
        except Exception as exc:
            print(cid, "ERR", exc)
