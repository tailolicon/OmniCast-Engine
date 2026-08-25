# V2_A2 — Voice Suite & Cap Assistant

> STATUS: ACTIVE  
> Chiến dịch V2 · Nhóm A2 · Verbatim harvest + cơ chế  
> Nguồn (CHỈ ĐỌC): `_refs/voice-pro/`,  
> `_refs/Cap Assistant - REUP (CÓ CHỨC NĂNG DỊCH VÀ LỒNG TIẾNG)/`,  
> `_refs/Cap Assistant Pro - CONTENT - Available for FREE USER/`  
> Đối chiếu OmniCast: `implementation/src/omnicast/media/{tts,voice_router,models}.py` + `providers/tts_*.py`  
> Ghi chú: Cap Assistant là app đóng gói (PyInstaller/Nuitka + `.exe` ~45–296MB). Verbatim lấy từ **assets JSON**, **Hướng dẫn .docx**, **strings nhúng trong EXE**, và (Pro) **transition_pool**. Không khuyến nghị dùng tính năng gắn nhãn **RỦI RO CHÍNH SÁCH**.

---

## Pipeline tóm tắt (Tầng 2 — ngữ cảnh)

### voice-pro (`_refs/voice-pro`)
```
text|SRT → AbusText.normalize_text + split_into_sentences
  → engine TTS (Edge / Azure SSML / Kokoro / F5 / CosyVoice / RVC)
  → AbusAudio.trim_silence (dBFS -50, padding 100ms)
  → ffmpeg stereo + (optional) SRT timeline silence-pad
  → CosyVoice frontend: TN (zh/en) + split_paragraph token_max=80
```

### Cap Assistant REUP v3.31 (`capassistant.exe`)
```
video → (Cloud STT VIP / local) → SRT gốc
  → SmartSubtitlePipeline / chunk translate (Gemini multi-account)
  → Auto Master TTS (Piper local VN + Edge Neural + TikTok voice ids)
  → FFmpeg assembly (setpts/atempo/crop/hflip/noise/…) → CapCut draft / export
```
Tiers strings: `FREE | PRO | PROMAX | ULTRA`. Hướng dẫn: PRO 349K/tháng, ULTRA 499K/tháng; ULTRA “byPass lách bản quyền”.

### Cap Assistant Pro CONTENT v3.8 (`CapAssistantPro-v3.8.exe`)
```
topic|idea|YT-link|raw script
  → LLM master prompt → JSON scenes (SRT + Prompts[] + I2V_Prompt)
  → TTS VO (speed sync) + image/I2V gen (Gemini / VEO3 studio)
  → CapCutDraftManager inject tracks (audio/images/sub/transitions)
  → export CapCut
```
Free-user gate: “Tự Động Cào Kịch Bản (AI Studio)” / copy prompt strategy = **PRO+ULTRA only**.

### OmniCast (hiện trạng)
```
Writer script → TTSModule → VoiceRouter (provider:voice chain)
  → optional loudnorm I=-14 TP=-1.5 LRA=11
  → NO text-normalize before TTS; NO sentence-chunk; NO silence-trim per segment
```

---

## Bảng VERBATIM

### 1. voice-pro — `AbusText.normalize_text` (chuẩn hoá trước TTS)

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_text.py:245-289` |
| **loại** | config / logic pipeline |
| **tóm tắt** | Lọc unicode, bỏ ngoặc, `&→and`, `%→percent`, `km→kilometers`, gộp dấu, gỡ lặp từ, collapse space |
| **OmniCast** | `media/tts.py` + `voice_router.synthesize` truyền `text` thô — **không** normalize |
| **khuyến nghị** | **GHÉP** module `text_normalize_for_tts()` trước mọi provider |

```python
# app/abus_text.py:245-289 (trích)
@classmethod
def normalize_text(cls, text) -> str:
    currency_symbols = '₩$€£¥₹₽₺₴₱'
    allowed_categories = {
        'Lu', 'Ll', 'Lt', 'Lm', 'Lo',
        'Nd', 'Nl', 'No',
        'Pc', 'Pd', 'Ps', 'Pe', 'Pi', 'Pf', 'Po',
        'Zs', 'Mn', 'Mc'
    }
    # 1. remove (), [], {}
    cleaned_text = re.sub(r'\([^()]*\)', '', text)
    cleaned_text = re.sub(r'\[.*?\]', '', cleaned_text)
    cleaned_text = re.sub(r'\{.*?\}', '', cleaned_text)
    # 2. symbols / abbr
    cleaned_text = re.sub(r'(\bMr)\.', r'\1', cleaned_text)
    cleaned_text = re.sub(r'&', ' and ', cleaned_text)
    cleaned_text = re.sub(r'%', ' percent', cleaned_text)
    cleaned_text = re.sub(r'(\d+)km', r'\1 kilometers', cleaned_text)
    # 3. unicode category filter (giữ currency)
    # 4. collapse !!! → !  and  ... → .
    # 5. remove repeated word + multi-space
    cleaned_text = re.sub(r'\b(\w+)\s+\1\b', r'\1', cleaned_text)
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text
```

---

### 2. voice-pro — sentence split đa ngôn ngữ + abbreviation list

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_text.py:16-99`, `178-201` |
| **loại** | config |
| **tóm tắt** | Bảng dấu kết câu CJK/Arabic/Hindi; pattern Mr./U.S.A./etc.; split regex `[.。．!！?？۔।॥]+[\s$]` |
| **OmniCast** | TỰ CHẾ – không chunk; Edge/Kokoro nhận full script một shot |
| **khuyến nghị** | **GHÉP** split-by-sentence trước TTS dài (>~500 ký tự) |

