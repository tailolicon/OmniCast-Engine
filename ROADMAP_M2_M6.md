# OmniCast Super-App — Roadmap chi tiết phần còn lại (M2 → M6)

> Nối tiếp `ARCHITECTURE_SuperApp_Plan.md` (v5) + `SPEC_M0_NenMong.md`.
> Trạng thái: **M0 xong** (jobengine, 20/20 test) · **M1 xong** (đa nền tảng `IPlatform` + destinations + biến thể 9:16 + HITL, đã wire `content_flow` qua Job Engine — theo báo cáo của chủ dự án).
> Nguyên tắc xuyên suốt: **tái dùng > viết lại** · additive/strangler (không gãy bản đang chạy) · mỗi PR phải xanh (`pytest -x`) · **cập nhật `IMPLEMENTATION_STATUS.md` mỗi PR** (quy tắc CLAUDE.md).

## Thứ tự phụ thuộc
```
M0 (done) ─ M1 (done) ─┬─ M2 Capability+Credential+Budget ─┬─ M4 Monetization/ROI ─┐
                       └─ M3 Runtime Router (local-first) ─┘                       ├─ M5 Cockpit+Remote+Webhooks ─ M6 Scale/Thương mại
                                                                                   ┘
```
M2 và M3 chạy song song được sau M1 (đều dựa vào Capability layer). M4 cần M2 (budget↔revenue). M5 gom UI cho M1–M4. M6 tuỳ chọn.

---

## M2 — Capability Registry + Credential Vault + Bảo vệ chi tiêu 3 tầng

**Mục tiêu:** hợp nhất provider/model rải rác về một registry theo *capability*, quản lý key/quota/budget tập trung (qua UI, không phải `.env`), và khoá chi tiêu 3 tầng chống đốt tiền.

**Tái dùng (KHÔNG viết lại):** `llm/registry.py`, `llm/client.py`, `llm/cost.py`; `media/providers/registry.py` + `interfaces.py`; `settings.youtube_key_pool` (đã xoay vòng key); `services/budget.py` (BudgetManager); **`cache/circuit_breaker.py` (Redis — đã có, dùng cho Claude API)**; `cache/rate_limiter.py`.

**Module mới:**
- `capabilities/` — `bus.py` (`CapabilityBus`), `registry.py` (khám phá manifest + entry-point), `types.py` (`Capability`, `ResolvePolicy`, `Result`).
- `credentials/` — `vault.py` (CRUD key + Fernet at-rest), `keypool.py` (`KeyPool`), `usage.py` (usage_ledger), `budget_guard.py` (3 tầng).

**Vault schema (thêm):** `providers`, `models`, `credentials`, `usage_ledger`, `budgets(scope=global|campaign|channel, limit_usd, spent_usd, reset_at)`.

**Interfaces:**
```python
class CapabilityBus(Protocol):
    async def run(self, capability: str, request: dict, *, policy=None, on_progress=None) -> Result: ...
class KeyPool(Protocol):
    def acquire(self, provider_id: str, need: int = 1) -> Credential: ...   # priority/round-robin, bỏ key cooldown
    def report(self, cred, used: int, status: Literal["ok","429","blocked","error"]) -> None: ...
class BudgetGuard(Protocol):
    def check(self, scope: str, scope_id: str, usd: float) -> None: ...     # raise QuotaExceeded nếu vượt
    def record(self, scope: str, scope_id: str, usd: float) -> None: ...
```

**3 tầng phòng vệ:**
1. **Key cooldown** — 429/`FlowBlocked` → key vào cooldown, tự loại khỏi pool tới `cooldown_until`.
2. **Provider circuit breaker** — *dùng lại `cache/circuit_breaker.py`*, mở rộng key theo `provider_id`; error-rate > ngưỡng/5 phút → ngắt provider, router rớt sang fallback.
3. **Budget kill-switch** — chuyển `services/budget.py` từ in-memory sang **bền trong vault** + thêm cấp `campaign`/`channel`; vượt ngưỡng → chặn request.

**PR breakdown + nghiệm thu:**
| PR | Nội dung | Nghiệm thu |
|---|---|---|
| M2-1 | Vault schema (providers/models/credentials/usage_ledger/budgets) + CRUD | pytest: init + CRUD; Fernet round-trip |
| M2-2 | `KeyPool` (acquire/report, cooldown) — tổng quát hoá youtube_key_pool | 429 → key cooldown, acquire trả key khác; hết key → QuotaExhausted |
| M2-3 | `BudgetGuard` bền (global/campaign/channel) thay BudgetManager in-memory | vượt ngưỡng campaign → chặn; số liệu sống qua restart |
| M2-4 | Provider circuit breaker (mở rộng `cache/circuit_breaker`) | error-rate cao → provider mở mạch, request bị chặn/nhả fallback |
| M2-5 | `CapabilityRegistry` + manifest; adapter cho `llm/registry` + `media/providers/registry` | `list_capabilities()` gộp cả LLM+media; provider cũ vẫn chạy qua adapter |
| M2-6 | `CapabilityBus.run` gọi qua KeyPool+Budget+breaker; wire 1 call LLM thật qua bus | 1 script step chạy qua bus, có ghi usage_ledger + trừ budget |
| M2-7 | API + UI tab **Keys/Usage/Budget** (health key, quota, spend) | endpoint trả trạng thái key/budget; dashboard hiển thị |

