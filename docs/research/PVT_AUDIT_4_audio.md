Tôi sẽ đọc hai brief đó trước, rồi thực hiện đúng nhiệm vụ và chỉ xuất report theo định dạng yêu cầu.Đang đọc code thật hai bên về tách giọng, mixdown, ducking và retime nền.### [CRITICAL] Không tách giọng/nhạc nền — trộn nguyên track gốc (kèm giọng Trung)
- **pyvideotrans**: `taskcfg.py:167-179`, `config.py:617-619`, `trans_create.py:214-246`, `trans_create.py:831-902`, `trans_create.py:1081-1119`, `prepare_audio.py:16-85` — tuỳ chọn `is_separate` (mặc định **False**); bật thì UVR/spleeter (`uvr_models` mặc định `"spleeter"`, `config.py:436`) tách `vocal.wav` + `instrument.wav`. Khi `embed_bgm=True` (mặc định), chỉ trộn lại **instrument** (không còn giọng gốc) qua `volume={backaudio_volume}` rồi `amix`.
- **OmniCast**: toàn bộ `implementation/src/omnicast/reup/` — **không** có UVR/spleeter/demucs/vocal/instrument. `runner.py:677-698` luôn lấy `audio_48k` (hoặc `retimed_bed`) làm bed; `mixdown.py:69-78` trộn full original × `original_volume`. Profile narration: `profiles.py:70-71` → `0.07`.
- **Hậu quả thực tế**: dưới giọng Việt vẫn nghe rõ (hoặc lờ mờ) **giọng Trung** + nhạc; hạ volume không xoá được lời thoại gốc. pyvideotrans mặc định thì **không** giữ audio gốc; bật tách thì chỉ còn nhạc/ambience sạch.
- **Cách vá**: thêm bước tách nguồn (UVR/spleeter như `prepare_audio.vocal_bgm`); mixdown chỉ nhận `instrument` (hoặc tắt bed hẳn nếu không tách). Sửa `runner.py` + module audio mới; bỏ thói quen “hạ full track 0.07”.

### [MAJOR] Hệ số nền / “ducking” sai ngữ cảnh so với chuẩn pyvideotrans
- **pyvideotrans**: `taskcfg.py:179`, `config.py:393` — `backaudio_volume = 0.8` áp lên **instrument đã tách**; voice TTS mặc định `volume="+0%"` (`taskcfg.py:141`). Mix: `trans_create.py:1114-1117` — `volume={backaudio_volume}` rồi `amix=inputs=2:duration=first:dropout_transition=2`. **Không** có loudness target EBU/YouTube.
- **OmniCast**: `profiles.py:70-71,113-114,156-157` — narration `original=0.07`, `voice=1.0`; không profile thì `profiles.py:317-318` → original **0.35**. `mixdown.py:78` — `amix ... normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11`.
- **Hậu quả thực tế**: 0.07/0.35 là duck **cả** giọng+nhạc → vừa lọt giọng Trung, vừa làm ambience quá yếu; 0.35 còn ồn hơn. `loudnorm` có thể kéo phần lọt tiếng gốc lên ở đoạn voice nhỏ.
- **Cách vá**: sau khi tách, đặt nền ≈ `0.8` trên instrument (có config); bỏ default 0.07/0.35 cho full-mix. Chỉnh `profiles.py`, `mixdown.py`; cân nhắc bỏ/đặt sau loudnorm chỉ khi bed sạch.

### [MAJOR] Giãn tiếng nền theo video: per-segment atempo vs kéo/lặp cả track
- **pyvideotrans**: căn video/voice xong mới `_separate()` (`trans_create.py:1280-1282`). Nếu `instrument` ngắn hơn `target_wav` hơn ~1s (`atime + 1000 < vtime`, `trans_create.py:1097-1109`): `loop_backaudio` mặc định **1** (`config.py:394`) → **lặp** cả instrument; không lặp thì `change_speed_rubberband` (`help_ffmpeg.py:497-533`) **một lần** cho cả file (pyrubberband, fallback `precise_speed_up_audio`). Tempo nền **đều** trên toàn video.
- **OmniCast**: `retime.py:162-185` `_stretch_original_bed` — mỗi segment cắt `slot_ms`, nếu `video_pts > 1.001` thì `_atempo_chain(1/video_pts)`, pad/trim `target_ms`; `retime.py:309-313` concat → `retimed_bed.wav`. `runner.py:641-687` đưa bed đó vào mixdown.
- **Hậu quả thực tế**: mỗi câu có `video_pts` khác → nhạc/ambience **nhảy tempo** giữa các câu; giọng Trung trong bed cũng bị kéo chậm méo. pyvideotrans: tempo nền ổn định (loop hoặc slow một hệ số toàn cục).
- **Cách vá**: sau voice track đủ dài, xử lý instrument **một lần** (loop hoặc rubberband toàn track) như `_separate`; không atempo per-segment trên full original. Sửa `retime.py` / `runner.py`.

### [MINOR] `amix` thiếu `duration=first` và `dropout_transition`
- **pyvideotrans**: `trans_create.py:1070`, `1115-1117` — `amix=inputs=2:duration=first:dropout_transition=2` (độ dài theo voice; fade 2s khi một nhánh hết).
- **OmniCast**: `mixdown.py:78` — `amix=inputs=N:normalize=0` (mặc định duration=longest, không dropout); `narration_incremental.py:180` tương tự.
- **Hậu quả thực tế**: bed/voice lệch vài chục–vài trăm ms → đuôi thừa/cúp cụt; hết một track có thể **cúp volume đột ngột** thay vì fade.
- **Cách vá**: trong `mixdown.py` (và `narration_incremental.py`) thêm `duration=first:dropout_transition=2` (voice = input 0/1 thống nhất với pyvideotrans).

### [MINOR] Chuẩn hoá loudness cuối — chỉ OmniCast có; pyvideotrans không
- **pyvideotrans**: sau mix chỉ `-ac 2 -b:a 128k -c:a pcm_s16le` / aac (`trans_create.py:1115-1190` vùng mix/export) — **không** `loudnorm` / LUFS target.
- **OmniCast**: `mixdown.py:78` — `loudnorm=I=-16:TP=-1.5:LRA=11` (gần YouTube/EBU R128).
- **Hậu quả thực tế**: không phải bug “thiếu bước pyvideotrans”; nhưng loudnorm trên bed **còn giọng Trung** có thể làm tiếng lọt nổi hơn ở đoạn voice yếu.
- **Cách vá**: giữ loudnorm sau khi bed chỉ còn instrument; trước đó không loudnorm trên full original+voice.
