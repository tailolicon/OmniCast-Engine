Tôi sẽ quét vét cạn toàn bộ slice constants/defaults: đọc hết `pyvideotrans` configure + codes, rồi đối chiếu với OmniCast `reup/` và `ingest/douyin/`.Đang đọc toàn bộ `configure/` và `codes/` của pyvideotrans trước.Đã đọc xong configure; tiếp theo quét hằng số rải rác trong pyvideotrans và toàn bộ OmniCast reup.Đã quét xong configure (7 file), codes, hằng số rải trong recognition/stt/rate, và toàn bộ `reup/` + ingest defaults. Báo cáo đối chiếu dưới đây.

---

# Report Agent 8 — Đối chiếu hằng số & mặc định (pyvideotrans ↔ OmniCast reup)

## BẢNG ĐỐI CHIẾU

| Hằng số | pyvideotrans | OmniCast | Lệch? | Hậu quả |
|--------|--------------|----------|-------|---------|
| **ASR model mặc định** | `large-v3-turbo` (`params.json` default, `config.py:630`) | `small` (`core/settings.py:126`, runner dùng `default_asr_model`) | **Có** | ASR zh kém hơn rõ trên video dài; sai/mất chữ nhiều hơn |
| **vad_filter** | `True` khi không pre-split (`stt_fun.py:287`) | `True` (`asr/models.py:29`, `runner.py:381`) | Không | — |
| **condition_on_previous_text** | `False` (`config.py:437`, `stt_fun.py:286`) | `False` (`asr/models.py:35`) | Không | Đã vá bug drift |
| **no_speech_threshold** | `0.6` (`config.py:380`; caller `_whisper.py:102`) | `0.6` (`asr/models.py:41`) | Không | — |
| **VAD threshold** | settings `0.5` (`config.py:374`); path faster-whisper **không** truyền `threshold` trong `vad_parameters` → dùng mặc định thư viện 0.5 | `0.5` explicit (`asr/models.py:40`, engine:84) | Không (cùng 0.5) | — |
| **min_silence_duration_ms** | `140` hardcode trong `vad_parameters` (`stt_fun.py:288`); settings default cũng 140 | `140` (`asr/models.py:39`) | Không | Đã vá bug cắt 2000ms |
| **min_speech_duration_ms (VAD whisper)** | hardcode `0` trong `vad_parameters` (`stt_fun.py:288`) | **không truyền** → mặc định silero/faster-whisper **~250ms** | **Có** | Câu/thán từ rất ngắn có thể bị VAD bỏ |
| **max_speech_duration_s (VAD whisper)** | settings `5` (`config.py:376`); caller `max(5s*1000,2000)=5000ms` → `max_speech_duration_s=5` (`_whisper.py:92`, `stt_fun.py:288`) | **không truyền** → mặc định thư viện **∞** | **Có** | Segment ASR dài bất thường; phụ đề/câu dịch/TTS quá dài, khó căn |
| **min_speech_duration_ms (VAD pre-split silero/ten)** | `2000` (`config.py:375`); clamp ≥0, tenvad ≥500 (`recognition/_base.py:152-155`) | Không có pre-split VAD riêng | N/A (kiến trúc khác) | pvt có pipeline 2-pass; reup chỉ dùng VAD built-in Whisper |
| **max_speech_duration_s2 / min_speech_ms2** | `2` s / `1000` ms cho recogn2pass (`config.py:377-378`) | Không có | N/A | — |
| **vad_type** | `"silero"` (`config.py:383`) | Chỉ VAD của faster-whisper | Khác stack | — |
| **beam_size** | `5` (`config.py:433`, truyền `stt_fun.py:284`) | **không truyền** → mặc định thư viện **5** | Không (trùng default lib) | An toàn hiện tại; đổi lib = đổi hành vi |
| **best_of** | `5` (`config.py:434`) | **không truyền** → lib **5** | Không | Như trên |
| **temperature (ASR)** | `""` → schedule `[0,0.2,…,1.0]` (`stt_fun.py:213-221`) | **không truyền** → lib cùng schedule fallback | Không (thực tế) | — |
| **repetition_penalty** | `1.0` (`config.py:439`) | **không truyền** → lib `1.0` | Không | — |
| **compression_ratio_threshold** | settings `2.4` (`config.py:440`); faster path truyền **2.2** (`_whisper.py:116`) | **không truyền** → lib **2.4** | **Có** (2.4 vs 2.2) | Ít lọc “lặp/nén” hơn pvt path faster → dễ dính ảo giác lặp |
| **word_timestamps** | `True` khi không pre-split (`stt_fun.py:291`) | `True` | Không | — |
| **initial_prompt / hotwords** | Có per-lang + hotwords (`config.py:397+`, `_whisper.py:110-111`) | Không | **Có** | ASR zh ít gợi ý domain → sai tên riêng/thuật ngữ |
| **cuda_com_type** | `"default"` (`config.py:396`) | GPU `float16` / CPU `int8` (`faster_whisper_engine.py:72`) | Có (cách chọn) | CPU chậm hơn/ít chính xác hơn nếu default khác |
| **max_audio_speed_rate** | **100** (`config.py:372`) — trần cứng chế độ only-audio | **1.2** hard-cap luôn (`rate_align.py:35`) | **Có** (ý đồ khác) | pvt cho phép tăng tốc audio rất mạnh; OmniCast giữ giọng ≤1.2x, dư ra giãn video |
| **Ngưỡng “chỉ audio” trong Both** | `ratio <= 1.2` → chỉ atempo, không giãn video (`_rate.py:509-511`) | Cùng số **1.2** nhưng là **cap cứng**, dư → video (`rate_align.py:141-148`) | **Có** (thuật toán) | pvt chia đôi phần dư (`diff/2`); OmniCast dồn hết phần >1.2x sang video → video dài hơn pvt Both-mode |
| **max_video_pts_rate** | **10** (`config.py:373`, clamp `_rate.py:502-503`) | **không có** | **Có** | Video có thể giãn >10× trên câu dub cực dài → giật/khung bất thường |
| **PTS_NUDGE** | `+0.005` (`_rate.py:140`) | `0.005` (`rate_align.py:39`, `build_setpts_filter`) | Không | — |
| **fps_mode (retime)** | default `"vfr"` (`config.py:341`); retime dùng vfr (`_rate.py:322`) | `vfr` (`media/retime.py:123`) | Không | — |
| **GOP retime** | `-g 1` (comment “keyframe mỗi frame”, `_rate.py` cut path) | `_GOP="1"` (`retime.py:32`) | Không | — |
| **CRF retime (segment)** | `"20"` (`_rate.py:338`) | `"20"` (`retime.py:33`) | Không | — |
| **preset retime** | `"veryfast"` (`_rate.py:339`) | `"veryfast"` (`retime.py:34`) | Không | — |
| **CRF export cuối** | settings **`23`** (`config.py:340`; `trans_create.py:1356`) | preset YouTube **`18`** (`bootstrap.py:68`, `exporting/models.py:17`) | **Có** | File to hơn, chất lượng cao hơn pvt default |
| **preset export cuối** | `"medium"` (`config.py:348`) | `"medium"` hardsub (`hardsub.py:462`); retime intermediate `veryfast` | Gần khớp export | — |
| **NVENC** | auto codec probe (`help_ffmpeg.py`) | `NVENC_CQ=25`, `NVENC_PRESET=p5` (`hardsub.py:48-49`) | Khác (OmniCast có) | — |
| **video_codec default** | H.264 = 264 (`config.py:352`) | `h264` / libx264 | Không | — |
| **out container** | `.mp4` | `mp4` | Không | — |
| **backaudio_volume (BGM/instrument)** | **0.8** (`config.py:393`) | BGM default **0.2** (`mixdown.py:54`); original bed profile **0.07** (`profiles.py:70`) | **Có** | pvt BGM to; reup duck original rất sâu dưới lồng tiếng (thiết kế reup zh→vi) |
| **loop_backaudio** | `1` (loop) (`config.py:394`) | BGM: `-stream_loop -1` khi có bgm (`mixdown.py:66`) | Gần | — |
| **original_volume fallback** | (tách instrument 0.8) | `0.35` nếu không profile (`profiles.py:317-318`) | Khác | — |
| **voice_volume** | (TTS full rồi amix) | `1.0` | — | — |
| **loudnorm mix** | Không (amix + volume) | `loudnorm=I=-16:TP=-1.5:LRA=11` (`mixdown.py:78`) | **Có** | OmniCast normalize to hơn; có thể nén dải động |
| **remove_dubb_silence** | `True` — cắt silence đầu/cuối WAV TTS (`config.py:390`, `base.py:120-121`) | **Không có** | **Có** | Clip TTS dài hơn thật → tăng atempo/giãn video không cần thiết |
| **TTS → wav** | 48k stereo pcm_s16le (`base.py:107-111`) | retime/mix: 48k; TTS sample_rate preset 22050/24000 | Khác giai đoạn | resample lúc mix |
| **voice_autorate / video_autorate** | default True / False (`params` `config.py:634-635`) | reup luôn rate-align khi `max_audio_speed` set (default 1.2) | Khác UX | — |
| **edgetts_max_concurrent** | `10` (`config.py:343`) | network TTS workers **`4`** (`tts/pipeline.py:217`) | **Có** | pvt nhanh hơn Edge; OmniCast ít 429 hơn (có comment) |
| **edgetts_retry_nums** | `3` | queue job `DEFAULT_MAX_ATTEMPTS=3` (`queue.py:31`); không riêng Edge | Gần | — |
| **dubbing_thread** | `1` (`config.py:388`) | local TTS workers **1**; network 4 | Gần | — |
| **dubbing_wait** | `1` s (`config.py:387`) | Không delay giữa clip | **Có** | Ít throttle API TTS |
| **trans_thread / aitrans_thread** | `10` / `50` (`config.py:384-385`) | job pool max **4** (`jobs.py:185`); translate batch tuần tự theo scene | **Có** | pvt song song dịch mạnh hơn |
| **batch_nums (dịch)** | `0` = concurrent (`config.py:357`) | `CONTEXTUAL_STAGE_BATCH_SIZE=8`, narration fast `16` (`contextual_pipeline.py:27`, `contextual_runtime.py:56`) | **Có** (khác đơn vị) | OmniCast batch theo segment/scene |
| **aitrans_temperature** | `0.1` (`config.py:355`) | **`0.2`** (`openai_engine.py:150`) | **Có** | Dịch “nhiệt” hơn, ít ổn định hơn chút |
| **retry_nums (settings)** | `1` (`config.py:456`) | queue **3 attempts**, backoff 15s/60s (`queue.py:31-32`) | **Có** | OmniCast bền job hơn |
| **translation_wait** | `0` | Không | Không | — |
| **cjk_len / other_len** | `15` / `40` (`config.py:446-447`) — wrap/cắt dòng phụ đề | QC `max_cpl=42` (`subtitle/qc.py:21`); ASS FontSize profile 12/42 | **Có** | pvt dòng CJK ngắn hơn; reup cho dòng dài hơn trước khi QC warn |
| **SubtitleQc max_cps / min_dur / max_dur** | (logic khác trong util) | `18` cps, `800`–`7000` ms, max 2 dòng (`qc.py:20-24`) | N/A so sánh 1-1 | — |
| **del_end_punc** | `True` — xóa punct cuối dòng ASR (`config.py:345`) | Không | **Có** | Ký tự `。！？` còn trong source; ít ảnh hưởng sau dịch |
| **merge_short_sub** | `False` default settings (`config.py:382`); code fallback `True` nếu get (`_base.py:130`) | Không merge ASR | **Có** | pvt có thể gộp dòng ngắn; reup giữ segment thô |
| **countdown_sec** | `30` | Không (CLI/headless) | N/A UI | — |
| **process_max / process_max_gpu / multi_gpus** | `0` / `1` / `False` | Job workers ≤4; cut workers `cpu//2` clamp 2–8 (`retime.py:47`) | Khác | — |
| **_CONCAT_BATCH retime** | (khác) | `60` (`retime.py:50`) | OmniCast only | Tránh CLI quá dài |
| **voiceover max_batch_inputs** | — | `24` (`voiceover_track.py:25`) | — | — |
| **HF_HUB_DOWNLOAD_TIMEOUT** | `"3600"` env (`config.py:65`) | Không set | **Có** | Download model có thể timeout sớm hơn trên net chậm |
| **OMP_NUM_THREADS** | `"1"` (`config.py:54`) | Không set | **Có** | Có thể oversubscribe CPU khi torch/ct2 |
| **noise_separate_nums** | `4` | Không (tách nhạc) | N/A | — |
| **Douyin thread** | (không trong pvt) | `5` (`ingest/.../default_config.py:50`) | N/A | — |
| **Douyin rate_limit** | — | `2` req/s + jitter 0–0.5s | N/A | — |
| **Douyin retry_times** | — | `3`, delays 1/2/5s | N/A | — |
| **mixdown/ffmpeg timeout** | (runffmpeg không 240s cứng) | `timeout=240` nhiều chỗ | OmniCast | Job dài có thể bị kill sớm |
| **ffprobe timeout** | — | `30` s (`ffprobe_service.py`) | — | — |
| **SAPI TTS timeout** | — | `120` s | — | — |
| **align_sub_audio** | `True` (`params`) | Retime + shift subtitle (`runner` + `retime`) | Khác implement | — |
| **embed_bgm / is_separate** | True / False defaults | Mix original bed + optional bgm | Khác | — |
| **FunASR / codes/model.py** | FunASRNano defaults: `ctc_weight=0.3`, `max_token_length=1500`, `max_length=512` generate | reup **không dùng** FunASR | N/A | Slice codes không ảnh hưởng pipeline reup hiện tại |

