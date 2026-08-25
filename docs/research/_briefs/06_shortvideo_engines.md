Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` — tuân thủ toàn bộ.

# Brief 06 — Pixelle-Video + MoneyPrinterTurbo + short-video-factory (engine short-video tự động)

- `_refs\Pixelle-Video` (~117 file) — "AI 全自动短视频引擎" (AIDC-AI), ComfyUI-based.
- `_refs\MoneyPrinterTurbo` (~44 file) — auto short video kinh điển (script→material→subtitle→BGM).
- `_refs\short-video-factory` (~35 file) — batch marketing/泛内容 videos.

Cả 3 cùng bài toán với OmniCast (1 lệnh → video hoàn chỉnh). Mổ cả ba, so sánh chéo.

Câu hỏi riêng (ngoài 10 mục chuẩn):
- Script→visual matching: mỗi repo quyết định "câu này hiện hình gì" thế nào (LLM tag?
  keyword search stock? gen ảnh?) — prompt/thuật toán VERBATIM.
- Pixelle-Video: workflow ComfyUI nào được dùng, tham số hoá ra sao, có template
  workflow đáng port sang provider model của OmniCast không.
- Subtitle/timing: cách khớp phụ đề với TTS (word-level? forced align?), so với
  subtitle_sync.py của OmniCast.
- Batch/orchestration + config per-channel: cái gì hay hơn channels/{id}.json của OmniCast.
- Prompt template mọi chỗ (title/hook/script nếu có, image prompt, negative) VERBATIM.

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_06_ShortVideoEngines.md`
