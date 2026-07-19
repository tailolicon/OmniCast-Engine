# OmniCast M0 — Đặc tả kỹ thuật: Nền móng (Job Engine · Storage · Checkpoint · Events)

> Tham chiếu: `ARCHITECTURE_SuperApp_Plan.md` (mục 4.10/4.11). M0 là nền móng cho M1 (publishing).
> **Nguyên tắc M0:** *không đổi hành vi sản xuất* — chỉ đưa pipeline hiện tại chạy qua khung mới (strangler-fig). Sau M0, render + upload YouTube vẫn chạy y như cũ, nhưng đã đi qua Job Engine + checkpoint + IStorage.

---

## 1. Phạm vi M0

**Trong phạm vi:**
1. **Vault schema mới** (bảng jobs/job_steps/checkpoints/assets/worker_slots/events) — bám pattern `vault/db.py`.
2. **`IStorage`** + `LocalDiskStorage` (impl duy nhất ở M0).
3. **Asset Registry** + GC TTL (daemon tối thiểu).
4. **Job Engine** trên RabbitMQ sẵn có: JobSpec generic, Submit/Status, **resource-slot concurrency** (QoS prefetch theo lớp tài nguyên).
5. **State machine + checkpoint + idempotency key** trên `pipeline/runner.py`.
6. **Event Bus + realtime** (SSE) cho cockpit.
7. **API v1** tối thiểu: submit job, job status, event stream, asset, health.
8. **Kernel-lite**: error taxonomy + config phân tầng (chỉ phần cần cho M0).

**Ngoài phạm vi (để M1+):** Platform/IPlatform, Credential Vault/key rotation, Capability Bus hợp nhất LLM, HITL/A/B, Circuit Breaker, Monetization. (Chỉ đặt *chỗ cắm* cho chúng.)

---

## 2. Kiến trúc M0 — thành phần mới ↔ module hiện có

| Thành phần M0 | Đặt ở đâu | Dựa trên cái đã có |
|---|---|---|
| Vault schema mới | `vault/db.py` (thêm bảng vào `init_db`) hoặc `vault/jobs.py` | pattern `_connect` (WAL+FK), `pipeline_executions` |
| IStorage | `storage/base.py` (`IStorage`) + `storage/local.py` (`LocalDiskStorage`) | `storage/file_ops.py`, `paths.py`, `cleanup.py` |
| Asset Registry | `storage/assets.py` (service) | `media/asset_manager.py` (gộp dần) |
| Job Engine | `jobengine/` (mới): `models.py`, `engine.py`, `worker.py`, `slots.py` | `queue/` (aio_pika, exchanges, DLQ, publisher/consumer) |
| State machine/checkpoint | `pipeline/runner.py` (mở rộng) + `pipeline/checkpoints.py` | `pipeline/models.py`, `executions.py` |
| Event bus | `kernel/events.py` | `structlog`, RabbitMQ `EXCHANGE_ALERT` |
| API v1 | `api/v1/` (router jobs/events/assets/health) | `api/server.py` (FastAPI) |
| Kernel-lite | `kernel/errors.py`, `kernel/config.py` | `shared/errors.py`, `config/settings.py` |

---

## 3. Vault schema M0 (DDL — bám `vault/db.py`)

> Thêm vào `init_db()` (executescript). Timestamps = TEXT ISO8601 UTC. JSON = TEXT. Giữ `pipeline_executions` cũ; bảng mới *bổ sung*, không phá.

