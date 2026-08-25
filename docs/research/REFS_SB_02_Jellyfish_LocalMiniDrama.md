# REFS_SB_02 — Jellyfish + LocalMiniDrama (AI Short Drama Studio)

> STATUS: ACTIVE  
> Ngày: 2026-08-02  
> Phạm vi: `_refs/Jellyfish` (Apache-2.0) + `_refs/LocalMiniDrama` (MIT)  
> Mục đích: đối chiếu pipeline kịch bản→分镜→shot, cast consistency, pacing thoại, UI workflow — map vào OmniCast `storyboard/` + `/storyboard`.
> **ROUND 2 (2026-08-02):** vá VERIFY E1/E4/V6/V7 + section ROUND2 VERBATIM FULL theo §4.3.

---

## 0. Tóm tắt điều hành (đọc 2 phút)

| Trục | **Jellyfish** | **LocalMiniDrama** | **OmniCast hiện tại** |
|------|---------------|--------------------|------------------------|
| Vai trò | Production **workspace** (chuẩn bị → xác nhận → gen) | Desktop **local-first** end-to-end (tải exe, SQLite) | Engine + cast registry + fail-closed continuity |
| Script→shot | Multi-agent tách bước, candidate **human-confirm** | Một system prompt分镜 + user suffix; optional universal omni | `extract.py` → DraftShot; chưa candidate gate UX-level |
| Cast model | **Actor + Costume + Props → Character**; shot link theo index | Character flat (appearance, identity_anchors, polished_prompt, four-view sheet) | Entity + refsheet + RefRole |
| Consistency | Entity merge/variant; ref `图N`; neighbor continuity in frame prompts | **Identity anchors + ref image ưu tiên text**; layout_description; continuity_snapshot | Token `[IMAGE n]` + RefRole; pixel drift chưa đo |
| Thoại | `ShotDialogLine` (speaker/target/mode); **chưa TTS/lip-sync** | dialogue + narration TTS; SRT burn; **không lip-sync thật** | TTS pipeline riêng; chưa multi-speaker per-shot drama |
| UI học | **Chuẩn bị (ready) tách khỏi Studio gen** | Canvas workflow + list mode | `/storyboard` cần tách prep vs gen |

**Bài học then chốt cho OmniCast:**
1. **Human-in-the-loop candidate confirm** (linked/ignored/accepted) trước khi `ready` — Jellyfish làm rất rõ.
2. **Tách “base prompt” (không có map ảnh) và “rendered prompt” (có `图N` / `[IMAGE n]`)** — Jellyfish enforce; LocalMiniDrama tương đương `@图片N`.
3. **Character sheet công nghiệp + 6-layer identity anchors + “cấm viết ngoại mạo vào prompt khi đã có ref”** — LocalMiniDrama.
4. **layout_description = spatial contract** + first/last frame movement evolution — LocalMiniDrama.
5. **UI: ChapterShotEditPage (prep) ≠ ChapterStudio (gen)** — map thẳng vào `/storyboard`.

---

## 1. Tổng quan kiến trúc

### 1.1 Jellyfish — module map

```
front/ (React+Vite+Ant Design)
  pages/aiStudio/
    project/ProjectWorkbench/     # Project lobby, chapters, roles, assets
    shots/ChapterShotEditPage     # ★ 分镜准备页 (prep)
    chapter/ChapterStudio         # ★ 生成工作台 (gen)
    assets/                       # Actor/Scene/Prop/Costume CRUD + images
backend/app/
  chains/agents/                  # LLM agents (script + frame prompts)
  models/studio_*.py              # ORM: projects, shots, assets, tasks
  services/
    script_processing_*.py        # divide/extract/consistency async
    film/shot_frame_prompt_tasks  # first/last/key frame prompt jobs
    studio/generation/{asset_image,frame,video}/
  core/task_manager/              # Unified async tasks + cancel
```

**Luồng end-to-end (script → video):**

```text
Chapter.raw_script
  → [optional] ScriptSimplifierAgent
  → [optional] ConsistencyCheckerAgent → ScriptOptimizerAgent (chỉ khi has_issues)
  → ScriptDividerAgent  → ScriptDivisionResult (shots[])
  → write shots rows (status=pending)
  → ElementExtractorAgent → StudioScriptExtractionDraft
      (global characters/scenes/props/costumes + per-shot links + dialogue_lines)
  → sync shot_extracted_candidates + dialogue_candidates
  → User: ChapterShotEditPage 确认 (link/ignore assets, accept/ignore dialogue)
  → shot.status = ready
  → Shot frame prompt agents (first/last/key) + asset images
  → ChapterStudio: reference_mode video gen (first | last | key | first_last | …)
  → generated_video_file_id on Shot
```

Cite: `site/content/product/workflow.md:7-36`, `site/content/docs/architecture/shot-status-flow.md:39-146`, `backend/app/services/script_processing_worker.py:53-195`.

### 1.2 LocalMiniDrama — module map

```
desktop/ (Electron) → frontweb/ (Vue3) + backend-node/ (Express + better-sqlite3)
backend-node/src/
  routes/  drama, characters, scenes, storyboards, images, videos, audio, …
  services/
    storyGenerationService.js      # outline → multi-episode script
    characterGenerationService.js  # extract + identity_anchors
    backgroundExtractionService.js # scenes
    propExtractionService.js
    episodeStoryboardService.js    # ★ 分镜 LLM
    framePromptService.js          # first/key/last frame text
    imageService.js                # image gen + auto ref order
    videoService.js / videoClient.js
    videoMergeService.js           # episode concat
    ttsService.js + narrationVideoPostProcess.js
    promptI18n.js                  # ★ ALL prompt templates
    universalSegmentPromptBundle.js # @图片N omni bundle
frontweb/src/
  views/ FilmCreate, DramaDetail, DramaCanvas, FreeCreate
  components/dramaCanvas/*         # LibTV-style canvas workflow
```

**Luồng end-to-end:**

```text
drama (title/genre/style)
  → story expansion (multi episode scripts)
  → extract characters → polished_prompt + identity_anchors → 工业参考表 image
  → extract scenes → polished 4-view or single → scene image
  → extract props → product-hero image
  → generate storyboards (classic OR universal omni)
  → per shot: first/last frame images (refs: scene + characters + props)
  → video (i2v / first-last / multi-ref omni with @图片N)
  → optional TTS dialogue + narration → merge → SRT burn-in
```

Cite: `README.md:124-138`, `backend-node/migrations/01_init.sql`, `backend-node/src/services/episodeStoryboardService.js:1231-1292`.

### 1.3 So sánh chéo kiến trúc

| | Jellyfish | LocalMiniDrama |
|--|-----------|----------------|
| Storage | SQL (MySQL-oriented models) + files | SQLite local + filesystem |
| LLM orchestration | LangChain AgentBase + structured Pydantic | Raw chat completions + JSON parse + continuation |
| Human gate | **Bắt buộc** candidate confirm | Tùy chọn (edit list/canvas; one-click pipeline) |
| Deployment | Docker compose server | Electron desktop, data offline |
| Closest to OmniCast | Cast composition + fail-ready workflow | Prompt craft + ref-order + continuity tricks |

---

## 2. Data model storyboard

### 2.1 Jellyfish (verbatim fields quan trọng)

**Shot** (`backend/app/models/studio_shots.py:24-128`):

| Field | Ý nghĩa |
|-------|---------|
| `id`, `chapter_id`, `index` | PK; số thứ tự trong chapter (unique) |
| `title`, `script_excerpt` | Tiêu đề + trích kịch bản |
| `status` | Enum `ShotStatus` (`types.py:34-39`): **`pending` \| `generating` \| `ready`**. Lưu ý runtime: `recompute_shot_status` / `mark_shot_generating` **chỉ** ghi `pending`/`ready` (không còn ghi `generating` — migration `sql/003-normalize-shot-status-remove-generating.sql`, `shot_status.py:1-9,90-96`); enum vẫn giữ `generating` cho tương thích. |
| `skip_extraction` | User bỏ qua extract → sẵn sàng ready |
| `last_extracted_at` | Phân biệt “chưa extract” vs “extract rỗng” |
| `generated_video_file_id` | Video đã gen |

**ShotDetail** (1:1, `studio_shots.py:131-218` — đủ field class):

| Field | Ý nghĩa | Dòng code |
|-------|---------|-----------|
| `id` | PK = `shots.id` (FK cascade) | 145-150 |
| `camera_shot` | ECU/CU/MCU/MS/MLS/LS/ELS | 151-155 |
| `angle` | EYE_LEVEL/HIGH_ANGLE/LOW_ANGLE/BIRD_EYE/DUTCH/OVER_SHOULDER | 156-160 |
| `movement` | STATIC/PAN/TILT/DOLLY_IN/DOLLY_OUT/TRACK/CRANE/HANDHELD/STEADICAM/ZOOM_* | 161-165 |
| `scene_id` | FK scenes, nullable | 166-172 |
| `duration` | **Nguồn thời lượng duy nhất (giây, int)** | 173 |
| `override_video_ratio` | Override tỉ lệ video cấp shot; null = inherit project | 174-179 |
| `mood_tags` | JSON `list[str]` | 180 |
| `atmosphere` | Mô tả không khí | 181 |
| `follow_atmosphere` | bool, default True — có kế thừa atmosphere | 182 |
| `has_bgm` | bool, default False — shot có BGM | 183 |
| `vfx_type` | VFXType code | 184-189 |
| `vfx_note` | Ghi chú VFX ngắn | 190 |
| `description` | Mô tả tổng thể shot (bổ sung prompt) | 191-196 |
| `action_beats` | JSON list 2–4 beat hành động theo thời gian | 197-202 |
| `prompt_template_id` | FK prompt_templates, optional | 203-208 |
| `first_frame_prompt` | Base prompt首帧 | 209-211 |
| `last_frame_prompt` | Base prompt尾帧 | 212-214 |
| `key_frame_prompt` | Base prompt关键帧 | 215-217 |

**Character composition** (`studio_assets.py:149-242`):

```text
Actor (diễn viên/外观资产, global-ish name unique)
  + Costume (服装)
  + Props via CharacterPropLink
  → Character (project-scoped name, actor_id, costume_id)
  → ShotCharacterLink(shot_id, character_id, index)
```

**Dialogue** (`ShotDialogLine`, lines 284-347):

- `index`, `text`, `line_mode` (DIALOGUE / VOICE_OVER / OFF_SCREEN / PHONE)
- `speaker_character_id`, `target_character_id`
- `speaker_name`, `target_name` (tạm khi chưa link)

**Candidates** (chuẩn bị):

- `ShotExtractedCandidate`: type ∈ character/scene/prop/costume; status pending/linked/ignored
- `ShotExtractedDialogueCandidate`: pending/accepted/ignored → ghi `ShotDialogLine`

**State machine / `ShotStatus`** (`types.py:34-39` + `shot_status.py` + `shot-status-flow.md`):

```text
ENUM (3 giá trị): pending | generating | ready

recompute_shot_status (static prep gate — hiện tại ghi DB):
  skip_extraction=true                         → ready
  never extracted (last_extracted_at is None)  → pending
  extracted, 0 asset candidates AND 0 dialogue → ready
  all asset candidates linked|ignored
    AND all dialogue candidates accepted|ignored → ready
  else                                         → pending

generating:
  - Vẫn là member của ShotStatus enum
  - mark_shot_generating() KHÔNG còn set status=generating; chỉ gọi recompute (pending|ready)
  - SQL 003: backfill lịch sử status='generating' → pending|ready
  - “Đang generate video/image” theo dõi qua GenerationTask, không qua shots.status
```

### 2.2 LocalMiniDrama

**storyboards** (`migrations/01_init.sql:36-60` + migrate.js extensions):

| Field | Ý nghĩa |
|-------|---------|
| `episode_id`, `storyboard_number` | Thuộc tập + thứ tự |
| `title`, `description`, `location`, `time` | Meta |
| `duration` | Giây (LLM gợi ý + project clip length) |
| `dialogue`, `narration` | Thoại vs旁白 (tách) |
| `action`, `result`, `atmosphere` | Hành động / kết quả / không khí |
| `shot_type`, `angle`, `movement` | 景别 / 机位 / 运镜 |
| `lighting_style`, `depth_of_field` | Ánh sáng / DOF |
| `image_prompt`, `polished_prompt`, `video_prompt` | Prompt layers |
| `universal_segment_text` | Omni multi-beat block |
| `characters` (JSON IDs), `scene_id`, props M2M | Bind assets |
| `layout_description` | **Spatial contract** (migrate 15+) |
| `continuity_snapshot` | JSON clothing/position/expression |
| `audio_local_path`, `narration_audio_local_path` | TTS |
| `image_url`/`local_path`, `last_frame_*` | Frames |

**characters** (core + anchors):

| Field | Ý nghĩa |
|-------|---------|
| `name`, `role` (main/supporting/minor) | |
| `description`, `personality`, `appearance` | Text |
| `voice_style` | Gợi ý TTS |
| `image_url` / `local_path` / `four_view_image_url` | Ảnh chuẩn |
| `polished_prompt` | Prompt công nghiệp ref sheet (ưu tiên khi gen) |
| `identity_anchors` | JSON 6 lớp (xem §3) |
| `negative_prompt`, `seedance2_asset` | Provider-specific |

**dramas / episodes / scenes / props / libraries**: drama-level asset reuse; `episode_characters` join.

### 2.3 Map sang OmniCast

| Jellyfish | LocalMiniDrama | OmniCast |
|-----------|----------------|----------|
| Character = Actor+Costume+Props | Character flat + anchors | Entity kinds character/location/prop/costume |
| ShotCharacterLink.index | characters[] order | ordered bindings / RefRole |
| ShotDialogLine | dialogue string + narration | Chưa structured multi-line drama |
| pending/generating/ready (enum; runtime prep=pending\|ready) + candidates | status draft/… loose | continuity fail-closed, chưa UX candidate |
| action_beats[] | action + multi-cut in one shot | Shot.beats / animatic |

