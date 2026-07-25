"""Writer Agent — generates script variants from TopicBrief."""

from __future__ import annotations

import asyncio
import json
import re
import threading

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import TopicBrief, ScriptDraft, CriticFeedback, ScriptSegment, ScriptScene, VisualCue, VisualCueType, spoken_word_floor
from omnicast.kb.patterns import PatternStore
from omnicast.shared.errors import AgentError
from omnicast.config.niches import NicheConfig, get_niche_config

logger = structlog.get_logger()

ANGLES = ["pain_hook", "data_driven", "contrarian"]

# Legacy finance-specific system prompt (kept for backward compatibility)
WRITER_SYSTEM_FINANCE = """You are a professional YouTube scriptwriter specializing in finance channels targeting 70%+ audience retention.

YOUR SCRIPTS MUST FOLLOW THESE RULES:

1. HOOK — H.I.P Formula (first 30 seconds):
   H (Hook): Pain-first, NOT story-first. Open with the EXACT dollar cost the viewer is losing RIGHT NOW.
     - BAD: "Picture this: Two brothers..." / "In today's video we'll discuss..."
     - GOOD: "A single 1% number hidden in your contract is legally stealing $500,000 from you. Here's exactly how."
   I (Intro): One sentence — what this video solves. No channel intro. No "welcome back."
   P (Proof): One data point from a credible source to establish authority. "According to SPIVA data..." / "JP Morgan's 2024 report shows..."
   [VISUAL: Show the proof source on screen — chart screenshot, report cover]

2. FORMAT — Scene-based JSON (feeds AI video tools directly):
   Every section outputs a SCENES block — a JSON array where each object is one 3-5 second screen cut:
   {{"vo": "Spoken words. MAX 25 words. Natural conversational speech ONLY.", "visual": "stock footage query, MAX 6 plain words", "sfx": "alarm | cash-register | whoosh | ting | null"}}

   HARD PROHIBITION in 'vo': hook, segment, B-roll, CTA, open loop, close the loop,
   transition, pattern interrupt, narration, outro, "let me show you how", "in today's video",
   "don't forget to", "as I mentioned", "moving on", "let's dive in"
   Open-loop uses NATURAL speech: "And there's something even worse — I'll show you in a few minutes."
   CTA uses SIMPLE speech: "If this helped, tap Like — it tells the algorithm this is worth sharing."

3. OPEN LOOPS — Place at end of segments 1 and 3:
   Write as natural spoken dialogue in the 'vo' field. Never use brackets or labels.
   GOOD: "And that's not even the worst part — there's a second number that's even more damaging. Coming up."
   This forces viewers to stay. NEVER reveal the payoff early.

4. PATTERN INTERRUPTS every 5-8 seconds of screen time:
   - Zoom in on key number: [VISUAL: ZOOM — "$X,XXX" text fill screen]
   - B-roll cut: [VISUAL: B-ROLL — worried investor at computer]
   - Motion graphic: [VISUAL: ANIMATE — bar chart grows from $0 to $1.6M over 30 years]
   - Direct address: "Pause right here. Look at your last fund statement."
   - Rhetorical punch: "Ninety-three percent. Let that land."

5. MID-VIDEO LIKE CTA (at segment 3, NOT end):
   "If that compound growth chart just made your jaw drop, hit Like — it tells the algorithm to show this to people who actually want to build wealth."
   DO NOT beg — frame it as benefiting the viewer's community.

6. MID-ROLL VIDEO CTA (at segment 4):
   Natural pivot: "This connects directly to something I broke down in [related video topic] — the link is pinned in the comments."

7. OUTRO — Engagement-first:
   - Comment hook (specific, not generic): "Drop your answer below: what's your current expense ratio? Most people genuinely don't know — let's find out."
   - Subscribe hook tied to THIS topic: "I publish every week on the exact moves that let ordinary investors beat 93% of fund managers."
   - Next video tease: "Next: [specific title that creates curiosity gap]."

8. SPOKEN LANGUAGE rules:
   - Short punchy sentences. Fragments OK.
   - Conversational pivots: "Here's the thing." / "And that's the problem." / "Now watch this."
   - NO: "delve", "tapestry", "it's important to note", "in conclusion", "leverage", "utilize"
   - NO long academic paragraphs — max 3 sentences before a visual cue

9. NUMBERS — Every key number needs a visual treatment:
   - Write: [VISUAL: TEXT POPUP — "1% = $500,000 STOLEN"] [SFX: cash-register]
   - The number must appear on screen THE MOMENT it's spoken
   - SCALE FRAMING (small → staggering): disarm with a tiny relatable anchor, then
     hit the staggering aggregate (small first, then the gut-punch total).
   - EVERYDAY EQUIVALENCE: convert every large/abstract number into a familiar
     physical comparison the viewer can picture (pools, a town's groceries, etc.).

UNIQUE INSIDER ANGLE: Every script must include one insight that feels like insider knowledge — something a viewer could not find in 5 minutes of Googling."""

# Backward compatibility alias
WRITER_SYSTEM = WRITER_SYSTEM_FINANCE


# `_build_generation_prompt` is synchronous but is called from the async
# generate loop once per variant — three sqlite reads per script, each pulling a
# row that can carry hundreds of KB of playbook text, all on the event loop.
# Making the prompt builder async is a wider change than this pass; a short TTL
# collapses the repeats, which is where the cost actually was.
_INTEL_CACHE_TTL_SECONDS = 60.0
_INTEL_CACHE: dict[str, tuple[float, object]] = {}
_INTEL_CACHE_LOCK = threading.Lock()


def invalidate_competitor_intel_cache(scope: str | None = None) -> None:
    """Drop cached rows after a learning run rewrites them.

    Without this, discovery calling `learn_for_channel` immediately before
    production — which `server.py` does — leaves the writer serving the PREVIOUS
    playbook (or, worse, the cached absence of one) for the rest of the TTL."""
    with _INTEL_CACHE_LOCK:
        if scope is None:
            _INTEL_CACHE.clear()
        else:
            _INTEL_CACHE.pop(scope, None)


def _load_competitor_intel(scope: str, *, ttl: float = _INTEL_CACHE_TTL_SECONDS):
    """Blocking vault read, isolated so callers can see it is blocking."""
    import time as _time

    now = _time.monotonic()
    with _INTEL_CACHE_LOCK:
        cached = _INTEL_CACHE.get(scope)
        if cached and now - cached[0] < ttl:
            return cached[1]

    from pathlib import Path as _P

    from omnicast.vault import db as _vdb
    _VDB = _P(__file__).resolve().parents[3] / "output" / "vault.db"
    _vdb.init_db(_VDB)
    row = _vdb.get_competitor_intel(scope, _VDB)
    if row is None:
        # NEVER cache an absence. A run that learns intel seconds later would
        # otherwise keep seeing "nothing learned yet" — and on a channel with
        # competitor_intel_required=True that is a hard generation failure on a
        # niche whose intel was just written.
        return None
    with _INTEL_CACHE_LOCK:
        _INTEL_CACHE[scope] = (_time.monotonic(), row)
    return row


def resolve_competitor_playbook(brief, artifact: str = "script_playbook"):
    """Gate + policy for one brief, as a testable unit.

    Lives at module level on purpose. While this logic was inline in
    `_build_generation_prompt`, an audit reverted BOTH halves of it — the
    policy read and the load-failure branch — and the entire test suite stayed
    green, because nothing exercised the prompt builder's gate. A rule nothing
    can fail is not a rule."""
    from omnicast.analytics.intel_gate import (
        STATUS_ERROR,
        CompetitorIntelRequired,
        IntelDecision,
        resolve_for_writer,
    )

    # §4.2: intel is written under a channel/audience/format/market/pillar key.
    # Reading only the niche key would find nothing on every scoped row; reading
    # ONLY the specific key would find nothing on a channel's first run while a
    # usable niche-level playbook sat one row away. So walk the chain, and
    # record which level answered — a borrowed niche-wide playbook is a
    # reasonable default and a terrible thing to apply silently.
    from omnicast.analytics.intel_scope import describe_level, fallback_chain

    channel = getattr(brief, "channel", None) or brief
    chain = fallback_chain(channel, pillar_id=getattr(brief, "pillar_id", ""))
    scope = chain[0][1]
    required = bool(brief.competitor_intel_required)
    try:
        intel = None
        matched_level = ""
        for level, key in chain:
            intel = _load_competitor_intel(key)
            if intel is not None:
                scope, matched_level = key, level
                break
        if intel is not None and matched_level != "exact":
            logger.info("competitor intel borrowed from a broader scope",
                        scope=scope, level=matched_level,
                        detail=describe_level(matched_level))
    except Exception as exc:
        # Load failure is its own outcome. Passing None to the gate would report
        # it as STATUS_MISSING ("nothing learned yet"), a different fact that
        # would then be counted as one in metrics.
        decision = IntelDecision(STATUS_ERROR, reason=f"vault read failed: {exc}")
        logger.warning("competitor intel rejected", scope=scope,
                       artifact=artifact, **decision.as_dict())
        if required:
            raise CompetitorIntelRequired(
                f"{scope} requires competitor intel but the vault could not be "
                f"read: {exc}") from exc
        return decision

    return resolve_for_writer(intel, artifact=artifact, required=required,
                              scope=scope)


