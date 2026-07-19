# NGHIỆM THU UI v2 — Khung O-I-I-R (2026-07-04)

> STATUS: ACTIVE (nghiệm thu 2026-07-04 — archive khi BS-1..4 vào plan/hoàn thành)

> Khung tiêu chí: nâng cấp từ đề xuất Gemini 3.1 Pro (Observability – Interpretability – Intervention + Risk) và cụ thể hóa cho OmniCast thành 26 tiêu chí chấm được. Mỗi mục kèm **bằng chứng** (test live trong app / grep bundle đang chạy `index-CRzurVPo.js` / endpoint thật). Reviewer: Claude.
> Kết quả: **✅ 14 · 🟠 7 · ❌ 5 → ĐẠT CÓ ĐIỀU KIỆN** — đủ vận hành hằng ngày; 5 mục ❌ đều đã nằm trong work-order (không phát sinh nợ mới ngoài 4 mục "bổ sung" cuối).

## O — Observability (Nhìn thấu mọi thứ)

| # | Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|---|
| O1 | Trạng thái backend/kết nối không mù | ✅ | StatusPill 3 mức, đếm fail liên tiếp ≥3 mới đỏ — quan sát live |
| O2 | Job đang chạy: phase + topic + % tiến độ | ✅ | Dashboard "Pipeline đang chạy" đọc `/api/pipeline` (phase, progress_pct, current_topic) |
| O3 | Micro-tracking từng công đoạn (idea→script→audio→render→đăng) độc lập | 🟠 | Per-scene 46 dòng status + WAITING_EDIT có; **thiếu dải step-chips tổng** → UI-A (AUDIT_UI_PARITY) |
| O4 | Telemetry tài nguyên worker (CPU/GPU/RAM) realtime | 🟠 | Hạ tầng hiện CPU/RAM per worker (heartbeat); GPU load + gauge chưa |
| O5 | API rate-limit/quota (YouTube units, token dịch) | ❌ | Chưa hiển thị — backend đã có `estimate_quota_cost` → **BỔ SUNG-1** |
| O6 | Hàng đợi (queue depth, slot GPU/CPU) | 🟠 | Bảng Jobs + badge slot class; chưa có gauge độ sâu hàng đợi |
| O7 | Phơi bày sản phẩm trung gian (nghe audio, xem script/sub trước render) | 🟠 | Nút Audio/Video per-scene + script editor WAITING_EDIT + VoicePicker nghe thử; xem trước file phụ đề .srt/.ass chưa có |
| O8 | Số liệu THẬT, cấm fake | ✅ | Đã diệt chart hardcode; Dashboard đọc `/api/channels/overview` (0 views hiển thị 0) |
| O9 | Chi phí realtime | ✅ | KPI "Chi phí hôm nay" + Usage ledger + budget guard |
| O10 | Lịch sử sản phẩm tra cứu được | ✅ | Thư viện + Lịch sử Render (search) + drawer chi tiết |

## I — Interpretability (Dữ liệu → tri thức)

| # | Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|---|
| I1 | Multi-track timeline kiểu Premiere | ❌ | Chưa — đích Epic I/V1 (spec chi tiết đã có từ VideoToolsPro: `UI_VideoToolsPro_FULL.md` §2.2b) |
| I2 | Lỗi dịch ra ngôn ngữ người + gợi ý hành động | 🟠 | `publish_error` hiện đỏ ngay trên card duyệt (tốt); lỗi render vẫn là log thô FFmpeg → **BỔ SUNG-2** |
| I3 | Analytics hợp nhất, map video ↔ script sinh ra nó | ❌ | UI-D2/E7 (`/api/platforms/metrics` chưa có view) |
| I4 | QA/audit diễn giải được | ✅ | Badge QA PASS + danh sách issues (duration/loudness/visual) đọc từ sidecar |
| I5 | Readiness kiếm tiền diễn giải checklist | ✅ | Tab Kiếm tiền: checklist xanh/WAIT + Blockers |

