Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` — tuân thủ toàn bộ.

# Brief 03 — waoowaoo (`_refs\waoowaoo`, ~1256 file code)

"AI 影视创作流" (AI film/TV creation flow) — repo trending, lớn nhất nhóm cùng ArcReel.

Câu hỏi riêng (ngoài 10 mục chuẩn):
- "Creation flow" của họ gồm những stage nào (剧本/分镜/资产/生成/剪辑?), stage nào tự động stage nào cần người duyệt — vẽ state machine.
- Asset system: nhân vật/bối cảnh/đạo cụ được định nghĩa, version hoá, tái sử dụng giữa các cảnh/tập thế nào.
- Cách họ dựng prompt cho từng shot từ (scene text + asset refs + style): thứ tự ghép, template VERBATIM, negative prompt, camera language.
- Video-gen provider nào (Seedance/Kling/Veo/…), i2v hay reference-to-video, first/last frame, và cách nối clip (transition).
- Điều phối job: queue, concurrency, cost guard, retry — cái gì đáng bê về batch runner của OmniCast.

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_03_waoowaoo.md`
