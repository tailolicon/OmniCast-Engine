# REFS_SB_01 — ArcReel 深度研究

> **Repo:** `_refs/ArcReel`  
> **Định vị:** Open-source AI Video Generation Workspace — Novel → Short Video  
> **License:** **AGPL-3.0** (`LICENSE`) — **chỉ học concept / kiến trúc / prompt pattern; CẤM chép code**  
> **Ngày nghiên cứu:** 2026-08-02  
> **Phương pháp:** đọc code thật (lib/, server/, agent_runtime_profile/), không suy từ README

---

## 0. Tóm tắt điều hành (cho OmniCast)

| Trục | ArcReel | OmniCast hiện tại | Hành động gợi ý |
|------|---------|-------------------|-----------------|
| Workspace | Project-first + shot-list (không NLE timeline) | Pipeline YouTube + storyboard module riêng | Học project/episode asset layout |
| Consistency | Character/scene/prop **sheet** + previous frame + (ref-video) `@name→[图N]` | Cast registry + `[IMAGE n]` + `RefRole` fail-closed | ArcReel sheet layout tốt; OmniCast binding **sâu hơn** (role ignore) |
| Prompt | YAML structured image/video + negative tail text; two-step content/visual | Refsheet prompt + binding token | Học YAML + writing guides + two-step |
| Provider | Protocol Image/Video/Text/Audio + custom endpoint + per-provider slots | Nhiều provider rời, Veo/Flow chưa nối storyboard | Học queue + capacity + resume |
| License | AGPL-3.0 | (project riêng) | **Không port code**; re-implement |

**ArcReel làm TỐT hơn OmniCast (hiện tại):** multi-provider abstraction hoàn chỉnh, generation queue (cancel/resume/orphan), two-step script (content≠visual), product fidelity, grid first-last chain, CapCut export, cost tracking, agent orchestration production-grade.  
**ArcReel kém hơn / OmniCast đã vượt:** `RefRole` + “controls X only; ignore Y”, cast-per-video fail-closed continuity gate, entity kind đầy đủ (costume), operator image win policy rõ ràng hơn.

---

## 1. Tổng quan kiến trúc

### 1.1 Module map

```
ArcReel/
├── lib/                          # Domain core (không phụ thuộc HTTP)
│   ├── script_models.py          # Pydantic schema toàn bộ script modes
│   ├── script_skeleton.py        # 4 skeleton kinds (segments/scenes/shots/video_units)
│   ├── prompt_builders*.py       # Prompt SSOT (image/video/script/ad/reference)
│   ├── prompt_utils.py           # image/video YAML render + drama Voice_Profiles
│   ├── media_generator.py        # Image/Video/Audio + version + ledger + ref compress
│   ├── generation_queue.py       # Task queue API
│   ├── generation_worker.py      # In-process asyncio worker, Capacity/Slot table
│   ├── project_manager.py        # projects/{name}/ FS + project.json
│   ├── image_backends/|video_|audio_|text_backends/
│   ├── reference_video/          # @mention → [图N], ad unit grouping
│   ├── grid/                     # Grid image-to-video
│   └── config/                   # PROVIDER_REGISTRY, resolver
├── server/
│   ├── app.py                    # FastAPI + worker boot
│   ├── routers/                  # REST
│   ├── services/generation_tasks.py  # Storyboard/video/TTS execute
│   ├── services/reference_video_tasks.py
│   ├── services/resume_executor.py
│   └── agent_runtime/            # Claude Agent SDK + MCP tools
├── frontend/                     # React 19 workspace (SSE tasks, assets, assistant)
└── agent_runtime_profile/        # CLAUDE.{narration,drama,ad}.md + skills/subagents
```

### 1.2 Luồng dữ liệu end-to-end

```
Upload novel/screenplay
  → Global character/scene/prop extraction (agent + project.json buckets)
  → Episode planning (ledger: hook, teaser, story_beats)
  → Script two-step:
       step1 content (novel_text / utterances / scene_description)  [không đụng visual]
       step2 visual  (image_prompt / video_prompt)                  [merge by id]
  → Design sheets: characters/scenes/props/products (i2i refs)
  → Storyboard images OR grid OR skip (reference-to-video)
  → Video clips (i2v / grid-cells / r2v)
  → TTS narration (optional, per segment)
  → FFmpeg compose + CapCut draft export
```

Nguồn workflow README: `README.en.md:77-90`. Domain language: `CONTEXT.md` (provider vs backend, task SM, reference compression).

### 1.3 Workspace model (câu hỏi riêng)

**Project-first + shot-list, KHÔNG timeline-first NLE.**

| Khái niệm | Tổ chức |
|-----------|---------|
| **Project** | Thư mục `projects/{slug}/` + `project.json` (style, overview, characters/scenes/props/products, episodes, content_mode, generation_mode) |
| **Episode** | `scripts/episode_N.json` + `drafts/episode_N/` (step1 intermediate) |
| **Shot list** | Theo skeleton: `segments` (narration) / `scenes` (drama) / `shots` (ad) / `video_units` (reference video) |
| **Assets** | FS: `characters/`, `scenes/`, `props/`, `products/`, `storyboards/`, `videos/`, `grids/`, `thumbnails/`, `output/` (`project_manager.py:168-180`) |
| **Global library** | SQLite `assets` table — character/scene/prop cross-project (`lib/db/models/asset.py`) |
| **Timeline** | Không có track/keyframe editor; “timeline” = ordered shot list + `transition_to_next` + compose |

**Storyboard có.** Mỗi segment/scene/shot mang `image_prompt` + `video_prompt` + `generated_assets` (`pending | storyboard_ready | completed`).  
**Reference-video mode** không storyboard image — unit → video thẳng (`storyboard_sequence.py:35-37`).

Hai trục trực giao (`script_skeleton.py:102-120`):

- `content_mode`: `narration` | `drama` | `ad`
- `generation_mode`: storyboard path (i2v) | `reference_video` | (grid path riêng)

---

## 2. Data model storyboard

### 2.1 Enum máy ảnh (verbatim schema)

`lib/script_models.py:29-66`:

```python
ShotType = Literal[
    "Extreme Close-up", "Close-up", "Medium Close-up", "Medium Shot",
    "Medium Long Shot", "Long Shot", "Extreme Long Shot",
    "Over-the-shoulder", "Point-of-view",
]
CameraMotion = Literal[
    "Static", "Pan Left", "Pan Right", "Tilt Up", "Tilt Down",
    "Zoom In", "Zoom Out", "Push In", "Pull Out",
    "Truck Left", "Truck Right", "Pedestal Up", "Pedestal Down",
    "Orbit", "Tracking Shot", "Shake",
]
TransitionType = Literal["cut", "fade", "dissolve"]
```

Enum drift: normalize case/separators; OOV → `Medium Shot` / `Static` (không fail cả episode) — `script_models.py:76-107`.

### 2.2 Image / Video prompt structs

```python
# script_models.py:123-169
class Composition(BaseModel):
    shot_type: ShotType
    lighting: str
    ambiance: str

class ImagePrompt(BaseModel):
    scene: str          # static frame only; motion → video_prompt.action
    composition: Composition

class VideoPrompt(_VideoPromptCore):  # narration/ad
    action: str
    camera_motion: CameraMotion
    ambiance_audio: str
    dialogue: list[Dialogue]  # optional

class DramaVideoPrompt(_VideoPromptCore):  # no dialogue — utterances at scene level
    ...
```

### 2.3 Narration segment (shot unit)

`NarrationSegment` (`script_models.py:211-257`):

| Field | Vai trò |
|-------|---------|
| `segment_id` | `E{ep}S{nn}` |
| `duration_seconds` | 1–60, constrained by model |
| `segment_break` | Scene cut → break previous-frame chain |
| `novel_text` | **Verbatim** source for TTS |
| `characters_in_segment` / `scenes` / `props` | Asset name refs (must match project.json) |
| `image_prompt` / `video_prompt` | Visual layer |
| `generated_assets` | Paths + status |
| `end_frame_image` | Optional last-frame override path |

**State machine per item** (`GeneratedAssets.status`):  
`pending → storyboard_ready → completed` (`script_models.py:189`).

### 2.4 Drama scene + utterances

`DramaScene` + `Utterance{kind: dialogue|voiceover, speaker, text}` — ADR 0040: dialogue → video lip-sync YAML; voiceover → subtitle/TTS only (`script_models.py:371-504`).

**Two-step merge:** step1 `DramaSceneContent` + step2 `DramaSceneVisual` → `merge_drama_visual_into_scenes` fail-loud on missing/orphan/duplicate `scene_id` (`script_models.py:609-662`).

### 2.5 Ad shot + product

`AdShot`: `section` (hook…cta), `voiceover_text`, `products_in_shot[]`, image/video prompts (`script_models.py:668-698`).

### 2.6 Reference video unit

```python
# script_models.py:830-870
class Shot:
    duration: int  # 1-15
    text: str      # may contain @[Name]

class ReferenceVideoUnit:
    unit_id: str   # E{ep}U{nn}
    shots: list[Shot]  # 1-4
    references: list[ReferenceResource]  # order = [图N] index
    duration_seconds: int
```

### 2.7 Asset types

`lib/asset_types.py:52-105`:

| type | sheet field | subdir | notes |
|------|-------------|--------|-------|
| character | `character_sheet` | characters | + voice_style, reference_image, reference_audio |
| scene | `scene_sheet` | scenes | |
| prop | `prop_sheet` | props | |
| product | `product_sheet` | products | multi `reference_images`; not in global library |

---

## 3. Cơ chế consistency nhân vật / bối cảnh / props

### 3.1 Pipeline consistency (3 tầng)

1. **Design sheet trước** — 4-view character (16:9), scene main+detail, prop 3-view, product multi-angle (`prompt_builders.py:24-53`).  
2. **Storyboard i2i** inject sheets của shot + **previous storyboard** (composition continuity) + product refs first.  
3. **Video**:
   - **i2v:** start_image = storyboard (optional end_frame)
   - **Grid:** cell chain first/last frames
   - **R2V:** `@[Name]` → ordered refs → `[图N]` tokens

### 3.2 Storyboard reference collection (code)

`server/services/generation_tasks.py:200-294`:

```
For target shot:
  for each name in characters_in_* / scenes / props:
    if project[bucket][name].*_sheet exists on disk:
      refs.append({image: path, label: name})  # label = exact asset name
  + extra_reference_images from payload
  + previous storyboard (unless index==0 or segment_break)
  Product refs (if products_in_shot) prepended + fidelity tail
```

