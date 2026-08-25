# V2_A1 — Dịch & Lồng tiếng: VideoLingo + pyvideotrans

> STATUS: ACTIVE  
> Chiến dịch V2 · Nhóm A1 · Verbatim harvest + cơ chế  
> Nguồn: `_refs/VideoLingo/`, `_refs/pyvideotrans/` (CHỈ ĐỌC)  
> Đối chiếu OmniCast: `implementation/src/omnicast/media/{tts,voice_router,subtitle}.py` + `media/providers/tts_*.py`

---

## Pipeline tóm tắt (Tầng 2 — ngữ cảnh)

### VideoLingo (`_refs/VideoLingo`)
```
yt/video → ASR (WhisperX) → NLP split → meaning split (LLM)
  → summarize terms → translate (faithfulness → expressiveness/reflect)
  → split-for-sub (align LLM) → gen SRT
  → audio task (trim text if too long) → TTS per line
  → speed/atempo chunk align → merge audio → burn dub video
```

### pyvideotrans (`_refs/pyvideotrans`)
```
prepare → recogn (22 ASR) → diariz → trans (24 MT/LLM)
  → dubbing (33 TTS registry) → align (SpeedRate: audio RB/atempo + video setpts)
  → recogn2pass (optional) → assembling → done
```

### OmniCast (hiện trạng)
```
Writer/Critic sinh script (ngôn ngữ đích, không pipeline dịch video)
  → TTSModule + VoiceRouter (fallback chain provider:voice)
  → SubtitleModule (placeholder WhisperX, chưa production)
  → render_engine loudnorm + mix
```
**OmniCast KHÔNG** làm video-to-video dub; trọng tâm kế thừa là: chuỗi prompt dịch đa bước, registry TTS, align tempo, SRT normalize, text-norm cho TTS.

---

## Bảng VERBATIM

### 1. VideoLingo — prompt split nghĩa (Netflix subtitle splitter)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:6-44` |
| **loại** | prompt |
| **tóm tắt** | Tách câu phụ đề thành N phần ≤ word_limit; 2 phương án `[br]` + assess + choice |
| **OmniCast** | TỰ CHẾ – không có split-by-meaning LLM; writer viết thẳng |
| **khuyến nghị** | **GHÉP** vào post-process phụ đề đa ngôn ngữ / caption pack |

```
## Role
You are a professional Netflix subtitle splitter in **{language}**.

## Task
Split the given subtitle text into **{num_parts}** parts, each less than **{word_limit}** words.

1. Maintain sentence meaning coherence according to Netflix subtitle standards
2. MOST IMPORTANT: Keep parts roughly equal in length (minimum 3 words each)
3. Split at natural points like punctuation marks or conjunctions
4. If provided text is repeated words, simply split at the middle of the repeated words.

## Steps
1. Analyze the sentence structure, complexity, and key splitting challenges
2. Generate two alternative splitting approaches with [br] tags at split positions
3. Compare both approaches highlighting their strengths and weaknesses
4. Choose the best splitting approach

## Given Text
<split_this_sentence>
{sentence}
</split_this_sentence>

## Output in only JSON format and no other text
```json
{
    "analysis": "...",
    "split1": "... [br] ...",
    "split2": "... [br] ...",
    "assess": "...",
    "choice": "1 or 2"
}
```
```

---

### 2. VideoLingo — prompt summarize + terminology

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:53-124` |
| **loại** | prompt |
| **tóm tắt** | 2 câu theme + ≤15 thuật ngữ src→tgt+note; loại trừ terms đã có |
| **OmniCast** | `agents/writer` / evidence — không glossary-first trước dịch phụ đề |
| **khuyến nghị** | **GHÉP** glossary channel-level trước khi localize script |

```
## Role
You are a video translation expert and terminology consultant, specializing in {src_lang} comprehension and {tgt_lang} expression optimization.

