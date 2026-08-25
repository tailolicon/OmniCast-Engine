Đọc trước: `docs/research/_briefs/v2/COMMON_V2.md` và tuân đủ 2 tầng + chuẩn output.

# Nhóm B2 — TOOLING & FLOW & REMOTION:
`_refs/VideoToolsPro` + `_refs/KiraAP` + `_refs/h2dev_flow` + `_refs/tobyflow` + `_refs/remotion`

Tầng 1 VERBATIM — săn:
- VideoToolsPro & KiraAP: mọi preset xử lý video (ffmpeg filter chains nguyên văn, encode
  profiles, batch rules), template metadata, mọi prompt nếu có LLM.
- h2dev_flow & tobyflow: TOÀN BỘ endpoint/payload họ dùng để điều khiển Google Flow
  (đặc biệt tobyflow: internal API, headers, tên trường model/aspect/duration, cách đính
  ảnh Bắt đầu/Kết thúc, cách poll kết quả). Đây là VÀNG cho `media/providers/flow_browser.py`
  (đang phải lái UI, rất giòn) — chép nguyên văn request/response schema + file:dòng.
- remotion: cấu hình render (fps, codec, crf, concurrency, audio), pattern composition/
  sequence/transition/spring configs trong examples & templates — các con số animation
  (damping/stiffness/duration) dùng thật.

Tầng 2 CƠ CHẾ:
- tobyflow/h2dev_flow: kiến trúc gọi Flow KHÔNG-UI (auth thế nào, refresh ra sao, chống
  đứt phiên) so với flow_browser hiện tại — lộ trình nâng cấp cụ thể từng bước.
- remotion: mô hình timeline/composition so `animation/` + Remotion templates OmniCast đã
  nhúng (`IntroCard/StatPop/OutroCTA`) — thiếu pattern nào đáng port (transition series,
  audio viz, subtitle comp).

Output: `docs/research/V2_B2_ToolsFlow.md`.
