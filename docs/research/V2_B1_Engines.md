# V2_B1 — VIDEO ENGINES: MoneyPrinterTurbo + Pixelle-Video

> STATUS: ACTIVE  
> Chiến dịch V2 · Nhóm B1 · Verbatim harvest + cơ chế  
> Nguồn: `_refs/MoneyPrinterTurbo/`, `_refs/Pixelle-Video/` (CHỈ ĐỌC)  
> Đối chiếu OmniCast: `implementation/render_real_video.py`, `media/render_engine.py`, `media/ffmpeg.py`, `media/subtitle.py`, `pipeline/`, `jobengine/`

---

## Pipeline tóm tắt (Tầng 2 — ngữ cảnh)

### MoneyPrinterTurbo (MPT)
```
video_subject
  → LLM generate_script (system + init params)
  → LLM generate_terms (EN search keywords; optional chronological order)
  → Edge/Azure/Gemini/SiliconFlow/MiMo TTS + SubMaker cues
  → subtitle: edge (from SubMaker) | whisper (ASR + Levenshtein correct vs script)
  → stock search Pexels/Pixabay/Coverr per term
     [match_materials_to_script] → download round-robin by term order
  → combine_videos: slice ≤ max_clip_duration, transition, loop to audio_len
  → ffmpeg concat demuxer re-encode → MoviePy burn subtitle + mix VO/BGM
```

### Pixelle-Video
```
topic|content|fixed script
  → LinearVideoPipeline template method:
      setup → generate_content (narrations JSON)
      → title → plan_visuals (image/video prompts EN)
      → storyboard frames
  → per frame: TTS → ComfyUI/API media → HTML frame template compose
      → image+audio → video segment
  → ffmpeg concat (demuxer|filter) → optional BGM (vol 0.2 loop)
  Workflows: selfhost/*.json | runninghub/*.json (remote workflow_id)
```

### OmniCast (hiện trạng)
```
Writer/Critic scenes (vo + visual stock query text)
  → TTS + music
  → SubtitleModule (placeholder WhisperX — chưa production)
  → render_real_video.py / render_engine EZFFMPEG / ffmpeg layers
  → pipeline YAML runner + JobEngine checkpoints
Visual: download_best_web_image / visual_match QC (ẢNH); Veo/Flow clips — KHÔNG stock-clip-per-sentence engine kiểu MPT
```

---

## Bảng VERBATIM

