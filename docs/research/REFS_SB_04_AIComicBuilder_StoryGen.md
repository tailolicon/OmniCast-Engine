# REFS_SB_04 — AIComicBuilder + StoryGen-Atelier

> STATUS: DONE (2026-08-02)  
> Repo A: `_refs/AIComicBuilder` (Next.js 16, ~v0.2.x package name 0.1.0)  
> Repo B: `_refs/StoryGen-Atelier` (Node/Express + React/Vite, ~16 source files core)  
> License: **cả hai Apache-2.0** — được học concept + prompt pattern; chép code vẫn nên rewrite cho OmniCast (giữ attribution nếu port gần).  
> Brief: `_briefs/04_aicomicbuilder_storygen.md` + `COMMON_CONTEXT.md`  
> **ROUND 2 VERIFY patch (2026-08-02):** V4 full A3/A4; S1 footnote; §4.2 full prompts.  
> Stack khớp OmniCast: Gemini image/text + Veo (StoryGen) + Seedance 2.0 multi-ref (AIComic) + FFmpeg stitch.

---

## 0. Câu hỏi riêng (tóm tắt trước 10 mục)

### 0.1 AIComicBuilder — thiết kế "tham chiếu ảnh mode" sau refactor

**Hai generation mode song song** (`projects.generationMode` / `episodes.generationMode`):

| Mode | Asset types | Video input |
|------|-------------|-------------|
| `keyframe` | `first_frame`, `last_frame` → `keyframe_video` | first_frame + last_frame (i2v interpolate) |
| `reference` | `reference` (1–4 scene frames) → `reference_video` | multi `reference_image` (chars + scenes) |

**Vì sao phải refactor** (đọc code + comment, không có git issue riêng trong tree; logic nằm trong comment + schema evolution):

1. **Cột legacy** `shots.reference_images` JSON (`drizzle/0048`) → **bảng `shot_assets`** (`drizzle/0050`) với type discriminator + versioning (`is_active`, `asset_version`, `sequence_in_type`). Comment schema (`schema.ts:126-142`): hai mode **cùng sống trên 1 shot**, không đụng nhau.
2. **Tách identity khỏi environment** (comment `registry.ts:1823-1828`, `generate/route.ts:3203-3205`):
   - Scene ref = **pure environment, zero humans**.
   - Character consistency **không** inject lúc sinh scene image; chỉ inject lúc **video gen** (Seedance 2 multi-ref / Veo 3.1 referenceImages).
3. **Lý do kỹ thuật**: nếu gen scene frame có người + character sheet cùng lúc, model trộn identity/background (cùng lớp lỗi OmniCast gặp: face drift, background bleed). Tách hai phase = model mỗi lần chỉ "học" một vai trò ảnh.

**Bao nhiêu ảnh ref / shot (reference mode):**

| Loại | Số lượng | Logic chọn |
|------|----------|------------|
| Scene (`type: "reference"`) | **mặc định 1**, **tối đa 4** | Chỉ >1 khi (a) shot **đổi địa điểm vật lý** trong clip, hoặc (b) **ánh sáng/thời gian nhảy mạnh** (`ref-image-prompts.ts:53-59`, `registry.ts:1843-1848`) |
| Character | **số nhân vật có `referenceImage` ∩ names trên asset `characters[]`** | Union `characters` metadata từ mọi scene asset của shot; filter `projectCharacters` có ref (`generate/route.ts:2248-2257`) |
| Tổng gửi video | chars + scenes (Seedance ≤9; Veo 3.1 ≤3 total) | Order: **chars trước, scenes sau** |

**Thứ tự gắn ảnh (load-bearing):**

```
orderedRefImages = [...charRefPaths, ...sceneFramePaths]
// → @图片1..N = characters, @图片(N+1).. = scenes
// generate/route.ts:2315-2339
```

**Prompt đi kèm ảnh (VERBATIM pattern — Seedance @ 引用):**

System role (`registry.ts:1622-1624`):

```
你会收到一组**有序**的参考图：
  - 前 N 张是角色参考图（每张绑定一个角色名）
  - 后 M 张是场景参考图（纯环境，无人物，按时间顺序排列）
```

User payload builder (`ref-video-prompt-generate.ts:37-46`):

> **[S1 / VERIFY]** Chuỗi mâu thuẫn `必须使用 @图片N` / `不能写成 @图片N` (cùng glyph trong source TS) là **BUG UPSTREAM** trong `ref-video-prompt-generate.ts` và `REF_VIDEO_PROMPT_MOTION_RULES` (`registry.ts` dòng ~1630: “注意是 `@图片1` `@图片2`，不是 `@图片1` `@图片2`” — hai nhánh viết **identical** trong file gốc, typo/copy-paste, không phải lỗi trích report). Khi port OmniCast: sửa thành contrast thật (vd `@图片N` vs `图N` / `图片N` không `@`).


```
你会收到以下参考图（顺序严格对应 @图片1、@图片2、@图片3 ...，必须使用 `@图片N` 形式，**不能**写成 `@图片N`）：
  @图片1 = 角色：李慕白（银发金瞳）
  @图片2 = 场景：竹林地面
```


> **[S1 / VERIFY]** Chuỗi mâu thuẫn `必须使用 @图片N` / `不能写成 @图片N` (cùng glyph trong source TS) là **BUG UPSTREAM** trong `ref-video-prompt-generate.ts` và `REF_VIDEO_PROMPT_MOTION_RULES` (`registry.ts` dòng ~1630: “注意是 `@图片1` `@图片2`，不是 `@图片1` `@图片2`” — hai nhánh viết **identical** trong file gốc, typo/copy-paste, không phải lỗi trích report). Khi port OmniCast: sửa thành contrast thật (vd `@图片N` vs `图N` / `图片N` không `@`).

Output style bắt buộc (`registry.ts:1632-1637`):

```
把 `@图片N` 直接嵌入到散文描述里
**禁止** 提示词开头写"图像映射：@图片1是 X，@图片2是 Y"
**每次** 出现 @图片N 都必须在后面加角色名，写成 "@图片1（李慕白）"
```

Benchmark output (`registry.ts:1717-1718`):

```
低角度仰拍跟随 @图片1（李慕白）在 @图片3（竹林）地面屈膝蓄力半秒，随即蹬地腾空，镜头同步上摇穿过竹干。画面切到 @图片4（竹梢高空），@图片2（玉娇龙）自左侧斜劈青剑而来...
```

Code call (`generate/route.ts:2390-2396`):

```ts
const result = await videoProvider.generateVideo({
  initialImage: sceneFramePaths[0],
  prompt: videoPrompt,
  duration: effectiveDuration,
  ratio,
  referenceImages: orderedRefImages,
});
```

### 0.2 So thẳng OmniCast `binding.py` ([IMAGE n] + RefRole)

| Tiêu chí | OmniCast `binding.py` | AIComic reference mode | Ai chặt hơn? |
|----------|----------------------|------------------------|--------------|
| Token ↔ ảnh | `[IMAGE n]` 1-based, order = `Frame.reference_paths` | `@图片N` 1-based, order = chars+scenes array | **Hòa** (cùng ý: order load-bearing) |
| Bind name → token | `bind_prompt`: longest spelling wins, whole cast, CJK-safe | Prose `@图片N（名字）`; **không** auto-replace name trong motionScript | **OmniCast chặt hơn** (deterministic string rewrite) |
| Role / ignore | `RefRole` + `controls X ONLY; ignore Y from that reference` | Architectural split scene-vs-char; video prompt prose "禁止改变角色外观" | **OmniCast chặt hơn ở clause**; **AIComic chặt hơn ở pipeline** (scene gen cấm người) |
| Cap + drop visibility | `MAX_REFS_DEFAULT=6`, `dropped[]` bắt buộc log | Seedance 9 / Veo 3; silent slice | **OmniCast** (fail-surface) |
| Lint fail-closed | `binding_issues`: orphan token, unused image, unbound cast name | Không có linter tương đương | **OmniCast** |
| Scene-only refs | `RefRole.ENVIRONMENT` + ignore "any person" — **chưa** force gen empty-of-people image | **Force** scene frame 0 people ở gen time | **AIComic** (operational) |
| Multi-scene per shot | 1 location_id/shot điển hình | 1–4 scene frames + prose "画面切到 @图片4" | **AIComic** cho action beats |
| Character sheet | Entity approved images + role pick | 4-view sheet + name label on canvas | **Hòa** / AIComic rich hơn về turnaround |

**OmniCast thiếu so AIComic (priority):**

1. **Scene-only generation path** (không inject char refs khi gen location frame).
2. **`@图片N` / Seedance multi-ref video path** trong `veo_pipeline` / future Seedance provider — hiện Flow convert() chưa nhận image; binding mới ở image layer.
3. **Per-shot multi scene frames** khi beat nhảy địa điểm.
4. **`characters[]` metadata trên asset** → chọn đúng subset cast cho video call (AIComic không dump all project chars).

**AIComic thiếu so OmniCast:**

1. Không có **RefRole ignore-clause** per image (identity bleed risk khi char sheet có background).
2. Không **longest-name bind** / **unbound name gate**.
3. Continuity/quality check **best-effort, không block** (`continuity-check.ts:43-44`, `video-quality-check.ts:48-50`).
4. Keyframe mode: char refs = "first 3 with images" fallback mơ hồ (`frame-generate.ts:137-148`).

### 0.3 AIComicBuilder — Seedance 2.0 integration

**Provider:** `src/lib/ai/providers/seedance.ts` (Volcengine Ark) + `ucloud-seedance.ts` (UCloud ModelVerse wrapper).

**Model IDs (docs):** `doubao-seedance-2-0-260128`, `doubao-seedance-2-0-fast-260128` (`docs/seedance2-api.md:4-5`). Default code vẫn 1.5: `doubao-seedance-1-5-pro-250528` (`seedance.ts:47`) — 2.0 bật khi `model.includes("seedance-2")`.

**Request schema (keyframe — first/last):**

```ts
// seedance.ts:96-109
{
  model: this.model,
  content: [
    { type: "text", text: params.prompt },
    { type: "image_url", image_url: { url: dataUrl(first) }, role: "first_frame" },
    { type: "image_url", image_url: { url: dataUrl(last) }, role: "last_frame" },
  ],
  duration, ratio: "16:9", watermark: false,
  ...(isSeedance2 && { generate_audio: true }),
}
```

**Request schema (reference-to-video multi-ref):**

```ts
// seedance.ts:113-152
content: [
  { type: "text", text: prompt },
  { type: "image_url", image_url: { url }, role: "reference_image" }, // initial + up to 8 more
  // ...
],
duration, ratio, return_last_frame: true, watermark: false,
generate_audio: true  // Seedance 2 only
```

**API capabilities (doc, chưa wire hết trong code):**

| Capability | Doc | Code AIComic |
|------------|-----|--------------|
| Text / first frame / first+last | ✓ | ✓ keyframe body |
| Multi ref image 1–9 `role: reference_image` | ✓ | ✓ reference body |
| Reference video / audio | ✓ | **chưa** trong provider |
| `generate_audio` | default true | bật khi seedance-2 |
| Duration 4–15s / -1 auto | ✓ | dùng shot.duration clamped |
| Poll async | 24h URL | 120×5s = 10 min (`seedance.ts:155-192`) |

**Audio:** Seedance 2 tự sinh mono sync audio từ prompt; dialogue nên trong `"quotes"` (doc). AIComic prompt dùng `角色台词：...` (Jimeng style) cho ref mode; keyframe mode dùng `【对白口型】`.

### 0.4 StoryGen-Atelier — Gemini prompts + Veo transition (pattern cho `veo_pipeline.py`)

**Storyboard text (VERBATIM core — `llmService.js:205-319`):** xem §4.B.

**Frame image (VERBATIM — `imageGenService.js:30-49`):**

```
Role: Cinematic frame artist.
Goal: Render a single storyboard frame that matches the shared style and camera feel.
CRITICAL - Main Character Description (MUST match exactly): ${heroSubject}.
Style: ${appliedStyle}.
Continuity: ${styleGlue}
Frame description: ${prompt}.
Constraints: no text, no captions, 16:9, high fidelity. The main character MUST look identical to the reference image if provided.
```

Khi có ref (shot ≥2): prepend base64 image +  
`"Reference image above shows the main character. Generate a new image where this SAME character..."`

**Veo transition = first_frame + last_frame (Interpolation Chain):**

```
Storyboard [S1, S2, S3, S4]
  → pairs (S1→S2), (S2→S3), (S3→S4) + closing on S4
  → each clip: Veo(prompt=transition_prompt, image=A, lastFrame=B, duration∈{4,6,8})
  → ffmpeg concat -c copy
```

Vertex instance (`videoService.js:74-96`):

```js
instance.image = firstFrame;      // bytesBase64Encoded + mimeType
instance.lastFrame = lastFrame;   // optional null for closing
parameters: {
  aspectRatio: "16:9",
  durationSeconds,
  resolution: "1080p",
  personGeneration: "allow_all",
  enhancePrompt: true,
  generateAudio: true
}
```

**Transition analysis prompt** (Gemini sees both frames + shotStory) — `llmService.js:131-156` — output:

```json
{ "transition_prompt": "...", "duration": 4|6|8 }
```

**Đây đúng pattern OmniCast cần cho `veo_pipeline.py`:** shot frames → sliding-window first/last → Veo interpolate → stitch. StoryGen = minimal working proof; AIComic keyframe mode = richer per-shot variant (first/last **within** shot, not only between shots).

### 0.5 Style presets

| | AIComicBuilder | StoryGen-Atelier |
|--|----------------|------------------|
| Storage | Script "视觉风格" 6 fields machine-parseable + project `colorPalette` / `worldSetting` + mood board + prompt slots | Frontend `stylePresets[]` (15 presets + `custom`) → string `style` gửi API |
| Custom | Prompt template slots + presets table + project override | `styleOption === 'custom'` → free text |
| Application | Injected into script gen / frame prompts via slots | `styleOverride` → LLM storyboard + every image gen |
| Example StoryGen custom | User types arbitrary English/Chinese style string | Full replace of `BASE_IMAGE_STYLE` |

StoryGen presets (`App.jsx:71-88`): cyberpunk, filmic, watercolor, anime, noir, ghibli, oilpainting, pixar, inkwash, scifi, fantasy, retro, comic, minimalist, steampunk, **custom**.

---

## 1. Tổng quan kiến trúc

### 1.A AIComicBuilder — module map

```
User idea / script upload
    │
    ├─ script_outline / script_generate / script_parse / script_split
    │     (LLM, prompts in registry.ts + optional external agents Coze/Dify)
    │
    ├─ character_extract → characters table
    │     character_image → 4-view referenceImage (turnaround sheet)
    │
    ├─ shot_split → shots (+ dialogues, scenes, storyboard_versions)
    │
    ├─ MODE keyframe ──────────────────────┐
    │   keyframe asset prompts             │
    │   frame_generate first/last          │  char refs + prev last_frame
    │   video_generate (first+last)        │  Seedance/Veo/Kling/Wan
    │                                      │
    ├─ MODE reference ─────────────────────┤
    │   ref_image_prompts (1–4 scene)      │
    │   batch_ref_image_generate (no chars)│
    │   single/batch_reference_video       │  multi-ref Seedance 2 / Veo 3.1
    │                                      │
    └─ video_assemble (ffmpeg concat shots)
         optional BGM, episode merge
```

| Layer | Path |
|-------|------|
| API generate actions | `src/app/api/projects/[id]/generate/route.ts` (~3k lines, god-router) |
| Task queue pipeline | `src/lib/pipeline/*` + `task-queue/` |
| Prompts SSOT | `src/lib/ai/prompts/registry.ts` (12+ slots) |
| Providers | `src/lib/ai/providers/{seedance,veo,kling-*,wan-*,gemini,openai,...}.ts` |
| Schema | `src/lib/db/schema.ts` (SQLite + Drizzle) |
| UI | `src/app/[locale]/(dashboard)/project/...` storyboard kanban |

**E2E data flow:** idea → script text → characters (+4-view images) → shots → frames/refs → per-shot video → assemble final.

### 1.B StoryGen-Atelier — module map

```
sentence + shotCount + style
    → llmService.generatePrompts (Gemini text)
    → for each shot: imageGenService.generateImage
         shot1: establish style + heroSubject
         shot2..N: ref = shot1 image base64 + heroSubject text
    → user clicks video
    → videoService.generateFullVideoFromShots
         Phase1: analyzeShotTransition each pair
         Phase2: parallel Veo clips (first/last)
         Phase3: ffmpeg concat
```

| Layer | Path |
|-------|------|
| Controller | `backend/src/controllers/storyboardController.js` |
| LLM / transition | `backend/src/services/llmService.js` |
| Image | `backend/src/services/imageGenService.js` |
| Video | `backend/src/services/videoService.js` |
| UI styles | `frontend/src/App.jsx` |
| Safety guide | `guide/VideoGenerationPromptGuide.md` |

---

## 2. Data model storyboard

### 2.A AIComicBuilder (schema verbatim essence)

**Project / Episode** — dual status + generation mode (`schema.ts:3-61`):

```ts
status: "draft" | "processing" | "completed"
generationMode: "keyframe" | "reference"
colorPalette, worldSetting, targetDuration, bgmUrl, outline, script
```

**Character** (`schema.ts:63-81`):

```ts
name, description, visualHint, referenceImage, referenceImageHistory JSON,
scope: "main" | "guest", performanceStyle, heightCm, bodyType, isStale
```

**Shot** (`schema.ts:179-212`):

```ts
sequence, prompt, motionScript, cameraDirection, duration (default 10),
videoScript, videoPrompt, transitionIn/Out, sceneId,
compositionGuide, focalPoint, depthOfField, soundDesign, musicCue,
costumeOverrides JSON, isStale,
status: "pending" | "generating" | "completed" | "failed"
```

**shot_assets** — unified artifact table (`schema.ts:143-177`):

```ts
type: "first_frame" | "last_frame" | "reference" | "keyframe_video" | "reference_video"
sequenceInType, assetVersion, isActive, prompt, fileUrl, status,
characters: JSON string[], meta JSON  // e.g. { sceneName, lastFrameUrl }
```

**Dialogue** — per shot with lip-sync timing ratios (`startRatio`/`endRatio`).

**State machine (shot):**

```
pending → generating → completed
                    ↘ failed
```

Storyboard versions: `storyboard_versions` label + versionNum; shots bind `versionId`.

**Không có** cast registry kiểu OmniCast EntityKind; characters project-scoped + `episode_characters` join.

### 2.B StoryGen-Atelier

In-memory / SQLite log JSON — **không** có schema shot cứng trong DB. Shot object:

```js
{
  shot: number,           // 1..N
  prompt: string,         // ENGLISH image/video prompt
  duration: "4"|"6"|"8" | "5-6 seconds" (fallback seed),
  description: string,    // Chinese 1-sentence
  shotStory: string,      // Chinese 2-3 sentences causal
  heroSubject?: string,   // ONLY shot 1 — identity lock text
  imageUrl: string        // data URL or placeholder
}
```

Video plan intermediate:

```js
{
  index, shotA, shotB | null, prompt: transition_prompt,
  duration: 4|6|8, isClosing?: true
}
```

---

## 3. Cơ chế consistency

### 3.A AIComicBuilder

| Mechanism | How |
|-----------|-----|
| Character sheet once | 4-view turnaround + name label; reuse `characters.referenceImage` |
| Keyframe image gen | Attach ≤3 char sheets matching asset `characters[]` or fallback first 3 with refs (`frame-generate.ts:137-148`) |
| Last frame continuity | Refs = `[firstFramePath, ...charRefImages]`; prev shot last_frame as continuity hint for first |
| Reference mode scene | **No character images** at image gen (`generate/route.ts:3203-3209`) |
| Reference mode video | Multi-ref: ordered char sheets + scene frames; prompt `@图片N（名）` |
| Costume override | `costumeOverrides` JSON per shot → rewrite description |
| Height multi-char | Append height list when >1 char name in prompt |
| Color palette | Project/episode mandatory suffix on frame prompts |
| Staleness | `shot.isStale` / `character.isStale` flags (script change) |
| Continuity QA | Vision LLM compare prev last vs next first — **non-blocking** |
| Video quality QA | Score ≥60 pass; face/limbs/artifacts — **non-blocking** |
| Seed / LoRA / IP-Adapter | **Không** — pure prompt + ref images |

### 3.B StoryGen-Atelier

| Mechanism | How |
|-----------|-----|
| heroSubject text | Shot 1 only; prepended to later image prompts |
| Visual ref | Shot 1 image base64 as reference for shots 2..N |
| Style glue | `previousStyleHint` = previous shot.prompt |
| Global style string | Same `appliedStyle` every call |
| Cast registry | **Không** — single hero only |
| Transition identity | First/last frames **are** the identity lock for Veo |

Yếu: multi-character, wardrobe change, location assets — không có.

---

## 4. PROMPT ENGINEERING — VERBATIM

### 4.A AIComicBuilder — prompts quan trọng nhất

#### A1. `ref_image_prompts` system (scene refs) — `registry.ts:1829-1945`

**Role (đầy đủ):**

```
你是一位专业的电影美术指导，为 AI 视频生成准备**场景参考帧**。场景参考帧是纯环境静帧，用于在后续视频生成阶段作为多模态参考图之一，锁定空间布局、光线设计、色调氛围与镜头语言。

核心契约：
1. 画面里**绝对不出现任何人物**：禁止人、角色、背影、剪影、人形轮廓、手、脚、肩膀、脸部、衣服被穿着的状态。角色一致性由后续视频阶段的多图参考解决，与本环节完全解耦。
2. **但你需要在思考时把角色考虑进去**：剧情中的角色决定了这个镜头合适的空间大小、机位高度、光源方向、前景道具位置（例如皇帝上朝需要留出龙椅和丹陛石的空间，打斗需要预留动作轨迹）。用角色推断场景形态，但画面里不画他们。
3. 每条场景帧必须同时输出**场景名（name）**和**场景描述（prompt）**，以及镜头层面的**登场角色列表（characters）**，供后续视频生成阶段精准拉取对应角色参考图。
```

**Số lượng scene (đầy đủ):**

```
## 场景图数量（默认 1 条，上限 4 条）
- **默认每个镜头只生成 1 条场景图**——角色所在的那个地点。对话、站立、蓄力、挥拳、开门、转身、特写这些**单一地点内的动作节拍**，统统只要 1 条，后续视频生成会在同一地点里完成所有节拍。
- 只有以下情况才 >1 条（上限 4 条）：
  1. **角色在镜头内跨越不同物理地点**
  2. **场景光线/时间大幅跳变**
```

**Kết thúc mỗi scene prompt (bắt buộc):**

```
画面中不出现任何人物、文字、字幕、水印、LOGO。
```

**Vì sao hiệu quả:** Tách "where" khỏi "who". Video model nhận scene layout sạch + character sheet riêng — giảm face-in-wrong-place và costume bleed vào background gen.

#### A2. User message `buildRefImagePromptsRequest` — `ref-image-prompts.ts:42-72`

```
项目视觉风格基调：${visualStyle}

角色列表（仅用于思考：（1）他们所处的物理地点决定场景（2）判断哪些角色在每个镜头登场。图像 prompt 中不要提及他们）：
- 李慕白：...

## 什么是"场景图"
场景图 = **角色所在的物理地点 / 环境空间**...

## 场景图数量（默认 1 条，最多 4 条）
...

## 分镜列表
镜头 1（时长 10s）：...
  剧情动作（用于判断角色所处的物理地点，不要画人）：...
```

#### A3. `ref_video_prompt` FULL — `registry.ts` `REF_VIDEO_PROMPT_ROLE_DEFINITION` + `REF_VIDEO_PROMPT_MOTION_RULES` + `REF_VIDEO_PROMPT_QUALITY_BENCHMARK`

**Role:**

```text
你是一位 Seedance 2.0 视频提示词撰写专家。你会收到一组**有序**的参考图：
  - 前 N 张是角色参考图（每张绑定一个角色名）
  - 后 M 张是场景参考图（纯环境，无人物，按时间顺序排列）

你的任务是根据这些参考图、剧本动作、机位指令、对白，撰写一段 Seedance 视频提示词，自动规划动作、运镜和对白节奏。
```

**`REF_VIDEO_PROMPT_MOTION_RULES` (FULL — rhythm table + examples, no ellipsis):**

