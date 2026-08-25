# REFS_SB_06 — Pixelle-Video + MoneyPrinterTurbo + short-video-factory

> **Repos:** `_refs/Pixelle-Video`, `_refs/MoneyPrinterTurbo`, `_refs/short-video-factory`  
> **Định vị:** Ba engine “1 lệnh → short video hoàn chỉnh” cùng bài toán với OmniCast (script → media → render)  
> **License:**  
> - Pixelle-Video: **Apache-2.0** (`_refs/Pixelle-Video/LICENSE`) — học concept + có thể tham chiếu pattern (không copy nguyên file nếu không cần)  
> - MoneyPrinterTurbo: **MIT** (`_refs/MoneyPrinterTurbo/LICENSE`) — học + port pattern an toàn  
> - short-video-factory: **AGPL-3.0** (`_refs/short-video-factory/LICENSE`) — **chỉ học concept / thuật toán; CẤM chép code**  
> **Ngày nghiên cứu:** 2026-08-02  
> **Phương pháp:** đọc code thật trong `_refs/`, không suy từ README; so sánh chéo + map gap OmniCast

---

## 0. Tóm tắt điều hành (cho OmniCast)

| Trục | Pixelle-Video | MoneyPrinterTurbo | short-video-factory | OmniCast hiện tại | Hành động gợi ý |
|------|---------------|-------------------|---------------------|-------------------|-----------------|
| **Script→visual** | LLM gen **image/video prompt** 1:1 narration → gen AI (ComfyUI/API) | LLM gen **stock search terms** → Pexels/Pixabay/Coverr | **Không match** — random cut local MP4 | Writer/Critic + storyboard binding; render vẫn stock/AI rời | Học **match_script_order** (MPT) + **LLM image prompt 1:1** (Pixelle) |
| **Consistency** | Style prefix toàn video; **không** cast/ref sheet | Không (stock B-roll) | Không | Cast + RefRole fail-closed | Không học consistency từ 3 repo này |
| **Subtitle** | Full-line text trên HTML template / frame; duration = TTS | Edge cues→sentence SRT **hoặc** Whisper + Levenshtein correct | Edge WordBoundary → SRT (gap-based) | `subtitle_sync.py`: word-level Whisper **hoặc** edge words → ASS | OmniCast **đã mạnh hơn**; học aggregation sentence (MPT) nếu cần “calm captions” |
| **Batch** | `SimpleBatchManager`: multi-topic, shared config | `video_count` multi-output + stop_at stages | `autoBatch` loop desktop | Pipeline YAML + channels | Học stop_at (MPT) + autoBatch UX (SVF) |
| **Per-channel config** | 1 file `config.yaml` global | `config.toml` global | Pinia persist UI only | `channels/{id}.json` **giàu nhất** | Giữ OmniCast; bổ sung batch-topic list |
| **License** | Apache-2.0 | MIT | AGPL-3.0 | — | AGPL: re-implement only |

**Ai làm tốt hơn OmniCast (trên trục short-auto):**

- **MoneyPrinterTurbo:** pipeline stock-footage “kinh điển” hoàn chỉnh (terms → download → concat → subtitle correct → multi-provider LLM); `match_materials_to_script` + ordered download; social metadata prompts.
- **Pixelle-Video:** storyboard frame model + **LLM narration→image_prompt** + HTML template library + ComfyUI/RunningHub workflow parameterization + TTS-driven video duration; asset-based pipeline (user media + VLM assign).
- **short-video-factory:** desktop batch marketing (autoBatch), EdgeTTS word-boundary SRT, FFmpeg loudnorm voice/BGM — đơn giản, phù hợp 泛内容.

**OmniCast đã vượt:** multi-channel brand (`channels/*.json`), Writer/Critic, ComplianceChecker, storyboard cast/RefRole, subtitle ASS styling theo channel, YouTube Data API upload.

---

## 1. Tổng quan kiến trúc

### 1.1 Module map — Pixelle-Video

```
Pixelle-Video/
├── pixelle_video/
│   ├── pipelines/          # LinearVideoPipeline template method
│   │   ├── standard.py     # Topic/script → narrations → image prompts → frames
│   │   ├── asset_based.py  # User assets + LLM scene assign
│   │   ├── linear.py       # PipelineContext + lifecycle hooks
│   │   └── custom.py
│   ├── prompts/            # SSOT prompt templates (topic/content/image/video/title/style/asset)
│   ├── models/storyboard.py
│   ├── services/
│   │   ├── frame_processor.py   # TTS → media → HTML compose → segment
│   │   ├── media.py             # ComfyKit / API media
│   │   ├── tts_service.py
│   │   ├── video.py             # concat + BGM
│   │   └── api_services/        # DashScope, Kling, Seedance, Seedream, GPT image...
│   └── utils/content_generators.py
├── workflows/
│   ├── runninghub/*.json   # wrapper: {source, workflow_id}
│   └── selfhost/*.json     # full ComfyUI graph + $prompt.value!
├── templates/{1080x1920,1920x1080,1080x1080}/*.html
├── api/                    # FastAPI
└── web/                    # Streamlit + batch_manager
```

**Luồng end-to-end (StandardPipeline)** — `pixelle_video/pipelines/standard.py:59-73`:

```
topic | fixed script
  → generate narrations (LLM JSON) OR split script
  → generate title
  → generate image_prompts (LLM, EN) + style prefix
  → per frame: TTS → ComfyUI/API image|video → HTML compose (title+narration) → segment
  → concat + optional BGM
  → persist metadata/storyboard
```

### 1.2 Module map — MoneyPrinterTurbo

```
MoneyPrinterTurbo/
├── app/services/
│   ├── task.py       # Orchestrator: script→terms→audio→subtitle→materials→video
│   ├── llm.py        # Multi-provider LLM + script/terms/social prompts
│   ├── material.py   # Pexels / Pixabay / Coverr search+download
│   ├── voice.py      # Edge/Azure/Gemini/SiliconFlow/MiMo TTS + subtitle from SubMaker
│   ├── subtitle.py   # faster-whisper word_timestamps + Levenshtein correct
│   ├── video.py      # MoviePy combine + burn subtitle + BGM
│   └── upload_post.py
├── app/models/schema.py   # VideoParams
├── config.example.toml
└── webui/Main.py
```

**Luồng** — `app/services/task.py:268-366`:

```
video_subject (+ optional video_script)
  → LLM script (or use provided)
  → LLM search terms (EN keywords)
  → TTS (full script once) + duration
  → subtitle (edge SubMaker OR whisper+correct)
  → stock download until audio_duration covered
  → combine clips to audio length + generate final (subtitle burn, BGM)
  → optional cross-post TikTok/IG
```

**stop_at** cho partial pipeline: `"script" | "terms" | "audio" | "subtitle" | "materials" | "video"` (`task.py:268`).

### 1.3 Module map — short-video-factory

```
short-video-factory/
├── src/views/Home/
│   ├── index.vue                 # Orchestrate: text → TTS → segments → render
│   └── components/
│       ├── TextGenerate.vue     # OpenAI-compat streamText (user prompt only)
│       ├── VideoManage.vue       # Local MP4 folder + random trim segments
│       ├── TtsControl.vue
│       └── VideoRender.vue       # autoBatch + output config
├── electron/
│   ├── tts/index.ts              # EdgeTTS + optional SRT
│   ├── lib/edge-tts.ts           # WordBoundary → getCaptionSrtString
│   └── ffmpeg/index.ts           # filter_complex concat + subtitles + loudnorm
└── src/store/app.ts              # Pinia persist (llm, voice, renderConfig)
```

**Luồng** — `src/views/Home/index.vue:219-287`:

```
user prompt → LLM streamText → script text
  → EdgeTTS synthesize (withCaption → .srt)
  → random local MP4 segments totaling TTS duration
  → FFmpeg: trim/scale/pad/concat + burn subtitles + voice loudnorm + optional BGM
  → if autoBatch: clear text, loop
```

### 1.4 So sánh kiến trúc một dòng

| | Pixelle | MPT | SVF | OmniCast |
|--|---------|-----|-----|----------|
| Runtime | Python async + Streamlit/API | Python + FastAPI/Streamlit | Electron desktop | Python package + FastAPI + dashboard |
| Visual source | AI gen (Comfy/API) hoặc user asset | Stock API hoặc local | Local folder only | AI + stock + render pipeline |
| Storyboard | `StoryboardFrame[]` explicit | Implicit (terms list) | Implicit (random clips) | `storyboard/` module |
| Duration driver | **Per-frame TTS** then media | **Whole-script TTS** then clips fill | Whole TTS then clips fill | Shot/narration driven |

---

## 2. Data model storyboard

### 2.1 Pixelle — schema verbatim

`pixelle_video/models/storyboard.py:22-143`:

```python
@dataclass
class StoryboardConfig:
    media_width: int
    media_height: int
    task_id: Optional[str] = None
    n_storyboard: int = 5
    min_narration_words: int = 5
    max_narration_words: int = 20
    min_image_prompt_words: int = 30
    max_image_prompt_words: int = 60
    video_fps: int = 30
    tts_inference_mode: str = "local"  # "local" | "comfyui"
    voice_id: Optional[str] = None
    tts_workflow: Optional[str] = None
    tts_speed: Optional[float] = None
    ref_audio: Optional[str] = None
    media_workflow: Optional[str] = None
    api_video_params: Optional[Dict[str, Any]] = None
    frame_template: str = "1080x1920/default.html"
    template_params: Optional[Dict[str, Any]] = None

@dataclass
class StoryboardFrame:
    index: int
    narration: str
    image_prompt: str  # can be None for static templates
    audio_path: Optional[str] = None
    media_type: Optional[str] = None  # "image" | "video"
    image_path / video_path / composed_image_path / video_segment_path
    duration: float = 0.0

@dataclass
class Storyboard:
    title: str
    config: StoryboardConfig
    frames: List[StoryboardFrame]
    content_metadata: Optional[ContentMetadata] = None
    final_video_path / total_duration / created_at / completed_at
```

**Asset-based scenes** — `pipelines/asset_based.py:57-67`:

```python
class SceneScript(BaseModel):
    scene_number: int
    asset_path: str
    narrations: List[str]  # 1-5 sentences
    duration: int

class VideoScript(BaseModel):
    scenes: List[SceneScript]
```

**State:** frame “done” khi `video_segment_path is not None` (`storyboard.py:117-122`). Không state machine phức tạp; pipeline linear fail-raises.

### 2.2 MoneyPrinterTurbo — không storyboard object

`VideoParams` (`app/models/schema.py:58-112`) là config task:

