# PLAN UI v3 — Full-Control Cockpit (bản cho agent UI thực thi)

> **Mục tiêu (người vận hành yêu cầu):** đưa **TẤT CẢ chức năng của dự án** vào UI và cho người dùng **kiểm soát video đầu ra mạnh ngang các repo `_refs`** (MoneyPrinterTurbo, Pixelle-Video, voice-pro, VideoToolsPro). UI v2 hiện tại chạy được nhưng **quá thưa** (mỗi trang vài nút, biển trắng) và **chưa lộ phần lớn API**. v3 = làm dày + phủ hết endpoint, KHÔNG đập lại nền.
>
> **Tiếp nối `SPEC_UI_v2.md`** (giữ nguyên stack/tokens/shell/ErrorBoundary/no-store đã có). Đây là lớp bổ sung tính năng + mật độ, không phải viết lại.
> Người thực thi: agent UI. Đọc §0 trước. Không hiểu chỗ nào → mở endpoint thật trong Chrome (`http://127.0.0.1:8767/api/...`) hoặc đọc handler Python, KHÔNG đoán field.

---

## 0. LUẬT CỨNG (kế thừa SPEC_UI_v2 §0 + bổ sung)

1. **Chỉ sửa `implementation/frontend_v2/`** (Vite+React19+TS+Tailwind4). KHÔNG sửa `.py` — **mọi endpoint cần đã tồn tại** (danh mục §2). Thiếu field/endpoint → ghi `BLOCKED: cần <X>` vào spec-report, bỏ qua phần đó, KHÔNG bịa/hardcode dữ liệu giả.
2. Build: `npm run build` (tsc + vite) phải **xanh** trước khi bàn giao. Bundle ra `../src/omnicast/api/webui_v2/`. Backend serve `/` (shell đã `no-store`; hashed asset immutable).
3. UTF-8; sau mỗi file `grep -c "Ã\|áº\|Ä'\|â€\|ðŸ" src/**` = 0. Icon = lucide-react (KHÔNG emoji). Offline: KHÔNG CDN/Google Fonts.
4. TypeScript: type response API theo QUAN SÁT THẬT; field không chắc → `unknown`/optional.
5. **Giữ nguyên** `ErrorBoundary`, `StatusPill`, `ConfirmModal`, `HashRouter`, `getMediaUrl`, TanStack Query hooks (`useApi`/`apiPost`/`useInvalidate`), SSE (`connectSSE`). Chỉ THÊM.
6. Mỗi Phase (§6) = 1 PR + verify §7 + 1 dòng vào `IMPLEMENTATION_STATUS.md`.
7. **Sau khi ghi file lớn → verify tail file** (máy này đã có 4 sự cố ghi cụt: App.tsx/client.ts/pages.jsx). Mở app thật kiểm mỗi PR.

---

## 1. NGUYÊN TẮC MẬT ĐỘ (học từ `_refs` — bắt buộc áp dụng)

Vì sao v2 thua `_refs`: v2 dàn 1-2 card giữa biển trắng; `_refs` **nhồi control + dữ liệu** kín màn.

1. **Bố cục 3 cột cho màn sản xuất** (Pixelle-Video `resources/webui.png`): trái = input/params, giữa = preview + timeline/scene, phải = log/asset/history. Không để cột nào trống.
2. **Mọi tham số backend nhận → 1 control trên UI** (MoneyPrinterTurbo: gom hết param 1 trang, dùng expander/section). Không giấu tính năng sau CLI.
3. **Bảng dày thay card thưa**: list dài → `<Table>` có filter/sort/badge trạng thái + **action inline mỗi hàng** (retry/cancel/mở/xoá), không mỗi item 1 card to.
4. **Live**: dùng SSE + `refetchInterval` để số liệu/log/tiến độ tự cập nhật, không cần F5.
5. **Không nuốt lỗi**: mọi lỗi API/job hiện rõ trong UI (đã có nguyên tắc này ở v2, mở rộng ra mọi màn).
6. **Trạng thái 3 mức** mọi bảng/panel: loading (Skeleton) · empty (EmptyState có CTA) · data.

---

## 2. HỢP ĐỒNG DỮ LIỆU — TOÀN BỘ ENDPOINT → MÀN HÌNH

> ~90 endpoint (server.py + render_routes.py). Bảng dưới map endpoint → nơi tiêu thụ. **In đậm = v2 CHƯA dùng** (gap phải lấp).

