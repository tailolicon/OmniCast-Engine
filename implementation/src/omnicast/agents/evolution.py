"""Evolution Agent — combine best elements from variants (Hub only)."""

from __future__ import annotations

import json
import re
import structlog

from omnicast.agents.base import BaseAgent
from omnicast.config.niches import NicheConfig
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft, TopicBrief, ScriptSegment, ScriptScene
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()

# Niche-appropriate mid-video like CTAs
_NICHE_CTA_MAP: dict[str, str] = {
    "finance": "If this is saving you money, the algorithm needs a like right now — it's how this channel stays free",
    "finance.retirement": "If this is helping your retirement plan, hit like — it tells the algorithm this matters",
    "finance.crypto": "If this alpha is saving your portfolio, smash like — helps the channel reach more investors",
    "health": "If this is helping your health journey, hit like — it keeps this channel going",
    "health.nutrition": "If this is changing how you think about food, hit like — it helps us reach more people",
    "mythology": "If ancient history is blowing your mind, hit like — it's how this channel stays alive",
    "psychology": "If this is making you rethink how your mind works, hit like — it keeps this research coming",
    "tech": "If this is keeping you ahead of the curve, hit like — it helps us cover what matters",
}


def _niche_mid_cta(niche_cfg: NicheConfig) -> str:
    """Pick CTA based on insider_angle keyword matching."""
    angle = niche_cfg.insider_angle.lower()
    if "historian" in angle or "ancient" in angle or "myth" in angle:
        return _NICHE_CTA_MAP["mythology"]
    if "retirement" in angle:
        return _NICHE_CTA_MAP["finance.retirement"]
    if "crypto" in angle or "chain" in angle:
        return _NICHE_CTA_MAP["finance.crypto"]
    if "nutrition" in angle or "food" in angle or "diet" in angle:
        return _NICHE_CTA_MAP["health.nutrition"]
    if "health" in angle or "medical" in angle or "doctor" in angle:
        return _NICHE_CTA_MAP["health"]
    if "psych" in angle or "behavior" in angle or "mind" in angle:
        return _NICHE_CTA_MAP["psychology"]
    if "tech" in angle or "engineer" in angle or "software" in angle:
        return _NICHE_CTA_MAP["tech"]
    return _NICHE_CTA_MAP["finance"]