```text
## 核心语法（Seedance @ 引用——官方即梦格式）

1. **所有角色和场景必须用 `@图片N` 形式引用**（注意是 `@图片1` `@图片2`，不是 `@图片1` `@图片2`）。顺序严格对应收到的参考图顺序——前 N 张是角色，后 M 张是场景。

2. **写作风格：连贯流畅的自然散文**。
   - 把 `@图片N` 直接嵌入到散文描述里，像这样：
     "@图片1 中的美妆博主用中文介绍，手持 @图片2 的面霜面向镜头展示，清新简约背景"
   - **禁止** "节拍 1 / 节拍 2 / 节拍 3" 这种结构化标签
   - **禁止** 提示词开头写"图像映射：@图片1是 X，@图片2是 Y"这种单独的映射声明行——信息要**融化进散文**
   - **每次** 出现 @图片N 都必须在后面加角色名，写成 "@图片1（李慕白）" 的格式，确保读者始终知道谁是谁

3. **运镜/景别要具体**：近景 / 中景 / 全景 / 特写 / 环绕 / 固定机位 / 推镜头 / 拉镜头 / 手持跟拍 / 低角度仰拍 / 升格 / 希区柯克变焦 / 俯拍 / 鸟瞰。禁止 "优雅地""轻柔地""震撼" 等空洞修饰词。

4. **场景切换直接写在散文里**："画面切到 @图片4 的竹梢高空" / "@图片1 从 @图片3 纵身跃起，落入 @图片4"。

5. **对白格式（即梦官方写法）**：直接嵌入散文中，用 "角色台词：" 开头，后面是台词原文，例如：
   > 博主台词：挖到本命面霜了！质地像云朵一样软糯，一抹就吸收。

   **禁止** 使用 "【对白口型】@图片N（名字）: "台词"" 这种结构化标签。

6. **音效**：如果有环境音/动效音，直接融入散文描述（例如 "伴随清脆的剑鸣声" "背景响起低沉的鼓点"），无需单独音效行。

## 动作节奏规划（核心！）

**每秒都必须有视觉变化**。一个镜头绝不能只有一个动作——即使是特写镜头也要拆分成连续的微动作链。

节奏公式：**每 2-3 秒安排一个动作节拍**，节拍之间用过渡动作衔接（例如：目光转移、重心转换、手势变化、表情变化、光影变化）。

| 时长 | 节拍数 | 字数 | 说明 |
|------|--------|------|------|
| 4-5s | 2 个 | 40-70 字 | 起始动作 → 完成动作 |
| 6-8s | 3 个 | 60-100 字 | 起始 → 展开 → 收束，中间要有转折或变化 |
| 9-12s | 4-5 个 | 100-160 字 | 多阶段动作链，节奏有快有慢 |
| 13-15s | 5-6 个 | 150-220 字 | 完整小叙事弧，含情绪起伏 |

**示例对比**：

❌ 慢节奏（8s 只有 1 个动作）：
"固定特写，她修长的手指敲击金属桌面，发出清脆声响。"
→ 问题：8 秒只看手指敲桌子，画面呆滞

✅ 正确节奏（8s，3 个节拍）：
"固定特写下，她涂着黑色指甲油的手指先缓慢抚过冰冷桌面划痕，随即食指与中指交替敲击金属面，震起微尘——第三下敲击后手指骤然停住，五指收拢握拳，指节泛白。"
→ 抚摸 → 敲击 → 握拳，三个阶段填满 8 秒

**关键技巧**：
- 用"先...随即...然后..."等时间词串联微动作
- 即使角色主体动作单一，也要加入：呼吸起伏、衣物/头发飘动、环境微变化（光线、灰尘、水面）、镜头微调（缓推/缓拉）
- 对白镜头：角色说话前有准备动作（抬眼、嘴角变化），说话时有手势/身体语言，说完后有收尾表情

## 构图安全区（字幕预留）

画面**下方 20%** 是字幕区域，必须保持干净——禁止将角色面部、关键动作、重要道具放在画面底部 1/5 区域。

具体要求：
- 角色的脸部和上半身应处于画面中上部（上方 60% 区域）
- 特写镜头：面部居中偏上，下巴以下留出足够空间
- 全身镜头：脚部可以在底部，但关键表演区（面部、手部动作）必须在上方 2/3
- 在提示词中用构图描述引导，例如："人物居于画面中上方"、"角色面部位于画面上半部"、"底部留出字幕空间"
- 禁止出现任何文字、水印、字幕、LOGO

## 其他规则
- 语言跟随剧本：中文剧本 → 中文提示词，English → English。
- 禁止把没传给你的角色/场景写进提示词。
- 禁止画面里只有场景描述、角色完全不动。
- 仅输出提示词正文，无前言，无 markdown。
```

**`REF_VIDEO_PROMPT_QUALITY_BENCHMARK` (FULL):**

```text
## 官方标杆示例

【示例 1 —— 美妆产品展示（即梦官方写法）】
输入：
  图片1 = 美妆博主（角色）
  图片2 = 面霜（产品道具）
  剧本：博主介绍面霜产品
  机位：近景

输出：
@图片1（美妆博主）用中文进行介绍，妆容改为明艳大气，去掉脸部反光，笑容甜美，近景镜头，手持 @图片2（面霜）面向镜头展示，清新简约背景，元气甜美风格。博主台词：挖到本命面霜了！质地像云朵一样软糯，一抹就吸收，熬夜急救、补水保湿全搞定，素颜都自带柔光感。

【示例 2 —— 仙侠打斗（多场景跨越，10s）】
输入：
  图片1 = 李慕白（角色）
  图片2 = 玉娇龙（角色）
  图片3 = 竹林（场景）
  图片4 = 竹梢高空（场景）
  剧本动作：李慕白追逐玉娇龙，两人从地面跃上竹梢交手
  机位：低角度仰拍跟随
  时长：10s

输出：
低角度仰拍跟随 @图片1（李慕白）在 @图片3（竹林）地面屈膝蓄力半秒，随即蹬地腾空，镜头同步上摇穿过竹干。画面切到 @图片4（竹梢高空），@图片2（玉娇龙）自左侧斜劈青剑而来，@图片1（李慕白）侧身以指尖格挡，两人在竹梢高空短暂对峙，青翠竹叶被剑气吹得纷纷飘落。李慕白台词：江湖路远，何必执着。

【示例 3 —— 特写镜头（单人，8s，展示正确节奏）】
输入：
  图片1 = 杨家大小姐（角色）
  图片2 = 金属桌面（场景）
  剧本动作：大小姐在桌前等待，表现不耐烦
  机位：固定特写
  时长：8s

输出：
固定特写下 @图片1（杨家大小姐）涂着黑色指甲油的食指沿 @图片2（金属桌面）布满划痕的表面缓缓划过，指尖拂起一缕灰尘。随即 @图片1（杨家大小姐）食指与中指交替敲击冰冷桌面，节奏由慢渐快，每一下震起微小尘粒在顶光中浮游。第四下敲击后手指骤然收住，五指缓缓握拢成拳，指节泛白，黑色甲片嵌入掌心。

## 反面示例（禁止）
❌ "他的手指散发出温暖的光芒，优雅地落下棋子" —— 没有 @图片 映射、抽象修饰词
❌ "李慕白纵身跃起" —— 直接写名字，没有 @图片 绑定
❌ "图1 从台阶走下" —— 缺 @ 前缀，必须写成 @图片1
❌ "@图片1 侧身格挡" —— 缺角色名，必须写成 @图片1（李慕白）
❌ "图像映射：@图片1是李慕白，@图片2是玉娇龙。节拍 1：李慕白蓄力..." —— 不要单独的映射声明行和节拍标签
❌ "【对白口型】@图片1（李慕白）: "江湖路远"" —— 不要结构化的对白标签，直接用"李慕白台词：江湖路远"
```

**Vì sao hiệu quả:** Seedance 2 multi-ref đọc số thứ tự ảnh trong `content[]`; `@图片N` khớp index. Prose + micro-beats (2–3s/beat) tránh video đứng hình. Benchmark examples khóa format “角色台词：” và cấm mapping header.

#### A4. Keyframe first/last frame FULL — `registry.ts` slots `frame_generate_first` / `frame_generate_last`

**FIRST_FRAME_STYLE_MATCHING** (note: runtime expands `${themeStyleMappingBlock()}` / `${artStyleBlock()}` / `${physicsRealismBlock()}` — xem ROUND 2 `blocks.ts`):

```text
=== 关键：画风匹配（最高优先级）===
仔细阅读下方的角色描述和场景描述。它们指定或暗示了画风。
你必须精确匹配该画风。不要默认使用写实风格。
- 如果附有参考图，参考图的视觉风格就是真理——精确匹配
- 输出的画风必须与角色设定图一致

${themeStyleMappingBlock()}

${artStyleBlock()}

${physicsRealismBlock()}
```

**FIRST_FRAME_REFERENCE_RULES:**

```text
=== 参考图（角色设定图）===
每张附带的参考图是一张角色设定图，展示4个视角（正面、四分之三侧面、侧面、背面）。
角色的名字印在每张设定图底部——用它来识别对应的角色。
强制一致性规则：
- 将设定图中的角色名与场景描述中的角色名对应
- 服装必须与参考图完全一致——相同的衣物类型、颜色、材质、配饰。不要替换（如不要把青色常服换成龙袍）
- 面孔、发型、发色、体型、肤色必须精确匹配
- 参考图中展示的所有配饰（帽子、佩刀、发簪、首饰）必须出现
- 画风必须与参考图精确匹配
```

**FIRST_FRAME_RENDERING_QUALITY:**

```text
=== 渲染 ===
材质：符合画风的丰富细节
光线：具有动机的电影级布光。使用轮廓光分离角色。
背景：完整渲染的详细环境。不要空白或抽象背景。
角色：精确匹配参考图的外貌和画风。表情生动，姿态自然有动感。
构图：电影级取景，明确的视觉焦点和景深。
```

**FIRST_FRAME_CONTINUITY_RULES:**

```text
=== 连续性要求 ===
此镜头紧接上一个镜头。附带的参考中包含上一个镜头的尾帧。保持视觉连续性：
- 相同的角色必须穿着一致的服装和比例
- 画风相同——不要在动漫和写实之间切换
- 环境光线和色温应平滑过渡
- 角色位置应从上一个镜头结束时的位置逻辑延续
```

**`buildFullPrompt` structure (first):** lines = `生成此镜头的首帧…` + style_matching + `=== 场景环境 ===` + scene + `=== 帧描述 ===` + startFrameDesc + `=== 角色描述 ===` + chars + reference_rules + optional continuity_rules + rendering_quality.

**LAST_FRAME_STYLE_MATCHING:**

```text
=== 关键：画风匹配（最高优先级）===
你必须精确匹配首帧图像（已附带）的画风。
如果首帧是动漫/漫画风格 → 此帧也必须是动漫/漫画风格。
如果首帧是写实风格 → 此帧也必须是写实风格。
不要改变或混合画风。这是不可协商的。
```

**LAST_FRAME_RELATIONSHIP_TO_FIRST:**

```text
=== 与首帧的关系 ===
此尾帧展示镜头动作的结束状态。与首帧相比：
- 相同的环境、布光方案和色彩基调
- 画风绝对相同——不可有任何变化
- 服装完全一致——角色穿着与设定图和首帧中完全相同的服装。不可换装。
- 面孔、发型、配饰相同——只有姿态/表情/位置发生变化
- 角色的位置、姿态和表情已按帧描述中的说明发生变化
```

**LAST_FRAME_NEXT_SHOT_READINESS:**

```text
=== 作为下一个镜头的起始点 ===
此帧将被复用为下一个镜头的首帧。确保：
- 姿态是稳定的——不处于运动中间，不模糊
- 构图完整，可作为独立画面成立
- 取景允许自然过渡到不同的镜头角度
```

**LAST_FRAME_RENDERING_QUALITY:**

```text
=== 渲染 ===
材质：匹配首帧风格的丰富细节
光线：与首帧相同的布光方案。仅在动作驱动的情况下变化。
背景：必须匹配首帧的环境。
角色：精确匹配参考图。展示镜头动作结束时的情感状态。
构图：镜头的自然收束，为下一个剪辑做好准备。
```

**Hardcoded last-frame reference preamble in `buildFullPrompt`:**

```text
=== 参考图 ===
第一张附带图像是此镜头的首帧——以它为视觉锚点。
其余附带图像是角色设定图（每张4个视角，名字印在底部）。
将每张设定图的角色名与场景中的角色对应。
```

**Vì sao hiệu quả:** Name-on-sheet thay token formal; last frame “stable pose” = bridge cho shot sau (giống OmniCast continuity gate tinh thần).

#### A5. Character 4-view FULL — `registry.ts` `character_image` slots

**CHAR_IMAGE_STYLE_MATCHING:**

```text
=== 关键：画风匹配（最高优先级）===
仔细阅读下方的角色描述。描述中指定或暗示了画风（如 动漫、漫画、写实照片级、卡通、水彩、像素风、油画 等）。
你必须精确匹配该画风。不要默认使用写实风格。不要覆盖描述中的风格。
- 如果描述中提到"动漫"/"漫画"/"anime"/"manga" → 生成动漫/漫画风格插画
- 如果描述中提到"写实"/"真人"/"photorealistic" → 生成写实渲染
- 如果描述暗示其他风格 → 忠实遵循该风格
- 如果完全未提及风格 → 根据角色的背景和类型推断最合适的风格

${themeStyleMappingBlock()}

**写作语言**：使用自然中文散文描述每个部分，不要权重语法 "（xx：1.99）"，不要结构化标签 "Scene:" "Style:"——Seedance/即梦 系图像模型对自然语言理解最强。
```

**CHAR_IMAGE_FACE_DETAIL:**

```text
=== 面部——高精度 ===
以适合所选画风的高精度渲染面部：
- 清晰一致的面部特征：骨骼结构、眼型、鼻型、嘴型——全部匹配描述中的外貌
- 眼睛：富有表现力、细节丰富、有高光反射和深度感——根据画风调整（动漫用动漫风格眼睛，写实用精细虹膜细节）
- 头发：清晰的发量、颜色和动态感，使用适合画风的渲染方式（写实用单根发丝，动漫用大块发束配高光条）
- 皮肤：符合画风的渲染——动漫用平滑赛璐珞着色，写实用毛孔级细节
- 整体：面部应具有辨识度和记忆点，有强烈的视觉特征
```

**CHAR_IMAGE_FOUR_VIEW_LAYOUT:**

```text
=== 四视图布局（必须严格遵守——这是角色设定集的核心输出形式）===
**强制输出四视图**：最终画面必须包含四个独立视角，从左到右水平排列在一张纯白画布上。**不要输出单视角肖像、不要只画两三个视角、不要把角色放在场景里**——这是一张专业的角色设定参考图（character turnaround sheet / 三视图 / 四视图）。

四个视角的精确要求（从左到右）：
1. **正面（Front / 0°）**——角色正对观众，肩膀平行画面，双臂自然放松垂于身侧，双脚与肩同宽自然站立，展示完整服装正面、腰带、武器挂件、胸前配饰。表情平静中性，便于后续衍生。
2. **四分之三侧面（3/4 View / 约 45°）**——角色向右旋转约 45°，展示面部立体深度、颧骨与鼻梁轮廓、侧前方服装结构与披风/外袍的层次。
3. **侧面轮廓（Profile / 90°）**——标准 90° 朝向画面右侧，清晰展示鼻子-下巴轮廓线、发型侧面体积、武器挂带位置、披风下摆、靴子侧面。
4. **背面（Back / 180°）**——完全背对观众，展示后脑发型与发饰、服装背部图案/绣纹、披风/斗篷全貌、背部装备（剑鞘、箭袋、背包等）。

**构图与画面组织要求**：
- 画面横向比例建议 16:9 或更宽，确保四个视角有充足的展示空间
- 画布背景必须是**纯白无纹理**，四个视角之间留适当间距，互不重叠
- 四个视角**头顶对齐、腰线对齐、脚底对齐**，整齐划一如专业设定集
- 统一景别——全部采用站立全身视图（从头顶到脚底，包含鞋/靴），便于服装和姿态的完整展示
- 如果角色手持武器，正面视图清晰展示持握方式，其他视角至少能看到武器的一部分
```

**CHAR_IMAGE_LIGHTING_RENDERING:**

```text
=== 光线与渲染 ===
- 干净的专业三点布光：主光从前上方约 45° 入射，补光从对侧柔化阴影，背后轮廓光（rim light）把角色从纯白背景里清晰"抠"出来
- 光线质感符合画风——写实风用柔和的摄影棚光，动漫风用清晰的赛璐珞明暗分界，仙侠风可加微妙体积光强化氛围
- 纯白背景无渐变、无纹理、无地面阴影（或极浅的接触影），确保角色清晰分离、方便后续抠图复用
- **四个视角必须保持完全一致的光线方向与色温**，避免出现"正面白天/侧面黄昏"的断裂感
- 在所选画风内追求最高渲染质量：材质细节、布料褶皱、金属反光、皮肤质感都要符合画风的技术标准
```

**CHAR_IMAGE_CONSISTENCY_RULES:**

```text
=== 四视角一致性（下游流水线的生死线）===
此参考图会被复用为后续所有镜头生成的权威参考——任何不一致都会在成片中放大成穿帮。严格执行：
- **身份一致**：四个视角必须是同一个人——相同的面孔骨架、相同的身高比例、相同的五官位置、相同的肤色
- **服装一致**：每一件衣物、配饰、腰带扣、纽扣、绣纹、口袋位置都逐一对齐，颜色值完全相同（不要正面深蓝背面浅蓝）
- **发型一致**：发色、发量、发长、刘海形状、发饰位置——四个视角可以看到不同侧面，但必须是同一个发型的不同角度
- **武器装备一致**：武器的颜色、长度、握把样式、挂载位置——正面挂在腰左侧，背面就要在腰左侧（从背后看就是右侧）
- **身材一致**：肩宽、腰围、腿长比例逐视图对齐，不要正面修长背面壮实
- **表情与气质一致**：四个视角都保持同一个中性/微表情，传达同一种性格气质（冷峻 / 温和 / 孤傲），不要有笑脸和怒脸混杂
```

**CHAR_IMAGE_NAME_LABEL:**

```text
=== 角色名标签 ===
{{NAME_LABEL_PLACEHOLDER}}
```

#### A6. Continuity / quality QA prompts

`continuity-check.ts:8-22`:

```
比较这两帧来自动画影片的连续画面。
第一帧是上一个镜头的末帧。
第二帧是下一个镜头的首帧。
检查：1服装 2位置 3光照 4色调 5背景
仅输出：{"pass": true/false, "issues": [...]}
```

`video-quality-check.ts:9-23`: score 0–100, pass ≥60.

#### A7. Video keyframe interpolation header — `registry.ts:1515-1532`

```
用自然中文散文描述从首帧到尾帧之间发生的动态过程。不要使用结构化标签...
时长策略：4-8秒聚焦一个核心动作；9-12秒 2-3 段时间戳；13-15秒 3-4 段...
构图安全区：画面下方 20% 是字幕区域...
禁止出现水印、字幕、文字 LOGO...
```

### 4.B StoryGen-Atelier — prompts VERBATIM

#### B1. Storyboard generation system+user — `llmService.js:205-319`

```
Role: You are a professional film storyboard artist.
Context: You are creating shot-level prompts for Google's Veo video generation model.

Your job:
- Take the user's story and style as inspiration.
- BUT you must ALWAYS follow the safety guidelines and adjust the story if needed.

IMPORTANT SAFETY OVERRIDES:
- If any part of the story ("${sentence}") or the visual style ("${appliedStyle}") suggests
  sexual content, graphic violence, self-harm, glorified death, hate, or illegal activities,
  you MUST rewrite that part into a safe, neutral, metaphorical, or positive version.
- All characters must be completely fictional.DO NOT use any real-world person names.
  Use generic role descriptions like "the main hero", "the woman", "the uncle", etc.
...
- All human characters must be clearly adults in safe, non-sexualized, non-exploitative contexts.

NEVER include these guidelines themselves in any shot.prompt text.
```

(+ full `PROMPT_GUIDE_CONTENT` from `guide/VideoGenerationPromptGuide.md`)

```
Goal: Create a continuous storyboard with EXACTLY ${shotCount} shots for the story: "${sentence}".
Global visual style: ${appliedStyle}.

*** CRITICAL NARRATIVE REQUIREMENTS ***
1. Continuous Story Arc: Beginning 25% / Middle 50% / End 25%
2. Visual Consistency: Define "Hero Subject"; consistent lighting/palette
3. Seamless Flow: "Continuing from the previous angle..."
4. Causal Relationship: shotStory 用 "因此"、"于是"、"紧接着"...
5. Temporal Continuity: no flashbacks unless requested

Output: ONLY raw JSON array:
- shot, prompt (ENGLISH only), duration (4|6|8), description (中文),
  shotStory (中文 2-3句), heroSubject (shot1 only, ENGLISH identity lock)
```

**Vì sao hiệu quả:** Safety-first + heroSubject single source of identity + English prompts for Veo + Chinese narrative for UX/causality.

#### B2. Transition analysis — `llmService.js:131-156`

```
Role: Expert Film Director and Cinematographer.
Context: You are generating prompts for Google's Veo video generation model.
IMPORTANT SAFETY GUIDELINES:
${PROMPT_GUIDE_CONTENT}
Frame A (previous shot) image: [IMAGE]
Frame A description: ${shotAText}
Frame B (next shot) image: [IMAGE]
Frame B description: ${shotBText}

Task: Analyze these two sequential storyboard frames (Frame A -> Frame B).
1. describe the specific camera movement and visual transition...
2. Determine the optimal duration ... (MUST be 4, 6, or 8 seconds).

Output ONLY a raw JSON object:
{
  "transition_prompt": "Detailed cinematic description, strictly following safety guidelines...",
  "duration": 4
}
```

#### B3. Frame image — `imageGenService.js:30-49` (full)

```
Role: Cinematic frame artist.
Goal: Render a single storyboard frame that matches the shared style and camera feel.
${heroInstruction}
Style: ${appliedStyle}.
Continuity: ${styleGlue}
Frame description: ${prompt}.
Constraints: no text, no captions, 16:9, high fidelity. The main character MUST look identical to the reference image if provided.
```

With ref image part:

```
Reference image above shows the main character. Generate a new image where this SAME character (identical appearance, clothing, colors) performs the action described below:

${imagePrompt}
```

#### B4. Closing clip prompt — `videoService.js:282`

```
${closingShot.prompt || closingShot.description || "Final lingering shot."} Hold on the final frame with a gentle cinematic finish.
```

---

## 5. Vòng QA / retry / repair

### AIComicBuilder

| Check | Detect | Repair | Budget | Give up |
|-------|--------|--------|--------|---------|
| Task queue retries | failed task | re-run | `maxRetries` default 3 (`schema.ts:383`) | status failed |
| Continuity check | clothing/light/bg break | **log only** | 1 call | pass on error |
| Video quality | score &lt;60, face/limbs | **log only** | 1 call | pass on error |
| AI optimize button | user-triggered field polish | rewrite field | 1 | user re-edit |
| Stale flags | script hash change | user regenerate | — | — |
| Agent validate | JSON parse agent output | 422 error | 1 | no silent fallback for agent path |
| Image gen batch | per-ref try/catch | count failed, continue others | per image | partial success |

**Không có** auto re-roll khi quality fail — khác fail-closed spirit của OmniCast continuity.

### StoryGen-Atelier

| Check | Detect | Repair | Budget |
|-------|--------|--------|--------|
| `retry(fn, attempts=2, delay=400)` | any throw | re-call | 2 |
| JSON parse storyboard | parse fail | throw (if has API key) or FALLBACK seed board | 1 |
| Transition parse fail | bad JSON | `{ transition_prompt: "Cinematic transition", duration: 6 }` | soft |
| Transition analyze fail | exception | same soft fallback | soft |
| Image gen fail | no inline image | placehold.co URL | soft |
| Video clip fail | throw | aborts whole `Promise.all` | hard fail stitch |

---

## 6. Tích hợp video-gen

### AIComicBuilder providers matrix

| Provider | Modes | Notes |
|----------|-------|-------|
| Seedance / UCloud Seedance | keyframe first+last; multi reference_image | `generate_audio` on v2; `return_last_frame` on ref |
| Veo (`veo.ts`) | keyframe image+lastFrame (not 3.0); ref mode Veo3.1 `config.referenceImages` max 3, duration locked 8s | poll 60×10s |
| Kling / Wan | via other provider files | similar i2v patterns |

**Keyframe video pipeline** (`pipeline/video-generate.ts`): requires both frames → `buildVideoPrompt` → provider.

**Reference video pipeline** (`generate/route.ts:2215+`): scene frames required → ordered multi-ref → optional LLM vision plan for prompt → `reference_video` asset.

### StoryGen-Atelier

- **Only** Vertex Veo first/last (Gemini video path disabled comment).
- Parallel clip generation then serial stitch.
- Closing shot: first frame only (`lastFrame: null`).
- Audio: `generateAudio: true` on Vertex params.
- Poll: 60 attempts × 40s (~40 min worst case).

**Pattern map → OmniCast `veo_pipeline.py`:**

```
OmniCast storyboard frames (ordered)
  for i in 0..n-2:
    prompt = gemini_analyze(frame[i], frame[i+1], shot_stories)
    clip[i] = veo(first=frame[i], last=frame[i+1], prompt, duration∈{4,6,8})
  clip[n-1] = veo(first=frame[n-1], last=None, closing_prompt)
  ffmpeg concat
```

AIComic keyframe mode thay thế: mỗi shot tự first+last (nội shot), rồi concat shots — **khác** StoryGen (inter-shot interpolate). OmniCast có thể cần **cả hai**: inter-shot bridge (StoryGen) + intra-shot motion (AIComic).

---

## 7. Pacing / timing

### AIComicBuilder

- Shot `duration` default **10s**, clamp theo model max (`getModelMaxDuration`).
- Seedance 2: 4–15s; prompt density scales with duration (2–3s per beat).
- Dialogue `startRatio`/`endRatio` for lip-sync placement (schema).
- Target duration project/episode fields influence script_split idea length.
- Transition in/out fields (`cut` default) — metadata, assemble may use later.

### StoryGen-Atelier

- Hard constraint duration ∈ **{4, 6, 8}** (Veo).
- Shot count 2–12 (controller clamp).
- Narrative pacing: 25/50/25% in LLM instructions.
- Transition duration chosen by Gemini vision, normalized to {4,6,8}.
- **No TTS voice-over sync** — video model audio only.

---

## 8. Chi tiết nhỏ đáng học