### 2.1 Sản xuất / video-output control (Studio) — TRỌNG TÂM
| Endpoint | Method | Dùng ở | Ghi chú |
|---|---|---|---|
| `/api/render/{channel_id}` | POST | Studio — panel render | **Query params điều khiển video** (xem §3.1): `script, beat_words, force, shorts, style, voice, voice_rate, voice_pitch, music, music_volume, music_mood`. Trả background job. |
| `/api/render/status` · `/api/render/latest` | GET | Studio | tiến độ + video/thumb/title mới nhất |
| `/api/run/{channel_id}` | POST | Studio — nút "Full Run" | chạy cả pipeline 1 kênh |
| `/api/run/{channel_id}/script` | POST | Studio — bước Script | chỉ sinh script |
| `/api/run/{channel_id}/images` | POST | Studio — bước Ảnh | chỉ sinh ảnh |
| `/api/run/{channel_id}/cancel` | POST | Studio | **huỷ job đang chạy** (v2 chưa có nút) |
| `/api/run/{channel_id}/log` | GET | Studio — cột phải | **log stream/tail** |
| `/api/scripts/{channel_id}` | GET | Studio/Thư viện | list script + variants + score + compliance |
| `/api/topics/{channel_id}` | GET | Studio — chọn chủ đề | **danh sách topic đã discover** |
| `/api/topics/{channel_id}/{topic_id}/{action}` | POST | Studio | **approve/reject/pick topic** |
| `/api/discovery/{channel_id}` | GET | Studio | brief discovery |
| `/api/dedup/check` | GET | Studio | **cảnh báo trùng topic trước khi chạy** |
| `/api/product/meta` · `/api/products` | GET | Studio/Thư viện | **QC manifest per-video** (duration/fps/audio/qa/voice/cost) |
| `/api/products/rebuild-meta` | POST | Thư viện | backfill manifest |
| `/api/voices` · `/api/voice/preview` · `/api/channel/{id}/voice` | GET/POST | Studio + Kênh | **539 giọng + nghe thử + lưu** (đã có trang `/voices` cũ — port vào panel) |
| `/api/music/harvest/{channel_id}` | POST | Studio | **tải nhạc nền cho kênh** |

### 2.2 Kênh & Niche
`/api/channels` · `/api/channels/overview` · `/api/channels/{id}` · `/api/channels/{id}/detail` · **`PUT /api/channels/{id}`** (sửa full config) · `POST /api/channels` · **`DELETE /api/channels/{id}`** · `/api/channels/refresh-stats` · `/api/niches` · **`/api/discover-niches` (POST)** · `/api/vault/create-channel/{niche_id}` · `/api/vault/archive/{niche_id}` · `/api/competitor-intel/{channel_id}` (POST học đối thủ) · `/api/competitor-intel/{niche}` (GET).

### 2.3 Duyệt & Đăng / Đa nền tảng
`/api/approvals` · `/api/approvals/{id}/{decision}` · `/api/publish/{channel_id}` · **`/api/platforms`** · **`/api/platforms/metrics` (GET+POST)** · **`/api/destinations`** · `/api/upload/status/{id}` · `/api/upload/{id}`.

### 2.4 Hệ thống (System — đã có nhiều sub-tab, bổ sung)
Providers: `/api/capabilities` · `/api/credentials` (GET+POST) · `/api/capabilities/{kind}/{provider_id}/health`. Policy: `/api/policy` · `/api/policy/fetch` · `/api/policy/rules/{id}/{action}`. Jobs: `/jobengine/api/v1/jobs` + retry + SSE. Budget: `/api/budgets`(GET+POST) · `/api/budget` · `/api/usage` · `/api/credits`. Vault/Infra: `/api/vault` · `/api/vault/save-all` · `/api/vault/health-check` · `/api/infra`. **Auto-pilot: `/api/auto/status` · `/api/auto/run`** (v2 CHƯA có). Scheduler: `/api/scheduler` · `/api/scheduler/toggle` · `/api/scheduler/channel/{id}`. Kill-switch: `/api/system/state|pause|resume`. Errors: `/api/errors` · `/api/errors/clear`. Pipelines: `/api/pipelines/executions` · `/api/pipelines/run`.

### 2.5 Kiếm tiền
`/api/monetization/offers` (GET+POST) · `/api/monetization/readiness` · `/api/monetization/conversions` (POST) · `/r/{placement_id}` (link tracking).

---

## 3. MÀN HÌNH — SPEC DÀY TỪNG CÁI

### 3.1 STUDIO — Trung tâm kiểm soát video (LÀM KỸ NHẤT, 3 cột)

Layout 3 cột (Pixelle webui.png). Trên cùng: chọn **Kênh** (dropdown) + **chủ đề** (từ `/api/topics`, hoặc "mới nhất").

