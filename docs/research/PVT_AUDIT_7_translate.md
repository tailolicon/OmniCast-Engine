Đang quét vét cạn toàn bộ slice `translator/` (pyvideotrans) và `reup/translate/` (OmniCast).Đang đọc toàn bộ module dịch OmniCast.Đã đọc hết 27 file `videotrans/translator/` và toàn bộ `reup/translate/`. Report theo định dạng bắt buộc:

---

# Report Agent 7 — Tầng dịch (pyvideotrans vs OmniCast)

## Trả lời 5 câu bắt buộc (tóm tắt)

1. **Toàn vẹn số dòng**: pyvideotrans mode text pad `""` khi thiếu dòng, cắt thừa; mode SRT **không** đối chiếu số block. OmniCast khớp `segment_id` (dialogue) / vị trí (narration) + retry/split — nhưng **không** chặn bản dịch rỗng/còn Hán, và dict theo id có thể **nuốt bản ghi trùng id**.
2. **Chia lô / ngữ cảnh**: pvt mặc định `trans_thread=10` / `aitrans_thread=50` (AI), hoặc cả list nếu `aitrans_context`; **không** có rolling context giữa lô. OmniCast scene ≤24 câu / gap 1.5s; lô 8 (dialogue) / 16 (narration); context = planner + profile + 6 câu đầu scene (source), không phải bản dịch lô trước.
3. **Sai format**: pvt retry API (tenacity), không retry vì lệch dòng. OmniCast retry/split batch khi lệch id/độ dài; fail hard nếu 1 câu vẫn lệch.
4. **Rỗng / trùng / còn Trung**: pvt chỉ fail khi **toàn bộ** rỗng; không detect trùng/Hán. OmniCast QC xung hô/confidence; **không** detect rỗng/Hán/trùng nội dung.
5. **Độ phức tạp**: pipeline contextual giải quyết xưng hô/diễn ngôn zh→vi mà pvt bỏ qua; nhưng phức tạp không thay cơ chế “đếm dòng + pad/retry đơn giản” của pvt cho lỗi rỗng/dịch sót.

---

### [CRITICAL] Mode text pyvideotrans: thiếu dòng → pad rỗng, thừa dòng → cắt im lặng
- **pyvideotrans**: `_base.py:100-118` — `sep_res = result.split("\n")`; chỉ lấy `x < len(it)`; nếu `len(sep_res) < len(it)` pad `""`; gán `text_list[i]['text']` kể cả rỗng. Chỉ raise khi `_empty_line >= len(self.text_list)` (`:120-121`).
- **OmniCast**: `openai_engine.py:236-243`, `contextual_runtime.py:452-476`, `537-616` — mismatch id/độ dài → raise hoặc split-retry; không pad rỗng.
- **Hậu quả thực tế**: pvt: câu TTS trống / timeline lệch (dòng sau trôi lên chỗ trước). OmniCast: job fail thay vì xuất im lặng — an toàn hơn nhưng dễ “kẹt” job.
- **Cách vá**: (OmniCast) sau adaptation, reject `subtitle_text`/`tts_text` rỗng khi `source_text` không rỗng → `needs_review` hoặc retry 1 câu; đừng pad im lặng kiểu pvt.

### [CRITICAL] Mode SRT AI pyvideotrans: không khóa 1-1 số block
- **pyvideotrans**: `_base.py:126-158` — ghép SRT, parse `get_subtitle_from_srt`, `return raws_list` **không** so `len(raws_list)` vs `len(self.text_list)`. Prompt SRT (`prompts/srt/chatgpt.txt:30-32`) yêu cầu 1-1 nhưng code không enforce.
- **OmniCast**: structured JSON + `segment_id` / positional length (`_validate_stage_item_ids`, `_run_stage_batch_with_positional_retry`).
- **Hậu quả thực tế**: pvt có thể lệch cả timeline phụ đề/dubbing sau dịch. OmniCast tránh lớp này.
- **Cách vá**: (tham chiếu) nếu port logic pvt, luôn so số block; thiếu → retry; dư → không tin parse.

### [CRITICAL] OmniCast: khớp id bằng `set` + dict — trùng `segment_id` / thiếu field text vẫn “pass”
- **pyvideotrans**: `_base.py:100-103` — map theo **thứ tự dòng**, không id.
- **OmniCast**: `contextual_runtime.py:452-462` — `batch_items = {item.segment_id: item ...}`; validate `expected_set == actual_set`. Trùng id → ghi đè; đủ tập id là pass. `subtitle_text=""` hợp lệ schema (`models.py:311-320`). `semantic_qc.py` không check rỗng/Hán.
- **Hậu quả thực tế**: một câu mất/sai nội dung nhưng review gate không bật; TTS im hoặc nói sai; còn chữ Hán trên phụ đề YouTube.
- **Cách vá**: `contextual_runtime.py` / `openai_engine.py` — (1) reject nếu `len(items) != len(expected)` hoặc id trùng; (2) flag `empty_translation` / `source_script_residue` (CJK trong target) → `needs_human_review`.

