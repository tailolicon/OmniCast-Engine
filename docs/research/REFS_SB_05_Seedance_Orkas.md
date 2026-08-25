# REFS SB-05 — seedance-2.0 Skill OS + Orkas-VideoStudio

> STATUS: ACTIVE (research one-shot)  
> Date: 2026-08-02  
> Sources: `_refs/seedance-2.0` (MIT), `_refs/Orkas-VideoStudio` (MIT)  
> Scope: prompt-craft, scene-before-prompt, plan.json IR, compose/edit, agent CLI/MCP — map vào gap OmniCast (WS1 storyboard→render, WS4 EDL re-render)

---

## 0. TL;DR cho OmniCast

| Nguồn | Bản chất | OmniCast đã port | Gap lớn còn lại |
|---|---|---|---|
| **seedance-2.0** | Skill OS hướng dẫn agent **viết prompt video** (không phải runtime gen). Director formula + anti-slop + role isolation + sequence canon. | `storyboard/slop.py`, `storyboard/binding.py`, comment trong `veo_pipeline.build_motion_prompt` | Chưa có **prompt compiler** clip-contract → natural language; chưa port camera/light/motion contracts đầy đủ; chưa port retake protocol + completed/reserved beat exclusions; tag syntax OmniCast dùng `[IMAGE n]` (Gemini) vs Seedance `@Image1` |
| **Orkas-VideoStudio** | Video = `plan.json` **readable / diffable / re-renderable**; agent = brain, CLI/MCP = hands | `repair_budget.py`, `consistency_check.py` (stage-consistency), một phần QA motion trong `qa_check` | **Chưa có plan.json/EDL IR**; chưa compose (HTML/GSAP); chưa edit pipeline (trim/concat/mix/burnsubs as first-class); chưa `delivery_promise`/`promise-check`; chưa gate A–D; chưa agent surface `ovs` |

**Một câu:** Seedance dạy *cách nói với model*; Orkas dạy *cách biến ý định thành plan có thể diff và re-render từng mảnh*. OmniCast đang có mảnh QA/consistency/slop/binding — còn thiếu **IR plan** + **prompt compiler đầy đủ**.

---

## 1. Tổng quan kiến trúc

### 1.1 seedance-2.0 — Skill OS, không phải video engine

Repo **không** gọi API Seedance để render trong runtime production. Nó là:

```
User intent
  → Root skill `SKILL.md` (gates + authority order + fast lane)
  → Sub-skills (prompt / camera / lighting / motion / audio / characters / …)
  → References (lexicon, retake, compiler, schemas)
  → Natural-language prompt (+ optional project-state JSON for sequences)
  → [Agent/user pastes vào Dreamina / Ark / fal / …]
```

**Module map (đọc từ tree):**

| Layer | Path | Vai trò |
|---|---|---|
| Root router | `SKILL.md` | Operating loop 13 bước, authority order, sequence gate, load map |
| Prompt builders | `skills/seedance-prompt*`, `interview*`, `sequence`, `continuation` | Viết brief + prompt |
| Craft specialists | `camera`, `lighting`, `motion`, `audio`, `characters`, `style`, `vfx`, `recipes` | Contracts per dimension |
| Safety | `copyright`, `filter`, `antislop` | IP-safe rewrite, filter false-positive, filler removal |
| Ops | `pipeline`, `troubleshoot` | API/workflow status, diagnosis tree |
| References | `references/*.md`, `vocab/*` | Lexicon + deep guides |
| Schemas | `schemas/*.schema.json` | project-state, clip-contract, prompt-spec, take-review |
| Scripts | `scripts/prompt_lint.py`, `extract_last_frame.py`, … | Lint golden prompts, continuity checks |
| Golden examples | `examples/golden-prompts/`, `sequence-airport-arrival/` | Prompt mẫu + sequence trace |

**Soul (verbatim, root):** *“Direct the model. Don't micro-manage the frame. An agent that reads the scene before it writes the prompt.”* — implement qua **Director's Read** (`references/directing-engine.md`) trước khi fill slots prompt.

### 1.2 Orkas-VideoStudio — agent toolkit + diffable IR

```
User plain language
  → video-router locks line (compose | generate | edit | AUTO)
  → stage-plan → project/plan.json (VideoEdl)
  → gate B (plan confirm) / gate C (paid gen)
  → stage-assemble walks plan:
       edit | generate | compose | provided per segment
  → ffmpeg tiers: concat → overlay → mix narration → burnsubs → loudness
  → promise-check + draft QA → gate D
```

**Package map:**

| Package | Path | Vai trò |
|---|---|---|
| `@orkas/video-studio-core` | `packages/core/src/ir/edl.ts` | VideoEdl types + `validateEdl` + `assessDelivery` + `summarizeEdl` |
| tools | `packages/tools` | edit/ffmpeg, render/HyperFrames, analyze (whisper/OCR), image/video/speak |
| CLI | `packages/cli/src/index.ts` | `ovs` — canonical interface |
| MCP | `packages/mcp/src/index.ts` | tools mirror CLI 1:1 |
| skills | `packages/skills/*/SKILL.md` | Knowledge pack (router, stages, craft, gates) |

**Data flow end-to-end (AUTO):** material → `ingest.json` (probe/transcribe/OCR) → `plan.json` → produce segments → assemble → `render_report.json` → deliverable mp4.

---

## 2. Data model storyboard / plan

### 2.1 seedance — clip contract + project state (internal), prompt = natural language (external)

**Nguyên tắc cứng** (`prompt-compiler.md`): planning có thể JSON; **final prompt gửi model = prose**, không dump JSON vào Seedance.

#### Clip contract (schema required fields) — `schemas/clip-contract.schema.json:6-44`

```json
{
  "project_id", "clip_id", "parent_clip_id", "scene_id", "sequence_index",
  "narrative_job", "felt_intent", "target_duration_sec",
  "generation_mode",
  "shot_structure": "compact_single_take | phased_single_take | dense_multishot | first_last_frame_transition | video_edit_contract",
  "already_happened": [],
  "this_clip_only": [],
  "reserved_for_later": [],
  "planned_start_state": {},
  "planned_end_state": {},
  "continuity_locks": [],
  "allowed_changes": [],
  "status": "planned|ready|generated|reviewed|accepted|accepted_with_deviation|repair|rejected"
}
```

#### Prompt-spec (compiler output envelope) — `schemas/prompt-spec.schema.json:6-33`