---

## 3. Cơ chế consistency

### 3.1 Jellyfish

1. **Script-level role confusion check** — `ConsistencyCheckerAgent` chỉ bắt “cùng người bị gán sai hành vi/đại từ”.
2. **Name dictionary hard constraint** — `ElementExtractorAgent` buộc `shots[*].character_names` ⊂ global `characters[].name` (verbatim, kể cả fullwidth brackets).
3. **EntityMerger + VariantAnalyzer** — gộp alias, timeline trang phục (`costume_timelines`).
4. **Character = Actor + Costume**: gen character image: ref image1 = actor face, image2 = costume (`sql/001-init-prompt-template.sql` character_image_front).
5. **Non-front views** bind front ref: `_resolve_front_ref` khi `view_angle` ≠ front (`asset_image/build_base.py:128-136`).
6. **Shot frame refs**: ordered list → tokens `图1`, `图2`…; replace entity names in base prompt; append:

```text
## 图片内容说明
图1: <name>
图2: <name>
## 生成内容
<base prompt with 图N>
```

Cite: `generation/frame/build_context.py:8-29`, `derive_preview.py:9-24, 286-300`.

7. **Neighbor continuity** injected into frame prompt (`shot_frame_prompt_tasks.py:162-189`): same scene → axis/direction stable; handoff to next shot.
8. **QA on generated base prompt**: reject if contains `## 图片内容说明` or missing lead character names; retry with `retry_guidance` (`shot_frame_prompt_tasks.py:589-607`).

**Không có:** IP-Adapter/LoRA code, pixel-level drift metric, auto re-roll identity score.

### 3.2 LocalMiniDrama (đặc biệt quan trọng khi model “yếu”)

Chiến lược: **đừng tin text appearance khi gen shot** — tin **ref image + anchors**.

1. **identity_anchors (6 lớp)** — extract từ `appearance`, lưu JSON + `color_palette` Hex.
2. **Industrial character reference sheet** — `getRolePolishPrompt` → `polished_prompt` → image system `getRoleGenerateImagePrompt` (FACE HERO + FRONT/BACK + SIDE PROFILE + COSTUME DETAIL).
3. **Prompt iron laws when generating frames** (first/key/last):
   - Chỉ nhân vật trong ALLOWED list
   - Mỗi nhân vật: `名字（参考图中的人物形象）` + position/pose/expression — **cấm** hair/face/skin trong prompt (trung version)
   - Scene lines **zero** human appearance
4. **layout_description** — “最高优先级空间合同”: standing left/center/right, prop **real-world scale**, breathing room for camera movement.
5. **First→last layout lock**: when gen last frame, prepend first frame as ref (`imageService.js` layout lock ~764-772).
6. **continuity_snapshot** JSON after image polish — clothing/posture/screen_position for next shot (`getContinuitySnapshotPrompt`).
7. **@图片N** for omni video: `@图片1` = scene only; `@图片2+` = characters in `characters[]` order; props next (`universalSegmentPromptBundle.js:109-120`, `promptI18n.js:306-315`).
8. **Seedance2 / ModelArk private assets** — optional certified character assets (migrate 20).

### 3.3 So sánh → OmniCast gap

| Cơ chế | Jellyfish | LMD | OmniCast | Gap |
|--------|-----------|-----|----------|-----|
| Ordered ref tokens | 图N | @图片N / Image N | [IMAGE n] + RefRole | Align role semantics (scene vs identity) |
| Character sheet multi-view | Actor views + costume | Industrial sheet + 4-view scene | refsheet.py | Học layout sheet LMD |
| Identity text anchors | description + actor desc | **6-layer Hex anchors** | Entity fields | Thêm structured anchors |
| Spatial lock | composition_anchor in frame agent | **layout_description** | continuity gate (layout-ish) | Persist layout contract per shot |
| Clothing drift | costume entity | **cấm clothing in image prompt** + snapshot | RefRole IDENTITY ignore clothing? | Enforce “ref owns wardrobe” |
| Pixel verify | không | không | không | Vẫn open |

---

## 4. PROMPT ENGINEERING — VERBATIM

> Giữ nguyên ngôn ngữ gốc. Chỉ trích **system/core templates** đầy đủ; user wrappers ngắn gọn hơn.

### 4.1 Jellyfish — pipeline script agents

#### (1) ScriptDividerAgent — system

Nguồn: `backend/app/chains/agents/script_divider_agent.py:13-22`

```
你是\"剧本分镜师\"。将完整剧本分割为多个镜头。每个镜头应是完整的连贯场景。
为每个镜头提供：
- index（镜头序号，章节内唯一；从 1 开始）
- start_line、end_line
- shot_name（镜头名称/镜头标题，分镜名；一句话描述该镜头画面/动作；不要把它当作场景名）
- script_excerpt（镜头对应的剧本摘录/文本）
- time_of_day
只输出 JSON，符合 ScriptDivisionResult 结构。
```

User: `## 输入脚本\n{script_text}\n\n## 输出\n`

**Vì sao hiệu quả:** Tách **shot_name ≠ scene_name**; bắt buộc `script_excerpt` + line range → audit được.

#### (2) ConsistencyCheckerAgent — system

Nguồn: `consistency_checker_agent.py:12-20`

```
你是\"一致性检查员\"。只做一件事：检测原文中是否把“同一个角色”在不同段落/镜头中赋予了不同的身份或行为主体，导致角色混淆（例如：同名不同人、代词指代混乱、行为归属错位）。

输出 ScriptConsistencyCheckResult：
- issues: 每条问题必须包含 character_candidates、description、suggestion；尽量给出 affected_lines（start_line/end_line）。
- has_issues: issues 非空则为 true

只输出 JSON。
```

**Vì sao:** Scope hẹp (role confusion only) → ít false positive, optimizer chỉ sửa tối thiểu.

#### (3) ScriptOptimizerAgent — system

Nguồn: `script_optimizer_agent.py:12-24`

```
你是\"剧本优化师\"。仅当一致性检查发现角色混淆问题时，对原文进行最小改写以消除混淆。

输入：
- script_text：原文
- consistency_json：一致性检查输出（ScriptConsistencyCheckResult）

输出 ScriptOptimizationResult：
- optimized_script_text：优化后的完整剧本文本（尽量少改，只改与 issues 相关的段落）
- change_summary：逐条对应 issues 的改动摘要

只输出 JSON。
```

#### (4) ScriptSimplifierAgent — system

Nguồn: `script_simplifier_agent.py:12-27`

```
你是"智能精简剧本Agent"。你的任务是：在不改变核心剧情走向的前提下精简剧本。

强约束：
- 必须保留剧情主体（关键事件、关键冲突、关键转折、结局/阶段性结果）。
- 必须保证剧情连续（时间顺序、因果关系、角色动机衔接不能断裂）。
- 禁止凭空新增关键设定或关键事件。
- 精简优先删除冗余重复描述、弱信息修饰、对主线无贡献的枝节句。
- 输出语言风格尽量贴近原文叙述口吻。

输出 ScriptSimplificationResult：
- simplified_script_text：精简后的完整文本
- simplification_summary：精简策略摘要（说明删改了什么、为何不影响主线）

只输出 JSON。
```

#### (5) ElementExtractorAgent — system (**NON-VERBATIM tóm tắt**; full ở §ROUND 2)

Nguồn: `element_extractor_agent.py:12-53`. Round 1 chỉ tóm điểm hard (KHÔNG thay cho chép đủ):

- Output `StudioScriptExtractionDraft` với characters/scenes/props/costumes/shots
- **Name dictionary**: shots chỉ được trích name đã có trong global list; cấm alias drift
- Group characters phải tạo entry cùng name
- `semantic_suggestion`: camera_shot/angle/movement enums + duration + **action_beats 2-4**
- dialogue_lines: `{index, text, line_mode, speaker_name?, target_name?}`
- **FULL system + user template:** xem section ROUND2 VERBATIM FULL.

#### (6) CharacterPortraitAnalysisAgent — system

Nguồn: `character_portrait_analysis_agent.py:12-29`

```
你是\"人物画像分析师\"。你的任务是：当给定一份“原文人物描述”时，判断其中缺少哪些关键信息，导致无法生成合理的人物画像（外貌/服装造型/气质/性格倾向/年龄感/显著标志特征/背景或动机线索等）。

要求：
- 输出必须严格服务于“可直接用于AI图像生成”的目的，optimized_description 需是一段连贯、正面、画面感强的描述。
- 原文仅作参照：只能在原文已明确给出的内容基础上进行顺滑连接或不改变原意的重排，不能修改、替换或弱化原文中的任何人物信息（年龄、性别、外貌特征、性格描述等）。
- 当原文信息不足时，进行合理的保守补全式扩展，使 optimized_description 至少覆盖以下维度：年龄、性别、性格倾向、外貌（面部特征、体态、肤质、发型等）、服装造型、气质、显著标志特征，并可适度加入背景或动机线索（需与整体画像目标一致）。
- issues：列出原文真正缺失的关键维度或存在的歧义点…
- optimized_description：…形成一段可直接复制用于AI图像生成模型的完整人物描述。

禁止项（严格执行）：
- optimized_description 中绝对不允许出现“未被详细说明”“信息不详”“未知”“不明确”“假设”“比如”“可以设想”“类似”“通常”“可能”“大概”等任何模糊、不稳定、占位或推测性词语。
- 所有描述必须使用肯定、具体的正面语言，直接给出可视觉化的细节。
…
只输出 JSON，符合 CharacterPortraitAnalysisResult 结构。
```

**Vì sao:** Cấm hedge words + post-process strip fuzzy markers (`_normalize` lines 83-108) — giảm prompt “không vẽ được”.

Scene/Prop/Costume analysis agents **cùng pattern** (issues + optimized_description, cấm模糊词):  
`scene_info_analysis_agent.py:12-29`, `prop_info_analysis_agent.py:12-29`, `costume_info_analysis_agent.py:12-29`.

#### (7) Shot frame base template (first/last/key) — **NON-VERBATIM tóm tắt**

Nguồn: `shot_frame_prompt_agents.py:109-181`. Round 1 rút gọn (có ellipsis) — **không đủ CHÉP ĐỦ**.

Ý chính: base prompt cấm `图N` / `## 图片内容说明`; 21 hard constraints; first frame = incomplete action state; neighbor continuity fields.

**FULL `_FRAME_FOCUS` + `_SHOT_FRAME_TEMPLATE`:** xem section ROUND2 VERBATIM FULL.

**Vì sao cực hay:** **Base prompt không được chứa token ảnh** — mapping do code append sau → tránh LLM “bịa” 图3. Khớp triết lý OmniCast `binding.py`.

#### (8) Asset image DB templates (actor front — excerpt)

Nguồn: `backend/sql/001-init-prompt-template.sql:6` (actor_image_front)

```
视觉风格：{{ visual_style }}
画面风格：{{ style }}

高质量电影级{{ visual_style }}人像摄影，超详细专业演员写真：
{{ description }}

镜头方向：正面
画面要求：
- 超高细节，8k分辨率…
负面提示（强烈负面）：
low quality, worst quality, blurry, deformed, bad anatomy, …
```

Character front (id 3): **“与参考图像1中完全相同的人…如果参考图像2存在，使用参考图像2的服装。”**

---

### 4.2 LocalMiniDrama — pipeline prompts

#### (A) Character extraction — system (zh) **VERBATIM FULL**

Nguồn: `promptI18n.js` `getCharacterExtractionPrompt` default zh return (lines 71-89). Placeholders `${style}` / `${imageRatio}` giữ nguyên như source.

```
你是一个专业的角色分析师，擅长从剧本中提取和分析角色信息。

**【语言要求】所有字段的值必须使用中文，禁止出现英文内容（role字段的值除外，固定为 main/supporting/minor）。**

你的任务是根据提供的剧本内容，提取并整理剧中出现的所有有名字角色的设定。

要求：
1. 提取所有有名字的角色（忽略无名路人或背景角色）
2. 对每个角色，提取以下信息（全部用中文填写）：
   - name: 角色名字（中文）
   - role: 角色类型，固定值之一：main / supporting / minor
   - appearance: 外貌描述（中文，100-200字，包含性别、年龄、体型、面部特征、发型、服装风格等，不含任何场景或环境信息）
   - description: 背景故事和角色关系（中文，50-100字）
3. 主要角色外貌要详细，次要角色可简化
- **风格要求**：${style}
- **图片比例**：${imageRatio}
输出格式：
**重要：必须只返回纯JSON数组，不要包含任何markdown代码块、说明文字或其他内容。直接以 [ 开头，以 ] 结尾。**
每个元素是一个角色对象，包含上述字段。
```

#### (B) Identity anchors — system (full)

Nguồn: `promptI18n.js:1492-1515`

```
You are a character visual analyst. Extract precise visual identity anchors from character appearance descriptions.

Output ONLY a valid JSON object with these exact 6 keys:
{
  "face_shape": "precise description of face/skull shape, jawline, cheekbones (e.g. oval face, sharp jawline, high cheekbones)",
  "facial_features": "eye shape+color+Hex, nose bridge+tip, lip thickness+shape (e.g. almond eyes #3D2B1F, straight nose, thin lips)",
  "unique_marks": "scars, moles, tattoos, birthmarks, distinctive features — or 'none'",
  "color_anchors": {
    "hair": "#HexCode (e.g. #1A0A00 for black, #C8A96E for blonde)",
    "eyes": "#HexCode",
    "skin": "#HexCode (e.g. #F5DEB3 for wheat, #FDDBB4 for fair)",
    "primary_outfit": "#HexCode of dominant clothing color"
  },
  "skin_texture": "skin tone description + texture (e.g. fair porcelain smooth, tanned slightly weathered)",
  "hair_style": "length + style + texture (e.g. shoulder-length wavy black hair with loose strands, short crew cut)"
}

Rules:
- Use Hex color codes for ALL color values — never use color names like "black" or "brown"
- Extract ONLY what is explicitly stated; infer Hex values from color descriptions
- Keep each field concise (1-2 sentences max)
- If information is missing for a field, write "unspecified"
- Output ONLY the JSON object, no markdown, no explanation
```