---

## Phát hiện nghiêm trọng (định dạng COMMON.md)

### [CRITICAL] VAD whisper thiếu `max_speech_duration_s` — segment ASR có thể dài vô hạn
- **pyvideotrans**: `configure/config.py:376` default `max_speech_duration_s=5`; `recognition/_whisper.py:92-96` tính `max_speech_ms`; `process/stt_fun.py:288` đưa vào `vad_parameters=dict(..., max_speech_duration_s=max_speech_ms/1000)`.
- **OmniCast**: `asr/faster_whisper_engine.py:83-86` chỉ truyền `threshold` + `min_silence_duration_ms`; `asr/models.py` không có field max speech.
- **Hậu quả thực tế**: VAD không cắt đoạn thoại dài → một segment 30–90s, dịch/TTS một cục, căn tốc độ ép video giãn mạnh hoặc giọng vội; dễ “mất nhịp” so với pvt.
- **Cách vá**: Thêm `vad_max_speech_s: float = 5.0` (và tùy chọn `vad_min_speech_ms: int = 0`) vào `TranscriptionOptions`; truyền trong `vad_parameters` giống `stt_fun.py:288`.

### [MAJOR] `min_speech_duration_ms` không set → mặc định thư viện ~250ms
- **pyvideotrans**: `stt_fun.py:288` hardcode `min_speech_duration_ms=0` (tắt lọc độ dài tối thiểu).
- **OmniCast**: không truyền → **dùng mặc định thư viện: ~250**.
- **Hậu quả thực tế**: Tiếng thốt, “嗯/啊”, từ đơn ngắn bị VAD bỏ → mất phụ đề/dòng thoại ngắn (cùng họ bug “mặc định thư viện” như silence 2000ms).
- **Cách vá**: Truyền `min_speech_duration_ms=0` trong `vad_parameters` (hoặc field options = 0).