```json
{
  "project_id", "clip_id", "prompt_version",
  "sequence_relation": "standalone|sequence_first_clip|seamless_continuation|intentional_next_shot|bridge_between_known_states|repair_tail|reanchor_after_drift",
  "generation_mode", "reference_roles",
  "opening_state_source": "planned_start_state|observed_end_state|user_supplied_final_frame|source_clip",
  "current_clip_action", "endpoint",
  "completed_beat_exclusions", "reserved_future_exclusions",
  "natural_language_prompt"
}
```

#### Project state — `schemas/project-state.schema.json`

Required: `story`, `world_bible`, `reference_registry`, `scenes`, `beats`, `clips`, `take_history`, `current_clip_id`, `canon_revision`.  
Scene có `arc_position: open|rising|turn|climax|release`, `max_chain_depth` (default 2, hard max 3), `anchor_source`.

**State machine take:** planned → generated → reviewed → accepted / accepted_with_deviation / repair / rejected. **Accepted observed state overrides planned state.**

### 2.2 Orkas — `VideoEdl` = plan.json đầy đủ

Types verbatim từ `packages/core/src/ir/edl.ts:26-210`:

```typescript
// Enums
DeliveryPromiseType = 'source_led' | 'motion_led' | 'compose_led' | 'hybrid'
SegmentRole         = 'hook' | 'body' | 'proof' | 'cta' | 'transition'
SegmentLayer        = 'primary' | 'overlay' | 'bg'
SegmentSource       = 'edit' | 'generate' | 'compose' | 'provided'
VideoReferenceIntent = 'reproduce' | 'edit' | 'guide'
VideoReferenceRole   = 'content'|'identity'|'composition'|'structure'|'style'|'motion'|'timing'|'audio'
VideoEditMode        = 'deterministic' | 'semantic' | 'mixed'
VariationType        = 'small' | 'medium' | 'large'

interface DeliveryPromise {
  type: DeliveryPromiseType;
  source_required: boolean;
  motion_min_ratio: number;  // [0..1] real motion vs compose cards
  quality_floor?: string;
}

interface EdlSegment {
  id: string;
  order: number;
  role: SegmentRole;
  layer: SegmentLayer;
  source: SegmentSource;
  target_sec: number;
  over?: string;           // overlay/bg sits over primary id
  spec: Record<string, unknown>;  // source-specific
  status?: string;
  produced_path?: string;  // written back for resume
  evidence?: Record<string, unknown>;
}

interface VideoEdl {
  aspect: string;              // "9:16" | "16:9" | "1:1"
  total_target_sec: number;
  language: string;
  delivery_promise: DeliveryPromise;
  style_kit?: StyleKit;
  references?: VideoReferenceMedia[];
  edit_strategy?: VideoEditStrategy;
  segments: EdlSegment[];
  tracks: { narration?, music?, captions? };  // required object; {} if empty
  cost_estimate?: { billable_generations: number };
}
```

**spec theo source** (`validateSpec`, edl.ts:690-818):

| source | spec bắt buộc |
|---|---|
| `edit` | `input_id`, `in_sec`, `out_sec` |
| `generate` | `prompt`; video: `media_kind`, `generation_duration_sec` (4–15), `ratio`, `resolution`, `generate_audio`, refs ≤9 images / ≤3 videos; optional `operation:"edit"`, `characters`, `refs`, `variation_type` |
| `compose` | `kind` (title-card, lower-third, stat-card, …) |
| `provided` | `asset_id`, `kind: video|image` |

**Skeleton plan.json** (từ `stage-plan/SKILL.md:57-88`) — copy shape này; validator reject mọi shape khác.

**composition-manifest v2** (compose line, không phải plan.json) — `stage-compose/SKILL.md:55-83`: canvas, scenes, art_direction, audio owner, source_alignment.

---

## 3. Cơ chế consistency nhân vật / bối cảnh / props

### 3.1 seedance

1. **Reference role map trước adjectives** (`reference-workflow.md:13-35`): mỗi asset một primary role — identity / first frame / last frame / product / environment / motion / camera / timing / audio / style. **Never infer authority from upload order or media type.**
2. **Dimension authority** (root SKILL.md step 7): mỗi controlled dimension đúng một winning asset; asset không own gì → drop.
3. **Character tags** (`seedance-characters`): `Character A`, `@Image1 subject`; no ambiguous pronouns after multi-character appears.
4. **Three-tier action hierarchy** (multi-person stabilizer):
   - Tier 1: persistent micro-motion (default for background people)
   - Tier 2: one focused response with time window
   - Tier 3: large actions **prohibited by default**
5. **Sequence:** canonical identity refs ≠ accepted continuity source. `extension_depth` cap 2–3 rồi re-anchor. Rejected takes never enter canon.
6. **I2V:** do not re-describe static identity (`i2v-guide.md:5-6`).

### 3.2 Orkas stage-consistency (`packages/skills/stage-consistency/SKILL.md`)

1. **Character bible** `project/characters/bible.json` — static vs dynamic features.
2. **Front portrait once, LOCK** — never regenerate anchor; side/back derived by edit.
3. **Cameo** = user photo as front portrait.
4. **Per-shot refs:** view-matched portrait + recent same-camera frame; priority: recent same camera > older > portrait-only.
5. **Describe motion by visual features, not names** (“figure in green dress”, not “Alice”).
6. **Verify keyframe BEFORE paying to animate** — re-roll cheap image, not video.
7. **Carry-forward:** extract last frame → next shot reference.
8. Caps: ≤3 characters, ≤3 scenes, ≤6 shots default.

### 3.3 OmniCast đã port

- `implementation/consistency_check.py` — DNA axes + re-roll stills + cache by hash (Orkas stage-consistency pattern).
- `storyboard/binding.py` — role isolation + `[IMAGE n]` tokens (Jellyfish + seedance transfer contract).
- `storyboard/` cast registry, refsheet, continuity gates.

**Chưa port:** character bible JSON + view-matched portrait set; explicit `extension_depth` / re-anchor schedule; carry-forward last frame as first-class pipeline step wired into storyboard→Veo (có `extract_last_frame` helper trong veo_pipeline nhưng WS1 gap: chưa nối storyboard).

---

## 4. PROMPT ENGINEERING — VERBATIM (quan trọng nhất)

### 4.1 Director Formula (slot order) — `skills/seedance-prompt/SKILL.md:35-46`