## Task
For the provided {src_lang} video text:
1. Summarize main topic in two sentences
2. Extract professional terms/names with {tgt_lang} translations (excluding existing terms)
3. Provide brief explanation for each term
...
  "theme": "Two-sentence video summary",
  "terms": [ {"src": "...", "tgt": "...", "note": "..."} ]
```

---

### 3. VideoLingo — faithfulness (dịch thẳng)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:144-187` + shared context `128-142` |
| **loại** | prompt |
| **tóm tắt** | Netflix translator: line-by-line JSON `{origin, direct}` + context previous/next + theme + points to note |
| **OmniCast** | Writer viết script đích; **không** có bước faithfulness riêng khi localize |
| **khuyến nghị** | **GHÉP** khi multi-lang: bước 1 literal trước free rewrite |

```
## Role
You are a professional Netflix subtitle translator, fluent in both {src_language} and {TARGET_LANGUAGE}, as well as their respective cultures.
Your expertise lies in accurately understanding the semantics and structure of the original {src_language} text and faithfully translating it into {TARGET_LANGUAGE} while preserving the original meaning.

## Task
1. Translate the original {src_language} subtitles into {TARGET_LANGUAGE} line by line
2. Ensure the translation is faithful to the original, accurately conveying the original meaning
3. Consider the context and professional terminology

### Context Information
<previous_content>...</previous_content>
<subsequent_content>...</subsequent_content>
### Content Summary
{summary_prompt}
### Points to Note
{things_to_note_prompt}

<translation_principles>
1. Faithful to the original...
2. Accurate terminology...
3. Understand the context...
</translation_principles>
```

---

### 4. VideoLingo — expressiveness / reflect (tự do hoá)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:190-247` |
| **loại** | prompt |
| **tóm tắt** | Reflect `direct` → issues fluency/style/concision → free translation; cấm comment trong free |
| **OmniCast** | Critic có rubric style nhưng không 2-pass dịch subtitle |
| **khuyến nghị** | **GHÉP** mirror Critic: pass1 fidelity, pass2 spoken/natural + density for TTS |

```
## Role
You are a professional Netflix subtitle translator and language consultant.
...
1. Analyze the direct translation results line by line, pointing out existing issues
2. Provide detailed modification suggestions
3. Perform free translation based on your analysis
4. Do not add comments or explanations in the translation...
5. Do not leave empty lines in the free translation...

<Translation Analysis Steps>
1. Direct Translation Reflection:
   - Evaluate language fluency
   - Check if the language style is consistent with the original text
   - Check the conciseness of the subtitles, point out where the translation is too wordy
2. {TARGET_LANGUAGE} Free Translation:
   - Aim for contextual smoothness and naturalness...
   - Adapt the language style to match the theme (casual tutorials / technical / formal docs)
</Translation Analysis Steps>
```

**Cơ chế bật/tắt:** `reflect_translate: true` (`config.yaml:67`); nếu false chỉ dùng `direct` (`translate_lines.py:49-53`).

---

### 5. VideoLingo — align prompt (map split src ↔ tgt)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:252-298` |
| **loại** | prompt |
| **tóm tắt** | Căn bản dịch theo điểm cắt src; cho phép rewrite nhẹ; cấm empty line |
| **OmniCast** | Không có align bipartite subtitle |
| **khuyến nghị** | **GHÉP** nếu làm caption song ngữ / retime |

---

### 6. VideoLingo — subtitle trim (rút gọn cho TTS fit duration)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:302-339` · gọi từ `_8_1_audio_task.py:18-44` |
| **loại** | prompt + cơ chế |
| **tóm tắt** | Ước duration syllable; nếu > slot (sau speed max) → LLM rút filler/modifier; fallback strip punctuation |
| **OmniCast** | `tts.py` duration estimate `words * 0.4` — **không** trim text theo slot |
| **khuyến nghị** | **GHÉP** pre-TTS density gate cho short-form |

```
## Role
You are a professional subtitle editor, editing and optimizing lengthy subtitles that exceed voiceover time before handing them to voice actors.
...
Consider a. Reducing filler words without modifying meaningful content. b. Omitting unnecessary modifiers or pronouns, for example:
- "Please explain your thought process" → "Please explain thought process"
...
{"analysis": "...", "result": "Optimized and shortened subtitle in the original subtitle language"}
```