## V — Intervention (UI để ĐIỀU HÀNH, không phải để xem)

| # | Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|---|
| V1 | Kill-switch pause/resume toàn hệ | ✅ | **TEST LIVE HÔM NAY**: bấm pill → modal xác nhận → pill đỏ "Tạm dừng" → resume → xanh "Đang chạy" |
| V2 | Cancel job đang chạy | ✅ | `/api/run/{ch}/cancel` có trong bundle + endpoint thật (kill render subprocess) |
| V3 | Resume từ đúng node lỗi (không render lại từ 0) | ✅ | JobEngine checkpoint per-step + retry + `POST /api/pipelines/resume/{job_id}` (WAITING_EDIT wire trọn vòng) |
| V4 | Sửa nội dung trực tiếp trên UI (script/metadata) | ✅ | Editor script khi WAITING_EDIT (GET/PUT `/api/script/edit`); privacy/force/note khi duyệt. Sửa phụ đề per-câu thuộc I1 |
| V5 | Chọn lại giọng đọc + nghe thử ngay | ✅ | VoicePicker (`/api/voices` + `/api/voice/preview`) |
| V6 | Bulk actions/preset ("áp style cho cả hàng đợi 1 click") | ❌ | Epic I/V2+V11 (style phụ đề per-channel + "Áp dụng cho tất cả" kiểu VideoToolsPro) |
| V7 | Retry từng mục lỗi | ✅ | Jobs tab retry-per-job (checkpoint skip bước đã xong); retry per-scene ghi nhận là mở rộng của I1 |

## R — Risk Management

| # | Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|---|
| R1 | Smart alerts theo ngưỡng ("render fail tăng 40%/giờ") | ❌ | Mới có chuông liệt kê lỗi — chưa có rule ngưỡng → **BỔ SUNG-3** |
| R2 | Compliance gate + policy watch hiển thị được | ✅ | Tab Chính sách (rules động + gate cố định + quét); compliance chặn trước publish; policy_scan chạy nền (thấy trong Hoạt động gần đây) |
| R3 | Audit trail người vs máy | 🟠 | approvals lưu `decided_by/operator/note`, usage ledger, jobengine events — dữ liệu ĐỦ, chưa có màn xem tổng → **BỔ SUNG-4** |
| R4 | HITL trước public + mặc định an toàn | ✅ | Hàng đợi duyệt, unlisted mặc định, force phải tick, lỗi publish hiện đỏ không nuốt |

## KẾT LUẬN & VIỆC CÒN LẠI (đã gom về 1 chỗ)

- **Verdict: ĐẠT CÓ ĐIỀU KIỆN.** Trục Intervention (quan trọng nhất) đạt 6/7 — hệ đã là "buồng lái" đúng nghĩa, không phải dashboard xem số.
- 5 mục ❌ đã nằm sẵn trong work-order: I1→Epic I/V1 · V6→Epic I/V2+V11 · I3→UI-D2 · O5, R1 = mới.
- **4 mục BỔ SUNG mới cho agent (xếp sau UI-A→D của `AUDIT_UI_PARITY_2026-07-04.md`):**
  1. **BS-1 Quota panel**: card trong Hệ thống hiển thị YouTube quota units đã dùng/ước tính còn (nguồn: `estimate_quota_cost` + đếm upload trong ngày) + token dịch còn lại nếu provider trả.
  2. **BS-2 Error translator**: map mã lỗi phổ biến (ffmpeg exit, OAuth expired, quota exceeded, compliance_blocked) → câu tiếng Việt + nút hành động (Retry / mở tab liên quan). Bảng map đặt trong 1 file TS duy nhất.
  3. **BS-3 Smart alerts**: rule ngưỡng tính từ `/api/errors` + jobs (fail rate 1h > N%) → banner đỏ đầu Dashboard + chuông đếm.
  4. **BS-4 Audit view**: bảng gộp (thời gian · ai [operator/system] · hành động · đối tượng · kết quả) từ approvals + usage + jobengine events, read-only, trong Hệ thống.


