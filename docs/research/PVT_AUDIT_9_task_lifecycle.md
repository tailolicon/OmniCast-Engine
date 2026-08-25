Đang quét vét cạn `task/` + `process/` của pyvideotrans và đối chiếu với reup OmniCast.Tiếp tục đọc phần assembling/join của pyvideotrans và toàn bộ pipeline OmniCast.# Agent 9 — Báo cáo vòng đời job (quét vét cạn)

## Trả lời 5 câu hỏi bắt buộc

### 1. Bước pyvideotrans theo thứ tự vs 11 stage OmniCast

| # | pyvideotrans (`TransCreate` + worker queue) | OmniCast (`runner.py`) | Ghi chú |
|---|---------------------------------------------|------------------------|---------|
| 0 | Tải/chọn file (UI/CLI, ngoài task) | `download` | Ta có ingest Douyin |
| 1 | `prepare` — tách novoice, extract 16k, tách chọn tách vocal/instrument, xóa file size=0, validate stream | `bootstrap` + `probe` + `extract_audio` | **Thiếu** tách vocal/BGM + `_unlink_size0` + chờ novoice async |
| 2 | `recogn` — ASR; skip nếu đã có `source_sub`; noise; rephrase; fix_punc | `asr` | **Thiếu** noise/rephrase/punc; cache hash tốt hơn skip-theo-tên-file |
| 3 | `diariz` — speaker (lỗi **không chặn**) | — | **Thiếu hẳn** |
| 4 | (only_one) countdown sửa SRT gốc | — | Headless: cố ý bỏ; có review gate sau dịch |
| 5 | `trans` — skip nếu đã có target_sub; `check_target_sub` khớp dòng | `translate` | **Thiếu** căn số dòng dịch theo timeline gốc |
| 6 | (only_one) sửa SRT đích / queue_tts | review gate trước TTS | Tương đương một phần |
| 7 | `dubbing` — TTS; skip clip đã có (`vail_file`) | `tts` | Tương đương + clip-hash size>44 |
| 8 | `align` — SpeedRate | `voice_track` / `retime` | Khác engine, cùng ý căn tốc |
| 9 | `recogn2pass` — ASR lại trên audio lồng tiếng | — | **Thiếu hẳn** |
| 10 | `assembling` — BGM, embed instrument, freeze cuối, mux `-t`, soft/hard sub, mkv/mp4 | `mixdown` + `export` + `publish` | **Thiếu** tách nền, freeze mux cuối (chỉ có trong retime), multi-format |
| 11 | `task_done` — dọn cache khi **thành công**, notify | vault `done` + library sync | **Thiếu** kiểm tra output cuối chặt |

**Sai thứ tự:** không thấy stage cốt lõi bị đảo. Khác chủ yếu là **bỏ bước** và **gộp** (prepare→3 stage; assemble→mix+export).

### 2. Xử lý lỗi giữa chừng

- **pyvideotrans** (`job.py:42-66`): catch → signal `error` → `set_end()` (không succeed) → `cleanup_on_error` **rỗng**. **Giữ** file target/cache; chỉ `rmtree(cache)` khi `set_end(succeed=True)` (`_base.py:113-129`). Diariz/noise/BGM: nhiều chỗ **log + bỏ qua**.
- **OmniCast** (`runner.py:758-760`, `queue.py:105-125`): exception → vault `failed` → rethrow; queue retry 3 lần; `clean_partial_workspace` chỉ xóa workspace **chưa** có `project.json`+`project.db`. Stage-hash **giữ** phần đã xong.

### 3. Cache / skip

- **pyvideotrans:** skip theo **file tồn tại + size>0** (`vail_file`): `source_sub`, `target_sub`, `vocal.wav`, TTS `filename` MD5 text+role… **Không** hash options ASR/model.
- **OmniCast:** **stage-hash** nội dung (`core/hashing.py`) cho extract/asr/translate/tts/mix/export + checkpoint dịch theo scene. Vững hơn khi đổi model; yếu hơn ở **không check size=0** trên nhiều stage.

### 4. Kết luận job THÀNH CÔNG

- **pyvideotrans:** đi hết `assembling` không exception + `task_done` → `set_end(True)`. Trước mux: bắt buộc `novoice_mp4` tồn tại, `target_wav` nếu dubbing (`trans_create.py:1237-1243`); sau mux: copy `tmp_target_mp4` (`1463-1472`).
- **OmniCast:** `export_hardsub_video` return + `publish` + vault `done`/`review`. **Không** probe duration/playable; `publish` chỉ copy **nếu** `exported_video.is_file()` — vẫn ghi meta và mark done.

### 5. Hậu xử lý bỏ qua

- Tách/ghép lại **instrument** (nền sạch)
- `recogn2pass` (SRT khớp giọng mới)
- Freeze khung cuối + `-t` ở mux export
- Soft sub / double sub / `out_video_ext` mkv
- `only_out_mp4` flatten folder
- Metadata soft-sub language
- Intro/outro: **cả hai** không có

---