Previous-frame policy (`storyboard_sequence.py:26-29`):

```text
label: 上一分镜图（镜头衔接参考）
description: 仅用于延续前一镜头的构图、色调和场景连续性，
  不是新增角色、服装或道具设定；请以当前 prompt 为准生成当前镜头。
```

→ **Soft role hint** (text description), **không** hard RefRole enum như OmniCast.

### 3.3 Character sheet layout (identity)

`prompt_builders.py:24-36` — 4 panels 16:9: left bust close-up (~40%), right three A-Pose full (front / 3/4 / back); guard: face/hair/clothes consistent, 5 fingers, proportions.

Character can also have user `reference_image` + TTS `reference_audio` + `voice_style` for video native audio (`asset_types.py:53-68`).

### 3.4 Reference-video binding `@ → [图N]`

`lib/reference_video/shot_parser.py:160-175`:

```python
def render_prompt_for_backend(text, references):
    # @Name / @[Name] → [图{1-based index in references}]
    # unregistered mention kept as-is
```

Order of `references[]` **is** attachment order — same load-bearing principle as OmniCast `Frame.reference_paths` / `[IMAGE n]`.

**So sánh trực tiếp với OmniCast cast-registry:**

| Khía cạnh | ArcReel | OmniCast |
|-----------|---------|----------|
| Registry scope | **Project-level** buckets (+ global SQLite library) | **Per-video** cast board (`Entity` list) |
| Entity kinds | character / scene / prop / product | character / location / prop / **costume** |
| Sheet | One multi-panel sheet path per asset | Multi-view sheets, view1 anchors view2..N (`refsheet.py`) |
| Token binding | `[图N]` (CN) in r2v; storyboard uses **label** on ref + free text names in YAML | `[IMAGE n]` + deterministic name→token replace |
| Role / ignore | Previous-frame **description string**; product fidelity tail | `RefRole` + ROLE_IGNORES (“controls X only; ignore Y”) |
| Fail-closed continuity | Soft (missing sheet → skip ref) | `continuity.py` fail-closed gates |
| Operator override | Upload ref image/audio dedicated API | `ImageSource.OPERATOR` wins |

**Kết luận:** ArcReel **production-complete** asset library + multi-mode generation; OmniCast **semantic binding** (role isolation) sâu hơn — đúng gap “mặt đổi theo frame”.

### 3.5 Reference compression / seed

- Chỉ nén **upload copy** gửi provider, không nén source/output (`CONTEXT.md:151-163`, `media_generator.py:192-236`).  
- 413 → ladder step down → floor error.  
- `seed` optional trên `ImageGenerationRequest` / `VideoGenerationRequest` — không auto re-seed consistency loop.

### 3.6 Không có

- IP-Adapter / LoRA training  
- Pixel-level face similarity verify  
- Automatic re-roll until consistency score  

---

## 4. PROMPT ENGINEERING — VERBATIM

> Tất cả dưới đây chép từ code; **AGPL — không paste vào production OmniCast**, học pattern rồi viết lại.

### 4.1 Asset design prompts (`lib/prompt_builders.py`)

#### Layout / guards / negatives (constants)

```
_CHARACTER_LAYOUT = (
    "横版 16:9 四格布局，纯白 (#FFFFFF) 背景：左侧约 40% 宽为胸像特写（清晰展示面部、发型、配饰、上装），"
    "右侧三个等宽面板分别为正面 / 四分之三侧面 / 背面的 A-Pose 全身视图。"
)
_SCENE_LAYOUT = "主画面占四分之三区域展示环境整体外观与氛围，右下角嵌入关键细节小图。"
_PROP_LAYOUT = "三视图水平排列于纯净浅灰背景：左侧正面全视图、中间 45° 侧视图体现立体感、右侧关键细节特写。"
_PRODUCT_LAYOUT = (
    "标准多角度产品参考图，纯净浅灰背景、均匀棚拍布光：正面、45° 侧面、背面三视图水平排列，"
    "下方一排关键细节特写（logo、文字、材质、接缝）。"
)

_CHARACTER_GUARD = "四个面板中角色面部、发型、服装、配饰完全一致；五官对称、手指完整为五指、肢体比例协调。"
_SCENE_GUARD = "画面中没有人物出镜，空间透视正常，陈设固定，光影统一。"
_PROP_GUARD = "外观结构完整，焦点清晰。"
_PRODUCT_FIDELITY_CORE = "logo、文字、配色、材质、比例与结构不得改变或臆造"
_PRODUCT_GUARD = (
    f"产品外观必须忠实于参考图中的真实产品：{_PRODUCT_FIDELITY_CORE}；各视图为同一件产品。"
    "参考图中的手部、模特及其他出镜人物一律不保留，画面只呈现产品本体；"
    "包装上印刷的人像图案属于产品外观，须原样保留。"
)

_NEGATIVE_TAIL_CHARACTER = "画面避免：水印、多余文字、Logo。"
_NEGATIVE_TAIL_SCENE = "画面避免：出镜人物、水印、多余文字、Logo。"
_NEGATIVE_TAIL_PROP = "画面避免：出镜人物、水印、多余文字、Logo。"
_NEGATIVE_TAIL_PRODUCT = "画面避免：出镜人物、水印、多余文字、Logo。"
_NEGATIVE_TAIL_STORYBOARD = "画面避免：水印、多余文字、Logo。"
_NEGATIVE_TAIL_VIDEO = "禁止出现：BGM、文字字幕、水印。"
```

**Vì sao hiệu quả:** negatives chỉ entity-exclude (không “low quality” noise); character **không** exclude 人物; scene exclude **出镜人物** (cho phép portrait-as-prop); product strip model hands nhưng giữ printed faces.

#### Character / scene / prop / product builders

```
# build_character_prompt:
{style_block}
角色「{name}」的设计参考图。

{description}

{_CHARACTER_LAYOUT}

{_CHARACTER_GUARD}

{_NEGATIVE_TAIL_CHARACTER}

# build_scene_prompt: 标志性场景「{name}」的视觉参考。 + layout/guard/neg
# build_prop_prompt:  道具「{name}」的多视角展示。 + ...
# build_product_prompt: 产品「{name}」的标准参考图。 (NO style prefix — realism)
```

#### Product fidelity + negative appenders

```
# append_product_fidelity_tail:
产品高保真还原（最高优先级）：画面中的产品「A」「B」必须与产品参考图完全一致——
{_PRODUCT_FIDELITY_CORE}，不得重新设计或美化产品本身；
项目画风只作用于产品以外的画面元素。

# append_image_negative_tail → _NEGATIVE_TAIL_STORYBOARD
# append_video_negative_tail → _NEGATIVE_TAIL_VIDEO
```

**Design note (file header `prompt_builders.py:1-13`):** negative **nối vào prompt text**, không dùng API `negative_prompt` (nhiều backend silent drop).

---

### 4.2 YAML render cho image/video gen (`lib/prompt_utils.py:35-99`)

Image YAML keys (order fixed):

```yaml
Style: <normalized project style>
Scene: <image_prompt.scene>
Composition:
  shot_type: ...
  lighting: ...
  ambiance: ...
```

Video YAML:

```yaml
Voice_Profiles:           # optional, drama only when characters inject
  - Speaker: ...
    Voice_Style: ...
Action: ...
Camera_Motion: ...
Ambiance_Audio: ...
Dialogue:                 # optional
  - Speaker: ...
    Line: ...
```

Runtime: `_normalize_storyboard_prompt` / `_normalize_video_prompt` (`generation_tasks.py:82-155`) convert structured dict → YAML + negative tail.

---

### 4.3 Scene / action writing guides (shared narration+drama step2)

`prompt_builders_script.py:129-149` — **verbatim core**:

```
_SCENE_WRITING_GUIDE = """这段文字将直接生成一张静态图：只描述此刻单帧画面上可见的内容，按主体（姿态 / 表情 / 服装）、环境（陈设 / 物件）、光线、氛围（雾、雨等可见信号）分层给出具体细节，写成连贯的叙述句而非关键词堆叠。光线与氛围在叙述中一笔带过即可，细节分别由 composition.lighting / composition.ambiance 承载。原文若是回忆 / 闪回 / 心理活动，将其改编为此刻可见的载体——人物神态、手中物件、环境痕迹，画面里只保留一个时空。画面元素（材质、装束、道具质感、环境年代特征）须贴合上方 `<style>` 块定义的风格基调，避免与风格相冲的元素混入（例如赛博朋克风下不出现榻榻米，国风水墨下不出现霓虹屏）。
   正例：「林清坐在窗边木桌前，左手撑着下巴，目光落在桌上一封拆开的信纸上；桌面摊着信封与一只褪色的怀表。半边脸笼在右侧落地窗逆光的蓝灰色阴影里，雨丝拍在木格窗棂，玻璃凝着细小水珠。」——主体、环境、光线、氛围各有一笔，全程叙述句。
   正例（原文是回忆）：原文「她想起亡母临终的嘱托」→「沈茹跪坐在灵位前，指尖抵着一串磨得发亮的佛珠，眼睑低垂。案上白烛烧过半，烛泪层层堆叠，烛焰在她侧脸投下摇晃的暖橙光斑；一缕香灰无声落在青砖上。」——回忆的分量由此刻的神态与旧物承载，画面只有一个时空。
   反例（跑偏）：「林清陷入了多年前那个绝望的雨夜，画面基调：忧郁。光影设定：冷调。」——「多年前的雨夜」不在此刻画面上；「忧郁 / 冷调」是抽象标签，不是可见细节。
   反例（过短）：「林清坐在窗边发呆。」——缺少环境元素、光线方向、氛围细节，至少应覆盖主体 / 环境 / 光线 / 氛围中三层。"""

_ACTION_WRITING_GUIDE = """首帧画面已定格主体、场景与风格，这段文字驱动它动起来：只描述该时长内发生的运动与变化，不复述画面中的静态内容；镜头运动专由 camera_motion 字段承载，action 只写主体与环境的运动。按主体动作（肢体 / 手势 / 表情过渡）、物件互动（摩挲信纸、推门带起的气流等）、环境动态（衣摆、尘埃、雨势、光影移动）分层写成连贯叙述句；动词应描述物理可观察动作（伸手 / 转身 / 摩挲 / 投向 / 收紧），避免内心动词。优先低缓、连贯的细微动作，动作量与该镜头时长匹配：5 秒级镜头通常完成一个连贯动作 + 一个细节互动；8 秒级可承载一次动作过渡（如「抬头—对视—开口」）；更长的镜头保持单一低缓的动作主线，随时长递增动作段数（如「起身—走到窗前—驻足」），而非叠加多条并行动作。
   正例：「林清缓缓抬起头，眼角微微收紧，手指无意识地摩挲信纸边缘；窗外雨势渐大，桌面投下的雨痕影子在缓慢移动。」——主体动作、物件互动、环境动态各有一笔。
   反例：「林清像蝴蝶般飞舞，思绪在过去与现在之间快速切换。」——「思绪切换」不是可拍摄的运动；「像蝴蝶般」是修辞，不是动作描述。"""

_LIGHTING_WRITING_GUIDE = (
    "描述具体的光源、方向、色温（如「左侧窗户透入的暖黄色晨光（约 3500K）」「头顶单点冷白色的吊灯」）。"
    "可附加摄影质感术语（如「浅景深」「逆光剪影」「丁达尔光柱」「轮廓光勾边」「35mm 胶片颗粒感」），"
    "让画面具备可观察的镜头语言而非抽象修辞；避免「光影神秘」「氛围唯美」这类抽象词。"
)
_AMBIANCE_WRITING_GUIDE = "描述可观察的环境效果（如「薄雾弥漫」「尘埃在光柱里翻飞」），避免抽象情绪词。"
_AMBIANCE_AUDIO_WRITING_GUIDE = (
    "只描写画内音（diegetic sound）：环境声、脚步、物体声响。不要写 BGM、配乐、画外音、旁白。"
)
```

