> STATUS: ACTIVE (2026-07-04) — spec redesign UI v3; thay định hướng layout của SPEC_UI_v2 (giữ SPEC_UI_v2 cho data-contract + build/serve).

# SPEC UI v3 — REDESIGN: Tách tab hợp lý + thẩm mỹ cockpit

> Lý do: qua 3 vòng QA, UI v2 chạy được nhưng (1) nhồi mọi thứ vào Studio → nút hành động bị chôn, (2) thẩm mỹ chưa đạt. Người vận hành yêu cầu học CÁCH BỐ TRÍ của VideoToolsPro / Cap Assistant / Linear (system-design) chứ không chỉ chức năng.
> Nền tảng thẩm mỹ: **`frontend_v2/DESIGN.md`** (dark cockpit Linear-grade — ĐỌC TRƯỚC). Data-contract + endpoint + build/serve: giữ nguyên `SPEC_UI_v2.md` §6/§8.
> Defect phải fix song song: `NGHIEM_THU_UI_v2.md` PHẦN 2 (Đ1–Đ18).

## 1. NGUYÊN TẮC BỐ TRÍ (rút từ refs)
- **VideoToolsPro:** 2 tab lớn tách bạch (Downloader vs Exporter); trong Exporter dùng **timeline 4-track** + **panel cấu hình collapsible** + **settings ở khu riêng** — KHÔNG nhồi. Bài học: tách theo NHIỆM VỤ, cấu hình sâu để riêng.
- **Linear/Raycast (DESIGN.md):** near-black, hairline, 1 accent, mật độ cao, số liệu mono. Bài học: đẹp = kỷ luật màu + typography, không phải thêm hiệu ứng.
- **Cap Assistant / Pixelle:** workflow tuyến tính rõ (nhập → cấu hình → chạy → xem kết quả) hiển thị 3 vùng. Bài học: 1 màn = 1 nhiệm vụ, kết quả luôn nhìn thấy.

## 2. INFORMATION ARCHITECTURE MỚI — sidebar nhóm (thay 7 mục phẳng)

```
━━ SẢN XUẤT ━━
  ▸ Bảng điều khiển        (Dashboard: KPI + StepFlow + số liệu thật)
  ▸ Xưởng                  (Studio GỌN: chỉ pipeline+preview+timeline; cấu hình → Drawer)
  ▸ Thư viện               (products: grid + drawer xem video/script/audit THẬT)
━━ KÊNH ━━
  ▸ Kênh & Niche           (bảng kênh + chỉ số per-kênh + drawer form-first; Niche sub-tab)
  ▸ Lịch & Tự động         (scheduler + auto-pilot — tách khỏi Hệ thống)
━━ PHÂN PHỐI ━━
  ▸ Duyệt & Đăng           (approval queue — video pass TỰ vào đây)
  ▸ Nền tảng & Đích        (platforms + destinations — MỚI, Đ mục 5 câu hỏi)
  ▸ Phân tích              (analytics per-video: /api/platforms/metrics — MỚI)
━━ KIẾM TIỀN ━━
  ▸ Doanh thu & Affiliate  (readiness + offers + revenue)
━━ HỆ THỐNG ━━
  ▸ Providers · Chính sách · Jobs · Hạ tầng · Chi phí  (5 sub-tab như hiện tại, giữ)
━━ ─────── ━━
  ▸ Văn phòng              (route riêng, fullscreen office — KHÔNG nhét thumbnail vào Xưởng)
```
Sidebar: nhóm có eyebrow uppercase; badge số (chờ duyệt, lỗi) trên mục tương ứng; icon-only < 1000px.

## 3. WIREFRAME TỪNG MÀN (khác v2)