class WriterAgent(BaseAgent):
    """Generates script variants and revises based on critic feedback.

    Two modes:
    - generate(): Create N=3 initial variants from brief
    - revise(): Revise a single variant based on CriticFeedback
    """

    def __init__(
        self,
        llm: LLMClient,
        pattern_store: PatternStore | None = None,
    ) -> None:
        """
        Args:
            llm: LLM client for API calls
            pattern_store: Optional KB for injecting learned patterns into prompts
        """
        super().__init__(llm)
        self._pattern_store = pattern_store

    @property
    def name(self) -> str:
        return "writer"

    @property
    def system_prompt(self) -> str:
        """System prompt for script generation."""
        return WRITER_SYSTEM

    @staticmethod
    def _load_active_policy_rules() -> str:
        """Load active policy rules from vault.db and format as a compliance block.

        Returns empty string if vault is unavailable (fail-open: Writer still works
        without DB; ComplianceChecker is the hard gate before upload).
        """
        try:
            from pathlib import Path as _Path
            from omnicast.vault import db as _vdb
            _VDB = _Path(__file__).resolve().parents[3] / "output" / "vault.db"
            _vdb.init_db(_VDB)
            rules = _vdb.get_active_rules(_VDB)
            if not rules:
                return ""
            rule_lines = "\n".join(f"  - {r.get('rule_text', str(r))}" for r in rules[:20])
            return (
                "\n\nACTIVE YOUTUBE POLICY RULES (human-approved — violations cause demonetization or removal):\n"
                + rule_lines
                + "\nApply all rules above. Scripts that violate them will be rejected by compliance."
            )
        except Exception:
            return ""

    def _build_system_prompt(
        self,
        niche_cfg: NicheConfig,
        audience: dict | None = None,
        channel_brand: dict | None = None,
    ) -> str:
        """Build niche-specific system prompt from NicheConfig + channel overrides + audience.

        Priority (highest → lowest):
          channel_brand fields  >  NicheConfig defaults
        """
        # ── Channel-level overrides ──────────────────────────────────────────
        brand_voice = (channel_brand or {}).get("brand_voice", "")
        tone = (channel_brand or {}).get("tone", "")
        voice_persona = (channel_brand or {}).get("voice_persona", "")
        channel_hook = (channel_brand or {}).get("hook_format", "")

        # ── Audience block ───────────────────────────────────────────────────
        audience_block = ""
        if audience:
            pain = "\n   - ".join(audience.get("pain_points", []))
            triggers = "\n   - ".join(audience.get("content_triggers", []))
            drivers = ", ".join(audience.get("engagement_drivers", []))
            audience_block = f"""
TARGET AUDIENCE PROFILE:
   Age: {audience.get("age_range", "unknown")} | Income: {audience.get("income_level", "unknown")}
   Primary pain points:
   - {pain}
   Content triggers that drive clicks + watch time:
   - {triggers}
   Engagement drivers: {drivers}
   Preferred video length: {audience.get("preferred_video_length_min", 10)} minutes

CRITICAL: Write SPECIFICALLY for this audience. Every sentence must speak to their pain points.
Do NOT write for a general audience. This viewer has SPECIFIC fears and goals — address them directly.
"""

        # ── Channel identity block (override NicheConfig defaults) ───────────
        channel_identity_block = ""
        if brand_voice or tone or voice_persona:
            channel_identity_block = f"""
CHANNEL IDENTITY (non-negotiable — this channel has a distinct voice):
{f'   Brand voice: {brand_voice}' if brand_voice else ''}
{f'   Tone: {tone} — every sentence must feel {tone}, not generic.' if tone else ''}
{f'   Voice persona: {voice_persona} — write AS this persona. Vocabulary, cadence, and authority level must match.' if voice_persona else ''}

Every word must sound like it comes from THIS specific channel identity, not a generic narrator.
"""

        # Channel hook overrides NicheConfig hook if present
        effective_hook_format = channel_hook if channel_hook else niche_cfg.hook_format

        # NARRATIVE channels (horror/story) get a completely different, story-native
        # system prompt — the explainer scaffolding below (greeting, proof-stat,
        # data scenes) is what makes generated horror read as AI slop.
        if getattr(niche_cfg, "content_format", "explainer") == "narrative":
            return self._build_narrative_system_prompt(
                niche_cfg, channel_identity_block, audience_block,
                effective_hook_format)

        return f"""You are a professional YouTube scriptwriter specializing in {niche_cfg.insider_angle}.
{channel_identity_block}{audience_block}

YOUR SCRIPTS MUST FOLLOW THESE RULES:

1. HOOK — G.H.P Formula (first 20 seconds), in THIS order:
   G (Greeting): The VERY FIRST scene opens with a short, warm spoken greeting (≤8 words)
     then flows STRAIGHT into the topic — like a real host. E.g. "Hey, so glad you're here —
     today we're tackling [topic]." Friendly, natural, NOT corporate. (This greeting is the
     channel's on-camera welcome; write a fresh natural one each video.)
   H (Hook): IMMEDIATELY after the greeting, the single most striking line of the whole video
     — pain-first, specific, a curiosity gap they cannot ignore. THIS exact line is also used
     as the video TITLE, so make it punchy and self-contained (≤70 chars ideal).
     Format/energy: {effective_hook_format}
     Examples:
     {chr(10).join(f"  - {ex}" for ex in niche_cfg.hook_examples)}
   P (Proof): One data point from a credible source. "According to {", ".join(niche_cfg.proof_sources[:2])}..."
   [VISUAL: Show the proof source on screen — chart screenshot, report cover]

2. FORMAT — Scene-based JSON (feeds AI video tools directly):
   Every section outputs a SCENES block — a JSON array where each object is one 3-5 second screen cut:
   {{"vo": "Spoken words. MAX 25 words. Natural conversational speech ONLY.", "visual": "stock footage query, MAX 6 plain words (concrete filmable subject, never a text/graphic description)", "sfx": "alarm | cash-register | whoosh | ting | null", "pace": "slow | normal | fast", "pause_after_ms": 0, "emphasis": ["exact words from vo to stress"]}}

   HARD PROHIBITION in 'vo' — these words KILL the video if TTS reads them:
     hook, segment, B-roll, CTA, open loop, close the loop, transition, pattern interrupt,
     narration, outro, "let me show you how", "in today's video", "don't forget to",
     "as I mentioned", "moving on", "let's dive in", "let me walk you through"
   Open-loop technique uses NATURAL speech in 'vo':
     GOOD: "And there's something even worse hiding in the fine print — I'll get to that in a few minutes."
     BAD:  "[OPEN LOOP: This creates tension...]" — this would be read aloud by TTS!
   CTA uses SIMPLE natural speech:
     GOOD: "If this helped, tap Like — it tells the algorithm this content is worth sharing."
     BAD:  "What's your current expense ratio? Comment below." — too hard, kills engagement.

3. OPEN LOOPS — Place at end of segments 1 and 3:
   Write as NATURAL spoken dialogue in the 'vo' field. Never use brackets or labels.
   GOOD vo: "And that's not even the worst part — there's a second number on page 3 that's even more damaging. I'll show you in a few minutes."
   This forces viewers to stay. NEVER reveal the payoff early.

4. PATTERN INTERRUPTS every 5-8 seconds of screen time:
   - Zoom in on key number: [VISUAL: ZOOM — "$X,XXX" text fill screen]
   - B-roll cut: [VISUAL: B-ROLL — {niche_cfg.broll_style}]
   - Motion graphic: [VISUAL: ANIMATE — bar chart grows]
   - Direct address: "Pause right here. Look at your last [relevant metric]."
   - Rhetorical punch: "Ninety-three percent. Let that land."

5. LIKE CTA — place RIGHT AFTER a satisfying payoff / 'aha' moment (e.g. just after
   you reveal a concrete fix), NEVER mid-explanation (it breaks concentration). One line,
   community-framed: "If that just clicked for you — tap Like, it's how this reaches the
   people who need it." Put it at the END of a resolved section, not the middle.

6. MID-ROLL VIDEO CTA — OPTIONAL and SOFT only: "I broke this down deeper in another
   video — link's pinned in the comments." NEVER say "right here" / "click here" / any
   end-screen language mid-video — that triggers a premature exit. The "watch next"
   prompt belongs ONLY in the outro (rule 7), never before it.

7. OUTRO — keep it VERY SHORT; the spoken outro ENDS on the comment hook. Subscribe and
   the next video are shown VISUALLY by the end-card — do NOT speak them.
   (0) OPTIONAL one-line balanced take (a genuine two-sided question, not a verdict).
   (1) Comment hook — ONE line that ENDS the script: "Which surprised you most — X, Y, or Z?
       Tell me below." Then STOP.
   ABSOLUTELY FORBIDDEN after the comment hook: a spoken 'subscribe', any channel promo
   ("I share/publish every week…", "the fixes that keep…"), a recap ("most people think…
   now you know"), or a spoken 'next video / watch this' tease. The end-card handles
   subscribe + watch-next on screen.
   HARD LIMIT: the entire outro is AT MOST 2 sentences / ~25 spoken words / ~8 seconds,
   ending on the comment ask.

8. SPOKEN LANGUAGE rules:
   - Short punchy sentences. Fragments OK.
   - Conversational pivots: "Here's the thing." / "And that's the problem." / "Now watch this."
   - NO: "delve", "tapestry", "it's important to note", "in conclusion", "leverage", "utilize"
   - NO long academic paragraphs — max 3 sentences before a visual cue

9. NUMBERS — Every key number needs a visual treatment:
   - Write: [VISUAL: TEXT POPUP — "KEY STAT"] [SFX: {niche_cfg.sfx_primary}]
   - The number must appear on screen THE MOMENT it's spoken
   - SCALE FRAMING (small → staggering): when a number is meant to SHOCK, first
     disarm with a tiny relatable anchor, THEN hit the staggering aggregate.
     e.g. "one dose barely moves the needle — but stack it every day for a year
     and the damage is enormous." Small first, then the gut-punch total.
   - EVERYDAY EQUIVALENCE: never leave a large/abstract number bare. Convert it to
     a familiar physical comparison the viewer can picture — "enough to fill 2.5
     million swimming pools", "the weekly groceries of a town of 50,000", "like
     running ten air conditioners non-stop". Pair every giant number with one.

10. PREMIUM EDITORIAL — what separates a top-tier channel (Vox/Johnny Harris) from AI slop:
   a) NO MECHANICAL LISTICLE. Never structure the script as "Number one… number two… number seven".
      Group points by MECHANISM or theme with named, curiosity-driving headings
      (e.g. "The Fat Paralysis", "The Roughage Blockade", "The Acid Burn") and connect them with a narrative arc.
   b) SHOW, DON'T READ (citations). The 'vo' states findings QUALITATIVELY — "the latest data shows…",
      "researchers found something brutal…". NEVER read the source aloud ("a 2023 X-journal review found…").
      Put the source NAME in the 'visual' field instead (e.g. visual: "PubMed study page on screen, title highlighted")
      so the proof appears on screen while the voice stays human.
   c) METAPHOR FOR MECHANISM. Every abstract physiological/technical process gets ONE vivid, FILMABLE metaphor
      (slowed stomach → "your stomach turns from a highway into a clogged alley; fat is the truck flipped across it").
      The metaphor's 'visual' must be a real filmable scene (traffic jam, flipped truck), not an idiom.
   d) EMPATHY, NOT SAFE. Name the real lived sensation — "food fermenting and foaming", "stuck in your throat
      six hours after eating", "losing an entire weekend to it". Make the viewer feel understood.
   e) CTA FROM EMPATHY. Replace boilerplate ("hit like, it keeps this channel going") with a shared-experience line
      ("If you've ever cancelled plans because you ate the wrong thing on Ozempic — tap like so I know we're not alone").

11. FLOW & ANTI-FORMULA (kills the "I can predict the next section" boredom that drops retention):
   a) VARY each section's OPENING — do NOT open every mechanism the same way (e.g. always body-science).
      Rotate: a 1-line mini-story / a common misconception ("Everyone thinks X — wrong") / a direct
      question / a surprising stat / a 'pull the fix forward then explain why'. Each section opens differently.
   b) BRIDGE between sections with a momentum sentence so it flows like one video, not article headings:
      "But [previous mechanism] isn't the only trap — pair it with this next mistake and your stomach
      has no chance." Never hard-cut from one heading straight into dry science.
   c) Occasionally lead a section with the TIP first, then explain WHY it works (curiosity inversion).

12. PAYOFF & PROMISE INTEGRITY (every promise you open MUST be closed — else it reads as clickbait):
   a) HOOK PAYOFF: any specific NUMBER or claim in the hook (e.g. "costs $3,600 a year", "4 foods")
      MUST be explicitly explained/resolved later in the body. If the hook says a dollar cost, one
      body line must say exactly where that cost comes from. Never drop a hook number unexplained.
   b) OPEN-LOOP WORDING MATCHES PAYOFF: the tease must be literally true of its reveal. If the culprit
      you later reveal is a DRINK (coffee, soda), do NOT tease it as "something people EAT" — use
      "consume"/"have"/"start their day with". The promise and the resolution must not contradict.
   c) ONE VIDEO SUGGESTION, AT THE END ONLY: never point to another video mid-script ("it's right
      here"/"watch this next" before the outro). At most ONE soft "pinned in the comments" mid-roll,
      and it must be the SAME topic as the outro's Next tease — never two different videos.

13. PROSODY — delivery direction per scene (modeled on the highest-retention narration style;
    a flat, even-paced voice is the #1 "AI slop" tell and kills retention):
   Every scene sets "pace", "pause_after_ms", and "emphasis":
   a) pace map (role of the line decides the speed):
      - "slow"  → greeting + hook scenes (lean in, weighty), the single most shocking stat or
        conclusion of each segment (let it LAND), and the outro/comment hook.
      - "fast"  → explanation runs, build-up chains, enumeration/montage lines, the high-energy
        climax where facts stack up rapid-fire.
      - "normal"→ everything else. TARGET MIX across the whole script: roughly 15-25% slow,
        25-40% fast, rest normal. A script where every scene is "normal" is a FAILURE.
   b) pause_after_ms — a deliberate silence AFTER the scene (the editor cuts breaths, so any
      pause that exists must be INTENTIONAL):
      - 400-700 after a twist reveal, a rhetorical question, or right before a chapter turn.
      - 800-1500 for the 2-4 biggest dramatic beats of the video (e.g. after the hook's
        gut-punch number, before the final answer is revealed). Use sparingly: 3-6 pauses
        >=400ms TOTAL per 10 minutes. Everything else stays 0 (back-to-back flow).
   c) emphasis — 1-3 EXACT words copied verbatim from this scene's vo that deserve a vocal
      spike: big numbers ("2.5 million"), strong adjectives ("enormous"), the twist word.
      Scenes with a key stat MUST list the stat in emphasis.
   d) Pace must CONTRAST: after 3+ consecutive fast scenes, force a slow or pause beat
      (pattern: build-build-build-LAND). Never more than 6 same-pace scenes in a row.

UNIQUE INSIDER ANGLE: Every script must include one insight that feels like insider knowledge — something a viewer could not find in 5 minutes of Googling.""" + self._load_active_policy_rules()

    async def execute(
        self,
        brief: TopicBrief,
        *,
        num_variants: int = 3,
        niche_cfg: NicheConfig | None = None,
        audience: dict | None = None,
        channel_brand: dict | None = None,
    ) -> list[ScriptDraft]:
        """Generate script variants from brief.

        Args:
            channel_brand: Channel-level identity overrides extracted from ChannelProfile.
                Keys: brand_voice, tone, hook_format, voice_persona.
                These take precedence over NicheConfig defaults.
        """
        variants = []

        # Get niche config if not provided
        if niche_cfg is None:
            niche_cfg = get_niche_config(brief.niche.value, brief.sub_niche)

        # Build system prompt: NicheConfig base + channel overrides on top
        system = self._build_system_prompt(niche_cfg, audience=audience, channel_brand=channel_brand)
        is_narrative = getattr(niche_cfg, "content_format", "explainer") == "narrative"

        # Fetch patterns if available
        patterns = []
        if self._pattern_store:
            patterns = await self._pattern_store.get_patterns_for_brief(
                brief_text=brief.title,
                niche=brief.niche,
                limit=3,
            )

        # Scene JSON overhead is ~5x the spoken words (visual/prosody fields):
        # a 1,500-word script needs ~18-20k output tokens. 12k silently TRUNCATES
        # Claude drafts under the word floor → 2 extra $0.14 expand calls per run
        # (measured 2026-07-08). Claude supports large outputs — give it headroom;
        # DeepSeek keeps the old cap (its API limit).
        _is_claude = "claude" in str(getattr(self._llm, "_model", "")).lower()
        _gen_tokens = 22000 if _is_claude else 12000

        for i, angle in enumerate(ANGLES[:num_variants]):
            variant_id = chr(ord("A") + i)
            # Warm the intel cache OFF the loop before the (synchronous) prompt
            # builder reads it. Otherwise `_build_generation_prompt` opens
            # sqlite on the event loop once per variant. The TTL cache alone
            # only reduced how often that happened; this moves it.
            await asyncio.to_thread(_load_competitor_intel, brief.niche.value.lower())
            prompt = self._build_generation_prompt(brief, angle, patterns, niche_cfg)

            try:
                response = await self.call_llm(
                    [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    max_tokens=_gen_tokens,
                )
                draft = self._parse_draft(response.content, variant_id, brief.title)
                # One-pass DeepSeek tops out ~1000 words; a single video needs 8+ min
                # for mid-roll ads. If short, run an expand pass that ADDS scenes to
                # reach the word floor (keeps the ≤25-word/scene caption discipline).
                draft = await self._ensure_length(
                    draft, brief, system, response.content, variant_id,
                    narrative=is_narrative)
                # Narrative CONTINUITY SELF-CHECK — the #1 reason horror scripts get
                # capped at 65 is a hook↔body / timeline / prop contradiction the
                # writer didn't notice. One focused pass finds + fixes them BEFORE
                # the critic ever sees it.
                if is_narrative:
                    draft = await self._continuity_pass(draft, brief)
                variants.append(draft)
            except Exception as exc:
                raise AgentError(f"Failed to generate variant {variant_id}: {exc}") from exc

        logger.info("Writer generated variants", count=len(variants), brief=brief.title)
        return variants

    def _build_continuity_prompt(self, draft: ScriptDraft, brief: TopicBrief) -> str:
        script = draft.raw_content or ""
        recent_rules = [
            str(point) for point in (brief.key_points or [])
            if str(point).startswith("DO NOT REUSE from recent videos")
        ]
        history_block = ""
        if recent_rules:
            history_block = (
                "\nRECENT CHANNEL HISTORY — HARD CONSTRAINT:\n"
                + "\n".join(recent_rules)
                + "\nRename every reused character consistently throughout its story and replace "
                  "any banned recurring prop/motif without changing the plot.\n"
            )
        return f"""You are the FINAL QUALITY EDITOR for a first-person true-horror compilation
(HOOK, several SEGMENTs, OUTRO — each with a SCENES: JSON array). Make only targeted
repairs. Keep every clean scene exactly as-is. PRESERVE the core fight-or-flight action,
physical danger, strongest image, narrator voice, story count, and approximate word count.
Never solve a flaw by making the protagonist passive or deleting the chase/escape/defense.

PASS 1 — BUILD A PRIVATE CONTINUITY LEDGER for each story, then repair every conflict:
1. HOOK ↔ BODY: whatever the hook/intro promises MUST be delivered exactly. A narrator
   must NOT pre-summarise or speak for the other stories ("one of us called, one ran"),
   and MUST NOT claim an action a story later contradicts (e.g. hook says "one ran, one
   called" but the same person both runs AND calls 911). If the intro over-promises, cut
   the promise; do not leave it unmet.
2. PREMISE: every story must fit the video's premise/title. A "walking home" video cannot
   contain someone who drives home and walks from their driveway.
3. TIMELINE: dates, nights, seasons, shifts and durations must agree. Do not have one electrician visit
   and then say the manager still needs to call the electrician. Do not
   start an 11-to-7 shift and require the worker to lock up and leave at 6 without explanation.
4. COUNTS: people / witnesses / objects must add up. If only one van remains, the narrator
   cannot later write down four plates. If one object left, there is only one object to count.
5. POSITIONS: track narrator, threat, vehicle, doors and routes. If the hook says a truck
   comes up the road with its lights off, the body cannot say the truck is already parked
   unless it clearly leaves and returns.
6. PROPS: a named prop introduced must pay off or at least not vanish unexplained.
7. ACTION ORDER: the sequence must be physically possible (can't back off the porch AND
   punch the door code twice without explaining when she approached).

PASS 2 — REMOVE MACHINE-MADE AUTHENTICITY:
8. CORROBORATION BUDGET: at most ONE aftermath/corroboration beat per story, and at least
   one story must have ZERO. Camera/static failure, police or ranger confirmation, tracks,
   records, witness confirmation, a later message, and a recurrence all count. Keep the
   single strongest one; cut the rest. Never make paranormal proof mechanically exact.
9. SPECIFICITY BUDGET: no more than FOUR exact numeric anchors per story and no more than
   one precise clock time. Exact numbers stay only when they affect a decision, distance,
   timing, or spatial logic. Replace arbitrary durations/counts with natural phrasing or cut.
10. ENDING DIVERSITY: every story must use a different ending shape. No two stories may
    end with later evidence proving the threat selected, knew, or followed the narrator.
    End within one or two beats of the strongest image/action; remove explanatory codas.
11. VOICE / AI RESIDUALS: each narrator needs distinct sentence rhythm, vocabulary and
    dialogue habits. Delete all stock self-reassurance ("I told myself", "I figured it was",
    "I convinced myself", "I wanted to believe"). Show doubt through an action or bad choice.

After editing, privately re-run the ledger against the FULL script. Do not output the ledger.
{history_block}

Output the FULL corrected script in the EXACT same format (HOOK:, SEGMENT N: <heading>,
OUTRO:, each followed by SCENES: and a valid JSON array of the same scene objects with the
same fields). No commentary. If there are genuinely no contradictions, output it unchanged.

CURRENT SCRIPT:
{script}"""

    async def _continuity_pass(self, draft: ScriptDraft, brief: TopicBrief) -> ScriptDraft:
        """One focused LLM pass that fixes hook↔body / timeline / prop / premise
        contradictions before the critic sees the draft. Returns the corrected draft,
        or the original if the pass fails or comes back suspiciously short."""
        if not (draft.raw_content or "").strip():
            return draft
        try:
            _mt = 22000 if "claude" in str(getattr(self._llm, "_model", "")).lower() else 12000
            resp = await self.call_llm(
                [{"role": "user", "content": self._build_continuity_prompt(draft, brief)}],
                max_tokens=_mt)
            fixed = self._parse_draft(resp.content, draft.variant_id, brief.title,
                                      version=draft.version)
            if fixed and self._word_count(fixed) >= int(self._word_count(draft) * 0.7):
                logger.info("Writer continuity pass applied", variant_id=draft.variant_id,
                            before=self._word_count(draft), after=self._word_count(fixed))
                return fixed
            logger.warning("Continuity pass output too short — keeping original",
                           variant_id=draft.variant_id)
        except Exception as exc:
            logger.warning("Continuity pass skipped", variant_id=draft.variant_id, error=str(exc))
        return draft

    def _word_count(self, draft: ScriptDraft) -> int:
        """Count every spoken scene, including hook and outro.

        The old segment-only count under-reported real narration and could trigger
        another full-script expansion even when the missing words lived entirely
        in the hook/outro allowance.
        """
        scenes = list(draft.hook_scenes or []) + [
            sc for seg in draft.segments for sc in (seg.scenes or [])
        ] + list(draft.outro_scenes or [])
        return sum(len(sc.voiceover.split()) for sc in scenes)

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        """Extract the first JSON object from an LLM response."""
        clean = re.sub(r"```(?:json)?", "", text or "").strip()
        start = clean.find("{")
        if start < 0:
            return {}
        candidate = clean[start:]
        decoder = json.JSONDecoder()
        for value in (
            candidate,
            re.sub(r",\s*([\]}])", r"\1", candidate),
        ):
            try:
                parsed, _ = decoder.raw_decode(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                continue
        return {}

    def _apply_narrative_expansion_patch(
        self,
        draft: ScriptDraft,
        payload: dict,
        brief_title: str,
    ) -> ScriptDraft:
        """Insert only newly generated scenes into a narrative draft.

        Patch indices refer to the original segment scenes. Applying insertions
        from the highest index down keeps every original index stable.
        """
        by_segment: dict[int, list[dict]] = {}
        for item in payload.get("insertions", []):
            if not isinstance(item, dict):
                continue
            try:
                segment_index = int(item.get("segment_index"))
                after_index = int(item.get("after_scene_index", -1))
            except (TypeError, ValueError):
                continue
            raw_scenes = item.get("scenes", [])
            if not isinstance(raw_scenes, list) or not raw_scenes:
                continue
            parsed_scenes = self._parse_scenes_json(
                "SCENES:\n" + json.dumps(raw_scenes, ensure_ascii=False))
            if not parsed_scenes:
                continue
            by_segment.setdefault(segment_index, []).append({
                "after": after_index,
                "scenes": parsed_scenes,
            })

        if not by_segment:
            return draft

        changed = False
        updated_segments: list[ScriptSegment] = []
        for segment in draft.segments:
            insertions = by_segment.get(segment.index, [])
            if not insertions:
                updated_segments.append(segment)
                continue
            scenes = list(segment.scenes or [])
            for insertion in sorted(insertions, key=lambda x: x["after"], reverse=True):
                position = max(0, min(len(scenes), insertion["after"] + 1))
                scenes[position:position] = insertion["scenes"]
                changed = True
            updated_segments.append(segment.model_copy(update={
                "scenes": scenes,
                "content": " ".join(sc.voiceover for sc in scenes),
                "estimated_duration_seconds": max(
                    30, int(sum(sc.duration_s for sc in scenes))),
            }))

        if not changed:
            return draft
        staged = draft.model_copy(update={"segments": updated_segments})
        serialized = self._draft_to_script_text(staged)
        return self._parse_draft(
            serialized, draft.variant_id, brief_title, version=draft.version)

    def _build_expansion_prompt(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        *,
        words: int,
        floor: int,
        previous_script: str,
        narrative: bool,
    ) -> str:
        """Build a format-aware expansion prompt.

        The explainer recipe (data points, objections, statistics) creates fake
        corroboration when it is accidentally applied to a horror narrative.
        """
        need = floor - words
        target_min = max(8, int(brief.target_duration_min or 0))
        if narrative:
            return (
                f"The horror script below is only {words} spoken words (~{words/150:.0f} min) — "
                f"too short for a {target_min}-minute video. ADD {need}–{need + 120} words "
                "as NEW scenes with causal story beats: a clearer physical "
                "layout, an obstacle that changes the protagonist's options, a plausible "
                "decision under pressure, short natural dialogue, and consequences of an "
                "action already present. Preserve the story count, distinct voices, threat "
                "types, ending shapes, and strongest fight-or-flight moments.\n"
                "Do NOT add statistics, official records, police/ranger confirmation, camera "
                "failure, extra witnesses, supernatural proof, arbitrary exact numbers, a "
                "second aftermath beat, or a later recurrence merely to fill space. Do NOT "
                "repeat or re-describe an existing scare. Keep each vo line <=28 words.\n"
                "Return exactly one JSON object with this schema:\n"
                '{"insertions":[{"segment_index":1,"after_scene_index":4,'
                '"scenes":[{"vo":"...","visual":"max 6 words","sfx":null,'
                '"pace":"slow|normal|fast","pause_after_ms":0,"emphasis":[]}]}]}\n'
                "segment_index is the printed SEGMENT number. after_scene_index is ZERO-BASED "
                "in the ORIGINAL segment (-1 means prepend). Do NOT output the full script, "
                "unchanged scenes, commentary, markdown, HOOK, or OUTRO.\n\n"
                f"CURRENT SCRIPT:\n{previous_script}"
            )
        return (
            f"The script below is only {words} spoken words (~{words/150:.0f} min) — too "
            f"short for a {target_min}-minute video. EXPAND it to at least {floor} "
            f"words (add ~{need}+ more) by INSERTING additional scenes into the "
            "existing segments: more data points, concrete examples, short "
            "mini-stories, objections + rebuttals, step-by-step detail. Keep EVERY "
            "vo line 18-25 words (never longer). Keep the same HOOK/SEGMENT/OUTRO "
            "structure and JSON format INCLUDING the prosody fields (pace, "
            "pause_after_ms, emphasis) on every scene — new scenes get them too "
            "(explanation runs = fast). Output the FULL expanded script only.\n\n"
            f"CURRENT SCRIPT:\n{previous_script}"
        )

    async def _ensure_length(self, draft, brief, system, prev_json, variant_id,
                             max_passes: int = 4, narrative: bool = False):
        """Expand a too-short draft until it clears the target length (scaled to
        this brief's target_duration_min, never below the 8-min mid-roll floor).
        Adds NEW scenes per segment; never lengthens individual vo lines."""
        floor = spoken_word_floor(brief.target_duration_min)
        if narrative:
            # Narrative expansion is a PATCH, never a full-script rewrite. One
            # pass per caller prevents the $0.10 → $0.60 runaway observed when
            # Claude re-emitted a growing 10k-token storyboard four times.
            words = self._word_count(draft)
            if words >= floor:
                return draft
            expand = self._build_expansion_prompt(
                draft, brief, words=words, floor=floor,
                previous_script=prev_json, narrative=True)
            try:
                need = max(1, floor - words)
                resp = await self.call_llm(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": expand}],
                    max_tokens=min(10000, max(3000, need * 10)),
                )
                payload = self._parse_json_object(resp.content)
                grown = self._apply_narrative_expansion_patch(
                    draft, payload, brief.title)
                if self._word_count(grown) > words:
                    logger.info(
                        "Writer narrative patch expansion applied",
                        variant_id=variant_id, before=words,
                        after=self._word_count(grown))
                    return grown
                logger.warning(
                    "Narrative expansion patch made no progress — keeping original",
                    variant_id=variant_id)
            except Exception as exc:
                logger.warning(
                    "Narrative expansion patch skipped",
                    variant_id=variant_id, error=str(exc))
            return draft

        for _ in range(max_passes):
            words = self._word_count(draft)
            if words >= floor:
                break
            expand = self._build_expansion_prompt(
                draft, brief, words=words, floor=floor,
                previous_script=prev_json, narrative=narrative)
            try:
                _mt = 22000 if "claude" in str(getattr(self._llm, "_model", "")).lower() else 14000
                resp = await self.call_llm(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": expand}],
                    max_tokens=_mt,
                )
                grown = self._parse_draft(resp.content, variant_id, brief.title)
                if self._word_count(grown) > words:
                    draft, prev_json = grown, resp.content
                else:
                    break  # no progress — stop
            except Exception:
                break
        return draft

    def _draft_to_script_text(self, draft: ScriptDraft) -> str:
        """Serialize a parsed ScriptDraft back into the HOOK/SEGMENT/SCENES text
        format that the expand pass (and `_parse_draft`) consume — lets a draft
        produced OUTSIDE `execute()` (e.g. the evolved winner) be fed through
        `_ensure_length`. Prosody fields are preserved so an expand keeps them."""
        def _block(scenes) -> str:
            objs = [{
                "vo": sc.voiceover,
                "visual": sc.visual_prompt,
                "sfx": sc.sfx or "null",
                "pace": getattr(sc, "pace", "normal") or "normal",
                "pause_after_ms": int(getattr(sc, "pause_after_ms", 0) or 0),
                "emphasis": list(getattr(sc, "emphasis", []) or []),
            } for sc in scenes]
            return "SCENES:\n" + json.dumps(objs, ensure_ascii=False)

        parts = ["HOOK:", _block(draft.hook_scenes or [])]
        for seg in draft.segments:
            parts.append(f"\nSEGMENT {seg.index}: {seg.heading}")
            parts.append(_block(seg.scenes or []))
        parts.append("\nOUTRO:")
        parts.append(_block(draft.outro_scenes or []))
        return "\n".join(parts)

    async def ensure_length(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        *,
        niche_cfg: NicheConfig | None = None,
        channel_brand: dict | None = None,
        audience: dict | None = None,
    ) -> ScriptDraft:
        """Word-floor enforcement for a draft built OUTSIDE `execute()` (the
        evolution merge). The evolved draft is what WINS, so it must clear the
        same ~8-min mid-roll floor the generated variants do. Rebuilds the system
        prompt + serializes the draft, then reuses the same expand loop."""
        if niche_cfg is None:
            niche_cfg = get_niche_config(brief.niche.value, getattr(brief, "sub_niche", None))
        system = self._build_system_prompt(
            niche_cfg, audience=audience, channel_brand=channel_brand)
        prev_json = self._draft_to_script_text(draft)
        return await self._ensure_length(
            draft, brief, system, prev_json, draft.variant_id,
            narrative=getattr(niche_cfg, "content_format", "explainer") == "narrative")

    async def revise(
        self,
        draft: ScriptDraft,
        feedback: CriticFeedback,
        brief: TopicBrief,
        *,
        niche_cfg: NicheConfig | None = None,
        channel_brand: dict | None = None,
        audience: dict | None = None,
    ) -> ScriptDraft:
        """Revise a draft based on critic feedback."""
        if niche_cfg is None:
            niche_cfg = get_niche_config(brief.niche.value, getattr(brief, "sub_niche", None))
        prompt = self._build_revision_prompt(
            draft, feedback, brief, niche_cfg=niche_cfg)

        try:
            _mt = 22000 if "claude" in str(getattr(self._llm, "_model", "")).lower() else 12000
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                max_tokens=_mt,
            )
            revised = self._parse_draft(
                response.content,
                draft.variant_id,
                brief.title,
                version=draft.version + 1,
            )
            # A revision is exactly ONE paid rewrite. Length fill and quality
            # validation belong to the caller, which can inspect critic routing
            # before deciding whether another call is justified.
            logger.info("Writer revised draft", variant_id=draft.variant_id, new_version=revised.version)
            return revised
        except Exception as exc:
            # A revision is an OPTIONAL improvement pass. If the LLM call fails
            # (auth/rate-limit/timeout/empty output), NEVER throw away the draft we
            # already have — degrade to a no-op and keep the original. The caller
            # keeps whichever score is higher, so a failed revise can't regress or
            # crash the whole pipeline (previously: expired claude -p token nuked a
            # draft that had already scored 84 / both-groups-pass).
            logger.warning("Writer revise failed — keeping original draft",
                           variant_id=draft.variant_id, error=str(exc))
            return draft

    def _build_narrative_system_prompt(
        self,
        niche_cfg: NicheConfig,
        channel_identity_block: str,
        audience_block: str,
        effective_hook_format: str,
    ) -> str:
        """Story-native system prompt for first-person narrative channels
        (horror/true-story). Keeps the JSON scene format + prosody machinery the
        parser/renderer need, but strips ALL explainer scaffolding: no greeting,
        no 'according to' proof, no statistics, no charts, no CTA-heavy outro."""
        return f"""You are a master first-person horror storyteller who writes narration for a faceless YouTube channel in the style of Mr. Nightmare, Lets Read, and Be. Busta.
{channel_identity_block}{audience_block}
VOICE / ROLE: {niche_cfg.insider_angle}

You are writing a compilation of {{N}} allegedly-true first-person stories (usually 3) told back-to-back. Each story is narrated by the person it happened to, as "I / we", in a plain, slightly shaken everyday voice. You ARE that person — never a host introducing someone else's tale.

═══ THE 7 LAWS OF DREAD (break any one and the video fails) ═══

1. COLD OPEN — NO GREETING, NO CHANNEL TALK. The very first line drops the listener straight inside the world. Either one chilling line from the scariest moment then pull back to the beginning, OR the quiet ordinary detail that will later curdle. NEVER "Hey guys", "welcome back", "today's video", "our first story comes from…". {effective_hook_format}

2. NO META-FRAMING, EVER. Forbidden phrases (they instantly break immersion): "this account comes from", "in her own words", "word for word", "according to", "the storyteller wrote", "sent to me", "a viewer submitted", "this is a true story", "case file", "report states". Do not announce that it is true — SHOW it through mundane specific detail. The only authority is "this happened to me."

3. GROUND IT, THEN BREAK IT — BUT VARY THE PACE. Establish an ordinary, relatable situation before the horror. HOW LONG you linger must differ per story: some open slow with a real runway; at least one should drop the listener into a fast, single-night, few-hours nightmare with almost no runway (compressed pacing scares differently). Make the ordinary REAL with:
   • SENSORY GROUNDING — the exact smell, the temperature, the sound the place makes. But keep it to 1-2 details, not a catalogue; a real person doesn't inventory a room.
   • ONE, MAYBE TWO grounded props — only if a prop actually PAYS OFF or earns credibility later. Do NOT drop in a thermos / keyring / worn logbook just to hit a "specificity" quota; unused props read as a checklist.
   • Rationalization may exist as behavior, never as a stock inner sentence. "I told myself", "I figured it was", "I convinced myself", and "I wanted to believe" are BANNED. Show uncertainty through checking, hesitation, dialogue, or a wrong decision.
   Escalate in concrete physical steps. Never explain the cause; you may leave it unresolved OR resolve it as a real human threat (see Law 7).

4. FEAR IS PHYSICAL, NEVER NAMED. Never write "I was scared/terrified/creeped out". Show the body: breath held, hand frozen on the door, the back-of-neck cold, legs that won't move, the heart heard in the ears. Let the listener supply the emotion.

5. THE THREAT MUST VARY — AND IT MUST ACT. Never resolve every scare to "a tall figure standing still, watching." That single image is now the generator's fingerprint — BANNED as the default. Across the three stories the KIND of threat must differ, and in EVERY story the threat eventually DOES something with real, physical consequence:
   • Sometimes it is a REAL PERSON (an intruder, a stalker, an unstable man) who acts violently — forces the door, runs at you, screams through it, smashes a window, is under the bed, grabs an ankle. This is the most visceral and belongs in at least one story (see Law 7).
   • Sometimes it is a SOUND, a wrongness in a place, something found, a call that shouldn't come — not a figure at all.
   • When it IS an uncanny figure, it must MOVE or ACT before the story ends (closes distance impossibly fast, is suddenly at the glass, is gone when you look back) — not just stand and stare for the whole account. "Almost-human but wrong" is a fine flavor, but stillness alone is not a climax.
   NEVER fangs/claws/gore or a described monster. The fear is what it DOES and what it wants, not how tall it stood.

6. ENDINGS THAT LINGER — AND MUST VARY. End shortly after the peak, on a quiet line that refuses to fully explain: NO "experts say", no debunk, no neat bow. But do NOT end every story the same way — an ending SHAPE repeated across stories is predictable and kills the dread. Rotate the KIND of ending (see the STRUCTURE menu below): the recontextualizing twist (a planted ordinary detail returns with cold new meaning) is only ONE option — powerful, but formulaic if it's always the move. Stop on the STRONGEST image — do NOT tack on three or four "I still…" sentences telling the listener how to feel. One quiet closing line, then silence.

7. REAL PEOPLE, REAL STAKES — mostly HUMAN threats. The scariest true stories are about PEOPLE (a stalker, a home invader, a man who followed you, someone in the back seat) — "it could happen to anyone" is what terrifies. HARD RULE: at least TWO of the three stories are entirely HUMAN-caused, with NO supernatural element at all. At MOST ONE story may be ambiguous-paranormal, and even then it must NEVER show impossible proof (no object teleporting onto a figure, no ghost returning a dead child's shirt then vanishing, no dead phone line ringing, no figure that dissolves). If it can't have happened to a real person, cut it.
   The narrator ACTS on fear (fight-or-flight): calls 911 (police slow / find nothing / too late), grabs a bat, locks the door, floors the gas, climbs out a window. BANNED: a passive narrator who "sits and waits for morning".
   BANNED "AI trying to prove it's true" PROOF-STACKING: a real person does NOT cite sheriff logs, annual crime reports, DMV records, safety audits, Ring-camera timestamps, "the same tread width", or 800-day-old footage. At most ONE aftermath/corroboration beat per story; at least one story has none. Under-confirm.

═══ VOICE — RAW, NOT LITERARY (this is where AI slop shows most) ═══
- Write like a real person posting on r/LetsNotMeet, NOT like a novelist. Plain, conversational, sometimes blunt. Short sentences, especially when scared — fragments are fine under panic. AVOID polished metaphor and lyrical description ("static came and went with the wind", "coffee steam stopping mid-air" = too writerly, cut it). A frightened person is not composing prose.
- GIVE EACH OF THE 3 STORIES A DIFFERENT NARRATOR VOICE (they are different people). Vary: age, region/slang, education level, how skeptical they are, whether they use dark humor, sentence length, how they remember dialogue. If all three sound like the same careful writer, you have failed. A trucker, a college kid, and a retired nurse do not talk alike.
- Real memory is MESSY: a slightly off detail, an aside that goes nowhere, an admission they did something dumb, a bit of gallows humor. Perfect, evenly-paced recollection reads as fake.
- QUOTE key dialogue verbatim in your own voice ("open up", a text that said "don't come upstairs"). NAME the ordinary people around you (a coworker, a sibling) — bystanders make it real; the threat stays unnamed. Anchor with throwaway specifics only a real memory carries — but never "this is a true story".
- Do NOT reuse character names, props, or settings across stories or across videos.

═══ BLACKLIST — these phrases/moves are AUTO-FAIL if they recur ═══
- "I told myself it was just…" (zero uses), "tall and completely still / standing perfectly still / motionless", "I didn't check / I never went back", "I still don't know what it was" as a coda.
- The rule of THREE (three knocks, three nights, three taps). Use messy, uneven numbers or none.
- Day-by-day escalation labels ("the first night… the second night… the third night"). Compress time or vary it.
- Over-used filler words: trim roughly 20% of "still", "never", "same", "exactly", "just".
- A figure at the tree line / end of the hall / edge of the light that only watches. If a figure appears, it must eventually act (Law 5).
- SELF-REASSURANCE PATTERN (the #1 AI tell): "I told myself…", "I wanted to believe…", "I figured it was…", "I convinced myself…", "I told myself maybe…". BANNED entirely. A scared person REACTS (looks, runs, freezes, grabs something) — they do not narrate a reasonable excuse before every beat. Show the doubt through action, not a stock inner line.
- APHORISTIC / PHILOSOPHICAL CODA: "Some things you don't want an explanation for…", "Some questions are better left unanswered…", "Some things you let stay a maybe…". BANNED. Real people end blunt — on an action, a fact, or a changed habit ("I quit that week"), never a fortune-cookie moral.
- INTRO WRAPPER that speaks for other narrators or spoils the stories: "One of us called the cops, one of us ran…", "we found out later how the nights lined up". BANNED — the first narrator cannot know or pre-summarise the other two accounts. Each story opens in its OWN voice.
- IDENTICAL ENDINGS: do NOT end all (or even two) stories with the same "an official source confirmed something + a third party saw it too + it still happens" recurrence beat. Vary the ending KIND per story (Law 6).
- PROOF-STACKING (see Law 7): sheriff logs, DMV records, annual crime reports, safety audits, camera timestamps, "same tread width", old footage. A real account does not read like a case file.

═══ STRUCTURE ═══
- A short cold-open hook (1-3 scenes) that becomes the video TITLE line — self-contained, ≤70 chars ideal, first-person, curiosity-gap ("I only stopped driving Route 9 after what stood in my headlights.").
- Then each story is one SEGMENT. Segment heading = an evocative 2-4 word place/phrase ("Mile Marker Twelve", "The Fourth Floor"), NOT "Story 1".
- STRUCTURE — VARY IT DELIBERATELY (this is a hard requirement). Horror dies when every story has the same shape; a channel where each account is "ordinary day → thing appears → planted object returns at the end" is instantly predictable. Build each story from a PALETTE of movements, arranged and ended DIFFERENTLY from the other stories in this video AND from your usual default. Never run the same shape twice in a row.
  PALETTE OF MOVEMENTS (draw what the story needs, in whatever order serves it — NOT a checklist to run 1-2-3): a casual trustworthy frame; a mundane runway that plants ordinary details; a normal complication that traps the narrator; a first wrong thing they rationalize away; escalation in physical steps; a worst moment of contact or recognition; a grounded practical aftermath (police/locksmith/report); a time-jump; a returning detail. Some stories use most of these; some skip several. A story can open IN the wrong moment and flash back, or stay entirely in one unbroken night.
  PICK A DIFFERENT SHAPE + ENDING per story (rotate — do NOT default to the same one every time):
    • TWIST PAYOFF — a planted ordinary detail returns with a cold new meaning. Strong, but must NOT be every story's ending.
    • PURE AMBIGUITY — never confirm what it was; a mundane explanation and a terrible one stay equally possible.
    • SLOW-BURN, NO RESOLUTION — the wrongness simply never resolves or stops; the dread is the absence of any answer.
    • FALSE ENDING — it seems over, relief lands, then one last beat pulls back in.
    • UNRELIABLE NARRATOR — a late detail makes the listener quietly doubt the narrator's own account or memory.
    • NOT ABOUT YOU — the narrator realizes they only witnessed something with its own purpose, indifferent to them.
    • ESCALATING RECURRENCE — the same wrong thing returns, worse, implying it never really ended.
  Also vary the SETTING and the KIND of wrong thing across the stories (a silent presence, a wrong sound, a place that shouldn't exist, a person who's subtly off, something found that shouldn't be there) so the accounts don't blur together.
- A brief OUTRO: one or two calm personal lines from the LAST narrator, staying fully in character (still the survivor, not a channel host). NO call-to-action — no "comment your story", no "vote which room next", no "I read every one". Those break the first-person spell and expose the format. Just a quiet human sign-off, then stop.

═══ OUTPUT FORMAT — scene-based JSON (one object per 3-6 second screen cut) ═══
Each scene object:
  "vo"     — the spoken narration for this cut. MAX ~28 words. RAW, CONVERSATIONAL first-person — how a real shaken person actually talks, not a novelist. Short sentences; fragments are fine at tense moments. Avoid lyrical metaphor. ZERO production jargon (never the words: hook, segment, b-roll, outro, cut, scene, narrator).
  "visual" — a concrete filmable REAL query, MAX 6 plain words (e.g. "dark warehouse aisle single light", "empty night gas station"), OR for a scare money-shot prefix with "photoreal grainy" (e.g. "photoreal grainy silhouette end of aisle"). Never text/graphics/charts.
  "sfx"    — null almost always (this channel runs silent — dread comes from restraint). Rare "whoosh" only at a hard chapter turn.
  "pace"   — "slow" | "normal" | "fast". Horror leans SLOW: hooks, worst moments and lingering lines are slow; brief escalations can be normal/fast. Target ~30-45% slow.
  "pause_after_ms" — 0 for flowing lines; 600-900 after a wrong-thing reveal; 1000-1600 for the 3-5 biggest dread beats (after the worst moment, before a turn). Silence IS the scare — use pauses deliberately.
  "emphasis" — 1-3 EXACT words from this vo to vocally stress (the wrong detail, a distance, a number of nights). [] if none.

Output the same section labels the parser expects: a HOOK: block, then SEGMENT N: <heading> blocks, then an OUTRO: block, each followed by SCENES: and a valid JSON array. Output JSON arrays only inside SCENES.

LENGTH: write to the target minutes given in the user prompt (~150 spoken words/minute). A rich, immersive, unhurried told story — do NOT pad with repetition; add texture and sensory detail instead.""" + self._load_active_policy_rules()

    def _build_narrative_generation_prompt(
        self,
        brief: TopicBrief,
        niche_cfg: NicheConfig,
    ) -> str:
        """Story-native user prompt (no angle/stat/proof scaffolding)."""
        hook_ex = niche_cfg.hook_examples[0] if niche_cfg.hook_examples else \
            "I only stopped driving that road after what stood in my headlights."
        kp = "\n".join(f"- {p}" for p in (brief.key_points or [])) or \
            "- (invent 3 distinct, mundane-turned-wrong first-person encounters that fit the topic)"
        return f"""Write a production-ready first-person HORROR NARRATION script for {brief.target_duration_min} minutes (~{brief.target_duration_min * 150} spoken words).

TOPIC / TITLE SEED: {brief.title}
This is a compilation of separate allegedly-true first-person stories on this theme, told back-to-back — usually 3, but use 2 (longer each) or 4 if the topic and the seeds below fit that better. Let the material decide the count; do not pad to hit a number.

LENGTH — HIT THE TARGET, THEN STOP (hard ceiling, no runaway):
- TOTAL spoken words across the whole script: MINIMUM {brief.target_duration_min * 150}, ideal {brief.target_duration_min * 155}, HARD CAP {brief.target_duration_min * 165}. A draft below the minimum triggers a costly repair call; budget the stories before writing. Do NOT exceed the cap — padding is a FAIL.
- TOTAL scene objects across all SCENES arrays combined: MINIMUM {brief.target_duration_min * 7}, aim for {brief.target_duration_min * 8}, HARD CAP {brief.target_duration_min * 10}. At roughly 18–22 spoken words per scene, this reaches the word target without bloated lines.
- Split the total roughly evenly across however many stories you choose: each story is a FULL arc of about {max(4, brief.target_duration_min // 3)}-{max(6, brief.target_duration_min // 2)} minutes — never a rushed 2-minute sketch, but never padded either. VARY the runway length per story (one slow build; at least one that opens fast, mid-crisis, in a single night).
- Every scene's "vo" stays ≤28 words. Advance the story each scene — NEVER repeat a beat, re-describe the same moment, or restate a feeling to fill space. When the LAST story's lingering line lands, STOP and emit the OUTRO. Depth and escalation fill the runtime, not repetition.

STORY SEEDS / BEATS TO USE:
{kp}

PRIVATE PREP — DO THIS BEFORE PROSE, NEVER OUTPUT IT:
- Write a one-line VOICE CARD per narrator: age/life context, region, sentence rhythm,
  vocabulary, skepticism level, and dialogue habit. No two cards may overlap.
- Build a CONTINUITY LEDGER per story: hook promise; timeline/shift; people and object
  counts; narrator/threat positions; doors/routes; introduced props; fight-or-flight
  response; escape; aftermath. Every later beat must agree with this ledger.
- Assign a different ending shape to every story before drafting.

HARD RESTRAINT BUDGETS:
- Use at most ONE aftermath/corroboration beat per story, and at least one story has ZERO.
  Camera/static failure, police/ranger confirmation, tracks, records, another witness,
  a later message, and recurrence all count. Never stack proof to make the story credible.
- Use no more than FOUR exact numeric anchors per story and no more than ONE precise clock
  time. A number stays only if it changes a decision, distance, timing, or spatial logic.
- No two stories may end with later evidence proving the threat selected, knew, or followed
  the narrator. End within one or two beats of the strongest image or action.
- "I told myself" is banned, as are "I figured it was", "I convinced myself", and
  "I wanted to believe". Show uncertainty through a check, hesitation, dialogue, or mistake.

Obey the 7 LAWS OF DREAD from your instructions. This script MUST NOT read as three variations of one template. In particular:
- COLD OPEN first-person — NO greeting, NO "our first story", NO "this account comes from".
- Each story a DIFFERENT SHAPE, different ending (rotate the STRUCTURE menu), different narrator VOICE (age/region/speech), different KIND of threat, and different pacing. Write a one-line voice-card in your head for each narrator first.
- THREAT MIX across the three: ≥1 is a real HUMAN danger who ACTS violently (intruder/stalker — forces a door, chases, screams, smashes); ≥1 stays plausibly explainable; at most one is clearly paranormal. NOT every story a tall figure standing still — that image is banned as the default.
- The narrator ACTS (calls 911 / grabs a weapon / runs / locks down). No passive "sat and waited for morning".
- Fear shown through the body, never the word "scared". Voice is RAW/conversational, not literary.
- Honor the BLACKLIST: no stock self-reassurance phrases at all, no "tall and still", no rule-of-three, no "night one/two/three", no "I still don't know what it was" coda. NO end CTA (comment/vote). NO reused names across stories.
- NO statistics, NO "according to", NO experts, NO debunk.

FINAL PRIVATE AUDIT BEFORE OUTPUT: re-check the full continuity ledger, number budget,
corroboration budget, ending diversity, narrator voices, and physical action order. Repair
any violation silently. Output only the finished script, never the cards/ledger/audit.

HOOK LINE ENERGY (this becomes the video title — first person, curiosity gap, ≤70 chars):
  "{hook_ex}"

Output HOOK:, then one SEGMENT N: <evocative place-name heading> block per story (usually 3), then OUTRO:, each with a SCENES: JSON array following the scene-object format from your instructions. Output valid JSON arrays only inside SCENES."""

    def _build_generation_prompt(
        self,
        brief: TopicBrief,
        angle: str,
        patterns: list[str],
        niche_cfg: NicheConfig | None = None,
    ) -> str:
        """Build the user prompt for variant generation."""
        if niche_cfg is not None and getattr(
                niche_cfg, "content_format", "explainer") == "narrative":
            return self._build_narrative_generation_prompt(brief, niche_cfg)
        angle_instruction = {
            "pain_hook": (
                "Open with the EXACT dollar amount or percentage the viewer is losing RIGHT NOW. "
                "Make them feel the pain in the first sentence."
            ),
            "data_driven": (
                "Open with a counterintuitive statistic that contradicts common belief. "
                "Lead with data, not story. Example: '93% of active fund managers underperform the index. Here's the 7% secret.'"
            ),
            "contrarian": (
                "Open by challenging the #1 piece of conventional wisdom on this topic. "
                "Make the viewer feel like everyone else has been lying to them."
            ),
        }.get(angle, "Open with a shocking specific number.")

        # ── Niche-specific injections ─────────────────────────────────────
        sfx1 = niche_cfg.sfx_primary if niche_cfg else "alarm"
        sfx2 = niche_cfg.sfx_secondary if niche_cfg else "alarm"
        broll = niche_cfg.broll_style if niche_cfg else "person + relevant context on screen"
        proof_src = niche_cfg.proof_sources[0] if niche_cfg and niche_cfg.proof_sources else "credible source"
        hook_ex = niche_cfg.hook_examples[0] if niche_cfg and niche_cfg.hook_examples else "Shocking specific number that costs the viewer RIGHT NOW."

        # Niche-specific comment hook + video CTA language
        niche_key = brief.niche.value.lower()
        if "finance" in niche_key or "retirement" in niche_key or "crypto" in niche_key:
            comment_hook_ex = "Drop a number below: how many years until you retire? I read every reply."
            video_cta_ex = "I broke down how to pick the right fund in another video — link in the description."
            like_cta_ex = "If this just changed how you think about your money — tap Like. It helps others find this."
            payoff_sfx = sfx1  # cash-register
        elif "health" in niche_key or "nutrition" in niche_key:
            comment_hook_ex = "One question: what is the one health habit you want to fix this month? Drop it below."
            video_cta_ex = "I covered the exact protocol in another video — link below if you want the full breakdown."
            like_cta_ex = "If this is changing how you see your health — tap Like. It keeps this research coming."
            payoff_sfx = sfx1  # heartbeat
        elif "myth" in niche_key or "histor" in niche_key:
            comment_hook_ex = "Which fact in this video shocked you most? Drop it below — I read everything."
            video_cta_ex = "I went deeper on this in another video — the link is pinned in the comments."
            like_cta_ex = "If ancient history just broke your brain a little — tap Like. That is why we do this."
            payoff_sfx = sfx1  # dramatic-sting
        elif "psych" in niche_key:
            comment_hook_ex = "One question: which bias from this video do you catch yourself doing? Comment below."
            video_cta_ex = "I covered the full behavioral framework in another video — link in the description."
            like_cta_ex = "If this explained something about yourself you never had words for — tap Like."
            payoff_sfx = sfx1
        elif "tech" in niche_key:
            comment_hook_ex = "What device or app are you most worried about after watching this? Drop it below."
            video_cta_ex = "I showed exactly how to harden this in another video — link below."
            like_cta_ex = "If this just made you smarter about your tech — tap Like. More of this coming."
            payoff_sfx = sfx1
        else:
            comment_hook_ex = "What is one thing from this video you are going to act on? Comment below."
            video_cta_ex = "I covered this in depth in another video — link in the description."
            like_cta_ex = "If this was useful — tap Like. It helps others find this too."
            payoff_sfx = sfx1

        prompt = f"""Write a production-ready YouTube script optimized for 70%+ audience retention.

TOPIC: {brief.title}
NICHE: {brief.niche.value} | MARKET: {brief.market.value}
TARGET LENGTH: {brief.target_duration_min} minutes (~{brief.target_duration_min * 150} spoken words)
VOICE: {niche_cfg.insider_angle if niche_cfg else "expert narrator"}

ANGLE: {angle_instruction}

KEY POINTS TO COVER:
{chr(10).join(f"- {p}" for p in brief.key_points)}

OUTPUT FORMAT — scene-based JSON, one object per 3-5 second screen cut:
  "vo"     — MAX 25 words. Natural spoken English. ZERO scripting jargon.
  "visual" — stock footage query, MAX 6 plain words: a concrete filmable subject (never text popups, graphics, or camera directions).
  "sfx"    — "{sfx1}" | "{sfx2}" | "whoosh" | "ting" | null
  "pace"   — "slow" | "normal" | "fast" — delivery speed for THIS scene (see PROSODY rules;
             slow = hook/big-stat/outro, fast = explanation runs & montage, mix required).
  "pause_after_ms" — 0 normally; 400-700 after a twist/question; 800-1500 for the 2-4
             biggest dramatic beats only.
  "emphasis" — array of 1-3 EXACT words from vo to vocally stress (numbers, twist words). [] if none.

For this niche, typical visuals include: {broll}
Primary SFX for key reveals: "{sfx1}"
Authority proof source: {proof_src}

Use EXACTLY these section labels. Output valid JSON arrays only.

HOOK EXAMPLE (follow this energy and specificity):
  H scene vo: "{hook_ex}"

HOOK:
SCENES:
[
  {{"vo": "[G — short warm spoken greeting (<=8 words) flowing straight into the topic, e.g. 'Hey, great to have you — today, [topic].']", "visual": "[{broll} — calm cinematic opener]", "sfx": null, "pace": "slow", "pause_after_ms": 0, "emphasis": []}},
  {{"vo": "[H — THE hook: pain-first, exact number/stat they are LOSING right now, a curiosity gap. Max 18 words. Self-contained (this becomes the TITLE). No 'imagine'/'picture this'.]", "visual": "[{broll} — most alarming version]", "sfx": "{sfx2}", "pace": "slow", "pause_after_ms": 900, "emphasis": ["[the hook's key number/word]"]}},
  {{"vo": "[P — credible data point: 'According to {proof_src}, X%...']", "visual": "[{proof_src} report cover or chart displayed full screen]", "sfx": "{sfx1}", "pace": "normal", "pause_after_ms": 0, "emphasis": ["[the stat]"]}}
]

SEGMENT 1: [Curiosity-gap heading — 5 words max]
SCENES:
[
  {{"vo": "[First punchy sentence setting up the core problem.]", "visual": "[{broll}]", "sfx": null}},
  {{"vo": "[Key statistic with source attribution.]", "visual": "[text-popup or chart animation showing the number]", "sfx": "{sfx1}"}},
  {{"vo": "[Build tension — what happens if they do nothing.]", "visual": "[consequence visual matching niche: {broll}]", "sfx": null}},
  {{"vo": "[Natural open-loop in plain speech — MUST sound like normal conversation, NOT a label. E.g.: 'And there is a second trap most people never catch — I will show you in a few minutes.']", "visual": "[presenter on camera leaning forward]", "sfx": null}}
]

SEGMENT 2: [Heading]
SCENES:
[
  {{"vo": "[Continue story or data. Short punchy sentence.]", "visual": "[{broll}]", "sfx": null}},
  {{"vo": "[Key insight or data point with source.]", "visual": "[chart or text popup — {niche_cfg.chart_palette if niche_cfg else 'appropriate palette'}]", "sfx": "{sfx2}"}},
  {{"vo": "[Rhetorical punch: restate the number simply. 'That is the real cost. Let it land.']", "visual": "[zoom in on number filling screen]", "sfx": null}},
  {{"vo": "[Bridge to next point.]", "visual": "[{broll}]", "sfx": null}}
]

SEGMENT 3: [Heading]
SCENES:
[
  {{"vo": "[Continue with next data point or evidence.]", "visual": "[{broll}]", "sfx": null}},
  {{"vo": "[Key data — most surprising finding.]", "visual": "[chart or graphic — concrete data]", "sfx": "{sfx1}"}},
  {{"vo": "[Second natural open-loop in plain speech. E.g.: 'Before I show you the fix, there is one more thing most people miss — stay with me.']", "visual": "[presenter direct-to-camera]", "sfx": null}},
  {{"vo": "{like_cta_ex}", "visual": "[presenter smiling, relaxed, direct camera]", "sfx": "ting"}}
]

SEGMENT 4: [Heading]
SCENES:
[
  {{"vo": "[Continue with solution or key action step.]", "visual": "[{broll}]", "sfx": null}},
  {{"vo": "[Most actionable takeaway — specific and concrete.]", "visual": "[chart, comparison, or step graphic]", "sfx": null}},
  {{"vo": "{video_cta_ex}", "visual": "[presenter gestures to side or below]", "sfx": null}}
]

SEGMENT 5: [Heading — resolve BOTH open loops from segments 1 and 3]
SCENES:
[
  {{"vo": "[Resolve open loop from segment 1 — deliver the exact payoff promised.]", "visual": "[the reveal: specific number, chart, or comparison]", "sfx": "{payoff_sfx}"}},
  {{"vo": "[Key resolution data — the proof the payoff is real.]", "visual": "[chart or animation showing result]", "sfx": null}},
  {{"vo": "[Resolve open loop from segment 3 — deliver that payoff too.]", "visual": "[second reveal — concrete visual]", "sfx": "{sfx1}"}},
  {{"vo": "[Final empowering takeaway. Actionable. What they can do TODAY.]", "visual": "[presenter direct-to-camera, confident]", "sfx": null}}
]

OUTRO:
SCENES:
[
  {{"vo": "{comment_hook_ex}", "visual": "[presenter leaning forward, engaged, direct camera]", "sfx": null}},
  {{"vo": "[EXPLICIT subscribe invite — MUST contain the word 'subscribe', framed with empathy/shared-identity tied to this topic, NOT generic. E.g.: 'If you are fighting this every single day, subscribe — I break down one real fix like this every week, and you should not have to figure it out alone.']", "visual": "[presenter direct-to-camera, warm]", "sfx": null}},
  {{"vo": "[Next video tease — use the NEXT QUEUED VIDEO title from above, add a curiosity gap. E.g.: 'Next: [exact title] — that one could save you even more.']", "visual": "[thumbnail-style teaser or presenter pointing]", "sfx": "whoosh"}}
]
"""
        if patterns:
            prompt += f"\nLEARNED PATTERNS FROM HIGH-PERFORMING VIDEOS:\n{chr(10).join(f'- {p.finding}' for p in patterns)}\n"

        # Competitor SCRIPT playbook — injected ONLY when it passed the gate in
        # analytics.intel_gate. An uncontrolled playbook (learned with no matched
        # control group) describes what winning channels always do, not what made
        # a video win; telling the model to "mirror" that is how survivorship
        # bias gets written into every script. The old code pasted it in
        # regardless and swallowed every error with `except: pass`, so a corrupt
        # or stale row looked exactly like a healthy one.
        _decision = resolve_competitor_playbook(brief)
        if _decision.usable:
            prompt += ("\nCOMPETITOR SCRIPT PLAYBOOK (validated against a matched "
                       "control group — mirror these winning hook/structure/pacing "
                       f"patterns):\n{_decision.playbook}\n")

        if brief.lessons:
            prompt += f"\nCHANNEL LESSONS:\n{chr(10).join(f'- {l}' for l in brief.lessons)}\n"

        if brief.topics_done:
            prompt += f"\nTOPICS ALREADY PUBLISHED ON THIS CHANNEL (do NOT duplicate):\n"
            prompt += chr(10).join(f"- {t}" for t in brief.topics_done) + "\n"

        if brief.next_topic:
            prompt += f"\nNEXT QUEUED VIDEO (use this EXACT title for the outro teaser):\n- {brief.next_topic}\n"
        else:
            prompt += "\nNEXT QUEUED VIDEO: unknown — invent a compelling teaser that fits this channel's niche.\n"

        prompt += """
HARD RULES — non-negotiable:
1. Output ONLY the script. Start with "HOOK:" on line 1. No preamble, no meta-text.
2. Every SCENES block must be a valid JSON array. No trailing commas. Use double quotes only.
3. "vo" field: 18-25 words per scene — use the FULL budget. Do NOT write thin
   8-12 word lines; each scene must carry a complete, substantive thought (a stat,
   an example, a consequence). Never exceed 25. Natural spoken English ONLY.
   BANNED WORDS in 'vo': hook, segment, B-roll, CTA, open loop, outro, narration,
   "let's dive in", "moving on", "as we discussed", "let me walk you through",
   "in today's video", "don't forget to like", "smash that subscribe button"
4. Open loops MUST be natural speech in 'vo' — not labels or brackets.
5. Segment 5 MUST resolve BOTH open loops from segments 1 and 3.
6. LENGTH IS MANDATORY: total vo words across ALL scenes MUST be {min_words}-{max_words}
   words (a ~{target}-minute video at ~150 wpm). A short script is a FAILURE — YouTube
   needs 8+ minutes of content to enable mid-roll ads. Since each scene is capped at 25
   words, you MUST write MANY scenes ({min_scenes}+ total) to reach the word count.
7. Each SEGMENT's SCENES array MUST contain 10-16 scenes (the examples above show only
   3-4 — EXPAND every segment to 10-16 rich scenes with distinct visuals). Keep adding
   substantive scenes (more data points, examples, mini-stories) until total ≥ {min_words} words.
8. YOUTUBE POLICY (mandatory — violations make the video unusable/demonetized):
   - NO scam/false promises: "get rich quick", "guaranteed income/profit", "100% guaranteed",
     "miracle cure", "double your money", "risk-free", "free money", "doctors hate".
   - NO advertiser-unfriendly words: profanity, graphic violence, self-harm, drugs, sexual content.
   - Make CLAIMS specific + sourced, not sensational. Advice framed as education, not promises.
9. FACTUAL GROUNDING (mandatory — fabricated stats get the channel flagged for misinformation):
   - Use ONLY statistics/numbers that appear in KEY POINTS above, or that are genuinely
     well-known public facts (e.g. "the S&P 500 has averaged about 10% annually").
   - Do NOT invent precise figures (specific percentages, dollar amounts, study results)
     and attach a fake source to them. If you lack a sourced number, speak QUALITATIVELY
     ("most retirees underestimate this", "studies consistently show") instead of a fake precise stat.
   - When you DO cite a number, attribute it only to a real, checkable source named in
     KEY POINTS / proof sources — never to a made-up "2024 report" that may not exist.
   - Rule of thumb: a viewer fact-checking any number in this script must find it TRUE.
10. PREMIUM EDITORIAL (mandatory — a counted, citation-reading script reads as AI and FAILS review):
   - NO listicle: never write "Number one/two/three…" as the spine. Group by named MECHANISM headings
     (e.g. "The Fat Paralysis", "The Roughage Blockade") + a narrative arc connecting them.
   - SHOW-DON'T-READ: 'vo' says findings qualitatively ("the latest data shows…"); NEVER read source
     name/year aloud. Put the source in the 'visual' field (e.g. "PubMed study page on screen") so it shows, not tells.
   - METAPHOR: each abstract mechanism gets ONE vivid FILMABLE metaphor; its 'visual' is a real scene
     (e.g. "traffic jam on a narrow alley", "truck flipped across a lane"), never an idiom.
   - EMPATHY: include ≥2 scenes naming the real felt sensation (fermenting, foaming, stuck in the throat hours later).
   - CTA from shared experience, not "keeps this channel going".
11. PROSODY IS MANDATORY: every scene object MUST carry "pace", "pause_after_ms", "emphasis".
   Target mix: 15-25% slow, 25-40% fast, rest normal; 3-6 pauses >=400ms total; every key
   stat listed in its scene's emphasis. An all-"normal" script is a FAILURE (flat robot voice).
""".format(target=brief.target_duration_min,
           min_words=brief.target_duration_min * 150,
           max_words=brief.target_duration_min * 175,
           min_scenes=brief.target_duration_min * 7)
        return prompt

    def _build_revision_prompt(
        self,
        draft: ScriptDraft,
        feedback: CriticFeedback,
        brief: TopicBrief,
        *,
        niche_cfg: NicheConfig | None = None,
    ) -> str:
        """Build the user prompt for revision."""
        # FULL SCRIPT, not a summary. The old 40-chars/scene summary made the
        # model REWRITE blind — "keep what works" is impossible when it can't
        # see what it wrote; hook promises drifted and length collapsed. Input
        # tokens are cheap (~$0.02 on Claude); a blind rewrite costs a full
        # extra revision round. Truncated defensively at ~40k chars.
        try:
            full_script = self._draft_to_script_text(draft)[:40000]
        except Exception:
            full_script = (draft.raw_content or "")[:40000]

        if niche_cfg is not None and getattr(
                niche_cfg, "content_format", "explainer") == "narrative":
            return f"""Revise this NARRATIVE HORROR script using the critic feedback below.
Make targeted edits, not a fresh rewrite. Keep the story count, approximate spoken length,
distinct narrator voices, scene JSON fields, and preserve the strongest fight-or-flight
action in each story. A repair must not make a protagonist passive.

NON-NEGOTIABLE QUALITY CONTRACT:
- Privately rebuild each story's continuity ledger: hook promise, timeline, counts,
  positions, props, threat movement, protagonist response, and escape. Fix every conflict.
- At most one aftermath/corroboration beat per story; at least one story gets none.
- Every story keeps a different ending shape. No two endings use later evidence to prove
  the threat selected, knew, or followed the narrator. Stop shortly after the peak.
- Maximum four exact numeric anchors and one precise clock time per story. Cut fake precision.
- Delete all stock self-reassurance: "I told myself", "I figured it was", "I convinced
  myself", "I wanted to believe". Show uncertainty through behavior or dialogue.
- Do not add records, camera glitches, official confirmation, extra witnesses, paranormal
  proof, a recurrence, or an explanatory coda unless the critic explicitly requires it.
- Keep vo raw and first-person (<=28 words), visuals filmable (<=6 words), SFX restrained,
  and all prosody fields intact. No CTA or host voice.

FULL ORIGINAL SCRIPT (variant {draft.variant_id}):
{full_script}

CRITIC FEEDBACK:
Score: {feedback.total_score}/100
Rejection reasons: {"; ".join(feedback.rejection_reasons)}
Specific fixes required: {"; ".join(feedback.specific_fixes)}

BRIEF: {brief.title}

Privately audit the final result against the quality contract, then output the FULL revised
script only: HOOK:, SEGMENT N: <heading>, OUTRO:, each followed by SCENES: and valid JSON.
Start with "HOOK:" — no preamble."""

        prompt = f"""Revise this YouTube script based on critic feedback. Keep what works, fix what doesn't.
Do NOT rewrite from scratch — make targeted improvements to the script below, preserving its
structure, its total length (never return FEWER spoken words than the original), and every
scene's prosody fields unless a fix requires changing them.

FULL ORIGINAL SCRIPT (variant {draft.variant_id}):
{full_script}

CRITIC FEEDBACK:
Score: {feedback.total_score}/100
Rejection reasons: {"; ".join(feedback.rejection_reasons)}
Specific fixes required: {"; ".join(feedback.specific_fixes)}

BRIEF: {brief.title}

OUTPUT the FULL revised script using scene-based JSON format.
Each scene: {{"vo": "MAX 25 words natural speech", "visual": "stock footage query", "sfx": "alarm|cash-register|whoosh|ting|null", "pace": "slow|normal|fast", "pause_after_ms": 0, "emphasis": ["key words"]}}
PROSODY: keep/assign pace per role (slow=hook/big-stat/outro, fast=explanation runs), 3-6 deliberate
pauses >=400ms at twists, key stats in emphasis. All-"normal" pacing is a failure.

BANNED in 'vo': hook, segment, B-roll, CTA, open loop, outro, "let's dive in", "in today's video", "don't forget to like"
Open loops must be NATURAL speech: "And there's something even more important coming up — stay with me."

HOOK:
SCENES:
[... 3-4 scenes ...]

SEGMENT 1: [heading]
SCENES:
[... 4-8 scenes ...]

(5 segments total, then OUTRO)

OUTRO:
SCENES:
[... 3 scenes ...]

Start output with "HOOK:" — no preamble.
"""
        return prompt

    # Scenes worth a vocal spike: contain a digit or a scale/quantity word.
    _EMPH_NUM_RE = re.compile(
        r"\d|\b(billion|million|trillion|thousand|hundred|percent|half|double|"
        r"triple|times)\b", re.IGNORECASE)

    @staticmethod
    def _repair_inner_quotes(s: str) -> str:
        """Escape unescaped double quotes INSIDE JSON string values.

        A quote closes a string only if the next non-space char is a JSON
        structural char (, : ] }). Any other quote inside a string is content
        the model forgot to escape — turn it into \\" so the array parses.
        """
        out: list[str] = []
        in_str = False
        i, n = 0, len(s)
        while i < n:
            c = s[i]
            if not in_str:
                if c == '"':
                    in_str = True
                out.append(c)
            elif c == "\\" and i + 1 < n:
                out.append(s[i:i + 2])
                i += 2
                continue
            elif c == '"':
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                if j >= n or s[j] in ",:]}":
                    in_str = False
                    out.append(c)
                else:
                    out.append('\\"')
            else:
                out.append(c)
            i += 1
        return "".join(out)

    def _parse_scenes_json(self, block: str) -> list[ScriptScene]:
        """Extract SCENES JSON array from a section block.

        Tries to find and parse the JSON array after 'SCENES:'.
        Falls back gracefully if JSON is malformed — returns empty list
        so the caller can still use narration-only fallback.
        """
        # NOTE: must NOT use a non-greedy regex to capture the array — scene
        # objects contain NESTED arrays (e.g. "emphasis": []) so r"\[.*?\]"
        # truncates at the first inner "]". raw_decode handles nesting.
        # Some models wrap the array in a ```json fence — strip fences first
        # (an unparsed SCENES block loses the whole segment's scenes).
        block = re.sub(r"```(?:json)?", "", block)
        m = re.search(r"SCENES\s*:\s*\[", block, re.IGNORECASE)
        if not m:
            return []
        start = m.end() - 1  # index of the opening '['
        raw_json = block[start:]
        dec = json.JSONDecoder()
        try:
            items, _ = dec.raw_decode(raw_json)
        except json.JSONDecodeError:
            # Try light cleanup: trailing commas before ] or }
            cleaned = re.sub(r",\s*([\]}])", r"\1", raw_json)
            try:
                items, _ = dec.raw_decode(cleaned)
            except json.JSONDecodeError:
                # LLMs regularly emit UNESCAPED double quotes inside string
                # values ('spinning circular "anxiety" loop') which kills the
                # whole segment's scenes. Repair: walk the string, escape any
                # quote that isn't structurally a string terminator.
                try:
                    items, _ = dec.raw_decode(self._repair_inner_quotes(cleaned))
                except json.JSONDecodeError:
                    logger.warning("Scene JSON parse failed, falling back to empty", raw=raw_json[:200])
                    return []

        scenes = []
        for item in items:
            if not isinstance(item, dict):
                continue
            vo = str(item.get("vo", item.get("voiceover", ""))).strip()
            visual = str(item.get("visual", item.get("visual_prompt", ""))).strip()
            sfx_raw = item.get("sfx", None)
            sfx = str(sfx_raw).strip() if sfx_raw and sfx_raw != "null" else None
            if not vo:
                continue
            word_count = len(vo.split())
            duration_s = round(word_count / 2.5, 1)  # 150wpm → 2.5 w/s
            # ── Prosody fields (optional; vfact pacing) ──────────────────
            pace = str(item.get("pace", "normal")).strip().lower()
            if pace not in ("slow", "normal", "fast"):
                pace = "normal"
            try:
                pause_after_ms = int(item.get("pause_after_ms", 0) or 0)
            except (TypeError, ValueError):
                pause_after_ms = 0
            pause_after_ms = max(0, min(pause_after_ms, 2000))
            emphasis_raw = item.get("emphasis", [])
            if isinstance(emphasis_raw, str):
                emphasis_raw = [emphasis_raw]
            emphasis = [str(e).strip() for e in emphasis_raw if str(e).strip()][:4] \
                if isinstance(emphasis_raw, list) else []
            # EMPHASIS INFLATION guard at the SOURCE: models mark 85-100% of
            # scenes (measured) despite the prompt — everything stressed =
            # nothing stressed. Keep emphasis only where there is an actual
            # stat/scale to spike (matches the renderer's pitch-lift rule).
            if emphasis:
                if not (self._EMPH_NUM_RE.search(vo)
                        or any(self._EMPH_NUM_RE.search(e) for e in emphasis)):
                    emphasis = []
            scenes.append(ScriptScene(
                voiceover=vo,
                visual_prompt=visual,
                sfx=sfx,
                duration_s=duration_s,
                pace=pace,
                pause_after_ms=pause_after_ms,
                emphasis=emphasis,
            ))
        return scenes

    def _parse_draft(self, content: str, variant_id: str, brief_title: str, version: int = 1) -> ScriptDraft:
        """Parse LLM output into ScriptDraft model.

        Supports new scene-based JSON format (primary):
            HOOK:
            SCENES:
            [{"vo": "...", "visual": "...", "sfx": "alarm"}]

        Falls back to legacy dual-column narration format if no SCENES block found.
        """
        # Strip markdown bold markers
        clean = re.sub(r"\*+", "", content)

        # ── HOOK ──────────────────────────────────────────────────────────
        hook_match = re.search(
            r"HOOK\s*:\s*\n?(.*?)(?=\nSEGMENT\s*1\b|\Z)",
            clean,
            re.DOTALL | re.IGNORECASE,
        )
        hook_block = hook_match.group(1).strip() if hook_match else ""
        hook_scenes = self._parse_scenes_json(hook_block)
        if hook_scenes:
            hook = " ".join(sc.voiceover for sc in hook_scenes)
        else:
            hook = self._extract_narration(hook_block)

        # ── OUTRO ─────────────────────────────────────────────────────────
        outro_match = re.search(
            r"OUTRO\s*:\s*\n?(.*?)$",
            clean,
            re.DOTALL | re.IGNORECASE,
        )
        outro_block = outro_match.group(1).strip() if outro_match else ""
        outro_scenes = self._parse_scenes_json(outro_block)
        if outro_scenes:
            outro = " ".join(sc.voiceover for sc in outro_scenes)
        else:
            outro = self._extract_narration(outro_block)

        # ── SEGMENTS ──────────────────────────────────────────────────────
        seg_matches = re.findall(
            r"SEGMENT\s*(\d+)\s*:\s*([^\n]*)\n(.*?)(?=\nSEGMENT\s*\d+|\nMID-ROLL|\nOUTRO|\Z)",
            clean,
            re.DOTALL | re.IGNORECASE,
        )
        seen_indices: set[int] = set()
        segments = []
        for idx_str, heading, body in seg_matches:
            idx = int(idx_str)
            if idx in seen_indices:
                continue  # deduplicate repeated segments
            seen_indices.add(idx)
            body_clean = body.strip()
            scenes = self._parse_scenes_json(body_clean)
            if scenes:
                narration = " ".join(sc.voiceover for sc in scenes)
                seg_words = sum(len(sc.voiceover.split()) for sc in scenes)
                duration_s = max(30, int(sum(sc.duration_s for sc in scenes)))
            else:
                # Legacy fallback
                narration = self._extract_narration(body_clean)
                seg_words = len(narration.split())
                duration_s = max(30, int(seg_words / 2.5))
            segments.append(ScriptSegment(
                index=idx,
                heading=heading.strip(),
                content=narration,
                raw_content=body_clean,
                scenes=scenes,
                visual_cues=self._parse_visual_cues(body_clean),  # legacy compat
                estimated_duration_seconds=duration_s,
            ))

        narration_words = len(" ".join(
            [hook] + [s.content for s in segments] + [outro]
        ).split())
        estimated_duration = narration_words / 2.5  # 150wpm

        return ScriptDraft(
            variant_id=variant_id,
            brief_title=brief_title,
            hook=hook,
            hook_raw=hook_block,
            hook_scenes=hook_scenes,
            segments=segments,
            outro=outro,
            outro_raw=outro_block,
            outro_scenes=outro_scenes,
            raw_content=content,  # full LLM output preserved
            word_count=narration_words,
            estimated_duration_seconds=int(estimated_duration),
            version=version,
        )

    # ── Visual cue extraction ──────────────────────────────────────────
    _VISUAL_TAG_RE = re.compile(r"\[VISUAL\b([^\]]*)\]", re.IGNORECASE)
    _SFX_TAG_RE    = re.compile(r"\[SFX\s*:\s*([^\]]+)\]", re.IGNORECASE)
    _ATTR_RE       = re.compile(r'(\w+)=["\']([^"\']*)["\']')

    @classmethod
    def _parse_visual_cues(cls, block: str) -> list[VisualCue]:
        """Extract structured [VISUAL:] and [SFX:] tags from a raw block."""
        cues: list[VisualCue] = []

        for m in cls._VISUAL_TAG_RE.finditer(block):
            raw = m.group(0)
            attrs_str = m.group(1).strip()
            attrs = dict(cls._ATTR_RE.findall(attrs_str))

            raw_type = attrs.get("type", "").lower().replace("-", "_")
            try:
                cue_type = VisualCueType(raw_type)
            except ValueError:
                # freeform [VISUAL: description] — classify by keywords
                low = attrs_str.lower()
                if any(k in low for k in ("b-roll", "broll", "footage", "stock")):
                    cue_type = VisualCueType.BROLL
                elif any(k in low for k in ("chart", "graph", "pie", "bar")):
                    cue_type = VisualCueType.CHART
                elif any(k in low for k in ("zoom", "ken-burns", "slam")):
                    cue_type = VisualCueType.ZOOM
                elif any(k in low for k in ("text", "popup", "pop-up", "number", "$", "%")):
                    cue_type = VisualCueType.TEXT_POPUP
                elif any(k in low for k in ("transition", "whip", "cut", "glitch")):
                    cue_type = VisualCueType.TRANSITION
                else:
                    cue_type = VisualCueType.BROLL  # default

            cues.append(VisualCue(
                type=cue_type,
                raw=raw,
                query=attrs.get("query", ""),
                source=attrs.get("source", ""),
                duration_s=float(attrs.get("duration", "0").replace("s", "") or 0),
                content=attrs.get("content", ""),
                color=attrs.get("color", ""),
                animation=attrs.get("animation", ""),
                template=attrs.get("template", ""),
                data=attrs.get("data", ""),
                palette=attrs.get("palette", ""),
                technique=attrs.get("technique", ""),
                direction=attrs.get("direction", ""),
                speed=attrs.get("speed", ""),
                target=attrs.get("target", ""),
            ))

        for m in cls._SFX_TAG_RE.finditer(block):
            raw = m.group(0)
            sfx_text = m.group(1).strip()
            parts = [p.strip() for p in sfx_text.split("|")]
            sound = parts[0] if parts else sfx_text
            timing = parts[1] if len(parts) > 1 else ""
            cues.append(VisualCue(
                type=VisualCueType.SFX,
                raw=raw,
                sound=sound,
                timing=timing,
            ))

        return cues

    # Direction-line prefixes to strip (not spoken aloud)
    _DIRECTION_PATTERNS = re.compile(
        r"^\["
        r"(VISUAL|SFX|PATTERN\s+INTERRUPT|OPEN\s+LOOP|MID-VIDEO\s+LIKE\s+CTA|MID-ROLL\s+VIDEO\s+CTA)",
        re.IGNORECASE,
    )
    _LABEL_PATTERNS = re.compile(
        r"^(MID-ROLL\s+(CTA|VIDEO\s+CTA)|MID-VIDEO\s+LIKE\s+CTA)\s*:",
        re.IGNORECASE,
    )
    _NARRATION_PREFIX = re.compile(r"^NARRATION\s*:\s*", re.IGNORECASE)

    @classmethod
    def _extract_narration(cls, text: str) -> str:
        """Extract spoken narration lines, stripping production direction cues.

        Strips: [VISUAL:], [SFX:], [PATTERN INTERRUPT:], [OPEN LOOP:],
        [MID-VIDEO LIKE CTA:], [MID-ROLL VIDEO CTA:], bare CTA labels, NARRATION: prefix.
        Critic evaluates pure voice copy only.
        """
        lines = text.splitlines()
        narration_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if cls._DIRECTION_PATTERNS.match(stripped):
                continue
            if cls._LABEL_PATTERNS.match(stripped):
                continue
            stripped = cls._NARRATION_PREFIX.sub("", stripped)
            if stripped:
                narration_lines.append(stripped)
        return "\n".join(narration_lines)
