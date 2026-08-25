Đọc code ASR/phụ đề hai phía theo brief.Đang đọc VAD, merge, hậu xử lý và cách OmniCast gọi ASR.### [CRITICAL] Cache ASR không fingerprint tham số VAD / chất lượng
- **pyvideotrans**: `videotrans/process/stt_fun.py:282-298` — mỗi lần gọi `transcribe` luôn dùng bộ tham số tường minh (`condition_on_previous_text`, `no_speech_threshold`, `vad_parameters` gồm `min_silence_duration_ms=140`, `min_speech_duration_ms=0`, `max_speech_duration_s=…`); không có cache stage theo hash bỏ sót các tham số này.
- **OmniCast**: `implementation/src/omnicast/reup/asr/persistence.py:14-26` — `build_asr_stage_hash` chỉ hash `model_name`, `language`, `vad_filter`, `word_timestamps`, `compute_type`, `version:1`. Không hash `condition_on_previous_text`, `no_speech_threshold`, `vad_min_silence_ms`, `vad_threshold`. `runner.py:388-391` tái dùng `segments.json` nếu hash trùng.
- **Hậu quả thực tế**: sau khi vá VAD (140ms / threshold 0.5 / `condition_on_previous_text=False`), project cũ vẫn ăn transcript cache lúc VAD 2000ms đã nuốt vài phút thoại; người dùng vẫn thấy **mất câu** dù code đã “sửa”.
- **Cách vá**: `persistence.py` — thêm vào hash: `condition_on_previous_text`, `no_speech_threshold`, `vad_min_silence_ms`, `vad_threshold`, `max_speech_duration_s` (nếu thêm), bump `version` ≥ 2.

### [MAJOR] VAD không giới hạn `max_speech_duration_s` (để mặc định vô hạn)
- **pyvideotrans**: `videotrans/process/stt_fun.py:288` + `videotrans/recognition/_whisper.py:92` — `vad_parameters=dict(min_silence_duration_ms=140, min_speech_duration_ms=0, max_speech_duration_s=max_speech_ms/1000)` với `_max_speech = max(int(settings.max_speech_duration_s * 1000), 2000)` và mặc định `max_speech_duration_s=5` (`configure/config.py:376`) → cắt cứng đoạn nói ~5s.
- **OmniCast**: `faster_whisper_engine.py:83-86` + `models.py:39-40` — chỉ truyền `threshold` và `min_silence_duration_ms`. `VadOptions` mặc định: `max_speech_duration_s=inf`.
- **Hậu quả thực tế**: monologue dài không nghỉ (Douyin zh) thành 1–vài segment rất dài; Whisper dễ lệch timestamp/nhại; TTS+rate-align phải nhồi cả đoạn dài vào một slot → giọng tăng tốc bất thường hoặc video giật.
- **Cách vá**: `models.py` thêm `vad_max_speech_s: float = 5.0`; `faster_whisper_engine.py` đưa vào `vad_parameters["max_speech_duration_s"]` và `min_speech_duration_ms=0` như pyvideotrans.

### [MAJOR] Không hậu xử lý cắt câu lại từ word timestamps (`_resegment`)
- **pyvideotrans**: `videotrans/process/stt_fun.py:291-315` bật `word_timestamps=True` rồi gọi `_resegment` (`stt_fun.py:664-814`): giữ segment ≤ `max_speech_ms`; segment dài hơn thì cắt theo (1) vượt `max_speech_ms`, (2) dấu kết `.?!。？！`, (3) pause ≥ 800ms, (4) dấu phẩy + pause ≥ 300ms, (5) đã > 50% max + pause ≥ 400ms; ghép text CJK không space.
- **OmniCast**: `faster_whisper_engine.py:89-118` — nhận nguyên `segment` Whisper, chỉ map `words` vào `WordTimestamp`, **không** resegment.
- **Hậu quả thực tế**: một câu Whisper 15–30s thành 1 subtitle/TTS unit; bản dịch/lồng tiếng lệch nhịp rõ so với pyvideotrans; khoảng lặng giữa từ không được dùng để tách câu.
- **Cách vá**: port `_resegment` sang module ASR (vd. `reup/asr/resegment.py`), gọi sau vòng lặp segment trong `faster_whisper_engine.py` với `max_speech_ms` ~5000.

