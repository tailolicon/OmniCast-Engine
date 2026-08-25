Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` — tuân thủ toàn bộ.

# Brief 04 — AIComicBuilder + StoryGen-Atelier (stack khớp OmniCast nhất)

- `_refs\AIComicBuilder` (~187 file) — 漫剧 generator kịch bản→video, v0.2.2 có
  "Seedance 2.0 接入 + 参考图模式重构" (reference-image mode REFACTOR — trọng tâm số 1).
- `_refs\StoryGen-Atelier` (~16 file) — storyboard bằng Gemini (text+frame) + Veo
  transition clips + ffmpeg stitch — ĐÚNG stack Gemini/Veo của OmniCast.

Câu hỏi riêng (ngoài 10 mục chuẩn):
- AIComicBuilder: thiết kế "tham chiếu ảnh mode" sau refactor — bao nhiêu ảnh ref/shot,
  chọn ảnh nào theo logic gì, prompt đi kèm ảnh viết thế nào (VERBATIM), vì sao họ phải refactor
  (đọc changelog/commit/issue nếu có). So thẳng với `storyboard/binding.py` (token `[IMAGE n]` + RefRole) của OmniCast: ai chặt chẽ hơn, thiếu gì.
- AIComicBuilder: tích hợp Seedance 2.0 — request schema, reference-to-video, audio.
- StoryGen-Atelier: prompt Gemini sinh storyboard text VERBATIM; prompt sinh frame VERBATIM;
  cách họ ra lệnh Veo làm "transition giữa 2 frame" (first/last frame?) — OmniCast đang cần
  chính pattern này cho `veo_pipeline.py`.
- Cả hai: style preset quản lý thế nào (StoryGen có "custom styles").

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_04_AIComicBuilder_StoryGen.md`
