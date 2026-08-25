Tôi sẽ quét hết slice được giao: liệt kê cây thư mục rồi đọc từng file logic, không bỏ sót.Ưu tiên đọc lớp validate/preflight trước: mainwin, OmniCast ops, reup_routes; sau đó quét component và winform.Tiếp tục quét logic nghiệp vụ trong component, mosstts, và các preflight còn lại của OmniCast.Đã quét hết slice (component, winform, mosstts, mainwin + OmniCast `ops/` + `reup_routes.py`). Report theo định dạng bắt buộc:

---

# Agent 10 — Report quét vét: rào chắn / leftovers

## CRITICAL

### [CRITICAL] `/run` chỉ chặn ffmpeg; `/queue` không preflight gì
- **pyvideotrans**: `_actions.py:310–454` (`check_start`) — trước khi chạy bắt buộc qua proxy, nhận diện, API key nhận diện, dịch, TTS, CUDA, target language khi embed phụ đề, độ dài tên file, output dir, LLM rephrase key; thiếu video → `_actions.py:325–328` lỗi ngay.
- **OmniCast**: `reup_routes.py:540–542` — `reup_run` chỉ `if not health["checks"]["ffmpeg"]["ok"]`; **không** dùng `health["ready"]`. `reup_enqueue` (`reup_routes.py:670–697`) **không gọi** `reup_health()` chút nào. Module `run_doctor` (`ops/doctor.py:191`) **không được wire** vào API reup (chỉ export trong `ops/__init__.py`).
- **Hậu quả thực tế**: Job vào queue `queued` → user đợi vài phút download/ASR rồi fail vì thiếu Claude CLI / OpenAI / Groq / VieNeu / disk đầy. Batch queue còn tệ hơn: 10 link cùng fail muộn.
- **Cách vá**: Trong `reup_routes.py` `reup_run` và `reup_enqueue`, chặn khi `not health["ready"]` (hoặc gọi `run_doctor` + `format_blocked_message` theo stage `download/asr/translate/tts/export`). Map check theo `translation_backend` / engine TTS.

### [CRITICAL] Cấu hình sai chỉ phát hiện giữa pipeline, sau khi tốn thời gian
- **pyvideotrans**: `_actions.py:161–164` + `233–240` + `fn_peiyin.py:313–316` — TTS type/API/language/role kiểm trước start; `_actions.py:243–251` nhận diện + API; `_actions.py:438–446` LLM rephrase thiếu key → mở form cấu hình, **không** bắt đầu.
- **OmniCast**: `runner.py:317–320` — `voice_preset_id` sai raise **sau** download/bootstrap; `runner.py:411–415` — OpenAI key chỉ check khi vào translate (sau ASR); `reup_routes.py:71–100` — `asr_model`, `translation_backend`, `voice_preset_id`, `voice_id` là free string, không allowlist; URL không validate format Douyin.
- **Hậu quả thực tế**: Typo `translation_backend="clade-cli"`, `voice_preset_id` lạ, `asr_model="smol"` → job chạy download + ASR (vài–chục phút) rồi crash. Không có message ngay lúc POST.
- **Cách vá**: Validate request trong `reup_run`/`reup_enqueue`: allowlist backend (`claude-cli|openai|groq`), allowlist ASR model (ít nhất tiny/base/small/medium/large-v3…), resolve `voice_preset_id`/`voice_id` trước queue, fail 400 ngay.

## MAJOR

### [MAJOR] Health endpoint báo “sẵn sàng” nhưng không đủ điều kiện chạy TTS local
- **pyvideotrans**: `_actions_base.py:546–553` — listen voice chặn nếu thiếu model Piper/VITS; `fn_peiyin.py:490–495` CUDA; `check_tts` chặn role khi không có target language.
- **OmniCast**: `reup_routes.py:103–152` — health chỉ: ffmpeg, package `vieneu`, `faster_whisper`, một trong ba backend dịch. **Không** check eSpeak NG (doctor có: `doctor.py:156–188`), disk ≥2GB (`doctor.py:18`, `33–57`), workspace ghi được, CUDA. Doctor đầy đủ hơn nhưng API không dùng.
- **Hậu quả thực tế**: UI/API hiện `ready: true` trong khi VieNeu local sẽ fail lúc TTS vì thiếu eSpeak; disk đầy vẫn “ready”.
- **Cách vá**: Nâng `reup_health` bằng logic `run_doctor` (hoặc gọi chung helper); `ready` phải phản ánh engine TTS + backend dịch đã chọn.

