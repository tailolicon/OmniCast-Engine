Tôi sẽ đọc code thật hai bên (subtitle, hardsub, pipeline order) rồi đối chiếu theo brief.### [MAJOR] Không wrap dòng phụ đề trước khi burn-in
- **pyvideotrans**: `videotrans/task/trans_create.py:1137-1180` + `videotrans/util/help_srt.py:457-520` — trước khi nhúng, mọi dòng qua `simple_wrap()`: CJK dùng `cjk_len` (mặc định **15**, `config.py:446`), ngôn ngữ khác dùng `other_len` (mặc định **40**, `config.py:447`); ưu tiên ngắt tại `, . ? ! ; ，。？；！` và khoảng trắng, không đủ thì cắt cứng.
- **OmniCast**: `implementation/src/omnicast/reup/subtitle/export.py:116-130` — ghi nguyên `subtitle_text`/`translated_text` vào ASS/SRT, **không** wrap. `subtitle/qc.py:19-24` có `max_cpl=42` nhưng **không** được `runner.py` gọi.
- **Hậu quả thực tế**: câu Việt dài (thường >40–60 ký tự) chạy một dòng ngang màn hình, che mặt/logo, hoặc tràn mép; trên short/vertical càng tệ.
- **Cách vá**: port `simple_wrap` (hoặc gọi logic tương đương) trong `export.py` ngay trước khi tạo `SSAEvent` / ghi SRT; với `vi` dùng maxlen ≈ 40–60, ưu tiên dấu câu; chỉ wrap bản burn-in, không đụng text TTS.

### [MAJOR] Font/style ASS không cùng hệ quy chiếu với “số đẹp trên 1080p”
- **pyvideotrans**: `help_srt.py:293-294` chuyển SRT→ASS bằng ffmpeg; ffmpeg ghi sẵn `PlayResX: 384`, `PlayResY: 288` (đã chạy thử xác nhận). Style mặc định `set_ass.py:20-51` / `help_srt.py:311-334`: **Arial, Fontsize 16, Outline 0.5–1, Shadow 0.5, MarginL/R/V 10, Alignment 2**. Không gắn PlayRes theo độ phân giải video.
- **OmniCast**: `export.py:112-141` — pysubs2 **không** ghi `PlayResX/Y` (libass fallback 384×288, đã ghi trong `media/overlay.py:124-128`). Bootstrap `project/bootstrap.py:125-130` đặt **FontSize 42**; profile zh→vi ghi đè **FontSize 12** (`profiles.py:86-92`, `171-178`); MarginV profile **48** vs pyvideotrans **10**.
- **Hậu quả thực tế**: cùng hệ 384×288, `FontSize` 12 ≈ bình thường trên 1080p; nếu job không apply profile (hoặc style bị seed lại về 42) phụ đề phình to (~3.5×). MarginV 48 kéo chữ lên cao hơn pyvideotrans rõ rệt. Đổi 720p/1080p/4K thì **cả hai** scale theo tỉ lệ frame/PlayRes — kích thước tương đối gần ổn định; **không** phải “PlayRes = pixel video” ở hai bên.
- **Cách vá**: trong `export.py` khi build ASS, set `subs.info["PlayResX"]="384"`, `PlayResY="288"` (khớp pyvideotrans/ffmpeg) **hoặc** PlayRes = width/height video rồi scale FontSize/Margin theo tỉ lệ; thống nhất default FontSize/MarginV với profile (12 / 48 hoặc 16 / 10); tránh bootstrap 42 nếu chưa chắc profile chạy.

### [MAJOR] Hardsub final không khóa thời lượng / kiểm tra track audio như pyvideotrans
- **pyvideotrans**: `trans_create.py:1236-1243` — bắt buộc `novoice.mp4` tồn tại; nếu có dubbing thì `target_wav` phải `vail_file` (tồn tại + size > 0, `help_misc.py:134-141`). `1308-1319` so sánh duration video vs audio, thiếu thì `_video_extend` (`tpad=stop_mode=clone`). Mux dùng **`-t duration_s`** (`1401`, `1441`).
- **OmniCast**: `hardsub.py:305-387`, `592-721` — chỉ check source video + file subtitle tồn tại; map audio `0:a?` hoặc replacement; **không** `-t`, **không** so duration, **không** kiểm tra output có audio / duration khớp. Retime path đã bù khung cuối (`retime.py:315-332`) nhưng hardsub vẫn không clamp. `runner.py:717` còn truyền `duration_ms=metadata.duration_ms` (duration **gốc**) dù video đã stretch.
- **Hậu quả thực tế**: khi audio/video lệch vài trăm ms–vài giây (mixdown, path tắt rate-align, drift encode), video xuất cắt cụt lời hoặc kéo im lặng/đen; progress bar export sai; job vẫn `done` nếu ffmpeg exit 0.
- **Cách vá**: sau mux, ffprobe output: bắt buộc có audio stream, `|dur_out - dur_audio|` trong ngưỡng; thêm `-t` theo max(video, audio) đã align; hardsub nhận `duration_ms=retimed.duration_ms` (hoặc probe `render_video`).