> Use `Subject + Action + Scene + Camera + Lighting/Style + Audio + Constraints`.  
> Put the subject and primary action first because early clauses set the shot hierarchy.

| Slot | Prompt-ready pattern (verbatim) |
|---|---|
| Subject | `Original ceramic perfume bottle on black acrylic, label preserved exactly` |
| Action | `condensation beads form and slide down the glass over five seconds` |
| Scene | `quiet rain-lit kitchen counter, shallow depth of field` |
| Camera | `slow dolly-in from medium product shot to macro label detail` |
| Light and style | `warm practical key from frame left, cool blue rim, clean commercial realism` |
| Audio | `Sound: low room tone, soft glass chime on final frame` |
| Constraints | `do not alter logo, shape, label, or cap geometry` |

**Vì sao hiệu quả:** attention budget — mệnh đề đầu conditioning mạnh nhất (`anti-slop-lexicon.md:38-46`). Empty evaluator ở opening tốn slot đắt nhất.

### 4.2 Mode gate — drafting priority (verbatim table) — `seedance-prompt/SKILL.md:48-59`

| Mode | Drafting priority | Common mistake | Repair |
|---|---|---|---|
| T2V | Build the whole shot in compact layers. | Too many events in one clip. | Keep one visible beat and one endpoint. |
| I2V | Preserve visible identity; add motion. | Re-describing the image until the product or face drifts. | Say `preserve @Image1 exactly`; add only dynamic changes. |
| V2V | Transfer motion, camera, or timing. | Copying unauthorized likeness or scene details. | Use owned/licensed/authorized references and restrict transfer role. |
| R2V | Assign separate roles to each asset. | One reference asked to control identity, pose, scene, and style. | Split roles or prioritize the most important role. |
| FLF2V | Move from first frame to last frame. | Treating the last frame as vague mood instead of endpoint. | State `@Image2` is the final visual target. |
| Edit | Preserve the source clip while changing one layer. | Rewriting the whole scene and losing continuity. | Say `@Video1 is the source clip; change only...` |
| Extend | Continue from accepted source footage only. | Starting from a planned ending or inventing the clip state. | Use observed end state. |

### 4.3 Compact templates — `seedance-prompt-short/SKILL.md:49-55`

```
T2V:  [Subject] [action and endpoint] in [scene]. Camera: [one move]. Light/style: [physical source]. Sound: [cue]. Constraint: [risk/continuity].
I2V:  @Image1 preserved; only [motion/light/camera] changes. Camera: [one move]. Sound: [cue]. Constraint: [what must not change].
V2V:  @Video1 controls [motion/camera/timing] only; new subject [anchor]. [Action]. Do not transfer [identity/scene/logo].
Chinese: @Image1为参考，严格保持[主体]不变；仅加入[动作/光线/镜头]。声音：[提示]。
```

Ideal length: **30–100 English words** (prompt-short). Full production: under active-surface budget; fast lane **~40–110 words**.

### 4.4 I2V minimal template — `references/i2v-guide.md:7-9`

```
@Image1 is the reference; preserve [identity/product/scene] exactly. Only [motion] changes. Camera: [one move]. Lighting: [source or transition]. Sound: [cue]. Constraint: [what must not change].
```

**Two I2V modes (field-observed):**
- **Hold mode:** 3–4 micro-actions; double lock `she stays seated…; she does not stand, turn, or leave frame`.
- **React mode:** expand one emotion into sub-beats ≥2s; `the clip begins exactly at this moment` if mid-scene still.

### 4.5 FLF2V template — `references/first-last-frame-guide.md:32-41`

```text
@Image1 is the first frame. @Image2 is the last frame.
Preserve [subject/product/character], [outfit/logo/shape], and scene layout.
Generate a continuous transition from [starting state] to [ending state].
Motion: [one physical action path].
Camera: [one controlled move or locked frame].
Lighting: [source and continuity].
Sound: [ambience/dialogue/SFX/music/silence].
Constraints: no new text, no watermark, no identity change, no object redesign.
```

### 4.6 R2V role isolation golden — `examples/golden-prompts/r2v-role-isolation.md:13`

```
@Image1 controls the original character identity and wardrobe. @Video1 controls camera rhythm only; ignore its performer, room, logo, and costume. @Audio1 controls tempo only; do not copy voice or song identity. The character walks toward the doorway in three steady steps as the camera matches the reference rhythm and stops when her hand reaches the handle.
```

### 4.7 Compact I2V golden — `examples/golden-prompts/compact-i2v.md:13`

```
@Image1 is the product identity reference; preserve its logo, shape, color, and material exactly. Only a narrow warm light sweep moves across the glass, ending with the label cleanly readable. Camera stays locked. Sound: one soft chime at the final highlight.
```

### 4.8 Sequence continuation prose pattern — `examples/sequence-airport-arrival/clip-01-prompt.md:3`

```
Begin at the airport terminal doors in light rain. The original traveler from @Image 1, wearing the same charcoal coat and pulling a small black suitcase, exits into the curbside crowd and moves left-to-right toward a black sedan with its rear passenger door already open. Camera tracks beside her at walking speed, keeping the open door ahead in frame. Cool rain reflections and taxi lights stay consistent. This clip only covers the terminal exit and approach to the open door; do not show her entering the car and do not let the vehicle depart. Stop when she reaches the open rear door.
```

**Clip-scope language** (`prompt-compiler.md:40-46`):  
`Begin with…` / `Continue the same…` / `This clip only…` / `Stop when…` / `Do not yet…`

### 4.9 Reference transfer template — `reference-workflow.md:67-73`

```
@Image1 controls product identity. @Video1 controls camera pace only. @Audio1 controls tempo only. Preserve the subject from @Image1; do not copy characters, logos, music, voice, or environment from @Video1/@Audio1.
```

### 4.10 Camera phrases — `skills/seedance-camera/SKILL.md:35-41`

| Need | Strong phrase | Avoid |
|---|---|---|
| Emotional realization | `slow dolly-in from medium close-up to tight close-up as Character A lowers the envelope` | `dramatic cinematic zoom` |
| Product reveal | `controlled slider move from silhouette to front three-quarter hero angle, ending on the label` | `dynamic product camera` |
| Scale | `low-angle crane up from boots to skyline, ending behind the character's shoulder` | `epic wide moving shot` |
| Instability | `subtle handheld shoulder camera, small breathing sway, subject kept centered` | `shaky chaotic camera everywhere` |
| Precision detail | `locked macro shot, focus stays on the watch gears while the second hand clicks once` | `cool close-up details` |