**Vì sao:** Hex + 6 keys → model yếu vẫn bám “màu tóc #1A0A00” thay vì “黑色漂亮头发”.

#### (C) Role polish — industrial sheet (zh core)

Nguồn: `promptI18n.js:1151-1237` (full dài — **verbatim trong file**). Cấu trúc output bắt buộc:

```
【基础设定】… 【标题栏】… 【FACE HERO CLOSE-UP｜左竖栏】…
【FRONT VIEW｜右区-正面全身】… 【BACK VIEW】… 【SIDE PROFILE CLOSE-UP】…
【COSTUME / SUIT DETAIL VIEW】… 【MATERIAL & TEXTURE NOTES】… 【SIGNATURE PROP…】
```

Image system (`getRoleGenerateImagePrompt`, lines 1243-1253): single canvas industrial layout, solid white, NOT 2×2 grid.

#### (D) Storyboard system — excerpt (zh)

Nguồn: `promptI18n.js:185-276`

```
【角色】你是一位资深影视分镜师，精通罗伯特·麦基的镜头拆解理论，擅长构建情绪节奏。

【任务】将小说剧本按**独立动作单元**拆解为分镜头方案。

【分镜拆解原则】
1. **动作单元划分**：每个分镜对应一个**叙事节拍**，允许包含1-4个快速连续的内部切镜…
3. **运镜要求**（**强制动态优先**）：…**固定镜头不得超过20%**。
…
【输出要求】JSON array fields: shot_number, title, segment_index, segment_title,
location, time, shot_type, camera_angle, camera_movement, lighting_style,
depth_of_field, action, result, dialogue, emotion, emotion_intensity
```

User suffix thêm: `layout_description` spatial contract, duration, characters ID-only, bgm empty (`getStoryboardUserPromptSuffix` 474-504).

#### (E) First frame prompt — iron laws (zh excerpt)

Nguồn: `promptI18n.js:567-611`

```
重要：这是镜头的首帧 - 一个完全静态的画面，展示动作发生之前的初始状态。
【最高优先级真实物理尺度…】
核心规则：
1. 聚焦初始静态状态…禁止包含任何动作或运动描述
3. 【出场角色铁律】仅允许…名单内的人物出现
4. 【角色外貌写法铁律】…只能写为「角色名（参考图中的人物形象）」+ 画面位置 + 姿态 + 表情 + 手持道具；…严禁写发型、发色…五官…
5. 【场景描写铁律】…严禁出现任何人物外貌描写
…5层结构输出… prompt 必须全文中文
```

Last frame thêm **movement evolution** cho clip 5–15s (lines 732-753): push-in → tighter framing; handheld drift; cấm swap left/right.

#### (F) Image polish — clothing ban (zh excerpt)

Nguồn: `promptI18n.js:1297-1344`

```
5. **角色外貌描述铁律**…仅允许使用固定身份特征…严禁…服装、衣着、服饰…
   服装…完全由参考图决定
8. **服装与连戏一致性铁律**：PREV_CONTINUITY_STATE 必须逐字匹配…未写明换衣服则绝不改变服装
```

#### (G) Universal Omni segment (video multi-ref)

Nguồn: `promptI18n.js:1350-1394` + multi-beat format `282-325`

```
@图片1 = scene/environment only; @图片2+ = characters in characters[] order; then props
Dialogue: @图片2 says:"verbatim line" …
结构:
第1行：画面风格和类型: …
第2行：生成一个由以下M个分镜组成的视频。
第3行：LINE3_REQUIRED (locked)
第4+：分镜k： Tk秒: …  Sum(Tk)=duration
```

#### (H) Continuity snapshot

Nguồn: `promptI18n.js:1417-1449` — JSON `characters.<name>.{screen_position, body_posture, clothing, expression, props}` + lighting/location.

---

### 4.3 Bảng bước LLM (trả lời câu hỏi riêng #1)

| Bước | Jellyfish | LocalMiniDrama | Model |
|------|-----------|----------------|-------|
| 0 Story gen | (nhập tay/chapter text) | `getStoryExpansionSystemPrompt` | text LLM user config |
| 1 Simplify | ScriptSimplifier | — | default text |
| 2 Consistency | ConsistencyChecker | — | text + thinking |
| 3 Optimize | ScriptOptimizer if issues | — | text |
| 4 Divide shots | ScriptDivider | **Storyboard system** (divide+camera cùng lúc) | text |
| 5 Extract entities | ElementExtractor | character/scene/prop extract riêng | text |
| 6 Portrait polish | CharacterPortraitAnalysis | RolePolish + IdentityAnchors | text |
| 7 Frame prompts | First/Last/Key agents | getFirst/Key/LastFrame + ImagePolish | text |
| 8 Image | asset/frame gen APIs | imageService multi-provider | image |
| 9 Video prompt | video preview/template | video_prompt / universal_segment | text optional |
| 10 Video | first_last / key modes | i2v / first-last / omni multi-ref | video |

**LLM “nào”:** Cả hai **không hardcode model** — multi-provider registry (Jellyfish `services/llm/`; LMD `ai_service_configs` + config.yaml). LMD README: 通义 / 火山 / 可灵 / Gemini / Agnes / ComfyUI local reverse-proxy.

---

## 5. Vòng QA / retry / repair

### Jellyfish

| Layer | Detect | Repair | Budget |
|-------|--------|--------|--------|
| JSON parse divider | list / wrapped keys | `_normalize` index/shot_name | 1 parse path |
| Extract cache | same division hash | skip re-LLM | cache key |
| Frame prompt QA | empty; has 图片说明; missing lead name | `retry_guidance` re-run agent | typically 1 retry path in task runner |
| Fuzzy portrait | 信息不详… in optimized | strip sentences | postprocess |
| Ready gate | pending candidates | human must link/ignore | hard block gen |
| Task | Celery/async timeout | cancel + task center | 900–1800s per task kind |

### LocalMiniDrama

| Layer | Detect | Repair | Budget |
|-------|--------|--------|--------|
| Storyboard JSON truncated | parseMeta.truncated | **auto continuation up to 3** | 3 cont (`episodeStoryboardService.js:966`) |
| max_tokens rejected | API error | retry without max_tokens | 1 |
| Image upload | fail | retry ≤3 (`uploadService`) | 3 |
| One-click pipeline | step fail | README: max 3 retries / step | 3 |
| Omni polish | stagnation | force rephrase (`getUniversalOmniPolishPrompt`) | user click N |
| Video URL invalid | non-http result | mark failed | — |
| FFmpeg normalize | aspect jump | pad+scale; skip if no ffmpeg | soft |

**Không có** vision-QA “cùng mặt không?” — consistency dựa pipeline + human re-roll.

---

## 6. Tích hợp video-gen

### Jellyfish

- Modes (`generation/video/build_context.py:10-17`):

```python
REQUIRED_FRAMES_BY_MODE = {
  "first": (first,),
  "last": (last,),
  "key": (key,),
  "first_last": (first, last),
  "first_last_key": (first, last, key),
  "text_only": (),
}
```

- Resolve images from `ShotFrameImage` by type; exact count enforced.
- Providers: OpenAI-compatible + Volcengine integrations under `core/integrations/`.
- Task manager: status, cancel, links back to project/chapter/shot.
- **Audio/TTS:** schema `start_time_sec` cho “对口型/字幕” future (`schemas/skills/common.py:44`) — **chưa pipeline TTS**.

### LocalMiniDrama

- Providers: Kling (incl Omni), Volcengine Seedance 1.x/2.0, Tongyi, Vidu, Agnes, Jimeng, Grok, v.v. (`videoClient.js`, README).
- Inputs: single image / first+last / `reference_image_urls[]` for omni.
- Post: download local; **ffmpeg normalize aspect** (`videoService.js:158-197`); episode **video merge**.
- Narration post: SRT + atempo fit + burn subtitles (`narrationVideoPostProcess.js`).
- Tail-frame link service between consecutive shots (`tailFrameLinkService.js`).

---

## 7. Pacing / timing / thoại

### Jellyfish

- `ShotDetail.duration` = **SSOT seconds**.
- Extract gợi ý duration + action_beats; frame agent pick beat phase theo first/key/last.
- Dialogue: multi-line structured; **không multi-voice TTS, không lip-sync, không subtitle burn**.
- Video model tự “nói” nếu prompt chứa thoại (phụ thuộc provider) — không kiểm soát.

### LocalMiniDrama

- Project: total duration + storyboard count + optional **per-clip duration** → inject into user prompt (`episodeStoryboardService.js:1200-1213`).
- Per-shot `duration` field; internal multi-cut trong 1 storyboard entry (5–15s AI clips).
- **Dynamic camera ≥80%** (prompt rule) → pacing cảm giác “drama”, tránh static.
- **Dialogue TTS**: MiniMax / OpenAI-compatible (`ttsService.js`); per-storyboard `audio_local_path`.
- **Narration TTS** riêng `narration_audio_local_path`; fit to slot with atempo; **SRT burn**.
- `voice_style` trên character — gợi ý, **không true multi-voice casting per line** (batch TTS dùng config voice_id, override optional).
- **Lip-sync:** prompt yêu cầu “口型同步” trong sound_effect / omni dialogue quotes — **không có Wav2Lip/SyncNet**. Phụ thuộc model video (Seedance/Kling) diễn đạt miệng.

### Map OmniCast

- OmniCast có TTS neural + FFmpeg render — mạnh hơn LMD về voice pipeline.
- Thiếu: structured dialogue lines per shot + speaker binding; drama multi-speaker assignment; optional subtitle burn for narration mode.

---

## 8. Chi tiết nhỏ đáng học

1. **Tách base prompt vs rendered prompt** (Jellyfish) — agent cấm `图N`; code compose mapping.
2. **PreparationState API** — một response sau link/ignore (`shot-status-flow.md:217-245`) → frontend không tự đoán.
3. **skip_extraction** — escape hatch cho shot hand-crafted.
4. **Actor ≠ Character** — tái dùng “diễn viên” across characters/costumes (Jellyfish).
5. **Name existence check API** — encourage reuse, giảm duplicate cast.
6. **layout_description + realistic scale contract** (LMD) — giảm prop giant / anachronism.
7. **First-frame as layout lock ref for last** (LMD imageService).
8. **@图片N never @姓名** for omni (LMD) — khớp binding token.
9. **Storyboard continuation on truncate** (LMD) — critical for long episodes.
10. **Canvas workflow** (LMD) — vertical pipeline node per shot; batch re-run group.
11. **Prompt overrides table** (LMD migrate 10) — 9 loại prompt user editable.
12. **Video aspect normalize ffmpeg** (LMD) — tránh jump khi merge multi-provider.
13. **Emotion intensity arrows** 3/2/1/0/-1 (LMD storyboard) — rhythm cue.
14. **segment_index / segment_title** — narrative beats grouping.
15. **File usages / task links** (Jellyfish) — trace asset provenance.

---

## 9. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện | Gap OmniCast | File đích gợi ý | Impact | Effort |
|---|-----------|--------------|-----------------|--------|--------|
| 1 | Candidate confirm → ready gate | Extract → gen không human gate UX | `storyboard/` + API + `/storyboard` UI | Tránh sai cast trước khi tốn Veo $ | M |
| 2 | Base vs rendered prompt split | binding có, frame agents chưa cấm token như Jellyfish | `binding.py`, frame prompt builders | Giảm token drift | S |
| 3 | 图N / @图片1=scene only | RefRole identity/env — enforce order scene-first | `binding.py`, `veo_pipeline.py` | Consistency multi-ref | S–M |
| 4 | Identity anchors 6-layer Hex | Entity appearance free text | `models` / `refsheet.py` + extract | Ổn định face khi model yếu | M |
| 5 | Industrial character sheet prompt | refsheet simpler | `refsheet.py` + image gen | Ảnh chuẩn cast | M |
| 6 | layout_description spatial contract | continuity gate layout-ish | `continuity.py` + Shot model | Standing flip ↓ | M |
| 7 | continuity_snapshot clothing/posture | chưa cross-shot snapshot | `continuity.py` | Wardrobe drift ↓ | M |
| 8 | Cấm clothing text khi có ref | RefRole clauses partial | `binding.py` ignore clauses | Face/outfit conflict ↓ | S |
| 9 | action_beats 2–4 + frame phase pick | beats/animatic có, chưa frame-phase | `animatic.py`, frame prompts | Keyframe đúng climax | S |
| 10 | first_last video mode | Veo/Flow first-last incomplete | `media/veo_pipeline.py` | Motion control | M–L |
| 11 | ShotDialogLine speaker/target | chưa drama multi-line | storyboard models + TTS router | Multi-voice drama | L |
| 12 | Narration + SRT burn path | YouTube VO strong; drama sub optional | render + TTS | Short-drama mode | M |
| 13 | UI prep page vs gen studio | `/storyboard` monolithic risk | frontend storyboard routes | Operator clarity | M |
| 14 | Prompt override store | hard-coded prompts | vault prompt_templates | A/B craft | S |
| 15 | Truncation continuation | long extract may truncate | `extract.py` | Completeness | S |
| 16 | Emotion intensity / segment grouping | pacing weaker | extract schema | Rhythm | S |

**Ưu tiên WS1 ngắn hạn:** #2, #3, #8, #1 (UX light), #6 — impact consistency cao, effort ≤M.