```python
SENTENCE_ENDING_MARKS = {'.', '。', '．', '!', '！', '?', '？', '۔', '।', '॥'}
COMMON_ABBREVIATIONS = {
    'Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'Inc.', 'Co.', 'Ltd.',
    'U.S.', 'U.S.A.', 'E.g.', 'i.e.', 'etc.', 'vs.', 'Dept.'
}
ABBREVIATION_PATTERNS = [
    r'\b([A-Z]\.)+[A-Z]?\b',
    r'\b(Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Sr\.|Jr\.)\b',
    r'\b(Inc\.|Corp\.|Ltd\.|Co\.)\b',
    r'\b(e\.g\.|i\.e\.|vs\.)\b',
]
# split_into_sentences:
sentence_ends = re.compile(r'[.。．!！?？۔।॥]+[\s$]')
```

---

### 3. voice-pro — SRT merge/split cho TTS (gap < 500ms)

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_text.py:301-368` |
| **loại** | config |
| **tóm tắt** | Tách event theo dấu kết/JP separators; gộp nếu gap < 500ms và chưa kết câu; JP min length 5 |
| **OmniCast** | `subtitle.py` placeholder — không pipeline TTS-from-SRT production |
| **khuyến nghị** | **GHÉP** nếu làm dub-from-SRT; **BỎ QUA** nếu chỉ TTS script gốc |

```python
# merge condition
gap = event.start - current_event.end
if (gap < 500 and
    not any(current_event.text.rstrip().endswith(mark)
            for mark in cls.SENTENCE_ENDING_MARKS)):
    current_event.text += " " + event.text
    current_event.end = event.end
JAPANESE_SEPARATORS = {'でも', 'だし', 'から', 'ので'}  # min len 5 before split
```

---

### 4. voice-pro — trim silence (khử “click/pop” đầu-cuối đoạn)

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_audio.py:35-98` |
| **loại** | config |
| **tóm tắt** | dBFS threshold −50, chunk 10ms, padding đuôi 100ms — gọi sau mọi TTS engine |
| **OmniCast** | Chỉ `loudnorm` global (`tts.py:75-88`); **không** trim silence per segment |
| **khuyến nghị** | **GHÉP** trim silence trước concat / sau mỗi chunk TTS |

```python
def trim_silence_audio(..., start_silence_threshold=-50.0,
                       end_silence_threshold=-50.0,
                       chunk_size=10, padding_duration=100):
    # scan dBFS > threshold; export + silent padding 100ms
```

---

### 5. voice-pro — Edge TTS prosody defaults (UI + user config)

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/tab_tts_edge.py:57-59`, `app/config-user.json5:47-49`, `app/abus_tts_edge.py:29-35` |
| **loại** | config |
| **tóm tắt** | pitch −400..+400 Hz step 10; rate −100..+200 %; volume −100..+100 %; default 0 |
| **OmniCast** | `tts_edge.py:55-56` `rate="+0%"`, `pitch="+0Hz"` — có param nhưng **không** channel-level UX / không volume |
| **khuyến nghị** | **GHÉP** `voice_prosody: {rate,pitch,volume}` vào channel JSON |

```json5
// config-user.json5
edge_tts_pitch: 0,
edge_tts_rate: 0,
edge_tts_volume: 0,
```
```python
# tab_tts_edge.py
edge_tts_pitch = gr.Slider(-400, 400, value=0, step=10, label="Pitch(Hz)")
edge_tts_rate  = gr.Slider(-100, 200, value=0, step=1,  label="Speech rate")
edge_tts_volume= gr.Slider(-100, 100, value=0, step=1,  label="Speech volume")
# abus_tts_edge.py
rate_options   = f'+{rate}%' if rate>=0 else f'{rate}%'
pitch_options  = f'+{pitch}Hz' if pitch>=0 else f'{pitch}Hz'
communicate = edge_tts.Communicate(text, voice, rate=..., volume=..., pitch=...)
```

---

### 6. voice-pro — Azure SSML prosody + 48kHz mp3

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_tts_azure.py:51-71` |
| **loại** | config / prompt-like SSML |
| **tóm tắt** | SSML `<prosody rate volume pitch>`; output `Audio48Khz192KBitRateMonoMp3` |
| **OmniCast** | Không Azure Speech; chỉ Edge/Kokoro/XTTS/F5 |
| **khuyến nghị** | **BỎ QUA** trừ khi cần Azure commercial SLA |

```python
ssml = f"""
...
    <prosody rate="{rate_options}" volume="{volume_options}" pitch="{pitch_options}">
...
"""
SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
```

---

### 7. voice-pro — Kokoro speed range + default voice

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/tab_tts_kokoro.py:32,56`, `app/abus_tts_kokoro.py:71-103` |
| **loại** | config |
| **tóm tắt** | speed 0.3–2.0 default 1.0; voice UI default `Heart ❤️`; `split_pattern=None`; sample 24kHz; normalize_text trước gen |
| **OmniCast** | `kokoro:af_heart` default; **không** expose speed slider; **không** normalize |
| **khuyến nghị** | **GHÉP** speed 0.3–2.0 per channel; **GHÉP** normalize |

```python
kokoro_tts_speed = gr.Slider(0.3, 2.0, value=1.0, step=0.1)
generator = pipeline(line, voice=kokoro_voice.voice_code, speed=speed_factor, split_pattern=None)
sf.write(output_voice_file, audio, 24000)
```

---

### 8. voice-pro — F5 models catalog + speed

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_tts_f5_models.json` (full), `tab_tts_f5_single.py:54-55` |
| **loại** | config |
| **tóm tắt** | Catalog F5 base/v1 + FI/FR/HI/IT/JA/RU/ES; speed 0.3–2.0; default model `SWivid/F5-TTS_v1` |
| **OmniCast** | Có provider F5/XTTS clone path qua router — catalog model chưa phong phú bằng |
| **khuyến nghị** | **GHÉP** model id map nếu clone đa ngôn ngữ |

