# PLAN Epic E — Nâng cấp UI OmniCast (bản chi tiết cho agent UI)

> ⚠️ **SUPERSEDED 2026-07-03:** người vận hành quyết định ĐẬP UI CŨ XÂY LẠI TỪ ĐẦU — xem **`SPEC_UI_v2.md`** (root). File này chỉ còn giá trị tham khảo: bảng data-contract (§2), copy empty-state (PR-2c), glossary (PR-3). KHÔNG làm theo lộ trình PR-1→PR-10 nữa.

> **Đối tượng đọc:** agent chuyên UI (giỏi vẽ giao diện, KHÔNG giỏi suy luận backend).
> **Cách dùng:** làm ĐÚNG THEO TỪNG PR bên dưới, theo thứ tự. Mỗi PR có checklist nghiệm thu — tự chấm đủ ✓ mới chuyển PR kế. KHÔNG tự sáng tạo ngoài phạm vi từng PR. Gặp thứ không hiểu → đọc đúng file/dòng được chỉ, KHÔNG đoán.
> Nguồn gốc yêu cầu: `MASTER_PLAN_SuperApp.md` §7 (Epic E + E-Q) và `ARCHITECTURE_SuperApp_Plan.md` §10.4.

---

## 0. LUẬT CỨNG — vi phạm 1 điều là PR bị từ chối

