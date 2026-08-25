# REFS_SB_03 — waoowaoo (AI 影视创作流)

> STATUS: DONE (2026-08-02) — Round 2 VERBATIM fix (V1/V2 + §4.1 full dump)  
> Repo: `_refs/waoowaoo` (~1256 file code, Next.js 15 full-stack)  
> License: **CC BY-NC-SA 4.0** — NonCommercial + ShareAlike. Chỉ học concept/prompt pattern; **CẤM chép code** vào sản phẩm thương mại OmniCast.  
> Brief: `_briefs/03_waoowaoo.md` + `COMMON_CONTEXT.md`

---

## 0. Câu hỏi riêng (tóm tắt trước 10 mục)

### 0.1 Creation flow — stage nào / auto vs human / state machine

UI stages (`messages/zh/stages.json`):

| # | Stage UI | Artifact | Auto? | Human gate |
|---|----------|----------|-------|------------|
| 1 | 配置 Config | models, ratio, artStyle | setup | User chọn model/style/ratio |
| 2 | 资产分析 Assets | characters / locations / props + images | LLM extract + image gen | **profileConfirmed**, chọn appearance/image, AI design/modify |
| 3 | 分镜编辑 Storyboard | clips → panels (text+image) | LLM 4 phase + panel image | Review panels, re-roll image, insert/edit |
| 4 | 视频生成 Videos | panel.videoUrl | i2v / first-last-frame | Chọn model, duration, generate per panel / batch |
| 5 | 配音生成 Voice | voiceLines + optional lipSync | TTS + lip-sync | Gán voice, confirm lines |
| 6 | 剪辑 Editor (extra) | VideoEditorProject | dissolve default | Transition type/duration, render |

**State machine (artifact-driven, không hard-lock stage):**

```
                    ┌─────────────┐
                    │  Project    │
                    │  + Config   │
                    └──────┬──────┘
                           │ novelText / import
                           ▼
              ┌────────────────────────┐
              │ STORY_TO_SCRIPT_RUN    │  auto LLM (chars/locs/props/clips/screenplay)
              └────────────┬───────────┘
                           │ hasScript
                           ▼
              ┌────────────────────────┐
              │ ASSET HUB / Project    │  human: confirm profile, gen sheets, select image
              │ appearances + slots    │  auto: AI design/modify/image tasks
              └────────────┬───────────┘
                           │ assets ready (implicit — prompts filter by name)
                           ▼
              ┌────────────────────────┐
              │ SCRIPT_TO_STORYBOARD   │  auto: Phase1→2cine∥2acting→3 detail
              │ → NovelPromotionPanel  │  retry atomic per phase (max 3)
              └────────────┬───────────┘
                           │ hasStoryboard (panels exist)
                           ▼
              ┌────────────────────────┐
              │ IMAGE_PANEL (per shot) │  auto gen + candidates; human pick/re-roll
              └────────────┬───────────┘
                           │ panel.imageUrl
                           ▼
              ┌────────────────────────┐
              │ VIDEO_PANEL            │  i2v normal | firstlastframe
              │ (+ optional LIP_SYNC)  │
              └────────────┬───────────┘
                           │ hasVideo
                           ▼
              ┌────────────────────────┐
              │ VOICE_LINE / analyze   │  parallel-ish with video stage UI
              └────────────┬───────────┘
                           ▼
              ┌────────────────────────┐
              │ Video Editor + Render  │  transitions: dissolve/fade/slide/none
              └────────────────────────┘
```

Readiness helper (`stage-readiness.ts`): `hasStory / hasScript / hasStoryboard / hasVideo / hasVoice` — **không chặn route cứng**, chỉ đo artifact.

### 0.2 Asset system — định nghĩa, version, tái sử dụng

| Loại | Model | Version hoá | Reuse |
|------|-------|-------------|-------|
| Character | `NovelPromotionCharacter` + `CharacterAppearance[]` | `appearanceIndex` (0 = primary), `changeReason` (vd "初始形象"), multi `descriptions`/`imageUrls` + `selectedIndex` | Project-scope; `sourceGlobalCharacterId` copy từ Global hub |
| Location | `NovelPromotionLocation` + `LocationImage[]` | multi images, `isSelected`, `availableSlots` (vị trí đứng cố định) | `sourceGlobalLocationId`; prop cũng `assetKind` trên location-backed |
| Prop | location-backed / AssetKind `prop` | variants giống location | `canCopyFromGlobal` |
| Global hub | `GlobalCharacter` / `GlobalLocation` / `GlobalVoice` + folders | parallel schema to project assets | Copy-into-project, giữ lineage |
| Voice | character `voiceId` / custom + GlobalVoice | bind 1 voice | hub copy |

**Không có semantic versioning (v1.2.3)** — version = appearance index + previous* undo fields (`previousImageUrl`, `previousDescription`).

### 0.3 Prompt per shot — thứ tự ghép

**Text storyboard (LLM multi-agent):**

1. Phase1 plan: asset libs + filtered appearance/full desc + props + clip/screenplay  
2. Phase2a cinematography: panels + location + characters + props  
3. Phase2b acting: panels + characters  
4. Phase3 detail: panels + age/gender desc → `shot_type` / `camera_move` / `video_prompt`

**Panel image gen:**

```
refs order = [sketch?] + [char appearance images…] + [location selected image]
prompt   = single_panel_image template(
  aspect_ratio,
  storyboard_text_json_input = { panel fields + photography_rules + acting_notes + character_appearances + location_reference },
  source_text,
  style
)
+ referenceImages: labeled (bar text = asset name)
```

**Video gen:** `firstLast custom | panel.firstLastFramePrompt | customPrompt | panel.videoPrompt | description` + source = panel still (i2v); optional last frame = another panel image.

**Negative prompt:** **không có** field/template negative riêng — thay bằng hard rules trong positive prompt ("绝对禁止文字", "禁止拼图", JSON 引号安全).

### 0.4 Video-gen providers

| Provider family | Models (constants) | Mode |
|-----------------|-------------------|------|
| Ark / Doubao Seedance | 2.0, 2.0 Fast, 1.5 Pro, 1.0 Pro/Lite (+ batch) | **i2v primary**; firstlastframe trên nhiều Seedance |
| FAL | Kling 2.5/3, Wan 2.6, Veo 3.1 Fast, Sora 2 | i2v paths |
| Google | Veo 3.1 / Fast (firstlastframe list) | poll async |
| Lip-sync | Bailian / FAL / Vidu (`lipsync/providers`) | post-video |

**Transition giữa clip:** **không** trong video-gen worker; chỉ Video Editor default `dissolve` 0.5s (`useEditorActions.ts`).

### 0.5 Job orchestration — đáng bê về OmniCast batch runner

| Mechanism | Chi tiết | OmniCast? |
|-----------|----------|-----------|
| 4 queue BullMQ | image / video / voice / text | Có — tách media type |
| attempts=5 exponential 2s | trừ story/script runs = 1 | Có |
| per-user concurrency gate | image/video default 5 | **Nên bê** |
| billing freeze quote | maxFrozenCost trước enqueue; OFF/SHADOW/ENFORCE | Cost guard shadow → enforce |
| atomic phase retry | script-to-storyboard max 3/step, delay ≤10s | Storyboard pipeline |
| candidate multi-image | 1–4, previousImageUrl undo | Re-roll UX |
| run-centric workflow | STORY_TO_SCRIPT / SCRIPT_TO_STORYBOARD + lease/artifacts | Long LLM DAG |
| capability catalog | firstlastframe / duration / audio flags | Tránh guess model |

---

## 1. Tổng quan kiến trúc

### 1.1 Stack

- **Frontend/Backend:** Next.js 15 App Router + React 19 (`src/app/`, `src/components/`)
- **DB:** MySQL + Prisma (`prisma/schema.prisma`) — domain `novel_promotion_*`
- **Queue:** Redis + BullMQ (`src/lib/task/queues.ts`, workers `image|video|voice|text`)
- **Storage:** MinIO / COS / local (`src/lib/storage/`)
- **Billing:** ledger + balance freeze (`src/lib/billing/`)
- **i18n prompts:** `lib/prompts/novel-promotion/*.zh|en.txt` + `src/lib/prompt-i18n/`

### 1.2 Module map

```
src/app/api/…                    # REST: projects, tasks, assets, editor
src/lib/novel-promotion/
  story-to-script/orchestrator   # text → clips + screenplay + asset extract
  script-to-storyboard/…         # multi-phase storyboard LLM
  stages/video|voice-stage-*     # UI runtime cho stage 4–5
src/lib/storyboard-phases.ts     # Phase1/2/2acting/3 executors
src/lib/assets/                  # kinds, prompt context, global hub actions
src/lib/workers/handlers/        # task handlers (panel image/video, assets…)
src/lib/generators/              # image/video/audio provider adapters
src/features/video-editor/       # timeline + transition + render
lib/prompts/                     # VERBATIM prompt templates (SSOT files)
```

### 1.3 Luồng dữ liệu end-to-end

```
User novel text / AI expand
    → STORY_TO_SCRIPT_RUN
        → characters + locations + props objects
        → clip list (start/end text anchors)
        → per-clip SCREENPLAY_CONVERT
    → User confirms assets, generates character sheets / location images
    → SCRIPT_TO_STORYBOARD_RUN (per clip, concurrent)
        → panels: description, characters[{name,appearance,slot}], location,
                  photographyRules, actingNotes, shot_type, camera_move, video_prompt, source_text
    → IMAGE_PANEL: refs + single_panel prompt → still(s)
    → VIDEO_PANEL: still → i2v (optional last frame)
    → VOICE_LINE + optional LIP_SYNC
    → Editor: timeline clips + dissolve + export
```

Cite: `README_en.md:7-26`, `stages.json`, `prisma/schema.prisma:79-330`, `task/types.ts:40-81`.

---

## 2. Data model storyboard

### 2.1 Hierarchy

```
Project
 └─ NovelPromotionProject (artStyle, videoRatio, *Model keys, workflowMode)
     ├─ NovelPromotionCharacter[] → CharacterAppearance[]
     ├─ NovelPromotionLocation[]  → LocationImage[]  (assetKind: location|prop)
     └─ NovelPromotionEpisode[]
         ├─ novelText, srtContent, audioUrl
         ├─ NovelPromotionClip[]   (1 clip ↔ 1 storyboard)
         │    content, characters, location, props, screenplay, startText/endText
         ├─ NovelPromotionStoryboard (clipId unique)
         │    └─ NovelPromotionPanel[]  (panelIndex)
         │         shotType, cameraMove, description, location, characters, props
         │         srtSegment/source_text, duration, photographyRules, actingNotes
         │         imageUrl, candidateImages, videoUrl, videoPrompt, firstLastFramePrompt
         │         videoGenerationMode: normal|firstlastframe
         │         linkedToNextPanel, lipSync*, sketchImageUrl
         ├─ NovelPromotionShot[] (legacy/SRT path)
         ├─ NovelPromotionVoiceLine[]
         └─ VideoEditorProject (projectData JSON timeline)
```

### 2.2 Panel character ref shape (JSON in DB)

From plan prompt schema:

```json
{
  "name": "角色名",
  "appearance": "形象名",
  "slot": "场景固定位置描述"
}
```

Names **must** match asset library exactly (VERBATIM).

### 2.3 Storyboard text phase machine

| Phase | Type key | Progress | Output |
|-------|----------|----------|--------|
| 1 | `1` | 10–40% | plan panels (description, chars, location, scene_type, source_text) |
| 2a | `2-cinematography` | 40–55% | photographyRules per panel |
| 2b | `2-acting` | 55–70% | actingDirections per panel |
| 3 | `3` | 70–100% | shot_type, camera_move, video_prompt (+ keep source_text) |

Cite: `storyboard-phases.ts:19-138`, `schema.prisma:188-241`.

### 2.4 UI stage readiness

```typescript
// stage-readiness.ts:66-73
hasStory: novelText non-empty
hasScript: any clip.screenplay
hasStoryboard: any storyboard with panels
hasVideo: any panel.videoUrl
hasVoice: voiceLines.length > 0
```

---

## 3. Cơ chế consistency (nhân vật / bối cảnh / props)

### 3.1 Reference images — số lượng, thứ tự, vai trò

`collectPanelReferenceImages` (`image-task-handler-shared.ts:225-263`):

1. **Sketch** (`panel.sketchImageUrl`) — nếu có, đầu tiên  
2. **Mỗi character** trong panel: match appearance by `changeReason` == `appearance` name → `selectedIndex` image or first  
3. **Location** selected image (`isSelected` else first)

→ Truyền `options.referenceImages` vào image generator (ordered array).

**Label trên ref:** `image-label.ts` vẽ bar chữ tên asset lên mép trên — model đọc label, prompt cấm vẽ chữ vào output.

### 3.2 Character sheet

- Suffix system (`constants.ts:192`): left 1/3 face close-up + right 2/3 tri-view (front/side/back), white bg.  
- Upload reference → `character_reference_to_sheet` (identity only, style từ user art style).  
- Multi appearance: wardrobe/age change = new `CharacterAppearance` row.

### 3.3 Location slots (spatial anchors)

Location create prompt forces `available_slots` (2–6 full phrases). Storyboard plan/cinematography treat `slot` as **priority anchor, not hard lock** when movement/dream/path.

### 3.4 Text filter into prompts

`buildPromptAssetContext` only injects characters/locations/props **present in clip** — giảm drift từ asset rác.

### 3.5 Seed / LoRA / IP-Adapter

**Không thấy** seed control, LoRA, hay IP-Adapter trong code gen path — consistency = **named assets + ref images + descriptive text + selectedIndex**.

### 3.6 Re-roll / verify

- Panel image: `candidateCount` 1–4; first gen sets `imageUrl`; re-gen writes `previousImageUrl` + candidates.  
- Storyboard LLM: retry 2× (phase executors) / atomic max 3 (`MAX_STEP_ATTEMPTS`).  
- Validate: non-empty panels, `source_text` required, filter `description=="无"`.  
- **Không** pixel-level face verify / CLIP similarity gate.

---

## 4. PROMPT ENGINEERING — VERBATIM

> **VERIFY V1/V2 fix (2026-08-02):** mọi khối dưới đây là **CHÉP ĐỦ từng chữ** từ file gốc trong `_refs/waoowaoo` (zh). **Cấm** paraphrase / `…` trong fence. File dài vẫn full; bản dump gom thêm file §4.1 VERIFY nằm ở `## ROUND 2`.
> Prompt files SSOT: `lib/prompts/novel-promotion/*.zh.txt` + `lib/prompts/character-reference/*.zh.txt` + suffix hằng số `src/lib/constants.ts`.

### 4.1 Clip split — `agent_clip.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/agent_clip.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Cắt clip theo “content elements” (hành động/thoại=2 element) → bound độ dài context cho storyboard; force exact asset names sớm; JSON quote an toàn bằng 「」.

```text
你是"剧本/文字片段预分割大师"。
任务：把用户输入给你的文字创意或剧本整份输入文字按场景/剧情边界切成若干批次，便于后续逐批转换为分镜。只输出 JSON，字段仅限如下结构，start为文字开始的文本，end为文字结束的文本，禁止任何多余文字以及禁止包含任何markdown标识符：

输出格式和要求
[
  {
    "start": 开局文本，最少包含五个字,
    "end": 结束文本，最少包含五个字,
    "summary": "总结概括片段内容",
    "location": "场景发生位置",
    "characters": ["角色1", "角色2"],
    "props": ["道具1", "道具2"]
  }
]

按照以下规则切分:

【什么是"内容元素"- 必须理解】
内容元素是指原文中可以独立成镜的最小单位，包括：
- 🎬 动作描述：每个独立动作算 1 个元素
  例："他站起身" = 1个元素，"他站起身，走向门口，推开门" = 3个元素
- 💬 对话台词：每段对话算 2 个元素（说话者 + 听者反应）
  例："陛下，请允许我介绍这位" = 2个元素
- 🎭 情绪/反应描述：每个角色的反应算 1 个元素
  例："皇帝眉头紧锁，皇后面色凝重" = 2个元素
- 🌅 场景描写：场景建立描写算 1-2 个元素
- 💭 心理活动/旁白：每段独白算 1 个元素

【计数示例】
原文："他走进房间，看见她坐在窗边。她抬头看他，眼中带着泪光，轻声说：你终于来了。"
- "他走进房间" = 1个元素（动作）
- "看见她坐在窗边" = 1个元素（场景描写）
- "她抬头看他，眼中带着泪光" = 2个元素（动作+情绪）
- "轻声说：你终于来了" = 2个元素（对话）
总计：6 个元素

1:【片段数量最小化 - 最高优先级】
   - 每个片段最多可容纳约 20 个内容元素（按上述定义计算）
   - 如果原文总元素 ≤ 20 个，必须只切分为 1 个片段，禁止拆分
   - 如果原文总元素 ≤ 40 个，最多切分为 2 个片段
   - 宁可片段稍长，也绝不过度切分
   - 只有当单个片段超过 20 个元素时，才考虑在场景变化处拆分
2:切割应该尽量完整切割,不要在剧情中间切割,确保剧情的完整性.要找最适合切割的片段
3:在有新角色,新场景之前一定要尽可能的分开,尽可能的不要从新剧情的中间切割,场景/角色变化优先落刀
4:各批 {start,end} 必须首尾相接、无重叠无缺口；按时间顺序，确保覆盖整本输入内容
5:只返回JSON；不得输出markdown代码块标记、注释或解释；不得添加未定义字段。- 只返回上述 JSON；不得输出markdown代码块标记、如```json注释或解释；不得添加未定义字段。
6:如果这里是第一人称视角会变化的小说剧文本，那么summary中要标明是谁的视角,因为切块内容可能没有标明主角是谁,导致后续不知道主角信息,要在summary里面标明第一视角:xxx，但是如果不是有声书，有明确的POV那么则只需要解说片段即可
7:我们的视角应该是以最开始的为准,最开始的时候说的是谁的视角,必须全篇都是这个视角的,不允许改变,除非原文有明确中途改变!
8:要完整切分我们输入的完整剧本/文字内容.
⚠️⚠️⚠️【JSON安全输出 - 最高优先级】⚠️⚠️⚠️
- 原文中的所有引号（""''「」『』等）在 JSON 字符串值中必须统一替换为日式方括号引号「」
- ❌ 严禁在 JSON 字符串值中出现英文双引号 " ！会破坏 JSON 结构！
- ✅ 正确：「弼马温，我是来取代你的」
- ❌ 错误："弼马温，我是来取代你的"
- 这条规则适用于 start、end、summary 等所有字符串字段

⚠️⚠️⚠️【资产选择 - 最高优先级规则】⚠️⚠️⚠️

【location 场景选择 - 必须100%精确匹配】
1. location 字段【只能】填写场景库中【完全一模一样】的名字
2. ❌ 严禁添加任何后缀！例如场景库是 "客厅"，禁止写成 "客厅_内景_白天"
3. ❌ 严禁修改场景库的名字！禁止改写、缩写、添加任何字符
4. 如果剧情发生在多个场景，用逗号分隔：如 "客厅,卧室"
5. 如果剧情场景不在场景库中，选择最接近的场景，或留空 null

【characters 角色选择 - 必须100%精确匹配】
1. characters 数组【只能】填写角色库中【完全一模一样】的名字
2. ❌ 严禁使用原文中的其他称呼！必须使用角色库的名字
3. 例如角色库有"张三"，原文写"老张"或"张总"，必须填写"张三"
4. ⭐ 参考【角色介绍】理解"我"对应哪个角色，以及其他称呼的映射关系

【props 道具选择 - 必须100%精确匹配】
1. props 数组【只能】填写道具库中【完全一模一样】的名字
2. ❌ 严禁改写、缩写、添加前后缀
3. 只选择当前片段里真正出镜、被持有、被使用、被重点提及的实体道具
4. 如果当前片段没有明确道具，返回空数组 []

【自检规则】
输出前检查：location、characters、props 中的每个名字是否都能在对应资产库中找到完全一致的？如果不能，必须修正！

原文如下:
{input}

场景库：
{locations_lib_name}

角色库：
{characters_lib_name}

角色介绍（⭐用于理解"我"和称呼对应的角色）：
{characters_introduction}

道具库：
{props_lib_name}
```

### 4.2 Storyboard plan — `agent_storyboard_plan.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/agent_storyboard_plan.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** (1) density ~15 chars/shot; (2) lip-sync-aware dialogue split; (3) continuity theo FOV; (4) VERBATIM asset names; (5) source_text bắt buộc cho VO/SRT.