1. **shot_assets versioning** — re-gen = new row `asset_version+1`, flip `is_active` — history không mất (`schema.ts:136-138`).
2. **Scene name in meta** (`sceneName`) — dùng làm label trong `@图片N = 场景：竹梢高空`.
3. **characters[] on asset, not only on shot** — video picks cast subset per shot from AI-declared names.
4. **Name printed on character sheet** — poor-man's token binding when provider lacks `[IMAGE n]` discipline.
5. **Prompt slot system** — project > global > code default; version history + presets (`prompt_templates` / `prompt_versions` / `prompt_presets`).
6. **Seedance prompt doctrine** (`docs/seedance-prompt-patterns.md:119-125`): *video model already sees frames — prompt says WHAT happens, not WHAT they look like.*
7. **Subtitle safe zone 20% bottom** — baked into video prompts (YouTube-friendly).
8. **StoryGen Interpolation Chain** — sliding window + parallel Veo + ffmpeg `-c copy` (zero re-encode).
9. **heroSubject only on shot 1** — avoid identity drift from re-describing.
10. **AIComic `isCharacterOnScreen`** — offscreen dialogue → `【画外音】` not lip-sync.
11. **Forbidden real names in image prompts** — prevent Gemini/image API 400 (`registry.ts:1867-1870`).
12. **Episode continue** — copy previous episode last frame as next first (release article).
13. **UCloud vs Ark** — same logical content roles, different HTTP envelope (`input.content` + `parameters` vs flat body).

---

## 9. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện | Gap OmniCast | File đích | Impact | Effort |
|---|-----------|--------------|-----------|--------|--------|
| 1 | **Scene-only location frames** (0 people) rồi gắn char refs lúc video | Location gen vẫn có thể trộn người; identity bleed | `storyboard/frames.py`, image providers, `binding.py` ENVIRONMENT path | Cao (face/bg) | M |
| 2 | **Interpolation Chain** first/last giữa consecutive frames + Gemini transition prompt | `veo_pipeline` Flow convert() chưa nhận image; chưa stitch chain | `media/veo_pipeline.py`, `storyboard/clips.py` | **Rất cao** | L |
| 3 | Seedance 2 multi-ref schema + `@图片N（名）` prose | Chưa có Seedance provider; binding dùng `[IMAGE n]` (tương thích nếu map index) | new `media/providers/seedance.py` + prompt adapter | Cao nếu dùng Seedance | M |
| 4 | Per-shot **1–4 scene refs** khi đổi địa điểm | 1 location_id / shot | `storyboard/models.py` Shot, `frames.py` | Trung (action) | M |
| 5 | `characters[]` on frame asset → subset cast for API | Cast full board risk over-ref | `binding.build_mappings` filter by shot.cast already — **đảm bảo** không fallback "first 3" | Trung | S |
| 6 | **RefRole ignore** (OmniCast đã có) + **scene gen ban people** (AIComic) = combine | Chỉ có text ignore, chưa enforce gen | `frames.py` + prompts | Cao | S–M |
| 7 | Duration micro-beats 2–3s trong video prompt | video prompts có thể tĩnh | Writer/video prompt templates | Trung | S |
| 8 | Subtitle safe zone bottom 20% | Chưa | style/video prompt suffix | UX YT | S |
| 9 | Non-blocking vision QA → **đổi thành fail-closed** cho production | OmniCast continuity gate tốt hơn — giữ | `continuity.py` | Giữ lợi thế | — |
| 10 | Character 4-view turnaround + name label | refsheet có thể học layout | `storyboard/refsheet.py` | Trung | M |
| 11 | Style presets list + custom free-text | Channel brand style; thêm preset library UI | channel config / frontend | UX | S |
| 12 | Closing hold clip pattern | End of video abrupt | `veo_pipeline` / assemble | Thấp | S |
| 13 | Prompt slot registry 3-level override | Hardcoded prompts nhiều chỗ | optional later | Maintain | L |
| 14 | `generate_audio` + quoted dialogue for Seedance | TTS pipeline riêng — optional dual path | media | Trung | M |

**Ưu tiên ship (WS1 alignment):**

1. **#2 StoryGen Interpolation Chain → `veo_pipeline`** (stack Gemini/Veo đúng OmniCast).  
2. **#1 Scene-only + binding ENVIRONMENT** (chống face drift user report).  
3. **#3 Seedance multi-ref** nếu roadmap có Seedance; map `[IMAGE n]` ↔ `@图片n` adapter.  
4. Giữ fail-closed OmniCast; **đừng** học soft-pass QA của AIComic.

---

## 10. KHÔNG nên học + LICENSE

### Anti-patterns

| Anti-pattern | Repo | Vì sao tránh |
|--------------|------|--------------|
| Continuity/quality **pass on error** | AIComic | Che defect; OmniCast fail-closed đúng hơn |
| Fallback "first 3 characters with refs" | AIComic keyframe | Sai cast; OmniCast `build_mappings` + dropped log tốt hơn |
| God-file `generate/route.ts` 3k+ lines | AIComic | Khó test; OmniCast nên giữ pipeline modules nhỏ |
| Placeholder image on failure | StoryGen | Fake success; pollute gallery |
| `Promise.all` video clips — 1 fail = all fail, no partial resume | StoryGen | Cần per-clip retry + checkpoint |
| Single hero only | StoryGen | Không scale multi-cast YouTube series |
| Hardcode duration only 4/6/8 without model matrix | StoryGen | OK cho Veo; Seedance cần 4–15 |
| Duplicate initialImage inside referenceImages list | Seedance provider (`initial` + full ordered list) | Có thể double-count same scene image — verify before port |
| Soft fallback transition "Cinematic transition" | StoryGen | Generic motion → mushy Veo output |

### LICENSE

| Repo | License | Khuyến nghị |
|------|---------|-------------|
| AIComicBuilder | **Apache-2.0** (`LICENSE`) | Học architecture + prompts; rewrite code; attribution nếu port lớn |
| StoryGen-Atelier | **Apache-2.0** (`LICENSE`) | Học Interpolation Chain; rewrite cho `veo_pipeline` |

Cả hai **OK** để học sâu (không AGPL / không thiếu license). Vẫn **không copy-paste** nguyên file vào OmniCast — adapt naming/types/vault SSOT.

---

## Phụ lục A — So sánh end-to-end 3 bên

| | OmniCast (hiện) | AIComicBuilder | StoryGen-Atelier |
|--|-----------------|----------------|------------------|
| Cast registry | Entity + RefRole + fail-closed | characters + costumes | heroSubject text |
| Image token | `[IMAGE n]` + ignore clause | name-on-sheet; `@图片N` video | single ref image shot1 |
| Video | Veo path partial; Flow no image | Seedance/Veo dual mode | Veo first/last chain |
| Consistency gate | fail-closed continuity | soft vision QA | none |
| Style | channel brand | script visual style + slots | 15 presets + custom |
| Complexity | mid product | full 漫剧 studio | minimal atelier |

---

## Phụ lục B — Seedance 2.0 content roles (doc cheatsheet)

```
Mutually exclusive modes:
  A) first_frame (+ optional last_frame)
  B) reference_image × 1..9  (+ optional reference_video/audio — not in AIComic code)

generate_audio: true → dialogue in quotes / 角色台词
duration: 4..15 or -1
ratio: 16:9 | 9:16 | ... | adaptive
```

Indirect first/last in multi-ref: *prompt* says "首帧为图片1…尾帧为图片2" (doc example) — AIComic prefers dedicated first/last roles for strict lock.

---

## ROUND 2 — VERBATIM FULL (theo VERIFY §4.2)

> Mục này chép **toàn bộ** file/module prompt bị verifier ghi “bỏ sót”. Nguồn: `_refs/AIComicBuilder/src/lib/ai/prompts/*` + StoryGen guide. Không tóm tắt, không `…`.

### R2.1 `registry.ts` — `script_generate` slots FULL

#### SCRIPT_GENERATE_ROLE_DEFINITION

```text
你是一位屡获殊荣的编剧，擅长视觉叙事和短片动画内容创作。你的剧本以电影级的节奏感、生动的画面描写和情感共鸣的对白著称。

你的任务：将一段简短的创意构想转化为一部精致的、可直接投入制作的剧本，专为AI动画生成优化（每个场景 = 一个5-15秒的动画镜头）。
```

#### SCRIPT_GENERATE_LANGUAGE_RULES

```text
【关键语言规则】你必须使用与用户输入相同的语言撰写整部剧本。如果用户用中文写作，则全部用中文输出；如果用英文，则全部用英文输出。此规则适用于以下所有章节。
```

#### SCRIPT_GENERATE_OUTPUT_FORMAT

```text
输出格式——剧本必须按以下顺序包含这些章节：
```

#### SCRIPT_GENERATE_VISUAL_STYLE_SECTION

```text
=== 1. 视觉风格 ===

**此章节是机器可读格式，下游程序会用正则解析。必须严格按以下 6 个字段输出，每字段独占一行，使用中文冒号"："，字段标签逐字不变，不要加 markdown 项目符号、不要加星号、不要合并字段、不要跳过字段。无论剧本整体语言是什么（中/英/日/韩），6 个字段标签永远保持中文原样。**

视觉风格：<一行值——画风关键词，例如"写实电影摄影 / 胶片质感" 或 "3D国漫渲染 / 中国仙侠概念设计" 或 "日漫赛璐珞 / 新海诚柔光">
色彩基调：<一行值——主色与冷暖倾向，例如"暖橘与深蓝的冷暖对比，低饱和度" 或 "高饱和霓虹冷色，赛博朋克紫青">
时代美学：<一行值——时代与美学背景，例如"1960年代老上海" 或 "近未来赛博2077" 或 "古代唐风">
氛围情绪：<一行值——整体情绪基调，例如"怀旧温情夹杂淡淡哀伤" 或 "压抑紧张的悬疑">
画幅比例：<必须是以下四选一："16:9 横屏" / "9:16 竖屏" / "2.35:1 宽银幕" / "1:1 方形"——不要自创其他格式>
参考导演：<一行值——可选的参考导演/风格，例如"王家卫 / 维伦纽瓦 / 新海诚"；如果没有明确参考则写"无">

【字段硬规则】
- 每个字段值必须是单行（值内部不允许换行）
- 每个值 ≤ 50 个汉字 或 ~80 个英文字符——保持精炼
- 尊重用户偏好：若用户明确指定"真人"则"视觉风格"填"写实真人电影"；若未指定则根据创意推断最合适的值
- 画幅比例必须严格四选一，不要写"1920x1080"、"横屏16:9"这种变体
- 参考导演是可选字段，但**字段本身不能省略**——没有就写"无"

【完整正确示例】
=== 1. 视觉风格 ===

视觉风格：写实真人电影摄影，胶片颗粒质感
色彩基调：暖橘与深琥珀为主，低饱和度，夜戏霓虹冷青点缀
时代美学：1960年代老上海，弄堂烟火气与旗袍风情
氛围情绪：怀旧温情中夹杂淡淡哀伤
画幅比例：2.35:1 宽银幕
参考导演：王家卫
```

#### SCRIPT_GENERATE_CHARACTER_SECTION

```text
=== 2. 角色描述 ===

**此章节同样是机器可读格式。为每个有名字的角色输出一个块，严格按以下 5 个字段。字段标签逐字不变，不要用 markdown 项目符号、不要用破折号开头、不要合并字段。字段标签永远保持中文。角色块之间空一行。**

角色：<角色名——必须与剧本中出现的名字完全一致>
外貌：<性别、年龄、身高/体型、脸型、五官、肤色、发色发型——一行>
服饰：<具体衣物、材质、颜色、配饰——一行>
标志特征：<伤疤、眼镜、纹身、胎记、首饰等；没有则写"无"——一行>
气质姿态：<体态语言、步态、习惯性动作、说话方式——一行>

（每个字段值必须是单行，不允许换行；相邻角色块之间空一行；不要用容器/代码块包裹）

【完整正确示例】
=== 2. 角色描述 ===

角色：林晓月
外貌：女，25岁，身高165cm，纤瘦，鹅蛋脸，柳叶眉，清澈杏眼，浅蜜色肌肤，黑色齐腰长直发
服饰：米白色棉麻衬衫袖口挽至手肘，高腰深蓝阔腿裤，棕色牛皮编织凉鞋，左腕檀木佛珠手链
标志特征：右耳后一颗小痣，笑起来有浅酒窝
气质姿态：走路轻盈有节奏感，说话时喜欢微微歪头，紧张时无意识拨弄手链

角色：赵东明
外貌：男，35岁，身高182cm，宽肩厚背壮硕体型，国字脸，浓眉大眼，古铜肤色，板寸微有灰丝
服饰：深灰工装夹克，内搭黑色圆领T恤，卡其多口袋工装裤，黑色厚底马丁靴，右手无名指银色宽戒
标志特征：左眉上一道3厘米旧疤，下巴修剪过的短茬胡须
气质姿态：站姿如松，习惯双手环胸，声音低沉有力，思考时拇指摩挲戒指
```

#### SCRIPT_GENERATE_SCENE_SECTION

```text
=== 3. 场景 ===
专业剧本格式：
- 场景标题："场景 [N] — [内景/外景]. [地点] — [时间]"
- 每个场景的括号内舞台提示：
  • 镜头构图（特写、全景、过肩镜头 等）
  • 角色走位和动作
  • 关键环境细节（光线、天气、道具、建筑、色彩）
  • 场景的情感节拍
- 角色对白：
  角色名
  （表演提示）
  "对白内容"

【示例】
场景 1 — 外景. 老城区弄堂 — 黄昏

（全景缓缓推进）夕阳将弄堂的青石板路染成暖橘色，两旁晾衣竿上挂满了花花绿绿的被单，在晚风中轻轻摇摆。远处传来收音机播放的老歌。

（中景）林晓月骑着一辆旧自行车从巷口拐进来，车篮里放着一袋刚买的菜，几根葱探出袋口。她单手扶把，另一只手拨开垂落的晾衣被单。

林晓月
（自言自语，微微喘气）
"又差点迟到……"

（近景切换）弄堂深处，赵东明倚在自家门框上，手里夹着一根没点燃的烟，眯眼看着晓月骑车过来，嘴角不易察觉地微微上扬。
```

#### SCRIPT_GENERATE_SCREENWRITING_PRINCIPLES

```text
编剧原则：
- 以"钩子"开场——一个引人注目的视觉画面或令人好奇的瞬间
- 每个场景都必须服务于故事：推进情节、揭示角色或制造张力
- "展示，而非讲述"——优先用视觉叙事取代旁白说明
- 对白应自然生动；潜台词优于直白表达
- 构建清晰的三幕结构：铺垫 → 冲突 → 解决
- 以情感收束结尾——意外、宣泄或一个有力的画面
- 根据目标时长调整场景数量。如创意中指定了目标时长（如"目标时长：10分钟"），按此计算场景数：约每30-60秒一个场景。10分钟的短片需要10-20个场景，而不是4-8个。
- 每个场景描述必须足够具体，让AI图像生成器能据此生成画面（描述颜色、空间关系、光照质量）
- 场景描述应与声明的视觉风格一致（如"写实"则描述摄影细节；如"动漫"则描述动漫美学）

【战斗/对决题材强制规则（最高优先级）】
如果用户的创意/标题中出现任何战斗信号词——"大战"、"对决"、"决战"、"交手"、"PK"、"VS"、"vs"、"battle"、"fight"、"duel"、"对打"、"厮杀"、"对抗"——那么这是一部**实打实的战斗题材**，必须严格遵守：

1. **战斗戏份占比硬性要求**：实际物理对战场景必须占总场景数的 **50% 以上**。禁止把"战斗"解读为"单方面压制 + 另一方顿悟 + 象征性一击"的文艺套路。用户说"大战"就是要拳拳到肉的持续对战序列。

2. **双方必须都是主动交战者**：
   - ❌ 错误：一方跪地/被困/迷茫，另一方只是冷眼/叹息/抬手，全程无真正肢体交锋
   - ❌ 错误：所有攻击都击中幻象/空气/替身，没有击中真身
   - ✅ 正确：A 攻击 → B 格挡/闪避/反击 → A 重整再攻 → B 反扑 → 僵持 → 变招……双方持续来回交手

3. **战斗序列的节拍结构**（分配到多个场景）：
   - **开场试探**（1-2 场）：双方走位、眼神锁定、武器出鞘
   - **第一波交锋**（2-3 场）：开局对招，试探彼此路数
   - **升级对抗**（3-5 场）：招式加重、变招、环境被波及
   - **逆转时刻**（1-2 场）：某一方陷入劣势又绝地反击，或双方两败俱伤
   - **终局一击**（1-2 场）：决胜的那一招
   - **余韵**（1 场）：战后余波、伤痕、走向

4. **每个战斗场景必须包含**：
   - 双方各自的动作（谁先手/谁后手/谁反击）
   - 具体的招式/武器/技能名称
   - 物理反馈：撞击、冲击波、护甲碎裂、地面龟裂、飞溅的鲜血或粒子效果
   - 镜头语言：快切、环绕、慢镜头、过肩、低角度仰拍等战斗专用运镜

5. **禁止用"顿悟/心魔/精神空间/哲理对话"替代实战**。这种内容只能作为战斗之间的**1 个过渡场景**，绝不能占据整部剧的主体。

6. **结局要尊重对决题材**：对决题材的结局通常是"一方彻底战胜另一方"或"两败俱伤后和解"，而不是"一方顿悟后对方消散"。

如果用户的创意是其他题材（言情、悬疑、治愈、纪录片等），忽略以上战斗规则，按正常三幕结构执行。

不要输出JSON。不要使用markdown代码块。仅输出纯文本剧本。
```

### R2.2 `registry.ts` — `script_parse` slots FULL

#### SCRIPT_PARSE_ROLE_DEFINITION

```text
你是一位资深剧本监制和结构化编辑，擅长将叙事文本**解析**为适合动画短片流水线的结构化剧本 JSON。

你的任务：读取用户的原始故事/散文/非结构化文本，**在不丢失任何原文信息的前提下**，将其解析为精确的 JSON 结构，为下游 AI 动画流水线（图像生成 → 视频生成）提供输入。

**关键心态**：你是"结构化者"，不是"改编者"。禁止重写、禁止精炼、禁止补充原文没有的情节。你的工作是给原文"打标签"和"分组"，不是"改稿子"。
```

#### SCRIPT_PARSE_FIDELITY_RULES

```text
=== 原文保真度（最高优先级——此规则优先于所有其他规则）===

**核心原则**：输出的 JSON 必须是原文的"无损结构化"。任何删除、精炼、改写都是违规。

【对白——逐字不动（最严格）】
- 原文中出现的**每一句台词**都必须进入对应场景的 dialogues 数组
- **台词 text 字段必须与原文完全一致**——包括语气词（"啊"、"嗯"、"呃"、"..."）、重复、口语化表达、省略号、标点符号
- 禁止把"我、我不是那个意思……" 精炼成 "我不是那个意思"
- 禁止把连续的"不！不！不要这样！"合并成一条"不要这样"
- 禁止把方言/口音/错别字"修正"成书面语
- 禁止把两个角色的台词合并成一条
- 长独白不要拆分，除非原文有明显的场景切换
- 如果原文用引号、破折号、冒号等标点区分对白，严格按原标记识别

【角色——名字精确】
- 角色名使用原文中出现的**原始名字**，不要改写（"老王" 不要改成 "王大爷"）
- 如果原文用代词（"他"、"她"）而上下文能明确指向某个角色，填入该角色名；如果真的无法判断，保留代词
- 旁白/画外音如果有具体说话人用原名；没有具体说话人用 "旁白" / "Narrator"

【情节——每一个事件都要落地】
- 原文中的每一个动作、每一个事件、每一个情感转折都必须在 scenes 的 description 或 dialogues 中体现
- 禁止把"她先推开门，然后愣了一下，最后摸了摸口袋里的信"精炼成"她推门进入"
- 叙述性旁白（非对白的解说文字）也要完整保留——放进 description 字段里，不要丢
- 时间跳跃/场景转换要拆成独立 scene，不要强行合并

【场景拆分——宁多勿少】
- 一个场景 = 一个连续的时空单元。时间跳跃、地点变化、叙事节拍转折都要新开 scene
- 如果原文一段话里包含 3 个节拍（进门→对话→离开），拆成 3 个 scene，不要压成 1 个
- 不确定要不要拆时，**默认拆分**

【自检清单——生成完 JSON 后回头对原文做一遍核对】
- □ 原文每一句带引号/冒号的对白都进 dialogues 了吗？
- □ 对白的 text 和原文逐字一致吗（语气词/重复/标点都在）？
- □ 原文中出现的每个角色名都出现在 JSON 里吗？
- □ 原文的每一个独立事件都有对应的 scene 吗？
- □ 没有把多个独立节拍强行塞进同一个 scene 吗？
如果任何一项不满足，**必须补 scene、补 dialogue、或者扩写 description**，不准降低要求。

【反例】
原文：
> "你……你怎么来了？"林晓月愣在门口，手里的钥匙掉在地上发出清脆的响声。赵东明没说话，只是静静地看着她，良久才低声说："我来，接你回家。"

❌ 错误的精炼：
scenes: [{
  description: "林晓月在门口遇见赵东明",
  dialogues: [
    { character: "林晓月", text: "你怎么来了", emotion: "惊讶" },
    { character: "赵东明", text: "我来接你回家", emotion: "平静" }
  ]
}]
（丢了：语气词"你……你"、钥匙掉地的动作、"良久才低声说"的停顿、原文的标点）

✅ 正确的无损解析：
scenes: [{
  description: "林晓月愣在门口，手中的钥匙脱手掉落在地面上发出清脆的响声。赵东明站在门外静静地看着她，沉默良久。",
  dialogues: [
    { character: "林晓月", text: "你……你怎么来了？", emotion: "震惊中带着迟疑，声音微颤" },
    { character: "赵东明", text: "我来，接你回家。", emotion: "沉默良久后低声开口，目光坚定" }
  ]
}]
```

#### SCRIPT_PARSE_OUTPUT_FORMAT

```text
输出单个JSON对象：
{
  "title": "引人入胜的标题",
  "synopsis": "1-2句话的故事梗概，捕捉核心冲突和利害关系",
  "scenes": [
    {
      "sceneNumber": 1,
      "setting": "具体地点 + 时间（如'灯光昏暗的地下工作室——深夜'）",
      "description": "详细的视觉描写：角色位置、动作、关键道具、光照质量（暖/冷/戏剧性）、氛围、色彩基调。以镜头指导的方式书写，让动画师可以直接执行。",
      "mood": "精确的情感基调（如'紧张的期待中带有潜在的温暖'）",
      "dialogues": [
        {
          "character": "角色名（必须与其他地方使用的名字完全一致）",
          "text": "自然的对白内容",
          "emotion": "具体的表演提示（如'压低声音急促地说，眼神游移不定'）"
        }
      ]
    }
  ]
}
```

#### SCRIPT_PARSE_PARSING_RULES

```text
故事编辑原则（**在原文保真度的前提下**应用，任何与保真度冲突的条款都以保真度优先）：
- 保留原作者的创作意图、基调和风格——这是字面意义，不要"优化"原作
- 识别叙事弧线：起因 → 发展 → 高潮 → 结局，用于判断场景拆分边界，**不要改写**
- 每个场景 = 一个连续的5-15秒动画镜头；长段落应拆分为多个场景（宁多勿少）
- 场景描写必须具有视觉具体性：指定空间关系、角色姿态、光线方向、主色调；但**原文已有的动作描写必须完整保留**，只允许补充（不允许替换）原文没写的视觉细节
- emotion 字段描述肢体表达 + 语气，不要只写情感名称（如"震惊中带迟疑，声音微颤"好于"震惊"）
- 在所有场景中保持角色名称的严格一致性，使用原文出现的原始名字
- 只在原文**完全没有提**的地方补充视觉推断，**不得覆盖原文已有描述**

【示例——原文到场景的转化】
原文："他走进房间，看到了她。"
转化后：
{
  "sceneNumber": 1,
  "setting": "老旧公寓客厅——傍晚",
  "description": "逆光剪影构图，橙红色夕阳从落地窗倾泻而入。男人推开半掩的木门，门轴发出轻微的吱呀声。女人背对门口站在窗前，纤细的身影被夕阳勾出金色轮廓，手中端着一杯已经凉透的茶。空气中悬浮着细小的灰尘颗粒，在光束中缓缓旋转。",
  "mood": "重逢的忐忑，夹杂着岁月沉淀的苦涩与温柔",
  "dialogues": []
}
```

#### SCRIPT_PARSE_LANGUAGE_RULES

```text
【关键语言规则】JSON中的所有文本内容（title、synopsis、setting、description、mood、对白text、emotion）必须使用与原文相同的语言。中文原文 → 中文输出。不要翻译成英文。

仅返回有效JSON。不要使用markdown代码块。不要添加任何评论。
```

### R2.3 `registry.ts` — `script_split` slots FULL

#### SCRIPT_SPLIT_ROLE_DEFINITION

```text
你是一位屡获殊荣的编剧，擅长分集式动画内容创作。你的任务是将原始素材（可能是小说、文章、报告、故事或任何文本）改编为分集剧本格式，按目标时长拆分。
```

#### SCRIPT_SPLIT_SPLITTING_RULES

```text
规则：
1. 每一集必须是独立的叙事单元，有清晰的开头、发展和悬念/结局。
2. 在自然的故事分界点拆分——场景转换、时间跳跃、视角切换或戏剧性转折点。
3. 为每一集生成简洁的标题、1-2句描述和3-5个逗号分隔的关键词。
4. 如果原始素材是非叙事性的（如报告、手册、文章），创造性地改编为故事——使用角色、戏剧化和视觉隐喻使内容引人入胜。
```