```json
{
  "SWivid/F5-TTS_v1": {
    "model_path": "hf://SWivid/F5-TTS/F5TTS_v1_Base/model_1250000.safetensors",
    "vocab_path": "hf://SWivid/F5-TTS/F5TTS_v1_Base/vocab.txt",
    "config": {"dim": 1024, "depth": 22, "heads": 16, "ff_mult": 2, "text_dim": 512, "conv_layers": 4}
  }
  // + Finnish, French, Hindi, Italian, Japanese, Russian, Spanish variants
}
```

---

### 9. voice-pro — CosyVoice text frontend (TN + chunk)

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `cosyvoice/cli/frontend.py:121-149`, `cosyvoice/utils/frontend_utils.py:26-117` |
| **loại** | config |
| **tóm tắt** | zh: WeTextProcessing TN; en: EnNormalizer + inflect spell numbers; split token_max_n=80, token_min_n=60, merge_len=20; ²→平方, ³→立方; strip brackets |
| **OmniCast** | **Thiếu hẳn** TN số/ngày; script số “2024” đọc kém trên một số voice |
| **khuyến nghị** | **GHÉP** spell-out numbers + paragraph chunk (80 token) cho script dài |

```python
# frontend_utils.py
def replace_corner_mark(text):
    text = text.replace('²', '平方')
    text = text.replace('³', '立方')
    return text

def split_paragraph(text, tokenize, lang="zh",
                    token_max_n=80, token_min_n=60, merge_len=20, comma_split=False):
    ...
# frontend.py text_normalize
texts = list(split_paragraph(..., "en", token_max_n=80, token_min_n=60, merge_len=20))
text = spell_out_number(text, self.inflect_parser)
```

---

### 10. voice-pro — CosyVoice emotion / language special tokens

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `cosyvoice/tokenizer/tokenizer.py:31`, `150-156`, `184` |
| **loại** | config |
| **tóm tắt** | LANGUAGES gồm `"vi": "vietnamese"`; EMOTION HAPPY/SAD/ANGRY/NEUTRAL |
| **OmniCast** | Không emotion tag TTS; VN chỉ qua Edge `vi-VN-*` |
| **khuyến nghị** | **GHÉP** emotion meta nếu engine hỗ trợ; không bịa emotion cho Edge |

```python
"vi": "vietnamese",
EMOTION = {"HAPPY": "HAPPY", "SAD": "SAD", "ANGRY": "ANGRY", "NEUTRAL": "NEUTRAL"}
```

---

### 11. voice-pro — MS/Edge voice catalog (tiếng Việt)

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/abus_voice_ms.py:529-530` (+ full `MS_VOICES` list ~220 entries từ `af-ZA`…`zu-ZA`) |
| **loại** | config |
| **tóm tắt** | `vi-VN-HoaiMyNeural` Female, `vi-VN-NamMinhNeural` Male — khớp OmniCast |
| **OmniCast** | `voice_router.py:63` `VN: edge:vi-VN-HoaiMyNeural` / `NamMinhNeural` — **đã có** |
| **khuyến nghị** | **BỎ QUA** (đã đồng bộ); mở rộng pool nếu cần |

```python
MSVoice('vi-VN-HoaiMyNeural', 'Female'),
MSVoice('vi-VN-NamMinhNeural', 'Male'),
```

---

### 12. voice-pro — RVC / karaoke / compression defaults

| field | value |
|-------|--------|
| **repo** | voice-pro |
| **file:line** | `app/config-user.json5` full |
| **loại** | config |
| **tóm tắt** | pitch_change 0; index_rate 0.5; filter_radius 3; rms_mix 0.25; protect 0.33; rvc_protect 0.23; compression_crf 23 preset medium; reverb wet 0.2 dry 0.8 |
| **OmniCast** | Không RVC/AI-cover (đúng hướng — tránh clone celebrity without rights) |
| **khuyến nghị** | **BỎ QUA** RVC cho product; compression CRF tham khảo render |

```json5
pitch_change: 0,
index_rate: 0.5,
filter_radius: 3,
rms_mix_rate: 0.25,
protect: 0.33,
rvc_protect: 0.23,
rvc_hop_length: 256,
rvc_clean_strength: 0.2,
compression_enable: true,
compression_crf: 23,
compression_preset: "medium",
reverb_rm_size: 0.15,
reverb_wet: 0.2,
reverb_dry: 0.8,
reverb_damping: 0.7,
```

---

### 13. Cap REUP — user_config / watermark branding

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `assets/user_config.json` (extracted) |
| **loại** | config |
| **tóm tắt** | Watermark text `@CapAssistantPro`, logo presets, CapCut draft path, tts_sync, lang=vi, ElevenLabs keys slots empty |
| **OmniCast** | Brand overlay channel JSON — khác mô hình CapCut inject |
| **khuyến nghị** | **GHÉP** ý “wm_text + use_wm” chỉ cho brand hợp pháp; **không** copy path CapCut |

```json
{
  "static_text": "CAPASSISTANT  PRO",
  "use_logo": false,
  "use_text": true,
  "use_wm": true,
  "wm_text": "@CapAssistantPro",
  "tts_sync": false,
  "lang": "vi",
  "capcut_draft_path": "C:\\Users\\...\\CapCut\\User Data\\Projects\\com.lveditor.draft"
}
```

---

### 14. Cap REUP — pricing / setup tips (Hướng dẫn .docx)

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `_refs/.../Hướng dẫn nè.docx` (text extract) |
| **loại** | config / tip vận hành |
| **tóm tắt** | Gói PRO 349K, ULTRA 499K/tháng; ULTRA = bypass bản quyền + server; install fonts; login TikTok (TTS tab) + Google (dịch SRT) |
| **OmniCast** | Không có SaaS tier |
| **khuyến nghị** | **Ghi nhận** tier model; **BỎ QUA** bypass (RỦI RO CHÍNH SÁCH) |

```
GÓI PRO: 349K / THÁNG
GÓI ULTRA: 499K / THÁNG
ULTRA HƠN PRO ở 4 tính năng byPass lách bản quyền và được nhiều tài nguyên SERVER hơn