**Vì sao hiệu quả:** tách **static frame vs motion**; cấm abstract mood words; scale action density theo duration; flashback → visible present carrier.

---

### 4.4 Narration step2 visual — FULL `build_narration_prompt` (V3 vá)

Nguồn: `lib/prompt_builders_script.py:256-347`. Đây là **toàn bộ** f-string return của hàm (không skeleton). Placeholders `{...}` giữ đúng như source; khi chạy, `{pacing_block}` = `NARRATION_PACING_RULES` + blank lines; `{_SCENE_WRITING_GUIDE}` / `{_ACTION_WRITING_GUIDE}` / lighting/ambiance guides = hằng §4.3; `{_ASSET_APPEARANCE_NOTE}` = `资产外观以上述描述为准：视觉字段写到出场资产的服装 / 材质 / 陈设细节时从中取材，不自行发明。`; `{segments_block}` = output của `_format_narration_step1_segments`.

```python
def build_narration_prompt(
    project_overview: dict,
    style: str,
    style_description: str,
    characters: dict,
    scenes: dict,
    props: dict,
    step1_segments: list[dict],
    episode: int,
    aspect_ratio: str = "9:16",
    target_language: str = "中文",
) -> str:
    pacing_block = render_pacing_section("narration") + "\n\n"
    segments_block = _format_narration_step1_segments(step1_segments)

    return f"""# 角色与任务

你是一位资深的短视频分镜编剧，擅长把已定稿的小说片段转化为可直接驱动 AI 图像 / 视频生成的视觉分镜。
你的任务：基于下方已定稿的「片段表」，为**每个片段**产出视觉层（image_prompt 与 video_prompt），按 segment_id 一一对齐。

**只产视觉层**：novel_text、时长、segment_break、出场角色 / 场景 / 道具均已在 step1 定稿、按 segment_id 透传，**不要重复输出、不要改写**；你只产出 image_prompt 与 video_prompt。
**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

{pacing_block}# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}（{_format_aspect_ratio_desc(aspect_ratio)}）
</style>

<characters>
{_format_assets_with_desc(characters)}
</characters>

<scenes>
{_format_assets_with_desc(scenes)}
</scenes>

<props>
{_format_assets_with_desc(props)}
</props>

{_ASSET_APPEARANCE_NOTE}

<segments>
{segments_block}
</segments>

segments 表每个片段已定稿（segment_id、逐字原文、时长、出场角色 / 场景 / 道具、是否场景切换），为只读上下文。

<episode_constraints>
当前正在生成第 {episode} 集。为每个片段输出一条视觉层，其 segment_id 必须与 segments 表逐字一致——逐一对应，不增、不减、不改写。
</episode_constraints>

# 字段写作指引

为每个片段产出下列视觉字段。

## 图片提示词（image_prompt）——切换到「摄影师」视角

- **image_prompt.scene**：{_SCENE_WRITING_GUIDE}
- **image_prompt.composition.shot_type**：从枚举中按画面内容选择，不强加倾向。
- **image_prompt.composition.lighting**：{_LIGHTING_WRITING_GUIDE}
- **image_prompt.composition.ambiance**：{_AMBIANCE_WRITING_GUIDE}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{_ACTION_WRITING_GUIDE}
- **video_prompt.camera_motion**：按画面内容自行选择。
- **video_prompt.ambiance_audio**：{_AMBIANCE_AUDIO_WRITING_GUIDE}
- **video_prompt.dialogue**：speaker 必须出现在该片段的出场角色中。

# 创作目标

输出可直接驱动 AI 生成的、视觉一致、节奏紧凑的分镜视觉层。忠于原文叙事、保留情绪张力。
"""
```

**Vì sao hiệu quả (sau khi full):** step2 **không** được đụng `novel_text` (TTS truth); `segment_id` alignment cứng; field guides inject full scene/action prose; pacing block + asset appearance note chặn tự bịa trang phục.

---

### 4.5 Drama step1 normalize + step2 visual

**Task lines** (`prompt_builders_script.py:162-170`):

```
_NORMALIZE_TASK_NOVEL = (
    "你的任务是将小说原文**改编**为结构化的分镜场景内容（含视觉改编描述、逐字口播 utterances "
    "与原文锚 source_text），用于后续 AI 视频生成。"
)
_NORMALIZE_TASK_SCREENPLAY = (
    "你的任务是从作者已写好的剧本中**提取**结构化的分镜场景内容："
    "逐字保留台词与画外音（落在 utterances）、摘录原文锚 source_text、把视觉层转写为场景描述，"
    "用于后续 AI 视频生成。这是成品剧本、不是待加工的素材——只做提取、不做再创作。"
)
```

**Drama visual role** (`:212-218`):

```
_DRAMA_VISUAL_ROLE = (
    "你是一位资深的短剧分镜摄影 / 动作设计师。下方分镜内容（场景边界、出场资产、逐字口播、"
    "原文锚、视觉改编描述）均已定稿，你的唯一职责是为每个分镜补全视觉生产层："
    "image_prompt（画面）与 video_prompt（动作 / 运镜 / 环境音）。"
    "**不要改写或重述口播、不要新增 / 删除 / 重排分镜、不要改动场景内容**——只按 scene_id 逐条产出视觉字段。"
)
```

Duration lower-bound for dialogue (`:599-604`): speech_rate from `lib.speech_rate` — pick duration ≥ TTS length estimate.

---

### 4.6 Narration step1 split (`build_narration_split_prompt`)

Key rules (`:714-770`):

- `novel_text` **逐字** — TTS truth source  
- Split at sentence/paragraph boundaries, keep semantic units  
- `segment_break` only real scene changes  
- Asset arrays required (empty `[]` if none)

---

### 4.7 Pacing rules shared (`lib/prompt_rules/episode_pacing.py`)

```
DRAMA_PACING_RULES = """分集节奏（短剧体裁建议）：
- 开篇 ~4 秒承担钩子职能：用强冲击 / 悬念 / 危机切入，避免介绍性远景。
- 中段每 ~15 秒宜安排一次转折点（动作转折 / 情绪反差 / 关系撕裂 / 异常事件），
  通过画面权重和景别变化呈现，避免长段平铺。
- 末镜停在情绪极致瞬间，shot_type 倾向 Close-up / Extreme Close-up，
  给观众留下回看的钩子。"""

NARRATION_PACING_RULES = """说书节奏建议：
- 首段画面（朗读前 ~4 秒）服务于钩子：用强冲击 / 悬念 / 危机匹配钩子台词，
  避免平铺式开场。
- 末段画面服务于卡点留悬（特写人物 / 关键物件 / 极端表情），
  shot_type 倾向 Close-up / Extreme Close-up。"""
```

Mirrored into subagent `.md` files; drift guarded by tests.

---

### 4.8 Ad / short-video prompt (`prompt_builders_ad.py`)

8-section funnel: `hook → pain_point → product_reveal → selling_point → demo → trust → price_promo → cta`  
Tiers 15/30/60/90s with audited second tables (`:60-110`).  

General rules excerpt:

```
- hook 与 cta 是绝对时长段（hook 2-4s、cta 3-6s），不随档位等比放大
- 即使 hook 不是产品画面，产品也应在前 3 秒内入画
- 单 section 超过 6 秒必须拆成多个镜头；全片平均 3-5 秒/镜
```

Reuses same `_SCENE_WRITING_GUIDE` / `_ACTION_WRITING_GUIDE`. Empty products → generic short-film path (no funnel).

---

### 4.9 Reference-video prompts

**Step1 unit split** — action-only text with `@[Name]`, no appearance (`prompt_builders_reference.py:70-133`).  

**Step2 shot text** structure (`:256-265`):

```
按「景别 → 构图 → 运镜 → 画面内容」四要素依次组织...
角色 / 场景 / 道具仅用 `@[名称]` 引用——外貌、服装、场景陈设等静态外观由参考图承担，**不要**在文本里描写
正例：「景别：中景，轻微仰拍。构图：@[角色A] 居画面中心...」
反例（写外貌）：「身穿某色服装的角色A ...」
```

**Runtime video prompt from unit** (`reference_video_tasks.py:94-108`): assemble shot texts → `render_prompt_for_backend` → `append_video_negative_tail`.

---

### 4.10 Grid prompt (`lib/grid/prompt_builder.py:93-175`)

```
你是一位专业的分镜画师。请严格按照 {rows}×{cols} 宫格布局生成一张包含恰好 {total} 个等大画格的联合图。
【布局要求】... 无边框、无间隙 ... 所有画格保持一致的角色外观、光线和色彩风格
【帧链节奏】
- 格0 是第一个场景的开场画面
- 格1~格N 是相邻场景的过渡帧（前一场景的结束 = 后一场景的开始）
【各格内容】...
【负面约束】禁止：文字、字幕、边框、水印、合并画格、拼贴感...
```

---