### 1. MPT — DEFAULT_SCRIPT_SYSTEM_PROMPT

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/services/llm.py:23-38` |
| **loại** | prompt |
| **tóm tắt** | System role sinh script video: raw text, N đoạn, cùng ngôn ngữ subject, cấm markdown/voiceover labels |
| **OmniCast** | `agents/writer.py` — scene JSON + VO rules riêng (TỰ CHẾ, khác format) |
| **khuyến nghị** | **GHÉP** ràng buộc “raw spoken only / no welcome fluff” vào short-form compilation mode |

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

Build runtime (`llm.py:612-628`):
```
# Initialization:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}
[- language: {language}]
[# Additional User Requirements: {video_script_prompt}]
```

---

### 2. MPT — generate_terms (stock search keywords)

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/services/llm.py:721-783` |
| **loại** | prompt |
| **tóm tắt** | Sinh JSON array EN search terms 1–3 words; optional chronological order theo script |
| **OmniCast** | Writer field `"visual": "stock footage query, MAX 6 plain words"` — có query per scene nhưng **không** engine tải stock clip theo term |
| **khuyến nghị** | **THAY/GHÉP** pipeline compilation: terms per sentence + ordered download |

```
# Role: Video Search Terms Generator

## Goals:
{goal}   # unordered: "Generate {amount} search terms for stock videos..."
         # ordered:   "Generate {amount} chronological stock-video search terms
         #             that follow the order of topics in the video script."

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. reply with english search terms only.
{ordering_rule}  # ordered: "6. keep the terms in the same order as the script narration;
                 # earlier terms must describe earlier visual moments."

## Output Example:
{output_example}

## Context:
### Video Subject
{video_subject}
### Video Script
{video_script}

Please note that you must use English for generating video search terms; Chinese is not accepted.
```

Config đi kèm (`task.py:48-49`): `amount=8 if match_materials_to_script else 5`.

---

### 3. MPT — social metadata prompt

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/services/llm.py:835-988` |
| **loại** | prompt + config |
| **tóm tắt** | Title/caption/hashtags theo platform; JSON minified; fallback hashtags |
| **OmniCast** | Upload metadata TỰ CHẾ / channel config — không bảng platform length |
| **khuyến nghị** | **GHÉP** `SOCIAL_PLATFORMS` caps vào publish prep |

**Config platforms (verbatim keys):**
```
SOCIAL_PLATFORMS = {
  "tiktok":          {"title_max": 100, "caption_max": 2200, "hashtag_count": 5},
  "youtube_shorts":  {"title_max": 100, "caption_max": 5000, "hashtag_count": 3},
  "instagram_reels": {"title_max": 125, "caption_max": 2200, "hashtag_count": 8},
  "facebook_reels":  {"title_max": 125, "caption_max": 2200, "hashtag_count": 5},
}
DEFAULT_SOCIAL_HASHTAGS = ["#shorts","#viral","#trending","#fyp","#video","#reels","#creator","#content"]
MAX_SOCIAL_SUBJECT_LENGTH = 500
MAX_SOCIAL_SCRIPT_LENGTH = 8000
```

Prompt core:
```
# Role: Short-Video Social Media Copywriter
## Goal
Write engaging publishing metadata for a short video that will be posted on {label}.
## Constraints
1. Respond ONLY with a single valid minified JSON object...
2. keys: "title", "caption", "hashtags"
3. title ≤ {title_max}; caption ≤ {caption_max} ends with CTA; no hashtags in caption
4. hashtags: exactly {hashtag_count} strings starting with "#"
...
```

---

### 4. MPT — VideoParams / render defaults

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/models/schema.py:18-112`, `app/services/video.py:65-69` |
| **loại** | config |
| **tóm tắt** | Aspect, clip duration, concat/transition, subtitle style, BGM vol, ffmpeg codec/bitrate |
| **OmniCast** | `render_real_video.py` crf 18 libx264; `orchestrator` music `volume_db=-20`; subtitle style TỰ CHẾ |
| **khuyến nghị** | **GHÉP** bảng default subtitle/BGM/clip_duration vào channel config compilation |

| key | default | unit / notes |
|-----|---------|--------------|
| `VideoAspect.landscape` | 16:9 → 1920×1080 | |
| `VideoAspect.portrait` | 9:16 → 1080×1920 | **default VideoParams** |
| `VideoAspect.square` | 1:1 → 1080×1080 | |
| `video_concat_mode` | `random` \| `sequential` | schema.py:18-20 |
| `video_transition_mode` | `None` / Shuffle / FadeIn / FadeOut / SlideIn / SlideOut | duration effect **1s** |
| `video_clip_duration` | **5** | seconds max slice per subclip |
| `match_materials_to_script` | **false** | bật ordered terms + download |
| `video_count` | 1 | |
| `video_source` | `pexels` | also pixabay, coverr, local |
| `voice_volume` | 1.0 | |
| `voice_rate` | 1.0 (VideoParams); **1.2** on SubtitleRequest/AudioRequest | |
| `bgm_type` | `random` | empty = no BGM |
| `bgm_volume` | **0.2** | linear mix scale |
| `subtitle_enabled` | true | |
| `subtitle_position` | `bottom` (or ui config) | top/center/bottom/custom |
| `custom_position` | 70.0 | % from top when custom |
| `font_name` | `STHeitiMedium.ttc` | |
| `text_fore_color` | `#FFFFFF` | |
| `text_background_color` | `True` → treat as `#000000` | bool\|str |
| `rounded_subtitle_background` | false | alpha 140 radius≈0.4×font |
| `font_size` | **60** | |
| `stroke_color` | `#000000` | |
| `stroke_width` | **1.5** | |
| `n_threads` | 2 | ffmpeg -threads |
| `paragraph_number` | 1 (ge1 le10) | |
| `fps` | **30** | video.py:69 |
| `audio_codec` | `aac` | |
| `audio_bitrate` | **192k** | comment: Docker AAC quality |
| `video_codec` | `libx264` + HW whitelist nvenc/amf/qsv/mf/videotoolbox | fallback libx264 |
| concat ffmpeg | `-f concat -safe 0 -c:v {codec} -threads N -pix_fmt yuv420p` | re-encode (not copy) |
| subtitle wrap | max_width = **0.9 × video_width**; pad_x = 0.6×font if bg | PIL measure, not max-chars |
| transition duration | **1** second | video_effects |
| prioritize unique source | random mode: longest subclip per source first | video.py:83-123 |
| gemini sampling | temperature **0.5**, top_p **1**, top_k **1**, max_output **2048** | llm.py:367-372 |
| `_max_retries` | **5** | script/terms |
| `edge_tts_timeout` | **30** s (0=disable) | config.example.toml:11 |
| `max_concurrent_tasks` | 5 | |
| `max_queued_tasks` | 100 | |
| whisper | model `large-v3`, device CPU, compute `int8`, beam_size **5**, vad min_silence **500ms** | subtitle.py |

MiMo TTS style default (`config.example.toml:191`):
```
mimo_tts_style_prompt = "请用自然、清晰、适合短视频旁白的语气朗读。"
```
*(Tóm tắt VI: Đọc bằng giọng tự nhiên, rõ, phù hợp narration short-form.)*

---

### 5. MPT — voice lists (sample / prefixes)

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/services/voice.py:59-139`, schema defaults |
| **loại** | config |
| **tóm tắt** | Multi-provider voice registry prefixes |
| **OmniCast** | `voice_router` + `provider:voice_id` (kokoro/edge/…) — **tương đương** hướng, list khác |
| **khuyến nghị** | **BỎ QUA** list chi tiết; giữ pattern prefix + fallback |

- Default UI/API voice often: `zh-CN-XiaoxiaoNeural-Female` / Edge Neural family  
- SiliconFlow CosyVoice: `siliconflow:FunAudioLLM/CosyVoice2-0.5B:{alex|anna|bella|…}-{Gender}`  
- Gemini: `gemini:Zephyr-Female`, Puck, Charon, Kore, …  
- MiMo: `mimo:冰糖-Female`, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean  
- `NO_VOICE_NAME = "no-voice"` (+ alias `none`)  
- Azure: loaded from `app/services/data/azure_voices.json`

---

### 6. MPT — material search + ordered download

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/services/material.py:55-470`, `task.py:40-50, 190-201` |
| **loại** | config + mechanism |
| **tóm tắt** | Pexels per_page 20 orientation; Pixabay per_page 50; Coverr page_size 20; min duration = max_clip; ordered round-robin per term |
| **OmniCast** | image web download + visual_match QC; **thiếu** stock video search API path |
| **khuyến nghị** | **THAY** cho kênh compilation B-roll video |

Pexels params: `query, per_page=20, orientation={portrait|landscape|square}`; exact resolution match.  
Pixabay: `w >= video_width`.  
Coverr: no aspect filter (~1% portrait); `urls=true`, sort popular.  
Timeouts: connect 30s / read 60s.  
`tls_verify` default **true**.

Ordered path comment (verbatim essence `material.py:395-402`):
> Default merges all candidates; first term can starve later topics. Round-robin: round i takes i-th candidate of each term so timeline tracks script order without rewriting the compositor.

---

### 7. MPT — subtitle pipeline (edge + whisper + correct)

| field | value |
|-------|--------|
| **repo** | MoneyPrinterTurbo |
| **file:line** | `app/services/task.py:134-169`, `subtitle.py:21-310`, `voice.py:1368+` |
| **loại** | config + mechanism |
| **tóm tắt** | Edge SubMaker cues → SRT; fallback Whisper; Levenshtein merge correct vs script lines |
| **OmniCast** | `media/subtitle.py` placeholder segments; `render_real_video.render_subtitle_overlay` bottom white+black stroke per scene |
| **khuyến nghị** | **GHÉP** correct-against-script + edge cue path; WhisperX word align khi đã wire thật |

```
subtitle_provider = "edge" | "whisper"   # config.example.toml:225
# edge missing file → fallback whisper
# whisper: word_timestamps, vad_filter, split on punctuation
# correct(): similarity > 0.8 merge subtitle cues to script lines
```

---

### 8. Pixelle — TOPIC_NARRATION_PROMPT

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `pixelle_video/prompts/topic_narration.py:20-131` |
| **loại** | prompt |
| **tóm tắt** | N storyboard narrations JSON; word min/max; anti-template openings; optional authoritative citations |
| **OmniCast** | Writer debate pipeline sâu hơn nhưng **không** output `{"narrations":[…]}` short-board cố định N |
| **khuyến nghị** | **GHÉP** anti-opening-repeat + word clamp cho short vertical pack |

Defaults khi gọi (`standard.py:110-112`, `StoryboardConfig`):  
`n_scenes=5`, `min_narration_words=5`, `max_narration_words=20`.

Output:
```json
{"narrations": ["...", "..."]}
```

---

### 9. Pixelle — CONTENT_NARRATION_PROMPT

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `pixelle_video/prompts/content_narration.py:20-77` |
| **loại** | prompt |
| **tóm tắt** | Rút/gỡn user content → đúng N narrations; long=extract, short=expand |
| **OmniCast** | `editorial_angle` / writer — không clamp word per board giống hệt |
| **khuyến nghị** | **GHÉP** cho “paste long article → short video” |

---

### 10. Pixelle — IMAGE / VIDEO prompt generators

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `prompts/image_generation.py:50-117`, `prompts/video_generation.py:23-99` |
| **loại** | prompt |
| **tóm tắt** | 1 EN prompt per narration; structure scene+action+emotion(+camera); JSON arrays |
| **OmniCast** | `media/prompt_builder.py` + VisualDirector — TỰ CHẾ, không batch JSON 1:1 narrations |
| **khuyến nghị** | **GHÉP** batch JSON 1:1 + camera vocabulary cho Veo/Flow |

Style presets (`image_generation.py:26-47`):
```
stick_figure: "stick figure style sketch, black and white lines, pure white background, minimalist hand-drawn feel"
minimal:      "minimalist abstract art, geometric shapes, clean composition, modern design, soft pastel colors"
concept:      "conceptual visual metaphors, symbolic elements, thought-provoking imagery, artistic interpretation"
DEFAULT_IMAGE_STYLE = "stick_figure"
```

Config prefix default (`schema.py:88-99`, `config.example.yaml:65`):
```
prompt_prefix: "Minimalist black-and-white matchstick figure style illustration, clean lines, simple sketch style"
```

---

### 11. Pixelle — TITLE / STYLE / ASSET prompts

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `title_generation.py:20-64`, `style_conversion.py:20-32`, `asset_script_generation.py:20-51` |
| **loại** | prompt |
| **tóm tắt** | Title ≤ max_length (default 15 chars!); style→SD/FLUX EN; asset-path scene script |
| **OmniCast** | Title/thumbnail agents riêng; asset-based pipeline partial |
| **khuyến nghị** | **GHÉP** asset_script (path binding); title max 15 **BỎ QUA** cho YouTube (quá ngắn) |

Style conversion:
```
Convert this style description into a detailed image generation prompt for Stable Diffusion/FLUX:
Style Description: {description}
Requirements:
- Focus on visual elements, colors, lighting, mood, atmosphere
- Output ONLY the prompt in English (no explanations)
- Keep it under 100 words
- Use comma-separated descriptive phrases
```

Asset script: duration target; 5–15s/scene; 1 asset path/scene; 1–3 narrations/scene; language = intent.

---

### 12. Pixelle — StoryboardConfig + VideoService defaults

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `models/storyboard.py:23-55`, `services/video.py:108-116`, `config/schema.py` |
| **loại** | config |
| **tóm tắt** | FPS, word counts, TTS, BGM, template path, ComfyUI |
| **OmniCast** | channel yaml + render CLI — rải rác |
| **khuyến nghị** | **GHÉP** single StoryboardConfig dataclass cho job media |

| key | default |
|-----|---------|
| `n_storyboard` | 5 |
| `min_narration_words` / `max` | 5 / 20 |
| `min_image_prompt_words` / `max` | 30 / 60 |
| `video_fps` | 30 |
| `tts_inference_mode` | `local` |
| Edge TTS voice | `zh-CN-YunjianNeural` |
| Edge TTS speed | **1.2** (0.5–2.0) |
| `frame_template` | `1080x1920/default.html` (example: `image_default.html`) |
| `bgm_volume` | **0.2** |
| `bgm_mode` | `loop` \| `once` |
| concat method | `demuxer` (copy) or `filter` |
| LLM direct media temp | **0.2** (`api_media.py:622`) |
| runninghub_concurrent_limit | 1 (1–10) |

---

### 13. Pixelle — ComfyUI workflow KSampler defaults (selfhost)

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `workflows/selfhost/image_flux.json:1-30`, `image_qwen.json`, `video_wan2.1_fusionx.json` |
| **loại** | config |
| **tóm tắt** | CFG/steps/sampler baked in workflow JSON; runninghub = remote workflow_id only |
| **OmniCast** | Provider wrappers (Gemini/Flow) — không graph ComfyUI |
| **khuyến nghị** | **BỎ QUA** nếu không adopt ComfyUI; **GHÉP** idea “workflow file = versioned graph” |

| workflow | steps | cfg | sampler | denoise | notes |
|----------|-------|-----|---------|---------|-------|
| `image_flux.json` | **20** | **1** | euler | 1 | scheduler simple |
| `image_qwen.json` | **4** | **1** | euler | 1 | Lightning LoRA 4steps |
| `video_wan2.1_fusionx.json` | **10** | **1** | uni_pc | 1 | |
| runninghub `image_flux.json` | n/a | n/a | n/a | n/a | `{"source":"runninghub","workflow_id":"1983427617984585729"}` |

Templates directory: `templates/{1080x1920,1080x1080,1920x1080}/` with `static_*` \| `image_*` \| `video_*` naming → skip media gen if static.

---

### 14. Pixelle — LinearVideoPipeline orchestration

| field | value |
|-------|--------|
| **repo** | Pixelle-Video |
| **file:line** | `pipelines/linear.py:66-119`, `pipelines/base.py:28-78`, `pipelines/standard.py` |
| **loại** | config/mechanism |
| **tóm tắt** | Template Method 8 bước; subclass override; progress callbacks |
| **OmniCast** | `pipeline/runner.py` YAML + Jinja + retry + JobEngine — declarative mạnh hơn list steps; **yếu hơn** về typed lifecycle hooks per media frame |
| **khuyến nghị** | **GHÉP** frame-level lifecycle (TTS→media→compose→segment) as reusable step types |

Lifecycle:
```
1 setup_environment
2 generate_content
3 determine_title
4 plan_visuals
5 initialize_storyboard
6 produce_assets
7 post_production
8 finalize
```

Also: `asset_based`, `custom`, web pipelines `digital_human`, `i2v`, `action_transfer`.

---

## Cơ chế OmniCast thiếu hoặc yếu hơn

| cơ chế | repo nguồn (file:dòng) | hiện trạng OmniCast (file:dòng) | mức | việc phải làm |
|--------|------------------------|----------------------------------|------|----------------|
| **Stock search-term LLM → clip-per-sentence ordered download** | MPT `llm.generate_terms` + `material._download_videos_by_script_order` + `match_materials_to_script` | Writer có `visual` query text; `download_best_web_image`/visual_match cho **ảnh**; không Pexels/Pixabay video loop | **CAO** | Thêm `StockClipModule`: terms ordered, download, slice max_clip, concat to VO; flag channel `compilation_mode` |
| **Subtitle from TTS cues + Whisper fallback + script Levenshtein correct** | MPT `task.generate_subtitle`, `voice.create_subtitle`, `subtitle.correct` | `media/subtitle.py` placeholder hardcode; overlay PNG in `render_real_video` | **CAO** | Wire WhisperX thật; prefer TTS word/cue timestamps; correct against scene VO text |
| **Subtitle wrap by pixel width (PIL) + stroke/bg/rounded** | MPT `video.wrap_text`, `generate_video` TextClip | Hardcoded bottom white text + black stroke in renderer; no ASS styling table | **TRUNG** | Port wrap_text + style params into channel `subtitle_style` |
| **BGM volume default 0.2 + random from pool + path sandbox** | MPT `bgm_volume=0.2`, `get_bgm_file`; Pixelle same 0.2 | `orchestrator` volume_db=-20 (~0.1 linear); music module | **THẤP** | Normalize to shared linear 0.15–0.25 default + ducking already in ffmpeg |
| **Clip duration cap + unique-source prioritization + loop to audio** | MPT `combine_videos` max_clip=5, `_prioritize_unique_source_clips` | Scene-based clips; Veo fixed 4/6/8s | **CAO** (compilation) | Reuse for B-roll montage channels |
| **Transition modes 1s fade/slide/shuffle** | MPT `VideoTransitionMode` + video_effects | Crossfade in ffmpeg builder partial | **TRUNG** | Expose transition enum on render job |
| **HW encoder fallback chain** | MPT `_write_videofile_with_codec_fallback` | libx264 crf18 fixed in CLI | **THẤP** | Optional nvenc with libx264 fallback |
| **Social metadata platform caps** | MPT `SOCIAL_PLATFORMS` | Publish path incomplete | **TRUNG** | Add metadata step before upload |
| **Per-narration EN image/video prompt batch JSON** | Pixelle image/video_generation prompts | prompt_builder + visual_director ad-hoc | **TRUNG** | Batch 1:1 scene prompts with camera language for Veo |
| **Anti-template opening diversity in short narration** | Pixelle topic_narration | Writer has anti-stock rules elsewhere but not short-board openings | **THẤP** | Steal opening diversity block for vertical shorts |
| **HTML frame templates by aspect (static/image/video)** | Pixelle `templates/` + `get_template_type` | Custom PNG cards in render_real_video | **TRUNG** | Optional template pack for quote/card channels |
| **ComfyUI/RunningHub workflow as pluggable media node** | Pixelle workflows + comfy services | providers/* API/browser only | **THẤP** | Only if self-host FLUX/Wan roadmap |
| **Linear pipeline template method for media frames** | Pixelle `LinearVideoPipeline` | YAML DAG good for channel jobs; weak typed media frame loop | **TRUNG** | Add `FrameProduceStep` composite step type |
| **TTS speed default 1.2 short-form** | Pixelle schema 1.2; MPT voice_rate often 1.2 on sub API | Channel voice rate varies | **THẤP** | Default short-form rate 1.15–1.25 |
| **Think-block strip + code-fence JSON recover for LLM** | MPT `_normalize_text_response`, `_strip_code_fence` | llm router may partial | **TRUNG** | Centralize response sanitizers |

---

## TOP-15 PATCH

1. **Stock compilation engine (MPT)** — `media/stock_clips.py` + provider Pexels: terms ordered, download, slice ≤5s, unique-source, concat to audio.  
2. **Wire `match_materials_to_script` flag on channel** — amount 8 terms chronological; map writer `visual` or dedicated term LLM.  
3. **Production SubtitleModule** — replace placeholder; WhisperX align + optional TTS cues; `subtitle.correct` vs VO.  
4. **Port `wrap_text` + stroke/bg style table** — channel `subtitle_style` → burn via ffmpeg ASS or pre-render.  
5. **Pixelle-style batch visual prompts** — one EN image/video prompt per scene JSON array into `prompt_builder` / Veo.  
6. **BGM default linear 0.2 + loop mode** — unify orchestrator/music with ducking.  
7. **Transition enum (none/fade/slide/shuffle)** — `render_engine` / `ffmpeg.py` 0.5–1s.  
8. **Social metadata step** — copy MPT platform caps for TikTok/Shorts/Reels before upload.  
9. **Frame lifecycle step type** — YAML: `frame_produce` = tts→media→compose→segment (Pixelle produce_assets).  
10. **Anti-opening-repeat block** — inject into short-form writer mode (Pixelle topic_narration rules 7–10).  
11. **Script system constraints** — raw spoken, no welcome, no markdown (MPT DEFAULT_SCRIPT) for compilation scripts.  
12. **Unique-source prioritization** when looping B-roll — avoid same stock clip thrashing.  
13. **Encoder fallback** — try h264_nvenc then libx264; pix_fmt yuv420p fps 30 aac 192k.  
14. **LLM output sanitize** — strip `<think>`, strip ```json fences before parse (MPT).  
15. **HTML/static template option** — skip gen-media for text-card scenes (Pixelle static_*).

---

## Ghi chú đối chiếu nhanh (Tầng 2 chi tiết brief)

### Clip-per-sentence vs OmniCast image match
- MPT **không** cắt clip đúng từng câu SRT 1:1 cứng; mô hình là: **nhiều EN terms** (5–8) → tải đủ total_duration ≥ audio → ghép subclips ≤ `video_clip_duration` (5s), random hoặc sequential.  
- Khi `match_materials_to_script=true`: terms **theo thứ tự script** + download **round-robin theo term** + concat sequential → gần “câu/đoạn → visual topic” hơn random pool.  
- OmniCast đã có **per-scene visual query text** (writer) và **image** retrieval/QC — để kênh compilation: **ghép stock video path MPT** lên field `visual`/`broll_query`, không cần đổi writer core.

### Subtitle vs `media/subtitle.py`
- MPT: timing từ **TTS SubMaker** (ưu tiên) hoặc **Whisper word timestamps**, rồi **align lại chữ** theo script (Levenshtein).  
- OmniCast: module subtitle vẫn stub; production burn-in chủ yếu **per-scene full line** trong `render_real_video` (không word-level SRT pipeline).  
- Ưu tiên patch: TTS-aligned SRT → ffmpeg `subtitles=` filter (render_engine đã có hook).

### Pixelle node-graph vs OmniCast YAML pipeline
- Pixelle “nodes” thực chất = **ComfyUI workflow JSON** (media gen) + **Python LinearVideoPipeline** (orchestration), không phải DAG YAML.  
- OmniCast YAML + JobEngine **linh hoạt hơn** về dependency/retry/idempotency.  
- Chỗ Pixelle thắng: **typed multi-phase media loop**, template_type gates (static skips gen), pluggable pipeline classes (standard/asset/i2v).  
- Nên **không** thay YAML bằng graph Comfy; **nên** thêm step types + lifecycle hooks lấy ý Pixelle.

---

*Hết báo cáo B1. Không sửa code / `_refs/`. Output duy nhất: `docs/research/V2_B1_Engines.md`.*
