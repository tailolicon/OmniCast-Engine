Đang đọc brief COMMON và 3_tts để thực hiện đúng nhiệm vụ.Đang đọc code TTS/lồng tiếng ở cả hai phía để đối chiếu.### [MAJOR] Không cắt im lặng đầu/cuối mỗi clip TTS (`remove_dubb_silence`)
- **pyvideotrans**: `configure/config.py:390` mặc định `remove_dubb_silence=True`. Sau khi convert mỗi câu sang WAV, `configure/base.py:120-121` gọi `tools.remove_silence_wav`. `util/help_ffmpeg.py:633-671` — `detect_nonsilent` (ngưỡng `dBFS-20`, `min_silence_len=100ms`), giữ head 80ms / tail 200ms, ghi đè file WAV.
- **OmniCast**: `reup/tts/pipeline.py` và `media/providers/tts_edge.py:87-94` / CapCut convert — chỉ synthesize + (tuỳ engine) ffmpeg mp3→wav; **không** có bước trim silence trước khi đo `duration_ms`.
- **Hậu quả thực tế**: Clip TTS thường có ~100–400ms im lặng đầu/cuối; `duration_ms` phình → `rate_align` tin câu “dài hơn slot” hơn thực → atempo mạnh hơn / giãn video nhiều hơn cần; hoặc pad im lặng thừa trong slot, lời nói trễ so với miệng nhân vật.
- **Cách vá**: Sau khi có raw WAV (trong `pipeline._one` hoặc router engine), gọi trim tương đương `remove_silence_wav` (pydub `detect_nonsilent` + padding 80/200ms), **rồi** mới probe `duration_ms` và ghi manifest.

### [MAJOR] Pool mạng 4 luồng, không có nhịp `dubbing_wait` giữa các request
- **pyvideotrans**: `configure/config.py:387-388` — `dubbing_wait=1` (giây), `dubbing_thread=1`. `tts/_base.py:52-54,155-168` — tuần tự thì `time.sleep(self.wait_sec)` sau mỗi câu; song song theo `dub_nums`. Edge riêng: `tts/_edgetts.py:18-20,42-108` — semaphore `edgetts_max_concurrent_tasks` (mặc định 10), retry `RETRY_NUMS≈4`, `RETRY_DELAY=5s`, timeout save 30s.
- **OmniCast**: `reup/tts/pipeline.py:215-224,235,283-286` — engine mạng (`edge`,`capcut`,`volcengine`,`chatterbox`) mặc định **4 workers**, `ThreadPoolExecutor` bắn song song; **không** sleep giữa job. Retry nằm ở provider (Edge: `tts_edge.py:27-28,115-140` — 6 lần, backoff 2^n giây; CapCut: `tts_capcut.py:91-101,274-285`).
- **Hậu quả thực tế**: Cùng lúc 4 request Edge/CapCut dễ dính rate-limit giữa job dài (code đã ghi nhận Edge chết ở clip ~255); job fail giữa chừng hoặc treo retry dài, mất thời gian hơn chạy 1 luồng + chờ 1s.
- **Cách vá**: Mặc định network workers=1 (hoặc 2); thêm `time.sleep` / token-bucket giữa lần gọi (env `OMNICAST_REUP_TTS_WAIT`); giữ pool cao chỉ khi user bật rõ.

### [MAJOR] Nhánh `build_voice_track` ép atempo vô hạn theo slot `end-start`, bỏ khe im lặng giữa câu
- **pyvideotrans**: `task/_rate.py:428-436,810-820` — khi có audio rate, gán `end_time = next.start` (nhường gap cho câu hiện tại); so `dubb_time` vs `source_duration` rồi rubberband/atempo + pad silence (`_concat_audio_aligned` ~639-707, 856-877).
- **OmniCast**: Runner mặc định dùng `rate_align` (`runner.py:613-647`) — đã bám gap-to-next + cap 1.2x. Nhưng khi `max_audio_speed` tắt: `voiceover_track.py:28-29,45-50,299-333` — slot = `end_ms - start_ms` (không tới câu sau); clip dài hơn → `speed = clip/slot` **không trần**, `atempo` chuỗi rồi `apad`/`atrim`.
- **Hậu quả thực tế**: Tắt rate-align (hoặc code path narration incremental vẫn `build_voice_track`): tiếng Việt dài bị bóp 1.5–3x từng câu khác nhau — giọng “lúc nhanh lúc chậm”, khó nghe; gap giữa subtitle không được dùng để chứa chỗ.
- **Cách vá**: `build_fit_filter` / fit stage dùng slot = `next_start - start` (giống `rate_align`); áp `max_audio_speed`; narration path gọi cùng planner, không fit uncapped.

