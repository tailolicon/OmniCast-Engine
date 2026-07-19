> Sinh boi agent nghien cuu workflow ws-research-456, 2026-07-19. Read-only.

Đã đủ bằng chứng. Đây là báo cáo WS5.

---

# BÁO CÁO WS5 — Ops / Scheduler / Cost (READ-ONLY)

Repo: `E:\Project\OmniCast Engine\implementation`. Đọc charter `WORKSTREAMS_ParallelUpgrade.md` (WS5 dòng 55-61). Không sửa file. WS0 (`narrative_pipeline.py`, phần narrative của `steps.py`) chỉ đọc để hiểu contract.

## Tóm tắt điều hành

Có **BỐN cơ chế điều phối rời rạc, không cái nào biết cái nào**, và kênh creepy đang chạy qua đường **ngoài** package pipeline chính thức. Cost notional (chi phí thật của subscription) được tính đúng trong narrative pipeline nhưng **rơi hoàn toàn khỏi vault/dashboard** vì chỉ marginal cost (=0 với CLI) mới chảy vào event. Quota-awareness và chống-sleep tồn tại dưới dạng vá script tay, không phải first-class trong scheduler. Frontend ĐÃ có sẵn chỗ cắm (`api/budget`, `api/pipelines/executions`, `api/scheduler`) nhưng đang hiển thị $0 và bỏ trống với creepy.

---

## 1. BẢN ĐỒ HIỆN TRẠNG (dẫn chứng file:line)

### 1a. Bốn cơ chế điều phối cùng tồn tại, không hợp nhất

| # | Cơ chế | File | Chạy thật? | Kênh creepy dùng? |
|---|--------|------|-----------|-------------------|
| 1 | **Batch runner ad-hoc** (quota-aware, detached) | `scripts/run_seq_batch.py` | CÓ — đường sản xuất creepy hiện tại | **CÓ (đường chính)** |
| 2 | **In-app autonomous scheduler** (MoneyPrinter-style) | `api/server.py:216-298` (`_scheduler_loop`, `_auto_cycle_task` @2977) | Có nhưng **off by default** (`enabled: False`) | Có thể, nhưng không phải đường creepy đang dùng |
| 3 | **PipelineScheduler** (Kestra-lite APScheduler cron) | `pipeline/runner.py:454-528` | CÓ chạy, nhưng **chỉ fire pipeline có `schedule:`** | **KHÔNG** — `default_channel.yaml` không có `schedule:` |
| 4 | **Weekly policy watcher** (APScheduler riêng) | `api/server.py:307-342` | CÓ | N/A |

Bằng chứng chốt: `default_channel.yaml` (file đầy đủ 71 dòng) **không có block `schedule:`** → `PipelineScheduler.start()` (`runner.py:491` `if not spec.schedule: continue`) bỏ qua nó. Chỉ `policy_watcher.yaml:15-17` có `schedule:`. Nghĩa là **package pipeline runner + scheduler chính thức KHÔNG bao giờ tự động sản xuất content** — nó chỉ chạy policy watcher.

### 1b. Kênh creepy đi đường TAY, bỏ qua runner + executions log

Chuỗi thật của creepy: `run_seq_batch.py:74` → `subprocess.run([PYTHON, run_phase2_unit_first.py, --topic ...])` → `run_phase2_unit_first.py:42-47` gọi **thẳng** `from omnicast.pipeline.steps import _step_script` rồi `await _step_script(...)`.

Hệ quả (dẫn chứng):
- **KHÔNG qua `PipelineRunner`** → **không có row nào trong `pipeline_executions`** (bảng chỉ được ghi bởi `runner.py:upsert_execution`, xem `executions.py:53`). Executions ledger **mù hoàn toàn** với sản xuất creepy.
- Retry/timeout/backoff của runner (`runner.py:370-449`) không áp dụng; batch tự cuộn retry riêng (`run_seq_batch.py:70-93`).
- Quota logic là **regex grep stdout log**: `run_seq_batch.py:32` `_LIMIT_RE = re.compile(r"session limit.{0,40}?resets ...")` → `seconds_until_reset()` (`:35-52`) ngủ tới lúc reset + cushion 300s → retry ≤3 (`:70`). Đây là công cụ vá NGOÀI scheduler, đúng như charter mô tả.
- Điểm nối duy nhất giữa hai hệ: `claude_cli.py:319-325` chủ động in "session limit" ra STDOUT để batch loop grep được — một hợp đồng ngầm string-matching, dễ vỡ khi CLI đổi format.