---

## M3 — Runtime Router (local-first) + hợp nhất chạy local↔remote↔browser

**Mục tiêu:** mỗi capability định tuyến sang `local | remote | browser` theo manifest + **fallback chain** + nhận biết tài nguyên; local ngang hàng remote.

**Tái dùng:** endpoint OpenAI-compat trong `settings` (ollama/groq/openai/deepseek); TTS local (`tts_local.py` kokoro/xtts/f5, `tts_edge.py`); `flow_browser.py` (đã có FlowBlocked + retry); `imagen4.py`/`browser_imagen.py`; `image_local.py`.

**Module mới:** `runtime/` — `router.py` (`RuntimeRouter`), `probe.py` (`ResourceProbe` GPU/VRAM/CPU), `adapters/` (`openai_compat.py`, `comfyui.py`, `sherpa_tts.py`, `llama_cpp.py`, `browser.py`).

**Interfaces:**
```python
class RuntimeRouter(Protocol):
    def resolve(self, capability: str, policy: ResolvePolicy) -> list[ResolvedTarget]: ...  # fallback chain đã sắp
class ResourceProbe(Protocol):
    def gpu_free_mb(self) -> int: ...
    def can_run(self, model_manifest) -> bool: ...   # model local nặng chỉ chạy khi đủ VRAM
```
Manifest model khai `runtime` + `min_vram_mb` + `fallback` (vd ảnh: `flow(browser) → imagen(remote) → comfyui(local) → stock`).

**PR breakdown + nghiệm thu:**
| PR | Nội dung | Nghiệm thu |
|---|---|---|
| M3-1 | `ResolvePolicy`/`ResolvedTarget` + `RuntimeRouter.resolve` (đọc manifest, sắp fallback) | resolve trả đúng chuỗi fallback theo policy (prefer local/remote) |
| M3-2 | `ResourceProbe` + gating theo VRAM | model local `min_vram_mb` > free → bị loại khỏi chain, rớt remote |
| M3-3 | Adapter `openai_compat` (gói ollama/groq/openai/deepseek) | cùng interface gọi được 4 backend (mock/live tuỳ key) |
| M3-4 | Adapter local: `sherpa_tts`, `comfyui`, `llama_cpp` + `browser`(flow) | mỗi adapter chạy qua router; fallback khi 1 backend lỗi |
| M3-5 | Wire `CapabilityBus` → RuntimeRouter (thay resolve ad-hoc trong `render_real_video`) | 1 scene ảnh chạy qua bus+router, tự fallback khi Flow bị chặn |
| M3-6 | Đo & log chọn backend (event `runtime.selected`) lên cockpit | dashboard thấy backend đã dùng + lý do fallback |

---

## M4 — Monetization / ROI (khép vòng tiền)

**Mục tiêu:** biến "máy ra video" thành "máy ra doanh thu" — chèn affiliate, đo click→conversion, ghép chi phí↔doanh thu ra ROI, feed ngược cho tối ưu.

**Tái dùng:** `analytics/roi.py` (ROICalculator), `analytics/health.py` (revenue có trọng số), `analytics/strategist.py` (quyết định niche theo ROI), `analytics/youtube_stats.py` (AdSense est.), `upload/compliance.py` (thêm rule disclosure), `platforms/*.fetch_analytics` (từ M1).

**Module mới:** `monetization/` — `offers.py` (registry), `linker.py` (bước `monetize` chèn link+CTA), `redirect.py` (short-url trackable + ghi click), `revenue.py` (gộp AdSense+affiliate+sponsor).

**Vault schema (thêm):** `offers`, `placements`, `clicks`, `conversions`, `revenue(scope, source, amount, currency, ts)`.

**PR breakdown + nghiệm thu:**
| PR | Nội dung | Nghiệm thu |
|---|---|---|
| M4-1 | Vault offers/placements/clicks/conversions/revenue + CRUD | init + CRUD; offer theo niche_tags |
| M4-2 | Bước pipeline `monetize`: chọn offer theo niche → chèn link+CTA vào description/pinned comment (per destination) | metadata có link short-url đúng; skip nếu kênh tắt monetize |
| M4-3 | `redirect` service (short-url → ghi click → 302) + conversion qua postback | click ghi vào `clicks`; postback → `conversions` |
| M4-4 | `revenue` gộp AdSense (`youtube_stats`) + affiliate + sponsor → nạp vào `ROICalculator` | ROI/kênh/chiến dịch ghép chi phí (budget M2) ↔ doanh thu |
| M4-5 | Compliance rule **affiliate disclosure** vào `ComplianceChecker` per-platform | video có affiliate mà thiếu disclosure → compliance fail |
| M4-6 | Feed doanh thu → `StrategistAgent`/Discovery (ưu tiên niche+offer ra tiền) | weekly review dùng revenue thật; report ROI per offer |