ĐĂNG NHẬP TIKTOK (TAB TEXT TO SPEECH)
ĐĂNG NHẬP GOOGLE (TAB TOOL DỊCH SRT)
```

---

### 15. Cap REUP — free-tier limits (strings EXE)

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `capassistant.exe` strings (offset ~263MB region) |
| **loại** | config |
| **tóm tắt** | FREE: chỉ video ngang landscape; dọc/vuông (Reels/TikTok/Shorts) yêu cầu upgrade; limit phút/tài khoản; tiers FREE/PRO/PROMAX/ULTRA |
| **OmniCast** | TỰ CHẾ – không free-tier gate |
| **khuyến nghị** | **Ghi nhận** product packaging; **BỎ QUA** copy logic license |

```
Tiers: FREE | PRO | PROMAX | ULTRA
"Tài khoản FREE chỉ hỗ trợ xử lý Video Ngang (Landscape).
 Video dọc/vuông (Reels, TikTok, Shorts) ... yêu cầu nâng cấp"
```

---

### 16. Cap REUP — TTS voice presets (Piper VN + Edge + TikTok ids)

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `capassistant.exe` strings |
| **loại** | config |
| **tóm tắt** | Piper: manhdung, minhkháng, phuongtrang, ngochuyen, maiphuong, thanhphuong2…; Edge: vi-VN-HoaiMy/NamMinh, en-US-Jenny/Guy, ko/ja/th/fr/de/es…; TikTok voice ids `en_us_001`… |
| **OmniCast** | Edge VN đã có; **không** Piper offline VN; **không** TikTok TTS login |
| **khuyến nghị** | **GHÉP** Piper VN offline optional provider; **BỎ QUA** TikTok unofficial TTS (ToS) |

```
Piper - Minh Khang (Nam) / Phương Trang (Nữ) / Ngọc Huyền / Mai Phương / Mạnh Dũng / Thanh Phương
EDGE VN - Hoài My  → vi-VN-HoaiMyNeural
EDGE VN - Nam Minh → vi-VN-NamMinhNeural
Nữ - Truyền cảm (Jessie) → en_us_001 + en-US-JennyNeural
Nam - Năng động (Chris)  → en_us_002 + en-US-GuyNeural
```

---

### 17. Cap REUP — FFmpeg transform graph (reup effects)

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `capassistant.exe` strings (`setpts`/`atempo`/`hflip`/`crop`/`noise`) |
| **loại** | config |
| **tóm tắt** | Speed video `setpts=f*PTS` + audio `atempo`; crop center; hflip; rotate; eq brightness/contrast; noise; dynamic crop sin/cos |
| **OmniCast** | Render gốc; không “unique-ify” reup |
| **khuyến nghị** | **Ghi nhận** kỹ thuật; các gói “bypass fingerprint” = **RỦI RO CHÍNH SÁCH** — **không** port |

```
[0:v]setpts=N/FRAME_RATE/TB[v_pts]
]setpts={speed}*PTS[vspd]
]atempo={speed}[aspd]
]crop=iw/…:ih/…:(iw-iw/…)/2:(ih-ih/…)/2,scale=…[vz]
]hflip[vf]
]rotate={deg}*PI/180…
]eq=brightness=…:contrast=…
]noise=alls=…
]crop=iw-2:ih-2:'min(2,max(0,1+sin(t*2)))':…  # micro jitter
```

**RỦI RO CHÍNH SÁCH** (strings UI REUP — chỉ ghi nhận):

```
1. Phantom Sub-Pixel Shift
2. Dynamic Temporal Noise
3. Micro Color-Space Shift
4. Tempo Shift & Audio Mask
5. Asymmetric GOP Injection
6. Dynamic Zoom & Pan
7. Ultimate Bypass
```
→ Mục đích né pHash / Content-ID / AI-detect khi reupload nội dung người khác. **Không khuyến nghị. Không implement.**

---

### 18. Cap REUP — Auto Master dub pipeline labels

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `capassistant.exe` strings |
| **loại** | tip / config |
| **tóm tắt** | Bước 3/4 tạo giọng thuyết minh VI; output `vietsub.srt` + `thuyetminh.wav`; `speed_factor` cho cloud STT; `strip_silence` + `atempo` merge |
| **OmniCast** | Không video-dub pipeline (A1 đã cover VideoLingo); gap là factory wrap |
| **khuyến nghị** | **GHÉP** naming convention artifacts; pipeline dub → tham chiếu A1 |

```
[BƯỚC 3/4] đang tạo giọng đọc thuyết minh tiếng Việt (Voice AI)...
outputs: vietsub.srt , thuyetminh.wav , master_voice_final.wav
strip_silence + ffmpeg atempo=...
```

---

### 19. Cap REUP — SmartSubtitle translate prompt fragment

| field | value |
|-------|--------|
| **repo** | Cap Assistant REUP |
| **file:line** | `capassistant.exe` strings (`SmartSubtitleChunker`) |
| **loại** | prompt |
| **tóm tắt** | Context trước **không dịch**, chỉ giữ tone/genre; chunk multi-thread Gemini (“vắt lưng câu”) |
| **OmniCast** | Writer sinh bản địa; không chunk-translate SRT |
| **khuyến nghị** | **GHÉP** pattern context-window khi dịch caption batch |

```
--- PREVIOUS CONTEXT (DO NOT TRANSLATE THIS, USE FOR TONE/GENRE REFERENCE ONLY): "..." ---
```
Tip HTML (strings): multi-account Gemini vì 1 account bị limit số câu/lượt — **RỦI RO ToS Google** nếu automation account farm.

---

### 20. Cap Pro — Master Film Director prompt (JSON scenes)

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | `CapAssistantPro-v3.8.exe` ~offset 41756543 |
| **loại** | prompt |
| **tóm tắt** | System role master director; JSON-safe rules; I2V motion engineering; pacing 1 vs 2–3 images theo độ dài SRT; VN full diacritics |
| **OmniCast** | `visual_director` / storyboard — TỰ CHẾ, **không** schema SRT+Prompts[]+I2V khớp CapCut inject |
| **khuyến nghị** | **GHÉP** schema scene + I2V rules + SRT 150-char; **GHÉP** VN diacritics enforcement |

```
You are a Master Film Director & Automation Architect. Create a video script
structurally optimized for programmatic parsing based on these precise rules:

CRITICAL RULES FOR JSON VALUES:
1. ABSOLUTELY NO DOUBLE QUOTES (`"`) inside ANY text values. Use single quotes (`'`).
2. NO ELLIPSIS: Do not use `...`. Use `.` or `,`.
3. NO NEWLINES / `\n` inside string values.
4. NO MARKDOWN: no `**`, `*`, or `#` in the SRT.

CORE METADATA:
- Language: {lang} (ALL text in 'SRT' natively in target language)
- Aspect Ratio: {ar} | Target Duration: {dur}

CINEMATIC COMPOSITION & VISUAL DNA:
- ALL Image Prompts ("Prompts" array) in highly descriptive ENGLISH, style: {style}.

I2V (IMAGE-TO-VIDEO) MOTION ENGINEERING (CRITICAL):
- Do NOT write basic camera moves only ("pan left", "zoom in").
- MUST describe SUBJECT ACTIONS, OBJECT TRANSFORMATIONS, ENVIRONMENTAL DYNAMICS.
- BAD: "Camera slowly zooms in on the man."
- GOOD: "The man raises his coffee cup and takes a sip, smiling warmly.
  His hair blows gently in the wind, and cars pass by in the blurred background.
  Volumetric dust particles float in the air."

PROMPTS & I2V ARRAYS SYNCHRONIZATION:
- "Prompts" and "I2V_Prompt" strictly length-matched (1:1).

DYNAMIC PACING:
- SRT short (~1–4s reading): exactly ONE image + ONE I2V.
- SRT long/complex (~5s+): 2–3 distinct image+I2V pairs; DO NOT split SRT text.

CRITICAL VIETNAMESE ACCENT ENFORCEMENT:
- SRT MUST be flawless Vietnamese WITH FULL DIACRITICS.
- NEVER strip accents — will CRASH THE ENGINE.

CRITICAL TIME LIMIT:
- If YT source longer than target, ONLY hooking intro / condensed summary.
- DO NOT process entire long video into short target.
```

---

### 21. Cap Pro — Video Editor SRT slicing rules

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | EXE ~41779774 |
| **loại** | prompt |
| **tóm tắt** | EN+VI only: max 150 chars/scene; ideal 60–140; 1 scene = 1 breath; fail breaks render |
| **OmniCast** | Subtitle/script không enforce 150-char hard limit |
| **khuyến nghị** | **GHÉP** hard limit + ideal band cho caption pack |

```
5. CRITICAL SUBTITLE (SRT) SLICING RULES (APPLY FOR ENGLISH & VIETNAMESE ONLY):
You are a professional Video Editor. You MUST strictly follow these rules when dividing the text into JSON scenes:
- MAX LIMIT: The "SRT" string MUST NEVER exceed 150 characters per Scene.
- CONDITIONAL SPLITTING: DO NOT fragment short sentences at every comma.
  IF approaching 150 chars, split at nearest natural pause.
- IDEAL LENGTH: 60 to 140 characters per Scene.
- DURATION LIMIT: Duration ideally {duration_rule}.
- NO PARAGRAPHS: 1 Scene = 1 Breath / 1 spoken line.
FAILURE TO FOLLOW THE 150-CHARACTER LIMIT WILL BREAK THE VIDEO RENDERING PIPELINE.
```

---

### 22. Cap Pro — Expert Video Director JSON schema + free gate

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | EXE ~41595403 |
| **loại** | prompt + config free-user |
| **tóm tắt** | Output chỉ JSON array SceneID/Timestamp/Duration/SRT/Prompts/I2V; AI Studio scrape + copy strategy = PRO/ULTRA only |
| **OmniCast** | TỰ CHẾ – không Playwright AI Studio harvest |
| **khuyến nghị** | **GHÉP** JSON schema; **BỎ QUA** browser-scrape AI Studio (ToS / fragile) |

```
You are an Expert Video Director. Create a highly engaging video script
strictly following these configurations:
Language: {L} | Ratio: {R} | Topic: {T} | Idea: {I} | CTA: {C}