### 1c. In-app scheduler đi đường KHÁC nữa (path #2)

`_auto_cycle_task` (`server.py:2977`) → `_run_channel_phase2` → `PipelineRunner.run_single_step(step_type="omnicast.script", pipeline_id="api_channel_phase2")` (`server.py:4089`). Đường này **CÓ** ghi `pipeline_executions` nhưng mỗi row chỉ là **một step đơn** (`runner.py:242-301`), không phải full pipeline `discovery→script→render→upload`. Topic lấy từ vault: `vault_db.get_next_topic(cid)` (`server.py:2993`) — dùng `topics.status='queued'` (`vault/db.py:827-836`). Vậy **cơ sở hạ tầng queue-từ-vault ĐÃ có sẵn** và đường in-app đã dùng nó; chỉ batch creepy là chưa.

### 1d. Cost tracking: notional tính đúng nhưng KHÔNG chảy vào vault/dashboard

Luồng cost (dẫn chứng nối tiếp):
1. `claude_cli.py:344` `notional = total_cost_usd` → gói vào `LLMResponse.notional_cost_usd` (`:352`), `cost_usd=0.0` (`:350`, cố ý — subscription không bill per-token, `:341-343`).
2. `narrative_pipeline.py:5866-5880` `_record_cost()` cộng `notional_cost_usd` vào `self._run_notional_cost_usd`; surface ra `aggregate_notional_cost_usd` trong `narrative_audit.json` (`steps.py:667-668`, ghi audit ở `steps.py:969`).
3. **NHƯNG** cost chảy vào dashboard đi qua kênh khác: `steps.py:1111` `_script_cost = get_session_cost()` — mà `get_session_cost()` (`llm/client.py:61-65`) chỉ tổng **marginal** `record_cost(model, cost_usd)`. `record_cost` không bao giờ được gọi với notional (grep xác nhận: `client.py:169,231,271` đều truyền `cost_usd`, =0 cho CLI).
4. Kết quả: `steps.py:1143` `_run_cost = _script_cost["total"] = 0` cho mọi run CLI → `write_pipeline_event(..., cost_usd=0)` (`:1148`) và `accumulate_cost` không được gọi (`:1151` `if _run_cost:` false).
5. `/api/budget` (`server.py:2232-2263`) tổng `cost_usd` từ `recent_results` và `cost_state.json` → **luôn $0 cho creepy**. Comment tự thú: "cost_state.json would otherwise read 0" (`:2236`).

Kết luận: **notional cost per-call ĐÃ có trong stdout log + `narrative_audit.json` (aggregate) nhưng có ZERO đường vào `pipeline_executions`, `usage_ledger`, `cost_state.json`, hay `/api/budget`.** Dashboard hiển thị $0.00 dù mỗi script creepy tốn notional thật.

### 1e. Frontend ĐÃ có chỗ cắm (không cần build UI mới)

Bundle `webui_v2/assets/index-DRL826G3.js` đã fetch: `api/pipelines/executions`, `api/budget`, `api/scheduler`, và render label "Chi phí" + `daily_spend`. Vậy **UI slot sẵn sàng**; vấn đề thuần là backend data = 0/rỗng.

### 1f. Chống máy-sleep: KHÔNG có gì trong code

Grep `SetThreadExecutionState|powercfg|schtasks|ES_SYSTEM_REQUIRED|caffeinate` toàn repo → chỉ khớp trong `IMPLEMENTATION_STATUS.md` (mô tả), `flow_browser.py` (không liên quan sleep), và docstring `run_seq_batch.py`/`batch_produce.py`. **Không có API call keep-awake, không Scheduled Task, không powercfg.** Batch chết khi Windows sleep là lỗ hổng đang mở (charter: đã mất 1 batch qua đêm).

### 1g. Bảng vault liên quan (đã tồn tại)

- `topics` (status queued/used/skipped, `vault/db.py:110-127`) — queue-space có sẵn.
- `usage_ledger` (cost_usd marginal, `:228-242`) — **không có cột notional**.
- `budgets` (limit/spent, `:244-256`) — chưa nối vào scheduler creepy.
- `pipeline_executions` (`executions.py:30-50`) — chỉ runner ghi; creepy không có row.
- Cost state hiện lưu ở **JSON file** `output/cost_state.json` (`api/state.py:241-269`), **vi phạm quy tắc CLAUDE.md "SQLite là SSOT, không tạo JSON mới cho dữ liệu cần query"**.

