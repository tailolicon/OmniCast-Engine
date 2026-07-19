> Sinh boi agent nghien cuu workflow ws-research-456, 2026-07-19. Read-only.

# BÁO CÁO WS4 — Render Engine Hardening (READ-ONLY)

Repo: `E:\Project\OmniCast Engine\implementation`. Đã đọc charter `WORKSTREAMS_ParallelUpgrade.md` (WS4 dòng 48-53) + `CLAUDE.md`. Không sửa file nào.

---

## 1. BẢN ĐỒ HIỆN TRẠNG (dẫn chứng file:line)

### 1a. Renderer THẬT = monolith `render_real_video.py` (~3400 dòng)
Đây là renderer chạy production. Được gọi bằng **subprocess** từ 3 nơi:
- `src/omnicast/pipeline/steps.py:1184` (`render_script = impl_root / "render_real_video.py"`) — đường production, CÓ QA gate cứng (`_audit_rendered_output` steps.py:1218-1234).
- `src/omnicast/api/render_routes.py:29,68` (`subprocess.Popen(cmd...)`) — đường API, **CHỈ check return code** (`render_routes.py:93`), KHÔNG chạy output_audit.
- `batch_produce.py:107`.

Pipeline finishing thật nằm ở `main()` (`render_real_video.py:1998`→~3400). Thứ tự (2985-3172): concat → BGM (`music_lib`) → captions (`subtitle_sync`) → kinetics → `_mix_sfx` → `_mix_diegetic_sfx` → story-beats splice → 2-pass loudnorm master → bumpers → QA. Đây là code có năng lực thật: Ken Burns, storyboard LLM, story beats/cards, SFX diegetic, kinetic callouts, mastering −14 LUFS, word-sync caption.

### 1b. "Port vào package" = STUB CHẾT, không phải port dở
Charter nói "monolith đang port dở vào package". Thực tế đo được: **package chưa port gì cả — nó là skeleton green-field không liên quan monolith.**
- `src/omnicast/media/render_engine.py` = class `EZFFMPEG` (115 dòng, render_engine.py:19) — chỉ **build một list argument ffmpeg**, không chạy.
- `src/omnicast/media/ffmpeg.py:72-81` `_run_ffmpeg()` **trả về `RenderResult` HARD-CODED** (`duration_seconds=300.0, file_size_mb=150.0`) — không hề exec ffmpeg. Comment ngay dòng 74 tự nhận "Placeholder for actual FFmpeg execution".
- Package KHÔNG có: ken burns, storyboard, story beats, SFX, kinetics, 2-pass master, word-sync caption. Tức là ~0% năng lực monolith.
- **Nghịch lý test:** `tests/test_ezffmpeg.py` + `tests/unit/test_ffmpeg.py` test cái STUB này (code chết), còn đường render thật (`render_real_video.py`, `subtitle_sync.py`, `music_lib.py`) **gần như KHÔNG có unit test nào**. Xác minh: `test_music.py:3` import `omnicast.media.music.MusicModule` (không phải `music_lib.py`); `test_subtitle.py:3` import `omnicast.media.subtitle.SubtitleModule` (không phải `subtitle_sync.py`); `test_qa_frames.py:9` chỉ test 3 pure helper của `qa_check` (`assess_motion, freeze_spans_from_stderr, is_blank_frame`), KHÔNG test `validate_video`.

### 1c. Hai tầng QA — cái mạnh thì không gate, cái gate thì không toàn cục
- `qa_check.validate_video` (`qa_check.py:195`) — **CHẠY THẬT**, ffprobe/ffmpeg thật: video/audio stream, not_silent (volumedetect), not_blank (luma 3 điểm), hook_frame, frozen_frames (freezedetect), motion_ratio. Nhưng gọi TRONG monolith ở `render_real_video.py:3190` và **KHÔNG BLOCKING**: fail chỉ log `"render kept for inspection"` (3198-3200), monolith vẫn exit 0.
- `output_audit.OutputQualityAuditor.inspect_product` (`src/omnicast/media/output_audit.py:131`) — **CHẠY THẬT**: duration/codec/48k/stereo/192k/LUFS + visual_relevance (token overlap) + pacing (syllable-rate FFT). Đây là gate CỨNG duy nhất (`steps.py:1221` raise RuntimeError + repair budget). Nhưng **chỉ trên đường pipeline**, không có trên render_routes/CLI.

