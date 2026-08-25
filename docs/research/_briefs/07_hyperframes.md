Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` — tuân thủ toàn bộ.

# Brief 07 — hyperframes (`_refs\hyperframes`, ~1090 file TS)

Framework TypeScript cho video, có `DESIGN.md`, `AGENTS.md`, `CLAUDE.md` — thiết kế
agent-first. OmniCast quan tâm ở góc: **contract giữa storyboard và renderer** nên
trông như thế nào khi cả hai bên đều do agent điều khiển.

Câu hỏi riêng (ngoài 10 mục chuẩn — mục nào không áp dụng cho framework thì ghi N/A):
- Đọc kỹ `DESIGN.md` + `AGENTS.md`: triết lý thiết kế API cho agent (khai báo cái gì,
  imperative cái gì), quy ước để LLM viết đúng — rút ra checklist.
- Frame/scene/timeline abstraction: schema, composition model, cách diff/re-render
  từng phần (liên quan EDL re-render WS4 + nối storyboard WS1).
- Text overlay/caption/motion primitives — OmniCast render HTML overlay + Remotion
  template; hyperframes có primitive nào đáng thay/bổ sung.
- Ecosystem: họ test video output thế nào (visual regression?), CI cho video.
- License + mức độ tái dùng: dùng làm dependency được không, hay chỉ học pattern.

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_07_hyperframes.md`