### [MAJOR] Không chặn proxy / credential dịch / model ASR “chắc chắn sai” trước run
- **pyvideotrans**: `_actions_base.py:369–394` + `set_proxy.py:57–67` — proxy lạ → popup xác nhận; `_actions.py:50–58` + `is_allow_translate` chặn ngôn ngữ/kênh dịch không khớp; `_actions.py:139–149` + `fn_recogn.py:107–112` chặn ngôn ngữ không hỗ trợ model nhận diện.
- **OmniCast**: `ReupRunRequest.proxy` (`reup_routes.py:94`) free string, không format-check; không có `is_allow_lang` ASR/TTS (pipeline cố định zh→vi nên ít cần, nhưng `asr_model`/`voice_id` vẫn tự do).
- **Hậu quả thực tế**: Proxy typo (`127.0.0.1:7890` thiếu scheme hoặc port sai) → download Douyin fail muộn / treo; model ASR sai → lỗi faster-whisper sau extract.
- **Cách vá**: Chuẩn hóa proxy (`http://` nếu thiếu scheme) + regex port; soft-warn hoặc 400. Allowlist model ASR.

### [MAJOR] Không có guard tên file Windows / ký tự cấm cho output
- **pyvideotrans**: `_actions.py:533–545` — basename chứa `?:<>*|/"` trên Win32 → stop trước chạy; `_actions.py:288–307` — path ≥170 **và** name ≥90 → hỏi user.
- **OmniCast**: `reup_routes.py:55–57` comment biết title Douyin có `#`/CJK (encode URL) nhưng **không** sanitize tên file export; không check độ dài path MAX_PATH khi publish.
- **Hậu quả thực tế**: Title Douyin có `?` `*` `|` `"` → fail ffmpeg/export hoặc path Windows hỏng; khó debug.
- **Cách vá**: Sanitize `title` khi tạo export/product path (strip `<>:"/\|?*`, cap độ dài stem).

### [MAJOR] Review/edit segment không validate timing; pyvideotrans chặn overlap khi chỉnh
- **pyvideotrans**: `onlyone_set_editdubb.py:389–422` — chỉnh start/end: không overlap câu trước/sau, start ≤ end.
- **OmniCast**: `reup_routes.py:499–527` — review chỉ sửa text + approve flag; không đụng timing; không guard timing khi operator chỉnh tay (nếu sau này có UI timing).
- **Hậu quả thực tế**: Hiện chưa critical (API chưa cho sửa time). Nếu mở chỉnh mốc thời gian mà thiếu guard → TTS/align đè lên nhau, mất tiếng/chồng thoại.
- **Cách vá**: Khi có endpoint chỉnh time, copy rule overlap từ `onlyone_set_editdubb`.

## MINOR

### [MINOR] Clear cache / output: pyvideotrans hỏi; OmniCast cache_ops an toàn hơn nhưng API reup không expose
- **pyvideotrans**: `_actions.py:253–286` — clear output + same input/output dir → confirm; input=output khi only_out_mp4 → hard error.
- **OmniCast**: `cache_ops.py:164–205` — cleanup chỉ xóa orphan, giữ referenced artifacts (tốt hơn); `project_safety.py:50–81` backup DB trước sửa. Nhưng doctor/cache/repair **không** gắn `/api/reup/*`.
- **Hậu quả thực tế**: Operator reup qua API không có “disk low / cache bloated” trước job dài.
- **Cách vá**: Optional: endpoint doctor + cache inventory; trên UI gọi trước batch.

### [MINOR] CUDA: họ chặn sớm khi bật GPU ảo
- **pyvideotrans**: `_actions_base.py:89–100`, `405–415` — CUDA checked mà `NVIDIA_GPU_NUMS==0` → error, uncheck.
- **OmniCast**: Không toggle CUDA trên reup API; faster-whisper dùng default device trong engine (ngoài slice này).
- **Hậu quả thực tế**: Thấp nếu luôn CPU; nếu bật CUDA default mà máy không GPU → fail load model.
- **Cách vá**: Doctor check CUDA khi settings bật GPU.

---

## Trả lời 5 câu hỏi bắt buộc

### 1. Nó chặn cấu hình sai nào TRƯỚC khi chạy? Ta chặn được bao nhiêu?

**pyvideotrans (`check_start` + winform fn_*):**

| Rào chắn | pyvideotrans | OmniCast reup API |
|---|---|---|
| Có file nguồn | Có | Không (URL free) |
| Proxy format | Có (warn) | Không |
| Recogn type + API key | Có | N/A (fixed faster-whisper package check lỏng) |
| Ngôn ngữ ↔ model ASR | Có | Không |
| Translate channel + target | Có | Partial (key OpenAI chỉ mid-run) |
| TTS API + role + language | Có | Mid-run preset |
| CUDA thật | Có | Không |
| SRT import format | Có | N/A |
| LLM rephrase key | Có | N/A |
| Tên file Win cấm / quá dài | Có | Không |
| Output ≠ input / clear cache confirm | Có | N/A (workspace riêng) |
| ffmpeg | (runtime) | Có (chỉ `/run`) |
| series_id tồn tại | N/A | Có |
| stop_after enum | N/A | Có |
| Hàng đợi rỗng | N/A | Có |

**Ước lượng: ~3/15 rào chắn “trước chạy” thật sự** trên đường reup API (ffmpeg + series + stop_after). Doctor/workspace safety **có code** nhưng **không gắn** vào `POST /run`/`/queue`.