```sql
-- Job Engine -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
  job_id        TEXT PRIMARY KEY,
  type          TEXT NOT NULL,                 -- "pipeline" | "step" | "render" | "upload" ...
  status        TEXT NOT NULL DEFAULT 'queued',-- queued|running|success|failed|cancelled|waiting_approval
  resource_class TEXT NOT NULL DEFAULT 'cpu',  -- cpu|gpu|net  (cho slot)
  priority      INTEGER NOT NULL DEFAULT 3,
  spec_json     TEXT NOT NULL DEFAULT '{}',    -- inputs/params
  parent_job_id TEXT,                          -- pipeline → step
  attempt       INTEGER NOT NULL DEFAULT 0,
  error         TEXT,
  created_at    TEXT NOT NULL,
  started_at    TEXT,
  finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id);

CREATE TABLE IF NOT EXISTS job_steps (
  job_id    TEXT NOT NULL REFERENCES jobs(job_id),
  idx       INTEGER NOT NULL,
  name      TEXT NOT NULL,
  status    TEXT NOT NULL DEFAULT 'pending',   -- + 'timeout' (mở rộng StepStatus)
  attempt   INTEGER NOT NULL DEFAULT 0,
  error     TEXT,
  started_at TEXT, finished_at TEXT,
  PRIMARY KEY (job_id, idx)
);

-- Checkpoint / idempotency ----------------------------------------------
CREATE TABLE IF NOT EXISTS checkpoints (
  job_id          TEXT NOT NULL,
  step            TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,               -- hash(step + inputs canonical)
  output_ref      TEXT,                        -- storage_ref của output (qua IStorage)
  output_json     TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL,
  PRIMARY KEY (job_id, step)
);
CREATE INDEX IF NOT EXISTS idx_ckpt_idem ON checkpoints(idempotency_key);

-- Asset Registry --------------------------------------------------------
CREATE TABLE IF NOT EXISTS assets (
  asset_id    TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,                   -- audio|image|video_intermediate|master|thumbnail|stock
  job_id      TEXT,
  storage_ref TEXT NOT NULL,                   -- "local://.../x.wav" | "s3://bucket/key"
  sha256      TEXT,
  size_bytes  INTEGER NOT NULL DEFAULT 0,
  state       TEXT NOT NULL DEFAULT 'active',  -- active|orphaned|deleted
  ttl_at      TEXT,                            -- NULL = giữ vô hạn
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_ttl ON assets(state, ttl_at);

-- Resource slots --------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker_slots (   -- CONFIG TĨNH: worker tự đọc lúc startup để set QoS prefetch.
  worker_id  TEXT PRIMARY KEY,              -- KHÔNG cập nhật realtime; RabbitMQ tự requeue khi worker crash (chưa ack)
  slots_gpu  INTEGER NOT NULL DEFAULT 0,    -- → hệ tự phục hồi, không cần đếm slot theo giây (Gemini).
  slots_cpu  INTEGER NOT NULL DEFAULT 4,
  slots_net  INTEGER NOT NULL DEFAULT 8,
  updated_at TEXT NOT NULL
);

-- Event log (cho realtime + audit) -------------------------------------
CREATE TABLE IF NOT EXISTS events (
  event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  type       TEXT NOT NULL,                    -- job.step.progress | job.finished | asset.gc ...
  job_id     TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
```

---

## 4. IStorage (storage/base.py)

```python
class StorageRef(str):  # "local://relpath" | "s3://bucket/key"
    ...

class IStorage(Protocol):
    scheme: str  # "local" | "s3" ...
    async def put(self, src_path: str, *, kind: str, ttl_s: int | None = None) -> StorageRef: ...
    async def put_bytes(self, data: bytes, *, name: str, kind: str, ttl_s: int | None = None) -> StorageRef: ...
    async def get(self, ref: StorageRef) -> str:          # trả local path dùng được (download nếu remote)
        ...
    async def open(self, ref: StorageRef) -> BinaryIO: ...
    async def url(self, ref: StorageRef, *, expires_s: int = 3600) -> str:  # presigned/file url cho UI
        ...
    async def exists(self, ref: StorageRef) -> bool: ...
    async def delete(self, ref: StorageRef) -> None: ...
```

