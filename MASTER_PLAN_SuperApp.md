# OmniCast Engine — MASTER PLAN: Hợp nhất · Xoá nợ kỹ thuật · Super-App sẵn sàng kiếm tiền

> **Vai trò của file này:** đây là bản kế hoạch thực thi (execution plan) để giao cho nhiều AI agent làm việc song song/tuần tự trên repo này. Không phải design doc — là danh sách công việc cụ thể, có file/module đích, tiêu chí nghiệm thu, và thứ tự phụ thuộc.
>
> **Nguồn sự thật đầu vào:** `OmniCast_Audit_Report.docx` (audit 02/07/2026, đọc trực tiếp code) + `IMPLEMENTATION_STATUS.md` (SSOT tiến độ) + `ARCHITECTURE_SuperApp_Plan.md` v5 (kiến trúc đích) + `SPEC_M0_NenMong.md` (đặc tả Job Engine đã có, xem Epic B2). File này **không lặp lại** nội dung 4 file trên — chỉ tổng hợp thành kế hoạch hành động, agent thực thi cần đọc cả 4 file gốc trước khi bắt đầu bất kỳ Epic nào.
>
> **Đã xác nhận:** `E:\Project\OmniCast Engine\implementation\OmniCast.bat` (→ `omnicast_desktop.py`, cổng 8767, phục vụ `api/webui/`) là **target thật của `OmniCast.lnk`** trên Desktop người dùng. Đây là launcher DUY NHẤT được công nhận chính thức từ giờ trở đi — mọi quyết định "giữ cái nào, xoá cái nào" trong kế hoạch này đều lấy đây làm mỏ neo.

---

## 0.1. Decisions and Execution Progress

These decisions are now fixed from the audit evidence and current repo state:

1. **Official UI:** keep `implementation/src/omnicast/api/webui/` served by `implementation/omnicast_desktop.py` on port 8767. `frontend/` is archived at `_archive/frontend_legacy/`; a future Vite migration must be a separate Epic, not mixed into Epic E.
2. **Official launcher:** `implementation/OmniCast.bat` is the real launcher. `Start OmniCast.bat` at repo root is only a wrapper to that launcher.
3. **Remote control:** Epic G remains last, after D6 proves stable end-to-end monetized operation.
4. **Affiliate/network input:** D2/D6 still require real operator-owned affiliate account/network/offer data; code cannot invent that acceptance evidence.

Current execution progress:

- **A1/A2 done:** launcher no longer hard-codes a personal Python path; root launcher delegates to the official launcher.
- **A5 done:** `.gitignore` now excludes `node_modules/`, `.venv/`, output/cache/log/media artifacts.
- **F1/F2/F3/F4/F5/F7 done by archive:** HTML mock, scratch/test root files, root media references, `Free/Free.zip`, and `implementation/phase1..phase7` moved to `_archive/`. `implement/` was archived/removed, but the local Auto-SpecKit hook recreates it as an empty directory; treat empty `implement/` as environment-generated noise, not project content.
- **A3/A4 done:** `frontend/` is archived to `_archive/frontend_legacy/`. Streamlit UI files (`dashboard/app.py`, `dashboard/auth.py`, `dashboard/tabs/`, `dashboard/components/`) are archived to `_archive/dashboard_streamlit_legacy/`; `dashboard/data_service.py`, `dashboard/models.py`, and `dashboard/__init__.py` remain because FastAPI and Telegram still use that data layer.
- **B1 done:** `PipelineRunner.run_single_step()` now provides a shared execution-ledger path for `omnicast.discovery` and `omnicast.script`; `/api/run/{channel_id}`, `/api/run/{channel_id}/script`, and `content_flow.py --phase 1/2` use that runner path while preserving the existing API state/log shell. Streamlit B1.4 is closed because the Streamlit UI layer is archived.
- **B2 done:** render submits through JobEngine by default (`OMNICAST_JOBENGINE=1`, rollback with `OMNICAST_JOBENGINE=0`) using resource class `GPU`; `/api/pipelines/run` submits pipeline jobs through JobEngine; pipeline jobs use `PipelineRunner.run_checkpointed_file()` with per-step checkpoints; WebUI listens to JobEngine SSE and no longer polls office log every 2-2.5s; slot serialization is covered by `test_gpu_slot_serializes`.
- **B3 done:** `render_real_video.py` remains the official render entrypoint. `channel_render.py` and `remotion_render.py` are retained because grep shows they are imported by `render_real_video.py` as support adapters; they are not duplicate production entrypoints to archive.
- **B4 done:** text/image/video provider selection now resolves through `CapabilityBus` with safe fallback to the existing hard-coded defaults. `CapabilityBus.resolve()` supports preferred provider selection and registry discovery includes the inline Anthropic path.
- **C done:** existing media providers are decorated to satisfy capability metadata/health contracts; `implementation/providers.manifest.yaml` registers current image/video/TTS providers; `CapabilityBus.resolve_with_fallback()` and `run_with_fallback()` provide shared fallback behavior; RuntimeRouter uses manifest runtime/VRAM metadata; `implementation/docs/ADD_NEW_PROVIDER.md` documents adding adapters without changing agents/pipeline/orchestrator.
- **D3/E6 partial:** approval queue now persists in `vault.db` through `/api/approvals`, supports approve/reject decisions, and appears in the official Monetization UI. The WebUI publish button now queues `/api/publish/{channel_id}` approvals instead of uploading directly, and approve continuation routes through `platforms/service.py` into platform adapters. Remaining D3/D6 work needs live publishing credentials, real offers, and E2E evidence.
- **WO-4 done at code/test level:** output-quality blockers now fail before spend/publish: render audio is mastered to -14 LUFS target, 48 kHz stereo AAC 192k; output audit rejects short/non-mastered files; media orchestrator rejects scripts under 1,500 spoken words and TTS voiceovers under 8 minutes; phase-2 blocks normalized duplicate topics that already have saved script products or used topic rows; health/YMYL compliance blocks missing medical disclaimers, dangerous medical advice, and unsourced specific medical citations/statistics; visual relevance QA and product-level `_output_audit.json` handoff are wired after render.
- **D/E/G still open:** not complete until each acceptance gate below has runtime/test evidence and real operator credentials/offers where required.

## 0. Mục tiêu cuối cùng & nguyên tắc thực thi bắt buộc

