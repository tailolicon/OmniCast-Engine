Đọc code pyvideotrans và OmniCast liên quan căn tốc độ/giãn hình để đối chiếu theo brief.Đối chiếu thêm hằng số, chỗ gọi, và các chi tiết còn thiếu.Kiểm tra thêm nguồn `video_duration_ms` và xử lý khi encode đoạn thất bại.### [CRITICAL] Đồng bộ A/V theo `target` kế hoạch, không theo thời lượng video thật sau encode
- **pyvideotrans**: `_rate.py:387-390`, `_rate.py:648-705` — sau `setpts`, đo `actual_duration` từng clip; gán `final_duration = real_duration`; khi ghép audio, pad/cắt **theo slot video thật**, rồi ghi lại `start_time`/`end_time` trên timeline đó.
- **OmniCast**: `retime.py:283-297`, `retime.py:315-332` — timeline audio/subtitle cộng dồn `segment.target_ms` (kế hoạch); chỉ sau khi concat xong mới probe **tổng** video và `tpad` bù shortfall nếu video ngắn hơn kế hoạch (>40 ms). Không chỉnh từng đoạn theo duration encode thực tế.
- **Hậu quả thực tế**: setpts không chính xác từng đoạn → lệch A/V **tích lũy giữa video** (giọng/phụ đề trước–sau hình), dù cuối file đã freeze-frame bù tổng. Video dài vài trăm câu dễ lệch hàng trăm ms đến vài giây giữa chừng; `tpad` cuối không sửa lệch giữa các câu.
- **Cách vá**: `retime.py` — sau mỗi `_cut_video_segment`, probe duration clip; dùng duration thật làm `end_ms - start_ms` và pad/cắt audio segment tương ứng (như `_concat_audio_aligned`); chỉ dùng `tpad` làm lớp cuối nếu vẫn lệch.

### [CRITICAL] Không có fallback khi cắt/PTS video fail; clip hỏng bị nuốt im hoặc làm hỏng cả job
- **pyvideotrans**: `_rate.py:160-182`, `_rate.py:57`, `_rate.py:595-601` — file `< 1024B` hoặc fail → cắt lại **không PTS** (`setpts=PTS`); vẫn đo duration; concat **bỏ** clip invalid (log warning).
- **OmniCast**: `retime.py:75-79`, `retime.py:111-128` — `_run` raise ngay nếu ffmpeg ≠ 0; không kiểm tra size; không cắt lại không-PTS; một đoạn fail = dừng cả retime.
- **Hậu quả thực tế**: đoạn quá ngắn / PTS lỗi / keyframe xấu → job reup fail giữa chừng, hoặc (nếu lách lỗi) mất hình một đoạn. pyvideotrans vẫn ra file (có thể kém hơn) thay vì vỡ pipeline.
- **Cách vá**: `retime.py` `_cut_video_segment` — nếu fail hoặc size < 1024B, retry cắt `setpts=PTS` + duration gốc; nếu vẫn fail, log + silent/black placeholder đúng `target_ms` thay vì kill cả job.

### [MAJOR] Chiến lược audio+video khi câu dịch dài: chia đôi vs trần audio cứng
- **pyvideotrans**: `_rate.py:505-516` — cả hai bật: `ratio ≤ 1.2` → chỉ siết audio về slot; `ratio > 1.2` → `joint = source + (dubb-source)/2`, audio và video cùng target đó, **bỏ mọi trần** (đúng comment dòng 27).
- **OmniCast**: `rate_align.py:34-35`, `rate_align.py:137-149` — `DEFAULT_MAX_AUDIO_SPEED = 1.2`; vượt cap → audio luôn `1.2`, `target_ms = clip/1.2`, phần còn lại đổ hết lên `video_pts`.
- **Hậu quả thực tế**: cùng câu (vd dub 6 s / slot 3 s): pyvideotrans ≈ audio 1.33× + video 1.5×; OmniCast = audio 1.2× + video ~1.67×. Câu rất dài (30 s/2 s): OmniCast `video_pts = 12.5` (chậm hình nặng, giọng “đều nhưng chậm timeline”); pyvideotrans giãn hình nhẹ hơn, siết giọng mạnh hơn. Người xem thấy nhịp hình/giọng khác hẳn “chuẩn pyvideotrans”.
- **Cách vá**: `rate_align.py` — thêm mode `split_excess` (half-half như upstream) hoặc ít nhất document + flag; nếu giữ cap-audio, thêm `max_video_pts` (xem mục sau).

