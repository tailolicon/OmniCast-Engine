Đọc trước: `docs/research/_briefs/v2/COMMON_V2.md` và tuân đủ 2 tầng + chuẩn output.

# Nhóm B1 — VIDEO ENGINES: `_refs/MoneyPrinterTurbo` + `_refs/Pixelle-Video`

MoneyPrinterTurbo là engine auto-video kinh điển (script→voice→clip stock→subtitle→render);
Pixelle-Video là engine thế hệ mới. OmniCast render qua `render_real_video.py` +
`media/render_engine.py` + `media/ffmpeg.py` — nhiều tham số tự chế.

Tầng 1 VERBATIM — săn:
- MPT: prompt sinh script + sinh từ khoá tìm clip (nguyên văn từng ngôn ngữ nếu có);
  config video (aspect, clip_duration min/max, concat mode, transition), subtitle
  (font/size/color/stroke/position/max chars per line), voice (danh sách + rate mặc định),
  bgm volume mặc định, mọi tham số ffmpeg dựng.
- Pixelle: toàn bộ workflow templates/nodes, prompt từng node, defaults (CFG/steps/model),
  cấu trúc job config; tham số ghép cảnh/caption/nhạc.

Tầng 2 CƠ CHẾ:
- Cách MPT chọn/cắt stock clip khớp nội dung từng câu (search term per sentence) — OmniCast
  có `download_best_web_image`/visual_match nhưng cho ẢNH; cơ chế clip-per-sentence có gì
  đáng ghép cho kênh compilation?
- Subtitle render pipeline (đặt dòng theo VO timing) so `media/subtitle.py`.
- Pixelle node-graph orchestration so `pipeline/` + `jobengine/` OmniCast — điểm nào giúp
  khai báo pipeline linh hoạt hơn YAML hiện tại.

Output: `docs/research/V2_B1_Engines.md`.