---

### 7. VideoLingo — TTS text clean prompt

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `core/prompts.py:343-364` |
| **loại** | prompt |
| **tóm tắt** | Retry lần cuối TTS: chỉ giữ `.,?!` |
| **OmniCast** | Không GPT-clean trước TTS fail |
| **khuyến nghị** | **GHÉP** sau 2 lần fail provider |

```
## Role
You are a text cleaning expert for TTS (Text-to-Speech) systems.
## Task
Clean the given text by:
1. Keep only basic punctuation (.,?!)
2. Preserve the original meaning
{"text": "cleaned text here"}
```

Cùng file: `clean_text_for_tts` xoá `& ® ™ ©`; empty/1-char → silent 100ms (`tts_main.py:18-33`).

---

### 8. VideoLingo — config tốc độ / phụ đề / ASR (verbatim keys)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `config.yaml:27-133` |
| **loại** | config |
| **tóm tắt** | Magic numbers sản xuất thật |
| **OmniCast** | LUFS loudnorm trong tts/render; không speed_factor dub |
| **khuyến nghị** | **THAY/GHÉP** các hằng align |

```yaml
whisper:
  model: 'large-v3'          # or large-v3-turbo; zh → Belle large-v3
  language: 'en'
  runtime: 'local'           # local | cloud | elevenlabs
subtitle:
  max_length: 75             # chars per line
  target_multiplier: 1.2     # translated lines "larger" for split threshold
summary_length: 8000
max_split_length: 20         # comment: <18 too fine for MT; >22 hard to align
reflect_translate: true
tts_method: 'azure_tts'
speed_factor:
  min: 1
  accept: 1.2                # max acceptable speed (soft)
  max: 1.4
min_subtitle_duration: 2.5   # force-extend short cues
min_trim_duration: 3.5       # don't split if shorter
tolerance: 1.5               # borrow gap into next slot (seconds)
max_workers: 4
```

WhisperX runtime (`asr_backend/whisperX_local.py:85-133`):
```python
batch_size = 16 if gpu_mem > 8 else 2   # cuda
compute_type = "float16" if bf16 else "int8"
vad_options = {"vad_onset": 0.500, "vad_offset": 0.363}
asr_options = {"temperatures": [0], "initial_prompt": ""}
```

Syllable duration defaults (`estimate_duration.py:10-17`):
```python
duration_params = {'en': 0.225, 'zh': 0.21, 'ja': 0.21, 'fr': 0.22, 'es': 0.22, 'ko': 0.21, 'default': 0.22}
pause = {'space': 0.15, 'default': 0.1}
```

Weighted char length for CJK split (`_5_split_sub.py:16-31`): zh/ja **1.75**, ko **1.5**, thai **1**, fullwidth **1.75**, else **1**.

---

### 9. VideoLingo — TTS engines (params)

| engine | file:line | params (verbatim) | OmniCast | rec |
|--------|-----------|-------------------|----------|-----|
| **edge** | `tts_backend/edge_tts.py:15-25` | voice default `en-US-JennyNeural` (cfg `zh-CN-XiaoxiaoNeural`); CLI `edge-tts --voice --text --write-media` — **no rate/pitch** | `tts_edge.py:55-56` rate `+0%` pitch `+0Hz`; sample **24k** | GHÉP expose rate/pitch từ channel |
| **azure** | `azure_tts.py:4-15` | SSML voice; `X-Microsoft-OutputFormat: riff-16khz-16bit-mono-pcm` | không Azure provider | BỎ QUA trừ khi cần enterprise |
| **openai** | `openai_tts.py:10-19` | model `tts-1`, `response_format: wav`, voices alloy/echo/…; retry decorator 3× delay1 | không | BỎ QUA / optional |
| **fish** | `fish_tts.py:12-19` | `chunk_length: 200`, `normalize: True`, `format: wav`, `latency: normal` | không | BỎ QUA |
| **gpt-sovits** | `gpt_sovits_tts.py:32-39` | local `9880/tts`, `speed_factor: 1.0`, refer_mode 1/2/3 (clone per-line) | XTTS/F5 clone khác API | GHÉP ý refer_mode 3 cho brand voice |
| **cosyvoice2** | `sf_cosyvoice2.py:38-44` | `FunAudioLLM/CosyVoice2-0.5B` + base64 ref audio+text | không | BỎ QUA |
| **tts_main** | `tts_main.py:42-80` | `max_retries=3`; last try GPT clean; duration==0 → retry / silent 100ms | VoiceRouter fallback chain, no per-line silent pad | GHÉP silent pad empty |