**`LocalDiskStorage` (storage/local.py):** gốc tại `output/store/<kind>/<yyyy>/<mm>/<uuid>.<ext>`; `url()` trả `file://` hoặc đường dẫn API tĩnh; `get()` trả thẳng path. Dùng `storage/file_ops.py` cho IO. **Mọi nơi domain code đang `os.path`/ghi file thẳng → đổi qua IStorage dần** (strangler: bọc, không xoá ngay).

---

## 5. Asset Registry (storage/assets.py)

```python
class AssetService:
    def register(self, ref: StorageRef, *, kind: str, job_id: str|None,
                 sha256: str|None=None, size: int=0, ttl_s: int|None=None) -> str: ...   # → asset_id
    def get(self, asset_id: str) -> AssetRow | None: ...
    def find(self, sha256: str) -> AssetRow | None: ...        # dedup
    def mark_orphaned(self, asset_id: str) -> None: ...
    def gc(self) -> int:                                        # xoá state!=deleted & ttl_at<now → IStorage.delete + state=deleted
        ...
```
- **GC daemon (M0 tối thiểu):** một coroutine/cron chạy mỗi 1h gọi `gc()`. Policy TTL mặc định: intermediate `ttl_s=86400` (24h); master để `ttl_at=NULL` ở M0 (offload/policy 7 ngày là M1).
- Dedup theo `sha256` (đỡ render lại ảnh y hệt — nối ý tưởng cache Flow).

---

## 6. Job Engine (jobengine/)

### 6.1 Model
```python
class JobStatus(str, Enum):
    QUEUED="queued"; RUNNING="running"; SUCCESS="success"
    FAILED="failed"; CANCELLED="cancelled"; WAITING_APPROVAL="waiting_approval"  # dùng ở M1

class ResourceClass(str, Enum): CPU="cpu"; GPU="gpu"; NET="net"

class JobSpec(BaseModel):
    job_id: str
    type: str                          # "pipeline" | "render" | "upload" | "tts" ...
    resource_class: ResourceClass = ResourceClass.CPU
    priority: int = 3
    payload: dict[str, Any] = {}
    parent_job_id: str | None = None
```

### 6.2 Hàng đợi theo lớp tài nguyên (dùng RabbitMQ sẵn có)
- Thêm exchange `omnicast.jobs` + queue **theo lớp tài nguyên**: `jobs.gpu`, `jobs.cpu`, `jobs.net` (giữ các queue video cũ trong M0, migrate sau).
- **Resource slot = QoS prefetch của consumer.** Worker đăng ký capacity (`worker_slots`); consumer cho mỗi queue đặt `channel.set_qos(prefetch_count = slots_<class>)`. Hết slot GPU → RabbitMQ không giao thêm message `jobs.gpu` → job render thứ 2 nằm chờ, trong khi worker vẫn nuốt `jobs.cpu`/`jobs.net`. **Đây là cơ chế chống OOM, không cần scheduler riêng.**
- Bổ sung **semaphore in-process** (`slots.py`) cho job nặng chạy ngoài message-loop (vd subprocess ffmpeg) để chắc chắn không vượt slot.

```python
class SlotManager:
    def __init__(self, gpu:int, cpu:int, net:int): ...
    async def acquire(self, rc: ResourceClass) -> AcquiredSlot: ...   # block tới khi có slot
    def release(self, slot: AcquiredSlot) -> None: ...
```

### 6.3 Submit / Status
```python
class JobEngine:
    async def submit(self, spec: JobSpec) -> str:                 # ghi jobs(queued) → publish vào jobs.<rc>
        ...
    async def status(self, job_id: str) -> JobView: ...           # đọc jobs + job_steps + checkpoints
    async def cancel(self, job_id: str) -> None: ...
    async def retry(self, job_id: str, *, only_failed: bool=True) -> str:  # re-submit, skip step đã checkpoint
        ...
```
- API **chỉ submit + status** (không chạy đồng bộ). Render/upload dài chạy trong worker.
- Worker (`worker.py`): consume `jobs.<rc>` → `acquire slot` → chạy handler theo `type` → cập nhật `jobs/job_steps` + phát event → ack. Lỗi → nack/DLQ + `status=failed`. (Tái dùng `message.process()` ack/nack + DLQ của `queue/`.)

