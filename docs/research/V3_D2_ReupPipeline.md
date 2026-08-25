# V3_D2 — Tool_Reup_Douyin (Reup Video): full zh→vi translate/dub pipeline extraction
**Working root:** `_refs/Tool_Reup_Douyin`  
**License:** NO LICENSE file; owner confirmed community repo + cleared direct reuse → **free to copy**. Port plan uses `copy as-is` / `copy + adapt` / `drop` (not clean-room reimplement).
**Scope note:** Prompts, thresholds, DDL, ffmpeg graphs, and gates are verbatim with `file:line`.

## 0. TL;DR — what to port, ranked
1. **Semantic QC rule set** (`semantic_qc.py`) + review gate predicate — hard-blocks TTS/export.
2. **Prompt family set** in `translate/presets.py` (dialogue + narration-fast + narration-fast-v2 + cartoon) — all system/user prompts.
3. **Scene routing predicate** (narration_score thresholds 0.75/0.45 + cue densities).
4. **Honorific / pronoun QC** (`COMMON_VI_PRONOUNS`, sub/tts divergence, locked relation directionality).
5. **Relationship memory + allowed_alternates side-specific whitelist**.
6. **Batch split-on-failure** for mismatched ids + retryable parse failures.
7. **Narration Fast V2 budget governor** (max $0.30, soft_stop 0.85, sparse escalation caps).
8. **Scientific notation autofix** for incomplete `10^`.
9. **subtitle_text vs tts_text dual fields** + narration neutralize helpers.
10. **Voice track fit** (atempo 0.5–2.0 chain, pad/trim to slot).
11. **Mix levels** original=0.07 voice=1.0 + loudnorm I=-16:TP=-1.5:LRA=11.
12. **Prompt cache key** sha1(family|role|model|langs|schema|route|profile).
13. **Structured Outputs schemas** in `translate/models.py`.
14. **Checkpoint resume** `contextual_translation.partial.json`.
15. **ASS style + Windows path escape** for hardsub.
16. **TTS clip hash** (text + full voice preset JSON).
17. **Project profiles** narration clear/fast/v2 numeric defaults.
18. **Doctor preflight** stage-blocking checks.
19. **Export presets** youtube-16x9 CRF18 / shorts-9x16 CRF20.
20. **Ops docs** REVIEW_REASON_CODES / ERROR_TAXONOMY / SEMANTIC_QC_SPEC as living QC knowledge.

## 1. Pipeline topology (exact)
### Entry
- UI / headless calls `run_contextual_translation` in `contextual_runtime.py`.
- If selected template is narration-fast-v2 family → delegates to `run_contextual_translation_v2` in `narration_fast_v2.py`.
```python
def run_contextual_translation(
    context: JobContext,
    *,
    workspace,
    database: ProjectDatabase,
    engine: OpenAITranslationEngine,
    segments: list[Row],
    selected_template: TranslationPromptTemplate,
    source_language: str,
    target_language: str,
    model: str,
    checkpoint_state: ContextualTranslationCheckpointState | None = None,
    checkpoint_writer: Callable[[list[SceneMemoryRecord], list[CharacterProfileRecord], list[RelationshipProfileRecord], list[SegmentAnalysisRecord], list[SceneRouteDecision], list[SceneTermEntitySheet], ContextualRunMetrics, list[str], int], None] | None = None,
) -> dict[str, object]:
    if is_narration_fast_v2_template(selected_template):
        from .narration_fast_v2 import run_contextual_translation_v2

        return run_contextual_translation_v2(
            context,
            workspace=workspace,
            database=database,
            engine=engine,
            segments=segments,
            selected_template=selected_template,
            source_language=source_language,
            target_language=target_language,
            model=model,
            checkpoint_state=checkpoint_state,
            checkpoint_writer=checkpoint_writer,
        )
```
-> `src/app/translate/contextual_runtime.py:619-648`
### Routing predicate (which lane a scene uses)
Base router `_route_scene` (used by both lanes):
```python
NARRATION_FAST_BATCH_SIZE = 16
NARRATION_ROUTE_HIGH_CONFIDENCE = 0.75
NARRATION_ROUTE_LOW_CONFIDENCE = 0.45
_ROUTING_REVIEW_CODES = {
    "uncertain_speaker",
    "uncertain_listener",
    "unclear_relationship",
    "unclear_context",
    "ambiguous_reference",
    "ambiguous_object_reference",
}
_VOCATIVE_PATTERN = re.compile(r"(各位|大家|朋友们|兄弟们|姐妹们|先生们|女士们|同学们|孩子们|观众朋友们)")
_BACKCHANNEL_PATTERN = re.compile(r"^(嗯|啊|哦|诶|欸|哎|呀|唉|好|行|对|是啊|对啊|嗯嗯)[！!。.\s]*$")
```
-> `src/app/translate/contextual_runtime.py:56-68`
```python
def _is_short_utterance(text: str) -> bool:
    return len(text.strip()) <= 12


def _is_long_sentence(text: str) -> bool:
    normalized = text.strip()
    return len(normalized) >= 24 or normalized.count("，") + normalized.count(",") >= 2


def _prior_review_penalty(scene, prior_analysis_rows: dict[str, dict[str, object]]) -> float:
    flagged = 0
    for row in scene.segments:
        analysis_row = prior_analysis_rows.get(str(row["segment_id"]))
        if not analysis_row:
            continue
        raw_codes = analysis_row.get("review_reason_codes_json") or []
        if isinstance(raw_codes, str):
            try:
                raw_codes = json.loads(raw_codes)
            except Exception:
                raw_codes = []
        normalized_codes = {_normalize_review_reason_code(str(item)) for item in raw_codes}
        if normalized_codes & _ROUTING_REVIEW_CODES:
            flagged += 1
    return _safe_ratio(flagged, len(scene.segments))


def _speaker_metrics_for_scene(scene, prior_analysis_rows: dict[str, dict[str, object]]) -> tuple[float, float]:
    speaker_keys: list[str] = []
    for row in scene.segments:
        analysis_row = prior_analysis_rows.get(str(row["segment_id"]))
        if not analysis_row:
            continue
        speaker_json = analysis_row.get("speaker_json") or {}
        if isinstance(speaker_json, str):
            try:
                speaker_json = json.loads(speaker_json)
            except Exception:
                speaker_json = {}
        speaker_key = str((speaker_json or {}).get("character_id") or "").strip().lower()
        if speaker_key and speaker_key != "unknown":
            speaker_keys.append(speaker_key)
    if not speaker_keys:
        return 0.6, 0.5
    dominance = max(speaker_keys.count(key) for key in set(speaker_keys)) / len(speaker_keys)
    if len(speaker_keys) <= 1:
        return max(0.0, min(1.0, dominance)), 0.0
    switches = sum(1 for left, right in zip(speaker_keys, speaker_keys[1:]) if left != right)
    return max(0.0, min(1.0, dominance)), _safe_ratio(switches, len(speaker_keys) - 1)


def _route_scene(
    scene,
    *,
    prior_analysis_rows: dict[str, dict[str, object]],
    narration_family_id: str,
    dialogue_family_id: str,
    prefer_narration: bool = False,
) -> SceneRouteDecision:
    texts = [str(row["source_text"] or "").strip() for row in scene.segments]
    nonempty_texts = [text for text in texts if text]
    total = max(1, len(nonempty_texts))
    speaker_dominance, speaker_switch_density = _speaker_metrics_for_scene(scene, prior_analysis_rows)
    question_density = _safe_ratio(sum(1 for text in nonempty_texts if "?" in text or "？" in text), total)
    vocative_density = _safe_ratio(sum(1 for text in nonempty_texts if _VOCATIVE_PATTERN.search(text)), total)
    backchannel_density = _safe_ratio(sum(1 for text in nonempty_texts if _BACKCHANNEL_PATTERN.match(text)), total)
    short_utterance_ratio = _safe_ratio(sum(1 for text in nonempty_texts if _is_short_utterance(text)), total)
    long_sentence_ratio = _safe_ratio(sum(1 for text in nonempty_texts if _is_long_sentence(text)), total)
    prior_penalty = _prior_review_penalty(scene, prior_analysis_rows)
    narration_score = (
        0.32 * speaker_dominance
        + 0.18 * (1.0 - speaker_switch_density)
        + 0.18 * long_sentence_ratio
        + 0.10 * (1.0 - short_utterance_ratio)
        + 0.08 * (1.0 - question_density)
        + 0.06 * (1.0 - vocative_density)
        + 0.05 * (1.0 - backchannel_density)
        - 0.15 * prior_penalty
    )
    if prefer_narration:
        narration_score += 0.2
        if (
            question_density == 0.0
            and vocative_density == 0.0
            and backchannel_density == 0.0
            and prior_penalty == 0.0
            and speaker_switch_density <= 0.5
        ):
            narration_score = max(narration_score, 0.76)
    narration_score = max(0.0, min(1.0, narration_score))
    route_mode = "dialogue"
    prompt_family_id = dialogue_family_id
    fallback_reason = ""
    if narration_score >= NARRATION_ROUTE_HIGH_CONFIDENCE:
        route_mode = "narration_fast"
        prompt_family_id = narration_family_id
    elif narration_score > NARRATION_ROUTE_LOW_CONFIDENCE:
        fallback_reason = "borderline_narration_score"
    return SceneRouteDecision(
        scene_id=scene.scene_id,
        scene_index=scene.scene_index,
        route_mode=route_mode,
        prompt_family_id=prompt_family_id,
        narration_score=round(narration_score, 4),
        speaker_dominance=round(speaker_dominance, 4),
        speaker_switch_density=round(speaker_switch_density, 4),
        question_density=round(question_density, 4),
        vocative_density=round(vocative_density, 4),
        backchannel_density=round(backchannel_density, 4),
        short_utterance_ratio=round(short_utterance_ratio, 4),
        long_sentence_ratio=round(long_sentence_ratio, 4),
        prior_review_penalty=round(prior_penalty, 4),
        fallback_reason=fallback_reason,
    )
```
-> `src/app/translate/contextual_runtime.py:171-284`
**Thresholds:** `NARRATION_ROUTE_HIGH_CONFIDENCE = 0.75` → `route_mode='narration_fast'`; score in `(0.45, 0.75]` → stay dialogue with `fallback_reason='borderline_narration_score'`; `<=0.45` → dialogue.
**Narration Fast V2 remaps** via `_route_scene_v2`:
```python
NARRATION_FAST_V2_ROUTE = "narration_fast_v2"
DIALOGUE_LEGACY_ROUTE = "dialogue_legacy"
NARRATION_FAST_V2_ROUTER_VERSION = "narration_fast_v2"
NARRATION_FAST_V2_POSTPROCESS_VERSION = "narration_fast_v2"
NARRATION_SPAN_MAX_GAP_MS = 1500
NARRATION_SPAN_MAX_RENDER_UNITS = 48
NARRATION_SPAN_MAX_SOURCE_CHARS = 3200
NARRATION_SPAN_MAX_DURATION_MS = 90_000
TARGET_CPS = 16.0
SLOT_PRESSURE_THRESHOLD = 1.10
```
-> `src/app/translate/narration_fast_v2.py:60-69`
```python
def _route_scene_v2(
    scene: SceneChunk,
    *,
    prior_analysis_rows: dict[str, dict[str, object]],
    narration_family_id: str,
    dialogue_family_id: str,
    prefer_narration: bool,
) -> SceneRouteDecision:
    decision = _route_scene(
        scene,
        prior_analysis_rows=prior_analysis_rows,
        narration_family_id=narration_family_id,
        dialogue_family_id=dialogue_family_id,
        prefer_narration=prefer_narration,
    )
    if (
        decision.route_mode == "narration_fast"
        and (
            _contains_direct_speech(scene)
            or decision.prior_review_penalty > 0.34
            or decision.narration_score < NARRATION_ROUTE_HIGH_CONFIDENCE
        )
    ):
        return decision.model_copy(
            update={
                "route_mode": DIALOGUE_LEGACY_ROUTE,
                "prompt_family_id": dialogue_family_id,
                "fallback_reason": decision.fallback_reason or "mixed_dialogue_cues",
            }
        )
    return decision.model_copy(
        update={
            "route_mode": (
                NARRATION_FAST_V2_ROUTE
                if decision.route_mode == "narration_fast"
                else DIALOGUE_LEGACY_ROUTE
            ),
            "prompt_family_id": (
                narration_family_id
                if decision.route_mode == "narration_fast"
                else dialogue_family_id
            ),
        }
    )
```
-> `src/app/translate/narration_fast_v2.py:193-236`
- If base chose `narration_fast` BUT (direct speech markers OR prior_review_penalty > 0.34 OR narration_score < 0.75) → force `dialogue_legacy`.
- Else `narration_fast` → `narration_fast_v2`; dialogue → `dialogue_legacy`.
### Lane A — Contextual V2 dialogue (`route_mode='dialogue'`)
Ordered stages (per scene, after `chunk_segments_into_scenes`):
| # | Stage | Function | File | LLM? | Model | I/O |
|---|-------|----------|------|------|-------|-----|
| 0 | Scene chunk | `chunk_segments_into_scenes` | `scene_chunker.py:28` | det | — | segments→SceneChunk |
| 1 | Route | `_route_scene` | `contextual_runtime.py:222` | det | — | SceneChunk→SceneRouteDecision |
| 2 | Scene planner | `engine.plan_scene` / LLM `scene_planner` | openai_engine + runtime | LLM | settings.default_translation_model (`gpt-4.1-mini`) | scene payload→ScenePlannerOutput |
| 3 | Semantic pass (batches of 8) | `engine.analyze_semantics` | openai_engine | LLM | same | batch→SemanticBatchOutput |
| 4 | Dialogue adaptation (batches of 8) | `engine.adapt_dialogue` | openai_engine | LLM | same | batch→DialogueAdaptationBatchOutput |
| 5 | Semantic critic (optional, non-narration) | `engine.critique_semantics` | openai_engine | LLM | same | batch→SemanticCriticBatchOutput |
| 6 | Semantic QC | `analyze_segment_analyses` | `semantic_qc.py:188` | det | — | analyses→issues |
| 7 | Persist + checkpoint | `persist_contextual_translation_*` | contextual_pipeline / checkpoint | det | — | DB+cache |
Dialogue batch size constant:
```python
CONTEXTUAL_STAGE_BATCH_SIZE = 8

```
-> `src/app/translate/contextual_pipeline.py:27-28`
### Lane B — narration_fast (v1, family `contextual-narration-fast-vi`)
When `is_narration_fast_template` or profile id starts with `zh-vi-narration-` and route_mode=`narration_fast`:
- **Skip LLM scene planner** → local `_build_narration_fast_scene_plan`
- Optional **term/entity mini-pass** if `_should_run_narration_term_entity_pass`
- Semantic + adaptation with **positional** structured outputs (no segment_id), batch size `NARRATION_FAST_BATCH_SIZE=16`
- **Skip critic** on pure narration path
```python
def _should_run_narration_term_entity_pass(scene, route_decision: SceneRouteDecision) -> bool:
    if route_decision.route_mode != "narration_fast":
        return False
    texts = [str(row["source_text"] or "").strip() for row in scene.segments]
    nonempty_texts = [text for text in texts if text]
    if len(nonempty_texts) < 2:
        return False
    total_chars = sum(len(text) for text in nonempty_texts)
    intro_marker_hits = sum(1 for text in nonempty_texts if any(marker in text for marker in _TERM_INTRO_PATTERNS))
    has_latin_or_digit = any(_LATIN_OR_DIGIT_PATTERN.search(text) for text in nonempty_texts)
    return total_chars >= 72 and (
        route_decision.long_sentence_ratio >= 0.35
        or intro_marker_hits > 0
        or has_latin_or_digit
        or len(nonempty_texts) >= 6
    )
```
-> `src/app/translate/contextual_runtime.py:287-302`
```python
def _build_narration_fast_scene_plan(scene) -> ScenePlannerOutput:
    lead_text = str(scene.segments[0]["source_text"] or "").strip() if scene.segments else ""
    short_lead = lead_text[:96] + ("..." if len(lead_text) > 96 else "")
    summary = f"Narration fast path scene with {len(scene.segments)} segments. Lead: {short_lead or 'narration batch'}"
    return ScenePlannerOutput(
        scene_id=scene.scene_id,
        scene_summary=summary,
        participants=[],
        recent_turn_digest=short_lead,
        open_ambiguities=[],
        unresolved_references=[],
        character_updates=[],
        relationship_updates=[],
    )
```
-> `src/app/translate/contextual_runtime.py:149-162`
### Lane C — narration_fast_v2 (`NARRATION_FAST_V2_ROUTE`)
Ordered stages:
| # | Stage | Function | LLM? |
|---|-------|----------|------|
| 0 | Scene chunk | `chunk_segments_into_scenes` | det |
| 1 | Route v2 | `_route_scene_v2` | det |
| 2 | Span build | `_build_narration_spans` (gap 1500ms, max 48 units, 3200 chars, 90s) | det |
| 3 | Base semantic | 1 pass → `canonical_text` only | LLM |
| 4 | Scientific notation autofix | `_apply_scientific_notation_autofix` | det |
| 5 | Sparse entity micro | if budget + hard entity flags | LLM |
| 6 | Sparse ambiguity micro | if budget + ambiguity flags | LLM |
| 7 | Slot rewrite | if slot_pressure > 1.10 | LLM |
| 8 | Local materialize | subtitle_text = tts_text = canonical_text | det |
| 9 | Dialogue legacy scenes | full dialogue stages via `_append_dialogue_scene_analyses` | LLM |
|10 | Semantic QC | `analyze_segment_analyses` | det |
```python
NARRATION_SPAN_MAX_GAP_MS = 1500
NARRATION_SPAN_MAX_RENDER_UNITS = 48
NARRATION_SPAN_MAX_SOURCE_CHARS = 3200
NARRATION_SPAN_MAX_DURATION_MS = 90_000
TARGET_CPS = 16.0
SLOT_PRESSURE_THRESHOLD = 1.10
```
-> `src/app/translate/narration_fast_v2.py:64-69`
```python
def _build_narration_spans(
    scenes: list[SceneChunk],
    route_decisions: list[SceneRouteDecision],
) -> tuple[list[NarrationSpan], dict[str, NarrationSpan]]:
    spans: list[NarrationSpan] = []
    span_by_scene_id: dict[str, NarrationSpan] = {}
    current_scenes: list[SceneChunk] = []

    def flush() -> None:
        nonlocal current_scenes
        if not current_scenes:
            return
        span_index = len(spans)
        span = NarrationSpan(
            span_id=f"span_{span_index:04d}",
            span_index=span_index,
            scene_ids=[scene.scene_id for scene in current_scenes],
            scene_indexes=[scene.scene_index for scene in current_scenes],
            segment_ids=[segment_id for scene in current_scenes for segment_id in scene.segment_ids],
            start_ms=current_scenes[0].start_ms,
            end_ms=current_scenes[-1].end_ms,
            total_source_chars=sum(
                len(str(row["source_text"] or "").strip())
                for scene in current_scenes
                for row in scene.segments
            ),
            render_unit_count=sum(len(scene.segments) for scene in current_scenes),
        )
        spans.append(span)
        for scene_id in span.scene_ids:
            span_by_scene_id[scene_id] = span
        current_scenes = []

    for scene, decision in zip(scenes, route_decisions):
        if decision.route_mode != NARRATION_FAST_V2_ROUTE:
            flush()
            continue
        if not current_scenes:
            current_scenes = [scene]
            continue
        previous_scene = current_scenes[-1]
        proposed_render_units = sum(len(item.segments) for item in current_scenes) + len(scene.segments)
        proposed_source_chars = sum(
            len(str(row["source_text"] or "").strip())
            for item in current_scenes
            for row in item.segments
        ) + sum(len(str(row["source_text"] or "").strip()) for row in scene.segments)
        proposed_duration_ms = max(0, scene.end_ms - current_scenes[0].start_ms)
        should_break = (
            scene.start_ms - previous_scene.end_ms > NARRATION_SPAN_MAX_GAP_MS
            or proposed_render_units > NARRATION_SPAN_MAX_RENDER_UNITS
            or proposed_source_chars > NARRATION_SPAN_MAX_SOURCE_CHARS
            or proposed_duration_ms > NARRATION_SPAN_MAX_DURATION_MS
            or _contains_direct_speech(scene)
            or decision.prior_review_penalty > 0.34
            or decision.fallback_reason == "borderline_narration_score"
        )
        if should_break:
            flush()
            current_scenes = [scene]
            continue
        current_scenes.append(scene)
    flush()
    return spans, span_by_scene_id
```
-> `src/app/translate/narration_fast_v2.py:239-302`

## 2. PROMPTS — the crown jewels
All seeded prompt templates live as code defaults in `src/app/translate/presets.py` and are written to project `presets/prompts/*.json` on bootstrap (`ensure_prompt_templates`). There is **no** separate repo-level prompt catalog directory (see KNOWN_LIMITATIONS).