### [MAJOR] Không có trần `max_video_pts_rate`
- **pyvideotrans**: `config.py:373` = `10`; `_rate.py:502-503` clamp `video_target`.
- **OmniCast**: `rate_align.py` chỉ cap audio speed; `video_pts = target_ms/slot_ms` không trần.
- **Hậu quả thực tế**: Câu Việt dài hơn slot nhiều lần → đoạn video giãn 15×–50×, chậm bất thường / artifact encode.
- **Cách vá**: Thêm `DEFAULT_MAX_VIDEO_PTS = 10` trong `rate_align.py`; khi `target_ms/slot_ms > cap` thì clamp và chấp nhận audio vẫn hơi nhanh hơn cap hoặc cắt/pad theo policy rõ ràng.

### [MAJOR] Không cắt silence đầu/cuối clip TTS (`remove_dubb_silence`)
- **pyvideotrans**: `config.py:390` `remove_dubb_silence=True`; `configure/base.py:120-121` gọi `remove_silence_wav` sau convert wav.
- **OmniCast**: không có bước tương đương trong `tts/` / `voiceover_track` / `retime`.
- **Hậu quả thực tế**: Đo lường duration clip “phình” vì silence tail → plan rate_align nghĩ cần speed/giãn video dù phần lời không dài.
- **Cách vá**: Sau synthesize, trim silence (port `tools.remove_silence_wav` hoặc `silenceremove`) trước khi đo `clip_duration_ms`.