**Rule:** one primary move; state start / speed / subject relationship / endpoint. Conflict → keep one, variants optional.

### 4.11 Lighting — `skills/seedance-lighting/SKILL.md:35-41`

| Mood | Prompt-ready lighting |
|---|---|
| Product luxury | `narrow warm strip light sweeps across brushed metal, black acrylic reflection remains clean` |
| Night drama | `warm practical lamp from frame left, blue moonlight rim on shoulders, soft hallway shadows` |
| Discovery | `door crack opens and a thin white beam widens across dust in the air` |
| Food realism | `large soft window light from the right, gentle bounce on the plate, no harsh specular glare` |
| Storm | `cool overcast daylight, intermittent lightning flashes briefly sharpen the silhouette` |

### 4.12 Motion / physics — `skills/seedance-motion/SKILL.md:36-50`

Strong: `Character A inhales, grips the cup tighter, then sets it down without looking away`  
Weak: `she feels nervous`  

Physics-forward: `the heavy oak door swings shut and the candle flames bend toward it`  
Timing: `0-2s: candle flame steady; 2-4s: door opens and flame bends; 4-6s: smoke trail curls toward the hallway`

### 4.13 Audio native — `skills/seedance-audio/SKILL.md:38-48`

Layers: `Dialogue: ... Sound: ... SFX: ... Music: ... Silence: ...`

| Need | Stable audio direction |
|---|---|
| Lip-sync | `Character A, locked medium close-up, says "I found it." Clear dry dialogue, no head turn.` |
| Product ad | `Sound: low room tone. SFX: magnetic click on lid open, soft glass chime at final frame.` |
| Beat sync | `@Audio1 provides tempo only; light pulses and foot taps match the downbeat.` |
| Drama | `Distant rain and refrigerator hum; no music during the line.` |

**Rules:** short quoted dialogue; one speaker per short clip when reliability matters; `@Audio1` = rhythm/mood unless surface docs exact playback. Field: Mandarin lip-sync strongest, English second; non-English keep very short.

### 4.14 Characters / performance — `skills/seedance-characters` + `directing-engine.md:58-66`

- Emotion → **one true visible gesture**, not emotion noun.  
- `she folds the letter, presses it flat with both hands, and does not look up` ≠ `grief`.  
- Multi-char: assign verbs separately; contact point + endpoint.

### 4.15 Style IP-safe — `skills/seedance-style/SKILL.md:34-40`

| User intent | Safe descriptor |
|---|---|
| Cozy hand-drawn fantasy | `hand-painted 2D animation, soft watercolor backgrounds, rounded character silhouettes, warm pastel palette, gentle parallax` |
| Sharp cyberpunk action | `neon noir city, wet pavement reflections, high-contrast magenta and cyan light, fast lateral tracking, angular silhouettes` |
| Premium product realism | `clean commercial realism, controlled reflections, shallow depth of field, neutral background, polished material detail` |

Layers: medium / surface / palette / camera-render / motion rhythm. **Do not** use studio/franchise/artist names as anchors unless authorized.

### 4.16 IP-safe rewrites — `skills/seedance-copyright/SKILL.md:35-52`

| Risk | Replace with |
|---|---|
| Named character or franchise | Original archetype, genre function, non-identical costume language |
| Studio or living-creator style | Medium, texture, palette, composition, line quality, motion rhythm |
| Celebrity or private person | Original performer description or authorized reference workflow |
| Brand logo | Generic product mark, blank label, or user-owned brand if authorized |
| Song, voice, performance | Tempo, energy, instrumentation, mood, or newly composed sound |
| Exact scene recreation | Original scene, similar narrative function, different setting/blocking |

**Example rewrite (verbatim):**  
`original masked rooftop courier in a red weatherproof jacket leaps between rain-slick buildings, low handheld tracking camera, blue police lights far below, no logos or franchise symbols`

### 4.17 Anti-slop — SIX classes (verbatim) — `skills/seedance-antislop` + `anti-slop-lexicon.md`

1. **Empty evaluators** — `cinematic, epic, stunning` → one observable detail  
2. **Borrowed image-model tokens** — `8K, masterpiece, ArtStation, Unreal Engine` → **delete**  
3. **Tag salad** — comma keyword dumps → shooting-brief prose  
4. **Negation slop** — `no blur, no extra fingers` → describe what IS; negation only in constraint slot  
5. **Adjective stacking** — three synonyms → one detail  
6. **Feel-suffix** — `电影感, vibey, 감성적인` → physical cause of feeling  

**Replacement table excerpt** (`anti-slop-lexicon.md:17-35`):

| Weak | Replace with |
|---|---|
| cinematic | shot scale, camera move, lighting, grade |
| epic | physical scale, stakes, crowd size, lens distance |
| dynamic | specific movement, speed, and endpoint |
| 8K / ultra-HD | delete; resolution is a render setting |
| masterpiece | delete |

**Visibility test:** camera / light meter / mic / stopwatch must detect the phrase.

### 4.18 Filter / forbidden surface wording — `filter-vocab.md` + `vocab/en.md`

**Safer production wording:**

| Risky surface | Safer |
|---|---|
| violent impact | high-energy collision, non-graphic action beat |
| weapon close-up | prop object held safely, action-scene staging |
| blood | red fabric accent, colored liquid, non-graphic aftermath |
| fight | choreographed action sequence, staged confrontation |
| celebrity face | original character with broad archetype traits |
| brand logo | generic product mark or blank label |

**English false-positive traps** (`vocab/en.md:90-98`):

| Trigger-prone | Clarification |
|---|---|
| shoot the scene | film the scene, capture the take |
| kill the lights | cut the lights to black |
| gun it / shot after shot | accelerate hard / take after take |
| dead silence | held silence, room tone only |
| blow up the image | enlarge the image to full frame |

**Boundary:** skill repairs **false positives only**; does not help evade safety for prohibited content (`seedance-filter/SKILL.md:27-29`).

### 4.19 Feeling → film (interview) — `seedance-interview/SKILL.md:96-106`

| User says | Brief writes |
|---|---|
| epic, cinematic | wide establishing frame, one slow push-in, low warm sun, rising score |
| cozy, warm | close framing, soft window light, gentle motion, quiet room tone |
| funny | locked camera, deadpan timing, one absurd visible beat, dry single SFX |
| like an ad | controlled hero light, tidy background, one polished camera move |
| sad, emotional | stillness, a little distance, cool soft light, sparse sound |