---

## 2. LỖ HỔNG (xếp theo tác động vào chất lượng/độ tin cậy video cuối)

**H1 — Batch creepy vô hình với hệ chính thức (tác động: tin cậy sản xuất).** Không executions row, không retry/timeout của runner, quota logic là grep string dễ vỡ. Nếu `claude_cli.py:319` đổi format hoặc quota hit ở stage khác không in ra stdout, batch ngủ sai/không ngủ → mất cả window (~2-3 run/5h). Không audit được "đêm qua chạy gì, pass/fail bao nhiêu". `run_seq_batch.py:88` chỉ ghi terminal line vào `summary.txt`.

**H2 — Máy sleep giết batch (tác động: mất sản lượng).** Đã mất 1 batch qua đêm. Zero cơ chế phòng vệ trong code. Đây là single point of failure cho toàn bộ throughput ban đêm.

**H3 — Cost dashboard mù với subscription (tác động: điều hành/ngân sách).** "Chi phí hôm nay" = $0.00 cho creepy dù đốt quota thật. Không thể trả lời "mỗi released script tốn bao nhiêu notional", không thể phát hiện run đốt quota bất thường, không nối `budgets` để chặn. Notional bị chôn trong JSON sidecar rời rạc.

**H4 — Bốn scheduler phân mảnh, mutual-exclusion tình cờ (tác động: throttle chết cả hai).** Charter luật #4: không chạy 2 pipeline LLM song song. Hiện in-app scheduler chỉ tránh batch nhờ `_scheduler_loop:282` check `active_jobs` — mà batch chỉ set active_job qua `_step_script:428` (best-effort, `if not _is_api`). Nếu race hoặc best-effort fail → hai hệ cùng gọi Claude → throttle chết cả hai. Không có khóa cross-process chính thức cho LLM (chỉ có xlock cho Flow browser trong `batch_produce.py`).

**H5 — Queue creepy không first-class.** Topic creepy đút tay qua argv (`run_seq_batch.py` nhận topic từ dòng lệnh), không đọc `topics.status='queued'` từ vault dù hạ tầng `get_next_topic` (`vault/db.py:827`) đã sẵn và đường in-app đã dùng. Không có "nguồn topic đơn" cho creepy.

**H6 — cost_state.json vi phạm SSOT.** Dữ liệu cost cần query lại nằm ở JSON file, không phải SQLite (CLAUDE.md cấm). Không rollover an toàn đa tiến trình, không join được với executions.

---

## 3. KẾ HOẠCH NÂNG CẤP (xếp theo tác động)

### P1 — Đưa cost notional vào vault + dashboard (tác động cao, effort **M**)
- **Mô tả:** Thêm cột `notional_cost_usd` vào `usage_ledger` (hoặc bảng mới `cost_ledger` per-run: execution_id, channel_id, role, effort, marginal_usd, notional_usd, calls, created_at). Ở cuối `_step_script`, ngoài `get_session_cost()` marginal, đọc `_narrative_result.aggregate_notional_cost_usd` và ghi một row cost vào vault; đồng thời truyền vào `write_pipeline_event(cost_usd=..., extra={notional_usd:...})`. Sửa `/api/budget` (`server.py:2232`) tổng thêm notional; expose `GET /api/cost/runs` per-run. Frontend đã có slot "Chi phí" → chỉ cần thêm field notional.
- **File đụng:** `vault/db.py` (schema + hàm insert/sum), `pipeline/steps.py` (chỉ vùng cost cuối `_step_script` ~1108-1158 — KHÔNG đụng phần narrative debate), `api/server.py` (`/api/budget`, endpoint mới), `api/state.py` (nếu chuyển cost_state sang vault). Contract narrative `aggregate_notional_cost_usd` chỉ đọc.
- **Rủi ro:** Thấp — chỉ thêm cột/đường ghi, không đổi hành vi gen. Cần migration idempotent (`ALTER TABLE ... ADD COLUMN` guarded).
- **Đo thành công khách quan:** Sau 1 batch creepy, `SELECT SUM(notional_cost_usd) FROM cost_ledger WHERE channel_id='true_dread_files_us'` > 0 và khớp (±1%) tổng notional trong các `narrative_audit.json` của batch đó; `/api/budget` trả về notional > 0; dashboard "Chi phí hôm nay" khác $0.00.

