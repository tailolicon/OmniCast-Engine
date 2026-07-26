"""Channel-style policies — per-channel visual sourcing strategy.

A channel's `channel_style` (channels/<id>.json) decides WHERE its visuals come
from, independent of the art style (`visual_style`/STYLE_PRESETS):

  - footage:      real stock B-roll dominates (documentary look). AI art = last resort.
  - storytelling: AI-generated illustrations dominate (one continuous illustrated
                  world, Flow/Imagen). Real web photos break immersion -> banned.
  - horror_real:  ONLY real imagery (stock footage, real photos, archival/CCTV
                  vibe). AI art is BANNED — coerced to real footage.
  - auto:         legacy behavior — storyboard LLM decides freely (default).

The policy acts at two points in render_real_video.py:
  1. `storyboard_directive` is appended to the storyboard system prompt (bias).
  2. `enforce_policy()` coerces any banned visual_type the LLM still emitted
     (hard guarantee — same pattern as the existing stat->stock coercion).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VISUAL_TYPES = ("stock_video", "generated_image", "web_search_image", "web_screenshot")


@dataclass(frozen=True)
class ChannelStylePolicy:
    style_id: str
    label: str
    allowed_types: tuple[str, ...]
    preferred_type: str  # coercion target when a banned type appears
    storyboard_directive: str
    requires_image_provider: bool = False
    default_image_provider: str | None = None
    # Hard cap on the share of stock_video cells (None = no cap). The storyboard
    # LLM ignores the appended directive when the base prompt's footage bias is
    # stronger (measured: storytelling board came back ~100% stock) — so the
    # ratio is ENFORCED deterministically in enforce_policy, not requested.
    stock_max_ratio: float | None = None


# Stock cells worth KEEPING on an illustrated channel: neutral atmosphere
# cutaways that don't break the painted world (never people/places with faces).
_ATMOSPHERE_RE = re.compile(
    r"\b(sky|cloud|rain|storm|lightning|fog|mist|ocean|sea|wave|fire|flame|"
    r"ember|candle|smoke|forest|tree|leaves|snow|wind|moon|stars?|night sky|"
    r"sunrise|sunset|river|waterfall)\b", re.I)


_FOOTAGE = ChannelStylePolicy(
    style_id="footage",
    label="Real footage / documentary",
    allowed_types=VISUAL_TYPES,  # gen image stays a last resort (base prompt caps it)
    preferred_type="stock_video",
    storyboard_directive=(
        "\n\nCHANNEL STYLE — FOOTAGE (OVERRIDES ANY CONFLICTING RATIO ABOVE):\n"
        "This channel is a real-footage documentary channel. 90%+ of scenes MUST be "
        "'stock_video' with concrete filmable queries. Use 'web_search_image' only for "
        "authority moments (real product/study/headline). 'generated_image' is allowed "
        "on AT MOST 1-2 scenes in the whole video, only for a pure abstract metaphor."
    ),
)

_STORYTELLING = ChannelStylePolicy(
    style_id="storytelling",
    label="Illustrated storytelling (AI images)",
    allowed_types=("generated_image", "stock_video"),
    preferred_type="generated_image",
    requires_image_provider=True,
    default_image_provider="flow",
    stock_max_ratio=0.15,
    storyboard_directive=(
        "\n\nCHANNEL STYLE — STORYTELLING (OVERRIDES CRITICAL #1 AND #1d ABOVE):\n"
        "This channel tells narrated stories over a CONTINUOUS ILLUSTRATED WORLD. "
        "Invert the bias: 85-95% of scenes MUST be 'generated_image' — one consistent "
        "painted/cinematic illustration style, same characters, same world, coherent "
        "lighting across every scene (like an animated audiobook). Write rich "
        "image_prompt: subject, setting, composition, lighting, mood, era. "
        "'stock_video' is allowed ONLY for neutral atmosphere cutaways (sky, rain, "
        "fire, ocean — never people). NEVER use 'web_search_image' or 'web_screenshot' "
        "— real photos shatter the illustrated world. Charts/text rules still apply."
    ),
)

_HORROR_REAL = ChannelStylePolicy(
    style_id="horror_real",
    label="Creepy/horror — real look (photoreal scare stills allowed)",
    allowed_types=("stock_video", "generated_image", "web_search_image", "web_screenshot"),
    preferred_type="stock_video",
    requires_image_provider=True,
    # Flow (browser session, Google AI Pro subscription) — per-image API billing
    # is banned by the operator; Flow output also reads MORE found-footage
    # (adds camcorder timestamps, VHS tone) than the API model.
    default_image_provider="flow",
    storyboard_directive=(
        "\n\nCHANNEL STYLE — HORROR REAL (OVERRIDES ANY CONFLICTING RULE ABOVE):\n"
        "This is a creepy/true-horror story channel. The look must read as REAL. "
        "Two visual lanes:\n"
        "  LANE 1 (~80% of scenes) 'stock_video' — dark, moody, liminal real "
        "footage: night road headlights, warehouse aisles, empty corridors, gas "
        "station at night, fog, flickering lights, CCTV hallways, snow at night.\n"
        "  LANE 2 (the SCARE MONEY-SHOTS, ~10-20%) 'generated_image' — ONLY when "
        "the scene's visual description contains an entity/moment no stock library "
        "has (a distant motionless silhouette at the end of an aisle, a face that "
        "is subtly wrong, an unbroken snowfield around a booth). The image_prompt "
        "MUST read as a FOUND PHOTO: 'grainy amateur night photograph, harsh "
        "flash/sodium light, motion blur, underexposed, like a photo a witness "
        "took' — NEVER illustration, painting, render, or clean composition. If "
        "the scene's visual note is prefixed 'photoreal grainy'/'grainy photoreal', "
        "it IS a money-shot: use 'generated_image' with that description.\n"
        "NEVER cartoon/AI-art styles anywhere. Dread comes from restraint: the "
        "figure is always distant, still, or partial — never a clear monster.\n"
        "UNCANNY RULE (what actually scares people): dread comes from DISTANCE, "
        "STILLNESS and ABSENCE, not from a shown face. Any figure MUST be far "
        "away, partial, or a pure SILHOUETTE in shadow — a wrong shape (too tall, "
        "too thin, too still) glimpsed at the end of a hall, between cars, past "
        "the treeline. NEVER a close-up face, and NEVER a distorted/deformed/"
        "melted/blank face — image models REFUSE to generate malformed human "
        "faces (they come back blank) AND it looks like cheap AI. Show the empty "
        "room, the open door, the shape in the dark. Never fangs/claws/gore/"
        "creature. The viewer needs a second look to see why the shape is wrong."
    ),
)

STYLE_POLICIES: dict[str, ChannelStylePolicy] = {
    "footage": _FOOTAGE,
    "storytelling": _STORYTELLING,
    "horror_real": _HORROR_REAL,
}


def get_style_policy(style_id: str | None) -> ChannelStylePolicy | None:
    """Policy for a channel_style id. None for 'auto'/unknown/missing (legacy)."""
    if not style_id:
        return None
    return STYLE_POLICIES.get(str(style_id).strip().lower())


_STOPWORDS = re.compile(
    r"\b(of|the|a|an|per|with|your|you|is|are|to|in|on|and|or|for|that|this|it)\b")


def _derive_stock_query(cell: dict, heading: str) -> str:
    """Concrete 2-5 word stock query from whatever the cell already has."""
    for key in ("stock_query", "search_query"):
        q = (cell.get(key) or "").strip()
        if q and not q.startswith("http"):
            return q.lower()
    prompt = (cell.get("image_prompt") or "").strip()
    src = prompt if prompt else heading
    words = _STOPWORDS.sub(" ", re.sub(r"[^a-zA-Z ]", " ", src.lower())).split()
    return " ".join(words[:5]).strip()


def enforce_policy(board: list[dict], headings: list[str],
                   policy: ChannelStylePolicy) -> list[dict]:
    """Coerce banned visual types to the policy's preferred type (in place).

    Returns the same list for convenience. Never raises: a cell it cannot fix
    keeps its type and the downstream per-type fallbacks handle it.
    """
    coerced = 0
    for i, cell in enumerate(board):
        if not isinstance(cell, dict):
            continue
        vtype = cell.get("visual_type", "generated_image")
        # A 'chart' cell only exists on channels that declared (and can back)
        # the chart_render capability — it is a REAL data visual with its own
        # fail-closed audit, never a sourcing-style question. Leave it alone.
        if vtype == "chart":
            continue
        # Empty stub cells (storyboard salvage losses default to generated_image
        # with no prompt at all) can't render anything useful — route them to the
        # policy's preferred source instead of a doomed blank image gen.
        is_stub = not any((cell.get(k) or "").strip()
                          for k in ("image_prompt", "stock_query", "search_query"))
        if vtype in policy.allowed_types and not (is_stub and vtype != policy.preferred_type):
            continue
        heading = headings[i] if i < len(headings) else ""
        _coerce_cell(cell, policy, heading)
        coerced += 1

    # Deterministic stock ratio cap (the LLM does not obey the ratio ask).
    # Keep only atmosphere cutaways as stock, up to the cap; everything else
    # becomes the preferred type (illustrated world stays coherent).
    if policy.stock_max_ratio is not None and board:
        stock_idx = [i for i, c in enumerate(board)
                     if isinstance(c, dict) and c.get("visual_type") == "stock_video"]
        # At least one atmosphere cutaway stays allowed even on tiny boards.
        cap = max(1, int(len(board) * policy.stock_max_ratio))
        if len(stock_idx) > cap:
            keep = [i for i in stock_idx
                    if _ATMOSPHERE_RE.search(board[i].get("stock_query") or "")][:cap]
            keep_set = set(keep)
            for i in stock_idx:
                if i in keep_set:
                    continue
                heading = headings[i] if i < len(headings) else ""
                _coerce_cell(board[i], policy, heading)
                coerced += 1

    if coerced:
        print(f"[style-policy] {policy.style_id}: coerced {coerced} scene(s) "
              f"to {policy.preferred_type}")
    return board


def _coerce_cell(cell: dict, policy: ChannelStylePolicy, heading: str) -> None:
    """Rewrite one cell to the policy's preferred visual type in place."""
    src_query = (cell.get("stock_query") or "").strip()
    cell["visual_type"] = policy.preferred_type
    if policy.preferred_type == "stock_video":
        if not src_query:
            cell["stock_query"] = _derive_stock_query(cell, heading)
    elif policy.preferred_type == "generated_image" and not (cell.get("image_prompt") or "").strip():
        # A stock query ('paris train station historic') is a usable subject —
        # reuse it as the illustration subject before falling back to heading.
        cell["image_prompt"] = (src_query or cell.get("search_query") or heading or "").strip()