### 1d. Windows-lock retry (WinError 5): đã vá nhưng phân mảnh
Có **3 implementation trùng lặp** của cùng một retry `os.replace`:
- `render_real_video.py:1635` `_replace_retry` (tries=6, delay=5s) — dùng ở 618/699/751/836/960/3150.
- `subtitle_sync.py:25` `_safe_replace` (attempts=8, delay=0.5*(i+1)).
- `music_lib.py:126-134` vòng lặp inline trong `mix_bgm` (6 tries, delay=5s).
Còn **2 `os.replace` TRẦN** chưa vá: `render_real_video.py:1074` (`_trim_silence`) và `:1137` (`_trim_to_span`) — trên file WAV audio per-scene (ít bị AV-lock hơn mp4, rủi ro thấp nhưng vẫn trần).

### 1e. Ràng buộc ngầm + parser mong manh (khớp bằng chứng lịch sử)
- **SFX-trước-splice**: chỉ được bảo vệ bằng COMMENT (`render_real_video.py:3089-3092`), không có cưỡng chế cấu trúc. Đảo thứ tự → cue drift âm thầm.
- **Storyboard parser**: `parse_script`/`_parse_json_script` (164-245) đa định dạng (JSON array + prose + `[Heading]`); cache schema token `"sb_v16"` (`render_real_video.py:1691`) = **16 lần đổi schema** → churn cao. `_repair_json_quotes` (1653) tự vá quote LLM.
- **Story beats/cards**: đầy fail-safe phòng thủ = dấu vết vỡ nhiều lần: `_insert_story_beats` skip khi `len(segs)>6` (538), `_overlay_story_cards` yêu cầu `_MIN_GAP_S=60s` + `_is_title` ≤6 từ (635-651). `_insert_story_beats` dựng filter_complex concat phức tạp (585-616) — điểm dễ vỡ nhất.

---

## 2. LỖ HỔNG (xếp theo tác động vào chất lượng/độ tin cậy video cuối)

**G1 — Đường API/CLI không có QA gate cứng.** Render qua `render_routes.py` chỉ check `rc` (93); `qa_check` nội bộ non-blocking (3198). ⇒ Video frame đen / câm / sai scene CÓ THỂ ship nếu render ngoài pipeline. Tác động: cao nhất — độ tin cậy.

**G2 — Đường render thật gần như 0 test; test đang phủ code chết (stub).** Bất kỳ refactor/port nào cũng "mù". `parse_script`, `split_into_shots`, `_detect_story_segments`, splice math — không golden test.

**G3 — QA bỏ lọt nhiều lỗi hình ảnh quan trọng:**
- *Sai scene / nhân vật đổi mặt*: `output_audit.inspect_visual_relevance` chỉ đếm overlap token bag-of-words, ngưỡng `len(overlap) < 2` (output_audit.py:367) — cực yếu, không phát hiện ảnh-lệch-narration.
- *Card đè narration*: không có check nào xác nhận card story-beat rơi vào khoảng lặng (splice có thể phủ lên tiếng nói).
- *AV-sync / caption drift*: không đo. Vấn đề proportional-timing drift được biết (comment 3041-3044) nhưng không có post-check. `duration_match` chỉ ±30% (qa_check.py:201).
- *Frame đen giữa video*: `not_blank` chỉ lấy mẫu 0.25/0.5/0.75 (qa_check.py:269) + hook 0.2/1/2 — chèn đen ngắn giữa 2 mẫu lọt. `frozen_frames` chỉ bắt span ≥ `min(8, dur*0.35)` (qa_check.py:298) — freeze 3-5s lọt.