**CỘT TRÁI — Bảng điều khiển sản xuất (nhồi hết param, kiểu MoneyPrinterTurbo, dùng section gập):**
- **Giọng đọc** (section): nghe-thử + chọn từ `/api/voices` (539 giọng, filter provider/lang/gender/accent/use-case như trang `/voices` cũ — port thành component `<VoicePicker>`), + `voice_rate` (slider -50%..+50%), + `voice_pitch` (slider). Nút ▶ preview gọi `/api/voice/preview`. Lưu mặc định kênh: `/api/channel/{id}/voice`.
- **Hình ảnh** (section): image model (Imagen4 / Nano Banana / Nano Banana Pro — field `flow_image_model` trong channel config), `style` override.
- **Nhạc nền** (section): toggle `music`, `music_mood` (dropdown 8 mood), `music_volume` (slider 0..1), nút "Tải nhạc" `/api/music/harvest/{id}`.
- **Nhịp & định dạng** (section): `beat_words` (slider 8..30), toggle `shorts` (9:16), toggle `force` (bỏ qua compliance-block).
- **Nút hành động** (rõ ràng, có trạng thái disabled khi đang chạy): `Sinh Script` (`/api/run/{id}/script`) → `Sinh Ảnh` (`/api/run/{id}/images`) → `Render Video` (`/api/render/{id}` kèm mọi param trên) · `Full Run` (`/api/run/{id}`) · `Huỷ` (`/api/run/{id}/cancel`, chỉ hiện khi đang chạy).
- Trước khi render: gọi `/api/dedup/check` → nếu trùng, cảnh báo vàng.

**CỘT GIỮA — Preview + Timeline scene:**
- Player video mới nhất (`/api/render/latest` → `getMediaUrl`), thumbnail, title.
- **Timeline/scene list**: đọc product `_status/status.json` (qua `/api/product/meta` hoặc `/api/run/{id}/log`) → hiện từng scene (idx, heading, trạng thái). Nếu asset scene expose qua `/media/` → cho play mp3/xem ảnh từng scene (nếu path không dưới `/media` → `BLOCKED: expose product assets`). Đây là "kiểm soát đầu ra tới từng scene" như voice-pro/VideoToolsPro.
- **QC badge** từ `/api/product/meta`: duration, fps, res, audio dB/48kHz/stereo, qa pass/fail per-check, voice_provider_used, cost. Đỏ nếu fail gate.

**CỘT PHẢI — Log + tiến độ (live):**
- Tiến độ job hiện tại (`/api/render/status` + SSE) — stage đang chạy, %.
- **Log tail** (`/api/run/{id}/log`, `refetchInterval` 2s hoặc SSE) — cuộn, mono, highlight lỗi đỏ.
- Lịch sử render gần đây (`/api/products?channel_id=` → bảng: slug, score, duration, qa, cost, voice; click mở meta).

### 3.2 DUYỆT & ĐĂNG (mở rộng đa nền tảng)
- Giữ card approval hiện có (thumbnail/privacy unlisted/force/publish_error/link YouTube).
- **THÊM**: badge platform (youtube/tiktok, `dry-run` nếu có) từ `raw.platform_id`. Bảng **Destinations** (`/api/destinations`) per kênh: platform × account × format_variant × enabled — toggle bật/tắt đích. Bảng **Platforms metrics** (`/api/platforms/metrics`): views/likes/revenue theo platform+video. Badge đếm approvals chờ trên sidebar.

### 3.3 HỆ THỐNG — thêm 2 sub-tab còn thiếu
- **Auto-pilot** (MỚI): `/api/auto/status` (đang bật/tắt, lịch, quyết định strategist gần nhất) + nút chạy `/api/auto/run` (ConfirmModal) + Scheduler (`/api/scheduler` list, `/api/scheduler/toggle`, `/api/scheduler/channel/{id}` bật/tắt từng kênh, hiện prime-time).
- **Platforms/Destinations** (MỚI, hoặc gộp vào Duyệt&Đăng): `/api/platforms` list + trạng thái auth per platform.
- Giữ Providers/Policy/Jobs/Budgets/Vault/Infra đã có; bổ sung: Pipeline Executions (`/api/pipelines/executions` + `/api/pipelines/run`), Errors clear (`/api/errors/clear`).

### 3.4 KÊNH & NICHE (làm dày)
- Bảng kênh (không phải 1 card): tên, niche, market, trạng thái, voice, #video, ROI — action inline: Sửa (`PUT`, form full config), Xoá (`DELETE`, confirm), Refresh-stats, Học đối thủ (`/api/competitor-intel/{id}`).
- **Niche discovery**: nút `/api/discover-niches` → bảng `/api/niches` → tạo kênh `/api/vault/create-channel/{niche_id}` / archive.
- Form sửa kênh = full channel config (voice_profile/fallback, style, brand, competitor_handles, target_duration, flow_image_model...).