### [MAJOR] Không có rolling context dịch giữa các lô (cả hai; OmniCast “giả” context)
- **pyvideotrans**: `_base.py:52-55, 92-110` — mỗi lô độc lập; `aitrans_context=True` thì `trans_thread = len(text_list)` (gửi hết một lần), không phải context chồng lô.
- **OmniCast**: lô 8/16 (`contextual_pipeline.py:27`, `contextual_runtime.py:56`); `_build_context_payload` (`contextual_pipeline.py:250-271`) chỉ `scene.segments[:6]` **source** + character/relationship memory — **không** bản dịch lô trước trong cùng scene.
- **Hậu quả thực tế**: thuật ngữ/xưng hô có thể nhảy giữa nửa đầu/nửa sau scene dài; pvt nặng hơn vì không memory quan hệ.
- **Cách vá**: trong `contextual_runtime` khi gọi batch k>1, nhét 2–4 cặp `(source, approved_subtitle)` của batch trước vào `context_payload`.

### [MAJOR] Retry lệch dòng: pvt không retry; OmniCast retry nhưng không “fallback nguồn”
- **pyvideotrans**: tenacity trên `_item_task` (vd `_openaicompat.py:36`); lệch dòng **không** trigger retry; pad rỗng (`_base.py:106-109`).
- **OmniCast**: `_run_stage_batch_with_retry` / `_positional_retry` (`contextual_runtime.py:371-616`) — split batch; 1 dòng vẫn lệch → `RuntimeError`. Không chèn nguyên `source_text`.
- **Hậu quả thực tế**: pvt xuất video “lủng” câu; OmniCast fail job (tốn ASR/download đã chạy — đã có checkpoint bù một phần, `runner.py:459-491`).
- **Cách vá**: sau hết retry 1-segment: ghi `source_text` + `needs_review=True` + risk `translation_failed` thay vì kill cả job (tuỳ product).

### [MAJOR] Không phát hiện bản dịch còn tiếng Trung / trùng lặp (cả hai tầng translator)
- **pyvideotrans**: không scan CJK/residual; không so dòng k-1. `cleartext` chỉ dọn entity/punctuation (`help_srt.py:63-66`).
- **OmniCast**: `semantic_qc.py:188-367` — honorific, confidence, sub≠tts pronoun; không residual Han, không duplicate-adjacent, không `subtitle == source`.
- **Hậu quả thực tế**: phụ đề lẫn Hán–Việt; 2–3 dòng lặp cùng câu; QC “xanh” vì không có rule.
- **Cách vá**: thêm rule deterministic trong `semantic_qc.analyze_segment_analyses`: residual Han ratio, exact-duplicate neighbor, empty target.

### [MAJOR] Prompt pvt khóa “LINE COUNT”; OmniCast khóa schema/id — khác triết lý, lỗ hổng khác nhau
- **pyvideotrans**: `prompts/text/chatgpt.txt:7-10, 47-48` — ABSOLUTE LINE COUNT LOCK; output `<TRANSLATE_TEXT>`; parse regex `_openaicompat.py:84-87`.
- **OmniCast**: Pydantic structured (`openai_engine.py:145-169`); prompt “exactly one item per segment_id” (`presets.py:56-58, 87-89`).
- **Hậu quả thực tế**: pvt fail-open (pad); OmniCast fail-closed (raise). Structured output vẫn cho phép text rỗng/sai nghĩa nếu id đúng.
- **Cách vá**: thêm constraint runtime (không chỉ prompt): non-empty + residual script check như trên.

### [MAJOR] `contextual_pipeline.run_contextual_translation` (legacy) batch “giả”
- **pyvideotrans**: chia lô thật, mỗi lô `it` đúng slice (`_base.py:69-73`).
- **OmniCast**: `contextual_pipeline.py:680-707` — `for batch_rows in scene_batches` nhưng payload `_scene_row_payload(scene)` (cả scene), `batch_rows` không dùng; `semantic_items` gán ngoài vòng lặp theo indent. **Entry production** là `contextual_runtime` (`runner.py:74,496`).
- **Hậu quả thực tế**: nếu ai gọi legacy path: spam API full-scene N lần / hành vi khó đoán.
- **Cách vá**: deprecate/xóa export legacy hoặc sửa dùng `_scene_batch_payload(scene, batch_rows)` + merge như runtime.