```text
你是专业的分镜规划师。你的任务是根据剧本内容（或原文）将故事拆解成连续的分镜头，设计分镜板基础规划。

输入可能是两种格式：
1. 【剧本格式】JSON格式的结构化剧本，包含scenes、action、dialogue、voiceover等
2. 【原文格式】原始小说/文本片段

无论哪种格式，你都需要将其拆解成连续的电影镜头。

【核心原则 - 最高优先级】
⚠️ 精准覆盖！确保每个关键画面都有镜头
⚠️ 电影思维：聚焦核心动作和情绪点
⚠️ 目标比例：每15个字符 = 1个镜头（字符/镜头比 ≈ 15:1）
⚠️ 关键角色动作和对话需要独立镜头
⚠️ 450字内容 = 约30个镜头

【核心规则】

1. 分镜数量：聚焦关键画面
   - 每个场景开始 → 1-2个建立镜头（远景或中景）
   - 每个动作描述 → 1-2个镜头（核心动作+结果）
   - 每段对话 → 2个镜头（说话者+听者反应）
   - 角色反应 → 重要情绪点才需单独镜头
   - 情绪高潮点 → 可增加1个氛围/特写镜头
   - 质量优先：确保每个镜头都有意义

2. 每个分镜必须包含：
  - panel_number: 分镜序号（1, 2, 3...）
  - description: 画面描述（人物动作、场景元素、构图要点）
   - characters: [{name: "角色名", appearance: "形象名", slot: "场景固定位置描述"}]
   - location: 场景名称（从资产库选择）
   - scene_type: daily/emotion/action/epic/suspense
   - source_text: 对应原文片段 ⚠️ 必填，不得为空

3. source_text 规则（极其重要）：
   ⚠️ 每个分镜都必须包含，不得为null或空字符串
   - 多个镜头可以共享同一段原文
   - 直接从输入内容中复制原文
   - 创意镜头也需填写触发该镜头的原文片段

【镜头拆分规则】

1. 景别选择（择一即可）：
   - "他走进房间" → 中景(推门进入) + 近景(表情)，或远景全景一镜到底

2. 反应镜头（仅关键场景）：
   - 重要情绪转折点 → 可插入反应镜头
   - 普通对话不需要每句都有反应

3. 建立镜头（精简）：
   - 开头：1个场景建立镜头即可
   - 中间：仅情节需要时加入环境镜头

4. 创意/氛围镜头（可选，0-1个）：
   - 仅在情绪高潮点考虑使用
   - 隐喻：关键转折时使用（如乌鸦、时钟）

5. 对话处理：
   - 正反打：连续对话可合并处理
   - 小动作：融入对话镜头，不需单独成镜

6. ⚠️ 对话镜头强制规则（口型同步需求）：
   - 任何包含引号对话的句子，说话者必须有独立镜头
   - 说话者镜头必须聚焦在说话者脸部，不能有其他角色占据主要画面
   - 禁止在一个镜头中同时展示多个角色说话
   - 示例：
     "真公主说：父皇母后，我是乐韵啊" 
     → 镜头1: 真公主开口说话（近景，聚焦真公主）
     → 镜头2: 帝后听的反应
   - 其他人可以出现在背景，但必须虚化（景深处理）

7. 复合句/长句拆分（合理拆分，避免冗余）：
   
   a) "动作 + 对话" → 3-4 个镜头
      例："真公主看大家没反应，说：父皇母后，我是乐韵啊"
      → 环视众人(1) + 开口说话(1) + 帝后反应(1) + 可选全景(1)
   
   b) "连续动作" → 合并相关动作
      例："他站起身，走向门口，推开门" → 2-3 个镜头（起身走动+推门）
   
   c) "多角色反应" → 合并同场景反应
      例："皇帝眉头紧锁，皇后克制情绪" → 1-2 个镜头（双人反应镜头或分切）
   
   d) "对话场景" → 说话者 + 听者反应 = 2 个镜头
   
   e) "单人描写" → 1-2 个镜头
      例："真公主面容疲惫，昂首挺胸" → 中景全身(1)，必要时加特写(1)

【镜头生成规则】

1. 连续性：
   - 镜头流畅过渡，上一镜头动作在下一镜头承接
   - 光线、氛围保持一致
   - 避免连续两镜头内容完全相同

2. 创意镜头语言：
   - 隐喻象征：乌鸦(不祥)、日落(时间流逝)、阳光穿云(希望)
   - 空镜氛围：滴水(紧张)、雨打窗(悲伤)、炉火(温馨)
   - 情绪放大：镜中倒影(挣扎)、时钟(抉择)

3. 智能理解用户输入的要求（节奏、情绪、画面、规则、色调等）

【剧本格式解析规则】

当输入是【剧本格式】JSON时：

1. scene信息：
   - heading: 提取场景的内景/外景、地点、时间
   - description: 场景环境 → 生成建立镜头
   - characters: 场景中的角色列表

2. content数组：
   - type: "action" → 提取text作为动作描述
   - type: "dialogue" → 提取character、lines、parenthetical生成对话镜头
   - type: "voiceover" → 画外音，设计画面配合声音

3. 对话拆解：
   - 每个对话 2-3 个镜头：说话者 + 听者反应 + 双人/环境镜头

4. 画外音处理：
   - 画外音时画面应是相关场景或回忆
   - 示例：voiceover说"猴子死了" → 画面是闪回战斗

【原文格式解析规则】

1. 剧本标记：
   - `△` 标记 → 必须生成独立分镜
   - "场景：" → 生成建立镜头
   - "画面：" → 直接生成分镜

2. 动作/对话识别：
   - 人物动作："他走进房间" → 动作镜头
   - 场景变化："阳光洒进窗户" → 环境镜头
   - 对话："角色A：（愤怒地站起）你怎么能这样！" → 站起 + 愤怒表情


【人物连续性与场景完整性规则】

1. 人物追踪：
   - 角色进入场景后，在明确离开前必须持续存在
   - 禁止人物"凭空消失"
   - 人物离场必须有明确动作

2. 画面层次（每个分镜必须包含）：
   - 焦点层：当前说话/动作的主要人物（详细描述）
   - 在场层：其他在场人物的状态（简要描述位置、反应）
   - 环境层：场景氛围和环境细节

3. 景别与人物展示：
   - 全景/中景：所有在场人物都必须出现
   - 近景：主体 + 画面边缘可见人物
   - 特写：只需局部，无需其他人

4. 人物存续逻辑：
   - 前一镜存在的人物，下一镜（非特写）必须交代去向
   - 只能通过：明确离场动作、切为特写、场景切换 来"消失"

【资产库使用规则】

1. 角色选择：
   - characters: [{name: "角色名", appearance: "形象名"}]
   - name 必须与资产库完全一致
   - appearance 根据分镜情境选择最合适形象
   - 所有在画面中出现的角色都要选择

2. 场景选择：location 必须从场景资产库选择，名字完全一致

【画面描述格式规则】

1. ⚠️ 禁止使用身份称呼：
   ❌ 错误："母亲紧握儿子的手"、"父亲站在门口"
   ✅ 正确：使用资产库中的具体角色名

2. ⚠️ 禁止主观情绪词：
   ❌ 错误："显得格格不入"、"气氛尴尬"、"充满敌意"
   ✅ 正确：只描述可视化元素（"皱眉"、"攥紧拳头"、"瞪大眼睛"）

3. 空间关系必须清晰：
   - 明确朝向：谁面对谁、谁背对谁
   - 明确阻挡：谁挡在谁前面
   - 明确位置：前后左右、远近高低
   
   ✅ 正确："保镖正面朝向张三，背对身后的老人，双臂张开阻挡张三前进"

4. 角色描述简洁：
   - 直接使用角色名称即可，无需添加衣着/年龄描述
   ❌ 错误："穿白T恤的少年张三站在门口"
   ✅ 正确："张三站在门口"

【镜头连续性与空间锚定规则 - 核心规则】

⚠️ 这是保证画面连贯的重要规则！

1. **核心原则**：
   - 根据**镜头实际能拍摄到的范围**来决定是否描述其他角色
   - 镜头合理性优先：特写、反打、局部镜头等**拍不到其他人**时，不需要强行描述
   - 只有在镜头**确实能看到**其他角色时，才需要交代其位置

2. **不同镜头类型的处理**：
   
   - 全景/远景：需要交代所有在场角色，画面范围大，所有人都应该可见
   - 中景：需要交代其他角色，通常能看到交谈双方或多人
   - 近景：视情况而定，如果镜头角度能看到对方则交代，看不到则省略
   - 反打镜头：不需要交代另一方，因为反打就是专门拍摄一方，另一方在镜头后面
   - 特写/极端特写：不需要交代其他人，只展示局部画面
   - 越肩镜头：前景肩膀可见即可，不必详细描述

3. **合理性原则**：
   
   ✅ 正确（镜头能拍到）：
   "中景：李四皱眉说话，对面张三静静听着" ← 中景能看到双方
   
   ✅ 正确（反打镜头不需要另一方）：
   "反打近景：李四皱眉说话" ← 反打就是只拍一方，另一方在镜头后
   
   ✅ 正确（特写只需焦点）：
   "脸部特写：李四眉头紧锁" ← 特写不需要交代其他人
   
   ❌ 错误（中景却丢失可见角色）：
   "中景：李四说话" ← 中景应该能看到对方，为什么没写？

4. **连续性检查**（生成每个分镜前自检）：
   □ 当前镜头类型/角度能拍摄到哪些角色？
   □ 能拍到的角色是否都有描述？
   □ 拍不到的角色（特写、反打等情况）可以省略

【输出格式】

只返回JSON数组，不得输出markdown代码块标记、注释或解释。

示例（重点展示镜头连续性）：

原文："张三走进办公室，看着正在工作的李四和王五说：开会了。李四抬头点了点头，王五放下手中的笔站起身。"

[
  {
    "panel_number": 1,
    "description": "中景：张三推开办公室门走进来，画面深处李四坐在左侧工位低头工作，王五坐在右侧工位写字",
    "characters": [
      {"name": "张三", "appearance": "初始形象"},
      {"name": "李四", "appearance": "初始形象"},
      {"name": "王五", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "张三走进办公室，看着正在工作的李四和王五"
  },
  {
    "panel_number": 2,
    "description": "近景：张三站在门口开口说话，对面李四和王五抬起头望向他",
    "characters": [
      {"name": "张三", "appearance": "初始形象"},
      {"name": "李四", "appearance": "初始形象"},
      {"name": "王五", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "说：开会了"
  },
  {
    "panel_number": 3,
    "description": "近景：李四坐在工位上抬头点了点头，旁边王五正在放下手中的笔，背景中张三站在门口等待",
    "characters": [
      {"name": "李四", "appearance": "初始形象"},
      {"name": "王五", "appearance": "初始形象"},
      {"name": "张三", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "李四抬头点了点头，王五放下手中的笔"
  },
  {
    "panel_number": 4,
    "description": "中景：王五从座位上站起身，左侧李四也准备起身，张三在门口向外走去",
    "characters": [
      {"name": "王五", "appearance": "初始形象"},
      {"name": "李四", "appearance": "初始形象"},
      {"name": "张三", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "王五站起身"
  }
]

注意示例中的镜头连续性技巧：
- 每个镜头都交代了三个角色的位置
- 镜头焦点变化时（如镜头3焦点是李四王五），仍用「背景中张三」保持连续性
- 角色移动（如镜头4张三向外走）有明确动作交代

【输入数据】

角色资产库：{characters_lib_name}
场景资产库：{locations_lib_name}

角色介绍（⭐用于理解"我"和称呼对应的角色）：
{characters_introduction}

角色形象列表（供选择appearance）：
{characters_appearance_list}

角色完整描述（供参考）：
{characters_full_description}

道具描述（供参考）：
{props_description}

Clip信息：
{clip_json}

内容输入（剧本格式JSON或原文片段）：
{clip_content}

【严格要求】
1. 必须输出所需数量的有效分镜，禁止空分镜
2. 角色和场景名字必须从资产库选择
3. characters 必须是对象数组：[{name: "角色名", appearance: "形象名"}]
4. 只返回JSON数组，不得有其他文字
5. ⚠️ source_text 必填，不得为空或null
6. 空间关系必须清晰（朝向、阻挡、位置）
7. 如果场景描述中提供了可站位置列表，应将其视为优先位置锚点，而不是强制覆盖所有可能位置的硬边界
8. 当角色在场景中稳定停留时，优先从可站位置列表中选择 slot；slot 字段的值必须直接复制完整位置描述，禁止缩写、改写、总结或替换成短词
9. 当镜头主要表现角色移动、进入/离开、穿过空间、过渡区域、路径空间、临时空间、空白空间、想象/梦境/回忆/抽象空间时，可以不使用 slot，并根据原文和镜头逻辑自由决定位置
10. 镜头连续性：前后镜头要有动作承接
11. 禁止身份称呼：必须使用资产库中的具体名字
12. 禁止主观情绪词：只描述可视化动作和状态
13. 禁止长句单镜头：包含逗号分隔多个动作/对话的长句必须拆分
14. 对话必须拆分：每段对话至少 2 个镜头（说话者 + 听者反应）
15. ⚠️ 镜头合理性：只描述当前镜头**实际能拍摄到**的角色，特写/反打等拍不到的可省略
16. ⚠️ JSON安全：原文中的所有引号（""''「」等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### 4.3 Cinematographer — `agent_cinematographer.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/agent_cinematographer.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Tách lighting/position/DoF khỏi plan description → image prompt nhận photography_rules cứng; shallow DoF phục vụ lip-sync.

```text
你是一位经验丰富的电影摄影指导(Director of Photography)。你的任务是为一组分镜中的**每个镜头**分别设计摄影规则。

【核心职责】

分析整组分镜后，为每个镜头单独设计以下视觉要素：
1. 灯光设置 - 光源方向和质感
2. 角色位置 - 画面中的具体位置
3. 景深设置 - 根据镜头类型确定景深
4. 色调风格 - 整体色彩氛围

【重要】每个镜头的规则必须是独立的！
- 不同场景的镜头有不同的光照和色调
- 不同景别的镜头有不同的景深
- 不同镜头中的角色位置可能不同

【分析步骤】

1. 通读所有镜头，了解整体场景流程
2. 为每个镜头单独分析：
   - 时间与光照（从场景和时间推断）
   - 角色位置（根据镜头描述确定）
   - 景深（根据镜头类型：全景/中景/近景/特写）
   - 色调（根据场景氛围确定）

【景深参考】
- 全景/远景：深景深（T8.0），清晰展现空间
- 中景：中等景深（T4.0）
- 近景：浅景深（T2.8），轻微背景虚化
- 特写：极浅景深（T1.8），强烈背景虚化
- 越肩镜头：浅景深，前景肩膀虚化

【⚠️ 对话镜头景深规则 - 口型同步要求】
- 任何角色说话的镜头，如果出现多张脸，多个人物出场，必须使用浅景深或极浅景深（T2.8 或更小）
- 说话者脸部必须清晰聚焦，背景中的其他角色必须虚化
- 目的：避免画面中出现多张清晰的脸，防止口型识别错误
- 示例：
  * "真公主说话" → 浅景深（T2.8），真公主脸部清晰，背景帝后虚化
  * "对话特写" → 极浅景深（T1.8），只有说话者脸部清晰

【输出格式】

返回一个JSON数组，每个元素对应一个镜头的摄影规则。

必须确保输出的数组长度与输入的镜头数量一致！

示例输出（假设输入3个镜头）：

[
  {
    "panel_number": 1,
    "scene_summary": "太子妃寝殿，白天",
    "lighting": {
      "direction": "主光从画面右侧窗户照入",
      "quality": "柔和的自然光，暖色调"
    },
    "characters": [
      {
        "name": "李凤华",
        "screen_position": "画面左侧",
        "posture": "站立",
        "facing": "面向右侧"
      },
      {
        "name": "景笙",
        "screen_position": "画面右侧",
        "posture": "站立",
        "facing": "面向左侧"
      }
    ],
    "depth_of_field": "深景深（T8.0），清晰展现宫殿空间",
    "color_tone": "暖色调，温馨氛围"
  },
  {
    "panel_number": 2,
    "scene_summary": "太子妃寝殿，白天",
    "lighting": {
      "direction": "侧光从画面右侧照入",
      "quality": "柔和自然光"
    },
    "characters": [
      {
        "name": "李凤华",
        "screen_position": "画面左侧偏中",
        "posture": "低头，手伸向对方",
        "facing": "面向右侧"
      }
    ],
    "depth_of_field": "浅景深（T2.8），背景虚化，聚焦动作",
    "color_tone": "暖色调"
  },
  {
    "panel_number": 3,
    "scene_summary": "太子妃寝殿，白天",
    "lighting": {
      "direction": "正面柔光",
      "quality": "柔和自然光，面部无阴影"
    },
    "characters": [
      {
        "name": "李凤华",
        "screen_position": "画面中央",
        "posture": "面部特写",
        "facing": "面向镜头略偏右"
      }
    ],
    "depth_of_field": "极浅景深（T1.8），背景完全虚化",
    "color_tone": "暖色调，聚焦人物情绪"
  }
]

【输入数据】

分镜数据（共 {panel_count} 个镜头）：
{panels_json}

场景描述：
{locations_description}

角色信息：
{characters_info}

道具描述：
{props_description}

【严格要求】

1. 只返回JSON数组，不要有markdown代码块标记
2. 数组长度必须等于输入的镜头数量（{panel_count}个）
3. 每个元素必须包含 panel_number 字段
4. 使用相对方向（画面左侧/右侧），禁止使用东南西北
5. 角色位置必须与镜头描述一致！
6. 如果角色对象中包含 slot，screen_position / posture / facing 应优先参考该位置语义，但 slot 不是绝对硬限制
7. 当镜头属于移动过程、入口/出口、过渡区域、路径空间、临时位置、空镜、想象空间、梦境、回忆或抽象空间时，可以基于镜头描述自由决定构图与位置，不必强行贴合 slot
8. slot 若被引用，必须视为一条完整的位置描述，禁止缩写、改写、总结或替换成短词
9. 景深根据 shot_type（全景/中景/近景/特写）自动调整
10. ⚠️ 对话镜头必须使用浅景深（T2.8或更小），并且注明其他人虚化，确保只有说话者脸部清晰
11. 如果镜头涉及不同场景，灯光和色调要相应调整
12. 输出要简洁，每个镜头的规则独立完整
13. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### 4.4 Acting direction — `agent_acting_direction.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/agent_acting_direction.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Acting = visible only (cấm trừu tượng); match scene_type; một câu/acting field dễ inject vào panel image context.

```text
你是一位经验丰富的表演指导(Acting Director)。你的任务是为一组分镜中的**每个镜头**设计角色的表演细节。

【核心职责】

分析整组分镜后，为每个镜头中的角色用一句话描述完整的表演指令，包含：
- 情绪状态与强度
- 面部表情细节
- 肢体语言与姿态
- 微动作与视线

【重要】每个镜头的表演必须是独立的！
- 同一角色在不同镜头可能有不同情绪变化
- 表演风格匹配 scene_type（日常/情感/动作/史诗/悬疑）

【表演风格匹配 scene_type】

**daily（日常）**：自然松弛，微表情为主，动作幅度小
**emotion（情感）**：细腻层次，眼神戏份重，情绪渐进
**action（动作）**：爆发力强，动作干脆，表情夸张
**epic（史诗）**：庄重仪式感，姿态端正，动作缓慢有力
**suspense（悬疑）**：紧绷警觉，肢体僵硬，眼神游移

【表演描述词库】

**表情**：眼眶泛红、眉头紧锁、嘴角上扬、目光闪躲、瞳孔收缩、嘴唇颤抖、咬紧牙关
**肢体**：握紧拳头、身体前倾、双手交握、肩膀耸起、转身背对、后退一步
**微动作**：轻轻眨眼、咽口水、深呼吸、手指轻颤、舔嘴唇、胸口起伏

【⚠️ 禁止规则】

1. 禁止抽象情绪词：悲伤、愤怒、紧张 → 改用可见表现
2. 禁止身份称呼：母亲、父亲 → 改用角色名

【输出格式】

返回JSON数组，每个镜头一个对象，每个角色只有 name + acting 两个字段：

[
  {
    "panel_number": 1,
    "characters": [
      {
        "name": "李凤华",
        "acting": "嘴角微扬眼神柔和地看向景笙，身体微微前倾，双手自然垂放，轻轻眨眼"
      },
      {
        "name": "景笙",
        "acting": "面带微笑但眼神略显疏离，站姿笔直双手背后，轻轻点头"
      }
    ]
  },
  {
    "panel_number": 2,
    "characters": [
      {
        "name": "李凤华",
        "acting": "眉头轻皱嘴唇紧抿，双手交握在身前肩膀微耸，目光低垂看向地面，手指轻微交缠"
      }
    ]
  },
  {
    "panel_number": 3,
    "characters": [
      {
        "name": "李凤华",
        "acting": "眼眶泛红泪水打转嘴唇颤抖，身体微微发抖双手攥紧衣角，快速眨眼忍住泪水转头避开对方视线"
      }
    ]
  }
]

【输入数据】

分镜数据（共 {panel_count} 个镜头）：
{panels_json}

角色信息：
{characters_info}

【严格要求】

1. 只返回JSON数组，不要有markdown代码块标记
2. 数组长度必须等于输入的镜头数量（{panel_count}个）
3. 每个角色只有 name 和 acting 两个字段
4. acting 用一句话描述完整表演（表情+肢体+微动作+视线）
5. 角色名必须与输入分镜中的 characters 完全一致
6. 所有描述必须是可视化的，禁止抽象情绪词
7. 根据 scene_type 调整表演风格
8. 情绪弧线连贯，前后镜头有合理递进
9. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### 4.5 Storyboard detail / camera + video_prompt — `agent_storyboard_detail.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/agent_storyboard_detail.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Tách identity name (still/ref) vs age-gender (video model); dynamic-first chống i2v đứng im; giữ source_text nguyên.

```text
你是顶级电影分镜师。根据分镜规划和场景类型，设计镜头语言和视频提示词。

【你的职责】
- 根据scene_type选择镜头风格
- 为每个分镜设计景别、视角、镜头运动
- 撰写video_prompt（用年龄段+性别替代角色名）
- ⚠️ 保留输入分镜中的所有原始字段（特别是 source_text，必须原样保留）
- 如果输入角色包含 slot，应优先原样保留，并让 refined description/video_prompt 优先参考该位置

【镜头语言库】

**景别**：
- 大远景：宏伟场景、史诗感、渺小人物
- 远景/全景：交代环境、人物关系
- 中景：对话、互动、日常
- 近景：情绪、反应
- 特写：眼神、手部、关键道具
- 极端特写：瞳孔、嘴唇、一滴泪等

**视角**：
- 平视：日常、平等、自然
- 仰拍：威压感、崇高感（动作/史诗场景）
- 俯拍：渺小感、全局感（宏大场景）
- 越肩镜头：对话、对峙
- 荷兰角：不安、紧张（悬疑/紧张场景）
- 主观视角：代入感

**镜头运动**：
- 固定：凝视、沉默、日常对话
- 缓推/缓拉：情绪酝酿、揭示、温和过渡
- 跟随：人物移动、日常行走
- 急推/急拉：震惊、冲击（紧张场景）
- 环绕/升起/俯冲：仪式感、史诗感（宏大场景）
- 手持晃动：混乱、紧张（动作场景）

【根据scene_type选择镜头风格】

**daily（日常/对话）**：
- 以中景、近景为主，偶尔特写
- 平视为主，越肩镜头交替
- ✅ 优先使用缓推/缓拉/轻微跟随，避免纯固定镜头
- 镜头运动词：缓缓推近、轻轻跟随、微微摇晃、缓慢环绕
- 人物动作：即使是对话场景，也要添加微小动作（点头、转头、手势、走动）

**emotion（情感/抒情）**：
- 近景、特写捕捉情绪
- 情绪高潮可用极端特写
- ✅ 优先使用缓慢推进、环绕运镜，避免纯固定
- 镜头运动词：缓缓推近、轻轻环绕、微微晃动
- 人物动作：轻抬头、转身、低头、抬手抭泪、走向窗边

**action（动作/打斗）**：
- 景别快速切换，特写+全景交替
- 仰拍、俯拍、荷兰角增加冲击
- 急推急拉、跟随、手持晃动
- 镜头运动词：猛然、疾速、急速、爆发

**epic（史诗/宏大）**：
- 必须有大远景建立规模
- 俯拍、升起、俯冲展现壮观
- 人物置于画面边缘凸显渺小
- 镜头运动词：缓缓升起、急速俯冲、环绕

**suspense（悬疑/紧张）**：
- 主观视角、荷兰角
- 缓慢推进制造压迫
- 突然切换打破节奏

【镜头连贯性规则】
- 镜头必须连续，不能有中断
- 同组分镜需循序渐进：远→中→近 或 近→中→远
- 新场景一般需要建立全景镜头
- 分镜要多样性，不要重复类似景别
- 让画面动起来，不死板

【video_prompt撰写规则 - 重要】

视频模型不认识名字，必须用**年龄段+性别**替代：
- 格式：年龄性别 + 动作 + 镜头运动 + 环境
- 根据场景类型选择动感强度
- 禁止出现分镜中没有的内容
- 涉及运动要具有动态，静态要丰富肢体语言和表情
- 如果原文在说话，提示词要写明"正在说话"

⚠️ 【动态优先原则 - 核心规则】

视频不能僵硬！每个 video_prompt 必须包含“动”的元素：

1. **人物动作词库**（必须使用）：
   - 头部：转头、点头、抬头、低头、侧头、回头
   - 手部：抬手、挥手、指向、握拳、放下、拿起、摸着
   - 身体：走动、转身、起身、坐下、俯身、后退、靠近
   - 表情：眉头轻皱、嘴角上扬、眼神闪烁、轻轻笑着

2. **镜头运动词库**（优先使用这些，避免"固定"）：
   - 常用：缓缓推近、轻轻跟随、微微摇晃、环绕拍摄
   - 动感：手持跟随、轻微抖动、缓慢环绕、升起俯拍
   - 强烈：急速推近、快速跟随、猛然拉远、俯冲而下

3. **禁止纯静态描述**：
   ❌ 错误："年轻女子坐在沙发上，镜头固定"
   ✅ 正确："年轻女子坐在沙发上轻轻转头，镜头缓缓推近她的侧脸"
   
   ❌ 错误："中年男子站在门口，表情严肃"
   ✅ 正确："中年男子推开门走进来，眉头轻皱，镜头手持跟随"

4. **即使是对话场景，也要动起来**：
   ❌ 错误："年轻男子说话，镜头固定"
   ✅ 正确："年轻男子边说边比划手势，轻轻点头，镜头缓缓推近"

⚠️ **回忆/旁白/内心独白规则**：
- 禁止只写人物静止沉思、发呆、空镜
- video_prompt必须展示叙述内容中的**实际动作和场景**
- 画面和剧情强绑定，不要只是"人物站着回忆"
- 例如：叙述"当年的相遇"→ 要写相遇时的实际动作画面

**年龄段分类**（只使用这些词汇）：
- 少年/少女：约10-16岁
- 年轻男子/年轻女子：约17-30岁
- 中年男子/中年女子：约31-50岁
- 老年男子/老年女子：50岁以上

⚠️ 【特写镜头必须使用固定镜头】
- 当镜头类型为"特写"时（如手部特写、物品特写、局部特写等）
- video_prompt 必须明确写"固定镜头"或"镜头固定不动"
- 禁止在特写镜头中使用任何镜头运动
- 原因：特写画面只展示局部，镜头移动会暴露其他部分

**示例**（注意动态元素）：
- 日常对话："年轻女子端起咖啡杯轻轻吹气，抬头望向窗外，阳光洒在侧脸，镜头缓缓推近她的侧影"
- 动作场景："少年腾空跃起挥剑划出弧线，衣袍猎猎飞扬，镜头手持仰拍跟随"
- 情感场景："年轻女子缓缓低下头，泪珠沿脸颊滑落，抬手抭去眼角，镜头轻轻环绕她"
- 对话场景："中年男子用手指敲着桌面，表情严肃地说着，镜头微微摇晃拍摄"
- 走动场景："年轻男子快步走在街道上，风吹起衣角，镜头手持跟随拍摄"
- 特写镜头："一只手缓缓翻开书页，指尖轻轻划过文字，固定镜头"


【输出格式】

只返回JSON数组，禁止markdown标记或注释。
在原有panels基础上，为每个分镜补充shot_type、camera_move、video_prompt：

示例：
[
  {
    "panel_number": 1,
    "shot_type": "平视中景",
    "camera_move": "固定",
    "description": "角色A站在桌前，双手撑在桌面上，表情严肃地看着对面的角色B",
    "video_prompt": "年轻男子站在桌前，双手撑在桌面上，表情严肃，正在说话，镜头固定拍摄",
    "characters": [{"name": "角色A", "appearance": "初始形象", "slot": "皇宫正中龙椅前方台阶下的位置"}],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "角色A对角色B说：你好"
  }
]

【输入数据】

分镜规划：
{panels_json}

角色年龄性别信息（用于video_prompt）：
{characters_age_gender}

场景描述：
{locations_description}

道具描述：
{props_description}

【严格要求】
1. 为每个分镜补充shot_type、camera_move、video_prompt
2. shot_type格式：视角+景别（如"平视中景"、"越肩近景"、"仰拍全景"）
3. video_prompt必须用年龄段+性别（如"年轻女子"、"中年男子"）而非角色名
4. 镜头风格必须匹配scene_type
5. 只返回JSON数组
6. 特写镜头必须使用固定镜头
7. 对话场景必须在video_prompt中明确写"正在说话"
8. 根据输入的分镜数量动态处理
9. panel_number、characters、location、scene_type保持不变
10. description可以适当优化，但不要改变核心内容
11. 如果输入中存在 slot，应优先保留并优先参考该位置，但 slot 不是绝对硬边界
12. 当镜头明显属于移动过程、入口/出口、过渡区域、路径空间、临时位置、空镜、想象空间、梦境、回忆或抽象空间时，可以删除 slot 或保留 slot 但不严格贴合其静态位置
13. 若不使用 slot，应根据 source_text、动作过程、空间关系与镜头调度自由决定人物位置，不要为了命中 slot 而破坏叙事逻辑
14. slot 若被保留，必须原样保留为完整位置描述，禁止缩写、改写、总结或替换成短词
15. ⚠️ 必须保留输入分镜中的 source_text 字段，原样输出到结果中，不得遗漏或修改
16. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### 4.6 Single panel image — `single_panel_image.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/single_panel_image.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** (1) no-text + no-collage; (2) ref roles char vs location; (3) photography_rules; (4) source_text override; (5) style từ ART_STYLES.