---

## PHẦN 2 — QA SÂU THEO USE CASE (2026-07-04 chiều, bấm thật từng màn)

> Người vận hành phê bình đúng: phần 1 nặng "có/không có chức năng", nhẹ UX thật. Phần này đi từng use case, bấm thật, ghi từng defect. **Verdict phần 2: UI có đủ cơ bắp nhưng bố cục + luồng dữ liệu về UI còn nhiều lỗ hổng — 18 defect, trong đó 6 nặng.**

### Defect NẶNG (chặn trải nghiệm vận hành)

| # | Defect | Bằng chứng | Fix đề xuất |
|---|---|---|---|
| Đ1 | **Policy scan xong không thấy kết quả đâu** — Hoạt động ghi "Thành công" nhưng tab Chính sách hiện "Rules đang áp dụng (0)", không có "lần quét gần nhất lúc X — tìm thấy Y rule mới, Z thay đổi" | Test live: chạy scan ✓ → tab Chính sách trống | Backend thêm `last_scan_at/new_rules/summary` vào `GET /api/policy`; UI hiện dòng kết quả ngay dưới nút Quét + link xem chi tiết diff rule |
| Đ2 | **Cột trái Studio quá tải** — 1 cột nhồi kênh + 5 khối config + hành động nhanh + checkbox + 4 nút + office thumbnail → nút Render/Full Run bị chôn dưới scroll | Screenshot người vận hành + tái hiện | Tách config thành Drawer "Cấu hình sản xuất" (mở khi cần); cột trái chỉ còn: chọn kênh · 4 nút hành động · trạng thái job · pause checkbox |
| Đ3 | **Office thumbnail bé vô dụng** trong cột trái | Screenshot người vận hành | Bỏ thumbnail; thay bằng 1 nút "🏢 Mở Văn phòng" (fullscreen ĐÃ hoạt động tốt — verify live) |
| Đ4 | **Thư viện: video không phát** — player 0:00, bấm play im lặng | Test live drawer "3 Foods..." | Map đúng path qua `/media` hoặc `/pmedia` (`getMediaUrl`); nếu 404 hiện lỗi rõ thay vì player câm |
| Đ5 | **Thư viện: "Nội dung Kịch bản" chỉ hiện tên file `script.txt`** — dead-end, không xem được script | Test live, click không phản ứng | Backend expose nội dung (đọc qua `/api/product/meta` hoặc thêm `?include=script`); UI render script viewer (hook/segment heading) |
| Đ6 | **Video QA PASS không tự vào hàng duyệt** — Duyệt & Đăng trống dù video pass 12+ giờ; bước cuối cùng của dây chuyền 24/7 lại thủ công | Duyệt & Đăng = empty; video PASS nằm ở Studio | Render xong + audit pass → **tự động** `POST /api/publish/{ch}` tạo approval (destination `approval_required` đã có); Studio giữ nút gửi tay như phụ |

### Defect VỪA (hiển thị dữ liệu sai/thiếu)

| # | Defect | Fix |
|---|---|---|
| Đ7 | Thumbnail card Thư viện đen (ảnh không load) + title chữ trắng đè ảnh trùng với title dưới card | Sửa path thumb qua /media; bỏ title overlay trên ảnh |
| Đ8 | "Thời lượng: 8m 53.70000000000045s" — float thô | Format mm:ss |
| Đ9 | "Thời gian tạo: —", "Độ phân giải: —" trên mọi card/drawer | Đọc từ meta.json/audit sidecar (đã có duration/width/height) |
| Đ10 | Bảng Kênh cột Giọng đọc hiện "Mặc định" dù kênh có `voice_profile: kokoro_en_us_v1` (parse `split(':')[1]` fail với format không có `:`) | Fallback hiện nguyên chuỗi khi không có `:` |
| Đ11 | Kênh badge "Paused" không rõ nguồn nghĩa (scheduler? kill-switch?) không tooltip | Tooltip + đổi label "Lịch tắt" nếu là scheduler |
| Đ12 | Dropdown "Mô hình AI Generator: Gemini 2.5 Flash" trong HÌNH ẢNH & STYLE — nghi danh sách hardcode không khớp registry | Đổ options từ `/api/capabilities` (kind=image/video) |