### 2.1 Full prompt catalog (verbatim from presets.py)
```python
from __future__ import annotations

import json
from pathlib import Path

from .models import TranslationPromptTemplate


def get_prompt_presets_dir(project_root: Path) -> Path:
    return project_root / "presets" / "prompts"


def default_translation_mode_for_languages(source_language: str, target_language: str) -> str:
    if source_language.lower() == "zh" and target_language.lower() == "vi":
        return "contextual_v2"
    return "legacy"


def _contextual_templates() -> list[TranslationPromptTemplate]:
    return [
        TranslationPromptTemplate(
            template_id="contextual_default_scene_planner",
            family_id="contextual-default-vi",
            translation_mode="contextual_v2",
            role="scene_planner",
            name="Contextual mặc định / Planner",
            category="contextual",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "You plan Chinese-to-Vietnamese dialogue translation at the scene level. "
                "Summarize the scene, identify likely participants, track ambiguities, and propose "
                "character or directional relationship updates only when there is evidence. "
                "Use hypothesized or unknown values instead of inventing certainty."
            ),
            user_prompt_template=(
                "Plan the current scene for contextual dialogue translation from {source_language} to "
                "{target_language}. Use Context, Glossary, and Constraints to keep discourse memory stable. "
                "Ground every update in the provided scene payload and keep ambiguous points inside the "
                "scene output rather than resolving them aggressively. "
                "Context: {context}. Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Contextual V2 planner tuned to keep hypotheses explicit.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_default_semantic",
            family_id="contextual-default-vi",
            translation_mode="contextual_v2",
            role="semantic_pass",
            name="Contextual mặc định / Semantic",
            category="contextual",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Analyze Chinese-to-Vietnamese dialogue semantics. Return exactly one semantic item for "
                "every segment in scene.segments. Preserve each segment_id verbatim. Never merge, omit, "
                "duplicate, or reorder segments. Focus on who is speaking to whom, honorific policy, "
                "ellipsis resolution, and safe in-world meaning. If anything is ambiguous, keep the "
                "semantic_translation conservative and move the uncertainty into review fields. If an "
                "uncertain noun repeats within a scene, keep one stable short neutral Vietnamese noun "
                "phrase, such as 'mon do' or 'thu do' when the referent is unclear. Never emit technical "
                "placeholder tokens or control words in user-facing text."
            ),
            user_prompt_template=(
                "Analyze the semantics of the current batch from {source_language} to {target_language}. "
                "The payload may be only part of a larger scene, but you must still return exactly one "
                "item per segment inside scene.segments. Use Context, Glossary, and Constraints to keep "
                "speaker, listener, and relationship decisions stable. If the same unresolved noun "
                "repeats across nearby lines, keep one stable short neutral Vietnamese noun phrase across "
                "those lines and never emit literal placeholder text. "
                "Context: {context}. Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Contextual V2 semantic pass tuned on real zh->vi dialogue data.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_default_adaptation",
            family_id="contextual-default-vi",
            translation_mode="contextual_v2",
            role="dialogue_adaptation",
            name="Contextual mặc định",
            category="contextual",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Adapt approved semantic dialogue into subtitle_text and tts_text. Return exactly one "
                "item for every segment in scene.segments and preserve each segment_id verbatim. "
                "subtitle_text must stay concise and readable. tts_text may sound more oral, but it must "
                "preserve the same honorific policy, speaker-listener relationship, and narrative intent. "
                "Do not output translator notes or explanations to the audience. If a key noun remains "
                "uncertain, keep one stable short neutral Vietnamese noun phrase across the scene and "
                "never print technical placeholder text."
            ),
            user_prompt_template=(
                "Write subtitle_text and tts_text for the current contextual batch from {source_language} "
                "to {target_language}. Return exactly one item per segment inside scene.segments. Use "
                "Context, Glossary, and Constraints to preserve the approved honorific policy. Keep all "
                "user-facing text as in-world dialogue only. If a term remains ambiguous, choose the "
                "safest natural line and move the uncertainty into review fields instead of explaining it "
                "inside subtitle_text or tts_text. Keep recurring unresolved nouns consistent with a "
                "short neutral Vietnamese phrase and never output placeholder tokens. Context: {context}. Glossary: {glossary}. "
                "Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            default_constraints_json={"max_lines": 2, "max_cpl": 42, "target_cps": 18},
            notes="Contextual V2 adaptation tuned to reduce honorific drift and viewer-facing notes.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_default_critic",
            family_id="contextual-default-vi",
            translation_mode="contextual_v2",
            role="semantic_critic",
            name="Contextual mặc định / Critic",
            category="contextual",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Review contextual dialogue outputs for semantic consistency. Return exactly one critic "
                "item for every segment in scene.segments and preserve each segment_id verbatim. Catch "
                "honorific drift, wrong addressee, relationship drift, unjustified pronoun insertion, "
                "and divergence between subtitle_text and tts_text. Treat literal placeholder tokens or "
                "control words in user-facing text as an issue."
            ),
            user_prompt_template=(
                "Review the current contextual batch from {source_language} to {target_language}. Return "
                "exactly one critic item per segment inside scene.segments. Use Context, Glossary, and "
                "Constraints to check discourse consistency instead of re-translating from scratch. "
                "Context: {context}. Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Contextual V2 critic tuned to keep one result per segment.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_fast_scene_planner",
            family_id="contextual-narration-fast-vi",
            translation_mode="contextual_v2",
            role="scene_planner",
            name="Narration Fast / Planner",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "You plan Chinese-to-Vietnamese narration translation for non-dialogue videos. "
                "Assume a neutral narrator unless the source clearly switches speaker. Avoid "
                "character and relationship updates unless there is explicit evidence."
            ),
            user_prompt_template=(
                "Plan the current narration scene from {source_language} to {target_language}. "
                "Keep the plan lightweight, prefer neutral narration, and record ambiguity instead "
                "of forcing dialogue assumptions. Context: {context}. Glossary: {glossary}. "
                "Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Narration fast path uses a local planner by default; this template stays as a fallback contract.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_fast_semantic",
            family_id="contextual-narration-fast-vi",
            translation_mode="contextual_v2",
            role="semantic_pass",
            name="Narration Fast / Semantic",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Analyze Chinese-to-Vietnamese narration semantics. Return exactly one semantic item for "
                "every segment in scene.segments, in the exact same order as scene.segments. Do not emit "
                "segment_id fields, do not merge, omit, duplicate, or reorder items. Treat the speaker "
                "as a neutral narrator by default, keep honorific_policy empty unless the line explicitly "
                "addresses an audience, and prefer conservative narration over dialogue-like guessing. If "
                "a technical term or referent is unclear, keep the translation neutral and move the "
                "uncertainty into review fields."
            ),
            user_prompt_template=(
                "Analyze the semantics of the current narration batch from {source_language} to "
                "{target_language}. Return exactly one item per segment inside scene.segments and keep "
                "the output order identical to scene.segments. Use the lightweight Context and "
                "Constraints to keep tone neutral and informative. Do not invent character relationships "
                "or honorific policy for plain narration. Context: {context}. Glossary: {glossary}. "
                "Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Narration fast semantic pass biases toward neutral voice-over and review routing for unclear terms.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_fast_term_entity",
            family_id="contextual-narration-fast-vi",
            translation_mode="contextual_v2",
            role="term_entity_pass",
            name="Narration Fast / Terms",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Review a Chinese-to-Vietnamese narration scene and extract only the recurring or "
                "meaning-critical technical terms and named entities that should stay stable across "
                "the scene. Return at most 6 items. Use zero-based segment_positions that point to the "
                "matching entries inside scene.segments. Use status='prefer' when a stable Vietnamese "
                "rendering is safe enough to reuse. Use status='needs_review' only when the term or "
                "entity is important and still too uncertain to recommend confidently. If nothing needs "
                "special handling, return an empty items list."
            ),
            user_prompt_template=(
                "Build a lightweight term/entity sheet for the current narration scene from "
                "{source_language} to {target_language}. Focus on recurring technical terms, scientific "
                "labels, proper names, and other meaning-critical nouns that could cause repeated drift "
                "later. Keep the sheet short and practical. Use Context, Glossary, and Constraints for "
                "existing stable choices, but do not invent certainty. Context: {context}. Glossary: "
                "{glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=1,
            default_constraints_json={
                "max_items": 6,
                "allow_empty": True,
                "zero_based_segment_positions": True,
            },
            notes="Narration term/entity mini-pass builds a reusable term sheet before semantic/adaptation.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_fast_adaptation",
            family_id="contextual-narration-fast-vi",
            translation_mode="contextual_v2",
            role="dialogue_adaptation",
            name="Narration Fast",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Adapt approved narration semantics into subtitle_text and tts_text. Return exactly one "
                "item for every segment in scene.segments, in the exact same order as scene.segments. Do "
                "not emit segment_id fields, do not merge, omit, duplicate, or reorder items. "
                "subtitle_text must stay concise, factual, and easy to read. tts_text should usually stay "
                "very close to subtitle_text; only make small oral adjustments when they do not add new "
                "pronouns, audience address, or semantic detail. Never add dialogue-style flourishes."
            ),
            user_prompt_template=(
                "Write subtitle_text and tts_text for the current narration batch from {source_language} "
                "to {target_language}. Return exactly one item per segment inside scene.segments and keep "
                "the output order identical to scene.segments. Keep the Vietnamese natural, concise, and "
                "easy to narrate. Prefer `tts_text = subtitle_text` unless a tiny oral smoothing change "
                "is clearly safe. Do not add audience-address terms "
                "such as 'quý vị' or 'các bạn' unless they are explicit in the approved semantics. "
                "Context: {context}. Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            default_constraints_json={"max_lines": 2, "max_cpl": 38, "target_cps": 16},
            notes="Narration fast adaptation keeps subtitle/TTS close to reduce review churn and reruns.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_semantic_v2",
            family_id="contextual-narration-fast-v2-vi",
            translation_mode="contextual_v2",
            role="semantic_pass",
            name="Narration Fast V2 / Semantic",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Translate Chinese narration into one stable Vietnamese canonical_text per segment. "
                "Return exactly one item for every render unit in span.render_units, in the same order. "
                "Do not emit segment_id fields, do not merge, omit, duplicate, or reorder items. "
                "canonical_text must stay factual, concise, and neutral. subtitle_text and tts_text will "
                "be derived locally from canonical_text, so do not create dialogue flourishes. Use risk_flags "
                "only for concrete risk classes such as entity_new, number_sensitive, pronoun_ambiguous, "
                "idiom_ambiguous, unsafe_to_guess, or needs_shortening."
            ),
            user_prompt_template=(
                "Produce one Vietnamese canonical_text per narration render unit from {source_language} to "
                "{target_language}. Return exactly one item per render unit in span.render_units and keep "
                "the order identical. Keep output compact and semantic-first. Use approved glossary entries "
                "when present. If a fact, entity, or referent is not safe to guess, set flags instead of "
                "inventing certainty. Context: {context}. Glossary: {glossary}. Constraints: {constraints}. "
                "Data: {source}"
            ),
            output_schema_version=1,
            default_constraints_json={
                "canonical_only": True,
                "max_lines": 2,
                "max_cpl": 38,
                "target_cps": 16,
            },
            notes="Narration fast v2 base semantic pass returns canonical_text only.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_entity_micro",
            family_id="contextual-narration-fast-v2-vi",
            translation_mode="contextual_v2",
            role="entity_micro_pass",
            name="Narration Fast V2 / Entity",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Resolve only the entity or technical-term spans provided. Return short approved_target "
                "choices when safe, otherwise keep status conservative. Never rewrite the whole narration."
            ),
            user_prompt_template=(
                "Resolve entity or technical-term spans from {source_language} to {target_language}. "
                "Only work on the listed candidate terms and their short local context. Prefer approved "
                "memory if it fits. If a term is still not safe to finalize, keep it conservative and mark "
                "the status accordingly. Context: {context}. Glossary: {glossary}. Constraints: {constraints}. "
                "Data: {source}"
            ),
            output_schema_version=1,
            default_constraints_json={"micro_pass": "entity", "max_items": 6},
            notes="Sparse entity resolution for narration fast v2.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_ambiguity_micro",
            family_id="contextual-narration-fast-v2-vi",
            translation_mode="contextual_v2",
            role="ambiguity_micro_pass",
            name="Narration Fast V2 / Ambiguity",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Resolve only the listed ambiguous narration spans. Return one item per input span and keep "
                "the output conservative. If the ambiguity is still unsafe, keep unsafe_to_guess=true."
            ),
            user_prompt_template=(
                "Resolve the listed ambiguous narration spans from {source_language} to {target_language}. "
                "Only decide the minimum needed wording for the listed spans. Do not rewrite unrelated text. "
                "If context is still insufficient, keep unsafe_to_guess true. Context: {context}. Glossary: "
                "{glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=1,
            default_constraints_json={"micro_pass": "ambiguity"},
            notes="Sparse ambiguity resolution for narration fast v2.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_narration_slot_rewrite",
            family_id="contextual-narration-fast-v2-vi",
            translation_mode="contextual_v2",
            role="dialogue_adaptation",
            name="Narration Fast V2",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Rewrite narration canonical_text only when slot pressure requires shortening. Return exactly "
                "one item per input item, in the same order. Keep facts, entities, and numbers unchanged. "
                "Do not add audience address or dialogue flourishes."
            ),
            user_prompt_template=(
                "Rewrite only the listed canonical_text items from {source_language} to {target_language} "
                "to fit subtitle/TTS slot limits without changing facts. Protected entities and numbers must "
                "stay unchanged. Return one item per input item in the same order. Context: {context}. "
                "Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=1,
            default_constraints_json={"micro_pass": "slot_rewrite", "max_lines": 2, "max_cpl": 38, "target_cps": 16},
            notes="Narration fast v2 slot rewrite micro-pass; also acts as the UI-selectable family anchor.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_cartoon_fun_scene_planner",
            family_id="contextual-cartoon-fun-vi",
            translation_mode="contextual_v2",
            role="scene_planner",
            name="Hoạt hình hài / Planner",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "You plan translation for humorous animation dialogue from Chinese to Vietnamese. "
                "Identify the comedic setup, likely participants, relationship hints, and any ambiguity "
                "that may affect pronouns, honorifics, or punchlines. Prefer explicit uncertainty over "
                "confident guessing."
            ),
            user_prompt_template=(
                "Plan the current humorous-animation scene from {source_language} to {target_language}. "
                "Use Context, Glossary, and Constraints to preserve character relationships and comic "
                "timing. If a key joke term stays ambiguous, record it in the scene output instead of "
                "forcing a single interpretation. Context: {context}. Glossary: {glossary}. "
                "Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Tuned on real Shinchan data to keep ambiguities visible for review.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_cartoon_fun_semantic",
            family_id="contextual-cartoon-fun-vi",
            translation_mode="contextual_v2",
            role="semantic_pass",
            name="Hoạt hình hài / Semantic",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Analyze humorous animation dialogue from Chinese to Vietnamese. Return exactly one "
                "semantic item for every segment in scene.segments. Preserve each segment_id verbatim. "
                "Never merge, omit, duplicate, or reorder segments. Keep the joke intent, but if "
                "speaker, listener, honorifics, or a key term are ambiguous, use unknown values and "
                "needs_human_review=true instead of guessing. semantic_translation must stay as in-world "
                "dialogue, not translator notes or explanations for the audience. If an uncertain noun or "
                "joke term repeats within a scene, keep one stable short neutral Vietnamese noun phrase, "
                "such as 'mon do' or 'thu do' when needed, and never emit technical placeholder text."
            ),
            user_prompt_template=(
                "Analyze the semantics of the current humorous-animation batch from {source_language} to "
                "{target_language}. The payload may be only part of a larger scene, but you must still "
                "return exactly one item per segment inside scene.segments. Use Context, Glossary, and "
                "Constraints to keep relationships stable. If any term is ambiguous, keep the "
                "semantic_translation as the safest in-world utterance and move the uncertainty into "
                "review fields instead of explaining it in the dialogue text. If the same unresolved term "
                "repeats, keep one stable short neutral Vietnamese noun phrase and never print placeholder "
                "tokens. Context: {context}. "
                "Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Tuned on real Shinchan sample to reduce missing segment ids and overconfident guesses.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_cartoon_fun_adaptation",
            family_id="contextual-cartoon-fun-vi",
            translation_mode="contextual_v2",
            role="dialogue_adaptation",
            name="Hoạt hình hài hước",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Adapt humorous animation dialogue into subtitle_text and tts_text. Return exactly one "
                "item for every segment in scene.segments and preserve every segment_id verbatim. Do not "
                "merge, omit, duplicate, or reorder segments. subtitle_text should be punchy and "
                "readable. tts_text can sound more playful and oral, but it must keep the same "
                "speaker-listener relationship and honorific policy. Never output translator notes, "
                "explanations, or ambiguity glosses inside subtitle_text or tts_text. If a term is "
                "ambiguous, choose the safest in-world line and send the uncertainty to review instead. "
                "Keep repeated unresolved nouns consistent with a short neutral Vietnamese phrase and "
                "never emit technical placeholder text."
            ),
            user_prompt_template=(
                "Write subtitle_text and tts_text for the current humorous-animation batch from "
                "{source_language} to {target_language}. Return exactly one item per segment inside "
                "scene.segments. Use Context, Glossary, and Constraints to preserve the approved "
                "honorific policy while keeping the dialogue lively. Keep all user-facing text as "
                "in-world dialogue only; do not explain ambiguity to the audience. If something stays "
                "uncertain, keep the line concise and move the doubt into review fields. Keep repeated "
                "unresolved nouns consistent with a short neutral Vietnamese phrase and never output "
                "placeholder tokens. Context: "
                "{context}. Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            default_constraints_json={"max_lines": 2, "max_cpl": 40, "target_cps": 18},
            notes="Tuned on real Shinchan sample to keep one output per segment and avoid meta dialogue.",
        ),
        TranslationPromptTemplate(
            template_id="contextual_cartoon_fun_critic",
            family_id="contextual-cartoon-fun-vi",
            translation_mode="contextual_v2",
            role="semantic_critic",
            name="Hoạt hình hài / Critic",
            category="style",
            source_lang="zh",
            target_lang="vi",
            system_prompt=(
                "Review humorous animation dialogue for semantic consistency. Return exactly one critic "
                "item for every segment in scene.segments. Preserve every segment_id verbatim. Catch "
                "honorific drift, wrong addressee, relationship drift, and cases where the rewrite "
                "changed the social tone or comedic intent. Treat literal placeholder tokens or control "
                "words in user-facing dialogue as issues."
            ),
            user_prompt_template=(
                "Review the current humorous-animation batch from {source_language} to {target_language}. "
                "Return exactly one critic item per segment inside scene.segments. Use Context, Glossary, "
                "and Constraints to verify discourse consistency without inventing missing facts. "
                "Context: {context}. Glossary: {glossary}. Constraints: {constraints}. Data: {source}"
            ),
            output_schema_version=2,
            notes="Tuned on real Shinchan sample to avoid partial critic outputs.",
        ),
    ]


def _default_prompt_templates(source_language: str, target_language: str) -> list[TranslationPromptTemplate]:
    templates = [
        TranslationPromptTemplate(
            template_id="default-vi-style",
            family_id="legacy-default-vi",
            translation_mode="legacy",
            role="legacy_translate",
            name="Dịch tự nhiên",
            category="mặc định",
            source_lang=source_language or "auto",
            target_lang=target_language or "vi",
            system_prompt="You are a subtitle editor. Keep the meaning accurate, concise, and easy to read.",
            user_prompt_template="Translate the following content to {target_language}: {source}",
            output_schema_version=1,
            default_constraints_json={"max_lines": 2, "max_cpl": 42, "target_cps": 18},
        )
    ]
    if default_translation_mode_for_languages(source_language, target_language) != "contextual_v2":
        return templates
    templates.extend(_contextual_templates())
    return templates


def ensure_prompt_templates(project_root: Path, source_language: str, target_language: str) -> list[Path]:
    presets_dir = get_prompt_presets_dir(project_root)
    presets_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = {path.stem for path in presets_dir.glob("*.json")}
    written_paths: list[Path] = []
    for template in _default_prompt_templates(source_language, target_language):
        path = presets_dir / f"{template.template_id}.json"
        if template.template_id in existing_ids and path.exists():
            continue
        path.write_text(
            json.dumps(template.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        written_paths.append(path)
    return written_paths


def list_prompt_templates(
    project_root: Path,
    *,
    translation_mode: str | None = None,
    role: str | None = None,
) -> list[TranslationPromptTemplate]:
    presets_dir = get_prompt_presets_dir(project_root)
    if not presets_dir.exists():
        return []

    templates: list[TranslationPromptTemplate] = []
    for path in sorted(presets_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            template = TranslationPromptTemplate.model_validate(payload)
            if translation_mode and template.translation_mode != translation_mode:
                continue
            if role and template.role != role:
                continue
            templates.append(template)
        except Exception:
            continue
    return templates


def load_prompt_template(project_root: Path, template_id: str) -> TranslationPromptTemplate:
    for template in list_prompt_templates(project_root):
        if template.template_id == template_id:
            return template
    raise FileNotFoundError(f"Khong tim thay prompt template: {template_id}")


def resolve_prompt_family(
    project_root: Path,
    selected_template: TranslationPromptTemplate,
) -> dict[str, TranslationPromptTemplate]:
    family_id = selected_template.family_id or selected_template.template_id
    templates = list_prompt_templates(
        project_root,
        translation_mode=selected_template.translation_mode,
    )
    family = {
        template.role: template
        for template in templates
        if (template.family_id or template.template_id) == family_id
    }
    if selected_template.role not in family:
        family[selected_template.role] = selected_template
    return family


def is_narration_fast_template(selected_template: TranslationPromptTemplate) -> bool:
    family_id = selected_template.family_id or selected_template.template_id
    return family_id in {"contextual-narration-fast-vi", "contextual-narration-fast-v2-vi"}


def is_narration_fast_v2_template(selected_template: TranslationPromptTemplate) -> bool:
    family_id = selected_template.family_id or selected_template.template_id
    return family_id == "contextual-narration-fast-v2-vi"


def save_prompt_template(project_root: Path, template: TranslationPromptTemplate) -> Path:
    presets_dir = get_prompt_presets_dir(project_root)
    presets_dir.mkdir(parents=True, exist_ok=True)
    path = presets_dir / f"{template.template_id}.json"
    path.write_text(
        json.dumps(template.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path

```
-> `src/app/translate/presets.py:1-587`

### 2.2 Structured Outputs Pydantic models (verbatim)
```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


STRICT_MODEL_CONFIG = ConfigDict(populate_by_name=True, extra="forbid")


class TranslationPromptTemplate(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    template_id: str
    name: str
    family_id: str | None = None
    translation_mode: str = "legacy"
    role: str = "legacy_translate"
    category: str = "default"
    source_lang: str = "auto"
    target_lang: str = "vi"
    system_prompt: str
    user_prompt_template: str
    output_schema_version: int = 1
    default_constraints_json: dict[str, object] = Field(default_factory=dict)
    notes: str = ""

    def render(
        self,
        *,
        source: str,
        source_language: str,
        target_language: str,
        glossary: str = "",
        constraints: str = "",
        context: str = "",
    ) -> str:
        return self.user_prompt_template.format(
            source=source,
            source_language=source_language,
            target_language=target_language,
            glossary=glossary,
            constraints=constraints,
            context=context,
        )


class TranslationOutputItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    segment_id: str
    translated_text: str
    subtitle_text: str
    tts_text: str


class BatchTranslationOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[TranslationOutputItem]


class CharacterSeed(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    character_id: str
    canonical_name_zh: str = ""
    canonical_name_vi: str = ""
    aliases: list[str] = Field(default_factory=list)
    gender_hint: str | None = None
    age_role: str | None = None
    social_role: str | None = None
    speech_style: str | None = None
    default_self_terms: list[str] = Field(default_factory=list)
    default_address_terms: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "hypothesized"
    evidence_segment_ids: list[str] = Field(default_factory=list)


class RelationshipSeed(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    relationship_id: str
    from_character_id: str
    to_character_id: str
    relation_type: str = "unknown"
    power_delta: str | None = None
    age_delta: str | None = None
    intimacy_level: str | None = None
    default_self_term: str | None = None
    default_address_term: str | None = None
    allowed_alternates: list[str] | dict[str, list[str]] = Field(default_factory=list)
    scope: str = "scene"
    confidence: float = 0.0
    status: str = "hypothesized"
    evidence_segment_ids: list[str] = Field(default_factory=list)


class KnowledgeState(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    character_id: str = "unknown"
    summary: str = ""


class PatchSuggestion(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    field_name: str
    value: str


class ScenePlannerOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    scene_id: str
    scene_summary: str
    participants: list[str] = Field(default_factory=list)
    location: str | None = None
    time_context: str | None = None
    active_topic: str | None = None
    current_conflict: str | None = None
    current_emotional_tone: str | None = None
    temporary_addressing_mode: str | None = None
    recent_turn_digest: str = ""
    who_knows_what: list[KnowledgeState] = Field(default_factory=list)
    open_ambiguities: list[str] = Field(default_factory=list)
    unresolved_references: list[str] = Field(default_factory=list)
    character_updates: list[CharacterSeed] = Field(default_factory=list)
    relationship_updates: list[RelationshipSeed] = Field(default_factory=list)


class SpeakerDecision(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    character_id: str = "unknown"
    speaker_cluster_id: str | None = None
    source: str = "inferred"
    confidence: float = 0.0


class ListenerDecision(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    character_id: str = "unknown"
    role: str = "primary"
    confidence: float = 0.0


class RegisterDecision(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    politeness: str = "informal"
    power_direction: str = "peer"
    emotional_tone: str = "neutral"
    confidence: float = 0.0


class ResolvedEllipsis(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    omitted_subject: str | None = None
    omitted_object: str | None = None
    confidence: float = 0.0


class HonorificPolicy(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    policy_id: str = ""
    self_term: str = ""
    address_term: str = ""
    locked: bool = False
    confidence: float = 0.0


class ConfidenceBreakdown(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    overall: float = 0.0
    speaker: float = 0.0
    listener: float = 0.0
    register_score: float = Field(default=0.0, alias="register")
    relation: float = 0.0
    translation: float = 0.0


class SegmentSemanticAnalysisItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    segment_id: str
    scene_id: str
    speaker: SpeakerDecision
    listeners: list[ListenerDecision] = Field(default_factory=list)
    turn_function: str = "statement"
    register_data: RegisterDecision = Field(alias="register")
    resolved_ellipsis: ResolvedEllipsis = Field(default_factory=ResolvedEllipsis)
    honorific_policy: HonorificPolicy = Field(default_factory=HonorificPolicy)
    semantic_translation: str
    glossary_hits: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    needs_human_review: bool = False
    review_reason_codes: list[str] = Field(default_factory=list)
    review_question: str = ""


class SemanticBatchOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[SegmentSemanticAnalysisItem]


class NarrationSemanticAnalysisItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    speaker: SpeakerDecision
    listeners: list[ListenerDecision] = Field(default_factory=list)
    turn_function: str = "statement"
    register_data: RegisterDecision = Field(alias="register")
    resolved_ellipsis: ResolvedEllipsis = Field(default_factory=ResolvedEllipsis)
    honorific_policy: HonorificPolicy = Field(default_factory=HonorificPolicy)
    semantic_translation: str
    glossary_hits: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    needs_human_review: bool = False
    review_reason_codes: list[str] = Field(default_factory=list)
    review_question: str = ""


class NarrationSemanticBatchOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationSemanticAnalysisItem]


class NarrationCanonicalEntityItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    src: str
    dst: str = ""
    status: str = "candidate"
    confidence: float = 0.0
    segment_positions: list[int] = Field(default_factory=list)
    notes: str = ""


class NarrationCanonicalItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    canonical_text: str
    risk_flags: list[str] = Field(default_factory=list)
    entities: list[NarrationCanonicalEntityItem] = Field(default_factory=list)
    needs_shortening: bool = False
    unsafe_to_guess: bool = False


class NarrationCanonicalSpanOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationCanonicalItem]


class NarrationEntityMicroItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    source_term: str
    approved_target: str = ""
    status: str = "candidate"
    confidence: float = 0.0
    segment_positions: list[int] = Field(default_factory=list)
    notes: str = ""


class NarrationEntityMicroOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationEntityMicroItem] = Field(default_factory=list)


class NarrationAmbiguityMicroItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    canonical_text: str
    unsafe_to_guess: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    review_reason_codes: list[str] = Field(default_factory=list)


class NarrationAmbiguityMicroOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationAmbiguityMicroItem]


class NarrationSlotRewriteItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    canonical_text: str
    changed: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    review_reason_codes: list[str] = Field(default_factory=list)


class NarrationSlotRewriteOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationSlotRewriteItem]


class DialogueAdaptationItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    segment_id: str
    honorific_policy: HonorificPolicy = Field(default_factory=HonorificPolicy)
    subtitle_text: str
    tts_text: str
    risk_flags: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    review_reason_codes: list[str] = Field(default_factory=list)


class DialogueAdaptationBatchOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[DialogueAdaptationItem]


class NarrationAdaptationItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    honorific_policy: HonorificPolicy = Field(default_factory=HonorificPolicy)
    subtitle_text: str
    tts_text: str
    risk_flags: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    review_reason_codes: list[str] = Field(default_factory=list)


class NarrationAdaptationBatchOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationAdaptationItem]


class NarrationTermEntityItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    source_term: str
    preferred_vi: str = ""
    category: str = "term"
    status: str = "prefer"
    confidence: float = 0.0
    segment_positions: list[int] = Field(default_factory=list)
    notes: str = ""


class NarrationTermEntityBatchOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[NarrationTermEntityItem] = Field(default_factory=list)


class ResolvedNarrationTermEntityItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    source_term: str
    preferred_vi: str = ""
    category: str = "term"
    status: str = "prefer"
    confidence: float = 0.0
    segment_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class SceneTermEntitySheet(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    scene_id: str
    route_mode: str = "narration_fast"
    active: bool = True
    items: list[ResolvedNarrationTermEntityItem] = Field(default_factory=list)


class ApprovedTermMemoryEntry(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    source_surface: str
    normalized_form: str = ""
    approved_target: str = ""
    context_fingerprint: str = ""
    approved_by_human: bool = False
    last_seen: str = ""
    confidence: float = 0.0


class NarrationBudgetPolicy(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    max_llm_cost_usd: float = 0.30
    reserve_ratio: float = 0.15
    soft_stop_ratio: float = 0.85
    entity_micro_cap: int = 12
    ambiguity_micro_cap: int = 10
    slot_rewrite_cap: int = 8
    full_rescue_cap: int = 2


class NarrationSpan(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    span_id: str
    span_index: int
    scene_ids: list[str] = Field(default_factory=list)
    scene_indexes: list[int] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    start_ms: int = 0
    end_ms: int = 0
    total_source_chars: int = 0
    render_unit_count: int = 0


class SemanticCriticIssue(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    code: str
    severity: str
    message: str


class SemanticCriticItem(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    segment_id: str
    passed: bool = True
    review_needed: bool = False
    error_codes: list[str] = Field(default_factory=list)
    issues: list[SemanticCriticIssue] = Field(default_factory=list)
    minimal_patch: list[PatchSuggestion] = Field(default_factory=list)


class SemanticCriticBatchOutput(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    items: list[SemanticCriticItem]


class SceneRouteDecision(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    scene_id: str
    scene_index: int
    route_mode: str
    prompt_family_id: str
    narration_score: float
    speaker_dominance: float = 0.0
    speaker_switch_density: float = 0.0
    question_density: float = 0.0
    vocative_density: float = 0.0
    backchannel_density: float = 0.0
    short_utterance_ratio: float = 0.0
    long_sentence_ratio: float = 0.0
    prior_review_penalty: float = 0.0
    fallback_reason: str = ""


class LLMCallMetric(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    role: str
    route_mode: str
    scene_id: str = ""
    batch_index: int | None = None
    batch_count: int | None = None
    prompt_cache_key: str = ""
    input_token_count: int | None = None
    output_token_count: int | None = None


class ContextualRunMetrics(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    llm_call_count: int = 0
    llm_retry_count: int = 0
    batch_count: int = 0
    span_count: int = 0
    narration_batch_size_caps: dict[str, int] = Field(default_factory=dict)
    term_entity_pass_scene_count: int = 0
    term_entity_entry_count: int = 0
    term_entity_review_hint_count: int = 0
    base_semantic_call_count: int = 0
    entity_micro_pass_count: int = 0
    ambiguity_micro_pass_count: int = 0
    slot_rewrite_count: int = 0
    full_rescue_count: int = 0
    estimated_cost_usd: float = 0.0
    budget_soft_stop_hit: bool = False
    approved_term_memory_hits: int = 0
    router_version: str = "v1"
    semantic_schema_version: int | None = None
    postprocess_version: str = "v1"
    call_metrics: list[LLMCallMetric] = Field(default_factory=list)

```
-> `src/app/translate/models.py:1-503`