---

## 10. KHÔNG nên học + LICENSE

### Anti-patterns

| Anti-pattern | Repo | Lý do |
|--------------|------|-------|
| Hardcode “fixed lens ≤20%” for **all** niches | LMD | Explainer/YouTube static B-roll khác short drama |
| Character portrait **hallucinate** age/face khi thiếu info | Jellyfish portrait agent | OmniCast fail-closed / VERBATIM names — cẩn trọng conservative fill |
| Một voice TTS cho mọi character | LMD default | Multi-cast drama cần voice map |
| “Lip-sync” chỉ bằng prompt | cả hai | User expect thật → under-deliver |
| EntityMerger phức tạp trước khi có human confirm | Jellyfish legacy path | ElementExtractor + candidates đủ cho MVP |
| ComfyUI local as default identity | LMD docs | Ops nặng; OmniCast ưu tiên cloud+ref |
| BGM per-shot design | LMD forbids intentionally | Đúng — OmniCast giữ BGM track-level |

### LICENSE

| Repo | License | Sao chép code? |
|------|---------|----------------|
| **Jellyfish** | **Apache-2.0** (`LICENSE`) | **OK** (giữ notice, NOTICE nếu có) |
| **LocalMiniDrama** | **MIT** (`LICENSE`, Copyright 2026 xuanyustudio) | **OK** (giữ copyright notice) |

Cả hai **được phép học concept + chép có attribution** — không AGPL.

---

## 11. Câu hỏi riêng (brief) — trả lời trực tiếp

### 11.1 Pipeline kịch bản → 分镜 → shot

**Jellyfish (multi-step, human mid-gate):**  
Simplify? → Consistency? → Optimize? → **Divide** → **Extract** (entities+dialogue+semantic) → **User confirm** → Frame prompts → Images → Video.

**LocalMiniDrama (asset-first then board):**  
Story expand → Characters (+anchors+sheet) → Scenes → Props → **Storyboard one-shot LLM** (camera+dialogue+layout) → Frame prompts → Images → Video → Merge (+ optional TTS/SRT).

Prompts: §4 VERBATIM.

### 11.2 Quản lý nhân vật (đối chiếu cast-registry + RefRole)

| | Jellyfish | LocalMiniDrama | OmniCast |
|--|-----------|----------------|----------|
| Card fields | name, description, style, visual_style, actor_id, costume_id, props | name, role, appearance, description, personality, voice_style, identity_anchors, polished_prompt, negative_prompt | Entity + refsheet |
| Ảnh chuẩn | Actor multi-view; Character = actor face + costume ref | Industrial sheet / four_view; local_path | Ordered refs |
| Gắn shot | ShotCharacterLink.index | characters JSON IDs order | binding ordered + RefRole |
| Token | 图N + name replace | @图片N / “参考图中的人物形象” | [IMAGE n] + role clause |

**Học:** (1) Actor/Costume tách như Jellyfish **hoặc** anchors+sheet như LMD — OmniCast có thể **kết hợp**: Entity.identity_anchors + RefRole + industrial sheet gen. (2) **Order = binding contract** bắt buộc scene slot 1.

### 11.3 Drama pacing / thoại / lip-sync / subtitle

- **Jellyfish:** structured dialogue lines; no TTS/subtitle/lip-sync productized.
- **LMD:** dialogue + narration TTS; SRT burn narration; multi-voice weak; lip-sync = model-side only.
- **OmniCast:** keep neural TTS; add speaker-tagged lines + optional dual tracks; don't promise lip-sync unless tool.

### 11.4 LocalMiniDrama “local” — model gì, consistency khi yếu

- **Local** = **data/runtime local** (SQLite, Electron), **không** = offline LLM. Model = user API (cloud) hoặc ComfyUI/WebUI reverse-proxy.
- Consistency khi model yếu: **ref image > text**; **cấm viết face/clothes trong shot prompt**; Hex anchors; layout lock; first-frame ref for last; omni `@图片N` ordered; human re-gen.

### 11.5 UI workflow Jellyfish → học cho `/storyboard`

```text
ChapterShotEditPage (prep)
  extract → asset candidates → dialogue candidates
  basic info / camera / skip_extraction
  until status=ready + preparation-state.ready_for_generation
       ↓
ChapterStudio (gen)
  video-readiness panel
  keyframe/ref images
  batch toolbar
  generate video
```

**Cho OmniCast `/storyboard`:**

1. **Hai mode rõ:** “Chuẩn bị cast & shot” vs “Sinh media” (tab hoặc route con).
2. **Checklist pending candidates** trước unlock gen (dù backend fail-closed).
3. **Prep mutation returns aggregated state** — đừng client tự đếm.
4. **Diagnosis panel** trên gen view (thiếu ref, thiếu duration) — xem `ChapterStudioReadinessDiagnosisPanel`.
5. **Không trộn** edit script division với re-roll video trên cùng form dense.

---

## 12. Ma trận so sánh nhanh

| Tiêu chí | Jellyfish | LocalMiniDrama | Winner cho OmniCast |
|----------|-----------|----------------|---------------------|
| Production-grade workflow | ★★★★★ | ★★★ | Jellyfish |
| Consistency tricks khi model yếu | ★★★ | ★★★★★ | LMD |
| Prompt craft depth | ★★★★ | ★★★★★ | LMD |
| Cast data model elegance | ★★★★★ Actor+Costume | ★★★ flat | Jellyfish |
| Desktop/local privacy | ★★ | ★★★★★ | LMD concept |
| TTS/subtitle | ★ | ★★★★ | LMD |
| OpenAPI/task infra | ★★★★★ | ★★★ | Jellyfish |
| Canvas UX | — | ★★★★★ | LMD inspiration |
| License friendliness | Apache-2.0 | MIT | Both OK |

---

---

## ROUND 2 — VERBATIM FULL (theo VERIFY §4.3)

> Vá E1/E4/V6/V7 + chép đủ các file VERIFY §4.3 yêu cầu. **CẤM ellipsis `…` trong khối verbatim dưới đây.**
> Số file/khối chép full: **7** (element_extractor, entity_merger, variant_analyzer, shot_frame_prompt_agents template, getStoryboardSystemPrompt zh+en, universalSegmentPromptBundle.js, getRolePolishPrompt).

### R2.1 Jellyfish — `element_extractor_agent.py` (system + user PromptTemplate)

Nguồn: `_refs/Jellyfish/backend/app/chains/agents/element_extractor_agent.py`

```python
_SCRIPT_EXTRACTOR_SYSTEM_PROMPT = """\
你是\"Studio 信息提取员\"。你的任务是：基于分镜结果（以及可选的一致性检查输出），输出可直接导入 Studio 的草稿结构 StudioScriptExtractionDraft（注意：ID 由导入 API 生成，因此这里全部使用 name 做引用键）。

输出 StudioScriptExtractionDraft：
- project_id（必填）
- chapter_id（必填）
- characters: [{name, description, costume_name?, prop_names[], tags[]}]
- scenes/props/costumes: [{name, description, tags[], prompt_template_id?, view_count}]
- shots: [{index, title, script_excerpt, scene_name?, character_names[], prop_names[], costume_names[], dialogue_lines[], actions[], semantic_suggestion?}]
  - dialogue_lines: [{index, text, line_mode, speaker_name?, target_name?}]
  - semantic_suggestion: {camera_shot?, angle?, movement?, duration?, action_beats[], notes?}

强约束：
- 同名实体在输出中只出现一次（全局去重）；shots 中引用必须使用同一名称
- shots.index 必须覆盖并对应输入分镜中的 index（不要跳号）
- 不要输出任何 id 字段（包括 char_001 等），由导入 API 生成

一致性强约束（必须严格遵守，否则导入会失败）：
- 先输出全局 characters/scenes/props/costumes 列表，再输出 shots；并把它们视为“字典”。
- shots[*].character_names / prop_names / costume_names / scene_name 只能从对应全局列表的 name 中选择（完全一致的字符串），禁止生成任何未在全局列表中出现的新名字。
- 禁止“同义名/括号变体/临时称呼”漂移：例如禁止在 shots 中写「女子（群）」但在 characters 中没有该条目；禁止「仙女A」与「仙女 A」混用。
- 遇到群体角色/泛指角色（如“女子（群）”“群众”“村民们”）：必须在 characters 列表中创建一条同名角色（name 完全一致），并在 shots 中引用该 name。
- 对于难以确定是否同一角色的称呼：宁可在 characters 里拆成两条不同 name，也不要在 shots 中凭空换名。
- 输出 shots 之前，必须做“全集校验”并补齐缺失：所有 shots[*] 中出现的 character_names/prop_names/costume_names/scene_name 的名字集合，必须都能在对应全局列表（characters/props/costumes/scenes）的 name 中找到；如果有缺失，必须在全局列表中补齐对应条目（描述可最小化，但 name 必须完全一致），禁止用别名替换来绕过。
- 角色名/场景名必须原样保留字符细节：包括全角/半角括号、空格、标点，不要自动做任何规范化或替换（例如不能把「女子（群）」改成「女子(群)」或「女子 （群）」）。
- 严格区分：shots[*].title 是“镜头标题”（一句话描述该镜头画面/动作），不要拿它当作 scenes 的 scene 名；shots[*].scene_name 才是场景名称，必须来自 scenes 全局列表的 name。
- 除实体与对白外，还必须尽量补充镜头语言默认建议：`camera_shot` / `angle` / `movement` / `duration`。
- `camera_shot` 只能输出：ECU / CU / MCU / MS / MLS / LS / ELS。
- `angle` 只能输出：EYE_LEVEL / HIGH_ANGLE / LOW_ANGLE / BIRD_EYE / DUTCH / OVER_SHOULDER。
- `movement` 只能输出：STATIC / PAN / TILT / DOLLY_IN / DOLLY_OUT / TRACK / CRANE / HANDHELD / STEADICAM / ZOOM_IN / ZOOM_OUT。
- `duration` 必须输出正整数秒数；若无法判断，可省略。
- `action_beats` 需要输出 2-4 条按镜头内部时间顺序排列的动作拍点；每一条只描述一个主要动作或状态变化，不要写成长段文学描述。
- `semantic_suggestion` 是“镜头默认语义建议”，不是最终生成提示词，不要输出提示词式修饰文本。

输入：
- project_id
- chapter_id
- script_division_json（ScriptDivisionResult）
- consistency_json（可选）

只输出 JSON。"""

SCRIPT_EXTRACTOR_PROMPT = PromptTemplate(
    input_variables=["project_id", "chapter_id", "script_division_json", "consistency_json"],
    template=(
        "## project_id\n{project_id}\n\n"
        "## chapter_id\n{chapter_id}\n\n"
        "## 一致性检查（可选）\n{consistency_json}\n\n"
        "## 分镜结果\n{script_division_json}\n\n"
        "## 输出\n"
    ),
)

```

### R2.2 Jellyfish — `entity_merger_agent.py` (system + user PromptTemplate)

Nguồn: `_refs/Jellyfish/backend/app/chains/agents/entity_merger_agent.py`

```python
_ENTITY_MERGER_SYSTEM_PROMPT = """\
你是\"实体合并师\"。合并多镜头提取结果，统一实体定义，为每个实体分配ID，识别变体和冲突。
请输出 EntityMergeResult，merged_library 中至少包含 characters/locations/scenes/props 四类。
每个实体条目（EntityEntry）需包含：
- 通用：id/name/type/description/aliases/normalized_name/confidence/first_appearance/evidence/first_shot/appearances/variants
- 角色（type=character）：尽量补充 costume_note、traits
- 地点（type=location）：尽量补充 location_type
- 道具（type=prop）：尽量补充 category、owner_character_id
variants 使用 {variant_key, description, affected_shots, evidence} 的最小结构。
当提供 previous_merge_json 与 conflict_resolutions_json 时，表示这是一次“重试合并”：你必须参考上一次的合并结果与冲突解决建议，优先消解 conflicts；必要时可调整实体合并/拆分策略，但要保持 ID 尽量稳定（除非建议明确要求变更）。
只输出 JSON，符合 EntityMergeResult 结构。"""

ENTITY_MERGER_PROMPT = PromptTemplate(
    input_variables=[
        "all_extractions_json",
        "historical_library_json",
        "script_division_json",
        "previous_merge_json",
        "conflict_resolutions_json",
    ],
    template=(
        "## 脚本分镜(来自上一步)\n{script_division_json}\n\n"
        "## 所有镜头提取结果\n{all_extractions_json}\n\n"
        "## 历史实体库\n{historical_library_json}\n\n"
        "## 上一次合并结果（可选，用于重试）\n{previous_merge_json}\n\n"
        "## 冲突解决建议（可选，用于重试）\n{conflict_resolutions_json}\n\n"
        "## 输出\n"
    ),
)

```

### R2.3 Jellyfish — `variant_analyzer_agent.py` (system + user PromptTemplate)

Nguồn: `_refs/Jellyfish/backend/app/chains/agents/variant_analyzer_agent.py`

```python
_VARIANT_ANALYZER_SYSTEM_PROMPT = """\
你是\"变体分析师\"。分析实体变体（特别是角色服装变化），构建时间线，生成变体建议。
输出 VariantAnalysisResult：costume_timelines.timeline_entries 使用 {shot_index, scene_id, costume_note, changes, evidence}；variant_suggestions 可带 evidence。
只输出 JSON，符合 VariantAnalysisResult 结构。"""

VARIANT_ANALYZER_PROMPT = PromptTemplate(
    input_variables=["merged_library_json", "all_extractions_json", "script_division_json"],
    template=(
        "## 脚本分镜(来自上一步)\n{script_division_json}\n\n"
        "## 合并后的实体库\n{merged_library_json}\n\n"
        "## 所有镜头提取结果\n{all_extractions_json}\n\n"
        "## 输出\n"
    ),
)

```