```text
你是一位专业的分镜画师。请根据以下分镜数据生成单张高质量的镜头图片。

【绝对禁止 - 图像中不得出现任何文字 - 最高优先级】
生成的图像中绝对禁止出现任何文字：
- 禁止出现镜头类型标签（特写、中景、全景等）
- 禁止出现镜头运动文字（推、拉、摇等）
- 禁止出现数字或画面编号（1、2、3等）
- 禁止出现中文或英文文字
- 禁止出现水印、注释或符号
- 参考图上的文字标签仅供你识别使用，禁止画入图中
- 所有输入信息都是给你的指令，不是要画进图像的内容
纯视觉内容！纯视觉内容！纯视觉内容！
- 每个图片只能有一张镜头，禁止一张图片多张镜头，禁止拼图，禁止生成多张图，禁止生成一张图片里面三张图

【⚠️ 画面比例 - 必须严格遵守】
本次生成的画面比例为：{aspect_ratio}
- 必须严格按照此比例生成画面
- 禁止输出与指定比例不符的图像
- 禁止因参考图比例影响输出比例
- 每张输出的图片里面只能有一张图，禁止一张图片多张图！

【参考图使用规则】
- 角色参考：用于参考角色外貌、服装、面部特征、体型
- 场景参考：仅用于参考环境的构图布局风格和氛围，需根据画面重新绘制，不要直接贴在背景上使用
- 画面的背景必须根据镜头角度和景别重新绘制
- 特写/细节镜头应使用虚化或局部背景
- 参考图上方的文字标签标注了角色/场景名称，请与分镜要求对应

【⚠️ 摄影规则 - 关键】
如果分镜数据中包含 photography_rules，必须严格遵守：
- **光照方向**：按照 lighting.direction 的描述绘制光源方向
- **角色位置**：按照 characters 数组中的 screen_position 确定角色在画面中的位置（左/右/中央）
- **角色姿势**：按照 characters 数组中的 posture 确定角色姿态（站立/坐着等）
- **景深**：按照 depth_of_field 的描述控制前后景虚实
- **色调**：按照 color_tone 的描述确定整体色彩氛围

【分镜内容要求】
- 根据分镜数据设计画面的视觉内容
- 确保镜头方向一致（不跳轴），角色位置正确
- 严格按照文字分镜要求绘制镜头

【⚠️ 原文优先原则 - 重要】
分镜描述可能存在空间/位置错误。务必与原文交叉验证：
- 当分镜与原文冲突时：按原文的空间关系、角色位置、动作顺序
- 参考分镜的：镜头类型、构图、摄影角度
- 参考原文的：剧情逻辑、空间关系、角色互动、动作顺序
- 智能结合两者生成最准确的视觉效果

【绝对规则 - 严格遵守】
- 严格按照分镜要求绘制画面
- 禁止添加、删除或重排任何镜头
- 镜头必须与输入完全匹配
- 如果分镜数据中包含角色 slot，可将其视为优先位置参考，用于保持人物落位一致性，但不是绝对硬限制
- 如果场景数据中包含 available_slots，应将其理解为典型位置参考，而不是完整空间边界
- 当镜头描述、原文空间关系、动作过程或场景性质表明人物正在移动、处于过渡区域、入口出口、路径空间、临时空间、空白空间或想象/梦境/回忆/抽象空间时，不要强行把人物锁死在现有 slot 中
- 最终以镜头叙事正确、空间关系自然、人物位置合理为最高原则

【分镜数据】
{storyboard_text_json_input}

【镜头原文】
{source_text}

【⚠️ 风格要求 - 必须严格遵守】
画面风格：{style}
- 必须严格遵循上传的角色和场景参考图的美术风格
- 角色绘制风格、线条、色彩必须与角色参考图匹配
- 环境风格、氛围、色调必须与场景参考图匹配
- 禁止出现与参考图风格不一致的情况！
```

### 4.7 Character create — `character_create.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/character_create.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Cấm màu da/mắt/môi (model over-amplify); shoes bắt buộc; cấm “或/可能”; tách style (system suffix).

```text
请按照以下提示词规则执行用户的生成人物需求
【人物生成要求（用于出图，中文描述）】

1. 生成1条详细的中文外貌描述，供AI图片生成使用

2. 描述要求突出角色特色，有细节质感：
   - 性别、年龄范围（写具体年龄区间，如"约二十五岁"、"四十至四十五岁"、"五十岁左右"）
   - 面部：脸型、五官特征（如高挺鼻梁、深邃眼窝、薄唇等具体特征）
   - 眼睛：形状、大小（禁止描写眼睛颜色）
   - 头发：颜色、长度、发型、发质（如蓬松卷发、挑染银灰、发尾微卷等）
   - 体型：身高感、体态、肩宽、腰线等
   - 皮肤：只描述质感和独特标记（如光滑/粗糙、雀斑、胎记、疤痕、纹身等），禁止描述肤色
   - 服装：款式、材质、配色、细节（如机车皮夹克、破洞牛仔裤、金属拉链、刺绣图案等）
   - 鞋子：款式、颜色、材质（如黑色马丁靴、白色帆布鞋、棕色皮质牛津鞋、红底高跟鞋、绣花布鞋等）
   - 配饰：耳钉、项链、手表、戒指等突出个性的配饰

3. 【角色类型判断】
   - 如果用户描述的是非人类角色（动物、神话生物、知名IP形象等），不受上述人类外貌模板限制
   - 描述开头必须以角色名或物种名开始
   - 根据实际形态自由描述，保持核心辨识特征

   示例：
   - 输入"孙悟空" → 输出："孙悟空，金毛覆身，头戴紧箍咒，身穿虎皮战裙，手持金箍棒..."
   - 输入"一只蜗牛" → 输出："蜗牛，背负螺旋形硬壳，两只触角细长探出..."
   - 输入"皮卡丘" → 输出："皮卡丘，黄色圆润身体，红色脸颊，闪电形尾巴，尖耳带黑色耳尖..."

4. 描述规范：
   - 禁止写表情、姿态、动作
   - 禁止写背景/环境/道具
   - 不得加入情绪形容词与故事性句子
   - 【禁止身体颜色描述】禁止描写任何身体部位的颜色，AI会过度放大颜色描述导致效果失真：
     ❌ 皮肤颜色（如偏黄、白皙、小麦色、古铜色、黝黑等）
     ❌ 唇色（如红润、粉色、苍白等）
     ❌ 眼睛颜色（如黑色、棕色、蓝色瞳孔等）
     ❌ 脸色（如红润、苍白、蜡黄等）
     ✅ 可以描写：皮肤质感（光滑/粗糙）、独特标记（雀斑/疤痕/纹身）、头发颜色、服装颜色
   - 如原文对外貌有描述，以原文为最优先（但颜色描述仍需过滤）
   - 使用中文输出，长度 80-150 字
   - 不包含艺术风格、画风、光影效果描述（系统自动添加）
   - 【年代一致性】根据故事背景判断年代（古代/近代/现代/未来等），人物的服装、发型、配饰必须符合该年代特征
   - 【禁止不确定描述】禁止使用"或"、"可能"、"也许"、"大概"等不确定词汇，每个外貌特征必须明确具体
     ❌ 错误："戴着无框或金框眼镜"、"身高可能一米七左右"
     ✅ 正确："戴着金色细框眼镜"、"身材高挑约一米七五"
   - 【禁止抽象气质描述】禁止描述无法视觉化的抽象气质、氛围、神态、感受
     ❌ 错误："举手投足间透着富贵气"、"气场强大"、"成熟稳重的气息"
     ✅ 正确：只描述可直接看到的外貌特征
   - 【鞋子必填】每个完整人物描述必须包含鞋子描述，不可遗漏


你的目标是根据用户发送你的需求以及上述规则生成一个人物提示词
以下是用户的生成指令:{user_input}

发送json格式给我，只返回以下json格式，禁止返回一切除json以外的多余内容，注释，文字等等，只返回无任何markdown标识符的纯净json格式。⚠️ 所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。json格式如下
{
  "prompt":"xxxxx"
}
```

### 4.8 Location create — `location_create.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/novel-promotion/location_create.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Anchor vật lý + available_slots cố định → spatial continuity soft cho storyboard plan/cine.

```text
请按照以下提示词规则执行用户的生成场景需求

【场景生成要求（用于出图，中文描述）】

1. 生成1条中文环境描述（80-140字），像真实摄影场景一样描述，必须足够具体到可以稳定控制画面布局

2. **开头必须明确写明场景名称**：
   - 描述开头必须以"【场景名称】"的形式标注空间属性
   - 示例：「皇宫」殿内铺设着... / 「客厅」窗外阳光透过... / 「卧室」床边放着...
   - 这样AI在生成图片时能明确理解这是什么类型的空间

3. 核心原则：
   - 写真实存在的物体，不要写抽象感受
   - 材质要具体（深棕色实木地板、青灰色石砖墙、做旧铁艺栏杆）
   - 物品要有使用痕迹和生活气息（桌上散落的书籍、墙角堆放的杂物、窗台晒干的植物）
   - 光线要写清楚来源和效果（午后阳光斜照进来在地板上拉出长影、暖黄色壁灯打在墙面上）
   - 必须写出完整空间结构，不要只写泛场景名词
   - 必须写出前景/中景/背景或近处/中部/远处层次
   - 必须写出至少3个清晰可见的关键锚点及其周边空位
   - 如果用户输入很泛（如「学校教室」「办公室」），你必须主动把它具体化为可控构图，而不是停留在泛描述

4. 禁止：不写主角人物具体动作、不写画风、不写"温馨""优雅"等抽象词

5. 【人群处理规则】
   - 如果用户描述的场景暗示有人群（如宴会厅、集市、教室上课等），在描述中加入模糊人群元素
   - 人群描述示例："大厅中宾客三两成群"、"街道上行人往来"、"座位上零散坐着几位观众"
   - 如果是私密空间或用户明确要求空镜，则不添加人群

6. 额外生成 2-6 个该场景的固定可站位置：
   - 每个位置必须是一条完整的位置描述短语，而不是短词
   - 每个位置必须依附于明确的场景锚物或区域
   - 位置描述中禁止写人物姿态、动作、情绪，只写空间位置
   - 这些位置里提到的锚点必须在场景描述中真实出现
   - 示例：饭桌左侧靠桌边的位置、教室后排靠窗那组课桌外侧的位置、皇宫正中龙椅前方台阶下的位置

以下是用户的生成指令:{user_input}

只返回以下json格式，禁止返回一切除json以外的多余内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "。
{
  "prompt":"「场景名称」场景描述内容",
  "available_slots":[
    "饭桌左侧靠桌边的位置",
    "门口内侧靠墙的位置"
  ]
}
```

### 4.9 Character reference sheet — `character_reference_to_sheet.zh.txt`

**Nguồn:** `_refs/waoowaoo/lib/prompts/character-reference/character_reference_to_sheet.zh.txt` (CHÉP ĐỦ — V1/V2 fix).

**Vì sao hiệu quả:** Ref = identity only; art style do user; auto-complete missing body parts.

```text
# 参考图转角色设定图提示词（图生图模式）

基于提供的参考图片，提取角色的面部五官特征、发型、体型和服装款式作为参考。

## 画风优先级规则

画风由用户选择的风格指令决定，严格遵循风格指令进行生成。
参考图仅用于保持角色身份特征（五官、发型、体型、服装结构），不能覆盖用户指定画风。
仅在未提供风格指令时，才可参考原图画风。

## 生成规则

1. 忽略原图的具体色调和光线
2. 使用自然柔和的摄影棚灯光
3. 绘制正常美观的人体比例
4. 不要复制原图的画质、模糊、噪点或瑕疵
5. 生成的图像必须清晰锐利、细节丰富、专业品质
6. 角色表情应为自然平静的中性表情，目光正视镜头

## 缺失部位自动补齐

如果参考图是半身或部分身体，请根据服装风格和人物特征合理补全未露出的部位：
- **缺少下半身**：根据上衣风格推断并绘制匹配的裤装/裙装
- **缺少脚部**：根据整体穿搭风格添加合适的鞋款
- **缺少手部/手臂**：根据姿态合理补全
- 保持整体风格一致，确保补全的部分与可见部分协调统一
```

### 4.10 System suffixes (`constants.ts`) — CHÉP ĐỦ

**Nguồn:** `_refs/waoowaoo/src/lib/constants.ts` (`CHARACTER_PROMPT_SUFFIX`, `PROP_PROMPT_SUFFIX`, `LOCATION_PROMPT_SUFFIX`).

```text
CHARACTER_PROMPT_SUFFIX = 角色设定图，画面分为左右两个区域：【左侧区域】占约1/3宽度，是角色的正面特写（如果是人类则展示完整正脸，如果是动物/生物则展示最具辨识度的正面形态）；【右侧区域】占约2/3宽度，是角色三视图横向排列（从左到右依次为：正面全身、侧面全身、背面全身），三视图高度一致。纯白色背景，无其他元素。

PROP_PROMPT_SUFFIX = 道具设定图，画面分为左右两个区域：【左侧区域】占约1/3宽度，是道具主体的主视图特写；【右侧区域】占约2/3宽度，是同一道具的三视图横向排列（从左到右依次为：正面、侧面、背面），三视图高度一致。纯白色背景，主体居中完整展示，无人物、无手部、无桌面陈设、无环境背景、无其他元素。

LOCATION_PROMPT_SUFFIX = 
```

### 4.11 Art styles (`constants.ts`) — block `ART_STYLES` CHÉP ĐỦ

**Nguồn:** `_refs/waoowaoo/src/lib/constants.ts` (export const ART_STYLES).

```typescript
export const ART_STYLES = [
  {
    value: 'american-comic',
    label: '漫画风',
    preview: '漫',
    promptZh: '日式动漫风格',
    promptEn: 'Japanese anime style'
  },
  {
    value: 'chinese-comic',
    label: '精致国漫',
    preview: '国',
    promptZh: '现代高质量漫画风格，动漫风格，细节丰富精致，线条锐利干净，质感饱满，超清，干净的画面风格，2D风格，动漫风格。',
    promptEn: 'Modern premium Chinese comic style, rich details, clean sharp line art, full texture, ultra-clear 2D anime aesthetics.'
  },
  {
    value: 'japanese-anime',
    label: '日系动漫风',
    preview: '日',
    promptZh: '现代日系动漫风格，赛璐璐上色，清晰干净的线条，视觉小说CG感。高质量2D风格',
    promptEn: 'Modern Japanese anime style, cel shading, clean line art, visual-novel CG look, high-quality 2D style.'
  },
  {
    value: 'realistic',
    label: '真人风格',
    preview: '实',
    promptZh: '真实电影级画面质感，真实现实场景，色彩饱满通透，画面干净精致，真实感',
    promptEn: 'Realistic cinematic look, real-world scene fidelity, rich transparent colors, clean and refined image quality.'
  }
]
```

### 4.12 Negative prompt

**Không có** negative prompt field trong panel/video pipeline. Constraints nằm trong positive prompt (ví dụ khối “绝对禁止” trong `single_panel_image.zh.txt` §4.6). Image models (Seedream/Banana/Imagen) gọi qua `referenceImages` + prompt string.

### 4.13 Camera language vocabulary

Nguồn đầy đủ: `agent_storyboard_detail.zh.txt` §4.5 — 景别 (大远景→极端特写), 视角 (平视/仰/俯/越肩/荷兰角/主观), 运动 (固定/缓推/急推/跟随/环绕/手持…), `shot_type` format `视角+景别` (vd `平视中景`). Không rút template; xem fence §4.5.

### 4.14 Ghi chú cross-ref ROUND 2

VERIFY §4.1 còn các file chưa nằm pipeline core (profile/visual, shot variant, insert, episode_split, story expand, modify/regenerate loops, select_location/prop, image_prompt_modify, character_image_to_description). **Full text** ở `## ROUND 2 — VERBATIM FULL` bên dưới (mỗi file một sub-heading).

## 5. Vòng QA / retry / repair

| Layer | Detect | Repair | Budget | Give up |
|-------|--------|--------|--------|---------|
| Phase LLM | empty JSON, all-empty panels, missing source_text | re-call AI | 2 attempts (phases) / 3 atomic | throw, task FAILED |
| JSON | markdown fences, bad quotes | strip fences; prompt forces 「」 | parse once | JsonParseError |
| Panel filter | description/location == "无" | drop panels | — | if 0 left → fail |
| Image gen | provider fail | BullMQ retry | 5 exp backoff | failed |
| Video | no imageUrl / no prompt / unsupported firstlast | hard error | 5 | failed |
| Billing | insufficient balance | reject enqueue | — | InsufficientBalanceError |
| Undo | bad gen | previousImageUrl / previousDescription | 1 step | manual re-gen |
| Candidates | multi still | user pick | 1–4 | — |

**Không có:** automated face-match, CLIP score, inter-shot color histogram check.

Atomic retry (`script-to-storyboard-atomic-retry.ts`): `MAX_STEP_ATTEMPTS = 3`, `MAX_RETRY_DELAY_MS = 10_000`, phase keys `phase1|phase2_cinematography|phase2_acting|phase3_detail`.

---

## 6. Tích hợp video-gen

### 6.1 Path chính: **image-to-video**

```typescript
// video.worker.ts:80-156
source = panel.imageUrl → base64
prompt = firstLastCustom || firstLastFramePrompt || custom || videoPrompt || description
mode   = firstLastFramePayload ? 'firstlastframe' : 'normal'
if firstlast: lastFrame from lastFrameStoryboardId + lastFramePanelIndex image
→ resolveVideoSourceFromGeneration({ imageUrl, options: { prompt, aspectRatio, generationMode, lastFrameImageUrl?, generateAudio? }})
```

### 6.2 Providers

From `constants.ts:68-115` + `generators/video/index.ts`:

- **Seedance** (Ark) — primary catalog, batch pricing −50%  
- **Kling** 2.5 Turbo Pro / 3 Standard / Pro via FAL i2v endpoints  
- **Veo** 3.1 (FAL + Google native poll)  
- **Wan 2.6**, **Sora 2** (FAL)  
- Capability JSON: duration 2–15s, resolution 480p/720p/1080p, `firstlastframe`, `generateAudio`

### 6.3 first / last frame

- Capability gate: `firstlastframe !== true` → throw `VIDEO_FIRSTLASTFRAME_MODEL_UNSUPPORTED`  
- Last frame = **another panel still**, not generated intermediate  
- Use case: continuity A→B (linked shots)

### 6.4 Reference-to-video

**Không** multi-ref video như Ingredients/Veo multi-image trong worker — video chỉ 1 (hoặc 2: first+last) image. Character consistency chủ yếu ở **still stage**.

### 6.5 Transition / edit

Editor defaults (`useEditorActions.ts:55-58`):

```typescript
transition: { type: 'dissolve', durationInFrames: 15 } // 0.5s @ 30fps
// options: none | dissolve | fade | slide
```

Default panel duration if missing: **3s** (`durationInFrames = (duration||3)*30`).

### 6.6 Audio

- Separate TTS voice lines  
- Lip-sync post-process (Kling default model id in billing)  
- Some Seedance models `supportGenerateAudio`

### 6.7 Polling / queue

- Video queue concurrency: `QUEUE_CONCURRENCY_VIDEO` default **4**  
- Per-user gate: `workflowConcurrency.video` default **5**  
- Async poll Seedance/Veo in `async-poll.ts` / `async-task-utils.ts`

---

## 7. Pacing / timing

| Mechanism | Rule |
|-----------|------|
| Shot density (plan) | ~15 Chinese chars → 1 panel; 450 chars ≈ 30 shots |
| Clip size | ≤ ~20 content elements per clip |
| Dialogue | speaker shot + reaction (≥2) for lip-sync |
| Panel.duration | Float field; editor fallback 3s |
| SRT path | `srtStart/srtEnd/srtDuration` on Shot; panel `srtSegment` = source_text |
| Voice match | index-based simple match in editor; `matchedVoiceLines` relation on panel |
| Video model duration | capability options 2–15s (user generationOptions) |

**Không** auto-align voice waveform → panel duration trong research scope; lip-sync takes `audioDurationMs` + `videoDurationMs`.

---

## 8. Chi tiết nhỏ đáng học

1. **Labeled reference images** — text bar tên asset trên ref; prompt cấm vẽ chữ.  
2. **Exact-name asset protocol** — mọi stage (clip/plan) force 100% match library; introduction map “我”→character.  
3. **Age-gender in video_prompt** — tránh model “đọc tên” sai identity.  
4. **Slot / available_slots** — spatial continuity soft anchors.  
5. **Multi-phase storyboard** — plan ∥ cine+acting → detail; tránh one-shot mega JSON.  
6. **previous* undo fields** — cheap re-roll UX.  
7. **Global asset hub + sourceGlobal*Id** — reuse cast across projects.  
8. **Capability catalog** — không hardcode firstlast trong business logic.  
9. **Billing freeze** — quote max cost before work; modes OFF/SHADOW/ENFORCE.  
10. **JSON quote sanitization** — force 「」 trong string values (LLM JSON broken by nested quotes).  
11. **Character color ban** — skin/eye/lip color forbidden (over-amplified by models).  
12. **Run-centric long workflows** — artifacts + lease cho story→script / script→board.  
13. **Guards scripts** (`scripts/guards/`) — no provider guessing, no dual SoT, prompt canary regression.  
14. **Prop tri-view white bg** vs **location full scene** — different suffixes.  
15. **linkedToNextPanel** field — schema sẵn cho chain continuity (UI first/last uses explicit lastFrame panel).

---

## 9. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện waoowaoo | Gap OmniCast (COMMON_CONTEXT) | File đích gợi ý | Impact | Effort |
|---|--------------------|-------------------------------|-----------------|--------|--------|
| 1 | Multi-phase storyboard (plan→cine→acting→detail) | Storyboard text có thể one-shot | `storyboard/` new planner modules | High — shot quality + camera language | L |
| 2 | `video_prompt` age+gender + dynamic verbs; names only in still | Chưa tách identity vs motion prompt cho Veo | `media/veo_pipeline.py`, storyboard binding | High — less freeze / wrong name | M |
| 3 | Ordered refs: sketch→chars→location + **labels** | Có ordered refs; chưa label bar | `refsheet.py` / outbound image prep | Med — multi-char disambiguation | M |
| 4 | Photography rules + acting notes injected into image prompt | Chưa có DoP/acting sub-agents | `storyboard/` | High | L |
| 5 | Location `available_slots` + panel `slot` soft anchor | Continuity gate text-level; thiếu spatial slots | `continuity.py`, entity location | High — layout drift | M |
| 6 | first/last frame i2v between panels | Veo convert() CHƯA nhận image; Flow Ingredients missing | `media/veo_pipeline.py` | **Critical** for face consistency | L |
| 7 | Candidate images 1–4 + previous undo | Re-roll UX incomplete | storyboard API + UI | Med | S |
| 8 | Per-user concurrency gate + 4 queues | Batch runner thiếu user/media concurrency policy | pipeline / task runner | Med ops | M |
| 9 | Billing freeze / cost quote | Cost guard cho batch YouTube | vault usage + runner | Med | M |
| 10 | Exact VERBATIM entity names throughout | Cast registry đã VERBATIM — align prompt language | `binding.py` prompts | Med | S |
| 11 | Lip-sync-aware dialogue shot split | Storyboard may merge dialogue | writer/storyboard plan | High for talking-head | M |
| 12 | Global asset hub | Cast per-video; cross-episode reuse manual | vault entities + channel library | Med series | L |
| 13 | Editor transitions dissolve default | FFmpeg concat may hard-cut | `render_real_video.py` | Low–Med polish | S |
| 14 | Prompt canary / semantic regression guards | Chưa | tests/ | Med maintainability | M |
| 15 | No negative prompt — positive hard rules | OmniCast may over-rely on negatives | prompt templates | Low–Med | S |

**Ưu tiên top 5 cho WS1 OmniCast:** #6 first/last (or i2v) wiring → #2 video prompt split → #3 labeled refs → #5 slots → #1 multi-phase plan.

---

## 10. KHÔNG nên học + LICENSE

### 10.1 Anti-patterns / hạn chế

| Issue | Ghi chú |
|-------|---------|
| **No automated visual QA** | Face drift chỉ fix bằng re-roll người |
| **Index-based voice↔panel match** | Yếu khi insert/delete panel |
| **License CC BY-NC-SA** | Không dùng code thương mại |
| **MySQL + heavy SaaS surface** | Billing/auth/docker — ngoài scope OmniCast local vault |
| **appearance match by changeReason string** | Fragile localization/rename |
| **american-comic label vs 日式动漫 prompt** | Naming confusing |
| **Default 3s duration** | Không bám VO length |
| **No seed control** | Reproducibility thấp |
| **Solo beta** | README admits bugs |

### 10.2 LICENSE

```
Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)
- NonCommercial — may not use material for commercial purposes
- ShareAlike — derivatives under same license
```

**Kết luận pháp lý cho OmniCast:** học kiến trúc, schema ý tưởng, prompt *patterns* (viết lại bằng lời của mình). **Cấm** copy-paste source TypeScript/prompt files nguyên văn vào product thương mại. Prompt trong report này chỉ phục vụ research nội bộ; khi implement phải paraphrase + rewrite.

---

## Phụ lục A — Task types (BullMQ)

`IMAGE_PANEL`, `IMAGE_CHARACTER`, `IMAGE_LOCATION`, `VIDEO_PANEL`, `LIP_SYNC`, `VOICE_*`, `STORY_TO_SCRIPT_RUN`, `SCRIPT_TO_STORYBOARD_RUN`, `CLIPS_BUILD`, `SCREENPLAY_CONVERT`, `ANALYZE_*`, `AI_CREATE/MODIFY_*`, `PANEL_VARIANT`, `ASSET_HUB_*`, `REFERENCE_TO_CHARACTER`, …

Queues: `waoowaoo-image|video|voice|text`. Default job: `attempts:5`, `backoff exponential 2000ms`, `removeOnComplete/Fail:500`.

---

## Phụ lục B — Panel image prompt context JSON shape

```json
{
  "panel": {
    "panel_id": "…",
    "shot_type": "平视中景",
    "camera_move": "缓缓推近",
    "description": "…",
    "image_prompt": "…",
    "video_prompt": "…",
    "location": "办公室",
    "characters": [{ "name": "张三", "appearance": "初始形象", "slot": "…" }],
    "source_text": "…",
    "photography_rules": { "lighting": {}, "characters": [], "depth_of_field": "…", "color_tone": "…" },
    "acting_notes": { "characters": [{ "name": "…", "acting": "…" }] }
  },
  "context": {
    "character_appearances": [{ "name": "…", "appearance": "…", "description": "…", "slot": "…" }],
    "location_reference": { "name": "…", "description": "…", "available_slots": ["…"] }
  }
}
```