| Field | Vai trò |
|-------|---------|
| `video_subject` | Chủ đề → LLM script |
| `video_script` | Override script |
| `video_terms` | Override keywords |
| `video_source` | pexels / pixabay / coverr / local |
| `match_materials_to_script` | Ordered terms + sequential concat |
| `video_clip_duration` | Max clip length (default 5s) |
| `video_count` | Số video output |
| `voice_*`, `bgm_*`, `subtitle_*`, font/stroke | Presentation |

Script persistence: `task_dir/script.json` = `{script, search_terms, params}` (`task.py:69-78`).

### 2.3 short-video-factory — không schema domain

State UI trong Pinia (`store/app.ts`):

- `prompt`, `llmConfig`
- `videoAssetsFolder`
- `voice`, `speed`, `language`
- `renderConfig` (size, path, bgmPath)
- `autoBatch`, `renderStatus` enum: `None | GenerateText | SynthesizedSpeech | SegmentVideo | Rendering | Completed | Failed`

Render payload: `{ videoFiles, timeRanges, audioFiles, outputSize, outputDuration, outputPath }` (`ffmpeg/types` + `index.vue:262-277`).

### 2.4 So với OmniCast

OmniCast storyboard: Entity cast, RefRole, continuity fail-closed — **mức narrative drama**.  
Ba repo này: **narration short-form / B-roll factory** — frame = “một câu nói + một hình”.  
Map: Pixelle `StoryboardFrame` ≈ OmniCast shot nhẹ (không character binding).

---

## 3. Cơ chế consistency (nhân vật / bối cảnh)

**Cả ba repo gần như không có character consistency.**

| Repo | Có gì | Không có |
|------|--------|----------|
| **Pixelle** | Global `prompt_prefix` style (stick-figure default); style conversion LLM; template visual identity | Ref sheet, IP-Adapter, seed lock per character, re-roll verify |
| **MPT** | Stock footage — “consistency” = brand font/subtitle only | Character |
| **SVF** | Local assets user-curated | Matching, style gen |

Pixelle **style presets** (`prompts/image_generation.py:26-44`):

```python
IMAGE_STYLE_PRESETS = {
    "stick_figure": {
        "description": "stick figure style sketch, black and white lines, pure white background, minimalist hand-drawn feel",
    },
    "minimal": {
        "description": "minimalist abstract art, geometric shapes, clean composition, modern design, soft pastel colors",
    },
    "concept": {
        "description": "conceptual visual metaphors, symbolic elements, thought-provoking imagery, artistic interpretation",
    },
}
```

Config default prefix (`config.example.yaml:65`):

```yaml
prompt_prefix: "Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style"
```

Apply: `build_image_prompt(base, prefix)` → `f"{prefix}, {prompt}"` (`utils/prompt_helper.py:20-49`).

**Kết luận cho OmniCast:** đừng học consistency từ đây; học **style suffix/prefix** đơn giản cho short-form abstract (finance explainers stick-figure style có thể là product mode).

---

## 4. PROMPT ENGINEERING — VERBATIM

> **ROUND-2 fix (V5):** mọi khối Pixelle dưới đây là **FULL string** từ source (`TOPIC_NARRATION_PROMPT` va cac hang so), không outline truncation.  
> Khối core cũng được lặp trong `## ROUND 2 — VERBATIM FULL` (VERIFY §4.6).  
> Lưu ý: chuỗi nguồn có thể chứa `...` literal (JSON example / social example) — đó là **nội dung source**, không phải truncation của report.

### 4.1 Pixelle-Video

#### 4.1.1 Topic → narrations — FULL VERBATIM

Nguồn: `_refs/Pixelle-Video/pixelle_video/prompts/topic_narration.py` — hằng `TOPIC_NARRATION_PROMPT` (lines 20–131).