### 4.20 Recipe skeletons — `seedance-recipes/SKILL.md:50-60`

```
Product I2V: @Image1 is the product reference; preserve logo, label, shape, and materials exactly. [One material or light change]. Camera: [single move]. Lighting: [physical source]. Sound: [ambient/SFX].
Drama T2V: Character A [visible emotional action] in [specific setting]. Camera: [motivated framing]. Lighting: [motivated source]. Sound: [ambient or short dialogue]. End state: [changed expression/action].
Reference Motion: @Video1 provides only [camera/action/timing] reference; do not transfer identity, costume, logo, or environment. New subject: [authorized/original subject]. [Action and endpoint].
First/Last Frame: @Image1 is the first frame. @Image2 is the last frame. Preserve [identity/product/scene anchors]. Generate a continuous transition from [start state] to [end state]. Camera: [locked or one controlled move]. Sound: [ambient/SFX].
```

### 4.21 Troubleshoot conservative retry — `seedance-troubleshoot/SKILL.md:60-62`

```
[Reference role if any]. Preserve [identity/product/environment] exactly. One visible action: [specific verb and consequence]. Camera: [single move]. Lighting: [physical source]. Sound: [ambient/SFX/dialogue]. Constraints: [what must not change].
```

### 4.22 Prompt compiler compile order — `prompt-compiler.md:16-27`

1. Lineage (project/clip/parent — often omit from final prompt to save budget)  
2. Source role tags  
3. Actual opening state (observed for continuations)  
4. Current clip action + endpoint  
5. Felt intent → **as camera/light/performance/sound carriers, never abstract emotion word**  
6. Camera/motion phase  
7. Light/env/style/audio only if state/intent-critical  
8. Exclusions (completed + reserved)  
9. Endpoint  

**Source-carries-state:** when clip/frame attached, text only carries **delta**.

### 4.23 Orkas generation prompt craft — `video-craft/SKILL.md:91-96`

- Concrete visual features, never abstractions.  
- Weak → strong: ✗ `a professional, friendly host in a modern office` → ✓ `woman, mid-30s, short black bob, charcoal blazer over white tee; sunlit open-plan office; soft window key from camera-left.`  
- First frame / last frame as static snapshots, never mid-action.  
- Name characters by visible features in motion text.

### 4.24 Đánh giá: rule nào áp Veo/Flow OmniCast vs đặc thù Seedance

| Rule | Áp thẳng Veo/Flow/Gemini? | Ghi chú |
|---|---|---|
| Subject+Action first; one beat; one camera move | **YES** | Universal attention budget |
| Anti-slop 6 classes | **YES** — đã partial trong `storyboard/slop.py` | Giữ + mở rộng camera/light vocab |
| I2V: motion-only when seed image present | **YES** — `veo_pipeline.build_motion_prompt` đã note | Enforce fail-closed từ storyboard |
| Role isolation + preserve/may_change | **YES** — `binding.py` | Map `@Image1` → `[IMAGE n]` / Flow Ingredients |
| IP-safe rewrite + filter false-positive | **YES** | ComplianceChecker parallel |
| Emotion → visible gesture | **YES** | Writer/Critic + storyboard extract |
| Completed/reserved beat exclusions | **YES** | Clip contract trong storyboard |
| Retake one-variable + budget | **YES** | Pair với `RepairBudget` |
| `@Image1` / `@Video1` / `@Audio1` syntax | **Seedance-specific** | OmniCast: `[IMAGE n]`, Gemini ordered refs, Flow Ingredients ≤14 |
| Surface prompt profiles (Dreamina/Ark/fal tags) | **Seedance-specific** | Không port syntax; port *idea* surface profiles |
| Native audio/lip-sync field reports (Mandarin-first) | **Partial** | Veo 3 has native audio but different behavior |
| `extension_depth` max 2–3 | **Heuristic portable** | Cap chain i2v from last frame |
| Multilingual @图片1 tags | **Seedance China surfaces** | Skip unless targeting those |
| Director's Read before prompt | **YES (process)** | Không cần Seedance model |

---

## 5. Vòng QA / retry / repair

### 5.1 seedance retake protocol — `references/retake-protocol.md:5-37`

| Verdict | When | Next |
|---|---|---|
| Keep | Primary spend delivered | Lock, move on |
| Fix in post | Color/text/sound/trim ends | Don't burn gens |
| Edit, don't regenerate | One layer wrong; surface supports edit | Change only failing layer |
| Re-roll | Prompt right, sample unlucky | Same prompt, new seed; max 2–3 then rewrite |
| Rewrite | Same flaw ≥2 takes | Diagnose mechanism, change prompt |

- **One-variable rule:** one clause OR seed OR mode OR one ref per retake.  
- **Attempt budget:** set before take 1; default 5 standard / 10 fast; at half budget no progress → change strategy.  
- Shot log: `Take N · changed: […] · seed: […] · verdict: […] · evidence: […]`  
- Sequence: accept / accept_with_deviation / repair / reject update canon differently.

### 5.2 seedance troubleshoot tree — excerpt `seedance-troubleshoot/SKILL.md:33-54`

Face/product drift → strengthen preserve, remove static re-describe.  
Camera jumps → one move.  
Continuation replay → completed beat exclusion.  
Future leak → reserved exclusion.  
Open motion lost → carry vector into opening sentence.

### 5.3 Orkas QA layers

| Layer | Tool | What |
|---|---|---|
| Structure plan | `ovs plan validate` | EDL schema + promise consistency |
| Promise (plan-time + produced) | `ovs plan promise-check` | motion_ratio vs floor; source_required; anti-slideshow |
| Compose draft | `ovs draft` + lint/check/snapshot | HyperFrames + media QA + frame evidence |
| Consistency stills | stage-consistency verify before animate | DNA axes |
| Assemble report | technical_probe, promise_preservation, visual_spotcheck, audio_spotcheck | Gate D |
| Repair budget | draft-repair-state pattern | same content signature → max failures then block |
| Send-back | max 2 rounds same failing check | then different strategy |

`assessDelivery` (`edl.ts:883-948`): motion_ratio on primary track; compose cards ≠ motion; default floors: motion_led 0.7, source_led 0.3, hybrid 0.2, compose_led 0; repetition run ≥3 same source → warn.

### 5.4 OmniCast đã port

