# SPEC UI v2 — Đập đi xây lại giao diện OmniCast (bản cho agent UI thực thi)

> **Quyết định:** UI hiện tại (`api/webui/` — Babel-in-browser, 1 file HTML 1.700 dòng) bị thay thế HOÀN TOÀN bằng app build chuẩn. Bản này là spec đầy đủ: stack, design system, kiến trúc màn hình, data contract, nghiệm thu. Học pattern trực tiếp từ `_refs/` (dẫn chiếu từng chỗ).
> **Thay thế `PLAN_EpicE_UI.md`** (giữ file cũ làm tham khảo data-contract, KHÔNG làm theo lộ trình PR cũ nữa).
> Người thực thi: agent UI. Đọc §0 trước. Không hiểu chỗ nào → đọc đúng file được dẫn, không đoán.

---

## 0. LUẬT CỨNG

1. Xây app MỚI tại `implementation/frontend_v2/` (Vite). KHÔNG sửa file nào trong `api/webui/` (app cũ chạy song song đến khi nghiệm thu xong — strangler). KHÔNG sửa file `.py` nào **trừ MỘT chỗ duy nhất** được chỉ ở §8 (mount thư mục build).
2. UI chỉ GỌI endpoint đã tồn tại (danh mục §6). Thiếu endpoint → ghi `BLOCKED: cần <endpoint>` vào cuối spec-report, bỏ qua phần đó. CẤM bịa endpoint, CẤM hardcode dữ liệu giả.
3. Offline-first: KHÔNG CDN, không Google Fonts link. Font/icon vendored trong repo.
4. Encoding UTF-8; sau mỗi file: `grep -c "Ã\|áº\|á»\|Ä'" src/**` = 0. Không dùng emoji làm icon.
5. Mỗi Phase (§9) = 1 PR + chạy verify checklist của Phase đó. Không gộp Phase.
6. TypeScript bắt buộc (Vite template react-ts). Types cho API response viết theo QUAN SÁT THẬT (mở `http://127.0.0.1:8767/api/...` trong Chrome xem JSON, hoặc đọc handler Python theo bảng §6) — field nào không chắc thì để `unknown`/optional, không bịa.
7. Video/pixel-art office cũ (`api/webui/office_app/`) được nhúng lại qua `<iframe src="/office_app/index.html">` — không port, không sửa.

## 1. STACK (chuẩn theo `_refs/pixel-agents/webview-ui` — repo tham chiếu sát nhất)

- **Vite + React 19 + TypeScript** (`npm create vite@latest frontend_v2 -- --template react-ts`).
- **Tailwind CSS v4** (`@import 'tailwindcss'` + `@theme` tokens — xem cách làm thật tại `_refs/pixel-agents/webview-ui/src/index.css`).
- State/server-data: **TanStack Query** (poll + cache + retry — thay cho đống `window.OMNI_*` cũ). Router: **react-router v7** (giữ tab khi F5, deep-link `/approvals`).
- Icons: **lucide-react** (import từng icon — tree-shaken, offline sau build).
- KHÔNG thêm chart lib; chart = SVG tự vẽ (bar/line đơn giản) hoặc bỏ qua.
- Font vendored: **Be Vietnam Pro** (400/500/600/700 woff2 — đã có sẵn `api/webui/assets/fonts/`, copy sang `frontend_v2/public/fonts/`) cho UI; **IBM Plex Mono** (tải woff2 về `public/fonts/`) cho số liệu/log — theo type system của `_refs/hyperframes/DESIGN.md`.

## 2. DESIGN SYSTEM (adapt từ `_refs/hyperframes/DESIGN.md` — đọc file đó trước khi viết CSS)

**Light mode = mặc định** (cockpit đọc số liệu ban ngày), có dark toggle (persist localStorage).

