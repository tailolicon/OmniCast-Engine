# OmniCast Super-App — Kế hoạch tái cấu trúc (v5 — VIẾT LẠI THEO CODE THẬT)

> ⚠️ Bản v1–v4 trước dựa vào doc cũ (`IMPLEMENTATION_DELTA.md`, đã xoá) nên **đánh giá sai trạng thái** — coi nhiều thứ là "chưa build" trong khi thực tế đã có. Bản này viết lại sau khi **đọc trực tiếp code** (`content_flow.py`, `media/orchestrator.py`, `upload/`, `analytics/`, `api/server.py`, `frontend/App.jsx`). Quyết định đã chốt: tái cấu trúc mạnh · API-first (web cockpit chính, remote/desktop nối sau) · **Milestone #1 = đa nền tảng đăng** · chạy lai server + điều khiển từ xa · giữ SQLite SSOT.

---

## 1. TRẠNG THÁI THỰC TẾ (đọc từ code, không từ doc)

OmniCast hôm nay **đã là một cockpit desktop tự động hoá YouTube gần hoàn chỉnh**, không phải chỉnh tay file/script.

| Tầng | Đã có (module thật) | Mức độ |
|---|---|---|
| **Cockpit/UI** | `omnicast_desktop.py` (app desktop Edge WebView2, tự bật FastAPI) · `frontend/App.jsx` (2002 dòng, 8 tab: Dashboard/Pipeline/Channels/Scripts/Infrastructure/Niche Discovery/Niche Vault/Budget) · webui thứ 2 trong `api/webui/` · ~50 endpoint API | ✅ Chạy |
| **Discovery** | Flow A niche (`niche_flow.py`,`discovery/`) + Flow B topic (`content_flow.py` phase 1, `DiscoveryOrchestrator`,`ChannelArchitect`); dynamic seeds, outlier detection, **dedup string+semantic LLM**, YouTube key rotation | ✅ |
| **Agents** | Debate đầy đủ: Writer · Critic(100đ) · **Thinking · Compliance · Evolution · VisualDirector · Tournament** · ChannelArchitect; BudgetManager; policy rules từ vault chèn vào prompt | ✅ (vượt doc cũ) |
| **Media** | `MediaPipelineOrchestrator`: TTS neural đa nguồn (kokoro/edge/xtts/f5 + VoiceRouter) → image (gemini/flow/local-sd) → music → subtitle → thumbnail → render → fingerprint; state machine | ✅ |
| **Upload** | `UploadPipelineOrchestrator`: compliance gate → **scheduler prime-time + rate limit** → YouTube Data API + OAuth → **thumbnail A/B registration**; channel_guard; DLQ | ✅ **YouTube-only** |
| **Analytics (closed-loop)** | `youtube_stats` (ước tính revenue) → `health` (CTR/AVD/views/subs/revenue có trọng số) → **`roi` (per video/niche/channel, tìm niche ROI âm)** → `diagnostic`/`retention`/`video_intel`/`competitor_intel`/`corrector`/`quality_scorer`/`kb_decay` → **`StrategistAgent` quyết định tuần: pause/boost/reallocate/canary** (auto_execute + confidence) | ✅ engine có |
| **Hạ tầng** | PostgreSQL+Alembic · **RabbitMQ (aio_pika, exchanges + DLQ)** · **Redis (rate limiter Token-Bucket + circuit breaker)** · vault SQLite SSOT (WAL) · **pipeline runner Kestra-lite YAML + APScheduler** · Telegram alerts · policy watcher | ✅ |

**Kết luận:** phần lõi sản xuất → đăng → phân tích → tối ưu **đã khép vòng cho 1 nền tảng (YouTube)**. Việc "super-app" KHÔNG phải xây từ đầu, mà là **mở rộng chiều ngang (đa nền tảng) + hợp nhất & quản lý hoá các mảnh đã có**.

---

## 2. Khoảng trống THẬT cho super-app (gap chính xác)