- `pipeline/repair_budget.py` — content-keyed max failures (Orkas draft-repair).  
- `consistency_check.py` — still verify + re-roll.  
- `qa_check.py` — ffprobe streams, blank frames, motion helpers (OpenMontage + Orkas-inspired).  

**Chưa:** promise-check; plan validate; retake log structured per clip; gate A–D; send-back only-affected-segment assemble.

---

## 6. Tích hợp video-gen

### 6.1 seedance modes

T2V / I2V / V2V / R2V / FLF2V / edit / extend — **surface-specific**. Root skill: never invent endpoint/duration/tag from provider name; conservative generic profile if unknown.

Reference caps (field, surface-dependent): images ~9, videos ~3, audio ~3 (`reference-workflow.md:7-9`).

### 6.2 Orkas generate

- BYO providers (OpenAI/Gemini/Doubao); `ovs image` / `ovs video` / `ovs speak`.  
- Caps: ≤6 shots, ≤3 characters, one aspect ratio.  
- Talking-head: **keep built-in lip-synced audio**; never mux second TTS over speaking clip.  
- `variation_type` small/medium/large = keyframe cost gate.  
- Semantic edit: `operation:"edit"` + top-level references + edit_strategy; may_change only declared axes.

### 6.3 OmniCast

`media/veo_pipeline.py`: Flow first → Gemini Veo fallback; sticky provider demotion (Orkas-inspired); `build_motion_prompt` motion-only when seeded; `extract_last_frame`; durations 4/6/8.  
**GAP:** Flow convert() CHƯA nhận image (COMMON_CONTEXT); storyboard not wired to veo_pipeline; no R2V multi-role package for Flow Ingredients ≤14.

---

## 7. Pacing / timing

### 7.1 seedance

- One visible beat + endpoint per short clip.  
- Multi-shot inside one gen: `multishot-grammar` + shots-per-duration budget (referenced; not fully expanded here).  
- Sequence: plan global, generate local; clip `target_duration_sec` from surface budget.  
- Audio: unify music in post across gens; per-clip ambience/SFX/dialogue only.  
- Dialogue English: ~5–10 words/line; ~16–20 words reliable lip-sync in ~15s (`vocab/en.md:63-64`).

### 7.2 Orkas video-craft

- Hook 1–3s; arc hook→gap→core→proof→payoff/CTA.  
- Explainer holds ~4–8s; social ~1–3s; cinematic ~10–20s.  
- Narration: ~150–160 wpm explainer; fit via `ovs narration fit` before TTS.  
- Cadence English ~2.2–2.7 words/sec; Chinese ~4–5 chars/sec (`stage-plan`).  
- Loudness −14 LUFS, TP ≤ −1 dBTP.  
- Captions as **data** in plan → burn once at assemble (re-render captions without re-render picture).

### 7.3 OmniCast

TTS-driven scene durations in render_real_video; Veo clip lengths forced to 4/6/8.  
**Missing:** plan-level narration lines with per-line `produced_path` separability; motion_min_ratio for slideshow guard on AI b-roll montages.

---

## 8. Chi tiết nhỏ đáng học

### seedance

1. **Authority order 9 tiers** (safety > surface limits > user must-haves > ref contracts > continuity > physical causality > camera > style > skill defaults) — `SKILL.md:59-77`.  
2. **Never invent observation** of attachments you cannot open — corrupt sequence canon.  
3. **Fast lane** skips full gates for simple non-IP single clips → interview-short + prompt-short.  
4. **Compression order:** tags → identity → action/endpoint → camera → light → audio → constraints → sequence clauses (`prompt-short`).  
5. **prompt_lint.py:** golden prompts must be natural language (not JSON); require control-critical “why this remains”.  
6. **extract_last_frame.py** for continuation handoff.  
7. **Source-look lock** (phone UGC / livestream / dashcam / film / studio) embraces artifacts as style (`seedance-style`).  
8. **Negation summons** — only constrain positively except dedicated constraint slot.  
9. **felt_intent** never ships as emotion word; compiles to craft carriers.  
10. Progressive disclosure: root skill routes; sub-skills load on demand (agent context budget).

### Orkas

1. **plan.json is the checkpoint** — `status`/`produced_path` written back; resume skips done segments.  
2. **Captions/narration as data, not baked pixels** — typo fix = one line + re-burn.  
3. **Narration added EXACTLY ONCE** at assemble mix tier; compose segments silent in AUTO.  
4. **`--on-existing-audio reject`** default catches double-voice bug.  
5. **Gate C signs exact billable count** — `cost_estimate.billable_generations` must match generate segment count.  
6. **stdout = JSON result; stderr = progress** — agent-pipe safe.  
7. **MCP mirrors CLI 1:1** with snake_case tool names (`plan_validate`, `edit_trim`, …).  
8. **`ovs skill video-router`** dumps full skill text into context for agents without native skill loaders.  
9. **Ingest from evidence** — probe/OCR/transcript before plan; never invent slide content.  
10. **Slideshow is a hard fail** via numbers, not LLM judgment.

---

## 9. Câu hỏi riêng brief

### 9.1 “reads the scene before it writes the prompt” — pipeline là gì, code đâu?

**Không phải** một vision model pipeline riêng trong seedance-2.0. Là **procedural skill loop**:

```
1. Intake (goal, surface, refs, safety)          — SKILL.md Operating Loop step 1
2. Sequence Gate / Mode Gate                     — steps 4–5
3. Reference authority map                       — step 7
4. Direction: Director's Read (5 questions)      — references/directing-engine.md Step 1
   Function · Turn · POV · Power · Subtext
5. Coherence: one intention → camera/light/…     — directing-engine Step 2
6. Prompt build via seedance-prompt formula      — skills/seedance-prompt
7. Anti-slop + coherence self-check              — step 12
8. On take return: retake-protocol + observed_end_state update
```

**“Code”:** markdown skills + JSON schemas + Python validators (`scripts/prompt_lint.py`, `project_state_check.py`, `continuity_chain_check.py`, `extract_last_frame.py`). Agent executes the loop; repo does not call Seedance API for generation inside the skill OS.

**Observation Fast Path (continuation):** if client can open attached frame/clip → agent fills observation record from pixels; if not → say so, user describes, `observation_confidence: low` (`seedance-continuation/SKILL.md:53-57`).

### 9.2 Orkas plan.json → WS4 EDL re-render + WS1 storyboard contract

**Đề xuất áp dụng (không implement trong research này):**

#### A. Storyboard → Render Contract (WS1)

