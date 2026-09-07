"""Clickbait title + thumbnail generation (all channels).

Two pieces, channel-agnostic:
  1. generate_clickbait(script, channel_meta, pillar_id) -> {title, thumb_text, thumb_prompt}
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

# Imported at module level so the `except` clauses below can NAME it. A broad
# `except Exception` that also catches this is how a fail-closed channel keeps
# rendering.
try:
    from omnicast.analytics.intel_gate import CompetitorIntelRequired
except Exception:  # pragma: no cover - package not importable in some scripts
    class CompetitorIntelRequired(RuntimeError):
        """Fallback so the handlers below are still well-formed."""

# Impact is the classic YouTube-thumbnail face; fall back to Arial Bold.
_FONT_IMPACT = "C:/Windows/Fonts/impact.ttf"
_FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
_FONT_TRUST = "C:/Windows/Fonts/georgiab.ttf"
_FONT_UI = "C:/Windows/Fonts/segoeuib.ttf"
TW, TH = 1280, 720

_UNSUPPORTED_NEWS_RE = re.compile(
    r"\b(breaking|just\s+(?:confirmed|announced|changed|revealed|got)|"
    r"suddenly|new\s+(?:social\s+security\s+)?rule|now\s+warns?)\b",
    re.I,
)
_UNSUPPORTED_SECRECY_RE = re.compile(
    r"\b(won't tell you|doesn't want you to know|hidden truth|"
    r"too rich for)\b",
    re.I,
)
_TRAP_RE = re.compile(r"\btrap\b", re.I)
_SCRIPT_NEWS_SUPPORT_RE = re.compile(
    r"\b(announced|confirmed|changed|new rule|takes effect|effective on|"
    r"released (?:today|this week|this month)|breaking)\b",
    re.I,
)
_WITHHOLDING_AS_LOSS_RE = re.compile(
    r"\b(takes?\s+back|takes?\s+\$|keeps?\s+\$|steals?|"
    r"money\s+(?:is\s+)?lost|you\s+lose)\b",
    re.I,
)
_SCRIPT_CORRECTS_LOSS_RE = re.compile(
    r"\b(not lost|withheld|withholding|recalculat(?:e|ed|ion)|"
    r"increased permanently)\b",
    re.I,
)


def _apply_packaging_truth_guard(data: dict, script_text: str) -> dict:
    """Choose the first high-CTR title that does not invent a news event.

    A current year in a standing rule is not evidence that an agency "just
    confirmed" anything. This deterministic pass considers the primary title
    and alternatives, preserving the model's creativity while refusing false
    recency. If every candidate makes the same unsupported claim, it supplies
    a conservative subject-specific fallback.
    """
    out = dict(data or {})
    candidates = [
        str(out.get("title") or "").strip(),
        *[str(x or "").strip() for x in (out.get("alternatives") or [])],
    ]
    supports_news = bool(_SCRIPT_NEWS_SUPPORT_RE.search(script_text or ""))
    corrects_loss_framing = bool(
        _SCRIPT_CORRECTS_LOSS_RE.search(script_text or ""))

    def acceptable(title: str) -> bool:
        if not title:
            return False
        if not supports_news and _UNSUPPORTED_NEWS_RE.search(title):
            return False
        if _UNSUPPORTED_SECRECY_RE.search(title):
            return False
        if _TRAP_RE.search(title) and not _TRAP_RE.search(script_text or ""):
            return False
        if (corrects_loss_framing
                and _WITHHOLDING_AS_LOSS_RE.search(title)):
            return False
        return True

    selected = next((title for title in candidates if acceptable(title)), "")
    if not selected:
        if re.search(r"\b(social security|SSA)\b", script_text or "", re.I):
            selected = (
                "Working While on Social Security? Where the Withheld Money Goes"
            )
        else:
            selected = "The Rule Behind What Changes — And What Does Not"
    original = str(out.get("title") or "").strip()
    out["title"] = selected[:100]
    out["truth_guard_replaced_title"] = selected != original
    return out


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
    "or invented recency ('BREAKING', 'NEW RULE', 'JUST CONFIRMED', 'NOW WARNS') "
    "unless the script explicitly reports that dated announcement/change; a "
    "current-year threshold by itself is NOT a new announcement. If the script "
    "distinguishes temporary withholding from permanent loss, the title MUST "
    "preserve that distinction — never say SSA 'TAKES BACK', 'KEEPS', 'STEALS', "
    "or that the viewer simply 'LOSES' the money. Never invent agency secrecy "
    "('SSA WON'T TELL YOU') or call a published conditional formula a 'TRAP'. "
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


def _packaging_pillar(meta: dict, script_text: str) -> str:
    """Which content pillar this script belongs to, for the scope key.

    Packaging was scoped on four dimensions and silently unscoped on the fifth,
    so annuities and social-security thumbnails still shared one channel-wide
    playbook — §4.2's finest level existed for the writer and not here. Uses the
    same deterministic classifier as the scorer and the brief builders, so a
    video's pillar is one answer everywhere."""
    try:
        from omnicast.analytics.pillars import classify_pillar, load_pillars

        pillars = load_pillars((meta or {}).get("content_pillars"))
        if not pillars:
            return ""
        match = classify_pillar(script_text[:2000], "", pillars)
        return match.pillar_id if match.is_classified else ""
    except Exception:
        return ""