## Phát hiện (CRITICAL → MINOR)

### [CRITICAL] Không xác minh file output cuối trước khi mark `done`
- **pyvideotrans**: `help_misc.py:134-142` — `vail_file` = exists + is_file + **size > 0**. `trans_create.py:1237-1243` raise nếu thiếu `novoice`/`target_wav`; `1463-1472` chỉ coi xong khi copy được `tmp_target_mp4`.
- **OmniCast**: `runner.py:711-756` gọi `export_hardsub_video` rồi `publish_reup_product` rồi `_done("export")`. `publish.py:81-82` — nếu không `is_file()` thì **bỏ qua copy**, vẫn `write_meta`. Không check size, không probe.
- **Hậu quả thực tế:** Job xanh “done”, product folder có `meta.json`/`script.txt` nhưng **không có `video.mp4`** (hoặc file rỗng nếu đường khác tạo), UI/library tưởng đã xuất.
- **Cách vá:** Sau export + publish: assert `video_path(product_dir).is_file()` và `stat().st_size > N`; fail job nếu không. Mirror `vail_file` helper trong `reup/core/`.

### [CRITICAL] Cache stage tin `exists()` không chặn file 0 byte / hỏng
- **pyvideotrans**: `vail_file` + `_unlink_size0` (`_base.py:71-78`, `trans_create.py:176`) xóa output 0-byte trước prepare.
- **OmniCast**: `extract_audio.py:148-150`, `mixdown.py:124-126`, `hardsub.py:641-643` — cache hit chỉ cần path + manifest **exists**. TTS đã có `st_size > 44` (`pipeline.py:106-113`) — các stage khác không.
- **Hậu quả thực tế:** Lần fail để lại `mixed_audio.wav`/`audio_16k.wav` rỗng + manifest (hoặc file dở từ tool khác) → retry **skip** → ASR rỗng / mix im / export lỗi mơ hồ; hoặc “done” với audio chết.
- **Cách vá:** Helper `is_valid_media(path, min_bytes=…)` dùng mọi cache gate; 0-byte → xóa + recompute. Align `extract_audio`/`mixdown`/`hardsub` với TTS.

### [MAJOR] Không tách vocal/instrument — mix cả track gốc (có thoại ZH) vào dưới lồng tiếng
- **pyvideotrans**: `trans_create.py:214-246`, `_split_audio_byraw` + UVR (`879-902`); assemble `_separate` (`1081-1121`) amix instrument với `backaudio_volume` (mặc định 0.8 trong cfg, thường hạ volume).
- **OmniCast**: `runner.py:677-698` — `mix_audio_tracks` với `original_audio_path` = full `audio_48k` (hoặc bed đã giãn), volume profile ~0.07. **Không** stage tách nền.
- **Hậu quả thực tế:** Nghe **lồng tiếng Việt + tiếng Trung thấp** (ghost dialogue), ồn hơn video “chỉ nhạc nền”; đúng kiểu “tự chế thay vì bám pyvideotrans”.
- **Cách vá:** Thêm stage optional `separate_bgm` (UVR/spleeter như `prepare_audio.vocal_bgm`) lưu `instrument.wav`; mixdown chỉ dùng instrument (+ BGM thủ công nếu có).

### [MAJOR] Thiếu `recogn2pass` — phụ đề hardsub không được căn lại theo audio lồng tiếng
- **pyvideotrans**: `trans_create.py:421-489` + `job.py:164-165` / `only_one.py:114-115` — ASR lại `target_wav`, ghi đè `target_sub` (lỗi thì **skip im**).
- **OmniCast**: Không có; hardsub dùng timeline dịch/retime (`runner.py:545-561`, `649-661`).
- **Hậu quả thực tế:** Sau TTS/atempo, chữ **trượt** so với miệng/giọng (đặc biệt câu dài VI); user thấy phụ đề lệch dù “đã căn tốc độ video”.
- **Cách vá:** Sau `voice_track`/`retime`, optional ASR trên voice track → cập nhật SRT/ASS trước export (flag, fail-soft như pyvideotrans).

### [MAJOR] Export hardsub không chốt độ dài A/V (`-t` / freeze) — lệch chỉ bù trong retime
- **pyvideotrans**: `trans_create.py:1308-1319` `_video_extend` (tpad clone); `1401`/`1441` **`-t duration_s`** sau khi video ≥ audio.
- **OmniCast**: `retime.py:315-332` có tpad khi video ngắn hơn plan; **`hardsub.py:305-387` không `-t`/`-shortest`/tpad**. `runner.py:717` còn truyền `duration_ms=metadata.duration_ms` (gốc) dù `render_video` đã retime — chỉ ảnh hưởng progress.
- **Hậu quả thực tế:** Path không retime, hoặc retime/mux lệch sample: video **cụt tiếng** hoặc audio **thừa im** / player báo length lạ; progress bar export “xong sớm”.
- **Cách vá:** Trước mux: probe video vs mixed audio; nếu audio dài hơn → tpad video; luôn `-t` theo duration chốt. Progress dùng `retimed.duration_ms` khi có.

