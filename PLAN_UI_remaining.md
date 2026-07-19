# PLAN — UI v2 backlog còn lại

> STATUS: ACTIVE (2026-07-05). Nguồn: `NGHIEM_THU_UI_v2.md`.
> **ĐÃ ĐÓNG hết** (xem §Phần 4+5 doc đó): S1,S2,S3,S5,Đ6, BS-1,BS-2,BS-3,BS-4, I3, V6(bulk-approve), + 1 vi phạm O8 phát hiện thêm (fake metrics ở Approvals).
> **CHỈ CÒN 1 epic lớn dưới đây** — không làm vội, cần spec riêng.

---

## I1 — Multi-track timeline kiểu Premiere (epic thật, nhiều tuần)

**Vì sao chưa làm:** cần track Video/Audio/Sub kéo-thả theo thời gian + sửa từng câu phụ đề per-line + đồng bộ lại audio/caption sau khi sửa. Đây không phải 1 PR nhỏ — làm ẩu sẽ vi phạm chính quy tắc chất lượng/no-fake-data đã áp dụng cho các phần khác.

**Trạng thái nền đã có (không phải làm lại):** Studio hiện có "Timeline phân cảnh" (scene strip, 1 track duy nhất, click chọn cảnh) + panel "Cảnh đang chọn" (nghe audio, xem heading). Đây là *nền* để mở rộng, không phải zero.

**Spec gốc để đọc trước khi làm:** `UI_VideoToolsPro_FULL.md` §2.2b (nếu còn tồn tại trong repo — kiểm tra trước, có thể đã archive).

**Việc cần khi triển khai (không làm ở đây):**
1. Xác nhận backend có endpoint sửa **1 câu phụ đề/1 scene** riêng lẻ (không phải toàn bộ script) — nếu chưa có, đây là việc backend trước.
2. Component `<MultiTrackTimeline>`: track Video (thumbnail scene) + track Audio (waveform hoặc block) + track Sub (text per-scene), cùng trục thời gian, kéo-resize duration.
3. Click 1 scene → sửa text phụ đề inline → gọi endpoint mới ở bước 1.
4. V6 nâng cao (bulk style-preset) đi kèm epic này — không làm riêng.

**Luật khi làm:** không thêm npm lib timeline/drag-drop chưa vendor (luật §0 cũ: không CDN, thư viện mới phải vendor). Ưu tiên tự viết bằng CSS grid/flex + pointer events thay vì kéo cả 1 thư viện lớn.