### 4.11 Style analysis (`lib/text_backends/prompts.py`)

```
STYLE_ANALYSIS_PROMPT = (
    "Analyze the visual style of this image. Describe the lighting, "
    "color palette, medium (e.g., oil painting, digital art, photography), "
    "texture, and overall mood. Do NOT describe the subject matter "
    "(e.g., people, objects) or specific content. Focus ONLY on the "
    "artistic style. Provide a concise comma-separated list of descriptors "
    "suitable for an image generation prompt."
)
```

---

### 4.12 Prompt design principles (ArcReel)

From module docs (`prompt_builders_script.py:1-10`):

1. **Không lặp enum** đã có trong response_schema  
2. **Không ép shot aesthetic** cứng — model tự chọn shot_type  
3. **Không hard word-count** (“≤200 字”) — dùng ví dụ  
4. **Positive + annotated negative examples** > checklist 必须/禁止  
5. **Content/visual split** (ADR 0041) — novel_text/utterances không qua step2 LLM  
6. **Tag neutralization** `<`→`＜` trong dynamic text chống prompt injection phá XML blocks  

---

## 5. Vòng QA / retry / repair

### 5.1 Structured validation

| Layer | Mechanism |
|-------|-----------|
| LLM output | Pydantic `extra="forbid"` on nested models; dynamic response_schema |
| Enum drift | Normalize / soft default (`script_models.py:76-107`) |
| Drama merge | Fail-loud missing/orphan/duplicate scene_id |
| “No worse” guard | Script edit must not introduce new validation errors |
| Duration | `assert_duration_supported` → `VideoCapabilityError` code (`generation_tasks.py:169-197`) |
| Empty r2v prompt | Enqueue guard + execute-time check |

### 5.2 API retry

`lib/retry.py`:

- `DEFAULT_MAX_ATTEMPTS = 3`, backoff `(2, 4, 8)` + jitter  
- Download: 5 attempts `(5, 10, 20, 40)`  
- Retryable: Connection/Timeout + string patterns 429/5xx  
- `NonRetryableError` short-circuit  

### 5.3 Video submit/poll/download

`video_backends/base.py`: `should_retry_submit/poll/download`, `poll_with_retry`, `persist_provider_job_id` for resume.

### 5.4 Task-level cancel / orphan / resume

State machine (`CONTEXT.md:61-66`):

```
queued → running → succeeded | failed | cancelling → cancelled
```

- **Cancel:** second-level — cancel asyncio Task + free slot (not DB-only)  
- **Orphan on restart:** if `provider_job_id` → resume poll; else mark failed **without re-submit** (avoid double charge)  
- **Non-resumable providers:** Grok, Vidu registered (`generation_worker.py:47-58`)  
- **Resume executor:** `resume_executor.py` — **không** require local storyboard files (job already paid)

### 5.5 Không có

- Automated visual QA (face ID / CLIP similarity)  
- Auto re-roll budget with quality scorer  
- Critic agent trên frame pixels  

Repair = user regenerate / image_edit (i2i instruction, does **not** rewrite image_prompt) + version history.

---

## 6. Tích hợp video-gen

### 6.1 Modes

| Mode | Input | Output |
|------|-------|--------|
| Image-to-video | Storyboard PNG (± end_frame) + video YAML | clip |
| Grid-to-video | Split grid cells as first/last | clips |
| Reference-to-video | Character/scene/prop sheets + `@` prompt | clip (skip storyboard) |

### 6.2 VideoCapabilities (`video_backends/base.py:392-413`)

```python
first_frame: bool = True
last_frame: bool = False
max_reference_images: int = 0
reference_audio_mode: NONE | DIRECT
max_reference_audio_count: int = 0
```

Request fields: `start_image`, `end_image`, `reference_images`, `reference_audio_files`, `generate_audio`, `seed`, `service_tier`.

### 6.3 Providers (built-in)

Image/Video backends under `lib/*_backends/`: Gemini (Veo), Ark (Seedance), Grok, OpenAI (Sora), Vidu, DashScope, MiniMax, Kling, Agnes, NewAPI + **custom endpoints**.

**No silent cross-provider fallback** — `GenerationContext` fails if declared lane fails (`CONTEXT.md:102-104`). Resolve order: request payload > project > global default.

### 6.4 Queue & concurrency

- In-process worker (same uvicorn process)  
- Slots: **provider × media_type** (image/video/audio)  
- Defaults IMAGE_MAX_WORKERS=5, VIDEO_MAX_WORKERS=3  
- Dependency chain: storyboard batch groups by `segment_break` (`build_storyboard_dependency_plan`)

### 6.5 Audio

- TTS: DashScope Qwen3 + OpenAI-compatible; queued like media (`CONTEXT.md:177-187`)  
- Native video audio: `Voice_Profiles` + optional reference_audio (Seedance/Wan)  
- `derive_voice_consistency`: `native | soft | none`

---

## 7. Pacing / timing

| Source | Rule |
|--------|------|
| Model | `supported_durations` discrete set SSOT (`CONTEXT.md:135-137`) |
| Project | `default_duration` null = AI auto within set |
| Drama step1 | Duration ≥ speech estimate (soft lower bound) |
| Narration | Split by reading rhythm; novel_text drives TTS length |
| Ad | Audited 15/30/60/90 section tables; 3–5s average shot |
| R2V unit | Sum of shots ≤ `max_duration`; pack near max |
| Pacing prompt | ~4s hook, ~15s mid turns, close-up ending |
| Compose | `transition_to_next`: cut/fade/dissolve; CapCut export |

Fallback item durations: segments 4s, scenes 8s (`script_models.py:801`).

---

## 8. Chi tiết nhỏ đáng học

1. **Prompt SSOT** — WebUI + Agent skills cùng `prompt_builders*` (header `prompt_builders.py:1-4`).  
2. **extra="forbid"** trên nested schema chặn hallucinated fields + typo.  
3. **SkipJsonSchema** ẩn runtime fields khỏi LLM schema.  
4. **VersionManager** auto-version mỗi regenerate + rollback.  
5. **Cost snapshot** frozen at API success — không recompute (`CONTEXT.md:167-169`).  
6. **path_safety / try_safe_join** trên mọi relative path từ JSON.  
7. **Reference label = asset name** for Gemini-style inline binding.  
8. **Image edit** forks image not prompt (`CONTEXT.md:117-119`).  
9. **Active credential** manual switch, multi-key per provider.  
10. **Agent sandbox** (bwrap) + skill/subagent orchestration.  
11. **import-linter** layers: config ← backends ← custom_provider.  
12. **SSE** task terminal events + asset fingerprints for UI cache.  
13. **Tag neutralize** in prompts against `</segments>` injection.  
14. **Product ref order:** sheet first, original photos last (anchor).  

---

## 9. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện ArcReel | Gap OmniCast | File đích gợi ý | Impact | Effort |
|---|-------------------|--------------|-----------------|--------|--------|
| 1 | Two-step content/visual split; novel_text never re-LLM | Script step có thể drift VO | `agents/writer*`, storyboard extract | High (TTS/script fidelity) | M |
| 2 | Structured ImagePrompt/VideoPrompt → YAML | Prompt ad-hoc string | `storyboard/schemas.py`, veo prompt builder | High | M |
| 3 | Scene/action writing guides + examples | Chưa có SSOT writing guide | `storyboard/` or `agents/` prompt packs | High | S |
| 4 | Previous-frame ref with “composition only” description | Chưa chain frames | `storyboard/binding.py`, pipeline | High | M |
| 5 | Character 4-view sheet layout constants | refsheet views khác; học layout | `storyboard/refsheet.py` | Med | S |
| 6 | `@name → [图N]` order = attachment order | Đã có `[IMAGE n]` — **giữ OmniCast** + harden | `binding.py` | — | — |
| 7 | RefRole still missing in ArcReel | OmniCast **ahead** — ship to veo | `binding.py`, `media/veo_pipeline.py` | Critical | M |
| 8 | Generation queue + resume by job_id | Jobs ad-hoc | new `pipeline/queue` or vault tasks | High ops | L |
| 9 | Provider Protocol + CapacityTable | Multi-provider rời | `media/providers/` | High | L |
| 10 | Negative as text tail (not API channel) | Unify across backends | image/video providers | Med | S |
| 11 | Product fidelity + sheet+original stack | Chưa product mode | optional future | Low now | M |
| 12 | Grid first-last chain | Chưa | optional | Med | L |
| 13 | Duration × speech_rate lower bound | Pacing vs VO length | storyboard/timing | High | S |
| 14 | Episode pacing rules (~4s hook) | YouTube pacing separate | writer prompts | Med | S |
| 15 | Connect storyboard → render | **WS1 gap** | `render_real_video.py`, `veo_pipeline.py` | Critical | L |
| 16 | Wire Flow Ingredients ≤14 | Gap | `media/veo_pipeline.py` | High | M |

### Ưu tiên 30 ngày (concept-only reimplementation)

1. **YAML structured prompts + writing guides** cho image/video gen.  
2. **Previous-storyboard continuity ref** + description “composition only”.  
3. **Ship RefRole bindings into Veo/Gemini path** (OmniCast advantage).  
4. **Two-step** script: lock VO text before visual prompts.  
5. **Duration vs VO length** soft constraint.

---

## 10. KHÔNG nên học + LICENSE

### License

**AGPL-3.0** — network copyleft.  
→ Học: kiến trúc, data model, prompt **patterns**, queue semantics.  
→ **Cấm:** copy-paste Python/TS/prompt strings vào OmniCast commercial path; fork network service without source offer.

### Anti-patterns / hạn chế

1. **AGPL** khóa reuse trực tiếp.  
2. Reference binding storyboard path **yếu hơn** OmniCast (label only, no ignore-role).  
3. Missing sheet → **skip silently** (có log) — có thể gen không ref.  
4. Không pixel consistency QA.  
5. Worker **single-process** — lease multi-worker là scaffold, không cluster.  
6. Orphan without job_id → fail (đúng anti-double-bill) nhưng UX “mất job”.  
7. Prompt-injection neutralize chỉ `<>` — không full LLM security.  
8. Complexity: ~1145 code files — onboarding cost cao.  
9. Windows native sandbox degrade (README).  
10. Enum soft-default có thể che shot_type drift.

---

## 11. Câu hỏi riêng — trả lời ngắn

### Workspace model?

**Project + episode + ordered shot list + asset folders.** Có storyboard/shot list rõ. Không NLE timeline-first.

