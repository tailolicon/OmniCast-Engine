# CHIẾN DỊCH V2 — BỐI CẢNH CHUNG (đọc trước brief nhóm)

Bạn là KIỂM TOÁN VIÊN KỸ THUẬT. Repo đích: `E:\Project\OmniCast Engine`.
Kho tham khảo: `_refs/` (CHỈ ĐỌC — cấm sửa). Code thật của dự án: `implementation/src/omnicast/`.

## Vì sao có chiến dịch này
Đợt 1 đã mổ 13 repo storyboard và OmniCast kế thừa được nhiều CƠ CHẾ. Nhưng chủ dự án
đánh giá: tầng TINH CHỈNH SÂU (từng prompt, từng config, từng magic number) của OmniCast
là đồ TỰ CHẾ, kém hơn đồ đã được các repo tinh luyện qua sản xuất thật. Đồng thời có thể
một số CƠ CHẾ OmniCast kế thừa nhưng làm YẾU HƠN bản gốc. Nhiệm vụ: moi bằng hết.

## HAI TẦNG PHẢI RÀ (cho MỌI repo trong brief nhóm)

### Tầng 1 — VERBATIM HARVEST (quan trọng nhất)
- MỌI prompt template / system prompt / few-shot / instruction gửi LLM hay model sinh
  ảnh/video/nhạc/giọng: chép NGUYÊN VĂN (kể cả tiếng Trung/Nhật — chép nguyên, thêm 1 dòng
  tóm tắt tiếng Việt), kèm `đường/dẫn/file:dòng`.
- MỌI config/default/constant có tác dụng tinh chỉnh: sampling (temperature/top_p/CFG/steps/
  seed policy), retry/backoff, timeout, ngưỡng chất lượng, kích thước/tỷ lệ/fps/bitrate,
  LUFS/audio, giới hạn độ dài, chunk size, khoảng nghỉ, giá/credit, model id... Ghi: key,
  giá trị mặc định, đơn vị, range nếu code có validate, và file:dòng.
- Chép cả COMMENT giải thích cạnh giá trị nếu có (đó là tri thức tinh luyện).
- CẤM tóm tắt thay cho trích. Tóm tắt chỉ đi KÈM trích.

### Tầng 2 — CƠ CHẾ (nghi ngờ chủ động)
- Mô tả pipeline chính của repo (ngắn).
- Đối chiếu với code OmniCast tương ứng (danh sách file dưới): cơ chế nào repo có mà
  OmniCast (a) THIẾU, (b) CÓ NHƯNG YẾU HƠN (đơn giản hoá sai, bỏ bước, ngưỡng sai,
  thiếu retry/fallback...), (c) làm NGƯỢC khuyến cáo. Nêu bằng chứng file:dòng CẢ HAI PHÍA.

## File OmniCast để đối chiếu (đọc thật, đừng đoán)
- Script/LLM: `implementation/src/omnicast/agents/writer.py`, `critic.py`, `compliance.py`,
  `editorial_angle.py`, `evidence_research.py`, `narrative_pipeline.py`, `visual_director.py`,
  `rubrics/*.py`, `llm/` (router/cost).
- Media: `media/prompt_builder.py`, `media/tts.py`, `media/voice_router.py`, `media/music.py`,
  `media/subtitle.py`, `media/render_engine.py`, `media/ffmpeg.py`, `media/thumbnail.py`,
  `media/veo_pipeline.py`, `media/providers/*.py` (nhất là `flow_browser.py`, `video_gemini.py`).
- Storyboard/phim: `storyboard/clips.py`, `frames.py`, `refsheet.py`, `style_lock.py`,
  `film_runner.py`, `slop.py`, `continuity.py`; `pipeline/edl.py`.
- Config: `config/settings.py`, `config/channel_styles.py`, `config/styles.py`,
  `config/default_channel.yaml`; render CLI `implementation/render_real_video.py`.

## CHUẨN OUTPUT (mỗi nhóm 1 file, ghi đúng đường dẫn brief nhóm chỉ định)
1. `## Bảng VERBATIM` — từng mục: [repo] [file:dòng] [loại: prompt|config] [trích nguyên văn
   trong code-fence] [tóm tắt 1 câu] [OmniCast hiện có gì ở đâu / "TỰ CHẾ – không đối chứng"]
   [khuyến nghị: THAY/GHÉP/BỎ QUA + lý do 1 câu].
2. `## Cơ chế OmniCast thiếu hoặc yếu hơn` — bảng: cơ chế | repo nguồn (file:dòng) |
   hiện trạng OmniCast (file:dòng) | mức (CAO/TRUNG/THẤP) | việc phải làm.
3. `## TOP-15 PATCH` — xếp hạng việc đáng làm ngay, mỗi việc 2 dòng: sửa gì, ở file nào.
CHỈ ghi file output của nhóm. Cấm sửa code, cấm sửa `_refs/`, cấm tạo file khác.
Làm việc TIẾT KIỆM: đọc có mục tiêu (tìm thư mục prompt/, config/, *.yaml, constants,
settings, i18n templates) thay vì đọc tràn lan; nhưng KHÔNG bỏ sót file prompt/config nào.