```css
:root {                       /* Light — palette "warm paper" của hyperframes */
  --bg:#f6f5f1; --surface:#ffffff; --surface2:#eeedea;
  --border:#e0dfdb; --border-hover:#d0cfcb;
  --text:#1a1a1a; --text2:#6b6b6b; --text3:#999999; --heading:#0a0a0a;
  --green:#1a7a0a; --green-soft:rgba(26,122,10,.07);
  --blue:#2563eb;  --blue-soft:rgba(37,99,235,.06);
  --purple:#7c3aed;--purple-soft:rgba(124,58,237,.06);
  --amber:#b45309; --amber-soft:rgba(180,83,9,.08);
  --red:#d14249;   --red-soft:rgba(209,66,73,.08);
}
.dark {                       /* Dark — hyperframes dark */
  --bg:#0a0a0a; --surface:#141414; --surface2:#1a1a1a;
  --border:#2a2a2a; --border-hover:#3a3a3a;
  --text:#e5e5e5; --text2:#a0a0a0; --text3:#666666; --heading:#f5f5f5;
  --green:#22c55e; --blue:#3b82f6; --purple:#a78bfa; --amber:#fbbf24; --red:#ef4444;
  /* -soft tương ứng: rgba(...,0.1) */
}
```

- **Type scale** (theo hyperframes): H1 24px/600, H2 18px/600, H3 15px/600, body 14px/400 lh1.6, caption 12px, mono 12.5px. Letter-spacing heading `-0.01em`.
- **Spacing:** 4/8/16/24/32px. **Radius:** card 12px, control 8px, pill 999px. **Shadow:** 1 mức duy nhất cho card `0 1px 2px rgba(0,0,0,.04), 0 1px 3px rgba(0,0,0,.06)`; KHÔNG glow, KHÔNG nhiều lớp bóng.
- **Nguyên tắc thị giác:** nền trang `--bg`, card trắng viền `--border`; MÀU chỉ dành cho trạng thái/hành động (xanh dương = primary action, xanh lá = success/money, đỏ = lỗi/destructive, amber = chờ); số liệu lớn dùng mono; mật độ vừa (row height 40px, card padding 16-20px).

## 3. INFORMATION ARCHITECTURE — 13 tab cũ → 7 mục (map đầy đủ, không mất chức năng)

```
SIDEBAR (7 mục + search):
1. Tổng quan        ← Dashboard cũ
2. Studio           ← Tạo Video + Sản xuất Video + Văn phòng(embed) gộp thành workflow
3. Thư viện         ← Kịch bản + sản phẩm đã render (products)
4. Kênh & Niche     ← Kênh + Niche Scanner + Niche Vault (sub-tab)
5. Duyệt & Đăng     ← Approvals + Lịch đăng (sub-tab)         [badge = số chờ duyệt]
6. Kiếm tiền        ← Monetization (readiness/offers/analytics)
7. Hệ thống         ← Providers + Hạ tầng + Chính sách + Chi phí (sub-tab)
```
Topbar: breadcrumb · StatusPill kết nối (3 trạng thái, không nhấp nháy) · KillSwitch pill (pause/resume thật) · dark toggle · chuông thông báo (đọc `/api/errors`).

## 4. MÀN HÌNH CHÍNH — spec từng cái

### 4.1 Studio (màn quan trọng nhất — học layout 3 cột của `_refs/Pixelle-Video/resources/webui.png`, MỞ ẢNH NÀY XEM trước khi code)

```
┌──────────┬──────────────────────────┬────────────────────┐
│ TRÁI      │ GIỮA — pipeline steps    │ PHẢI — kết quả      │
│ Kênh +    │ ① Topic    [Chạy] [log] │ ▶ video player      │
│ model +   │ ② Kịch bản [Chạy] score │ thumbnail + title   │
│ quick     │ ③ Render   [Chạy] %     │ audit badge (pass/  │
│ actions + │ ④ Gửi duyệt [nút]       │  issues từ sidecar) │
│ office    │ mỗi step: trạng thái     │ [Gửi duyệt đăng]    │
│ embed thu │ chờ/đang/xong/lỗi + retry│ stats: dài/size/res │
│ nhỏ       │ (SSE cập nhật realtime)  │ + link sản phẩm cũ  │
└──────────┴──────────────────────────┴────────────────────┘
```
- Step model: mỗi step là card có `trạng thái` (idle/running/success/failed — status-tag per item học từ `_refs/h2dev_flow` sidepanel), nút chạy riêng, log thu gọn (giữ live log agent như hiện tại qua SSE `/jobengine/api/v1/events/stream` + `/api/render/status` poll 3s khi đang render).
- Actions gọi endpoint cũ: Phase1 `/api/run/{ch}`, Phase2 `/api/run/{ch}/script`, Render `/api/render/{ch}`, Gửi duyệt `POST /api/publish/{ch}` body `{privacy_status:'unlisted'}`.
- Kết quả phải: `GET /api/render/latest?channel_id=` (video/thumb/title qua `/media/...`) + audit đọc từ `/api/monetization/readiness.outputs[0].audit` — hiện badge `Đạt chuẩn đăng` xanh hoặc list issues đỏ (duration/loudness/visual).
- Office pixel-art: khối thu nhỏ góc trái dưới, iframe `/office_app/index.html`, nút phóng to (route riêng `/studio/office` full-screen iframe).