### 3.1 XƯỞNG (Studio) — fix nhồi nhét (Đ2, Đ3)
```
┌ StepFlow: ① Ý tưởng ✓ ── ② Kịch bản ✓ ── ③ Dựng ▶ ── ④ Duyệt ○ ──────────────[⚙ Cấu hình]┐
├─────────────┬────────────────────────────────────────┬──────────────────────┤
│ RAIL TRÁI    │ GIỮA — Preview + Timeline               │ RAIL PHẢI            │
│ (200px)      │ ▶ video player (16:9, lớn)             │ Live log (mono,      │
│ • Chọn kênh  │ stats: thời lượng mm:ss·MB·QA badge     │  auto-scroll)        │
│ • [Sinh KB]  │ ─ Timeline 4-track ─                    │ ─────────            │
│ • [Dựng]     │ Sub | Voice(▶ nghe) | Tách giọng | SFX  │ Lịch sử render       │
│ • [Full Run] │ click chip → sửa inline; ▶ nghe scene   │ (có ngày giờ)        │
│ • ☐ Dừng sau │                                          │                      │
│   sinh script│                                          │                      │
│ • job status │                                          │                      │
└─────────────┴────────────────────────────────────────┴──────────────────────┘
```
- **5 panel cấu hình (Discovery/TTS/Image/BGM/Format) → Drawer "⚙ Cấu hình sản xuất"** mở từ nút góc phải StepFlow. KHÔNG inline. Drawer chia section collapsible như VideoToolsPro.
- **4 nút hành động lớn, chỉ [Full Run] là primary accent;** còn lại secondary. Không chôn dưới scroll.
- Office KHÔNG ở đây (Đ3) → chuyển thành mục sidebar "Văn phòng".

### 3.2 BẢNG ĐIỀU KHIỂN — thêm StepFlow + fix số
- Hàng KPI 4 cột (mono) → **StepFlow job đang chạy** (dải chip, click job → Xưởng) → 2 cột: [số liệu kênh thật /api/channels/overview] | [Hoạt động gần đây + Lỗi]. Đ8/Đ9 format số.

### 3.3 THƯ VIỆN — fix xem được (Đ4, Đ5, Đ7)
- Grid card: thumbnail THẬT (getMediaUrl→/media, lỗi→placeholder icon), badge QA + điểm + trạng thái. Title dưới ảnh, không overlay.
- Click → **Drawer**: video player chạy được (báo lỗi rõ nếu 404); **script viewer render nội dung thật** (hook/segment heading) không chỉ tên file; meta (ngày, độ phân giải) từ sidecar; nút Render / Gửi duyệt.

### 3.4 DUYỆT & ĐĂNG — fix auto-queue (Đ6)
- Render xong + audit PASS → **tự** tạo approval (destination approval_required). Màn này là hàng chờ thật, không trống vô lý.
- Card ngang: thumbnail + title + badge platform + risk badge (public=cao/unlisted=vừa/dry-run=thấp) + thời gian chờ. Duyệt→modal privacy(unlisted mặc định)+force. Lỗi publish đỏ trên card. + Bảng "Đã đăng gần đây" (Đ13).

### 3.5 KÊNH & NICHE — fix form-first (Đ10, Đ16)
- Bảng: cột Views/Subs/Videos/Doanh thu per-kênh (mono) + Giọng đọc (hiện nguyên chuỗi, Đ10) + trạng thái có tooltip (Đ11).
- Drawer sửa kênh: **form fields trước** (tên, niche, giọng qua VoicePicker nghe thử, style phụ đề, lịch) → JSON "Nâng cao" gập cuối. Không JSON-first.

### 3.6 NỀN TẢNG & ĐÍCH (mới) · PHÂN TÍCH (mới) · LỊCH & TỰ ĐỘNG (tách ra)
- Nền tảng & Đích: bảng /api/platforms (format 16:9/9:16, adapter chính thức/dry-run) + /api/destinations per kênh.
- Phân tích: /api/platforms/metrics — per-video views/likes/revenue theo platform; map video ↔ script sinh ra nó.
- Lịch & Tự động: scheduler toggle 24/7 + auto-pilot status/run (chuyển từ Hệ thống ra, giảm tải Hệ thống).