### 6.4 State machine + checkpoint + idempotency (mở rộng `pipeline/runner.py`)
- Pipeline = 1 job type `"pipeline"`; mỗi step có thể là job con (hoặc chạy in-process tuần tự — M0 giữ in-process như runner hiện tại, chỉ thêm checkpoint).
- **Trước khi chạy step:** tính `idempotency_key = sha256(step_id + canonical_json(inputs))`. Nếu `checkpoints` có key này **và** `output_ref` còn tồn tại (`IStorage.exists`) → **skip**, nạp output từ checkpoint (status=`skipped`/`success`).
  > **⚠ Gotcha (Gemini):** `inputs` đưa vào hash **PHẢI deterministic** — sanitize bỏ các trường bất định runtime (`timestamp`, `uuid4`, `run_id/execution_id/job_id`, các key kết thúc `_at`, absolute path tạm). Nếu không, hash đổi mỗi lần → checkpoint vô hiệu. → hàm `canonical_inputs()` trong `jobengine/idempotency.py` tự lọc theo danh sách key bất định + cho caller truyền `ignore` thêm. (`canonical_json` dùng `sort_keys=True`.)
- **Sau khi step success:** ghi `checkpoints(job_id, step, idempotency_key, output_ref, output_json)`.
- **Fail ở step N:** job `failed` tại N; `retry(only_failed=True)` chạy lại từ N (các step < N skip nhờ checkpoint) — *không tốn lại LLM/voice/render đã xong*. Đây là tổng quát hoá per-image-retry của Flow cho toàn pipeline.
- Mở rộng `StepStatus` thêm `TIMEOUT="timeout"`.

---

## 7. Event Bus + realtime (kernel/events.py + API)

```python
class EventBus:
    def emit(self, type: str, *, job_id: str|None=None, **payload) -> None:
        # 1) ghi bảng events  2) đẩy vào in-memory pub/sub (asyncio.Queue per subscriber)
        ...
    async def subscribe(self, *, job_id: str|None=None) -> AsyncIterator[Event]: ...
```
- Event chuẩn M0: `job.queued`, `job.started`, `job.step.progress` (payload `{idx,total,name,state}`), `job.step.finished`, `job.finished`, `asset.gc`, `slot.wait`.
- **API SSE:** `GET /api/v1/events/stream?job_id=` → `text/event-stream` đẩy realtime cho cockpit (không polling). (WebSocket là tuỳ chọn; SSE đủ cho M0.)

---

## 8. API v1 (api/v1/)

| Method · Path | Việc |
|---|---|
| `POST /api/v1/jobs` | submit job (body = JobSpec) → `{job_id}` |
| `GET /api/v1/jobs/{id}` | status đầy đủ (job + steps + checkpoints) |
| `POST /api/v1/jobs/{id}/retry` | retry (only_failed) |
| `POST /api/v1/jobs/{id}/cancel` | cancel |
| `GET /api/v1/jobs?status=&limit=` | list |
| `GET /api/v1/events/stream` | SSE realtime |
| `GET /api/v1/assets/{id}` / `…/url` | metadata / presigned url |
| `GET /api/v1/health` | db/queue/storage/worker-slots OK? |

Versioned `/api/v1`; giữ `api/server.py` cũ chạy song song tới khi migrate xong.

---

## 9. Kernel-lite