### 2.3 Prompt assembly ORDER (prompt-cache reuse)
Structured call builds user prompt as: template.render with placeholders → then appends fixed sections in this order: Constraints, Context, Glossary, Source.
```python
    def _build_structured_user_prompt(
        self,
        *,
        template: TranslationPromptTemplate,
        source_payload: str,
        source_language: str,
        target_language: str,
        glossary_payload: str,
        constraints_payload: str,
        context_payload: str,
    ) -> str:
        prefix = template.render(
            source="<<SOURCE_PAYLOAD>>",
            source_language=source_language,
            target_language=target_language,
            glossary="<<GLOSSARY_PAYLOAD>>",
            constraints="<<CONSTRAINTS_PAYLOAD>>",
            context="<<CONTEXT_PAYLOAD>>",
        )
        return "\n\n".join(
            [
                prefix,
                "## Constraints",
                constraints_payload,
                "## Context",
                context_payload,
                "## Glossary",
                glossary_payload,
                "## Source",
                source_payload,
            ]
        )
```
-> `src/app/translate/openai_engine.py:80-111`
### 2.4 `prompt_cache_key` builder (verbatim)
```python
    @staticmethod
    def build_prompt_cache_key(
        *,
        template: TranslationPromptTemplate,
        model: str,
        source_language: str,
        target_language: str,
        route_mode: str,
        project_profile_id: str | None,
    ) -> str:
        family_id = template.family_id or template.template_id
        raw_value = "|".join(
            [
                family_id,
                template.role,
                model,
                source_language,
                target_language,
                str(template.output_schema_version),
                route_mode,
                project_profile_id or "none",
            ]
        )
        return hashlib.sha1(raw_value.encode("utf-8")).hexdigest()
```
-> `src/app/translate/openai_engine.py:55-78`
### 2.5 Request-building code (temperature / model)
**No** `top_p`, `max_output_tokens`, `reasoning` effort, or `service_tier` in this codebase. Only:
```python
    def _call_structured_output(
        self,
        *,
        client,
        model: str,
        template: TranslationPromptTemplate,
        user_prompt: str,
        output_model,
        prompt_cache_key: str | None = None,
        record_call: Callable[[LLMCallMetric], None] | None = None,
        route_mode: str = "dialogue",
        scene_id: str = "",
        batch_index: int | None = None,
        batch_count: int | None = None,
    ):
        response = client.responses.parse(
            model=model,
            instructions=template.system_prompt,
            input=user_prompt,
            text_format=output_model,
            temperature=0.2,
            prompt_cache_key=prompt_cache_key,
        )
        if record_call is not None:
            usage = getattr(response, "usage", None)
            record_call(
                LLMCallMetric(
                    role=template.role,
                    route_mode=route_mode,
                    scene_id=scene_id,
                    batch_index=batch_index,
                    batch_count=batch_count,
                    prompt_cache_key=prompt_cache_key or "",
                    input_token_count=self._usage_value(usage, "input_tokens", "prompt_tokens", "total_input_tokens"),
                    output_token_count=self._usage_value(usage, "output_tokens", "completion_tokens", "total_output_tokens"),
                )
            )
        parsed = response.output_parsed
        if not parsed:
            raise RuntimeError("Model khong tra ve du lieu co parse duoc")
        return parsed
```
-> `src/app/translate/openai_engine.py:130-170`
Default model:
```python
class AppSettings(BaseModel):
    ui_language: str = "vi"
    ui_mode: str = "simple_v2"
    dependency_paths: DependencyPaths = Field(default_factory=DependencyPaths)
    model_cache_dir: str | None = None
    openai_api_key_encrypted: str | None = None
    default_asr_model: str = "small"
    default_translation_model: str = "gpt-4.1-mini"
    gpu_enabled: bool = False
    telemetry_opt_out: bool = True
```
-> `src/app/core/settings.py:120-129`
Pricing map used for budget estimation (not request params):
```python
_MODEL_PRICE_PER_1M_TOKENS_USD: dict[str, tuple[float, float]] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5.4-mini": (0.40, 1.60),
    "gpt-5.4": (2.00, 8.00),
}

```
-> `src/app/translate/openai_engine.py:28-34`
```python
    @staticmethod
    def estimate_metric_cost_usd(metric: LLMCallMetric, *, model: str) -> float:
        input_price, output_price = _MODEL_PRICE_PER_1M_TOKENS_USD.get(
            model,
            _MODEL_PRICE_PER_1M_TOKENS_USD["gpt-4.1-mini"],
        )
        input_tokens = max(0, int(metric.input_token_count or 0))
        output_tokens = max(0, int(metric.output_token_count or 0))
        return round(((input_tokens * input_price) + (output_tokens * output_price)) / 1_000_000.0, 6)

    @classmethod
    def estimate_total_cost_usd(cls, metrics: list[LLMCallMetric], *, model: str) -> float:
        return round(sum(cls.estimate_metric_cost_usd(metric, model=model) for metric in metrics), 6)
```
-> `src/app/translate/openai_engine.py:172-184`
### 2.6 Interpolated variables per template
All contextual templates use `TranslationPromptTemplate.render` vars: `{source}`, `{source_language}`, `{target_language}`, `{glossary}`, `{constraints}`, `{context}`.
- `source` / structured `Data:` → JSON scene or span payload built by runtime (`_scene_row_payload`, `_span_payload`).
- `context` → character/relationship/scene memory + recent turns (`_build_context_payload` / `_span_context_payload`).
- `glossary` → term sheet + term memory (`_build_glossary_payload`, `_term_glossary_payload`).
- `constraints` → `template.default_constraints_json` dumped JSON (e.g. max_lines/max_cpl/target_cps).
Legacy template only: `user_prompt_template="Translate the following content to {target_language}: {source}"`.

## 3. Scene chunking & context windows
```python
DEFAULT_SCENE_GAP_MS = 1500
DEFAULT_SCENE_MAX_SEGMENTS = 24
DEFAULT_SCENE_MAX_DURATION_MS = 75_000


@dataclass(slots=True, frozen=True)
class SceneChunk:
    scene_id: str
    scene_index: int
    start_segment_index: int
    end_segment_index: int
    start_ms: int
    end_ms: int
    segment_ids: list[str]
    segments: list[Row]

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def chunk_segments_into_scenes(
    segments: list[Row],
    *,
    gap_ms: int = DEFAULT_SCENE_GAP_MS,
    max_segments: int = DEFAULT_SCENE_MAX_SEGMENTS,
    max_duration_ms: int = DEFAULT_SCENE_MAX_DURATION_MS,
) -> list[SceneChunk]:
    if not segments:
        return []

    scenes: list[SceneChunk] = []
    current: list[Row] = []
    scene_index = 0

    def flush() -> None:
        nonlocal current
        if not current:
            return
        start_segment_index = int(current[0]["segment_index"])
        end_segment_index = int(current[-1]["segment_index"])
        start_ms = int(current[0]["start_ms"])
        end_ms = int(current[-1]["end_ms"])
        scene_id = f"scene_{scene_index:04d}"
        scenes.append(
            SceneChunk(
                scene_id=scene_id,
                scene_index=scene_index,
                start_segment_index=start_segment_index,
                end_segment_index=end_segment_index,
                start_ms=start_ms,
                end_ms=end_ms,
                segment_ids=[str(row["segment_id"]) for row in current],
                segments=list(current),
            )
        )
        current = []

    previous_row: Row | None = None
    for row in segments:
        if previous_row is None:
            current.append(row)
            previous_row = row
            continue

        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        previous_end_ms = int(previous_row["end_ms"])
        current_start_ms = int(current[0]["start_ms"])
        should_split = False
        if start_ms - previous_end_ms >= gap_ms:
            should_split = True
        elif len(current) >= max_segments:
            should_split = True
        elif end_ms - current_start_ms >= max_duration_ms:
            should_split = True

        if should_split:
            flush()
            scene_index += 1
        current.append(row)
        previous_row = row

    flush()
    return scenes
```
-> `src/app/translate/scene_chunker.py:7-91`
**Constants:** gap_ms=1500 (1.5s), max_segments=24, max_duration_ms=75000. No overlap between scenes.

### Batch sizes
- Dialogue stages: `CONTEXTUAL_STAGE_BATCH_SIZE = 8`
- Narration fast: `NARRATION_FAST_BATCH_SIZE = 16`
- Narration v2 spans: max render units 48, chars 3200, duration 90s, gap 1500ms

### Split-on-failure (mismatched ids AND retryable parse)
```python
def _is_retryable_stage_exception(exc: Exception) -> bool:
    if isinstance(exc, ValidationError):
        return True
    if isinstance(exc, RuntimeError):
        message = " ".join(str(part) for part in exc.args).lower()
        return any(marker in message for marker in ("model khong tra ve du lieu co parse duoc", "invalid json", "json_invalid", "unexpected end", "eof while parsing"))
    return False


def _summarize_retryable_stage_exception(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error_types = sorted({str(error.get("type") or "validation_error") for error in exc.errors()})
        return f"structured output validation failed ({', '.join(error_types)})"
    return str(exc).strip().splitlines()[0] or exc.__class__.__name__


def _retry_stage_batch_with_split(
    *,
    context: JobContext,
    stage_label: str,
    scene_id: str,
    batch_rows: list[Row],
    batch_index: int,
    batch_count: int,
    stage_runner: Callable[[list[Row], int, int], Any],
    reason: str,
    on_retry: Callable[[], None] | None = None,
) -> dict[str, Any]:
    midpoint = max(1, len(batch_rows) // 2)
    left_rows = batch_rows[:midpoint]
    right_rows = batch_rows[midpoint:]
    context.logger.warning(
        "%s failed for scene=%s batch=%s/%s (%s). Retrying with smaller batches (%s + %s).",
        stage_label,
        scene_id,
        batch_index,
        batch_count,
        reason,
        len(left_rows),
        len(right_rows),
    )
    if on_retry is not None:
        on_retry()
    merged_items = _run_stage_batch_with_retry(
        context=context,
        stage_label=stage_label,
        scene_id=scene_id,
        batch_rows=left_rows,
        batch_index=batch_index,
        batch_count=batch_count,
        stage_runner=stage_runner,
        on_retry=on_retry,
    )
    if right_rows:
        merged_items.update(
            _run_stage_batch_with_retry(
                context=context,
                stage_label=stage_label,
                scene_id=scene_id,
                batch_rows=right_rows,
                batch_index=batch_index,
                batch_count=batch_count,
                stage_runner=stage_runner,
                on_retry=on_retry,
            )
        )
    return merged_items


def _run_stage_batch_with_retry(
    *,
    context: JobContext,
    stage_label: str,
    scene_id: str,
    batch_rows: list[Row],
    batch_index: int,
    batch_count: int,
    stage_runner: Callable[[list[Row], int, int], Any],
    on_retry: Callable[[], None] | None = None,
) -> dict[str, Any]:
    context.cancellation_token.raise_if_canceled()
    try:
        output = stage_runner(batch_rows, batch_index, batch_count)
    except Exception as exc:
        if len(batch_rows) <= 1 or not _is_retryable_stage_exception(exc):
            raise
        return _retry_stage_batch_with_split(
            context=context,
            stage_label=stage_label,
            scene_id=scene_id,
            batch_rows=batch_rows,
            batch_index=batch_index,
            batch_count=batch_count,
            stage_runner=stage_runner,
            reason=_summarize_retryable_stage_exception(exc),
            on_retry=on_retry,
```
-> `src/app/translate/contextual_runtime.py:355-450`
Positional under-return also splits and can downshift narration batch caps for remaining batches (see tests + runtime positional retry helpers around `_run_stage_batch_with_positional_retry`).

### Checkpointing
```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.project.models import CharacterProfileRecord, RelationshipProfileRecord, SceneMemoryRecord, SegmentAnalysisRecord

from .models import ContextualRunMetrics, SceneRouteDecision, SceneTermEntitySheet, TranslationPromptTemplate


@dataclass(slots=True)
class ContextualTranslationCheckpointState:
    scenes: list[SceneMemoryRecord]
    character_profiles: list[CharacterProfileRecord]
    relationship_profiles: list[RelationshipProfileRecord]
    analyses: list[SegmentAnalysisRecord]
    route_decisions: list[SceneRouteDecision]
    term_entity_sheets: list[SceneTermEntitySheet]
    metrics: ContextualRunMetrics
    completed_scene_ids: list[str]
    completed_scene_count: int
    total_scene_count: int


def _cache_dir(workspace, stage_hash: str) -> Path:
    return workspace.cache_dir / "translate_contextual" / stage_hash


def checkpoint_path(workspace, stage_hash: str) -> Path:
    return _cache_dir(workspace, stage_hash) / "contextual_translation.partial.json"


def _restore_record_list(payload_items: list[dict[str, object]], record_type):
    return [record_type(**item) for item in payload_items]


def _build_checkpoint_payload(
    *,
    stage_hash: str,
    selected_template: TranslationPromptTemplate,
    scenes: list[SceneMemoryRecord],
    character_profiles: list[CharacterProfileRecord],
    relationship_profiles: list[RelationshipProfileRecord],
    analyses: list[SegmentAnalysisRecord],
    route_decisions: list[SceneRouteDecision],
    term_entity_sheets: list[SceneTermEntitySheet],
    metrics: ContextualRunMetrics,
    completed_scene_ids: list[str],
    total_scene_count: int,
) -> dict[str, object]:
    return {
        "stage_hash": stage_hash,
        "selected_template_id": selected_template.template_id,
        "selected_template_family_id": selected_template.family_id,
        "translation_mode": selected_template.translation_mode,
        "scenes": [asdict(item) for item in scenes],
        "character_profiles": [asdict(item) for item in character_profiles],
        "relationship_profiles": [asdict(item) for item in relationship_profiles],
        "segment_analyses": [asdict(item) for item in analyses],
        "route_decisions": [item.model_dump(mode="json") for item in route_decisions],
        "term_entity_sheets": [item.model_dump(mode="json") for item in term_entity_sheets],
        "metrics": metrics.model_dump(mode="json"),
        "checkpoint": {
            "completed_scene_ids": list(completed_scene_ids),
            "completed_scene_count": len(completed_scene_ids),
            "total_scene_count": total_scene_count,
        },
    }


def persist_contextual_translation_checkpoint(
    workspace,
    *,
    stage_hash: str,
    selected_template: TranslationPromptTemplate,
    scenes: list[SceneMemoryRecord],
    character_profiles: list[CharacterProfileRecord],
    relationship_profiles: list[RelationshipProfileRecord],
    analyses: list[SegmentAnalysisRecord],
    route_decisions: list[SceneRouteDecision],
    term_entity_sheets: list[SceneTermEntitySheet],
    metrics: ContextualRunMetrics,
    completed_scene_ids: list[str],
    total_scene_count: int,
) -> Path:
    cache_dir = _cache_dir(workspace, stage_hash)
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = _build_checkpoint_payload(
        stage_hash=stage_hash,
        selected_template=selected_template,
        scenes=scenes,
        character_profiles=character_profiles,
        relationship_profiles=relationship_profiles,
        analyses=analyses,
        route_decisions=route_decisions,
        term_entity_sheets=term_entity_sheets,
        metrics=metrics,
        completed_scene_ids=completed_scene_ids,
        total_scene_count=total_scene_count,
    )
    path = checkpoint_path(workspace, stage_hash)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_contextual_translation_checkpoint(
    workspace,
    *,
    stage_hash: str,
) -> ContextualTranslationCheckpointState | None:
    path = checkpoint_path(workspace, stage_hash)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    checkpoint_meta = dict(payload.get("checkpoint") or {})
    return ContextualTranslationCheckpointState(
        scenes=_restore_record_list(payload.get("scenes", []), SceneMemoryRecord),
        character_profiles=_restore_record_list(payload.get("character_profiles", []), CharacterProfileRecord),
        relationship_profiles=_restore_record_list(payload.get("relationship_profiles", []), RelationshipProfileRecord),
        analyses=_restore_record_list(payload.get("segment_analyses", []), SegmentAnalysisRecord),
        route_decisions=[SceneRouteDecision.model_validate(item) for item in payload.get("route_decisions", [])],
        term_entity_sheets=[SceneTermEntitySheet.model_validate(item) for item in payload.get("term_entity_sheets", [])],
        metrics=ContextualRunMetrics.model_validate(payload.get("metrics") or {}),
        completed_scene_ids=[str(item) for item in checkpoint_meta.get("completed_scene_ids", [])],
        completed_scene_count=int(checkpoint_meta.get("completed_scene_count", 0)),
        total_scene_count=int(checkpoint_meta.get("total_scene_count", 0)),
    )


def clear_contextual_translation_checkpoint(workspace, *, stage_hash: str) -> None:
    path = checkpoint_path(workspace, stage_hash)
    if path.exists():
        path.unlink()

```
-> `src/app/translate/contextual_checkpoint.py:1-134`
Key path: `workspace.cache_dir / translate_contextual / {stage_hash} / contextual_translation.partial.json`.
Resume: load completed_scene_ids; skip those scenes; restore analyses/profiles/metrics.