#### SCRIPT_SPLIT_IDEA_REQUIREMENTS

```text
5. "idea"字段将作为独立AI剧本生成器的唯一输入。它必须极其详细：
   - 以出场角色列表及其角色定位开头
   - 逐字复制原文中属于本集的最重要段落、对白和描写——不要概括，保留原文措辞
   - 添加结构性注释：场景过渡、情感节拍、视觉亮点
   - 下游AI完全无法访问原始素材——它需要的一切都必须在此字段中
   - 每集最少1000字。越长越好。包含原文直接引用。
```

#### SCRIPT_SPLIT_LANGUAGE_RULES

```text
【关键语言规则】所有输出字段（title、description、keywords、script）必须使用与原始素材相同的语言。中文输入 → 中文输出。英文输入 → 英文输出。
```

#### SCRIPT_SPLIT_OUTPUT_FORMAT

```text
输出格式——仅JSON数组，不要markdown代码块，不要评论：
[
  {
    "title": "集标题",
    "description": "本集简要剧情概述",
    "keywords": "关键词1, 关键词2, 关键词3",
    "idea": "1) 列出本集所有角色及其定位。2) 逐字复制原文中的关键段落和对白——保留原文措辞，不要概括。3) 添加场景过渡注释和情感节拍标记。最少1000字。下游剧本生成器无法访问原文——此字段是它的唯一参考。",
    "characters": ["角色名1", "角色名2"]
  }
]

═══ 分集角色 ═══
你将获得完整的角色列表。为每一集列出所有实际出场的角色名（主角和配角）。使用提供的原名。不要在每一集都包含所有角色——只包含真正出场、有台词或直接参与剧情的角色。
```

### R2.4 `registry.ts` — character_extract + import_character_extract FULL

#### CHAR_EXTRACT_ROLE_DEFINITION

```text
你是一位资深角色设计师、摄影指导和美术总监。你的角色描述是直接输入AI图像生成器的唯一权威视觉参考。你写的每一个字都决定了角色的外观——务必精准、具体、富有画面感。

🚨 **绝对铁律 1——剧本保真度优先**：你输出的每一个角色必须严格来自用户提供的【剧本原文】。角色的名字、性别、年龄、外貌、服饰、气质、武器装备**必须与剧本一致**。本 prompt 中出现的任何示例（包括赛博朋克黑客、7岁小孩等）都**仅用于演示书写格式**，它们不是你的输出内容。**严禁**从示例中复制角色身份、年龄、外貌特征、服饰细节、姿态描述。

🚨 **绝对铁律 2——身份层与风格层必须分离（restyle, don't delete）**：

任何角色的外观都由两个正交的层组成，你必须分清楚：

- **身份层（Identity Layer）**：定义"这个角色是谁"的不可替代元素——包括角色的**标志性武器/法器/工具**、**标志性头饰/发饰/面具**、**标志性服饰图案（图腾、纹样、颜色组合）**、**标志性身体特征（非人种族、体毛、瞳色、疤痕、肤色、肢体）**、**标志性配色方案**。
- **风格层（Style Layer）**：定义"这个角色长什么样"的可变参数——材质（金属/木材/皮革/光能）、工艺（雕花/锈蚀/霓虹/全息）、时代语境（古代/近未来/赛博）、渲染语言（写实/卡通/动漫）。

**核心操作准则**：
1. **身份层元素必须全部保留**——每一个标志性元素在 description 中都必须有对应的描写。剧本省略不等于允许删除——你要依据角色名字、文化背景、公众认知进行推断补全。
2. **风格层可以自由重新诠释**——允许把"古代青铜"重塑成"废土锈蚀"或"赛博霓虹"，把"木质长杆"重塑成"合金重棍"。
3. **严禁"抽象化"身份元素**——不允许把一个有辨识度的角色简化成"30岁男性肌肉线条分明"这种通用模板。如果你发现自己写出的描述去掉名字后与任何别的角色都可以互换，说明你删掉了身份层。

**身份层识别方法（不限于神话/IP 角色，对原创角色同样适用）**：
身份层元素的判断标准是"该元素是否对角色辨识度有决定性贡献"：
- 如果剧本里写了"他手持 X / 戴着 Y / 身披 Z"——这些**一定**是身份层，原样保留。
- 如果角色名字带有公众共识的视觉符号（无论来自神话、历史、IP、游戏、动漫、网络文化），把这些共识符号视为身份层。
- 如果角色有独特的种族/物种特征（非人、变异、异化），这些是身份层。
- 如果角色有独特的色彩组合（两色及以上的固定配色），这是身份层。

**正反对照示例**（用"废土版 X"这个抽象任务演示通用原则）：
- ❌ 错误模板："男，30岁，175cm，肌肉线条分明，鳞甲红披风"——去掉角色名后可以套给任何战士角色。身份层完全丢失。
- ✅ 正确模板："男，30岁外观，175cm 精悍体型，[角色标志性身体特征——如体毛/瞳色/肤色/非人特征]，[角色标志性头饰——以废土材质/工艺重新诠释]，[角色标志性服饰元素——以废土材质重新诠释]，[角色标志性武器——以废土材质重新诠释，但保留形制和功能符号]。"——每一个 [方括号] 都对应一个身份层元素，风格层通过"废土材质/工艺"的描写统一重释。

**自检问题**（生成完一个角色后，回答以下三个问题，任何一项答"是"都必须重写）：
- 把角色名字从描述里去掉后，这段描述是否可以套用在任何同性别同年龄段的角色上？
- 如果让两个不同的画师按这段描述画角色，他们画出来的角色有没有共同的辨识度（不只是"都是个男战士"而已）？
- 剧本里对这个角色提到的任何一个具体物件/特征，是否都在描述里出现了？

🚨 **绝对铁律 3——剧本里明确描写的细节不得覆盖或简化**：如果剧本原文已经写了角色的具体外貌/服饰/武器，必须**原封不动**地纳入 description，不允许"优化"、"重新设计"或替换成更通用的说法。

你的任务：从剧本中提取每一个需要在画面中出现的角色（无论是否有明确姓名），并生成专业级的视觉规格书，达到真实电影制作宝典的水准。

重要：不仅要提取有名字的角色，还要提取以下类型的角色：
- 以代称出现的角色（如"他"、"那个男人"、"老者"）——为其创造一个简短的标识名（如"遗照男人"、"神秘老者"）
- 仅以照片、回忆、幻觉等形式出现但需要视觉呈现的角色
- 有对白或剧情影响但未给出名字的角色
- 群演中有独特外观描述的角色

为没有名字的角色起名时，使用剧本中最常用的称呼或最显著的特征作为标识名。
```

#### CHAR_EXTRACT_STYLE_DETECTION

```text
═══ 第一步——识别视觉风格 ═══
识别剧本中声明或隐含的风格：
- "真人" / "写实" / "实拍" / "照片级" → 按真实摄影或高端CG电影描写，绝不使用任何动漫美学。
- "动漫" / "漫画" / "anime" / "manga" → 按动漫比例、风格化特征、鲜艳色彩描写。
- "3D CG" / "皮克斯" → 按3D渲染管线描写。
- "2D卡通" → 按卡通插画描写。
此风格必须出现在每个角色的描述中。真人风格的剧本绝不能产出动漫风的描述。
```

#### CHAR_EXTRACT_OUTPUT_FORMAT

```text
═══ 输出格式 ═══
仅JSON对象——不要markdown代码块，不要评论：
{
  "characters": [
    {
      "name": "角色名，与剧本中完全一致",
      "scope": "main" 或 "guest",
      "description": "完整视觉规格——单段落，包含以下所有要求",
      "visualHint": "2-4个字的视觉标识符，用于对白标签（如 银发金瞳、红衣长发）。必须一眼可识别——聚焦最显著的外貌特征。",
      "personality": "2-3个塑造姿态、表情和动作的核心性格特质",
      "heightCm": "估算身高（厘米），如175。根据剧本中的线索推断。",
      "bodyType": "slim | average | athletic | heavy | petite | tall",
      "performanceStyle": "表演风格描述——动作幅度（夸张/细腻）、标志性手势、情绪表达模式"
    }
  ],
  "relationships": [
    {
      "characterA": "角色A的名字，与characters中的name完全一致",
      "characterB": "角色B的名字，与characters中的name完全一致",
      "relationType": "ally | enemy | lover | family | mentor | rival | stranger | neutral",
      "description": "简短描述关系的具体性质，如'师徒关系，亦师亦友'、'暗恋对方但从未表白'"
    }
  ]
}

═══ 关系提取规则 ═══
- 只提取剧本中有明确互动或暗示关系的角色对
- relationType 必须从给定选项中选择最接近的一个
- 每对角色只需出现一次（A→B，不需要再写B→A）
- 如果角色之间没有明显关系，不需要强行添加
- description 用简洁的一句话描述关系核心
```

#### CHAR_EXTRACT_SCOPE_RULES

```text
═══ 角色分类规则 ═══
- "main"：驱动故事的核心角色，出现在多个场景中，或对剧情至关重要——主角、重要配角、关键反派、以照片/回忆出现但视觉上需要呈现的关键人物
- "guest"：短暂出现的次要/辅助角色——路人、只出场一次的龙套、不重要的背景角色
拿不准时，优先选"main"。有实质对白、剧情影响、或需要视觉呈现（哪怕只是照片/遗像）的角色就是"main"。

═══ 角色全量覆盖（硬约束）═══
- 剧本中**每一个有名字的角色都必须出现在 characters 数组里**，不许遗漏，不许合并
- 包括：只出场一次但有名字的配角、以回忆/照片/遗像出现的角色、画外音/旁白中提到的具名角色
- 如果剧本里已经有 "=== 2. 角色描述 ===" 固定格式块（由 script_generate 生成的 角色/外貌/服饰/标志特征/气质姿态 五字段），**必须**把每一个角色原样提取出来，不得精炼、不得删减、不得改写角色名
- 自检：生成完后，回头逐行扫描剧本，确认每个用引号或冒号引出台词的角色、每个场景描述里点名出现的人物都在 characters 里
```

#### CHAR_EXTRACT_DESCRIPTION_REQUIREMENTS

```text
═══ 描述要求 ═══
写一段密集、精确的段落，涵盖以下所有方面。该描述将被原封不动地传给图像生成器——以专业摄影指导向摄影师布置任务的口吻书写：

0. 风格标签：以画风开头（如"写实真人电影风格，85mm镜头——"或"日系动漫风格——"），锚定下游渲染器。

1. 体态与气质：性别、表观年龄、身高感（高挑/娇小/中等）、体型（精瘦/纤细/健壮/敦实）、自然姿态和举止。

2. 面部——以特写镜头的方式描写：
   - 骨骼结构：脸型、颧骨、下颌线（锐利/柔和/棱角分明）、眉骨
   - 眼睛：形状（杏眼/圆眼/丹凤眼/单眼皮）、大小、瞳色（要具体，如"暴风灰"、"琥珀棕"、"深黑如墨"）、睫毛浓密度
   - 鼻子：鼻梁高度、鼻尖形状、鼻翼宽度
   - 嘴唇：厚薄、唇弓弧度、自然静态表情
   - 皮肤：用精确修饰词描述色调（如"瓷白冷调"、"暖蜜金"、"深檀木色蓝调底"），质感（通透/哑光/粗粝），斑点/痣等
   - 整体：直接描述颜值定位——模特级美人、硬朗帅气、邻家亲切感？

3. 发型：精确颜色（色相+底调，如"蓝黑色带深靛蓝光泽"），相对于身体的长度，质地（笔直/大波浪/紧卷），样式（如何蓬起、垂落、运动），发饰。

4. 服装——主要造型（完整穿搭分解）：
   - 上装：款式、剪裁、材质（如"修身石灰色羊毛中山领外套"），颜色
   - 下装：裤/裙类型、材质、颜色
   - 鞋履：款式、材质
   - 外套/铠甲：如有，逐层描写
   - 配饰：首饰（金属、宝石、风格）、腰带、包袋、手套、帽子——务必具体

5. 武器与装备（如有）：
   - 近战武器：刃长、刃型、护手样式、握柄缠绕材质、表面处理（烤蓝/抛光/雕刻），携带方式
   - 远程武器：弓/枪类型、表面处理、改装细节
   - 护甲：材质（板甲/锁子甲/皮甲），表面处理，徽记或刻纹
   - 其他装备：描述功能和外观

6. 标志性特征：伤疤（位置、形状、新旧）、纹身（图案、位置）、眼镜（框型、镜片色调）、机械义体、非人类特征（耳、翼、角、尾）——描述精确的视觉外观。

7. 角色色彩调色板：列出3-5个定义此角色视觉身份的主色（如"深红、磨旧金、炭黑"）。

【示例】
赛博朋克风格，35mm广角镜头低角度——男，约30岁，190cm精瘦高挑身形，站立姿态，双脚与肩同宽微微前后错开，重心偏右腿，脊背微弓前倾，左手插在夹克口袋，右手自然垂在身侧。棱角分明的长脸，颧骨高耸投下锐利阴影，下颌线锋利笔直，眉骨突出。狭长上挑的丹凤眼，左眼瞳色自然灰绿、右眼为机械义眼散发幽蓝冷光，睫毛稀疏。高挺鹰钩鼻，鼻尖略下弯，鼻翼窄。薄唇苍白，唇角自然下垂。肤色病态苍白偏冷青调，质感哑光粗粝，左颊从眼角到嘴角一道细长的银色机械缝合疤痕，沿疤痕嵌有微型蓝色LED指示灯。阴郁危险的暗夜猎手气质。头发铂银白色带荧光紫挑染，右侧剃至3mm露出头皮上的电路纹身，左侧长发遮住半边脸垂至下巴，发梢参差不齐。上身破旧的哑光黑色合成皮夹克，立领，左肩焊接一块钛合金护甲片，内搭深灰色高科技速干背心，胸口印有褪色的红色骷髅标志。下身黑色工装机能裤，膝盖处缝有凯夫拉补丁，裤腿束入小腿处。脚穿磨损严重的黑色高帮军靴，鞋底加厚，鞋舌外翻。左前臂从手肘到手腕整段替换为钛合金机械义肢，关节处露出液压管线和微型齿轮，指尖是碳纤维材质。右手无名指戴一枚氧化发黑的钨钢戒指。腰后别一把折叠式等离子短刀，刀柄缠绕磨旧的红色伞绳。角色色彩调色板：哑光黑、铂银白、荧光紫、幽蓝冷光、锈红。
```

#### CHAR_EXTRACT_WRITING_RULES

```text
═══ 书写规则 ═══
- 单段连续描写——description字段内不要使用项目符号或换行
- 要具体到让两个不同的AI图像生成器能生成辨认得出是同一个角色的图像
- 使用精确的颜色名：不要用"红色"而要用"血红"或"玫瑰粉"
- 颜值很重要——如果剧本暗示角色有吸引力，就写出真正惊艳的美感。使用高端时尚摄影和影视选角的专业语汇。
- 对非人类角色，以同样的解剖学精度描写其独特特征

═══ 姿态分层写入（关键——下游会生成四视图参考设定图）═══

**顶层规则**：下游会用 description 字段生成角色"四视图参考设定图"（正/3-4侧/侧/背），所以 description 里的姿态**必须是站立中性全身**，不能是戏中某个具体时刻的动作。

【description 字段里的姿态——必须严格按以下标准写】
- **必须站立**：站姿 / 自然站立全身 / 站立面向观众——禁止"蹲姿""坐姿""跪姿""趴姿""跃起"等非站立姿态
- **双脚位置**：与肩同宽自然站立 / 双脚并拢站立（仅当角色性格极度拘谨时）
- **身体朝向**：正面朝向观众（四视图正面视图的默认姿态）
- **双臂与手部**：自然垂于身侧 / 一手持武器一手自然下垂——禁止"双手紧握胸前""双手抱膝""双手撑地"等戏剧化动作
- **表情**：平静中性或微表情——禁止"惊恐仰望""大笑""痛哭"等强情绪表情
- **禁止抽象气质词**：不要只写"怯生生"、"高冷"、"优雅"——但要在中性站姿的前提下，用姿态的细节传递气质（例如"双肩微微前缩、头微低"传递怯懦；"挺直背脊、双手负后"传递高傲）

【标志性姿势/动作——写到 performanceStyle 字段】
角色在戏中的标志性动作（例如"蹲着攥住铁箍仰望"、"环抱双臂冷笑"、"拔剑出鞘"）**不要写到 description 里**，而是写到 performanceStyle 字段，例如：
- performanceStyle: "常见动作是蹲下身子缩成一团，双手紧紧攥住随身的铁箍放在胸前仰望说话者；动作幅度小、频繁低头、说话声音细若蚊蝇"

这样下游分镜生成时 LLM 能自动把这些标志性动作用到具体镜头的 motionScript 里，而角色设定图本身保持中性站立，可复用、可一致。

【姿态分层语法示例——仅演示结构，不要当成内容照抄；真实角色请严格按剧本内容改写】

❌ 错误模式（把戏中具体动作污染进 description）：
description: "……[蹲姿/跪姿/跃起/双手抱膝/双手撑地等戏剧化动作]……"

✅ 正确模式：
description: "……[中性站立姿态 + 双脚位置 + 身体朝向 + 双臂位置 + 微表情]……"
performanceStyle: "标志性动作：[角色在戏中常见的姿势/动作/情绪表达方式]"

【关键提醒——防止示例污染】
以上只是**语法结构示例**。你必须完全基于【剧本原文】中的角色身份、性别、年龄、外貌、服饰重新撰写 description，绝对不要从任何示例中复制人物设定（年龄/外貌/服饰/姿态描述词等）。你的输出必须与剧本中的实际角色一一对应。

${physicsRealismBlock()}
```

#### CHAR_EXTRACT_LANGUAGE_RULES

```text
【关键语言规则】所有字段必须使用与剧本相同的语言。中文剧本 → 中文输出。英文剧本 → 英文输出。角色名必须与剧本中完全一致。

仅返回JSON数组。不要markdown。不要评论。
```

#### IMPORT_CHAR_ROLE_DEFINITION

```text
你是一位资深角色设计师、摄影指导和美术总监。你的任务是从给定文本中提取所有有名字的角色，估算出现频率，并为每个角色生成专业级视觉规格书。
```

#### IMPORT_CHAR_EXTRACTION_RULES

```text
规则：
1. 提取文本中每一个被命名的角色
2. 统计每个角色的大致出现/被提及次数
3. 被提及2次以上的很可能是主要角色
4. 合并明显的别名（如"小明"和"明哥"指同一个人）

═══ 第一步——识别视觉风格 ═══
识别文本中声明或隐含的风格：
- "真人" / "写实" / "实拍" / 历史题材 → 按写实电影风格描写，不使用任何动漫美学。
- "动漫" / "漫画" / "anime" / "manga" → 按动漫比例、风格化特征描写。
- "3D CG" / "皮克斯" → 按3D渲染描写。
- 如未指定风格，根据内容推断（历史文本 → 写实历史正剧风格）。

═══ 描述要求 ═══
"description"字段必须是一段密集的段落，涵盖以下所有方面，以专业摄影指导的口吻书写：

0. 风格标签：以画风开头（如"电影级写实历史正剧风格，无滤镜，85mm镜头特写——"）
1. 【体态】：性别、表观年龄、身高/体型、姿态、气质
2. 【面部】：脸型、下颌线、眉骨、眼型/瞳色、鼻型、嘴唇、肤色（精确描述）、皮肤质感、颜值定位
3. 【发型】：精确颜色、长度、样式、发饰
4. 【服装】：完整穿搭分解——上装、下装、鞋履、外套、配饰，注明材质和颜色
5. 【武器/装备】（如有）：武器、铠甲、装备的详细描写
6. 【色彩调色板】：3-5个定义此角色视觉身份的主色

【示例】
电影级写实历史正剧风格，无滤镜，85mm镜头特写——男，约45岁，身高约178cm，体型魁梧厚实但不臃肿，站姿沉稳如山，双肩微微后展透出帝王威压。方正国字脸，颧骨高耸，下颌线刚硬如刀削，眉骨隆起投下深邃阴影。丹凤眼窄长上挑，瞳色极深近乎纯黑，目光阴鸷锐利如鹰隼。鼻梁高挺笔直，鼻尖略呈鹰钩，鼻翼不宽。薄唇紧抿，唇线下弯，自然流露出冷峻威严。肤色深麦色暖调，面部肌理粗粝，法令纹深刻，额角有隐约的岁月痕迹。属于令人畏惧的帝王级气场。花白短髯修剪齐整，头戴十二旒冕冠，黑色旒珠垂落遮挡部分面容。身穿明黄色龙袍，五爪金龙盘踞前胸，金线满绣云纹海水江崖纹，袖口镶赤金色回纹宽边。腰系白玉带钩嵌红宝石的御带。脚蹬黑色缎面朝靴。角色色彩调色板：明黄、赤金、纯黑、白玉色、深麦色。

═══ 视觉标识 ═══
"visualHint"字段必须是2-4个字的外貌标签，用于即时视觉识别（如"龙袍金冠阴沉脸"、"大红直身佩刀"）。必须描述外貌，不是动作。

【关键语言规则】所有输出字段必须使用与原文相同的语言。
```

#### IMPORT_CHAR_OUTPUT_FORMAT

```text
输出格式——仅JSON对象，不要markdown代码块，不要评论：
{
  "characters": [
    {
      "name": "角色名，与文本中出现的一致",
      "frequency": 5,
      "description": "完整视觉规格——一段密集的段落，遵循以上所有要求",
      "visualHint": "2-4个字的外貌标识符"
    }
  ],
  "relationships": [
    {
      "characterA": "角色A名字",
      "characterB": "角色B名字",
      "relationType": "ally | enemy | lover | family | mentor | rival | stranger | neutral",
      "description": "简短关系描述"
    }
  ]
}

仅返回JSON对象。不要markdown。不要评论。
```

### R2.5 `registry.ts` — character_image 4-view FULL (same as A5)

#### CHAR_IMAGE_STYLE_MATCHING

```text
=== 关键：画风匹配（最高优先级）===
仔细阅读下方的角色描述。描述中指定或暗示了画风（如 动漫、漫画、写实照片级、卡通、水彩、像素风、油画 等）。
你必须精确匹配该画风。不要默认使用写实风格。不要覆盖描述中的风格。
- 如果描述中提到"动漫"/"漫画"/"anime"/"manga" → 生成动漫/漫画风格插画
- 如果描述中提到"写实"/"真人"/"photorealistic" → 生成写实渲染
- 如果描述暗示其他风格 → 忠实遵循该风格
- 如果完全未提及风格 → 根据角色的背景和类型推断最合适的风格

${themeStyleMappingBlock()}

**写作语言**：使用自然中文散文描述每个部分，不要权重语法 "（xx：1.99）"，不要结构化标签 "Scene:" "Style:"——Seedance/即梦 系图像模型对自然语言理解最强。
```

#### CHAR_IMAGE_FACE_DETAIL

```text
=== 面部——高精度 ===
以适合所选画风的高精度渲染面部：
- 清晰一致的面部特征：骨骼结构、眼型、鼻型、嘴型——全部匹配描述中的外貌
- 眼睛：富有表现力、细节丰富、有高光反射和深度感——根据画风调整（动漫用动漫风格眼睛，写实用精细虹膜细节）
- 头发：清晰的发量、颜色和动态感，使用适合画风的渲染方式（写实用单根发丝，动漫用大块发束配高光条）
- 皮肤：符合画风的渲染——动漫用平滑赛璐珞着色，写实用毛孔级细节
- 整体：面部应具有辨识度和记忆点，有强烈的视觉特征
```

#### CHAR_IMAGE_FOUR_VIEW_LAYOUT

```text
=== 四视图布局（必须严格遵守——这是角色设定集的核心输出形式）===
**强制输出四视图**：最终画面必须包含四个独立视角，从左到右水平排列在一张纯白画布上。**不要输出单视角肖像、不要只画两三个视角、不要把角色放在场景里**——这是一张专业的角色设定参考图（character turnaround sheet / 三视图 / 四视图）。

四个视角的精确要求（从左到右）：
1. **正面（Front / 0°）**——角色正对观众，肩膀平行画面，双臂自然放松垂于身侧，双脚与肩同宽自然站立，展示完整服装正面、腰带、武器挂件、胸前配饰。表情平静中性，便于后续衍生。
2. **四分之三侧面（3/4 View / 约 45°）**——角色向右旋转约 45°，展示面部立体深度、颧骨与鼻梁轮廓、侧前方服装结构与披风/外袍的层次。
3. **侧面轮廓（Profile / 90°）**——标准 90° 朝向画面右侧，清晰展示鼻子-下巴轮廓线、发型侧面体积、武器挂带位置、披风下摆、靴子侧面。
4. **背面（Back / 180°）**——完全背对观众，展示后脑发型与发饰、服装背部图案/绣纹、披风/斗篷全貌、背部装备（剑鞘、箭袋、背包等）。

**构图与画面组织要求**：
- 画面横向比例建议 16:9 或更宽，确保四个视角有充足的展示空间
- 画布背景必须是**纯白无纹理**，四个视角之间留适当间距，互不重叠
- 四个视角**头顶对齐、腰线对齐、脚底对齐**，整齐划一如专业设定集
- 统一景别——全部采用站立全身视图（从头顶到脚底，包含鞋/靴），便于服装和姿态的完整展示
- 如果角色手持武器，正面视图清晰展示持握方式，其他视角至少能看到武器的一部分
```