| # | Gap | Hiện trạng | Mức |
|---|---|---|---|
| G1 | **Đa nền tảng đăng** | `upload/` + scheduler + analytics **khoá cứng YouTube**; không có TikTok/FB/IG/Shorts | 🔴 Lớn — **M1** |
| G2 | **Hợp nhất provider/capability + quản lý key qua UI** | Có `llm/registry` + `media/providers/registry` **tách rời**; key trong `.env`; chỉ YouTube có rotation | 🟠 Một phần |
| G3 | **Runtime router local-first** | Có mảnh (ollama endpoint, TTS local, flow browser) nhưng **không có router hợp nhất + fallback + resource-aware** | 🟠 Một phần |
| G4 | **Resiliency xuyên phase** | `content_flow` chạy 4 phase **tuần tự in-process**; crash giữa chừng → chạy lại phase; chưa checkpoint/idempotency xuyên phase (RabbitMQ + Kestra-lite có nhưng content pipeline chưa dùng job/checkpoint) | 🔴 → **PR1 jobengine đã bắt đầu** |
| G5 | **Cổng duyệt người (HITL)** | Upload để `private`/dry-run; **không có trạng thái chờ-duyệt** trước khi public | 🟠 Cao giá trị |
| G6 | **Affiliate / monetize nội dung** | `roi` chỉ tính theo revenue kiểu AdSense; **không có offer registry / chèn link affiliate / tracking** | 🟠 |
| G7 | **Concurrency theo tài nguyên** | Nhiều render song song không giới hạn slot GPU/CPU | 🟠 |

> Lưu ý quan trọng: **đừng xây lại cái đã có** — Redis circuit-breaker + rate-limiter, RabbitMQ+DLQ, ROI+Strategist closed-loop, thumbnail A/B, scheduler prime-time **đã tồn tại**. Super-app = *generalize + unify + extend*, không rebuild.

---

## 3. Nguyên tắc kiến trúc (giữ nguyên)
Capability-based (xin năng lực, không gọi provider) · Open/Closed (thêm provider/platform/model/key = manifest, không sửa lõi) · local↔remote parity · vault SQLite SSOT · API-first · compliance per-platform first-class · fail-safe + resume.

---

## 4. Kiến trúc đích — MAP vào module hiện có (extend, không rebuild)

### G1 · Platform Layer *(M1 — ưu tiên #1)*
Tổng quát hoá `upload/` (đang YouTube) thành interface **`IPlatform`**; YouTube hiện tại trở thành `platforms/youtube/` (chính là code `upload/youtube_api`+`oauth`+`scheduler`+`compliance` bê qua). Thêm `platforms/tiktok|facebook|instagram/`.
```python
class IPlatform(Protocol):
    id: str; format_spec: FormatSpec           # aspect/độ dài/codec/caption-rule
    async def authenticate(account) -> AuthState
    async def quota(account) -> QuotaInfo
    async def validate(video, meta) -> list[PolicyIssue]   # compliance per-platform
    async def publish(video, meta, account) -> PublishResult
    async def fetch_analytics(post_id, account) -> PostStats   # 2 chiều — feed vào analytics/ sẵn có
    async def fetch_comments(post_id, account) -> list[Comment]
```
- **Channel → destinations:** một kênh có nhiều đích (platform × account × format variant × lịch). Render *master* → xuất biến thể (YT 16:9 dài, TikTok/Shorts/Reels 9:16). `MediaPipelineOrchestrator` đã render được — chỉ thêm bước "xuất biến thể theo `format_spec`".
- **Analytics/Strategist tái dùng:** `youtube_stats`→ tổng quát thành `IPlatform.fetch_analytics`; `health`/`roi`/`StrategistAgent` vốn đã per-channel/niche → mở rộng khoá thêm `platform`. **Không viết lại closed-loop**, chỉ đa-nền-tảng-hoá nguồn số liệu.
- Giữ luật: upload qua API chính thức; nền tảng không có API hợp lệ → `manual/skip`, không browser-automation upload.

### G2 · Capability & Credential
- **Capability Registry:** gộp `llm/registry` + `media/providers/registry` dưới một registry theo capability (`text/image/video/tts/stt/translate/...`) + manifest. Hai registry hiện tại thành adapter mỏng (tương thích ngược).
- **Credential Vault:** tổng quát hoá `settings.youtube_key_pool` thành KeyPool chung (bảng `credentials` trong vault, Fernet at-rest, priority, cooldown). Quản lý qua UI (đang chỉ `.env`). Quota/usage/budget: tái dùng `services/budget.py` + `llm/cost.py` (chuyển budget in-memory → bền trong vault + thêm cấp **campaign/channel**).
- **Circuit breaker ĐÃ CÓ** (`cache/circuit_breaker.py`, Redis) — chỉ cần gắn vào Runtime Router + provider-level (hiện đang dùng cho Claude API).