Introduce intermediate **clip contract** (seedance-shaped) bridging storyboard models → Veo:

```
Storyboard.Shot
  → ClipContract {
       narrative_job, felt_intent,
       generation_mode: t2v|i2v|r2v|flf2v,
       reference_roles (from binding.py),
       current_clip_action (motion-only if i2v),
       endpoint,
       already_happened / reserved_for_later,
       continuity_locks
     }
  → natural_language_prompt (compiler)
  → VeoClipSpec.motion_prompt + seed_image / ingredients
```

Files đích gợi ý: `storyboard/clips.py` or new `storyboard/prompt_compiler.py`; wire `render_real_video.py` + `veo_pipeline.py`.

#### B. Diffable EDL (WS4)

Adopt slim **OmniCast VideoEdl** (Orkas-compatible concepts, Python/Pydantic in vault or product dir):

```
output/products/{id}/plan.json
  aspect, total_target_sec, language
  delivery_promise: { type, source_required, motion_min_ratio }
  segments: [
    { id, order, role, layer, source: generate|edit|compose|tts_overlay|provided,
      target_sec, spec: { prompt?, seed_image?, veo_duration?, input_id?, in_sec?, out_sec? },
      status, produced_path }
  ]
  tracks: { narration: { segments: [{text, start_sec, target_sec, produced_path}] },
            music, captions: { lines: [...] } }
  cost_estimate: { billable_generations }
```

**Re-render semantics:** change one segment / one narration line → re-produce only that node + re-assemble dependents. Matches Orkas stage-assemble resume.

**promise-check port:** fail ship if AI montage motion_ratio under floor (anti-slideshow for YouTube automation).

**Compose line:** optional later — HyperFrames already in `_refs`; Orkas stage-compose is the contract if OmniCast wants HTML lower-thirds without FFmpeg drawtext soup.

#### C. MCP/CLI agent surface design (Orkas)

Principles to copy for OmniCast agent ops:

1. **CLI canonical, MCP mirror 1:1** — same verbs, JSON stdout.  
2. **Self-describing knowledge:** `ovs skills` / `ovs skill <name>` injects SKILL.md.  
3. **Deterministic validators before billable work:** plan validate → promise-check → gate.  
4. **Progress on stderr, result on stdout.**  
5. **Gate transition resolver** returns next_action / allowed_ops — agent never invents second confirmation FSM.  
6. Thin wrappers over ffmpeg/HyperFrames/whisper — knowledge in skills, not buried in CLI help only.

Suggested OmniCast surface (conceptual):

```
omnicast doctor
omnicast plan validate|summarize|promise-check
omnicast storyboard compile-prompt <shot>
omnicast render draft|final
omnicast qa video|consistency
omnicast skill router|prompt-craft|...
```

---

## 10. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện | Gap OmniCast | File đích gợi ý | Impact video quality | Effort |
|---|---|---|---|---|---|
| 1 | Director formula + compile order + clip-scope language | Prompt Veo/image still ad-hoc; storyboard not compiled | `storyboard/prompt_compiler.py`, `veo_pipeline.py` | **Rất cao** — face/product drift, generic look | M |
| 2 | I2V motion-only + dual Hold/React mode | Partial in veo_pipeline; not enforced from storyboard | `storyboard/frames.py`, `veo_pipeline.py` | Cao | S |
| 3 | Role isolation prose + preserve/may_change | binding.py has structure; need prompt sentence templates | `storyboard/binding.py`, prompt_compiler | Cao | S |
| 4 | Anti-slop 6 classes + opening position | slop.py exists — extend camera/light/audio + wire fail-closed pre-gen | `storyboard/slop.py` | Trung | S |
| 5 | Completed/reserved beat exclusions | No clip-scope exclusions in multi-shot Veo chain | `storyboard/clips.py`, continuity | Cao (replay/leak) | M |
| 6 | Retake protocol one-variable + take log | RepairBudget only; no creative triage | `pipeline/retake.py` + product status | Trung–Cao (cost) | M |
| 7 | Character three-tier multi-person hierarchy | Not in character prompts | Writer/storyboard extract prompts | Trung | S |
| 8 | Sequence max_chain_depth + re-anchor from canonical refs | extract_last_frame exists; no chain policy | `veo_pipeline.py`, storyboard pipeline | Cao identity decay | M |
| 9 | **plan.json VideoEdl** + validate + promise-check | No diffable re-render IR (WS4) | new `pipeline/edl.py` or `vault` product plan | **Rất cao** (ops + quality) | L |
| 10 | Captions/narration as data with per-line produced_path | Monolithic audio often | render path + tracks schema | Cao (iteration UX) | M |
| 11 | Delivery promise anti-slideshow | AI montage can ship static-looking | `qa_check` + plan assessDelivery port | Cao YouTube retention | M |
| 12 | stage-consistency bible + view-matched portraits | DNA check only; no multi-view anchor set | characters + consistency_check | Cao face consistency | M |
| 13 | Gate B/C for billable gen confirmation | 24/7 auto may skip; still useful for agent mode | API + agent skills | Cost control | M |
| 14 | IP-safe rewrite / filter vocab | ComplianceChecker rules; less prompt-craft rewrite | compliance + prompt_compiler | Policy + quality | S |
| 15 | Orkas compose HTML/GSAP for explainers | OmniCast FFmpeg+HTML overlay partial | future compose path | Medium (format diversity) | L |
| 16 | Agent CLI skill dump + MCP 1:1 | No agent-native surface | new CLI package | Dev velocity | M |
| 17 | video-craft hook/pacing/safe zones | Partial dashboard; not enforced in plan | craft checks in qa | Retention | M |
| 18 | Flow Ingredients ≤14 with explicit roles | COMMON_CONTEXT gap | Flow provider + binding | High when Flow image path lands | M |

**Priority stack for next builds:**

1. **P0:** prompt_compiler (1+2+3+5) — closes face-drift loop at language layer.  
2. **P0:** plan.json thin EDL (9+10+11) — enables WS4 re-render.  
3. **P1:** retake log + chain depth (6+8).  
4. **P1:** multi-view character bible (12).  
5. **P2:** agent surface + compose (15+16).

---

## 11. KHÔNG nên học + LICENSE

### Anti-patterns