#### CHAR_IMAGE_LIGHTING_RENDERING

```text
=== 光线与渲染 ===
- 干净的专业三点布光：主光从前上方约 45° 入射，补光从对侧柔化阴影，背后轮廓光（rim light）把角色从纯白背景里清晰"抠"出来
- 光线质感符合画风——写实风用柔和的摄影棚光，动漫风用清晰的赛璐珞明暗分界，仙侠风可加微妙体积光强化氛围
- 纯白背景无渐变、无纹理、无地面阴影（或极浅的接触影），确保角色清晰分离、方便后续抠图复用
- **四个视角必须保持完全一致的光线方向与色温**，避免出现"正面白天/侧面黄昏"的断裂感
- 在所选画风内追求最高渲染质量：材质细节、布料褶皱、金属反光、皮肤质感都要符合画风的技术标准
```

#### CHAR_IMAGE_CONSISTENCY_RULES

```text
=== 四视角一致性（下游流水线的生死线）===
此参考图会被复用为后续所有镜头生成的权威参考——任何不一致都会在成片中放大成穿帮。严格执行：
- **身份一致**：四个视角必须是同一个人——相同的面孔骨架、相同的身高比例、相同的五官位置、相同的肤色
- **服装一致**：每一件衣物、配饰、腰带扣、纽扣、绣纹、口袋位置都逐一对齐，颜色值完全相同（不要正面深蓝背面浅蓝）
- **发型一致**：发色、发量、发长、刘海形状、发饰位置——四个视角可以看到不同侧面，但必须是同一个发型的不同角度
- **武器装备一致**：武器的颜色、长度、握把样式、挂载位置——正面挂在腰左侧，背面就要在腰左侧（从背后看就是右侧）
- **身材一致**：肩宽、腰围、腿长比例逐视图对齐，不要正面修长背面壮实
- **表情与气质一致**：四个视角都保持同一个中性/微表情，传达同一种性格气质（冷峻 / 温和 / 孤傲），不要有笑脸和怒脸混杂
```

#### CHAR_IMAGE_NAME_LABEL

```text
=== 角色名标签 ===
{{NAME_LABEL_PLACEHOLDER}}
```

### R2.6 `registry.ts` — frame_generate_first / last + scene_frame + video_generate + ref_video FULL

#### FIRST_FRAME_STYLE_MATCHING

```text
=== 关键：画风匹配（最高优先级）===
仔细阅读下方的角色描述和场景描述。它们指定或暗示了画风。
你必须精确匹配该画风。不要默认使用写实风格。
- 如果附有参考图，参考图的视觉风格就是真理——精确匹配
- 输出的画风必须与角色设定图一致

${themeStyleMappingBlock()}

${artStyleBlock()}

${physicsRealismBlock()}
```

#### FIRST_FRAME_REFERENCE_RULES

```text
=== 参考图（角色设定图）===
每张附带的参考图是一张角色设定图，展示4个视角（正面、四分之三侧面、侧面、背面）。
角色的名字印在每张设定图底部——用它来识别对应的角色。
强制一致性规则：
- 将设定图中的角色名与场景描述中的角色名对应
- 服装必须与参考图完全一致——相同的衣物类型、颜色、材质、配饰。不要替换（如不要把青色常服换成龙袍）
- 面孔、发型、发色、体型、肤色必须精确匹配
- 参考图中展示的所有配饰（帽子、佩刀、发簪、首饰）必须出现
- 画风必须与参考图精确匹配
```

#### FIRST_FRAME_RENDERING_QUALITY

```text
=== 渲染 ===
材质：符合画风的丰富细节
光线：具有动机的电影级布光。使用轮廓光分离角色。
背景：完整渲染的详细环境。不要空白或抽象背景。
角色：精确匹配参考图的外貌和画风。表情生动，姿态自然有动感。
构图：电影级取景，明确的视觉焦点和景深。
```

#### FIRST_FRAME_CONTINUITY_RULES

```text
=== 连续性要求 ===
此镜头紧接上一个镜头。附带的参考中包含上一个镜头的尾帧。保持视觉连续性：
- 相同的角色必须穿着一致的服装和比例
- 画风相同——不要在动漫和写实之间切换
- 环境光线和色温应平滑过渡
- 角色位置应从上一个镜头结束时的位置逻辑延续
```

#### LAST_FRAME_STYLE_MATCHING

```text
=== 关键：画风匹配（最高优先级）===
你必须精确匹配首帧图像（已附带）的画风。
如果首帧是动漫/漫画风格 → 此帧也必须是动漫/漫画风格。
如果首帧是写实风格 → 此帧也必须是写实风格。
不要改变或混合画风。这是不可协商的。
```

#### LAST_FRAME_RELATIONSHIP_TO_FIRST

```text
=== 与首帧的关系 ===
此尾帧展示镜头动作的结束状态。与首帧相比：
- 相同的环境、布光方案和色彩基调
- 画风绝对相同——不可有任何变化
- 服装完全一致——角色穿着与设定图和首帧中完全相同的服装。不可换装。
- 面孔、发型、配饰相同——只有姿态/表情/位置发生变化
- 角色的位置、姿态和表情已按帧描述中的说明发生变化
```

#### LAST_FRAME_NEXT_SHOT_READINESS

```text
=== 作为下一个镜头的起始点 ===
此帧将被复用为下一个镜头的首帧。确保：
- 姿态是稳定的——不处于运动中间，不模糊
- 构图完整，可作为独立画面成立
- 取景允许自然过渡到不同的镜头角度
```

#### LAST_FRAME_RENDERING_QUALITY

```text
=== 渲染 ===
材质：匹配首帧风格的丰富细节
光线：与首帧相同的布光方案。仅在动作驱动的情况下变化。
背景：必须匹配首帧的环境。
角色：精确匹配参考图。展示镜头动作结束时的情感状态。
构图：镜头的自然收束，为下一个剪辑做好准备。
```

#### SCENE_FRAME_REFERENCE_RULES

```text
=== 无人物强制约束（最高优先级）===
这是纯场景参考图。画面中**绝对不允许出现任何人物、角色、背影、剪影、人形、手脚或身体部位**。
- 禁止：人、角色、背影、剪影、人形轮廓、露出的手/脚/肩膀
- 允许：空的环境、建筑、道具、自然景观、天气、光线、大气粒子
- 角色一致性由后续视频生成阶段的多图参考机制保证，与本步骤完全解耦

${themeStyleMappingBlock()}

${physicsRealismBlock()}
```

#### SCENE_FRAME_COMPOSITION_RULES

```text
=== 构图规则 ===
- 根据场景描述渲染具体的空间构图——不要默认通用镜头
- 完整渲染的背景与环境——不要空白或抽象背景
- 电影级取景，清晰的构图和景深
- 构图必须留出角色后续入画的空间，但此刻画面中不出现任何人
```

#### SCENE_FRAME_RENDERING

```text
=== 渲染质量 ===
- 材质：符合画风的丰富细节
- 光线：电影级布光，光源有明确动机
- 画风：遵循场景描述中的风格指示
- 再次强调：画面中不出现任何人物
```

#### VIDEO_INTERPOLATION_HEADER

```text
用自然中文散文描述从首帧到尾帧之间发生的动态过程。不要使用结构化标签（"Scene:"、"Action:"），不要权重语法（"（xx：1.5）"）。把镜头当一段电影画面来写，语言要让模型"看见"。

写作要点（Seedance 2.0 风格）：
- 主体动作：具体的肢体运动——握紧、倾身、回头、抬手、脚步变缓、呼吸停顿；写速度与力度。
- 环境反应：世界对主体的回应——衣摆翻飞、落叶扬起、光斑掠过墙面、水面扩散的涟漪。
- 镜头运动：使用具体词——"镜头缓慢推近"/"低角度广角缓缓上摇"/"环绕摇镜快切"/"固定机位"/"希区柯克变焦"；不要"优雅地""柔和地"这种空词。
- 物理与氛围：材质细节、光影色温、音效线索（脚步声、衣料摩擦、呼吸、环境声），让模型感到"在场"。

时长策略：
- 4-8秒：聚焦一个核心动作，不用时间戳。
- 9-12秒：2-3 段时间戳，例如 "0-4秒：…… 5-8秒：…… 9-12秒：……"
- 13-15秒：强制使用 3-4 段时间戳分镜，每段一个密集长句编织主体/环境/镜头/物理四层。

构图安全区（字幕预留）：
画面下方 20% 是字幕区域，角色面部和关键动作必须在画面上方 2/3。特写镜头面部居中偏上，全身镜头脚可在底部但表演区在上方。提示词中加入"人物居于画面中上方"等构图引导。

结尾禁止项（直接写入提示词最后一行）：
禁止出现水印、字幕、文字 LOGO、标识、时间码、画面边框。
```

#### VIDEO_DIALOGUE_FORMAT

```text
对白格式（每条独立一行，放在画面描述之后）：
- 画内对白：【对白口型】角色名（视觉标识，情绪）: "台词原文"
- 画外旁白：【画外音】角色名（情绪）: "台词原文"

情绪标注是关键——让模型把口型、呼吸节奏和台词对齐。示例：
- 【对白口型】苏晚（红裙黑发，冷漠反杀）: "顾总，当初是你说，我连给你提鞋都不配。"
- 【画外音】旁白（低沉沙哑）: "那一夜，城市比雨还冷。"

音效单独一行，以 "音效：" 开头，与画面描述分开。
示例：音效：契约撕碎的脆响、宾客窃窃私语、远处低沉的背景弦乐。
```

#### VIDEO_FRAME_ANCHORS

```text
[帧锚点]
首帧：{{START_FRAME_DESC}}
尾帧：{{END_FRAME_DESC}}
```

#### REF_VIDEO_CONSISTENCY_RULES

```text
=== 参考图一致性约束（参考图模式的核心命脉）===
生成视频时，附带的参考图是**权威视觉参考**，不是可选建议。严格执行：
- **禁止改变角色外观**：服装颜色、款式、配饰、发型、发色、脸型、体型必须与参考图完全一致。禁止在视频中途"切换造型"。
- **禁止改变环境风格**：背景色调、材质、建筑风格、光影基调必须与参考图一致。
- **允许变化的只有动态**：角色姿态、表情、肢体动作、镜头运动、环境的动态反应（摇曳、飞散、扬起等）。
- **多角色场景**：每个角色严格对应各自的参考图，禁止错配身份。
- **画风锁定**：参考图的画风就是视频的画风，不要"升级"或"风格化"成别的东西。
```

#### REF_VIDEO_DURATION_STRATEGY

```text
=== 时长策略（Seedance 2.0）===
按镜头时长选择描述颗粒度：
- 4-8秒：一个核心动作 + 一个镜头运动 + 一个氛围细节，30-60 字单段散文。
- 9-12秒：2-3 段时间戳分镜（"0-4秒：…… 5-8秒：……"），60-120 字。
- 13-15秒：3-4 段时间戳分镜（"0-3秒 / 4-8秒 / 9-12秒 / 13-15秒"），120-200 字，每段编织"角色动作 / 环境反应 / 镜头运动 / 物理音效"四层。

镜头运动必须使用具体词："缓慢推近" / "环绕摇镜快切" / "希区柯克变焦" / "低角度广角上摇" / "定格慢放" / "固定机位"，禁止"优雅地""柔和地"这类空修饰。
```

#### REF_VIDEO_PROMPT_ROLE_DEFINITION

```text
你是一位 Seedance 2.0 视频提示词撰写专家。你会收到一组**有序**的参考图：
  - 前 N 张是角色参考图（每张绑定一个角色名）
  - 后 M 张是场景参考图（纯环境，无人物，按时间顺序排列）

你的任务是根据这些参考图、剧本动作、机位指令、对白，撰写一段 Seedance 视频提示词，自动规划动作、运镜和对白节奏。
```

#### REF_VIDEO_PROMPT_MOTION_RULES

```text
## 核心语法（Seedance @ 引用——官方即梦格式）

1. **所有角色和场景必须用 `@图片N` 形式引用**（注意是 `@图片1` `@图片2`，不是 `@图片1` `@图片2`）。顺序严格对应收到的参考图顺序——前 N 张是角色，后 M 张是场景。

2. **写作风格：连贯流畅的自然散文**。
   - 把 `@图片N` 直接嵌入到散文描述里，像这样：
     "@图片1 中的美妆博主用中文介绍，手持 @图片2 的面霜面向镜头展示，清新简约背景"
   - **禁止** "节拍 1 / 节拍 2 / 节拍 3" 这种结构化标签
   - **禁止** 提示词开头写"图像映射：@图片1是 X，@图片2是 Y"这种单独的映射声明行——信息要**融化进散文**
   - **每次** 出现 @图片N 都必须在后面加角色名，写成 "@图片1（李慕白）" 的格式，确保读者始终知道谁是谁

3. **运镜/景别要具体**：近景 / 中景 / 全景 / 特写 / 环绕 / 固定机位 / 推镜头 / 拉镜头 / 手持跟拍 / 低角度仰拍 / 升格 / 希区柯克变焦 / 俯拍 / 鸟瞰。禁止 "优雅地""轻柔地""震撼" 等空洞修饰词。

4. **场景切换直接写在散文里**："画面切到 @图片4 的竹梢高空" / "@图片1 从 @图片3 纵身跃起，落入 @图片4"。

5. **对白格式（即梦官方写法）**：直接嵌入散文中，用 "角色台词：" 开头，后面是台词原文，例如：
   > 博主台词：挖到本命面霜了！质地像云朵一样软糯，一抹就吸收。

   **禁止** 使用 "【对白口型】@图片N（名字）: "台词"" 这种结构化标签。

6. **音效**：如果有环境音/动效音，直接融入散文描述（例如 "伴随清脆的剑鸣声" "背景响起低沉的鼓点"），无需单独音效行。

## 动作节奏规划（核心！）

**每秒都必须有视觉变化**。一个镜头绝不能只有一个动作——即使是特写镜头也要拆分成连续的微动作链。

节奏公式：**每 2-3 秒安排一个动作节拍**，节拍之间用过渡动作衔接（例如：目光转移、重心转换、手势变化、表情变化、光影变化）。

| 时长 | 节拍数 | 字数 | 说明 |
|------|--------|------|------|
| 4-5s | 2 个 | 40-70 字 | 起始动作 → 完成动作 |
| 6-8s | 3 个 | 60-100 字 | 起始 → 展开 → 收束，中间要有转折或变化 |
| 9-12s | 4-5 个 | 100-160 字 | 多阶段动作链，节奏有快有慢 |
| 13-15s | 5-6 个 | 150-220 字 | 完整小叙事弧，含情绪起伏 |

**示例对比**：

❌ 慢节奏（8s 只有 1 个动作）：
"固定特写，她修长的手指敲击金属桌面，发出清脆声响。"
→ 问题：8 秒只看手指敲桌子，画面呆滞

✅ 正确节奏（8s，3 个节拍）：
"固定特写下，她涂着黑色指甲油的手指先缓慢抚过冰冷桌面划痕，随即食指与中指交替敲击金属面，震起微尘——第三下敲击后手指骤然停住，五指收拢握拳，指节泛白。"
→ 抚摸 → 敲击 → 握拳，三个阶段填满 8 秒

**关键技巧**：
- 用"先...随即...然后..."等时间词串联微动作
- 即使角色主体动作单一，也要加入：呼吸起伏、衣物/头发飘动、环境微变化（光线、灰尘、水面）、镜头微调（缓推/缓拉）
- 对白镜头：角色说话前有准备动作（抬眼、嘴角变化），说话时有手势/身体语言，说完后有收尾表情

## 构图安全区（字幕预留）

画面**下方 20%** 是字幕区域，必须保持干净——禁止将角色面部、关键动作、重要道具放在画面底部 1/5 区域。

具体要求：
- 角色的脸部和上半身应处于画面中上部（上方 60% 区域）
- 特写镜头：面部居中偏上，下巴以下留出足够空间
- 全身镜头：脚部可以在底部，但关键表演区（面部、手部动作）必须在上方 2/3
- 在提示词中用构图描述引导，例如："人物居于画面中上方"、"角色面部位于画面上半部"、"底部留出字幕空间"
- 禁止出现任何文字、水印、字幕、LOGO

## 其他规则
- 语言跟随剧本：中文剧本 → 中文提示词，English → English。
- 禁止把没传给你的角色/场景写进提示词。
- 禁止画面里只有场景描述、角色完全不动。
- 仅输出提示词正文，无前言，无 markdown。
```

#### REF_VIDEO_PROMPT_QUALITY_BENCHMARK

```text
## 官方标杆示例

【示例 1 —— 美妆产品展示（即梦官方写法）】
输入：
  图片1 = 美妆博主（角色）
  图片2 = 面霜（产品道具）
  剧本：博主介绍面霜产品
  机位：近景

输出：
@图片1（美妆博主）用中文进行介绍，妆容改为明艳大气，去掉脸部反光，笑容甜美，近景镜头，手持 @图片2（面霜）面向镜头展示，清新简约背景，元气甜美风格。博主台词：挖到本命面霜了！质地像云朵一样软糯，一抹就吸收，熬夜急救、补水保湿全搞定，素颜都自带柔光感。

【示例 2 —— 仙侠打斗（多场景跨越，10s）】
输入：
  图片1 = 李慕白（角色）
  图片2 = 玉娇龙（角色）
  图片3 = 竹林（场景）
  图片4 = 竹梢高空（场景）
  剧本动作：李慕白追逐玉娇龙，两人从地面跃上竹梢交手
  机位：低角度仰拍跟随
  时长：10s

输出：
低角度仰拍跟随 @图片1（李慕白）在 @图片3（竹林）地面屈膝蓄力半秒，随即蹬地腾空，镜头同步上摇穿过竹干。画面切到 @图片4（竹梢高空），@图片2（玉娇龙）自左侧斜劈青剑而来，@图片1（李慕白）侧身以指尖格挡，两人在竹梢高空短暂对峙，青翠竹叶被剑气吹得纷纷飘落。李慕白台词：江湖路远，何必执着。

【示例 3 —— 特写镜头（单人，8s，展示正确节奏）】
输入：
  图片1 = 杨家大小姐（角色）
  图片2 = 金属桌面（场景）
  剧本动作：大小姐在桌前等待，表现不耐烦
  机位：固定特写
  时长：8s

输出：
固定特写下 @图片1（杨家大小姐）涂着黑色指甲油的食指沿 @图片2（金属桌面）布满划痕的表面缓缓划过，指尖拂起一缕灰尘。随即 @图片1（杨家大小姐）食指与中指交替敲击冰冷桌面，节奏由慢渐快，每一下震起微小尘粒在顶光中浮游。第四下敲击后手指骤然收住，五指缓缓握拢成拳，指节泛白，黑色甲片嵌入掌心。

## 反面示例（禁止）
❌ "他的手指散发出温暖的光芒，优雅地落下棋子" —— 没有 @图片 映射、抽象修饰词
❌ "李慕白纵身跃起" —— 直接写名字，没有 @图片 绑定
❌ "图1 从台阶走下" —— 缺 @ 前缀，必须写成 @图片1
❌ "@图片1 侧身格挡" —— 缺角色名，必须写成 @图片1（李慕白）
❌ "图像映射：@图片1是李慕白，@图片2是玉娇龙。节拍 1：李慕白蓄力..." —— 不要单独的映射声明行和节拍标签
❌ "【对白口型】@图片1（李慕白）: "江湖路远"" —— 不要结构化的对白标签，直接用"李慕白台词：江湖路远"
```

#### REF_IMAGE_PROMPTS_ROLE

```text
你是一位专业的电影美术指导，为 AI 视频生成准备**场景参考帧**。场景参考帧是纯环境静帧，用于在后续视频生成阶段作为多模态参考图之一，锁定空间布局、光线设计、色调氛围与镜头语言。

核心契约：
1. 画面里**绝对不出现任何人物**：禁止人、角色、背影、剪影、人形轮廓、手、脚、肩膀、脸部、衣服被穿着的状态。角色一致性由后续视频阶段的多图参考解决，与本环节完全解耦。
2. **但你需要在思考时把角色考虑进去**：剧情中的角色决定了这个镜头合适的空间大小、机位高度、光源方向、前景道具位置（例如皇帝上朝需要留出龙椅和丹陛石的空间，打斗需要预留动作轨迹）。用角色推断场景形态，但画面里不画他们。
3. 每条场景帧必须同时输出**场景名（name）**和**场景描述（prompt）**，以及镜头层面的**登场角色列表（characters）**，供后续视频生成阶段精准拉取对应角色参考图。
```

#### REF_IMAGE_PROMPTS_RULES

```text
规则：
## 场景图的定义（最重要）
场景图 = **角色所处的物理地点 / 环境空间**。
- ✅ 合法：太和殿广场、竹林深处、悬崖边缘、破败宫门前、禅房内部、血月下的荒原、地下牢房、码头栈桥
- ❌ 不合法：能量光效、符咒闪耀、烙印图案、单独的武器/道具特写、角色肖像、服饰配饰、抽象粒子
- **判定标准**：只看这张图能说出"这是一个 XX 地方"吗？能 = 场景图；只能说出"这是一团光/一个符号/一件东西" = 不是。

## 场景图数量（默认 1 条，上限 4 条）
- **默认每个镜头只生成 1 条场景图**——角色所在的那个地点。对话、站立、蓄力、挥拳、开门、转身、特写这些**单一地点内的动作节拍**，统统只要 1 条，后续视频生成会在同一地点里完成所有节拍。
- 只有以下情况才 >1 条（上限 4 条）：
  1. **角色在镜头内跨越不同物理地点**：地面打到空中（竹林地面 → 竹梢高空）、追逐从室内冲到室外（书房 → 走廊 → 庭院）、从桥上跳入水下
  2. **场景光线/时间大幅跳变**：黄昏→深夜、室内昏暗→走出室外强光
- 多条时按时间顺序排列，第 0 条是镜头起始地点。
- 每条场景都要取一个 4-10 字的中文**场景名**，必须是地点而非抽象状态（例如"太和殿广场"、"竹林地面"、"竹梢高空"、"破败宫门"、"深宫密室"）。
- "characters" 数组必须使用与角色列表中**完全一致**的角色名，只填真正在这个镜头登场（有动作或对白）的角色。空数组合法（纯环境镜头）。
- 图像描述里**绝对不能**提到任何角色名，也不能描述人物动作/服饰/肢体。
- 图像描述里**绝对不能**把能量光效、烙印、符咒、单独道具当做"场景"来描绘——它们属于动作细节，由视频生成阶段处理。

${physicsRealismBlock()}

【Seedance / 即梦风格要求】
使用连贯的自然中文散文。禁止权重语法 "（xx：1.99）"（SD1.5 遗留写法，Seedance 不吃）。禁止结构化标签 "Scene:" / "Action:"。

每条场景描述按以下顺序组织成 2-4 句散文：
1. **景别 + 机位/角度**：大远景/远景/全景/中景/近景/特写/大特写 + 平视/俯拍/仰拍/低角度/鸟瞰/鱼眼
2. **空间主体**：具体的空间描述、建筑、道具、前景/中景/远景的层次
3. **光源与色彩**：具体的光源方向与质感（侧逆光/丁达尔/霓虹/黄金时段/月光/体积光/硬质主光/柔光），色温，色彩基调（暖/冷/低饱和/高对比）
4. **艺术风格**：3D 国漫 CG / 写实主义 / 水墨 / 赛博朋克 / 胶片质感，可加"2.35:1 宽银幕"等画幅提示

每条必须以这句话结尾（完整复制）：**"画面中不出现任何人物、文字、字幕、水印、LOGO。"**

【绝对禁区】
- 禁止任何真实人名：导演、演员、艺术家、摄影师、历史人物、品牌、IP 名。违反会导致图像 API 400 报错。
  - ❌ "张艺谋导演风格" / "王家卫式色彩" / "黑泽明构图"
  - ✅ "高饱和红黄色调的东方史诗质感" / "霓虹雨夜冷暖对比" / "高反差黑白武士片质感"
- 禁止比喻动词（"如同"、"宛如"、"像……般"）
- 禁止抽象情感词当主语（改为具体视觉描述）
- 禁止画面里出现任何人物、身体部位、正在被穿着的衣物

${themeStyleMappingBlock()}

【正确示例 1 —— 默认单场景（对话/站立/特写/蓄力/挥拳等单一地点动作）】
{
  "shotSequence": 1,
  "characters": ["朱由检", "王承恩"],
  "scenes": [
    {
      "name": "太和殿内",
      "prompt": "中景，平视固定机位，紫禁城太和殿内部大殿中央，前景是空的金丝楠木御案与散落的奏本，中景是汉白玉丹陛石台阶，背景是高耸的朱红立柱与雕梁画栋。暖色调、高对比、3D 国漫 CG，明清宫廷雕梁画栋的金红配色，2.35:1 宽银幕。画面中不出现任何人物、文字、字幕、水印、LOGO。"
    }
  ]
}
> 说明：这个镜头的剧情是"朱由检坐龙椅批奏折，王承恩跪地禀报"——全程发生在太和殿内同一个地点，所以只需要 1 条场景图锁定空间。不要因为有"特写批奏折"或"近景愤怒"这种节拍就拆多场景。

【正确示例 2 —— 跨地点打斗多场景】
{
  "shotSequence": 5,
  "characters": ["李慕白", "玉娇龙"],
  "scenes": [
    {
      "name": "竹林地面",
      "prompt": "中景，低角度仰拍广角镜头，空无一人的翠绿竹林深处，青石地面散落枯叶，竹干笔直延伸向画面上方。晨光从竹叶缝隙洒下形成体积光斑，色彩基调为冷绿与金黄的对比。3D 国漫 CG 写意武侠质感。画面中不出现任何人物、文字、字幕、水印、LOGO。"
    },
    {
      "name": "竹梢高空",
      "prompt": "大远景，高角度俯拍，翠绿竹林的顶部竹梢在风中轻轻摇曳，远处是云雾缭绕的山峦剪影，天空呈现淡蓝到金黄的渐变。体积光穿透云层，2.35:1 宽银幕，3D 国漫 CG 写意武侠质感。画面中不出现任何人物、文字、字幕、水印、LOGO。"
    }
  ]
}
> 说明：这个镜头里角色**真的**从竹林地面跃到了竹梢高空——两个物理地点不同，所以 2 条。

【反面示例 —— 不要把特效/道具/光效当场景】
❌ 错误：
{
  "shotSequence": 3,
  "scenes": [
    { "name": "烙印红光闪耀", "prompt": "大特写，平视固定机位，经文环形烙印图案剧烈向外扩张..." }
  ]
}
→ 这不是场景图，是动作细节/特效细节。这个镜头真正的场景应该是"角色所在的物理地点"，比如"大雷音寺佛堂"。烙印闪耀这种特效由后续视频生成阶段在那个地点内表现。

✅ 正确改写：
{
  "shotSequence": 3,
  "characters": ["如来佛祖", "孙悟空"],
  "scenes": [
    { "name": "大雷音寺佛堂", "prompt": "中景，平视固定机位，宏大的大雷音寺佛堂内部，金色莲花宝座居中，四周半空悬浮暗金色经文环，梁柱雕刻满饰佛纹。暗金与暗红色调，3D 国漫顶级渲染，电影级历史正剧质感。画面中不出现任何人物、文字、字幕、水印、LOGO。" }
  ]
}

【关键语言规则】使用与输入相同的语言输出。中文输入 → 中文输出。英文输入 → 英文输出。
```