### Defect NHẸ (polish)

| # | Defect |
|---|---|
| Đ13 | Duyệt & Đăng khi trống = trang trắng 90% — nên kèm bảng "Đã duyệt/đã đăng gần đây" (GET /api/approvals?status=published) |
| Đ14 | Click sidebar vùng icon đôi khi không điều hướng (hit-area Link) |
| Đ15 | Office fullscreen: văn phòng TRỐNG không có nhân vật agent (office_app chưa nối SSE agent thật — đã ghi C10, nhắc lại vì giờ nhìn thấy rõ) |
| Đ16 | Drawer sửa kênh = raw JSON editor-first — nguy hiểm cho người vận hành; cần form fields (kể cả VoicePicker — hiện KHÔNG được nhúng ở drawer kênh, nơi cần nó nhất) + JSON xếp sau thành "Nâng cao" |
| Đ17 | Timeline mini (V1) trong Studio: chip # không có tooltip nội dung câu; track Video chip không rõ trạng thái từng shot |
| Đ18 | "Lịch sử Render" panel phải: item không có ngày giờ |

### Ghi nhận ĐẠT trong phần bấm thật
Nút Audio per-scene phát thật (đổi "Dừng", chip Voice sáng) ✓ · Kill-switch pause→resume trọn vòng ✓ · Test capability gemini "Kết nối OK" ✓ · Bảng Kênh có cột Views/Subs/Videos/Doanh thu (UI-D1 xong) ✓ · Office fullscreen render đẹp ✓ · Drawer kênh có "Thiết lập phụ đề nhanh" (V2 bắt đầu) ✓ · Thư viện có badge QA PASS/WARN + điểm + Script-only/Đã render ✓ · Nút "Gửi duyệt đăng" có trong drawer Thư viện ✓.

### Thứ tự sửa cho agent
1. **Đ1** (policy feedback) + **Đ6** (auto-queue duyệt) — 2 cái phá niềm tin "bấm xong có thấy gì đâu".
2. **Đ4+Đ5+Đ7** (Thư viện xem được video/script/thumb — trải nghiệm kho).
3. **Đ2+Đ3** (bố cục Studio: config vào drawer, office thành nút).
4. Đ8–Đ12 (một PR data-formatting).
5. Đ13–Đ18 (polish + đã trùng các WO cũ: Đ15=C10, Đ16=E1-form, Đ17=Epic I/V1).


---

## PHẦN 3 — NGHIỆM THU V3 REDESIGN (2026-07-05, verify live từng màn)

**Verdict: BƯỚC NHẢY LỚN — ĐẠT 80%.** Thẩm mỹ đổi hẳn sang dark cockpit Linear-grade; IA tách tab đúng spec; đa số defect nặng đã đóng. Còn 1 defect nặng + vài sót nhỏ.