Built in `panel-image-task-handler.ts:65-138`.

---

## Phụ lục C — Mapping sang OmniCast storyboard hiện tại

| OmniCast | waoowaoo tương đương |
|----------|----------------------|
| `Entity` character/location/prop/costume | Character + Appearance / Location (+ prop kind) |
| `refsheet.py` | CharacterAppearance images + CHARACTER_PROMPT_SUFFIX sheet |
| `binding.py` RefRole + [IMAGE n] | Labeled refs + prompt “角色参考/场景参考” roles (weaker formal binding) |
| `continuity.py` fail-closed | Soft rules in plan prompt + source_text priority |
| Cast human approve | `profileConfirmed` |
| Veo pipeline | VIDEO_PANEL i2v + firstlastframe |
| GAP: pixel drift measure | **also missing** in waoowaoo |
| GAP: Flow Ingredients ≤14 | waoowaoo also not multi-ref video |

---

## Đã đọc

### Round 1 (cơ chế / schema / orchestration)
- `docs/research/_briefs/COMMON_CONTEXT.md`, `03_waoowaoo.md`
- `docs/research/REFS_SB_00_VERIFY.md` §2.3, §3.2 (V1, V2), §4.1
- `LICENSE`, `README_en.md`
- `messages/zh/stages.json`, `messages/zh/storyboard.json`
- `prisma/schema.prisma` (NovelPromotion*, Global*, VideoEditor*, Media)
- `src/lib/storyboard-phases.ts`
- `src/lib/novel-promotion/stage-readiness.ts`
- `src/lib/novel-promotion/story-to-script/orchestrator.ts`
- `src/lib/novel-promotion/script-to-storyboard/orchestrator.ts`
- `src/lib/workers/handlers/script-to-storyboard-helpers.ts`
- `src/lib/workers/handlers/script-to-storyboard-atomic-retry.ts`
- `src/lib/workers/handlers/panel-image-task-handler.ts`
- `src/lib/workers/handlers/image-task-handler-shared.ts` (collectPanelReferenceImages)
- `src/lib/workers/video.worker.ts`
- `src/lib/workers/user-concurrency-gate.ts`
- `src/lib/task/queues.ts`, `types.ts`, `submitter.ts`
- `src/lib/workflow-concurrency.ts`
- `src/lib/assets/services/asset-prompt-context.ts`
- `src/lib/assets/kinds/registry.ts`
- `src/lib/assets/services/asset-actions.ts`
- `src/lib/billing/task-policy.ts`, `mode.ts`, `ledger.ts`
- `src/lib/billing/cost.ts`
- `src/lib/constants.ts` (models, ART_STYLES, CHARACTER/PROP/LOCATION_PROMPT_SUFFIX — full string)
- `src/lib/image-label.ts`
- `src/lib/prop-image-prompt.ts`
- `src/lib/generators/video/index.ts`
- `src/lib/async-poll.ts`, `async-task-utils.ts`
- `src/features/video-editor/hooks/useEditorActions.ts`
- `src/features/video-editor/components/TransitionPicker.tsx`
- `src/types/storyboard-types.ts`, `project.ts`
- `standards/capabilities/image-video.catalog.json`

### Round 2 — prompt FULL (mọi file dưới đã mở và chép nguyên văn vào §4 và/hoặc ROUND 2)
- `lib/prompts/novel-promotion/agent_clip.zh.txt`
- `lib/prompts/novel-promotion/agent_storyboard_plan.zh.txt`
- `lib/prompts/novel-promotion/agent_cinematographer.zh.txt`
- `lib/prompts/novel-promotion/agent_acting_direction.zh.txt`
- `lib/prompts/novel-promotion/agent_storyboard_detail.zh.txt`
- `lib/prompts/novel-promotion/single_panel_image.zh.txt`
- `lib/prompts/novel-promotion/character_create.zh.txt`
- `lib/prompts/novel-promotion/location_create.zh.txt`
- `lib/prompts/character-reference/character_reference_to_sheet.zh.txt`
- `lib/prompts/novel-promotion/agent_character_profile.zh.txt`
- `lib/prompts/novel-promotion/agent_character_visual.zh.txt`
- `lib/prompts/novel-promotion/agent_shot_variant_analysis.zh.txt`
- `lib/prompts/novel-promotion/agent_shot_variant_generate.zh.txt`
- `lib/prompts/novel-promotion/agent_storyboard_insert.zh.txt`
- `lib/prompts/novel-promotion/episode_split.zh.txt`
- `lib/prompts/novel-promotion/ai_story_expand.zh.txt`
- `lib/prompts/novel-promotion/character_modify.zh.txt`
- `lib/prompts/novel-promotion/character_regenerate.zh.txt`
- `lib/prompts/novel-promotion/character_description_update.zh.txt`
- `lib/prompts/novel-promotion/location_modify.zh.txt`
- `lib/prompts/novel-promotion/location_regenerate.zh.txt`
- `lib/prompts/novel-promotion/location_description_update.zh.txt`
- `lib/prompts/novel-promotion/prop_description_update.zh.txt`
- `lib/prompts/novel-promotion/storyboard_edit.zh.txt`
- `lib/prompts/novel-promotion/select_location.zh.txt`
- `lib/prompts/novel-promotion/select_prop.zh.txt`
- `lib/prompts/character-reference/character_image_to_description.zh.txt`
- `lib/prompts/novel-promotion/image_prompt_modify.zh.txt`

### Chưa đọc sâu (round sau nếu cần)
- Full `screenplay_conversion.zh.txt`, `voice_analysis.zh.txt` (không nằm §4.1 VERIFY list lần này)
- Mọi API route `src/app/api/**`
- Full video-editor Remotion/render path
- Toàn bộ unit tests
- `analyze-global*` multi-episode path
- Bản `*.en.txt` tương ứng (zh là SSOT production cho brief này)

---

*End of REFS_SB_03_waoowaoo.md — Round 2 VERBATIM fix*

---

## ROUND 2 — VERBATIM FULL (theo VERIFY §4.1)

> Round 2 sau `REFS_SB_00_VERIFY.md` §2.3 / §3.2 V1–V2 / §4.1.
> Mỗi file dưới đây là **CHÉP ĐỦ từng chữ** từ `_refs/waoowaoo` (zh). Không rút gọn, không `…`.
> Nhóm 1–9: pipeline core (clip → plan → cine → acting → detail → single_panel → character/location create → sheet).
> Nhóm 10+: file VERIFY §4.1 từng bỏ sót / asset edit / variant / insert / select.

### R2.1 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_clip.zh.txt`

```text
你是"剧本/文字片段预分割大师"。
任务：把用户输入给你的文字创意或剧本整份输入文字按场景/剧情边界切成若干批次，便于后续逐批转换为分镜。只输出 JSON，字段仅限如下结构，start为文字开始的文本，end为文字结束的文本，禁止任何多余文字以及禁止包含任何markdown标识符：

输出格式和要求
[
  {
    "start": 开局文本，最少包含五个字,
    "end": 结束文本，最少包含五个字,
    "summary": "总结概括片段内容",
    "location": "场景发生位置",
    "characters": ["角色1", "角色2"],
    "props": ["道具1", "道具2"]
  }
]

按照以下规则切分:

【什么是"内容元素"- 必须理解】
内容元素是指原文中可以独立成镜的最小单位，包括：
- 🎬 动作描述：每个独立动作算 1 个元素
  例："他站起身" = 1个元素，"他站起身，走向门口，推开门" = 3个元素
- 💬 对话台词：每段对话算 2 个元素（说话者 + 听者反应）
  例："陛下，请允许我介绍这位" = 2个元素
- 🎭 情绪/反应描述：每个角色的反应算 1 个元素
  例："皇帝眉头紧锁，皇后面色凝重" = 2个元素
- 🌅 场景描写：场景建立描写算 1-2 个元素
- 💭 心理活动/旁白：每段独白算 1 个元素

【计数示例】
原文："他走进房间，看见她坐在窗边。她抬头看他，眼中带着泪光，轻声说：你终于来了。"
- "他走进房间" = 1个元素（动作）
- "看见她坐在窗边" = 1个元素（场景描写）
- "她抬头看他，眼中带着泪光" = 2个元素（动作+情绪）
- "轻声说：你终于来了" = 2个元素（对话）
总计：6 个元素

1:【片段数量最小化 - 最高优先级】
   - 每个片段最多可容纳约 20 个内容元素（按上述定义计算）
   - 如果原文总元素 ≤ 20 个，必须只切分为 1 个片段，禁止拆分
   - 如果原文总元素 ≤ 40 个，最多切分为 2 个片段
   - 宁可片段稍长，也绝不过度切分
   - 只有当单个片段超过 20 个元素时，才考虑在场景变化处拆分
2:切割应该尽量完整切割,不要在剧情中间切割,确保剧情的完整性.要找最适合切割的片段
3:在有新角色,新场景之前一定要尽可能的分开,尽可能的不要从新剧情的中间切割,场景/角色变化优先落刀
4:各批 {start,end} 必须首尾相接、无重叠无缺口；按时间顺序，确保覆盖整本输入内容
5:只返回JSON；不得输出markdown代码块标记、注释或解释；不得添加未定义字段。- 只返回上述 JSON；不得输出markdown代码块标记、如```json注释或解释；不得添加未定义字段。
6:如果这里是第一人称视角会变化的小说剧文本，那么summary中要标明是谁的视角,因为切块内容可能没有标明主角是谁,导致后续不知道主角信息,要在summary里面标明第一视角:xxx，但是如果不是有声书，有明确的POV那么则只需要解说片段即可
7:我们的视角应该是以最开始的为准,最开始的时候说的是谁的视角,必须全篇都是这个视角的,不允许改变,除非原文有明确中途改变!
8:要完整切分我们输入的完整剧本/文字内容.
⚠️⚠️⚠️【JSON安全输出 - 最高优先级】⚠️⚠️⚠️
- 原文中的所有引号（""''「」『』等）在 JSON 字符串值中必须统一替换为日式方括号引号「」
- ❌ 严禁在 JSON 字符串值中出现英文双引号 " ！会破坏 JSON 结构！
- ✅ 正确：「弼马温，我是来取代你的」
- ❌ 错误："弼马温，我是来取代你的"
- 这条规则适用于 start、end、summary 等所有字符串字段

⚠️⚠️⚠️【资产选择 - 最高优先级规则】⚠️⚠️⚠️

【location 场景选择 - 必须100%精确匹配】
1. location 字段【只能】填写场景库中【完全一模一样】的名字
2. ❌ 严禁添加任何后缀！例如场景库是 "客厅"，禁止写成 "客厅_内景_白天"
3. ❌ 严禁修改场景库的名字！禁止改写、缩写、添加任何字符
4. 如果剧情发生在多个场景，用逗号分隔：如 "客厅,卧室"
5. 如果剧情场景不在场景库中，选择最接近的场景，或留空 null

【characters 角色选择 - 必须100%精确匹配】
1. characters 数组【只能】填写角色库中【完全一模一样】的名字
2. ❌ 严禁使用原文中的其他称呼！必须使用角色库的名字
3. 例如角色库有"张三"，原文写"老张"或"张总"，必须填写"张三"
4. ⭐ 参考【角色介绍】理解"我"对应哪个角色，以及其他称呼的映射关系

【props 道具选择 - 必须100%精确匹配】
1. props 数组【只能】填写道具库中【完全一模一样】的名字
2. ❌ 严禁改写、缩写、添加前后缀
3. 只选择当前片段里真正出镜、被持有、被使用、被重点提及的实体道具
4. 如果当前片段没有明确道具，返回空数组 []

【自检规则】
输出前检查：location、characters、props 中的每个名字是否都能在对应资产库中找到完全一致的？如果不能，必须修正！

原文如下:
{input}

场景库：
{locations_lib_name}

角色库：
{characters_lib_name}

角色介绍（⭐用于理解"我"和称呼对应的角色）：
{characters_introduction}

道具库：
{props_lib_name}
```

### R2.2 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_storyboard_plan.zh.txt`

```text
你是专业的分镜规划师。你的任务是根据剧本内容（或原文）将故事拆解成连续的分镜头，设计分镜板基础规划。

输入可能是两种格式：
1. 【剧本格式】JSON格式的结构化剧本，包含scenes、action、dialogue、voiceover等
2. 【原文格式】原始小说/文本片段

无论哪种格式，你都需要将其拆解成连续的电影镜头。

【核心原则 - 最高优先级】
⚠️ 精准覆盖！确保每个关键画面都有镜头
⚠️ 电影思维：聚焦核心动作和情绪点
⚠️ 目标比例：每15个字符 = 1个镜头（字符/镜头比 ≈ 15:1）
⚠️ 关键角色动作和对话需要独立镜头
⚠️ 450字内容 = 约30个镜头

【核心规则】

1. 分镜数量：聚焦关键画面
   - 每个场景开始 → 1-2个建立镜头（远景或中景）
   - 每个动作描述 → 1-2个镜头（核心动作+结果）
   - 每段对话 → 2个镜头（说话者+听者反应）
   - 角色反应 → 重要情绪点才需单独镜头
   - 情绪高潮点 → 可增加1个氛围/特写镜头
   - 质量优先：确保每个镜头都有意义

2. 每个分镜必须包含：
  - panel_number: 分镜序号（1, 2, 3...）
  - description: 画面描述（人物动作、场景元素、构图要点）
   - characters: [{name: "角色名", appearance: "形象名", slot: "场景固定位置描述"}]
   - location: 场景名称（从资产库选择）
   - scene_type: daily/emotion/action/epic/suspense
   - source_text: 对应原文片段 ⚠️ 必填，不得为空

3. source_text 规则（极其重要）：
   ⚠️ 每个分镜都必须包含，不得为null或空字符串
   - 多个镜头可以共享同一段原文
   - 直接从输入内容中复制原文
   - 创意镜头也需填写触发该镜头的原文片段

【镜头拆分规则】

1. 景别选择（择一即可）：
   - "他走进房间" → 中景(推门进入) + 近景(表情)，或远景全景一镜到底

2. 反应镜头（仅关键场景）：
   - 重要情绪转折点 → 可插入反应镜头
   - 普通对话不需要每句都有反应

3. 建立镜头（精简）：
   - 开头：1个场景建立镜头即可
   - 中间：仅情节需要时加入环境镜头

4. 创意/氛围镜头（可选，0-1个）：
   - 仅在情绪高潮点考虑使用
   - 隐喻：关键转折时使用（如乌鸦、时钟）

5. 对话处理：
   - 正反打：连续对话可合并处理
   - 小动作：融入对话镜头，不需单独成镜

6. ⚠️ 对话镜头强制规则（口型同步需求）：
   - 任何包含引号对话的句子，说话者必须有独立镜头
   - 说话者镜头必须聚焦在说话者脸部，不能有其他角色占据主要画面
   - 禁止在一个镜头中同时展示多个角色说话
   - 示例：
     "真公主说：父皇母后，我是乐韵啊" 
     → 镜头1: 真公主开口说话（近景，聚焦真公主）
     → 镜头2: 帝后听的反应
   - 其他人可以出现在背景，但必须虚化（景深处理）

7. 复合句/长句拆分（合理拆分，避免冗余）：
   
   a) "动作 + 对话" → 3-4 个镜头
      例："真公主看大家没反应，说：父皇母后，我是乐韵啊"
      → 环视众人(1) + 开口说话(1) + 帝后反应(1) + 可选全景(1)
   
   b) "连续动作" → 合并相关动作
      例："他站起身，走向门口，推开门" → 2-3 个镜头（起身走动+推门）
   
   c) "多角色反应" → 合并同场景反应
      例："皇帝眉头紧锁，皇后克制情绪" → 1-2 个镜头（双人反应镜头或分切）
   
   d) "对话场景" → 说话者 + 听者反应 = 2 个镜头
   
   e) "单人描写" → 1-2 个镜头
      例："真公主面容疲惫，昂首挺胸" → 中景全身(1)，必要时加特写(1)

【镜头生成规则】

1. 连续性：
   - 镜头流畅过渡，上一镜头动作在下一镜头承接
   - 光线、氛围保持一致
   - 避免连续两镜头内容完全相同

2. 创意镜头语言：
   - 隐喻象征：乌鸦(不祥)、日落(时间流逝)、阳光穿云(希望)
   - 空镜氛围：滴水(紧张)、雨打窗(悲伤)、炉火(温馨)
   - 情绪放大：镜中倒影(挣扎)、时钟(抉择)

3. 智能理解用户输入的要求（节奏、情绪、画面、规则、色调等）

【剧本格式解析规则】

当输入是【剧本格式】JSON时：

1. scene信息：
   - heading: 提取场景的内景/外景、地点、时间
   - description: 场景环境 → 生成建立镜头
   - characters: 场景中的角色列表

2. content数组：
   - type: "action" → 提取text作为动作描述
   - type: "dialogue" → 提取character、lines、parenthetical生成对话镜头
   - type: "voiceover" → 画外音，设计画面配合声音

3. 对话拆解：
   - 每个对话 2-3 个镜头：说话者 + 听者反应 + 双人/环境镜头

4. 画外音处理：
   - 画外音时画面应是相关场景或回忆
   - 示例：voiceover说"猴子死了" → 画面是闪回战斗

【原文格式解析规则】

1. 剧本标记：
   - `△` 标记 → 必须生成独立分镜
   - "场景：" → 生成建立镜头
   - "画面：" → 直接生成分镜

2. 动作/对话识别：
   - 人物动作："他走进房间" → 动作镜头
   - 场景变化："阳光洒进窗户" → 环境镜头
   - 对话："角色A：（愤怒地站起）你怎么能这样！" → 站起 + 愤怒表情


【人物连续性与场景完整性规则】

1. 人物追踪：
   - 角色进入场景后，在明确离开前必须持续存在
   - 禁止人物"凭空消失"
   - 人物离场必须有明确动作

2. 画面层次（每个分镜必须包含）：
   - 焦点层：当前说话/动作的主要人物（详细描述）
   - 在场层：其他在场人物的状态（简要描述位置、反应）
   - 环境层：场景氛围和环境细节

3. 景别与人物展示：
   - 全景/中景：所有在场人物都必须出现
   - 近景：主体 + 画面边缘可见人物
   - 特写：只需局部，无需其他人

4. 人物存续逻辑：
   - 前一镜存在的人物，下一镜（非特写）必须交代去向
   - 只能通过：明确离场动作、切为特写、场景切换 来"消失"

【资产库使用规则】

1. 角色选择：
   - characters: [{name: "角色名", appearance: "形象名"}]
   - name 必须与资产库完全一致
   - appearance 根据分镜情境选择最合适形象
   - 所有在画面中出现的角色都要选择

2. 场景选择：location 必须从场景资产库选择，名字完全一致

【画面描述格式规则】

1. ⚠️ 禁止使用身份称呼：
   ❌ 错误："母亲紧握儿子的手"、"父亲站在门口"
   ✅ 正确：使用资产库中的具体角色名

2. ⚠️ 禁止主观情绪词：
   ❌ 错误："显得格格不入"、"气氛尴尬"、"充满敌意"
   ✅ 正确：只描述可视化元素（"皱眉"、"攥紧拳头"、"瞪大眼睛"）

3. 空间关系必须清晰：
   - 明确朝向：谁面对谁、谁背对谁
   - 明确阻挡：谁挡在谁前面
   - 明确位置：前后左右、远近高低
   
   ✅ 正确："保镖正面朝向张三，背对身后的老人，双臂张开阻挡张三前进"

4. 角色描述简洁：
   - 直接使用角色名称即可，无需添加衣着/年龄描述
   ❌ 错误："穿白T恤的少年张三站在门口"
   ✅ 正确："张三站在门口"

【镜头连续性与空间锚定规则 - 核心规则】

⚠️ 这是保证画面连贯的重要规则！

1. **核心原则**：
   - 根据**镜头实际能拍摄到的范围**来决定是否描述其他角色
   - 镜头合理性优先：特写、反打、局部镜头等**拍不到其他人**时，不需要强行描述
   - 只有在镜头**确实能看到**其他角色时，才需要交代其位置

2. **不同镜头类型的处理**：
   
   - 全景/远景：需要交代所有在场角色，画面范围大，所有人都应该可见
   - 中景：需要交代其他角色，通常能看到交谈双方或多人
   - 近景：视情况而定，如果镜头角度能看到对方则交代，看不到则省略
   - 反打镜头：不需要交代另一方，因为反打就是专门拍摄一方，另一方在镜头后面
   - 特写/极端特写：不需要交代其他人，只展示局部画面
   - 越肩镜头：前景肩膀可见即可，不必详细描述

3. **合理性原则**：
   
   ✅ 正确（镜头能拍到）：
   "中景：李四皱眉说话，对面张三静静听着" ← 中景能看到双方
   
   ✅ 正确（反打镜头不需要另一方）：
   "反打近景：李四皱眉说话" ← 反打就是只拍一方，另一方在镜头后
   
   ✅ 正确（特写只需焦点）：
   "脸部特写：李四眉头紧锁" ← 特写不需要交代其他人
   
   ❌ 错误（中景却丢失可见角色）：
   "中景：李四说话" ← 中景应该能看到对方，为什么没写？

4. **连续性检查**（生成每个分镜前自检）：
   □ 当前镜头类型/角度能拍摄到哪些角色？
   □ 能拍到的角色是否都有描述？
   □ 拍不到的角色（特写、反打等情况）可以省略

【输出格式】

只返回JSON数组，不得输出markdown代码块标记、注释或解释。

示例（重点展示镜头连续性）：

原文："张三走进办公室，看着正在工作的李四和王五说：开会了。李四抬头点了点头，王五放下手中的笔站起身。"

[
  {
    "panel_number": 1,
    "description": "中景：张三推开办公室门走进来，画面深处李四坐在左侧工位低头工作，王五坐在右侧工位写字",
    "characters": [
      {"name": "张三", "appearance": "初始形象"},
      {"name": "李四", "appearance": "初始形象"},
      {"name": "王五", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "张三走进办公室，看着正在工作的李四和王五"
  },
  {
    "panel_number": 2,
    "description": "近景：张三站在门口开口说话，对面李四和王五抬起头望向他",
    "characters": [
      {"name": "张三", "appearance": "初始形象"},
      {"name": "李四", "appearance": "初始形象"},
      {"name": "王五", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "说：开会了"
  },
  {
    "panel_number": 3,
    "description": "近景：李四坐在工位上抬头点了点头，旁边王五正在放下手中的笔，背景中张三站在门口等待",
    "characters": [
      {"name": "李四", "appearance": "初始形象"},
      {"name": "王五", "appearance": "初始形象"},
      {"name": "张三", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "李四抬头点了点头，王五放下手中的笔"
  },
  {
    "panel_number": 4,
    "description": "中景：王五从座位上站起身，左侧李四也准备起身，张三在门口向外走去",
    "characters": [
      {"name": "王五", "appearance": "初始形象"},
      {"name": "李四", "appearance": "初始形象"},
      {"name": "张三", "appearance": "初始形象"}
    ],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "王五站起身"
  }
]

注意示例中的镜头连续性技巧：
- 每个镜头都交代了三个角色的位置
- 镜头焦点变化时（如镜头3焦点是李四王五），仍用「背景中张三」保持连续性
- 角色移动（如镜头4张三向外走）有明确动作交代

【输入数据】

角色资产库：{characters_lib_name}
场景资产库：{locations_lib_name}

角色介绍（⭐用于理解"我"和称呼对应的角色）：
{characters_introduction}

角色形象列表（供选择appearance）：
{characters_appearance_list}

角色完整描述（供参考）：
{characters_full_description}

道具描述（供参考）：
{props_description}

Clip信息：
{clip_json}

内容输入（剧本格式JSON或原文片段）：
{clip_content}

【严格要求】
1. 必须输出所需数量的有效分镜，禁止空分镜
2. 角色和场景名字必须从资产库选择
3. characters 必须是对象数组：[{name: "角色名", appearance: "形象名"}]
4. 只返回JSON数组，不得有其他文字
5. ⚠️ source_text 必填，不得为空或null
6. 空间关系必须清晰（朝向、阻挡、位置）
7. 如果场景描述中提供了可站位置列表，应将其视为优先位置锚点，而不是强制覆盖所有可能位置的硬边界
8. 当角色在场景中稳定停留时，优先从可站位置列表中选择 slot；slot 字段的值必须直接复制完整位置描述，禁止缩写、改写、总结或替换成短词
9. 当镜头主要表现角色移动、进入/离开、穿过空间、过渡区域、路径空间、临时空间、空白空间、想象/梦境/回忆/抽象空间时，可以不使用 slot，并根据原文和镜头逻辑自由决定位置
10. 镜头连续性：前后镜头要有动作承接
11. 禁止身份称呼：必须使用资产库中的具体名字
12. 禁止主观情绪词：只描述可视化动作和状态
13. 禁止长句单镜头：包含逗号分隔多个动作/对话的长句必须拆分
14. 对话必须拆分：每段对话至少 2 个镜头（说话者 + 听者反应）
15. ⚠️ 镜头合理性：只描述当前镜头**实际能拍摄到**的角色，特写/反打等拍不到的可省略
16. ⚠️ JSON安全：原文中的所有引号（""''「」等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### R2.3 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_cinematographer.zh.txt`