### G3 · Runtime Router (local-first)
Router định tuyến mỗi capability sang `local|remote|browser` theo manifest + fallback chain + resource probe (GPU/VRAM). Bọc các adapter đã có: OpenAI-compat (ollama/groq/openai/deepseek), flow browser, TTS local, ComfyUI. Domain code chỉ xin capability.

### G4 · Job Engine + Checkpoint *(đang làm — PR1 xong)*
`content_flow` 4 phase tuần tự → bọc dưới **Job Engine** (đã có `jobengine/` PR1: schema jobs/steps/checkpoints/assets/worker_slots/events + idempotency util). Tái dùng **RabbitMQ + DLQ** sẵn có (đừng thêm Celery). Checkpoint sau mỗi phase → crash chỉ chạy lại phase lỗi (không tốn lại LLM/render). **Resource slot = QoS prefetch** trên queue `jobs.gpu/cpu/net` (chống OOM khi nhiều render). Per-step progress → SSE lên cockpit.

### G5 · HITL Gate
Thêm job state **`WAITING_FOR_APPROVAL`**: render xong → bắn Telegram/Dashboard kèm **A/B title + thumbnail** (thumbnail A/B đã có ở `upload/thumbnail` + `media/thumbnail`; thêm title variants) → người duyệt + lướt kiểm bản quyền → mới publish. **Bật/tắt theo destination** (`approval_required`) để kênh auto 24/7 vẫn chạy.

### G6 · Monetization (extend `analytics/roi`)
ROI engine đã có (revenue−cost). Thêm: **Offer/Affiliate registry** (network/link/niche/commission) → bước `monetize` chèn link+CTA vào description/pinned comment (short-url trackable) → click/conversion → nạp vào `revenue` của ROI sẵn có. Compliance: thêm rule **affiliate disclosure** per-platform. Closed-loop: doanh thu affiliate feed `StrategistAgent` (đã chọn niche theo ROI) để ưu tiên offer ra tiền.

### G7 · Cockpit (extend dashboard hiện có)
Thêm tab/panel vào dashboard sẵn có: **Destinations** (đa nền tảng), **Keys/Usage/Quota**, **Approvals (HITL)**, **Hàng đợi job trạng thái + retry-lỗi**, **Revenue/ROI** (mở rộng tab Budget). Realtime qua SSE. Remote control (mobile) dùng chung API + auth/RBAC.

---

## 5. Data model — deltas vào vault.db (bổ sung, không phá)
Đã có (PR1): `jobs, job_steps, checkpoints, assets, worker_slots, events`. Thêm theo milestone:
- `platforms, accounts, destinations, publish_targets, post_metrics` (G1)
- `providers, models, credentials, usage_ledger` (G2) · `budgets(scope=global|campaign|channel)` (extend budget)
- `approvals, ab_variants` (G5) · `offers, placements, clicks, conversions, revenue` (G6)
> Bảng cũ (`niches, health_logs, scripts, pipeline_executions`, …) giữ nguyên.

---

## 6. Milestones (re-anchored theo trạng thái thật)