## 4. Semantic QC rule set
```python
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .relationship_memory import split_allowed_alternates_by_side


DEFAULT_CONFIDENCE_THRESHOLD = 0.65
LOCKED_RELATION_STATUSES = {"locked_by_human", "confirmed", "locked"}

COMMON_VI_PRONOUNS = {
    "anh",
    "em",
    "tôi",
    "toi",
    "ta",
    "tao",
    "mày",
    "may",
    "cậu",
    "cau",
    "bạn",
    "ban",
    "con",
    "mẹ",
    "me",
    "cha",
    "bố",
    "bo",
    "ông",
    "ong",
    "bà",
    "ba",
    "cô",
    "co",
    "chú",
    "chu",
    "dì",
    "di",
    "thầy",
    "thay",
    "sư phụ",
    "su phu",
    "sư huynh",
    "su huynh",
    "sư tỷ",
    "su ty",
    "chúng ta",
    "chung ta",
    "chúng tôi",
    "chung toi",
    "quý vị",
    "quy vi",
    "quý khách",
    "quy khach",
    "các bạn",
    "cac ban",
    "mọi người",
    "moi nguoi",
    "khán giả",
    "khan gia",
}
GENERIC_AUDIENCE_IDS = {
    "audience",
    "general humanity",
    "general audience",
    "viewer",
    "viewers",
    "public",
    "nguoi xem",
    "khan gia",
}
GENERIC_AUDIENCE_ROLES = {"audience"}


@dataclass(slots=True, frozen=True)
class SemanticQcIssue:
    segment_id: str
    segment_index: int
    code: str
    severity: str
    message: str


@dataclass(slots=True, frozen=True)
class SemanticQcReport:
    total_segments: int
    issues: list[SemanticQcIssue]

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")


def _row_value(row: object, field: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(field, default)
    try:
        return row[field]  # type: ignore[index]
    except Exception:
        return getattr(row, field, default)


def _normalize_text(text: str) -> str:
    # Normalize punctuation boundaries so "em," still counts as a vocative/pronoun.
    normalized = re.sub(r"[^\w\s]", " ", (text or "").strip().lower().replace("\n", " "), flags=re.UNICODE)
    return " ".join(normalized.split())


def _contains_term(text: str, term: str) -> bool:
    normalized_text = f" {_normalize_text(text)} "
    normalized_term = f" {_normalize_text(term)} "
    return bool(term and normalized_term in normalized_text)


def _extract_pronoun_terms(text: str) -> set[str]:
    normalized = f" {_normalize_text(text)} "
    return {term for term in COMMON_VI_PRONOUNS if f" {term} " in normalized}


def _primary_listener_payload(row: object) -> dict[str, object]:
    listeners = _row_value(row, "listeners_json", []) or []
    if isinstance(listeners, list) and listeners:
        primary_listener = listeners[0] or {}
        if isinstance(primary_listener, dict):
            return primary_listener
    return {}


def _pair_key(row: object) -> tuple[str, str]:
    speaker = _row_value(row, "speaker_json", {}) or {}
    primary_listener = _primary_listener_payload(row)
    speaker_id = str((speaker or {}).get("character_id", "unknown"))
    listener_id = str(primary_listener.get("character_id", "unknown") or "unknown")
    return speaker_id, listener_id


def _is_generic_audience_listener(listener: dict[str, object]) -> bool:
    if not listener:
        return False
    listener_role = _normalize_text(str(listener.get("role", "") or ""))
    listener_id = _normalize_text(str(listener.get("character_id", "") or ""))
    return listener_role in GENERIC_AUDIENCE_ROLES or listener_id in GENERIC_AUDIENCE_IDS


def _is_narration_like(row: object) -> bool:
    speaker = _row_value(row, "speaker_json", {}) or {}
    speaker_source = _normalize_text(str((speaker or {}).get("source", "") or ""))
    if speaker_source == "narration":
        return True
    return _is_generic_audience_listener(_primary_listener_payload(row))


def _effective_honorific_terms(
    row: object,
    *,
    honorific_policy: dict[str, object],
    subtitle_text: str,
    tts_text: str,
) -> tuple[str, str]:
    self_term = str(honorific_policy.get("self_term", "") or "").strip()
    address_term = str(honorific_policy.get("address_term", "") or "").strip()
    if not (self_term or address_term):
        return self_term, address_term
    if not _is_narration_like(row):
        return self_term, address_term
    subtitle_has_policy = (self_term and _contains_term(subtitle_text, self_term)) or (
        address_term and _contains_term(subtitle_text, address_term)
    )
    tts_has_policy = (self_term and _contains_term(tts_text, self_term)) or (
        address_term and _contains_term(tts_text, address_term)
    )
    if subtitle_has_policy or tts_has_policy:
        return self_term, address_term
    return "", ""


def _relation_status_is_locked(status: object) -> bool:
    return str(status or "").strip().lower() in LOCKED_RELATION_STATUSES


def analyze_segment_analyses(
    rows: Iterable[object],
    *,
    relationship_defaults: dict[tuple[str, str], dict[str, object]] | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> SemanticQcReport:
    normalized_rows = list(rows)
    issues: list[SemanticQcIssue] = []
    previous_policy_by_pair: dict[tuple[str, str, str], tuple[str, str]] = {}
    relationship_map = relationship_defaults or {}

    for row in normalized_rows:
        segment_id = str(_row_value(row, "segment_id", ""))
        segment_index = int(_row_value(row, "segment_index", 0))
        scene_id = str(_row_value(row, "scene_id", ""))
        confidence = _row_value(row, "confidence_json", {}) or {}
        speaker = _row_value(row, "speaker_json", {}) or {}
        honorific_policy = _row_value(row, "honorific_policy_json", {}) or {}
        risk_flags = set(_row_value(row, "risk_flags_json", []) or [])
        resolved_ellipsis = _row_value(row, "resolved_ellipsis_json", {}) or {}
        subtitle_text = str(_row_value(row, "approved_subtitle_text", "") or "")
        tts_text = str(_row_value(row, "approved_tts_text", "") or "")

        speaker_confidence = float(confidence.get("speaker", speaker.get("confidence", 0.0)) or 0.0)
        listener_confidence = float(confidence.get("listener", 0.0) or 0.0)
        relation_confidence = float(confidence.get("relation", honorific_policy.get("confidence", 0.0)) or 0.0)
        overall_confidence = float(confidence.get("overall", 0.0) or 0.0)
        ellipsis_confidence = float(resolved_ellipsis.get("confidence", 0.0) or 0.0)

        narration_like = _is_narration_like(row)
        self_term, address_term = _effective_honorific_terms(
            row,
            honorific_policy=honorific_policy,
            subtitle_text=subtitle_text,
            tts_text=tts_text,
        )
        weak_listener_evidence = listener_confidence < 0.5 or "listener_ambiguous" in risk_flags
        weak_discourse_evidence = min(speaker_confidence, max(listener_confidence, ellipsis_confidence)) < 0.55

        if overall_confidence < confidence_threshold:
            issues.append(
                SemanticQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="low_confidence_gate",
                    severity="error",
                    message="Confidence tong the thap, can review truoc khi TTS/export.",
                )
            )

        if (self_term or address_term) and weak_listener_evidence:
            issues.append(
                SemanticQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="addressee_mismatch",
                    severity="warning",
                    message="Da chen xung ho nhung nguoi nghe con mo ho.",
                )
            )

        if (self_term or address_term) and weak_discourse_evidence:
            issues.append(
                SemanticQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="pronoun_without_evidence",
                    severity="warning",
                    message="Da chen ngoi xung ho khi bang chung discourse con yeu.",
                )
            )

        subtitle_pronouns = _extract_pronoun_terms(subtitle_text)
        tts_pronouns = _extract_pronoun_terms(tts_text)
        if narration_like and subtitle_pronouns != tts_pronouns and (subtitle_pronouns or tts_pronouns):
            issues.append(
                SemanticQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="sub_tts_pronoun_divergence",
                    severity="error",
                    message="Thuyet minh dang lech cach goi khan gia/xung ho giua subtitle va TTS.",
                )
            )
        elif subtitle_pronouns and tts_pronouns and subtitle_pronouns != tts_pronouns:
            issues.append(
                SemanticQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="sub_tts_pronoun_divergence",
                    severity="error",
                    message="Phu de va loi TTS dang dung ngoi xung ho khac nhau.",
                )
            )
        elif self_term and address_term:
            sub_has_policy = _contains_term(subtitle_text, self_term) or _contains_term(subtitle_text, address_term)
            tts_has_policy = _contains_term(tts_text, self_term) or _contains_term(tts_text, address_term)
            if sub_has_policy != tts_has_policy:
                unsafe_tts_only_injection = tts_has_policy and not sub_has_policy and (
                    weak_listener_evidence or weak_discourse_evidence or narration_like
                )
                issues.append(
                    SemanticQcIssue(
                        segment_id=segment_id,
                        segment_index=segment_index,
                        code="sub_tts_pronoun_divergence",
                        severity="error" if unsafe_tts_only_injection else "warning",
                        message=(
                            "Loi TTS dang tu them xung ho khi bang chung nguoi nghe/discourse con yeu."
                            if unsafe_tts_only_injection
                            else "Phu de va loi TTS chua bam cung policy xung ho."
                        ),
                    )
                )

        pair = _pair_key(row)
        if pair[0] != "unknown" or pair[1] != "unknown":
            pair_key = (scene_id, pair[0], pair[1])
            policy_signature = (self_term, address_term)
            previous_signature = previous_policy_by_pair.get(pair_key)
            if previous_signature and previous_signature != policy_signature and self_term and address_term:
                issues.append(
                    SemanticQcIssue(
                        segment_id=segment_id,
                        segment_index=segment_index,
                        code="honorific_drift",
                        severity="error",
                        message="Cap speaker/listener nay dang troi xung ho trong cung scene.",
                    )
                )
            previous_policy_by_pair[pair_key] = policy_signature

        relation_defaults = relationship_map.get(pair, {})
        expected_self_term = str(relation_defaults.get("default_self_term", "") or "")
        expected_address_term = str(relation_defaults.get("default_address_term", "") or "")
        allowed_self_alternates, allowed_address_alternates = split_allowed_alternates_by_side(
            relation_defaults.get("allowed_alternates_json", [])
        )
        relation_status_locked = _relation_status_is_locked(relation_defaults.get("status"))
        if relation_confidence >= 0.7 and (expected_self_term or expected_address_term):
            if (
                expected_self_term
                and self_term
                and self_term != expected_self_term
                and self_term not in allowed_self_alternates
            ):
                issues.append(
                    SemanticQcIssue(
                        segment_id=segment_id,
                        segment_index=segment_index,
                        code="directionality_mismatch",
                        severity="error" if relation_status_locked else "warning",
                        message=(
                            "Xung ho tu xung khong khop relation memory da khoa/xac nhan."
                            if relation_status_locked
                            else "Xung ho tu xung khong khop relation memory hien co."
                        ),
                    )
                )
            if (
                expected_address_term
                and address_term
                and address_term != expected_address_term
                and address_term not in allowed_address_alternates
            ):
                issues.append(
                    SemanticQcIssue(
                        segment_id=segment_id,
                        segment_index=segment_index,
                        code="directionality_mismatch",
                        severity="error" if relation_status_locked else "warning",
                        message=(
                            "Xung ho goi nguoi nghe khong khop relation memory da khoa/xac nhan."
                            if relation_status_locked
                            else "Xung ho goi nguoi nghe khong khop relation memory hien co."
                        ),
                    )
                )

    return SemanticQcReport(total_segments=len(normalized_rows), issues=issues)

```
-> `src/app/translate/semantic_qc.py:1-367`
### Rule table
| rule id | threshold / condition | severity | hard-block? |
|---------|----------------------|----------|-------------|
| low_confidence_gate | overall_confidence < 0.65 | error | yes (via semantic_qc_passed=false) |
| addressee_mismatch | honorific terms + listener_conf < 0.5 or listener_ambiguous | warning | no alone |
| pronoun_without_evidence | honorific + min(speaker, max(listener, ellipsis)) < 0.55 | warning | no alone |
| sub_tts_pronoun_divergence | pronoun set sub≠tts; or TTS-only policy inject under weak evidence | error (or warning if not unsafe) | yes when error |
| honorific_drift | same speaker/listener pair policy changes mid-scene | error | yes |
| directionality_mismatch | self/address ≠ relation memory defaults and not in allowed_alternates; conf≥0.7 | error if locked else warning | yes when error |
### Review gate predicate (TTS/export)
```python
# main_window.py:_ensure_contextual_semantic_ready
pending_rows = [
    row for row in analysis_rows
    if bool(row['needs_human_review']) or not bool(row['semantic_qc_passed'])
]
if pending_rows: block TTS/export
```
-> `src/app/ui/main_window.py:6497-6526`
### Distilled docs (full)
#### docs/REVIEW_REASON_CODES.md
```markdown
# Review Reason Codes

This file records stable review reason codes used by contextual translation and semantic QC.

## Purpose

Review reason codes should be:

- short
- normalized
- stable across prompts, runtime normalization, tests, and fixtures

This keeps real-world regressions assertable.

## Current normalization hook

- [src/app/translate/contextual_runtime.py](C:\Users\HulkBeoti\Documents\Reup_Video\src\app\translate\contextual_runtime.py)

## Current code families

- `uncertain_speaker`
- `uncertain_listener`
- `ambiguous_term`
- `technical_term_uncertainty`
- `ambiguous_reference`
- `ambiguous_object_reference`
- `ambiguous_damage_description`
- `tone_ambiguity`
- `unspecified_review_reason`

## Semantic QC related codes

These may come from deterministic QC instead of the model:

- `low_confidence_gate`
- `addressee_mismatch`
- `pronoun_without_evidence`
- `sub_tts_pronoun_divergence`
- `honorific_drift`
- `directionality_mismatch`

## Severity note

- `sub_tts_pronoun_divergence` is not always equally severe.
- When `tts_text` is the only side injecting pronoun/vocative and listener or ellipsis evidence is weak, it should be treated as blocking semantic QC, not just a cosmetic warning.
- `directionality_mismatch` should also be treated as blocking when it violates a locked/confirmed relationship memory, because that means the reviewer has already frozen the intended honorific direction.

## Rules

- Prefer normalized snake_case codes over raw model prose.
- If model output is noisy, normalize before persisting and testing.
- `technical_term_uncertainty` is reserved for narration/term-sheet style cases where a term or named entity is central enough that the runtime should hold the segment in review instead of silently guessing a Vietnamese rendering.
- `ambiguous_term` can still be cleared automatically in narration fast v2 for narrow deterministic cases such as incomplete scientific notation (`10^`) when adjacent lines provide exactly one safe exponent hint; if the hint set conflicts or stays incomplete, the segment must remain in review.
- narration fast v2 still routes unresolved hard cases to stable codes such as `technical_term_uncertainty`, `ambiguous_term`, or `low_confidence_gate`; the cost-saving lane must abstain and review, not guess.
- New codes should be documented here when they become stable enough for fixtures/tests.

```
-> `docs/REVIEW_REASON_CODES.md:1-55`
#### docs/ERROR_TAXONOMY.md
```markdown
# Error Taxonomy

This file classifies failures for regression-oriented bugfix work.

## 1. Input / Context

Definition:
- wrong or missing source context enters the stage

Examples:
- scene window omits relevant turns
- glossary/context payload is empty when required

Typical fix:
- fix payload builder, scene windowing, or fixture preparation

## 2. Schema / Contract

Definition:
- model output schema or internal data contract lacks required fields or invariants

Examples:
- no `speaker/listener` field
- no explicit `honorific_policy`
- no way to represent review state
- relation memory stores alternates too coarsely, so a self-only alternate accidentally relaxes address-side checks

Typical fix:
- update Pydantic/DB schema and callers together

## 3. Memory Persistence / Restore

Definition:
- character/relationship/scene state is not stored, restored, or locked correctly

Examples:
- relationship defaults drift after reload
- active artifacts restore but semantic state does not
- relationship status (`hypothesized` vs `locked_by_human`) is dropped before QC, so locked memory is enforced too weakly

Typical fix:
- fix DB persistence, restore logic, or locking semantics

## 4. Semantic Inference

Definition:
- speaker/listener/relation/register inference is wrong or overconfident

Examples:
- wrong speaker
- wrong listener
- pronoun inserted without evidence

Typical fix:
- prompt/schema/context changes plus confidence/review routing

## 5. Dialogue Adaptation

Definition:
- `subtitle_text` and `tts_text` diverge in meaning, honorifics, or discourse stance

Examples:
- subtitle neutral, TTS adds "em"
- TTS changes politeness level

Typical fix:
- tighten adaptation invariant or critic/QC checks

## 6. Semantic QC / Severity

Definition:
- a real semantic failure is only marked as warning or not flagged at all

Examples:
- `sub_tts_pronoun_divergence` stays warning when it should block export
- vocative or pronoun appears only in `tts_text`, but punctuation-boundary matching misses it
- TTS-only pronoun injection under ambiguous listener evidence is treated as non-blocking
- `directionality_mismatch` stays warning even when relation memory was manually locked
- neutral narration inherits stale default audience policy and gets false-positive `honorific_drift`
- narration `tts_text` injects `quy vi`/`cac ban` while subtitle stays neutral and QC misses the one-sided drift

Typical fix:
- promote severity, add new QC rule, or add invariant

## 7. Review Routing / Confidence

Definition:
- ambiguous or low-confidence outputs do not reach human review

Examples:
- `needs_human_review` stays false under weak listener evidence

Typical fix:
- confidence threshold, reason code normalization, review gate logic

## 8. Gate / Safety Enforcement

Definition:
- TTS/export can proceed even though semantic state is unsafe

Examples:
- semantic QC has issues but downstream still runs

Typical fix:
- block at canonical output, TTS stage, subtitle export, and video export

## 9. Voice / Speaker Mapping

Definition:
- wrong speaker uses wrong voice preset or wrong voiceover track

Examples:
- future speaker->voice binding mismatch

Typical fix:
- binding layer, lock semantics, speaker validation

## 10. UI / Human Review UX

Definition:
- reviewer cannot see enough context to make the correct decision

Examples:
- review panel misses scene summary or surrounding turns

Typical fix:
- improve review surface, not translation logic

## 11. Export / Render / State Staleness

Definition:
- downstream artifacts are stale or inconsistent with approved canonical data

Examples:
- video uses old mixed audio after subtitle review
- cached TTS clips lose duration metadata on rerun, so voice track fitting trims audio before the sentence is fully spoken

Typical fix:
- invalidate state, recompute expected artifact hash, block export when stale

## 12. Environment / Packaging

Definition:
- app fails because runtime dependency or packaging contract is broken

Examples:
- missing mpv DLL, ffmpeg path, PyInstaller bundle omission

Typical fix:
- detection, build script, installer, runtime diagnostics

## 13. Translation Runtime / Batch Resilience

Definition:
- a retryable LLM batch failure aborts the whole contextual run instead of degrading safely to smaller batches

Examples:
- dialogue adaptation returns truncated structured JSON on a long scene batch and the run crashes on a parse error
- stage output is structurally invalid for a large batch but succeeds when rows are retried in smaller slices

Typical fix:
- treat retryable structured-output parse/schema failures as a batch-size/runtime resilience issue
- split to smaller batches automatically
- still surface the original error once the batch is down to a single row

## Required handling rules

- Ambiguous semantic cases must fail-safe to review, not silent guessing.
- Any class-4/5/6/7/8 bug should usually produce a regression fixture.
- Any class-13 bug should usually produce a regression fixture plus a runtime retry/guard test.
- Export/TTS must not proceed through unsafe class-4/5/6/7 states.

```
-> `docs/ERROR_TAXONOMY.md:1-171`
#### docs/SEMANTIC_QC_SPEC.md
```markdown
# Semantic QC Spec

This document records the intended role of semantic QC before TTS/export.

## Current implementation location

- rules: [src/app/translate/semantic_qc.py](C:\Users\HulkBeoti\Documents\Reup_Video\src\app\translate\semantic_qc.py)
- QC recompute + persistence: [src/app/translate/contextual_pipeline.py](C:\Users\HulkBeoti\Documents\Reup_Video\src\app\translate\contextual_pipeline.py)
- review UI: [src/app/ui/main_window.py](C:\Users\HulkBeoti\Documents\Reup_Video\src\app\ui\main_window.py)

## Purpose

Semantic QC is the last deterministic safety layer between:

- contextual translation outputs
- human review queue
- TTS/export

It should catch classes of failure that are dangerous even when the text is fluent.

## Current rule families

- `low_confidence_gate`
- `addressee_mismatch`
- `pronoun_without_evidence`
- `sub_tts_pronoun_divergence`
- `honorific_drift`
- `directionality_mismatch`

## Core invariants

1. `subtitle_text` and `tts_text` should preserve the same discourse stance.
2. Honorific policy should not drift inside the same speaker/listener pair without evidence.
3. Pronoun or vocative insertion under weak listener evidence should not silently pass.
4. Locked relation memory should constrain honorific choices.
5. Unsafe semantic outputs must not proceed to TTS/export.
6. Pronoun/vocative detection must work across punctuation boundaries such as `em,` or `anh...`.
7. If `tts_text` adds honorific policy that `subtitle_text` does not carry, and listener/discourse evidence is weak, QC should raise an error rather than a warning.
8. If relationship memory is `locked_by_human` or otherwise confirmed, a self/address-term mismatch against that relation should raise an error rather than a warning.
9. `allowed_alternates` under a locked/confirmed relation acts as a whitelist override for valid alternate self/address terms; those alternates must not be blocked as `directionality_mismatch`.
10. When `allowed_alternates` is side-specific, it must only relax the intended side:
    - `self_terms` may relax `self_term` only
    - `address_terms` may relax `address_term` only
    - legacy flat lists continue to mean "allowed on both sides"
11. Narration-safe rows must not inherit stale default audience honorific policy if `subtitle_text` and `tts_text` are both neutral.
12. Narration rows must not let `tts_text` inject audience-address terms such as `quy vi`, `cac ban`, or `moi nguoi` on only one side.

## Fail-safe rule

If the system cannot be confident enough about:

- speaker
- listener
- relation
- honorific policy
- key semantic referent

then the output should prefer:

- conservative wording
- `needs_human_review = true`
- semantic QC issue

instead of a confident but risky guess.

For narration videos in particular, this means:

- incomplete fragments stay in review
- technical-term uncertainty stays in review until a human closes the term
- neutral narration should remain neutral unless the audience address is explicit in both subtitle and TTS

## Recommended future additions

- speaker/listener consistency across adjacent reply pairs
- scene memory drift checks
- unresolved proper noun tracking
- locked policy override detection
- future speaker -> voice preset mismatch checks

## Review reason code expectations

Review reason codes should be:

- normalized
- stable
- reusable across fixtures and test assertions

Normalization currently lives in:
- [src/app/translate/contextual_runtime.py](C:\Users\HulkBeoti\Documents\Reup_Video\src\app\translate\contextual_runtime.py)

```
-> `docs/SEMANTIC_QC_SPEC.md:1-89`
#### docs/KNOWN_LIMITATIONS.md
```markdown
# Known Limitations

This file tracks current limitations so future bugfixes do not confuse "not implemented yet" with regressions.

## Current known limits

1. No automatic diarization / speaker clustering pipeline is wired end-to-end.
2. Speaker -> voice preset binding va voice policy hien van la manual; chua co diarization auto hay speaker cluster -> character binding.
3. Prompt templates are seeded from code into project-local preset files, not managed from a single repo prompt catalog directory.
4. Golden semantic datasets da co semantic-QC manifest va review-gate manifest, nhung do phu van mong so voi cac edge case thuc te.
5. Some real-world sample resolution/polish scripts live under [scripts](C:\Users\HulkBeoti\Documents\Reup_Video\scripts) and are useful for exploration, but they are not a substitute for fixture-driven regression tests.
6. Register-aware voice style da co layer rieng cho `speed/volume/pitch`, nhung chua co emotion modeling sau hon, auto voice casting, hoac policy semantic tinh vi hon theo actor/persona.
7. Release hardening hien moi o muc local Windows personal-use:
   - doctor/preflight co the block dung stage
   - workspace backup/repair/cache ops da co
   - nhung chua co transactional rollback day du hay auto dependency installer
8. Packaging smoke da co headless doctor mode va checklist, nhung van can manual validation tren bundle/installer truoc khi ship cho nguoi khac.
9. Clean-machine validation kit hien tai moi cover `bundle first`:
   - da co script chuan bi kit + report contract
   - installer validation van la wave tiep theo sau khi bundle pass tren may sach

## Important distinction

- A limitation should route to review or conservative behavior.
- A regression is when behavior becomes worse than intended contract or prior guard.

## Current contract reminders

- `allowed_alternates` in relationship memory now supports both:
  - legacy flat lists, which apply to both sides
  - side-specific dictionaries such as `self_terms` and `address_terms`
- Refactors to semantic QC should preserve the behavior that whitelisted alternates remain safe even under `locked_by_human` relations.
- Speaker binding should preserve three fail-safe rules:
  - no saved bindings => global preset path
  - active bindings + unresolved recognized speaker => block TTS/export
  - `unknown_*` placeholder speakers => fallback to global preset
- Voice policy should preserve six precedence/fail-safe rules:
  - explicit speaker binding wins over voice policy
  - relationship policy wins over character policy
  - missing preset in selected policy source blocks instead of silently falling back
  - no matching policy is safe to fall back to the global preset
  - style-only policies are valid and must not be treated as unbound
  - relationship style overrides beat character style overrides field-by-field
- Register-aware voice style should preserve four rules:
  - it only affects `speed/volume/pitch`, not preset selection
  - it sits below relationship/character style overrides
  - `needs_human_review` or weak speaker/relation confidence skips register-aware style
  - missing register style policy is a safe fallback, not a blocker

```
-> `docs/KNOWN_LIMITATIONS.md:1-48`
#### docs/GOLDEN_SEMANTIC_DATASET.md
```markdown
# Golden Semantic Dataset

This dataset is the stable reference layer for semantic behavior that should remain intentional across refactors.

## Purpose

Use it when a zh->vi semantic case has a known intended outcome and we want the repo to keep enforcing that outcome automatically.

Typical examples:

- a dialogue pair that should pass cleanly
- a narration line that should stay neutral
- a locked relation case that must block when directionality drifts
- an allowed alternate case that must stay safe

## Storage

- semantic QC dataset manifest:
  - [tests/fixtures/golden/semantic_dataset_manifest.json](C:\Users\HulkBeoti\Documents\Reup_Video\tests\fixtures\golden\semantic_dataset_manifest.json)
- review gate dataset manifest:
  - [tests/fixtures/golden/review_gate_dataset_manifest.json](C:\Users\HulkBeoti\Documents\Reup_Video\tests\fixtures\golden\review_gate_dataset_manifest.json)
- fixture folder:
  - [tests/fixtures/golden](C:\Users\HulkBeoti\Documents\Reup_Video\tests\fixtures\golden)
- semantic QC harness:
  - [tests/semantic_qc/test_golden_semantic_dataset.py](C:\Users\HulkBeoti\Documents\Reup_Video\tests\semantic_qc\test_golden_semantic_dataset.py)
- review gate harness:
  - [tests/integration/test_review_gate_dataset.py](C:\Users\HulkBeoti\Documents\Reup_Video\tests\integration\test_review_gate_dataset.py)

## Contract

Each dataset entry should declare:

- `fixture_id`
- `path`
- `source_run`
- `class`
- `expected_outcome`
- `expected.error_count`
- `expected.warning_count`
- `expected.required_codes`
- `expected.forbidden_codes`

For review-gate entries, use:

- `fixture_id`
- `path`
- `source_run`
- `class`
- `expected_outcome`

Each fixture should stay minimal, anonymized if needed, and semantically meaningful.

## When to add a case

Add a golden case when:

- the intended semantic behavior is stable
- we want future refactors to preserve it exactly
- the case is no longer ambiguous after review/policy decisions

Do not add unresolved ambiguous cases to the semantic QC manifest. Those belong in regression fixtures or the review-gate manifest until the routing policy is clear.

## Current scope

Current dataset covers:

- stable family-style honorific consistency
- neutral narration
- locked relation allowed alternates
- side-specific alternate contract
- reviewed real-world dialogue from `Video_test_TQ`
- real-world fail-safe cases for pronoun divergence and low-confidence single-turn ambiguity
- reviewed object-reference cases from `Shinchan`
- reviewed technical narration/object phrase cases from `Wilderness`
- narration-safe stale audience-policy cases from `Earth depth`
- narration TTS-only audience-address injection as a blocking QC case
- narration pre-review fail-safe routing for:
  - `incomplete_fragment`
  - `technical_term_uncertainty`
- pre-review fail-safe routing for:
  - `ambiguous_term`
  - `ambiguous_object_reference`
  - `uncertain_speaker`
  - `unclear_relationship`
  - `tone_ambiguity`
  - `insufficient_context`

```
-> `docs/GOLDEN_SEMANTIC_DATASET.md:1-86`