### [MAJOR] `compression_ratio_threshold` lệch path faster của pvt
- **pyvideotrans**: settings `2.4` nhưng `_whisper.py:116` truyền **2.2** vào faster-whisper.
- **OmniCast**: không truyền → **mặc định thư viện: 2.4**.
- **Hậu quả thực tế**: Ít reject segment “lặp/nén bất thường” hơn pvt → ảo giác lặp câu trên audio ồn.
- **Cách vá**: Truyền `compression_ratio_threshold=2.2` (và `beam_size`/`best_of` explicit) trong `model.transcribe(...)`.

### [MAJOR] Model ASR mặc định `small` vs `large-v3-turbo`
- **pyvideotrans**: `params` default `model_name="large-v3-turbo"` (`config.py:630`).
- **OmniCast**: `default_asr_model="small"` (`core/settings.py:126`).
- **Hậu quả thực tế**: Sai chữ zh hàng loạt → dịch/TTS sai nghĩa; người dùng thấy “phụ đề lệch nội dung”.
- **Cách vá**: Đổi default lên `large-v3-turbo` (hoặc `medium`) khi GPU; giữ `small` chỉ làm fallback CPU.

### [MAJOR] Thuật toán trần tốc độ audio khác pvt Both-mode (không chỉ số)
- **pyvideotrans**: Both: nếu `ratio<=1.2` chỉ audio; else `joint_target = source + (diff/2)` — chia đôi dư cho audio+video (`_rate.py:505-516`). Settings `max_audio_speed_rate=100` gần như không chặn.
- **OmniCast**: hard-cap audio `1.2`, **toàn bộ** phần vượt dồn video (`rate_align.py:141-148`).
- **Hậu quả thực tế**: Cùng input, video reup dài hơn pvt; giọng đều hơn nhưng timeline “dãn” nhiều hơn mong đợi so với bản pvt.
- **Cách vá**: Nếu muốn bám pvt: implement nhánh Both (half-split) + optional `max_audio_speed_rate`/`max_video_pts_rate` từ config; nếu giữ cap 1.2 thì **document** rõ và vẫn thêm cap PTS.