- **M0 — Nền móng resiliency *(đang làm)*.** Job Engine + checkpoint/idempotency (bọc `content_flow`), IStorage + Asset Registry, resource slots, SSE. *Không đổi hành vi sản xuất.* (PR1 xong; còn PR2–PR8 theo `SPEC_M0_NenMong.md`.)
- **M1 — Đa nền tảng đăng *(ưu tiên #1)*.** `IPlatform` + tách YouTube ra `platforms/youtube/` + thêm nền tảng #2; channel→destinations; render biến thể 9:16; analytics đa-nền-tảng-hoá; cockpit tab Destinations. **+ HITL gate (G5)** vì gắn với publishing.
- **M2 — Hợp nhất Capability + Credential Vault.** Gộp registry; KeyPool + quota/budget bền (global/campaign/channel); gắn circuit-breaker sẵn có vào router; tab Keys/Usage.
- **M3 — Runtime Router local-first.** Router + fallback + resource probe; adapter local.
- **M4 — Monetization/ROI mở rộng (G6) + Webhooks + Remote control hoàn chỉnh.**
- **M5 — Tuỳ chọn:** desktop shell nâng cao, Postgres scale, marketplace plugin, bán OmniCast (license/affiliate).

---

## 7. Migration (strangler — `content_flow` luôn chạy)
1. Tầng mới dựng *cạnh* code cũ; `upload/` cũ vẫn chạy tới khi `platforms/youtube/` thay thế xong.
2. Mỗi milestone phải xanh: render 1 video + upload YouTube (dry_run) vẫn OK sau từng bước.
3. Schema chỉ *thêm* bảng; migrate `channels/{id}.json` → bảng channels/destinations bằng script một chiều, giữ JSON tới khi ổn.
4. Feature flag cho đường mới; verify bằng `pytest -x` + render thật.

## 8. KHÔNG xây lại (tái dùng nguyên trạng)
RabbitMQ+DLQ · Redis circuit-breaker + rate-limiter · `services/budget` + `llm/cost` · ROI + health + StrategistAgent closed-loop · thumbnail A/B · scheduler prime-time · agent debate (tournament/evolution) · dashboard 8 tab · pipeline runner Kestra-lite + APScheduler · vault SQLite. → Super-app = generalize + unify + extend các thứ này, không viết lại.

## 9. Việc tiếp theo
1. Bạn duyệt bản v5 này (đã đúng trạng thái thật).
2. Chốt **nền tảng #2** cho M1 (cần xác minh API đăng video hợp lệ của TikTok/IG/FB).
3. Tiếp tục **PR2 (IStorage)** của M0, hoặc nhảy thẳng phác thảo `IPlatform` cho M1 — tuỳ bạn.

> Ghi chú: các doc khác ở repo root (`Plans.md`, `implementation_plan.md`, `omnicast_design_spec.md`, `PROJECT_CONTEXT.md`, `spec.md`, `DASHBOARD_API.md`...) có thể cũng đã lỗi thời như delta. Nếu muốn, mình rà & đối chiếu với code rồi đề xuất cập nhật/gộp — nhưng sẽ không xoá gì nếu bạn chưa duyệt.

---

## 10. WORK ORDER 2026-07-03 — đánh giá code-grounded + việc giao cho agent thực thi

> Kết quả phiên đánh giá 2026-07-03 (đọc code + chấm output thật, KHÔNG sửa code).
> Danh sách việc **đủ chi tiết để một agent khác cầm làm ngay**, kèm file/hàm/dòng cụ thể.
> Ưu tiên: **WO-4 (chất lượng output) ≥ WO-1 (publish wiring)** — output hiện tại CHƯA đạt chuẩn kiếm tiền dù pipeline chạy được.

### 10.1 Trạng thái thật (khác với bảng gap cũ ở STATUS)

| Hạng mục | Thực tế đọc từ code 2026-07-03 |
|---|---|
| HITL approve→publish credential thật | ✅ **ĐÃ CÓ** — `api/server.py::_publish_approved_video` (~dòng 1353): compliance gate → OAuth token check → `UploadPipelineOrchestrator` → ghi `published_videos`. OAuth token kênh `beat_glp1_nausea` đã tạo (2026-07-03, `output/_yt_tokens/`). |
| GPU/CPU slots | ✅ **ĐÃ ENFORCE in-process** — `jobengine/slots.py::SlotManager` (GPU=1/CPU=4/NET=8) + `jobengine/engine.py:58` `async with self.slots.acquire(...)`. Thiếu: config qua env. |
| MultiPlatformPublisher | ❌ **KHÔNG có caller production nào** — `platforms/publisher.py` hoàn chỉnh nhưng zero call site ngoài test. Đây là gap M1 thật. |
| WebUI publish | ❌ Nút "Đăng YouTube" (`api/webui/app/data.jsx:547`) gọi thẳng `POST /api/upload/{id}` — **bypass cổng duyệt HITL** và bypass MultiPlatformPublisher. |
| LLM call qua CapabilityBus | 🟠 Chỉ `pipeline/steps.py::_llm_client` đi qua bus. Còn ~10 chỗ ad-hoc `LLMClient(provider=...)`: `api/server.py` dòng 1909, 1910, 2150, 2878, 2879, 3367, 3673–3675, 3788; `analytics/competitor_intel.py:223`. |
| RuntimeRouter | 🟢 Đã live gián tiếp qua `CapabilityBus.resolve_with_fallback()` cho image/video (B4-C1). Wire nốt các LLM site (trên) là xong M3 cho text. |

### 10.2 Đánh giá output thật (chuẩn "đủ tốt để kiếm tiền")

Mẫu: video render mới nhất `output/pipeline_renders/beat_glp1_nausea/20260616_221520.mp4` + script mới nhất `output/products/beat_glp1_nausea/20260702_1143_*/script.txt` (score 104).

| Tiêu chí | Kết quả | Đạt? |
|---|---|---|
| Hình ảnh | 1080p30 h264, phụ đề burn-in rõ | ✅ |
| Thumbnail | CTR-style tốt ("OZEMPIC STEALS MG", ảnh cảm xúc + red circle) | ✅ |
| Script structure | Hook mạnh, segment rõ, CTA/engagement, 1.847 từ (~12 min VO) | ✅ |
| **Audio** | **mono 24 kHz, mean −27.4 dB, max −8.2 dB** (chuẩn YT ≈ −14 LUFS stereo 48 kHz) | ❌ CHẶN |
| **Độ dài render** | **6:43 < 8:00 (ngưỡng mid-roll)** < 10 min target kênh | ❌ CHẶN |
| **Visual relevance** | B-roll lạc đề: stock footage *Adobe Premiere Pro* tại ~6:20 trong video sức khỏe GLP-1 | ❌ CHẶN |
| **Fact accuracy (YMYL)** | Citation/số liệu không kiểm chứng ("Journal of Clinical Endocrinology 300%", "72% deficient trong 6 tháng", "NIH 2024 review"); anecdote bịa ("Sarah, 42") không disclaimer; `_compliance.json` pass vì ComplianceChecker chỉ check keyword | ❌ CHẶN |
| Medical disclaimer | Không có trong script/description | ❌ |
| Dedup topic | 5 product runs (16/6→2/7) cùng 1 topic — dedup không chặn ở stage script | ⚠️ |
| Script 2026-07-02 (score 104) | `meta.json` stage="script" — **chưa render** | ⚠️ |

### 10.3 Việc cần làm (theo thứ tự)

**WO-4 — Chất lượng output (LÀM TRƯỚC, chặn kiếm tiền):**
1. *Audio mastering:* trong render path (`media/render_engine.py` / `media/ffmpeg.py` — chỗ mux audio cuối), thêm filter `loudnorm=I=-14:TP=-1.5:LRA=11`, resample 48 kHz, stereo, aac ≥192k. Mở rộng `media/output_audit.py` (ffprobe) check loudness/sample_rate/channels — fail job nếu lệch.
2. *Độ dài:* gate ở `media/orchestrator.py`: tổng VO < 1.500 từ hoặc render < 8:00 → fail sớm trước khi tốn render. (Expander VO đã có ở `api/server.py` phase-2 `_TARGET_VO` ~3788 — chỉ cần enforce phía media.)
3. *Visual relevance QA:* sau bước chọn stock/b-roll (`media/providers/stock_video.py` + `visual_director`), thêm gate chấm scene↔clip relevance (vision/flash LLM); reject clip chứa UI phần mềm/text không liên quan. Bug thật: frame ~6:20 của `20260616_221520.mp4` là Adobe Premiere Pro.
4. *Fact-check gate (YMYL):* bước mới sau Critic, trước compliance: LLM verify từng claim/citation trong script; **cấm citation không nguồn** (viết lại thành "studies suggest" hoặc xoá); bắt buộc medical disclaimer chuẩn vào outro + description. Wire vào `agents/orchestrator` (DebateOrchestrator) hoặc policy rule mới trong `vault.db::policy_rules`.
5. *Dedup:* check topic-slug vault trước khi phase-2 chạy lại topic đã có product (hiện `record_published` chỉ ghi khi upload nên script-stage lặp tự do — 5 runs cùng topic).

**WO-1 — Wire M1 publish (sau WO-4):**
1. Tạo `platforms/service.py`: `build_platform_registry()` (YouTubePlatform bọc `YouTubeUploader(OAuth2Manager(settings.youtube_token_dir))` + `ComplianceChecker` + `PlatformAnalyticsStore`; TikTokPlatform dry-run) và `publish_channel(channel_id, video_path, metadata)`: `destinations_for_channel()` → export variant 9:16 bằng `media/variants.py::RenderVariantExporter` khi destination `format_variant`=`tiktok_9x16` → `MonetizationLinker.monetize_metadata()` (tự no-op khi chưa có offer) → `MultiPlatformPublisher.publish(require_approval=True)`.
2. `api/server.py`: thêm `POST /api/publish/{channel_id}` — submit qua JobEngine (`ResourceClass.NET`); outcome `WAITING_APPROVAL` → insert row `approvals` (tái dùng `_ensure_approvals_table`; schema đã có `destination_id`/`platform_id`).
3. Mở rộng `_publish_approved_video`: route theo `platform_id` của approval row — `youtube` giữ nguyên path hiện tại; `tiktok` → `TikTokPlatform.publish(dry_run=True)` + ghi `post_metrics`.
4. WebUI: `api/webui/app/data.jsx:547` đổi nút đăng → gọi `/api/publish/{id}` (vào hàng duyệt); nút Approve (`data.jsx:590`) gửi kèm `privacy_status:"unlisted"` (endpoint `decide_approval` đã nhận override này).

**WO-2 — CapabilityBus cho LLM (M2/M3):** tạo `capabilities/llm_factory.py::create_llm(default_provider, model=None)` (copy logic `pipeline/steps.py::_llm_client` dòng 62–81, fallback LLMClient trực tiếp khi bus không resolve) → thay 10 call site ở §10.1 → `pipeline/steps.py` delegate về factory.

**WO-3 — Slots config:** `jobengine/slots.py::SlotManager.__init__` đọc env `OMNICAST_SLOTS_GPU/CPU/NET` (default 1/4/8).

**WO-5 — E2E test qua app (sau WO-1..4):**
1. Chạy `implementation/OmniCast.bat` (desktop WebView2, FastAPI 127.0.0.1:8767).
2. Script 2026-07-02 score 104 đã sẵn → chạy phase render cho `beat_glp1_nausea` (JobEngine GPU slot).
3. `POST /api/publish/beat_glp1_nausea` → tab Monetization/Approvals hiện hàng chờ.
4. Approve với `privacy_status=unlisted` → verify: YouTube video id trả về, row `published_videos` trong vault, `post_metrics` bắt đầu có, TikTok outcome dry-run.
5. Kiểm output audit pass (loudness/duration/relevance gates mới). OAuth token đã sẵn; Google Cloud app đang "Testing" status (đủ upload unlisted bằng chính account đó). Quota upload ≈1.600 units/video.
6. Test xanh → cập nhật `IMPLEMENTATION_STATUS.md` trong cùng PR (quy tắc CLAUDE.md).

**Affiliate:** chưa có offer thật → giữ readiness WAIT, không cấu hình offer giả. Kiếm tiền giai đoạn đầu = AdSense/YPP ⇒ WO-4 là điều kiện tiên quyết.

### 10.4 KIỂM TRA LẠI 2026-07-03 (chiều) — sau khi agent thực thi wire WO: trạng thái + 3 BUG mới

Đã chạy app thật (OmniCast.lnk → OmniCast.bat → pythonw omnicast_desktop.py) và rà code mới (files sửa 2026-07-03 ~16:09).

**WO đã làm xong (verify từ code):**
- ✅ WO-1: `platforms/service.py` (build_platform_registry + publish_approval_row + MonetizationLinker + TikTok dry-run mặc định cho non-YouTube) · `POST /api/publish/{channel_id}` tạo approval per-destination · WebUI nút "Gửi duyệt đăng" (`data.jsx:547`) thay upload thẳng · `_publish_approved_video` delegate về service.
- ✅ WO-4.1: `media/render_engine.py` có `AUDIO_MASTER_FILTER = loudnorm I=-14:TP=-1.5:LRA=11 + 48kHz stereo`, mux `-ar 48000 -ac 2`.
- ✅ WO-4.2: `media/orchestrator.py` MIN_SCRIPT_WORDS=1500, MIN_VOICEOVER_SECONDS=480; audit check duration/48kHz/stereo.
- ✅ WO-4.3 (một phần): `output_audit.py` có check `editor_ui_visual_detected` + `visual_topic_overlap_too_low`.
- ✅ WO-4.4: `upload/compliance.py` gate medical disclaimer + "Health/YMYL needs disclaimer and verifiable sources".
- ✅ Monetization tab đủ section G7: Readiness checklist, Destinations, Approvals, Capabilities, Budgets, Usage, Credentials.

**WO CHƯA làm:**
- ❌ WO-2: `capabilities/llm_factory.py` chưa tồn tại; 10 call site LLM ad-hoc vẫn nguyên.
- ❌ WO-3: `jobengine/slots.py` chưa đọc env `OMNICAST_SLOTS_*`.
- ❌ WO-1.1 (một phần): export variant 9:16 (`RenderVariantExporter`) chưa được gọi trong `platforms/service.py` (TikTok destination đang disabled nên chưa lộ).

**BUG mới phát hiện khi chạy app (chặn E2E — sửa TRƯỚC khi test tiếp):**

| # | Triệu chứng | Nguyên nhân gốc (đã trace) | Fix đề xuất |
|---|---|---|---|
| BUG-1 | **cmd nhấp nháy LIÊN TỤC không ngớt** (không theo nhịp) + UI báo "Mất kết nối máy chủ" | Vòng khuếch đại: (1) `api/webui/index.html:1687` setInterval `OmniLoad()` 7s + `data.jsx:474` SSE job-event cũng trigger `OmniLoad` (debounce 250ms) + mỗi `_run` action xong lại `OmniLoad` → readiness bị gọi dồn dập; (2) mỗi call `/api/monetization/readiness` → `_latest_video_outputs()` (`server.py:682`): `rglob("*.mp4")` toàn repo + `OutputQualityAuditor.inspect()` 5 file, mỗi file **1 ffprobe + 1 ffmpeg ebur128 decode TOÀN BỘ audio (~10–60s/file 100MB, timeout 90s)** → một call kéo dài cả phút, spawn 10+ process; (3) **không có in-flight guard, không cache** → call sau chồng call trước, sau vài phút có N call song song cùng audit lại đúng 5 file đó → console spawn liên tục bất tận; (4) subprocess không có `CREATE_NO_WINDOW` nên mỗi process = 1 cửa sổ console; (5) nếu còn instance zombie (WebView ẩn/backend cũ chưa chết) thì nó vẫn poll ngầm → nhấp nháy cả khi không mở app | (a) Readiness **đọc sidecar `_output_audit.json`** do pipeline ghi sau render — KHÔNG đo lại trong endpoint; (b) cache audit theo `(path, mtime)` + **in-flight guard/single-flight** cho readiness (đang chạy thì trả kết quả cũ); (c) thêm `creationflags=subprocess.CREATE_NO_WINDOW` (win32) cho MỌI `subprocess.run/Popen`: `output_audit.py`, `runtime/probe.py` (nvidia-smi), `media/ffmpeg.py`, render Popen trong `render_routes.py`/`server.py`; (d) giới hạn scan vào `output/products` + `output/pipeline_renders`, bỏ rglob root; (e) kill process zombie giữ port 8767 khi start (xem BUG-3) |
| BUG-2 | **UI mojibake tiếng Việt** ("Chi phÃ­ hÃ´m nay", "KÃªnh", "Hoáº¡t Ä'á»™ng gáº§n Ä'Ã¢y"...) khắp Dashboard/Kênh/Monetization | Chuỗi double-encoded nằm **cứng trong `api/webui/app/pages.jsx`** (114 dòng dính, file bị lưu sai encoding 2026-07-03 02:26 — UTF-8 bytes bị đọc như latin-1 rồi re-encode). KHÔNG phải lỗi charset của server | Sửa lại literal tiếng Việt đúng UTF-8 trong `pages.jsx` (grep `Ã|áº|Ä'` ra đủ 114 dòng); quy tắc cho agent: mọi edit file .jsx phải giữ UTF-8, verify bằng `grep -c "Ã"` = 0 sau edit |
| BUG-3 | App khởi động chậm/1 lần crash để lại backend zombie; log cũ đầy `RuntimeError: cannot schedule new futures after shutdown` | `omnicast_desktop.py` đã có single-instance lock (tốt, mới thêm) nhưng khi WebView crash thì server thread dừng theo (finally → stop) còn tiến trình treo đôi lúc giữ port 8767; instance kế mở window trỏ backend cũ sắp chết → "Mất kết nối" | Thêm health-check `GET /api/status` trước khi reuse port đang mở (`already_up`): nếu port mở nhưng /api/status fail → kill PID giữ port (hoặc đổi port) rồi start server mới |

**Trình tự cho agent thực thi kế tiếp:** BUG-1 → BUG-2 (gộp với E-Q1) → WO-2/WO-3 → render lại script score-104 (audit gates mới sẽ enforce audio/duration/visual) → E2E `POST /api/publish/beat_glp1_nausea` → approve unlisted (WO-5).

**UI quality:** chẩn đoán "vì sao UI thua `_refs` dù audit đã nêu" + work-order cải thiện (E-Q1→E-Q5, gồm Epic H Vite migration) đã ghi tại `MASTER_PLAN_SuperApp.md` §7.2.

### 10.5 ĐÃ SỬA 2026-07-03 (BUG-1/2/3) — verified live

- ✅ **BUG-1** (console storm / "Mất kết nối"): `server.py::_latest_video_outputs` viết lại — chỉ scan `output/products` + `output/pipeline_renders` (bỏ `rglob` toàn repo + `_ROOT`), **ưu tiên đọc sidecar `_output_audit.json`** (không đo lại), fallback `OutputQualityAuditor(measure_loudness=False)` (ffprobe rẻ, KHÔNG ebur128), + **cache TTL 60s theo (path,mtime)**. `output_audit.py`: thêm `creationflags=CREATE_NO_WINDOW` (win32) cho `_ffprobe`/`_measure_integrated_lufs`. Đo live: readiness 2.28s→0.07s (cached), trước ~cả phút + spawn 10+ process. *(Còn lại: subprocess ở `media/ffmpeg.py`/`runtime/probe.py`/render Popen chưa gắn NO_WINDOW — bắn lẻ, không phải storm; để riêng.)*
- ✅ **BUG-2** (mojibake tiếng Việt 114 dòng): sửa `api/webui/app/pages.jsx` bằng `ftfy.fix_text` (double-encoded UTF-8→latin1). Verify: `grep 'Ã|áº|Ä‘|â€|ðŸ'` = 0, emoji khôi phục, line count giữ nguyên 1091; render live 0 mojibake, "Chi phí/Kênh/Kịch bản" đúng.
- ✅ **BUG-3** (zombie backend giữ port): `omnicast_desktop.py` thêm `_backend_healthy()` (GET `/api/status`); `already_up = _port_open() and _backend_healthy()`; nếu port mở nhưng không healthy → chờ ~10s cho zombie hồi/chết trước khi start mới, kèm cảnh báo rõ.

### 10.6 TIẾN ĐỘ WO (cập nhật 2026-07-03, phiên tiếp)

- ✅ **WO-3** — `jobengine/slots.py::SlotManager` đọc env `OMNICAST_SLOTS_GPU/CPU/NET` (default 1/4/8, arg tường minh vẫn thắng). Verified.
- ✅ **WO-2** — `capabilities/llm_factory.py::create_llm(default_provider, model, db_path)` (rút từ `steps._llm_client`, fallback LLMClient trực tiếp). Thay **11 call site**: `api/server.py` (10) + `analytics/competitor_intel.py` (1); `pipeline/steps.py::_llm_client` delegate về factory. Verified: AST + import server.py + factory trả LLMClient(deepseek).
- ✅ **WO-1.1** — export 9:16 trong `platforms/service.py`: thêm `_maybe_export_variant(request, platform)` gọi trước `platform.publish` — nếu `platform.format_spec.aspect_ratio != 16:9` (vd TikTok 9:16) và không dry-run → `RenderVariantExporter().export()` ra `_variants/{stem}_{variant}.mp4`, request trỏ sang biến thể. No-op cho 16:9/dry-run. Verified: export ra đúng **1080×1920**.
- ⏳ **WO-5** — E2E render score-104 + publish→approve: **chưa chạy** — render đầy đủ ~10-40 phút (CPU/GPU); bước approve→upload YouTube là hành động đăng ra ngoài, **cần user xác nhận** trước khi thực thi (kể cả unlisted).

**Còn lại:** WO-5 (E2E — cần user xác nhận bước upload).