## 5. zh→vi specific intelligence
### 5.1 Character / relationship / scene memory DDL
```sql
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_dir TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    translation_mode TEXT NOT NULL DEFAULT 'legacy',
    video_asset_id TEXT,
    active_subtitle_track_id TEXT,
    active_voice_preset_id TEXT,
    active_export_preset_id TEXT,
    active_watermark_profile_id TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media_assets (
    asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    duration_ms INTEGER,
    fps REAL,
    width INTEGER,
    height INTEGER,
    audio_channels INTEGER,
    sample_rate INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS segments (
    segment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    source_lang TEXT,
    target_lang TEXT,
    source_text TEXT NOT NULL DEFAULT '',
    source_text_norm TEXT NOT NULL DEFAULT '',
    translated_text TEXT NOT NULL DEFAULT '',
    translated_text_norm TEXT NOT NULL DEFAULT '',
    subtitle_text TEXT NOT NULL DEFAULT '',
    tts_text TEXT NOT NULL DEFAULT '',
    audio_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    meta_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subtitle_tracks (
    track_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'user',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subtitle_events (
    event_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_segment_id TEXT,
    event_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    source_lang TEXT,
    target_lang TEXT,
    source_text TEXT NOT NULL DEFAULT '',
    source_text_norm TEXT NOT NULL DEFAULT '',
    translated_text TEXT NOT NULL DEFAULT '',
    translated_text_norm TEXT NOT NULL DEFAULT '',
    subtitle_text TEXT NOT NULL DEFAULT '',
    tts_text TEXT NOT NULL DEFAULT '',
    audio_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    meta_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(track_id) REFERENCES subtitle_tracks(track_id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_runs (
    job_id TEXT PRIMARY KEY,
    project_id TEXT,
    stage TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    input_hash TEXT NOT NULL DEFAULT '',
    output_paths_json TEXT NOT NULL DEFAULT '[]',
    log_path TEXT,
    error_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    retry_of_job_id TEXT,
    message TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE SET NULL,
    FOREIGN KEY(retry_of_job_id) REFERENCES job_runs(job_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_media_assets_project_id ON media_assets(project_id);
CREATE INDEX IF NOT EXISTS idx_segments_project_id ON segments(project_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_tracks_project_id ON subtitle_tracks(project_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_events_project_track ON subtitle_events(project_id, track_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subtitle_events_track_index ON subtitle_events(track_id, event_index);
CREATE INDEX IF NOT EXISTS idx_job_runs_project_id ON job_runs(project_id);

CREATE TABLE IF NOT EXISTS character_profiles (
    character_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    canonical_name_zh TEXT NOT NULL DEFAULT '',
    canonical_name_vi TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    gender_hint TEXT,
    age_role TEXT,
    social_role TEXT,
    speech_style TEXT,
    default_register_profile_json TEXT NOT NULL DEFAULT '{}',
    default_self_terms_json TEXT NOT NULL DEFAULT '[]',
    default_address_terms_json TEXT NOT NULL DEFAULT '[]',
    forbidden_terms_json TEXT NOT NULL DEFAULT '[]',
    evidence_segment_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'hypothesized',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationship_profiles (
    relationship_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    from_character_id TEXT NOT NULL,
    to_character_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'unknown',
    power_delta TEXT,
    age_delta TEXT,
    intimacy_level TEXT,
    default_self_term TEXT,
    default_address_term TEXT,
    allowed_alternates_json TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'scene',
    status TEXT NOT NULL DEFAULT 'hypothesized',
    evidence_segment_ids_json TEXT NOT NULL DEFAULT '[]',
    last_updated_scene_id TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_memories (
    scene_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    scene_index INTEGER NOT NULL,
    start_segment_index INTEGER NOT NULL,
    end_segment_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    location TEXT,
    time_context TEXT,
    short_scene_summary TEXT NOT NULL DEFAULT '',
    recent_turn_digest TEXT NOT NULL DEFAULT '',
    active_topic TEXT,
    current_conflict TEXT,
    current_emotional_tone TEXT,
    temporary_addressing_mode TEXT,
    who_knows_what_json TEXT NOT NULL DEFAULT '{}',
    open_ambiguities_json TEXT NOT NULL DEFAULT '[]',
    unresolved_references_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS segment_analyses (
    segment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    speaker_json TEXT NOT NULL DEFAULT '{}',
    listeners_json TEXT NOT NULL DEFAULT '[]',
    register_json TEXT NOT NULL DEFAULT '{}',
    turn_function TEXT,
    resolved_ellipsis_json TEXT NOT NULL DEFAULT '{}',
    honorific_policy_json TEXT NOT NULL DEFAULT '{}',
    semantic_translation TEXT NOT NULL DEFAULT '',
    glossary_hits_json TEXT NOT NULL DEFAULT '[]',
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    confidence_json TEXT NOT NULL DEFAULT '{}',
    needs_human_review INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'draft',
    review_scope TEXT,
    review_reason_codes_json TEXT NOT NULL DEFAULT '[]',
    review_question TEXT NOT NULL DEFAULT '',
    approved_subtitle_text TEXT NOT NULL DEFAULT '',
    approved_tts_text TEXT NOT NULL DEFAULT '',
    semantic_qc_passed INTEGER NOT NULL DEFAULT 0,
    semantic_qc_issues_json TEXT NOT NULL DEFAULT '[]',
    source_template_family_id TEXT,
    adaptation_template_family_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY(scene_id) REFERENCES scene_memories(scene_id) ON DELETE CASCADE,
    FOREIGN KEY(segment_id) REFERENCES segments(segment_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_character_profiles_project_id ON character_profiles(project_id);
CREATE INDEX IF NOT EXISTS idx_relationship_profiles_project_id ON relationship_profiles(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_profiles_direction ON relationship_profiles(project_id, from_character_id, to_character_id);
CREATE INDEX IF NOT EXISTS idx_scene_memories_project_id ON scene_memories(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scene_memories_project_scene_index ON scene_memories(project_id, scene_index);
CREATE INDEX IF NOT EXISTS idx_segment_analyses_project_id ON segment_analyses(project_id);
CREATE INDEX IF NOT EXISTS idx_segment_analyses_scene_id ON segment_analyses(scene_id);

CREATE TABLE IF NOT EXISTS speaker_bindings (
    binding_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    speaker_type TEXT NOT NULL DEFAULT 'character',
    speaker_key TEXT NOT NULL,
    voice_preset_id TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_speaker_bindings_unique
ON speaker_bindings(project_id, speaker_type, speaker_key);
CREATE INDEX IF NOT EXISTS idx_speaker_bindings_project_id ON speaker_bindings(project_id);

CREATE TABLE IF NOT EXISTS voice_policies (
    policy_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    policy_scope TEXT NOT NULL DEFAULT 'character',
    speaker_character_id TEXT NOT NULL,
    listener_character_id TEXT NOT NULL DEFAULT '',
    voice_preset_id TEXT NOT NULL,
    speed_override REAL,
    volume_override REAL,
    pitch_override REAL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_policies_unique
ON voice_policies(project_id, policy_scope, speaker_character_id, listener_character_id);
CREATE INDEX IF NOT EXISTS idx_voice_policies_project_id ON voice_policies(project_id);

CREATE TABLE IF NOT EXISTS register_voice_style_policies (
    policy_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    politeness TEXT NOT NULL DEFAULT '',
    power_direction TEXT NOT NULL DEFAULT '',
    emotional_tone TEXT NOT NULL DEFAULT '',
    turn_function TEXT NOT NULL DEFAULT '',
    relation_type TEXT NOT NULL DEFAULT '',
    speed_override REAL,
    volume_override REAL,
    pitch_override REAL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_register_voice_style_policies_unique
ON register_voice_style_policies(
    project_id,
    politeness,
    power_direction,
    emotional_tone,
    turn_function,
    relation_type
);
CREATE INDEX IF NOT EXISTS idx_register_voice_style_policies_project_id
ON register_voice_style_policies(project_id);
"""
```
-> `src/app/project/database.py` SCHEMA_SQL
Characters identified by `character_id` string from LLM seeds; relationships directional `(from_character_id, to_character_id)` unique per project; scene_memories hold summary + ambiguities; segment_analyses hold per-line honorific_policy + approved_subtitle/tts.
### 5.2 Honorifics / xưng hô
Pronoun detection inventory (QC):
```python
COMMON_VI_PRONOUNS = {
    "anh",
    "em",
    "tôi",
    "toi",
    "ta",
    "tao",
    "mày",
    "may",
    "cậu",
    "cau",
    "bạn",
    "ban",
    "con",
    "mẹ",
    "me",
    "cha",
    "bố",
    "bo",
    "ông",
    "ong",
    "bà",
    "ba",
    "cô",
    "co",
    "chú",
    "chu",
    "dì",
    "di",
    "thầy",
    "thay",
    "sư phụ",
    "su phu",
    "sư huynh",
    "su huynh",
    "sư tỷ",
    "su ty",
    "chúng ta",
    "chung ta",
    "chúng tôi",
    "chung toi",
    "quý vị",
    "quy vi",
    "quý khách",
    "quy khach",
    "các bạn",
    "cac ban",
    "mọi người",
    "moi nguoi",
    "khán giả",
    "khan gia",
}
```
-> `src/app/translate/semantic_qc.py:13-64`
Policy fields on each segment: `HonorificPolicy.self_term`, `address_term`, `locked`, `confidence` (models.py).
Selection is primarily **LLM-driven** in semantic_pass + dialogue_adaptation prompts (preserve honorific policy; empty for narration unless explicit audience address). Deterministic enforcement is QC + locked relationship memory.
Allowed alternates side split:
```python
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from app.project.models import RelationshipProfileRecord


AllowedAlternatesJson = list[str] | dict[str, list[str]]


def _row_value(row: object, field: str, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(field, default)
    try:
        return row[field]  # type: ignore[index]
    except Exception:
        return getattr(row, field, default)


def clone_allowed_alternates(value: object) -> AllowedAlternatesJson:
    if isinstance(value, Mapping):
        cloned: dict[str, list[str]] = {}
        for key, items in value.items():
            if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
                cloned[str(key)] = [str(item) for item in items]
        return cloned
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    return []


def _load_json_like(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, (Mapping, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def split_allowed_alternates_by_side(value: object) -> tuple[set[str], set[str]]:
    cloned = clone_allowed_alternates(value)
    if isinstance(cloned, dict):
        shared_terms = set(cloned.get("both_terms", [])) | set(cloned.get("all_terms", [])) | set(cloned.get("terms", []))
        self_terms = set(cloned.get("self_terms", [])) | shared_terms
        address_terms = set(cloned.get("address_terms", [])) | shared_terms
        return self_terms, address_terms
    legacy_terms = set(cloned)
    return legacy_terms, legacy_terms


def relationship_record_from_row(row: object, *, project_id: str) -> RelationshipProfileRecord:
    allowed_alternates = _load_json_like(_row_value(row, "allowed_alternates_json"), [])
    evidence_segment_ids = _load_json_like(_row_value(row, "evidence_segment_ids_json"), [])
    return RelationshipProfileRecord(
        relationship_id=str(_row_value(row, "relationship_id", "")),
        project_id=project_id,
        from_character_id=str(_row_value(row, "from_character_id", "")),
        to_character_id=str(_row_value(row, "to_character_id", "")),
        relation_type=str(_row_value(row, "relation_type", "unknown") or "unknown"),
        power_delta=str(_row_value(row, "power_delta")) if _row_value(row, "power_delta") is not None else None,
        age_delta=str(_row_value(row, "age_delta")) if _row_value(row, "age_delta") is not None else None,
        intimacy_level=str(_row_value(row, "intimacy_level")) if _row_value(row, "intimacy_level") is not None else None,
        default_self_term=str(_row_value(row, "default_self_term")) if _row_value(row, "default_self_term") is not None else None,
        default_address_term=str(_row_value(row, "default_address_term")) if _row_value(row, "default_address_term") is not None else None,
        allowed_alternates_json=clone_allowed_alternates(allowed_alternates),
        scope=str(_row_value(row, "scope", "scene") or "scene"),
        status=str(_row_value(row, "status", "hypothesized") or "hypothesized"),
        evidence_segment_ids_json=[str(item) for item in evidence_segment_ids],
        last_updated_scene_id=(
            str(_row_value(row, "last_updated_scene_id"))
            if _row_value(row, "last_updated_scene_id") is not None
            else None
        ),
        notes=str(_row_value(row, "notes", "") or ""),
        created_at=str(_row_value(row, "created_at", "") or ""),
        updated_at=str(_row_value(row, "updated_at", "") or ""),
    )


def build_locked_relationship_record(
    *,
    existing: RelationshipProfileRecord | None,
    project_id: str,
    relationship_id: str,
    speaker_id: str,
    listener_id: str,
    self_term: str,
    address_term: str,
    now: str,
) -> RelationshipProfileRecord:
    return RelationshipProfileRecord(
        relationship_id=relationship_id,
        project_id=project_id,
        from_character_id=speaker_id,
        to_character_id=listener_id,
        relation_type=existing.relation_type if existing and existing.relation_type else "manual_locked",
        power_delta=existing.power_delta if existing else None,
        age_delta=existing.age_delta if existing else None,
        intimacy_level=existing.intimacy_level if existing else None,
        default_self_term=self_term or None,
        default_address_term=address_term or None,
        allowed_alternates_json=clone_allowed_alternates(existing.allowed_alternates_json if existing else []),
        scope=existing.scope if existing and existing.scope else "global",
        status="locked_by_human",
        evidence_segment_ids_json=list(existing.evidence_segment_ids_json) if existing else [],
        last_updated_scene_id=existing.last_updated_scene_id if existing else None,
        notes=existing.notes if existing else "",
        created_at=existing.created_at if existing and existing.created_at else now,
        updated_at=now,
    )

```
-> `src/app/translate/relationship_memory.py:1-116`
Narration neutralize strips audience vocatives for review preset:
```python
TIMECODE_PATTERN = re.compile(r"^(?P<hours>\d{1,2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})[.,](?P<millis>\d{3})$")
_TTS_WHITESPACE_PATTERN = re.compile(r"\s+")
_TTS_PUNCT_SPACING_PATTERN = re.compile(r"\s+([,.;:?!])")
_NARRATION_AUDIENCE_PATTERN = r"(?:các bạn|cac ban|mọi người|moi nguoi|quý vị|quy vi|bạn|ban)"
_NARRATION_LEADING_AUDIENCE_QUESTION_PATTERN = re.compile(
    rf"^(?:{_NARRATION_AUDIENCE_PATTERN})\b[^?!.]{{0,120}}\?\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_NARRATION_LEADING_VOCATIVE_PATTERN = re.compile(
    rf"^(?:{_NARRATION_AUDIENCE_PATTERN})(?:\s+(?:ơi|à|này))?\s*[,.:!…-]*\s*",
    re.IGNORECASE,
)
_NARRATION_PREFIX_CHUNGTA_PATTERN = re.compile(
    r"^(?P<prefix>giờ|gio|bây giờ|bay gio|hôm nay|hom nay|lúc này|luc nay)\s+"
    r"(?:chúng ta|chung ta)\s+",
    re.IGNORECASE,
)
_NARRATION_CHUNGTA_IMPERATIVE_PATTERN = re.compile(
    r"^(?:chúng ta|chung ta)\s+(?:hãy\s+|hay\s+|cùng\s+|cung\s+)",
    re.IGNORECASE,
)
_NARRATION_TRAILING_AUDIENCE_QUESTION_PATTERN = re.compile(
    rf"(?:,\s*)?(?:{_NARRATION_AUDIENCE_PATTERN}\s+(?:thấy\s+|thay\s+)?)?"
    r"(?:có\s+|co\s+)?(?:đúng không|dung khong)\s*[.?!…]*$",
    re.IGNORECASE,
)
_NARRATION_TRAILING_CONFIRMATION_PATTERN = re.compile(
    r"(?:,\s*)?(?:phải không|phai khong|nhỉ|nhi)\s*[.?!…]*$",
    re.IGNORECASE,
)
_NARRATION_TRAILING_AUDIENCE_PATTERN = re.compile(
    rf"(?:,\s*)?(?:{_NARRATION_AUDIENCE_PATTERN})\s*[.?!…]*$",
    re.IGNORECASE,
)
_NARRATION_TRAILING_SOFTENER_PATTERN = re.compile(
    r"(?:,\s*)?(?:nhé|nhe|nhỉ|nhi|nha|ha)\s*[.?!…]*$",
    re.IGNORECASE,
)
_NARRATION_TRAILING_PUNCT_PATTERN = re.compile(r"[\s,;:!?.…-]+$")


def format_timestamp_ms(total_ms: int) -> str:
    if total_ms < 0:
        raise ValueError("Timestamp khong duoc am")

    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_timestamp_ms(value: str) -> int:
    candidate = value.strip()
    match = TIMECODE_PATTERN.match(candidate)
    if not match:
        raise ValueError(f"Timestamp khong hop le: {value}")

    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    millis = int(match.group("millis"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Timestamp khong hop le: {value}")
    return (((hours * 60) + minutes) * 60 + seconds) * 1_000 + millis


def suggest_subtitle_text(translated_text: str, source_text: str) -> str:
    candidate = translated_text.strip()
    if candidate:
        return candidate
    return source_text.strip()


def normalize_tts_text(value: str) -> str:
    candidate = value.replace("\r\n", "\n").replace("\r", "\n")
    candidate = candidate.replace("\n", " ")
    candidate = candidate.replace("/", ", ")
    candidate = candidate.replace("|", ", ")
    candidate = _TTS_WHITESPACE_PATTERN.sub(" ", candidate).strip()
    candidate = _TTS_PUNCT_SPACING_PATTERN.sub(r"\1", candidate)
    return candidate


def suggest_tts_text(
    subtitle_text: str,
    translated_text: str,
    source_text: str,
    *,
    existing_tts_text: str = "",
) -> str:
    for candidate in (existing_tts_text, subtitle_text, translated_text, source_text):
        normalized = normalize_tts_text(candidate)
        if normalized:
            return normalized
    return ""


def _capitalize_sentence_start(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    first = candidate[0]
    if first.isalpha():
        return first.upper() + candidate[1:]
    return candidate


def neutralize_narration_review_text(value: str) -> str:
    candidate = normalize_tts_text(value)
    if not candidate:
        return ""

    original = candidate
```
-> `src/app/subtitle/editing.py:8-120`
### 5.3 Register model
Produced by LLM into `RegisterDecision` / `register_json`:
- politeness default `informal` (dialogue model) / `neutral` (narration base)
- power_direction default `peer` / `neutral`
- emotional_tone default `neutral` / `informative`
- turn_function default `statement`
- relation_type on relationship_profiles default `unknown`
Consumed by: semantic QC (indirect via confidence), voice register style policies table `register_voice_style_policies` (speed/volume/pitch only; skips if needs_human_review or weak confidence — KNOWN_LIMITATIONS).
Narration base defaults:
```python
def _base_narration_speaker() -> dict[str, object]:
    return {"character_id": "narrator", "source": "narration", "confidence": 0.99}


def _base_narration_listener() -> list[dict[str, object]]:
    return [{"character_id": "audience", "role": "audience", "confidence": 0.95}]


def _base_narration_register() -> dict[str, object]:
    return {
        "politeness": "neutral",
        "power_direction": "neutral",
        "emotional_tone": "informative",
        "confidence": 0.95,
    }


def _base_narration_confidence() -> dict[str, object]:
    return {
        "overall": 0.92,
        "speaker": 0.99,
        "listener": 0.95,
        "register": 0.95,
        "relation": 0.0,
        "translation": 0.9,
    }
```
-> `src/app/translate/narration_fast_v2.py:148-173`
### 5.4 Term memory
```json
{
  "items": []
}

```
-> `src/app/translate/narration_term_memory_defaults.json:1-3` (global defaults empty; project store at `.ops/narration_term_memory.json`).
Mini-pass: term_entity_pass prompt max 6 items; statuses prefer/needs_review; anchor positions or source_text fallback; inject as glossary into later prompts; needs_review → technical_term_uncertainty on segments.
### 5.5 subtitle_text vs tts_text
- Dual fields on `segments` and `segment_analyses.approved_*`.
- Dialogue adaptation prompts: subtitle concise/readable; tts more oral but same honorifics/intent.
- Narration fast: prefer tts_text = subtitle_text; no audience address unless explicit.
- Narration v2: both = canonical_text by default.
- Local TTS normalize: newlines→space, `/` and `|` → `, `, collapse whitespace, fix punct spacing (`normalize_tts_text`).
```python
def normalize_tts_text(value: str) -> str:
    candidate = value.replace("\r\n", "\n").replace("\r", "\n")
    candidate = candidate.replace("\n", " ")
    candidate = candidate.replace("/", ", ")
    candidate = candidate.replace("|", ", ")
    candidate = _TTS_WHITESPACE_PATTERN.sub(" ", candidate).strip()
    candidate = _TTS_PUNCT_SPACING_PATTERN.sub(r"\1", candidate)
    return candidate


def suggest_tts_text(
    subtitle_text: str,
    translated_text: str,
    source_text: str,
    *,
    existing_tts_text: str = "",
) -> str:
    for candidate in (existing_tts_text, subtitle_text, translated_text, source_text):
        normalized = normalize_tts_text(candidate)
        if normalized:
            return normalized
    return ""

```
-> `src/app/subtitle/editing.py:81-103`
### 5.6 Chinese-specific handling
- Vocative/backchannel patterns for routing (各位/大家/... 嗯/啊/...).
- Term intro markers (称为/学名/术语/...).
- Scientific notation repair (10^ incomplete + Chinese numerals 0–200):
```python
_SCIENTIFIC_NOTATION_CUE_RE = re.compile(r"10\s*(?:\^|mũ|mu|次方|的)", re.IGNORECASE)
_INCOMPLETE_SCIENTIFIC_NOTATION_RE = re.compile(r"10\s*(?:\^|mũ)\s*(?=[\.\,\!\?\;\:]|$)", re.IGNORECASE)
_ARABIC_EXPONENT_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_CHINESE_NUMERAL_RE = re.compile(r"[零〇一二两三四五六七八九十百千]+")
```
-> `src/app/translate/narration_fast_v2.py:80-83`
```python
def _parse_simple_chinese_integer(token: str) -> int | None:
    token = str(token or "").strip()
    if not token:
        return None
    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000}
    total = 0
    current = 0
    for char in token:
        if char in digit_map:
            current = digit_map[char]
            continue
        if char in unit_map:
            total += max(1, current) * unit_map[char]
            current = 0
            continue
        return None
    return total + current


def _extract_exponent_hints(*texts: str) -> set[str]:
    hints: set[str] = set()
    for raw_text in texts:
        text = str(raw_text or "").strip()
        if not text:
            continue
        for match in _ARABIC_EXPONENT_RE.findall(text):
            value = int(match)
            if 0 < value <= 200:
                hints.add(str(value))
        if len(text) > 24:
            continue
        for token in _CHINESE_NUMERAL_RE.findall(text):
            value = _parse_simple_chinese_integer(token)
            if value is not None and 0 < value <= 200:
                hints.add(str(value))
    return hints


def _has_incomplete_scientific_notation(text: str) -> bool:
    return bool(_INCOMPLETE_SCIENTIFIC_NOTATION_RE.search(str(text or "")))


def _repair_incomplete_scientific_notation(text: str, *, exponent: str) -> str:
    repaired = _INCOMPLETE_SCIENTIFIC_NOTATION_RE.sub(f"10 mũ {exponent}", str(text or ""))
    return _normalize_canonical_text(repaired)


def _apply_scientific_notation_autofix(
    *,
    render_rows: list[dict[str, object]],
    canonical_by_segment: dict[str, dict[str, object]],
) -> list[str]:
    ordered_rows = list(sorted(render_rows, key=lambda row: int(row["segment_index"])))
    position_by_segment_id = {str(row["segment_id"]): index for index, row in enumerate(ordered_rows)}
    changed_segment_ids: list[str] = []
    for row in ordered_rows:
        segment_id = str(row["segment_id"])
        payload = canonical_by_segment.get(segment_id)
        if payload is None:
            continue
        canonical_text = str(payload.get("canonical_text") or "")
        source_text = str(payload.get("source_text") or row["source_text"] or "")
        if not _has_incomplete_scientific_notation(canonical_text):
            continue
        if not _SCIENTIFIC_NOTATION_CUE_RE.search(source_text) and not _SCIENTIFIC_NOTATION_CUE_RE.search(canonical_text):
            continue
        row_position = position_by_segment_id[segment_id]
        hint_values: set[str] = set()
        for neighbor_position in range(max(0, row_position - 2), min(len(ordered_rows), row_position + 3)):
            if neighbor_position == row_position:
                continue
            neighbor_row = ordered_rows[neighbor_position]
            neighbor_payload = canonical_by_segment.get(str(neighbor_row["segment_id"]), {})
            hint_values.update(
                _extract_exponent_hints(
                    str(neighbor_row["source_text"] or ""),
                    str(neighbor_payload.get("canonical_text") or ""),
                )
            )
        if len(hint_values) != 1:
            continue
        exponent = next(iter(hint_values))
        repaired_text = _repair_incomplete_scientific_notation(canonical_text, exponent=exponent)
        if not repaired_text or _has_incomplete_scientific_notation(repaired_text):
            continue
        payload["canonical_text"] = repaired_text
        payload["unsafe_to_guess"] = False
        payload["risk_flags"] = [
            flag
            for flag in list(payload.get("risk_flags", []))
            if str(flag) not in {"unsafe_to_guess", "ambiguous_term"}
        ]
        payload["slot_pressure"] = _estimated_slot_pressure(
            repaired_text,
            max(0, int(row["end_ms"]) - int(row["start_ms"])),
        )
        changed_segment_ids.append(segment_id)
    return changed_segment_ids
```
-> `src/app/translate/narration_fast_v2.py:367-478`
- Ambiguity flags: idiom_ambiguous, cultural_reference, title_ambiguous, etc.
- Neutral unresolved nouns: prompts suggest short phrases like 'mon do'/'thu do'.
NOT FOUND: dedicated Hán-Việt vs pinyin name transliteration table.
NOT FOUND: explicit 成语 dictionary.

## 6. Budget governor & cost control
```python
class NarrationBudgetPolicy(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    max_llm_cost_usd: float = 0.30
    reserve_ratio: float = 0.15
    soft_stop_ratio: float = 0.85
    entity_micro_cap: int = 12
    ambiguity_micro_cap: int = 10
    slot_rewrite_cap: int = 8
    full_rescue_cap: int = 2
```
-> `src/app/translate/models.py:397-406`
```python
def _budget_allows_soft_escalation(metrics: ContextualRunMetrics, policy: NarrationBudgetPolicy) -> bool:
    if metrics.estimated_cost_usd >= policy.max_llm_cost_usd * policy.soft_stop_ratio:
        metrics.budget_soft_stop_hit = True
        return False
    return True


def _refresh_cost(metrics: ContextualRunMetrics, *, engine: OpenAITranslationEngine, model: str) -> None:
    metrics.estimated_cost_usd = engine.estimate_total_cost_usd(metrics.call_metrics, model=model)
```
-> `src/app/translate/narration_fast_v2.py:481-489`
```python
    policy = NarrationBudgetPolicy(
        entity_micro_cap=min(12, max(1, math.ceil(0.15 * max(1, len(spans))))),
        ambiguity_micro_cap=min(10, max(1, math.ceil(0.12 * max(1, len(spans))))),
        slot_rewrite_cap=min(8, max(1, math.ceil(0.10 * max(1, len(spans))))),
    )
```
-> `src/app/translate/narration_fast_v2.py:1011-1015`
- Caps scale with span count: entity≤12 (15% spans), ambiguity≤10 (12%), slot_rewrite≤8 (10%), full_rescue_cap default 2.
- Soft stop at 85% of max_llm_cost_usd (default 0.30) → no more soft escalations; `budget_soft_stop_hit=True`.
- Cost from token usage * price table / 1e6.
NOT FOUND: separate pre-call token estimator (uses post-call usage only).