**Mục tiêu cuối (Definition of Done toàn dự án):**
1. Double-click `OmniCast.lnk` → mở đúng 1 ứng dụng, đầy đủ chức năng, không còn UI/launcher nào khác cạnh tranh trong repo.
2. Không còn 2 đường code khác nhau cho cùng 1 nghiệp vụ (single source of truth cho discovery/script/render/publish).
3. Toàn bộ hạ tầng đã xây (Job Engine M0, Capability Bus M2, Monetization M1/M4, Platform M1) **được cắm dây và hoạt động thật**, không còn module mồ côi.
4. Có thể bật kênh mới, chạy 24/7, đăng video, gắn affiliate link, và **thấy tiền vào** (dù là số nhỏ ban đầu) — không chỉ là hạ tầng có sẵn mà workflow thật đã chạy được từ đầu đến cuối qua UI.
5. Thêm 1 provider mới (giọng đọc, ảnh, video, nhạc nền) chỉ cần viết 1 adapter + đăng ký manifest — **không sửa code lõi của agent/orchestrator**.
6. Repo sạch: không file rác, không thư mục trùng tên, không script "scratch" nằm ngoài `tests/`/`scripts/`.

**Nguyên tắc bắt buộc cho MỌI agent làm việc trên plan này (copy từ CLAUDE.md + bổ sung):**
- **Strangler, không big-bang.** Mỗi PR phải giữ pipeline hiện tại chạy được (`pytest -x` xanh + render 1 video thật + upload dry-run OK) trước khi merge tiếp PR sau.
- **SQLite `vault.db` là SSOT** cho mọi dữ liệu có lifecycle. Không tạo JSON file mới cho dữ liệu dạng này.
- **Upload 100% qua YouTube Data API v3** (và API chính thức của các nền tảng mới nếu mở rộng) — không browser automation cho hành vi đăng bài.
- **Cập nhật `IMPLEMENTATION_STATUS.md` trong cùng PR** mỗi khi đổi trạng thái module (thêm/sửa/xoá/hoàn thành).
- **Không thêm chỉ thị ghi đè hành vi AI vào bất kỳ doc nào** (đã có tiền lệ xấu trong `AGENTS.md` cũ, đã gỡ — không lặp lại).
- Khi nghi ngờ giữa doc và code → **tin code**.
- Agent nhận 1 Epic/PR nào thì đọc kỹ mục tương ứng bên dưới TRƯỚC, không tự suy diễn phạm vi.

---

## 1. Kiến trúc đích — một luồng duy nhất

```
                     ┌─────────────────────────────────────────┐
                     │   api/webui/  (qua omnicast_desktop.py)  │  ← ĐIỂM TRUY CẬP DUY NHẤT
                     └───────────────────┬───────────────────────┘
                                         │ REST + SSE
                     ┌───────────────────▼───────────────────────┐
                     │        api/server.py  (FastAPI, 1 backend)│
                     └───────────────────┬───────────────────────┘
                                         │
                     ┌───────────────────▼───────────────────────┐
                     │   pipeline/runner.py (Kestra-lite)         │  ← NGUỒN SỰ THẬT DUY NHẤT
                     │   cho discovery→script→render→upload       │     cho quy trình sản xuất
                     └───────┬───────────┬────────────┬───────────┘
                             │           │            │
                     ┌───────▼───┐ ┌─────▼─────┐ ┌────▼──────┐
                     │ jobengine │ │ capability │ │ platforms/│
                     │  (M0)     │ │ bus (M2)   │ │  (M1)     │
                     │ checkpoint│ │ provider   │ │ multi-    │
                     │ + slot    │ │ manifest   │ │ publish   │
                     └───────────┘ └────────────┘ └───────────┘
```

Ba khối dưới cùng (`jobengine`, `capability bus`, `platforms`) **đã tồn tại trong code** (theo audit) nhưng chưa được `pipeline/runner.py` gọi tới thật. Epic B là việc đấu nối 3 khối này vào giữa — đây là phần việc kỹ thuật quan trọng nhất của toàn kế hoạch.

---

## 2. Danh sách Epic (workstream)

| Epic | Tên | Có thể chạy song song với | Phải xong trước khi bắt đầu |
|---|---|---|---|
| **A** | Hợp nhất điểm truy cập — 1 app duy nhất | E, F | — (làm trước tiên, ít rủi ro) |
| **B** | Xoá nợ kỹ thuật liên kết (3 đường code → 1) | — | A xong (để biết UI nào là chính thức mà không phá lúc đang dọn) |
| **C** | Kiến trúc plug-in Provider (voice/image/video/BGM mở rộng được) | D, E (sau khi B1 xong) | B1 (hợp nhất pipeline runner) |
| **D** | Super-App vận hành thật — kiếm tiền được | E | B2 (Job Engine wired), C (capability bus wired) |
| **E** | Nâng cấp UI toàn diện | C, D (làm song song, thêm dần theo backend đã sẵn sàng) | A xong |
| **F** | Dọn dẹp rác / archive | — (làm bất kỳ lúc nào, độc lập) | — |
| **G** | Remote Control — điều khiển từ điện thoại | — | **D + E ổn định** (xem mục 0 nguyên tắc: đây là nâng cấp SAU CÙNG, chỉ bắt đầu khi hệ thống đã vận hành 24/7 không cần can thiệp tay thường xuyên) |

**Khuyến nghị phân công nếu có nhiều agent cùng lúc:** 1 agent làm Epic A → F trước (dọn dẹp, rủi ro thấp, 1-2 ngày). Sau đó tách 2 agent: Agent-1 làm Epic B (backend, cần hiểu sâu kiến trúc), Agent-2 bắt đầu Epic E cho các phần UI không phụ thuộc B (vd Settings Modal, toast/router). Khi B1+B2 xong, Agent-3 vào Epic C, rồi Epic D. Epic E tiếp tục xuyên suốt, thêm tab mới mỗi khi 1 phần backend ở D sẵn sàng. **Epic G KHÔNG giao cho agent nào cho tới khi bạn xác nhận D6 (kiểm thử kiếm tiền end-to-end) đã pass ổn định.**

---

## 3. Epic A — Hợp nhất điểm truy cập (1 app duy nhất)