Export merge (`_11_merge_audio.py:41-48,119-127`):
```
ffmpeg -ar 16000 -ac 1 -b:a 64k  → final mp3 16k mono 64k
```

---

### 10. VideoLingo — align atempo + chunk logic (verbatim)

| field | value |
|-------|--------|
| **repo** | VideoLingo |
| **file:line** | `_10_gen_audio.py:30-63,125-211` · `_8_2_dub_chunks.py:15-24` |
| **loại** | config + ffmpeg |
| **tóm tắt** | Ước est_dur; merge lines nếu too fast; TTS; tính speed_factor chunk; `atempo`; truncate ≤0.6s overflow |
| **OmniCast** | Không proportional timing; TTS full script 1 shot |
| **khuyến nghị** | **THAY** nếu làm dub-over-video; **GHÉP** atempo util cho scene-timed VO |

```python
# speed flag
if est_dur / accept > tol_dur: return 2   # irreparable
elif est_dur > tol_dur: return 1          # need speedup
elif est_dur < duration - tolerance: return -1  # too slow
else: return 0

# ffmpeg atempo
cmd = ['ffmpeg', '-i', input_file, '-filter:a', f'atempo={atempo}', '-y', output_file]
# if output > expected*1.02 and input_dur < 3 and diff<=0.1 → trim
# chunk overflow >0.6s → Exception; ≤0.6s → truncate last wav
```

`process_chunk` logic (prefer keep gaps, then drop gaps, then use tol_dur):
```python
if (chunk_durs + all_gaps) / accept < durations:
    speed_factor = max(min_speed, (chunk_durs + all_gaps) / (durations - 0.1)); keep_gaps=True
elif chunk_durs / accept < durations:
    speed_factor = max(min_speed, chunk_durs / (durations - 0.1)); keep_gaps=False
# ...
```

Dub video merge (`_12_dub_to_vid.py:65-87`):
```
subtitles=...:force_style='FontSize=17,FontName=Arial,PrimaryColour=&H00FFFF,
  OutlineColour=&H000000,OutlineWidth=1,BackColour=&H33000000,Alignment=2,MarginV=27,BorderStyle=4'
amix=inputs=2:duration=first:dropout_transition=3
-c:a aac -b:a 96k
normalize_audio_volume target_db=-20.0
```

---

### 11. pyvideotrans — TTS registry (int ID + ChannelProvider)

| field | value |
|-------|--------|
| **repo** | pyvideotrans |
| **file:line** | `videotrans/tts/__init__.py:1-185` |
| **loại** | config / registry |
| **tóm tắt** | 32 channel constants 0–31; lazy `get_class`; `SUPPORT_CLONE`, `CHANGE_BY_LANGUAGE`; `is_allow_lang` per engine |
| **OmniCast** | `providers/registry.py` + string `provider:voice`; ít engine; **có** fallback chain (pyvideotrans: 1 engine/job) |
| **khuyến nghị** | **GHÉP** is_allow_lang + SUPPORT_CLONE metadata; giữ OmniCast fallback |

```python
EDGE_TTS = 0
...
TTS_API = 31
SUPPORT_CLONE = [COSYVOICE, CLONE_VOICE, F5, INDEX, VOXCPM, SPARK, DIA, CHATTERBOX, GPTSOVITS, ...]
CHANGE_BY_LANGUAGE = [EDGE, MINIMAXI, AZURE, DOUBAO2, AI302, KOKORO, PIPER, VITS]
# run() → get_class(tts_type, "tts", _ID_NAME_DICT)(**kwargs).run()
```