### [MAJOR] Thiếu placeholder im lặng đúng độ dài khi TTS lỗi / file rỗng (fail-fast cả job)
- **pyvideotrans**: `tts/_base.py:137-148` — chỉ fail nếu **mọi** câu đều lỗi. `task/_rate.py:441-447,822-828` — thiếu file → tạo `silent_place_*.wav` đúng `source_duration`. `_run_no_rate_change_mode` 728-735: không có file thì chèn silence = độ dài subtitle.
- **OmniCast**: `pipeline.py:238-286` — exception trong `_one` / `pool.map` **raise**, dừng cả stage TTS. Provider rỗng thì raise (`router_engine.py:88-89`). `retime.py:135-144,236-237` **có** silence nếu clip thiếu trên map — nhưng map chỉ có artifact đã synth thành công; fail sớm thì không tới bước đó.
- **Hậu quả thực tế**: 1 câu CapCut/Edge fail ở phút thứ 20 → hỏng cả job, phải chạy lại (cache giúp một phần). Không có bản “thiếu vài câu, còn lại đúng timeline”.
- **Cách vá**: Tùy chọn `allow_partial_tts`: lỗi/rỗng → ghi silence WAV đúng `end_ms-start_ms`, vẫn append artifact; log số câu fail; chỉ abort nếu fail rate > ngưỡng.

### [MINOR] Biến tốc chỉ `atempo`, không Rubber Band như pyvideotrans ưu tiên
- **pyvideotrans**: `task/_rate.py:209-244,544-552` — ưu tiên `pyrubberband.time_stretch`; fallback `_precise_speed_up_audio` (atempo + `-t` cắt đúng target).
- **OmniCast**: `voiceover_track.py:32-50`, `media/retime.py:97-108,147-152` — chỉ chuỗi `atempo` 0.5–2.0.
- **Hậu quả thực tế**: Cùng hệ số tăng tốc, giọng “chipmunk/metal” và artefact formant rõ hơn rubberband, nhất là >1.3x.
- **Cách vá**: Trong `_fit_audio_segment` / `build_fit_filter`, nếu có rubberband CLI/`pyrubberband` thì dùng; không thì giữ atempo.

### [MINOR] Không re-measure độ dài clip sau trim/convert so với “kỳ vọng” timeline một lần nữa
- **pyvideotrans**: Sau TTS, align đọc lại `len(AudioSegment.from_file(...))` làm `dubb_time` (`_rate.py:448-449,830-831`) rồi mới so với slot; concat pad/cắt theo độ dài **thật**.
- **OmniCast**: Tin `duration_ms` lúc synth/cache (`pipeline.py:120-130,250`) cho `build_align_plan`; fit filter dùng con số đó, không probe lại sau fit. Cache manifest có thể lệch nếu file WAV đổi tay.
- **Hậu quả thực tế**: Hiếm khi lệch nhẹ vài chục ms/câu; tích lũy trên video dài có thể trôi phụ đề vs miệng nếu metadata sai.
- **Cách vá**: Trước `build_align_plan` và sau mỗi fit, probe lại duration WAV; reject/recompute nếu lệch > ngưỡng (vd. 50ms).

---

**Trả lời 5 câu hỏi brief (tóm tắt có chứng cứ ở trên)**  
1. **Có** — pyvideotrans cắt silence mỗi clip (mặc định bật); OmniCast **không** → đo dài ảo, căn timing sai hướng “siết/giãn quá tay”.  
2. pyvideotrans: thread mặc định **1**, wait **1s**; Edge concurrent cấu hình + retry 5s. OmniCast mạng: **4** workers, **không** wait giữa request (chỉ retry trong provider).  
3. pyvideotrans: **concat + silence pad** theo mốc thời gian. OmniCast rate-path: **concat tuần tự** theo plan; fallback: **adelay + amix** tuyệt đối. Cả hai chống trôi tốt nếu giữ mốc tuyệt đối; concat+pad dễ kiểm soát gap/pad hơn amix nhiều input.  
4. pyvideotrans: **chèn im lặng đúng slot**, job partial OK. OmniCast: **raise** ở TTS; retime **sẽ** silence nếu thiếu clip trên map nhưng thường không tới.  
5. **Có** so sánh độ dài clip vs slot (cả hai phía) khi align/fit; OmniCast không re-probe sau cache/fit như pyvideotrans.