## 7. ASR config
```python
from __future__ import annotations

from pathlib import Path

from app.core.jobs import JobContext
from app.core.settings import AppSettings

from .base import ASREngine
from .models import SegmentDraft, TranscriptionOptions, TranscriptionResult, WordTimestamp


class FasterWhisperEngine(ASREngine):
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def transcribe(
        self,
        context: JobContext,
        *,
        audio_path: str,
        options: TranscriptionOptions,
        duration_ms: int | None = None,
    ) -> TranscriptionResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("faster-whisper chua duoc cai dat") from exc

        model = WhisperModel(
            options.model_name,
            device="cuda" if self._settings.gpu_enabled else "cpu",
            compute_type=options.compute_type or ("float16" if self._settings.gpu_enabled else "int8"),
            download_root=self._settings.model_cache_dir,
        )
        context.report_progress(5, "Dang khoi tao faster-whisper")

        segments, info = model.transcribe(
            audio=audio_path,
            language=options.language,
            vad_filter=options.vad_filter,
            word_timestamps=options.word_timestamps,
        )

        draft_segments: list[SegmentDraft] = []
        detected_language = getattr(info, "language", options.language)
        for index, segment in enumerate(segments):
            context.cancellation_token.raise_if_canceled()
            words: list[WordTimestamp] = []
            for word in getattr(segment, "words", []) or []:
                words.append(
                    WordTimestamp(
                        start_ms=int(float(getattr(word, "start", 0.0)) * 1000),
                        end_ms=int(float(getattr(word, "end", 0.0)) * 1000),
                        text=str(getattr(word, "word", "")).strip(),
                        probability=float(getattr(word, "probability", 0.0))
                        if getattr(word, "probability", None) is not None
                        else None,
                    )
                )

            start_ms = int(float(getattr(segment, "start", 0.0)) * 1000)
            end_ms = int(float(getattr(segment, "end", 0.0)) * 1000)
            text = str(getattr(segment, "text", "")).strip()
            draft_segments.append(
                SegmentDraft(
                    segment_index=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_text=text,
                    language=detected_language,
                    words=words,
                )
            )

            if duration_ms:
                progress = min(95, max(10, int((end_ms / max(duration_ms, 1)) * 90)))
                context.report_progress(progress, f"ASR segment {index + 1}")

        context.report_progress(98, "Da xong transcribe, dang persist")
        return TranscriptionResult(
            source_audio_path=Path(audio_path),
            detected_language=detected_language,
            duration_ms=duration_ms,
            segments=draft_segments,
        )


```
-> `src/app/asr/faster_whisper_engine.py:1-86`
- model_name from options (settings.default_asr_model=`small`)
- device cuda if gpu_enabled else cpu
- compute_type float16 if gpu else int8 (unless options override)
- vad_filter default True; word_timestamps default True
NOT FOUND: explicit beam_size, VAD parameter dict, condition_on_previous_text, temperature fallback list, initial_prompt — library defaults only.
Speakers: **no diarization** (KNOWN_LIMITATIONS #1). Speaker IDs come from contextual LLM inference later.
segments DDL: see SCHEMA_SQL `segments` table above.

## 8. TTS + audio
### 8.1 Default voice presets (bootstrap)
```python
    voice_preset = {
        "voice_preset_id": "default-sapi",
        "name": "Windows SAPI Default",
        "engine": "sapi",
        "voice_id": "default",
        "speed": 1.0,
        "volume": 1.0,
        "pitch": 0.0,
        "sample_rate": 22050,
        "notes": "Fallback local offline TTS bang Windows SAPI.",
    }
    vieneu_voice_preset = {
        "voice_preset_id": "vieneu-default-vi",
        "name": "VieNeu Vietnamese",
        "engine": "vieneu",
        "voice_id": "default",
        "speed": 1.0,
        "volume": 1.0,
        "pitch": 0.0,
        "sample_rate": 24000,
        "language": "vi",
        "engine_options": {"mode": "local"},
        "notes": "TTS tieng Viet local bang VieNeu. Can cai package vieneu va eSpeak NG.",
    }
    vieneu_clone_preset = {
        "voice_preset_id": "vieneu-clone-template",
        "name": "VieNeu Voice Clone",
        "engine": "vieneu",
        "voice_id": "default",
        "speed": 1.0,
        "volume": 1.0,
        "pitch": 0.0,
        "sample_rate": 24000,
        "language": "vi",
        "engine_options": {
            "mode": "local",
            "ref_audio_path": "assets/voices/reference.wav",
            "ref_text": "",
        },
        "notes": "Preset clone giong mau. Hay thay ref_audio_path/ref_text bang mau cua ban trong tab Long tieng & Audio.",
    }
```
-> `src/app/project/bootstrap.py:133-173`
### 8.2 TTS clip cache key
```python
def build_tts_stage_hash(
    segments: list[Row],
    preset: VoicePreset,
    *,
    allow_source_fallback: bool = True,
    segment_voice_preset_ids: Mapping[str, str] | None = None,
    segment_voice_presets: Mapping[str, VoicePreset] | None = None,
) -> str:
    def _effective_synthesis_text(row: Row) -> str:
        if allow_source_fallback:
            return (row["tts_text"] or row["subtitle_text"] or row["translated_text"] or row["source_text"] or "").strip()
        return (row["tts_text"] or row["subtitle_text"] or row["translated_text"] or "").strip()

    normalized_segment_voice_preset_ids = {
        str(segment_id): str(preset_id)
        for segment_id, preset_id in (segment_voice_preset_ids or {}).items()
        if str(segment_id).strip() and str(preset_id).strip()
    }
    normalized_segment_voice_presets = {
        str(segment_id): segment_preset.model_dump(mode="json")
        for segment_id, segment_preset in (segment_voice_presets or {}).items()
        if str(segment_id).strip()
    }
    return build_stage_hash(
        {
            "stage": "tts",
            "preset": preset.model_dump(mode="json"),
            "allow_source_fallback": allow_source_fallback,
            "segments": [
                {
                    "segment_id": row["segment_id"],
                    "segment_index": row["segment_index"],
                    "start_ms": row["start_ms"],
                    "end_ms": row["end_ms"],
                    "synthesis_text": _effective_synthesis_text(row),
                    "voice_preset": normalized_segment_voice_presets.get(
                        str(row["segment_id"]),
                        {
                            **preset.model_dump(mode="json"),
                            "voice_preset_id": normalized_segment_voice_preset_ids.get(
                                str(row["segment_id"]),
                                preset.voice_preset_id,
                            ),
                        },
                    ),
                }
                for row in segments
            ],
            "version": 4,
        }
    )


def build_tts_clip_hash(*, text: str, preset: VoicePreset) -> str:
    return build_stage_hash(
        {
            "stage": "tts_clip",
            "text": text,
            "voice_preset": preset.model_dump(mode="json"),
            "version": 1,
        }
    )
```
-> `src/app/tts/base.py:24-85`
Stage hash includes per-segment synthesis_text + full preset dump; clip hash = sha256 of {stage:tts_clip, text, voice_preset, version:1}.
Cache layout: `cache/tts/{stage_hash}/raw/`, `cache/tts/clips/{clip_hash}/clip.wav`.
### 8.3 Speaker→voice binding precedence (documented + code structure)
From KNOWN_LIMITATIONS / tests / speaker_binding.py:
1. Explicit speaker binding wins over voice policy
2. Relationship policy wins over character policy
3. Missing preset in selected policy source **blocks**
4. No matching policy → global preset
5. Style-only policies valid (speed/volume/pitch)
6. Relationship style overrides character style field-by-field
7. Register-aware style only speed/volume/pitch; below rel/char style; skip if needs_human_review or weak confidence
8. unknown_* speakers fall back to global; active bindings + unresolved recognized speaker blocks TTS
Resolver implementation: `src/app/tts/speaker_binding.py` (`SpeakerBindingPlan`, discover_* helpers). Full file ~580 lines — copy as-is.
### 8.4 Voiceover time-fitting
```python
from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.core.hashing import build_stage_hash, fingerprint_path
from app.core.jobs import JobContext
from app.project.models import ProjectWorkspace
from app.tts.models import SynthesizedSegmentArtifact


@dataclass(slots=True)
class VoiceTrackResult:
    stage_hash: str
    cache_dir: Path
    voice_track_path: Path
    manifest_path: Path
    fitted_clips: list[SynthesizedSegmentArtifact] = field(default_factory=list)


DEFAULT_MAX_BATCH_INPUTS = 24


def _slot_duration_ms(artifact: SynthesizedSegmentArtifact) -> int:
    return max(1, artifact.end_ms - artifact.start_ms)


def _build_atempo_filter(speed: float) -> str:
    remaining = speed
    parts: list[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.5f}")
    return ",".join(parts)


def build_fit_filter(clip_duration_ms: int, slot_ms: int) -> str:
    slot_sec = max(0.001, slot_ms / 1000.0)
    if clip_duration_ms <= 0 or clip_duration_ms <= slot_ms:
        return f"aresample=48000,apad=pad_dur={slot_sec:.3f},atrim=end={slot_sec:.3f}"
    speed = clip_duration_ms / slot_ms
    return f"aresample=48000,{_build_atempo_filter(speed)},apad=pad_dur={slot_sec:.3f},atrim=end={slot_sec:.3f}"


def build_voice_track_stage_hash(
    artifacts: list[SynthesizedSegmentArtifact],
    *,
    total_duration_ms: int,
) -> str:
    return build_stage_hash(
        {
            "stage": "voice_track",
            "total_duration_ms": total_duration_ms,
            "artifacts": [
                {
                    "segment_id": item.segment_id,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "raw_wav_path": fingerprint_path(item.raw_wav_path),
                    "duration_ms": item.duration_ms,
                }
                for item in artifacts
            ],
            "version": 1,
        }
    )


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "FFmpeg that bai").strip())


def _build_aligned_mix_command(
    *,
    ffmpeg_executable: str,
    output_path: Path,
    total_duration_ms: int,
    artifacts: list[SynthesizedSegmentArtifact],
) -> list[str]:
    inputs = [
        ffmpeg_executable,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=48000:cl=stereo:d={max(0.001, total_duration_ms / 1000.0):.3f}",
    ]
    filter_parts: list[str] = []
    mix_inputs = ["[0:a]"]
    for input_index, artifact in enumerate(artifacts, start=1):
        if not artifact.fitted_wav_path:
            continue
        inputs.extend(["-i", str(artifact.fitted_wav_path)])
        filter_parts.append(
            f"[{input_index}:a]adelay={artifact.start_ms}|{artifact.start_ms}[v{input_index}]"
        )
        mix_inputs.append(f"[v{input_index}]")

    if len(mix_inputs) == 1:
        filter_parts.append("[0:a]anull[out]")
    else:
        filter_parts.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0[out]")

    inputs.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            "48000",
            str(output_path),
        ]
    )
    return inputs


def _build_mix_tracks_command(
    *,
    ffmpeg_executable: str,
    output_path: Path,
    input_paths: list[Path],
) -> list[str]:
    command = [ffmpeg_executable, "-y"]
    filter_parts: list[str] = []
    mix_inputs: list[str] = []
    for input_index, input_path in enumerate(input_paths):
        command.extend(["-i", str(input_path)])
        filter_parts.append(f"[{input_index}:a]aresample=48000[m{input_index}]")
        mix_inputs.append(f"[m{input_index}]")

    if not mix_inputs:
        raise ValueError("Khong co input nao de mix")
    if len(mix_inputs) == 1:
        filter_parts.append(f"{mix_inputs[0]}anull[out]")
    else:
        filter_parts.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0[out]")

    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            "48000",
            str(output_path),
        ]
    )
    return command


def _render_voice_track_batches(
    context: JobContext,
    *,
    ffmpeg_executable: str,
    cache_dir: Path,
    voice_track_path: Path,
    total_duration_ms: int,
    fitted_artifacts: list[SynthesizedSegmentArtifact],
    max_batch_inputs: int,
) -> None:
    if max_batch_inputs < 1:
        raise ValueError("max_batch_inputs phai lon hon 0")
    if not fitted_artifacts:
        _run_ffmpeg(
            [
                ffmpeg_executable,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=48000:cl=stereo:d={max(0.001, total_duration_ms / 1000.0):.3f}",
                "-ac",
                "2",
                "-ar",
                "48000",
                str(voice_track_path),
            ]
        )
        return

    if len(fitted_artifacts) <= max_batch_inputs:
        _run_ffmpeg(
            _build_aligned_mix_command(
                ffmpeg_executable=ffmpeg_executable,
                output_path=voice_track_path,
                total_duration_ms=total_duration_ms,
                artifacts=fitted_artifacts,
            )
        )
        return

    partial_dir = cache_dir / "partials"
    partial_dir.mkdir(parents=True, exist_ok=True)
    total_batches = math.ceil(len(fitted_artifacts) / max_batch_inputs)
    current_paths: list[Path] = []

    for batch_index, start in enumerate(range(0, len(fitted_artifacts), max_batch_inputs), start=1):
        batch = fitted_artifacts[start : start + max_batch_inputs]
        partial_path = partial_dir / f"aligned_batch_{batch_index:03d}.wav"
        if not partial_path.exists():
            _run_ffmpeg(
                _build_aligned_mix_command(
                    ffmpeg_executable=ffmpeg_executable,
                    output_path=partial_path,
                    total_duration_ms=total_duration_ms,
                    artifacts=batch,
                )
            )
        current_paths.append(partial_path)
        progress = 80 + int(batch_index * 10 / max(1, total_batches))
        context.report_progress(min(90, progress), f"Mix batch {batch_index}/{total_batches}")

    level = 0
    while len(current_paths) > 1:
        next_paths: list[Path] = []
        total_mix_batches = math.ceil(len(current_paths) / max_batch_inputs)
        for batch_index, start in enumerate(range(0, len(current_paths), max_batch_inputs), start=1):
            batch_paths = current_paths[start : start + max_batch_inputs]
            if len(batch_paths) == 1:
                next_paths.append(batch_paths[0])
                continue
            merged_path = partial_dir / f"mix_level_{level:02d}_{batch_index:03d}.wav"
            if not merged_path.exists():
                _run_ffmpeg(
                    _build_mix_tracks_command(
                        ffmpeg_executable=ffmpeg_executable,
                        output_path=merged_path,
                        input_paths=batch_paths,
                    )
                )
            next_paths.append(merged_path)
            progress = 90 + int(batch_index * 9 / max(1, total_mix_batches))
            context.report_progress(min(99, progress), f"Gop batch {batch_index}/{total_mix_batches}")
        current_paths = next_paths
        level += 1

    final_path = current_paths[0]
    if final_path != voice_track_path:
        shutil.copyfile(final_path, voice_track_path)


def build_voice_track(
    context: JobContext,
    *,
    workspace: ProjectWorkspace,
    artifacts: list[SynthesizedSegmentArtifact],
    ffmpeg_path: str | None,
    total_duration_ms: int,
    max_batch_inputs: int = DEFAULT_MAX_BATCH_INPUTS,
) -> VoiceTrackResult:
    ffmpeg_executable = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg_executable:
        raise RuntimeError("Khong tim thay ffmpeg.exe")

    stage_hash = build_voice_track_stage_hash(artifacts, total_duration_ms=total_duration_ms)
    cache_dir = workspace.cache_dir / "mix" / stage_hash
    fitted_dir = cache_dir / "fitted"
    fitted_dir.mkdir(parents=True, exist_ok=True)
    voice_track_path = cache_dir / "voice_track.wav"
    manifest_path = cache_dir / "voice_track_manifest.json"
    if manifest_path.exists() and voice_track_path.exists():
        context.report_progress(100, "Dung cache voice track")
        return VoiceTrackResult(
            stage_hash=stage_hash,
            cache_dir=cache_dir,
            voice_track_path=voice_track_path,
            manifest_path=manifest_path,
            fitted_clips=artifacts,
        )

    fitted_artifacts: list[SynthesizedSegmentArtifact] = []
    total = max(1, len(artifacts))
    for index, artifact in enumerate(artifacts, start=1):
        slot_ms = _slot_duration_ms(artifact)
        fitted_path = fitted_dir / f"{artifact.segment_index:04d}_{artifact.segment_id}.wav"
        if not fitted_path.exists():
            filter_expr = build_fit_filter(artifact.duration_ms, slot_ms)
            _run_ffmpeg(
                [
                    ffmpeg_executable,
                    "-y",
                    "-i",
                    str(artifact.raw_wav_path),
                    "-filter:a",
                    filter_expr,
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    str(fitted_path),
                ]
            )
        fitted_artifacts.append(
            SynthesizedSegmentArtifact(
                segment_id=artifact.segment_id,
                segment_index=artifact.segment_index,
                start_ms=artifact.start_ms,
                end_ms=artifact.end_ms,
                text=artifact.text,
                raw_wav_path=artifact.raw_wav_path,
                duration_ms=artifact.duration_ms,
                sample_rate=artifact.sample_rate,
                voice_id=artifact.voice_id,
                voice_preset_id=artifact.voice_preset_id,
                speaker_key=artifact.speaker_key,
                fitted_wav_path=fitted_path,
                fitted_duration_ms=slot_ms,
            )
        )
        context.report_progress(min(80, int(index * 80 / total)), f"Fit clip {index}/{total}")

    _render_voice_track_batches(
        context,
        ffmpeg_executable=ffmpeg_executable,
        cache_dir=cache_dir,
        voice_track_path=voice_track_path,
        total_duration_ms=total_duration_ms,
        fitted_artifacts=fitted_artifacts,
        max_batch_inputs=max_batch_inputs,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "stage_hash": stage_hash,
                "voice_track_path": str(voice_track_path),
                "total_duration_ms": total_duration_ms,
                "fitted_clips": [
                    {
                        "segment_id": item.segment_id,
                        "segment_index": item.segment_index,
                        "start_ms": item.start_ms,
                        "end_ms": item.end_ms,
                        "raw_wav_path": str(item.raw_wav_path),
                        "fitted_wav_path": str(item.fitted_wav_path) if item.fitted_wav_path else None,
                        "fitted_duration_ms": item.fitted_duration_ms,
                    }
                    for item in fitted_artifacts
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context.report_progress(100, "Da tao voice track")
    return VoiceTrackResult(
        stage_hash=stage_hash,
        cache_dir=cache_dir,
        voice_track_path=voice_track_path,
        manifest_path=manifest_path,
        fitted_clips=fitted_artifacts,
    )

```
-> `src/app/audio/voiceover_track.py:1-377`
Logic: if clip ≤ slot → pad + atrim; if longer → atempo speed-up (chain of 0.5..2.0 factors) then pad/trim. adelay by start_ms. amix normalize=0. Sample rate 48000 stereo. Batch max inputs 24.
NOT FOUND: crossfade constants; no ducking sidechain in voice track (only mix levels).
### 8.5 Mixdown
```python
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.hashing import build_stage_hash, fingerprint_path
from app.core.jobs import JobContext
from app.project.models import ProjectWorkspace


@dataclass(slots=True)
class MixdownResult:
    stage_hash: str
    cache_dir: Path
    mixed_audio_path: Path
    manifest_path: Path


def build_mixdown_stage_hash(
    *,
    original_audio_path: Path,
    voice_track_path: Path,
    original_volume: float,
    voice_volume: float,
    bgm_path: Path | None,
    bgm_volume: float,
) -> str:
    return build_stage_hash(
        {
            "stage": "mixdown",
            "original_audio_path": fingerprint_path(original_audio_path),
            "voice_track_path": fingerprint_path(voice_track_path),
            "original_volume": original_volume,
            "voice_volume": voice_volume,
            "bgm_path": fingerprint_path(bgm_path) if bgm_path and bgm_path.exists() else None,
            "bgm_volume": bgm_volume,
            "version": 1,
        }
    )


def build_mixdown_command(
    *,
    ffmpeg_executable: str,
    original_audio_path: Path,
    voice_track_path: Path,
    output_path: Path,
    original_volume: float,
    voice_volume: float,
    bgm_path: Path | None = None,
    bgm_volume: float = 0.2,
) -> list[str]:
    command = [
        ffmpeg_executable,
        "-y",
        "-i",
        str(original_audio_path),
        "-i",
        str(voice_track_path),
    ]
    input_count = 2
    if bgm_path is not None:
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        input_count += 1

    filter_parts = [
        f"[0:a]aresample=48000,volume={original_volume:.3f}[orig]",
        f"[1:a]aresample=48000,volume={voice_volume:.3f}[voice]",
    ]
    mix_inputs = ["[orig]", "[voice]"]
    if bgm_path is not None:
        filter_parts.append(f"[2:a]aresample=48000,volume={bgm_volume:.3f}[bgm]")
        mix_inputs.append("[bgm]")
    filter_parts.append(
        "".join(mix_inputs) + f"amix=inputs={input_count}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            "48000",
            str(output_path),
        ]
    )
    return command


def mix_audio_tracks(
    context: JobContext,
    *,
    workspace: ProjectWorkspace,
    original_audio_path: Path,
    voice_track_path: Path,
    ffmpeg_path: str | None,
    original_volume: float,
    voice_volume: float,
    bgm_path: Path | None = None,
    bgm_volume: float = 0.2,
) -> MixdownResult:
    ffmpeg_executable = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg_executable:
        raise RuntimeError("Khong tim thay ffmpeg.exe")

    stage_hash = build_mixdown_stage_hash(
        original_audio_path=original_audio_path,
        voice_track_path=voice_track_path,
        original_volume=original_volume,
        voice_volume=voice_volume,
        bgm_path=bgm_path,
        bgm_volume=bgm_volume,
    )
    cache_dir = workspace.cache_dir / "mix" / stage_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    mixed_audio_path = cache_dir / "mixed_audio.wav"
    manifest_path = cache_dir / "mix_manifest.json"
    if manifest_path.exists() and mixed_audio_path.exists():
        context.report_progress(100, "Dung cache mixed audio")
        return MixdownResult(stage_hash=stage_hash, cache_dir=cache_dir, mixed_audio_path=mixed_audio_path, manifest_path=manifest_path)

    command = build_mixdown_command(
        ffmpeg_executable=ffmpeg_executable,
        original_audio_path=original_audio_path,
        voice_track_path=voice_track_path,
        output_path=mixed_audio_path,
        original_volume=original_volume,
        voice_volume=voice_volume,
        bgm_path=bgm_path,
        bgm_volume=bgm_volume,
    )
    context.report_progress(20, "Dang mix voice + audio goc")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Mixdown that bai").strip())

    manifest_path.write_text(
        json.dumps(
            {
                "stage_hash": stage_hash,
                "original_audio_path": str(original_audio_path),
                "voice_track_path": str(voice_track_path),
                "bgm_path": str(bgm_path) if bgm_path else None,
                "original_volume": original_volume,
                "voice_volume": voice_volume,
                "bgm_volume": bgm_volume,
                "mixed_audio_path": str(mixed_audio_path),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context.report_progress(100, "Da tao mixed audio")
    return MixdownResult(stage_hash=stage_hash, cache_dir=cache_dir, mixed_audio_path=mixed_audio_path, manifest_path=manifest_path)

```
-> `src/app/audio/mixdown.py:1-170`
Filter: `[0:a]aresample=48000,volume={original_volume}[orig]`; voice volume; optional bgm volume default 0.2; `amix ... normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11`.
Profile recommended original_volume=0.07, voice_volume=1.0, BGM=0.0 in simple mode.
NOT FOUND: sidechaincompress / ducking params.

## 9. Subtitle rendering
### Default ASS style (bootstrap)
```python
    style_preset = {
        "style_preset_id": "default-ass",
        "name": "Mac dinh ASS",
        "description": "Outline dam, phu hop hard-sub co ban",
        "ass_style_json": {
            "FontName": "Arial",
            "FontSize": 42,
            "Outline": 2,
            "Shadow": 0,
            "Alignment": 2,
            "MarginV": 48,
        },
    }
```
-> `src/app/project/bootstrap.py:120-132`
Profile override for narration: FontSize 12 (not 42).
Subtext gốc rendering:
```python
def _render_ass_with_source_subtext(primary_text: str, source_text: str, *, base_font_size: int) -> str:
    if not source_text.strip():
        return primary_text
    subtext_font_size = max(10, int(round(base_font_size * 0.75)))
    subtext_override = f"{{\\fs{subtext_font_size}\\1a&H55&\\3a&H55&}}"
    return f"{primary_text}\\N{subtext_override}{source_text}"


def _segment_render_text(
    row: Row,
    *,
    ass: bool,
    allow_source_fallback: bool,
    subtitle_subtext_mode: str,
    base_font_size: int,
) -> str:
    primary_text = _segment_subtitle_text(row, allow_source_fallback=allow_source_fallback)
    source_text = str(row["source_text"] or "").strip()
    normalized_subtext_mode = normalize_subtitle_subtext_mode(subtitle_subtext_mode)
    if ass:
        primary_text = primary_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")
        source_text = source_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")
        if normalized_subtext_mode == "source_text" and source_text:
            return _render_ass_with_source_subtext(primary_text, source_text, base_font_size=base_font_size)
        return primary_text
    if normalized_subtext_mode == "source_text" and source_text:
        return f"{primary_text}\n{source_text}" if primary_text else source_text
    return primary_text
```
-> `src/app/subtitle/export.py:75-102`
subtext_font_size = max(10, round(base*0.75)); alpha H55 on primary colors.
### Hardsub burn-in + Windows path escape
```python
def escape_ffmpeg_filter_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return (
        value.replace(":", r"\:")
        .replace("'", r"\'")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(",", r"\,")
    )
```
-> `src/app/subtitle/hardsub.py:130-138`
```python
def build_video_filter_graph(
    *,
    subtitle_path: Path,
    export_preset: ExportPreset,
    watermark_input_index: int | None = None,
) -> tuple[str, str]:
    current_label = "[0:v]"
    filters: list[str] = []
    step_index = 0

    resolution_filter = _resolution_filter(export_preset)
    if resolution_filter:
        next_label = f"[v{step_index}]"
        filters.append(f"{current_label}{resolution_filter}{next_label}")
        current_label = next_label
        step_index += 1

    if export_preset.burn_subtitles:
        next_label = f"[v{step_index}]"
        filters.append(f"{current_label}ass='{escape_ffmpeg_filter_path(subtitle_path)}'{next_label}")
        current_label = next_label
        step_index += 1

    if export_preset.watermark_enabled and watermark_input_index is not None:
        rgba_label = f"[wmrgba{step_index}]"
        wm_label = f"[wm{step_index}]"
        base_label = f"[base{step_index}]"
        filters.append(
            f"[{watermark_input_index}:v]format=rgba,colorchannelmixer=aa={export_preset.watermark_opacity:.3f}{rgba_label}"
        )
        filters.append(
            f"{rgba_label}{current_label}scale2ref=w=main_w*{export_preset.watermark_scale:.4f}:h=ow/mdar{wm_label}{base_label}"
        )
        overlay_x, overlay_y = _overlay_position_expr(
            export_preset.watermark_position,
            export_preset.watermark_margin,
        )
        next_label = "[vout]"
        filters.append(f"{base_label}{wm_label}overlay={overlay_x}:{overlay_y}{next_label}")
        current_label = next_label

    if current_label != "[vout]":
        filters.append(f"{current_label}null[vout]")
    return ";".join(filters), "[vout]"


def build_hardsub_command(
    *,
    ffmpeg_executable: str,
    source_video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    export_preset: ExportPreset,
    replacement_audio_path: Path | None = None,
    watermark_path: Path | None = None,
) -> list[str]:
    effective_preset = export_preset.model_copy(
        update={"watermark_enabled": export_preset.watermark_enabled or watermark_path is not None}
    )
    video_codec = VIDEO_CODEC_MAP.get(effective_preset.video_codec.lower(), "libx264")
    audio_codec = AUDIO_CODEC_MAP.get(effective_preset.audio_codec.lower(), "aac")
    subtitle_codec = SUBTITLE_CODEC_BY_CONTAINER.get(effective_preset.container.lower(), "srt")
    command = [
        ffmpeg_executable,
        "-y",
        "-i",
        str(source_video_path),
    ]
    next_input_index = 1
    audio_map_label = "0:a?"
    if replacement_audio_path is not None:
        command.extend(
            [
                "-i",
                str(replacement_audio_path),
            ]
        )
        audio_map_label = f"{next_input_index}:a:0"
        next_input_index += 1
    subtitle_input_index: int | None = None
    if not effective_preset.burn_subtitles:
        subtitle_input_index = next_input_index
        command.extend(["-i", str(subtitle_path)])
        next_input_index += 1
    watermark_input_index: int | None = None
    if watermark_path is not None:
        watermark_input_index = next_input_index
        command.extend(["-i", str(watermark_path)])
    video_filter_graph, output_label = build_video_filter_graph(
        subtitle_path=subtitle_path,
        export_preset=effective_preset,
        watermark_input_index=watermark_input_index,
    )
    command.extend(["-filter_complex", video_filter_graph, "-map", output_label])
    command.extend(["-map", audio_map_label])
    if subtitle_input_index is not None:
        command.extend(["-map", f"{subtitle_input_index}:0"])
    command.extend(["-c:v", video_codec])
    if video_codec != "copy":
        command.extend(["-preset", "medium", "-crf", str(effective_preset.crf)])
    command.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", audio_codec])
    if audio_codec != "copy":
        command.extend(["-b:a", "192k"])
    if subtitle_input_index is not None:
        command.extend(["-c:s", subtitle_codec])
    command.extend(["-progress", "pipe:1", "-nostats", str(output_path)])
    return command
```
-> `src/app/subtitle/hardsub.py:192-298`
ASS filter: `ass='{escaped_path}'` after resolve path with `\`→`/`, escape `: ' [ ] ,`.
Video: libx264 medium crf from preset, pix_fmt yuv420p, movflags +faststart, audio aac 192k.
### Subtitle QC constants
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True, frozen=True)
class SubtitleQcIssue:
    segment_id: str
    segment_index: int
    code: str
    severity: str
    message: str
    cps: float | None = None
    cpl: int | None = None