### P2 — Chống máy-sleep cấp OS (tác động cao, effort **S**)
- **Mô tả:** Hai lớp. (1) In-process: gọi `ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)` ở đầu `run_seq_batch.py` (và reset khi xong) — giữ máy thức suốt batch mà không đổi power plan vĩnh viễn. Mẫu ctypes Windows đã có tiền lệ trong repo (`batch_produce.py:42-56` dùng `windll.kernel32`). (2) Cấp OS bền hơn: một Windows Scheduled Task (`schtasks`) chạy batch với cờ "Wake the computer to run this task" + "Run whether user is logged on or not", thay cho Start-Process tay. Cung cấp file `.xml`/lệnh `schtasks /create` cụ thể cho máy Windows 11 này.
- **File đụng:** `scripts/run_seq_batch.py` (thêm keep-awake), file mới `scripts/omnicast_batch_task.xml` + `scripts/register_batch_task.ps1` (không đụng code chính).
- **Rủi ro:** Thấp. `SetThreadExecutionState` an toàn, tự hết khi process chết. Scheduled Task cần quyền admin một lần.
- **Đo thành công khách quan:** Chạy `powercfg /requests` khi batch chạy → thấy SYSTEM request từ python.exe; để máy idle qua ngưỡng sleep (vd 15 phút) trong lúc batch chạy → batch vẫn tiến (log tiếp tục có dòng mới sau mốc sleep). Chạy batch 3 topic qua đêm không mất run nào.