1. **CHỈ được sửa các file trong `implementation/src/omnicast/api/webui/`** (index.html, app/*.jsx, assets/). KHÔNG sửa bất kỳ file `.py` nào. KHÔNG sửa `office_app/` (đó là app Vite build sẵn).
2. **KHÔNG đổi tên/đường dẫn API.** UI chỉ GỌI endpoint đã có. Cần dữ liệu mà không có endpoint → ghi chú "BLOCKED: cần endpoint X" vào PR description và bỏ qua phần đó, KHÔNG tự chế endpoint, KHÔNG hardcode dữ liệu giả.
3. **KHÔNG xoá / đổi tên** các hàm và biến global có sẵn: `OmniLoad`, `OmniLoadScripts`, `OmniConnectJobEvents`, `_get`, `_post`, `_run`, `_commit`, `window.__omniRerender`, và mọi `window.OMNI_*`. Chỉ được THÊM.
4. **Encoding:** mọi file .jsx/.html lưu UTF-8. Sau MỖI lần sửa file chạy: `grep -c "Ã\|áº\|Ä'" implementation/src/omnicast/api/webui/app/*.jsx` — kết quả phải là **0** cho mọi file. Nếu editor của bạn làm hỏng dấu tiếng Việt → viết lại chuỗi đó bằng tay.
5. **KHÔNG thêm thư viện từ CDN/npm.** App chạy offline trong desktop WebView2. Tài nguyên mới (icon SVG, font) phải **vendored** — chép file vào `assets/`.
6. **KHÔNG đụng logic polling/backend-call tần suất** (setInterval trong index.html/data.jsx) trừ khi PR chỉ định rõ. BUG-1 (cmd nhấp nháy) là việc của agent backend, không phải của bạn.
7. Không dùng emoji ký tự làm icon trong code mới. Icon = SVG component (xem PR-1).
8. Mỗi PR = 1 commit message rõ ràng `EpicE/<mã PR>: <nội dung>` + cập nhật 1 dòng vào `IMPLEMENTATION_STATUS.md` mục 2.
9. **Cách xem shape dữ liệu thật (bắt buộc làm, cấm đoán field):** mở app (OmniCast.lnk), rồi mở Chrome vào `http://127.0.0.1:8767` — cùng backend, có DevTools. Vào tab Network/Console xem JSON từng endpoint. Hoặc đọc handler Python theo bảng §2.
10. Sau mỗi PR: mở app thật, bấm qua đủ 13 tab, chụp màn hình tab bị ảnh hưởng, không có lỗi đỏ trong Console.

---

## 1. BẢN ĐỒ CODE UI HIỆN TẠI (đọc kỹ trước khi viết dòng nào)

```
implementation/src/omnicast/api/webui/
├── index.html          # ~1.700 dòng: <style> toàn bộ CSS (CSS vars có sẵn) + shell React
│                       #   dòng ~1380: load react.js / react-dom.js / babel.js (UMD, offline)
│                       #   dòng ~1498-1503: load app/*.jsx qua <script type="text/babel">
│                       #   dòng ~1627-1668: <App/> — switch tab → component
├── app/data.jsx        # TẦNG DỮ LIỆU: _get/_post/_run, OmniLoad() nạp mọi endpoint
│                       #   vào window.OMNI_*, SSE job events, toast
├── app/pages.jsx       # Dashboard, Channels, Scanner, NicheVault, Scheduler, Policy,
│                       #   Monetization, Infrastructure, Budget  (⚠ 114 dòng mojibake)
├── app/production.jsx  # CreateVideo, VideoProduction, Scripts
├── app/office.jsx / office_embed.jsx / character.jsx   # tab Văn phòng (KHÔNG đụng)
├── office_app/         # app pixel-art Vite build sẵn (KHÔNG đụng)
└── assets/             # react.js, react-dom.js, babel.js, ảnh, font
```

**Cơ chế state (không có Redux/Router):** `OmniLoad()` fetch tất cả endpoint → gán vào `window.OMNI_*` → gọi `_commit()` → gọi `window.__omniRerender()` (setState ép App render lại). Component đọc thẳng `window.OMNI_*` trong lúc render. Interval 7s + SSE + sau mỗi `_run` action đều gọi lại `OmniLoad()`.

**Helpers (data.jsx):**
- `_get(path, timeoutMs=6000)` → Promise<json> (tự abort khi quá giờ).
- `_post(path, body)` → Promise<json>.
- `_run(label, promise)` → hiện toast `label ✓ / ✗` rồi tự `OmniLoad()`. Mọi nút hành động PHẢI bọc qua `_run`.

**Tab id hiện có (index.html ~1657):** `dashboard, office, create, produce, channels, scripts, scanner, vault, scheduler, policy, monetization, infra, budget`.

**CSS vars có sẵn (dùng lại, đừng chế màu mới):** `--bg --bg-sidebar --surface --surface2 --surface3 --border --border-hover --text --text2 --text3 --blue --green --amber --red --purple` (+ biến thể `-soft`), radius `--r-sm/md/lg/xl`, shadow `--shadow-sm/md/lg`, `--font --mono`, layout `--sidebar-w --topbar-h --rightpanel-w`.

## 2. HỢP ĐỒNG DỮ LIỆU — global ↔ endpoint ↔ handler (đọc handler khi cần biết field)

| Global (window.*) | Endpoint | Handler (file:dòng ~) |
|---|---|---|
| OMNI_STATUS | GET /api/status | api/server.py (tìm `"/api/status"`) |
| OMNI_INFRA | GET /api/infra | api/server.py:2040 |
| OMNI_RENDER / OMNI_RENDER_OUT | GET /api/render/status · /api/render/latest | api/render_routes.py:307 · :336 |
| OMNI_CH_OVERVIEW | GET /api/channels/overview | api/server.py |
| OMNI_AUTO | GET /api/auto/status | api/server.py |
| OMNI_POLICY | GET /api/policy | api/server.py:2160-2190 |
| OMNI_SCHED | GET /api/scheduler | api/server.py:189-240 |
| OMNI_PLATFORMS / OMNI_DESTINATIONS | GET /api/platforms · /api/destinations | api/server.py |
| OMNI_CREDENTIALS | GET /api/credentials | api/server.py (trả list, KHÔNG có secret) |
| OMNI_OFFERS / OMNI_READINESS | GET /api/monetization/offers · /readiness | api/server.py:715 |
| OMNI_CAPABILITIES | GET /api/capabilities | api/server.py:1065 |
| OMNI_BUDGETS / OMNI_USAGE | GET /api/budgets · /api/usage | api/server.py |
| OMNI_APPROVALS | GET /api/approvals | api/server.py:1296 |
| OMNI_ERRORS | GET /api/errors?limit=30 | api/server.py |
| — (jobs) | GET /jobengine/api/v1/jobs · SSE /jobengine/api/v1/events/stream | src/omnicast/jobengine/api.py |

**Action endpoints UI được phép gọi (đều đã tồn tại):**
`POST /api/publish/{channel_id}` (body `{privacy_status}`) · `POST /api/approvals/{id}/approve|reject` (body nhận `privacy_status, force, note, operator`) · `POST /api/policy/fetch` · `POST /api/policy/rules/{id}` (body `{action: approve|reject}`) · `POST /api/scheduler/toggle` · `POST /api/auto/run` · `POST /api/system/pause|resume` · `POST /api/credentials` · `POST /api/monetization/offers` · `POST /api/budgets` · `POST /api/capabilities/{kind}/{provider_id}/health` · `POST /api/channels/refresh-stats`.

---

## 3. CÁC PR — LÀM THEO ĐÚNG THỨ TỰ

### PR-1 · E-Q1 — Chữ & Icon (nền tảng, làm đầu tiên)

**1a. Sửa 114 dòng mojibake trong `app/pages.jsx`.**
- Tìm đủ: `grep -n "Ã\|áº\|Ä'" app/pages.jsx`.
- Nguyên tắc: chuỗi hỏng là tiếng Việt bị double-encode. Viết lại BẰNG TAY theo nghĩa. Bảng chuỗi chuẩn (dùng đúng nguyên văn):

| Đang hiển thị (hỏng) | Viết lại thành |
|---|---|
| `Chi phÃ­ hÃ´m nay` | `Chi phí hôm nay` |
| `KÃªnh` | `Kênh` |
| `Hoáº¡t Ä‘á»™ng gáº§n Ä‘Ã¢y` | `Hoạt động gần đây` |
| `Ä‘ang cháº¡y` | `đang chạy` |
| `Lá»—i gáº§n Ä‘Ã¢y` | `Lỗi gần đây` |
| `KhÃ´ng cÃ³ lá»—i nÃ o` | `Không có lỗi nào` |
| `KhÃ´ng cÃ³ pipeline nÃ o Ä‘ang cháº¡y` | `Không có pipeline nào đang chạy` |
| `Táº¥t cáº£ pipeline cháº¡y á»•n Ä‘á»‹nh` | `Tất cả pipeline chạy ổn định` |
| `Tá»•ng chi phÃ­` | `Tổng chi phí` |
| `HoÃ n thÃ nh` | `Hoàn thành` |
| chuỗi bắt đầu `ðŸ` hoặc `âœ`/`â‰` | đó là EMOJI hỏng → thay bằng `<Icon/>` (mục 1b), không gõ lại emoji |

- Các dòng hỏng khác không có trong bảng: suy ra nghĩa từ context (label KPI, tiêu đề card, mô tả trang) và viết tiếng Việt có dấu chuẩn.

**1b. Icon system.** Tạo `assets/icons.svg` (SVG sprite, vendored — chép path từ bộ lucide.dev, ~30 icon: dashboard, video, film, tv, file-text, search, archive, calendar, shield, dollar-sign, server, wallet, settings, play, pause, check, x, refresh-cw, upload, alert-triangle, clock, zap, key, plug, activity, bar-chart, eye, thumbs-up, thumbs-down, external-link). Thêm vào **đầu `app/data.jsx`** (để mọi file sau dùng được):

```jsx
function Icon({ name, size = 16, className = '', style = {} }) {
  return (
    <svg width={size} height={size} className={'ico ' + className} style={style}
         fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <use href={'assets/icons.svg#' + name} />
    </svg>
  );
}
window.Icon = Icon;
```

- Thay TẤT CẢ emoji đang làm icon trong `pages.jsx`, `production.jsx`, `index.html` (sidebar/topbar) bằng `<Icon name="..."/>`. Emoji trong chuỗi văn bản thuần (câu mô tả) thì bỏ hẳn, không thay.

**1c. Font tiếng Việt.** Tải Be Vietnam Pro (400/500/600/700, woff2) vào `assets/fonts/`, khai báo `@font-face` trong `<style>` của index.html, đổi `--font: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif;`. KHÔNG dùng Google Fonts link (offline).

**Nghiệm thu PR-1:** `grep -c "Ã\|áº\|Ä'" app/*.jsx` = 0 mọi file · mở app: 13 tab không còn ô vuông/ký tự lạ · mọi icon là SVG cùng stroke-width · console không lỗi 404 font/icon.

### PR-2 · E-Q2 — Skeleton, Empty-state, Status pill

**2a. Component dùng chung** (thêm cuối `data.jsx`, expose `window.*`):
- `Skeleton({w, h, style})`: div bo góc `--r-sm`, nền `--surface3`, animation shimmer (thêm keyframes vào index.html).
- `EmptyState({icon, title, desc, actionLabel, onAction})`: căn giữa card, icon 32px màu `--text3`, title 14px 600, desc 13px `--text3`, nút ghost tùy chọn.

**2b. Quy tắc 3 trạng thái cho MỌI card/bảng dữ liệu:** global tương ứng `undefined` → Skeleton; mảng rỗng/`null` → EmptyState; có data → render. Cấm hiển thị bảng trống hoặc số `0` trơ trọi khi thực chất là "chưa có dữ liệu".

**2c. Copy EmptyState (dùng nguyên văn):**

| Chỗ | title | desc | action |
|---|---|---|---|
| Approvals (Monetization) | `Chưa có video chờ duyệt` | `Render xong một video rồi bấm "Gửi duyệt đăng" ở tab Sản xuất Video — video sẽ xuất hiện ở đây để bạn duyệt trước khi đăng.` | `Đi tới Sản xuất Video` → `setTab('produce')` |
| Offers | `Chưa cấu hình affiliate offer` | `Thêm offer (link + commission) để hệ thống tự chèn link kiếm tiền vào mô tả video.` | `Thêm offer` (mở form sẵn có) |
| Destinations | `Kênh chưa có đích đăng nào bật` | `Bật destination trong file cấu hình kênh để đăng đa nền tảng.` | — |
| Pipeline (Dashboard) | `Không có pipeline nào đang chạy` | `Bấm "Full Run Pipeline" ở tab Văn phòng hoặc chạy từng phase ở tab Kênh.` | — |
| Errors | `Không có lỗi nào 🎉` → dùng `Không có lỗi nào` + `<Icon name="check"/>` | `Hệ thống đang chạy sạch.` | — |
| Usage ledger | `Chưa có usage nào được ghi` | `Số liệu xuất hiện sau lần chạy pipeline đầu tiên đi qua CapabilityBus.` | — |

**2d. Status pill thay banner đỏ:** topbar hiện có pill "Hệ thống đang chạy"/"Mất kết nối máy chủ". Sửa thành 3 trạng thái dựa `window.__omniApiUp`: xanh `Đang chạy` · vàng `Đang kết nối lại…` (khi fetch fail < 3 lần liên tiếp) · đỏ `Mất kết nối` (≥ 3 lần). Đếm số lần fail liên tiếp trong data.jsx (biến module, không đổi logic interval). Pill KHÔNG nhấp nháy, chỉ đổi màu.

**Nghiệm thu PR-2:** tắt backend (đóng app, mở `http://127.0.0.1:8767` fail) → mọi tab hiện Skeleton→EmptyState chứ không trắng/vỡ; pill chuyển vàng rồi đỏ, không giật. Mở lại app → data về đủ.

### PR-3 · E-Q3 — Nhất quán ngôn ngữ

- Quy tắc: **label vận hành = tiếng Việt có dấu**; **thuật ngữ hệ thống giữ EN**: Pipeline, Render, Approve/Reject (nút được viết `Duyệt` / `Từ chối`), Capabilities, Budgets, Usage, Offer, Destination, Provider, Credential, Readiness.
- Sweep 13 tab + mọi toast label trong `_run(...)` + tooltip. Câu trộn kiểu "Real-time job status" → "Trạng thái job real-time".
- Glossary bắt buộc: `channel=Kênh · script=Kịch bản · schedule=Lịch đăng · cost=Chi phí · revenue=Doanh thu · views=Lượt xem · subscriber=Sub · error=Lỗi · waiting approval=Chờ duyệt · published=Đã đăng · failed=Thất bại · draft=Nháp`.

**Nghiệm thu:** duyệt từng tab, không còn card nào có 2 ngôn ngữ lẫn trong cùng 1 câu.

### PR-4 · E8 + E12 — Kill-switch thật + UX nền

- **E8:** `KillSwitchPill` (tìm trong index.html/pages.jsx) hiện chỉ đọc `/api/system/state`. Thêm click → modal xác nhận (`Tạm dừng toàn hệ thống? Mọi job mới sẽ không chạy.`) → `_run('Tạm dừng hệ thống', _post('/api/system/pause'))`; khi đang paused → nút `Chạy lại` → `/api/system/resume`.
- **E12:** (a) thay mọi `alert(`/`confirm(` trong app/*.jsx bằng toast (`_run`) hoặc modal component mới `ConfirmModal({title, desc, onOk})`; (b) giữ tab khi F5: đọc/ghi `location.hash` (`#tab=monetization`) trong state `tab` của App (index.html ~1627) — KHÔNG thêm react-router (không vendored lib mới); (c) breakpoint: dưới 1280px ẩn right-panel, dưới 1000px sidebar thu thành icon-only (CSS media query, đã có class sidebar).

**Nghiệm thu:** bấm pause → `/api/system/state` trả paused, pill đổi trạng thái, resume lại được · F5 giữ nguyên tab · kéo hẹp cửa sổ không vỡ layout · `grep -rn "alert(\|confirm(" app/` = 0.

### PR-5 · E6 — Approval Queue hoàn chỉnh (màn hình kiếm tiền quan trọng nhất)

Hiện Approvals nằm trong tab Monetization (pages.jsx ~857-965) dạng list chữ. Nâng thành:
- Mỗi approval = card ngang: **thumbnail** (từ `raw.thumbnail_paths[0]` — hiển thị qua `/media/` path nếu có, lỗi thì placeholder `<Icon name="film"/>`), title, kênh + platform badge (`youtube` đỏ / `tiktok` đen + chữ `dry-run` nếu `raw.dry_run`), thời gian chờ (`requested_at` → "x phút trước"), 200 ký tự đầu của `summary`.
- Nút **`Duyệt`** mở modal: dropdown Privacy (`unlisted` mặc định · `private` · `public`), checkbox `Force (bỏ qua cảnh báo compliance)` → gọi `_run('Duyệt & đăng', _post('/api/approvals/'+id+'/approve', {privacy_status, force, operator:'dashboard'}))`.
- Nút **`Từ chối`** → modal nhập lý do → `_post(.../reject, {note})`.
- Sau approve: đọc response — nếu `approval.raw.youtube_video_id` có → toast kèm link `https://youtu.be/<id>` (mở tab ngoài); nếu `approval.raw.publish_error` → hiện box đỏ lỗi NGAY trên card (đây là phần quan trọng: lỗi phải nhìn thấy được, không nuốt).
- Thêm badge đếm số approval đang chờ lên item `Monetization` ở sidebar (giống badge số có sẵn của các tab khác).

**Nghiệm thu:** tạo approval thật bằng nút "Gửi duyệt đăng" (tab Sản xuất Video) → card hiện đủ thumbnail/title/badge → Duyệt với `unlisted` → thấy link YouTube hoặc lỗi rõ ràng trên card.

### PR-6 · E1 — Providers & Credentials Manager (tab mới `providers`)

Tab sidebar mới `Providers` (icon `plug`), đặt trong nhóm HỆ THỐNG trên `Monetization`.

- **Nguồn dữ liệu:** `OMNI_CAPABILITIES` (mỗi capability có `kind, provider_id, model_id, runtime, cost_per_unit, metadata`), `OMNI_CREDENTIALS`, `OMNI_USAGE`, `OMNI_PROVIDER_HEALTH`.
- **Layout:** group theo `kind` (text / image / video / tts / music / platform) → mỗi provider 1 card: tên, runtime badge (`local`/`remote`/`browser`), model list, trạng thái credential (`Đã cấu hình` xanh nếu có credential provider đó trong OMNI_CREDENTIALS, ngược lại `Chưa có key` vàng).
- **Form động (PHẦN QUAN TRỌNG):** đọc `metadata.config_schema` của capability — object dạng `{field_name: {type, label?, provider?}}`. Render input theo `type`: `api_key`/`secret` → password input; `base_url`/`string` → text; `oauth` → chỉ hiện hướng dẫn `Chạy scripts/youtube_authorize.py --channel <id>` (KHÔNG làm OAuth trong UI). Nếu `config_schema` rỗng → 1 ô `API key` mặc định. Submit → `_run('Lưu credential', _post('/api/credentials', {provider: provider_id, name: field_name, secret: value}))` — đọc handler `POST /api/credentials` trong server.py để khớp đúng tên field body TRƯỚC khi code, cấm đoán.
- **Nút `Test kết nối`** → `_run('Test '+provider_id, _post('/api/capabilities/'+kind+'/'+provider_id+'/health'))` → hiện kết quả trên card (ok xanh / lỗi đỏ kèm message). KHÔNG tự chế logic test.
- **Usage mini-table** dưới mỗi card trả phí: lọc `OMNI_USAGE` theo provider (cost, số lần). 
- Sau khi lưu credential, secret KHÔNG BAO GIỜ hiển thị lại (API vốn không trả secret) — hiện `••••` + ngày tạo.

**Nghiệm thu:** thêm 1 key giả → card chuyển `Đã cấu hình`, GET /api/credentials thấy record (không lộ secret) · Test kết nối 1 provider local (kokoro) trả ok · reload app giữ nguyên trạng thái.

### PR-7 · E9 — Preview media trong Scripts/Sản xuất

- File media đã được serve tại mount `/media/` (xem `_media_rel` trong render_routes.py — video/thumb trả đường dẫn tương đối `/media/...`).
- Tab Sản xuất Video: khi `OMNI_RENDER_OUT.video` có → `<video controls>` inline (max-height 360) + thumbnail + title, nút `Gửi duyệt đăng` ngay dưới (gọi `/api/publish/{channel_id}` — nút đã có, đưa về cạnh preview).
- Tab Kịch bản (`Scripts`): với variant đang xem, nếu product dir có audio scene (`_assets/scene_XX.mp3`) — chỉ hiện player khi backend expose qua `/media/`; nếu path không nằm dưới `/media/` → ghi `BLOCKED: cần expose product assets qua /media` và bỏ qua (luật §0.2).

**Nghiệm thu:** sau 1 render xong, xem được video ngay trong tab Sản xuất không cần mở file explorer.

### PR-8 · E10 + E5 — Jobs & Pipelines có retry từng mục

- Panel mới trong tab Hạ tầng (hoặc section trên tab Pipeline nếu có sẵn khu jobs): bảng jobs từ `GET /jobengine/api/v1/jobs` (đọc `jobengine/api.py` để biết route + field chính xác): cột id ngắn, type, resource_class, status badge (`queued` xám / `running` xanh dương pulse / `success` xanh / `failed` đỏ), thời gian, error (tooltip).
- Hàng `failed` có nút `Chạy lại` → POST endpoint retry của jobengine API (đọc file để lấy route; nếu không có route retry → `BLOCKED: cần endpoint retry` và bỏ qua).
- Live update qua SSE có sẵn (`OmniConnectJobEvents` đã nghe `/jobengine/api/v1/events/stream`) — chỉ cần render lại từ `OMNI_JOB_EVENTS`.
- Section Pipeline Executions: bảng từ `GET /api/pipelines/executions` + nút trigger `POST /api/pipelines/run` (dropdown pipeline id nếu endpoint list có).

**Nghiệm thu:** chạy 1 render → job hiện `running` realtime không cần F5 → nếu fail bấm `Chạy lại` job đó chạy tiếp từ checkpoint.

### PR-9 · E2 + E7 — Monetization CRUD + Analytics

- **E2:** form thêm/sửa Offer (name, network, url, commission, niche, active toggle) → `POST /api/monetization/offers`; bảng conversions/clicks nếu endpoint có (đọc server.py, thiếu → BLOCKED note); hiển thị link tracking mẫu `/r/{placement_id}` với nút copy.
- **E7:** tab hoặc section Analytics: bảng metrics từ `GET /api/platforms/metrics` (per video: views/likes/revenue theo platform) + card "Quyết định Strategist gần nhất" nếu có endpoint (không có → BLOCKED note). Chart: dùng SVG tự vẽ bar/line đơn giản (KHÔNG thêm chart lib).

### PR-10 · E-Q5 — Chốt bản sắc thẩm mỹ (làm cuối)

Đề xuất mặc định (đã cân nhắc): **(a) clean-SaaS toàn app**; office_app pixel-art giữ nguyên trong tab Văn phòng như "màn hình giám sát" — đóng khung card có header riêng `Văn phòng Agent` để nhìn có chủ đích thay vì lạc tông. Nếu người vận hành muốn hướng (b) pixel-art toàn app → chờ xác nhận, KHÔNG tự làm.

### Epic H (E-Q4 · Vite migration) — KHÔNG nằm trong loạt PR này
Chỉ bắt đầu khi PR-1 → PR-9 đã merge và người vận hành duyệt. Sẽ có plan riêng.

---

## 4. GIAO THỨC VERIFY CHUNG (làm sau MỖI PR)

1. `grep -c "Ã\|áº\|Ä'" app/*.jsx` → 0 mọi file.
2. Đóng app cũ hoàn toàn (không còn cửa sổ), mở lại `OmniCast.lnk`.
3. Mở Chrome `http://127.0.0.1:8767` → DevTools Console: **0 lỗi đỏ**, không request 404.
4. Bấm qua đủ 13 tab. Tab thay đổi trong PR: chụp màn hình đính kèm PR.
5. Không sửa file nào ngoài `api/webui/` (`git status` hoặc so mtime).
6. Ghi 1 dòng kết quả vào `IMPLEMENTATION_STATUS.md` mục 2 (quy tắc CLAUDE.md).