### 4.2 Duyệt & Đăng (màn kiếm tiền — làm kỹ nhất thứ 2)
- Card ngang mỗi approval: thumbnail 160×90 (từ `raw.thumbnail_paths[0]` map sang `/media/`, lỗi → placeholder icon film) · title · badge platform (youtube đỏ / tiktok đen + tag `dry-run` nếu `raw.dry_run`) · "x phút trước" · 2 dòng đầu summary.
- Nút `Duyệt` → modal: select privacy (**unlisted mặc định**/private/public) + checkbox force + note → `POST /api/approvals/{id}/approve` body `{privacy_status, force, note, operator:'dashboard'}`. Response có `raw.youtube_video_id` → toast + nút mở `https://youtu.be/{id}`; có `raw.publish_error` → box đỏ hiện NGAY trên card (lỗi không được nuốt).
- `Từ chối` → modal note → `/reject`. Sub-tab `Lịch đăng`: port nguyên chức năng Scheduler cũ (`/api/scheduler`, `/toggle`, `/api/auto/status`, `/api/auto/run`).

### 4.3 Hệ thống › Providers (port từ tab Providers hiện có — đã đúng chức năng, chỉ làm đẹp lại)
- Grid card theo kind (text/image/video/tts), runtime badge local/remote/browser, nút `Test` → `POST /api/capabilities/{kind}/{provider_id}/health` (kết quả ok/error hiện trên card + timestamp), form credential động theo `metadata.config_schema` (password input cho api_key/secret; oauth → chỉ text hướng dẫn chạy `scripts/youtube_authorize.py`), bảng usage lọc từ `/api/usage`. Secret không bao giờ hiển thị lại.
- Pattern tham chiếu: Settings Modal của `_refs/pixel-agents/webview-ui/src/components/SettingsModal.tsx` (nhóm setting, mô tả dưới field) + "Test Connection" của Pixelle-Video/MoneyPrinterTurbo.

### 4.4 Thư viện
- Grid sản phẩm: thumbnail + title + score badge + ngày + trạng thái (script-only / đã render / đã đăng). Nguồn: `/api/products` + `/api/product/meta`. Click → drawer chi tiết: video player (nếu có), script viewer (đọc đẹp: hook/segment headings), variants + debate scores, nút `Render` / `Gửi duyệt`.
- Voice preview trong drawer kênh (học `_refs/voice-pro`): `/api/voices` + `POST /api/voice/preview` → `<audio>` nghe thử trước khi set `/api/channel/{id}/voice`.

### 4.5 Tổng quan
- 4 KPI (Đang chạy/Script hôm nay/Chi phí hôm nay/Kênh) + hàng đợi job realtime (SSE) + Lỗi gần đây + Hoạt động gần đây. Mỗi khối có skeleton + empty-state (copy tiếng Việt lấy nguyên văn từ `PLAN_EpicE_UI.md` §PR-2c — bảng copy đó vẫn hiệu lực).

### 4.6 Kênh & Niche · Kiếm tiền · Hệ thống (các sub còn lại)
- Port 1-1 chức năng từ tab cũ (đọc component tương ứng trong `api/webui/app/pages.jsx` để biết ĐỦ danh sách nút/hành vi — đó là source of truth chức năng), áp component library mới. Kiếm tiền: Readiness checklist (xanh/WAIT như hiện tại), Offers CRUD, blockers panel. Hệ thống: Hạ tầng (infra components + worker + error log), Chính sách (policy rules + fetch + approve/reject), Chi phí (budget + usage).