---

### 12. pyvideotrans — BaseTTS defaults (rate/pitch/volume/threads)

| field | value |
|-------|--------|
| **repo** | pyvideotrans |
| **file:line** | `tts/_base.py:43-55,228-255` |
| **loại** | config |
| **tóm tắt** | Defaults edge-format; optional zh/en TextNorm; wait_sec giữa dòng |
| **OmniCast** | edge defaults `+0%`/`+0Hz`; Kokoro speed clamp 0.5–1.5; **không** cn_tn/en_tn |
| **khuyến nghị** | **GHÉP** normal_text pipeline + per-line wait |

```python
volume = '+0%'   # edge-tts format
rate = '+0%'
pitch = '+0Hz'
wait_sec = float(settings.get('dubbing_wait', 0))  # default settings: 1
dub_nums = int(settings.get('dubbing_thread', 1))
# normalizer: cn_tn.TextNorm(to_banjiao=True) | en_tn.EnglishNormalizer if normal_text
```

EdgeTTS concurrency (`_edgetts.py:18-23,63-71`):
```python
MAX_CONCURRENT_TASKS = settings.get('edgetts_max_concurrent_tasks', 10)  # default 10
RETRY_NUMS = settings.get('edgetts_retry_nums', 3) + 1
RETRY_DELAY = 5
SAVE_TIMEOUT = 30
Communicate(text, voice=role, rate=..., volume=..., pitch=..., connect_timeout=5)
```

OpenAI TTS (`_openaitts.py:24-34`): tenacity `retry_nums` (default settings **1**), `wait_fixed(2)`, `speed=get_speed()` from rate%, wav stream.

---

### 13. pyvideotrans — settings defaults (VAD / Whisper / subtitle / align)

| field | value |
|-------|--------|
| **repo** | pyvideotrans |
| **file:line** | `configure/config.py:343-458` |
| **loại** | config |
| **tóm tắt** | Bảng hằng production |
| **OmniCast** | không VAD/max_speech pipeline |
| **khuyến nghị** | **GHÉP** cjk_len/other_len khi format caption |

```python
"edgetts_max_concurrent_tasks": 10,
"edgetts_retry_nums": 3,
"max_audio_speed_rate": 100,      # rubberband/atempo cap (very high)
"max_video_pts_rate": 10,
"threshold": 0.5,
"min_speech_duration_ms": 2000,
"max_speech_duration_s": 5,       # 1st pass ASR segment cap
"min_speech_duration_ms2": 1000,
"max_speech_duration_s2": 2,      # 2nd pass short cues
"min_silence_duration_ms": 140,
"no_speech_threshold": 0.6,
"vad_type": "silero",
"trans_thread": 10,
"aitrans_thread": 50,
"dubbing_wait": 1,
"dubbing_thread": 1,
"normal_text": False,
"remove_dubb_silence": True,
"backaudio_volume": 0.8,
"beam_size": 5,
"best_of": 5,
"condition_on_previous_text": False,
"compression_ratio_threshold": 2.4,
"cjk_len": 15,                    # max chars/line CJK
"other_len": 40,                  # max chars/line alphabetic
"llm_chunk_size": 50,
"aitrans_temperature": 0.1,
"retry_nums": 1,
```

Whisper kwargs (`recognition/_whisper.py:62-83`):
```python
_max_speech = max(int(max_speech_duration_s * 1000), 2000)
# recogn2pass → max_speech_duration_s2, min 500ms
no_speech_threshold, condition_on_previous_text, temperature,
compression_ratio_threshold, max_speech_ms
```

SRT text helpers (`util/help_srt.py:9-33,62-80`):
- Non-SRT text: split lines >**50** chars on `[,.，。]`
- `cleartext`: strip `&#39;` `&quot;` `\u200b`; collapse multi-punct → `,`
- `delete_punc`: keep decimal points