**G4 — Không có EDL / re-render per-segment.** Sửa 1 scene = chạy lại toàn monolith (tốn lại Flow quota/credit). `repair_budget` (steps.py:1200) chặn sau 3 fail nhưng không scope theo segment. `clips[]` là mp4 per-scene trong `work/` nhưng KHÔNG persist manifest để re-render phẫu thuật.

**G5 — Port sang package sẽ NUỐT prosody (cảnh báo chéo WS2 xác minh).** `voice_router.py:197` `synthesize(text, specs, output_path, voice_clone_path)` — **không có tham số prosody**; `provider.generate` (226) chỉ nhận `text/model/voice_clone_path/output_path`. Monolith thì có `_scene_rate`/`_scene_pitch`/`_lead_silence`/`_render_voice_provider` (render_real_video.py:2757-2838, 1194). Port render sang package mà không mang theo = prosody biến mất im lặng.

**G6 — STRICT-mode nhị nguyên.** Nhiều bước gate bằng `STRICT` (raise) vs non-strict (warn + đi tiếp): BGM (3004-3014), SFX (839), master (3154), caption (3070). Render non-strict có thể âm thầm rớt BGM/SFX/caption/master mà vẫn exit 0 và qua gate lỏng.

---

## 3. KẾ HOẠCH NÂNG CẤP (xếp hạng)

**P1 — QA thành gate cứng, dùng chung mọi đường exit.** Cho `qa_check.validate_video` exit non-zero khi hard-fail (sau env flag mặc định bật cho pipeline) TẠI `render_real_video.py:3198`; đồng thời `render_routes.py` gọi `output_audit.inspect_product` sau `rc==0`. *File:* `render_real_video.py`, `render_routes.py`. *Effort:* M. *Rủi ro:* false-fail chặn render hợp lệ → giảm nhờ split soft/hard sẵn có (qa_check.py:336). *Đo:* nhét mp4 đen/câm tổng hợp → gate reject; % video shipped có sidecar QA-fail → 0.

**P2 — Characterization tests bọc đường thật TRƯỚC khi port (điều kiện tiên quyết strangler).** Tách pure functions (`parse_script`, `_parse_json_script`, `_split_blocks`, `split_into_shots`, `_detect_story_segments`, `_repair_json_quotes`, story-beat time math) và pin bằng golden test + 1 e2e render fixture 2-scene (cần ffmpeg, mark slow). *File:* `tests/unit/test_render_parse.py` (mới), `tests/test_render_e2e.py` (mới); import từ `render_real_video`. *Effort:* M. *Rủi ro:* thấp (extract read-only). *Đo:* coverage trên parse/segment/splice; cố ý làm hỏng parser → suite bắt.

**P3 — Strangler port có parity harness.** Seam tại "scene list → final mp4". Port leaf-first: (1) thay stub `ffmpeg.py:_run_ffmpeg` bằng exec THẬT; (2) ken-burns; (3) finishing steps — mỗi bước sau feature flag, validate bằng golden-render diff (ffprobe metadata + parity `qa_check` + frame-hash N mẫu) so với monolith trên cùng script. **BẮT BUỘC mang prosody** (carry `_scene_rate/pitch/lead_silence` vào package voice path, hoặc giữ TTS trong monolith tới khi WS2 xong prosody). *File:* `render_engine.py`, `ffmpeg.py` (giết stub hard-code), submodule mới. *Effort:* L. *Rủi ro:* cao (drift hành vi) → parity harness phải khớp metadata monolith trong dung sai TRƯỚC khi lật flag.