## 4. PHASES BUILD (mỗi phase 1 PR, build+screenshot đối chiếu DESIGN.md, verify trong app)
| P | Việc | Nghiệm thu |
|---|---|---|
| V3-1 | Áp DESIGN.md: đổi tokens sang dark cockpit, component library refactor (Button 1-primary, StepFlow, KPI mono, Table density, Drawer) | Dark mode mặc định; screenshot cạnh Linear/Raycast không lạc tông |
| V3-2 | Sidebar nhóm mới (IA §2) + routing | 6 nhóm, badge, icon-only responsive; F5 giữ tab |
| V3-3 | Xưởng tái cấu trúc (3.1): config→Drawer, 4 nút gọn, office ra ngoài | Nút Render không bị chôn; drawer cấu hình mở/đóng; office là mục riêng |
| V3-4 | Duyệt auto-queue (3.4, Đ6) + risk badge | Video PASS tự xuất hiện ở Duyệt; risk badge đúng |
| V3-5 | Thư viện xem được (3.3, Đ4/5/7) | Video phát / script hiện nội dung / thumb thật |
| V3-6 | Kênh form-first + chỉ số (3.5) + Nền tảng&Đích + Phân tích + Lịch&Tự động (3.6) | Đủ 3 màn mới, form không JSON-first |
| V3-7 | Polish: Đ8-Đ18 còn lại, empty-state mọi nơi, error-translator, dark/light toggle, chốt v2→v3 | Toàn bộ QA §2 xanh; đối chiếu DESIGN.md §7 "Cấm" = 0 vi phạm |

## 5. QUY TẮC AN TOÀN BUILD (bắt buộc — đã có 3 sự cố)
- Ghi file lớn: dùng cách ghi + **đọc lại verify byte** ngay (sandbox mount từng trả bản cũ/cụt). `npm run build` (tsc+vite) phải xanh phía Windows trước khi bàn giao.
- KHÔNG bịa endpoint (danh mục ở SPEC_UI_v2 §6). Thiếu → ghi BLOCKED, backend bổ sung trước.
- Mỗi phase: mở app thật, screenshot màn đổi, so DESIGN.md. Cập nhật IMPLEMENTATION_STATUS §2 + đóng defect trong NGHIEM_THU §2.


## 6. TRẠNG THÁI BUILD (2026-07-04)
- ✅ **V3-1 phần nền ĐÃ LÀM + deploy + build xanh:** `frontend_v2/DESIGN.md` (dark cockpit Linear-grade) + `src/index.css` đổi token sang **dark-first** (accent indigo #6366f1, hairline, focus-ring, scrollbar tùy biến, `.light` override) + `App.tsx` mặc định theme `dark` + logic class `light`. `tsc -b` sạch, bundle `index-Do7pFYt3.js`/`index-fQKIXUrv.css` đã vào `webui_v2/`.
- ⏳ **Chưa chụp được ảnh xác minh live:** một tiến trình OmniCast cũ bị **zombie giữ `output/_desktop.lock`** → mọi lần mở app mới tự thoát ("another instance already running"), backend 8767 không lên lại. **Không xóa được lock từ sandbox** (Permission denied). → cần đóng tiến trình cũ bằng Task Manager (hoặc reboot) rồi mở lại; app sẽ hiện dark cockpit mới.
- **BUG-4 (mới, ghi cho agent Windows):** single-instance lock không tự giải phóng khi WebView crash/đóng bất thường → lock file trơ, app không mở lại được cho tới khi kill thủ công. Fix: khi acquire lock thất bại, kiểm tra port 8767 có sống không (`GET /api/status`); nếu chết → coi lock là stale, ghi đè + tiếp tục (kèm PID check).
- ⏳ **V3-2 → V3-7 (IA restructure, Studio decram, per-page redesign):** LỚN, nhiều file .tsx. Vì sandbox mount từng trả bản cũ/cụt khi ghi file lớn (đã có 3 sự cố + BUG-4), **khuyến nghị agent chạy trực tiếp phía Windows** build theo §3–§4, mỗi phase build+screenshot đối chiếu `frontend_v2/DESIGN.md`.
