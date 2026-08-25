Đọc trước: `docs/research/_briefs/COMMON_CONTEXT.md`. Vai trò: KIỂM TOÁN VIÊN ÁP DỤNG.

# Gap Audit 2 — Reports 02 (Jellyfish/LocalMiniDrama) + 03 (waoowaoo) vs THỰC TẾ

Trọng tâm đặc biệt (đúng chỗ demo Miko vừa fail): pipeline LÀM PHIM LIỀN MẠCH của 2 repo drama —
- waoowaoo multi-phase (plan → cinematographer → acting → detail), photography_rules/actingNotes
  per panel, "上一镜头动作在下一镜头承接", slot/available_slots bối cảnh, first/last giữa panel,
  candidate 1-4 + undo, mọi rule trong phụ lục ROUND 2 (62 file prompt full).
- Jellyfish/LMD: ShotDetail đầy đủ field, identity anchors 6 lớp, industrial character sheet,
  layout_description, continuity_snapshot, getStoryboardSystemPrompt full (pacing 5-15s,
  dynamic camera ≥80%), universalSegmentPromptBundle, base-vs-rendered prompt, SRT/narration path.

Nhiệm vụ y hệt Gap Audit 1: từng khuyến nghị → đối chiếu code
(`implementation/src/omnicast/storyboard/*`, `media/*`) + quy trình demo
(`implementation/output/products/anim_demo/miko_lantern_ep1/DEMO_STATE.md`) → phân loại
ÁP DỤNG ĐÚNG / MỘT PHẦN / BỎ QUA / VI PHẠM + severity + bằng chứng file:line.

Output: `docs/research/GAP_2_drama.md` — bảng đầy đủ + TOP-10 việc sửa ngay.
Chỉ ghi file đó. Cấm sửa code, cấm sửa `_refs`.