**P4 — EDL / re-render per-segment.** Persist render manifest (EDL): mỗi scene `{index, asset_hash, voice_hash, clip_path, t_start, t_dur, visual_type}`. Lưu mp4 per-scene content-addressed trong `work/cache`. Re-render = diff EDL → chỉ recompose scene đổi → concat + finishing lại. Splice-in-place dùng lại chính graph trim/concat của `_insert_story_beats`. *File:* `media/edl.py` (mới), `render_real_video.py` (persist manifest + `--resegment idx`). *Effort:* L. *Rủi ro:* trung bình (artifact seam concat) → *Đo:* đổi 1 scene, assert chỉ clip đó re-encode (mtime), Δduration cuối == Δscene, QA vẫn pass.

**P5 — Tăng lực QA gate về nội dung.** Thêm: (a) blank/freeze check tại TỪNG scene boundary (dùng EDL times) — chèn đen giữa video không lọt; (b) card-over-narration: mỗi cửa sổ story-beat phải trùng silence span (dùng lại `silencedetect` của pacing); (c) AV-sync/caption-drift: whisper 2-3 cửa sổ so với ASS burned, hoặc assert caption coverage vs speech; (d) tùy chọn CLIP/embedding scene-relevance (mạnh hơn token overlap — giáp ranh WS1). *File:* `qa_check.py`, `output_audit.py`. *Effort:* M-L. *Rủi ro:* chi phí probe → giữ sampled, cap runtime. *Đo:* seed fixture bad (chèn đen, card đè tiếng, caption lệch) → mỗi cái bị bắt.

**P6 — Hợp nhất lock-retry + vá os.replace trần.** Một helper chung import bởi cả 3 module; thay `os.replace` trần ở 1074/1137. *File:* util mới + `render_real_video.py`, `subtitle_sync.py`, `music_lib.py`. *Effort:* S. *Đo:* grep còn 1 implementation; giả lập `PermissionError` → retry rồi raise.

**P7 — Cưỡng chế thứ tự finishing bằng cấu trúc.** Danh sách post-steps có thứ tự khai báo + guard assert SFX trước splice, thay vì comment. *File:* `render_real_video.py` main. *Effort:* S-M. *Đo:* unit test assert order; đảo → assertion fail.

---

## 4. QUICK WINS (1 buổi)

- **QW1 (P6):** Gộp 3 lock-retry thành 1 helper + vá 2 `os.replace` trần (1074, 1137). ~S.
- **QW2 (P2 subset):** Thêm characterization test cho parser thuần (`parse_script`, `_parse_json_script`, `_split_blocks`, `split_into_shots`, `_detect_story_segments`, `_repair_json_quotes`) — import trực tiếp, KHÔNG cần ffmpeg. Khóa hành vi trước khi port. ~S.
- **QW3 (P1 subset):** Env flag `OMNICAST_QA_STRICT` cho `qa_check` exit non-zero khi hard-fail (render_real_video.py:3198) + wire `render_routes.py` gọi `output_audit.inspect_product` sau `rc==0` — bịt lỗ hổng gate đường API. ~S.
- **QW4:** Cho `ffmpeg.py:_run_ffmpeg` (72-81) `raise NotImplementedError` thay vì trả `RenderResult` hard-code 300s/150MB, để không ai nhầm package renderer là chạy được; test phản ánh thực tế. ~S (đụng file trong phạm vi WS4).

---

**File liên quan (absolute):**
- `E:\Project\OmniCast Engine\implementation\render_real_video.py` (monolith thật)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\render_engine.py` (EZFFMPEG stub)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\ffmpeg.py` (FFmpegModule stub, _run_ffmpeg hard-code)
- `E:\Project\OmniCast Engine\implementation\qa_check.py` (QA thật, non-blocking)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\output_audit.py` (gate cứng, chỉ pipeline)
- `E:\Project\OmniCast Engine\implementation\subtitle_sync.py`, `music_lib.py` (đường thật, không test)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\pipeline\steps.py:1184-1234` (shell-out + gate, contract WS0/WS5)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\api\render_routes.py:29-95` (đường API, thiếu gate)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\voice_router.py:197` (prosody swallow — cảnh báo chéo WS2)