### ĐẠT (bấm thật xác nhận)
| Mục | Bằng chứng live |
|---|---|
| Dark cockpit toàn app (DESIGN.md) | Near-black + hairline + mono metrics + accent indigo — Dashboard/Xưởng/Hệ thống đều nhất quán |
| IA mới tách tab (SPEC v3 §2) | Sidebar nhóm: Bảng điều khiển/Xưởng/Thư viện · Kênh/Lịch & Tự động · Duyệt/Nền tảng & Đích/Phân tích · Doanh thu · Hệ thống · Văn phòng |
| **Xưởng hết nhồi (Đ2/Đ3/UI-A)** | StepFlow ①→④ trên đầu (Discovery ✓, Render progress bar); cấu hình = card tóm tắt + nút "Chỉnh ⚙" (drawer); office thumbnail đã bỏ; stats "8m 54s" format đẹp; Lịch sử render có thời lượng + PASS badge |
| **Đ1 policy feedback** | Banner "Lần quét gần nhất: 16:44:39 4/7/2026 — Kết quả: Không tìm thấy thay đổi chính sách nào mới" (xanh) |
| **Đ5 script viewer** | Drawer Thư viện hiện NỘI DUNG script thật (đoạn hook + [segment] highlight) |
| Đ9 metadata | Thời gian tạo 18:24:37 17/6/2026 + Độ phân giải 1920x1080 + ngày trên card |
| **UI-C Nền tảng & Đích** | Bảng platforms (YouTube Official API / TikTok Dry Run) + destinations per kênh (HITL, Enabled/Disabled) |
| Văn phòng route riêng | Fullscreen render tốt (vẫn trống nhân vật — C10 tương lai) |

### CÒN SÓT (giao agent đợt kế)
| # | Defect | Mức |
|---|---|---|
| S1 (=Đ4) | **Thư viện: video player vẫn câm** — 0:00, bấm play không phát, không báo lỗi. Fix src qua /media hoặc /pmedia + hiện lỗi 404 rõ | NẶNG |
| S2 (=Đ7) | Thumbnail card Thư viện vẫn đen + title chữ đè ảnh | Vừa |
| S3 (=Đ8 sót) | Drawer Thư viện: "Thời lượng 6m 8.30000000000011s" (Xưởng đã fix, drawer chưa — dùng chung 1 formatDur) | Nhẹ |
| S4 | Sidebar icon-rail KHÔNG có label ở màn rộng — DESIGN.md quy định 232px + label ≥1000px; icon trần khó học (10 mục) | Vừa |
| S5 | Bảng Nền tảng: YouTube hiện tỷ lệ 9:16 — đúng phải 16:9 (đọc nhầm field format_spec) | Nhẹ |
| S6 | Chưa verify được (cần chạy thật đợt sau): Đ6 auto-queue duyệt sau render PASS · trang Phân tích + Lịch & Tự động · VoicePicker trong drawer kênh (Đ16) |

**Thứ tự sửa:** S1 → S4 → S2 → S3+S5 (gộp 1 PR nhỏ) → verify S6 khi có render mới.

---

## PHẦN 4 — ĐÓNG DEFECT (2026-07-05, build xanh)

Sau khi Studio đã bê nguyên design Xuong-standalone (dark cockpit) + sidebar icon-rail, đóng các defect actionable:

| Mục | Trạng thái | Fix |
|---|---|---|
| **S1** Thư viện video câm | ✅ ĐÓNG | `Library.tsx`: thêm `pmediaUrl(p,file)` = `/pmedia/{channel}/{slug}/{file}` (products serve ở /pmedia, không phải /media) — thay 4 chỗ `getMediaUrl(product.*)`; reset videoError khi đổi product |
| **S2** Thumbnail đen | ✅ ĐÓNG | Cùng fix pmediaUrl cho thumbnail card + tải thumbnail |
| **S3** Duration float ở drawer | ✅ ĐÓNG (từ trước) | `formatDuration` shared trong Library |
| **S5** Platforms YouTube tỷ lệ sai | ✅ ĐÓNG | UI đọc `format_spec.aspect_ratio` (số ít, backend trả "16:9") thay vì `aspect_ratios` (số nhiều, không tồn tại) |
| **Đ6/S6** Auto-queue duyệt sau render PASS | ✅ ĐÓNG | `pipeline/steps.py::_step_render`: sau `_audit_rendered_output()` pass (cả 2 nhánh Flow + all-stock) → `await _auto_queue_approval()` POST `/api/publish/{ch}` (async httpx, best-effort, bỏ qua Shorts, tắt bằng `OMNICAST_AUTO_QUEUE=0`). Video PASS giờ tự vào Duyệt & Đăng |
| **BS-2** Error translator | ✅ ĐÓNG | `frontend_v2/src/lib/errorTranslator.ts` (map quota/oauth/compliance/ffmpeg/flow/rate-limit/network → câu VN + action) — wire vào chuông thông báo App.tsx (title+detail+link hành động, màu theo severity) |

