# BỐI CẢNH CHUNG — Nghiên cứu repo storyboard/AI-video trong _refs (đọc TRƯỚC khi làm brief)

Bạn là research agent cho dự án **OmniCast Engine** (`E:\Project\OmniCast Engine`) —
hệ thống tự sản xuất video YouTube: script (Writer/Critic) → storyboard → media
(TTS/image/video) → render (FFmpeg) → upload. Code thật: `implementation/src/omnicast/`.

## Hiện trạng storyboard của OmniCast (để bạn map phát hiện vào gap)

Đã có `implementation/src/omnicast/storyboard/` (~5000 dòng, Pydantic, fail-closed):
- **Cast registry theo video**: `Entity` tách `character/location/prop/costume`,
  mỗi entity có reference sheet riêng (`refsheet.py`), tên giữ VERBATIM.
- **Token binding** `[IMAGE n]` trong prompt + `RefRole` (ảnh ref chỉ được điều khiển
  identity/environment/… + mệnh đề "controls X only; ignore Y") — `binding.py`.
- **Cổng liên tục** fail-closed (`continuity.py`), rào duyệt cast người, API + trang `/storyboard`.
- Gemini image provider nhận **ordered reference images**. Veo qua `media/veo_pipeline.py`
  (Flow browser-automation → fallback Gemini API; Flow convert() CHƯA nhận image).
- **GAP còn lại (WS1)**: chưa nối storyboard vào `render_real_video.py`/`veo_pipeline`;
  chưa đo drift định lượng ở tầng pixel (mới gate ở tầng bố trí); Flow "Ingredients"
  (≤14 ảnh ref) chưa implement; nhân vật từng đổi mặt theo frame (user report).

## Nhiệm vụ

ĐỌC CODE THẬT của (các) repo được giao trong `_refs\` — KHÔNG đoán từ README.
Repo lớn thì grep/tìm có chủ đích: file chứa prompt template, schema/model, pipeline
orchestration, consistency, QA/retry. Nhiều repo comment tiếng Trung — vẫn phải đọc,
dịch ý chính. Được phép spawn subagent của bạn để chia việc đọc.

## Cấu trúc report BẮT BUỘC (mỗi mục đều cite `file:line`)

1. **Tổng quan kiến trúc** — module map + luồng dữ liệu end-to-end (script vào → video ra).
2. **Data model storyboard** — schema/class verbatim (scene/shot/character/asset), quan hệ, state machine.
3. **Cơ chế consistency** nhân vật/bối cảnh/props — reference image dùng thế nào (bao nhiêu ảnh,
   vai trò gì, thứ tự ra sao), seed, character sheet, IP-adapter/LoRA, re-roll, verify.
4. **PROMPT ENGINEERING — VERBATIM, quan trọng nhất**: chép NGUYÊN VĂN mọi prompt template
   (system/user/negative/style suffix/camera language/JSON-schema instruction), giữ nguyên
   ngôn ngữ gốc, kèm `file:line` + 1-2 câu giải thích vì sao prompt viết như vậy hiệu quả.
   Đừng tóm tắt prompt — CHÉP ĐỦ.
5. **Vòng QA/retry/repair** — detect lỗi gì, sửa thế nào, budget bao nhiêu, khi nào bỏ cuộc.
6. **Tích hợp video-gen** — i2v/t2v, first/last-frame, reference-to-video, transition, audio,
   provider fallback, polling/queue.
7. **Pacing/timing** — thời lượng shot quyết định thế nào, khớp voice-over ra sao, beat logic.
8. **Chi tiết nhỏ đáng học** — naming, cache key, error handling, kỹ thuật ffmpeg, UX flow.
9. **ĐỀ XUẤT CHO OMNICAST** — bảng: phát hiện → gap OmniCast tương ứng → file đích
   (vd `storyboard/binding.py`, `media/veo_pipeline.py`) → impact (video quality) → effort (S/M/L).
10. **KHÔNG nên học + LICENSE** — anti-pattern trong repo, và license (MIT/Apache OK;
    AGPL/không-license = chỉ học concept, CẤM chép code — ghi rõ).

## Quy tắc đầu ra

- Report viết **tiếng Việt**, prompt/code verbatim giữ nguyên ngôn ngữ gốc.
- Ghi file vào ĐÚNG đường dẫn output ghi trong brief (`docs/research/…`). KHÔNG sửa/ghi
  bất kỳ file nào khác trong repo OmniCast. KHÔNG sửa gì trong `_refs\`.
- Dài thoải mái (300–700 dòng) — đây là tài liệu để build lại, thà thừa còn hơn thiếu.
- Cuối report: mục "Đã đọc" liệt kê các file đã mở (để round sau biết còn sót gì).