**Mục tiêu:** `OmniCast.lnk` → `implementation\OmniCast.bat` → `omnicast_desktop.py` → `api/webui/` là con đường DUY NHẤT người dùng cuối thấy.

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| A1 | Khoá launcher chính thức | Sửa `implementation/OmniCast.bat`: bỏ hard-code path Python cá nhân (`C:\Users\Tailolicon\...\Python313\pythonw.exe`), copy logic dò `.venv\Scripts\pythonw.exe` từ `Start OmniCast.bat` (kèm thông báo lỗi rõ nếu thiếu venv) | Chạy `.bat` trên máy sạch (không có path cứng đó) vẫn mở được app |
| A2 | Loại bỏ launcher trùng | Xoá `Start OmniCast.bat` (root) — hoặc biến thành 1 dòng `call "implementation\OmniCast.bat"` nếu muốn giữ vì lý do quen tay | Chỉ còn 1 hành vi "mở OmniCast" duy nhất trong repo |
| A3 | Quyết định UI chính thức: `api/webui/` hay `frontend/` | **DONE 2026-07-02:** giữ `api/webui/` làm UI chính thức của desktop app; archive `frontend/` vào `_archive/frontend_legacy/`. Nếu muốn Vite sau này, tạo Epic migration riêng, không trộn vào Epic E. | Quyết định ghi rõ vào `IMPLEMENTATION_STATUS.md`; `frontend/` không còn ở root production path |
| A4 | Dọn UI thừa | **DONE 2026-07-02:** HTML mock đã archive; Streamlit UI (`dashboard/app.py`, `dashboard/auth.py`, `dashboard/tabs/`, `dashboard/components/`) đã archive vào `_archive/dashboard_streamlit_legacy/`. Giữ `dashboard/data_service.py`, `dashboard/models.py`, `dashboard/__init__.py` vì `server.py`/Telegram còn phụ thuộc data layer. | `dashboard/` production package chỉ còn data-service/model exports; archive giữ UI tham khảo |
| A5 | Cập nhật `.gitignore` | Đảm bảo `node_modules/`, `.venv/`, `__pycache__/`, `output/`, `*.mp4`, `*.mkv` không lọt vào git nữa (nếu chưa có) | `git status` sạch sau khi archive xong |

**Kiểm chứng cuối Epic A:** double-click `OmniCast.lnk` trên máy thật → mở đúng 1 cửa sổ, không lỗi console, render + upload dry-run vẫn hoạt động như trước khi dọn.

---

## 4. Epic B — Xoá nợ kỹ thuật liên kết

### B1 — Hợp nhất 3 đường chạy discovery→script về `pipeline/runner.py`

**Vấn đề (từ audit):** `api/server.py` (`_run_channel_phase1`/`_run_channel_phase2`), `content_flow.py` (CLI), và `pipeline/steps.py` (Kestra-lite) đều tự viết lại logic gọi `DiscoveryOrchestrator`/`DebateOrchestrator` — 3 bản sao độc lập.

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| B1.1 | Xác nhận `pipeline/steps.py` là bản đúng nhất | So `_step_discovery`/`_step_script` trong `pipeline/steps.py` với `_run_channel_phase1`/`_run_channel_phase2` trong `api/server.py` — hợp nhất thành 1 hàm dùng chung (đề xuất: chuyển logic vào `pipeline/steps.py`, coi đây là "hàm nghiệp vụ", cả API endpoint lẫn CLI đều gọi vào đây) | Không còn đoạn code Python giống nhau >80% ở 2 nơi (kiểm bằng đọc thủ công, không cần tool đo) |
| B1.2 | `api/server.py` gọi qua pipeline runner | Sửa `/api/run/{channel_id}` và `/api/run/{channel_id}/script` để **gọi `PipelineRunner` chạy step `omnicast.discovery`/`omnicast.script` trực tiếp** (không phải chạy cả pipeline YAML nếu chỉ cần 1 step — có thể thêm hàm `PipelineRunner.run_single_step()` nếu chưa có) thay vì tự `from omnicast.discovery.orchestrator import DiscoveryOrchestrator` rồi tự lắp lại | UI bấm "Discover"/"Write Script" vẫn hoạt động y hệt cũ, nhưng qua đường pipeline runner (log/execution xuất hiện trong `/api/pipelines/executions`) |
| B1.3 | `content_flow.py` gọi qua pipeline runner | Tương tự B1.2 cho CLI | `python content_flow.py` (hoặc lệnh tương đương) chạy ra kết quả giống hệt trước khi sửa |
| B1.4 | Dashboard Streamlit (nếu chưa archive ở A4) hoặc phần còn giữ lại | Nếu còn dùng `content_flow` gián tiếp qua `dashboard/tabs/vault.py`, xác nhận vẫn hoạt động sau B1.3 | Không lỗi import |

### B2 — Wire Job Engine M0 vào luồng sản xuất thật

**Vấn đề (từ audit + đã có sẵn `SPEC_M0_NenMong.md`):** `jobengine/` đã code xong (8 PR, test pass) nhưng 0 caller ngoài test.

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| B2.1 | Bật `OMNICAST_JOBENGINE=1` cho 1 luồng thử nghiệm | Theo đúng mục 10 (chiến lược migration) của `SPEC_M0_NenMong.md` — bắt đầu bằng bọc bước **render** (job nặng nhất, hưởng lợi nhiều nhất từ resource slot GPU/CPU) qua `jobengine.engine.JobEngine.submit()` thay vì gọi `subprocess.Popen` trực tiếp trong `render_routes.py` | Render 1 video qua job engine ra file giống hệt trước; `GET /api/v1/jobs/{id}` trả status đúng |
| B2.2 | Checkpoint cho discovery→script→render | Nối `pipeline/runner.py` (đã có state machine cơ bản) với `jobengine/checkpoint.py` để mỗi step ghi checkpoint thật | Kill server giữa chừng lúc đang render → khởi động lại → `retry` chỉ chạy lại step lỗi, không render lại từ đầu |
| B2.3 | SSE event stream lên UI | Bật `GET /api/v1/events/stream`, sửa `LiveAgentFeed`/`ActiveJobCard` trong UI để **chuyển từ polling 1.5s sang SSE** (đóng luôn 1 gạch đầu dòng UX nợ ở Epic E) | Network tab trình duyệt không còn request lặp mỗi 1.5s cho log, thay bằng 1 kết nối SSE |
| B2.4 | Resource slot cho render song song | Bật `worker_slots` + QoS như mục 6.2 của `SPEC_M0_NenMong.md`, test ép 2 kênh render cùng lúc | Không OOM, job thứ 2 chờ đúng như thiết kế |

### B3 — Dọn render engine trùng lặp

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| B3.1 | Xác nhận đường render chính thức | `render_real_video.py` (được `render_routes.py` gọi qua subprocess) là chính thức theo audit. Kiểm tra `remotion_render.py`/`channel_render.py` có còn được dùng ở đâu không (grep toàn repo) | Có danh sách rõ ràng: dùng hay không dùng |
| B3.2 | Archive nhánh không dùng | Nếu B3.1 xác nhận không còn dùng → chuyển `remotion_render.py`/`channel_render.py` vào `_archive/` kèm ghi chú lý do (vd "thử nghiệm Remotion render, chưa production-ready, xem lại nếu muốn chất lượng cao hơn FFmpeg") | Không còn 2 file render cùng làm 1 việc nằm ở root gây nhầm lẫn |