class EvolutionAgent(BaseAgent):
    """Combine best elements from multiple variants into one superior draft.

    Only used for Hub channels (high quality requirement).
    """

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    @property
    def name(self) -> str:
        return "evolution"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt(niche_cfg=None)

    def _build_system_prompt(self, niche_cfg: NicheConfig | None) -> str:
        if niche_cfg and niche_cfg.content_format == "narrative":
            return self._build_narrative_system_prompt(niche_cfg)

        # Niche-specific hook guidance
        if niche_cfg:
            hook_guide = niche_cfg.hook_format
            insider = niche_cfg.insider_angle
            mid_cta = _niche_mid_cta(niche_cfg)
        else:
            hook_guide = "pain-first + specific number"
            insider = "expert narrator"
            mid_cta = "If this helped, tap Like — it tells the algorithm this is worth sharing"

        return (
            f"You are an expert YouTube script editor — voice: {insider}. "
            "Merge the best elements from multiple script variants into one superior script. "
            "Use the strongest hook, best data points, and most compelling storytelling. "
            "STAY TRUE TO THE CHANNEL'S NICHE AND VOICE.\n\n"
            "OUTPUT FORMAT — scene-based JSON (feeds AI video tools directly):\n"
            "Each section outputs a SCENES block: a JSON array where each object = one 3-5 second screen cut.\n"
            '{"vo": "MAX 25 words. Natural spoken English ONLY.", "visual": "stock footage search query", "sfx": "alarm|cash-register|whoosh|ting|null", "pace": "slow|normal|fast", "pause_after_ms": 0, "emphasis": ["exact words from vo to stress"]}\n\n'
            "PROSODY IS MANDATORY on every scene (a flat, even voice is the #1 AI-slop tell): "
            "pace — slow for greeting/hook/the single most shocking stat or conclusion of each "
            "segment/the outro; fast for explanation runs, build-up chains, enumeration; normal "
            "otherwise. Target mix ~15-25% slow, ~25-40% fast — an all-'normal' script is a FAILURE. "
            "pause_after_ms — 0 normally; 400-700 after a twist/rhetorical question or before a "
            "chapter turn; 800-1500 for the 2-4 biggest dramatic beats (use 3-6 total). "
            "emphasis — 1-3 EXACT words copied from this scene's vo (big numbers, the twist word); "
            "every scene with a key stat MUST list that stat. Carry the strongest prosody over "
            "from the source variants.\n"
            "BANNED in 'vo': hook, segment, B-roll, CTA, open loop, outro, narration, "
            "'let me show you how', 'in today's video', 'don't forget to like', 'smash subscribe'\n"
            "Open loops = NATURAL speech in vo: \"And there's something even worse coming — I'll show you in a few minutes.\"\n"
            f"Like CTA = SIMPLE: \"{mid_cta}\"\n\n"
            "HOOK:\nSCENES:\n[3-4 scenes — pain-first hook, {hook_guide}]\n\n"
            "SEGMENT 1: [Title]\nSCENES:\n[4-8 scenes — last scene = natural open-loop speech]\n\n"
            "SEGMENT 2: [Title]\nSCENES:\n[4-8 scenes]\n\n"
            "SEGMENT 3: [Title]\nSCENES:\n[4-8 scenes — include like CTA as natural scene]\n\n"
            "SEGMENT 4: [Title]\nSCENES:\n[4-8 scenes — include related video mention naturally]\n\n"
            "SEGMENT 5: [Title — resolve both open loops]\nSCENES:\n[4-8 scenes]\n\n"
            "OUTRO:\nSCENES:\n[3 scenes — comment question, subscribe reason, next video tease]\n\n"
            "Start output with 'HOOK:' on line 1. No preamble. Valid JSON arrays only."
        )

    @staticmethod
    def _build_narrative_system_prompt(niche_cfg: NicheConfig) -> str:
        return (
            "You are a ruthless editor of first-person true-horror narration. "
            "Merge only demonstrably stronger material from the supplied variants; "
            "do not average their prose or invent a generic host voice. Preserve the "
            "number of stories requested by the topic and keep each story internally "
            "consistent: narrator, location, threat, injuries, escape, and aftermath. "
            "Each story needs an ordinary setup, one initially plausible wrong detail, "
            "concrete escalation, realistic fight-or-flight action, and a short distinct "
            "ending. At least one threat should be human and physically active. Avoid "
            "proof-stacking, supernatural evidence that is too neat, repeated exact-number "
            "anchors, 'I told myself/I figured/I convinced myself', purple prose, and "
            "movie-trailer language. No greeting, statistics, sources, channel talk, calls "
            "to action, related-video mention, moral, or explanation of the mystery.\n\n"
            "OUTPUT FORMAT: HOOK, then one SEGMENT per story, then OUTRO. Every section "
            "contains a SCENES JSON array. Each scene object uses: "
            '{"vo":"natural spoken English, max 35 words",'
            '"visual":"literal filmable shot matching the narration",'
            '"sfx":"subtle sound or null","pace":"slow|normal|fast",'
            '"pause_after_ms":0,"emphasis":["exact words from vo"]}. '
            "Visuals must not add evidence or actions absent from the voiceover. Keep the "
            "combined spoken length near the strongest complete source variant. Start with "
            "HOOK: on line 1, no preamble, valid JSON arrays only."
        )

    async def execute(
        self,
        variants: list[ScriptDraft],
        brief: TopicBrief,
        *,
        winner_id: str | None = None,
        niche_cfg: NicheConfig | None = None,
    ) -> ScriptDraft:
        """Combine best elements from variants."""
        if not variants:
            raise AgentError("No variants provided for evolution")

        # Build niche-aware system prompt for this specific call
        niche_system = self._build_system_prompt(niche_cfg)

        prompt = f"Topic: {brief.title}\nNiche: {brief.niche.value}\n\n"
        prompt += "Merge the best from these variants:\n\n"

        for variant in variants:
            priority = " [WINNER - prioritize this structure]" if variant.variant_id == winner_id else ""
            prompt += f"--- Variant {variant.variant_id}{priority} ---\n"
            # Send the FULL variant content (light per-segment cap only). Heavy
            # truncation here starved the merge — it could only see ~500 chars/
            # segment, so the merged draft came out far shorter than either source
            # (~680w) and leaned entirely on the expand pass to rebuild length.
            prompt += f"HOOK: {variant.hook[:800]}\n\n"
            for seg in variant.segments:
                # Send scene vos if available, else narration
                if seg.scenes:
                    vos = " | ".join(sc.voiceover for sc in seg.scenes)
                    prompt += f"SEGMENT {seg.index}: {seg.heading}\nScenes: {vos[:2000]}\n\n"
                else:
                    prompt += f"SEGMENT {seg.index}: {seg.heading}\n{seg.content[:1500]}\n\n"
            prompt += f"OUTRO: {variant.outro[:500]}\n\n"

        if niche_cfg and niche_cfg.content_format == "narrative":
            prompt += (
                "\nWrite the merged script now. Preserve the requested story count; "
                "use one SEGMENT per story and do not add any CTA or host framing. "
                "Start with 'HOOK:' on line 1."
            )
        else:
            prompt += (
                "\nWrite the merged superior script now using scene-based JSON format. "
                "Output SCENES blocks with valid JSON arrays. "
                "Natural open-loops in 'vo' at end of Segment 1 and 3. "
                "Start with 'HOOK:' on line 1."
            )

        try:
            self._call_count += 1
            logger.info("Agent LLM call started", agent=self.name, message_count=1)
            response = await self._llm.complete(
                system=niche_system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,  # merged script = ~30-40 verbose scene objects; 4000 truncated (→748-word output)
            )
            logger.info(
                "Agent LLM call completed",
                agent=self.name,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
            )
            self._last_cost_usd = response.cost_usd
            evolved = _parse_evolution_response(response.content, brief)
            logger.info("Evolution agent completed", variants_count=len(variants))
            return evolved

        except Exception as exc:
            raise AgentError(f"Evolution failed: {exc}") from exc