## 5. COMPONENT LIBRARY (`src/components/ui/` — làm TRƯỚC màn hình)

`Button` (primary/ghost/danger/sm) · `Card` (+CardHeader title/sub/actions) · `KPI` (label/value/sub, value = mono) · `Badge` (green/blue/amber/red/neutral) · `StatusTag` (idle/running[pulse]/success/failed) · `Table` (sticky header, row 40px) · `Modal` + `ConfirmModal` · `Drawer` (phải, 480px) · `Toast` (queue, auto 4s) · `Tabs` (sub-tab trong trang) · `Select/Input/Checkbox` · `Skeleton` (shimmer) · `EmptyState` (icon/title/desc/action) · `StatusPill` (kết nối: xanh Đang chạy/vàng Đang kết nối lại…/đỏ Mất kết nối — đếm fail liên tiếp ≥3 mới đỏ) · `VideoPlayer` (wrap <video controls>) · `LogViewer` (mono, auto-scroll, collapse) · `JsonKV` (hiện dict đẹp).
Mỗi component: props tối thiểu, không config thừa. Storybook KHÔNG cần.

## 6. DATA LAYER

- `src/api/client.ts`: `apiGet/apiPost` (fetch, timeout 8s, base ``). `src/api/hooks.ts`: `useApi(path, {poll})` bọc TanStack Query; poll mặc định: status 5s, render/status 3s CHỈ khi đang render, approvals 10s, còn lại staleTime 30s + refetch on focus. **Cấm** gọi `/api/credits` tự động (mở Chrome thật — chỉ gọi khi bấm nút).
- SSE: `src/api/sse.ts` — 1 kết nối `/jobengine/api/v1/events/stream`, đẩy vào Query cache invalidate.
- Bảng endpoint (đầy đủ, đã tồn tại — handler xem `api/server.py` + `api/render_routes.py`):
  `GET /api/status · /api/infra · /api/errors?limit=30 · /api/channels/overview · /api/auto/status · /api/scheduler · /api/policy · /api/platforms · /api/destinations · /api/credentials · /api/capabilities · /api/budgets · /api/usage · /api/approvals · /api/monetization/offers · /api/monetization/readiness · /api/render/status · /api/render/latest · /api/products · /api/product/meta · /api/voices · /api/pipelines/executions · /jobengine/api/v1/jobs`
  `POST /api/run/{ch} · /api/run/{ch}/script · /api/render/{ch} · /api/publish/{ch} · /api/approvals/{id}/approve|reject · /api/policy/fetch · /api/policy/rules/{id} · /api/scheduler/toggle · /api/auto/run · /api/system/pause|resume · /api/credentials · /api/monetization/offers · /api/budgets · /api/capabilities/{kind}/{pid}/health · /api/channels/refresh-stats · /api/voice/preview · /api/channel/{id}/voice · /api/pipelines/run`

## 7. NGÔN NGỮ & COPY
Label vận hành = tiếng Việt; thuật ngữ giữ EN: Studio, Providers, Capabilities, Budgets, Usage, Offer, Destination, Readiness. Glossary + copy empty-state: dùng bảng trong `PLAN_EpicE_UI.md` (PR-2c, PR-3). Không câu nửa Việt nửa Anh trong 1 card.

## 8. BUILD & SERVE (điểm sửa backend DUY NHẤT được phép)

- `npm run build` → output `implementation/src/omnicast/api/webui_v2/` (cấu hình Vite `outDir`, `base: '/'`).
- Sửa `api/server.py` chỗ mount static hiện tại: nếu env `OMNICAST_UI=v1` → serve `api/webui/` (đường cũ); mặc định serve `api/webui_v2/` nếu thư mục tồn tại, fallback `api/webui/`. Giữ nguyên mount `/office_app` và `/media`.
- Dev loop: `npm run dev` (proxy `/api`+`/media`+`/jobengine`+`/office_app` → `127.0.0.1:8767` trong `vite.config.ts`).

## 9. PHASES (mỗi Phase 1 PR, verify xong mới đi tiếp)