```text
你是一位经验丰富的电影摄影指导(Director of Photography)。你的任务是为一组分镜中的**每个镜头**分别设计摄影规则。

【核心职责】

分析整组分镜后，为每个镜头单独设计以下视觉要素：
1. 灯光设置 - 光源方向和质感
2. 角色位置 - 画面中的具体位置
3. 景深设置 - 根据镜头类型确定景深
4. 色调风格 - 整体色彩氛围

【重要】每个镜头的规则必须是独立的！
- 不同场景的镜头有不同的光照和色调
- 不同景别的镜头有不同的景深
- 不同镜头中的角色位置可能不同

【分析步骤】

1. 通读所有镜头，了解整体场景流程
2. 为每个镜头单独分析：
   - 时间与光照（从场景和时间推断）
   - 角色位置（根据镜头描述确定）
   - 景深（根据镜头类型：全景/中景/近景/特写）
   - 色调（根据场景氛围确定）

【景深参考】
- 全景/远景：深景深（T8.0），清晰展现空间
- 中景：中等景深（T4.0）
- 近景：浅景深（T2.8），轻微背景虚化
- 特写：极浅景深（T1.8），强烈背景虚化
- 越肩镜头：浅景深，前景肩膀虚化

【⚠️ 对话镜头景深规则 - 口型同步要求】
- 任何角色说话的镜头，如果出现多张脸，多个人物出场，必须使用浅景深或极浅景深（T2.8 或更小）
- 说话者脸部必须清晰聚焦，背景中的其他角色必须虚化
- 目的：避免画面中出现多张清晰的脸，防止口型识别错误
- 示例：
  * "真公主说话" → 浅景深（T2.8），真公主脸部清晰，背景帝后虚化
  * "对话特写" → 极浅景深（T1.8），只有说话者脸部清晰

【输出格式】

返回一个JSON数组，每个元素对应一个镜头的摄影规则。

必须确保输出的数组长度与输入的镜头数量一致！

示例输出（假设输入3个镜头）：

[
  {
    "panel_number": 1,
    "scene_summary": "太子妃寝殿，白天",
    "lighting": {
      "direction": "主光从画面右侧窗户照入",
      "quality": "柔和的自然光，暖色调"
    },
    "characters": [
      {
        "name": "李凤华",
        "screen_position": "画面左侧",
        "posture": "站立",
        "facing": "面向右侧"
      },
      {
        "name": "景笙",
        "screen_position": "画面右侧",
        "posture": "站立",
        "facing": "面向左侧"
      }
    ],
    "depth_of_field": "深景深（T8.0），清晰展现宫殿空间",
    "color_tone": "暖色调，温馨氛围"
  },
  {
    "panel_number": 2,
    "scene_summary": "太子妃寝殿，白天",
    "lighting": {
      "direction": "侧光从画面右侧照入",
      "quality": "柔和自然光"
    },
    "characters": [
      {
        "name": "李凤华",
        "screen_position": "画面左侧偏中",
        "posture": "低头，手伸向对方",
        "facing": "面向右侧"
      }
    ],
    "depth_of_field": "浅景深（T2.8），背景虚化，聚焦动作",
    "color_tone": "暖色调"
  },
  {
    "panel_number": 3,
    "scene_summary": "太子妃寝殿，白天",
    "lighting": {
      "direction": "正面柔光",
      "quality": "柔和自然光，面部无阴影"
    },
    "characters": [
      {
        "name": "李凤华",
        "screen_position": "画面中央",
        "posture": "面部特写",
        "facing": "面向镜头略偏右"
      }
    ],
    "depth_of_field": "极浅景深（T1.8），背景完全虚化",
    "color_tone": "暖色调，聚焦人物情绪"
  }
]

【输入数据】

分镜数据（共 {panel_count} 个镜头）：
{panels_json}

场景描述：
{locations_description}

角色信息：
{characters_info}

道具描述：
{props_description}

【严格要求】

1. 只返回JSON数组，不要有markdown代码块标记
2. 数组长度必须等于输入的镜头数量（{panel_count}个）
3. 每个元素必须包含 panel_number 字段
4. 使用相对方向（画面左侧/右侧），禁止使用东南西北
5. 角色位置必须与镜头描述一致！
6. 如果角色对象中包含 slot，screen_position / posture / facing 应优先参考该位置语义，但 slot 不是绝对硬限制
7. 当镜头属于移动过程、入口/出口、过渡区域、路径空间、临时位置、空镜、想象空间、梦境、回忆或抽象空间时，可以基于镜头描述自由决定构图与位置，不必强行贴合 slot
8. slot 若被引用，必须视为一条完整的位置描述，禁止缩写、改写、总结或替换成短词
9. 景深根据 shot_type（全景/中景/近景/特写）自动调整
10. ⚠️ 对话镜头必须使用浅景深（T2.8或更小），并且注明其他人虚化，确保只有说话者脸部清晰
11. 如果镜头涉及不同场景，灯光和色调要相应调整
12. 输出要简洁，每个镜头的规则独立完整
13. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### R2.4 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_acting_direction.zh.txt`

```text
你是一位经验丰富的表演指导(Acting Director)。你的任务是为一组分镜中的**每个镜头**设计角色的表演细节。

【核心职责】

分析整组分镜后，为每个镜头中的角色用一句话描述完整的表演指令，包含：
- 情绪状态与强度
- 面部表情细节
- 肢体语言与姿态
- 微动作与视线

【重要】每个镜头的表演必须是独立的！
- 同一角色在不同镜头可能有不同情绪变化
- 表演风格匹配 scene_type（日常/情感/动作/史诗/悬疑）

【表演风格匹配 scene_type】

**daily（日常）**：自然松弛，微表情为主，动作幅度小
**emotion（情感）**：细腻层次，眼神戏份重，情绪渐进
**action（动作）**：爆发力强，动作干脆，表情夸张
**epic（史诗）**：庄重仪式感，姿态端正，动作缓慢有力
**suspense（悬疑）**：紧绷警觉，肢体僵硬，眼神游移

【表演描述词库】

**表情**：眼眶泛红、眉头紧锁、嘴角上扬、目光闪躲、瞳孔收缩、嘴唇颤抖、咬紧牙关
**肢体**：握紧拳头、身体前倾、双手交握、肩膀耸起、转身背对、后退一步
**微动作**：轻轻眨眼、咽口水、深呼吸、手指轻颤、舔嘴唇、胸口起伏

【⚠️ 禁止规则】

1. 禁止抽象情绪词：悲伤、愤怒、紧张 → 改用可见表现
2. 禁止身份称呼：母亲、父亲 → 改用角色名

【输出格式】

返回JSON数组，每个镜头一个对象，每个角色只有 name + acting 两个字段：

[
  {
    "panel_number": 1,
    "characters": [
      {
        "name": "李凤华",
        "acting": "嘴角微扬眼神柔和地看向景笙，身体微微前倾，双手自然垂放，轻轻眨眼"
      },
      {
        "name": "景笙",
        "acting": "面带微笑但眼神略显疏离，站姿笔直双手背后，轻轻点头"
      }
    ]
  },
  {
    "panel_number": 2,
    "characters": [
      {
        "name": "李凤华",
        "acting": "眉头轻皱嘴唇紧抿，双手交握在身前肩膀微耸，目光低垂看向地面，手指轻微交缠"
      }
    ]
  },
  {
    "panel_number": 3,
    "characters": [
      {
        "name": "李凤华",
        "acting": "眼眶泛红泪水打转嘴唇颤抖，身体微微发抖双手攥紧衣角，快速眨眼忍住泪水转头避开对方视线"
      }
    ]
  }
]

【输入数据】

分镜数据（共 {panel_count} 个镜头）：
{panels_json}

角色信息：
{characters_info}

【严格要求】

1. 只返回JSON数组，不要有markdown代码块标记
2. 数组长度必须等于输入的镜头数量（{panel_count}个）
3. 每个角色只有 name 和 acting 两个字段
4. acting 用一句话描述完整表演（表情+肢体+微动作+视线）
5. 角色名必须与输入分镜中的 characters 完全一致
6. 所有描述必须是可视化的，禁止抽象情绪词
7. 根据 scene_type 调整表演风格
8. 情绪弧线连贯，前后镜头有合理递进
9. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### R2.5 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_storyboard_detail.zh.txt`

```text
你是顶级电影分镜师。根据分镜规划和场景类型，设计镜头语言和视频提示词。

【你的职责】
- 根据scene_type选择镜头风格
- 为每个分镜设计景别、视角、镜头运动
- 撰写video_prompt（用年龄段+性别替代角色名）
- ⚠️ 保留输入分镜中的所有原始字段（特别是 source_text，必须原样保留）
- 如果输入角色包含 slot，应优先原样保留，并让 refined description/video_prompt 优先参考该位置

【镜头语言库】

**景别**：
- 大远景：宏伟场景、史诗感、渺小人物
- 远景/全景：交代环境、人物关系
- 中景：对话、互动、日常
- 近景：情绪、反应
- 特写：眼神、手部、关键道具
- 极端特写：瞳孔、嘴唇、一滴泪等

**视角**：
- 平视：日常、平等、自然
- 仰拍：威压感、崇高感（动作/史诗场景）
- 俯拍：渺小感、全局感（宏大场景）
- 越肩镜头：对话、对峙
- 荷兰角：不安、紧张（悬疑/紧张场景）
- 主观视角：代入感

**镜头运动**：
- 固定：凝视、沉默、日常对话
- 缓推/缓拉：情绪酝酿、揭示、温和过渡
- 跟随：人物移动、日常行走
- 急推/急拉：震惊、冲击（紧张场景）
- 环绕/升起/俯冲：仪式感、史诗感（宏大场景）
- 手持晃动：混乱、紧张（动作场景）

【根据scene_type选择镜头风格】

**daily（日常/对话）**：
- 以中景、近景为主，偶尔特写
- 平视为主，越肩镜头交替
- ✅ 优先使用缓推/缓拉/轻微跟随，避免纯固定镜头
- 镜头运动词：缓缓推近、轻轻跟随、微微摇晃、缓慢环绕
- 人物动作：即使是对话场景，也要添加微小动作（点头、转头、手势、走动）

**emotion（情感/抒情）**：
- 近景、特写捕捉情绪
- 情绪高潮可用极端特写
- ✅ 优先使用缓慢推进、环绕运镜，避免纯固定
- 镜头运动词：缓缓推近、轻轻环绕、微微晃动
- 人物动作：轻抬头、转身、低头、抬手抭泪、走向窗边

**action（动作/打斗）**：
- 景别快速切换，特写+全景交替
- 仰拍、俯拍、荷兰角增加冲击
- 急推急拉、跟随、手持晃动
- 镜头运动词：猛然、疾速、急速、爆发

**epic（史诗/宏大）**：
- 必须有大远景建立规模
- 俯拍、升起、俯冲展现壮观
- 人物置于画面边缘凸显渺小
- 镜头运动词：缓缓升起、急速俯冲、环绕

**suspense（悬疑/紧张）**：
- 主观视角、荷兰角
- 缓慢推进制造压迫
- 突然切换打破节奏

【镜头连贯性规则】
- 镜头必须连续，不能有中断
- 同组分镜需循序渐进：远→中→近 或 近→中→远
- 新场景一般需要建立全景镜头
- 分镜要多样性，不要重复类似景别
- 让画面动起来，不死板

【video_prompt撰写规则 - 重要】

视频模型不认识名字，必须用**年龄段+性别**替代：
- 格式：年龄性别 + 动作 + 镜头运动 + 环境
- 根据场景类型选择动感强度
- 禁止出现分镜中没有的内容
- 涉及运动要具有动态，静态要丰富肢体语言和表情
- 如果原文在说话，提示词要写明"正在说话"

⚠️ 【动态优先原则 - 核心规则】

视频不能僵硬！每个 video_prompt 必须包含“动”的元素：

1. **人物动作词库**（必须使用）：
   - 头部：转头、点头、抬头、低头、侧头、回头
   - 手部：抬手、挥手、指向、握拳、放下、拿起、摸着
   - 身体：走动、转身、起身、坐下、俯身、后退、靠近
   - 表情：眉头轻皱、嘴角上扬、眼神闪烁、轻轻笑着

2. **镜头运动词库**（优先使用这些，避免"固定"）：
   - 常用：缓缓推近、轻轻跟随、微微摇晃、环绕拍摄
   - 动感：手持跟随、轻微抖动、缓慢环绕、升起俯拍
   - 强烈：急速推近、快速跟随、猛然拉远、俯冲而下

3. **禁止纯静态描述**：
   ❌ 错误："年轻女子坐在沙发上，镜头固定"
   ✅ 正确："年轻女子坐在沙发上轻轻转头，镜头缓缓推近她的侧脸"
   
   ❌ 错误："中年男子站在门口，表情严肃"
   ✅ 正确："中年男子推开门走进来，眉头轻皱，镜头手持跟随"

4. **即使是对话场景，也要动起来**：
   ❌ 错误："年轻男子说话，镜头固定"
   ✅ 正确："年轻男子边说边比划手势，轻轻点头，镜头缓缓推近"

⚠️ **回忆/旁白/内心独白规则**：
- 禁止只写人物静止沉思、发呆、空镜
- video_prompt必须展示叙述内容中的**实际动作和场景**
- 画面和剧情强绑定，不要只是"人物站着回忆"
- 例如：叙述"当年的相遇"→ 要写相遇时的实际动作画面

**年龄段分类**（只使用这些词汇）：
- 少年/少女：约10-16岁
- 年轻男子/年轻女子：约17-30岁
- 中年男子/中年女子：约31-50岁
- 老年男子/老年女子：50岁以上

⚠️ 【特写镜头必须使用固定镜头】
- 当镜头类型为"特写"时（如手部特写、物品特写、局部特写等）
- video_prompt 必须明确写"固定镜头"或"镜头固定不动"
- 禁止在特写镜头中使用任何镜头运动
- 原因：特写画面只展示局部，镜头移动会暴露其他部分

**示例**（注意动态元素）：
- 日常对话："年轻女子端起咖啡杯轻轻吹气，抬头望向窗外，阳光洒在侧脸，镜头缓缓推近她的侧影"
- 动作场景："少年腾空跃起挥剑划出弧线，衣袍猎猎飞扬，镜头手持仰拍跟随"
- 情感场景："年轻女子缓缓低下头，泪珠沿脸颊滑落，抬手抭去眼角，镜头轻轻环绕她"
- 对话场景："中年男子用手指敲着桌面，表情严肃地说着，镜头微微摇晃拍摄"
- 走动场景："年轻男子快步走在街道上，风吹起衣角，镜头手持跟随拍摄"
- 特写镜头："一只手缓缓翻开书页，指尖轻轻划过文字，固定镜头"


【输出格式】

只返回JSON数组，禁止markdown标记或注释。
在原有panels基础上，为每个分镜补充shot_type、camera_move、video_prompt：

示例：
[
  {
    "panel_number": 1,
    "shot_type": "平视中景",
    "camera_move": "固定",
    "description": "角色A站在桌前，双手撑在桌面上，表情严肃地看着对面的角色B",
    "video_prompt": "年轻男子站在桌前，双手撑在桌面上，表情严肃，正在说话，镜头固定拍摄",
    "characters": [{"name": "角色A", "appearance": "初始形象", "slot": "皇宫正中龙椅前方台阶下的位置"}],
    "location": "办公室",
    "scene_type": "daily",
    "source_text": "角色A对角色B说：你好"
  }
]

【输入数据】

分镜规划：
{panels_json}

角色年龄性别信息（用于video_prompt）：
{characters_age_gender}

场景描述：
{locations_description}

道具描述：
{props_description}

【严格要求】
1. 为每个分镜补充shot_type、camera_move、video_prompt
2. shot_type格式：视角+景别（如"平视中景"、"越肩近景"、"仰拍全景"）
3. video_prompt必须用年龄段+性别（如"年轻女子"、"中年男子"）而非角色名
4. 镜头风格必须匹配scene_type
5. 只返回JSON数组
6. 特写镜头必须使用固定镜头
7. 对话场景必须在video_prompt中明确写"正在说话"
8. 根据输入的分镜数量动态处理
9. panel_number、characters、location、scene_type保持不变
10. description可以适当优化，但不要改变核心内容
11. 如果输入中存在 slot，应优先保留并优先参考该位置，但 slot 不是绝对硬边界
12. 当镜头明显属于移动过程、入口/出口、过渡区域、路径空间、临时位置、空镜、想象空间、梦境、回忆或抽象空间时，可以删除 slot 或保留 slot 但不严格贴合其静态位置
13. 若不使用 slot，应根据 source_text、动作过程、空间关系与镜头调度自由决定人物位置，不要为了命中 slot 而破坏叙事逻辑
14. slot 若被保留，必须原样保留为完整位置描述，禁止缩写、改写、总结或替换成短词
15. ⚠️ 必须保留输入分镜中的 source_text 字段，原样输出到结果中，不得遗漏或修改
16. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "
```

### R2.6 — `_refs/waoowaoo/lib/prompts/novel-promotion/single_panel_image.zh.txt`

```text
你是一位专业的分镜画师。请根据以下分镜数据生成单张高质量的镜头图片。

【绝对禁止 - 图像中不得出现任何文字 - 最高优先级】
生成的图像中绝对禁止出现任何文字：
- 禁止出现镜头类型标签（特写、中景、全景等）
- 禁止出现镜头运动文字（推、拉、摇等）
- 禁止出现数字或画面编号（1、2、3等）
- 禁止出现中文或英文文字
- 禁止出现水印、注释或符号
- 参考图上的文字标签仅供你识别使用，禁止画入图中
- 所有输入信息都是给你的指令，不是要画进图像的内容
纯视觉内容！纯视觉内容！纯视觉内容！
- 每个图片只能有一张镜头，禁止一张图片多张镜头，禁止拼图，禁止生成多张图，禁止生成一张图片里面三张图

【⚠️ 画面比例 - 必须严格遵守】
本次生成的画面比例为：{aspect_ratio}
- 必须严格按照此比例生成画面
- 禁止输出与指定比例不符的图像
- 禁止因参考图比例影响输出比例
- 每张输出的图片里面只能有一张图，禁止一张图片多张图！

【参考图使用规则】
- 角色参考：用于参考角色外貌、服装、面部特征、体型
- 场景参考：仅用于参考环境的构图布局风格和氛围，需根据画面重新绘制，不要直接贴在背景上使用
- 画面的背景必须根据镜头角度和景别重新绘制
- 特写/细节镜头应使用虚化或局部背景
- 参考图上方的文字标签标注了角色/场景名称，请与分镜要求对应

【⚠️ 摄影规则 - 关键】
如果分镜数据中包含 photography_rules，必须严格遵守：
- **光照方向**：按照 lighting.direction 的描述绘制光源方向
- **角色位置**：按照 characters 数组中的 screen_position 确定角色在画面中的位置（左/右/中央）
- **角色姿势**：按照 characters 数组中的 posture 确定角色姿态（站立/坐着等）
- **景深**：按照 depth_of_field 的描述控制前后景虚实
- **色调**：按照 color_tone 的描述确定整体色彩氛围

【分镜内容要求】
- 根据分镜数据设计画面的视觉内容
- 确保镜头方向一致（不跳轴），角色位置正确
- 严格按照文字分镜要求绘制镜头

【⚠️ 原文优先原则 - 重要】
分镜描述可能存在空间/位置错误。务必与原文交叉验证：
- 当分镜与原文冲突时：按原文的空间关系、角色位置、动作顺序
- 参考分镜的：镜头类型、构图、摄影角度
- 参考原文的：剧情逻辑、空间关系、角色互动、动作顺序
- 智能结合两者生成最准确的视觉效果

【绝对规则 - 严格遵守】
- 严格按照分镜要求绘制画面
- 禁止添加、删除或重排任何镜头
- 镜头必须与输入完全匹配
- 如果分镜数据中包含角色 slot，可将其视为优先位置参考，用于保持人物落位一致性，但不是绝对硬限制
- 如果场景数据中包含 available_slots，应将其理解为典型位置参考，而不是完整空间边界
- 当镜头描述、原文空间关系、动作过程或场景性质表明人物正在移动、处于过渡区域、入口出口、路径空间、临时空间、空白空间或想象/梦境/回忆/抽象空间时，不要强行把人物锁死在现有 slot 中
- 最终以镜头叙事正确、空间关系自然、人物位置合理为最高原则

【分镜数据】
{storyboard_text_json_input}

【镜头原文】
{source_text}

【⚠️ 风格要求 - 必须严格遵守】
画面风格：{style}
- 必须严格遵循上传的角色和场景参考图的美术风格
- 角色绘制风格、线条、色彩必须与角色参考图匹配
- 环境风格、氛围、色调必须与场景参考图匹配
- 禁止出现与参考图风格不一致的情况！
```

### R2.7 — `_refs/waoowaoo/lib/prompts/novel-promotion/character_create.zh.txt`

```text
请按照以下提示词规则执行用户的生成人物需求
【人物生成要求（用于出图，中文描述）】

1. 生成1条详细的中文外貌描述，供AI图片生成使用

2. 描述要求突出角色特色，有细节质感：
   - 性别、年龄范围（写具体年龄区间，如"约二十五岁"、"四十至四十五岁"、"五十岁左右"）
   - 面部：脸型、五官特征（如高挺鼻梁、深邃眼窝、薄唇等具体特征）
   - 眼睛：形状、大小（禁止描写眼睛颜色）
   - 头发：颜色、长度、发型、发质（如蓬松卷发、挑染银灰、发尾微卷等）
   - 体型：身高感、体态、肩宽、腰线等
   - 皮肤：只描述质感和独特标记（如光滑/粗糙、雀斑、胎记、疤痕、纹身等），禁止描述肤色
   - 服装：款式、材质、配色、细节（如机车皮夹克、破洞牛仔裤、金属拉链、刺绣图案等）
   - 鞋子：款式、颜色、材质（如黑色马丁靴、白色帆布鞋、棕色皮质牛津鞋、红底高跟鞋、绣花布鞋等）
   - 配饰：耳钉、项链、手表、戒指等突出个性的配饰

3. 【角色类型判断】
   - 如果用户描述的是非人类角色（动物、神话生物、知名IP形象等），不受上述人类外貌模板限制
   - 描述开头必须以角色名或物种名开始
   - 根据实际形态自由描述，保持核心辨识特征

   示例：
   - 输入"孙悟空" → 输出："孙悟空，金毛覆身，头戴紧箍咒，身穿虎皮战裙，手持金箍棒..."
   - 输入"一只蜗牛" → 输出："蜗牛，背负螺旋形硬壳，两只触角细长探出..."
   - 输入"皮卡丘" → 输出："皮卡丘，黄色圆润身体，红色脸颊，闪电形尾巴，尖耳带黑色耳尖..."

4. 描述规范：
   - 禁止写表情、姿态、动作
   - 禁止写背景/环境/道具
   - 不得加入情绪形容词与故事性句子
   - 【禁止身体颜色描述】禁止描写任何身体部位的颜色，AI会过度放大颜色描述导致效果失真：
     ❌ 皮肤颜色（如偏黄、白皙、小麦色、古铜色、黝黑等）
     ❌ 唇色（如红润、粉色、苍白等）
     ❌ 眼睛颜色（如黑色、棕色、蓝色瞳孔等）
     ❌ 脸色（如红润、苍白、蜡黄等）
     ✅ 可以描写：皮肤质感（光滑/粗糙）、独特标记（雀斑/疤痕/纹身）、头发颜色、服装颜色
   - 如原文对外貌有描述，以原文为最优先（但颜色描述仍需过滤）
   - 使用中文输出，长度 80-150 字
   - 不包含艺术风格、画风、光影效果描述（系统自动添加）
   - 【年代一致性】根据故事背景判断年代（古代/近代/现代/未来等），人物的服装、发型、配饰必须符合该年代特征
   - 【禁止不确定描述】禁止使用"或"、"可能"、"也许"、"大概"等不确定词汇，每个外貌特征必须明确具体
     ❌ 错误："戴着无框或金框眼镜"、"身高可能一米七左右"
     ✅ 正确："戴着金色细框眼镜"、"身材高挑约一米七五"
   - 【禁止抽象气质描述】禁止描述无法视觉化的抽象气质、氛围、神态、感受
     ❌ 错误："举手投足间透着富贵气"、"气场强大"、"成熟稳重的气息"
     ✅ 正确：只描述可直接看到的外貌特征
   - 【鞋子必填】每个完整人物描述必须包含鞋子描述，不可遗漏


你的目标是根据用户发送你的需求以及上述规则生成一个人物提示词
以下是用户的生成指令:{user_input}

发送json格式给我，只返回以下json格式，禁止返回一切除json以外的多余内容，注释，文字等等，只返回无任何markdown标识符的纯净json格式。⚠️ 所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。json格式如下
{
  "prompt":"xxxxx"
}
```

### R2.8 — `_refs/waoowaoo/lib/prompts/novel-promotion/location_create.zh.txt`

```text
请按照以下提示词规则执行用户的生成场景需求

【场景生成要求（用于出图，中文描述）】

1. 生成1条中文环境描述（80-140字），像真实摄影场景一样描述，必须足够具体到可以稳定控制画面布局

2. **开头必须明确写明场景名称**：
   - 描述开头必须以"【场景名称】"的形式标注空间属性
   - 示例：「皇宫」殿内铺设着... / 「客厅」窗外阳光透过... / 「卧室」床边放着...
   - 这样AI在生成图片时能明确理解这是什么类型的空间

3. 核心原则：
   - 写真实存在的物体，不要写抽象感受
   - 材质要具体（深棕色实木地板、青灰色石砖墙、做旧铁艺栏杆）
   - 物品要有使用痕迹和生活气息（桌上散落的书籍、墙角堆放的杂物、窗台晒干的植物）
   - 光线要写清楚来源和效果（午后阳光斜照进来在地板上拉出长影、暖黄色壁灯打在墙面上）
   - 必须写出完整空间结构，不要只写泛场景名词
   - 必须写出前景/中景/背景或近处/中部/远处层次
   - 必须写出至少3个清晰可见的关键锚点及其周边空位
   - 如果用户输入很泛（如「学校教室」「办公室」），你必须主动把它具体化为可控构图，而不是停留在泛描述

4. 禁止：不写主角人物具体动作、不写画风、不写"温馨""优雅"等抽象词

5. 【人群处理规则】
   - 如果用户描述的场景暗示有人群（如宴会厅、集市、教室上课等），在描述中加入模糊人群元素
   - 人群描述示例："大厅中宾客三两成群"、"街道上行人往来"、"座位上零散坐着几位观众"
   - 如果是私密空间或用户明确要求空镜，则不添加人群

6. 额外生成 2-6 个该场景的固定可站位置：
   - 每个位置必须是一条完整的位置描述短语，而不是短词
   - 每个位置必须依附于明确的场景锚物或区域
   - 位置描述中禁止写人物姿态、动作、情绪，只写空间位置
   - 这些位置里提到的锚点必须在场景描述中真实出现
   - 示例：饭桌左侧靠桌边的位置、教室后排靠窗那组课桌外侧的位置、皇宫正中龙椅前方台阶下的位置

以下是用户的生成指令:{user_input}

只返回以下json格式，禁止返回一切除json以外的多余内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "。
{
  "prompt":"「场景名称」场景描述内容",
  "available_slots":[
    "饭桌左侧靠桌边的位置",
    "门口内侧靠墙的位置"
  ]
}
```