- **Error taxonomy** (`kernel/errors.py`): `OmnicastError` → `ProviderError`, `RateLimited`, `Blocked`(kế thừa `FlowBlocked`), `QuotaExceeded`, `StorageError`, `JobError`. (Circuit breaker/budget dùng ở M2 nhưng định nghĩa lỗi sẵn.)
- **Config phân tầng** (`kernel/config.py`): tách `core` (db path, mode, queue url, storage root) khỏi provider/platform config (sẽ vào vault ở M1/M2). M0 vẫn đọc `config/settings.py`, chỉ bọc lại.

---

## 10. Chiến lược migration (strangler — mỗi PR phải XANH)

1. Thêm bảng vault mới (không phá bảng cũ) + `IStorage`/AssetService — *chưa ai dùng*. Test riêng.
2. Bọc **một** đường ghi file của render (vd output master) qua `IStorage` + `assets.register`. Render vẫn ra đúng file. Test render 1 video.
3. Đưa pipeline hiện tại chạy **dưới Job Engine** (type `"pipeline"`), nhưng vẫn in-process; thêm checkpoint. Verify execution log + checkpoint.
4. Thêm `jobs.<rc>` queue + worker cho **render** (job nặng) với slot QoS; upload + script tạm in-process. Verify không OOM khi ép 2 render.
5. Thêm SSE event stream; cockpit hiển thị tiến độ realtime.
6. GC daemon bật cuối cùng (sau khi asset registry đã ghi đủ).
- **Feature flag** `OMNICAST_JOBENGINE=1` để bật/tắt đường mới.

---

## 11. Phân rã PR (thứ tự) + tiêu chí nghiệm thu

| PR | Nội dung | Nghiệm thu |
|---|---|---|
| PR1 | Vault schema M0 (DDL) + models | `pytest`: init_db tạo đủ bảng; CRUD jobs/assets/checkpoints |
| PR2 | `IStorage` + `LocalDiskStorage` | put/get/url/exists/delete round-trip; test dedup sha256 |
| PR3 | AssetService + GC | register/gc theo TTL; orphan→deleted; không xoá master |
| PR4 | Job Engine model + submit/status (in-process worker) | submit→running→success; status đọc đúng |
| PR5 | Checkpoint + idempotency trong runner | fail giữa pipeline → retry chỉ chạy lại step lỗi (assert skip step trước) |
| PR6 | RabbitMQ `jobs.<rc>` + worker + slot QoS | ép 2 job GPU → job thứ 2 `queued` tới khi slot trống (no OOM) |
| PR7 | EventBus + SSE `/events/stream` | client nhận `job.step.progress` realtime |
| PR8 | API v1 jobs/assets/health + flag | render+upload YouTube chạy qua Job Engine vẫn ra video đúng (E2E dry_run) |

**Tiêu chí "M0 done":** chạy lại đúng pipeline cũ qua Job Engine, render 1 video thật + upload dry_run thành công, kill giữa chừng rồi `retry` không render lại phần đã xong, ép 2 render không OOM, cockpit thấy tiến độ realtime. Verify bằng `pytest -x` + 1 lần render thật + (khuyến nghị) subagent review PR8.

---

## 12. Quyết định mở (cần bạn chốt trước khi code)
1. **Job con vs in-process:** M0 giữ step in-process (đơn giản, ít rủi ro) hay tách mỗi step thành job riêng ngay (linh hoạt scale, phức tạp hơn)? *Khuyến nghị: in-process M0, tách dần.*
2. **SSE đủ chưa** hay cần WebSocket 2 chiều ngay? *Khuyến nghị: SSE M0.*
3. **GC master policy:** M0 giữ master vô hạn (an toàn) hay áp 7 ngày luôn? *Khuyến nghị: vô hạn ở M0.*
4. Giữ **SQLite SSOT** cho jobs (đồng ý) — chấp nhận trần ghi 1 server tới khi cần Postgres.

> Sau khi bạn duyệt spec này, mình bắt đầu **PR1 (vault schema)** — nhỏ, an toàn, không đụng đường chạy hiện tại.