def _scoped_playbook(meta: dict, artifact: str, pillar_id: str = ""):
    """(text, decision) for one competitor artifact, scoped and gated.

    `channel_meta` here is a raw dict read from `channels/<id>.json`, so it is
    wrapped in a tiny attribute view — `intel_scope` reads its dimensions with
    `getattr`, and a dict would silently produce `*` for every one of them."""
    from omnicast.analytics.intel_gate import CompetitorIntelRequired
    from omnicast.analytics.intel_scope import resolve_scoped_playbook

    class _ChannelView:
        def __init__(self, raw: dict, pillar: str) -> None:
            for key in ("channel_id", "niche", "market", "intel_archetype",
                        "audience_segment", "content_format"):
                setattr(self, key, raw.get(key, "") or "")
            self.pillar_id = pillar

    try:
        return resolve_scoped_playbook(
            _ChannelView(meta or {}, pillar_id), artifact,
            pillar_id=pillar_id,
            required=bool((meta or {}).get("competitor_intel_required")))
    except CompetitorIntelRequired:
        # FAIL CLOSED. A channel that declares `competitor_intel_required` has
        # said it would rather stop than ship packaging built from patterns
        # nobody verified. Catching this alongside everything else turned that
        # declaration into a no-op — the channel kept rendering, which is the
        # single thing it asked not to happen.
        raise
    except Exception as exc:
        # Everything else: packaging degrades to no playbook, and says so.
        print(f"[clickbait] competitor {artifact} unavailable: {exc}")
        return "", None



# Words a thumbnail hook may use without appearing in the story: short dread
# vocabulary. Anything else must occur in the script — v24 (07/09) shipped
# "MILER 47", a non-word the LLM invented, baked into the thumbnail.
_HOOK_VOCAB = set("""
it its was wasn't wasnt there here not never no don't dont do stop look behind you your
me my we they he she who what why when where how the a an of in on at to and or but
wrong right number ticket mile marker call caller answer dispatch radio signal night
road truck tow shoulder gone dead alone still again back home late last first one two
three someone nobody something nothing knock door voice light lights dark watching
waiting following wait listen run hide open close closed inside outside under over
came come left stayed returned real true false
""".split())