---

### 14. pyvideotrans — SpeedRate align (core algorithm + ffmpeg)

| field | value |
|-------|--------|
| **repo** | pyvideotrans |
| **file:line** | `task/_rate.py:1-66` (doc), `209-286`, `451-516`, `639-705` |
| **loại** | config + mechanism |
| **tóm tắt** | Pre-fill gaps end→next start; audio only / video only / both (ratio≤1.2 audio only; else split half); rubberband else chained atempo; setpts video |
| **OmniCast** | Không |
| **khuyến nghị** | **THAY** module align nếu làm video dub; else **GHÉP** audio-only TtsSpeedRate cho timed SRT VO |

```
## Audio + Video both:
if dubb > source:
  ratio = dubb/source
  if ratio <= 1.2: audio_target = video_target = source
  else: joint = source + (diff/2); both target = joint

## Audio only:
if ratio > max_audio_speed_rate: audio_target = dubb / max_rate
else: audio_target = source

## Video only: video_target = min(dubb, source * max_video_pts_rate)
```

Rubberband:
```python
time_stretch_rate = max(0.2, min(current/target, 50.0))
y_stretched = pyrb.time_stretch(y, sr, time_stretch_rate)
```

Fallback atempo chain (`_rate.py:247-278`):
```python
# atempo param must be in [0.5, 2.0] — chain while >2.0
filter_str = "atempo=2.0,atempo=..."  # e.g.
cmd = ['-y','-i',input,'-filter:a',filter_str,'-t', f"{target/1000}",
       '-ar','48000','-ac','2','-c:a','pcm_s16le', f'{input}-after.wav']
```

Video cut (`_rate.py:125-147`):
```
-ss ... -t source_s -an -c:v libx264 -g 1 -preset veryfast -crf 20 -pix_fmt yuv420p
-vf setpts={pts+0.005}*PTS   # or setpts=PTS
-fps_mode vfr | -r fps -fps_mode cfr
-t target_s
# invalid clip < 1024 bytes → backup cut without speed
```

Audio concat sample: **48000 Hz stereo**.  
`TtsSpeedRate`: force accelerate to slot, **no max rate limit** (`max_audio_speed_rate=100`).

---

### 15. pyvideotrans — prompt dịch SRT (dubbing-safe)

| field | value |
|-------|--------|
| **repo** | pyvideotrans |
| **file:line** | `prompts/srt/chatgpt.txt` (toàn file; azure/deepseek/gemini… cùng pattern) |
| **loại** | prompt |
| **tóm tắt** | 1-to-1 block, zero-shift, aggressive compression, CJK 2.5–3.5 syl/s, ellipsis bridge, spoken register |
| **OmniCast** | Writer không có density-by-duration rule |
| **khuyến nghị** | **GHÉP** vào multi-lang writer system prompt (phần DUBBING-SAFE PACING) |

```
# ROLE
You are an expert "Multilingual Dubbing Script Adapter" and "SRT Formatter".
...
## 1. DUBBING-SAFE PACING & CONCISENESS
- Aggressive Compression...
- Alphabetic: contractions, short synonyms
- CJK: 2.5–3.5 pronounced syllables per second of the block's duration
- Abugida: avoid long compounds...
## 2. ABSOLUTE 1-TO-1 BLOCK MAPPING & "ZERO-SHIFT" RULE
- MUST NOT merge blocks; MUST NOT shift semantic elements between blocks
- Ellipsis Bridging (`...`) for mid-clause
## 3. SPOKEN REGISTER & LOCALIZATION
...
# OUTPUT only inside <TRANSLATE_TEXT>...</TRANSLATE_TEXT>
```

Translator batching (`translator/_base.py:37-73`):
- Text mode: batches of `trans_thread` (default 10)
- AI SRT mode: `aitrans_thread` (50) or full list if `aitrans_context`
- `aisendsrt` default True

---

### 16. OmniCast baseline (đối chứng)