### [MINOR] Nhiệt độ dịch 0.2 vs 0.1
- **pyvideotrans**: `aitrans_temperature=0.1` (`config.py:355`).
- **OmniCast**: `temperature=0.2` (`translate/openai_engine.py:150`).
- **Hậu quả thực tế**: Cùng prompt, bản dịch biến thiên/“bay” hơn chút.
- **Cách vá**: Hạ `temperature=0.1` trong `openai_engine` / llm backends.

### [MINOR] Âm lượng BGM/original khác hẳn (0.8 vs 0.07/0.2)
- **pyvideotrans**: `backaudio_volume=0.8` (`config.py:393`).
- **OmniCast**: profile narration `recommended_original_volume=0.07`, bgm `0.2` (`profiles.py:70`, `mixdown.py:54`).
- **Hậu quả thực tế**: Reup duck nền mạnh (cố ý zh→vi); so pvt thì nền nhỏ hơn nhiều — không phải bug nếu intentional.
- **Cách vá**: Chỉ chỉnh nếu muốn parity pvt; expose hằng trong settings.

### [MINOR] CRF export 18 vs 23; loudnorm có/không
- **pyvideotrans**: export `crf=23`, `preset=medium`; mix không loudnorm.
- **OmniCast**: `crf=18` + `loudnorm=I=-16:TP=-1.5:LRA=11`.
- **Hậu quả thực tế**: File to hơn, loudness chuẩn streaming; khác “âm thanh cảm nhận” so pvt.
- **Cách vá**: Đồng bộ crf/preset nếu cần parity dung lượng; loudnorm giữ nếu muốn YouTube.

### [MINOR] Env ổn định (`OMP_NUM_THREADS=1`, `HF_HUB_DOWNLOAD_TIMEOUT=3600`)
- **pyvideotrans**: `configure/config.py:54-65`.
- **OmniCast**: không set khi load ASR.
- **Hậu quả thực tế**: Hiếm — download model timeout; contention CPU khi multi-thread.
- **Cách vá**: Set env tương tự khi khởi tạo engine ASR (process-level).

---

## Ghi chú phạm vi

- Đã đọc **hết** 7 file `videotrans/configure/` + `videotrans/codes/model.py`.
- Hằng số rải: `process/stt_fun.py`, `recognition/_whisper.py`, `_base.py`, `task/_rate.py`, `task/trans_create.py`.
- OmniCast: toàn bộ defaults trong `reup/` (ASR, rate, retime, mix, export, TTS workers, translate batch, queue) + `ingest/douyin/_vendor/config/default_config.py`.
- `codes/model.py` (FunASRNano) **không** có counterpart trong reup — ghi N/A, không bịa ảnh hưởng output reup.
- Hai bug đã biết (VAD silence 2000 / lead-in) **đã được vá** trong OmniCast hiện tại (`condition_on_previous_text=False`, `vad_min_silence_ms=140`, lead-in trong `rate_align.py`).
