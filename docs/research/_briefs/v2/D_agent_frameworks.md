Đọc trước: `docs/research/_briefs/v2/COMMON_V2.md` và tuân đủ 2 tầng + chuẩn output.

# Nhóm D — AGENT FRAMEWORKS:
`_refs/ChatDev` + `_refs/ChatDev1` + `_refs/agent-office` + `_refs/pixel-agents`

Mục tiêu: moi KỸ THUẬT PROMPT đa-agent đã tinh luyện để nâng writer/critic/compliance/
thinking của OmniCast (`agents/*.py` — debate, role prompts phần lớn tự chế).

Tầng 1 VERBATIM — săn:
- ChatDev (cả 2 bản, so diff nếu là 2 version): toàn bộ RoleConfig/PhaseConfig prompts
  (CEO/CTO/Programmer/Reviewer/Tester...), format trao đổi 2-agent (chat chain), điều kiện
  kết thúc vòng, chống lặp/chống nịnh (self-reflection, "modality"), mọi config vòng lặp
  (số turn tối đa mỗi phase, temperature từng role).
- agent-office & pixel-agents: cấu trúc phân vai, memory/blackboard giữa agent, prompt
  giao việc & tổng hợp, cơ chế phát hiện agent bịa/đi lạc.

Tầng 2 CƠ CHẾ:
- Chat-chain 2-agent có kết thúc bằng "<INFO>"-style marker của ChatDev so với vòng
  writer↔critic OmniCast (`agents/writer.py`, `critic.py`, `narrative_pipeline.py`):
  điều kiện dừng, chống critic mềm, chống writer phớt lờ note — cái nào đáng port.
- Cách họ nén lịch sử hội thoại giữa phase (summary handoff) so `thinking.py`/pipeline.

Output: `docs/research/V2_D_AgentFrameworks.md`.