### [MINOR] Kích thước lô mặc định khác nhau rất xa
- **pyvideotrans**: default `trans_thread=10`, `aitrans_thread=50`, `aisendsrt=True` (`config.py:350-386`; `_base.py:51-55`).
- **OmniCast**: scene max 24 / 75s / gap 1500ms (`scene_chunker.py:7-9`); batch 8 dialogue / 16 narration; narration downshift sau under-return (`contextual_runtime.py:952-965`).
- **Hậu quả thực tế**: pvt lô 50 dòng AI dễ lệch/cắt token; OmniCast lô nhỏ ổn định hơn, nhiều call hơn (chi phí/time).
- **Cách vá**: giữ lô nhỏ OmniCast; không port 50. Cân nhắc lô 10–12 nếu cost.

### [MINOR] Rate limit / wait giữa lô
- **pyvideotrans**: `wait_sec = translation_wait` (default 0) sau mỗi lô (`_base.py:40, 110, 149`).
- **OmniCast**: không sleep giữa scene; chỉ Groq 429 backoff (`llm_backends.py:164-195`); Claude validate retry 2 lần (`:124-160`); Groq path json_object **không** retry validation.
- **Hậu quả thực tế**: OpenAI/Claude burst → 429/timeout; Groq json lỏng có thể ValidationError kill batch.
- **Cách vá**: mirror Claude 2-attempt validate cho Groq fallback; optional `translation_wait` nhỏ giữa scene.

### [MINOR] Xử lý xuống dòng / ký tự đặc biệt trong câu nguồn
- **pyvideotrans**: line-mode `replace("\n", " ")` trước dịch (`_base.py:68`); join `\n` khi gửi; DeepL skip nếu chỉ punctuation (`_deepl.py:27-28`).
- **OmniCast**: gửi `source_text` nguyên trong JSON; không normalize newline/punctuation trước model.
- **Hậu quả thực tế**: pvt tránh “vỡ dòng” giả; OmniCast nếu ASR nhét `\n` trong segment có thể làm model “tưởng” multi-line (hiếm vì segment thường 1 dòng).
- **Cách vá**: normalize `source_text` → single line trước payload batch.

### [MINOR] Cache dịch
- **pyvideotrans**: file cache MD5 theo channel/url/model/lang/content (`_base.py:160-175`).
- **OmniCast**: stage hash + checkpoint scene + full cache (`persistence.py`, `contextual_checkpoint.py`, `runner.py:447-525`).
- **Hậu quả thực tế**: OmniCast mạnh hơn resume job dài; pvt cache mịn theo lô.
- **Cách vá**: không bắt buộc; checkpoint đã đủ.

---

## Bảng so sánh nhanh (câu hỏi brief)

| Hạng mục | pyvideotrans | OmniCast |
|---|---|---|
| Khớp 1 câu gốc → 1 câu dịch | Thứ tự dòng; pad/cắt | `segment_id` / positional + retry |
| Lệch số dòng | Im lặng (pad/cắt) hoặc SRT lệch cả list | Fail / split-retry |
| Cỡ lô | 5–10 MT; ~50 AI (hoặc all) | 8 dialogue / 16 narration trong scene ≤24 |
| Context giữa lô | Không (trừ gửi cả list) | Memory quan hệ + 6 source đầu scene; không rolling bản dịch |
| Sai format model | Retry HTTP; không retry lệch dòng | Retry parse + split batch |
| Rỗng / trùng / còn Hán | Chỉ “all empty” | Không (QC xưng hô/confidence) |
| Độ phức tạp | 1 pass + prompt | Planner + semantic + adapt + critic + route narration + term micro |

## Kết luận vận hành

- **Toàn vẹn id/số item**: OmniCast **chắc hơn** pvt (không pad rỗng kiểu `_run_text`).
- **Lỗ hổng còn mở cùng “họ” bug ASR/align**: quality text **rỗng / residual Chinese / trùng id** lọt sau gate id — user thấy phụ đề/TTS hỏng **không** báo “mismatch segment”.
- **Contextual stack** đáng giá cho phim thoại zh→vi (xưng hô); **không** thay rule deterministic “mỗi source non-empty phải có target non-empty + đúng script đích”.
- Ưu tiên vá nhỏ: empty/residual/duplicate checks trong `semantic_qc` + reject `len(items)`/`duplicate ids` trong `_run_stage_batch_with_retry`.