| Phase | Nội dung | Verify |
|---|---|---|
| P1 | Scaffold Vite+TS+Tailwind, tokens §2, font vendored, component library §5, shell (sidebar 7 mục + topbar + router + StatusPill) — trang trống có skeleton | `npm run build` sạch; mở qua backend thấy shell + dark toggle; 0 console error |
| P2 | Tổng quan + Data layer hoàn chỉnh (hooks/SSE) | KPI số thật; rút mạng → StatusPill vàng→đỏ, không vỡ layout |
| P3 | Studio (4.1) đủ 4 step + kết quả + office embed | Chạy được Phase1/2 thật từ UI, log realtime, video cũ xem được trong player |
| P4 | Duyệt & Đăng (4.2) + Lịch đăng | Tạo approval thật → duyệt unlisted → thấy link YouTube hoặc lỗi đỏ trên card |
| P5 | Thư viện (4.4) + voice preview | Xem script score-104, nghe thử 1 voice |
| P6 | Kênh & Niche + Kiếm tiền + Hệ thống (4.3/4.6) | Test capability 1 provider ok; đủ parity checklist §10 |
| P7 | Polish: responsive (≥1000px sidebar icon-only), keyboard esc đóng modal, chuyển `/` sang v2 mặc định, chụp screenshot từng màn so với v1 | Toàn bộ §10 pass; đóng app cũ webui/ không còn được serve mặc định |

## 10. NGHIỆM THU CUỐI (parity + chất lượng)

1. **Parity:** mọi hành động làm được ở UI cũ đều làm được ở v2 (đối chiếu danh sách action §6 — từng nút bấm thử, ghi bảng ✓).
2. First paint < 1s sau khi backend sẵn sàng (không còn Babel runtime).
3. 0 console error, 0 request 404 (trừ favicon), 0 mojibake, 0 emoji-icon.
4. Mọi bảng/card có đủ 3 trạng thái loading/empty/data; lỗi API hiện trong UI (không nuốt).
5. Ảnh chụp 7 màn hình đặt cạnh screenshot Pixelle-Video/hyperframes — người vận hành duyệt cảm quan lần cuối.
6. Cập nhật `IMPLEMENTATION_STATUS.md` (mục 2 + đánh dấu webui cũ = legacy) trong cùng PR P7.

---

## 11. KẾT QUẢ KIỂM TRA CODE v2 — 2026-07-04 (reviewer: Claude)

**ĐẠT (chất lượng cao, đúng spec):** stack đúng 100% (Vite 8 + React 19 + TS + Tailwind 4 + TanStack Query + react-router 7 + lucide, oxlint); design tokens đúng từng mã hex §2, dark mode persist; fonts vendored; shell chuẩn (7 mục IA, StatusPill 3 trạng thái có đếm fail liên tiếp, KillSwitch + ConfirmModal, chuông lỗi, breadcrumb, sidebar icon-only <md); **HashRouter** (né được deep-link 404 của StaticFiles — lựa chọn đúng); `getMediaUrl` xử lý path Windows; Studio đủ steps + SSE log + audit badge đọc từ readiness sidecar + player; Approvals đủ privacy **unlisted mặc định** + force + `publish_error` hiện trên card + link YouTube; build minified ~360KB; mount strangler `OMNICAST_UI=v1` đúng §8.

**ĐÃ SỬA trong lần review này (3 lỗi chặn):**
1. `/office_app` không được mount riêng khi "/" trỏ webui_v2 → iframe Văn phòng 404. Đã thêm mount trong `api/server.py` (khối webui cuối file).
2. Envelope bug: `/api/errors`, `/api/infra`, `/api/system/state` bọc `{data, source, fetched_at}` nhưng v2 đọc field ở root → chuông lỗi luôn rỗng, KillSwitch không phản ánh paused, tab Hạ tầng rỗng. Đã thêm `unwrapEnvelope()` tập trung trong `api/client.ts` + 2 fetch thô trong `App.tsx`.
3. `src/App.tsx` + `src/api/client.ts` bị **cắt cụt cuối file** (đứt giữa dòng — lỗi ghi file qua mount, cùng loại sự cố NUL-bytes của pages.jsx v1). Đã khôi phục + rebuild bundle (`assets/index-oX5oOP7v.js`).