@dataclass(slots=True, frozen=True)
class SubtitleQcConfig:
    max_lines: int = 2
    max_cpl: int = 42
    max_cps: float = 18.0
    min_duration_ms: int = 800
    max_duration_ms: int = 7000


@dataclass(slots=True, frozen=True)
class SubtitleQcReport:
    total_segments: int
    issues: list[SubtitleQcIssue]

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def ok_count(self) -> int:
        return max(0, self.total_segments - len({issue.segment_id for issue in self.issues}))


def _normalized_subtitle_text(row: dict[str, object]) -> str:
    subtitle_text = str(row.get("subtitle_text", "") or "").strip()
    translated_text = str(row.get("translated_text", "") or "").strip()
    source_text = str(row.get("source_text", "") or "").strip()
    return subtitle_text or translated_text or source_text


def _count_visible_characters(text: str) -> int:
    return len(text.replace("\r", "").replace("\n", ""))


def _max_line_length(text: str) -> int:
    return max((len(line) for line in text.splitlines()), default=0)


def _line_count(text: str) -> int:
    return max(1, len(text.splitlines())) if text else 0


def analyze_subtitle_rows(
    rows: Iterable[dict[str, object]],
    *,
    config: SubtitleQcConfig | None = None,
) -> SubtitleQcReport:
    cfg = config or SubtitleQcConfig()
    normalized_rows = list(rows)
    issues: list[SubtitleQcIssue] = []
    previous_end_ms: int | None = None

    for row in normalized_rows:
        segment_id = str(row["segment_id"])
        segment_index = int(row["segment_index"])
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        explicit_text = str(row.get("subtitle_text", "") or "").strip() or str(
            row.get("translated_text", "") or ""
        ).strip()
        text = explicit_text or _normalized_subtitle_text(row)
        duration_ms = end_ms - start_ms
        cps = (_count_visible_characters(text) / (duration_ms / 1000.0)) if duration_ms > 0 and text else 0.0
        cpl = _max_line_length(text)
        line_count = _line_count(text)

        if previous_end_ms is not None and start_ms < previous_end_ms:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="overlap",
                    severity="error",
                    message="Segment bi overlap voi segment truoc",
                )
            )
        previous_end_ms = end_ms

        if duration_ms <= 0:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="invalid_duration",
                    severity="error",
                    message="Duration phai lon hon 0",
                )
            )
            continue

        if not explicit_text:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="empty_text",
                    severity="warning",
                    message="Subtitle text dang rong",
                )
            )

        if duration_ms < cfg.min_duration_ms:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="short_duration",
                    severity="warning",
                    message=f"Duration ngan hon {cfg.min_duration_ms} ms",
                )
            )

        if duration_ms > cfg.max_duration_ms:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="long_duration",
                    severity="warning",
                    message=f"Duration dai hon {cfg.max_duration_ms} ms",
                )
            )

        if line_count > cfg.max_lines:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="too_many_lines",
                    severity="warning",
                    message=f"So dong vuot qua {cfg.max_lines}",
                    cpl=cpl,
                )
            )

        if cpl > cfg.max_cpl:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="high_cpl",
                    severity="warning",
                    message=f"CPL vuot qua {cfg.max_cpl}",
                    cpl=cpl,
                )
            )

        if cps > cfg.max_cps:
            issues.append(
                SubtitleQcIssue(
                    segment_id=segment_id,
                    segment_index=segment_index,
                    code="high_cps",
                    severity="warning",
                    message=f"CPS vuot qua {cfg.max_cps:.1f}",
                    cps=round(cps, 2),
                    cpl=cpl,
                )
            )

    return SubtitleQcReport(total_segments=len(normalized_rows), issues=issues)

