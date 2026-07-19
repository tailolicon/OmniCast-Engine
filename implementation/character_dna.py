"""Character DNA — lock a recurring channel mascot's look across every shot.

Pattern from wind-comic: a model interprets the SAME reference image differently
per prompt, so the protagonist's face drifts. Fix = a compact, structured
natural-language "DNA block" (8 fields: eyes/jaw/nose/mouth/hair style+color/
skin/signature outfit) injected into EVERY scene image prompt — a text anchor
that holds the identity even without true image-reference conditioning.

Two ways to get the DNA:
  • Manual / channel-defined: a `character` dict in channels/<id>.json.
  • Auto-extract from a portrait via Gemini vision (if GOOGLE_API_KEY set).

Free + cached: extract once per mascot, reuse the block in all prompts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_CACHE_DIR = ROOT / "output" / "_characters"
_FIELDS = ["eyeShape", "jawShape", "noseShape", "mouthShape",
           "hairStyle", "hairColor", "skinTone", "signatureOutfit"]


def build_dna_block(character: dict) -> str:
    """Compose a compact (~1 line) DNA prompt block from a character dict.

    character: {name, eyeShape, jawShape, noseShape, mouthShape, hairStyle,
    hairColor, skinTone, signatureOutfit} (any subset) OR {name, description}.
    """
    if not character:
        return ""
    name = character.get("name") or "the recurring character"
    if character.get("description") and not any(character.get(f) for f in _FIELDS):
        return f"SAME recurring character {name}: {character['description'].strip()}"
    parts = []
    label = {
        "eyeShape": "eyes", "jawShape": "jaw", "noseShape": "nose",
        "mouthShape": "mouth", "hairStyle": "hair", "hairColor": "hair color",
        "skinTone": "skin", "signatureOutfit": "signature outfit",
    }
    for f in _FIELDS:
        v = (character.get(f) or "").strip()
        if v:
            parts.append(f"{label[f]} {v}")
    if not parts:
        return ""
    return (f"SAME recurring character {name} (keep identical in every shot): "
            + ", ".join(parts))


def _cache_path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:60]
    return _CACHE_DIR / f"{safe}.json"


def extract_dna_from_image(image_path: str, name: str = "") -> dict | None:
    """Vision-extract the 8-field DNA from a portrait via Gemini. Cached by
    image path. Returns None if no GOOGLE_API_KEY or extraction fails."""
    src = ROOT / "src"
    import sys
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    cache = _cache_path(image_path)
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        from omnicast.config.settings import get_settings
        s = get_settings()
        if not s.google_api_key:
            return None
        import base64
        from google import genai
        from google.genai import types

        img = Path(image_path).read_bytes()
        client = genai.Client(api_key=s.google_api_key)
        prompt = (
            "You are a character-identity extractor for AI video. From this "
            "portrait, output ONLY JSON with these exact keys, each a short "
            "phrase: eyeShape, jawShape, noseShape, mouthShape, hairStyle, "
            "hairColor, skinTone, signatureOutfit. No extra text."
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_bytes(data=img, mime_type="image/png"), prompt],
        )
        txt = resp.candidates[0].content.parts[0].text
        import re
        m = re.search(r"\{[\s\S]*\}", txt)
        data = json.loads(m.group(0) if m else txt)
        data["name"] = name or data.get("name", "mascot")
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
    except Exception as exc:
        print(f"      [warn] character DNA vision extract failed: {exc}")
        return None


def resolve_character(channel: dict | None) -> dict | None:
    """Get a character dict for a channel: explicit `character` block wins; else
    if `character_portrait` path set, vision-extract (cached); else None."""
    if not channel:
        return None
    char = channel.get("character")
    if isinstance(char, dict) and char:
        return char
    portrait = channel.get("character_portrait")
    if portrait and Path(portrait).exists():
        return extract_dna_from_image(portrait, channel.get("name", "mascot"))
    return None