### [MINOR] ASS hardsub: filter `ass=` vs `subtitles=`, không có bước style ASS “Default + Bottom”
- **pyvideotrans**: hardsub dùng `subtitles=filename='…'` (`trans_create.py:1424-1425`); ASS sau `set_ass_font` có style **Default + Bottom**, bilingual qua `###` + `{\rBottom}` (`help_srt.py:337-438`, `trans_create.py:1156-1168`).
- **OmniCast**: `hardsub.py:259-261` — `ass='…'`; bilingual/subtext bằng override `{\fs…}` inline (`export.py:75-80`), không style Bottom riêng.
- **Hậu quả thực tế**: thường ổn với ASS thuần; đổi softsub/SRT burn hoặc font đặc biệt có thể khác hành vi libass/ffmpeg; subtext hai dòng khó chỉnh màu/viền độc lập như pyvideotrans.
- **Cách vá**: giữ `ass=` nếu chỉ burn ASS; nếu cần parity bilingual, thêm style Bottom trong `export.py` giống `help_srt.py`.

### [MINOR] Pipeline thiếu bước bảo vệ chất lượng phụ đề sau dịch / sau TTS
- **pyvideotrans** thứ tự (`task/job.py:76-204` + `trans_create.py`):  
  `prepare → recogn → diariz → trans → dubbing → align → (recogn2pass) → assembling → task_done`.  
  `check_target_sub` (`_base.py:93-110`) kéo số dòng dịch về timeline gốc khi lệch. Align ghi lại SRT theo thời gian TTS (`trans_create.py:710-719`). `vail_file` / size=0 dọn trước và sau các stage.
- **OmniCast** (`runner.py`):  
  `download → bootstrap → probe → extract_audio → asr → translate → subtitles → tts → voice_track(+retime) → mixdown → export`.  
  Có review gate trước TTS; **không** có `check_target_sub`, **không** `recogn2pass`, **không** QC wrap/cps trước export.
- **Hậu quả thực tế**: lệch số dòng dịch (backend lạ) → TTS/sub lệch slot im lặng; phụ đề dài/CPS cao chỉ lộ khi xem video; không có “lưới an toàn” dòng cuối trước khi tuyên bố xong.
- **Cách vá**: trước export gọi `analyze_subtitle_rows` (fail hoặc auto-wrap nếu `max_cpl` vượt); sau translate assert `len(source)==len(target)` theo `segment_id`; optionally re-time sub từ timeline retime (đã có `shift_subtitle_rows`) và từ chối job nếu 0 event text.

### [MINOR] Progress / “job done” không phản ánh độ dài thật sau retime
- **pyvideotrans**: progress ghép theo `out_time` + duration video đã extend (`trans_create.py:1498-1517`); `task_done` (`748-778`) chủ yếu dọn file + signal succeed, **không** so số dòng phụ đề, nhưng đã chặn sớm bằng `vail_file` các artifact bắt buộc.
- **OmniCast**: `hardsub.py:398-408` + `runner.py:717` — % progress dựa `metadata.duration_ms` gốc; `runner.py:241-250` / `746` đánh `done` khi ffmpeg + publish xong, không probe duration/audio/subtitle count.
- **Hậu quả thực tế**: UI báo progress “kẹt 99%” hoặc nhảy sai trên video đã giãn; file hỏng vẫn có thể vào product nếu ffmpeg lạ trả 0 (hiếm) mà không có guard duration.
- **Cách vá**: truyền đúng duration retimed; sau `export_hardsub_video` probe và so với `mixed_audio` / plan `output_duration_ms` trước `publish_reup_product`.

---

**Trả lời thẳng 5 câu hỏi brief**

1. **PlayRes**: pyvideotrans **có** PlayRes 384×288 (ffmpeg SRT→ASS), **không** set theo kích thước video. OmniCast **không** khai → libass cũng 384×288. Hai bên cùng hệ; “đúng hơn” cho WYSIWYG pixel-video là set PlayRes = WxH video **và** scale style; với ScaledBorderAndShadow, hệ 384×288 ổn định hơn khi đổi độ phân giải nguồn.
2. **Style**: pyvideotrans Arial/16/Outline~1/Shadow0.5/Margin10; OmniCast profile Arial/12/Outline2/Shadow0/MarginV48.
3. **Ngắt dòng**: pyvideotrans `simple_wrap` (15 CJK / 40 other, ưu tiên dấu câu); OmniCast **không** ngắt theo luật độ dài.
4. **Thứ tự stage**: giống trục chính ASR→dịch→TTS→align/retime→mux; OmniCast thiếu diariz/recogn2pass/check_target_sub/wrap-trước-burn; có contextual translate + review + retime (đã có tpad).
5. **Guard trước “thành công”**: pyvideotrans kiểm file phụ đề/audio/novoice + size>0 + căn duration mux; OmniCast kiểm thiếu segment ASR, file sub, ffmpeg exit code — **không** kiểm duration output / có track audio / số dòng phụ đề.