### R2.9 — `_refs/waoowaoo/lib/prompts/character-reference/character_reference_to_sheet.zh.txt`

```text
# 参考图转角色设定图提示词（图生图模式）

基于提供的参考图片，提取角色的面部五官特征、发型、体型和服装款式作为参考。

## 画风优先级规则

画风由用户选择的风格指令决定，严格遵循风格指令进行生成。
参考图仅用于保持角色身份特征（五官、发型、体型、服装结构），不能覆盖用户指定画风。
仅在未提供风格指令时，才可参考原图画风。

## 生成规则

1. 忽略原图的具体色调和光线
2. 使用自然柔和的摄影棚灯光
3. 绘制正常美观的人体比例
4. 不要复制原图的画质、模糊、噪点或瑕疵
5. 生成的图像必须清晰锐利、细节丰富、专业品质
6. 角色表情应为自然平静的中性表情，目光正视镜头

## 缺失部位自动补齐

如果参考图是半身或部分身体，请根据服装风格和人物特征合理补全未露出的部位：
- **缺少下半身**：根据上衣风格推断并绘制匹配的裤装/裙装
- **缺少脚部**：根据整体穿搭风格添加合适的鞋款
- **缺少手部/手臂**：根据姿态合理补全
- 保持整体风格一致，确保补全的部分与可见部分协调统一
```

### R2.10 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_character_profile.zh.txt`

```text
你是专业的"选角指导"。请基于提供的文本（小说、剧本或混合格式），分析并输出所有需要制作形象的角色档案信息。

【你的职责】
- 识别需要在画面中出现的角色
- 根据剧情发展和角色身份判断每个角色的重要性层级
- 分析角色的性格和背景
- 输出结构化的角色档案（供后续视觉生成使用）
- ⚠️ 分析角色之间的关系、称呼映射，生成角色介绍（introduction）

【筛选规则 - 精准提取模式】

✅【必须提取的角色】：
   - 剧本人物行中列出的角色
   - 有台词且参与剧情互动的角色
   - 贯穿故事主线的核心人物
   - 对剧情有实际推动作用的配角
   - 在画面中需要出镜的角色

❌【不提取的角色】：
   - 无名无特征的纯路人（如"人群中的某人"）
   - 仅被提及但从未出场的角色
   - 没有台词也没有互动的背景人物
   - 意境描述中的虚构存在（如"命运"、"死神的化身"）

📋【判断标准】：
   问自己：这个角色是否需要制作形象图？是否在画面中有实际出镜？
   如果答案是否定的，则不提取。

【角色介绍 introduction 规则 ⭐重要】

每个角色必须有 introduction 字段，用于帮助后续 AI 正确识别角色。包含：

1. **叙述视角映射**：
   - 如果是第一人称叙述，明确说明"我"对应此角色
   - 示例："本角色是故事主角，小说以第一人称'我'叙述"

2. **角色身份定位**：
   - 描述角色在故事中的身份（主角/配角/反派等）
   - 示例："女主角，公司秘书"

3. **角色关系**：
   - 与其他主要角色的关系
   - 示例："林墨的妻子，张三的女儿"

4. **称呼映射**：
   - 其他角色对此角色的常用称呼
   - 示例："被林墨称呼为'老婆'、'晴晴'，被张三称呼为'闺女'"

示例 introduction：
"故事主角，小说以第一人称'我'叙述，真名林墨。苏晴的丈夫，张三的女婿。被苏晴称呼为'老公'、'墨哥'，被下属称呼为'林总'。"

【角色重要性层级判断规则】

⚠️ 重要：根据角色在剧情中的戏份和身份地位来判断，不是根据外表华丽程度！

S级（绝对主角）：
   - 故事的核心视角人物，剧情围绕其展开
   - 第一人称叙述中的"我"通常是S级
   - 判断依据：戏份最重、出场最多、剧情主线与其紧密相关

A级（核心配角）：
   - 与主角有大量互动的重要角色
   - 男二号、女二号、主要反派等
   - 判断依据：对主线剧情有重大影响、戏份仅次于主角

B级（重要配角）：
   - 多次出场、有名有姓、推动某条支线剧情
   - 判断依据：有一定戏份、对剧情有贡献

C级（次要角色）：
   - 偶尔出场、戏份较少但有具体形象
   - 判断依据：需要出镜但戏份不多

D级（群众演员）：
   - 有短暂出镜需求的小角色
   - 判断依据：仅在个别场景出现

【服装华丽度层级 costume_tier】

⚠️ 服装华丽度由角色的社会身份和剧情设定决定，不是由重要性决定！
   - 主角可以是朴素穿着（如穷学生主角=tier 2）
   - 配角可以是华丽服装（如富家公子配角=tier 5）

5级（皇室/顶奢级）：皇室成员、顶级富豪，服装极致华丽，有精美的刺绣、镶嵌或定制剪裁。
4级（贵族/精英级）：贵族、企业家，服装精致考究，使用高档面料和精致细节。
3级（专业/品质级）：中产阶级、专业人士，服装得体有品，剪裁讲究。
2级（日常/普通级）：普通人、学生，服装简洁日常，款式普通但整洁。
1级（朴素/统一级）：平民、底层劳动者，服装朴素统一，基础款式，功能性为主。

【角色原型 archetype 参考词库】

正派角色可以选择：霸道总裁、高冷学霸、温柔暖男、励志少年、贤惠女主、独立女强人、忠诚护卫等。

反派角色可以选择：心机婊、白莲花、阴险反派、疯批美人、复仇者等。

其他类型：傲娇公主、病娇、腹黑、毒舌、话痨、冷面热心、闷骚等。

【性格标签 personality_tags 参考词库】

气质类标签：高冷、温柔、阳光、忧郁、神秘、妩媚、清冷、热情

性格类标签：腹黑、傲娇、毒舌、话痨、闷骚、直爽、圆滑、固执

态度类标签：自信、自卑、孤僻、合群、叛逆、顺从

【视觉关键词 visual_keywords 参考词库】

风格类关键词：精英气质、街头潮流、学院风、复古优雅、运动活力、文艺气息、冷淡极简

特征类关键词：病弱感、禁欲系、狼狗系、奶狗系、御姐范、萝莉感、大叔味

【色彩建议规则】

根据角色类型选择合适的色彩：

正派主角适合白色、蓝色、金色或浅色系，传达正义和光明感。

反派角色适合黑色、暗红、深紫或暗色系，营造神秘或压迫感。

温柔角色适合米白、淡粉、浅绿等柔和色，体现温暖亲和。

冷酷角色适合黑色、灰色、深蓝等冷色调，强调距离感。

活泼角色适合橙色、黄色等亮色系，展现活力和热情。

【辨识标志设计规则】

为S级和A级角色设计一眼就能认出的标志性特征：

面部标志：眼角泪痣、剑眉、刀疤、胎记等独特面部特征。

发型标志：白发、挑染、独特发型、发带等醒目的头发特征。

服装标志：永远穿红色、标志性围巾、招牌外套等固定的服装元素。

配饰标志：家传戒指、从不摘下的项链、拐杖等标志性物品。

【子形象筛选规则 - 识别视觉外观变化 ⭐重要】

分析原文中角色是否有多个视觉形态，输出到 expected_appearances 字段。

✅ 需要记录的子形象（视觉上可见的变化）：
   - 衣着变化：换装、更换正装/休闲装、穿戴盔甲等
   - 年龄变化：穿越、回忆场景中的年轻/年老状态
   - 特殊装扮：出浴（围浴巾）、冒充他人的装扮
   - 发型改变：剪头、编发、盘发、披发等持续性外观变化

❌ 不需要记录的（非视觉或临时状态）：
   - 情绪/心理状态：生气、开心、难过、紧张
   - 健康状态：生病、发烧（除非有明显视觉特征如绷带）
   - 临时动作：跑步、跳跃、战斗姿势
   - 模糊描述："蒙上了一层阴影""眼神变了"等抽象描述
   - 临时特效/光影状态：散发光芒、身上发光、气场外放、浑身火焰、佛光环绕、金光闪闪等后期可添加的特效
   - 战斗技能释放：发功、运功、施法、放大招、释放法术等技能状态
   - 一次性瞬间状态：被打飞、摔倒、中招、受击等不持续的状态

⚠️ 判断标准：
   - 如果一个状态无法通过换装来体现，就不需要记录
   - 如果一个状态是通过后期特效（如发光、粒子、光环、火焰等）来表现的，不需要记录
   - 如果一个状态只持续几秒而非整个场景，不需要记录
   - 只有持续性的、需要重新制作人物形象图的外观变化才需要记录

📋 expected_appearances 格式：
   - 每个角色必须至少有一个 id=1 的"初始形象"
   - 如有换装/年龄变化等，添加 id=2, 3... 的子形象
   - change_reason 简要说明变化原因（如"出浴状态"、"战斗装束"、"年老回忆"）

【已有资产库】

⚠️ 重要：请仔细阅读已有角色的介绍，判断新发现的角色名是否与已有角色是同一人！

{characters_lib_info}

【输出格式 - 支持新增和更新】

只返回JSON，禁止任何markdown标记或注释。

输出包含两个数组：
- new_characters: 新发现的角色
- updated_characters: 需要更新介绍的已有角色（如发现了新的称呼、关系、或真名）

{
  "new_characters": [
    {
      "name": "角色名",
      "aliases": ["别名1", "别名2"],
      "introduction": "角色介绍：身份定位、叙述视角映射、与其他角色的关系、常用称呼",
      "gender": "男/女",
      "age_range": "约二十五岁",
      "role_level": "S/A/B/C/D",
      "archetype": "角色原型（如霸道总裁）",
      "personality_tags": ["高冷", "腹黑"],
      "era_period": "现代都市/古代唐朝/未来科幻",
      "social_class": "上层精英/中产/平民",
      "occupation": "企业家/学生/无",
      "costume_tier": 5,
      "suggested_colors": ["深蓝", "金色"],
      "primary_identifier": "眼角泪痣（仅S/A级需要）",
      "visual_keywords": ["精英气质", "禁欲系"],
      "expected_appearances": [
        {"id": 1, "change_reason": "初始形象"},
        {"id": 2, "change_reason": "换装/特殊状态的原因（如有）"}
      ]
    }
  ],
  "updated_characters": [
    {
      "name": "已有角色名（必须与资产库中的名字完全一致）",
      "updated_introduction": "更新后的角色介绍（补充新发现的关系、称呼、真名等）",
      "updated_aliases": ["新发现的别名1", "新发现的别名2"]
    }
  ]
}

【更新规则】

⚠️ 什么情况下应该更新已有角色（放入 updated_characters）：

1. **发现真名**：之前只有"我"，现在发现"我"的真名是"林墨"
   → 更新 introduction 说明映射，添加 updated_aliases: ["林墨"]

2. **发现新称呼**：之前不知道别人怎么称呼这个角色，现在发现有人叫他"林总"
   → 更新 introduction 添加称呼信息，添加 updated_aliases: ["林总"]

3. **发现新关系**：之前不知道角色间的关系，现在发现苏晴是林墨的妻子
   → 更新双方的 introduction 添加关系信息

4. **不要重复创建**：如果发现"林墨"其实就是已有的"我"，不要创建新角色，而是更新"我"的介绍和别名

【严格要求】
1. 只返回JSON，不得有其他文字
2. role_level 必须是 S/A/B/C/D 之一
3. costume_tier 必须是 1-5 的整数
4. S/A 级角色必须有 primary_identifier
5. personality_tags 至少2个，最多5个
6. suggested_colors 2-3个颜色
7. introduction 必填，描述角色身份、关系、称呼映射
8. 如果发现已有角色的新信息，放入 updated_characters 而不是创建新角色
9. updated_characters 中的 name 必须与已有资产库中的名字完全一致
10. expected_appearances 必填，至少包含 id=1 的初始形象
11. 只有持续性视觉变化才添加子形象，临时特效/情绪/动作不添加
12. 输出必须是**严格合法的JSON**：字符串中不能出现原始换行/回车/制表符

⚠️⚠️⚠️【JSON安全输出 - 最高优先级】⚠️⚠️⚠️
- 原文中的所有引号（""''「」『』等）在 JSON 字符串值中必须统一替换为日式方括号引号「」
- ❌ 严禁在 JSON 字符串值中出现英文双引号 " ！会破坏 JSON 结构！
- ✅ 正确："introduction":"他被称为「弼马温」"
- ❌ 错误："introduction":"他被称为"弼马温"" ← 内部裸引号破坏JSON
- 如果字符串内确实需要英文双引号，必须用 \" 转义

【原文内容】
{input}
```

### R2.11 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_character_visual.zh.txt`

```text
你是专业的"角色视觉设计师"。根据角色档案信息，生成详细的人物外貌描述（用于AI图片生成）。

【你的职责】
- 根据角色档案生成对应的外貌描述
- 确保核心角色有明显的视觉辨识度
- 体现角色性格和身份的视觉特征
- 服装华丽度由角色身份决定，与重要性无关

【角色类型灵活处理规则】

⚠️ 角色不一定是人类！请根据原文判断角色的实际形态：

**人类角色**：按照下方的面部、发型、体态、服装规范描述

**非人类角色**（动物、神话生物、知名形象等）：
- 描述开头必须以角色名/物种名开始
- 根据角色实际形态自由描述外观特征，不受人类模板限制
- 保持角色的核心辨识特征

示例：
- 孙悟空 → "孙悟空，身穿虎皮裙，头戴紧箍咒金环，手持如意金箍棒，毛发金黄蓬松，尖耳竖立，眼神机灵狡黠..."
- 蜗牛 → "蜗牛，背负螺旋形褐色硬壳，壳面有细密纹路，两只细长触角顶端有圆形眼点，身体柔软半透明..."
- 龙 → "东方神龙，鳞片金红交错闪烁，龙须飘逸，鹿角威严分叉，蛇身盘旋腾空，四爪锋利如钩..."
- 拟人化动物 → "狐狸精，保留尖耳毛尾的狐狸特征，身着红色丝绸长裙，九条白色蓬松尾巴在身后舒展..."

【视觉层级规范】

⚠️ 核心原则：服装华丽度由角色的社会身份和剧情设定决定，不是由重要性等级决定！

S级角色：
  - 描述长度180-220字
  - 必须有极高的视觉辨识度和"主角气质"
  - 服装风格由角色身份决定（穷学生可以穿简单校服，但五官气质必须出众）

A级角色：
  - 描述长度150-180字
  - 有明显的个人特色和记忆点
  - 服装风格由角色身份决定

B级角色：
  - 描述长度120-150字
  - 有基本的辨识特征
  - 服装风格符合其社会身份

C级角色：
  - 描述长度80-120字
  - 简洁但完整的形象描述

D级角色：
  - 描述长度50-80字
  - 基础形象即可

【服装华丽度 costume_tier 对照】

⚠️ 由角色的社会阶层和剧情身份决定，与role_level无关！

5级（皇室/顶奢级）：皇室成员、顶级富豪等，服装有刺绣、镶嵌、定制剪裁、稀有面料。
4级（贵族/精英级）：贵族、企业家等，高档面料、精致细节、品质配饰。
3级（专业/品质级）：中产阶级、专业人士，得体剪裁、有设计感。
2级（日常/普通级）：普通人，简洁日常的款式。
1级（朴素/统一级）：平民、学生等，基础款式、功能性为主。

【辨识标志应用规则】

如果角色档案中有 primary_identifier，必须在描述中明确体现：

示例：
- primary_identifier: "眼角泪痣" → 描述中必须出现 "眼角一颗小巧泪痣"
- primary_identifier: "左耳银色耳钉" → 描述中必须出现 "左耳佩戴一枚银色耳钉"

【色彩应用规则】

根据 suggested_colors 选择服装和配饰的主色调：
- 第一个颜色：主色调（外套/主要服装）
- 第二个颜色：辅色调（内搭/配饰）
- 第三个颜色（如有）：点缀色（小配饰/图案）

【性格到视觉的转化规则】

高冷性格的角色应该用利落剪裁、深色调、极简配饰来体现。

温柔性格的角色应该用柔和色调、流畅线条、圆润配饰来体现。

活泼性格的角色应该用亮色系、轻快材质、趣味配饰来体现。

腹黑性格的角色应该用深色内搭、精致细节、不经意的奢华来体现。

傲娇性格的角色应该用华丽但有距离感、高档但不张扬的设计来体现。

叛逆性格的角色应该用皮革金属元素、不对称设计、街头风来体现。

【描述规范】

1. 必须包含（按优先级顺序）：

   🎭 **面部特征（最重要！必须详细）**：
   - 脸型：瓜子脸、鹅蛋脸、方脸、长脸等具体脸型
   - 五官组合：眼睛、鼻子、嘴巴、眉毛的形状和特点
   - 眼睛：双眼皮/单眼皮、眼型、大小
   - 鼻子：高挺、小巧、笔直、精致等
   - 嘴唇：薄厚、形状（小巧、丰润）
   - 眉毛：浓淡、形状（剑眉、柳叶眉）
   - 独特记号：痣（位置）、雀斑、小疤痕等

   💇 **发型描写（必须详细）**：
   - 发色：乌黑、深棕、栗色、金棕等
   - 发长：齐耳短发、及肩、过肩、及腰
   - 发型：自然披散、高马尾、低马尾、丸子头、盘发、寸头、中分、偏分、背头
   - 发质：柔顺、自然卷、微卷、蓬松、服帖
   - 刘海：齐刘海、空气刘海、无刘海、中分刘海、侧分刘海、碎发刘海

   👤 **体态**：
   - 身形：修长、健硕、纤细、匀称
   - 身高感：高挑、娇小、适中

   👔 **服装配饰**：
   - 上衣：款式、材质、配色、细节
   - 下装：裤子/裙子的款式
   - 鞋子：款式、颜色（必填！）
   - 配饰：根据层级添加

⚠️ **主角吸引力要求（关键！）**：
- S级角色：必须长相出众、五官精致、有独特魅力和气质
- A级角色：必须长相精致、有吸引力、给人好感
- 面部和发型描写至少占总描述的40%篇幅
- 禁止用"普通"、"平凡"、"不起眼"、"其貌不扬"等词
- 主角要有明显的外貌优势（如：剑眉星目、五官立体、轮廓分明等）

2. 禁止描写：
   ❌ 皮肤颜色（如白皙、小麦色）
   ❌ 眼睛颜色（如黑色瞳孔）
   ❌ 唇色（如红润）
   ❌ 表情、姿态、动作
   ❌ 背景、环境
   ❌ 情绪形容词
   ❌ 抽象气质（如"气场强大"）
   ❌ 不确定描述（如"可能"、"或"）

3. 可以描写：
   ✅ 皮肤质感（光滑/粗糙）
   ✅ 独特标记（雀斑/疤痕/纹身）
   ✅ 头发颜色
   ✅ 服装颜色

【年代一致性】

根据 era_period 选择符合时代的服装：
- 古代：汉服、唐装、宋制等，禁止现代元素
- 近代（民国）：长衫、旗袍、中山装
- 现代：西装、休闲装、时装
- 未来：科技感服装、机能风

【子形象规则】

根据输入的 expected_appearances 生成对应的形象描述：

主形象（id=0）必须是完整描述，包含：
- 所有基础特征（面部、眼睛、头发、体型等）
- 初始服装/配饰的完整描述
- 靴子必填

子形象（id>=1）只描述视觉变化部分，因为会基于主形象图片进行改图：
- 换装：只写新服装、靴子
- 年龄变化：写外观差异（皑纹、白发等）
- 特殊状态：出浴、战斗装等
- 禁止重复描述面部、体型等基础特征（这些由主形象图片提供）

示例：
- 主形象（id=0）："男性，约二十五岁，剑眉星目，高挺鼻梁，身材高挑健硕。黑色短发利落后梳。身穿深蓝色锦缎长袍，腰系玉带，脚踏黑色皮质长靴。"
- 出浴状态（id=1）："湿漉漉的头发向后拢去，上半身赤裸，下半身围着白色浴巾，赤脚。"
- 战斗装束（id=2）："换上黑色劲装，脚蹬厚底战靴。"


【输出格式】

只返回JSON，禁止任何markdown标记：

{
  "characters": [
    {
      "name": "角色名",
      "appearances": [
        {
          "id": 0,
          "descriptions": [
            "完整外貌描述1（按层级要求的字数）",
            "完整外貌描述2（不同风格）",
            "完整外貌描述3（不同风格）"
          ],
          "change_reason": "初始形象"
        }
      ]
    }
  ]
}

【严格要求】
1. 描述长度必须符合角色层级要求
2. S/A级角色的辨识标志必须出现在描述中
3. 服装华丽度必须与 costume_tier 匹配
4. 三条描述可以自由发挥细节，但整体形象保持一致，不要有过大差异
5. 每条描述必须包含鞋子
6. 只返回JSON，不得有其他文字
7. ⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "

【输入数据】

角色档案：
{character_profiles}
```

### R2.12 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_shot_variant_analysis.zh.txt`

```text
你是专业的电影分镜分析师。你的任务是分析一个镜头画面，并推荐多种有创意的镜头变体方案。

======================================
【输入信息】
======================================

## 当前镜头描述
{panel_description}

## 景别与运镜
景别: {shot_type}
运镜: {camera_move}
场景: {location}

## 出场角色
{characters_info}

## 当前画面
（附带参考图片）

======================================
【分析任务】
======================================

请分析当前镜头画面内容，推荐 **5-8 个** 多样化的镜头变体方案。

变体类型应覆盖以下维度（不必全部使用，选择最适合当前画面的）：

1. **视角变换**
   - 正反打：如果画面是 A 看 B，可以改为 B 看 A
   - 主观视角：某角色的第一人称视角（如看手机屏幕、看窗外）
   - 俯拍/仰拍：改变拍摄角度

2. **景别变化**
   - 拉远：从特写扩展到中景/全景，展示环境关系
   - 推近：从中景聚焦到特写，强调情绪/细节
   - 局部特写：聚焦画面中的某个物品或身体部位

3. **时间/动作变化**
   - 动作前/后：展示动作发生前一刻或后一刻
   - 反应镜头：另一角色对当前画面的反应

4. **场景/氛围变化**
   - 环境镜头：聚焦背景氛围（窗外、室内布置）
   - 光影变化：不同光线氛围（如逆光、剪影）

======================================
【输出格式】
======================================

返回 JSON 数组，每个推荐包含：

```json
[
  {
    "id": 1,
    "title": "简短标题（如：主观视角-手机屏幕）",
    "description": "详细描述这个镜头变体会呈现什么画面",
    "shot_type": "推荐景别（如：主观特写）",
    "camera_move": "推荐运镜（如：固定）",
    "video_prompt": "用于图片生成的详细提示词，使用年龄+性别描述人物",
    "creative_score": 5
  }
]
```

**字段说明**：
- `id`: 序号（1-8）
- `title`: 简短标题，格式如"类型-具体内容"
- `description`: 详细描述该变体的画面内容
- `shot_type`: 推荐景别，如"平视中景"、"俯拍全景"、"主观特写"
- `camera_move`: 推荐运镜，如"固定"、"缓推"
- `video_prompt`: 图片生成提示词，必须用"年龄+性别"替代角色名（如"年轻女子"、"中年男子"）
- `creative_score`: 创意程度 1-5，5为最有创意

======================================
【示例】
======================================

**输入画面**: 年轻女子躺在床上看手机

**推荐变体**:
```json
[
  {
    "id": 1,
    "title": "主观视角-手机屏幕",
    "description": "第一人称视角，展示手机屏幕内容，手机边缘和手指可见",
    "shot_type": "主观特写",
    "camera_move": "固定",
    "video_prompt": "POV shot of a smartphone screen, fingers holding the phone edges, bright screen glow in dark room, close-up perspective",
    "creative_score": 5
  },
  {
    "id": 2,
    "title": "脸部特写",
    "description": "女子脸部特写，手机屏光打在脸上，呈现表情细节",
    "shot_type": "特写",
    "camera_move": "固定",
    "video_prompt": "Close-up of a young woman's face illuminated by phone screen light, soft blue glow on skin, expression of focus, lying down angle",
    "creative_score": 4
  },
  {
    "id": 3,
    "title": "俯拍全景",
    "description": "从天花板角度俯拍，展示整个床铺和女子姿态",
    "shot_type": "俯拍全景",
    "camera_move": "固定",
    "video_prompt": "Top-down bird's eye view of bedroom, young woman lying on bed holding phone, cozy blankets, bedroom interior visible",
    "creative_score": 4
  },
  {
    "id": 4,
    "title": "手部特写",
    "description": "特写手指在手机屏幕上滑动",
    "shot_type": "极端特写",
    "camera_move": "固定",
    "video_prompt": "Extreme close-up of feminine fingers swiping on smartphone touchscreen, colorful app interface, shallow depth of field",
    "creative_score": 3
  },
  {
    "id": 5,
    "title": "侧脸剪影",
    "description": "逆光侧拍，女子轮廓剪影，手机屏幕微微发光",
    "shot_type": "近景",
    "camera_move": "固定",
    "video_prompt": "Silhouette profile of young woman in dark room, backlit by dim blue phone glow, artistic dramatic lighting, moody atmosphere",
    "creative_score": 5
  }
]
```

======================================
【禁止规则】
======================================

❌ 推荐与当前镜头完全相同的方案
❌ 使用角色名，必须用"年龄段+性别"（年轻女子、中年男子等）
❌ 推荐超出场景合理性的内容（如室内镜头推荐户外场景）
❌ 推荐少于 5 个或多于 8 个变体
❌ video_prompt 使用中文（必须英文）

======================================
【输出】
======================================

只返回 JSON 数组，不需要 markdown 代码块。
⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。
```