| module | file:line | hiện trạng |
|--------|-----------|------------|
| VoiceRouter | `voice_router.py:1-246` | `provider:voice` parse; market pools; ordered fallback; **no** low-quality last resort |
| TTSModule | `tts.py:32-98` | chain + loudnorm `I={target}:TP=-1.5:LRA=11` → **24k** |
| Edge provider | `tts_edge.py:48-103` | rate/pitch defaults; WordBoundary → `.words.json`; ffmpeg 24k |
| Kokoro | `tts_local.py:110-132` | speed clamp **0.5–1.5**, default 1.0 |
| Subtitle | `subtitle.py:17-58` | **placeholder** segments; format SRT only — **không** WhisperX thật, **không** align dub |

---

## Cơ chế OmniCast thiếu hoặc yếu hơn

| cơ chế | repo nguồn (file:line) | OmniCast (file:line) | mức | việc phải làm |
|--------|------------------------|----------------------|-----|---------------|
| 2-pass dịch faithfulness→express + glossary | VL `prompts.py:144-247`, `_4_2_translate.py:54-57` chunk 600/10 | Writer 1-pass | **CAO** | Pipeline localize: terms → faith → free; optional Critic pass density |
| Dubbing-safe density (CJK syl/s, zero-shift) | PVT `prompts/srt/chatgpt.txt` | Không | **CAO** | Inject vào multi-lang writer/critic rubric |
| Pre-TTS trim by estimated duration | VL `_8_1_audio_task.py:18-44` | `tts.py:60-61` words*0.4 only | **CAO** | Syllable estimator + trim prompt before TTS |
| Proportional audio align (atempo/RB + gap borrow) | VL `_10_gen_audio.py`; PVT `_rate.py` | Không | **CAO** (nếu dub video) / **TRUNG** (nếu chỉ VO) | Port `SpeedRate` audio-only hoặc VL chunk atempo |
| TTS registry metadata (lang allow, clone flags) | PVT `tts/__init__.py` | registry string IDs only | **TRUNG** | Annotate providers: langs, clone?, rate API shape |
| Fallback chain multi-provider | OmniCast **mạnh hơn** `voice_router.py` | PVT 1 engine/job | — | Giữ OmniCast; học per-engine caps từ PVT |
| Text normalization CN/EN for TTS | PVT `_base.py:228-243`, `util/cn_tn.py` | Không | **TRUNG** | Optional normalizer before generate |
| Edge concurrency + retry + timeout | PVT `_edgetts.py:18-71` | Edge 1 request, no retry | **TRUNG** | Semaphore + 3 retry + 30s timeout |
| Subtitle max line length CJK/latin | PVT cjk_len=15 other_len=40; VL max_length=75 + weight | subtitle placeholder | **CAO** | Real caption packer + weights |
| WhisperX real ASR + VAD + beam | VL whisperX_local; PVT settings beam 5 | subtitle.py stub | **CAO** | Implement subtitle.py per doc or delete claim |
| Post-TTS clean on failure | VL `get_correct_text_prompt` | Fail chain only | **THẤP** | Clean once before last provider |
| Video setpts slow-down | PVT `_rate.py` | Không | **THẤP** (out of scope YouTube-native) | Chỉ khi feature dub-import video |
| WordBoundary captions prefer TTS timing | OmniCast `tts_edge.py:77-102` | **mạnh hơn** VL/PVT | — | Giữ; wire vào subtitle module |
| LUFS loudnorm | OmniCast `tts.py:84` I=target | VL peak normalize -20dBFS | — | Giữ OmniCast (chuẩn hơn) |
| 1-to-1 SRT batch translate validation | VL length match; PVT block count | Không | **TRUNG** | Validator khi import/translate SRT |

### Trả lời 3 nghi vấn brief