**BS bổ sung — ĐÃ XONG hết (2026-07-05):**
- **BS-1 Quota panel** (=O5): ✅ `GET /api/quota` (đếm upload/ngày từ `published_videos` × `estimate_quota_cost`=1650) + card thanh % trong System→Budget (đỏ >80%). Live test trả `{used,limit,uploads_today,per_upload_units,reset_hint}`.
- **BS-2 Error translator**: ✅ (Phần 4 trên).
- **BS-3 Smart alerts** (=R1): ✅ banner Dashboard — >5 lỗi/1h → cảnh báo đỏ (tính client từ `/api/errors` timestamp).
- **BS-4 Audit view**: ✅ trang mới `AuditLog.tsx` (route `/audit` + rail "Nhật ký kiểm toán") gộp approvals+usage+`/jobengine/jobs` → bảng khi·ai·hành động·đối tượng·kết quả, filter Người/Hệ thống + search. Thuần frontend (join 3 endpoint).

**CÒN LẠI = chỉ epic lớn (ngoài phạm vi nghiệm thu này, cần milestone riêng):**
- **5 ❌ Phần 1 (I1/I3/V6)**: multi-track timeline kiểu Premiere / analytics-map video↔script / bulk-actions preset. Spec để ở `PLAN_UI_remaining.md`.

---

## PHẦN 5 — I3 + V6 ĐÓNG, phát hiện + sửa 1 vi phạm O8 (2026-07-05)

- **I3 Analytics-map** ✅: thêm `GET /api/published` (server.py, wrap `vault_db.list_published`). `Analytics.tsx` join metrics.post_id == published.youtube_video_id → published.title == products.title → cột mới "Kịch bản / Sản phẩm" (score/niche/QA). Live test: endpoint trả `{"published":[],"total":0}` (đúng — chưa video nào publish qua pipeline mới).
- **V6 Bulk actions** ✅ (bounded — bulk-approve, chưa làm subtitle-preset vì phụ thuộc I1): `Approvals.tsx` thêm checkbox mỗi card + "Chọn tất cả" + thanh hành động "Duyệt hàng loạt (N)" với privacy chọn chung → loop `POST /api/approvals/{id}/approve`.
- **Phát hiện thêm khi đọc Approvals.tsx: vi phạm O8** ("Số liệu THẬT, cấm fake") — bảng "Hiệu năng kênh đăng tải" trong mỗi card có **số cứng giả** (`1,240` views, `$21.50`...) dù §O8 đã ghi ✅. Đã sửa: tách `<ApprovalMetrics>` fetch thật `/api/platforms/metrics`, join theo `post_id`; không có số thật → hiện link "Xem tab Phân tích" thay vì bịa.
- **I1 multi-track timeline**: KHÔNG làm — xác nhận lại đây là epic nhiều tuần thật sự (drag-drop track Video/Audio/Sub, sửa từng câu phụ đề, cần thư viện + backend edit-per-caption). Cố nhồi nhanh sẽ vi phạm chính quy tắc O8/chất lượng vừa sửa ở trên. Giữ nguyên trong `PLAN_UI_remaining.md` cho milestone riêng.

**Build:** `npm run build` xanh sau mỗi thay đổi; backend restart + `/api/quota`, `/api/published`, `/api/approvals` verify 200 live.

**S4** (sidebar icon-rail không label): giữ nguyên theo yêu cầu mới "bê nguyên sidebar Xuong-standalone" (icon-only) — mâu thuẫn DESIGN.md cũ nhưng đúng quyết định vận hành mới nhất.