### B4 — Capability Bus M2: wire lời gọi LLM/media thật

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| B4.1 | Đổi `LLMClient(provider="anthropic")` hard-code → gọi qua `CapabilityBus` | Trong `pipeline/steps.py` (sau B1.1, đây là nơi duy nhất còn logic này) — thay khởi tạo trực tiếp bằng `CapabilityBus.resolve("text")` (hoặc tên capability tương ứng đã định nghĩa trong `capabilities/`) | Đổi provider LLM qua UI/config (không sửa code) vẫn chạy được |
| B4.2 | Tương tự cho TTS/image/video/music providers trong `media/orchestrator.py` | Đối chiếu `media/providers/registry.py` hiện có với `capabilities/` — hợp nhất theo đúng mục G2 của `ARCHITECTURE_SuperApp_Plan.md` (registry cũ trở thành adapter mỏng, không xoá) | 1 lần render dùng capability bus cho toàn bộ TTS/image/music, không còn khởi tạo provider trực tiếp trong orchestrator |

> **Epic B là phần việc rủi ro cao nhất trong toàn kế hoạch — mỗi mục con (B1.x, B2.x...) nên là 1 PR riêng, chạy `pytest -x` + render 1 video thật + upload dry-run sau MỖI PR, không gộp nhiều mục vào 1 PR.**

---

## 5. Epic C — Kiến trúc Plug-in Provider (mở rộng không đập-xây-lại)

**Mục tiêu cụ thể theo yêu cầu của bạn:** thêm 1 nguồn giọng đọc / ảnh / video / nhạc nền mới trong tương lai chỉ cần (1) viết 1 file adapter tuân theo interface có sẵn, (2) đăng ký vào registry/manifest, KHÔNG sửa `agents/`, `media/orchestrator.py`, hay `pipeline/`.

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| C1 | Chuẩn hoá interface Provider theo capability | Dựa trên khối `class IPlatform(Protocol)` mẫu đã có trong `ARCHITECTURE_SuperApp_Plan.md` mục G1 — làm tương tự cho từng capability: `ITTSProvider`, `IImageProvider`, `IVideoProvider`, `IMusicProvider` (đặt tại `capabilities/interfaces.py` hoặc file riêng mỗi loại trong `media/providers/`). Mỗi interface tối thiểu có: `id`, `capability`, `async def generate(...)`, `async def health_check()`, khai báo `cost_per_unit`/`rate_limit` để `services/budget.py` dùng được ngay | Có 1 file interface rõ ràng, có docstring hướng dẫn cách viết adapter mới |
| C2 | Chuyển toàn bộ provider hiện có (kokoro/edge/xtts/f5 TTS; gemini/flow/local-sd image; gemini/flow video) thành adapter tuân theo C1 | Không viết lại logic gọi API, chỉ bọc lại đúng interface | Test hiện có (`test_tts.py`, `test_media_models.py`...) vẫn pass |
| C3 | Manifest đăng ký provider (JSON/YAML, không sửa code khi thêm mới) | VD `providers.manifest.yaml` hoặc dùng thẳng bảng `providers`/`models` đã có trong vault.db (theo `IMPLEMENTATION_STATUS.md` mục Capability/Credential M2) — mỗi entry: `id, capability, adapter_class, priority, cost, requires_credential` | Thêm 1 dòng manifest mới (trỏ vào 1 class Python đã viết sẵn) → provider xuất hiện trong `GET /api/capabilities` mà không cần deploy lại code lõi |
| C4 | `VoiceRouter`/tương đương tổng quát hoá cho mọi capability | Đã có `voice_router.py` cho TTS (theo IMPLEMENTATION_STATUS.md) — nhân rộng pattern fallback-chain này cho image/video/music qua `CapabilityBus.resolve(capability, fallback_chain=[...])` chung 1 chỗ, không viết lại logic fallback riêng cho từng loại | 1 hàm `resolve_with_fallback()` dùng chung, có test giả lập provider đầu tiên lỗi → fallback provider thứ 2 |
| C5 | Tài liệu hướng dẫn "Thêm provider mới" | Viết `docs/ADD_NEW_PROVIDER.md` (mới) — hướng dẫn từng bước: copy template adapter → implement `generate()` → thêm dòng manifest → test → xong. Đây chính là cơ chế cho phép bạn "học từ repo khác rồi thêm nguồn mới" sau này mà không cần AI agent hiểu lại toàn bộ kiến trúc | Agent khác (hoặc chính bạn) có thể theo tài liệu này thêm 1 provider giả lập (mock) trong <30 phút mà không đụng code lõi |
| C6 | Runtime Router M3 wiring | Theo `ARCHITECTURE_SuperApp_Plan.md` G3 — bọc `RuntimeRouter`/`ResourceProbe` (đã có resolver) vào C3/C4 để tự động chọn `local|remote|browser` theo tài nguyên máy (VD: nếu không đủ VRAM cho TTS local → tự fallback API remote) | Giả lập thiếu VRAM (`OMNICAST_GPU_FREE_MB` override) → router tự chuyển sang remote provider |

**Đây là Epic quan trọng nhất cho yêu cầu "mở rộng trong tương lai" của bạn — ưu tiên làm đúng và có tài liệu rõ ràng hơn là làm nhanh.**

---

## 6. Epic D — Super-App vận hành thật, sẵn sàng kiếm tiền