### [MAJOR] Dịch xong không `check_target_sub` — lệch số dòng vs timeline gốc
- **pyvideotrans**: `_base.py:93-110` — nếu `len(target)≠len(source)`, map text theo `time` về khung source.
- **OmniCast**: `translate/` không có bước tương đương; contextual pipeline ghi segment-level nhưng không guard “mọi segment vẫn 1-1 timeline TTS”.
- **Hậu quả thực tế:** Batch LLM gộp/tách dòng → TTS/slot **lệch câu**, im hoặc nói đè chỗ trống; khó debug.
- **Cách vá:** Sau persist translation: assert `count(subtitle_events)==count(segments)` và mỗi `segment_id` có text non-empty (hoặc mark review); không cho TTS nếu vỡ 1-1.

### [MAJOR] Validate media đầu vào yếu hơn prepare pyvideotrans
- **pyvideotrans**: `trans_create.py:184-193` — không video stream (trừ audio/tiqu) → raise; không audio và không SRT sẵn → raise.
- **OmniCast**: `extract_audio.py:142-143` raise nếu không audio stream; `runner` ASR raise nếu 0 segment (`403-404`). **Không** chặn sớm “file hỏng / 0 duration / không video” trước khi tốn bootstrap+ASR.
- **Hậu quả thực tế:** Job chạy lâu rồi fail muộn; hoặc video no-picture vẫn đi export.
- **Cách vá:** Trong `probe`: fail-fast nếu `duration_ms` null/0 hoặc thiếu video stream khi export hardsub.

### [MINOR] Diarization / multi-voice pipeline có ở pyvideotrans, ta không có
- **pyvideotrans**: `job.py:104-122`, `trans_create.py:491-571` — speaker.json; lỗi không chặn.
- **OmniCast**: `speaker_binding` module tồn tại nhưng **runner không gọi diariz**.
- **Hậu quả thực tế:** Phim nhiều nhân vật → **một giọng** đọc hết; kém immersive (không mất data).
- **Cách vá:** Stage optional sau ASR nếu profile bật multi-voice.

### [MINOR] Denoise / fix punctuation / LLM rephrase bỏ
- **pyvideotrans**: `trans_create.py:296-319`, `348-374`, `390-408`.
- **OmniCast:** không trong runner.
- **Hậu quả thực tế:** ASR ồn / thiếu dấu → dịch/TTS kém; không silent data loss như VAD.
- **Cách vá:** optional flags profile; không block pipeline.

### [MINOR] pyvideotrans giữ artifact khi fail; ta có thể “resume cache độc” sau fail
- **pyvideotrans**: `job.py:65-66` không xóa; user sửa SRT/file rồi chạy lại, skip file đã có.
- **OmniCast**: `queue.py:128-148` giữ workspace hợp lệ; retry dựa hash. **Không** invalidate cache stage fail giữa chừng (file tồn tại nửa vời đã nêu CRITICAL).
- **Hậu quả thực tế:** Retry “nhanh” nhưng **lặp bug** trên cache xấu.
- **Cách vá:** Khi stage fail: xóa manifest/output stage đó; hoặc version `cache_ok` chỉ set sau validate.

### [MINOR] Hàng đợi / hủy mềm
- **pyvideotrans**: `job.py:206-245` multi-worker theo GPU; `stoped_uuid_set` + `_exit()` giữa bước; `only_one` countdown.
- **OmniCast**: `queue.py` **serial 1 worker**, retry backoff 15s/60s; `CancellationToken` trong `JobContext` runner **luôn token mới, không wire cancel API** (`runner.py:147-154`).
- **Hậu quả thực tế:** Hủy job vault không dừng thread đang ffmpeg/ASR; queue backlog chậm hơn multi-GPU prepare/regcon.
- **Cách vá:** Truyền token từ queue/API; check giữa stage; optional parallel prepare-only nếu cần.

### [MINOR] Soft-sub / multi-format / only_out_mp4
- **pyvideotrans**: `taskcfg.py:173-176`, `trans_create.py:1296-1391`, `770-773`.
- **OmniCast**: hardsub ASS burn + publish `video.mp4` (`hardsub.py`, `publish.py`).
- **Hậu quả thực tế:** Không đổi được container/soft-sub không re-encode; không blocker reup Douyin mặc định.
- **Cách vá:** chỉ khi product cần.

---

## Tóm tắt ưu tiên vá

1. **CRITICAL:** Gate “output thật” + `vail_file`-style trên mọi cache/media.  
2. **MAJOR:** Tách nền / mix instrument; optional recogn2pass; chốt A/V duration ở export; 1-1 subtitle sau dịch.  
3. **MINOR:** Diariz, denoise, cancel token, multi-format.

**Cache stage-hash của OmniCast chín hơn skip-theo-file của pyvideotrans** — nhưng thiếu “file hợp lệ (size>0 / probe)” nên vẫn cùng class lỗi “tưởng xong / skip nhầm” như hai bug mẫu (ASR/VAD, align thiếu lead).