### Backend/frontend chia việc?

- **Frontend:** React workspace, SSE tasks, asset UI, assistant.  
- **Backend:** FastAPI + in-process GenerationWorker.  
- **Agent:** Claude SDK skills enqueue same queue as WebUI.  
- **States:** queued/running/succeeded/failed/cancelling/cancelled; resume via `provider_job_id`.

### Provider abstraction?

- Protocols: `ImageBackend`, `VideoBackend`, `AudioBackend`, `TextBackend`.  
- `PROVIDER_REGISTRY` + custom `ENDPOINT_REGISTRY`.  
- Credentials multi-key, active switch; Agent Anthropic credentials **tách** media credentials.  
- **No silent multi-provider fallback.**

### Character consistency vs OmniCast cast-registry?

- ArcReel: project library + sheets + previous frame + r2v `[图N]`.  
- OmniCast: per-video entities + `[IMAGE n]` + **RefRole** — tốt hơn về semantic isolation; ArcReel mature hơn về productized multi-mode pipeline.

### Video-gen prompt from scene?

1. Structured `video_prompt` → YAML (`Action`/`Camera_Motion`/`Ambiance_Audio`/`Dialogue`) + `禁止出现：BGM、文字字幕、水印。`  
2. R2V: shot texts with `@` → `[图N]` + same video negative.  
3. Grid path separate.

### Tốt hơn / kém hơn OmniCast?

**Tốt hơn:** queue/resume, multi-provider, two-step script, product fidelity, grid, export, agent runtime, cost, writing-guide quality.  
**Kém hơn:** RefRole ignore clauses, fail-closed cast continuity, costume entity, operator-image policy clarity, AGPL reuse.

---

## ROUND 2 — VERBATIM FULL (theo VERIFY §4.4)

> **LICENSE / reuse:** ArcReel là **AGPL-3.0**. Toàn bộ khối verbatim trong section này **CHỈ để nghiên cứu nội bộ**.
> **CẤM** chép nguyên văn vào code OmniCast (commercial / network service). Học pattern rồi viết lại.

Mục tiêu: vá V3 + bổ sung partial list VERIFY §4.4 — **CẤM ellipsis truncation trong khối verbatim**.

---

### R2.1 Drama visual builders — FULL (`prompt_builders_script.py`)

#### Constants dùng bởi step2 drama (`:211-218`)

```python
# step2（build_drama_prompt）开篇角色定位 + 收尾目标——视觉层专责，无 source_kind 分支
_DRAMA_VISUAL_ROLE = (
    "你是一位资深的短剧分镜摄影 / 动作设计师。下方分镜内容（场景边界、出场资产、逐字口播、"
    "原文锚、视觉改编描述）均已定稿，你的唯一职责是为每个分镜补全视觉生产层："
    "image_prompt（画面）与 video_prompt（动作 / 运镜 / 环境音）。"
    "**不要改写或重述口播、不要新增 / 删除 / 重排分镜、不要改动场景内容**——只按 scene_id 逐条产出视觉字段。"
)
_DRAMA_VISUAL_GOAL = "输出可直接驱动 AI 图像 / 视频生成的、视觉一致、节奏紧凑的视觉层。忠于已定稿的分镜内容与戏剧张力。"
```

#### `_ASSET_APPEARANCE_NOTE` (`:44-45`)

```python
# step2 资产块的取材注记（narration / drama 共用）：外观细节以登记描述为准，不自行发明。
_ASSET_APPEARANCE_NOTE = "资产外观以上述描述为准：视觉字段写到出场资产的服装 / 材质 / 陈设细节时从中取材，不自行发明。"
```

#### `build_drama_prompt` FULL (`:406-503`)

```python
def build_drama_prompt(
    project_overview: dict,
    style: str,
    style_description: str,
    scenes_content: str,
    episode: int,
    aspect_ratio: str = "16:9",
    target_language: str = "中文",
    characters: dict | None = None,
    scenes: dict | None = None,
    props: dict | None = None,
) -> str:
    """构建剧集动画模式 step2（视觉层）prompt。

    内容抽取前移到 step1（见 ADR 0041）：场景边界、出场资产、逐字口播 utterances、原文锚
    source_text、视觉改编描述均已在 step1 定稿，``scenes_content`` 是其渲染输入
    （``render_drama_content_for_step2``）。step2 仅产出视觉层（image_prompt / video_prompt），
    LLM 输出按 scene_id 与 step1 内容对齐、由后端合并；不再按 source_kind 分支、不再识别口播、
    不再标注资产或时长——这些都是 step1 的职责。

    ``characters`` / ``scenes`` / ``props`` 注入出场资产的外观描述（project.json 各 bucket），
    供视觉字段写服装 / 材质 / 陈设细节时取材；三者都为 None 时不渲染资产块。
    """
    pacing_block = render_pacing_section("drama") + "\n\n"
    assets_block = ""
    if characters is not None or scenes is not None or props is not None:
        assets_block = f"""<characters>
{_format_assets_with_desc(characters or {})}
</characters>

<scenes>
{_format_assets_with_desc(scenes or {})}
</scenes>

<props>
{_format_assets_with_desc(props or {})}
</props>

{_ASSET_APPEARANCE_NOTE}

"""

    return f"""# 角色与任务

{_DRAMA_VISUAL_ROLE}
你的任务：基于下方已定稿的「分镜内容」，为每个 scene_id 逐条产出视觉层 JSON（image_prompt / video_prompt）。

**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。
**对齐约束**：每个分镜产出一条视觉层，`scene_id` 必须与下方内容逐字一致、不增不减不改；不要输出口播 / 时长 / 资产等非视觉字段。

{pacing_block}# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}（{_format_aspect_ratio_desc(aspect_ratio)}）
</style>

{assets_block}分镜内容中的「口播」与「原文锚」仅供理解戏剧节奏与语境，不要复制进视觉字段。

<shots>
{scenes_content}
</shots>

<episode_constraints>
当前正在生成第 {episode} 集。每条视觉层的 scene_id 必须逐字等于上方分镜内容里的 scene_id；若该 ID 含拆分/编辑后缀（如 `_1`），也必须原样保留，不得改写、合并或新增。
</episode_constraints>

# 字段写作指引

对每个分镜，按下列章节填写视觉字段。

## 图片提示词（image_prompt）——切换到「摄影师」视角

- **image_prompt.scene**：{_SCENE_WRITING_GUIDE}
- **image_prompt.composition.shot_type**：从枚举中按画面内容选择，不强加倾向。
- **image_prompt.composition.lighting**：{_LIGHTING_WRITING_GUIDE}
- **image_prompt.composition.ambiance**：{_AMBIANCE_WRITING_GUIDE}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{_ACTION_WRITING_GUIDE}
- **video_prompt.camera_motion**：按画面内容自行选择。
- **video_prompt.ambiance_audio**：{_AMBIANCE_AUDIO_WRITING_GUIDE}

# 创作目标

{_DRAMA_VISUAL_GOAL}
"""
```

Ghi chú: `render_drama_content_for_step2` (`:350-403`) chỉ **render** step1 dict → text block `<shots>`; không phải LLM system prompt. Step2 inject kết quả qua `{scenes_content}`.

---

### R2.2 Grid `prompt_builder.py` — FULL file

Nguồn: `lib/grid/prompt_builder.py` (toàn file).