**1. Chuỗi VideoLingo hơn gì OmniCast writer thẳng?**  
Writer OmniCast tối ưu narrative YouTube (hook, structure, compliance), **không** giải bài toán: (a) giữ 1-1 cue video, (b) term consistency, (c) density TTS trong slot thời gian, (d) reflect naturalness sau literal.  
**Bước đáng ghép:**  
- Glossary/terms (summarize) → channel style bible đa ngôn ngữ  
- Faithfulness → Expressiveness 2-pass **khi localize** (không thay writer gốc)  
- Trim-for-duration trước TTS  
- Critic rubric: “speakable within N seconds / syl-per-sec CJK”

**2. pyvideotrans TTS vs voice_router**  
PVT: **registry int → lazy class**, `is_allow_lang`, clone set, BaseTTS rate/pitch/volume/normalizer/thread/wait, per-engine retry (tenacity/edge semaphore). **Không** multi-provider fallback trong 1 job.  
OmniCast: **fallback chain** + market voice pools + quality gate — tốt hơn cho 24/7 channel.  
**Thiếu/yếu OmniCast:** per-engine concurrency caps, text-norm, lang allowlist, timing proportional, char/chunk limits, TTS clean retry.

**3. Sync phụ đề↔audio↔video vs subtitle.py**  
VL: retime SRT theo `new_sub_times` sau atempo; burn ASS style.  
PVT: `SpeedRate` rewrite `start_time/end_time` theo slot audio/video thực.  
OmniCast `subtitle.py`: stub cố định 0–5s — **không** sync. Edge `.words.json` là asset mạnh nhất hiện có nhưng **chưa** consume trong SubtitleModule.

---

## TOP-15 PATCH

1. **Implement SubtitleModule thật** (WhisperX hoặc prefer Edge WordBoundary) — `media/subtitle.py`.  
2. **Caption line packer** cjk_len=15 / other_len=40 + VL char weights — `media/subtitle.py` + util.  
3. **Inject dubbing-safe pacing** (PVT srt prompt density rules) vào multi-lang writer system — `agents/writer.py` / prompts.  
4. **2-pass localize** faith→free + glossary JSON — new `agents/localize.py` hoặc pipeline step.  
5. **Syllable duration estimator** port VL `estimate_duration.py` — `media/tts_timing.py`.  
6. **Pre-TTS trim prompt** khi est > slot — `media/tts.py` / orchestrator.  
7. **Audio-only SpeedRate** (atempo chain + gap fill) cho timed SRT VO — port PVT `_rate.py` subset.  
8. **Edge retry/semaphore** (10 concurrent, 3 retry, 30s) — `providers/tts_edge.py`.  
9. **TTS text normalizer** (en_tn/cn_tn optional + clean punct) — `media/tts.py`.  
10. **Provider metadata** langs/clone/rate-format on registry — `providers/registry.py`.  
11. **GPT/text clean on last TTS fail** — `voice_router.py`.  
12. **Expose rate/pitch/speed** from channel config through VoiceRouter → providers.  
13. **Wire `.words.json` → SRT** (skip Whisper when Edge) — `subtitle.py`.  
14. **Chunk/batch translate SRT** with 1-1 length validation if feature import video — pipeline optional.  
15. **Update IMPLEMENTATION_STATUS.md** sau khi implement (không trong research này).

---

## Phụ lục — Map file nhanh

| Chủ đề | VideoLingo | pyvideotrans | OmniCast |
|--------|------------|--------------|----------|
| Prompts dịch | `core/prompts.py` | `prompts/srt/*.txt`, `prompts/text/*.txt` | agents/* |
| Config | `config.yaml` | `configure/config.py` Settings | channel JSON + settings |
| TTS entry | `tts_backend/tts_main.py` | `tts/__init__.run` + `_base.py` | `tts.py` + `voice_router.py` |
| Align | `_8_2_`, `_10_`, `_11_` | `task/_rate.py` | — |
| ASR | `asr_backend/whisperX_local.py` | `recognition/_whisper.py` | `subtitle.py` stub |
| SRT util | `_6_gen_sub.py` | `util/help_srt.py` | `subtitle.py` |

---

*Harvest date: 2026-08-04 · Chỉ đọc `_refs/` · Không sửa code nguồn tham chiếu.*