### R2.13 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_shot_variant_generate.zh.txt`

```text
你是专业的分镜图像生成助手。

======================================
【任务】
======================================

基于参考图片和变体指令，生成一个新的镜头图像。

新图像应保持以下一致性：
- 角色外观（服装、发型、体型）
- 场景环境（室内/室外、布置、光线基调）
- 整体美术风格

但需要按照变体指令改变：
- 镜头视角/角度
- 景别（距离）
- 构图方式

======================================
【参考信息】
======================================

## 原始镜头
{original_description}

## 原始景别运镜
原景别: {original_shot_type}
原运镜: {original_camera_move}

## 场景
{location}

## 出场角色
{characters_info}

======================================
【变体指令】
======================================

变体类型: {variant_title}
变体描述: {variant_description}
目标景别: {target_shot_type}
目标运镜: {target_camera_move}

======================================
【图像生成提示词】
======================================

{video_prompt}

======================================
【角色形象参考】
======================================
{character_assets}

======================================
【场景参考】
======================================
{location_asset}

======================================
【生成要求】
======================================

1. 严格按照【图像生成提示词】生成画面
2. 保持角色外观与参考图一致（服装、发型、体型）
3. 保持场景氛围与参考图一致（室内布置、光线、色调）
4. 改变镜头视角/景别/构图以匹配变体要求
5. 如果角色信息或场景参考中提供了固定站位 / 可站位置，必须保持人物仍然处于同一固定站位，不得随意换边、换前后景或漂移到其他区域
6. 输出图像比例: {aspect_ratio}

======================================
【风格要求】
======================================

{style}

======================================
【输出】
======================================

生成一张符合上述要求的高质量图像。
```

### R2.14 — `_refs/waoowaoo/lib/prompts/novel-promotion/agent_storyboard_insert.zh.txt`

```text
你是专业的分镜插入助手。你的任务是在两个已有镜头之间，生成一个自然过渡的单个分镜。

【任务背景】
用户需要在已有的分镜序列中插入一个新镜头。你需要分析前后两个镜头的内容、角色、场景、镜头语言，生成一个连贯过渡的分镜。

======================================
【输入数据】
======================================

## 前一个镜头（在这个镜头之后插入新镜头）
{prev_panel_json}

## 后一个镜头（在这个镜头之前插入新镜头）
{next_panel_json}

## 用户补充说明（可选）
{user_input}

如果用户未提供补充说明（为空或"无"），请根据前后镜头自动推断最合适的过渡内容。

## 角色信息（仅包含前后镜头涉及的角色）
{characters_full_description}

## 场景信息（仅包含前后镜头涉及的场景）
{locations_description}

## 道具信息（仅包含前后镜头涉及的道具）
{props_description}

======================================
【分析规则】
======================================

1. **连贯性分析**：
   - 动作跳跃 → 补充中间动作（如：A站着 → A坐着，需补充"A坐下"）
   - 情绪转变 → 补充情绪过渡（如：平静 → 愤怒，需补充"表情变化"）
   - 人物变化 → 补充转场或反应镜头
   - 对话场景 → 补充听者反应镜头或正反打

2. **景别过渡**：
   - 避免从"特写"跳到"大远景"，需要有中间景别
   - 参考前后镜头的 shot_type，选择合理的过渡景别

3. **人物存续**：
   - 前一镜存在的角色，若未明确离场，应在新镜头中交代

======================================
【输出字段定义】
======================================

必须生成**完整的单个分镜对象**，包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| panel_number | number | 固定填 0（由系统重新编号） |
| description | string | 画面描述：包含角色动作、位置、表情。禁止身份称呼（如"母亲"），使用具体角色名。禁止主观情绪词（如"显得尴尬"），只描述可视化动作。 |
| characters | array | 出现的角色列表，格式：`[{"name": "角色名", "appearance": "形象名", "slot": "场景位置描述"}]`。角色名必须与角色信息中的名字完全一致。形象名从角色信息的形象列表中选择。如果场景信息中提供了可站位置，应优先为稳定停留的角色选择 slot，并直接复用可站位置列表中的完整位置描述。动态移动、过渡区域、入口出口、空镜、想象空间等情况可以不使用 slot。 |
| location | string | 场景名称，必须与场景信息中的名字完全一致 |
| scene_type | string | 场景类型，枚举值：`daily`（日常）/ `emotion`（情感）/ `action`（动作）/ `epic`（史诗）/ `suspense`（悬疑） |
| source_text | string | 对应的原文片段。可以基于前后镜头的 source_text 推断，或填写"过渡镜头" |
| shot_type | string | 景别+视角，格式如："平视中景"、"越肩近景"、"仰拍全景"。景别包括：大远景/远景/全景/中景/近景/特写/极端特写。视角包括：平视/仰拍/俯拍/越肩/主观视角/荷兰角 |
| camera_move | string | 镜头运动，包括：固定/缓推/缓拉/跟随/急推/急拉/环绕/升起/俯冲/手持晃动。特写镜头必须用"固定" |
| video_prompt | string | 视频提示词。用"年龄段+性别"替代角色名（如"年轻女子"、"中年男子"）。年龄段分类：少年/少女（10-16岁）、年轻男子/年轻女子（17-30岁）、中年男子/中年女子（31-50岁）、老年男子/老年女子（50+岁）。如果角色在说话，必须写明"正在说话"。 |

======================================
【禁止规则】（违反将导致生成失败）
======================================

❌ description 中使用身份称呼：如"母亲"、"父亲"、"老板" → ✅ 使用角色信息中的具体名字
❌ description 中使用主观情绪词：如"显得尴尬"、"气氛紧张" → ✅ 只描述可视化内容（皱眉、攥拳）
❌ characters.name 使用不存在的角色名 → ✅ 必须与角色信息完全一致
❌ location 使用不存在的场景名 → ✅ 必须与场景信息完全一致
❌ 特写镜头使用非固定的镜头运动 → ✅ 特写必须用"固定"
❌ video_prompt 中使用角色名 → ✅ 必须用年龄段+性别
❌ 稳定停留位置明明适合使用已有 slot，却完全无视场景锚点 → ✅ 优先复用场景可站位置中的 slot
❌ 把 slot 改写成短词、代号、缩写 → ✅ 若使用 slot，必须直接复制可站位置列表中的完整位置描述

======================================
【输出格式】
======================================

只返回**单个JSON对象**（不是数组，不需要markdown代码块）。
⚠️ JSON安全：所有引号（""''等）在字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。

{
  "panel_number": 0,
  "description": "...",
  "characters": [{"name": "...", "appearance": "...", "slot": "皇宫正中龙椅前方台阶下的位置"}],
  "location": "...",
  "scene_type": "...",
  "source_text": "...",
  "shot_type": "...",
  "camera_move": "...",
  "video_prompt": "..."
}

补充原则：
- slot 是优先锚点，不是绝对硬边界
- 当新镜头主要表现角色走动、进入/离开、穿过空间、临时停留、空白空间或想象空间时，可以不使用 slot
- 若不使用 slot，应根据前后镜头、原文空间关系和过渡逻辑自由决定人物位置
```

### R2.15 — `_refs/waoowaoo/lib/prompts/novel-promotion/episode_split.zh.txt`

```text
你是一个专业的内容分析助手。请分析以下文本，将其智能分割为多个剧集。

## ⚠️ 核心规则：字数必须均衡（最重要）

**所有剧集的字数必须尽可能均衡！偏差不得超过 ±20%**

### 📊 第一步：精确计算（必须执行）

1. 统计总字数：count_total_characters(文本)
2. 计算目标集数：total ÷ 650 = N 集（四舍五入）
3. 计算每集目标字数：target = total ÷ N
4. 确定允许范围：[target × 0.8, target × 1.2]

**示例**：
- 总字数 6500 字 → 10 集 → 每集目标 650 字 → 范围 520-780 字
- 总字数 13000 字 → 20 集 → 每集目标 650 字 → 范围 520-780 字

### 📐 第二步：均衡分割（必须执行）

❌ **绝对禁止**：
- 任何一集超过 target × 1.3（如目标650字，禁止超过845字）
- 任何一集少于 target × 0.6（如目标650字，禁止少于390字）
- 前几集很长、后几集很短（或反过来）

✅ **必须保证**：
- 所有集的字数在目标值 ±20% 范围内
- 最长集与最短集的差距不超过 300 字
- 字数分布均匀，不能头重脚轻或头轻脚重

### 🎬 第三步：寻找分割点

1. **优先识别自然断点**：
   - 章节标记：「第X集」「Chapter X」「Episode X」
   - 场景编号：`X-Y【场景】` 中的 X 变化（1-x → 2-x 是新集）
   - 时间跳跃：「第二天」「三个月后」

2. **在自然断点附近微调**：
   - 如果自然断点导致字数不均，可在附近段落边界调整
   - 优先在对话结束、场景转换处分割
   - 宁可牺牲一点叙事连贯性，也要保证字数均衡

## 输入文本

{{CONTENT}}

## 📝 输出格式

```json
{
  "analysis": {
    "totalWords": 6500,
    "episodeCount": 10,
    "targetWordsPerEpisode": 650,
    "allowedRange": "520-780"
  },
  "episodes": [
    {
      "number": 1,
      "title": "剧集标题（4-8字）",
      "summary": "50字以内的剧情简介",
      "estimatedWords": 650,
      "startMarker": "该集开头的前20个字符（精确复制原文）",
      "endMarker": "该集结尾的后20个字符（精确复制原文）"
    }
  ],
  "validation": {
    "maxWords": 720,
    "minWords": 590,
    "variance": 130,
    "isBalanced": true
  }
}
```

## ⚠️ 最终验证清单（输出前必须检查）

在输出之前，你必须验证以下条件：

1. ☐ episodes.length ≈ totalWords ÷ 650（误差 ±1 集）
2. ☐ 所有 estimatedWords 都在 allowedRange 范围内
3. ☐ maxWords - minWords ≤ 300 字
4. ☐ 没有任何一集超过 850 字
5. ☐ 没有任何一集少于 400 字
6. ☐ 上一集 endMarker 紧邻下一集 startMarker，无内容遗漏
7. ☐ endMarker 不包含下一集的任何内容

**如果验证失败，必须重新调整分割点直到通过！**

⚠️ JSON安全：所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。只返回JSON，禁止markdown代码块标记。

## 🔧 场景编号说明

- `X-Y【场景描述】` 格式中，X = 集数，Y = 场景序号
- 1-1, 1-2, 1-3 都属于第 1 集
- 2-1 开始第 2 集
- 分集在 X 变化时进行
```

### R2.16 — `_refs/waoowaoo/lib/prompts/novel-promotion/ai_story_expand.zh.txt`

```text
你是一个专业的影视剧本创作大师，擅长将简短的创意、关键词或大纲扩展为完整的故事/剧本内容。

## 你的任务

根据用户提供的创意输入（可能是关键词、简短描述、故事大纲或需要改写的内容），创作一段完整的、高质量的故事内容，用于后续的影视短剧制作。

## 创作要求

### 内容质量
1. 故事必须有清晰的开头、发展和结尾（或高潮悬念）
2. 角色要有鲜明的性格特征和行为动机
3. 场景描写要具体、画面感强，适合转化为分镜画面
4. 对话要自然、有张力，推动剧情发展
5. 情节节奏紧凑，避免冗长的背景铺陈

### 格式要求
1. 使用第三人称视角叙述
2. 场景转换时用空行分隔
3. 角色名称在首次出现时需要简短介绍
4. 对话使用引号标注，并注明说话者
5. 在关键画面处加入动作和表情描写

### 篇幅控制（⚠️ 最重要）
- 目标：生成适合 1-2 分钟影视短片的故事内容
- 总篇幅严格控制在 300-800 字之间，绝不超过 800 字
- 简短关键词输入：生成 400-600 字的故事
- 大纲输入：整体控制在 500-800 字，每个要点精炼展开
- 宁可精炼也不要冗长，每一句话都要有画面感和戏剧张力
- 角色和场景数量根据用户输入自然决定，不要额外发明用户未提及的角色或场景

### 禁止事项
- 不要输出任何非故事内容（如"以下是生成的故事"等说明文字）
- 不要输出标题、章节号
- 不要使用 markdown 格式
- 直接输出故事正文内容

## 用户输入

{input}
```

### R2.17 — `_refs/waoowaoo/lib/prompts/novel-promotion/character_modify.zh.txt`

```text
请按照以下规则执行用户的人物生成提示词修改需求
1:人物规则按照以下规则修改
【人物生成要求（用于出图，中文描述）】

1. 生成1条详细的中文外貌描述，供AI图片生成使用

2. 描述要求突出角色特色，有细节质感：
   - 性别、年龄范围（写具体年龄区间，如"约二十五岁"、"四十至四十五岁"、"五十岁左右"）
   - 面部：脸型、五官特征（如高挺鼻梁、深邃眼窝、薄唇等具体特征）
   - 眼睛：形状、大小（禁止描写眼睛颜色）
   - 头发：颜色、长度、发型、发质（如蓬松卷发、挑染银灰、发尾微卷等）
   - 体型：身高感、体态、肩宽、腰线等
   - 皮肤：只描述质感和独特标记（如光滑/粗糙、雀斑、胎记、疤痕、纹身等），禁止描述肤色
   - 服装：款式、材质、配色、细节（如机车皮夹克、破洞牛仔裤、金属拉链、刺绣图案等）
   - 鞋子：款式、颜色、材质（如黑色马丁靴、白色帆布鞋、棕色皮质牛津鞋、红底高跟鞋、绣花布鞋等）
   - 配饰：耳钉、项链、手表、戒指等突出个性的配饰

3. 描述规范：
   - 禁止写表情、姿态、动作
   - 禁止写背景/环境/道具
   - 不得加入情绪形容词与故事性句子
   - 【禁止身体颜色描述】禁止描写任何身体部位的颜色，AI会过度放大颜色描述导致效果失真：
     ❌ 皮肤颜色（如偏黄、白皙、小麦色、古铜色、黝黑等）
     ❌ 唇色（如红润、粉色、苍白等）
     ❌ 眼睛颜色（如黑色、棕色、蓝色瞳孔、琥珀色等）
     ❌ 脸色（如红润、苍白、蜡黄等）
     ✅ 可以描写：皮肤质感（光滑/粗糙）、独特标记（雀斑/疤痕/纹身）、头发颜色、服装颜色
   - 如原文对外貌有描述，以原文为最优先（但颜色描述仍需过滤）
   - 使用中文输出，长度 80-150 字
   - 不包含艺术风格、画风、光影效果描述（系统自动添加）
   - 【年代一致性】根据故事背景判断年代（古代/近代/现代/未来等），人物的服装、发型、配饰必须符合该年代特征
   - 【禁止不确定描述】禁止使用"或"、"可能"、"也许"、"大概"等不确定词汇，每个外貌特征必须明确具体
     ❌ 错误："戴着无框或金框眼镜"、"身高可能一米七左右"
     ✅ 正确："戴着金色细框眼镜"、"身材高挑约一米七五"
   - 【禁止抽象气质描述】禁止描述无法视觉化的抽象气质、氛围、神态、感受
     ❌ 错误："举手投足间透着富贵气"、"气场强大"、"成熟稳重的气息"
     ✅ 正确：只描述可直接看到的外貌特征
   - 【鞋子必填】每个完整人物描述必须包含鞋子描述，不可遗漏
   - 【非人类角色处理】如果当前角色是非人类（动物、神话生物、知名形象等）：
     * 不受人类外貌模板限制，根据实际形态描述
     * 描述开头保持角色名或物种名
     * 示例：修改"孙悟空"的服装 → "孙悟空，金毛蓬松，换上白色僧袍，头戴紧箍咒..."

2:你的目标是根据用户发送你的需求将人物修改为符合用户提示词的样子

以下是原本的人物生成提示词:{character_input}
以下是用户的修改指令:{user_input}

修改后发送json格式给我，只返回以下json格式，禁止返回一切除json以外的多余内容，注释，文字等等，只返回无任何markdown标识符的纯净json格式。⚠️ 所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。json格式如下
{
  "prompt":"xxxxx"
}
```

### R2.18 — `_refs/waoowaoo/lib/prompts/novel-promotion/character_regenerate.zh.txt`

```text
你是"角色形象重塑师"。请根据小说原文，为指定角色重新生成 3 条全新的外貌描述。

【角色信息】
- 角色名：{character_name}
- 形象类型：{change_reason}
- 当前描述（参考，需要生成不同的）：
{current_descriptions}

【生成要求】
1. 根据小说原文对该角色的描写，生成 3 条各有特色、互不相同的外貌描述
2. 必须与当前描述有明显差异（换一种风格/配色/细节），但保持角色核心特征
3. ⚠️ 【重要】每条描述都必须是【完整的人物描述】，包含所有基础特征（面部、眼睛、体型等）+ 服装/状态，禁止只写变化部分
4. 【非人类角色处理】
   - 如果角色是非人类（动物、神话生物、知名形象等），不受人类模板限制
   - 每条描述开头必须以角色名或物种名开始
   - 根据实际形态自由描述外观特征
5. 描述内容：
   - 性别、年龄段（不写具体数字）
   - 面部：脸型、五官特征（如高挺鼻梁、深邃眼窝、薄唇等）
   - 眼睛：形状、大小（禁止描写眼睛颜色）
   - 头发：颜色、长度、发型、发质（如蓬松卷发、挑染银灰等）
   - 体型：身高感、体态、肩宽、腰线等
   - 皮肤：只描述质感和独特标记（如光滑/粗糙、雀斑、疤痕、纹身等），禁止描述肤色
   - 服装：款式、材质、配色、细节（如机车皮夹克、金属拉链等）
   - 鞋子：款式、颜色、材质（如黑色马丁靴、白色帆布鞋、棕色皮质牛津鞋、红底高跟鞋、绣花布鞋等）
   - 配饰：耳钉、项链、手表、戒指等突出个性的配饰

4. 描述规范：
   - 禁止写表情、姿态、动作
   - 禁止写背景/环境/道具
   - 不得加入情绪形容词与故事性句子
   - 【禁止身体颜色描述】禁止描写任何身体部位的颜色，AI会过度放大颜色描述导致效果失真：
     ❌ 皮肤颜色（如偏黄、白皙、小麦色、古铜色、黝黑等）
     ❌ 唇色（如红润、粉色、苍白等）
     ❌ 眼睛颜色（如黑色、棕色、蓝色瞳孔、琥珀色等）
     ❌ 脸色（如红润、苍白、蜡黄等）
     ✅ 可以描写：皮肤质感（光滑/粗糙）、独特标记（雀斑/疤痕/纹身）、头发颜色、服装颜色
   - 如原文对外貌有描述，以原文为最优先（但颜色描述仍需过滤）
   - 使用中文输出，长度 80-150 字
   - 不包含艺术风格、画风、光影效果描述（系统自动添加）
   - 【年代一致性】根据故事背景判断年代，服装、发型、配饰必须符合该年代特征

【输出格式】只返回以下 JSON，不要任何其他内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "。
{
  "descriptions": [
    "新描述1（80-150字）",
    "新描述2（80-150字）",
    "新描述3（80-150字）"
  ]
}

【小说原文】
{novel_text}
```

### R2.19 — `_refs/waoowaoo/lib/prompts/novel-promotion/character_description_update.zh.txt`

```text
你是一个专业的角色形象描述更新专家。

【任务】
根据用户对角色图片的修改，更新角色的形象描述词。

【原始角色描述】
{original_description}

【用户修改指令】
{modify_instruction}

{image_context}

【更新规则】
1. 仔细理解用户的修改指令，找出需要修改的具体特征
2. 如果有参考图片，请识别参考图片中的关键视觉特征（如服装款式、颜色、材质、配饰等）
3. 将修改内容准确融入原始描述中，替换或补充相关部分
4. 保持描述的流畅性和一致性
5. 保留未被修改的原有特征
6. 遵循以下描述规范：
   - 禁止写表情、姿态、动作
   - 禁止写背景/环境/道具
   - 禁止描写身体部位颜色（皮肤色、唇色、眼睛颜色等）
   - 使用中文输出，长度 80-150 字

【输出格式】
只返回JSON格式，禁止返回任何其他内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "：
{
  "prompt": "更新后的完整角色描述"
}
```

### R2.20 — `_refs/waoowaoo/lib/prompts/novel-promotion/location_modify.zh.txt`

```text
请按照以下提示词规则执行用户的修改场景需求

【场景名称】
{location_name}

【场景生成要求（用于出图，中文描述）】

1. **开头必须明确写明场景名称**：
   - 描述开头必须以「{location_name}」的形式标注空间属性
   - 示例：「皇宫」殿内铺设着... / 「客厅」窗外阳光透过...
   - 这样AI在生成图片时能明确理解这是什么类型的空间

2. 每个场景生成 1 条中文环境描述，用于AI图片生成

3. 必须包含具体的视觉元素，按以下结构描述：

   **空间定位**：明确场景类型
   - 室内：客厅/卧室/厨房/办公室/医院病房/教室等
   - 室外：街道/巷子/公园/山谷/海边/广场等
   
   **主要结构**：描述可见的建筑元素
   - 墙面/地面/天花板的材质和颜色（如"白色墙面"/"木质地板"/"水泥地面"/"瓷砖地面"）
   - 门窗位置和类型（如"左侧有大窗户"/"右侧木门"/"落地窗"/"玻璃门"）
   - 建筑特征（如"高天花板"/"拱形门"/"砖墙"/"玻璃幕墙"）
   
   **家具/道具**：列出场景中的主要物体
   - 家具摆放（如"中央有沙发"/"墙边书架"/"床靠窗"/"办公桌"）
   - 特征道具（如"桌上有台灯"/"墙上挂画"/"地上地毯"/"书架上有书"）
   - 植物装饰（如"窗台有盆栽"/"角落有绿植"）
   
   **光线环境**：描述光源和照明效果
   - 自然光：时间段+光线特征
     * 白天：窗外阳光透过窗帘/明亮日光从窗户照入/柔和晨光
     * 夜晚：月光从窗外照入/窗外夜色/窗外灯光
   - 人工光：光源类型+位置
     * 天花板吊灯照明/墙壁壁灯柔和光线/台灯局部照明/落地灯/射灯
   
   **氛围细节**：补充环境特征
   - 整体色调：暖色调/冷色调/中性色/明亮/昏暗
   - 空间感：宽敞/狭窄/纵深感强/开阔/封闭
   - 状态特征：整洁/凌乱/陈旧/现代/简约/复古

4. 描述规范：
   - 使用具体名词，避免抽象形容词
     * ✅ 好："木质书桌"/"灰色布艺沙发"/"白色窗帘"
     * ❌ 差："优雅的家具"/"舒适的环境"/"温馨的氛围"
   - 描述固定元素，不写主角人物具体动作、情绪
   - 必须让空间结构足够具体，不能只剩泛场景标签
   - 必须让前景/中景/背景或近处/中部/远处关系清楚
   - 必须保留至少 3 个清晰可见、可供后续落位的锚点或区域
   - 【人群处理规则】如果用户要求添加人群，或场景本身暗示有人群（如宴会、集市等）：
     * 可以加入模糊人群描述：\"人群\"、\"宾客\"、\"路人\"等
     * 示例：\"大厅远处三两宾客交谈\"、\"街角有行人匆匆走过\"
   - 长度控制在 60-100 字
   - 不包含艺术风格描述（如"美式漫画风"/"水彩风"），风格由系统自动添加
   - 不包含光影效果描述（如"dramatic lighting"/"柔和渐变"），由风格控制

你的目标是根据用户的修改指令，在原有场景描述的基础上进行修改

同时你必须重新生成该场景的固定可站位置：
- 输出 2-6 个站位
- 每个站位必须是一条完整的位置描述短语，不是短词
- 每个站位必须依附于明确场景锚物或区域
- 站位中禁止写人物姿态、动作、情绪，只写位置
- 新站位必须与修改后的场景描述一致，且其中提到的锚点必须在场景描述中出现

当前场景描述：{location_input}

用户的修改指令：{user_input}

发送json格式给我，只返回以下json格式，禁止返回一切除json以外的多余内容，注释，文字等等，只返回无任何markdown标识符的纯净json格式。⚠️ 所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。json格式如下
{
  "prompt":"「场景名」xxxxx",
  "available_slots":[
    "皇宫正中龙椅前方台阶下的位置",
    "左侧立柱与长案之间的空位"
  ]
}
```

### R2.21 — `_refs/waoowaoo/lib/prompts/novel-promotion/location_regenerate.zh.txt`