def _valid_hook(text: str, script_text: str) -> bool:
    """2–4 words, each a hook-vocabulary word, a number, or a word that
    appears in the story. Rejects invented tokens like MILER."""
    words = [re.sub(r"[^A-Za-z0-9']", "", w).lower() for w in (text or "").split()]
    words = [w for w in words if w]
    if not (1 <= len(words) <= 4):
        return False
    script_words = set(re.findall(r"[a-z0-9']+", (script_text or "").lower()))
    for w in words:
        if w.isdigit() or w in _HOOK_VOCAB or w in script_words:
            continue
        return False
    return True


_HOOK_FALLBACKS = ["IT WASN'T THERE", "DON'T ANSWER", "WRONG NUMBER", "NOBODY CALLED"]

def generate_clickbait(script_text: str, channel_meta: dict | None = None,
                       pillar_id: str = "") -> dict | None:
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
        # SCOPED AND GATED, exactly like the writer's script playbook.
        #
        # This used to be `get_competitor_intel(niche)` inside
        # `except Exception: pass`: no channel/audience/format/pillar scope, no
        # comparability check, no freshness check, and every failure silent. A
        # retirement channel for 65-year-olds could therefore dress its
        # thumbnails from a 25-year-old audience's playbook, or from an
        # uncontrolled or stale artifact, and nothing would say so — the §4.2
        # failure the scope key exists to end, still live on the packaging path
        # after the writer had been fixed.
        playbook = ""
        # SSOT FIRST. `pillar_id` comes from `TopicBrief.pillar_id` via the
        # product metadata — the same answer the scorer and the writer used.
        # Re-deriving it from the script text is a FALLBACK for callers that
        # have no brief, and it is noted as one: a video about annuities that
        # mentions Medicare repeatedly can classify as social_security and take
        # the wrong playbook.
        _pillar = str(pillar_id or "").strip()
        _pillar_source = "brief"
        if not _pillar:
            _pillar = _packaging_pillar(meta, script_text)
            _pillar_source = "classified from script (no pillar on the brief)"
        if _pillar and _pillar_source != "brief":
            print(f"[clickbait] pillar '{_pillar}' {_pillar_source}")
        for artifact, header in (
            ("title_playbook",
             "COMPETITOR TITLE PLAYBOOK (mirror these winning patterns)"),
            ("thumbnail_playbook",
             "COMPETITOR THUMBNAIL PLAYBOOK (thumb_prompt + thumb_text must "
             "follow this recipe)"),
        ):
            text, decision = _scoped_playbook(meta, artifact, _pillar)
            if text:
                borrowed = ""
                level = getattr(decision, "scope_level", "") if decision else ""
                if level not in ("", "exact"):
                    from omnicast.analytics.intel_scope import describe_level

                    borrowed = f"\n[SCOPE NOTE: {describe_level(level)}]"
                playbook += f"\n\n{header}:{borrowed}\n{text}"
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
        _tt = (data.get("thumb_text") or "").strip().upper()[:40]
        if not _valid_hook(_tt, script_text):
            # One retry with the rule spelled out, then a safe fallback —
            # never a made-up word on the most-seen asset of the video.
            print(f"      [warn] thumb_text {_tt!r} is not made of real story words; retrying")
            try:
                _fix = _run(LLMClient(provider=_prov, model=_mdl).complete(
                    system="You write 2-4 word ALL-CAPS YouTube horror thumbnail hooks.",
                    messages=[{"role": "user", "content":
                        "Rewrite this hook using ONLY common English words or words that appear in the "
                        "story below (numbers allowed). 2-4 words, ALL CAPS, no invented words, no "
                        f"punctuation except apostrophes. Reply with the hook only.\nBAD HOOK: {_tt}\n"
                        f"STORY:\n{script_text[:3000]}"}],
                    max_tokens=30, temperature=0.4))
                _cand = (getattr(_fix, "content", "") or "").strip().strip('"').upper()[:40]
                _tt = _cand if _valid_hook(_cand, script_text) else ""
            except Exception as _fe:
                print(f"      [warn] hook retry failed ({_fe})"); _tt = ""
            if not _tt:
                _tt = next((h for h in _HOOK_FALLBACKS if _valid_hook(h, script_text)), _HOOK_FALLBACKS[0])
                print(f"      [warn] thumb_text fallback -> {_tt!r}")
        packaged = {
            "title": (data.get("title") or "").strip()[:100],
            "thumb_text": _tt,
            "thumb_prompt": (data.get("thumb_prompt") or "").strip(),
            "alternatives": [a.strip()[:100] for a in (data.get("alternatives") or [])][:3],
        }
        return _apply_packaging_truth_guard(packaged, script_text)
    except CompetitorIntelRequired:
        # The outer net must not close over this either: the channel declared
        # that it would rather stop than ship unverified packaging, and a
        # `return None` here turns the declaration back into a no-op one frame
        # further out.
        raise
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
    layout: str = "impact",
) -> None:
    """Compose a 1280x720 thumbnail in the audience's packaging grammar.

    ``impact`` preserves the entertainment-oriented, outlined display type.
    ``trust`` is deliberately quieter: a navy editorial panel, a restrained
    gold rule and large serif/sans typography.  The latter is for older
    finance/health audiences where an exaggerated MrBeast treatment reads as
    a scam signal rather than a click signal.
    """
    from PIL import Image, ImageDraw, ImageEnhance

    base = Image.open(bg_png).convert("RGB")
    scale = max(TW / base.width, TH / base.height)
    base = base.resize((int(base.width * scale), int(base.height * scale)))
    x0 = (base.width - TW) // 2
    y0 = (base.height - TH) // 2
    img = base.crop((x0, y0, x0 + TW, y0 + TH))

    if layout == "trust":
        # Keep the real scene recognizable, but calm saturation and make a
        # deterministic reading zone.  The graduated panel preserves subject
        # detail on the right instead of crushing the entire frame.
        img = ImageEnhance.Color(img).enhance(0.78)
        img = ImageEnhance.Contrast(img).enhance(1.08).convert("RGBA")
        panel = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        px = panel.load()
        navy = (11, 36, 61)
        for x in range(820):
            alpha = int(232 * max(0.0, 1.0 - (x / 900) ** 2))
            for y in range(TH):
                px[x, y] = (*navy, alpha)
        img = Image.alpha_composite(img, panel)
        draw = ImageDraw.Draw(img)

        # A small masthead establishes the desk/editor identity without
        # competing with the one promise the viewer must read on a phone.
        ui = _font(_FONT_UI, 30)
        draw.rounded_rectangle((62, 54, 456, 101), radius=8,
                               fill=(8, 29, 49, 220),
                               outline=(*accent, 230), width=2)
        draw.text((82, 61), "THE RETIREMENT DESK", font=ui,
                  fill=(244, 242, 234, 255))
        draw.rectangle((65, 132, 236, 140), fill=(*accent, 255))

        words = (thumb_text or "THE RULE").upper().split()
        if len(words) >= 3:
            mid = (len(words) + 1) // 2
            lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        elif len(words) == 2:
            lines = [words[0], words[1]]
        else:
            lines = [words[0]]
        longest = max(len(line) for line in lines)
        size = 112 if longest <= 10 else 92 if longest <= 15 else 76
        font = _font(_FONT_TRUST, size)
        line_h = int(size * 1.13)
        y = 190
        for i, line in enumerate(lines):
            # Put the concrete number/last promise in gold; everything else
            # stays warm white. A small shadow is enough—no meme outline.
            colour = (*accent, 255) if (
                any(ch.isdigit() for ch in line) or i == len(lines) - 1
            ) else (248, 246, 239, 255)
            draw.text((70 + 3, y + 4), line, font=font,
                      fill=(0, 0, 0, 125))
            draw.text((70, y), line, font=font, fill=colour)
            y += line_h

        out_png.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out_png, quality=95)
        return

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