### 2. Nó cảnh báo gì mà ta im lặng?

- Proxy trông sai (`http://127.0.0.1:port`) — vẫn cho chạy nhưng hỏi.
- Tên file quá dài trên Windows.
- CUDA không khả dụng khi user bật.
- Ngôn ngữ/model nhận diện không match (tips text).
- TTS role “No” + không target language → không cho lồng tiếng.
- Clear cache sẽ xóa output — confirm.
- LLM rephrase thiếu API key — mở form cấu hình.
- File audio trong queue → ép chế độ extract-only (UI).

OmniCast im lặng với hầu hết; chỉ fail muộn hoặc health lỏng.

### 3. `mosstts` là gì, có đáng lấy không?

**MOSS-TTS Nano** — runtime ONNX TTS local (chủ yếu **zh/en**), voice clone, chunk theo token budget (`voice_clone_max_text_tokens=75`), WeTextProcessing + robust text normalizer (`text_normalization_pipeline.py`, `tts_robust_normalizer_single_script.py`).

| Thành phần | Đáng lấy cho OmniCast zh→vi? |
|---|---|
| Engine ONNX + model MOSS | **Không** — target là tiếng Việt (VieNeu/CapCut/Edge…), không phải Moss zh/en |
| WeTextProcessing zh TN | **Không** cho pipeline hiện tại (TTS là VI) |
| `normalize_tts_text` robust (URL/hashtag/markdown, CJK space) | **Có thể MINOR** nếu VieNeu đọc số/URL/hashtag dở — port rule VI riêng, **đừng** copy cả package |
| Token-budget sentence split | **Có thể** nếu TTS VI cắt câu dài kém — pattern binary-search token cut ở `onnx_tts_runtime.py:345–385` |

**Kết luận:** không port `mosstts/`; tối đa học pattern normalize/chunk nếu đo được VieNeu fail trên text bẩn.

### 4. Ngược lại: OmniCast có gì pyvideotrans KHÔNG có mà thật sự tốt hơn?

1. **Hàng đợi tuần tự** (`reup_routes.py:569–571`, `queue.py`) — tránh 5 job đè GPU/CPU/rate-limit Douyin.
2. **Resume theo content-hash stage** — không re-download/re-ASR khi resume (comment `runner.py:384–387`).
3. **Human review gate** — `needs_human_review` chặn TTS/export khi dịch nghi ngờ (`reup_routes.py:503–505`, `runner`).
4. **Doctor theo stage + disk + writable path** (`doctor.py`) — thiết kế tốt hơn popup rời; (thiếu: chưa gắn API).
5. **Workspace safety + backup DB** (`project_safety.py`) — inspect schema, stale artifacts, backup trước repair.
6. **Cache cleanup giữ artifact đang referenced** (`cache_ops.py`) — an toàn hơn “xóa cả thư mục output”.
7. **Path open sandbox** (`reup_routes.py:450–473`) — không `os.startfile` path ngoài products/workspace.
8. **Library series/episode validate trước queue** — tránh job mồ côi.
9. **media_url encode `#`/CJK** — fix download link vỡ.
10. **Health đa backend dịch** — claude-cli | openai | groq, không ép OpenAI.

### 5. Phần pyvideotrans **không** nên bắt chước?

1. **Toàn bộ `winform/*` + `component/*` Qt** — UI desktop 50+ provider; OmniCast là API/dashboard, không port form.
2. **Soft-confirm “Yes để tiếp tục”** với proxy/path dài — backend API cần **hard 400**, không popup.
3. **`clear_cache` xóa cả output dir** user chỉ định — nguy hiểm; giữ model OmniCast orphan-only.
4. **Shutdown máy khi xong** (`_actions.py:648–652`) — không phù hợp server 24/7.
5. **`mosstts` engine** — sai ngôn ngữ, nặng, phụ thuộc ONNX/WeText riêng.
6. **Bug pitch listen**: `_actions_base.py:529` `else f'{volume}Hz'` khi pitch âm — **đừng copy**.
7. **Mode ép extract khi có audio** — logic UI; reup luôn full dub pipeline.
8. **Danh sách cloud TTS/STT API settings rải 60 file winform** — OmniCast đã có provider registry; không nhân đôi form key từng vendor.

---

## Tóm tắt ưu tiên vá (ảnh hưởng output / thời gian operator)

1. **CRITICAL**: `reup_run`/`reup_enqueue` enforce full preflight (`ready` / doctor), không chỉ ffmpeg.  
2. **CRITICAL**: Validate `translation_backend`, `voice_preset_id`/`voice_id`, `asr_model` **trước** queue.  
3. **MAJOR**: Health = doctor (eSpeak, disk, write).  
4. **MAJOR**: Sanitize tên file export Windows.  
5. **MINOR**: Wire doctor/cache inventory lên API nếu UI batch dài.

*Không bịa line: mọi `file:line` trên đã mở file trong slice xác minh.*