### [MAJOR] Không có `_post_fix` sau nhận dạng
- **pyvideotrans**: `videotrans/recognition/_base.py:106-138` — (a) bỏ dòng chỉ toàn dấu/ký hiệu (`NON_WORD` tại `configure/contants.py:70`); (b) sửa overlap: nếu `prev.end_time > curr.start_time` thì kéo `prev.end_time = curr.start_time`; (c) tùy chọn merge short (`merge_short_sub`, mặc định `False` trong config).
- **OmniCast**: `faster_whisper_engine.py` + `persistence.py` — ghi thẳng segment; `subtitle/qc.py:88-96` chỉ **cảnh báo** overlap, không sửa.
- **Hậu quả thực tế**: dòng `"……"` / `"。"` vào pipeline dịch–TTS; hai segment chồng thời gian làm align/voiceover xén audio hoặc chồng tiếng.
- **Cách vá**: thêm bước post-process trước `persist_transcription_result` (lọc `NON_WORD`, clamp overlap); không bắt buộc port full merge 6 phase nếu `merge_short_sub` off.

### [MAJOR] Giữ segment text rỗng; không hard-fail kiểu pyvideotrans khi iterator rỗng giữa chừng
- **pyvideotrans**: `stt_fun.py:263-265` / `313-314` — `if not text.strip(): continue`; nếu `not texts` sau khi iterate → trả lỗi `"No transcription results returned..."`. `_base.py:97-98` raise nếu không còn speech.
- **OmniCast**: `faster_whisper_engine.py:108-117` luôn `append` kể cả `text==""`; `runner.py:403-404` chỉ fail khi **list rỗng hoàn toàn**, không loại empty text.
- **Hậu quả thực tế**: segment trống tốn slot TTS/dịch, tạo “lỗ” im lặng hoặc metadata rác; khó phát hiện segment Whisper failed-but-emitted.
- **Cách vá**: `faster_whisper_engine.py` — `continue` khi `not text`; sau loop nếu `not draft_segments` thì raise.

### [MAJOR] Không đối chiếu `duration_after_vad` với độ dài audio (không phát hiện VAD nuốt thoại)
- **pyvideotrans**: dùng VAD qua faster-whisper (log nội bộ “VAD filter removed …”) và/hoặc pre-split silero/tenvad (`process/vad.py`, `_base.py:145-183`); khi `whisper_prepare` bật, `clip_timestamps` ép nhận dạng đúng các khoảng VAD (`stt_fun.py:227-257`). Không có assert coverage %, nhưng luôn biết audio duration (`_whisper.py:26`) và loại timestamp vượt `last_end_time` (`stt_fun.py:261-262`).
- **OmniCast**: `faster_whisper_engine.py:76-129` — bỏ qua `info.duration` / `info.duration_after_vad`; không so tổng span subtitle với `duration_ms`; không pre-VAD + `clip_timestamps`.
- **Hậu quả thực tế**: VAD cấu hình sai hoặc audio lạ nuốt 10–30% thoại mà job vẫn “thành công” với N segments; chỉ phát hiện khi nghe video cuối (cùng lớp bug đã mất 2:13).
- **Cách vá**: đọc `info.duration_after_vad`; nếu `1 - after/before > ngưỡng` (vd. 15%) → log error/raise hoặc warn cứng trong `runner`; tùy chọn port pre-VAD path.

### [MINOR] Không lọc segment có `end` vượt tổng thời lượng audio
- **pyvideotrans**: `stt_fun.py:202,261-262` — `if segment.end > last_end_time: continue` với `last_end_time = audio_duration/1000`.
- **OmniCast**: `faster_whisper_engine.py:106-107` — nhận mọi `end_ms` Whisper trả về.
- **Hậu quả thực tế**: timestamp ảo sau EOF làm align/export phụ đề tràn, clip cuối lệch.
- **Cách vá**: clamp/skip khi `end_ms > duration_ms` (truyền sẵn vào engine).

### [MINOR] Không có nhánh pre-VAD + batch `clip_timestamps` (và không có re-STT file lồng tiếng)
- **pyvideotrans**: `recognition/_whisper.py:50-53` (`whisper_prepare` → `_vad_split` → file `speech_timestamps`); `stt_fun.py:227-257` `BatchedInferencePipeline` + `vad_filter=False` + `clip_timestamps`. `recogn2pass` (`task/trans_create.py:421+`) là **lượt 2 trên audio dub** để subtitle ngắn, không phải merge multi-pass source.
- **OmniCast**: một lượt `model.transcribe` duy nhất trên full audio (`faster_whisper_engine.py:76-87`); không re-ASR dub.
- **Hậu quả thực tế**: trên video dài/ồn, pre-VAD silero/tenvad của pyvideotrans đôi khi bắt speech ổn định hơn pure in-model VAD; thiếu re-STT dub chỉ ảnh hưởng phụ đề nhúng sau lồng tiếng, không phải transcript nguồn.
- **Cách vá**: optional sau — port silero VAD + `clip_timestamps` khi cần; re-STT dub chỉ nếu product cần subtitle theo giọng VI.