```python
"""Grid prompt builder for grid-image-to-video feature."""

from __future__ import annotations

from math import gcd


def _extract_image_desc(scene: dict) -> str:
    """Extract image description from a scene.

    If image_prompt is a dict, join scene + composition fields.
    If string, return as-is.
    """
    image_prompt = scene.get("image_prompt", "")
    if isinstance(image_prompt, dict):
        parts = []
        scene_text = image_prompt.get("scene", "")
        if scene_text:
            parts.append(scene_text)
        composition = image_prompt.get("composition", {})
        if isinstance(composition, dict):
            comp_parts = [f"{k}: {v}" for k, v in composition.items() if v]
            if comp_parts:
                parts.append("，".join(comp_parts))
        return "；".join(parts) if parts else ""
    return str(image_prompt)


def _extract_action(scene: dict) -> str:
    """Extract closing action from video_prompt.

    If dict, return action field. If string, return as-is.
    """
    video_prompt = scene.get("video_prompt", "")
    if isinstance(video_prompt, dict):
        return str(video_prompt.get("action", ""))
    return str(video_prompt)


def _compute_panel_aspect(grid_aspect_ratio: str, rows: int, cols: int) -> str:
    """从整体宫格比例推算单格比例。

    例：grid 4:3, 3行2列 → panel (4/2):(3/3) = 2:1
    """
    gw, gh = (int(x) for x in grid_aspect_ratio.split(":"))
    pw = gw * rows  # 交叉相乘避免浮点
    ph = gh * cols
    g = gcd(pw, ph)
    return f"{pw // g}:{ph // g}"


def build_grid_prompt(
    *,
    scenes: list[dict],
    id_field: str,
    rows: int,
    cols: int,
    style: str,
    aspect_ratio: str = "16:9",
    grid_aspect_ratio: str | None = None,
    reference_image_mapping: dict[str, str] | None = None,
) -> str:
    """Assemble a grid image generation prompt with first-last frame chain structure.

    Args:
        scenes: List of scene dicts with image_prompt and video_prompt fields.
        id_field: Key in each scene dict for the scene ID.
        rows: Number of rows in the grid.
        cols: Number of columns in the grid.
        style: Style description for the grid.
        aspect_ratio: Aspect ratio for each cell (default "16:9").
        reference_image_mapping: Optional mapping of image labels to character names.

    Returns:
        Assembled prompt string.
    """
    total = rows * cols
    n_scenes = len(scenes)

    # Number of content cells: first frame + (n_scenes - 1) transitions + last first frame
    # Cell 0: first scene opening
    # Cells 1..n_scenes-2: transitions between consecutive scenes
    # Cell n_scenes-1: last scene opening
    # Remaining cells: placeholders
    n_content = n_scenes  # 1 first + (n-2) transitions + 1 last = n

    effective_grid_ar = grid_aspect_ratio or aspect_ratio
    panel_ar = _compute_panel_aspect(effective_grid_ar, rows, cols)

    lines: list[str] = []

    # Header
    lines.append(
        f"你是一位专业的分镜画师。请严格按照 {rows}×{cols} 宫格布局生成一张包含恰好 {total} 个等大画格的联合图。"
    )
    lines.append("")

    # Layout requirements
    lines.append("【布局要求】")
    lines.append(f"- 恰好 {rows} 行 {cols} 列，共 {total} 个画格，阅读顺序：从左到右，从上到下")
    lines.append(f"- 整体图片比例：{effective_grid_ar}")
    lines.append(f"- 每个画格比例：{panel_ar}，所有画格大小完全相同")
    lines.append("- 画格之间无边框、无间隙、无留白，紧密排列")
    lines.append("- 不得合并画格、不得遗漏画格、不得错位排列")
    lines.append("- 所有画格保持一致的角色外观、光线和色彩风格")
    lines.append("")

    # Frame chain rhythm
    lines.append("【帧链节奏】")
    lines.append("本宫格采用首尾帧链式结构：")
    lines.append("- 格0 是第一个场景的开场画面")
    lines.append(f"- 格1~格{n_content - 1} 是相邻场景的过渡帧（前一场景的结束 = 后一场景的开始）")
    lines.append("- 相邻格之间应体现画面的自然过渡和动作延续")
    lines.append("")

    # Reference images (optional)
    if reference_image_mapping:
        lines.append("【参考图说明】")
        for label, character in reference_image_mapping.items():
            lines.append(f"- {label}：{character}")
        lines.append("")

    # Cell contents
    lines.append("【各格内容】")

    for cell_idx in range(total):
        row_num = cell_idx // cols + 1
        col_num = cell_idx % cols + 1
        position = f"row{row_num} col{col_num}"

        if cell_idx == 0:
            # First scene opening
            scene = scenes[0]
            scene_id = scene.get(id_field, "")
            image_desc = _extract_image_desc(scene)
            lines.append(f"格{cell_idx}（{position}）— {scene_id}开场：")
            lines.append(f"  {image_desc}")

        elif cell_idx < n_scenes:
            # Transition between scenes[cell_idx-1] and scenes[cell_idx]
            prev_scene = scenes[cell_idx - 1]
            next_scene = scenes[cell_idx]
            prev_scene_id = prev_scene.get(id_field, "")
            next_scene_id = next_scene.get(id_field, "")
            prev_action = _extract_action(prev_scene)
            next_image_desc = _extract_image_desc(next_scene)
            lines.append(f"格{cell_idx}（{position}）— {prev_scene_id}→{next_scene_id}过渡：")
            lines.append(f"  {prev_action}，过渡到 {next_image_desc}")

        else:
            # Placeholder
            lines.append(f"格{cell_idx}（{position}）— 空占位：纯灰色背景，无任何内容")

    lines.append("")

    # Style requirements
    lines.append("【风格要求】")
    lines.append(style)
    lines.append("")

    # Negative constraints
    lines.append("【负面约束】")
    lines.append("禁止出现以下任何元素：")
    lines.append("- 文字、字幕、标签、标题、数字编号、时间戳")
    lines.append("- 水印、logo、签名")
    lines.append("- 白色边框、黑色边框、粗边框、装饰性边框")
    lines.append("- 分隔线、间隙、间距、留白、padding、margin")
    lines.append("- 白色背景、纯色背景条")
    lines.append("- 合并的画格、缺失的画格、错位的画格")
    lines.append("- 连续全景图（非分格）、单张大图")
    lines.append("- 模糊、低画质、噪点")
    lines.append("- 拼贴感、蒙太奇拼接感")
    lines.append("- 画格大小不一致、画格比例不一致")

    return "\n".join(lines)
```

---

### R2.3 `prompt_builders_ad.py` — tier tables + builders FULL

#### Tiers / section values / general rules / tier tables (`:34-110`)

```python
AD_DURATION_TIERS: tuple[int, ...] = (15, 30, 60, 90)

#: 默认推荐档（秒），档位等距 tie-break 的锚点。
AD_DEFAULT_TIER = 30

#: section 八值引导（不硬枚举，留给 prompt 约束；与审定配比表用词一致）。
AD_SECTION_VALUES: tuple[str, ...] = (
    "hook",
    "pain_point",
    "product_reveal",
    "selling_point",
    "demo",
    "trust",
    "price_promo",
    "cta",
)

_AD_GENERAL_RULES = """\
通用规则（适用于全部档位）：

- hook 与 cta 是绝对时长段（hook 2-4s、cta 3-6s），不随档位等比放大；加长的秒数优先给 selling_point/demo，其次 trust
- price_promo 永远紧贴 cta 构成「促单收尾块」
- 即使 hook 不是产品画面，产品也应在前 3 秒内入画（文字/局部/手持均可）
- 单 section 超过 6 秒必须拆成多个镜头；全片平均 3-5 秒/镜，开头允许 2-3 秒快切；镜头数宁多勿少（多场景多角度有平台官方数据背书）
- 30 秒档为默认推荐档；90 秒档用「小故事」组织而非平铺卖点，仅适合高客单/需教育的产品"""

_AD_TIER_TABLES: dict[int, str] = {
    15: """\
15 秒档（冲动型/投流款，5-6 镜头；只保五段：pain_point 并入 hook、trust 砍掉、price_promo 并入 cta）：

| section | 秒数 | 累计 | 镜头数 |
|---|---|---|---|
| hook（兼任 pain_point） | 3 | 0-3 | 1 |
| product_reveal | 2 | 3-5 | 1 |
| selling_point（1 个核心卖点） | 3 | 5-8 | 1 |
| demo | 4 | 8-12 | 1-2 |
| cta（可带一句促销词兼任 price_promo） | 3 | 12-15 | 1 |""",
    30: """\
30 秒档（标准带货位，默认推荐，8-10 镜头；八段全保，trust 与 price_promo 压成一句话镜头；产品极低客单且无可信背书时首砍 trust、秒数还给 demo）：

| section | 秒数 | 累计 | 镜头数 |
|---|---|---|---|
| hook | 3 | 0-3 | 1 |
| pain_point | 4 | 3-7 | 1-2 |
| product_reveal | 3 | 7-10 | 1 |
| selling_point（1-2 个） | 6 | 10-16 | 2 |
| demo | 6 | 16-22 | 2 |
| trust（一句话社证） | 3 | 22-25 | 1 |
| price_promo | 2 | 25-27 | 1 |
| cta | 3 | 27-30 | 1 |""",
    60: """\
60 秒档（完整说服链，13-16 镜头；八段全保各自成块，增量给 selling_point+demo）：

| section | 秒数 | 累计 | 镜头数 |
|---|---|---|---|
| hook | 3 | 0-3 | 1 |
| pain_point（1-2 个具体情境） | 7 | 3-10 | 2 |
| product_reveal | 5 | 10-15 | 1-2 |
| selling_point（2-3 个，每个 4-6s 一镜） | 12 | 15-27 | 3 |
| demo（多角度/前后对比） | 15 | 27-42 | 3-4 |
| trust（评价+销量/资质） | 8 | 42-50 | 2 |
| price_promo（原价锚定→到手价→限时） | 5 | 50-55 | 1-2 |
| cta（行动指令+重申核心利益） | 5 | 55-60 | 1 |""",
    90: """\
90 秒档（叙事型/高客单，18-22 镜头；八段全保，增量给 demo/selling_point/trust/pain_point）：

| section | 秒数 | 累计 | 镜头数 |
|---|---|---|---|
| hook（可用悬念/故事钩） | 4 | 0-4 | 1 |
| pain_point（人物+冲突小叙事） | 10 | 4-14 | 2-3 |
| product_reveal（转折点：遇见产品） | 6 | 14-20 | 1-2 |
| selling_point（3 个，逐个展开） | 20 | 20-40 | 3-4 |
| demo（多场景使用过程，核心块） | 24 | 40-64 | 4-6 |
| trust（证言/检测报告/销量） | 12 | 64-76 | 2-3 |
| price_promo（价格锚定+优惠拆解） | 8 | 76-84 | 2 |
| cta（紧迫感收口） | 6 | 84-90 | 1 |""",
}
```

#### `_format_pacing_block` (`:118-128`)

```python
def _format_pacing_block(target_duration: int) -> str:
    """渲染配比段：通用规则 + 命中档位的审定表；非四档整数附按比例适配说明。"""
    tier = nearest_ad_tier(target_duration)
    parts = [_AD_GENERAL_RULES, _AD_TIER_TABLES[tier]]
    if tier != target_duration:
        parts.append(
            f"目标总时长 {target_duration} 秒不在审定档位内，按最近档位 {tier} 秒的配比模板"
            f"按比例适配到 {target_duration} 秒：hook 与 cta 是绝对时长段维持原秒数，"
            "伸缩量按通用规则优先给 selling_point/demo，其次 trust。"
        )
    return "\n\n".join(parts)
```

#### `build_ad_prompt` FULL (`:178-345`)