### 3.5 THƯ VIỆN
- Bảng products (`/api/products`) dày: video, script (variants+score+compliance từ `/api/scripts/{id}`), QC meta, nghe voice, xem thumb. Nút rebuild-meta.

### 3.6 TỔNG QUAN (Dashboard) — thêm widget
Giữ 4 KPI + pipeline + activity + errors. THÊM: mini chart revenue/ROI (SVG tự vẽ từ `/api/platforms/metrics`), queue jobs (`/jobengine/api/v1/jobs`), health per-kênh (`/api/channels/overview`), quick-actions (Full Run / Discover / Pause).

---

## 4. COMPONENT DÙNG CHUNG cần thêm (`src/components/`)
`<VoicePicker>` (port trang `/voices` cũ) · `<RenderControlPanel>` (§3.1 trái) · `<SceneTimeline>` · `<LogTail>` (SSE/poll) · `<QCBadge>` (từ product meta) · `<DataTable>` (filter/sort/inline-action, dùng lại khắp nơi) · `<MiniChart>` (SVG bar/line) · `<SectionAccordion>` (section gập cho param).

## 5. NGÔN NGỮ
VN có dấu cho label vận hành; giữ EN thuật ngữ (Render, Pipeline, Provider, Capability, Budget, Offer, Destination). Không trộn 2 ngôn ngữ trong 1 câu.

---

## 6. PHASES (mỗi Phase 1 PR)
| Phase | Nội dung | Verify chính |
|---|---|---|
| V3-P1 | `<DataTable>` + `<SectionAccordion>` + `<LogTail>` + `<QCBadge>` + `<MiniChart>` (component nền) | build xanh; render demo |
| V3-P2 | **Studio 3 cột + RenderControlPanel đầy đủ param + VoicePicker + dedup** | chạy render thật từ UI với param tuỳ chỉnh; log live; huỷ được |
| V3-P3 | **Studio giữa: SceneTimeline + QC panel + player + lịch sử** | xem meta+scene 1 video đã render |
| V3-P4 | Duyệt&Đăng đa nền tảng + Destinations + Platforms metrics | toggle destination; bảng metrics |
| V3-P5 | System: Auto-pilot + Scheduler + Pipeline Executions | bật/tắt auto; trigger pipeline |
| V3-P6 | Kênh&Niche dày (bảng + form sửa full + discovery) | sửa 1 kênh; discover niche |
| V3-P7 | Dashboard widget + Thư viện dày | chart hiện; bảng products |
| V3-P8 | Polish mật độ toàn app (cắt whitespace, responsive, live) | không màn nào thưa/trắng |

## 7. VERIFY CHUNG (sau MỖI Phase)
1. `npm run build` xanh; `grep -c "Ã\|áº\|Ä'" src/**` = 0.
2. Mở `http://127.0.0.1:8767/?cb=<ts>` (cache-bust) trong Chrome — DevTools Console 0 lỗi đỏ, 0 request 404.
3. Bấm qua 7 mục + sub-tab; chụp màn Phase đó.
4. Đối chiếu mật độ với `_refs/Pixelle-Video/resources/webui.png` + MoneyPrinterTurbo — không còn biển trắng.
5. Ghi 1 dòng `IMPLEMENTATION_STATUS.md`.

## 8. ĐÃ LÀM (nền v2 — đừng đụng lại)
Stack/tokens/dark/shell/StatusPill/KillSwitch/ConfirmModal/HashRouter/ErrorBoundary/no-store; pages Dashboard/Studio(cơ bản)/Approvals(cơ bản)/Library/Channels(1 card)/Monetization(offers+readiness)/System(Providers/Policy/Jobs/Budgets/Vault/Infra). Bug build `Badge purple` + font 500/600 + blank(no-store) đã fix — xem `SPEC_UI_v2.md` §11.1.

## 9. GROUNDING _refs (đã đọc trực tiếp phiên này)
- **MoneyPrinterTurbo/webui/Main.py**: mẫu "1 trang nhồi hết param" (LLM/script/source/aspect/clip-dur/transition/concurrent/voice gender+name+rate/BGM none-random-custom+volume/subtitle font-size-color-stroke-position-bg/log/keys). → áp cho §3.1 cột trái.
- **Pixelle-Video** (`README_EN` + `resources/webui.png`): 3 cột, agent/chat + workflow template có preview + script split modes. → áp layout §3.1.
- **hyperframes/DESIGN.md**: color/typo/spacing/radius/shadow/cards/buttons/badges — đã vào tokens v2.
- **VideoToolsPro / voice-pro / pyvideotrans**: retry per-item, voice trial-listen, dub per-segment. → áp SceneTimeline + LogTail retry + VoicePicker.