STRICT OUTPUT FORMAT: ONLY A VALID JSON ARRAY. NO MARKDOWN.
[
  {
    "SceneID": 1,
    "Timestamp": "00:00:00-->00:00:04",
    "Duration": 4.0,
    "SRT": "Text in target language",
    "Prompts": ["English image prompt"],
    "I2V_Prompt": "English motion prompt"
  }
]

FREE-tier gates (UI strings):
"Tính năng Tự Động Cào Kịch Bản (AI Studio) ... chỉ dành riêng cho hạng PRO và ULTRA."
"Tính năng Copy lệnh (Chiến Lược Kịch Bản) chỉ dành riêng cho hạng PRO và ULTRA."
"Please activate your license to use the system."
```

---

### 23. Cap Pro — Character DNA + Visual DNA prompts

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | EXE ~41809229, ~41810602 |
| **loại** | prompt |
| **tóm tắt** | Vision extract character DNA ≤25 words; style DNA 6 refs → 20–50 word EN style line |
| **OmniCast** | `character_anchor.py` / style_guide — gần ý nhưng prompt khác |
| **khuyến nghị** | **GHÉP** verbatim DNA prompts vào vision pipeline |

```
You are an expert character designer. Analyze this character image and extract
their core visual DNA (gender, age, hair style and color, eye color, clothing style,
distinctive features/props). Return ONLY a comma-separated list of keywords in English.
No markdown, no explanations, no full sentences. Keep it under 25 words.
Example: 'young asian woman, silver twin tails, cybernetic glowing blue eyes,
black techwear jacket, neon tattoos'

Analyze the visual DNA of these 6 reference images. Extract only the shared visual
style for image generation. Output ONLY a single English style prompt (20-50 words).
Focus on art style, color palette, lighting, atmosphere, composition, and rendering quality.
Merge redundant traits. No explanations. No labels. No bullet points. No markdown.
Return exactly one line optimized for AI image generation.
```

---

### 24. Cap Pro — Explainer TYPE2 prompt template + 2.5 wps

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | EXE (cạnh MAX LIMIT block) |
| **loại** | prompt |
| **tóm tắt** | Duration = words/2.5; layout 5 variants; one character; negative no watermark |
| **OmniCast** | Không wps-based duration; visual_director không layout slots cố định |
| **khuyến nghị** | **GHÉP** 2.5 wps timing + composition layouts + `no text, no watermark` |

```
4. CHUẨN MỰC PROMPTS (TYPE 2 - EXPLAINER):
- QUY TẮC THỜI GIAN: 2.5 từ/giây.
  Duration = (Số từ trong cột SRT) / 2.5
- CẤU TRÚC BẮT BUỘC: A single cohesive scene of ONE main character.
  [THE SCENE]: ...
  [THE CHARACTER & STYLE]: ...
  [EMOTION]: ...
  [COMPOSITION]: layouts —
    Character left/right/top/bottom/centered with isolated environment.
  Avoid repeating same layout consecutive scenes. Medium shot.
CRITICAL RULES: DO NOT generate character sheets, multiple views, or split screens.
STRICTLY ONE character interacting with the scene.

Negative: append 'no text, no watermark, no typography' to end of Prompt
(unless script explicitly needs on-screen text).
```

---

### 25. Cap Pro — VIRAL TIPS + absolute taboos (in-app help)

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | EXE ~41708872 (guide_html) |
| **loại** | tip |
| **tóm tắt** | Commas → more image switches; concise DNA keywords; clear CapCut trash after 5 videos; no open timeline during inject; leave Chrome alone |
| **OmniCast** | Không CapCut inject |
| **khuyến nghị** | **GHÉP** tip “comma → cut visual”; **BỎ QUA** CapCut backdoor (RỦI RO ToS CapCut / reverse engineering draft) |

```
VIRAL TIPS:
1. Scripts with commas: More pauses → AI switches images more frequently.
2. Concise DNA: keywords only (Cyberpunk, Neon, Masterpiece) — not paragraphs.
3. Clear Cache regularly: After 5 videos, [Clear CapCut Trash].

2 ABSOLUTE TABOOS:
1. NO OPEN TIMELINES: inject only when CapCut is on Homepage.
2. LEAVE CHROME ALONE: do not click bot-opened browser windows.