| Anti-pattern | Why |
|---|---|
| Dump internal JSON into video model prompt | Seedance explicitly forbids; wastes budget, confuses model |
| Re-describe seed image static identity | Causes drift (source-carries-state inverted) |
| Stack many camera moves in 5s | Chaos / jitter |
| Emotion nouns without gestures | Unrenderable |
| Assume rights from uploaded likeness | Legal + filter |
| Silent primary-axis switch mid-run (Orkas) | Scope creep / wrong line |
| Bake narration into compose AND assemble mix | Double voice defect |
| Guess OCR/screen content without looking | Wrong voiceover |
| Infinite re-roll same prompt after 2–3 same flaws | Cost spiral |
| Port Seedance `@Image1` syntax into Gemini as-is | Wrong parser; use OmniCast tokens |
| Treat community field reports as platform guarantees | seedance labels many tips field-observed |

### LICENSE

| Repo | License | Implication |
|---|---|---|
| seedance-2.0 | **MIT** (`LICENSE`) | OK học + port concepts + adapt heuristics; keep notice if copying substantial text into product docs |
| Orkas-VideoStudio | **MIT** (`LICENSE`) | Same; repair_budget/consistency already cite MIT |

**Cả hai MIT → được port concept + adapt code với attribution.** Không AGPL. Vẫn: không copy nguyên SKILL.md dài vào production prompts without trimming; prefer implement as deterministic Python gates (pattern OmniCast đã làm với slop.py).

---

## 12. Map “đã port vs chưa port” Orkas (explicit)

| Orkas component | OmniCast status |
|---|---|
| draft-repair-state | **Ported** → `pipeline/repair_budget.py` |
| stage-consistency (still verify) | **Ported partial** → `consistency_check.py` |
| QA motion/blank helpers | **Ported partial** → `qa_check` |
| plan.json / validateEdl | **NOT** |
| assessDelivery / promise-check | **NOT** |
| stage-plan / stage-assemble | **NOT** |
| stage-compose HyperFrames | **NOT** (HyperFrames only as `_refs`) |
| stage-edit trim/concat/mix/burnsubs as IR | **NOT** (FFmpeg in render_real_video is monolithic) |
| gate-control A–D | **NOT** |
| video-router + skill pack install | **NOT** |
| MCP/CLI ovs surface | **NOT** |
| narration fit + per-line paths | **NOT** |
| character bible multi-view | **NOT** (DNA single-path) |

---

## 13. Seedance skill inventory (for completeness)

All under `skills/` with parent `seedance-20` v6.6.0:

`seedance-prompt`, `seedance-prompt-short`, `seedance-interview`, `seedance-interview-short`, `seedance-sequence`, `seedance-continuation`, `seedance-camera`, `seedance-lighting`, `seedance-motion`, `seedance-audio`, `seedance-characters`, `seedance-style`, `seedance-vfx`, `seedance-recipes`, `seedance-antislop`, `seedance-copyright`, `seedance-filter`, `seedance-pipeline`, `seedance-troubleshoot`, `seedance-examples-{zh,ja,ko}`, `seedance-vocab-{en,es,ja,ko,ru,zh}`.

---

## Đã đọc

### seedance-2.0
- `SKILL.md`
- `LICENSE`
- `skills/seedance-prompt/SKILL.md`
- `skills/seedance-prompt-short/SKILL.md`
- `skills/seedance-antislop/SKILL.md`
- `skills/seedance-copyright/SKILL.md`
- `skills/seedance-filter/SKILL.md`
- `skills/seedance-pipeline/SKILL.md`
- `skills/seedance-interview/SKILL.md`
- `skills/seedance-interview-short/SKILL.md`
- `skills/seedance-camera/SKILL.md`
- `skills/seedance-characters/SKILL.md`
- `skills/seedance-lighting/SKILL.md`
- `skills/seedance-motion/SKILL.md`
- `skills/seedance-audio/SKILL.md`
- `skills/seedance-style/SKILL.md`
- `skills/seedance-sequence/SKILL.md`
- `skills/seedance-continuation/SKILL.md`
- `skills/seedance-troubleshoot/SKILL.md`
- `skills/seedance-recipes/SKILL.md`
- `skills/seedance-vfx/SKILL.md`
- `references/anti-slop-lexicon.md`
- `references/filter-vocab.md`
- `references/i2v-guide.md`
- `references/reference-workflow.md`
- `references/quick-ref.md`
- `references/retake-protocol.md`
- `references/prompt-compiler.md`
- `references/first-last-frame-guide.md`
- `references/directing-engine.md` (partial)
- `references/vocab/en.md`
- `schemas/prompt-spec.schema.json`
- `schemas/clip-contract.schema.json`
- `schemas/project-state.schema.json` (partial)
- `examples/golden-prompts/compact-i2v.md`
- `examples/golden-prompts/r2v-role-isolation.md`
- `examples/sequence-airport-arrival/clip-01-prompt.md`
- `scripts/prompt_lint.py`

### Orkas-VideoStudio
- `README.md`
- `AGENTS.md`
- `LICENSE`
- `packages/core/src/ir/edl.ts` (full)
- `packages/cli/src/index.ts` (large partial)
- `packages/mcp/src/index.ts` (partial)
- `packages/skills/video-router/SKILL.md`
- `packages/skills/stage-plan/SKILL.md`
- `packages/skills/stage-compose/SKILL.md`
- `packages/skills/stage-edit/SKILL.md`
- `packages/skills/stage-generate/SKILL.md`
- `packages/skills/stage-assemble/SKILL.md`
- `packages/skills/stage-consistency/SKILL.md`
- `packages/skills/gate-control/SKILL.md`
- `packages/skills/video-craft/SKILL.md`

### OmniCast (map gap)
- `implementation/src/omnicast/pipeline/repair_budget.py`
- `implementation/consistency_check.py`
- `implementation/qa_check.py`
- `implementation/src/omnicast/storyboard/slop.py`
- `implementation/src/omnicast/storyboard/binding.py`
- `implementation/src/omnicast/media/veo_pipeline.py`
- `docs/research/_briefs/COMMON_CONTEXT.md`
- `docs/research/_briefs/05_seedance_orkas.md`

### Chưa mở sâu (round sau nếu cần)
- seedance: `multishot-grammar.md`, `model-mechanics.md`, `allocation-model.md`, full `sequence-project-state.md`, all golden prompts, all vocab non-EN, migrated originals
- Orkas: `tools/src/edit/edit.ts`, `tools/src/render/*`, composition-design-review, frontend-design skill, decide/admission gates code

---

*End of REFS_SB_05_Seedance_Orkas.md*