```python
def build_ad_prompt(
    project_overview: dict,
    style: str,
    style_description: str,
    characters: dict,
    scenes: dict,
    props: dict,
    products: dict,
    brief: str,
    target_duration: int,
    generation_mode: str,
    supported_durations: list[int] | None,
    episode: int = 1,
    aspect_ratio: str = "9:16",
    target_language: str = "中文",
) -> str:
    """构建广告/短片模式的剧本生成 prompt。

    ``products`` 非空走带货八段框架 + 审定配比表；为空自动分流通用短片 prompt
    （无带货框架，不设显式子模式开关）。
    """
    if not isinstance(target_duration, int) or isinstance(target_duration, bool) or target_duration <= 0:
        raise ValueError(f"target_duration 必须为正整数秒，当前为 {target_duration!r}")

    duration_constraint = _shot_duration_constraint(generation_mode, supported_durations)
    # 口播字数→时长折算从 lib.speech_rate 单一真相源取（与 drama step1 下界、字幕派生同口径）。
    # 语速表按语言代码（zh / en / vi）登记；target_language 是自由文本（默认「中文」），
    # 未登记值回退默认语速（zh 口径），量词（字 / 词）由 reading_unit_noun 同源派生。
    speech_rate = speech_rate_units_per_second(target_language)
    unit_label = reading_unit_noun(target_language)
    voiceover_rate_note = f"口播长度按约 {speech_rate:g} {unit_label}/秒折算"
    character_names = list(characters.keys())
    scene_names = list(scenes.keys())
    prop_names = list(props.keys())
    product_names = list(products.keys())

    common_header = f"""**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}（{_format_aspect_ratio_desc(aspect_ratio)}）
</style>

<brief>
{brief or "（未提供，按产品信息与常识自行设计）"}
</brief>

<characters>
{_format_names(characters)}
</characters>

<scenes>
{_format_names(scenes)}
</scenes>

<props>
{_format_names(props)}
</props>"""

    common_constraints = f"""<episode_constraints>
本片为单视频（恒第 {episode} 集）。所有 shot_id 必须严格使用 `E{episode}S{{两位序号}}` 格式（如 E{episode}S01、E{episode}S02），按播放顺序连续编号，不得使用其他集号前缀。
</episode_constraints>"""

    common_field_guides = f"""## 图片提示词（image_prompt）——切换到「摄影师」视角

- **image_prompt.scene**：{_SCENE_WRITING_GUIDE}
- **image_prompt.composition.shot_type**：从枚举中按画面内容选择，不强加倾向。
- **image_prompt.composition.lighting**：{_LIGHTING_WRITING_GUIDE}
- **image_prompt.composition.ambiance**：{_AMBIANCE_WRITING_GUIDE}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{_ACTION_WRITING_GUIDE}
- **video_prompt.camera_motion**：按画面内容自行选择。
- **video_prompt.ambiance_audio**：{_AMBIANCE_AUDIO_WRITING_GUIDE}
- **video_prompt.dialogue**：仅当镜头内有出镜人物开口说话时填写（口播旁白写在 voiceover_text，不要重复进 dialogue）；speaker 必须出现在 characters_in_shot。"""

    if not products:
        return f"""# 角色与任务

你是一位资深的短视频编导，精通把一段创作诉求转写为可直接驱动 AI 图像 / 视频生成的结构化镜头脚本。
你的任务：基于下方创作 brief，产出一支约 {target_duration} 秒的通用短片镜头脚本（平铺 shots[]），符合 schema 的 JSON。

{common_header}

# 时长与节奏

- 全片目标总时长 {target_duration} 秒，各镜头 duration_seconds 之和应贴近该值。
- 单镜头{duration_constraint}；全片平均 3-5 秒/镜，按内容节奏自行切分。

{common_constraints}

# 字段写作指引

## 基础字段

- **section**：本片无带货框架，按内容自拟简短英文段落标签（如 opening/development/climax/ending），用于标记镜头在叙事中的位置。
- **voiceover_text**：每镜头的口播文案，必须完整可照稿配音；无口播的纯画面镜头填空字符串。{voiceover_rate_note}。
- **characters_in_shot** / **scenes** / **props**：仅列出此镜头画面中实际出现的资产。
  - 候选 characters：[{", ".join(character_names) or "（无）"}]
  - 候选 scenes：[{", ".join(scene_names) or "（无）"}]
  - 候选 props：[{", ".join(prop_names) or "（无）"}]
  - 不要发明候选之外的名称。
- **products_in_shot**：本项目无产品资产，所有镜头一律填空数组。

{common_field_guides}

# 创作目标

输出可直接驱动 AI 生成的、视觉一致、节奏紧凑的短片脚本。忠于创作 brief、保留情绪张力。
"""

    return f"""# 角色与任务

你是一位资深的带货短视频编导，精通把产品卖点与创作诉求转写为可直接驱动 AI 图像 / 视频生成的结构化镜头脚本。
你的任务：基于下方产品信息与创作 brief，按带货八段框架与时长配比，产出一支约 {target_duration} 秒的带货短视频镜头脚本（平铺 shots[]），符合 schema 的 JSON。

{common_header}

<products>
{_format_products(products)}
</products>

# 带货八段框架与时长配比

带货短视频按八个段落组织：{" → ".join(AD_SECTION_VALUES)}。
下方配比表经审定，是各段时长与镜头数的执行标准：

{_format_pacing_block(target_duration)}

{common_constraints}

# 字段写作指引

对每个镜头，按下列章节填写字段。

## 基础字段

- **section**：该镜头所属的带货框架段落标签，使用上方八值（如 hook、pain_point）；同段多镜头重复同一标签。
- **voiceover_text**：每镜头的口播文案，必须完整可照稿配音、与画面同步；无口播的纯画面镜头填空字符串。全片口播连起来应是一篇完整流畅的带货话术，{voiceover_rate_note}。
- **duration_seconds**：单镜头{duration_constraint}；各段合计遵循配比表，全片总和贴近 {target_duration} 秒。
- **products_in_shot**：该镜头画面中实际出现的产品名称列表（产品入画即列出，含局部/手持/包装）；氛围镜头填空数组。
  - 候选 products：[{", ".join(product_names)}]
  - 不要发明候选之外的名称。
- **characters_in_shot** / **scenes** / **props**：仅列出此镜头画面中实际出现的资产。
  - 候选 characters：[{", ".join(character_names) or "（无）"}]
  - 候选 scenes：[{", ".join(scene_names) or "（无）"}]
  - 候选 props：[{", ".join(prop_names) or "（无）"}]
  - 不要发明候选之外的名称。

{common_field_guides}

# 创作目标

输出可直接驱动 AI 生成的、产品忠实、节奏紧凑的带货镜头脚本。卖点表达贴合 <products> 的 selling_points，不夸大、不虚构功效。
"""
```

---

### R2.4 `prompt_builders_reference.py` step1 + step2 FULL

#### `build_reference_units_split_prompt` FULL (`:21-134`)

```python
def build_reference_units_split_prompt(
    *,
    novel_text: str,
    project_overview: dict,
    characters: dict,
    scenes: dict,
    props: dict,
    supported_durations: list[int],
    max_duration: int,
    max_reference_images: int | None,
    default_duration: int | None,
    episode: int,
    target_language: str = "中文",
) -> str:
    """Step-1 video_unit 拆分 prompt：源文 → 结构化 unit 表（shots 叙事文本 + 时长）。

    由 ``split_reference_video_units`` MCP tool 消费。输出受 response_schema
    （``build_reference_units_step1_model``，单 shot 时长枚举硬约束）约束为结构化 JSON；
    unit 总时长上限与 references 上限依赖运行时能力值，在 prompt 给出指引、由工具后校验。
    references 不进 LLM 输出，由工具从 shot 文本的 ``@[名称]`` 引用机械派生。

    Args:
        supported_durations: 单 shot 允许的时长取值集合（秒）。
        max_duration: unit 总时长上限（秒），即单次视频生成上限。
        max_reference_images: 单 unit 参考图上限；None 时不写入硬性数量约束。
        default_duration: 用户项目偏好的默认单 shot 秒数；须为 supported_durations 成员或 None。
    """
    normalized_durations = sorted({int(d) for d in supported_durations})
    if not normalized_durations:
        raise ValueError("supported_durations 不能为空：必须提供模型支持的秒数集合")
    if default_duration is not None and int(default_duration) not in normalized_durations:
        raise ValueError(f"default_duration={default_duration} 不在 supported_durations={normalized_durations} 内")

    durations_str = ", ".join(str(d) for d in normalized_durations)
    default_rule = (
        f"单 shot 默认取 {default_duration} 秒，叙事需要更长时可取更长档（偏好可被内容需要覆盖，硬约束不可）"
        if default_duration is not None
        else "按叙事需要从档位中取值，不强制默认值"
    )
    max_refs_rule = (
        f"\n- **references 上限**：一个 unit 内 `@` 引用的资产名（去重后）不超过 {max_reference_images} 个；"
        "超出时把次要角色融入背景描述（不用 `@` 引用），不要压缩主体资产。"
        if max_reference_images is not None
        else ""
    )
    character_names = list(characters.keys())
    scene_names = list(scenes.keys())
    prop_names = list(props.keys())

    return f"""# 角色与任务

你是一位参考生视频单元架构师，本任务是把源文拆分为适配多模态参考视频模型的 video_unit 表（step1 内容拆分）。
每个 video_unit 对应**一次视频生成调用**，含 1-4 个 shot；shot 表示镜头切换，但共享同一次生成。
视觉编排（景别 / 构图 / 运镜扩写）由后续 step2 以你的拆分为基底生成，本阶段只定叙事内容与时间结构。

**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名保持英文。
例外（逐字保留、不翻译）：`@[名称]` 中的资产名须逐字等于下方候选表中的登记名。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<characters>
{_format_asset_names(characters)}
</characters>

<scenes>
{_format_asset_names(scenes)}
</scenes>

<props>
{_format_asset_names(props)}
</props>

## 小说原文

<novel>
{novel_text}
</novel>

# 拆分规则

当前正在生成第 {episode} 集。

- **unit 边界**：每个 unit 对应一个连贯的视频生成片段——同一时间、同一地点、主体动作连续；
  时间 / 空间 / 情节重大切换点开新 unit。
- **unit_id**：`E{episode}U{{两位序号}}` 格式（如 E{episode}U01），按顺序递增，不得用其他集号前缀。
- **时长决策序**（自上而下，高优先级是硬边界，低优先级在其内做优化）：
  1. 硬约束：单 shot 时长必须取支持档位（{durations_str}）中的值；unit 内所有 shot 时长之和不超过 {max_duration} 秒。
     叙事需要的总时长放不下时，把该 unit 按叙事顺序重拆为多个 unit，**不得违约时长**。
  2. 默认偏好：{default_rule}。
  3. 打包效率：在 1、2 之内组合 shot，使 unit 总时长贴近 {max_duration} 秒；不要默认选最短 / 保守值。{max_refs_rule}

# shot 文本写作指引

- 每 shot 的 `text` 聚焦当下瞬间的**可见动作**：谁做了什么、物件互动、环境动态；动词描述物理可观察动作
  （伸手 / 转身 / 推门 / 投向），避免「陷入 / 回忆 / 意识到 / 决定」等内心动词。
- 角色 / 场景 / 道具统一用 `@[名称]` 引用，名称必须逐字取自下列候选，不要发明候选之外的名称：
  - character: {", ".join(character_names) or "（暂无）"}
  - scene: {", ".join(scene_names) or "（暂无）"}
  - prop: {", ".join(prop_names) or "（暂无）"}
- **不要**描写外貌、服装、场景陈设、色调光影——静态外观由参考图承担；泛指群演（老人甲 / 村民若干）
  写入叙事文本即可，不用 `@` 引用、不占 references 名额。
- 本阶段不写景别 / 构图 / 运镜（step2 补），把叙事内容与动作过程写清楚即可。

请覆盖全部源文情节，按叙事顺序逐 unit 产出。
"""
```

#### `render_reference_units_for_step2` (`:137-156`)