"backdoor" to inject Audio, Images, and Subtitles directly into CapCut Timeline.
```
→ Inject draft CapCut không public API = **RỦI RO CHÍNH SÁCH / ToS** — chỉ học schema JSON, không port backdoor.

---

### 26. Cap Pro — config.json TTS providers

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | `config.json` (package root) |
| **loại** | config |
| **tóm tắt** | GEMINI_API_KEY + TTS_PROVIDERS.VBEE keys empty |
| **OmniCast** | Gemini image/video providers; không VBEE |
| **khuyến nghị** | **Ghi nhận** VBEE là TTS cloud VN thương mại — optional provider nếu có license |

```json
{
  "GEMINI_API_KEY": "",
  "TTS_PROVIDERS": {
    "VBEE": { "API_KEY": "", "APP_ID": "" }
  }
}
```

---

### 27. Cap Pro — transition_pool CapCut effect meta

| field | value |
|-------|--------|
| **repo** | Cap Assistant Pro |
| **file:line** | `transition_pool/*/config.json`, `extra.json` |
| **loại** | config |
| **tóm tắt** | AE→CapCut effect pack; default transition duration ~2.0s, isOverlap true |
| **OmniCast** | FFmpeg/HTML overlay transitions — khác stack |
| **khuyến nghị** | **GHÉP** default duration 2s / overlap policy nếu có transition system |

```json
// config.json
{
  "ae_tool": "AEExporter:1.5.4",
  "bALG_BACH_CONFIG": false,
  "effect": { "Link": [{ "path": "AmazingFeature/", "type": "AmazingFeature", "zorder": 8029 }] },
  "name": "AE2Effect_...",
  "version": "14.8.0"
}
// extra.json
{ "transition": { "defaultDura": 2.000001, "isOverlap": true } }
```

---

### 28. OmniCast baseline (đối chứng) — TTS không normalize

| field | value |
|-------|--------|
| **repo** | OmniCast |
| **file:line** | `media/tts.py:32-57`, `media/voice_router.py:197-231`, `media/models.py:43-57` |
| **loại** | config |
| **tóm tắt** | Xác nhận: text thô → provider; loudnorm I=−14; default chain kokoro/edge; **không** sentence split, **không** trim silence, **không** spell numbers |
| **OmniCast** | (chính nó) |
| **khuyến nghị** | baseline để patch |

```python
# tts.py
result = await self._router.synthesize(request.text, chain, output_path, ...)
if request.target_lufs:
    await self._normalize_lufs(result.audio_path, request.target_lufs)
# models.py
target_lufs: float = -14.0
# voice_router: path = await provider.generate(text, model=spec.voice, ...)
# tts_edge: Communicate(text, voice, rate="+0%", pitch="+0Hz")  # no pre-norm
```

---

## Cơ chế OmniCast thiếu hoặc yếu hơn

| cơ chế | repo nguồn (file:dòng) | hiện trạng OmniCast (file:dòng) | mức | việc phải làm |
|--------|------------------------|----------------------------------|------|----------------|
| Text normalize trước TTS (`& % km`, strip brackets, unicode filter) | voice-pro `abus_text.py:245-289` | `tts.py` / `voice_router.py` text thô | **CAO** | Thêm `normalize_tts_text()` gọi trước mọi provider |
| Spell-out numbers / TN (en inflect, zh WeText) | CosyVoice `frontend.py:121-147`, `frontend_utils.py:42-58` | Không | **CAO** | Number/date expander theo locale (VN/EN tối thiểu) |
| Sentence / paragraph chunk (token_max 80, max SRT 150c) | CosyVoice `frontend_utils.py:65-117`; Cap Pro SRT rules | Full script 1 shot | **CAO** | Chunk + concat với silence pad có kiểm soát |
| Trim silence per segment (−50 dBFS, pad 100ms) | voice-pro `abus_audio.py:35-98` | Chỉ loudnorm global `tts.py:75-88` | **CAO** | Trim trước/sau mỗi chunk; giữ LUFS −14 |
| Prosody per channel (rate/pitch/volume Edge) | voice-pro `tab_tts_edge.py:57-59` | Edge cố định +0 `tts_edge.py:55-56` | **TRUNG** | Channel JSON `voice_prosody` |
| Kokoro/F5 speed 0.3–2.0 | `tab_tts_kokoro.py:56` | Không expose | **TRUNG** | Thêm speed vào VoiceSpec hoặc TTSRequest |
| SRT timeline silence-pad + merge gap 500ms | voice-pro `abus_tts_*.py` srt_to_voice + `abus_text.py:348-358` | Không dub-from-SRT | **TRUNG** | Nếu ship dub: port timeline align (kết hợp A1) |
| Content factory JSON schema (SRT+Prompts+I2V 1:1) | Cap Pro master prompt | Writer/visual_director tách rời | **CAO** | Schema `Scene` unified cho render pack |
| I2V motion engineering rules (action not just camera) | Cap Pro prompt | veo_pipeline / prompt_builder yếu hơn | **CAO** | Port GOOD/BAD I2V examples vào prompt_builder |
| Visual/Character DNA extract prompts | Cap Pro EXE vision prompts | `character_anchor.py` TỰ CHẾ | **TRUNG** | Thay prompt DNA bằng verbatim Cap Pro |
| Duration = words/2.5 | Cap Pro TYPE2 | Ước `words*0.4` fallback `tts.py:60-61` | **TRUNG** | Unified WPS constant (2.5) cho timing |
| Negative prompt `no text, no watermark, no typography` | Cap Pro strings | `ImageGenRequest.negative_prompt` default `""` `models.py:70` | **TRUNG** | Default negative cho image gen |
| Offline Piper VN voices | Cap REUP voice table | Chỉ Edge cloud cho VN | **THẤP** | Optional piper provider offline |
| CapCut draft inject / backdoor | Cap Pro `CapCutDraftManager.*` | Không — FFmpeg/HTML render | **—** | **BỎ QUA** (ToS) |
| Fingerprint bypass (pHash, GOP, micro color) | Cap REUP UI strings | Không | **—** | **BỎ QUA** — **RỦI RO CHÍNH SÁCH** |
| AI Studio Playwright scrape scripts | Cap Pro free gate strings | Không | **—** | **BỎ QUA** (ToS + fragile); dùng API chính thức |
| Multi-account Gemini translate farm | Cap REUP tips | Không | **—** | **BỎ QUA** farm; rate-limit hợp pháp |
| Transition default 2s overlap | Cap Pro `extra.json` | Custom | **THẤP** | Align transition default nếu có EDL |
| Loudness target | OmniCast `target_lufs=-14` | voice-pro **không** LUFS chuẩn hóa (chỉ trim) | **—** | OmniCast **mạnh hơn** ở loudnorm — giữ |

### Bước thiếu text-normalization (xác nhận)

| # | Bước (voice-pro / CosyVoice) | OmniCast |
|---|------------------------------|----------|
| 1 | Strip `()` `[]` `{}` | ❌ |
| 2 | `& → and`, `% → percent`, `\d+km → kilometers` | ❌ |
| 3 | Unicode category filter (giữ currency) | ❌ |
| 4 | Collapse `!!!` / `...` | ❌ |
| 5 | Dedup word lặp + multi-space | ❌ |
| 6 | Fullwidth punct → ASCII (spacy path) | ❌ |
| 7 | Spell Arabic numerals (inflect EN) | ❌ |
| 8 | Corner marks ²/³ | ❌ |
| 9 | Remove CJK brackets / em-dash | ❌ |
| 10 | Split paragraph max 80 tokens | ❌ |
| 11 | Drop punctuation-only chunks | ❌ |
| 12 | SRT merge/split for TTS | ❌ |
| — | Loudnorm I/TP/LRA | ✅ `tts.py` |

### Content factory — bước Cap Pro vs OmniCast (reup-hợp-pháp / biên tập có biến đổi)

| Bước Cap Pro | OmniCast | Ghi chú |
|--------------|----------|---------|
| Ingest topic / idea / CTA | ✅ Channel + writer | |
| Optional YT summarize-to-duration (hook only) | ❌ | Hợp pháp nếu nguồn/license OK + transformative summary |
| Master prompt → JSON scenes | ⚠️ partial | Writer không emit Prompts[]/I2V 1:1 |
| SRT ≤150c, 2.5 wps duration | ❌ | |
| TTS VO + measure speed align images | ⚠️ TTS only | Không auto-align image duration to VO |
| Image gen + I2V per scene | ⚠️ image/video providers | Thiếu I2V prompt quality rules |
| Style/Character DNA lock | ⚠️ character_anchor | Prompt kém hơn |
| Inject CapCut timeline | ❌ (khác stack) | Dùng FFmpeg/EDL thay — **không** backdoor |
| Transition pack 2s | ⚠️ | |
| Export multi-platform | ⚠️ YouTube API only | Đúng ToS; không browser upload |
| Fingerprint bypass reup | ❌ **không làm** | Đúng hướng compliance |

**Reup hợp pháp (khuyến nghị định hướng):** nguồn public domain / license / fair-use commentary với **biến đổi thực chất** (script mới, VO mới, visual mới, editorial angle) — **không** unique-ify video người khác để lách Content-ID.

---

## TOP-15 PATCH

1. **Thêm `normalize_tts_text()`** — port logic `abus_text.normalize_text` + spell numbers locale; gọi từ `VoiceRouter.synthesize` trước provider.  
   File: `media/tts_normalize.py` (mới), `media/voice_router.py`.

2. **Chunk script dài** — sentence split đa ngôn ngữ + CosyVoice-style max ~80 tokens; concat + pad silence 80–120ms.  
   File: `media/tts.py`, `media/tts_normalize.py`.

3. **Trim silence per segment** — dBFS −50, pad 100ms (voice-pro), rồi mới loudnorm −14.  
   File: `media/tts.py`, optional `media/ffmpeg.py`.

4. **Unified Scene schema** — `SceneID, Duration, SRT, prompts[], i2v_prompts[]` length-matched.  
   File: `agents/visual_director.py`, `storyboard/*`, `media/prompt_builder.py`.

5. **Port Master Film Director / I2V GOOD-BAD rules** vào system prompt visual.  
   File: `media/prompt_builder.py`, `agents/visual_director.py`.

6. **Hard limit SRT 150 chars / ideal 60–140** cho caption + scene split (EN/VI).  
   File: `media/subtitle.py`, writer post-process.

7. **WPS timing 2.5** thay magic `words*0.4` fallback.  
   File: `media/tts.py`, orchestrator duration estimates.

8. **Channel `voice_prosody`** `{rate,pitch,volume}` → Edge (và map speed Kokoro).  
   File: `channels/*.json` schema, `providers/tts_edge.py`, `tts_local.py`.

9. **Default image negative** `no text, no watermark, no typography`.  
   File: `media/models.py`, `prompt_builder.py`.

10. **Character/Style DNA prompts** Cap Pro verbatim cho vision extract.  
    File: `media/character_anchor.py`, `style_guide.py`.

11. **Explainer composition layouts** (5 slot L/R/T/B/C) + no multi-view.  
    File: `media/prompt_builder.py`, `config/styles.py`.

12. **Optional Piper offline VN** provider (từ catalog REUP) cạnh Edge.  
    File: `media/providers/tts_piper.py`, `voice_router.py`.

13. **Expand F5 model catalog** theo `abus_tts_f5_models.json` cho clone đa locale.  
    File: `media/providers/tts_local.py` / chatterbox path.

14. **VO-driven image timing** — đo duration TTS từng câu → set scene length (Cap Pro “Absolute Sync”).  
    File: `media/orchestrator.py`, `pipeline/edl.py`.

15. **Compliance gate tài liệu** — blacklist fingerprint-bypass & CapCut inject; checklist reup hợp pháp (biến đổi thực chất).  
    File: `compliance/*`, `Claude.md` notes — **không** port code REUP bypass.

---

## Phụ lục — nguồn extract

| artifact | path |
|----------|------|
| voice-pro source | `_refs/voice-pro/app/*`, `cosyvoice/*` |
| Cap REUP rar | `_refs/Cap Assistant - REUP.../capassistant-v3.31-stable.rar` |
| Cap Pro rar | `_refs/Cap Assistant Pro.../CapAssistantPro-v3.8.exe` inside rar |
| Guide | `_refs/.../Hướng dẫn nè.docx` |
| Scratch (có thể xóa) | `docs/research/_tmp_cap_extract/` |

**Security note:** REUP binary chứa chuỗi credential hardcode (email/password patterns) — **không** copy secrets vào doc/code; nếu team từng chạy app, coi như credential compromised.

---

*Kết thúc V2_A2 — VoiceCap.*