---

## M5 — Cockpit & Remote control + Webhooks

**Mục tiêu:** gom mọi năng lực M1–M4 lên buồng lái realtime; điều khiển từ xa (điện thoại); tích hợp ngoài.

**Tái dùng:** dashboard React 8 tab (`frontend/App.jsx`) + `api/server.py` (~50 endpoint) + Job Engine SSE (M0) + `telegram/`.

**Việc:**
- **Tab mới/mở rộng:** Destinations (đa nền tảng), Keys/Usage/Budget (M2), Approvals/HITL (duyệt A/B title+thumb), Job Queue (trạng thái từng cảnh + nút retry-lỗi), Revenue/ROI (mở rộng tab Budget).
- **Realtime:** nối SSE `/api/v1/events/stream` (M0) vào dashboard thay polling.
- **Remote web (mobile):** cùng API + **auth/RBAC/audit** (middleware); client gọn cho điện thoại.
- **Webhooks:** outbound (job xong/lỗi/budget-kill → Discord/Slack/Telegram); inbound `POST /api/v1/triggers/{name}` (auth key, **chỉ kích pipeline template đã đăng ký**, validate param — input không tin cậy).

**PR breakdown + nghiệm thu:**
| PR | Nội dung | Nghiệm thu |
|---|---|---|
| M5-1 | SSE realtime vào dashboard (job progress per-cảnh) | UI cập nhật không polling; hiện tiến độ render |
| M5-2 | Tab Job Queue + nút **retry chỉ phần lỗi** (gọi engine.retry) | retry job lỗi → chỉ chạy lại step lỗi (checkpoint) |
| M5-3 | Tab Approvals/HITL (duyệt A/B → publish) | duyệt trên UI → job `WAITING_FOR_APPROVAL` chuyển publish |
| M5-4 | Tab Destinations + Keys/Usage/Budget + Revenue/ROI | hiển thị đủ số liệu M1/M2/M4 |
| M5-5 | Remote auth/RBAC/audit + client mobile | đăng nhập, quyền hạn, log truy cập; điều khiển từ điện thoại |
| M5-6 | Webhooks outbound + inbound (bảng `webhooks`, auth, template-only) | job xong bắn Discord; trigger ngoài kích đúng 1 pipeline template |

---

## M6 — Scale & Thương mại (tuỳ chọn)

**Mục tiêu:** mở đường scale nhiều worker + (nếu muốn) bán OmniCast.

| Hạng mục | Nội dung | Ghi chú |
|---|---|---|
| IStorage S3/MinIO | Thêm backend `S3Storage` sau `IStorage` (M0) + offload master → cold storage sau 7 ngày | multi-worker chia sẻ media; local vẫn là default |
| Postgres scale | Đường `SQLite → Postgres` khi chạm trần ghi 1 server (code PG đã tồn tại) | chỉ khi cần; giữ SQLite tới giới hạn |
| Plugin marketplace | Provider/platform bên thứ ba qua entry-point + manifest (đã thiết kế Open/Closed) | thêm nền tảng/model = drop-in |
| Bán OmniCast (nhánh B) | Licensing (key/HWID hoặc LemonSqueezy) + affiliate program + multi-tenant | sản phẩm tách riêng, chỉ làm khi tự dùng đã ổn |
| RabbitMQ distributed worker | Bật `jobengine/rabbit.py` live (QoS=slots) chạy nhiều worker máy render GPU riêng | cần broker; hiện in-process đủ 1 máy |

---

## Xuyên suốt (mọi milestone)
- **Verification:** `pytest -x` mỗi PR; PR bảo mật/kiến trúc (credential, webhook inbound, RBAC) → review kỹ (khuyến nghị subagent review).
- **Doc sync:** cập nhật `IMPLEMENTATION_STATUS.md` (mục tiến độ + gap) trong cùng PR — không để lỗi thời.
- **Migration:** strangler — tầng mới cạnh code cũ, adapter bọc dần; feature flag cho đường mới; `content_flow` + upload YouTube luôn chạy được.
- **Compliance/luật:** upload chỉ qua API chính thức; neural-only TTS; nhạc AI/royalty-free; affiliate phải disclosure; secrets Fernet at-rest.

## "Definition of done" của Super-App
Chạy 24/7: sản xuất → đăng **N nền tảng** (biến thể format) với **HITL tuỳ kênh** → kéo analytics 2 chiều → tính **ROI thật (chi phí↔doanh thu, có affiliate)** → Strategist tối ưu niche/offer; **thêm model/key/nền tảng/backend-local = drop-in manifest, không sửa lõi**; điều khiển từ web + điện thoại; chống sập (job queue + checkpoint + slot + circuit breaker + budget) và tự dọn rác (GC).

## Bước kế tiếp đề xuất
Bắt đầu **M2-1** (vault schema credentials/usage/budget) — nhỏ, additive, nền cho M2–M4. Hoặc nếu bạn muốn ưu tiên local trước, **M3-1** (RuntimeRouter.resolve). Nói mình milestone/PR nào, mình code + tự test như M0.