#### REF_IMAGE_PROMPTS_FORMAT

```text
仅输出有效 JSON 数组（不要 markdown，不要代码块，不要前言）：

[
  {
    "shotSequence": 1,
    "characters": ["角色名1", "角色名2"],
    "scenes": [
      { "name": "场景名1", "prompt": "场景描述1" },
      { "name": "场景名2", "prompt": "场景描述2" }
    ]
  }
]

**字段硬性要求**：
- `characters`：这个镜头里会登场（有动作或对白）的角色名，必须和输入角色列表完全一致。空数组合法。
- `scenes`：每个元素必须同时有 `name`（4-10 字中文场景名）和 `prompt`（完整 Seedance 散文描述）。
- 禁止使用 legacy 的 `prompts: [string]` 数组格式。
- scenes 数组按时间顺序，第 0 个是起始空间。
```

### R2.file `script-generate.ts` FULL (`src/lib/ai/prompts/script-generate.ts`)

```text
/**
 * User-side prompt builder for script generation.
 * The authoritative SYSTEM prompt lives in the prompt registry under the
 * `script_generate` key (see src/lib/ai/prompts/registry.ts). This file
 * only builds the per-request user message so the two are not duplicated.
 */

function detectLanguage(text: string): string {
  if (/[\u4e00-\u9fff]/.test(text)) return "Chinese (中文)";
  if (/[\u3040-\u309f\u30a0-\u30ff]/.test(text)) return "Japanese (日本語)";
  if (/[\uac00-\ud7af]/.test(text)) return "Korean (한국어)";
  return "English";
}

export function buildScriptGeneratePrompt(idea: string): string {
  const lang = detectLanguage(idea);

  return `Write a complete, production-ready screenplay based on this creative concept:

"${idea}"

OUTPUT LANGUAGE: ${lang}. You MUST write EVERY word of your output in ${lang}, including all section headers, character descriptions, stage directions, and dialogue. Do NOT use English if the language is not English.

**STRICT FORMAT REMINDER** (details are in the system prompt — do not violate):
- Sections 1 (视觉风格) and 2 (角色描述) are machine-readable key:value blocks with fixed Chinese field labels. No markdown, no bullets, no code fences. One field per line.
- Section 3 (场景) is free-form screenplay prose.
- Field labels stay in Chinese verbatim regardless of the output language of the rest of the screenplay.

Content quality:
- Respect user-specified art style if given; otherwise infer the most fitting style from the concept.
- CHARACTERS section must cover every named character with all 5 required fields — downstream AI image generators rely on these to produce consistent visuals.
- Each scene description must be vivid enough for an AI image generator to produce a frame directly.
- Write RICHLY and in DETAIL — every scene needs specific visual descriptions, character actions, emotional beats, and dialogue. Avoid rushing through the story.`;
}

```

### R2.file `script-parse.ts` FULL (`src/lib/ai/prompts/script-parse.ts`)

```text
export const SCRIPT_PARSE_SYSTEM = `You are a senior script supervisor and story editor specializing in adapting written narratives into structured screenplays for animated short films.

Your task: analyze a user's raw story, prose, or unstructured script and restructure it into a precisely formatted screenplay JSON optimized for downstream AI animation pipeline (image generation → video generation).

Output a single JSON object:
{
  "title": "Compelling, evocative title",
  "synopsis": "A 1-2 sentence logline capturing the core conflict and stakes",
  "scenes": [
    {
      "sceneNumber": 1,
      "setting": "Specific location + time (e.g., 'Dimly lit basement workshop — late night')",
      "description": "Detailed visual description: character positions, actions, key props, lighting quality (warm/cold/dramatic), atmosphere, color palette. Written as a shot direction an animator can follow.",
      "mood": "Precise emotional tone (e.g., 'tense anticipation with underlying warmth')",
      "dialogues": [
        {
          "character": "CHARACTER_NAME (must match exact name used elsewhere)",
          "text": "Natural dialogue line",
          "emotion": "Specific delivery direction (e.g., 'whispering urgently, eyes darting')"
        }
      ]
    }
  ]
}

Story editing principles:
- Preserve the author's original intent, tone, and voice
- Identify and strengthen the narrative arc: INCITING INCIDENT → RISING ACTION → CLIMAX → DENOUEMENT
- Each scene = one continuous 5–15 second animated shot; split long passages into multiple scenes
- Scene descriptions must be visually concrete: specify spatial relationships, character postures, lighting direction, dominant colors
- Dialogue emotions should describe physical expression, not just named feelings
- Maintain strict character name consistency across all scenes
- If the source is vague, infer reasonable visual details that serve the story

CRITICAL LANGUAGE RULE: All text content in the JSON (title, synopsis, setting, description, mood, dialogue text, emotion) MUST be in the SAME LANGUAGE as the source text. If the source is in Chinese, all output text must be in Chinese. Do NOT translate to English.

Respond ONLY with valid JSON. No markdown fences. No commentary.`;

export function buildScriptParsePrompt(script: string): string {
  return `Analyze and structure the following story into a production-ready screenplay. Identify the narrative beats, define clear scenes with rich visual descriptions, and extract all dialogue with precise delivery directions.

--- SOURCE TEXT ---
${script}
--- END ---

IMPORTANT: Your output language MUST match the language of the source text above. If it is in Chinese, write ALL JSON text fields in Chinese. Do NOT translate to English.`;
}

```

### R2.file `script-split.ts` FULL (`src/lib/ai/prompts/script-split.ts`)

```text
export const SCRIPT_SPLIT_SYSTEM = `You are an award-winning screenwriter specializing in episodic animated content. Your task is to take source material (which may be a novel, article, report, story, or any text) and adapt it into episodic screenplay format, split by target duration.

RULES:
1. Each episode MUST be a self-contained narrative unit with a clear beginning, rising action, and cliffhanger or resolution.
2. Split at natural story boundaries — scene changes, time jumps, perspective shifts, or dramatic turning points.
3. Generate a concise title, a 1-2 sentence description, and 3-5 comma-separated keywords for each episode.
4. If the source material is non-narrative (e.g. a report, manual, article), creatively adapt it into a story — use characters, dramatization, and visual metaphors to make the content engaging.
5. The "idea" field will be fed into a SEPARATE AI screenplay generator as its ONLY input. It MUST be extremely detailed:
   - Start with a list of characters appearing in this episode and their roles
   - COPY verbatim the most important paragraphs, dialogues, and descriptions from the source text that belong to this episode — do NOT summarize them, PRESERVE the original wording
   - Add structural notes: scene transitions, emotional beats, visual highlights
   - The downstream AI will have NO access to the source material — everything it needs must be in this field
   - Minimum 1000 words per episode. Longer is better. Include direct quotes from the source.

CRITICAL LANGUAGE RULE: ALL output fields (title, description, keywords, script) MUST be in the SAME LANGUAGE as the source material. Chinese input → Chinese output. English input → English output.

OUTPUT FORMAT — JSON array only, no markdown fences, no commentary:
[
  {
    "title": "Episode title",
    "description": "Brief plot summary for this episode",
    "keywords": "keyword1, keyword2, keyword3",
    "idea": "1) List all characters in this episode with roles. 2) COPY the key paragraphs and dialogues from the source text verbatim — preserve original wording, do not summarize. 3) Add scene transition notes and emotional beat markers. Minimum 1000 words. The downstream screenplay generator has NO access to the source — this field is its only reference.",
    "characters": ["character name 1", "character name 2"]
  }
]

═══ EPISODE CHARACTERS ═══
You will be given a full list of extracted characters. For each episode, list ALL character names (both main and supporting) who actually appear in that specific episode. Use exact names as provided. Do NOT include every character in every episode — only those who genuinely appear, speak, or are directly involved in that episode's plot.`;

export function buildScriptSplitPrompt(
  scriptChunk: string,
  context: {
    chunkIndex: number;
    totalChunks: number;
    episodeOffset: number;
  }
): string {
  const positionHint =
    context.totalChunks === 1
      ? ""
      : `\nThis is chunk ${context.chunkIndex + 1} of ${context.totalChunks}. Episodes in this chunk should be numbered starting from ${context.episodeOffset + 1}.`;

  return `Split the following text into episodes. Each episode should be a natural narrative unit — use your judgment to find the best split points based on story structure, scene changes, and dramatic beats.${positionHint}

--- TEXT ---
${scriptChunk}
--- END ---

Return ONLY the JSON array. No markdown. No commentary.`;
}

```

### R2.file `character-extract.ts` FULL (`src/lib/ai/prompts/character-extract.ts`)

```text
export const CHARACTER_EXTRACT_SYSTEM = `You are a senior character designer, cinematographer, and art director. Your character descriptions are the single authoritative visual reference fed directly into a photorealistic AI image generator. Every word you write determines what the character looks like — be surgical, specific, and evocative.

Your task: extract every named character from the screenplay and produce a professional visual specification at the level of a real film production bible.

═══ STEP 1 — DETECT VISUAL STYLE ═══
Identify the style declared or implied by the screenplay:
- "真人" / "realistic" / "live-action" / "photorealistic" → describe as if writing for a real-world photo shoot or high-end CG film. NO anime aesthetics whatsoever.
- "动漫" / "anime" / "manga" → describe with anime proportions, stylized features, vivid palette.
- "3D CG" / "Pixar" → describe for 3D rendering pipeline.
- "2D cartoon" → describe for cartoon illustration.
This style MUST appear in every description. A 真人 screenplay must NEVER produce anime-sounding output.

═══ OUTPUT FORMAT ═══
JSON array only — no markdown fences, no commentary:
[
  {
    "name": "Character name exactly as written in screenplay",
    "scope": "main" or "guest",
    "description": "Full visual specification — single paragraph, all requirements below",
    "visualHint": "2–4 word visual identifier for dialogue labels (e.g. 银发金瞳, red coat auburn hair). Must be instantly recognizable at a glance — focus on the most distinctive physical trait(s).",
    "personality": "2–3 defining traits that shape posture, expression, and movement"
  }
]

═══ SCOPE RULES ═══
- "main": core characters who drive the story, appear in multiple scenes, or are central to the plot — protagonists, deuteragonists, key antagonists
- "guest": minor / supporting characters who appear briefly — bystanders, one-scene extras, named but non-essential roles
When in doubt, prefer "main". A character with meaningful dialogue or plot impact is "main".

═══ DESCRIPTION REQUIREMENTS ═══
Write one dense, precise paragraph covering ALL of the following. The description will be passed verbatim to an image generator — write it as a professional cinematographer briefing a photographer:

0. STYLE TAG: Open with the art style (e.g., "Photorealistic live-action, shot on 85mm lens —" or "Anime style —"). This anchors the downstream renderer.

1. PHYSIQUE & BEARING: gender, apparent age, exact height feel (statuesque / petite / average), body type (lean-athletic / willowy / muscular / stocky), natural posture and how they carry themselves.

2. FACE — WRITE THIS AS A CLOSE-UP LENS DESCRIPTION:
   - Bone structure: face shape, cheekbone prominence, jawline definition (sharp / soft / angular), brow ridge
   - Eyes: shape (almond / round / hooded / monolid), size, iris color with specificity (e.g., "storm-grey", "amber-flecked hazel", "deep obsidian"), visible limbal ring, lash density
   - Nose: bridge height, tip shape (refined / bulbous / upturned), nostril width
   - Lips: fullness, cupid's bow definition, natural resting expression
   - Skin: tone with precise descriptor (e.g., "porcelain cool-white", "warm honey-gold", "deep ebony with blue undertone"), texture quality (luminous / matte / weathered), any marks
   - Overall: rate and describe their attractiveness tier — are they model-beautiful, ruggedly handsome, girl-next-door charming? Be direct.

3. HAIR: exact color (shade + undertone, e.g., "blue-black with deep indigo highlights"), length relative to body, texture (pin-straight / loose waves / tight coils), style (how it sits, falls, moves), any accessories in hair.

4. OUTFIT — PRIMARY COSTUME (full wardrobe breakdown):
   - Top: garment type, cut, material (e.g., "fitted slate-grey wool mandarin-collar jacket"), color
   - Bottom: trousers / skirt / robe type, material, color
   - Footwear: style, material, heel height if relevant
   - Outerwear / armor: describe layer by layer if applicable
   - Accessories: jewelry (describe metal, stone, style), belt, bag, gloves, hat — be specific

5. WEAPONS & EQUIPMENT (if applicable):
   - Melee weapons: blade length, edge geometry, cross-guard style, hilt wrapping material, finish (blued / polished / engraved), how it is carried (sheathed at hip / strapped to back)
   - Ranged weapons: bow / gun type, finish, any custom modifications, quiver or holster detail
   - Armor: material (plate / chain / leather), surface treatment (burnished / matte / battle-worn), any insignia or engravings
   - Other gear: describe function and appearance

6. DISTINGUISHING FEATURES: scars (location, shape, age), tattoos (design, placement), glasses (frame style, lens tint), cybernetics, non-human traits (ears, wings, horns, tail) — describe the exact visual appearance.

7. CHARACTER COLOR PALETTE: list 3–5 dominant colors that define this character's visual identity (e.g., "crimson, brushed gold, charcoal black").

═══ WRITING RULES ═══
- ONE CONTINUOUS PARAGRAPH — no bullet points, no line breaks inside the description field
- Be specific enough that two different AI image generators produce recognizably the same character
- Use precise color names: not "red" but "blood crimson" or "dusty rose"
- Beauty matters — if the screenplay implies an attractive character, write them as genuinely, strikingly beautiful. Use the vocabulary of high-fashion photography and film casting.
- For non-human characters, apply the same level of anatomical specificity to their unique features

CRITICAL LANGUAGE RULE: ALL fields MUST be written in the SAME LANGUAGE as the screenplay. Chinese screenplay → Chinese output. English screenplay → English output. Character names must match the screenplay exactly.

Respond ONLY with the JSON array. No markdown. No commentary.`;

export function buildCharacterExtractPrompt(screenplay: string): string {
  return `Extract and create detailed visual character specifications for EVERY named character in this screenplay. Each description must be specific enough to serve as a binding art reference for consistent AI image generation.

--- SCREENPLAY ---
${screenplay}
--- END ---

IMPORTANT: Your output language MUST match the language of the screenplay above. If it is in Chinese, write ALL fields (name, description, personality) in Chinese.`;
}

```

### R2.file `import-character-extract.ts` FULL (`src/lib/ai/prompts/import-character-extract.ts`)

```text
export const IMPORT_CHARACTER_EXTRACT_SYSTEM = `You are a senior character designer, cinematographer, and art director. Your task is to extract ALL named characters from the given text, estimate appearance frequency, and produce a professional visual specification for each character at the level of a real film production bible.

RULES:
1. Extract EVERY character who is named in the text
2. Count approximate appearances/mentions for each character
3. Characters mentioned 2+ times are likely main characters
4. Merge obvious aliases (e.g. "小明" and "明哥" referring to the same person)

═══ STEP 1 — DETECT VISUAL STYLE ═══
Identify the style declared or implied by the text:
- "真人" / "realistic" / "live-action" / historical → describe as photorealistic cinematic. NO anime aesthetics.
- "动漫" / "anime" / "manga" → describe with anime proportions, stylized features.
- "3D CG" / "Pixar" → describe for 3D rendering.
- If no style is specified, infer from content (historical text → photorealistic historical drama).

═══ DESCRIPTION REQUIREMENTS ═══
The "description" field must be ONE dense paragraph covering ALL of the following, written as a professional cinematographer briefing a photographer:

0. STYLE TAG: Open with art style (e.g. "电影级写实历史正剧风格，无滤镜，85mm镜头特写——")
1. 【体态】: gender, apparent age, height/build, posture, how they carry themselves
2. 【面部】: face shape, jawline, brow ridge, eye shape/color, nose, lips, skin tone with precise descriptor, skin texture, attractiveness
3. 【发型】: exact color, length, style, any head accessories
4. 【服装】: full wardrobe breakdown — top, bottom, footwear, outerwear, accessories with materials and colors
5. 【武器/装备】(if applicable): detailed description of weapons, armor, gear
6. 【色彩调色板】: 3-5 dominant colors defining this character's visual identity

═══ VISUAL HINT ═══
The "visualHint" field must be 2-4 word PHYSICAL APPEARANCE tags for instant visual identification (e.g. "龙袍金冠阴沉脸", "大红直身佩刀", "silver hair red coat"). Must describe APPEARANCE, not actions.

CRITICAL LANGUAGE RULE: ALL output fields MUST be in the SAME LANGUAGE as the source text.

OUTPUT FORMAT — JSON array only, no markdown fences, no commentary:
[
  {
    "name": "Character name as it appears in text",
    "frequency": 5,
    "description": "Full visual specification — one dense paragraph following ALL requirements above",
    "visualHint": "2-4 word physical appearance identifier"
  }
]

Respond ONLY with the JSON array. No markdown. No commentary.`;

export function buildImportCharacterExtractPrompt(textChunk: string): string {
  return `Extract all named characters from the following text. For each character, produce a detailed visual specification suitable for AI image generation. Count their approximate appearances. If the text doesn't describe a character's appearance explicitly, INFER it from their role, era, and context (e.g. a Ming Dynasty emperor wears 龙袍, a soldier wears 铠甲).

--- TEXT ---
${textChunk}
--- END ---

Return ONLY the JSON array.`;
}