```
# Role Definition
You are a professional content creation expert, skilled at expanding topics into engaging short video scripts, explaining viewpoints in an accessible way to help audiences understand complex concepts.
Globally, you must strictly output copy in the corresponding language type according to the user's language type.

# Core Task
The user will input a topic or theme. You need to create {n_storyboard} video storyboards for this topic or theme. Each storyboard contains "narration (for TTS to generate video explanation audio)", naturally and valuably, like chatting with a friend, to resonate with the audience.
- Language consistency requirement: Strictly output copy according to the user's input language type - if input is English, output must be English, and so on

# Input Topic
{topic}

# Output Requirements

## Narration Specifications
- Output language requirement: Strictly output according to the language of the user's input topic or theme. For example: if the user's input is in English, the output copy must be in English, same for Chinese.
- Purpose: For TTS to generate short video audio, explaining topics in an accessible way
- Word count limit: Strictly control to {min_words}~{max_words} words (minimum not less than {min_words} words)
- Ending format: Do not use punctuation at the end of each narration. If there are sentence breaks in the narration, Chinese punctuation (,。?!……:"") must be used to express tone and pauses. Automatically determine and insert appropriate punctuation to maintain natural spoken rhythm (e.g., "Right? Wrong." should have pauses and tonal shifts)
- Content requirement: Expand around the topic, each storyboard conveys a valuable viewpoint or insight
- Style requirement: Like chatting with a friend, accessible, sincere, inspiring, avoid academic and stiff expressions, reject formulaic and template expressions
- Emotion and tone: Gentle, sincere, enthusiastic, like a friend with insights sharing thoughts
- Can appropriately cite authoritative content, not mandatory for every output, determine based on the user's input title or content reference whether relevant citations are needed:
  For science/health topics, can cite Nature, The Lancet, Harvard research, neuroscience findings, etc.;
  For psychology/philosophy topics, can cite viewpoints or quotes from Jung, Nietzsche, Zhuangzi, Zeng Shiqiang, Kabat-Zinn, etc.;
  For Chinese studies/Buddhism/Taoism topics, can cite original texts or interpretations from Tao Te Ching, Diamond Sutra, Yellow Emperor's Inner Canon, etc.;
  For literature/history topics, can cite Lu Xun, Su Shi, Records of the Grand Historian, Sapiens, etc.;
  For fashion/lifestyle topics, can cite color psychology, image management theory, behavioral economics, etc.
  Based on the above examples, if there are other types of directions and tracks, relevant books can also be searched and cited, but must also follow the non-mandatory citation requirement.

  If there are citations, integrate them naturally, do not pile them up stiffly, do not fabricate sources.

## Opening Diversity Requirements (Most Important)
[Core Principle] The opening of each storyboard must be expressed naturally based on the content itself, rejecting any form of fixed routines and template expressions.

[Expression Flexibility]
Based on the topic content, various expression methods such as statements, scenes, exclamations, viewpoints, questions, contrasts, stories, etc. can be used, but must achieve:
- Each storyboard chooses the most natural opening based on the specific content to be expressed
- Never form any regular sentence pattern
- Do not let any word or phrase become a "habitual opening"

[Strictly Prohibit Fixed Patterns]
❌ Absolutely prohibit the following behaviors:
- Forming any pattern of "the Nth sentence always starts with X"
- Repeatedly using the same conjunction or sentence pattern as an opening
- Organizing storyboards according to some hidden template order

[Special Emphasis]
## Language Consistency Requirements (Strictly Enforce)
- Narration language must match the user's input video intent
- If video intent is in Chinese, narration must be in Chinese
- If video intent is in English, narration must be in English
- Unless the video intent explicitly specifies an output language, strictly follow the original language of the intent
- The opening of the first storyboard should be completely naturally chosen based on the topic content, without any fixed vocabulary tendency
- In the entire set of narrations, if any word (such as "sometimes", "actually", "have you ever") appears more than once as an opening, it is a failed creation
- Should be as natural and fluent as a real person speaking, not applying any sentence pattern template

## Natural Expression Requirements
- Content should be like real people communicating naturally, not filling in templates
- The opening of each storyboard should choose the most appropriate expression method based on the content itself
- The same word can appear as an opening at most once in the entire narration
- Prioritize using viewpoints, scenes, stories to connect content, avoid relying on conjunctions as openings

## Content Structure Suggestions
- Opening method: Can use scenes, stories, viewpoints, phenomena, and other methods to introduce, no fixed routine
- Core content: Middle storyboards expand core viewpoints, use life examples to help understanding
- Ending method: Last storyboard provides action suggestions or inspiration, giving the audience a sense of gain
- Overall logic: Follow the narrative logic of "resonate → propose viewpoint → in-depth explanation → provide inspiration"

## Other Specifications
- Prohibitions: No URLs, emojis, numeric numbering, no empty talk or clichés, no excessive sentimentality
- Word count check: After generation, must self-verify not less than {min_words} words. If insufficient, supplement with specific viewpoints or examples

## Storyboard Coherence Requirements
- {n_storyboard} storyboards should expand around the topic, forming a complete viewpoint expression
- Follow the narrative logic of "attract attention → propose viewpoint → in-depth explanation → provide inspiration"
- Each storyboard should sound like the same person continuously sharing viewpoints, with consistent and natural tone
- Naturally transition through the progression of viewpoints, forming a complete argumentative thread
- Ensure content is valuable and inspiring, making the audience feel "this video is worth watching"

# Output Format
Strictly output in the following JSON format, do not add any additional text explanations:


```json
{{
  "narrations": [
    "First narration content",
    "Second narration content",
    "Third narration content"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Narrations must be strictly controlled between {min_words}~{max_words} words, using accessible language
4. {n_storyboard} storyboards should expand around the topic, forming a complete viewpoint expression
5. Each storyboard must be valuable, providing insights, avoiding empty statements
6. Output format is {{"narrations": [narration array]}} JSON object

[Diversity Core Requirements - Must Strictly Execute]
7. The first narration should not use a fixed word as an opening. Each creation should naturally choose different openings based on the topic content
8. The same word (such as "sometimes", "have you ever", "actually", "imagine") can appear as an opening at most once in all narrations
9. Do not form any hidden sentence pattern rules. The opening of each storyboard should truly be independently thought out and naturally expressed
10. Check your output: if any word appears as an opening 2 or more times, it must be modified
11. Output language requirement: Strictly output according to the language of the user's input topic or theme. For example: if the user's input is in English, the output copy must be in English, same for Chinese.

Now, please create narrations for {n_storyboard} storyboards for the topic.
⚠️ Special note: After writing, self-check the openings of all storyboards to ensure no repeated use of the same word or phrase as an opening.
Only output JSON, no other content.

```

**Vì sao hiệu quả:** (1) JSON schema cứng → parse ổn; (2) anti-template opening giảm “AI smell”; (3) min/max words khớp TTS ngắn; (4) language lock + citation guidance có điều kiện.

#### 4.1.2 Content refine → narrations — FULL VERBATIM

Nguồn: `content_narration.py` — `CONTENT_NARRATION_PROMPT` (lines 20–77).

```
# Role Definition
Globally, you must strictly output copy in the corresponding language type according to the user's language type.
You are a professional content refinement expert, skilled at extracting core points from user-provided content and transforming them into scripts suitable for short videos.

# Core Task
The user will provide content (which may be long or short), and you need to extract narrations for {n_storyboard} video storyboards (for TTS to generate video audio).

# User-Provided Content
{content}

# Output Requirements

## Narration Specifications
- Language consistency requirement: Strictly output copy according to the user's input language type - if input is English, output must be English, and so on
- Purpose: For TTS to generate short video audio
- Word count limit: Strictly control to {min_words}~{max_words} words (minimum not less than {min_words} words)
- Ending format: Do not use punctuation at the end
- Refinement strategy:
  * If user content is long: Extract {n_storyboard} core points, remove redundant information
  * If user content is short: Appropriately expand while retaining core viewpoints, add examples or explanations
  * If user content is just right: Optimize expression to make it more suitable for voice narration
- Style requirement: Maintain the core viewpoint of user content, but express it in a more colloquial way suitable for TTS
- Opening suggestion: The first storyboard can use a question or scene introduction to attract audience attention
- Core content: Middle storyboards expand on the core points of user content
- Ending suggestion: The last storyboard provides a summary or inspiration
- Emotion and tone: Gentle, sincere, natural, like sharing viewpoints with a friend
- Prohibitions: No URLs, emojis, numeric numbering, no empty talk or clichés
- Word count check: After generation, must self-verify that each segment is not less than {min_words} words

## Storyboard Coherence Requirements
- {n_storyboard} storyboards should expand based on the core viewpoint of user content, forming a complete expression
- Maintain logical coherence and natural transitions
- Each storyboard should sound like the same person narrating, with consistent tone
- Ensure the refined content is faithful to the user's original meaning, but more suitable for short video presentation

# Output Format
Strictly output in the following JSON format, do not add any additional text explanations:

```json
{{
  "narrations": [
    "First {min_words}~{max_words} word narration",
    "Second {min_words}~{max_words} word narration",
    "Third {min_words}~{max_words} word narration"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Narrations must be strictly controlled between {min_words}~{max_words} words
4. Must output exactly {n_storyboard} storyboard narrations
5. Content must be faithful to the user's original meaning, but optimized for voice narration expression
6. Output format is {{"narrations": [narration array]}} JSON object

Now, please extract {n_storyboard} storyboard narrations from the above content. Only output JSON, no other content.

```

#### 4.1.3 Narration → image prompts — FULL VERBATIM (SCRIPT→VISUAL)

Nguồn: `image_generation.py` — `IMAGE_PROMPT_GENERATION_PROMPT` (lines 50–117).

```
# Role Definition
You are a professional visual creative designer, skilled at creating expressive and symbolic image prompts for video scripts, transforming abstract concepts into concrete visual scenes.

# Core Task
Based on the existing video script, create corresponding **English** image prompts for each storyboard's "narration content", ensuring visual scenes perfectly match the narrative content and enhance audience understanding and memory.

**Important: The input contains {narrations_count} narrations. You must generate one corresponding image prompt for each narration, totaling {narrations_count} image prompts.**

# Input Content
{narrations_json}

# Output Requirements

## Image Prompt Specifications
- Language: **Must use English** (for AI image generation models)
- Description structure: scene + character action + emotion + symbolic elements
- Description length: Ensure clear, complete, and creative descriptions (recommended 50-100 English words)

## Visual Creative Requirements
- Each image must accurately reflect the specific content and emotion of the corresponding narration
- Use symbolic techniques to visualize abstract concepts (e.g., use paths to represent life choices, chains to represent constraints, etc.)
- Scenes should express rich emotions and actions to enhance visual impact
- Highlight themes through composition and element arrangement, avoid overly literal representations

## Key English Vocabulary Reference
- Symbolic elements: symbolic elements
- Expression: expression / facial expression
- Action: action / gesture / movement
- Scene: scene / setting
- Atmosphere: atmosphere / mood

## Visual and Copy Coordination Principles
- Images should serve the copy, becoming a visual extension of the copy content
- Avoid visual elements unrelated to or contradicting the copy content
- Choose visual presentation methods that best enhance the persuasiveness of the copy
- Ensure the audience can quickly understand the core viewpoint of the copy through images

## Creative Guidance
1. **Phenomenon Description Copy**: Use intuitive scenes to represent social phenomena
2. **Cause Analysis Copy**: Use visual metaphors of cause-and-effect relationships to represent internal logic
3. **Impact Argumentation Copy**: Use consequence scenes or contrast techniques to represent the degree of impact
4. **In-depth Discussion Copy**: Use concretization of abstract concepts to represent deep thinking
5. **Conclusion Inspiration Copy**: Use open-ended scenes or guiding elements to represent inspiration

# Output Format
Strictly output in the following JSON format, **image prompts must be in English**:

```json
{{
  "image_prompts": [
    "[detailed English image prompt following the style requirements]",
    "[detailed English image prompt following the style requirements]"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Input is {{"narrations": [narration array]}} format, output is {{"image_prompts": [image prompt array]}} format
4. **The output image_prompts array must contain exactly {narrations_count} elements, corresponding one-to-one with the input narrations array**
5. **Image prompts must use English** (for AI image generation models)
6. Image prompts must accurately reflect the specific content and emotion of the corresponding narration
7. Each image must be creative and visually impactful, avoid being monotonous
8. Ensure visual scenes can enhance the persuasiveness of the copy and audience understanding

Now, please create {narrations_count} corresponding **English** image prompts for the above {narrations_count} narrations. Only output JSON, no other content.

```

**Style presets** (cùng file, lines 26–44) — FULL:

```python
IMAGE_STYLE_PRESETS = {
    "stick_figure": {
        "name": "Stick Figure Sketch",
        "description": "stick figure style sketch, black and white lines, pure white background, minimalist hand-drawn feel",
        "use_case": "General scenes, simple and intuitive"
    },
    
    "minimal": {
        "name": "Minimalist Abstract",
        "description": "minimalist abstract art, geometric shapes, clean composition, modern design, soft pastel colors",
        "use_case": "Modern, artistic feel"
    },
    
    "concept": {
        "name": "Conceptual Visual",
        "description": "conceptual visual metaphors, symbolic elements, thought-provoking imagery, artistic interpretation",
        "use_case": "Deep content, philosophical thinking"
    },
}
```

**Thuật toán matching:** không keyword search; **LLM 1:1 mapping** narration_i → image_prompt_i; batch 10, retry 3 (`content_generators.py:269-318`). Prefix style apply sau: `build_image_prompt(base, prefix)` → `"prefix, prompt"` (`prompt_helper.py:20-49`).

#### 4.1.4 Narration → video prompts — FULL VERBATIM

Nguồn: `video_generation.py` — `VIDEO_PROMPT_GENERATION_PROMPT` (lines 23–99).

```
# Role Definition
You are a professional video creative designer, skilled at creating dynamic and expressive video generation prompts for video scripts, transforming narrative content into vivid video scenes.

# Core Task
Based on the existing video script, create corresponding **English** video generation prompts for each storyboard's "narration content", ensuring video scenes perfectly match the narrative content and enhance audience understanding and memory through dynamic visuals.

**Important: The input contains {narrations_count} narrations. You must generate one corresponding video prompt for each narration, totaling {narrations_count} video prompts.**

# Input Content
{narrations_json}

# Output Requirements

## Video Prompt Specifications
- Language: **Must use English** (for AI video generation models)
- Description structure: scene + character action + camera movement + emotion + atmosphere
- Description length: Ensure clear, complete, and creative descriptions (recommended 50-100 English words)
- Dynamic elements: Emphasize actions, movements, changes, and other dynamic effects

## Visual Creative Requirements
- Each video must accurately reflect the specific content and emotion of the corresponding narration
- Highlight visual dynamics: character actions, object movements, camera movements, scene transitions, etc.
- Use symbolic techniques to visualize abstract concepts (e.g., use flowing water to represent the passage of time, rising stairs to represent progress, etc.)
- Scenes should express rich emotions and actions to enhance visual impact
- Enhance expressiveness through camera language (push, pull, pan, tilt) and editing rhythm

## Key English Vocabulary Reference
- Actions: moving, running, flowing, transforming, growing, falling
- Camera: camera pan, zoom in, zoom out, tracking shot, aerial view
- Transitions: transition, fade in, fade out, dissolve
- Atmosphere: dynamic, energetic, peaceful, dramatic, mysterious
- Lighting: lighting changes, shadows moving, sunlight streaming

## Video and Copy Coordination Principles
- Videos should serve the copy, becoming a visual extension of the copy content
- Avoid visual elements unrelated to or contradicting the copy content
- Choose dynamic presentation methods that best enhance the persuasiveness of the copy
- Ensure the audience can quickly understand the core viewpoint of the copy through video dynamics

## Creative Guidance
1. **Phenomenon Description Copy**: Use dynamic scenes to represent the occurrence process of social phenomena
2. **Cause Analysis Copy**: Use dynamic evolution of cause-and-effect relationships to represent internal logic
3. **Impact Argumentation Copy**: Use dynamic unfolding of consequence scenes or contrasts to represent the degree of impact
4. **In-depth Discussion Copy**: Use dynamic concretization of abstract concepts to represent deep thinking
5. **Conclusion Inspiration Copy**: Use open-ended dynamic scenes or guiding movements to represent inspiration

## Video-Specific Considerations
- Emphasize dynamics: Each video should include obvious actions or movements
- Camera language: Appropriately use camera techniques such as push, pull, pan, tilt to enhance expressiveness
- Duration consideration: Videos should be a coherent dynamic process, not static images
- Fluidity: Pay attention to the fluidity and naturalness of actions

# Output Format
Strictly output in the following JSON format, **video prompts must be in English**:

```json
{{
  "video_prompts": [
    "[detailed English video prompt with dynamic elements and camera movements]",
    "[detailed English video prompt with dynamic elements and camera movements]"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Input is {{"narrations": [narration array]}} format, output is {{"video_prompts": [video prompt array]}} format
4. **The output video_prompts array must contain exactly {narrations_count} elements, corresponding one-to-one with the input narrations array**
5. **Video prompts must use English** (for AI video generation models)
6. Video prompts must accurately reflect the specific content and emotion of the corresponding narration
7. Each video must emphasize dynamics and sense of movement, avoid static descriptions
8. Appropriately use camera language to enhance expressiveness
9. Ensure video scenes can enhance the persuasiveness of the copy and audience understanding

Now, please create {narrations_count} corresponding **English** video prompts for the above {narrations_count} narrations. Only output JSON, no other content.

```

#### 4.1.5 Title — FULL VERBATIM

Nguồn: `title_generation.py` — `TITLE_GENERATION_PROMPT` (lines 20–64).

```
Please generate a short, attractive title for the following content.

Content:
{content}

Requirements:
1. **Language Consistency (CRITICAL)**: The title MUST be in the same language as the input content
   - If the input content is in English, the title MUST be in English
   - If the input content is in Chinese, the title MUST be in Chinese
   - Strictly follow the language of the input content

2. **Character Limit (CRITICAL)**: The title MUST NOT exceed {max_length} characters
   - Count every character including spaces
   - The title must be complete and meaningful within this limit
   - Do NOT generate a title that would need to be cut off

3. **Core Message (CRITICAL)**: The title MUST capture the MAIN POINT of the content
   - Identify the central theme or key message
   - Don't focus on just one aspect if the content has multiple important points
   - Ensure the title accurately represents what the content is about

4. **No Punctuation at End**: Do NOT include any punctuation marks at the end of the title
   - No period (.), comma (,), exclamation mark (!), question mark (?), etc.
   - The title should end with a word or number, not punctuation

5. **Completeness**: Ensure the title is a complete, meaningful phrase
   - Do not cut off in the middle of a word or number
   - Do not create incomplete phrases like "Rise Early for" or "How to Make"
   - Use abbreviations or shorter words if needed to fit the limit
   
6. **Abbreviation Examples** (use when needed to fit character limit):
   - For English:
     * "10,000" → "10K"
     * "per month" → "monthly" or "a month"
     * "early to bed and early to rise" → "Sleep Early" or "Early Habits"
     * "makes you healthy" → "for Health" or "Stay Healthy"
   - For Chinese:
     * "10,000元" → "万元" or "1万"
     * "每个月" → "月入" or "月收"

7. Accurately summarize the core content
8. Attractive and engaging, suitable as a video title
9. Output only the title text, no quotes, no explanations

Title:
```

#### 4.1.6 Style conversion — FULL VERBATIM

Nguồn: `style_conversion.py` — `STYLE_CONVERSION_PROMPT` (lines 20–32).

```
Convert this style description into a detailed image generation prompt for Stable Diffusion/FLUX:

Style Description: {description}

Requirements:
- Focus on visual elements, colors, lighting, mood, atmosphere
- Be specific and detailed
- Use professional photography/art terminology
- Output ONLY the prompt in English (no explanations)
- Keep it under 100 words
- Use comma-separated descriptive phrases

Image Prompt:
```

#### 4.1.7 Asset-based script — FULL VERBATIM

Nguồn: `asset_script_generation.py` — `ASSET_SCRIPT_GENERATION_PROMPT` (lines 20–51).  
Runtime inject: `title_section = f"- Video Title: {title}\n" if title else ""`;  
`title_instruction = f"6. Narration content should be consistent with the video title: {title}\n" if title else ""`.

```
You are a professional video script creator. Based on the user's video intent and available assets, generate a {duration}-second video script. Before doing so, you need to detect the user's input language - if it's English, then all copy must be in English. Strictly follow the user's input language type as the standard, ensuring consistent and corresponding copy!

## Requirements
{title_section}- Video Intent: {intent}
- Target Duration: {duration} seconds

## Available Assets (use exact paths in output)
{assets_text}

## Creation Guidelines
1. Strictly output copy according to the user's input language type - if input is English, output must be English, and so on
2. Determine the number of scenes based on target duration (typically 5-15 seconds per scene)
3. Assign one asset from available assets to each scene
4. Each scene can contain 1-3 narration sentences
5. Try to use all available assets, but assets can be reused if needed
6. Total duration of all scenes should approximately equal {duration} seconds
{title_instruction}

## Language Consistency Requirements (Strictly Enforce)
- Narration language must match the user's input video intent
- If video intent is in Chinese, narration must be in Chinese
- If video intent is in English, narration must be in English
- Unless the video intent explicitly specifies an output language, strictly follow the original language of the intent

## Output Requirements
Provide for each scene:
- scene_number: Scene number (starting from 1)
- asset_path: Exact path selected from available assets list
- narrations: Array containing 1-3 narration sentences
- duration: Estimated duration (seconds)

Now please begin generating the video script:
```

**Matching asset:** LLM chọn `asset_path` exact từ list (sau khi VLM/analyse_image mô tả assets) — không embedding search.

Config default image prefix (`config.example.yaml:65`):

```yaml
prompt_prefix: "Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style"
```

---

### 4.2 MoneyPrinterTurbo

#### 4.2.1 Script system prompt (DEFAULT) — FULL VERBATIM

Nguồn: `app/services/llm.py` — `DEFAULT_SCRIPT_SYSTEM_PROMPT` (lines 23–38), sau `.strip()`.

```
# Role: Video Script Generator

## Goals:
Generate a script for a video, depending on the subject of the video.

## Constrains:
1. the script is to be returned as a string with the specified number of paragraphs.
2. do not under any circumstance reference this prompt in your response.
3. get straight to the point, don't start with unnecessary things like, "welcome to this video".
4. you must not include any type of markdown or formatting in the script, never use a title.
5. only return the raw content of the script.
6. do not include "voiceover", "narrator" or similar indicators of what should be spoken at the beginning of each paragraph or line.
7. you must not mention the prompt, or anything about the script itself. also, never talk about the amount of paragraphs or lines. just write the script.
8. respond in the same language as the video subject.
```

Runtime append trong `build_script_prompt` (`llm.py:612-626`) — FULL logic:

```python
prompt = custom_system_prompt or DEFAULT_SCRIPT_SYSTEM_PROMPT
prompt += f"""

# Initialization:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
""".rstrip()
if language:
    prompt += f"\n- language: {language}"
if video_script_prompt:
    prompt += f"""

# Additional User Requirements:
{video_script_prompt}
""".rstrip()
```

Limits: `video_script_prompt` max 2000 chars; `custom_system_prompt` max 8000 (`llm.py:18-19`, schema Field).

#### 4.2.2 Search terms — FULL template + cả hai nhánh goal

Nguồn: `generate_terms` (`llm.py:721-783`). Prompt là f-string; dưới đây là **toàn bộ skeleton** + **chuỗi goal/ordering/output_example** đúng source.

**Skeleton (FULL, mọi placeholder giữ nguyên):**

```
# Role: Video Search Terms Generator

## Goals:
{goal}

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. reply with english search terms only.
{ordering_rule}

## Output Example:
{output_example}

## Context:
### Video Subject
{video_subject}

### Video Script
{video_script}

Please note that you must use English for generating video search terms; Chinese is not accepted.
```

**Khi `match_script_order=False`:**

- `goal` = `Generate {amount} search terms for stock videos, depending on the subject of a video.`
- `ordering_rule` = `""` (chuỗi rỗng — dòng 6 không xuất hiện)
- `output_example` = `["search term 1", "search term 2", "search term 3","search term 4", "search term 5"]`

**Khi `match_script_order=True`:**

- `goal` = `Generate {amount} chronological stock-video search terms that follow the order of topics in the video script.`
- `ordering_rule` = `6. keep the terms in the same order as the script narration; earlier terms must describe earlier visual moments.`
- `output_example` = `json.dumps(example_terms[:amount])` với `example_terms = ["opening visual topic", "script visual topic 2", (cac index den amount), "final visual topic"]`.

**Thuật toán sau prompt** (`material.py:304-470`):

1. Mỗi term → API search (Pexels orientation / Pixabay / Coverr).
2. Default: gộp candidates, random shuffle, download until `total_duration > audio_duration`.
3. `match_script_order=True`: **round-robin theo term groups** — term1[0], term2[0], rồi term1[1] v.v. tránh keyword đầu “ăn hết” timeline.

Amount: `8 if match_materials_to_script else 5` (`task.py:46-49`).

#### 4.2.3 Social metadata — FULL template + language branches

Nguồn: `build_social_metadata_prompt` (`llm.py:965-988`) + `_social_language_instruction` (`llm.py:897-905`).

**Prompt skeleton (FULL):**

```
# Role: Short-Video Social Media Copywriter

## Goal
Write engaging publishing metadata for a short video that will be posted on {label}.

## Constraints
1. Respond ONLY with a single valid minified JSON object. No markdown, no code fences, no commentary.
2. The JSON must contain exactly these keys: "title", "caption", "hashtags".
3. "title": a catchy hook, at most {spec['title_max']} characters.
4. "caption": an engaging description that ends with a call to action, at most {spec['caption_max']} characters. Do not put hashtags inside the caption.
5. "hashtags": a JSON array of exactly {spec['hashtag_count']} strings. Each must start with "#", contain no spaces, and be relevant to the topic and to {label}.
6. {language_instruction}

## Output Example
{{"title":"...","caption":"...","hashtags":["#example","#video"]}}

## Context
### Video Subject
{video_subject}

### Video Script
{video_script}
```

**`language_instruction` khi language auto:**

```
Use the same language as the video subject and script. If the subject and script use different languages, prefer the script language.
```

**Khi language chỉ định:**

```
Write "title" and "caption" in this language: {language}.
```

**Platforms** (`llm.py:835-840`) FULL:

```python
SOCIAL_PLATFORMS = {
    "tiktok": {"title_max": 100, "caption_max": 2200, "hashtag_count": 5},
    "youtube_shorts": {"title_max": 100, "caption_max": 5000, "hashtag_count": 3},
    "instagram_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 8},
    "facebook_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 5},
}
```

**Không có image gen prompt / negative** trong MPT — visual = stock.

---

### 4.3 short-video-factory

**Không có system/domain prompt template trong `src/`.**  
Grep xác nhận: xem `## ROUND 2` §R2.7.

`TextGenerate.vue:146-155` — FULL call site:

```typescript
    const result = streamText({
      model: openai.chat(appStore.llmConfig.modelName),
      // system: ``,
      // 未来也许会设置一个系统提示词，但现在必须注释掉，因为部分接口提交空 system prompt 会报错
      prompt: appStore.prompt,
      onError: (error) => {
        throw error
      },
      abortSignal: abortController.value.signal,
    })
```

Connectivity test only (`TextGenerate.vue:226-229`):

```typescript
    const result = await generateText({
      model: openai.chat(config.value.modelName),
      prompt: 'Hello',
    })
```

Toàn bộ “prompt engineering” = **user paste** vào `appStore.prompt`. Không title/hook/script/image/negative domain template.

---

### 4.4 Negative prompts

| Repo | Negative |
|------|----------|
| Pixelle | Optional `negative_prompt` param → ComfyKit (`media.py:243-244`); Flux selfhost dùng `ConditioningZeroOut` trên positive (không text negative điển hình) — `workflows/selfhost/image_flux.json:48-58` |
| MPT | N/A |
| SVF | N/A |

---

## 5. Vòng QA / retry / repair

### Pixelle

| Layer | Behavior | Source |
|-------|----------|--------|
| Image prompt batches | `max_retries=3` per batch | `content_generators.py:275-308` |
| Narration count | Too few → raise; too many → truncate | `content_generators.py:142-148` |
| Title over limit | Word-boundary truncate | `content_generators.py:76-89` |
| Frame fail | Log + re-raise (no skip frame) | `frame_processor.py:147-149` |
| Batch topics | Fail one topic → record error, **continue** | `batch_manager.py:130-147` |
| Persistence fail | Log, don't fail video | `standard.py:516-518` |

**Không có:** visual QA, lip-sync check, re-gen on bad image.

### MoneyPrinterTurbo

| Layer | Behavior |
|-------|----------|
| LLM script/terms | `_max_retries = 5` (`llm.py:13`) |
| Terms JSON parse | Strip code fence + regex `\[.*]` recovery (`llm.py:705-820`) |
| Subtitle edge fail | Fallback whisper (`task.py:150-162`) |
| Whisper ASR vs script | Levenshtein merge/correct, threshold 0.8 (`subtitle.py:200-290`) |
| Material empty | Task FAILED |
| Invalid download | Skip file, continue |
| Thinking models | Strip `<think>...</think>` (`llm.py:56-57`) |

**Subtitle correct algorithm** (quan trọng) — `subtitle.py:200-261`:

1. Split script by punctuation → `script_lines`.
2. Walk subtitle items; if mismatch, greedily merge next subs while similarity increases.
3. If `similarity(script_line, combined) > 0.8` OR still mismatch: **replace text with script_line**, keep timing.
4. Extra script lines get leftover timings or zero timing.

### short-video-factory

| Layer | Behavior |
|-------|----------|
| TTS duration invalid | Throw, abort render |
| Asset duration fail | Skip asset, continue loop |
| Insufficient total duration | Throw after maxAttempts |
| autoBatch | On success → clear + recurse; on fail stop |
| LLM | AbortController cancel |

**Không có:** script-to-visual QA, subtitle correct to script.

---

## 6. Tích hợp video-gen

### Pixelle

| Path | Chi tiết |
|------|----------|
| Image Comfy | Flux, Qwen, SD3.5, SDXL, Z-image; selfhost full graph / RunningHub workflow_id |
| Video Comfy | Wan2.1 FusionX, Wan2.2, Qwen-Wan, LTX2 i2v, digital human |
| Direct API | `api/` prefix → DashScope, Kling, Seedance, Seedream, GPT image |
| Duration sync | **TTS first** → `media_params["duration"] = frame.duration` (`frame_processor.py:235-239`) |
| First frame for API video | Optional `first_frame_workflow` gen image then i2v (`frame_processor.py:295-316`) |
| Driving audio | `use_narration_audio_as_driving_audio` → digital human |
| Fallback | Config default_workflow required; no multi-provider auto-fallback chain like ArcReel |

### MoneyPrinterTurbo

| Path | Chi tiết |
|------|----------|
| Video gen | **Không AI video** — stock cut/concat MoviePy |
| Transitions | FadeIn/Out, SlideIn/Out, Shuffle (`VideoTransitionMode`) |
| Effects | `video_effects.py` |
| Multi output | `video_count` with random concat for diversity |

### short-video-factory

| Path | Chi tiết |
|------|----------|
| Video gen | Local MP4 only |
| FFmpeg | trim → scale/pad → concat → subtitles → loudnorm amix BGM |
| Codecs | libx264 CRF 23, aac 128k, fps 30 |

### OmniCast map

- Pixelle duration-from-TTS + first_frame_workflow ≈ pattern cho `veo_pipeline` / i2v.
- MPT stock path ≈ OmniCast footage channels (`channel_style: "footage"`).

---

## 7. Pacing / timing

### 7.1 Shot duration

| Repo | Rule |
|------|------|
| **Pixelle** | `duration = probe(TTS audio)` per frame; video workflow target = that duration; image segment = still for audio length |
| **MPT** | Full script TTS once; clips ≤ `video_clip_duration` (default 5s) fill `audio_duration`; last clip trimmed |
| **SVF** | Segment random 2–15s; fill TTS duration; last segment adjusted (`VideoManage.vue:210-288`) |

### 7.2 Subtitle / TTS alignment (câu hỏi riêng)

#### Pixelle

- **Không** word-level SRT burn.
- Narration text vẽ **full line** trên HTML template (`frame_processor.py:372-378`: `text=frame.narration`).
- Timing = cả segment audio; user đọc full caption suốt shot.
- Ưu điểm: đơn giản, không ASR drift. Nhược: không karaoke, line dài.

#### MoneyPrinterTurbo — 2 provider

**A. Edge SubMaker (default `subtitle_provider=edge`)** — `voice.py:1368-1391`, `_build_subtitle_items_from_edge_cues:1267-1318`:

1. Edge TTS 7.x `cues` (word/phrase level).
2. Aggregate cues until text matches next `script_lines` (punctuation split).
3. Start = first cue start, end = last cue end.
4. Lý do: Chinese word-level SRT “tien / la / mot / loai” khó đọc.

**B. Whisper fallback** — `subtitle.py:21-142`:

```python
segments, info = model.transcribe(
    audio_file,
    beam_size=5,
    word_timestamps=True,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
)
# break segment on punctuation in word stream
```

Rồi `correct()` merge/replace bằng script gốc.

#### short-video-factory

Edge `WordBoundary` list → `getCaptionSrtString()` (`edge-tts.ts:361-408`):

- Gộp words thành sentence cho đến **voice gap > 100ms** (100 * 10^4 ticks).
- CJK compact (no space) join; Latin space join.
- Burn via FFmpeg `subtitles=` filter.

#### OmniCast `subtitle_sync.py` (so sánh)

| Feature | OmniCast | MPT | SVF | Pixelle |
|---------|----------|-----|-----|---------|
| Primary | faster-whisper `word_timestamps` **hoặc** exact edge words | Edge cues→sentence OR whisper+correct | Edge WordBoundary gap | HTML full line |
| Chunking | Smart: punct / 5–7 words / avoid split mid-number `$172,000` | Script punctuation match | Voice gap 100ms | N/A (full shot) |
| Format | ASS (style/preset/channel_meta) | SRT → MoviePy burn | SRT FFmpeg | HTML CSS |
| Gap fill | `fill_gaps(max_gap=1.0)` clear on pause | N/A | N/A | N/A |
| Script ground truth | Prefer TTS words path | `correct()` forces script text | No (ASR of TTS only) | Narration text = script |

**Verdict:** OmniCast `subtitle_sync` **đã vượt** cả ba về styling + number-safe chunking + dual path (TTS words / whisper). MPT đáng học: **force script text** khi ASR lệch (Levenshtein). Pixelle đáng học cho static-card modes: full-line overlay không cần word sync.

---

## 8. Chi tiết nhỏ đáng học

### 8.1 Pixelle

1. **Template naming convention:** `static_*` / `image_*` / `video_*` → skip/gen pipeline (`standard.py:163-169`, `config.example.yaml:82-85`).
2. **HTML templates** với meta `template:media-width/height` + design system (PingFang, card layouts) — gallery nhiều style life insights / neon / book.
3. **TTS-driven video duration** comment tường minh (`frame_processor.py:18-20`).
4. **RunningHub parallel** semaphore `runninghub_concurrent_limit` (`standard.py:309-366`).
5. **Comfy param injection:** node title `$prompt.value!`, `$width.value` — ComfyKit maps dict keys → nodes (`image_flux.json:138-144`).
6. **Static template** = zero Comfy cost path cho pure typography shorts.
7. **Task isolation** dir per `task_id`.

### 8.2 MoneyPrinterTurbo

1. **stop_at** progressive pipeline — debug/API partial.
2. **match_materials_to_script** end-to-end: ordered terms + ordered download + sequential concat (`task.py:42-50`, `material.py:386-470`).
3. **Unique source prioritize** — giảm lặp cùng clip (`video.py:83-120`).
4. **API key rotation** thread-safe counter (`material.py:49-52`).
5. **TLS verify default on** cho stock download.
6. **g4f opt-in disabled** security posture.
7. **no-voice mode** duration estimate CJK/EN (`voice.py:214-248`).
8. **Material cache** MD5 URL (`material.py:251-259`).
9. **video_count** A/B visual diversity.

### 8.3 short-video-factory

1. **autoBatch** chip UX + recursive render (`index.vue:283-287`).
2. **loudnorm** voice I=-16, BGM I=-25 (`ffmpeg/index.ts:102-115`).
3. **Random BGM** from folder each run.
4. **Desktop-first** offline assets — phù hợp agency marketing batch.
5. **Error toast** copyable detail.

### 8.4 Config per-channel (câu hỏi riêng)

| Aspect | OmniCast `channels/{id}.json` | Pixelle | MPT | SVF |
|--------|------------------------------|---------|-----|-----|
| Brand voice / niche / audience | ✅ rich | ❌ | ❌ | ❌ |
| voice_profile + fallback chain | ✅ | voice_id single | voice_name | Edge voice pick |
| Visual style / channel_style | ✅ | template + prefix | aspect/font | output size only |
| Destinations / schedule | ✅ | ❌ | upload_post optional | ❌ |
| Multi-channel SSOT | ✅ files | 1 config.yaml | 1 config.toml | UI persist |
| Batch multi-topic | pipeline | SimpleBatchManager topics[] | video_count same subject | autoBatch same prompt |

**Verdict:** OmniCast channel config **vẫn hay hơn**. Nên **bổ sung** (không thay):

- `batch_topics: string[]` hoặc vault table topics per channel.
- `match_materials_to_script: bool` + `stock_providers`.
- `visual_mode: "ai_image" | "ai_video" | "stock" | "local_assets" | "static_template"`.
- `prompt_prefix` / `image_style_preset` kiểu Pixelle.
- `custom_system_prompt` / `video_script_prompt` kiểu MPT.

---

## 9. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện | Gap OmniCast | File đích gợi ý | Impact | Effort |
|---|-----------|--------------|-----------------|--------|--------|
| 1 | LLM narration→image_prompt 1:1 (EN, symbolic) | Storyboard image prompts chưa chuẩn hóa short-form | `storyboard/` + Writer visual step | High (visual relevance) | M |
| 2 | Style prefix global + style conversion LLM | Visual brand only in channel JSON loosely | `channels/*.json` + image provider | Med | S |
| 3 | MPT `generate_terms` + ordered stock match | Footage mode matching mơ hồ | `media/` stock service mới hoặc material matcher | High for footage channels | M |
| 4 | `match_materials_to_script` round-robin download | Timeline “sai hình sớm” | stock downloader | High | S–M |
| 5 | Subtitle `correct()` force script text | Whisper path có thể lệch wording | `subtitle_sync.py` | Med | S |
| 6 | Edge cues → sentence aggregate (MPT) | Có edge words path; có thể thêm sentence mode | `subtitle_sync.py` | Low–Med | S |
| 7 | HTML template library (static/image/video) | Overlay chủ yếu FFmpeg/ASS | `render_real_video` / template dir | Med (style variety) | L |
| 8 | TTS-first duration for i2v/API video | Veo duration sync | `media/veo_pipeline.py` | High | M |
| 9 | `stop_at` partial pipeline | Debug stages khó | `pipeline/` runner | Med DX | S |
| 10 | SimpleBatchManager multi-topic shared config | Batch multi-video per channel | vault + API batch endpoint | High ops | M |
| 11 | autoBatch UX (SVF) | Continuous factory mode | dashboard | Med | S |
| 12 | loudnorm voice/BGM levels | BGM mix ad-hoc | FFmpeg compose | Med audio | S |
| 13 | Social metadata JSON per platform | Upload metadata partial | upload module | Med | S |
| 14 | custom_system_prompt + video_script_prompt hooks | Writer rigid | agents Writer | Med | S |
| 15 | Asset-based: VLM describe + LLM assign path | User asset marketing videos | new pipeline mode | Med | L |
| 16 | Static template zero-gen path | Always heavy media | template mode in render | Med cost | M |
| 17 | RunningHub concurrent semaphore pattern | Parallel gen limits | media queue | Med | S |
| 18 | Pixelle Comfy `$param.value!` template | OmniCast providers rời | optional Comfy provider | Low (unless selfhost) | L |

**Ưu tiên top 5 cho OmniCast short path:** **1, 3, 4, 8, 10**.

---

## 10. KHÔNG nên học + LICENSE

### Anti-patterns

| Pattern | Repo | Lý do tránh |
|---------|------|-------------|
| Random B-roll không semantic match | SVF (default), MPT (default random) | “Nói A hiện B” — trừ comedy/aesthetic |
| Full-script TTS single blob + generic clips | MPT | Khó shot-level control; OmniCast shot model tốt hơn |
| Empty system prompt + user-only | SVF | Output quality phụ thuộc user 100% |
| No character consistency khi gen face | Pixelle | Stick-figure OK; realistic face sẽ drift |
| AGPL desktop copy | SVF | License trap |
| Hardcoded Bing Edge TTS client token in repo | SVF `edge-tts.ts:8` | Security/ToS fragility |
| Frame fail = whole job die without partial resume | Pixelle | Cần checkpoint |
| Stock dependency + geo blocks | MPT | China VPN note — ops pain |
| Levenshtein correct always overwrite with script even low similarity | MPT `correct` still writes script_line | Có thể timing sai nếu ASR segment wrong |

### LICENSE summary

| Repo | License | Port code? |
|------|---------|------------|
| Pixelle-Video | Apache-2.0 | Có thể tham chiếu/port có attribution |
| MoneyPrinterTurbo | MIT | Có thể port pattern/code có attribution |
| short-video-factory | **AGPL-3.0** | **CẤM chép code** — chỉ concept (autoBatch, loudnorm targets, random segment algo re-implement) |

---

## 11. Câu hỏi riêng — trả lời tập trung

### 11.1 Script → visual matching

| Repo | Quyết định “câu này hiện gì” | Prompt / thuật toán |
|------|------------------------------|---------------------|
| **Pixelle** | LLM image/video prompt EN per narration; prefix style; Comfy/API gen | §4.1.3 + `build_image_prompt(prefix, p)` |
| **MPT** | LLM EN stock keywords (5–8); search API; optional ordered RR download | §4.2.2 + `material.download_videos` |
| **SVF** | **Không** — random local clips 2–15s fill audio | `VideoManage.getVideoSegments` |

### 11.2 Pixelle ComfyUI workflows — có đáng port?

**Danh sách chính** (`workflows/`):

| Key | Role |
|-----|------|
| `image_flux.json` / `image_flux2` | Default image |
| `image_qwen`, `image_sd3.5`, `image_sdxl`, `image_Z-image`, `image_qwen_chinese_cartoon` | Alt image models |
| `video_wan2.1_fusionx`, `video_wan2.2`, `video_qwen_wan2.2`, `i2v_LTX2` | Video |
| `tts_edge`, `tts_index2`, `tts_spark` | TTS |
| `analyse_image`, `analyse_video`, `video_understanding` | Asset VLM |
| `digital_*`, `af_scail` | Digital human |

**Parameterization:**

- Config: `comfyui.image.default_workflow`, `prompt_prefix`, width/height from template.
- Runtime dict: `{prompt, width, height, duration, negative_prompt, steps, seed, cfg, sampler, ...}` → ComfyKit (`media.py:232-255`).
- Selfhost graph nodes title `$prompt.value!` bind params.
- RunningHub: thin wrapper `{"source":"runninghub","workflow_id":"..."}` only.

**Port sang OmniCast provider model?**

- **Nên học concept:** (1) named workflow registry `source/name.json`; (2) prompt_prefix; (3) duration param for video; (4) template_type gates media.
- **Không cần port nguyên Comfy graph** trừ khi team chạy selfhost Flux/Wan. OmniCast đã có Gemini/Veo/Kokoro — map **logical** workflow slots (`image_default`, `video_i2v`, `tts_edge`) chứ không JSON Comfy.
- **Template HTML library** đáng port ý tưởng (static explainers) hơn workflow Flux.

### 11.3 Subtitle/timing vs OmniCast

Xem §7.2. Tóm tắt: OmniCast `subtitle_sync` word-level + ASS + channel style **đã lead**; bổ sung MPT **script-correct** và optional **sentence-aggregate** mode.

### 11.4 Batch + per-channel config

- Pixelle batch: topics list + shared config + title_prefix — tốt cho factory.
- MPT: video_count same script different material shuffle — A/B visual.
- SVF: autoBatch continuous same prompt — marketing spam-friendly.
- OmniCast channel JSON **vẫn SSOT brand tốt nhất**; thiếu multi-topic batch runner + visual_mode flags.

### 11.5 Prompt inventory

Đã chép verbatim các template quan trọng ở §4. Danh mục đầy đủ:

| Template | File |
|----------|------|
| Topic narration | `Pixelle .../prompts/topic_narration.py` |
| Content narration | `.../content_narration.py` |
| Image prompts | `.../image_generation.py` |
| Video prompts | `.../video_generation.py` |
| Title | `.../title_generation.py` |
| Style conversion | `.../style_conversion.py` |
| Asset script | `.../asset_script_generation.py` |
| Default image prefix | `config.example.yaml` + presets |
| Script system | MPT `llm.py` DEFAULT_SCRIPT_SYSTEM_PROMPT |
| Terms generator | MPT `generate_terms` prompt |
| Social metadata | MPT `build_social_metadata_prompt` |
| SVF | User prompt only (no template) |

---

## 12. So sánh chéo 3 repo (matrix)

| Dimension | Pixelle-Video | MoneyPrinterTurbo | short-video-factory |
|-----------|---------------|-------------------|---------------------|
| Target use | AI short explainers + marketing asset | Stock B-roll shorts viral | Local-asset marketing batch |
| Language | Python | Python | TypeScript/Electron |
| LLM role | Narration + image/video prompts + title | Script + terms + social | Script only (user prompt) |
| Visual | Gen AI / user asset | Stock API | Local random |
| Subtitle | Full-frame HTML text | Edge sentence / Whisper+correct | Edge word→SRT |
| Batch | Multi-topic shared style | Multi-count same subject | autoBatch loop |
| Extensibility | Comfy workflows + API providers | Many LLM/TTS providers | OpenAI-compat + Edge only |
| Closest OmniCast mode | AI image explainer shorts | Footage finance shorts | Local B-roll batch ops |

---

## 13. Đã đọc (file index) — cập nhật ROUND 2

### Pixelle-Video
- `pixelle_video/pipelines/standard.py`, `linear.py`, `asset_based.py`
- `pixelle_video/models/storyboard.py`
- `pixelle_video/prompts/topic_narration.py` — **FULL string ROUND 2**
- `pixelle_video/prompts/content_narration.py` — **FULL string ROUND 2**
- `pixelle_video/prompts/image_generation.py` — **FULL string ROUND 2**
- `pixelle_video/prompts/video_generation.py` — **FULL string ROUND 2**
- `pixelle_video/prompts/title_generation.py` — FULL
- `pixelle_video/prompts/style_conversion.py` — FULL
- `pixelle_video/prompts/asset_script_generation.py` — FULL
- `pixelle_video/utils/content_generators.py`, `prompt_helper.py`, `workflow_util.py`
- `pixelle_video/services/frame_processor.py`, `media.py`, `comfy_base_service.py`
- `web/utils/batch_manager.py`
- `config.example.yaml`
- `workflows/runninghub/image_flux.json`, `workflows/selfhost/image_flux.json`
- `templates/1080x1920/image_default.html`
- `docs/en/development/architecture.md`
- `LICENSE`, `README.md` (skim)

### MoneyPrinterTurbo
- `app/services/task.py`, `llm.py` (DEFAULT_SCRIPT + **generate_terms FULL** + **social metadata FULL**), `material.py`, `subtitle.py`, `voice.py`, `video.py` (partial)
- `app/models/schema.py`
- `config.example.toml`
- `LICENSE`

### short-video-factory
- `src/views/Home/index.vue`, `components/TextGenerate.vue`, `VideoManage.vue`, `VideoRender.vue`, `TtsControl.vue`
- `src/store/app.ts`, `src/App.vue`, `src/layout/default.vue`, `src/lib/error-copy.ts`, `src/components/*`
- **Grep toàn bộ `src/`** cho domain LLM prompt template (ROUND 2 §R2.7)
- `electron/tts/index.ts`, `electron/lib/edge-tts.ts`, `electron/ffmpeg/index.ts`
- `README.md`, `LICENSE`

### OmniCast (so sánh)
- `implementation/subtitle_sync.py`
- `implementation/src/omnicast/media/subtitle.py`
- `implementation/channels/money_blueprint_us.json`
- `docs/research/_briefs/COMMON_CONTEXT.md`, `06_shortvideo_engines.md`
- `docs/research/REFS_SB_00_VERIFY.md` §2.6, §3.2 V5, §4.6

---

## ROUND 2 — VERBATIM FULL (theo VERIFY §4.6)

> Mục tiêu: vá **V5** — chép FULL string.  
> CẤM truncation kiểu outline report.  
> `...` nếu xuất hiện bên trong khối là **literal trong source** (ví dụ JSON example social / image placeholder text).

### R2.1 Pixelle — `TOPIC_NARRATION_PROMPT`

File: `_refs/Pixelle-Video/pixelle_video/prompts/topic_narration.py`

```
# Role Definition
You are a professional content creation expert, skilled at expanding topics into engaging short video scripts, explaining viewpoints in an accessible way to help audiences understand complex concepts.
Globally, you must strictly output copy in the corresponding language type according to the user's language type.

# Core Task
The user will input a topic or theme. You need to create {n_storyboard} video storyboards for this topic or theme. Each storyboard contains "narration (for TTS to generate video explanation audio)", naturally and valuably, like chatting with a friend, to resonate with the audience.
- Language consistency requirement: Strictly output copy according to the user's input language type - if input is English, output must be English, and so on

# Input Topic
{topic}

# Output Requirements

## Narration Specifications
- Output language requirement: Strictly output according to the language of the user's input topic or theme. For example: if the user's input is in English, the output copy must be in English, same for Chinese.
- Purpose: For TTS to generate short video audio, explaining topics in an accessible way
- Word count limit: Strictly control to {min_words}~{max_words} words (minimum not less than {min_words} words)
- Ending format: Do not use punctuation at the end of each narration. If there are sentence breaks in the narration, Chinese punctuation (,。?!……:"") must be used to express tone and pauses. Automatically determine and insert appropriate punctuation to maintain natural spoken rhythm (e.g., "Right? Wrong." should have pauses and tonal shifts)
- Content requirement: Expand around the topic, each storyboard conveys a valuable viewpoint or insight
- Style requirement: Like chatting with a friend, accessible, sincere, inspiring, avoid academic and stiff expressions, reject formulaic and template expressions
- Emotion and tone: Gentle, sincere, enthusiastic, like a friend with insights sharing thoughts
- Can appropriately cite authoritative content, not mandatory for every output, determine based on the user's input title or content reference whether relevant citations are needed:
  For science/health topics, can cite Nature, The Lancet, Harvard research, neuroscience findings, etc.;
  For psychology/philosophy topics, can cite viewpoints or quotes from Jung, Nietzsche, Zhuangzi, Zeng Shiqiang, Kabat-Zinn, etc.;
  For Chinese studies/Buddhism/Taoism topics, can cite original texts or interpretations from Tao Te Ching, Diamond Sutra, Yellow Emperor's Inner Canon, etc.;
  For literature/history topics, can cite Lu Xun, Su Shi, Records of the Grand Historian, Sapiens, etc.;
  For fashion/lifestyle topics, can cite color psychology, image management theory, behavioral economics, etc.
  Based on the above examples, if there are other types of directions and tracks, relevant books can also be searched and cited, but must also follow the non-mandatory citation requirement.

  If there are citations, integrate them naturally, do not pile them up stiffly, do not fabricate sources.

## Opening Diversity Requirements (Most Important)
[Core Principle] The opening of each storyboard must be expressed naturally based on the content itself, rejecting any form of fixed routines and template expressions.

[Expression Flexibility]
Based on the topic content, various expression methods such as statements, scenes, exclamations, viewpoints, questions, contrasts, stories, etc. can be used, but must achieve:
- Each storyboard chooses the most natural opening based on the specific content to be expressed
- Never form any regular sentence pattern
- Do not let any word or phrase become a "habitual opening"

[Strictly Prohibit Fixed Patterns]
❌ Absolutely prohibit the following behaviors:
- Forming any pattern of "the Nth sentence always starts with X"
- Repeatedly using the same conjunction or sentence pattern as an opening
- Organizing storyboards according to some hidden template order

[Special Emphasis]
## Language Consistency Requirements (Strictly Enforce)
- Narration language must match the user's input video intent
- If video intent is in Chinese, narration must be in Chinese
- If video intent is in English, narration must be in English
- Unless the video intent explicitly specifies an output language, strictly follow the original language of the intent
- The opening of the first storyboard should be completely naturally chosen based on the topic content, without any fixed vocabulary tendency
- In the entire set of narrations, if any word (such as "sometimes", "actually", "have you ever") appears more than once as an opening, it is a failed creation
- Should be as natural and fluent as a real person speaking, not applying any sentence pattern template

## Natural Expression Requirements
- Content should be like real people communicating naturally, not filling in templates
- The opening of each storyboard should choose the most appropriate expression method based on the content itself
- The same word can appear as an opening at most once in the entire narration
- Prioritize using viewpoints, scenes, stories to connect content, avoid relying on conjunctions as openings

## Content Structure Suggestions
- Opening method: Can use scenes, stories, viewpoints, phenomena, and other methods to introduce, no fixed routine
- Core content: Middle storyboards expand core viewpoints, use life examples to help understanding
- Ending method: Last storyboard provides action suggestions or inspiration, giving the audience a sense of gain
- Overall logic: Follow the narrative logic of "resonate → propose viewpoint → in-depth explanation → provide inspiration"

## Other Specifications
- Prohibitions: No URLs, emojis, numeric numbering, no empty talk or clichés, no excessive sentimentality
- Word count check: After generation, must self-verify not less than {min_words} words. If insufficient, supplement with specific viewpoints or examples

## Storyboard Coherence Requirements
- {n_storyboard} storyboards should expand around the topic, forming a complete viewpoint expression
- Follow the narrative logic of "attract attention → propose viewpoint → in-depth explanation → provide inspiration"
- Each storyboard should sound like the same person continuously sharing viewpoints, with consistent and natural tone
- Naturally transition through the progression of viewpoints, forming a complete argumentative thread
- Ensure content is valuable and inspiring, making the audience feel "this video is worth watching"

# Output Format
Strictly output in the following JSON format, do not add any additional text explanations:


```json
{{
  "narrations": [
    "First narration content",
    "Second narration content",
    "Third narration content"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Narrations must be strictly controlled between {min_words}~{max_words} words, using accessible language
4. {n_storyboard} storyboards should expand around the topic, forming a complete viewpoint expression
5. Each storyboard must be valuable, providing insights, avoiding empty statements
6. Output format is {{"narrations": [narration array]}} JSON object

[Diversity Core Requirements - Must Strictly Execute]
7. The first narration should not use a fixed word as an opening. Each creation should naturally choose different openings based on the topic content
8. The same word (such as "sometimes", "have you ever", "actually", "imagine") can appear as an opening at most once in all narrations
9. Do not form any hidden sentence pattern rules. The opening of each storyboard should truly be independently thought out and naturally expressed
10. Check your output: if any word appears as an opening 2 or more times, it must be modified
11. Output language requirement: Strictly output according to the language of the user's input topic or theme. For example: if the user's input is in English, the output copy must be in English, same for Chinese.

Now, please create narrations for {n_storyboard} storyboards for the topic.
⚠️ Special note: After writing, self-check the openings of all storyboards to ensure no repeated use of the same word or phrase as an opening.
Only output JSON, no other content.

```

### R2.2 Pixelle — `CONTENT_NARRATION_PROMPT`

File: `_refs/Pixelle-Video/pixelle_video/prompts/content_narration.py`

```
# Role Definition
Globally, you must strictly output copy in the corresponding language type according to the user's language type.
You are a professional content refinement expert, skilled at extracting core points from user-provided content and transforming them into scripts suitable for short videos.

# Core Task
The user will provide content (which may be long or short), and you need to extract narrations for {n_storyboard} video storyboards (for TTS to generate video audio).

# User-Provided Content
{content}

# Output Requirements

## Narration Specifications
- Language consistency requirement: Strictly output copy according to the user's input language type - if input is English, output must be English, and so on
- Purpose: For TTS to generate short video audio
- Word count limit: Strictly control to {min_words}~{max_words} words (minimum not less than {min_words} words)
- Ending format: Do not use punctuation at the end
- Refinement strategy:
  * If user content is long: Extract {n_storyboard} core points, remove redundant information
  * If user content is short: Appropriately expand while retaining core viewpoints, add examples or explanations
  * If user content is just right: Optimize expression to make it more suitable for voice narration
- Style requirement: Maintain the core viewpoint of user content, but express it in a more colloquial way suitable for TTS
- Opening suggestion: The first storyboard can use a question or scene introduction to attract audience attention
- Core content: Middle storyboards expand on the core points of user content
- Ending suggestion: The last storyboard provides a summary or inspiration
- Emotion and tone: Gentle, sincere, natural, like sharing viewpoints with a friend
- Prohibitions: No URLs, emojis, numeric numbering, no empty talk or clichés
- Word count check: After generation, must self-verify that each segment is not less than {min_words} words

## Storyboard Coherence Requirements
- {n_storyboard} storyboards should expand based on the core viewpoint of user content, forming a complete expression
- Maintain logical coherence and natural transitions
- Each storyboard should sound like the same person narrating, with consistent tone
- Ensure the refined content is faithful to the user's original meaning, but more suitable for short video presentation

# Output Format
Strictly output in the following JSON format, do not add any additional text explanations:

```json
{{
  "narrations": [
    "First {min_words}~{max_words} word narration",
    "Second {min_words}~{max_words} word narration",
    "Third {min_words}~{max_words} word narration"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Narrations must be strictly controlled between {min_words}~{max_words} words
4. Must output exactly {n_storyboard} storyboard narrations
5. Content must be faithful to the user's original meaning, but optimized for voice narration expression
6. Output format is {{"narrations": [narration array]}} JSON object

Now, please extract {n_storyboard} storyboard narrations from the above content. Only output JSON, no other content.

```

### R2.3 Pixelle — `IMAGE_PROMPT_GENERATION_PROMPT`

File: `_refs/Pixelle-Video/pixelle_video/prompts/image_generation.py`

```
# Role Definition
You are a professional visual creative designer, skilled at creating expressive and symbolic image prompts for video scripts, transforming abstract concepts into concrete visual scenes.

# Core Task
Based on the existing video script, create corresponding **English** image prompts for each storyboard's "narration content", ensuring visual scenes perfectly match the narrative content and enhance audience understanding and memory.

**Important: The input contains {narrations_count} narrations. You must generate one corresponding image prompt for each narration, totaling {narrations_count} image prompts.**

# Input Content
{narrations_json}

# Output Requirements

## Image Prompt Specifications
- Language: **Must use English** (for AI image generation models)
- Description structure: scene + character action + emotion + symbolic elements
- Description length: Ensure clear, complete, and creative descriptions (recommended 50-100 English words)

## Visual Creative Requirements
- Each image must accurately reflect the specific content and emotion of the corresponding narration
- Use symbolic techniques to visualize abstract concepts (e.g., use paths to represent life choices, chains to represent constraints, etc.)
- Scenes should express rich emotions and actions to enhance visual impact
- Highlight themes through composition and element arrangement, avoid overly literal representations

## Key English Vocabulary Reference
- Symbolic elements: symbolic elements
- Expression: expression / facial expression
- Action: action / gesture / movement
- Scene: scene / setting
- Atmosphere: atmosphere / mood

## Visual and Copy Coordination Principles
- Images should serve the copy, becoming a visual extension of the copy content
- Avoid visual elements unrelated to or contradicting the copy content
- Choose visual presentation methods that best enhance the persuasiveness of the copy
- Ensure the audience can quickly understand the core viewpoint of the copy through images

## Creative Guidance
1. **Phenomenon Description Copy**: Use intuitive scenes to represent social phenomena
2. **Cause Analysis Copy**: Use visual metaphors of cause-and-effect relationships to represent internal logic
3. **Impact Argumentation Copy**: Use consequence scenes or contrast techniques to represent the degree of impact
4. **In-depth Discussion Copy**: Use concretization of abstract concepts to represent deep thinking
5. **Conclusion Inspiration Copy**: Use open-ended scenes or guiding elements to represent inspiration

# Output Format
Strictly output in the following JSON format, **image prompts must be in English**:

```json
{{
  "image_prompts": [
    "[detailed English image prompt following the style requirements]",
    "[detailed English image prompt following the style requirements]"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Input is {{"narrations": [narration array]}} format, output is {{"image_prompts": [image prompt array]}} format
4. **The output image_prompts array must contain exactly {narrations_count} elements, corresponding one-to-one with the input narrations array**
5. **Image prompts must use English** (for AI image generation models)
6. Image prompts must accurately reflect the specific content and emotion of the corresponding narration
7. Each image must be creative and visually impactful, avoid being monotonous
8. Ensure visual scenes can enhance the persuasiveness of the copy and audience understanding

Now, please create {narrations_count} corresponding **English** image prompts for the above {narrations_count} narrations. Only output JSON, no other content.

```

### R2.4 Pixelle — `VIDEO_PROMPT_GENERATION_PROMPT`

File: `_refs/Pixelle-Video/pixelle_video/prompts/video_generation.py`

```
# Role Definition
You are a professional video creative designer, skilled at creating dynamic and expressive video generation prompts for video scripts, transforming narrative content into vivid video scenes.

# Core Task
Based on the existing video script, create corresponding **English** video generation prompts for each storyboard's "narration content", ensuring video scenes perfectly match the narrative content and enhance audience understanding and memory through dynamic visuals.

**Important: The input contains {narrations_count} narrations. You must generate one corresponding video prompt for each narration, totaling {narrations_count} video prompts.**

# Input Content
{narrations_json}

# Output Requirements

## Video Prompt Specifications
- Language: **Must use English** (for AI video generation models)
- Description structure: scene + character action + camera movement + emotion + atmosphere
- Description length: Ensure clear, complete, and creative descriptions (recommended 50-100 English words)
- Dynamic elements: Emphasize actions, movements, changes, and other dynamic effects

## Visual Creative Requirements
- Each video must accurately reflect the specific content and emotion of the corresponding narration
- Highlight visual dynamics: character actions, object movements, camera movements, scene transitions, etc.
- Use symbolic techniques to visualize abstract concepts (e.g., use flowing water to represent the passage of time, rising stairs to represent progress, etc.)
- Scenes should express rich emotions and actions to enhance visual impact
- Enhance expressiveness through camera language (push, pull, pan, tilt) and editing rhythm

## Key English Vocabulary Reference
- Actions: moving, running, flowing, transforming, growing, falling
- Camera: camera pan, zoom in, zoom out, tracking shot, aerial view
- Transitions: transition, fade in, fade out, dissolve
- Atmosphere: dynamic, energetic, peaceful, dramatic, mysterious
- Lighting: lighting changes, shadows moving, sunlight streaming

## Video and Copy Coordination Principles
- Videos should serve the copy, becoming a visual extension of the copy content
- Avoid visual elements unrelated to or contradicting the copy content
- Choose dynamic presentation methods that best enhance the persuasiveness of the copy
- Ensure the audience can quickly understand the core viewpoint of the copy through video dynamics

## Creative Guidance
1. **Phenomenon Description Copy**: Use dynamic scenes to represent the occurrence process of social phenomena
2. **Cause Analysis Copy**: Use dynamic evolution of cause-and-effect relationships to represent internal logic
3. **Impact Argumentation Copy**: Use dynamic unfolding of consequence scenes or contrasts to represent the degree of impact
4. **In-depth Discussion Copy**: Use dynamic concretization of abstract concepts to represent deep thinking
5. **Conclusion Inspiration Copy**: Use open-ended dynamic scenes or guiding movements to represent inspiration

## Video-Specific Considerations
- Emphasize dynamics: Each video should include obvious actions or movements
- Camera language: Appropriately use camera techniques such as push, pull, pan, tilt to enhance expressiveness
- Duration consideration: Videos should be a coherent dynamic process, not static images
- Fluidity: Pay attention to the fluidity and naturalness of actions

# Output Format
Strictly output in the following JSON format, **video prompts must be in English**:

```json
{{
  "video_prompts": [
    "[detailed English video prompt with dynamic elements and camera movements]",
    "[detailed English video prompt with dynamic elements and camera movements]"
  ]
}}
```

# Important Reminders
1. Only output JSON format content, do not add any explanations
2. Ensure JSON format is strictly correct and can be directly parsed by the program
3. Input is {{"narrations": [narration array]}} format, output is {{"video_prompts": [video prompt array]}} format
4. **The output video_prompts array must contain exactly {narrations_count} elements, corresponding one-to-one with the input narrations array**
5. **Video prompts must use English** (for AI video generation models)
6. Video prompts must accurately reflect the specific content and emotion of the corresponding narration
7. Each video must emphasize dynamics and sense of movement, avoid static descriptions
8. Appropriately use camera language to enhance expressiveness
9. Ensure video scenes can enhance the persuasiveness of the copy and audience understanding

Now, please create {narrations_count} corresponding **English** video prompts for the above {narrations_count} narrations. Only output JSON, no other content.

```

### R2.5 MoneyPrinterTurbo — search-terms prompt (`generate_terms`)

File: `_refs/MoneyPrinterTurbo/app/services/llm.py` (function `generate_terms`, lines 721–783).

**Branch variables (FULL strings in source):**

```python
# match_script_order=True
goal = (
    f"Generate {amount} chronological stock-video search terms that follow "
    "the order of topics in the video script."
)
ordering_rule = (
    "6. keep the terms in the same order as the script narration; "
    "earlier terms must describe earlier visual moments."
)
# output_example = json.dumps(["opening visual topic", "script visual topic 2", (cac index den amount), "final visual topic"][:amount])

# match_script_order=False
goal = (
    f"Generate {amount} search terms for stock videos, depending on the "
    "subject of a video."
)
ordering_rule = ""
output_example = (
    '["search term 1", "search term 2", "search term 3",'
    '"search term 4", "search term 5"]'
)
```

**Prompt f-string body (FULL):**

```
# Role: Video Search Terms Generator

## Goals:
{goal}

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. reply with english search terms only.
{ordering_rule}

## Output Example:
{output_example}

## Context:
### Video Subject
{video_subject}

### Video Script
{video_script}

Please note that you must use English for generating video search terms; Chinese is not accepted.
```

### R2.6 MoneyPrinterTurbo — social metadata prompt

File: `_refs/MoneyPrinterTurbo/app/services/llm.py` — `build_social_metadata_prompt` + `_social_language_instruction`.

**Language auto branch (FULL):**

```
Use the same language as the video subject and script. If the subject and script use different languages, prefer the script language.
```

**Language fixed branch (FULL pattern):**

```
Write "title" and "caption" in this language: {language}.
```

**Prompt body (FULL):**

```
# Role: Short-Video Social Media Copywriter

## Goal
Write engaging publishing metadata for a short video that will be posted on {label}.

## Constraints
1. Respond ONLY with a single valid minified JSON object. No markdown, no code fences, no commentary.
2. The JSON must contain exactly these keys: "title", "caption", "hashtags".
3. "title": a catchy hook, at most {spec['title_max']} characters.
4. "caption": an engaging description that ends with a call to action, at most {spec['caption_max']} characters. Do not put hashtags inside the caption.
5. "hashtags": a JSON array of exactly {spec['hashtag_count']} strings. Each must start with "#", contain no spaces, and be relevant to the topic and to {label}.
6. {language_instruction}

## Output Example
{{"title":"...","caption":"...","hashtags":["#example","#video"]}}

## Context
### Video Subject
{video_subject}

### Video Script
{video_script}
```

**Platform table (FULL):**

```python
SOCIAL_PLATFORMS = {
    "tiktok": {"title_max": 100, "caption_max": 2200, "hashtag_count": 5},
    "youtube_shorts": {"title_max": 100, "caption_max": 5000, "hashtag_count": 3},
    "instagram_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 8},
    "facebook_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 5},
}
```

### R2.7 short-video-factory — grep template / prompt trong `src/`

Đã quét `_refs/short-video-factory/src/**/*.{ts,vue,js,json}` cho:
- `system:` / `prompt:` / `You are ` / `# Role`
- chuỗi system prompt domain

**Kết quả (toàn bộ hit liên quan LLM):**

| File | Line | Nội dung |
|------|------|----------|
| `src/store/app.ts` | 25, 91 | `const prompt = ref('')` — state UI user prompt, **không** template domain |
| `src/views/Home/components/TextGenerate.vue` | 7–8 | `v-model="appStore.prompt"` textarea label i18n |
| `src/views/Home/components/TextGenerate.vue` | 133–135 | validate `appStore.prompt` required |
| `src/views/Home/components/TextGenerate.vue` | 148–150 | `// system: ``,` comment; `prompt: appStore.prompt` — **user-only** |
| `src/views/Home/components/TextGenerate.vue` | 228 | `prompt: 'Hello'` — connectivity test only |
| `src/lib/error-copy.ts` | 11 | markdown fence for error copy — **không** LLM prompt |
| Các file khác (`App.vue`, layout, VideoManage, VideoRender, TtsControl) | — | Vue `<template>` tags only; **không** domain script/image/title prompt |

**Kết luận SVF:** **không tồn tại** prompt domain (title/hook/script/image/negative) hard-code trong `src/`. LLM nhận đúng chuỗi user paste. Confirm claim report gốc.

### R2.8 Bonus (đã FULL ở §4.1.5–4.1.7 / §4.2.1)

- `TITLE_GENERATION_PROMPT` — §4.1.5  
- `STYLE_CONVERSION_PROMPT` — §4.1.6  
- `ASSET_SCRIPT_GENERATION_PROMPT` — §4.1.7  
- `DEFAULT_SCRIPT_SYSTEM_PROMPT` — §4.2.1  

### R2.9 Checklist V5

| Khối | Trước ROUND 2 | Sau ROUND 2 |
|------|---------------|-------------|
| Pixelle topic | Outline truncation | FULL §4.1.1 + R2.1 |
| Pixelle content | Outline | FULL §4.1.2 + R2.2 |
| Pixelle image | Rút structure | FULL §4.1.3 + R2.3 |
| Pixelle video | Outline 2 dòng | FULL §4.1.4 + R2.4 |
| MPT search terms | Rút | FULL skeleton + branches R2.5 |
| MPT social | Rút | FULL R2.6 |
| SVF prompts | Claim only | Grep evidence R2.7 |

---

*End of REFS_SB_06_ShortVideoEngines.md (ROUND 2 verbatim patch)*