def _parse_scenes_json(block: str) -> list[ScriptScene]:
    """Extract and parse SCENES JSON array from a section block.

    Uses JSONDecoder.raw_decode (NOT a non-greedy regex): scene objects contain
    nested arrays (``"emphasis": []``) that ``r"\\[.*?\\]"`` truncates at the first
    inner ``]``. Parses prosody fields (pace/pause_after_ms/emphasis) so the
    evolved winner keeps its delivery direction — matches the Writer's parser.
    """
    m = re.search(r"SCENES\s*:\s*\[", block, re.IGNORECASE)
    if not m:
        return []
    start = m.end() - 1  # opening '['
    raw_json = block[start:]
    dec = json.JSONDecoder()
    try:
        items, _ = dec.raw_decode(raw_json)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([\]}])", r"\1", raw_json)
        try:
            items, _ = dec.raw_decode(cleaned)
        except json.JSONDecodeError:
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
        scenes.append(ScriptScene(
            voiceover=vo,
            visual_prompt=visual,
            sfx=sfx,
            duration_s=round(word_count / 2.5, 1),
            pace=pace,
            pause_after_ms=pause_after_ms,
            emphasis=emphasis,
        ))
    return scenes


def _parse_evolution_response(text: str, brief: TopicBrief) -> ScriptDraft:
    """Parse LLM response into ScriptDraft. Supports scene-based JSON format."""

    # Strip markdown bold/italic around section headers
    text = re.sub(r"\*+", "", text)

    # Extract HOOK
    hook_match = re.search(
        r"HOOK\s*:\s*\n?(.*?)(?=\nSEGMENT\s*1|\Z)", text, re.DOTALL | re.IGNORECASE
    )
    hook_raw = hook_match.group(1).strip() if hook_match else ""
    hook_scenes = _parse_scenes_json(hook_raw)
    hook = " ".join(sc.voiceover for sc in hook_scenes) if hook_scenes else hook_raw.strip()

    # Extract OUTRO
    outro_match = re.search(
        r"OUTRO\s*:\s*\n?(.*?)$", text, re.DOTALL | re.IGNORECASE
    )
    outro_raw = outro_match.group(1).strip() if outro_match else ""
    outro_scenes = _parse_scenes_json(outro_raw)
    outro = " ".join(sc.voiceover for sc in outro_scenes) if outro_scenes else outro_raw.strip()

    # Extract all SEGMENT blocks
    segment_matches = re.findall(
        r"SEGMENT\s*(\d+)\s*:\s*([^\n]*)\n(.*?)(?=\nSEGMENT\s*\d+|\nOUTRO|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )

    seen: set[int] = set()
    segments = []
    for idx_str, title, body in segment_matches:
        idx = int(idx_str)
        if idx in seen:
            continue
        seen.add(idx)
        body_clean = body.strip()
        scenes = _parse_scenes_json(body_clean)
        if scenes:
            narration = " ".join(sc.voiceover for sc in scenes)
            duration_s = max(30, int(sum(sc.duration_s for sc in scenes)))
        else:
            # Fallback: plain text
            narration = body_clean
            duration_s = max(30, int(len(narration.split()) / 2.5))
        segments.append(ScriptSegment(
            index=idx,
            heading=title.strip(),
            content=narration,
            scenes=scenes,
            estimated_duration_seconds=duration_s,
        ))

    # Fallback: if parser got nothing
    if not hook and not segments:
        hook = text.strip()

    all_narration = " ".join([hook] + [s.content for s in segments] + [outro])
    word_count = len(all_narration.split())

    return ScriptDraft(
        variant_id="evolved",
        brief_title=brief.title,
        hook=hook,
        hook_scenes=hook_scenes,
        segments=segments,
        outro=outro,
        outro_scenes=outro_scenes,
        word_count=word_count,
        estimated_duration_seconds=int(word_count * 0.4),
        version=1,
    )
