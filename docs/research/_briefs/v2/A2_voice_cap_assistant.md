Đọc trước: `docs/research/_briefs/v2/COMMON_V2.md` và tuân đủ 2 tầng + chuẩn output.

# Nhóm A2 — VOICE SUITE & CAP ASSISTANT:
`_refs/voice-pro` + `_refs/Cap Assistant - REUP (CÓ CHỨC NĂNG DỊCH VÀ LỒNG TIẾNG)` +
`_refs/Cap Assistant Pro - CONTENT - Available for FREE USER`

voice-pro là suite TTS/clone đa engine; 2 bản Cap Assistant là tool sản xuất content thật
(REUP có dịch & lồng tiếng; Pro có luồng CONTENT). Chúng có thể là app đóng gói (JS/exe/
config) — nếu gặp mã build/minify thì moi phần đọc được: file cấu hình, template, resource,
strings nhúng, presets.

Tầng 1 VERBATIM — săn:
- voice-pro: mọi preset giọng (đặc biệt tiếng Việt/đa ngôn ngữ), tham số từng engine
  (speed/pitch/energy/emotion), chuẩn hoá văn bản trước TTS (số, ngày, viết tắt, ký hiệu),
  giới hạn chunk, cách nối đoạn, khử click/pop, loudness đích.
- Cap Assistant ×2: template tiêu đề/mô tả/hashtag/caption; prompt dịch & lồng tiếng;
  cấu hình reup (đổi tốc độ? crop? lật? watermark removal? — CHỈ GHI NHẬN để hiểu, gắn nhãn
  "RỦI RO CHÍNH SÁCH" cho mục nào vi phạm bản quyền/ToS, TUYỆT ĐỐI không khuyến nghị dùng
  mục vi phạm); cấu hình đăng đa nền tảng; mọi giới hạn free-user (rate, số job).
- Mọi danh sách "mẹo" trong resource/help/strings của app (thường chứa tri thức vận hành).

Tầng 2 CƠ CHẾ:
- Text-normalization pipeline trước TTS của voice-pro so với `media/tts.py` OmniCast
  (OmniCast gần như không chuẩn hoá — xác nhận và liệt kê bước thiếu).
- Luồng "content factory" của Cap Assistant Pro (từ nguồn → caption/dub → xuất) — bước nào
  OmniCast pipeline thiếu cho kênh reup-hợp-pháp/biên tập lại có biến đổi thực chất.

Output: `docs/research/V2_A2_VoiceCap.md`.