### P3 — Hợp nhất batch/quota vào scheduler chính thức (tác động cao, effort **L**)
- **Mô tả:** Biến quota-window thành first-class trong package. (a) Thêm `QuotaGate` (module mới trong `pipeline/`): lưu `reset_at` vào vault `system_state` khi `claude_cli` bắt session limit, thay vì grep stdout; runner check gate trước mỗi step LLM, ngủ tới reset. (b) Cho `PipelineRunner` một chế độ "queue-driven creepy": đọc `topics.status='queued'` (`get_next_topic`), chạy full spec, mark used — thay `run_phase2_unit_first.py` bằng `runner.run_file(default_channel.yaml)` để mọi run creepy có executions row + retry chuẩn. (c) Một khóa LLM cross-process chính thức (file lock trong vault/filesystem) để luật charter #4 được enforce, không còn tình cờ. (d) Tạo `creepy_channel.yaml` với `schedule:` để `PipelineScheduler` tự fire, hoặc giữ launch tay nhưng qua runner.
- **File đụng:** `pipeline/runner.py`, `pipeline/quota_gate.py` (mới), `pipeline/steps.py` (chỉ vùng cost/observability), `scripts/run_seq_batch.py` (rút gọn thành wrapper gọi runner), `pipelines/creepy_channel.yaml` (mới), `llm/claude_cli.py` (ghi reset_at vào vault thay vì chỉ log — vùng `:319-325`). Cẩn thận: `_step_script` phần narrative thuộc WS0 — chỉ đụng vỏ điều phối.
- **Rủi ro:** Trung bình-cao. Đây là refactor đường sản xuất đang chạy live của WS0. PHẢI phối hợp với WS0 (interface đóng băng, charter #3). TDD bắt buộc: test QuotaGate parse + sleep, test queue-drdriven run ghi executions. Không merge khi suite chưa xanh (charter #1, ≥1363 pass).
- **Đo thành công khách quan:** Sau hợp nhất: mọi run creepy tạo 1 row `pipeline_executions` (query đếm rows = số topic chạy). Mô phỏng session-limit (inject `reset_at` tương lai) → runner ngủ đúng tới mốc, không grep stdout. Chạy 2 batch cùng lúc → khóa LLM chặn cái thứ hai (log "waiting for LLM lock"), không còn double-throttle. `run_seq_batch.py` giảm còn <30 dòng wrapper.

### P4 — Queue creepy từ vault first-class (tác động trung bình, effort **S-M**)
- **Mô tả:** Nối topic generator (WS3 sẽ sản) vào `topics.status='queued'` cho creepy; batch/runner tiêu thụ qua `get_next_topic` thay argv. Ranking đã có (`list_topics` ORDER BY queued/score, `vault/db.py:821`).
- **File đụng:** `scripts/run_seq_batch.py` (đọc queue thay argv), có thể `pipeline/steps.py` discovery step. Phối hợp WS3.
- **Rủi ro:** Thấp. Hạ tầng đã có.
- **Đo thành công khách quan:** Chạy batch không truyền argv topic → nó tự lấy N topic queued cao điểm nhất, mark `used_at` sau mỗi run; `SELECT status, count(*) FROM topics` phản ánh đúng số đã tiêu thụ.

### P5 — Chuyển cost_state.json sang vault (tác động trung bình, effort **S**)
- **Mô tả:** Đọc/ghi cost qua vault (tận dụng row cost từ P1) thay `output/cost_state.json`, tuân CLAUDE.md SSOT. Rollover theo ngày bằng query, an toàn đa tiến trình.
- **File đụng:** `api/state.py:241-269`, `api/server.py:2232`.
- **Rủi ro:** Thấp, nhưng nên làm SAU P1.
- **Đo thành công khách quan:** Grep repo không còn ghi `cost_state.json`; `/api/budget` trả số từ vault; hai tiến trình ghi cost đồng thời không mất mát (test concurrent insert).

---

## 4. QUICK WINS (1 buổi)

1. **Keep-awake in-process (P2 lớp 1)** — thêm ~8 dòng `SetThreadExecutionState` vào `run_seq_batch.py` (mẫu ctypes đã có ở `batch_produce.py:42-56`). Xác minh ngay bằng `powercfg /requests`. Chặn đứng lỗ hổng "mất batch qua đêm" ngay tối nay. **Effort XS, tác động cao.**
2. **Ghi notional vào pipeline_event (nửa P1)** — tại `steps.py:1146` chuyền thêm `extra={"notional_usd": _narrative_result.aggregate_notional_cost_usd}` và cho `/api/budget` tổng field này. Không cần migration schema; dashboard hết $0.00 cho creepy. **Effort S.**
3. **Log batch → executions ngay cả đường tay** — trong `run_seq_batch.py` sau mỗi run, gọi `upsert_execution` (hoặc endpoint) ghi 1 row `pipeline_executions` với status từ terminal line (ACCEPTED/REJECTED). Executions dashboard hết mù với creepy trước khi làm P3 đầy đủ. **Effort S.**
4. **Đưa reset_at vào vault khi quota hit** — tại `claude_cli.py:325`, ngoài `logger.warning`, ghi `set_system_state("claude_reset_at", parsed)` (hàm `set_system_state` đã tồn tại, dùng ở `server.py:2647`). Bước đệm cho QuotaGate, và cho phép dashboard hiển thị "quota resets HH:MM". **Effort S.**

---

## Ghi chú phối hợp

- P3 đụng vỏ điều phối quanh `_step_script` — **bắt buộc phối hợp WS0** (charter #3, interface đóng băng). Chỉ đụng phần cost/observability/quota, không đụng debate narrative.
- Mọi thay đổi schema vault phải giữ tương thích bảng hiện có (charter #3 mục 4) và cập nhật `IMPLEMENTATION_STATUS.md` cùng nhánh (charter #5).
- Nhánh `ws/ops-scheduler-cost`; merge chỉ khi `python -m pytest tests/unit/ -q` xanh ≥1363 pass.

### File tham chiếu chính (tuyệt đối)
- `E:\Project\OmniCast Engine\implementation\scripts\run_seq_batch.py` — batch quota-aware ad-hoc
- `E:\Project\OmniCast Engine\implementation\scripts\run_phase2_unit_first.py` — driver gọi thẳng `_step_script`
- `E:\Project\OmniCast Engine\implementation\src\omnicast\pipeline\runner.py` — PipelineRunner + PipelineScheduler
- `E:\Project\OmniCast Engine\implementation\src\omnicast\pipeline\executions.py` — bảng `pipeline_executions`
- `E:\Project\OmniCast Engine\implementation\src\omnicast\pipeline\steps.py` (vùng cost ~1108-1166; quota grep contract ở `llm/claude_cli.py:319-325`)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\api\server.py` — scheduler `:216-345`, `/api/budget` `:2232`, `/api/scheduler` `:499`, `_auto_cycle_task` `:2977`
- `E:\Project\OmniCast Engine\implementation\src\omnicast\api\state.py` — cost_state.json `:241-269`
- `E:\Project\OmniCast Engine\implementation\src\omnicast\vault\db.py` — `topics` `:110`, `usage_ledger` `:228`, `budgets` `:244`, `get_next_topic` `:827`
- `E:\Project\OmniCast Engine\implementation\pipelines\default_channel.yaml` (không có `schedule:`), `policy_watcher.yaml` (có)
- `E:\Project\OmniCast Engine\implementation\batch_produce.py` — batch #2 (script+render pipelined), mẫu ctypes Windows `:42-56`