**CHƯA ĐẠT PARITY (P6 dở dang — việc còn lại cho agent UI):**
- Thiếu hẳn UI cho: **Providers/Capabilities** (test connection + form credential động theo `config_schema` — §4.3, quan trọng nhất), **Policy/Chính sách** (`/api/policy*`), **Budgets + Usage + Credentials list**, **Auto-pilot** (`/api/auto/status|run`), **Platforms/Destinations**, **bảng JobEngine jobs** (SSE đã kết nối nhưng không có view nào đọc `/jobengine/api/v1/jobs`). `System.tsx` hiện chỉ có card Vault + Infra; `Monetization.tsx` chỉ offers + readiness.
- Polish nhỏ: footer "v2.0.0 · OFFLINE MODE" (copy sai — bỏ "OFFLINE MODE"); nút kill-switch label "PAUSED/ACTIVE" (đổi "Tạm dừng/Đang chạy"); ô Tìm kiếm chưa có chức năng (ẩn đi hoặc làm thật); font thiếu weight 500/600 (đang nhảy 400→700).
- Lưu ý cho agent: khi ghi file lớn qua tool, verify lại tail file sau khi ghi (đã có 3 sự cố ghi hỏng trên máy này); build bằng `npm run build` (tsc + vite) trước khi bàn giao.

### 11.1 CẬP NHẬT 2026-07-04 (sáng) — P6 HOÀN THÀNH + verify live trong app

- ✅ **P6 xong:** trang Hệ thống giờ có 6 sub-tab (Providers · Tự động & Lịch · Chính sách · Jobs · Hạ tầng · Chi phí). Providers có credential form + nút Test (đã bấm thử live: gemini trả "Kết nối OK"); Jobs có bảng JobEngine + retry-per-job; Policy có fetch/approve/reject; Chi phí có budgets + usage ledger; InfraTab đọc đúng shape thật db/redis/workers (bỏ bảng Gemini/Kokoro latency bịa của bản cũ). Approvals có destinations chips; Auto-pilot nằm trong "Tự động & Lịch".
- ✅ **Sửa vi phạm nặng nhất (luật §0.2):** Dashboard có 2 chart hardcode số giả ("12,840 views +18.4%", "$184.50 +22.1%") trong khi kênh thật 0 view — đã thay bằng số thật từ `/api/channels/overview.totals` (views/videos/subs/est_revenue + linked) kèm ghi chú trung thực khi = 0. **Cấm tái phạm: không bao giờ vẽ chart bằng mảng số cứng.**
- ✅ Polish: footer bỏ "OFFLINE MODE", kill-switch label Việt hóa ("Tạm dừng/Đang chạy"), bỏ ô tìm kiếm chết.
- ✅ `tsc -b` sạch + build `assets/index-C3BtEM_K.js` (399KB) đã deploy vào `webui_v2/`; app mở lên first-paint nhanh, Dashboard/Hệ thống/Duyệt & Đăng verify bằng mắt trong app thật.
- Còn lại (P7): parity checklist từng nút (§10.1) + chụp đủ 7 màn + khi ổn thì archive webui v1.

### 11.1 CẬP NHẬT 2026-07-04 (phiên sau) — build fix + trạng thái parity thực tế
**LỖI CHẶN (build gãy) — ĐÃ SỬA:**
- `tsc -b` fail: `System.tsx:282` truyền `<Badge variant="purple">` nhưng union `BadgeProps.variant` thiếu `'purple'`. Đã thêm `'purple'` vào union + class `bg-[var(--purple-soft)]` trong `components/ui/index.tsx`. `npm run build` giờ xanh (bundle `index-B_OoAmSv.js`).
- Font 500/600 thiếu → faux-bold: khai báo weight-range `400 500` (Regular) + `600 700` (Bold) trong `src/index.css` (không cần tải thêm file). Hết "nhảy 400→700".