```

### R2.file `character-image.ts` FULL (`src/lib/ai/prompts/character-image.ts`)

```text
export function buildCharacterTurnaroundPrompt(description: string, characterName?: string): string {
  return `Character four-view reference sheet — professional character design document.

=== CRITICAL: ART STYLE FIDELITY ===
The CHARACTER DESCRIPTION below is authoritative. It may specify an art style explicitly, implicitly, or through a combination of modifiers (e.g. "3D 国漫 CG 渲染", "水墨写意", "赛博朋克像素画", "cel-shaded anime", "oil painting portrait", "PBR realtime render").

Rules for interpreting style:
1. Treat the FULL style phrase as one atomic instruction. Do NOT cherry-pick individual words and map them to a default bucket. "3D 写实国漫渲染" is NOT the same as "photorealistic" — it is a stylized 3D CG render in the Chinese animation idiom.
2. Style modifiers like "写实 / realistic / 高清 / 精致" describe RENDERING FIDELITY, not medium. They raise detail level within the chosen medium; they never convert the medium to live-action photography.
3. The medium (2D illustration / 3D CG / photograph / painting / pixel / etc.) is determined ONLY by explicit medium words such as "照片 / photograph / live-action / 真人实拍 / 摄影". In the ABSENCE of such explicit photographic words, DO NOT output a photograph or live-action render, even if "写实" or "realistic" appears.
4. When multiple style words are present, the most specific / most restrictive one wins. "国漫" + "3D" + "写实" → stylized 3D CG in Chinese animation style with high rendering fidelity.
5. Color palette, lighting mood, and era references in the description (e.g. "低饱和度暗沉色调", "电影级历史正剧质感") are MANDATORY and must be honored exactly — they are not decorative.
6. If no style is mentioned at all, infer the most appropriate stylized illustration from the character's setting and genre. Default to stylized illustration, NOT photography.

=== CHARACTER DESCRIPTION (authoritative) ===
${characterName ? `Name: ${characterName}\n` : ''}${description}

=== FACE — HIGH DETAIL ===
Render the face with precision appropriate to the chosen medium and style:
- Consistent facial bone structure, eye shape, nose, mouth — matching the description exactly
- Eyes expressive and detailed, rendered in the chosen medium's idiom
- Hair with defined volume, color and flow, rendered in the chosen medium's idiom
- Skin and surface shading rendered in the chosen medium's idiom (cel-shading, subsurface, PBR, painterly, etc.)
- The face must be striking, memorable, and instantly recognizable across all four views

=== WEAPONS, COSTUME & EQUIPMENT ===
- All props, armor, clothing and equipment must be rendered in the SAME medium and style as the character
- Material detail must match the style (painterly strokes for paintings, PBR materials for 3D CG, clean flats for anime, etc.)
- Scale and anatomy must be correct relative to the body

=== FOUR-VIEW LAYOUT ===
Four views arranged LEFT to RIGHT on a clean pure white canvas, consistent medium shot (waist to crown) across all four:
1. FRONT — facing viewer directly, showing full outfit and any held items
2. THREE-QUARTER — rotated ~45° right, showing face depth and dimensional form
3. SIDE PROFILE — perfect 90° facing right, clear silhouette
4. BACK — fully facing away, hairstyle and clothing back detail

=== LIGHTING & RENDERING ===
- Clean professional key/fill/rim lighting, consistent direction across all four views
- Pure white background for clean character separation
- Honor any mood/tone/palette constraints from the description (if it says "低饱和度暗沉", the output MUST be low-saturation and muted, NOT bright)
- Highest quality achievable WITHIN the chosen medium and style — never break medium to chase fidelity

=== CONSISTENCY ACROSS ALL FOUR VIEWS ===
- Identical character identity, proportions and colors in every view
- Identical outfit, accessories, weapon placement, hair
- Heads aligned at the same top edge, waist at the same bottom edge
- Consistent expression across all views

=== CHARACTER NAME LABEL ===
${characterName ? `Display the character's name "${characterName}" as a clean typographic label below the four-view layout. Use a modern sans-serif font, dark text on white background, centered alignment.` : 'No character name label required.'}

=== FINAL OUTPUT STANDARD ===
Professional character design reference sheet. This is the single canonical reference — all future generated frames MUST reproduce this exact character in this exact medium and style. Zero medium drift, zero style drift, zero AI artifacts.`;
}

```

### R2.file `keyframe-prompts.ts` FULL (`src/lib/ai/prompts/keyframe-prompts.ts`)

```text
/**
 * User-side prompt builder for the keyframe (first/last frame) image-prompt
 * generation step. Mirrors `buildRefImagePromptsRequest` for the reference
 * mode pipeline. The system prompt lives in the registry under the
 * `shot_split_keyframe_assets` key.
 */

export function buildKeyframePromptsRequest(
  shots: Array<{
    sequence: number;
    prompt: string;
    motionScript?: string | null;
    cameraDirection?: string | null;
  }>,
  characters: Array<{
    name: string;
    description?: string | null;
    visualHint?: string | null;
  }>,
  visualStyle?: string
): string {
  const charDescriptions = characters
    .map(
      (c) =>
        `${c.name}（${c.visualHint || "无视觉标识"}）: ${c.description || ""}`
    )
    .join("\n");

  const shotDescriptions = shots
    .map(
      (s) =>
        `镜头 ${s.sequence}: ${s.prompt}${
          s.motionScript ? `\n动作: ${s.motionScript}` : ""
        }${s.cameraDirection ? `\n镜头运动: ${s.cameraDirection}` : ""}`
    )
    .join("\n\n");

  return `${visualStyle ? `视觉风格: ${visualStyle}\n\n` : ""}角色:\n${charDescriptions}\n\n分镜:\n${shotDescriptions}`;
}

```

### R2.file `frame-generate.ts` FULL (`src/lib/ai/prompts/frame-generate.ts`)

```text
import { getPromptDefinition } from "./registry";

export function buildFirstFramePrompt(params: {
  sceneDescription: string;
  startFrameDesc: string;
  characterDescriptions: string;
  previousLastFrame?: string;
  slotContents?: Record<string, string>;
}): string {
  const def = getPromptDefinition("frame_generate_first");
  if (def) {
    return def.buildFullPrompt(params.slotContents ?? {}, {
      sceneDescription: params.sceneDescription,
      startFrameDesc: params.startFrameDesc,
      characterDescriptions: params.characterDescriptions,
      previousLastFrame: params.previousLastFrame,
    });
  }

  // Fallback: hardcoded prompt (should not be reached if registry is intact)
  const lines: string[] = [];

  lines.push(`生成该镜头的开场帧，作为一张高质量图像。`);
  lines.push(``);
  lines.push(`=== 关键：画风（最高优先级）===`);
  lines.push(`阅读下方的角色描述和场景描述，它们指定或暗示了一种画风。`);
  lines.push(`你必须完全匹配该画风。不得默认使用写实风格。`);
  lines.push(`- 如果描述中提到 动漫/漫画/anime/manga/卡通/cartoon → 生成动漫/漫画风格插画`);
  lines.push(`- 如果描述中提到 写实/真人/photorealistic → 生成写实风格图像`);
  lines.push(`- 如果附有参考图，其视觉风格即为标准——必须精确匹配`);
  lines.push(`- 输出的画风必须与角色参考图保持一致`);
  lines.push(``);
  lines.push(`=== 场景环境 ===`);
  lines.push(params.sceneDescription);
  lines.push(``);
  lines.push(`=== 画面描述 ===`);
  lines.push(params.startFrameDesc);
  lines.push(``);
  lines.push(`=== 角色描述 ===`);
  lines.push(params.characterDescriptions);
  lines.push(``);
  lines.push(`=== 参考图（角色设定图）===`);
  lines.push(`每张附带的参考图是一张角色设定图，展示 4 个视角（正面、四分之三侧面、侧面、背面）。`);
  lines.push(`角色名印在每张设定图底部——用它来识别对应的角色。`);
  lines.push(`强制一致性规则：`);
  lines.push(`- 将设定图中的角色名与场景描述中的角色名匹配`);
  lines.push(`- 服装必须与参考完全一致——相同的衣物类型、颜色、材质、配饰。不得替换（例如：不得将青色常服替换为龙袍）`);
  lines.push(`- 面部、发型、发色、体型、肤色必须精确匹配`);
  lines.push(`- 参考图中展示的所有配饰（帽子、佩刀、发簪、首饰）都必须出现`);
  lines.push(`- 画风必须与参考图精确匹配`);
  lines.push(``);

  if (params.previousLastFrame) {
    lines.push(`=== 连续性要求 ===`);
    lines.push(`该镜头紧接上一个镜头。附带的参考包含上一个镜头的末帧。保持视觉连续性：`);
    lines.push(`- 相同角色必须穿着一致的服装并保持一致的比例`);
    lines.push(`- 相同画风——不得在动漫和写实之间切换`);
    lines.push(`- 环境光照和色温应平滑过渡`);
    lines.push(`- 角色位置应从上一个镜头结束时的位置自然延续`);
    lines.push(``);
  }

  lines.push(`=== 渲染 ===`);
  lines.push(`质感：与画风相称的丰富细节`);
  lines.push(`光照：电影级打光，具有合理的光源。使用轮廓光分离角色。`);
  lines.push(`背景：完整渲染、细节丰富的环境。不得使用空白或抽象背景。`);
  lines.push(`角色：外观和画风精确匹配参考图。表情生动，姿势自然动感。`);
  lines.push(`构图：电影式取景，具有清晰的焦点和景深。`);

  return lines.join("\n");
}

export function buildLastFramePrompt(params: {
  sceneDescription: string;
  endFrameDesc: string;
  characterDescriptions: string;
  firstFramePath: string;
  slotContents?: Record<string, string>;
}): string {
  const def = getPromptDefinition("frame_generate_last");
  if (def) {
    return def.buildFullPrompt(params.slotContents ?? {}, {
      sceneDescription: params.sceneDescription,
      endFrameDesc: params.endFrameDesc,
      characterDescriptions: params.characterDescriptions,
    });
  }

  // Fallback: hardcoded prompt (should not be reached if registry is intact)
  const lines: string[] = [];

  lines.push(`生成该镜头的结束帧，作为一张高质量图像。`);
  lines.push(``);
  lines.push(`=== 关键：画风（最高优先级）===`);
  lines.push(`你必须精确匹配首帧图像（已附带）的画风。`);
  lines.push(`如果首帧是动漫/漫画风格 → 此帧也必须是动漫/漫画风格。`);
  lines.push(`如果首帧是写实风格 → 此帧也必须是写实风格。`);
  lines.push(`不得更改或混用画风。这是不可妥协的。`);
  lines.push(``);
  lines.push(`=== 场景环境 ===`);
  lines.push(params.sceneDescription);
  lines.push(``);
  lines.push(`=== 画面描述 ===`);
  lines.push(params.endFrameDesc);
  lines.push(``);
  lines.push(`=== 角色描述 ===`);
  lines.push(params.characterDescriptions);
  lines.push(``);
  lines.push(`=== 参考图 ===`);
  lines.push(`第一张附带图像是该镜头的开场帧——以它作为你的视觉锚点。`);
  lines.push(`其余附带图像是角色设定图（每张 4 个视角，名字印在底部）。`);
  lines.push(`将每张角色设定图的名字与场景中的角色匹配。`);
  lines.push(``);
  lines.push(`=== 与首帧的关系 ===`);
  lines.push(`此结束帧展示镜头动作完成后的终止状态。与首帧相比：`);
  lines.push(`- 相同的环境、光照设置和色彩方案`);
  lines.push(`- 相同画风——绝对不得更改风格`);
  lines.push(`- 服装完全一致——角色穿着与参考设定图和首帧中完全相同的服装。不得更换服装。`);
  lines.push(`- 相同的面部、发型、配饰——仅姿势/表情/位置发生变化`);
  lines.push(`- 角色的位置、姿势和表情已按上方画面描述发生变化`);
  lines.push(``);
  lines.push(`=== 作为下一镜头的起始点 ===`);
  lines.push(`此帧将被复用为下一个镜头的开场帧。确保：`);
  lines.push(`- 姿势是稳定的——非运动中间态或模糊的`);
  lines.push(`- 构图是完整的，可作为独立画面成立`);
  lines.push(`- 取景允许自然过渡到不同的机位角度`);
  lines.push(``);
  lines.push(`=== 渲染 ===`);
  lines.push(`质感：与首帧风格匹配的丰富细节`);
  lines.push(`光照：与首帧相同的光照设置。仅在动作需要时才变化。`);
  lines.push(`背景：必须与首帧的环境一致。`);
  lines.push(`角色：精确匹配参考图。展示镜头动作结束时的情绪状态。`);
  lines.push(`构图：镜头的自然收束，为切换到下一个镜头做好准备。`);

  return lines.join("\n");
}

```

### R2.file `scene-frame-generate.ts` FULL (`src/lib/ai/prompts/scene-frame-generate.ts`)

```text
import { getPromptDefinition } from "./registry";

export function buildSceneFramePrompt(params: {
  sceneDescription: string;
  charRefMapping: string;
  characterDescriptions: string;
  cameraDirection?: string | null;
  startFrameDesc?: string | null;
  motionScript?: string | null;
  /** Pre-resolved slot contents from the resolver (if available) */
  slotContents?: Record<string, string>;
}): string {
  const def = getPromptDefinition("scene_frame_generate");
  if (!def) {
    throw new Error("scene_frame_generate prompt definition not found in registry");
  }

  return def.buildFullPrompt(params.slotContents ?? {}, {
    sceneDescription: params.sceneDescription,
    charRefMapping: params.charRefMapping,
    characterDescriptions: params.characterDescriptions,
    cameraDirection: params.cameraDirection ?? "",
    startFrameDesc: params.startFrameDesc ?? "",
    motionScript: params.motionScript ?? "",
  });
}

```

### R2.file `video-generate.ts` FULL (`src/lib/ai/prompts/video-generate.ts`)

```text
import { getPromptDefinition } from "./registry";

type CharacterRef = { name: string; visualHint?: string | null };

function detectLanguage(text: string): "zh" | "en" {
  const chineseChars = text.match(/[\u4e00-\u9fff]/g);
  return chineseChars && chineseChars.length > text.length * 0.1 ? "zh" : "en";
}

function getLabels(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        characterAppearance: "角色形象",
        dialogueLipSync: "对白口型",
        offscreenVoice: "画外音",
        camera: "镜头运动",
        duration: "时长",
        interpolation: "关键帧插值",
        openingFrame: "起始帧",
        closingFrame: "结束帧",
        videoScript: "视频脚本",
        frameAnchors: "帧锚点",
        separator: "，",
        period: "。",
        colon: "：",
        paren: { open: "（", close: "）" },
      }
    : {
        characterAppearance: "Character Appearance",
        dialogueLipSync: "Dialogue Lip Sync",
        offscreenVoice: "Off-screen Voice",
        camera: "Camera Movement",
        duration: "Duration",
        interpolation: "Keyframe Interpolation",
        openingFrame: "Opening Frame",
        closingFrame: "Closing Frame",
        videoScript: "Video Script",
        frameAnchors: "Frame Anchors",
        separator: ", ",
        period: ".",
        colon: ": ",
        paren: { open: "(", close: ")" },
      };
}

function buildCharacterLine(characters?: CharacterRef[], lang: "zh" | "en" = "zh"): string | null {
  const withHints = (characters ?? []).filter((c) => c.visualHint);
  if (!withHints.length) return null;
  const L = getLabels(lang);
  return withHints.map((c) => `${c.name}${L.paren.open}${c.visualHint}${L.paren.close}`).join(L.separator);
}

/**
 * Resolve a single slot value: use slotContents override, then registry default, then hardcoded fallback.
 */
function resolveSlot(
  slotContents: Record<string, string> | undefined,
  promptKey: string,
  slotKey: string,
  hardcodedFallback: string
): string {
  if (slotContents && slotKey in slotContents) return slotContents[slotKey];
  const def = getPromptDefinition(promptKey);
  if (def) {
    const s = def.slots.find((sl) => sl.key === slotKey);
    if (s) return s.defaultContent;
  }
  return hardcodedFallback;
}

/**
 * Prompt for reference-image-based video generation (Toonflow/Kling reference mode).
 * Seedance-style format: Shot description (prose) → Camera → 【对白口型】.
 * No frame interpolation header, no [FRAME ANCHORS] — the reference image provides visual context.
 */
export function buildReferenceVideoPrompt(params: {
  videoScript: string;
  cameraDirection: string;
  duration?: number;
  characters?: CharacterRef[];
  dialogues?: Array<{ characterName: string; text: string; offscreen?: boolean; visualHint?: string }>;
  slotContents?: Record<string, string>;
}): string {
  const lang = detectLanguage(params.videoScript);
  const L = getLabels(lang);
  const lines: string[] = [];

  if (params.duration) {
    lines.push(`${L.duration}${L.colon}${params.duration}s${L.period}`);
    lines.push(``);
  }

  const charLine = buildCharacterLine(params.characters, lang);
  if (charLine) {
    lines.push(`${L.characterAppearance}${L.colon}${charLine}${L.period}`);
    lines.push(``);
  }

  lines.push(params.videoScript);

  lines.push(``);
  lines.push(`${L.camera}${L.colon}${params.cameraDirection}${L.period}`);

  if (params.dialogues?.length) {
    // Resolve dialogue format slot to extract labels
    const dialogueFormatText = resolveSlot(
      params.slotContents,
      "ref_video_generate",
      "dialogue_format",
      ""
    );

    // Extract labels from the slot content, or use lang-aware defaults
    const defaultOnScreen = lang === "zh" ? "【对白口型】" : "[Dialogue Lip Sync]";
    const defaultOffScreen = lang === "zh" ? "【画外音】" : "[Off-screen Voice]";
    const onScreenLabel = extractLabel(dialogueFormatText, "画内对白", defaultOnScreen);
    const offScreenLabel = extractLabel(dialogueFormatText, "画外旁白", defaultOffScreen);

    lines.push(``);
    for (const d of params.dialogues) {
      if (d.offscreen) {
        lines.push(`${offScreenLabel}${d.characterName}: "${d.text}"`);
      } else {
        const label = d.visualHint ? `${d.characterName}${L.paren.open}${d.visualHint}${L.paren.close}` : d.characterName;
        lines.push(`${onScreenLabel}${label}: "${d.text}"`);
      }
    }
  }

  return lines.join("\n");
}

export function buildVideoPrompt(params: {
  videoScript: string;
  cameraDirection: string;
  startFrameDesc?: string;
  endFrameDesc?: string;
  sceneDescription?: string;       // kept for call-site compatibility, not used in output
  duration?: number;
  characters?: CharacterRef[];
  dialogues?: Array<{ characterName: string; text: string; offscreen?: boolean; visualHint?: string }>;
  slotContents?: Record<string, string>;
}): string {
  const lang = detectLanguage(params.videoScript);
  const L = getLabels(lang);
  const lines: string[] = [];

  if (params.duration) {
    lines.push(`${L.duration}${L.colon}${params.duration}s${L.period}`);
    lines.push(``);
  }

  const charLine = buildCharacterLine(params.characters, lang);
  if (charLine) {
    lines.push(`${L.characterAppearance}${L.colon}${charLine}${L.period}`);
    lines.push(``);
  }

  // Interpolation header from slot or registry default
  const defaultInterpolation = lang === "zh"
    ? "从起始帧到结束帧进行平滑插值。"
    : "Smoothly interpolate from the opening frame to the closing frame.";
  const interpolationHeader = resolveSlot(
    params.slotContents,
    "video_generate",
    "interpolation_header",
    defaultInterpolation
  );
  lines.push(interpolationHeader);
  lines.push(``);

  lines.push(params.videoScript);

  lines.push(``);
  lines.push(`${L.camera}${L.colon}${params.cameraDirection}${L.period}`);

  const hasStart = !!params.startFrameDesc;
  const hasEnd = !!params.endFrameDesc;
  if (hasStart || hasEnd) {
    // Resolve frame_anchors slot for label text
    const frameAnchorsText = resolveSlot(
      params.slotContents,
      "video_generate",
      "frame_anchors",
      ""
    );

    // Extract anchor header and labels from slot content, or use lang-aware defaults
    const defaultAnchorHeader = lang === "zh" ? "[帧锚点]" : "[FRAME ANCHORS]";
    const defaultOpeningLabel = lang === "zh" ? "起始帧：" : "Opening frame:";
    const defaultClosingLabel = lang === "zh" ? "结束帧：" : "Closing frame:";
    const anchorHeader = extractAnchorHeader(frameAnchorsText, defaultAnchorHeader);
    const openingLabel = extractFrameLabel(frameAnchorsText, "首帧", defaultOpeningLabel);
    const closingLabel = extractFrameLabel(frameAnchorsText, "尾帧", defaultClosingLabel);

    lines.push(``);
    lines.push(anchorHeader);
    if (hasStart) lines.push(`${openingLabel} ${params.startFrameDesc}`);
    if (hasEnd) lines.push(`${closingLabel} ${params.endFrameDesc}`);
  }

  if (params.dialogues?.length) {
    // Resolve dialogue format slot to extract labels
    const dialogueFormatText = resolveSlot(
      params.slotContents,
      "video_generate",
      "dialogue_format",
      ""
    );

    const defaultOnScreen = lang === "zh" ? "【对白口型】" : "[Dialogue Lip Sync]";
    const defaultOffScreen = lang === "zh" ? "【画外音】" : "[Off-screen Voice]";
    const onScreenLabel = extractLabel(dialogueFormatText, "画内对白", defaultOnScreen);
    const offScreenLabel = extractLabel(dialogueFormatText, "画外旁白", defaultOffScreen);

    lines.push(``);
    for (const d of params.dialogues) {
      if (d.offscreen) {
        lines.push(`${offScreenLabel}${d.characterName}: "${d.text}"`);
      } else {
        const label = d.visualHint ? `${d.characterName}${L.paren.open}${d.visualHint}${L.paren.close}` : d.characterName;
        lines.push(`${onScreenLabel}${label}: "${d.text}"`);
      }
    }
  }

  return lines.join("\n");
}

// ── Helpers for extracting labels from slot content ──────

/**
 * Extract dialogue label (e.g. 【对白口型】or 【画外音】) from the slot format text.
 */
function extractLabel(
  slotText: string,
  _lineHint: string,
  fallback: string
): string {
  if (!slotText) return fallback;
  // Match patterns like 【对白口型】 or 【画外音】 from the slot content
  const lines = slotText.split("\n");
  for (const line of lines) {
    if (line.includes(_lineHint)) {
      const match = line.match(/(【[^】]+】)/);
      if (match) return match[1];
    }
  }
  return fallback;
}

/**
 * Extract the anchor section header (e.g. [FRAME ANCHORS] or [帧锚点]) from slot text.
 */
function extractAnchorHeader(slotText: string, fallback: string): string {
  if (!slotText) return fallback;
  const match = slotText.match(/^\[([^\]]+)\]/m);
  if (match) return `[${match[1]}]`;
  return fallback;
}

/**
 * Extract frame label (e.g. "Opening frame:" or "首帧：") from slot text.
 */
function extractFrameLabel(slotText: string, lineHint: string, fallback: string): string {
  if (!slotText) return fallback;
  const lines = slotText.split("\n");
  for (const line of lines) {
    if (line.includes(lineHint)) {
      // Extract label before the placeholder (e.g. "首帧：" from "首帧：{{START_FRAME_DESC}}")
      const match = line.match(/^([^{]+)/);
      if (match) return match[1].trim();
    }
  }
  return fallback;
}

```

### R2.file `presets.ts` FULL (`src/lib/ai/prompts/presets.ts`)

```text
export interface BuiltInPreset {
  id: string;
  name: string;
  nameKey: string;
  descriptionKey: string;
  promptKey: string;
  slots: Record<string, string>;
}

// Empty for now — preset content will be authored later
export const BUILT_IN_PRESETS: BuiltInPreset[] = [];

```

### R2.file `blocks.ts` FULL (`src/lib/ai/prompts/blocks.ts`)

```text
/**
 * Reusable prompt building blocks.
 * Extracted from duplicated text across multiple prompt templates.
 */

export function artStyleBlock(): string {
  return `## 画风一致性
- 在所有生成的图像中保持项目"视觉风格"部分定义的视觉风格
- 风格要素包括：渲染技法、色彩方案、光照氛围、质感品质
- 不得在同一项目中混用风格（例如：不得将写实角色放在卡通背景中）
- 如果声明了特定画风（动漫、写实、水彩等），所有帧都必须匹配`;
}

export function referenceImageBlock(): string {
  return `## 参考图使用规则
- 参考图定义了角色的标准外观
- 必须匹配：脸型、发型/发色、瞳色、肤色、服装细节、配饰
- 可调整：姿势、表情、角度——这些随镜头变化
- 绝不违背参考图中的核心身份特征`;
}

export function languageRuleBlock(defaultLang?: string): string {
  return `## 关键语言规则
输出必须与输入语言一致。如果用户使用中文书写，则全部以中文回复。如果使用英文，则全部以英文回复。不得在输出中混用语言。${
    defaultLang ? `\n语言不明确时的默认语言：${defaultLang}` : ""
  }`;
}

/**
 * Shared theme → art style mapping used by character_image, ref_image_prompts,
 * frame_generate_first, and scene_frame_generate. Single source of truth to
 * prevent style drift across the pipeline (角色图/参考图/首帧图).
 */
export function themeStyleMappingBlock(): string {
  return `**主题 → 画风自动映射表**（全流水线共用，确保角色图/参考图/首帧图画风一致）：
- 仙侠/修真/玄幻 → 3D 国漫渲染风格、中国仙侠概念设计，细腻材质与体积光
- 古风/历史 → 中国风工笔画 / 水墨 / 古典绘画，讲究线条与留白
- 赛博朋克/未来/科幻 → 未来科幻写实 CG、概念设计，硬表面与发光材质
- 现实/都市/人物 → 电影摄影写实风格、胶片质感，自然肤质
- 奇幻/西方魔法 → 西幻概念原画、油画质感
- 日系动漫 → 日漫赛璐珞 / 新海诚柔光 / 吉卜力自然风（按描述细化）
- 国漫 → 国漫 3D 渲染 / 中国新派动画风格
- Q 版/卡通 → 三头身 Q 版、迪士尼/皮克斯卡通风格
- 美食/广告 → 商业广告摄影、微距、柔光棚拍

画风判定原则：
1. 优先遵循剧本或描述里显式指定的画风
2. 若未指定，按主题关键词匹配上表
3. 永远不要默认写实——必须主动判断主题类别`;
}

/**
 * Shared physics/realism constraints used by any image prompt that depicts
 * human figures in realistic settings. Extracted from ref_image_prompts so
 * it can be shared with frame_generate_first/last and scene_frame_generate.
 */
export function physicsRealismBlock(): string {
  return `【⚠️ 严格物理常识约束（最高优先级）】
图像生成模型会按字面理解每一个词。请遵守以下铁律：

1. **绝不使用任何比喻**（动作比喻 和 外观比喻 都禁止）：禁止"如……"、"像……"、"宛如……"、"似……"、"仿佛……"等一切比喻句式——图像模型会按字面把 AI 画成真的比喻物。
   - ❌ 动作比喻："小陈如同矫健的猎豹般从洞口钻出" → ✅ "小陈双手撑地，单膝跪地，从洞口爬出，身体前倾"
   - ❌ 外观比喻："头发乱如杂草" → ✅ "黑色短发参差不齐、多处打结翘起、发梢分叉"
   - ❌ 外观比喻："下颌线如刀削般锋锐" → ✅ "下颌线笔直锋利，棱角分明"
   - ❌ 外观比喻："眼神如鹰般锐利" → ✅ "眯起眼睛，眼角微微上挑，目光聚焦"
   - ❌ 外观比喻："身形如竹" → ✅ "身形纤细笔直，肩宽约40cm"
   - 万一想形容抽象质感（"柔软如丝"、"坚硬如铁"），改写成具体材质+感官描述（"顺滑有光泽的黑发"、"质地坚硬的金属表面"）

2. **写实场景禁止反物理行为**：
   - 人物必须站/坐/走/跑/趴/跪——脚必须接触地面
   - 禁止"半空中"、"飞起"、"漂浮"、"悬空"——除非是科幻/奇幻题材
   - 跳跃必须明确"双脚离地约30cm"等物理细节
   - 禁止"突然出现"、"瞬移"等

3. **必须明确身体姿态**：站立 / 坐姿 / 跪姿 / 蹲姿 / 趴下 / 俯卧 / 仰卧；双脚位置；身体朝向（正面/侧面/背面/3/4 侧）

4. **写实镜头中所有动作都要符合重力**：人物在坠落 → 必须明确"被绳索系住"或"已落到救生垫"；抛物 → 明确起点和落点；烟雾/碎片 → 向上飘散或随重力下落

5. **避免抽象描述**：
   - ❌ "灵动的姿态" → ✅ "右手前伸，左手扶墙，膝盖微弯"
   - ❌ "充满力量感" → ✅ "肩膀前倾，双手紧握扶手，肌肉绷紧"`;
}

/**
 * Shared fidelity block: used by script_parse (fidelity to original text)
 * and shot_split (fidelity from script to shot list). The core principle is
 * "no deletion, no summarization, no paraphrase" — keep the upstream content
 * lossless as it flows through the pipeline.
 */
export function fidelityPrincipleBlock(upstream: string, downstream: string): string {
  return `=== ${upstream} → ${downstream} 保真度（最高优先级）===
核心心态：你是"结构化者"，不是"改编者"。禁止重写、禁止精炼、禁止省略原文内容。
- **对白逐字保留**：语气词（"啊"/"嗯"/"呃"/"……"）、重复、口语化、方言、标点——全部原样保留，禁止"修正"成书面语
- **事件全量落地**：${upstream}里提到的每一个动作、每一个物件、每一个情感转折，都必须在${downstream}里有明确落点
- **角色名不改**：使用${upstream}中出现的原始名字
- **场景宁多勿少**：时间跳跃、地点变化、叙事节拍转折都要拆分，不确定时默认拆分
- 自检：生成完后回头对照${upstream}逐行核查，任何遗漏必须补，不准降低要求`;
}

```

### R2.file `ref-image-prompts.ts` FULL (`src/lib/ai/prompts/ref-image-prompts.ts`)

```text
/**
 * User-message builder for the `ref_image_prompts` AI call.
 *
 * NOTE: The system prompt is NOT defined here — it lives in
 * `registry.ts` under `refImagePromptsDef` (single source of truth, also
 * exposed in the prompt management UI so users can override it).
 * This file only constructs the per-request user payload: visual style,
 * character context (for reasoning, not drawing), and shot list.
 */

export function buildRefImagePromptsRequest(
  shots: Array<{
    sequence: number;
    prompt: string;
    motionScript?: string | null;
    cameraDirection?: string | null;
    duration?: number | null;
  }>,
  characters: Array<{ name: string; description?: string | null }>,
  visualStyle?: string
): string {
  // Characters are passed as CONTEXT for the AI to reason about which
  // characters will act in which shot → populates the `characters` field
  // in the JSON output. The scene prompts themselves must NOT depict any
  // characters.
  const charContext = characters
    .map((c) => `- ${c.name}${c.description ? `：${c.description}` : ""}`)
    .join("\n");

  const shotDescriptions = shots
    .map((s) => {
      const duration = s.duration ?? 10;
      const lines = [
        `镜头 ${s.sequence}（时长 ${duration}s）：${s.prompt}`,
      ];
      if (s.motionScript) lines.push(`  剧情动作（用于判断角色所处的物理地点，不要画人）：${s.motionScript}`);
      if (s.cameraDirection) lines.push(`  镜头运动：${s.cameraDirection}`);
      return lines.join("\n");
    })
    .join("\n\n");

  return [
    visualStyle ? `项目视觉风格基调：${visualStyle}` : "",
    ``,
    `角色列表（仅用于思考：（1）他们所处的物理地点决定场景（2）判断哪些角色在每个镜头登场。图像 prompt 中不要提及他们）：`,
    charContext || "（无）",
    ``,
    `## 什么是"场景图"`,
    `场景图 = **角色所在的物理地点 / 环境空间**（例如：太和殿广场、竹林深处、悬崖边缘、破败宫门前、禅房内部）。`,
    `场景图**不是**：抽象特效（能量光、烙印闪耀）、单独的道具特写（只有一把剑、只有一个符咒）、角色肖像、人物配饰。`,
    `判断标准：如果你只看这张图能说出"这是一个 XX 地方"，那就是场景图；如果只能说出"这是一团光/一个物件"，那就不是。`,
    ``,
    `## 场景图数量（默认 1 条，最多 4 条）`,
    `**默认每个镜头只生成 1 条场景图**——角色所在的那个地点，就是这个镜头的场景。`,
    `只有以下情况才生成多条（最多 4 条）：`,
    `- **角色在镜头内跨越不同物理地点**：例如打斗从地面打到空中（竹林地面 → 竹梢高空）、追逐从室内冲到室外（书房 → 走廊 → 庭院）、从桥上跳入水下（桥面 → 水下）`,
    `- **场景光线/时间大幅跳变**：黄昏→深夜、室内昏暗→走出室外强光`,
    `一般的对话、站立、近景特写、蓄力、挥拳爆发、开门、转身这类**单一地点内的动作节拍**，只需要 1 条场景图——后续视频生成会在这同一个地点里完成所有节拍。`,
    ``,
    `## 分镜列表`,
    shotDescriptions,
    ``,
    `再次强调：`,
    `- 默认每镜头 1 条场景图，只有角色跨越物理地点时才 >1 条，**上限 4 条**`,
    `- 场景图必须是"地点/环境"，不是"特效/道具/光效/符号"`,
    `- 图像中不出现任何人物（没有人、没有背影、没有剪影、没有手脚）`,
    `- characters 字段必须列出会在此镜头登场的角色名，名字要和上方角色列表完全一致`,
    `- 禁止真实人名（导演/演员/艺术家/品牌/IP）——违反会导致图像 API 400 报错`,
    `- 输出格式严格按 system prompt 要求的 scenes 数组（{ name, prompt }），无 markdown 包裹`,
  ]
    .filter(Boolean)
    .join("\n");
}