```python
def render_reference_units_for_step2(units: list[dict]) -> str:
    """把结构化 step1 units 渲染为 step2 prompt 的输入文本。

    机械渲染、无 LLM 参与：unit_id + 各 shot 时长与叙事文本 + references 表。
    step2 以此为唯一基底做视觉扩写（见 ADR 0041）。
    """
    blocks: list[str] = []
    for unit in units:
        shots = unit.get("shots") or []
        total = sum(int(s.get("duration") or 0) for s in shots if isinstance(s, dict))
        refs = unit.get("references") or []
        refs_line = ", ".join(f"{r.get('type')}:{r.get('name')}" for r in refs if isinstance(r, dict)) or "（无）"
        lines = [f"#### {unit.get('unit_id')}（预估总时长 {total}s）", f"references: {refs_line}"]
        for idx, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                continue
            duration = shot.get("duration")
            lines.append(f"Shot {idx} ({duration if duration is not None else 0}s): {shot.get('text', '')}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
```

#### `build_reference_video_prompt` FULL (`:159-276`)

```python
def build_reference_video_prompt(
    *,
    project_overview: dict,
    style: str,
    style_description: str,
    characters: dict,
    scenes: dict,
    props: dict,
    step1_units: list[dict],
    supported_durations: list[int],
    max_refs: int | None,
    episode: int,
    max_duration: int | None = None,
    aspect_ratio: str = "9:16",
    target_language: str = "中文",
) -> str:
    """构建参考生视频模式的 LLM Prompt。

    Args:
        project_overview: 项目概述（synopsis, genre, theme, world_setting）。
        style / style_description: 视觉风格标签与描述。
        characters / scenes / props: 三类已注册资产字典（用于候选列表）。
        step1_units: 结构化 step1 units（``step1_reference_units.json`` 经校验后的 dict 列表），
            由 ``render_reference_units_for_step2`` 机械渲染进 prompt——step2 以其为唯一基底，
            不解析自由文本。
        supported_durations: 当前视频模型支持的单镜头时长列表（秒）。
        max_refs: 当前视频模型支持的最大参考图数；为 None 时不写入硬性数量约束。
        max_duration: 当前视频模型的单次生成时长上限（秒）。传入时 prompt 会显式
            给出时长目标（贴近 step1 预估、不默认选最短值）；上限本身由动态 schema 的
            duration 枚举硬约束，prompt 不复述。为 None 时不插入该段。
    """
    character_names = list(characters.keys())
    scene_names = list(scenes.keys())
    prop_names = list(props.keys())

    durations_desc = "/".join(str(d) for d in supported_durations) + "s"
    max_refs_line = (
        f"\n    - **references 数量不超过 {max_refs}**（模型上限）；超出时把次要角色合并到背景描述。"
        if max_refs is not None
        else ""
    )
    duration_guide_line = (
        f"\n    - `duration`：unit 内所有 Shot `duration` 之和应贴近 step1 预估时长；预估缺失或超过 "
        f"{max_duration} 秒（当前模型上限）时，以 {max_duration} 秒为目标。不要默认选最短值。"
        if max_duration is not None
        else ""
    )

    return f"""# 角色与任务

你是一位资深的短视频分镜编剧，本任务是为「参考生视频」模式产出 JSON 剧本。
你的任务：基于下方 step1_units 表，按 schema 产出 ReferenceVideoScript。

**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}
</style>

<characters>
{_format_asset_names(characters)}
</characters>

<scenes>
{_format_asset_names(scenes)}
</scenes>

<props>
{_format_asset_names(props)}
</props>

<step1_units>
{render_reference_units_for_step2(step1_units)}
</step1_units>

<episode_constraints>
当前正在生成第 {episode} 集。本集所有 unit_id 沿用 step1_units 表中的编号，必须严格使用 `E{episode}U{{两位序号}}` 格式（如 E{episode}U01、E{episode}U02），不得使用其他集号前缀。
若 step1_units 表里出现非 `E{episode}` 前缀（如残留自其他集号的编号），视为脏数据，请按当前集号 `E{episode}` 重写。
</episode_constraints>

# 字段写作指引

对每个 video_unit，按下列要求填写字段：

a. **shots**：{duration_guide_line}
    - `text`：这段文字将直接驱动该镜头的视频生成（语言遵循上方"输出语言"约束）。按「景别 → 构图 → 运镜 → 画面内容」四要素依次组织，写足画面信息、宁详勿略：
        - 景别：大全景 / 全景 / 中景 / 近景 / 特写，及拍摄角度（俯拍 / 仰拍 / 平视）。
        - 构图：主体在画面中的位置、前景与背景的关系（如中心构图、对角线构图、以公路 / 廊柱作引导线）。
        - 运镜：机位与镜头运动（固定机位 / 跟随 / 推近 / 拉远 / 摇移），含镜头内焦点主体的变更。
        - 画面内容：占篇幅大头——镜头时长内发生的全部可见运动：每个出场主体各自的动作链（肢体 / 手势 / 神态过渡）、物件互动、背景与环境动态（人群、天气、衣摆、光影移动），可带运动质感（如动态模糊），末尾用一句点明氛围基调。动作量与 `duration` 匹配：短镜头完成一个连贯动作 + 一个细节互动，更长的镜头随时长递增动作段数。
        - 角色 / 场景 / 道具仅用 `@[名称]` 引用——外貌、服装、场景陈设等静态外观由参考图承担，**不要**在文本里描写；动作、姿态、互动与环境动态则写得越具体越好。动词应描述物理可观察动作（伸手 / 转身 / 摩挲 / 投向 / 收紧），避免「陷入 / 回忆 / 意识到 / 决定」等内心动词。
        - 正例：「景别：中景，轻微仰拍。构图：@[角色A] 居画面中心，@[场景A] 的窗棂与案几为前景。运镜：固定机位，缓慢推近。画面内容：@[角色A] 在 @[场景A] 中缓步走向窗前，抬手推开木窗，衣摆随穿堂风轻扬；随后低头凝视手中的 @[道具A]，指尖缓缓收紧，呼吸放缓，目光从 @[道具A] 缓慢抬起投向窗外；烛焰随风明灭，光影在面部缓慢移动，渲染压抑而克制的氛围。」
        - 反例（过短）：「@[角色A] 站在 @[场景A] 里。」——没有景别 / 构图 / 运镜，也没有动作过程与环境动态，生成的视频会近乎静止。
        - 反例（写外貌）：「身穿某色服装的角色A 站在某色场景A 前，手里紧握着某色道具A」——外貌 / 服装 / 颜色应由参考图承担，且未用 `@[名称]` 引用。

b. **references**：每个 shot `text` 中出现的 `@[名称]` 都要在 references 注册一次。
    - `name` 必须来自候选：
        - character: {", ".join(character_names) or "（暂无）"}
        - scene: {", ".join(scene_names) or "（暂无）"}
        - prop: {", ".join(prop_names) or "（暂无）"}{max_refs_line}

c. **duration_seconds**：请编排各 shot 时长，使其相加正好落在支持集合（{durations_desc}）内。

请按 step1_units 顺序逐 unit 产出。
"""
```

---

### R2.5 Checklist ROUND 2 vs VERIFY §4.4

| VERIFY yêu cầu | Vị trí report |
|----------------|---------------|
| Full `build_narration_prompt` | §4.4 (V3 vá) |
| Full drama visual builders | R2.1 |
| Full grid `prompt_builder.py` | R2.2 |
| Full ad tier tables + `build_ad_prompt` | R2.3 |
| Full reference step1+2 | R2.4 |

---

## Đã đọc (file list)

### Core domain
- `LICENSE`, `README.en.md`, `CONTEXT.md` (partial, language section)
- `lib/script_models.py` (full structure through reference video)
- `lib/script_skeleton.py`
- `lib/asset_types.py`
- `lib/prompt_builders.py` (full)
- `lib/prompt_builders_script.py` (**full** — ROUND2: `build_narration_prompt`, `build_drama_prompt`, drama constants)
- `lib/prompt_builders_ad.py` (**full** — ROUND2: tier tables + `build_ad_prompt`)
- `lib/prompt_builders_reference.py` (**full** — ROUND2: step1 split + step2 video prompt)
- `lib/prompt_utils.py` (full)
- `lib/prompt_rules/episode_pacing.py` (full)
- `lib/grid/prompt_builder.py` (**full file** — ROUND2)
- `lib/text_backends/prompts.py` (full)
- `lib/storyboard_sequence.py` (full)
- `lib/media_generator.py` (header + ref compression + API surface)
- `lib/generation_queue.py` (enqueue + states)
- `lib/generation_worker.py` (header + orphan/resume signals)
- `lib/retry.py`
- `lib/providers.py`
- `lib/project_manager.py` (SUBDIRS, content_mode)
- `lib/image_backends/base.py`, `lib/video_backends/base.py` (capabilities + request), `lib/audio_backends/base.py`
- `lib/reference_video/shot_parser.py` (render + assemble)
- `lib/db/models/asset.py`
- `alembic/versions/d67efd76058f_create_assets_table.py`

### Server services
- `server/services/generation_tasks.py` (prompt normalize, ref collect, storyboard execute, TTS, design refs)
- `server/services/reference_video_tasks.py` (unit prompt, constraints)
- `server/services/resume_executor.py`

### OmniCast (comparison only, not modified)
- `implementation/src/omnicast/storyboard/binding.py` (header)
- `implementation/src/omnicast/storyboard/refsheet.py` (header + VIEWS)

### ROUND 2 re-read (verbatim extract)
- `lib/prompt_builders_script.py:211-218,256-347,406-503` (drama constants + narration/drama builders)
- `lib/grid/prompt_builder.py` (entire file)
- `lib/prompt_builders_ad.py:34-110,118-128,178-345`
- `lib/prompt_builders_reference.py:21-276`
- `docs/research/REFS_SB_00_VERIFY.md` §2.1, §3.2 V3, §4.4

### Chưa đọc sâu (vòng sau nếu cần)
- Toàn bộ `agent_runtime_profile/.claude/skills/*` SKILL.md (logic đã được mirror trong prompt_builders + generation_tasks)
- Từng video backend provider file (ark/gemini/…)
- Frontend stores/components chi tiết
- 52 ADR files (đã bám qua CONTEXT + code comments ADR 0001/0006/0007/0010/0033/0034/0040/0041/0049)
- Compose FFmpeg skill scripts

---

*Report only under `docs/research/`. No other OmniCast files modified. `_refs/ArcReel` untouched. ROUND 2: V3 + VERIFY §4.4 verbatim.*