### R2.4 Jellyfish — `shot_frame_prompt_agents.py` (`_FRAME_FOCUS` + `_SHOT_FRAME_TEMPLATE`)

Nguồn: `_refs/Jellyfish/backend/app/chains/agents/shot_frame_prompt_agents.py:109-181`

Runtime builds three templates by replacing `{frame_name}` / `{frame_focus}` for 首帧 / 尾帧 / 关键帧 (`_build_frame_template`).

```python
_FRAME_FOCUS = {

    "首帧": "优先描述镜头开始时最先看到的画面建立信息，强调开场定场、主体初始状态与进入情境的第一印象；只表现触发瞬间或最初反应，不要直接写成后续完成动作、最终姿态或情绪爆发完成态。",
    "尾帧": "优先描述镜头结束时最终停留的画面状态，强调动作收束、人物结束姿态、视线落点或情绪余韵。",
    "关键帧": "优先捕捉镜头中最具代表性、最有戏剧张力或信息密度最高的瞬间，不必平均描述整个过程。",
}

_SHOT_FRAME_TEMPLATE = """你是一名专业影视分镜提示词设计师，需要为同一项目中的镜头生成**{frame_name}基础提示词**。

你的任务是生成“基础提示词”，只描述画面本身，供后续系统继续拼接图片映射说明。

## 强约束
1. 必须继承项目级画面表现形式与题材风格：{visual_style} / {style}
2. 项目是否要求统一风格：{unify_style}
3. 若镜头信息不足，优先向项目风格与已确认实体设定收敛，不要自由发散到其他风格
4. 当前镜头已确认的角色、场景、道具、服装名称必须原样保留，不得翻译、不得改名、不得替换为同义词
5. 不得输出“图1/图2”、不得输出“## 图片内容说明”、不得输出引用映射说明
6. 输出应为一句或几句简洁、可视化、可直接用于图像生成模型的中文描述
7. 尽量保持统一描述口径，优先按“景别/机位/运镜 -> 场景环境 -> 主体人物/关键对象 -> 动作状态 -> 氛围情绪 -> 风格收束”组织
8. 只输出一个 JSON 对象：{{"prompt": "你的提示词内容"}}，不要输出其他文字
9. 当前帧关注重点：{frame_focus}
10. 主体优先级建议：{subject_priority}
11. 不要为了“写全信息”而平均罗列所有角色、道具、服装；优先突出主角色、主场景和主动作，其余元素仅在能强化当前画面时再进入提示词
12. 如果下面提供了“修正要求”，必须逐条满足后再输出最终结果
13. 若存在上一镜头信息，当前画面应尽量承接上一镜头的动作、空间方向、视线或情绪，不要像全新场景重新开局
14. 若存在下一镜头信息，当前画面应为下一镜头留下自然的动作或情绪收束，避免硬切
15. 尽量明确主体在画面中的相对位置、朝向与动作峰值，减少构图和轴线突变
16. 若提供了构图与空间锚点建议，应尽量落实到画面描述中，让主体位置、环境重心和空间方向更稳定
17. 若提供了朝向与视线建议，应保持人物左右关系、视线落点与反打轴线稳定，不要无故翻转
18. 若提供了当前帧专项建议，应优先满足该建议，确保首帧/关键帧/尾帧各自承担清晰职责
19. 若提供了导演指令摘要，应将其视为最高优先级的镜头执行约束，优先体现到最终画面描述中
20. 若当前为首帧，只能表现事件触发瞬间或最初反应，不要直接把后续完成动作、最终姿态或情绪爆发结果写进画面
21. 若当前为首帧且镜头存在连续动作链，应优先使用“刚开始 / 尚未完成 / 被打断”的未完成态表达，而不是结果态表达

## 镜头信息
剧本摘录：{script_excerpt}
镜头标题：{title}
镜头补充描述：{shot_description}
景别：{camera_shot}
机位角度：{angle}
运镜：{movement}
氛围：{atmosphere}
情绪标签：{mood_tags}
视效：{vfx_type} - {vfx_note}
时长：{duration}秒
对白摘要：{dialog_summary}
动作拍点：{action_beats}
动作拍点阶段：{action_beat_phases}
当前帧优先消费阶段：{selected_action_beat_phase}
当前帧主拍点：{selected_action_beat_text}

## 已确认实体上下文
角色：{character_context}
场景：{scene_context}
道具：{prop_context}
服装：{costume_context}

## 相邻镜头承接信息
上一镜头标题：{previous_shot_title}
上一镜头剧本摘录：{previous_shot_script_excerpt}
上一镜头结尾状态：{previous_shot_end_state}
下一镜头标题：{next_shot_title}
下一镜头剧本摘录：{next_shot_script_excerpt}
下一镜头起始目标：{next_shot_start_goal}
连续性建议：{continuity_guidance}
构图与空间锚点：{composition_anchor}
朝向与视线建议：{screen_direction_guidance}
当前帧专项建议：{frame_specific_guidance}
导演指令摘要：{director_command_summary}

修正要求：{retry_guidance}

## 输出（仅 {frame_name} 基础提示词，JSON：{{"prompt": "..."}}）
"""
```

### R2.5 LocalMiniDrama — `getStoryboardSystemPrompt` full function (en + zh)

Nguồn: `_refs/LocalMiniDrama/backend-node/src/services/promptI18n.js` — function `getStoryboardSystemPrompt` (từ khai báo đến trước `getUniversalOmniMultiBeatFormatSpec`).

```javascript
function getStoryboardSystemPrompt(cfg) {
  if (isEnglish(cfg)) {
    return `[Role] You are a senior film storyboard artist, proficient in Robert McKee's shot breakdown theory, skilled at building emotional rhythm.

[Task] Break down the novel script into storyboard shots based on **independent action units**.

[Shot Breakdown Principles]
1. **Action Unit Division**: Each storyboard shot corresponds to a **narrative beat**, and may contain 1-4 rapid internal cuts (described in the style of "Shot 1 ... Cut to Shot 2 ...") to fully utilize AI video clips of 5-15 seconds, avoiding excessive short clips caused by the old "one action per shot" rule that wastes generation time.
   - Ideal for merging character power awakening, quick reactions, or continuous actions into one storyboard entry connected by internal cuts
   - Only split into separate shots when there are clear pauses, scene changes, or narrative reasons for independent presentation
   - Traditional storyboard prompt style (with multi-shot cut descriptions) is fully supported

2. **Shot Type Standards** (choose based on storytelling needs):
   - Extreme Long Shot (ELS): Environment, atmosphere building
   - Long Shot (LS): Full body action, spatial relationships
   - Medium Shot (MS): Interactive dialogue, emotional communication
   - Close-Up (CU): Detail display, emotional expression
   - Extreme Close-Up (ECU): Key props, intense emotions

3. **Camera Movement Requirements**（**Dynamic Priority Mandatory**）:
   - 【Core Rule】: Every video segment MUST use **dynamic camera movement**. **Static/fixed shots shall not exceed 20%**. Prioritize push/pull/pan/tilt/track/crane/orbit/whip/roll/zoom.
   - Basic movements:
     * Push In: Forward approach, builds tension/intimacy
     * Pull Out: Backward reveal, shows environment or emotional release
     * Pan: Horizontal rotation, spatial reveal or lateral following
     * Tilt: Vertical rotation, height reveal or emotional rise/fall
     * Tracking/Follow: Camera follows subject, keeps subject framed
     * Crane Up: Ascending boom, grandeur or liberation
     * Crane Down: Descending boom, oppression or weight
     * Orbit: 360° circling around subject,立体 spatial depth
     * Handheld: Slight shake, realism/tension
   - Advanced movements:
     * Zoom: Optical zoom in/out without moving camera position
     * Roll: Rotation along lens axis, vertigo or weightlessness
     * Whip Pan: Rapid whip pan, temporal jump or chaos
     * Spiral: Ascend/descend while orbiting, dreamlike or crushing
   - Cinematic compound shots (use based on emotion):
     * Hitchcock Zoom (hitchcock_zoom): Push + zoom out (or reverse), spatial distortion vertigo, expresses terror/disorientation
     * Bullet Time (bullet_time): Orbit + slow-motion, subject ultra-slow, background spins fast, captures peak dramatic moment
     * Dutch Angle + Move (dutch_angle_move): Tilted frame + pan/orbit, mental breakdown/world collapse
     * Dolly + Track (dolly_track): Push + lateral move, complex emotional progression
     * Slow-mo Orbit (slowmo_orbit): Slow-motion circling, time-freezing dramatic instant

4. **Emotion & Intensity Markers**:
   - Emotion: Brief description (excited, sad, nervous, happy, etc.)
   - Intensity: Emotion level using arrows
     * Extremely strong ↑↑↑ (3): Emotional peak, high tension
     * Strong ↑↑ (2): Significant emotional fluctuation
     * Moderate ↑ (1): Noticeable emotional change
     * Stable → (0): Emotion remains unchanged
     * Weak ↓ (-1): Emotion subsiding

5. **Narrative Segment Grouping**:
   - Group consecutive shots into named narrative segments (e.g., "Arrival", "Confrontation", "Resolution")
   - Each segment = a coherent dramatic beat or scene transition
   - Segment rules:
     * 1–3 segments for short scripts (≤10 shots)
     * 3–6 segments for medium scripts (10–30 shots)
     * Shot count per segment: suggest 3–8 shots (avoid 1-shot segments unless a major turning point)
     * Opening shots: wide/establishing, closing shots: close-up/reaction to cap the beat

