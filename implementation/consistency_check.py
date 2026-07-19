"""Character consistency QA — verify generated scene stills against the channel
mascot's DNA BEFORE they enter the video.

Pattern ported from Orkas-VideoStudio's stage-consistency skill (MIT): catch
identity drift at the STILL — re-rolling a cheap image (Flow image gen is free)
is far cheaper than discovering the drift after composing/animating. Rules kept
from the source skill:

  - verify against the DNA identity axes (face/hair/build/outfit), not vibes;
  - re-roll the image, bounded, never the downstream work;
  - NEVER hard-fail the render — keep the best candidate and note the
    shortcoming (a drifted mascot beats no video in a 24/7 pipeline);
  - cache verdicts by content hash so a resumed run re-verifies nothing.

Uses the same Gemini vision access as character_dna.py; silently no-ops when
GOOGLE_API_KEY is absent.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
_VERIFY_CACHE = ROOT / "output" / "_characters" / "_verify"

# Bounds: verification is an LLM-vision call per image; re-rolls spend provider
# quota. Caps keep a long video from turning QA into its own cost center.
MAX_CHECKS_DEFAULT = 16
MAX_REROLLS_DEFAULT = 4


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_path(image_path: Path, dna_block: str) -> Path | None:
    try:
        key = _sha(image_path.read_bytes() + dna_block.encode("utf-8"))
        return _VERIFY_CACHE / f"{key[:40]}.json"
    except Exception:
        return None


def verify_image(image_path: Path, dna_block: str) -> dict | None:
    """Vision-check one still against the DNA block.

    Returns {"match": bool, "reason": str} or None when unverifiable (no API
    key / API error) — the caller treats None as "unverified", never as a fail.
    Verdicts are cached by (image bytes + DNA) hash.
    """
    cp = _cache_path(image_path, dna_block)
    if cp and cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass
    import sys
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from omnicast.config.settings import get_settings
        s = get_settings()
        if not s.google_api_key:
            return None
        from google import genai
        from google.genai import types

        img = image_path.read_bytes()
        client = genai.Client(api_key=s.google_api_key)
        prompt = (
            "You are a character-identity QA checker for AI video. The video's "
            f"recurring character is defined as: \"{dna_block}\".\n"
            "Check the image against the IDENTITY axes only (gender, age range, "
            "facial features, hair style+color, body shape, signature outfit). "
            "Ignore pose, expression, lighting, background, art-style rendering "
            "differences. If the image shows NO humanoid character at all, that "
            "is a match (nothing contradicts the identity).\n"
            "Output ONLY JSON: {\"match\": true|false, \"reason\": \"<short>\"}"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_bytes(data=img, mime_type="image/png"), prompt],
        )
        txt = resp.candidates[0].content.parts[0].text
        m = re.search(r"\{[\s\S]*\}", txt)
        data = json.loads(m.group(0) if m else txt)
        verdict = {"match": bool(data.get("match")),
                   "reason": str(data.get("reason", ""))[:200]}
        if cp:
            _VERIFY_CACHE.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
        return verdict
    except Exception as exc:
        print(f"      [warn] consistency verify failed for "
              f"{image_path.name}: {str(exc)[:80]}")
        return None


def verify_scenes(
    scene_images: dict[int, Path],
    dna_block: str,
    *,
    regen: Callable[[int, Path], bool] | None = None,
    max_checks: int = MAX_CHECKS_DEFAULT,
    max_rerolls: int = MAX_REROLLS_DEFAULT,
) -> dict:
    """Verify generated scene stills against the mascot DNA; re-roll drifted ones.

    scene_images: scene index -> generated PNG path (only GENERATED shots — web
    photos/stock frames are not the mascot and must not be checked).
    regen(i, path) -> bool: caller-supplied re-generator (same prompt, fresh
    roll, must also refresh the caller's prompt-cache). None = verify-only.

    Returns {"checked", "passed", "rerolled": [i], "drifted": [i],
    "unverified": [i]} — "drifted" shots stay in the video (never hard-fail),
    they are surfaced for the operator/status instead.
    """
    out = {"checked": 0, "passed": 0, "rerolled": [], "drifted": [],
           "unverified": []}
    if not dna_block or not scene_images:
        return out
    rerolls_left = max_rerolls
    consecutive_errors = 0
    for i in sorted(scene_images)[:max_checks]:
        img = scene_images[i]
        if not img.exists():
            continue
        v = verify_image(img, dna_block)
        if v is None:
            out["unverified"].append(i)
            consecutive_errors += 1
            if consecutive_errors >= 2:
                # Vision API down/keyless — stop burning calls; rest unverified.
                out["unverified"] += [j for j in sorted(scene_images)[:max_checks]
                                      if j > i]
                break
            continue
        consecutive_errors = 0
        out["checked"] += 1
        if v["match"]:
            out["passed"] += 1
            continue
        print(f"      [consistency] scene {i}: identity drift — {v['reason']}")
        if regen is None or rerolls_left <= 0:
            out["drifted"].append(i)
            continue
        rerolls_left -= 1
        ok = False
        try:
            ok = bool(regen(i, img))
        except Exception as exc:
            print(f"      [consistency] re-roll error scene {i}: {str(exc)[:80]}")
        v2 = verify_image(img, dna_block) if ok else None
        if v2 and v2["match"]:
            out["rerolled"].append(i)
            out["passed"] += 1
            print(f"      [consistency] scene {i}: re-roll fixed the drift")
        else:
            # Keep the best we have and note the shortcoming (never hard-fail).
            out["drifted"].append(i)
            if v2:
                print(f"      [consistency] scene {i}: still drifted after "
                      f"re-roll — {v2['reason']} (keeping)")
    return out
