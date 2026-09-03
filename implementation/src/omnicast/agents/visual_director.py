"""Visual Director Agent — fixes visual_prompt + sfx per scene without touching VO.

Triggered when:
  voiceover_score >= VO_PASS (53)  AND  production_score < PROD_PASS (23)

The VO text is fully locked. Only visual_prompt and sfx fields are rewritten.
Uses DeepSeek v4 Flash — no deep reasoning needed, just visual creativity.
Cheap: pattern-matching task, not legal/compliance reasoning.

NEW: Also supports AI media gen enrichment (image_prompt, video_prompt, etc.)
via the enrich() method for the new provider-based media pipeline.
"""

from __future__ import annotations

import json
import re
import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft, ScriptSegment, ScriptScene, TopicBrief
from omnicast.config.niches import NicheConfig, get_niche_config
from omnicast.media.style_guide import StyleGuide
from omnicast.media.prompt_builder import format_style_guide_for_prompt
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class VisualDirectorAgent(BaseAgent):
    """Rewrites visual_prompt and sfx for every scene. VO text is never touched.

    Input:  ScriptDraft (with scenes having weak visual_prompt/sfx)
    Output: ScriptDraft (same VO, improved visual_prompt + sfx)
    
    NEW: Also supports AI media gen enrichment via enrich() method.
    """

    def __init__(self, llm: LLMClient) -> None:
        """
        Args:
            llm: Should be LLMClient(provider="deepseek", model=settings.deepseek_flash_model)
                 DeepSeek v4 Flash — fast + cheap for mechanical visual generation.
        """
        super().__init__(llm)

    @property
    def name(self) -> str:
        return "visual_director"

    @property
    def system_prompt(self) -> str:
        return (
            "You are a YouTube video visual director. "
            "You receive a list of scenes where the voiceover (VO) text is final and locked. "
            "Your ONLY job: write a specific, filmable visual_prompt and appropriate sfx for each scene. "
            "Rules for visual_prompt: include SUBJECT + ACTION + CONTEXT. Must be searchable on Pexels/Storyblocks. "
            "BANNED visuals: 'relevant footage', 'appropriate visual', 'person looking worried', 'related imagery'. "
            "Rules for sfx: use the niche primary/secondary SFX only on key numbers or dramatic reveals. "
            "Output valid JSON array only. No explanation outside JSON."
        )

    async def execute(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        *,
        niche_cfg: NicheConfig | None = None,
        visual_fixes: list[str] | None = None,
        channel_brand: dict | None = None,
    ) -> ScriptDraft:
        """Rewrite visual_prompt + sfx for all scenes. Returns new ScriptDraft."""
        if niche_cfg is None:
            niche_cfg = get_niche_config(brief.niche.value, getattr(brief, "sub_niche", ""))

        prompt = self._build_prompt(draft, brief, niche_cfg, visual_fixes or [])

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                max_tokens=min(
                    16000,
                    max(4000, self._scene_count(draft) * 70),
                ),
                temperature=0.4,
            )
            improved_scenes_map = self._parse_response(response.content)
            new_draft = self._apply_scenes(draft, improved_scenes_map)
            logger.info(
                "Visual Director completed",
                variant_id=draft.variant_id,
                scenes_updated=len(improved_scenes_map),
            )
            return new_draft
        except Exception as exc:
            logger.warning("Visual Director failed — returning original draft", error=str(exc))
            return draft  # safe fallback: original VO+visuals unchanged

    @staticmethod
    def _scene_count(draft: ScriptDraft) -> int:
        return (
            len(draft.hook_scenes)
            + sum(len(segment.scenes) for segment in draft.segments)
            + len(draft.outro_scenes)
        )

    async def enrich(
        self,
        draft: ScriptDraft,
        guide: StyleGuide,
        brief: TopicBrief | None = None,
    ) -> ScriptDraft:
        """Enrich ScriptDraft with AI media gen fields (image_prompt, video_prompt, etc.).
        
        This is the NEW method for the provider-based media pipeline.
        It populates the 5 new fields in ScriptScene:
        - image_prompt: detailed prompt for image generation
        - negative_prompt: what to avoid
        - video_prompt: camera/motion for image-to-video
        - text_overlay: text to display on scene
        - transition: cut | fade | dissolve | whip-pan
        
        Args:
            draft: ScriptDraft to enrich
            guide: StyleGuide for visual direction
            brief: Optional TopicBrief for context
        
        Returns:
            ScriptDraft with AI media gen fields populated
        """
        # Process each segment (batching scenes per segment)
        new_segments = []
        
        for seg in draft.segments:
            if not seg.scenes:
                new_segments.append(seg)
                continue
            
            # Build prompt for this segment's scenes
            prompt = self._build_enrich_prompt(seg, guide, brief)
            
            try:
                response = await self.call_llm(
                    [{"role": "user", "content": prompt}],
                    max_tokens=3000,
                    temperature=0.3,
                )
                enriched_scenes = self._parse_enrich_response(response.content, len(seg.scenes))
                new_scenes = self._apply_enrich_to_scenes(seg.scenes, enriched_scenes)
                new_segments.append(seg.model_copy(update={"scenes": new_scenes}))
            except Exception as exc:
                logger.warning("Enrich failed for segment, keeping original", segment=seg.heading, error=str(exc))
                new_segments.append(seg)
        
        new_draft = draft.model_copy(update={"segments": new_segments})
        logger.info(
            "Visual Director enrich completed",
            variant_id=draft.variant_id,
            segments_processed=len(new_segments),
        )
        return new_draft

    def _build_prompt(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        niche_cfg: NicheConfig,
        visual_fixes: list[str],
    ) -> str:
        sfx_opts = f"{niche_cfg.sfx_primary} | {niche_cfg.sfx_secondary} | whoosh | ting | null"
        fixes_block = ""
        if visual_fixes:
            fixes_block = "\nCRITIC VISUAL FIXES TO ADDRESS:\n" + "\n".join(
                f"  - {f}" for f in visual_fixes
            ) + "\n"

        # Build scene list
        scene_items: list[str] = []
        scene_id = 0

        def _add_scene(sid: int, vo: str, visual: str, sfx: str | None) -> None:
            scene_items.append(
                f'{{"scene_id": {sid}, "vo_locked": "{_esc(vo)}", '
                f'"current_visual": "{_esc(visual)}", "current_sfx": "{sfx or "null"}"}}'
            )

        # Hook — use the actual storyboard scenes when present so changes can be
        # applied, rather than generating throwaway pseudo-scenes.
        if draft.hook_scenes:
            for scene in draft.hook_scenes:
                scene_id += 1
                _add_scene(
                    scene_id, scene.voiceover,
                    scene.visual_prompt, scene.sfx)
        else:
            for sentence in re.split(r"(?<=[.!?])\s+", draft.hook.strip()):
                if sentence:
                    scene_id += 1
                    _add_scene(
                        scene_id, sentence, "(hook — needs visual)", None)

        # Segments
        for seg in draft.segments:
            if seg.scenes:
                for sc in seg.scenes:
                    scene_id += 1
                    _add_scene(scene_id, sc.voiceover, sc.visual_prompt, sc.sfx)
            else:
                # Legacy: no scenes → treat whole segment as one block
                scene_id += 1
                _add_scene(scene_id, seg.content[:100], "(no scene data)", None)

        # Outro
        if draft.outro_scenes:
            for scene in draft.outro_scenes:
                scene_id += 1
                _add_scene(
                    scene_id, scene.voiceover,
                    scene.visual_prompt, scene.sfx)
        elif draft.outro:
            scene_id += 1
            _add_scene(
                scene_id, draft.outro[:100], "(outro — needs visual)", None)

        scenes_json = "[\n  " + ",\n  ".join(scene_items) + "\n]"

        prompt = f"""Topic: {brief.title}
Niche: {brief.niche.value} | Voice: {niche_cfg.insider_angle}
Typical visuals for this niche: {niche_cfg.broll_style}
Available SFX: {sfx_opts}
Verified official source pages: {", ".join(brief.source_urls) or "(none supplied)"}
{fixes_block}
SCENES (vo_locked = DO NOT CHANGE, fix visual and sfx only):
{scenes_json}

OUTPUT: JSON array with one object per scene. Keep scene_id and vo_locked EXACTLY as given.
Only change visual_prompt and sfx.
[
  {{
    "scene_id": 1,
    "vo_locked": "<exact original VO>",
    "visual_prompt": "<subject + action + context — specific and filmable>",
    "sfx": "<{niche_cfg.sfx_primary}|{niche_cfg.sfx_secondary}|whoosh|ting|null>"
  }},
  ...
]

VISUAL PROMPT RULES:
- Must name a SPECIFIC subject (not 'person' — say 'worried 55-year-old man')
- Must include an ACTION ('reviewing 401k statement' not 'looking at paper')
- Must include CONTEXT ('at kitchen table, morning light' or 'on trading floor')
- Must be findable on Pexels/Storyblocks with this exact query
- Official screenshots, forms, calculators, statement fields, and document
  titles may be named ONLY when they occur in the verified source-page list
  above. Never invent a form field or tool to satisfy a critic suggestion.
- For verified official pages, request a legible screen capture of that exact
  URL or a faithful diagram of the spoken rule; do not fabricate UI contents.
- Match SFX to the VO moment: use {niche_cfg.sfx_primary} when a key number is spoken, {niche_cfg.sfx_secondary} for warnings/reveals
"""
        return prompt

    def _parse_response(self, content: str) -> dict[int, tuple[str, str | None]]:
        """Parse LLM response → {scene_id: (visual_prompt, sfx)}."""
        m = re.search(r"\[.*?\]", content, re.DOTALL)
        if not m:
            return {}
        raw = m.group(0)
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([\]}])", r"\1", raw)
            try:
                items = json.loads(cleaned)
            except json.JSONDecodeError:
                return {}

        result = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = item.get("scene_id")
            visual = str(item.get("visual_prompt", "")).strip()
            sfx_raw = item.get("sfx", None)
            sfx = str(sfx_raw).strip() if sfx_raw and sfx_raw != "null" else None
            if sid is not None and visual:
                result[int(sid)] = (visual, sfx)
        return result

    def _apply_scenes(
        self,
        draft: ScriptDraft,
        scenes_map: dict[int, tuple[str, str | None]],
    ) -> ScriptDraft:
        """Apply improved visuals to draft. Only visual_prompt + sfx change."""
        if not scenes_map:
            return draft

        scene_id = 0

        new_hook_scenes: list[ScriptScene] = []
        if draft.hook_scenes:
            for scene in draft.hook_scenes:
                scene_id += 1
                if scene_id in scenes_map:
                    visual, sfx = scenes_map[scene_id]
                    new_hook_scenes.append(scene.model_copy(update={
                        "visual_prompt": visual,
                        "sfx": sfx,
                    }))
                else:
                    new_hook_scenes.append(scene)
        else:
            # Pseudo hook records have no ScriptScene to update.
            scene_id += len([
                sentence
                for sentence in re.split(
                    r"(?<=[.!?])\s+", draft.hook.strip())
                if sentence
            ])

        new_segments: list[ScriptSegment] = []
        for seg in draft.segments:
            if not seg.scenes:
                scene_id += 1  # skip legacy segment
                new_segments.append(seg)
                continue

            new_scenes: list[ScriptScene] = []
            for sc in seg.scenes:
                scene_id += 1
                if scene_id in scenes_map:
                    visual, sfx = scenes_map[scene_id]
                    new_scenes.append(sc.model_copy(update={
                        "visual_prompt": visual,
                        "sfx": sfx,
                    }))
                else:
                    new_scenes.append(sc)

            new_segments.append(seg.model_copy(update={"scenes": new_scenes}))

        new_outro_scenes: list[ScriptScene] = []
        if draft.outro_scenes:
            for scene in draft.outro_scenes:
                scene_id += 1
                if scene_id in scenes_map:
                    visual, sfx = scenes_map[scene_id]
                    new_outro_scenes.append(scene.model_copy(update={
                        "visual_prompt": visual,
                        "sfx": sfx,
                    }))
                else:
                    new_outro_scenes.append(scene)

        return draft.model_copy(update={
            "hook_scenes": new_hook_scenes,
            "segments": new_segments,
            "outro_scenes": new_outro_scenes,
        })

    def _build_enrich_prompt(
        self,
        seg: ScriptSegment,
        guide: StyleGuide,
        brief: TopicBrief | None,
    ) -> str:
        """Build prompt for AI media gen enrichment."""
        # Format style guide
        style_guide_md = format_style_guide_for_prompt(guide)
        
        # Build scene list
        scene_items = []
        for i, scene in enumerate(seg.scenes):
            scene_items.append(
                f'{i}. VO: "{scene.voiceover}"\n   Visual: "{scene.visual_prompt}"'
            )
        
        scenes_text = "\n".join(scene_items)
        
        # Build brief context
        brief_ctx = ""
        if brief:
            brief_ctx = f"""
Brief: {brief.title}
Niche: {brief.niche.value}
Brand Voice: {brief.brand_voice}
"""
        
        prompt = f"""You are a Visual Director. Convert each scene's narration + b-roll query
into AI generation prompts for image and image-to-video models.

For EACH scene, output JSON:
{{
  "scene_idx": <int>,
  "image_prompt": "Detailed visual description for AI image generation.
                  Concrete subjects, setting, lighting, composition.
                  50-80 words. NO camera motion (that's video_prompt's job).",
  "negative_prompt": "Things to avoid: blurry, distorted, watermark, text,
                     low quality, deformed faces, extra limbs",
  "video_prompt": "Camera and motion description for image-to-video.
                  Subject motion, camera move (pan/zoom/dolly), pacing.
                  20-40 words. References the image.",
  "transition": "cut | fade | dissolve | whip-pan"
}}

{style_guide_md}

{brief_ctx}
Continuity rule: each scene continues from the previous (same world,
same characters, same lighting unless scene change). Use transition to
signal scene breaks.

Process this segment ({seg.heading}):
{scenes_text}

Output a JSON array of {len(seg.scenes)} objects in scene order."""
        return prompt

    def _parse_enrich_response(self, content: str, expected_count: int) -> list[dict]:
        """Parse LLM response → list of scene enrichment data."""
        m = re.search(r"\[.*?\]", content, re.DOTALL)
        if not m:
            logger.warning("No JSON array found in enrich response")
            return []
        
        raw = m.group(0)
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*([\]}])", r"\1", raw)
            try:
                items = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse enrich JSON", error=str(exc))
                return []
        
        if not isinstance(items, list):
            logger.warning("Enrich response is not a list")
            return []
        
        # Validate and normalize
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result.append({
                "scene_idx": item.get("scene_idx", 0),
                "image_prompt": str(item.get("image_prompt", "")).strip(),
                "negative_prompt": str(item.get("negative_prompt", "")).strip(),
                "video_prompt": str(item.get("video_prompt", "")).strip(),
                "transition": str(item.get("transition", "cut")).strip(),
            })
        
        return result

    def _apply_enrich_to_scenes(
        self,
        scenes: list[ScriptScene],
        enriched_data: list[dict],
    ) -> list[ScriptScene]:
        """Apply enrichment data to scenes."""
        if not enriched_data:
            return scenes
        
        # Build map by scene_idx
        data_map = {item["scene_idx"]: item for item in enriched_data}
        
        new_scenes = []
        for i, scene in enumerate(scenes):
            if i in data_map:
                data = data_map[i]
                new_scenes.append(ScriptScene(
                    voiceover=scene.voiceover,
                    visual_prompt=scene.visual_prompt,
                    sfx=scene.sfx,
                    duration_s=scene.duration_s,
                    image_prompt=data["image_prompt"],
                    negative_prompt=data["negative_prompt"],
                    video_prompt=data["video_prompt"],
                    text_overlay="",  # Not populated by LLM in this version
                    transition=data["transition"],
                ))
            else:
                new_scenes.append(scene)
        
        return new_scenes


def _esc(s: str) -> str:
    """Escape double quotes for JSON string embedding."""
    return s.replace('"', '\\"').replace("\n", " ")