[Output Requirements]
1. Return a JSON array. Each element is one shot object containing ALL of the following fields:
   - shot_number: Shot number (integer, starting from 1)
   - title: Shot title (3–8 words, concise summary of this shot's key action or visual, e.g., "Lin Wei Enters the Room", "Tense Eye Contact")
   - segment_index: Segment index (0-based integer, e.g., 0, 1, 2…)
   - segment_title: Segment name (short 2–6 words, e.g., "Chance Encounter", "Hidden Truth Revealed")
   - location: Location name (e.g., "bedroom interior", "rooftop", "hospital corridor")
   - time: Time of day (e.g., "morning", "dusk", "night", "afternoon")
   - shot_type: Shot type (extreme long shot/long shot/medium shot/close-up/extreme close-up)
   - camera_angle: Camera angle (eye-level/low-angle/high-angle/side/back)
   - camera_movement: Camera movement — MUST be one of: static, push, pull, pan, tilt, tracking, crane_up, crane_dn, orbit, handheld, zoom, roll, whip_pan, spiral, hitchcock_zoom, bullet_time, dutch_angle_move, dolly_track, slowmo_orbit (prefer dynamic over static)
   - lighting_style: Lighting style — choose ONE: natural/front/side/backlit/top/under/soft/dramatic/golden_hour/blue_hour/night/neon
   - depth_of_field: Depth of field — choose ONE: extreme_shallow/shallow/medium/deep (close-up → shallow/extreme_shallow; wide shot → deep)
   - action: Action description
   - result: Visual result of the action
   - dialogue: Character dialogue or narration (if any)
   - emotion: Current emotion
   - emotion_intensity: Emotion intensity level (3/2/1/0/-1)

**CRITICAL: Return ONLY a valid JSON array. Do NOT include any markdown code blocks, explanations, or other text. Start directly with [ and end with ].**

[Important Notes]
- Shot count should match the number of **narrative beats** in the script (merging rapid consecutive actions with internal cuts inside a single storyboard entry is encouraged to optimize AI video duration)
- Each shot must have clear title, action (which may include multi-cut descriptions), result
- Shot types must match storytelling rhythm (don't use same shot type continuously)
- Emotion intensity must accurately reflect script atmosphere changes
- segment_index must be sequential integers starting from 0; all shots in the same segment share the same index and title`;
  }
  const _sbOverride = _overrideCache['storyboard_system'];
  if (_sbOverride) {
    return _sbOverride + '\n\n**重要：必须只返回纯JSON数组，不要包含任何markdown代码块、说明文字或其他内容。直接以 [ 开头，以 ] 结尾。**\n\n【重要提示】\n- 镜头数量必须与剧本中的独立动作数量匹配（不允许合并或减少）\n- 每个镜头必须有明确的动作和结果\n- 景别选择必须符合叙事节奏（不要连续使用同一景别）\n- 情绪强度必须准确反映剧本氛围变化';
  }
  return `【角色】你是一位资深影视分镜师，精通罗伯特·麦基的镜头拆解理论，擅长构建情绪节奏。

【任务】将小说剧本按**独立动作单元**拆解为分镜头方案。

【分镜拆解原则】
1. **动作单元划分**：每个分镜对应一个**叙事节拍**，允许包含1-4个快速连续的内部切镜（使用“镜头1 ... 切镜到镜头2 ...”风格描述），以充分利用AI视频至少5秒、最长可达15秒的时长，避免因“一个镜头一个动作”导致产生过多短时长片段造成时间浪费。
   - 适合将角色能量觉醒、快速反应、连续动作等合并在一个分镜内，用内部切镜串联
   - 仅当动作间有明显停顿、场景切换或叙事需要独立呈现时，才拆分为多个分镜
   - 传统分镜风格的提示词（含多镜头切镜描述）同样支持

2. **景别标准**（根据叙事需要选择）：
   - 大远景：环境、氛围营造
   - 远景：全身动作、空间关系
   - 中景：交互对话、情感交流
   - 近景：细节展示、情绪表达
   - 特写：关键道具、强烈情绪

3. **运镜要求**（**强制动态优先**）：
   - 【运镜总原则】：每段视频必须使用**动态运镜**，**固定镜头不得超过20%**。优先选择推/拉/摇/跟/升/降/环绕/甩/旋转/变焦等运动镜头。
   - 基础运镜：
     * 推镜（push）：镜头向前推进，增强紧张/亲密感
     * 拉镜（pull）：镜头向后拉开，揭示环境或情绪回落
     * 横摇（pan）：水平旋转摄像机，展现空间或跟随横向动作
     * 纵摇（tilt）：垂直旋转摄像机，展现高度或情绪起伏
     * 跟镜/跟踪（tracking）：摄像机跟随主体移动，保持主体在画框内
     * 升镜（crane_up）：吊臂上升，展现宏大或解放感
     * 降镜（crane_dn）：吊臂下降，压迫或沉重感
     * 环绕（orbit）：绕主体360°运动，展现立体空间
     * 手持（handheld）：轻微晃动，增加真实/紧张感
   - 进阶运镜：
     * 变焦（zoom）：光学变焦推进或拉远，不移动机位
     * 旋转/滚镜（roll）：镜头沿光轴旋转，制造眩晕/失重
     * 甩镜（whip_pan）：快速急摇，制造时空跳转或混乱感
     * 螺旋（spiral）：边升/降边环绕，梦幻或压迫感
   - 电影化组合镜头（根据剧情情绪选用）：
     * 希区柯克镜头（hitchcock_zoom）：向前推+变焦拉远（或反向），制造空间扭曲的眩晕感，表现惊恐/错乱
     * 子弹时间（bullet_time）：环绕+升格（slow-motion），主体动作极缓，背景高速旋转，表现关键高能时刻
     * 荷兰角+运镜（dutch_angle_move）：倾斜构图+横摇/环绕，表现精神错乱/世界崩塌
     * 推轨复合（dolly_track）：推镜+横向移动，复杂情绪递进
     * 升格环绕（slowmo_orbit）：慢动作环绕，时间凝固的戏剧性时刻

4. **情绪与强度标记**：
   - emotion：简短描述（兴奋、悲伤、紧张、愉快等）
   - emotion_intensity：用箭头表示情绪等级
     * 极强 ↑↑↑ (3)：情绪高峰、高度紧张
     * 强 ↑↑ (2)：情绪明显波动
     * 中 ↑ (1)：情绪有所变化
     * 平稳 → (0)：情绪不变
     * 弱 ↓ (-1)：情绪回落

5. **叙事段落分组**：
   - 将连续镜头归组为命名段落（如"邂逅"、"矛盾激化"、"和解"）
   - 每个段落 = 一个连贯的戏剧节拍或场景切换
   - 分组规则：
     * 短剧本（≤10个镜头）：1–3个段落
     * 中等剧本（10–30个镜头）：3–6个段落
     * 每段建议3–8个镜头，避免1镜头单独成段（除非是重大转折点）
     * 段落开篇用大远景/远景建立环境，段落结尾用近景/特写收尾

【输出要求】
1. 返回一个JSON数组，每个元素是一个镜头对象，必须包含以下**全部**字段：
   - shot_number：镜头号（整数，从1开始）
   - title：镜头标题（3–8字，简洁概括本镜头的核心动作或视觉重点，如"林薇走进房间"、"紧张的对视"）
   - segment_index：段落索引（从0开始的整数，如 0、1、2……）
   - segment_title：段落名称（简短2–6字，如"意外相遇"、"真相大白"）
   - location：场景地点名称（如"卧室内"、"天台"、"医院走廊"）
   - time：拍摄时间（如"清晨"、"黄昏"、"夜晚"、"午后"）
   - shot_type：景别（大远景/远景/中景/近景/特写）
   - camera_angle：机位角度（平视/仰视/俯视/侧面/背面）
   - camera_movement：运镜方式（static/推镜push/拉镜pull/横摇pan/纵摇tilt/跟镜tracking/升镜crane_up/降镜crane_dn/环绕orbit/手持handheld/变焦zoom/旋转roll/甩镜whip_pan/螺旋spiral/希区柯克hitchcock_zoom/子弹时间bullet_time/荷兰角dutch_angle_move/推轨复合dolly_track/升格环绕slowmo_orbit）——**强制动态优先，固定镜头不得超过20%**
   - lighting_style：灯光风格 — 从以下选一个填入：natural/front/side/backlit/top/under/soft/dramatic/golden_hour/blue_hour/night/neon（根据 time 和 atmosphere 判断；夜晚→night，黄昏→golden_hour，室内暖光→soft，强情绪→dramatic，逆光→backlit）
   - depth_of_field：景深 — 从以下选一个填入：extreme_shallow/shallow/medium/deep（特写/近景→shallow，中景→medium，远景/大远景→deep）
   - action：动作描述
   - result：动作完成后的画面结果
   - dialogue：角色对话或旁白（如有）
   - emotion：当前情绪
   - emotion_intensity：情绪强度等级（3/2/1/0/-1）

2. **构图与视觉设计参考**（生成分镜时运用）：
   - 景别变化规律：禁止连续3个及以上镜头使用相同景别，情绪递进时逐步推近（远→中→近→特写）
   - 构图建议：三分法（稳定叙事）/ 对角线（动态张力）/ 框架构图（增加纵深）/ 中心构图（庄重仪式感）
   - 光线方向：在 atmosphere 字段中注明光源方向和色温（如"左侧冷蓝光，逆光轮廓"）
   - 对话场景：使用正反打（过肩镜头交替），避免连续同向构图

**重要：必须只返回纯JSON数组，不要包含任何markdown代码块、说明文字或其他内容。直接以 [ 开头，以 ] 结尾。**

【重要提示】
- 镜头数量应与剧本中的**叙事节拍**数量匹配（允许在单个分镜内用内部切镜合并快速连续动作，以优化AI视频时长）
- 每个分镜必须有明确的 title（标题）、action（动作）和 result（结果）；action 中可包含多镜头切镜描述
- 景别选择必须符合叙事节奏（不要连续使用同一景别）
- 情绪强度必须准确反映剧本氛围变化
- segment_index 必须从0开始递增的整数，同一段落内所有镜头共享相同的 segment_index 和 segment_title`;
}

/**
 * 全能片段描述统一格式说明（分镜批量生成 / 生成全能提示词 / 润色 共用）
 */
```

### R2.6 LocalMiniDrama — `universalSegmentPromptBundle.js` full file

Nguồn: `_refs/LocalMiniDrama/backend-node/src/services/universalSegmentPromptBundle.js`

```javascript
/**
 * 全能片段（Omni / Seedance 多图参考）用户消息构建：供「生成」与「润色」共用。
 * @param {import('better-sqlite3').Database} db
 * @param {number} sbId
 * @param {object} reqBody 可选 duration、force_without_reference_images（为 true 时不校验场景/角色/道具是否已上图，仍构建提示词）
 * @param {{ universalSegmentOverride?: string | undefined }} opts 若传入则覆盖库中的 universal 写入 CURRENT_UNIVERSAL_SEGMENT
 * @returns {{ ok:true, userPrompt:string, durationLabel:string, durationSec:number, sbId:number, episodeId:number, storyboardNumber:number } | { ok:false, code:'not_found'|'bad_request', message:string }}
 */
function buildUniversalSegmentUserPromptBundle(db, sbId, reqBody, opts = {}) {
  const bodyIn = reqBody && typeof reqBody === 'object' ? reqBody : {};
  const forceWithoutReferenceImages = !!bodyIn.force_without_reference_images;

  const sb = db.prepare(
    `SELECT id, episode_id, storyboard_number, scene_id, title, description, location, time,
      action, dialogue, narration, result, atmosphere,
      image_prompt, polished_prompt, video_prompt, universal_segment_text,
      shot_type, angle, angle_h, angle_v, angle_s, movement, lighting_style, depth_of_field,
      characters, local_path, duration, segment_index, segment_title
     FROM storyboards WHERE id = ? AND deleted_at IS NULL`
  ).get(sbId);
  if (!sb) return { ok: false, code: 'not_found', message: '分镜不存在' };

  let dramaId = null;
  let dramaRow = null;
  try {
    const epRow = db.prepare('SELECT drama_id FROM episodes WHERE id = ? AND deleted_at IS NULL').get(sb.episode_id);
    dramaId = epRow?.drama_id ?? null;
    if (dramaId) {
      dramaRow = db.prepare('SELECT title, genre, style, metadata FROM dramas WHERE id = ? AND deleted_at IS NULL').get(dramaId);
    }
  } catch (_) {}

  let styleZh = '';
  let styleEn = '';
  try {
    const loadConfig = require('../config').loadConfig;
    const { mergeCfgStyleWithDrama } = require('../utils/dramaStyleMerge');
    let cfg = loadConfig();
    cfg = mergeCfgStyleWithDrama(cfg, dramaRow || {});
    styleEn = (cfg?.style?.default_style_en || cfg?.style?.default_style || '').trim();
    styleZh = (cfg?.style?.default_style_zh || '').trim();
  } catch (_) {}

  const chunk = (k, v) => {
    const s = v != null && String(v).trim() ? String(v).trim() : '';
    return s ? `${k}: ${s}` : null;
  };

  const universalForLine =
    opts.universalSegmentOverride !== undefined ? opts.universalSegmentOverride : sb.universal_segment_text;

  const lines = [
    chunk('TITLE', sb.title),
    chunk('DESCRIPTION', sb.description),
    chunk('LOCATION', sb.location),
    chunk('TIME', sb.time),
    chunk('ACTION', sb.action),
    chunk('DIALOGUE', sb.dialogue),
    chunk('NARRATION', sb.narration),
    chunk('RESULT', sb.result),
    chunk('ATMOSPHERE', sb.atmosphere),
    chunk('IMAGE_PROMPT', sb.image_prompt),
    chunk('POLISHED_IMAGE_PROMPT', sb.polished_prompt),
    chunk('VIDEO_PROMPT', sb.video_prompt),
    chunk('SHOT_TYPE', sb.shot_type),
    chunk('ANGLE', sb.angle),
    chunk('ANGLE_H', sb.angle_h),
    chunk('ANGLE_V', sb.angle_v),
    chunk('ANGLE_S', sb.angle_s),
    chunk('MOVEMENT', sb.movement),
    chunk('LIGHTING', sb.lighting_style),
    chunk('DEPTH_OF_FIELD', sb.depth_of_field),
    chunk('CURRENT_UNIVERSAL_SEGMENT', universalForLine),
  ].filter(Boolean);

  const hasMediaRef = (row) =>
    row && (String(row.local_path || '').trim() !== '' || String(row.image_url || '').trim() !== '');

  let sceneRow = null;
  let sceneBlock = '';
  if (sb.scene_id) {
    try {
      sceneRow = db
        .prepare('SELECT location, time, prompt, image_url, local_path FROM scenes WHERE id = ? AND deleted_at IS NULL')
        .get(sb.scene_id);
      if (sceneRow) {
        const scBits = [
          chunk('SCENE_LOCATION', sceneRow.location),
          chunk('SCENE_TIME', sceneRow.time),
          chunk('SCENE_PROMPT', sceneRow.prompt),
          hasMediaRef(sceneRow) ? 'SCENE_HAS_REFERENCE_IMAGE: yes' : 'SCENE_HAS_REFERENCE_IMAGE: no',
        ].filter(Boolean);
        sceneBlock = scBits.join('\n');
      }
    } catch (_) {}
  }

  const charOrderEntries = [];
  const charKeySeen = new Set();
  const pushCharEntry = (key, nameHint) => {
    if (!key || charKeySeen.has(key)) return;
    charKeySeen.add(key);
    charOrderEntries.push({
      key,
      nameHint: nameHint != null && String(nameHint).trim() ? String(nameHint).trim() : '',
    });
  };
  /** 与前端 collectSbOmniReferenceAbsoluteUrls / 视频 API 参考图顺序一致：仅以分镜 characters JSON 的本剧角色顺序为准，避免再追加 storyboard_characters 导致槽位与界面 @图片N 错位。 */
  let charOrderFromDramaJson = false;
  try {
    if (sb.characters) {
      const parsed = JSON.parse(sb.characters);
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          const cid = typeof item === 'object' && item != null ? item.id : item;
          const idNum = Number(cid);
          if (!Number.isFinite(idNum)) continue;
          const nm =
            typeof item === 'object' && item != null && item.name != null ? String(item.name).trim() : '';
          pushCharEntry(`drama:${idNum}`, nm);
        }
        if (charOrderEntries.length > 0) charOrderFromDramaJson = true;
      }
    }
    if (!charOrderFromDramaJson) {
      const libLinks = db
        .prepare('SELECT character_id FROM storyboard_characters WHERE storyboard_id = ? ORDER BY id ASC')
        .all(sbId);
      for (const link of libLinks) {
        const lid = Number(link.character_id);
        if (!Number.isFinite(lid)) continue;
        pushCharEntry(`lib:${lid}`, '');
      }
    }
  } catch (_) {}

  const charNamesOrdered = [];
  const nameSeen = new Set();
  for (const ent of charOrderEntries) {
    let row = null;
    if (ent.key.startsWith('drama:')) {
      row = db.prepare('SELECT name FROM characters WHERE id = ? AND deleted_at IS NULL').get(Number(ent.key.slice(6)));
    } else if (ent.key.startsWith('lib:')) {
      row = db.prepare('SELECT name FROM character_libraries WHERE id = ? AND deleted_at IS NULL').get(Number(ent.key.slice(4)));
    }
    const nm = (row?.name || ent.nameHint || '').trim();
    if (nm && !nameSeen.has(nm)) {
      nameSeen.add(nm);
      charNamesOrdered.push(nm);
    }
  }
  const charNames = charNamesOrdered.join(', ');

  let propRows = [];
  try {
    propRows =
      db
        .prepare(
          `SELECT p.id, p.name, p.local_path, p.image_url FROM storyboard_props sp
         JOIN props p ON p.id = sp.prop_id AND p.deleted_at IS NULL
         WHERE sp.storyboard_id = ?
         ORDER BY sp.prop_id ASC`
        )
        .all(sbId) || [];
  } catch (_) {
    propRows = [];
  }
  const propNamesOrdered = [];
  const propSeen = new Set();
  for (const r of propRows) {
    const n = r?.name != null && String(r.name).trim() ? String(r.name).trim() : '';
    if (n && !propSeen.has(n)) {
      propSeen.add(n);
      propNamesOrdered.push(n);
    }
  }
  const propNames = propNamesOrdered;

  let prevDesc = '(first shot)';
  let nextDesc = '(last shot)';
  if (sb.episode_id != null && sb.storyboard_number != null) {
    const prevShot = db
      .prepare(
        'SELECT action, location, time FROM storyboards WHERE episode_id = ? AND storyboard_number < ? AND deleted_at IS NULL ORDER BY storyboard_number DESC LIMIT 1'
      )
      .get(sb.episode_id, sb.storyboard_number);
    const nextShot = db
      .prepare(
        'SELECT action, location, time FROM storyboards WHERE episode_id = ? AND storyboard_number > ? AND deleted_at IS NULL ORDER BY storyboard_number ASC LIMIT 1'
      )
      .get(sb.episode_id, sb.storyboard_number);
    if (prevShot) {
      prevDesc =
        (prevShot.action || [prevShot.location, prevShot.time].filter(Boolean).join(' ')).slice(0, 160).trim() ||
        '(first shot)';
    }
    if (nextShot) {
      nextDesc =
        (nextShot.action || [nextShot.location, nextShot.time].filter(Boolean).join(' ')).slice(0, 160).trim() ||
        '(last shot)';
    }
  }

  const slots = [];
  const pushSlot = (kind, summary) => {
    const num = slots.length + 1;
    const brief = String(summary || '').trim() || kind;
    slots.push({ num, tag: `@图片${num}`, kind, summary: brief });
  };
  if (sceneRow && hasMediaRef(sceneRow)) {
    pushSlot('场景', String(sceneRow.location || '').trim() || '场景环境');
  }
  for (const ent of charOrderEntries) {
    let row = null;
    if (ent.key.startsWith('drama:')) {
      row = db
        .prepare('SELECT name, local_path, image_url FROM characters WHERE id = ? AND deleted_at IS NULL')
        .get(Number(ent.key.slice(6)));
    } else if (ent.key.startsWith('lib:')) {
      row = db
        .prepare('SELECT name, local_path, image_url FROM character_libraries WHERE id = ? AND deleted_at IS NULL')
        .get(Number(ent.key.slice(4)));
    }
    if (!hasMediaRef(row)) continue;
    const cn = String(row.name || ent.nameHint || '角色').trim();
    pushSlot('角色', cn);
  }
  for (const pr of propRows) {
    if (!hasMediaRef(pr)) continue;
    pushSlot('道具', String(pr.name || '道具').trim());
  }

  const charSlots = slots.filter((s) => s.kind === '角色');
  const sceneFirst = slots.length > 0 && slots[0].kind === '场景';
  const charBindingBlock =
    charSlots.length > 0
      ? [
          sceneFirst
            ? 'CHARACTER_IMAGE_BINDING（@图片1 仅为场景/环境；人物从 @图片2 起依次对应下列姓名，勿把人绑在 @图片1）:'
            : 'CHARACTER_IMAGE_BINDING（首张参考图非场景，以 IMAGE_SLOT_MAP 为准；人物与下列 @图片N 一一对应）:',
          ...charSlots.map((s) =>
            sceneFirst
              ? `「${s.summary}」→ ${s.tag}（外貌/动作绑定 ${s.tag} ，示例：${s.tag} 的侧脸；禁止「@图片1 中的${s.summary}」）`
              : `「${s.summary}」→ ${s.tag}（外貌/动作绑定 ${s.tag} ，示例：${s.tag} 的侧脸）`
          ),
        ].join('\n')
      : slots.length === 0 && forceWithoutReferenceImages
        ? [
            'CHARACTER_IMAGE_BINDING（无图强制模式）:',
            '- 尚无已解析的 @图片 槽位；ORDERED_CHARACTER_NAMES 仅用于剧情理解，禁止写成 @姓名 指代参考图。',
            '- 若输出中出现 @图片N，仅表示与将来补图顺序对齐的占位，勿将具体外貌绑定到错误序号。',
          ].join('\n')
        : [
            'CHARACTER_IMAGE_BINDING: 当前无「角色」参考槽位；若出现人物且 @图片1 为场景，勿将人物外貌写在 @图片1。',
          ].join('\n');

  if (slots.length === 0 && !forceWithoutReferenceImages) {
    return {
      ok: false,
      code: 'bad_request',
      message: '请至少为场景、角色或道具上传一张参考图后再生成，以便对应 @图片1、@图片2 与 API 参考顺序一致',
    };
  }

  let imageSlotMapBlock;
  let line3Required;
  if (slots.length === 0) {
    imageSlotMapBlock = [
      'IMAGE_SLOT_MAP（无图强制模式：尚无已上传场景/角色/道具参考图；视频 API 当前无实际参考图槽位。若正文仍写 @图片N，仅表示与将来补图顺序对齐的占位，出片前须核对）:',
      '（解析结果：无已绑定图像的槽位 — 优先依据剧本与分镜字段写清运镜、节奏与情绪；可不使用 @图片N，或自 @图片1 起预留占位，勿编造与剧本矛盾的细节。）',
    ].join('\n');
    line3Required =
      '当前尚未上传参考图；以剧本与分镜字段书写整段内的运镜与时间轴；若写 @图片N 仅为后续补图预留占位，勿将具体人脸绑定到尚未确定序号的图片；勿编造与剧本矛盾的情节。';
  } else {
    imageSlotMapBlock = [
      'IMAGE_SLOT_MAP（全能模式提交视频时参考图顺序；正文仅可使用下列占位符，与 API 一致）:',
      ...slots.map((s) => `${s.tag} = ${s.kind}「${s.summary}」`),
    ].join('\n');
    line3Required =
      slots[0].kind === '场景'
        ? '环境、光影与陈设定性参考 @图片1。若 @图片1 为宫格或多画面拼图，禁止成片复刻其分格或并列布局，仅提取统一的室内空间与光线语义；须单镜头完整连续画面。'
        : '本片段以首张参考图 @图片1 作为画面锚点展开。';
  }

  const charCount = charNamesOrdered.length;
  const propCount = propNames.length;

  let projectClipSec = 5;
  if (dramaRow?.metadata) {
    try {
      const m = typeof dramaRow.metadata === 'string' ? JSON.parse(dramaRow.metadata) : dramaRow.metadata;
      const v = Number(m?.video_clip_duration);
      if (Number.isFinite(v) && v > 0) projectClipSec = Math.min(120, Math.max(1, v));
    } catch (_) {}
  }
  const body = bodyIn;
  const bodyDurRaw = body.duration != null && body.duration !== '' ? Number(body.duration) : NaN;
  const sbDurRaw = sb.duration != null ? Number(sb.duration) : NaN;
  const durationSec = Number.isFinite(bodyDurRaw) && bodyDurRaw > 0
    ? Math.min(120, Math.max(1, bodyDurRaw))
    : Number.isFinite(sbDurRaw) && sbDurRaw > 0
      ? Math.min(120, Math.max(1, sbDurRaw))
      : projectClipSec;
  const durationLabel = Number.isInteger(durationSec) ? String(durationSec) : String(Math.round(durationSec * 10) / 10);

  const genreHint = (dramaRow?.genre && String(dramaRow.genre).trim()) || '';
  const dramaTitle = (dramaRow?.title && String(dramaRow.title).trim()) || '';
  const styleHintBlock = [
    `STYLE_HINT:`,
    chunk('DRAMA_TITLE', dramaTitle),
    chunk('DRAMA_GENRE', genreHint),
    chunk('STYLE_ZH', styleZh),
    chunk('STYLE_EN', styleEn),
  ]
    .filter(Boolean)
    .join('\n');

  const refContract = [
    'REFERENCE_RULE:',
    ...(slots.length === 0
      ? [
          '- 当前为无图强制模式：视频 API 尚无参考图；可不写 @图片N，若写则仅为补图前占位，出片前须与实际上传顺序一致。',
          '- 禁止用 @场景、@姓名、@道具名 等形式指代参考图；将来有图时须一律改为 @图片N（与 MAP 一致）。',
        ]
      : [
          '- 绑定到某张参考图时，只能写 IMAGE_SLOT_MAP 里列出的 @图片N（阿拉伯数字，如 @图片1、@图片2）。',
          '- 禁止用 @场景、@姓名、@林薇、@道具名 等形式指代参考图；需要指图时一律 @图片N。',
          '- 若 @图片1 为「场景」：只写环境/光影/陈设；人物外貌与动作按 CHARACTER_IMAGE_BINDING 从 @图片2 起。若首张参考图即角色，则以 MAP 为准。',
          '- 场景参考若为四宫格/九宫格等拼图：见 SCENE_REFERENCE_LAYOUT；成片须单镜头连续画面，禁止模仿拼图布局。',
        ]),
    '- 每个 @图片N 与后随的中/英文字之间保留一个半角空格（后处理也会修正，但模型应直接写对）。',
    '- ORDERED_CHARACTER_NAMES 仅供理解剧情，不得当作图占位符。',
    `有图参考槽位数: ${slots.length}；绑定角色数(含无图): ${charCount}；绑定道具数(含无图): ${propCount}`,
  ].join('\n');

  const assetLine = `ORDERED_CHARACTER_NAMES（仅剧情理解）: ${charNames || 'none'}\nORDERED_PROP_NAMES: ${propNames.join(', ') || 'none'}`;

  if (lines.length === 0 && !sceneBlock && !charNames && !propNames.length) {
    return { ok: false, code: 'bad_request', message: '分镜中暂无可用信息，请先填写动作、对白、视频提示词或绑定场景/角色等' };
  }

  const hasSceneSlot = slots.some((s) => s.kind === '场景');
  const sceneLayoutBlock = hasSceneSlot
    ? [
        'SCENE_REFERENCE_LAYOUT（场景参考图可能是多宫格/多视角拼图，仅作内容与空间参考，成片禁止模仿拼图）:',
        '- 场景槽位（通常为 @图片1）常见为四宫格、九宫格或带分割线的多视角场景图：只提取家具、装修、色调、空间关系与光影，不要在提示中引导模型生成「分屏、宫格、多画面并列、复刻参考图网格」。',
        '- 每一个「分镜k： Tk秒:」所在行的正文里都应点明：单镜头连续画幅、无成片宫格分屏；参考拼图仅用于理解空间与光线。',
      ].join('\n')
    : '';

  let episodeScript = '';
  let episodeTableTitle = '';
  try {
    const ep = db.prepare('SELECT script_content, title FROM episodes WHERE id = ? AND deleted_at IS NULL').get(sb.episode_id);
    if (ep) {
      episodeTableTitle = (ep.title && String(ep.title).trim()) || '';
      episodeScript = ep.script_content != null ? String(ep.script_content) : '';
    }
  } catch (_) {}
  const SCRIPT_CAP = 20000;
  if (episodeScript.length > SCRIPT_CAP) {
    episodeScript = `${episodeScript.slice(0, SCRIPT_CAP)}\n...[EPISODE_SCRIPT_TRUNCATED]`;
  }

  const mHeuristic = Math.min(8, Math.max(1, Math.round(durationSec / 5)));
  let shotPacingBlock = '';
  try {
    const all = db
      .prepare(
        'SELECT id, storyboard_number, segment_index, segment_title FROM storyboards WHERE episode_id = ? AND deleted_at IS NULL ORDER BY storyboard_number ASC'
      )
      .all(sb.episode_id);
    const ix = all.findIndex((r) => Number(r.id) === Number(sb.id));
    const totalShots = all.length || 1;
    const posTag =
      ix <= 0 ? 'first_in_episode' : ix === all.length - 1 ? 'last_in_episode' : 'middle_of_episode';
    const prevSeg = ix > 0 ? String(all[ix - 1].segment_title || '').trim() : '';
    const nextSeg = ix >= 0 && ix < all.length - 1 ? String(all[ix + 1].segment_title || '').trim() : '';
    const currSeg = String(sb.segment_title || '').trim();
    const segChange = ix > 0 && currSeg && prevSeg && currSeg !== prevSeg;
    shotPacingBlock = [
      'SHOT_PACING_AND_POSITION:',
      `TOTAL_CLIP_SECONDS: ${durationLabel}（本条数据库分镜 = 一次成片 API 的整段时长；下文 M 个子分镜仅为同一时间轴内节拍拆分）`,
      `M_HEURISTIC_ONLY: 约 ${mHeuristic}（不得照抄为最终 M；须结合剧本高潮/对白密度/转场/机位与 movement 等自决 1～8 的整数 M）`,
      `SHOT_ORDER: ${ix >= 0 ? ix + 1 : '?'} / ${totalShots}`,
      `SHOT_POSITION_TAG: ${posTag}`,
      chunk('SEGMENT_TITLE_PREV', prevSeg || null),
      chunk('SEGMENT_TITLE_CURRENT', currSeg || null),
      chunk('SEGMENT_TITLE_NEXT', nextSeg || null),
      segChange
        ? 'BOUNDARY_HINT: 段落标题相对上一镜已变化 → 转场/新叙事块概率高 → 可提高 M 或前几秒侧重空间/情绪铺垫再入冲突。'
        : 'BOUNDARY_HINT: 同段落延续 → M 可保守；若 ACTION 内对白长、机位少，也可 M=1 但在单行内写满时间流动。',
    ].join('\n');
  } catch (_) {
    shotPacingBlock = [
      'SHOT_PACING_AND_POSITION:',
      `TOTAL_CLIP_SECONDS: ${durationLabel}`,
      `M_HEURISTIC_ONLY: 约 ${mHeuristic}`,
    ].join('\n');
  }

  let neighborDetailBlock = '';
  try {
    const prevFull = db
      .prepare(
        `SELECT storyboard_number, title, segment_title, action, dialogue, narration, shot_type, movement, atmosphere
         FROM storyboards WHERE episode_id = ? AND storyboard_number < ? AND deleted_at IS NULL ORDER BY storyboard_number DESC LIMIT 1`
      )
      .get(sb.episode_id, sb.storyboard_number);
    const nextFull = db
      .prepare(
        `SELECT storyboard_number, title, segment_title, action, dialogue, narration, shot_type, movement, atmosphere
         FROM storyboards WHERE episode_id = ? AND storyboard_number > ? AND deleted_at IS NULL ORDER BY storyboard_number ASC LIMIT 1`
      )
      .get(sb.episode_id, sb.storyboard_number);
    const fmtN = (row, tag) => {
      if (!row) return `${tag}: (none)`;
      const bits = [
        `${tag}:`,
        chunk('N_NUM', row.storyboard_number),
        chunk('N_TITLE', row.title),
        chunk('N_SEGMENT', row.segment_title),
        chunk('N_ACTION', row.action),
        chunk('N_DIALOGUE', row.dialogue),
        chunk('N_NARRATION', row.narration),
        chunk('N_SHOT_TYPE', row.shot_type),
        chunk('N_MOVEMENT', row.movement),
        chunk('N_ATMOSPHERE', row.atmosphere),
      ].filter(Boolean);
      return bits.join('\n');
    };
    neighborDetailBlock = [fmtN(prevFull, 'NEIGHBOR_PREV_DETAIL'), '', fmtN(nextFull, 'NEIGHBOR_NEXT_DETAIL')].join('\n');
  } catch (_) {}

  const multiBeatContract = [
    'MULTI_BEAT_OUTPUT（一条成片 API 内的多节拍文案）:',
    '- 总行数 = 3 + M。M 为你选择的子分镜条数（时间轴节拍），整数 1～8。',
    '- 第1行：「画面风格和类型:」…',
    `- 第2行：必须为「生成一个由以下M个分镜组成的视频。」（将 M 替换为你的整数；与下文实际「分镜1…分镜M」条数一致）。`,
    '- 第3行：必须逐字等于 LINE3_REQUIRED（见下）。',
    '- 第4行到第(3+M)行：依次为「分镜1： T1秒:」「分镜2： T2秒:」…「分镜M： TM秒:」；每行冒号后先写秒数再写该子时段内的动态影像与运镜描写。',
    `- 约束：T1+T2+…+TM 必须严格等于 TOTAL_CLIP_SECONDS（数值与 ${durationLabel} 一致）；每个 Tk>0；子分镜序号连续无跳号。`,
    '- 若 M=1：即仅一行「分镜1： TOTAL秒:」写满整段；若 M>1：每行只覆盖本子时段，前后行衔接成连续时间线，避免剧情跳跃或重复前一行已完成的动作。',
    '- 禁止额外说明行、markdown、英文小标题；禁止把「子分镜」写成多次独立成片 API。',
  ].join('\n');

  const userPrompt = [
    `TOTAL_CLIP_SECONDS: ${durationLabel}`,
    `DURATION_SECONDS: ${durationLabel}`,
    multiBeatContract,
    shotPacingBlock,
    neighborDetailBlock || null,
    'LINE3_REQUIRED（第3行必须与下面整句完全一致，含标点）:',
    line3Required,
    `EPISODE_SCRIPT:\n${episodeScript || '(本集剧本为空；仅凭分镜与邻镜推断节奏，勿编造大段新剧情)'}`,
    chunk('EPISODE_TABLE_TITLE', episodeTableTitle),
    imageSlotMapBlock,
    sceneLayoutBlock || null,
    charBindingBlock,
    styleHintBlock,
    refContract,
    assetLine,
    sceneBlock || null,
    `CONTEXT_PREV_SHORT: ${prevDesc}`,
    `CONTEXT_NEXT_SHORT: ${nextDesc}`,
    '--- STORYBOARD FIELDS ---',
    ...lines,
  ]
    .filter(Boolean)
    .join('\n');

  return {
    ok: true,
    userPrompt,
    durationLabel,
    durationSec,
    sbId,
    episodeId: Number(sb.episode_id) || 0,
    storyboardNumber: Number(sb.storyboard_number) || 0,
  };
}

module.exports = { buildUniversalSegmentUserPromptBundle };
```

### R2.7 LocalMiniDrama — `getRolePolishPrompt` full function

Nguồn: `_refs/LocalMiniDrama/backend-node/src/services/promptI18n.js` — function `getRolePolishPrompt` (đến trước `getRoleGenerateImagePrompt`).

```javascript
function getRolePolishPrompt(cfg) {
  const style = styleTextZhForPolish(cfg);
  return `# 工业角色参考表标准提示词生成器

## 你的身份
你是专业的角色视觉设计师，负责将角色描述转换为「工业角色参考表」绘图提示词：分栏、标签清晰、主体填满画幅；**不是**四宫格拼图、**不是**海报、**不是**真人棚拍写真、**不是**漫画分镜、**不是**贴纸拼贴。

## 核心规则

### 提取与限制
- **仅提取**：角色描述中明确的外貌与服装特征
- **严禁添加**：场景、环境、叙事性光影特效、情绪形容词堆砌
- **标志性道具（可选）**：仅当原文明确写出身份关键道具时，写在「SIGNATURE PROP / EQUIPMENT DETAIL」小窗内容里；**不得**凭空加武器或剧情道具
- **全版面一致**：所有面板同一角色、同一年龄段与妆面；发型、瞳色、服装、体型、比例完全一致
- **时代匹配**：服装与发型必须符合作品类型所属时代背景${style ? '\n- **画风风格（须贯穿各栏描述，与下长生图侧画风块一致）**：' + style : ''}

### 版式（强制，减少留白）
- **顶部标题栏**：浅灰细边框技术标题条，标题使用用户提供的角色名称（或作品内统一称呼），与正文描述一致
- **左约三分之一竖栏**：仅放置 **FACE HERO CLOSE-UP**（主面部特写竖条，大块面部占位，减少无用留白）
- **右约三分之二区域**：放置 **FRONT VIEW**、**BACK VIEW**、**SIDE PROFILE CLOSE-UP**、**COSTUME / SUIT DETAIL VIEW**、**MATERIAL & TEXTURE NOTES**；各分区配有清晰英文/中英对照标签
- **禁止侧身全身**：不设置 90° 侧面全身面板
- **FRONT VIEW 与 BACK VIEW**：同一角色、同一套服装版本、同一身高比例、同一灯光与同一标尺尺度；正面与背面均为稳定直立全身（头顶到脚底），不做动作姿势，无扭身；双臂自然下垂于体侧，手部自然
- **SIDE PROFILE CLOSE-UP**：90° 侧面脸部特写（非全身），展示侧脸轮廓、鼻梁侧面、耳部、发型侧面与下颌线；**必须与左侧 FACE HERO CLOSE-UP 同一张脸**（不可变成另一年龄或另一妆面），与正脸形成互补而非重复
- **COSTUME / SUIT DETAIL VIEW 与 MATERIAL & TEXTURE NOTES**：仅在右侧区域内展示衣领、袖口、腰带、鞋靴、配饰、边缘轮廓及布料/金属/皮革/绷带等材质；**MATERIAL & TEXTURE NOTES** 只能用**短标签**（如 cloth、metal、leather、wet fabric、edge wear），**不得**写成横跨全画幅的底部长文说明栏
- **可选**：**SIGNATURE PROP / EQUIPMENT DETAIL** 小窗（按需）
- **取消**：色板条、调色块模块
- **分隔**：各面板之间细浅灰分割线，边界规整、留白克制；整体 4K 级细节密度、结构稳定的电影工业参考表质感

### 输出语言约束
- **禁止情绪描写**：禁止「带憧憬」、「给人…感」等
- **禁止抽象形容**：禁止「俊美」「自信」「温柔」等无法直接画出的词
- **只用具象描述**：可视化物理特征

### 避免与生图侧重复
- **不要**重复赘述纯白底、禁止拼贴分镜等生图 API 系统提示里已有的硬性条款
- **须**在润色输出中明确：标题条应显示的标题文字、各分区的英文标签名（如 FACE HERO CLOSE-UP、FRONT VIEW、SIDE PROFILE CLOSE-UP、MATERIAL & TEXTURE NOTES），并与上方【输出格式】各节一一对应（参考表画面上的技术标签不是「水印」）
- 正文仍以具象外貌/服装/材质为主，避免空洞「8K」「超高清」堆砌

## 时代服装匹配表

| 类型 | 服装体系 |
|------|---------|
| 古风/仙侠/玄幻 | 中国古代汉服体系，交领右衽、广袖长袍 |
| 武侠 | 中国古代劲装体系，交领窄袖劲装 |
| 西幻/奇幻 | 欧洲中世纪服饰，束腰长袍、斗篷 |
| 现代都市 | 现代服装，T恤、衬衫、西装、连衣裙 |

## 抽象词汇转具象示例

| 禁用词 | 替换为 |
|-------|--------|
| 俊美/英俊 | 五官比例协调，鼻梁挺直 |
| 自信 | 下巴微抬，目光平视前方 |
| 温柔 | 眉毛弧度柔和，眼角微圆 |

## 输出格式

【基础设定】
人物基础: 性别，年龄段，身高体型，肤色
五官: 眉形，眼型，瞳色，鼻型，唇形
表情（全身与主特写）: 中性、无表情或统一证件照式平静
发型: 颜色，长度，质感，发型结构
服装: 款式名称，主色，材质，领型，袖型

【标题栏】
标题条内要显示的确切标题文字（通常即角色名）

【FACE HERO CLOSE-UP｜左竖栏】
主脸特写（竖向大画幅）：发际线到下颌，肤质、眉眼妆面、唇形与整体脸型比例

【FRONT VIEW｜右区-正面全身】
正面全身：从头到脚完整入画，站姿稳定，服装前襟与裤/裙正面结构

【BACK VIEW｜右区-背面全身】
背面全身：从头到脚后跟完整入画，与正面同比例同服装；后脑发型、后领、背身裁片与下摆

【SIDE PROFILE CLOSE-UP｜右区】
90° 侧面脸部特写：侧脸轮廓、鼻梁侧面、耳部、发型侧面、下颌线与唇线侧面（与左栏正脸同一人，互补不重复）

【COSTUME / SUIT DETAIL VIEW｜右区】
衣领、袖口、腰带、鞋靴、配饰、裁片边缘等（不写整景）

【MATERIAL & TEXTURE NOTES｜右区小标签】
若干短英文或中英标签列举材质关键词（非长段落）

【SIGNATURE PROP / EQUIPMENT DETAIL｜可选】
仅当有原文依据时写道具局部特写说明`;
}

/**
 * 角色参考表图片生成：图片AI 的 system prompt，工业分栏版式（非四宫格），画风由用户消息首部强调
 */
```


## Đã đọc

### Jellyfish
- `README.md`, `LICENSE`
- `site/content/product/workflow.md`, `site/content/docs/architecture/shot-status-flow.md`
- `backend/app/models/studio_shots.py`, `studio_assets.py`, `types.py` (`ShotStatus` enum)
- `backend/app/services/studio/shot_status.py` (`recompute_shot_status`, `mark_shot_generating`)
- `backend/sql/003-normalize-shot-status-remove-generating.sql`
- `backend/app/chains/agents/element_extractor_agent.py` (**full** ROUND 2)
- `backend/app/chains/agents/entity_merger_agent.py` (**full** ROUND 2)
- `backend/app/chains/agents/variant_analyzer_agent.py` (**full** ROUND 2)
- `backend/app/chains/agents/shot_frame_prompt_agents.py` (**full** template ROUND 2)
- `backend/app/chains/agents/*.py` (divider, optimizer, simplifier, consistency, portrait, scene/prop/costume, script_processing_agents)
- `backend/app/services/script_processing_worker.py`
- `backend/app/services/film/shot_frame_prompt_tasks.py`
- `backend/app/services/studio/generation/video/build_context.py`
- `backend/app/services/studio/generation/frame/{build_context,derive_preview,build_base}.py`
- `backend/app/services/studio/generation/asset_image/build_base.py`
- `backend/sql/001-init-prompt-template.sql`
- `front/src/pages/aiStudio/shots/ChapterShotEditPage.tsx` (+ tree layouts)

### LocalMiniDrama
- `README.md`, `LICENSE`, `docs/story.md`
- `backend-node/migrations/01_init.sql`, `src/db/migrate.js` (columns)
- `backend-node/src/services/promptI18n.js` — `getCharacterExtractionPrompt` zh full; `getStoryboardSystemPrompt` **full zh+en** (ROUND 2); `getRolePolishPrompt` **full** (ROUND 2); identity anchors; first/key/last/omni excerpts
- `backend-node/src/services/universalSegmentPromptBundle.js` (**full file** ROUND 2)
- `characterGenerationService.js`, `characterLibraryService.js` (partial)
- `episodeStoryboardService.js` (prompt assembly + continuation)
- `storyboardFrameBinding.js`
- `imageService.js` (ref order + layout lock)
- `videoService.js`, `ttsService.js`, `narrationVideoPostProcess.js`
- `taskService.js`, `routes/audio.js`
- Front tree: `DramaCanvas`, `FilmCreate`, canvas components

### OmniCast (đối chiếu gap)
- `implementation/src/omnicast/storyboard/{binding,continuity,extract,models}.py` (grep/headers)

### Verify meta
- `docs/research/REFS_SB_00_VERIFY.md` §2.2, §3.1 (E1, E4), §3.2 (V6, V7), §4.3

---

*Hết report REFS_SB_02 (ROUND 2: vá E1/E4/V6/V7 + VERBATIM FULL theo VERIFY §4.3).*
