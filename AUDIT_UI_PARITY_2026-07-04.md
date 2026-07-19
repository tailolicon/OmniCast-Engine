# AUDIT PARITY UI v2 — 6 câu hỏi vận hành (2026-07-04)

> STATUS: ACTIVE (work-order UI-A..D2 — archive khi các mục xong)

> Đối chiếu bằng **bundle đang chạy** (`webui_v2/assets/index-CRzurVPo.js`) — nguồn sự thật runtime, đáng tin hơn source đọc qua mount (mount có lúc trả bản cũ — xem cảnh báo trong SPEC_UI_v2 §11.2).
> Agent thực thi: làm theo thứ tự UI-B → UI-D1 → UI-A → UI-C → UI-D2, xong rồi mới quay lại Epic I/I1 (V1 timeline + V2 sub style + V12 nghe thử per-scene — xem `UI_VideoToolsPro_FULL.md` §3).

| Câu hỏi vận hành | Trạng thái | Việc cần làm |
|---|---|---|
| 1. Pipeline đang ở công đoạn nào / xong gì | 🟠 Dashboard có progress % + phase + topic per job; Studio có Live Logs + per-scene status + WAITING_EDIT | **UI-A**: dải step-checklist "① Discovery → ② Script → ③ Render → ④ Duyệt" (✓ xong / ▶ đang / ○ chờ / ✗ lỗi) trên đầu Studio + card Dashboard. Dữ liệu: `/api/pipeline` (active_jobs: phase, progress_pct, current_topic) + `/jobengine/api/v1/jobs/{id}` steps. KHÔNG cần graph editor — 4 chip là đủ (C8-lite) |
| 2. Giao diện Office | 🟠 iframe Studio + route fullscreen `/studio/office` ĐÃ code; đang 404 vì server mất mount | **UI-B** (1 dòng, làm NGAY): trong khối webui cuối `server.py`, trước mount `"/"`: `app.mount("/office_app", StaticFiles(directory=str(_WEBUI_V1_DIR / "office_app"), html=True), name="office_app")` khi đang serve v2 |
| 3. Chức năng UI cũ (v1) | 🟢 ~90% parity: dashboard, Studio (create+produce), Thư viện (scripts+products), Kênh + Niche Scanner/Vault (2 sub-tab), Duyệt & Đăng, Kiếm tiền, Hệ thống 6 sub-tab (Providers/Tự động & Lịch/Chính sách/Jobs/Hạ tầng/Chi phí) | — (P7 checklist từng nút vẫn phải chạy trước khi archive v1) |
| 4. Kho voice nghe thử | ✅ CÓ: `VoicePicker` trong `components/ui` gọi `/api/voices` + `/api/voice/preview` (bundle xác nhận) | — |
| 5. Kho thông tin các nền tảng | ❌ CHƯA CÓ VIEW (bundle 0 ref `/api/platforms`, `/api/destinations` — backend + bảng vault có sẵn) | **UI-C**: section "Nền tảng & Đích đăng" đặt trong tab Kiếm tiền: bảng Platforms (id, format 16:9/9:16, trạng thái adapter chính thức/dry-run) + bảng Destinations per kênh (platform, format_variant, approval_required, enabled). Read-only trước, sửa sau |
| 6. Theo dõi chỉ số các kênh | 🟠 Dashboard có TỔNG views/video/subs/doanh thu thật; Kênh chỉ có nút "Cập nhật số liệu" | **UI-D1**: bảng Kênh thêm cột Views / Subs / Video / Doanh thu per-kênh từ `/api/channels/overview.channels[]` (đã có total_views, subscribers, video_count, est_revenue_usd, linked). **UI-D2** (= E7): màn Analytics trong Kiếm tiền đọc `/api/platforms/metrics` — bảng per-video theo platform |

Luật cũ vẫn áp: không bịa endpoint, không hardcode số giả, verify tail file sau khi ghi, build phía Windows.

## BỔ SUNG 2026-07-08 — Niche scan (chạy live từ UI)
- **N1 (UI, vừa):** tab "Ý tưởng & Ngách" — 9 card đều hiện placeholder "Ngách tiềm năng cao về..." + badge "pts" trống. UI không map đúng schema `niche_results.json` (`niche_name`, `total_score`, `estimated_rpm`, `category`, `why_opportunity`). Fix: đổi field map + hiện breakdown D/G/R/S.
- **N2 (backend, vừa):** patch momentum cross-scan nằm ở `niche_flow.py` (CLI path) nhưng scan từ UI đi qua server path (`/api/discover-niches` → NicheDiscovererAgent) nên KHÔNG có momentum. Fix: tách momentum-annotate thành helper chung, gọi ở chỗ server ghi `niche_results.json`.
- **N3 (UI, nhẹ):** niche `_duplicate_of` (6/9 lần này) nên dim/gắn badge "Đã có trong vault" thay vì hiển thị ngang hàng — 2 niche điểm cao nhất (96) đều là dup.

