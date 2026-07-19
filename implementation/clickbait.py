"""Clickbait title + thumbnail generation (all channels).

Two pieces, channel-agnostic:
  1. generate_clickbait(script, channel_meta) -> {title, thumb_text, thumb_prompt}
     via DeepSeek — a curiosity-gap YouTube title + 2-4 punchy thumbnail words +
     a dramatic high-contrast thumbnail background prompt in the channel's style.
  2. compose_thumbnail(bg_png, thumb_text, out_png, accent) -> PIL 1280x720
     clickbait thumbnail: cover bg + vignette + huge bold outlined text with the
     key word in the channel accent colour.
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Impact is the classic YouTube-thumbnail face; fall back to Arial Bold.
_FONT_IMPACT = "C:/Windows/Fonts/impact.ttf"
_FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
TW, TH = 1280, 720

_SYSTEM = (
    "You are a top-1% YouTube packaging strategist (Vox / Johnny Harris / MrBeast level "
    "CTR). PROCESS (do this internally): brainstorm 8 DISTINCT title candidates spanning "
    "different structures + emotional angles, judge each on raw click-through power (scroll-"
    "stopping curiosity, specific stake, no spoiler), then RETURN ONLY THE SINGLE STRONGEST "
    "as 'title' and the 2 next-best as 'alternatives'. Do the same brainstorm-then-pick for "
    "thumb_text. Quality bar: if a title could belong to any generic health channel, it's a "
    "FAIL — regenerate it. Return ONLY a "
    "JSON object: {\"title\": \"A HIGH-CTR YOUTUBE TITLE built FROM the script's single "
    "most striking claim/hook (use the hook as raw material, do NOT copy a flat spoken "
    "sentence verbatim, and NEVER use the greeting or a bland recap). Target 40-65 chars "
    "(<=70 hard max). Use EXACTLY ONE proven structure that best fits (VARY across "
    "videos — do not always pick the same one): "
    "(a) WARNING/negative command — 'Stop Eating This On Ozempic'; "
    "(b) CURIOSITY GAP — 'The Silent Deficiency 50% of Ozempic Users Ignore'; "
    "(c) NUMBER + STAKES — 'The $3,600 Mistake You're Making on Ozempic'; "
    "(d) WHY (explain a paradox/symptom) — 'Why You Feel So Exhausted on Ozempic "
    "(It's Not Just Weight Loss)'; "
    "(e) HOW (promise a fix) — 'How to Stop the Silent Nutrient Drain (Before It's "
    "Too Late)'. A short parenthetical kicker — (It's not just X) / (Before it's too "
    "late) — adds curiosity or urgency; use it when it fits. "
    "HARD RULES: name the SPECIFIC subject (drug/brand/topic keyword) so the right viewer "
    "self-identifies; lead with the strongest STAKE (a scary symptom — 'exhaustion', "
    "'numb hands' — or a money loss) when the script has one; open a curiosity gap. "
    "DO NOT SPOIL THE ANSWER: never name the specific culprit/nutrient/mechanism the video "
    "reveals (e.g. say 'a silent deficiency' / 'a hidden mistake', NOT 'B12'). If the title "
    "gives away the payoff, the viewer has no reason to click. "
    "GOOD (gap kept): 'The Silent Deficiency 50% of Ozempic Users Ignore', 'The $3,600 "
    "Mistake You're Making on Ozempic', 'Stop Eating These \"Healthy\" Foods on Ozempic'. "
    "BAD (spoils / bland): 'The Food Stealing Your B12' (names the answer), '3 Foods "
    "Wrecking Your Ozempic Results' (generic, no stake). "
    "FORBIDDEN: literal greeting, flat recap, generic summary, clickbait lies, "
    "demonetizing words. A bland title is a FAIL even if accurate>\", "
    "\"thumb_text\": \"2-4 UPPERCASE words for "
    "the thumbnail — a VISCERAL SCROLL-STOPPER that creates a CURIOSITY GAP. PICK ONE form: "
    "(a) WARNING COMMAND anchored to the VISIBLE subject — 'STOP EATING THIS', "
    "'NOT THIS COFFEE', 'SKIP THIS TONIGHT'; "
    "(b) MYSTERY THREAT — 'SILENT DRAIN', 'HIDDEN DAMAGE', 'THE REAL CAUSE'; "
    "(c) CURIOSITY QUESTION — 'WHY SO TIRED?', 'IS THIS YOU?'. "
    "ANCHOR RULE: at least ONE word must be a CONCRETE NOUN the viewer can see or feel "
    "(DINNER, COFFEE, SHOT, NAUSEA, PLATE, WINE...) — abstract-only phrases are a FAIL "
    "even if dramatic ('TONIGHT MATTERS', 'THINK AGAIN', 'BE CAREFUL' = FAIL; "
    "'WRONG DINNER?', 'SKIP THIS DINNER', 'NAUSEA STARTS HERE' = PASS). A floating "
    "generic command with no referent reads as spam. "
    "ABSOLUTE RULE — DO NOT SPOIL: NEVER put the video's answer/mechanism on the thumbnail "
    "(no 'STEALS B12', no 'OZEMPIC STEALS B12' — that reveals the payoff and kills the "
    "click). The thumb POSES the threat; the video DELIVERS the answer. "
    "Keep it short, active, punchy (a verb, 'YOU/YOUR', or '?'), NOT a static noun label. "
    "GOOD (gap, no spoiler, anchored): 'SILENT DRAIN', 'STOP EATING THIS', 'WHY SO TIRED?', 'HIDDEN ON OZEMPIC'. "
    "BAD (spoils or flat): 'OZEMPIC STEALS B12', 'B12 HEIST', 'NAUSEA TRAP', 'HEALTH TIPS'. "
    "POLICY-SAFE: never use defamatory/medical-misinfo words ('POISON', 'TOXIC', "
    "'DANGEROUS', 'CURE', 'MIRACLE') — they get the video demonetized. "
    "COMPLEMENT THE TITLE — do NOT repeat the title's words. The thumb adds the EMOTIONAL "
    "punch the title sets up: a 'Why your morning coffee is a trap' title pairs with a thumb "
    "that shows the threat ('STOP THIS!' over a crossed-out coffee), not the words 'coffee "
    "trap' again. Title states the angle; thumb makes you feel the danger. "
    "Make the viewer NEED to know more\", \"thumb_prompt\": \"a "
    "detailed prompt for a PHOTOREALISTIC, cinematic thumbnail image — describe a "
    "real human subject with an EXAGGERATED dramatic facial expression (shock, pain, "
    "disbelief) or a striking real-world object. MUST be BRIGHT, high-contrast, and "
    "saturated (punchy colors, well-lit subject — NEVER dark/dim/muddy; a dark thumb "
    "reads as a black smudge at small mobile size and gets scrolled past). Strong rim "
    "light on the subject, vivid background. Leave a clear empty area on one side for big "
    "text. Describe it like a real photograph, NOT a cartoon/vector/illustration. "
    "OPTIONAL VISUAL CUE: if (and ONLY if) it "
    "suits a high-drama / 'this is the culprit' style video, you MAY add a bold "
    "hand-drawn red arrow or red circle pointing at the key object — great for "
    "health/scam/warning/exposé topics, but OMIT it for calm/serious genres "
    "(history, documentary, science explainer) where it would look cheap. You decide "
    "per topic\", \"alternatives\": [\"2nd-best title\", \"3rd-best title\"]}. "
    "Match the channel tone. The thumb_text must be VERY short — it goes on a thumbnail."
)


# Narrative / true-horror-story channels need a completely different packaging voice.
# The explainer prompt above (health warnings, "parenthetical kicker", BRIGHT thumbs)
# produces wrong titles like "The Room… (Night Shift Horror)" — a tacked-on genre tag
# that reads as amateur. Top horror channels (Mr. Nightmare, Lets Read) use clean
# first-person curiosity titles or the "N TRUE <setting> Stories" anthology form, and
# DARK grainy thumbnails.
_SYSTEM_NARRATIVE = (
    "You are a top-1% packaging strategist for TRUE-SCARY-STORY YouTube channels "
    "(Mr. Nightmare / Lets Read / Corpse Husband level). PROCESS (internally): "
    "brainstorm 8 DISTINCT title candidates, judge each on scroll-stopping dread + "
    "curiosity (no spoiler), RETURN ONLY the single strongest as 'title' and the 2 "
    "next-best as 'alternatives'. Return ONLY a JSON object: "
    "{\"title\": \"A HIGH-CTR title in the channel's first-person true-story voice, "
    "built FROM the script's most unsettling moment. Target 40-65 chars (<=70 hard "
    "max). Use EXACTLY ONE proven horror structure (VARY across videos): "
    "(a) FIRST-PERSON CONFESSION — 'I Only Quit the Night Shift After What I Saw'; "
    "(b) THE PLACE THAT'S WRONG — 'The Room That Should Have Been Empty'; "
    "(c) ANTHOLOGY COUNT (use when the script is multiple accounts) — "
    "'3 TRUE Night Shift Encounters That Still Scare Me'; "
    "(d) THE THING GLIMPSED — 'Something Was Standing at Mile Marker 12'. "
    "HARD RULES: keep the DREAD, keep it grounded and real ('true', 'really "
    "happened' tone), open a curiosity gap, name the concrete SETTING (hospital, "
    "rural road, parking garage, night shift) so the right viewer self-identifies. "
    "DO NOT SPOIL what the figure/thing turns out to be. "
    "FORBIDDEN: a tacked-on genre tag in parentheses like '(Night Shift Horror)', "
    "'(Scary Story)', '(True Horror)' — the genre belongs IN the sentence, never as a "
    "bracketed label. No greeting, no flat recap, no fake clickbait, no gore words that "
    "demonetize ('MURDER', 'DEAD BODY'). A bland or over-tagged title is a FAIL>\", "
    "\"thumb_text\": \"2-4 UPPERCASE words for the thumbnail — a dread curiosity gap "
    "anchored to a CONCRETE thing the viewer sees/feels (a place or a presence): "
    "'IT WAS STILL THERE', 'ROOM 314', 'DON'T LOOK BACK', 'IT COPIED ME'. "
    "Pose the threat, never reveal what it was. No health/scam words>\", "
    "\"thumb_prompt\": \"a prompt for a PHOTOREALISTIC, grainy, found-footage-style "
    "horror thumbnail — a real amateur night photo. The dread comes from DISTANCE and "
    "STILLNESS: a far-off or partial uncanny figure / pure silhouette in shadow (too "
    "tall, too still) at the end of a hall, past the treeline, between cars — NEVER a "
    "close-up or distorted face. Cold, desaturated, mostly dark with a single weak "
    "light source (one lamp, headlights, an EXIT sign) and a faint cold rim light on "
    "the figure. Leave a clear darker area on one side for big text. Describe it like a "
    "real photograph, NOT a cartoon/illustration, and NO red arrows/circles>\", "
    "\"alternatives\": [\"2nd-best title\", \"3rd-best title\"]}. "
    "Match the channel's quiet-dread tone. thumb_text must be VERY short."
)


def generate_clickbait(script_text: str, channel_meta: dict | None = None) -> dict | None:
    """One DeepSeek call -> {title, thumb_text, thumb_prompt}. None on failure."""
    try:
        src = ROOT / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        import asyncio

        import orjson

        from omnicast.config.settings import get_settings
        from omnicast.llm.client import LLMClient

        s = get_settings()
        meta = channel_meta or {}
        # Narrative/horror channels use a story-native packaging prompt (the default
        # _SYSTEM is explainer-only and tacks on genre tags like "(Night Shift Horror)").
        _blob = f"{meta.get('channel_style','')} {meta.get('content_format','')} {meta.get('niche','')} {meta.get('tone','')}".lower()
        _is_narrative = (str(meta.get("channel_style", "")).lower() == "horror_real"
                         or str(meta.get("content_format", "")).lower() == "narrative"
                         or "horror" in _blob or "scary" in _blob or "story" in _blob)
        system_prompt = _SYSTEM_NARRATIVE if _is_narrative else _SYSTEM
        # Inject competitor-learned playbooks (how winning channels in this niche
        # name titles + design thumbnails) so output mirrors what already works.
        playbook = ""
        try:
            from omnicast.vault import db as _vdb
            VAULT_DB = ROOT / "output" / "vault.db"
            ci = _vdb.get_competitor_intel((meta.get("niche", "") or "").lower(), VAULT_DB)
            if ci:
                if ci.title_playbook:
                    playbook += f"\n\nCOMPETITOR TITLE PLAYBOOK (mirror these winning patterns):\n{ci.title_playbook}"
                if ci.thumbnail_playbook:
                    playbook += f"\n\nCOMPETITOR THUMBNAIL PLAYBOOK (thumb_prompt + thumb_text must follow this recipe):\n{ci.thumbnail_playbook}"
        except Exception:
            pass
        ctx = (
            f"Channel: {meta.get('name','')} | niche: {meta.get('niche','')} | "
            f"tone: {meta.get('tone','')} | brand_voice: {meta.get('brand_voice','')}"
            f"{playbook}\n\n"
            f"SCRIPT:\n{script_text[:1800]}"
        )
        def _run(coro):
            # Robust against a thread that already has a running event loop.
            try:
                asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                    return _ex.submit(lambda: asyncio.run(coro)).result()
            except RuntimeError:
                return asyncio.run(coro)

        # CTR packaging is a HIGH-SKILL creative task — use a STRONG model, not the
        # cheap chat model that produced bland titles. deepseek-v4-pro (reasoning) is
        # the strong workhorse and is always funded here; Claude Sonnet is tried only
        # if explicitly preferred (often out of credits → 400 + noise, so not first).
        # chat is the last-ditch fallback. Order = strong-and-working first.
        _prefer_claude = os.environ.get("CLICKBAIT_USE_CLAUDE") == "1"
        model_chain = [
            ("deepseek", getattr(s, "deepseek_pro_model", None)),
            ("deepseek", getattr(s, "deepseek_chat_model", None)),
        ]
        if _prefer_claude:
            model_chain.insert(0, ("anthropic", getattr(s, "claude_model", None)))
        resp = None
        for _prov, _mdl in model_chain:
            if not _mdl:
                continue
            try:
                resp = _run(LLMClient(provider=_prov, model=_mdl).complete(
                    system=system_prompt, messages=[{"role": "user", "content": ctx}],
                    max_tokens=2200, temperature=0.9))
                if resp and resp.content:
                    break
            except Exception as _e:
                print(f"      [warn] clickbait {_prov}:{_mdl} failed ({_e}); next")
                resp = None
        if not resp or not resp.content:
            return None
        m = re.search(r"\{[\s\S]*\}", resp.content)
        data = orjson.loads(m.group(0) if m else resp.content)
        return {
            "title": (data.get("title") or "").strip()[:100],
            "thumb_text": (data.get("thumb_text") or "").strip().upper()[:40],
            "thumb_prompt": (data.get("thumb_prompt") or "").strip(),
            "alternatives": [a.strip()[:100] for a in (data.get("alternatives") or [])][:3],
        }
    except Exception as exc:
        print(f"      [warn] clickbait LLM failed ({exc})")
        return None


def _font(path_primary: str, size: int):
    from PIL import ImageFont
    for p in (path_primary, _FONT_BOLD):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def compose_thumbnail(
    bg_png: Path, thumb_text: str, out_png: Path,
    *, accent: tuple[int, int, int] = (255, 209, 71),
) -> None:
    """Compose a 1280x720 clickbait thumbnail: bg + vignette + huge outlined text
    with the last word in the channel accent colour."""
    from PIL import Image, ImageDraw

    base = Image.open(bg_png).convert("RGB")
    scale = max(TW / base.width, TH / base.height)
    base = base.resize((int(base.width * scale), int(base.height * scale)))
    x0 = (base.width - TW) // 2
    y0 = (base.height - TH) // 2
    img = base.crop((x0, y0, x0 + TW, y0 + TH))

    # Bottom-up dark gradient so big text reads.
    grad = Image.new("L", (1, TH), 0)
    for y in range(TH):
        grad.putpixel((0, y), int(max(0, (y / TH - 0.35)) * 255 * 1.4))
    grad = grad.resize((TW, TH))
    dark = Image.new("RGB", (TW, TH), (0, 0, 0))
    img = Image.composite(dark, img, grad)

    draw = ImageDraw.Draw(img)
    words = (thumb_text or "BREAKING").split()
    # 2 lines max; last line keyword gets accent.
    if len(words) >= 3:
        mid = (len(words) + 1) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    elif len(words) == 2:
        lines = [words[0], words[1]]
    else:
        lines = [words[0]]

    size = 150 if max(len(l) for l in lines) <= 9 else 110
    font = _font(_FONT_IMPACT, size)
    line_h = int(size * 1.06)
    total_h = line_h * len(lines)
    y = TH - 70 - total_h
    for i, line in enumerate(lines):
        up = line.upper()
        w = draw.textlength(up, font=font)
        x = (TW - w) // 2
        col = accent if (i == len(lines) - 1 and len(lines) > 1) else (255, 255, 255)
        # thick black outline
        for ox in range(-6, 7, 2):
            for oy in range(-6, 7, 2):
                draw.text((x + ox, y + oy), up, font=font, fill=(0, 0, 0))
        draw.text((x, y), up, font=font, fill=col)
        y += line_h

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)


if __name__ == "__main__":  # smoke: compose from an existing illustration
    a = sorted((ROOT / "output/real/_assets").glob("scene_0*_illu.png"))
    if a:
        compose_thumbnail(a[0], "PENSION GONE", ROOT / "output/real/_thumb_smoke.png")
        print("thumb ->", ROOT / "output/real/_thumb_smoke.png")