**PARITY — thực tế đã HƠN §11 gốc (review cũ lỗi thời):** `System.tsx` nay có đủ sub-tab **Providers** (capabilities + credentials + test health + form config), **Policy** (fetch + approve/reject rule), **Jobs** (`/jobengine/api/v1/jobs` + retry, badge GPU tím), **Budgets + Usage**, **Hạ tầng** (vault keys + `/api/infra`). Các polish footer/kill-switch/search cũng đã xử lý ở lần trước (grep = 0).

**CÒN THIẾU thật (feature, không phải lỗi):** UI cho **Auto-pilot** (`/api/auto/status|run`) và **Platforms/Destinations** (`/api/platforms` · `/api/destinations`) — chưa có view nào gọi. + P7 polish cuối (responsive verify, screenshot đối chiếu, chốt v2 mặc định).

### 11.2 KIỂM TRA 2026-07-04 (trưa) — đợt Epic I đầu của agent: PASS live, 1 bug mở, 1 cảnh báo hạ tầng

**Verify live trong app (bundle `index-CRzurVPo.js` 11:35):**
- ✅ **Studio lột xác theo layout Pixelle 3 cột:** trái = 5 khối cấu hình collapsible (Chủ đề & Discovery / Giọng đọc & TTS / Hình ảnh & Style / Nhạc nền BGM / Nhịp & Định dạng) + quick actions + nút Sinh Script/Sinh Ảnh/Render/Full Run; giữa = player + stats (thời lượng/dung lượng/**QA Status PASS**) + **PHÂN CẢNH CHI TIẾT 46 dòng có status từng scene (C4)**; phải = Live Monitor Logs mono + Lịch sử Render có search.
- ✅ **C1 pause-sửa-tiếp wire trọn vòng:** checkbox "Tạm dừng sau khi sinh Script" (ghi `pause_after_script` vào channel qua PUT `/api/channels/{id}`) → `pipeline/runner.py` raise `WAITING_EDIT:<script_path>` → server bắt vào job state → Studio hiện editor (GET/PUT `/api/script/edit`) → `POST /api/pipelines/resume/{job_id}` set `resume_script` + retry từ checkpoint.
- ✅ Endpoint mới đều tồn tại thật: `script/edit` GET+PUT, `dedup/check`, `topics/{ch}` + action, `run/{ch}/cancel`, `run/{ch}/images`, `music/harvest`, `pipelines/resume`. Bundle chứa đủ (grep WAITING_EDIT/script\_edit/dedup... = có).
- ✅ Build fix của agent đúng: Badge thêm 'purple', font weight-range 400-500/600-700.
- ✅ **Video mới "3 Foods Quietly Wrecking Your Ozempic Results" dài 8:53 + QA PASS** — vượt ngưỡng mid-roll 8:00, audit gates hoạt động.

**BUG MỞ (giao agent phía Windows sửa — lý do xem cảnh báo dưới):**
- ❌ `/office_app/index.html` → **404 runtime** (log xác nhận). Mount `/office_app` từng được thêm vào khối webui cuối `server.py` (xem §11 mục 1) nhưng bản server.py hiện tại của agent không còn nó → Studio hiện "Pixel Office chưa được cài". Fix: thêm lại trước mount `"/"`:
  `app.mount("/office_app", StaticFiles(directory=str(_WEBUI_V1_DIR / "office_app"), html=True), name="office_app")` (chỉ khi serve v2).

**⚠️ CẢNH BÁO HẠ TẦNG QUAN TRỌNG (cho MỌI agent làm việc qua phiên cowork/sandbox):**
- Sandbox mount có lúc trả **bản cũ/cắt cụt** của file vừa được sửa phía Windows (đã bắt được: `server.py` "kết thúc" giữa hàm ở dòng 4188, `Studio.tsx`/`Approvals.tsx`/`sse.ts` "đứt" giữa JSX — trong khi app chạy hoàn hảo và build 11:35 xanh → bản Windows nguyên vẹn).
- Hệ quả: (1) **CẤM edit file code từ sandbox khi file đó vừa được agent Windows sửa** — sẽ ghi đè bản tốt bằng bản cụt; (2) typecheck/build từ sandbox có thể fail giả — tin kết quả build chạy phía Windows; (3) trước khi edit bất kỳ file nào từ sandbox: so byte-size + tail với hành vi runtime thật của app; thấy nghi ngờ → dừng, giao việc cho agent Windows.