```
-> `src/app/subtitle/qc.py:1-182`
max_lines=2, max_cpl=42, max_cps=18.0, min_duration_ms=800, max_duration_ms=7000; overlap is **error** (start < previous_end).

## 10. Project profiles
Profiles are code defaults written to `presets/project_profiles/*.json`:
```python
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.project.database import ProjectDatabase
from app.tts.presets import list_voice_presets, save_voice_preset


class ProjectProfile(BaseModel):
    project_profile_id: str
    name: str
    description: str = ""
    source_language: str | None = None
    target_language: str | None = None
    translation_mode: str | None = None
    recommended_prompt_template_id: str | None = None
    active_voice_preset_id: str | None = None
    active_export_preset_id: str | None = None
    active_watermark_profile_id: str | None = None
    recommended_original_volume: float | None = None
    recommended_voice_volume: float | None = None
    voice_preset_overrides: dict[str, dict[str, object]] = Field(default_factory=dict)
    style_preset_overrides: dict[str, dict[str, object]] = Field(default_factory=dict)
    notes: str = ""


class ProjectProfileState(BaseModel):
    project_profile_id: str
    name: str
    applied_at: str
    recommended_prompt_template_id: str | None = None
    active_voice_preset_id: str | None = None
    active_export_preset_id: str | None = None
    active_watermark_profile_id: str | None = None
    recommended_original_volume: float | None = None
    recommended_voice_volume: float | None = None
    subtitle_subtext_mode: str = "off"


VALID_SUBTITLE_SUBTEXT_MODES = {"off", "source_text"}


def get_project_profiles_dir(project_root: Path) -> Path:
    return project_root / "presets" / "project_profiles"


def get_project_profile_state_path(project_root: Path) -> Path:
    return project_root / ".ops" / "project_profile_state.json"


def _default_project_profiles() -> list[ProjectProfile]:
    return [
        ProjectProfile(
            project_profile_id="zh-vi-narration-clear-vieneu",
            name="Narration Clear VieNeu",
            description=(
                "Preset zh->vi cho video thuyet minh/kham pha: VieNeu cham nhe, "
                "chu 12, giam nen goc de de nghe."
            ),
            source_language="zh",
            target_language="vi",
            translation_mode="contextual_v2",
            recommended_prompt_template_id="contextual_default_adaptation",
            active_voice_preset_id="vieneu-default-vi",
            active_export_preset_id="youtube-16x9",
            active_watermark_profile_id="watermark-none",
            recommended_original_volume=0.07,
            recommended_voice_volume=1.0,
            voice_preset_overrides={
                "vieneu-default-vi": {
                    "speed": 0.93,
                    "volume": 1.0,
                    "pitch": 0.0,
                    "sample_rate": 24000,
                    "language": "vi",
                    "notes": (
                        "VieNeu cham nhe cho video narration zh->vi, uu tien ro y "
                        "va giam cam giac doc voi."
                    ),
                }
            },
            style_preset_overrides={
                "default-ass": {
                    "FontSize": 12,
                    "Outline": 2,
                    "Shadow": 0,
                    "Alignment": 2,
                    "MarginV": 48,
                }
            },
            notes=(
                "Mau duoc rut ra tu cac video khoa hoc/kham pha/narration dai. "
                "Nen giu cau gon, trung tinh, de nghe va uu tien fit/slot an toan."
            ),
        ),
        ProjectProfile(
            project_profile_id="zh-vi-narration-fast-vieneu",
            name="Narration Fast VieNeu",
            description=(
                "Preset zh->vi cho video thuyet minh dai: giu giong/ASS giong profile narration "
                "clear, nhung uu tien fast path voi planner noi bo, batch lon hon va context nhe hon."
            ),
            source_language="zh",
            target_language="vi",
            translation_mode="contextual_v2",
            recommended_prompt_template_id="contextual_narration_fast_adaptation",
            active_voice_preset_id="vieneu-default-vi",
            active_export_preset_id="youtube-16x9",
            active_watermark_profile_id="watermark-none",
            recommended_original_volume=0.07,
            recommended_voice_volume=1.0,
            voice_preset_overrides={
                "vieneu-default-vi": {
                    "speed": 0.93,
                    "volume": 1.0,
                    "pitch": 0.0,
                    "sample_rate": 24000,
                    "language": "vi",
                    "notes": (
                        "VieNeu cham nhe cho fast-path narration zh->vi, uu tien doc ro y "
                        "va khong qua voi."
                    ),
                }
            },
            style_preset_overrides={
                "default-ass": {
                    "FontSize": 12,
                    "Outline": 2,
                    "Shadow": 0,
                    "Alignment": 2,
                    "MarginV": 48,
                }
            },
            notes=(
                "Fast path dung cho video khoa hoc/kham pha/hoang da it doi thoai. "
                "Uu tien narration trung tinh, giam token/call va giam review gia do memory dialogue."
            ),
        ),
        ProjectProfile(
            project_profile_id="zh-vi-narration-fast-v2-vieneu",
            name="Narration Fast V2 VieNeu",
            description=(
                "Preset zh->vi cho video thuyet minh dai: span-based, canonical-only narration, "
                "subtext mac dinh tat, sparse escalation va budget governor."
            ),
            source_language="zh",
            target_language="vi",
            translation_mode="contextual_v2",
            recommended_prompt_template_id="contextual_narration_slot_rewrite",
            active_voice_preset_id="vieneu-default-vi",
            active_export_preset_id="youtube-16x9",
            active_watermark_profile_id="watermark-none",
            recommended_original_volume=0.07,
            recommended_voice_volume=1.0,
            voice_preset_overrides={
                "vieneu-default-vi": {
                    "speed": 0.93,
                    "volume": 1.0,
                    "pitch": 0.0,
                    "sample_rate": 24000,
                    "language": "vi",
                    "notes": (
                        "VieNeu cham nhe cho narration fast v2 zh->vi, uu tien de nghe "
                        "va giam can goi adaptation LLM."
                    ),
                }
            },
            style_preset_overrides={
                "default-ass": {
                    "FontSize": 12,
                    "Outline": 2,
                    "Shadow": 0,
                    "Alignment": 2,
                    "MarginV": 48,
                }
            },
            notes=(
                "Narration Fast Path v2: span-based, canonical_text only, sparse escalation, "
                "term memory, budget governor <= 0.30 USD va subtext goc mac dinh tat."
            ),
        ),
    ]


def default_project_profiles() -> list[ProjectProfile]:
    return [profile.model_copy(deep=True) for profile in _default_project_profiles()]


def ensure_project_profiles(project_root: Path) -> list[Path]:
    profiles_dir = get_project_profiles_dir(project_root)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    existing_ids = {path.stem for path in profiles_dir.glob("*.json")}
    for profile in default_project_profiles():
        path = profiles_dir / f"{profile.project_profile_id}.json"
        if profile.project_profile_id in existing_ids and path.exists():
            continue
        path.write_text(
            json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        written_paths.append(path)
    return written_paths


def list_project_profiles(project_root: Path) -> list[ProjectProfile]:
    profiles_dir = get_project_profiles_dir(project_root)
    if not profiles_dir.exists():
        return []
    profiles: list[ProjectProfile] = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            profiles.append(ProjectProfile.model_validate(payload))
        except Exception:
            continue
    return profiles


def load_project_profile(project_root: Path, project_profile_id: str) -> ProjectProfile:
    for profile in list_project_profiles(project_root):
        if profile.project_profile_id == project_profile_id:
            return profile
    raise FileNotFoundError(f"Khong tim thay project profile: {project_profile_id}")


def load_project_profile_state(project_root: Path) -> ProjectProfileState | None:
    state_path = get_project_profile_state_path(project_root)
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["subtitle_subtext_mode"] = normalize_subtitle_subtext_mode(
            payload.get("subtitle_subtext_mode")
        )
        return ProjectProfileState.model_validate(payload)
    except Exception:
        return None


def normalize_subtitle_subtext_mode(value: object) -> str:
    raw_value = str(value or "off").strip().lower()
    if raw_value not in VALID_SUBTITLE_SUBTEXT_MODES:
        return "off"
    return raw_value


def save_project_profile_state(project_root: Path, state: ProjectProfileState) -> ProjectProfileState:
    normalized_state = state.model_copy(
        update={"subtitle_subtext_mode": normalize_subtitle_subtext_mode(state.subtitle_subtext_mode)}
    )
    state_path = get_project_profile_state_path(project_root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(normalized_state.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return normalized_state


def ensure_project_profile_state(
    project_root: Path,
    *,
    project_profile_id: str | None = None,
    name: str | None = None,
    applied_at: str | None = None,
) -> ProjectProfileState:
    existing_state = load_project_profile_state(project_root)
    if existing_state is not None:
        return save_project_profile_state(project_root, existing_state)
    resolved_profile_id = project_profile_id or "manual"
    resolved_name = name or resolved_profile_id
    state = ProjectProfileState(
        project_profile_id=resolved_profile_id,
        name=resolved_name,
        applied_at=applied_at or "",
        subtitle_subtext_mode="off",
    )
    return save_project_profile_state(project_root, state)


def set_project_subtitle_subtext_mode(project_root: Path, mode: str, *, applied_at: str = "") -> ProjectProfileState:
    state = ensure_project_profile_state(project_root, applied_at=applied_at)
    updated_state = state.model_copy(
        update={
            "subtitle_subtext_mode": normalize_subtitle_subtext_mode(mode),
            "applied_at": applied_at or state.applied_at,
        }
    )
    return save_project_profile_state(project_root, updated_state)


def resolve_subtitle_subtext_mode(project_root: Path) -> str:
    state = load_project_profile_state(project_root)
    if state is None:
        return "off"
    return normalize_subtitle_subtext_mode(state.subtitle_subtext_mode)


def resolve_project_profile_mix_defaults(
    project_root: Path,
    *,
    original_volume: float | None,
    voice_volume: float | None,
) -> tuple[float, float, ProjectProfileState | None]:
    state = load_project_profile_state(project_root)
    resolved_original_volume = original_volume
    resolved_voice_volume = voice_volume
    if state is not None:
        if resolved_original_volume is None:
            resolved_original_volume = state.recommended_original_volume
        if resolved_voice_volume is None:
            resolved_voice_volume = state.recommended_voice_volume
    if resolved_original_volume is None:
        resolved_original_volume = 0.35
    if resolved_voice_volume is None:
        resolved_voice_volume = 1.0
    return resolved_original_volume, resolved_voice_volume, state


def _find_style_preset_path(project_root: Path, style_preset_id: str) -> Path | None:
    styles_dir = project_root / "presets" / "styles"
    if not styles_dir.exists():
        return None
    for path in sorted(styles_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("style_preset_id") == style_preset_id:
            return path
    return None


def _apply_voice_preset_overrides(project_root: Path, profile: ProjectProfile) -> None:
    presets_by_id = {preset.voice_preset_id: preset for preset in list_voice_presets(project_root)}
    for preset_id, overrides in profile.voice_preset_overrides.items():
        base_preset = presets_by_id.get(preset_id)
        if base_preset is None:
            raise FileNotFoundError(f"Khong tim thay voice preset de apply profile: {preset_id}")
        update_payload = dict(overrides)
        engine_options_override = update_payload.pop("engine_options", None)
        if isinstance(engine_options_override, dict):
            update_payload["engine_options"] = {
                **dict(base_preset.engine_options),
                **engine_options_override,
            }
        save_voice_preset(project_root, base_preset.model_copy(update=update_payload))


def _apply_style_preset_overrides(project_root: Path, profile: ProjectProfile) -> None:
    for style_preset_id, overrides in profile.style_preset_overrides.items():
        path = _find_style_preset_path(project_root, style_preset_id)
        if path is None:
            raise FileNotFoundError(f"Khong tim thay style preset de apply profile: {style_preset_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        ass_style = dict(payload.get("ass_style_json") or {})
        ass_style.update(overrides)
        payload["ass_style_json"] = ass_style
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_project_profile(
    project_root: Path,
    *,
    project_id: str,
    database: ProjectDatabase,
    project_profile_id: str,
    applied_at: str,
) -> ProjectProfileState:
    profile = load_project_profile(project_root, project_profile_id)
    existing_state = load_project_profile_state(project_root)
    _apply_voice_preset_overrides(project_root, profile)
    _apply_style_preset_overrides(project_root, profile)

    if profile.translation_mode:
        database.set_translation_mode(project_id, profile.translation_mode, updated_at=applied_at)
    if profile.active_voice_preset_id is not None:
        database.set_active_voice_preset_id(
            project_id,
            profile.active_voice_preset_id,
            updated_at=applied_at,
        )
    if profile.active_export_preset_id is not None:
        database.set_active_export_preset_id(
            project_id,
            profile.active_export_preset_id,
            updated_at=applied_at,
        )
    if profile.active_watermark_profile_id is not None:
        database.set_active_watermark_profile_id(
            project_id,
            profile.active_watermark_profile_id,
            updated_at=applied_at,
        )

    state = ProjectProfileState(
        project_profile_id=profile.project_profile_id,
        name=profile.name,
        applied_at=applied_at,
        recommended_prompt_template_id=profile.recommended_prompt_template_id,
        active_voice_preset_id=profile.active_voice_preset_id,
        active_export_preset_id=profile.active_export_preset_id,
        active_watermark_profile_id=profile.active_watermark_profile_id,
        recommended_original_volume=profile.recommended_original_volume,
        recommended_voice_volume=profile.recommended_voice_volume,
        subtitle_subtext_mode=(
            existing_state.subtitle_subtext_mode
            if existing_state is not None
            else "off"
        ),
    )
    return save_project_profile_state(project_root, state)

```
-> `src/app/project/profiles.py:1-416`
```markdown
# Project Profiles

Project profiles dong goi mot bo cai dat tai su dung cho workspace moi hoac project da co.

Current built-in profile:

- `zh-vi-narration-clear-vieneu`
  - video thuyet minh/kham pha `zh -> vi`
  - `translation_mode = contextual_v2`
  - prompt khuyen nghi: `contextual_default_adaptation`
  - active voice preset: `vieneu-default-vi`
  - override `VieNeu speed = 0.93`
  - override `default-ass FontSize = 12`
  - downstream mix khuyen nghi:
    - `original_volume = 0.07`
    - `voice_volume = 1.0`
- `zh-vi-narration-fast-vieneu`
  - video thuyet minh dai, it hoi thoai
  - `translation_mode = contextual_v2`
  - prompt khuyen nghi: `contextual_narration_fast_adaptation`
  - active voice preset: `vieneu-default-vi`
  - override `VieNeu speed = 0.93`
  - override `default-ass FontSize = 12`
  - downstream mix khuyen nghi:
    - `original_volume = 0.07`
    - `voice_volume = 1.0`
  - fast path runtime:
    - route theo `scene`, khong ep ca video di cung mot duong
    - scene narration ro rang se di `Narration Fast Path`
    - scene hoi thoai hoac borderline se fallback sang dialogue path day du
    - scene narration co the chay `term/entity mini-pass` scene-level truoc semantic/adaptation
    - mini-pass tao `narration_term_sheet` nhe de giu cach goi thuat ngu/thuc the on dinh trong scene
    - neu model bo trong `segment_positions`, runtime se fallback anchor `source_term -> source_text` de review hint van bam dung segment
    - neu mini-pass danh dau mot term trung tam la `needs_review`, runtime se route dung segment do sang review thay vi doan nghia
    - narration batches dung structured output theo vi tri, khong phu thuoc `segment_id`
    - bo qua LLM scene planner cho scene narration
    - bo qua semantic critic cho scene narration
    - dung batch semantic/adaptation lon hon
    - neu batch narration bi under-return, runtime se tu ha batch cap cho cac batch narration con lai thay vi tiep tuc retry batch lon lap lai
    - gui context/glossary nhe hon de giam token va review gia cho narration videos
    - co `prompt_cache_key` on dinh theo family/role/model/route/profile de giam input token lap lai
    - contextual runs dai se checkpoint partial theo `scene` trong cache, nen neu mat ket noi giua chung co the resume tu scene da xong thay vi mat sach progress
- `zh-vi-narration-fast-v2-vieneu`
  - video thuyet minh dai, uu tien cost/throughput
  - `translation_mode = contextual_v2`
  - prompt khuyen nghi: `contextual_narration_slot_rewrite`
  - active voice preset: `vieneu-default-vi`
  - override `VieNeu speed = 0.93`
  - override `default-ass FontSize = 12`
  - downstream mix khuyen nghi:
    - `original_volume = 0.07`
    - `voice_volume = 1.0`
  - narration v2 runtime:
    - route theo `scene`, chi co 2 lane: `narration_fast_v2` va `dialogue_legacy`
    - narration scenes lien tiep duoc gom thanh `span` de giam call/token
    - base path chi chay `1 semantic pass` va sinh `canonical_text`
    - `subtitle_text = tts_text = canonical_text` theo mac dinh, khong chay default dialogue adaptation
    - escalation la sparse:
      - `entity_micro_pass`
      - `ambiguity_micro_pass`
      - `slot_rewrite`
    - co `NarrationBudgetPolicy` voi soft-stop de giu estimated LLM cost trong budget
    - co run-local / project-local / global narration term memory
  - subtitle subtext:
    - project state co `subtitle_subtext_mode = off | source_text`
    - mac dinh `off`
    - UI co toggle `Subtext gốc`
    - toggle chi anh huong preview/export/hardsub, khong anh huong TTS hay semantic QC
  - downstream narration:
    - uu tien incremental rerun khi khong co speaker binding / voice policy
    - tach `visual_base` va `final_mux`
    - tach audio theo `scene-level chunks`
    - subtitle-only edit co the reuse TTS/audio
    - audio-only edit co the reuse `visual_base` va mux lai bang `-c:v copy`

Workspace layout:

- available profiles: `presets/project_profiles/*.json`
- applied profile state: `.ops/project_profile_state.json`

Current behavior:

- bootstrap project moi co san profile files
- neu tao project voi `project_profile_id`, profile se duoc apply ngay vao preset files + active project settings
- UI co `Chế độ giao diện`:
  - `Đơn giản (V2)` la mac dinh
  - mode nay uu tien tao project moi bang profile `zh-vi-narration-fast-v2-vieneu`
  - an cac form/policy/ops nang va giu lai flow chinh: tao project -> ASR & Dịch -> review -> Phụ đề -> TTS -> track giọng -> trộn -> xuất
  - co the bat lai `Nâng cao` bat cu luc nao de hien toan bo lane cu
- simple mode tu goi y ten project / thu muc project theo video da chon, dung workspace root on dinh thay vi `cwd`, va mac dinh `zh -> vi`, `ASR = zh`, mix narration `goc = 0.07`, `giong = 1.0`, `BGM = 0.0`
- simple mode cung rut gon quy trinh nhanh tren tab `Du an` thanh 4 hanh dong ro hon: `1. Chuan bi video`, `2. Tao phu de`, `3. Mo review`, `4. Hoan thien video`
- `rerun_contextual_downstream.py` se tu dung `recommended_original_volume` / `recommended_voice_volume` tu profile state neu khong override tay

Useful commands:

```powershell
python .\scripts\apply_project_profile.py --project-root <project-root> --project-profile-id zh-vi-narration-clear-vieneu
```

```powershell
python .\scripts\run_contextual_v2_headless.py --input-video <video> --project-root <project-root> --project-profile-id zh-vi-narration-clear-vieneu
```

```powershell
python .\scripts\run_contextual_v2_headless.py --input-video <video> --project-root <project-root> --project-profile-id zh-vi-narration-fast-vieneu
```

```powershell
python .\scripts\run_contextual_v2_headless.py --input-video <video> --project-root <project-root> --project-profile-id zh-vi-narration-fast-v2-vieneu
```

```powershell
python .\scripts\resume_contextual_v2_project.py --project-root <project-root>
```

Design note:

- profile nay co y tong quat hoa tu cac video narration khoa hoc/kham pha/hoang da, khong gan cung vao mot sample cu the
- neu can style moi, them profile moi thay vi sua tay tung project roi nho bang mieng

```
-> `docs/PROJECT_PROFILES.md:1-119`
Numeric meaning: original_volume 0.07 ducks source SFX/music under VI VO; VieNeu speed 0.93 slows slightly for intelligibility; FontSize 12 for dense narration readability; budget 0.30 USD for long videos.

## 11. Export presets & watermark
```python
    export_preset = {
        "export_preset_id": "youtube-16x9",
        "name": "YouTube 16:9",
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
        "resolution_mode": "keep",
        "target_aspect": "16:9",
        "target_width": 1920,
        "target_height": 1080,
        "crf": 18,
        "burn_subtitles": True,
        "watermark_enabled": False,
        "watermark_path": None,
        "watermark_position": "top-right",
        "watermark_opacity": 0.85,
        "watermark_scale": 0.16,
        "watermark_margin": 24,
        "notes": "Preset co ban cho YouTube ngang 16:9",
    }
    shorts_export_preset = {
        "export_preset_id": "shorts-9x16",
        "name": "Shorts 9:16",
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
        "resolution_mode": "pad",
        "target_aspect": "9:16",
        "target_width": 1080,
        "target_height": 1920,
        "crf": 20,
        "burn_subtitles": True,
        "watermark_enabled": False,
        "watermark_path": None,
        "watermark_position": "top-right",
        "watermark_opacity": 0.85,
        "watermark_scale": 0.18,
        "watermark_margin": 28,
        "notes": "Preset shorts/doc cho nen tang dung 9:16, giu frame bang pad.",
    }
    watermark_none_profile = {
        "watermark_profile_id": "watermark-none",
        "name": "Khong watermark",
        "watermark_enabled": False,
        "watermark_path": None,
        "watermark_position": "top-right",
        "watermark_opacity": 0.85,
        "watermark_scale": 0.16,
        "watermark_margin": 24,
        "notes": "Tat watermark/logo cho lan export nay.",
    }
    watermark_logo_profile = {
        "watermark_profile_id": "watermark-logo-top-right",
        "name": "Logo top-right",
        "watermark_enabled": True,
        "watermark_path": "assets/logos/logo.png",
        "watermark_position": "top-right",
        "watermark_opacity": 0.85,
        "watermark_scale": 0.16,
        "watermark_margin": 24,
        "notes": "Mau reusable profile. Hay thay assets/logos/logo.png bang logo cua ban.",
```
-> `src/app/project/bootstrap.py:58-118`
ffmpeg args from hardsub command builder (section 9). Watermark: format=rgba,colorchannelmixer=aa=opacity; scale2ref scale; overlay position.
NOT FOUND: explicit fps field in export preset (keeps source fps).

## 12. Ops / resilience
### Doctor checks
```python
from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

from app.core.ffmpeg import detect_ffmpeg_installation
from app.core.paths import get_appdata_dir
from app.core.settings import AppSettings
from app.ops.models import DoctorCheckResult, DoctorReport, utc_now_iso
from app.project.models import ProjectWorkspace
from app.subtitle.preview import PreviewUnavailableError, load_mpv_module, resolve_mpv_dll_path
from app.tts.models import VoicePreset
from app.tts.vieneu_engine import detect_vieneu_installation, get_vieneu_mode

DEFAULT_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024


def _status_for_bool(value: bool) -> str:
    return "ok" if value else "error"


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-", delete=True):
            return True
    except OSError:
        return False


def _disk_usage_check(path: Path, minimum_free_bytes: int) -> DoctorCheckResult:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return DoctorCheckResult(
            name="disk_space",
            status="warning",
            message=f"Khong doc duoc dung luong dia tai {path}: {exc}",
            fix_hint="Kiem tra quyen truy cap vao o dia chua workspace hoac appdata.",
        )
    free_gb = usage.free / (1024**3)
    if usage.free >= minimum_free_bytes:
        return DoctorCheckResult(
            name="disk_space",
            status="ok",
            message=f"Dung luong trong con lai: {free_gb:.2f} GB",
            detail_json={"free_bytes": usage.free, "path": str(path)},
        )
    return DoctorCheckResult(
        name="disk_space",
        status="warning",
        message=f"Dung luong trong thap: {free_gb:.2f} GB",
        fix_hint="Giai phong bo nho truoc khi rerun TTS/mix/export dai.",
        detail_json={"free_bytes": usage.free, "path": str(path), "minimum_free_bytes": minimum_free_bytes},
    )


def _check_ffmpeg(settings: AppSettings) -> list[DoctorCheckResult]:
    installation = detect_ffmpeg_installation(settings)
    return [
        DoctorCheckResult(
            name="ffmpeg",
            status=_status_for_bool(installation.ffmpeg.available),
            message=installation.ffmpeg.version_line or installation.ffmpeg.error or "ffmpeg san sang",
            fix_hint="Cau hinh duong dan ffmpeg.exe trong Cai dat hoac copy dependency vao bundle.",
            blocking_stages=("probe_media", "extract_audio", "asr", "voice_track", "mixdown", "export_video"),
            detail_json={"path": installation.ffmpeg.executable},
        ),
        DoctorCheckResult(
            name="ffprobe",
            status=_status_for_bool(installation.ffprobe.available),
            message=installation.ffprobe.version_line or installation.ffprobe.error or "ffprobe san sang",
            fix_hint="Cau hinh duong dan ffprobe.exe trong Cai dat hoac copy dependency vao bundle.",
            blocking_stages=("probe_media", "extract_audio", "asr", "export_video"),
            detail_json={"path": installation.ffprobe.executable},
        ),
    ]


def _check_mpv(settings: AppSettings) -> DoctorCheckResult:
    try:
        resolved_path = resolve_mpv_dll_path(settings.dependency_paths.mpv_dll_path)
    except PreviewUnavailableError as exc:
        return DoctorCheckResult(
            name="mpv",
            status="warning",
            message=str(exc),
            fix_hint="Cau hinh mpv_dll_path trong Cai dat hoac copy mpv-2.dll vao bundle.",
            blocking_stages=("preview",),
        )
    module_spec = importlib.util.find_spec("mpv")
    try:
        if module_spec is None:
            load_mpv_module(settings.dependency_paths.mpv_dll_path)
        mpv_module_ready = True
    except Exception:
        mpv_module_ready = False
    status = "ok" if mpv_module_ready else "error"
    message = "mpv preview san sang" if mpv_module_ready else "Tim thay mpv dll nhung khong tai duoc python-mpv"
    return DoctorCheckResult(
        name="mpv",
        status=status,
        message=message,
        fix_hint="Cai python-mpv neu muon preview subtitle trong app.",
        blocking_stages=("preview",),
        detail_json={"path": str(resolved_path)},
    )


def _check_openai_api_key(settings: AppSettings) -> DoctorCheckResult:
    ready = bool(settings.openai_api_key)
    return DoctorCheckResult(
        name="openai_api_key",
        status=_status_for_bool(ready),
        message="OpenAI API key san sang" if ready else "Chua cau hinh OpenAI API key",
        fix_hint="Nhap OpenAI API key trong tab Cai dat truoc khi chay dich.",
        blocking_stages=("translate",),
    )


def _check_model_cache_dir(settings: AppSettings) -> DoctorCheckResult:
    raw_path = str(settings.model_cache_dir or "").strip()
    if not raw_path:
        return DoctorCheckResult(
            name="model_cache_dir",
            status="warning",
            message="Chua cau hinh thu muc model cache",
            fix_hint="Luu lai Cai dat de app tao thu muc cache model mac dinh.",
        )
    path = Path(raw_path)
    path.mkdir(parents=True, exist_ok=True)
    writable = _is_writable_directory(path)
    return DoctorCheckResult(
        name="model_cache_dir",
        status="ok" if writable else "warning",
        message=f"Model cache dir: {path}",
        fix_hint="Kiem tra quyen ghi vao model cache dir.",
        detail_json={"path": str(path)},
    )


def _check_writable_path(name: str, path: Path, *, blocking_stages: tuple[str, ...]) -> DoctorCheckResult:
    writable = _is_writable_directory(path)
    return DoctorCheckResult(
        name=name,
        status=_status_for_bool(writable),
        message=f"Co the ghi vao {path}" if writable else f"Khong the ghi vao {path}",
        fix_hint="Kiem tra quyen ghi, antivirus, hoac duong dan khong hop le.",
        blocking_stages=blocking_stages,
        detail_json={"path": str(path)},
    )


def _check_vieneu_local(voice_preset: VoicePreset | None) -> DoctorCheckResult:
    environment = detect_vieneu_installation()
    requires_local_vieneu = False
    if voice_preset is not None and voice_preset.engine.strip().lower() == "vieneu":
        try:
            requires_local_vieneu = get_vieneu_mode(voice_preset) == "local"
        except ValueError:
            requires_local_vieneu = True

    if environment.local_ready:
        return DoctorCheckResult(
            name="vieneu_local",
            status="ok",
            message=environment.detail,
            blocking_stages=("tts",),
            detail_json={
                "package_version": environment.package_version,
                "espeak_path": str(environment.espeak_path) if environment.espeak_path else None,
            },
        )

    status = "error" if requires_local_vieneu else "warning"
    return DoctorCheckResult(
        name="vieneu_local",
        status=status,
        message=environment.detail,
        fix_hint="Can cai package vieneu va eSpeak NG neu muon chay VieNeu local.",
        blocking_stages=("tts",) if requires_local_vieneu else (),
        detail_json={
            "package_version": environment.package_version,
            "espeak_path": str(environment.espeak_path) if environment.espeak_path else None,
        },
    )


def run_doctor(
    *,
    settings: AppSettings,
    workspace: ProjectWorkspace | None = None,
    requested_stages: list[str] | tuple[str, ...] | None = None,
    voice_preset: VoicePreset | None = None,
    minimum_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> DoctorReport:
    checks: list[DoctorCheckResult] = []
    checks.extend(_check_ffmpeg(settings))
    checks.append(_check_mpv(settings))
    checks.append(_check_vieneu_local(voice_preset))
    checks.append(_check_openai_api_key(settings))
    checks.append(_check_model_cache_dir(settings))

    appdata_dir = get_appdata_dir()
    checks.append(
        _check_writable_path(
            "appdata_write",
            appdata_dir,
            blocking_stages=("translate", "tts", "voice_track", "mixdown", "export_video"),
        )
    )
    checks.append(_disk_usage_check(appdata_dir, minimum_free_bytes))

    if workspace is not None:
        checks.append(
            _check_writable_path(
                "workspace_write",
                workspace.root_dir,
                blocking_stages=("probe_media", "extract_audio", "asr", "translate", "tts", "voice_track", "mixdown", "export_video"),
            )
        )
        checks.append(
            _check_writable_path(
                "cache_write",
                workspace.cache_dir,
                blocking_stages=("extract_audio", "asr", "translate", "tts", "voice_track", "mixdown"),
            )
        )
        checks.append(_disk_usage_check(workspace.root_dir, minimum_free_bytes))

    return DoctorReport(
        generated_at=utc_now_iso(),
        checks=checks,
        requested_stages=tuple(str(stage).strip().lower() for stage in (requested_stages or []) if str(stage).strip()),
    )


def format_blocked_message(report: DoctorReport, *, stages: list[str] | tuple[str, ...], action_label: str) -> str:
    blocking_checks = report.blocking_checks_for(stages)
    if not blocking_checks:
        return ""
    lines = [f"Blocked because {action_label} chua dat dieu kien moi truong:"]
    for item in blocking_checks:
        lines.append(f"- {item.name}: {item.message}")
        if item.fix_hint:
            lines.append(f"  Goi y: {item.fix_hint}")
    return "\n".join(lines)

```
-> `src/app/ops/doctor.py:1-249`
| check | blocks stages |
|-------|---------------|
| ffmpeg | probe_media, extract_audio, asr, voice_track, mixdown, export_video |
| ffprobe | probe_media, extract_audio, asr, export_video |
| mpv | preview |
| openai_api_key | translate |
| vieneu_local | tts (if local required) |
| appdata_write | translate, tts, voice_track, mixdown, export_video |
| workspace_write | probe…export |
| cache_write | extract…mixdown |
| disk_space | warning only if < 2GB |
### Project safety / backup
```python
def create_workspace_backup(
    workspace,
    *,
    reason: str,
    stage: str,
) -> BackupManifest:
    ensure_ops_layout(workspace.root_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = get_backups_root(workspace.root_dir) / f"{timestamp}-{_sanitize_label(stage)}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    copied_files: list[Path] = []
    for source_path in (workspace.database_path, workspace.project_json_path):
        if source_path.exists():
            target_path = backup_dir / source_path.name
            shutil.copy2(source_path, target_path)
            copied_files.append(target_path)

    manifest = BackupManifest(
        created_at=utc_now_iso(),
        workspace_root=workspace.root_dir,
        backup_dir=backup_dir,
        reason=reason,
        stage=stage,
        project_id=getattr(workspace, "project_id", None),
        copied_files=copied_files,
    )
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest
```
-> `src/app/ops/project_safety.py:50-81`
Backs up `database_path` + `project_json_path` to `.ops/backups/{timestamp}-{stage}/`. Triggered from UI before destructive/review-resolution ops (e.g. reason strings in main_window).
### Cache layout
```python
_BUCKET_RELATIVE_DIRS: dict[str, tuple[str, ...]] = {
    "audio": ("cache", "extract_audio"),
    "asr": ("cache", "asr"),
    "translate": ("cache", "translate"),
    "translate_contextual": ("cache", "translate_contextual"),
    "tts": ("cache", "tts"),
    "mix": ("cache", "mix"),
    "subs": ("cache", "subs"),
    "exports": ("exports",),
}
```
-> `src/app/ops/cache_ops.py:11-20`
Also bootstrap: cache/extract_audio, asr, translate, subs, tts, mix, export; translate_contextual under cache. Orphan cleanup deletes unreferenced files; keeps paths referenced by job_runs + pipeline state manifests.
### Jobs state machine
```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELING = "canceling"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
```
-> `src/app/core/jobs.py:23-29`
queued → running → success | failed | canceled; canceling intermediate via token. JobCancelledError on cancel. retry_of_job_id supported.
```python
# hashing
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


def build_stage_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def fingerprint_path(path: Path) -> dict[str, object]:
    stats = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stats.st_size,
        "mtime_ns": stats.st_mtime_ns,
    }


```
-> `src/app/core/hashing.py:1-19`
```markdown
# AI Bugfix Workflow

This document defines the default bugfix workflow for AI-assisted changes in this repo.

## Goal

Turn real-world failures into durable regression knowledge.

The target outcome is not "the sample looks fixed".
The target outcome is:

- reproducible bug
- identified root cause
- correct-layer fix
- regression guard
- safe failover to review when ambiguity remains

## Mandatory sequence

1. Reproduce
   - Extract the smallest fixture that still reproduces the bug.
   - Prefer JSON/YAML/text fixture over a large binary sample.
   - Anonymize if needed.

2. Classify
   - Map the bug to a class in [ERROR_TAXONOMY.md](C:\Users\HulkBeoti\Documents\Reup_Video\docs\ERROR_TAXONOMY.md).
   - If needed, add a new class.

3. Root cause
   - Identify the primary faulty layer:
     - input/context
     - schema/contract
     - memory persistence
     - semantic inference
     - adaptation
     - QC severity
     - review routing
     - gate
     - mapping/binding
     - UI state
     - export/render

4. Write a failing test before the fix
   - Unit test for a deterministic rule when possible.
   - Integration test for stage interactions.
   - Semantic regression test for real zh->vi discourse failures.

5. Fix the smallest correct layer
   - Do not hardcode to one literal sentence unless it is glossary policy.
   - Prefer deterministic logic for deterministic rules.
   - Use prompt/schema changes only when the failure is actually inference-related.

6. Add regression guard
   - semantic QC rule
   - invariant
   - confidence threshold
   - locked memory rule
   - review queue routing
   - TTS/export gate

7. Audit blast radius
   - List at least 3 nearby patterns likely affected.
   - Propose follow-up tests.

8. Update docs/spec
   - taxonomy
   - QC spec
   - prompt contract
   - known limitations
   - fixture manifest

## Safety requirements

- Do not let TTS/export continue when semantic state is unsafe.
- Do not silently invent speaker/listener or honorific decisions under weak evidence.
- If confidence is too low or evidence conflicts, route to review.

## Fixture rules

- Put regression fixtures under [tests/fixtures/regression](C:\Users\HulkBeoti\Documents\Reup_Video\tests\fixtures\regression)
- Put stable golden reference fixtures under [tests/fixtures/golden](C:\Users\HulkBeoti\Documents\Reup_Video\tests\fixtures\golden)
- Register new fixtures in [tests/fixtures/manifest.json](C:\Users\HulkBeoti\Documents\Reup_Video\tests\fixtures\manifest.json)

## Required outputs for every meaningful bugfix

- failing fixture
- failing test
- fix
- passing test
- guard
- blast-radius note
- fail-safe note


```
-> `docs/AI_BUGFIX_WORKFLOW.md:1-93`
```markdown
# Release Checklist

This checklist is for local Windows bundle / installer validation.

## Prepare validation kit on dev machine

1. Chon 2 project copy da review sach:
   - 1 project ngan, nhieu speaker
   - 1 project dai kieu narration / object reference
2. Tao validation kit:
   - `python .\scripts\prepare_clean_machine_validation.py --short-project-root <path-short> --long-project-root <path-long> --clean-build`
3. Xac nhan kit co:
   - `bundle\...`
   - `projects\short-*`
   - `projects\long-*`
   - `run_bundle_smoke.ps1`
   - `reports\clean_machine_validation_report.template.json`
   - `prepare_clean_machine_validation_summary.json`

## Before build

1. Run `ruff check src tests scripts`.
2. Run `pytest -q`.
3. Open one real project and ensure:
   - `pending_review_count = 0`
   - semantic gate is clean
   - TTS/export still works on current machine

## Build bundle

1. Build PyInstaller bundle:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\build_pyinstaller.ps1 -Clean`
2. If needed, build installer:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -BuildBundle`

## Smoke the bundle

1. Run bundle smoke:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\smoke_release_bundle.ps1`
2. Verify the bundle can generate a doctor report.
3. Check that bundled dependencies are present when expected:
   - `dependencies\ffmpeg\ffmpeg.exe`
   - `dependencies\ffmpeg\ffprobe.exe`
   - `dependencies\mpv\mpv-2.dll`
   - `dependencies\espeak-ng\`

## Functional validation on a sample project

1. Launch the built app.
2. Open a sample project copy.
3. Run `Doctor` from `Cai dat` or `Du an`.
4. Verify `Workspace safety` is clean enough for rerun.
5. Run a short downstream rerun:
   - `TTS`
   - `Track giong`
   - `Tron am thanh`
   - `Xuat video`
6. Confirm:
   - backup was created under `workspace\.ops\backups`
   - cache cleanup does not remove referenced artifacts
   - output video is created successfully

## Clean-machine validation on VM / second machine

1. Copy the prepared validation kit to the clean machine.
2. Do not install Python or manually copy DLLs outside the bundle layout.
3. Run:
   - `powershell -ExecutionPolicy Bypass -File .\run_bundle_smoke.ps1`
4. Open the bundled app and validate:
   - preview on the short project
   - downstream rerun on the short project
   - downstream rerun on the long project
5. Keep these artifacts:
   - `reports\bundle_doctor_report.json`
   - smoke log / screenshots
   - rerun summary JSON from both projects
   - output video paths
6. Finalize the report back on the dev machine:
   - `python .\scripts\finalize_clean_machine_validation.py --kit-root <kit-root> --machine-label <vm-name> --windows-version "<windows-version>" --bundle-smoke-passed --preview-passed --short-project-summary <path> --long-project-summary <path>`

## Do not ship if

- doctor reports blocking errors for the stage you need
- workspace repair reports schema errors
- semantic review queue is still non-zero for a contextual project
- TTS/export succeeds only after manual file copying outside the documented dependency paths

```
-> `docs/RELEASE_CHECKLIST.md:1-86`

## 13. PORT PLAN FOR OMNICAST
License column: **NO-LICENSE / community-cleared → free to copy**.

| capability | source file:line | numeric config to carry | difficulty | OmniCast equivalent | verdict |
|------------|------------------|-------------------------|------------|---------------------|---------|
| Prompt families (all roles) | translate/presets.py:19-473 | max_cpl 38–42, cps 16–18 | M | agents/ prompts (generic) | **copy as-is** then wire |
| Structured output models | translate/models.py | schema v1/v2 | M | none for zh-vi discourse | **copy as-is** |
| OpenAI structured call + cache key | openai_engine.py:55-170 | temp=0.2, prices | S | media LLM helpers | **copy + adapt** (provider abstraction) |
| Scene chunker | scene_chunker.py:7-9 | gap 1500ms, 24 segs, 75s | S | none | **copy as-is** |
| Route predicate | contextual_runtime.py:222-284 | 0.75/0.45 weights | M | none | **copy as-is** |
| Batch split retry | contextual_runtime.py:355-450 | binary split | M | pipeline retry | **copy + adapt** |
| Contextual dialogue runtime | contextual_runtime.py:619+ | batch 8 | L | none | **copy + adapt** |
| Narration fast v2 | narration_fast_v2.py | budget 0.30/0.85, spans | L | none | **copy + adapt** |
| Semantic QC | semantic_qc.py | conf 0.65, listener 0.5/0.55 | M | compliance (YT policy only) | **copy as-is** |
| Review gate | main_window.py:6497-6526 | needs_review OR !qc_passed | S | vault status | **copy + adapt** |
| Relationship memory | relationship_memory.py + DDL | locked statuses | M | vault | **copy as-is** |
| Term memory | narration_term_memory* | max 6 terms | S | none | **copy as-is** |
| Sci notation autofix | nfv2.py:367-478 | exp 1–200 | S | none | **copy as-is** |
| ASR faster-whisper | faster_whisper_engine.py | model small, vad True | S | none/local ASR | **copy + adapt** |
| TTS clip/stage hash | tts/base.py | version 4/1 | S | media/tts.py | **copy + adapt** |
| Speaker binding/voice policy | tts/speaker_binding.py | precedence rules | M | media/voice_router.py | **copy + adapt** |
| Voice track fit | audio/voiceover_track.py | atempo 0.5–2, ar 48k | M | media/ffmpeg.py | **copy as-is** |
| Mixdown | audio/mixdown.py | 0.07/1.0, loudnorm -16 | S | media/ffmpeg.py | **copy as-is** |
| Subtitle QC | subtitle/qc.py | cps18 cpl42 | S | media/subtitle.py | **copy + adapt** |
| ASS export + subtext | subtitle/export.py | fs*0.75, H55 | S | media/subtitle.py | **copy + adapt** |
| Hardsub + path escape | subtitle/hardsub.py:130-138 | crf18/20, aac 192k | M | media/ffmpeg.py | **copy as-is** |
| Project profiles | project/profiles.py | volumes/speed | S | channels/*.json | **copy + adapt** |
| Checkpoint resume | contextual_checkpoint.py | partial json | M | pipeline executions | **copy + adapt** |
| Doctor preflight | ops/doctor.py | 2GB free | S | none | **copy + adapt** |
| Cache ops | ops/cache_ops.py | bucket tree | S | products/cache | **copy + adapt** |
| Jobs model | core/jobs.py | state enum | S | pipeline jobs | **drop** if vault jobs suffice |
| UI review console | ui/main_window.py | — | L | frontend | **drop** (re-UI); keep gate logic |
| SAPI TTS | tts/sapi_engine.py | — | S | forbidden robot voice policy | **drop** |
| VieNeu engine | tts/vieneu_engine.py | 24kHz | M | media/tts providers | **copy + adapt** or map to OmniCast TTS |

### TOP-20 most valuable carry-overs
1. Semantic QC rules + conf 0.65 / listener 0.5 / discourse 0.55 — last safety net before dub.
2. Review gate: block if needs_human_review or !semantic_qc_passed.
3. Full zh→vi prompt families (dialogue + narration + cartoon) at temperature 0.2 structured outputs.
4. HonorificPolicy + COMMON_VI_PRONOUNS dual-text divergence errors.
5. Locked relationship memory with side-specific allowed_alternates.
6. Scene router narration_score ≥0.75 / ≤0.45 with cue densities.
7. Scene chunk gap 1500ms / 24 segs / 75s.
8. Batch split retry on id mismatch + invalid JSON parse.
9. Narration Fast V2: canonical_text only + sparse escalation + $0.30 budget soft-stop 0.85.
10. Span limits 48 units / 3200 chars / 90s / gap 1500ms.
11. Term/entity mini-pass max 6 + needs_review → technical_term_uncertainty.
12. Scientific notation incomplete 10^ autofix from neighbor exponents.
13. subtitle_text vs tts_text dual fields + normalize_tts_text.
14. Prompt-cache assembly order Constraints→Context→Glossary→Source + sha1 cache key.
15. Mix original_volume=0.07, voice=1.0, loudnorm I=-16:TP=-1.5:LRA=11.
16. Voice fit atempo chain + pad/trim to subtitle slots.
17. TTS clip hash (text+preset) for incremental rerun.
18. ASS path escape for Windows hardsub.
19. Narration profiles VieNeu speed 0.93 + FontSize 12.
20. REVIEW_REASON_CODES + ERROR_TAXONOMY as living regression taxonomy.

## 14. TRAPS / GOTCHAS
- Temperature only 0.2; no max_output_tokens — long batches fail and rely on split retry.
- Narration positional outputs (no segment_id) vs dialogue id-keyed — wrong validation path will false-fail.
- Prompt templates seeded once; editing code defaults won't update existing project JSON presets.
- ASS hardsub path escape is mandatory on Windows drives (`C:` → `C\:`).
- TTS cache duration 0 causes premature atempo/trim (ERROR_TAXONOMY class 11).
- No diarization — speaker ids are LLM guesses; voice binding must fail-safe.
- SAPI present as fallback in Reup — **do not port** into OmniCast (robot voice ban).
- Global term memory file is empty; real memory is project-local after human approve.
- Mix has no ducking sidechain — original_volume fixed gain only.
- Review codes must be normalized before persist or fixtures break.

## 15. NOT FOUND
- LICENSE file
- Explicit beam_size / VAD parameter object / temperature list / initial_prompt in ASR wrapper
- Diarization pipeline
- top_p, max_output_tokens, reasoning effort, service_tier on OpenAI calls
- sidechaincompress / audio ducking
- Crossfade constants in voice track
- Dedicated Hán-Việt name dictionary / 成语 table
- Repo-level presets/ tree (presets are **generated into project** on bootstrap)
- Export fps field
- Pre-call token estimation (post-usage only)