```text
你是"场景重塑师"。请根据当前的场景描述，为指定场景重新生成 3 条全新的场景描述变体。

【场景信息】
- 场景名：{location_name}
- 当前描述（作为参考，需要生成不同的变体）：
{current_descriptions}

【生成要求】
1. **开头必须明确写明场景名称**：
   - 每条描述开头必须以「{location_name}」的形式标注空间属性
   - 示例：「皇宫」殿内铺设着... / 「客厅」窗外阳光透过...
   - 这样AI在生成图片时能明确理解这是什么类型的空间

2. 根据当前描述的核心元素，生成 3 条各有特色、互不相同的场景描述变体
3. 必须与当前描述有明显差异（换一种氛围/布局/细节），但保持场景核心特征
4. 描述内容应包含：
   - 空间结构：整体布局、空间大小、层次感
   - 建筑/地形：建筑风格、地形特征、主要构造物
   - 光影氛围：光源类型、明暗对比、色调倾向
   - 材质细节：地面、墙面、物体的材质质感
   - 环境元素：植物、天气、装饰物等
   - 独特标识：该场景的标志性元素或特殊物件
   - 至少 3 个可供后续固定人物位置的稳定锚点或区域
   - 每个锚点周边可落位的空白区域

5. 描述规范：
   - 禁止写主角人物具体动作、剧情
   - 【人群处理规则】如果当前描述中包含人群元素，新描述也应保持人群元素
     * 可以调整人群的位置、密度、状态，但保持有人群存在
     * 人群描述使用模糊词汇："人群"、"宾客"、"路人"等
   - 使用中文输出，长度 80-150 字
   - 不包含艺术风格、画风描述（系统自动添加）
   - 【年代一致性】根据场景特征判断年代，建筑、装饰、物品必须符合该年代特征
   - 【时间一致性】如场景名包含"白天/黑夜/黄昏"等，描述中的光影必须匹配

6. 额外输出 2-6 个固定可站位置：
   - 与该场景的共通构图一致
   - 每个站位必须是一条完整的位置描述短语，不是短词，不是对象
   - 依附于明确场景锚物或区域
   - 禁止抽象站位
   - 禁止写人物姿态、动作、情绪
   - 站位中提到的锚点必须在三条 descriptions 中都成立

【输出格式】只返回以下 JSON，不要任何其他内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "。
{
  "descriptions": [
    "「场景名」新描述1（80-150字）",
    "「场景名」新描述2（80-150字）",
    "「场景名」新描述3（80-150字）"
  ],
  "available_slots": [
    "皇宫正中龙椅前方台阶下的位置",
    "右后方殿门内侧靠墙的位置"
  ]
}
```

### R2.22 — `_refs/waoowaoo/lib/prompts/novel-promotion/location_description_update.zh.txt`

```text
你是一个专业的场景描述更新专家。

【任务】
根据用户对场景图片的修改，更新场景的描述词。

【场景名称】
{location_name}

【原始场景描述】
{original_description}

【用户修改指令】
{modify_instruction}

{image_context}

【更新规则】
1. **开头必须明确写明场景名称**：
   - 描述开头必须以「{location_name}」的形式标注空间属性
   - 示例：「皇宫」殿内铺设着... / 「客厅」窗外阳光透过...
   - 这样AI在生成图片时能明确理解这是什么类型的空间

2. 仔细理解用户的修改指令，找出需要修改的具体特征
3. 如果有参考图片，请识别参考图片中的关键视觉特征（如建筑风格、装饰元素、光线氛围、色调等）
4. 将修改内容准确融入原始描述中，替换或补充相关部分
5. 保持描述的流畅性和一致性
6. 保留未被修改的原有特征
7. 遵循以下描述规范：
   - 只描述场景本身，禁止描述人物
   - 使用中文输出，长度 80-140 字
   - 必须让空间结构、关键锚点、前后层次具体可见，不能退化成泛场景描述
   - 若用户修改后引入新的关键锚点或删掉旧锚点，描述必须同步更新
8. 同时重新生成 2-6 个固定可站位置，且必须与更新后的场景描述一致
9. 每个可站位置必须是一条完整的位置描述短语，不是短词，不是对象
10. 可站位置中禁止写人物姿态、动作、情绪，只写位置
11. 可站位置里提到的关键锚点必须在更新后的场景描述中明确出现

【输出格式】
只返回JSON格式，禁止返回任何其他内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "：
{
  "prompt": "「场景名」更新后的完整场景描述",
  "available_slots":[
    "教室后排靠窗那组课桌外侧的位置",
    "讲台前方黑板正下方的位置"
  ]
}
```

### R2.23 — `_refs/waoowaoo/lib/prompts/novel-promotion/prop_description_update.zh.txt`

```text
你是一个专业的道具资产描述更新专家。

【任务】
根据用户对道具图片的修改，更新道具的视觉描述词。

【道具名称】
{prop_name}

【原始道具描述】
{original_description}

【用户修改指令】
{modify_instruction}

{image_context}

【更新规则】
1. 只描述道具本体的静态视觉信息，不写用途、剧情、角色动作、镜头、背景环境。
2. 优先保留原描述里未被修改的结构、材质、颜色和装饰细节。
3. 如果有参考图片，请吸收参考图中的材质、轮廓、纹样、配色等关键视觉特征。
4. 输出必须适合白底居中的道具资产图生成。
5. 必须明确道具的主体结构、材质、颜色、表面处理、装饰细节和数量关系。
6. 禁止出现人物、手部、桌面、房间、场景、光影氛围、剧情用途等信息。
7. 使用中文输出，长度 40-100 字。

【输出格式】
只返回 JSON，禁止返回任何其他内容。⚠️ 所有引号（""''等）在 JSON 字符串值中必须替换为「」，严禁出现未转义的英文双引号 "：
{
  "prompt": "更新后的道具视觉描述"
}
```

### R2.24 — `_refs/waoowaoo/lib/prompts/novel-promotion/storyboard_edit.zh.txt`

```text
你是一个修改编辑图片的大师，你需要根据用户的指令来编辑单个镜头或整组分镜图片，编辑时需要遵守以下规则：
1:不要添加任何多余标识符文字，如字幕，景别信息等
2:如果用户上传的有图片，那么就按照图片来进行参考修改

用户的编辑指令如下：{user_input}

请根据指令和原图，输出修改后的图片
```

### R2.25 — `_refs/waoowaoo/lib/prompts/novel-promotion/select_location.zh.txt`

```text
你是"场景资产建立师"。请基于我提供的文本（可能是小说、剧本、或混合格式），筛选【需要制作画面的场景】，生成用于出图与后续生产的资产 JSON。

【筛选规则 - 精准提取模式】

✅【必须提取的场景】：
  - 剧本场景头部中出现的地点（如"内景 客厅 白天"）
  - 角色实际身处、产生互动的具体场所
  - 剧情主线发生的核心地点
  - 多次出现或戏份较重的场景
  - 有明确空间描写、需要制作背景画面的地点

❌【不提取的场景】（严格执行！）：
  - 一次性路过、仅提及但无剧情发生的地点
  - 意境类、比喻类、修辞类描述（如"从天堂打到地狱"、"从天上打到地下"、"心灵深处"、"记忆长河"等）
  - 抽象空间或无法具象化的概念（如"命运交汇点"、"时空裂缝"）
  - 仅作为对话背景提及、没有实际画面需求的地点
  - 纯过渡性场景（如"穿过走廊"、"路过门口"等一笔带过的移动描述）
  - 回忆/幻想中一闪而过、没有具体剧情的场景
  - 战斗过程中一笔带过的地点（如"打遍三界"、"从山上打到山下"、"从天宫打到凡间"等表示战斗范围的修辞）

📋【判断标准】：
  问自己：这个场景是否需要单独制作一张背景图？角色是否在此场景有实际戏份？
  如果只是一句话带过的地点，则不提取。
  如果是表示"打斗范围"的修辞（如从天堂到地狱），则不提取。

🔄【去重规则】：
  - 若场景在库中已存在则跳过，场景库如下：{locations_lib_name}
  - 同一场景不同称呼合并为一个（如"书房"和"张先生的书房"视为同一场景）
  - 返回的场景名必须与资产库中已有名称完全一致

【场景生成要求 - A: 全景空间版】
侧重点：宽广完整的空间全貌、整体布局、画面层次

⚠️ 【核心要求】必须生成【宽广的空间全景】，展示场景的完整面貌，而非局部特写！
- 镜头应该是【广角/远景】视角，能看到整个空间的全貌
- 展示空间的完整边界（墙壁、地面、天花板/天空）
- 让观众能够清晰理解这是一个什么样的完整空间
- 严格按照原文的场景描述来描写，原文描述的场景是最优先级，其他才可以自由发挥

1. **开头必须明确写明场景名称**：
   - 每条描述开头必须以「场景名」的形式标注空间属性
   - 示例：「皇宫」殿内铺设着... / 「客厅」窗外阳光透过... / 「卧室」床边放着...
   - 这样AI在生成图片时能明确理解这是什么类型的空间

2. 每个场景生成 3 条中文环境描述（用于AI图片生成），供用户选择

3. 3条描述要求：
   - 全部符合原文描述的场景特征
   - 可以自由发挥细节，但整体风格保持一致，不要有过大差异
   - 全部使用广角/远景视角，展示完整空间全貌
   - 每条描述开头都必须以「场景名」标注

4. 每条描述都必须包含：

   **宽广空间感**（最重要）：
   - 必须是【广角镜头】或【远景视角】，能看到空间的大部分区域
   - 室内场景：能看到2-3面墙壁、地板、部分天花板
   - 室外场景：能看到开阔的视野、远处的地平线或建筑群
   - 强调空间的【开阔感】和【完整性】

   **空间定位与规模**：
   - 场景类型（室内/室外/幻想空间）
   - 空间大小感：描述实际的空间尺度（如"约30平米的客厅"/"一眼望不到边的草原"）
   - 层高/纵深感：能看到的最远距离

   **空间层次**（创造画面深度）：
   - 前景：靠近镜头的元素（桌角/门框边缘/植物叶片/栏杆等，部分可见）
   - 中景：主要场景区域（核心物体的完整呈现）
   - 背景：远处可见的元素（窗外景色/远处墙面/天际线/门廊深处）

   **物体布局**：
   - 使用明确的位置词：左侧/右侧/中央/角落/靠窗/远处
   - 描述物体之间的空间关系和前后层次
   - 5-8件物体，每件都有位置说明
   - 至少 2-3 个后续可作为人物落位锚点的关键物体或区域必须被明确写出，如桌边、门内侧、窗下墙边、讲台前、龙椅前台阶

   **光线方向**：光从哪个方向照入，照亮哪些区域

   **可落位空间**（必须体现）：
   - 必须说明哪些区域留有可供人物站立或出现的空白空间
   - 这些空白区域必须与关键锚点相邻，便于后续固定人物位置
   - 禁止把所有锚点都塞满家具或遮挡物，导致后续无法落人

5. 描述规范：
   - 强调位置关系词：前方、远处、左侧、角落、靠近、深处
   - 长度 100-150 字
   
   ⚠️【场景图不能出现任何角色 - 核心规则】：
   
   场景图的用途：场景图是纯粹的"背景板"，主角和重要角色会在后期通过 AI 合成到背景上。
   因此，场景描述中**绝对不能出现任何有名有姓的角色**。
   
   ❌ 错误示例（包含了角色）：
      - "两只猴王持棒对峙" → 错！猴王是角色，不能出现
      - "张三站在门口迎接" → 错！张三是角色，不能出现
      - "孙悟空和六耳猕猴在街上打斗" → 错！主角不能出现
      
   ✅ 正确示例（纯背景）：
      - "「古道」广角镜头展现蜿蜒在险峻石林间的黄土古道，前景几株枯松，中景道路宽阔平坦，尘土飞扬，背景是连绵群山。"
      - "「宴会厅」大厅远处三两宾客交谈" → 可以！这是无名背景群众
      - "「集市」街道上行人往来" → 可以！这是模糊的路人群众
   
   📋 什么情况可以写人群？
      - 只有无名的、模糊的背景群众可以出现（如"宾客"、"路人"、"行人"、"围观群众"）
      - 这些群众不能有具体描述，只能用模糊词汇
      - 如果场景是私密空间或无人场景，保持空镜即可
   
   - 不包含艺术风格描述，风格由系统自动添加

6. 场景命名规则：中文 "地点_时间/状态"
   - 示例："客厅_白天"/"空间站_夜间"/"仙宫_黄昏"/"森林_迷雾中"

7. 剧情中出现的关键元素必须在场景中体现（如椅子、桌子等）

8.如无特殊要求，使用用户输入的语言来进行场景生成，例如输入英文输出偏西方场景，中文则输出偏中国场景，但是原则要按照文字剧本里实际发生的地点为准，

9. 如果原文或用户输入过于泛化（如「学校教室」「办公室」「客厅」），你必须主动将其具体化为可控画面的完整空间：
   - 明确主视角下能看到的关键结构
   - 明确前景/中景/背景
   - 明确至少 3 个稳定锚点及其周边空位
   - 禁止只输出泛泛的场景名词堆砌

【输出规范（只允许以下 JSON 结构；字段名中文；不得输出任何多余文字）】
{
  "locations": [
    {
      "name": "场景_时间",
      "summary": "场景简要说明（用途/人物关联，如：张三居住的主卧室、公司高层会议室等）",
      "has_crowd": true/false,
      "crowd_description": "人群类型描述（仅当has_crowd为true时填写，如：宴会宾客、集市人群、学生们等）",
      "available_slots": [
        "皇宫正中龙椅前方台阶下的位置",
        "左侧立柱与长案之间的空位",
        "右后方殿门内侧靠墙的位置"
      ],
      "descriptions": [
        "「场景名」场景环境描述1（如has_crowd为true则包含人群元素）",
        "「场景名」场景环境描述2",
        "「场景名」场景环境描述3"
      ]
    }
  ]
}

【严格性】
- 若无符合条件的场景，locations数组返回 []。
- 每个场景必须生成 2-6 个 available_slots，且每个站位都必须具体、可复用、与场景内明确锚物相关。
- 每个 available_slots 元素必须是一条完整的位置描述短语，不是短词，不是结构化对象。
- 站位描述必须像「皇宫正中龙椅前方台阶下的位置」「教室后排靠窗那组课桌外侧的位置」这样，直接说明锚物、方位和具体区域。
- 禁止抽象站位，如「左边」「中间」「角落」；禁止写人物姿态、动作、情绪；只描述位置本身。
- available_slots 中提到的所有关键锚点，必须在 descriptions 中清楚出现，否则该站位无效，不能输出。
- 只返回上述 JSON；不得输出markdown代码块标记、如```json注释或解释；不得添加未定义字段。
- 每条描述必须遵守长度限制（100-150字）；发现超长请自行截断。
- 禁止在 JSON 字符串值中出现英文双引号 "。原文中的所有引号（""''等）必须统一替换为「」。如字符串内确实需要英文双引号，必须转义为 \"

【原文内容如下】
{input}
```

### R2.26 — `_refs/waoowaoo/lib/prompts/novel-promotion/select_prop.zh.txt`

```text
你是"关键剧情道具资产分析师"。

任务：从输入文本中只识别【关键道具】，用于建立需要长期保持外观一致的资产库。宁缺毋滥。只返回 JSON，不得包含任何额外解释或 markdown。

道具的核心定义：
道具是可以脱离特定场景独立存在的、跨场景/跨时间线出现的实体物件。一个物件必须能被角色「带走」或「转移到另一个场景」，并且在文本中有明确证据表明它会被持续持有、反复使用、反复提及，才有资格成为道具资产。大部分故事中道具数量非常少，甚至为零。

输出格式：
{
  "props": [
    {
      "name": "道具名称",
      "summary": "给人阅读的简短道具说明",
      "description": "用于生成图片的纯视觉描述"
    }
  ]
}

关键道具判定标准：
1. 必须是剧情中真实出现的实体物件。
2. 必须是可移动的——能够被角色携带、转移、带离当前场景。
3. 必须有明确文本证据表明它跨场景或跨时间线重复出现，且需要保持外观一致；禁止凭常识猜测它以后还会出现。
4. 必须至少满足以下一种情况：
   - 被角色持有、使用、争夺、交付、隐藏、丢失、寻找
   - 是推进情节的关键工具、武器、法器、证物、信物、钥匙、线索载体
   - 是角色长期携带或反复回收使用的专属物件、独特装备、特殊交通工具
5. 必须同时满足以下至少一条“唯一性/持续性”条件，否则不输出：
   - 物件具有不可替代的独特身份，例如祖传、特制、唯一、带特殊能力、带特殊机关、带独特编号/纹样/损伤
   - 文本明确表明同一件物品在多个场景/多个时间点反复出现
   - 文本明确表明角色长期随身携带、持续依赖或反复寻找同一件物品

严格不提取：
1. 普通背景陈设、家具、餐具、食物、饮料、日用品、装饰物。
2. 仅被顺带提及、没有剧情功能的物件。
3. 场景自带的环境元素，除非它被明确当作关键道具使用。
4. 普通服装、妆容、饰品，除非它本身就是关键线索或关键信物。
5. 抽象概念、情绪、能力、身份、地点、生物、身体部位。
6. 场景固有设施——物件是某个场景的组成部分或内置设备，即便它参与了剧情互动（如被黑客入侵的电脑、被砸碎的窗户、着火的壁炉），只要它在物理上依附于场景、无法被角色带走，就不是道具。这类属于"场景状态"，由场景描述承载。
7. 场景常规配置——如果一个物件是该类场景的标配（电脑房的电脑、厨房的灶台、图书馆的书架、实验室的仪器、监控室的屏幕），直接不提取。
8. 普通可替换物件——即使它被角色短暂使用，只要换成同类另一件物品剧情仍成立，就不是道具。例如餐厅里的叉子、桌上的杯子、办公桌上的笔、本子、普通手机、普通雨伞、普通行李箱、普通书籍。
9. 一次性动作依赖物件——如果它只在单个场景里承担一次动作功能，没有明确后续复现证据，不输出。

判断倾向：
1. 仅因外观具体、名词明确，不足以成为关键道具；必须有明确剧情作用。
2. 如果一个物件既可能是背景物，也可能是道具，默认按背景物处理，不输出。
3. 如果只是"出现过"，但没有"被使用/被强调/影响剧情"，不输出。
4. 如果不确定它是否值得进入资产库，直接不输出。
5. 优先少报，禁止为了凑数量而输出。
6. 可移动性测试：问自己"角色能把它装进口袋/背包/车里带到另一个场景吗？"如果不能，不输出。
7. 可替换性测试：问自己"把它替换成同类另一件普通物品，剧情是否仍然成立？"如果答案是“成立”，不输出。
8. 贯穿性测试：如果文本没有明确证据证明它会在后续再次出现或被长期持有，默认不输出。
9. 对“餐厅里的叉子、桌上的酒杯、房间里的台灯、办公室里的电脑”这类典型场景内物件，一律默认不输出。

示例判断（帮助校准标准）：
✅ 应提取：角色随身携带的左轮手枪（跨场景出现、可移动）
✅ 应提取：关键证物信封（被发现、传递、多场景出现）
✅ 应提取：主角可操控时间的手表（核心道具，贯穿全剧）
✅ 应提取：主角驾驶的黑色越野车（跨场景移动工具）
✅ 应提取：祖传青铜短剑（独特身份，反复出现，无法被普通物件替代）
❌ 不提取：电脑房里的电脑（场景固有设施）
❌ 不提取：被黑客入侵、显示关键线索的电脑（场景设施的状态变化，不可移动）
❌ 不提取：监控室的监控屏幕（场景固有设施）
❌ 不提取：厨房的冰箱（场景常规配置）
❌ 不提取：图书馆的某本古籍（除非角色将它取走带到其他场景使用）
❌ 不提取：餐厅里的叉子（普通可替换餐具，即使角色拿它吃饭或短暂拿在手里）
❌ 不提取：桌上的红酒杯（单场景普通物件，不具备贯穿性）
❌ 不提取：办公室里的普通笔记本电脑（普通设备，场景配置）

输出要求：
1. 只输出三个字段：name、summary、description。
2. name、summary、description 都不能为空。
3. 如果道具库里已经有完全同名道具，不要重复输出。
4. 名称尽量简洁稳定，例如"青铜匕首""录音笔""红绳手链"。
5. summary 只给人阅读，简短说明这是一个什么道具；禁止写剧情作用、使用过程、出现频次、角色互动、镜头描述。
6. description 只写图片生成所需的静态视觉信息；只允许写材质、颜色、形状、结构、数量关系、装饰细节；禁止写用途、剧情、动作、人物、手部、桌面、环境、背景。
7. 如果 summary 或 description 中出现"多次出现""被角色使用""推进剧情""在画面中"这类语义，视为错误，禁止输出。
8. 通常不超过 3 个；只有确实都是关键道具时才可更多。
9. 如果没有合适道具，返回 {"props": []}。绝大多数情况下返回空数组是正确的。
10. JSON 字符串值中的引号统一替换为「」。
11. 宁可漏掉边缘候选，也不要把场景里的普通物件误报为道具。

输入文本：
{input}

已有道具库：
{props_lib_name}
```

### R2.27 — `_refs/waoowaoo/lib/prompts/character-reference/character_image_to_description.zh.txt`

```text
# 图片反推角色描述提示词

请分析这张角色图片，生成一段详细的角色外貌描述（用于 AI 图片生成）。

## 输出要求

生成一段完整的角色视觉描述，包含以下要素：

1. 性别和年龄段（如：约二十五岁的男性）
2. 发型发色（如：黑色短发、微卷的棕色长发）
3. 脸型五官特征（如：剑眉星目、高鼻梁、薄唇）
4. 体态身材（如：身形修长、体格健壮）
5. 服装风格（如：深蓝色西装、白色衬衫、皮质腰带）
6. 配饰特征（如：左手戴银色手表、胸前别金色胸针）
7. 整体气质关键词（如：精英气质、禁欲系、高冷、温柔暖男）

## 缺失内容补齐规则

如果参考图只展示了部分身体（如上半身、头像），请根据已有信息合理推断并补全：
- **缺少下半身**：根据上衣风格推断裤装/裙装类型（如西装上衣配深蓝色西裤、休闲上衣配牛仔裤）
- **缺少鞋子**：根据整体穿搭风格推断鞋款（如正装配皮鞋、休闲装配运动鞋或帆布鞋）
- **缺少配饰细节**：根据角色气质合理添加配饰（如商务风配手表、休闲风配手环）

## 禁止描写

- 皮肤颜色
- 眼睛颜色
- 表情
- 动作
- 背景
- 姿势

## 输出格式

一段连贯的描述文字，约200-300字，直接可用于图片生成提示词。
只返回描述文字，不要有任何标题、序号或其他格式。
```

### R2.28 — `_refs/waoowaoo/lib/prompts/novel-promotion/image_prompt_modify.zh.txt`

```text
请按照以下提示词规则执行用户的ai生图以及视频运动提示词场景需求
1. 详细描述镜头角度和地点、动作、人物、环境，也就是谁、和谁、在哪里、干了什么，如果是空镜标题等，那么也要描述出原文想要表达的东西，例如作者名字，或者和原文有关的内容，提示词务必详细完整

2. **场景描述使用规则（重要）：**
   - locations字段：只写场景名字（如"病房_白天"）
   - image_prompt字段：直接使用场景名字（如"病房_白天"），可以结合具体位置描述（如"病房_白天的窗边"）
   - **禁止添加光线、色调、天气描述**：场景资产已包含完整的光线和色调信息，提示词中不要添加"阳光"、"光线"、"明亮"、"昏暗"、"温暖色调"、"冷色调"、"天气"等描述
   - **人物所在的位置和互动的地方要和场景提示词中已有的物品有关系，不要出现人物和场景没有的关系进行互动**

3. **人物描述使用规则：**
   - characters字段：只写人物名字（如"Victor"）
   - image_prompt字段：直接使用人物名字（如"Victor"），可以结合动作和情绪描述（如"Victor站在门口，表情严肃"）
   - 写图片生成提示词的时候务必要写明地点+人物名字+情绪+动作
   - 我们这个是有声书第一视角，第一视角默认就是主角的视角，也就是在pov中的人物决策，如无其他意外那么这个就是主角，按照这个名字来进行主视角生成

4. 我们的场景限制只对有效目前人物处在实际发生地点的有效！例如有回忆、旁白等情况，我们不应该完全限制在固定场景之内，而是可以插入多样性的画面

5. 使用中文输出提示词，提示词编写规范按照用简洁连贯的自然语言写明：主体 + 行为 + 环境 + 空间关系
   例如：Dr.Smith站在病床边，看着躺在床上的Mary，病房_白天

6.涉及到文字内容的全部使用原文srt的语言作为输出，如原文srt是英文，就代表着我们这个面向英文观众，那么如果会画面内容里面出现文字的话（例如出现了医院名字的特写）就要输出英文的具体文字提示词（注意，主要提示词还是中文），如：医院的镜头特写，上面写着hospital

7.使用主体+行为+环境的提示词，确保不要错过主体，除非无主体的空镜，否则一定要交代主体是谁

按照用户的修改指令把提示词修改为用户需要的样子，用户可能会发送一些额外内容让你修改，例如让你把人物修改为另外一个人物，这个时候你会看到人物或场景的具体描述词
例如用户输入：把张三(黑色长发,穿着西装...)修改为小明(蓝色头发，红色眼睛...)然后就可以利用这些具体描述词来按照以上的生成提示词规则修改。

当前的图片提示词：{prompt_input}

当前的视频提示词：{video_prompt_input}

用户的修改指令：{user_input}

结果发送json格式给我，只返回以下json格式，禁止返回一切除json以外的多余内容，注释，文字等等，只返回无任何markdown标识符的纯净json格式。⚠️ 所有引号（""''等）在 JSON 字符串值中必须统一替换为「」，严禁出现未转义的英文双引号 "。json格式如下
{
  "image_prompt": "修改后的图片提示词（静态画面描述）",
  "video_prompt": ""
}
```

### R2.29 — `_refs/waoowaoo/src/lib/constants.ts` — CHARACTER_PROMPT_SUFFIX

```text
角色设定图，画面分为左右两个区域：【左侧区域】占约1/3宽度，是角色的正面特写（如果是人类则展示完整正脸，如果是动物/生物则展示最具辨识度的正面形态）；【右侧区域】占约2/3宽度，是角色三视图横向排列（从左到右依次为：正面全身、侧面全身、背面全身），三视图高度一致。纯白色背景，无其他元素。
```

### R2.30 — `_refs/waoowaoo/src/lib/constants.ts` — PROP_PROMPT_SUFFIX

```text
道具设定图，画面分为左右两个区域：【左侧区域】占约1/3宽度，是道具主体的主视图特写；【右侧区域】占约2/3宽度，是同一道具的三视图横向排列（从左到右依次为：正面、侧面、背面），三视图高度一致。纯白色背景，主体居中完整展示，无人物、无手部、无桌面陈设、无环境背景、无其他元素。
```

### R2.31 — `_refs/waoowaoo/src/lib/constants.ts` — LOCATION_PROMPT_SUFFIX

```text

```

**ROUND 2 file count (prompt .txt + 3 constant strings):** 31