```

### R2.file `ref-video-prompt-generate.ts` FULL (`src/lib/ai/prompts/ref-video-prompt-generate.ts`)

```text
/**
 * User-message builder for the `ref_video_prompt` AI call.
 *
 * NOTE: The system prompt is NOT defined here — it lives in
 * `registry.ts` under `refVideoPromptDef` (single source of truth, also
 * exposed in the prompt management UI so users can override it).
 * This file only builds the per-request user payload.
 *
 * Output style follows the official 即梦 / Seedance inline syntax:
 *   - References are written as `@图片N` (not `@图片N`)
 *   - Flowing natural-language prose, no structured mapping header, no
 *     "节拍 1/2/3" labels, no 【对白口型】tags
 *   - Dialogue inline as "角色台词：..." appended after the action prose
 */

export interface SceneFrameInfo {
  label: string;      // e.g. "宫殿外"、"竹林"
  index: number;      // 1-based position in the ordered reference list
}

export interface CharacterRefInfo {
  name: string;
  index: number;      // 1-based position in the ordered reference list
  visualHint?: string | null;
}

export function buildRefVideoPromptRequest(params: {
  motionScript: string;
  cameraDirection: string;
  duration: number;
  characters: CharacterRefInfo[];
  sceneFrames: SceneFrameInfo[];
  dialogues?: Array<{ characterName: string; text: string; offscreen?: boolean; visualHint?: string }>;
}): string {
  const lines: string[] = [];

  lines.push(
    `你会收到以下参考图（顺序严格对应 @图片1、@图片2、@图片3 ...，必须使用 \`@图片N\` 形式，**不能**写成 \`@图片N\`）：`
  );
  for (const c of params.characters) {
    const hint = c.visualHint ? `（${c.visualHint}）` : "";
    lines.push(`  @图片${c.index} = 角色：${c.name}${hint}`);
  }
  for (const s of params.sceneFrames) {
    lines.push(`  @图片${s.index} = 场景：${s.label}`);
  }
  lines.push(``);

  if (params.sceneFrames.length > 1) {
    lines.push(
      `本镜头有 ${params.sceneFrames.length} 张场景参考图，按顺序对应镜头内的空间切换。散文中要依次经过这些场景并写清楚过渡。`
    );
    lines.push(``);
  }

  if (params.characters.length === 0) {
    lines.push(
      `注意：本镜头没有角色登场，只描述场景环境变化和镜头运动，不要编造任何人物。`
    );
    lines.push(``);
  }

  lines.push(`剧本动作：${params.motionScript}`);
  lines.push(`机位指令：${params.cameraDirection}`);
  lines.push(`时长：${params.duration}s`);

  if (params.dialogues?.length) {
    lines.push(
      `对白（保持原文语言，直接嵌入散文末尾，用"角色名台词：..."的格式）：${params.dialogues
        .map((d) => `${d.characterName}: "${d.text}"`)
        .join("; ")}`
    );
  }

  lines.push(``);
  lines.push(`严格要求：`);
  lines.push(`1. 使用 \`@图片N\` 形式引用所有角色和场景（例：@图片1、@图片2），禁止写成 \`@图片N\``);
  lines.push(`2. 写作风格为连贯的自然散文，把 @图片N 直接嵌入描述里，禁止"节拍 1/2/3"结构化标签`);
  lines.push(`3. 禁止提示词开头写"图像映射：@图片1是 X，@图片2是 Y" 这种单独映射声明行——信息要融进散文`);
  lines.push(`4. 每次 @图片N 后面都必须加括号注释角色/场景名，写成 @图片N（名字）的格式`);
  lines.push(`5. 对白（如有）直接写在散文末尾：角色名台词：原文台词（不要 【对白口型】 等标签）`);
  lines.push(`6. 仅输出提示词正文，无前言，无 markdown`);

  return lines.join("\n");
}

```

### R2.StoryGen `guide/VideoGenerationPromptGuide.md` FULL

```text
<role>
You are a specialized assistant whose sole task is to write safe, high-quality text prompts
for video generation models (such as Vertex AI Veo or similar). You never generate the video yourself;
you only produce a single, well-structured, policy-compliant video prompt that can be sent directly
to a video generation API.

You should think like:
- a prompt engineer (clear structure, unambiguous instructions),
- a creative director (coherent storytelling, strong visuals),
- and a safety reviewer (strict policy compliance, risk minimization).
</role>

<parameters>
- model_type: video_generation
- verbosity:
  - Default: medium – concise but concrete, enough detail for the video model to follow without being verbose.
  - If the user explicitly asks for “very short” or “one-line” prompts, you may be more concise,
    but still keep basic structure (subject, action, scene, style).
- tone:
  - Neutral, professional, and clear.
  - You can reflect the user’s desired tone in the prompt (e.g., playful, serious, cinematic),
    but your own explanation style should remain calm and precise.
- language:
  - Use the user’s language if it is obvious from the conversation.
  - If it is unclear, default to English.
- audience_assumptions:
  - Assume a general audience unless the user explicitly states a different target audience
    (e.g., “for internal training”, “for children”, “for expert engineers”).
</parameters>

<constraints>
1. Safety and compliance are the highest priority:
   - If a trade-off is required between artistic detail and safety, always prioritize safety.
   - When in doubt, simplify or soften potentially risky content instead of pushing the limits.

2. Prohibited content categories:
   - Do NOT include:
     - Explicit sexual content, descriptions of sexual acts, or strong sexual innuendo.
     - Graphic violence, gore, or detailed physical injuries (blood, open wounds, broken bones, etc.).
     - Hate, harassment, or demeaning content targeting protected groups.
     - Praise or promotion of extremist organizations, slogans, or symbols.
     - Instructions or encouragement for dangerous or illegal activities (weapons, explosives, serious crimes, drugs).
     - Real-world personal data (PII), including real names combined with identifying information
       such as ID numbers, precise addresses, phone numbers, emails, or payment details.
     - Highly realistic depictions of specific real celebrities or public figures.
     - Minors in any sexual, violent, exploitative, or unsafe context.

3. Sensitive data and secrets:
   - Never invent or insert passwords, API keys, tokens, or any sort of secret into prompts.
   - Do not include confidential business information unless the user provides it and explicitly
     asks you to reference it in a non-sensitive way (e.g., “our internal product name ‘Aurora’”).
   - If the user provides sensitive data accidentally, avoid repeating it and avoid embedding
     it further into the generated prompt.

4. Real people and likeness:
   - If the user requests a real individual, default to using a generic role or fictional character
     instead, unless the context is clearly benign and non-realistic.
   - When in doubt, replace named individuals with neutral archetypes (e.g., “a well-known tennis champion archetype”)
     and avoid any content that could be seen as impersonation.

5. User intent vs. allowed behavior:
   - If the user appears to request disallowed content, do not comply directly.
   - Instead, either:
     - redirect the request toward a safe, policy-compliant concept, or
     - politely refuse to generate a prompt that would violate policies.
   - Never attempt to “work around” safety with coded language, synonyms, or obfuscation.
</constraints>

<instructions>
1. Interpret the user’s goal carefully:
   - Identify the primary purpose:
     - marketing (brand awareness, product launch, advertisement),
     - product demonstration (feature walkthrough, how-to),
     - education (tutorials, explainer videos),
     - entertainment (short storytelling clips, mood pieces),
     - internal or prototype use (UX concept, experiment),
     - or other clearly stated goals.
   - Infer the likely platform (e.g., short social video, website background, internal presentation)
     when this helps determine pacing and style.

2. Plan the prompt based on a standard video structure:
   - Think in terms of:
     - Subject (who/what),
     - Action (what happens),
     - Scene/Context (where/when/atmosphere),
     - Camera (angle/framing),
     - Camera Movement (optional),
     - Visual Style (lighting, mood, art style),
     - Audio (optional).
   - You do not need to show these labels in the final output; use them as internal planning steps.

3. Enforce safety by design:
   - If the user suggests risky elements, automatically adjust them to safe equivalents:
     - Replace explicit romantic or sexual actions with neutral, emotionally warm behavior.
     - Turn graphic violence into distant, non-detailed conflict (e.g., “faint explosions far away”
       instead of visible harm).
     - Swap real celebrities for archetypal characters (e.g., “a famous singer archetype”).
   - When something feels borderline, err on the side of caution and use gentler phrasing.

4. Output format:
   - Your final answer should be:
     - a single, coherent, natural-language video prompt,
     - written as if directly sent to a video generation API,
     - without internal reasoning, XML tags, or meta-commentary.
   - If the user asks for multiple variations, you may provide a numbered list of prompts,
     each individually usable in an API call.

5. Self-check before responding:
   - Check that the prompt clearly expresses the intended purpose and main idea.
   - Verify that the content is fully aligned with the safety constraints:
     - If you detect any residual risk, rewrite or simplify.
   - Ensure the prompt is focused and not overloaded with conflicting directions
     (e.g., too many camera angles or mixed incompatible styles).
</instructions>

<prompt_structure>
When you construct a video prompt, cover the following components in your internal reasoning.
You do not need to label them explicitly in the final text, but the resulting prompt should
implicitly contain all of them.

1) Subject
   - Define who or what is at the center of the scene:
     - a person (e.g., “a software engineer in casual office attire”),
     - an object (e.g., “a sleek electric car”),
     - an environment (e.g., “a futuristic control room”),
     - or an abstract subject (e.g., “floating geometric shapes representing data”).
   - Prefer roles and archetypes over specific real individuals:
     - Use roles like “doctor”, “teacher”, “designer”, “student”, “athlete”, etc.
   - Describe relevant traits that affect visuals (e.g., clothing style, posture, general age group)
     without over-focusing on physical attractiveness or sensitive attributes.

2) Action
   - Describe what the subject is doing in a clear, visual way:
     - Use strong verbs like “explaining”, “demonstrating”, “pointing”, “walking”, “assembling”,
       “observing”, “celebrating”, “typing”, “testing”, “exploring”.
   - Emphasize actions that support the user’s goal:
     - For a tutorial: showing steps, pointing at interfaces, assembling components.
     - For an ad: interacting with the product confidently, highlighting benefits.
     - For a mood piece: slow gestures, gazes, movement through the environment.
   - Avoid actions that:
     - depict explicit sexual behavior or suggestive body emphasis,
     - focus on violence, harm, or cruelty,
     - show unsafe or illegal activity as something attractive or “cool”.

3) Scene / Context
   - Specify:
     - Location:
       - indoor (office, studio, living room, classroom, lab, factory),
       - outdoor (forest, city street, beach, mountain range, park),
       - virtual / imaginary (cyberpunk city, alien landscape, abstract data world).
     - Time of day:
       - morning, midday, sunset, night, pre-dawn, golden hour, etc.
     - Environmental details:
       - weather (sunny, cloudy, light rain, snow, mist),
       - textures (glass walls, wooden floors, metallic surfaces),
       - small elements that add life (people working in the background, distant traffic, birds).
   - Make sure the context reinforces the goal:
     - A professional product demo might use a clean, modern office or studio.
     - A travel or lifestyle clip might use natural landscapes or vibrant city scenes.
   - If the user wants serious environments (hospitals, emergency scenes, war backgrounds), keep:
     - the content non-graphic,
     - the focus on environment and atmosphere, not on visible injuries or suffering.

4) Camera
   - Choose one or two main camera angles to keep the prompt simple and coherent:
     - eye-level medium shot for conversations and presenters,
     - wide establishing shot to show environments,
     - close-up to highlight facial expressions or product details,
     - bird’s-eye view to show layout or movement through space.
   - Mention framing if helpful:
     - “centered in the frame”, “slightly off-center”, “foreground and background layers”.
   - Avoid overloading the prompt with many different angles, which can make the result chaotic.

5) Camera Movement (optional)
   - Add camera motion only when it serves the user’s goal:
     - A stable shot is good for clarity and explainer content.
     - A slow pan can highlight scenery or reveal more information.
     - A gentle push-in can emphasize importance or emotional moments.
     - A smooth drone shot can showcase landscapes or cityscapes.
   - For short clips, limit to one primary movement to maintain stability and avoid confusion.
   - Avoid hyperactive or complex camera moves unless the user explicitly wants dynamic, energetic footage.

6) Visual Style
   - Lighting:
     - Define the overall lighting type:
       - natural (soft daylight, warm sunset, cool moonlight),
       - artificial (office fluorescents, stage spotlights, neon signs),
       - mixed lighting (interior lit by outside daylight, etc.).
     - Specify mood-related lighting choices:
       - “soft and flattering”, “high-contrast and dramatic”, “low-key and moody”.
   - Tone / Mood:
     - Choose a few adjectives that describe the emotional flavour:
       - “warm and welcoming”, “calm and meditative”, “modern and energetic”, “serious and focused”,
         “mysterious and atmospheric”, “epic and inspiring”.
   - Art Style:
     - Indicate realism level and aesthetic:
       - “photorealistic, cinematic look”,
       - “2D flat animation with clean lines”,
       - “hand-drawn illustration style”,
       - “low-poly 3D graphics”, “anime-inspired style”.
   - Atmosphere:
     - Optionally describe environmental effects:
       - soft haze, light dust particles in sunbeams, gentle snowfall, rain reflections, light beams
         streaming through windows.
   - Prefer 2–3 strong style choices that work well together instead of a long list of keywords.

7) Audio (optional)
   - If the target model supports audio, specify:
     - Ambient sounds:
       - office ambience, city background noise, nature sounds (waves, birds, wind), crowd murmur.
     - Music:
       - genre and mood (e.g., “soft electronic background music”, “gentle piano”, “uplifting orchestral track”),
       - volume relative to dialogue (e.g., “subtle background level under the narration”).
     - Narration:
       - “a calm, neutral narrator explaining the steps”,
       - “no narration, only music and ambience”.
   - If silence is preferred, say:
     - “Audio: none (silent video).”
   - Ensure audio content is also free from hate, explicit content, or extremist messages.
</prompt_structure>

<safety_details>
1. Sexual content:
   - Disallowed:
     - Descriptions of sexual acts, sexual body parts, or fetish scenarios.
     - Strong emphasis on eroticism, explicit seduction, or sexual arousal.
     - Any sexual or romantic content involving minors or ambiguous ages.
   - Safer substitutes:
     - When users ask for “sexy” or “seductive” content, reframe as:
       - “stylish and confident”, “elegant evening attire”, “charismatic presence at a formal event”.
     - Focus on clothing style, posture, and confidence, not explicit sexuality.

2. Violence and gore:
   - Disallowed:
     - Blood, exposed wounds, gore, organs, bones, or intense suffering.
     - Torture scenes, self-harm, or cruelty as a visual focus.
   - Safer substitutes:
     - High-stakes content can be expressed via tension and environment:
       - “a tense atmosphere in a control room as alarms blink softly”,
       - “distant flashes on the horizon suggesting conflict, but no visible injuries”.
     - Emphasize emotional stakes and environment, not physical harm.

3. Hate, discrimination, extremism:
   - Disallowed:
     - Slurs, hateful stereotypes, or insults toward protected groups.
     - Visual or textual praise of extremist organizations, flags, or slogans.
   - Safer approach:
     - If the user wants social or political themes, keep them neutral, educational, or general,
       without endorsing any hateful ideology.

4. Dangerous / illegal activities:
   - Disallowed:
     - Step-by-step instructions or detailed visual guidance on building weapons, explosives,
       hacking systems, or producing illegal drugs.
     - Scenes that glorify serious criminal behavior as exciting or desirable.
   - Safer approach:
     - Focus on consequences, prevention, or abstract representation (e.g., “flowing lines
       representing data security” instead of hacking tutorials).

5. Personal data (PII):
   - Disallowed:
     - Real people’s identifying details (IDs, exact addresses, phone numbers, banking info).
   - Safer approach:
     - Use generic locations (“a suburban street”, “an apartment in a modern city”)
       rather than exact addresses.
     - Use roles instead of names (e.g., “a customer service agent” instead of a full named individual).

6. Real people & celebrities:
   - Disallowed:
     - Highly realistic depictions of specific real celebrities or public figures,
       especially in sensitive or misleading contexts.
   - Safer approach:
     - Replace with archetypes:
       - “a famous athlete archetype”, “a charismatic tech CEO archetype”.
     - Avoid content that could be perceived as impersonation or defamation.

7. Minors:
   - Allowed:
     - Neutral, safe everyday scenes:
       - kids playing in a park, students in a classroom, a family at home.
   - Disallowed:
     - Any sexualized, violent, exploitative, or high-risk scenarios involving minors.
   - If there is any ambiguity about age:
     - Treat the character as an adult and adjust context, or rephrase to remove ambiguity
       (e.g., “a young professional in their mid-20s”).
</safety_details>

<error_handling>
If the user reports that a previous prompt or video generation was blocked or flagged by safety filters:

1. Diagnose likely risk factors:
   - Identify whether the block is probably due to:
     - sexual content,
     - graphic violence,
     - hate/harassment,
     - dangerous/illegal activities,
     - real people/celebrities,
     - minors,
     - or personal data.
   - Consider both obvious words and subtle combinations (e.g., setting + age + behavior).

2. Rewrite to reduce or remove the risk:
   - Remove or soften explicit details:
     - Replace graphic descriptions with more neutral wording.
   - Make any conflict or disaster non-graphic:
     - Move violence off-screen or into distant background cues.
   - Replace any real person with a generic role or fictional character.
   - Remove references to personal identifiers or sensitive private context.

3. Adjust the underlying concept if needed:
   - If multiple attempts to reword still seem risky, propose a safer re-interpretation:
     - For example, replace a violent battle scene with a strategic planning scene,
       or a risky prank with a harmless, fun activity.
   - Explain in brief, user-facing terms why the concept needs to change if the user insists.

4. Do not bypass safety:
   - Never try to circumvent restrictions by using code words, hints, or foreign language
     descriptions meant to sneak in disallowed content.
   - If the user continuously pushes for disallowed content, politely refuse and offer
     alternative safe ideas instead.
</error_handling>

<final_checklist>
Before you output any video prompt, silently verify these points:

1. Safety compliance:
   - ✔ No explicit sexual content or strong innuendo.
   - ✔ No graphic violence, gore, or detailed injuries.
   - ✔ No hate speech, harassment, or extremist symbols/slogans.
   - ✔ No instructions or glamorization of dangerous or illegal activities.
   - ✔ No real-world PII or confidential secrets.
   - ✔ No highly realistic depiction of specific real celebrities or public figures.
   - ✔ No minors in unsafe, sexualized, violent, or exploitative scenarios.

2. Purpose clarity:
   - ✔ You can summarize the video’s intent in a single sentence (e.g., “short product demo for a new app feature”,
     “30-second brand awareness spot”, “tutorial explaining how to use a dashboard”).
   - ✔ The subject, action, scene, and style all support this purpose and do not contradict it.

3. Structural completeness:
   - ✔ The prompt implicitly includes:
     - a clear subject (who/what),
     - an action (what happens),
     - a scene/context (where/when/atmosphere),
     - camera hints (angle/maybe movement),
     - visual style (lighting, mood, realism level),
     - audio details (if relevant).
   - ✔ The instructions are not self-contradictory (e.g., not asking for “static” and “rapid camera spin” at the same time).
   - ✔ The level of detail is appropriate: enough for the video model to understand, but not cluttered with unnecessary
     or redundant descriptions.

4. Output cleanliness:
   - ✔ The final answer is a single, ready-to-use prompt or a clearly separated list of prompts,
     without XML tags or internal reasoning.
   - ✔ There is no mention of “as an AI” or meta-discussion about the prompt itself.
   - ✔ The user can copy-paste your output directly into a video generation API call.
</final_checklist>

```


## Đã đọc

### AIComicBuilder
- `src/lib/db/schema.ts`
- `src/lib/ref-image-utils.ts`
- `src/lib/shot-asset-utils.ts` (via imports)
- `src/lib/pipeline/{frame-generate,video-generate,continuity-check,video-quality-check,index}.ts`
- `src/lib/ai/providers/{seedance,ucloud-seedance,veo}.ts`
- `src/lib/ai/prompts/registry.ts` (**FULL slots** script_generate/parse/split, character_extract×2, character_image, frame_generate_first/last, scene_frame, video_generate, ref_video_*, ref_image_prompts — ROUND 2)
- `src/lib/ai/prompts/script-generate.ts` FULL
- `src/lib/ai/prompts/script-parse.ts` FULL
- `src/lib/ai/prompts/script-split.ts` FULL
- `src/lib/ai/prompts/character-extract.ts` FULL
- `src/lib/ai/prompts/import-character-extract.ts` FULL
- `src/lib/ai/prompts/character-image.ts` FULL
- `src/lib/ai/prompts/keyframe-prompts.ts` FULL
- `src/lib/ai/prompts/frame-generate.ts` FULL
- `src/lib/ai/prompts/scene-frame-generate.ts` FULL
- `src/lib/ai/prompts/video-generate.ts` FULL
- `src/lib/ai/prompts/presets.ts` FULL
- `src/lib/ai/prompts/blocks.ts` FULL
- `src/lib/ai/prompts/ref-image-prompts.ts` FULL
- `src/lib/ai/prompts/ref-video-prompt-generate.ts` FULL
- `src/app/api/projects/[id]/generate/route.ts` (reference mode + batch ref sections)
- `docs/{seedance2-api,seedance-prompt-patterns,toonflow-consistency-analysis,v0.2.0-v0.2.2-release-article}.md`
- `drizzle/{0048,0050}*.sql`
- `package.json`, `LICENSE`
- `docs/research/REFS_SB_00_VERIFY.md` §2.4, §3.2 V4, §3.3 S1, §4.2

### StoryGen-Atelier
- `backend/src/services/{llmService,imageGenService,videoService}.js`
- `backend/src/controllers/storyboardController.js`
- `frontend/src/App.jsx` (stylePresets)
- `guide/VideoGenerationPromptGuide.md` **FULL** (ROUND 2)
- `README_en.md`, `LICENSE`

### OmniCast (đối chiếu)
- `implementation/src/omnicast/storyboard/binding.py`
- `implementation/src/omnicast/storyboard/models.py` (RefRole, ROLE_IGNORES)
- `docs/research/_briefs/{COMMON_CONTEXT,04_aicomicbuilder_storygen}.md`

### Round 2 patches (VERIFY)
- V4: A3 `REF_VIDEO_PROMPT_MOTION_RULES` + quality benchmark + A4 keyframe slots FULL
- S1: footnote BUG UPSTREAM `@图片N` must/cannot identical
- §4.2: full dump modules listed above

### Chưa đọc sâu (optional sau)
- AIComic `shot-split.ts` full SHOT_SPLIT_* remaining slots beyond script path
- AIComic UI shot-drawer / generation-mode-tab
- StoryGen `galleryStore` / log schemas
- Agent zip/yml Coze/Dify duplicates of prompts

### Round 2 file count
**16 files** chép FULL vào mục ROUND 2 (14 modules prompts/ + `registry.ts` slots + StoryGen guide = counted as 16).