**Mục tiêu:** không chỉ có hạ tầng monetization/multi-platform (đã có theo audit) mà phải **chạy được luồng thật từ đầu đến cuối và ra tiền**, dù ban đầu là số nhỏ.

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| D1 | Credential Vault thật, có UI | Bật `OMNICAST_CREDENTIAL_FERNET_KEY` thật (không chỉ để trống); UI nhập/xem (ẩn secret) API key theo provider + OAuth YouTube token — xem chi tiết UI ở Epic E4 | `GET /api/credentials` trả danh sách provider đã cấu hình, không lộ secret; đăng nhập YouTube OAuth qua UI thành công |
| D2 | Ít nhất 1 offer affiliate thật hoạt động | Tạo 1 offer thật (network/link/niche/commission) qua `monetization/affiliate.py` + `POST /api/monetization/offers`; đảm bảo `monetization/linker.py` tự chèn link vào description/pinned comment khi publish | 1 video thật publish có link affiliate kèm disclosure (tuân `ComplianceChecker` FTC rule), `GET /api/monetization/readiness` không còn ở trạng thái WAIT do thiếu offer |
| D3 | HITL Approval Gate — thêm cả backend lẫn UI (hiện thiếu cả 2, theo audit) | Thêm bảng `approvals` (theo mục 5 data model của `ARCHITECTURE_SuperApp_Plan.md`) + endpoint `POST /api/approvals/{job_id}/approve`\|`reject` + job state `WAITING_FOR_APPROVAL` (đã định nghĩa sẵn trong `SPEC_M0_NenMong.md` mục 6.1, `JobStatus.WAITING_APPROVAL`) — video render xong → chờ duyệt trước khi publish (bật/tắt theo `destination.approval_required`) | Render 1 video → xuất hiện trong hàng đợi chờ duyệt → bấm Approve trên UI → publish thật chạy tiếp |
| D4 | Publish đa nền tảng — kích hoạt nền tảng #2 thật (không chỉ dry-run) | Theo `ARCHITECTURE_SuperApp_Plan.md` M1 — xác nhận API TikTok Content Posting (hoặc nền tảng khác đã có adapter `platforms/tiktok/`) đủ điều kiện production, chuyển từ dry-run sang publish thật cho ít nhất 1 kênh test | 1 video xuất hiện thật trên nền tảng #2, `fetch_analytics` đọc được số liệu về |
| D5 | Vòng lặp ROI/Strategist chạy tự động | Xác nhận `StrategistAgent` (đã có, theo IMPLEMENTATION_STATUS.md) chạy theo lịch tuần thật (không chỉ code có sẵn), quyết định pause/boost/reallocate được log lại và (tối thiểu) hiển thị trên UI Analytics (Epic E7) | Sau 1 tuần vận hành thật, có ít nhất 1 quyết định tự động của Strategist xuất hiện trong log/UI |
| D6 | Kiểm thử "kiếm tiền được" end-to-end | Chạy toàn bộ chuỗi: discovery → script → render → HITL approve → publish YouTube (+ nền tảng #2 nếu D4 xong) → gắn affiliate link → theo dõi conversion qua `/r/{placement_id}` → revenue ghi vào `revenue_events` → hiển thị trên Budget/ROI tab | 1 lần chạy demo đầy đủ có bằng chứng số liệu thật (dù nhỏ) trong vault.db |

---

## 7. Epic E — Nâng cấp UI toàn diện

Đóng toàn bộ danh sách "tính năng câm" + gap so với `_refs/` đã liệt kê trong `OmniCast_Audit_Report.docx` Phần 4.2 và Phần 5. Nhóm theo mức ưu tiên, mỗi nhóm là 1 PR UI độc lập (không cần chờ nhau, nhưng cần backend tương ứng đã sẵn sàng — xem cột "Phụ thuộc").

> **📚 BỔ SUNG 2026-07-04 — nghiên cứu TOÀN BỘ 13 repo `_refs/`: xem `NGHIEN_CUU_REFS_FULL.md` (root).** Trích đầy đủ chức năng + giao diện từng repo, kèm **ma trận 18 chức năng C1–C18 → OmniCast đã có/chưa → ưu tiên**, và đề xuất **Epic I "Control Pack"** (I1: pause-sửa-tiếp pipeline, preview-trước-khi-tốn-tiền, per-scene queue status/retry, risk badge, sound chime; I2: vault browser, pipeline graph, subtitle style editor, BGM library, overlay preview, A/B hook; I3: remote/office sống/đa ngôn ngữ). Epic I chạy SAU P7 của `SPEC_UI_v2.md`.

### 7.0 Ba nhóm chức năng UI còn thiếu — xác nhận lặp lại ở nhiều repo tham chiếu

> Trích nguyên văn từ audit (`OmniCast_Audit_Report.docx` Phần 5) — giữ lại chi tiết để agent biết **chính xác học pattern nào từ repo nào** trong `_refs/`, không chỉ đọc mô tả chung chung ở bảng 7.1.

**(a) Quản lý Credential/Provider qua UI, không sửa file**
- `_refs/pyvideotrans`: 70+ màn hình cấu hình riêng cho từng provider (Whisper/Qwen/ChatGPT/DeepSeek/Gemini/TTS), có nút "Test Connection".
- `_refs/Pixelle-Video`, `_refs/MoneyPrinterTurbo`: Settings panel chọn preset LLM + nhập API key + test kết nối ComfyUI/RunningHub ngay trong UI.
- `_refs/pixel-agents`: Settings Modal cấu hình toàn bộ runtime (đường dẫn, bật/tắt hook, layout) không cần sửa file, có Import/Export config.
- 1DevTool (theo `PHAN_TICH_1DevTool_va_SuperApp.md` có sẵn ở root): bảng usage/quota đa provider + key rotation trực quan, risk badge cho hành động agent.
- → OmniCast hiện phải sửa `.env`/`channels/*.json` thủ công — đây là khoảng cách rõ nhất với mọi repo tham chiếu có tính năng tương tự. **Áp dụng ở E1 + E11.**

**7.0.1 — Vì sao "70+ màn hình cấu hình provider" là yêu cầu bắt buộc, không phải tuỳ chọn**

Đây là hạng mục người vận hành (bạn) đánh giá là cần thiết nhất trong Epic E, nên làm rõ thêm để agent không đánh giá thấp:
- **Không hardcode 70 màn hình riêng lẻ.** Cách làm đúng (khớp Epic C — kiến trúc plug-in): mỗi provider trong manifest (mục C3) khai báo schema cấu hình của chính nó (loại field: `api_key`/`oauth`/`base_url`/`voice_id`...). E1 xây **1 component render-form-động** đọc schema đó và tự vẽ ra đúng số ô nhập cần thiết + nút "Test Connection" gọi `health_check()` của adapter (đã định nghĩa ở C1). Khi C thêm 1 provider mới qua manifest, màn hình cấu hình cho nó **tự xuất hiện** trong E1 — không cần sửa code UI.
- Nhóm màn hình tối thiểu cần có ngay khi ra mắt: **LLM** (Anthropic/DeepSeek/...), **TTS** (Kokoro/Edge/XTTS/F5), **Image** (Gemini/Flow/local-SD), **Video** (Gemini/Flow), **Music/BGM** (nguồn nhạc mới sẽ thêm dần), **Nền tảng đăng bài** (YouTube OAuth, TikTok...).
- Mỗi màn hình bắt buộc có: input theo đúng loại credential, nút Test Connection (gọi thật, không giả), badge trạng thái, và (nếu là provider trả phí) hiển thị usage/quota hiện tại lấy từ `/api/usage`.
- **Đây chính là điều kiện tiên quyết để bạn tự thêm nguồn giọng đọc/ảnh/video/BGM mới mà không cần agent code lại UI** — khớp thẳng với yêu cầu mở rộng bạn đã nêu ở Epic C.

**(b) Preview media ngay trong dashboard**
- `_refs/voice-pro`, `_refs/MoneyPrinterTurbo`: nút nghe thử giọng đọc (voice trial-listen) trước khi chọn.
- `_refs/Pixelle-Video`: video preview auto-play + History tab tải lại kết quả cũ.
- `_refs/hyperframes`: live preview iframe đồng bộ real-time với timeline chỉnh sửa.
- → `ScriptViewer` của OmniCast hiện chỉ hiện text + copy prompt, chưa nghe/xem trước audio/ảnh/video đã render trong cùng màn hình. **Áp dụng ở E9.**

**(c) Retry theo từng mục + hàng đợi có trạng thái rõ ràng**
- `_refs/h2dev_flow`: hàng đợi có status tag từng item (Chờ/Đang tạo/Xong/Lỗi/Quá giờ) — pattern đơn giản, dễ áp dụng nhất.
- `_refs/VideoToolsPro`: hàng đợi batch có nút "retry lỗi" riêng cho từng file, không phải chạy lại toàn bộ.
- → Pipeline tab của OmniCast có cột Failed nhưng phải trigger lại toàn bộ channel, chưa có nút retry-per-job/per-scene. **Áp dụng ở E10.**

### 7.1 Bảng hạng mục UI

| # | Hạng mục UI | Nội dung | Tham chiếu repo (pattern học theo) | Phụ thuộc |
|---|---|---|---|---|
| E1 | Credential & Provider Manager (tab mới, xem chi tiết 7.0.1) | Màn hình cấu hình **riêng cho từng provider** (không phải 1 form chung) — mỗi provider (LLM, TTS, Image, Video, Music/BGM, nền tảng đăng bài) có block riêng: nhập API key/OAuth, nút "Test Connection", badge trạng thái (OK/lỗi/chưa cấu hình), bảng usage/quota (`/api/usage`), key rotation dự phòng | `pyvideotrans` (70+ màn hình riêng/provider), `Pixelle-Video`/`MoneyPrinterTurbo` (preset + test connection), 1DevTool (usage/quota + key rotation) | D1 + C3 (manifest) |
| E2 | Monetization tab (tách khỏi Destinations) | CRUD offers, bảng conversions, preview link tracking `/r/{id}` | — (thiết kế mới, không có mẫu trực tiếp trong `_refs/`) | D2 |
| E3 | Compliance/Policy panel | Hiển thị `GET /api/policy` (active + pending rules), nút Fetch (`POST /api/policy/fetch`), Approve/Reject rule | — | Không phụ thuộc Epic khác — làm ngay được |
| E4 | Automation/Scheduler panel | Toggle 24/7 (`/api/scheduler/toggle`), theo từng kênh, xem `/api/auto/status`, nút `/api/auto/run` | — | Không phụ thuộc |
| E5 | Pipeline Executions panel | Lịch sử chạy YAML pipeline (`/api/pipelines/executions`), nút trigger `/api/pipelines/run`, hiển thị retry | `h2dev_flow` (status tag per-item cho hàng đợi) | B1 (để executions phản ánh đúng luồng hợp nhất) |
| E6 | Approval Queue (HITL) | Bảng job `WAITING_FOR_APPROVAL` + thumbnail + tóm tắt script + nút Duyệt/Từ chối | — | D3 |
| E7 | Analytics/ROI tab (mới) | Biểu đồ theo `/api/platforms/metrics`, quyết định Strategist gần nhất, refresh-stats theo kênh | — | D5 |
| E8 | Kill-Switch action thật | Nút Pause/Resume gọi `POST /api/system/pause`/`resume` ngay trong `KillSwitchPill` (hiện chỉ đọc) | — | Không phụ thuộc — làm ngay |
| E9 | Preview media trong Scripts/Pipeline tab | Nút nghe thử audio, xem ảnh scene, xem video đã render ngay trong `ScriptViewer` | `voice-pro`/`MoneyPrinterTurbo` (voice trial-listen), `Pixelle-Video` (video preview auto-play + History tab), `hyperframes` (live preview iframe) | C2 (cần biết asset ref chuẩn hoá qua `IStorage`, xem `SPEC_M0_NenMong.md` mục 4) |
| E10 | Retry-per-item trong Pipeline/hàng đợi | Nút retry riêng từng job lỗi thay vì chạy lại toàn channel | `h2dev_flow` (status tag Chờ/Đang tạo/Xong/Lỗi/Quá giờ), `VideoToolsPro` (nút retry lỗi riêng từng file) | B2.2 (checkpoint) |
| E11 | Settings Modal runtime | Đổi model AI, bật/tắt tính năng, đường dẫn thư mục — không cần sửa file & restart | `pixel-agents` (Settings Modal + Import/Export config) | C3 (manifest provider) |
| E12 | UX nền tảng | Thay `alert()`/`confirm()` bằng toast/modal nhất quán; thêm React Router (giữ tab khi F5); responsive breakpoints; dark/light toggle (tuỳ chọn) | — | Không phụ thuộc — làm bất kỳ lúc nào, khuyến nghị làm sớm vì ảnh hưởng toàn bộ UI sau này |

> **📋 CẬP NHẬT 2026-07-03: người vận hành quyết định REBUILD UI TỪ ĐẦU — spec thực thi chính thức là `SPEC_UI_v2.md` (root):** Vite + React + TS + Tailwind v4, design system theo `_refs/hyperframes/DESIGN.md`, layout Studio theo `_refs/Pixelle-Video`, 13 tab → 7 mục, build tĩnh thay Babel-in-browser, chạy strangler song song webui cũ. `PLAN_EpicE_UI.md` (bản vá UI cũ) đã superseded — chỉ còn dùng bảng data-contract + copy + glossary trong đó.

### 7.2 E-Q — UI Quality Pass (bổ sung 2026-07-03): vì sao UI vẫn thua `_refs` dù audit đã nêu, và việc phải làm

> Chẩn đoán từ phiên chạy app thật + đọc code 2026-07-03. Trả lời thẳng câu hỏi "audit đã nhắc mà sao UI vẫn xấu": **Epic E mới chỉ nằm trên giấy** — các agent tới nay chỉ làm backend (Epic A/B/D + WO wiring), chưa có PR nào đụng E1–E12; đồng thời có 4 nguyên nhân chất lượng nằm NGOÀI danh sách tính năng của E1–E12 (thiếu tính năng ≠ toàn bộ vấn đề — phần "nhìn rẻ" đến từ nền tảng thị giác bên dưới):

1. **Trần chất lượng của stack:** `api/webui/index.html` ~1.700 dòng + React UMD + **Babel Standalone transpile JSX trong trình duyệt mỗi lần mở app** (`index.html:1380-1503`) — khởi động chậm, không minify, không TS/lint. Các repo tham chiếu đều là app build chuẩn (`pixel-agents/webview-ui`: React 19 + Vite; `hyperframes`: bun + build; ngay cả `office_app` nhúng trong chính webui này cũng là Vite build với asset hash).
2. **Icon = emoji ký tự** (💰🎬⚡🗄️) render phụ thuộc font Windows, dễ vỡ trên WebView2, và chính là loại ký tự bị nát khi file lưu sai encoding (BUG-2: 114 dòng mojibake trong `pages.jsx` đang hiển thị "ðŸ'°" thay vì icon). Refs dùng SVG icon set nên luôn sắc nét.
3. **Thiếu ngữ pháp thị giác nhất quán:** label trộn VN/EN trong cùng card; không skeleton-loading; không empty-state (tab Monetization hiện bảng trống + số 0 không giải thích); banner "Mất kết nối máy chủ" (BUG-1) chớp liên tục tạo cảm giác app hỏng.
4. **Bất nhất giữa 2 khu vực UI:** tab Văn phòng là app pixel-art Vite hoàn chỉnh (học từ `_refs/agent-office` + `pixel-agents`, có font/asset riêng) đứng cạnh 12 tab hand-rolled — chênh lệch đập vào mắt ngay khi chuyển tab.

**Hạng mục E-Q (mỗi mục 1 PR, làm được ngay không chờ backend):**

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| E-Q1 | Nền chữ & icon (đi cùng fix BUG-2) | Sửa 114 dòng mojibake `pages.jsx`; thay TOÀN BỘ emoji icon bằng SVG set (lucide, vendored vào `assets/icons/`, bọc 1 component `<Icon name/>`); font stack hỗ trợ tiếng Việt đầy đủ (Inter/Be Vietnam Pro + system fallback); thêm check `grep -c "Ã\|áº\|Ä'" app/*.jsx` = 0 vào quy trình verify của agent | Zero mojibake/ô vuông ở mọi tab trên WebView2; mọi icon là SVG |
| E-Q2 | Design tokens + trạng thái màn hình | Gom tokens (spacing 4/8px, radius, shadow, palette light/dark, type-scale) về 1 file CSS vars duy nhất; mọi card/table/button/badge dùng tokens; thêm skeleton-loading + empty-state có call-to-action cho TỪNG tab (Monetization/Approvals ưu tiên); banner kết nối → pill trạng thái nhỏ + retry im lặng | Chụp trước/sau từng tab; không còn bảng trống/số 0 thiếu giải thích; không còn banner đỏ chớp |
| E-Q3 | Nhất quán ngôn ngữ | Chọn VN làm ngôn ngữ vận hành chính (giữ thuật ngữ kỹ thuật EN: Capabilities, Budgets...); sweep label 12 tab + toast + tooltip | Không còn câu nửa VN nửa EN trong cùng 1 card |
| E-Q4 | **Epic H — Vite migration** (tách riêng đúng quyết định A3, giờ lên lịch chính thức) | Chuyển `app/*.jsx` sang Vite build ra static bundle FastAPI serve tại `/` (đúng cách `office_app` đã làm); xoá `babel.js`/`react.js` UMD runtime; cấu trúc component giữ nguyên; TS optional | First paint < 1s; không còn `<script type="text/babel">`; bundle minified |
| E-Q5 | Đồng bộ thẩm mỹ với office_app | Quyết 1 lần, ghi vào DESIGN note: (a) clean-SaaS toàn app, office_app là "màn hình giám sát" đóng khung riêng; hoặc (b) lấy pixel-art làm bản sắc (như `pixel-agents`) áp cho topbar/badge/loading toàn app | 2 khu vực UI không còn trông như 2 sản phẩm khác nhau |

**Thứ tự:** E-Q1 (gộp với fix BUG-2, làm NGAY) → E-Q2 + E-Q3 (song song E3/E4/E8/E12) → E-Q4 (Epic H — sau khi E1/E6 xong để khỏi build lại 2 lần) → E-Q5. Các mục E1–E12 (tính năng) vẫn theo bảng 7.1; E-Q là lớp chất lượng nền bên dưới chúng.

---

## 8. Epic F — Dọn dẹp rác (độc lập, làm song song bất kỳ lúc nào)

| # | Việc | Nghiệm thu |
|---|---|---|
| F1 | Xoá `implement/` (thư mục rỗng, đặt tên nhầm) | Không còn thư mục này |
| F2 | Xoá/archive `scratch_*.py` (10 file), `test_flow_imagen.py`, `test_imagen_dry.py` (di chuyển vào `tests/` nếu còn giá trị, không thì xoá) | `implementation/` root không còn file `scratch_*` |
| F3 | Archive `OmniCast Engine (standalone).html` | Xem A4 |
| F4 | Archive/di chuyển ra ngoài repo: 3 file `.mp4` (~556MB) + 1 file `.mkv` (~19MB) ở root | Dung lượng repo giảm đáng kể, `git status` sạch |
| F5 | Gộp `phase1/` .. `phase7/` (chỉ chứa `.md`) vào `_analysis/` | Root `implementation/` gọn hơn, giữ giá trị lịch sử |
| F6 | Rà soát `benchmark_writers.py` và các file CLI rời rạc khác (`bumper.py`, `character_dna.py`, `clickbait.py`, `html_overlay.py`, `music_harvester.py`, `music_lib.py`, `qa_check.py`, `setup_avatar.py`, `subtitle_sync.py`, `wikimedia_fetcher.py`, `vault.py`, `_run_pipeline.py`...) — phân loại: công cụ hợp lệ (di chuyển vào `scripts/`) vs tàn dư (archive) | Có bảng phân loại rõ ràng ghi vào `IMPLEMENTATION_STATUS.md`, root `implementation/` chỉ còn entrypoint chính thức (`omnicast_desktop.py`, `run_backend.py`, `render_real_video.py`, `policy_check.py`) |
| F7 | `Free.zip` + `Free/` ở root | Xoá bản gốc chưa tích hợp nếu asset đã có sẵn trong `api/webui/assets/` |

---

## 9. Epic G — Remote Control: điều khiển từ điện thoại (nâng cấp sau cùng)

> **Chỉ bắt đầu Epic này sau khi D6 (kiểm thử "kiếm tiền được" end-to-end) đã pass và hệ thống chạy 24/7 ổn định ít nhất vài tuần không cần can thiệp tay thường xuyên.** Đây là yêu cầu của bạn nhưng đúng thứ tự ưu tiên là làm cuối — điều khiển từ xa một hệ thống chưa ổn định chỉ tạo thêm rủi ro vận hành (bấm nhầm nút trên điện thoại khi đang debug production).

**Mục tiêu:** biến OmniCast từ "app desktop phải ngồi máy mới thao tác được" thành "dây chuyền tự động chạy 24/7, chỉ cần điện thoại để giám sát + duyệt (approve) + bấm dừng khẩn cấp khi cần".

| # | Việc | Chi tiết | Nghiệm thu |
|---|---|---|---|
| G1 | Xác thực & phân quyền từ xa | Thêm lớp auth (API key riêng cho remote hoặc OAuth cá nhân) cho `api/server.py` — hiện tại CORS mở `*` và không auth (chấp nhận được khi chỉ chạy local qua desktop app, **không chấp nhận được khi mở ra ngoài Internet**). Thêm RBAC tối thiểu: role "operator" (xem + duyệt) vs "admin" (đổi cấu hình/credential) | Gọi API không có token hợp lệ → 401; role operator không sửa được credential |
| G2 | Expose server ra ngoài an toàn | **Không** mở port thẳng ra Internet. Dùng 1 trong: Cloudflare Tunnel / Tailscale / VPN cá nhân — chọn 1 giải pháp theo hạ tầng bạn đang có. Ghi rõ lựa chọn + lý do vào `IMPLEMENTATION_STATUS.md` | Truy cập được `api/webui/` từ mạng di động qua đường hầm an toàn, không lộ port ra IP công khai |
| G3 | Giao diện tối ưu di động (mobile-first view) | Không cần app native riêng — làm 1 view rút gọn responsive (dựa trên E12 đã có Router + breakpoint) tập trung vào: trạng thái tổng quan (KPI), Approval Queue (E6), Kill-Switch (E8), Error Log — đây là 4 màn hình duy nhất người vận hành cần trên điện thoại, không nhồi cả 12 tab desktop | Mở `api/webui/` trên trình duyệt điện thoại → layout dùng được bằng ngón tay, không phải zoom/scroll ngang |
| G4 | Thông báo đẩy khi cần duyệt/khi có lỗi | Tái dùng `telegram/` (đã có sẵn theo IMPLEMENTATION_STATUS.md, đang dùng cho policy watcher alert) — mở rộng gửi Telegram khi: có job vào `WAITING_FOR_APPROVAL` (D3), khi có lỗi liên tiếp (giống ngưỡng đã áp dụng cho policy fetcher), khi Kill-Switch bị kích hoạt. Bấm link trong Telegram mở thẳng màn hình liên quan trên `api/webui/` (qua G2 tunnel) | Giả lập 1 job chờ duyệt → nhận được tin Telegram trong <1 phút, bấm vào mở đúng màn hình Approval |
| G5 | Hành động nhanh ngay trong Telegram (tuỳ chọn, không bắt buộc) | Nếu muốn duyệt/dừng mà không cần mở trình duyệt: dùng Telegram inline button gọi thẳng `POST /api/approvals/{id}/approve` hoặc `POST /api/system/pause` qua bot webhook | Bấm nút trong Telegram → hành động thực thi thật, có xác nhận phản hồi lại chat |
| G6 | Kiểm thử vận hành từ xa thật | Rời khỏi mạng nhà/văn phòng (dùng 4G/5G) → xác nhận: xem được trạng thái, duyệt được 1 job, dừng khẩn cấp được hệ thống — toàn bộ qua điện thoại | Có bằng chứng (video/ảnh chụp màn hình) 1 lần thao tác thật qua mobile network thành công |

---

## 10. Thứ tự thực thi khuyến nghị tổng thể

```
Tuần 1:   Epic A (toàn bộ) + Epic F (toàn bộ, song song)  →  chốt "1 app duy nhất"
Tuần 2-3: Epic B1 → B2 → B3 → B4 (tuần tự, mỗi mục 1 PR + verify)
          song song: Epic E3, E4, E8, E12 (không phụ thuộc B/D)
Tuần 4-5: Epic C (toàn bộ) — nền tảng mở rộng provider
          song song: Epic E1, E11 (khi C có tiến độ)
Tuần 6-7: Epic D (toàn bộ) — vận hành thật, bật kiếm tiền
          song song: Epic E2, E5, E6, E7, E9, E10 (theo từng phần D tương ứng xong)
Tuần 8:   D6 — kiểm thử end-to-end "kiếm tiền được", rà soát IMPLEMENTATION_STATUS.md lần cuối
──────────────────────────── chốt ổn định trước khi qua Epic G ────────────────────────────
Tuần 9+
(sau khi vận
hành ổn định
vài tuần):     Epic G (toàn bộ) — Remote Control di động, KHÔNG làm song song với A-F
```

Đây là ước lượng tham khảo — agent triển khai có thể nén thời gian nếu làm song song nhiều Epic hơn, miễn tuân thủ cột "Phụ thuộc" ở mỗi bảng. **Epic G cố tình tách khỏi nhịp 8 tuần đầu — đúng như bạn nói, đây là nâng cấp cuối cùng khi hệ thống đã ổn định, không phải mục tiêu ra mắt đầu tiên.**

---

## 11. Quyết định cần bạn chốt trước khi agent bắt đầu

1. **UI chính thức (A3):** giữ `api/webui/` (khuyến nghị) hay migrate sang `frontend/` (Vite)?
2. **Nền tảng #2 cho Epic D4:** TikTok (đã có adapter theo status) hay ưu tiên nền tảng khác? Cần xác nhận đã có tài khoản/API access hợp lệ chưa.
3. **Ngân sách affiliate cho D2:** bạn tự chọn network/offer thật nào để cấu hình đầu tiên (Amazon Associates, ClickBank, hay network khác)?
4. **Job con vs in-process cho Job Engine (B2):** giữ nguyên khuyến nghị "in-process, tách dần" của `SPEC_M0_NenMong.md` mục 12, hay đẩy nhanh sang job riêng ngay?
5. **Mức độ ưu tiên Epic E12 (UX nền tảng):** làm sớm (tuần 1, ảnh hưởng ít code nghiệp vụ) hay để cuối cùng?
6. **Giải pháp remote access cho Epic G2:** Cloudflare Tunnel, Tailscale, hay VPN riêng bạn đã có sẵn? (chỉ cần trả lời khi gần tới Epic G, không chặn các Epic khác)

> Sau khi bạn chốt các câu 1-5, agent nhận Epic A có thể bắt đầu ngay — không phụ thuộc câu trả lời cho D/C/G. Câu 6 có thể trả lời sau, khi hệ thống đã ổn định và chuẩn bị bước vào Epic G.