### [MAJOR] Không có trần `max_video_pts_rate` — hình có thể chậm cực đoan
- **pyvideotrans**: `_rate.py:332-333`, `config.py:372-373` — `max_audio_speed_rate` mặc định **100**, `max_video_pts_rate` mặc định **10**; mode chỉ-video áp trần PTS (`_rate.py:497-503`). Mode both >1.2 thì bỏ trần, nhưng mode only-video có bảo vệ.
- **OmniCast**: `rate_align.py:35`, `rate_align.py:146-159` — chỉ có `max_audio_speed` (mặc định 1.2); **không** có `max_video_pts`; `video_pts = target_ms/slot_ms` không trần (đo được 12.5× ở case 30 s/2 s).
- **Hậu quả thực tế**: câu dịch dài gấp nhiều lần slot → slow-mo rất nặng, stutter VFR, encode lâu, cảm giác “tua chậm”; phụ đề/slot phình theo.
- **Cách vá**: `rate_align.py` — thêm `max_video_pts` (mặc định 10); khi `target/slot` vượt trần, siết thêm audio (hoặc cắt/cảnh báo) thay vì PTS vô hạn.

### [MAJOR] Tăng tốc audio chỉ `atempo`, không Rubber Band
- **pyvideotrans**: `_rate.py:8-9`, `_rate.py:209-244`, `_rate.py:351-354`, `_rate.py:544-552` — ưu tiên `pyrubberband` + binary `rubberband`; fallback mới dùng chuỗi `atempo` (`_rate.py:247-284`), rate clamp rubberband `0.2…50`.
- **OmniCast**: `retime.py:97-108`, `retime.py:147-158` — chỉ `_atempo_chain` (0.5–2.0 xích nhau); không rubberband.
- **Hậu quả thực tế**: cùng hệ số 1.2–2×, giọng VI sau atempo dễ “kim loại”/pha hơn rubberband; càng nhiều câu bị speed-up càng rõ.
- **Cách vá**: `retime.py` `_fit_audio_segment` — nếu có rubberband/pyrb thì time-stretch như `_change_speed_rubberband`; không có thì mới atempo.

### [MAJOR] Câu đầu start &lt; 100 ms: OmniCast tạo clip lead-in siêu ngắn, dễ vỡ encode
- **pyvideotrans**: `_rate.py:424-426` — video rate bật và `start_time < 100` → `start_time_source = 0` (gộp phần mở đầu vào câu đầu, tránh clip quá ngắn).
- **OmniCast**: `rate_align.py:114-127` — mọi `ordered[0][1] > 0` đều thêm lead-in; start 50 ms → clip 50 ms riêng (`video_pts=1`).
- **Hậu quả thực tế**: clip &lt; 1 frame / rất ngắn → ffmpeg cắt fail hoặc file rỗng (kết hợp CRITICAL fallback ở trên) → job fail hoặc mất vài chục ms đầu.
- **Cách vá**: `rate_align.py` — nếu `first_start < 100` (hoặc &lt; `MIN_CLIP_MS` ≈ 40 như hằng upstream), không tạo lead-in; gán `source_start_ms=0` cho câu đầu (giống upstream).

