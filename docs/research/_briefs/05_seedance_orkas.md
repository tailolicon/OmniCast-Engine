Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` — tuân thủ toàn bộ.

# Brief 05 — seedance-2.0 Skill OS + Orkas-VideoStudio (prompt-craft & plan/QA)

- `_refs\seedance-2.0` (~30 file) — "Skill OS: Direct the model. Don't micro-manage the frame.
  An agent that reads the scene before it writes the prompt" — ĐÂY LÀ REPO VỀ CÁCH VIẾT PROMPT
  video-gen. User yêu cầu học "cả những thứ nhỏ như prompt viết thế nào" → repo này là lõi.
- `_refs\Orkas-VideoStudio` (~72 file) — video = `plan.json` readable/diffable/re-renderable.
  OmniCast đã port qa_check/consistency_check/repair_budget từ đây rồi — tìm phần CHƯA port.

Câu hỏi riêng (ngoài 10 mục chuẩn):
- seedance-2.0: chép VERBATIM TOÀN BỘ skill instructions/heuristics — cách tả chủ thể,
  hành động, camera move, ánh sáng, audio native, "IP-safe rewrites", những từ CẤM dùng,
  cấu trúc câu prompt (thứ tự mệnh đề), khác nhau t2v vs i2v vs reference-to-video.
  Đánh giá: rule nào áp thẳng được cho Veo/Flow prompt của OmniCast, rule nào là đặc thù Seedance.
- seedance-2.0: "reads the scene before it writes the prompt" — pipeline phân tích scene
  trước khi viết prompt là gì, code đâu.
- Orkas: schema plan.json ĐẦY ĐỦ (mọi node type, transition, audio track); phần compose/edit
  (không chỉ QA) — OmniCast chưa có gì tương đương "video as diffable plan"; đề xuất
  áp dụng cho EDL re-render (WS4) + storyboard→render contract (WS1).
- Orkas: MCP/CLI surface cho coding agent — cách họ thiết kế lệnh cho agent gọi.

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_05_Seedance_Orkas.md`