### [MAJOR] Video dài hơn kế hoạch không bị cắt; chỉ bù khi ngắn
- **pyvideotrans**: `_rate.py:147`, `_rate.py:674-686` — `-t target` khi cắt; audio khớp `actual_duration` từng slot (cắt audio nếu dài hơn video slot khi có video rate).
- **OmniCast**: `retime.py:320-332` — chỉ `tpad` khi `cursor_ms - actual_ms > 40`; **không** trim khi video dài hơn voice/plan; timeline subtitle/audio vẫn theo `cursor_ms`.
- **Hậu quả thực tế**: nudge `+0.005` PTS (`rate_align.py:39`, `171-175`) làm nhiều đoạn hơi dài → video cuối dài hơn track giọng; hết lời vẫn còn hình, hoặc mux lệch đuôi.
- **Cách vá**: `retime.py` — sau concat, nếu `actual_ms > cursor_ms + 40` thì trim video về `cursor_ms`; kết hợp probe từng đoạn (mục CRITICAL đầu).

### [MINOR] Không gộp các đoạn `pts≈1` liền kề (cả hai bên đều cắt từng câu)
- **pyvideotrans**: `_rate.py:528-537`, `_rate.py:560-578` — mỗi subtitle (+ lead-in) một task cắt/encode; **không** merge đoạn không đổi tốc độ.
- **OmniCast**: `retime.py:14-15`, `retime.py:250-281` — cắt/encode **mọi** slot plan (kể cả lead-in và đoạn 1.0×); batch concat 60.
- **Hậu quả thực tế**: ~N câu ≈ N (hoặc N+1) lần encode libx264 — chậm, tốn đĩa; **không phải lệch so với pyvideotrans** (upstream cũng vậy). Gộp đoạn 1.0× là tối ưu thêm, không phải “bám upstream”.
- **Cách vá** (tùy chọn): `retime.py` / `rate_align.py` — gộp span `video_pts≈1` và `audio_speed≈1` liền kề thành một cut copy/`-c copy` khi có thể.

### [MINOR] Độ phủ timeline nguồn: lead-in + kéo slot tới hết video — đã khớp ý upstream; không còn lỗ “sau câu cuối” trong planner
- **pyvideotrans**: `_rate.py:428-436` (end → next start hoặc `raw_total_time`), `_rate.py:455-463` (clip 0→first start), `_rate.py:416-417` (đo lại duration file gốc).
- **OmniCast**: `rate_align.py:114-134` — lead-in `[0, first_start)`; slot `→ next_start` hoặc `video_duration_ms`; test `test_reup_retime.py:219-234` khẳng định `sum(slot_ms) == video_duration_ms`.
- **Hậu quả thực tế**: **trong planner**, không còn lỗ kiểu 6,1 s đầu hay mất trailer **nếu** `video_duration_ms` đúng. Rủi ro còn lại ở runner: `runner.py:609` — `metadata.duration_ms or max(end_ms subtitle)`; nếu ffprobe `duration` null/0, trailer sau câu cuối **bị cắt** (lỗ cùng họ với “không phủ hết video”).
- **Cách vá**: `runner.py` — trước `build_align_plan`, luôn lấy duration từ file video nguồn (ffprobe/path), không fallback `max(end_ms)` trừ khi probe fail có log rõ.

---

**Trả lời 5 câu brief (gói gọn)**  
1. **Phủ timeline:** planner phủ 0→hết video (lead-in + slot→câu sau/end); không còn lỗ “sau câu cuối” trong plan nếu duration đúng. Lỗ còn lại: duration sai / drift encode.  
2. **Trần tốc độ:** pyvideotrans `max_audio_speed_rate=100`, `max_video_pts_rate=10`; OmniCast `max_audio_speed=1.2`, **không** trần PTS.  
3. **Gộp đoạn không đổi tốc độ:** **không** (cả hai cắt từng câu).  
4. **Chống trôi TS:** pyvideotrans = gap→slot + duration thật từng clip + pad/cắt audio theo video; OmniCast = gap→slot + timeline kế hoạch + `tpad` tổng (yếu hơn).  
5. **Câu dịch dài gấp nhiều lần slot:** pyvideotrans both = chia đôi excess (bỏ trần); OmniCast = audio kẹp 1.2×, video gánh phần còn (PTS có thể &gt;10).
