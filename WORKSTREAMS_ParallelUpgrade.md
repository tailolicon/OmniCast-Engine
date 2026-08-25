> STATUS: ACTIVE

# Chương trình nâng cấp song song — phân luồng & luật cách ly

Phương pháp đã chứng minh ở script-gen (chạy thật → autopsy → vá → test giữ):
15 vòng, 74→88 điểm, mỗi lớp lỗi thành gate vĩnh viễn. Nhân bản cho các phần còn lại.

## Luật cách ly (BẮT BUỘC cho mọi agent)

1. **Mỗi luồng một GIT WORKTREE riêng** — `git worktree add ../omnicast-ws-<tên> ws/<tên-luồng>`
   (thư mục NGOÀI repo gốc), làm việc + commit TRONG worktree đó. **CẤM checkout/switch
   nhánh trong thư mục gốc `E:\Project\OmniCast Engine`**: checkout đổi code trên đĩa
   dưới chân batch LIVE + các session khác (sự cố thật 14:31 19/07: session WS1 checkout
   `ws/visuals-flow` tại gốc giữa lúc batch self-storage đang gen và session WS0 đang
   commit — 2 commit dính chéo nhánh). Thư mục gốc Ở NGUYÊN `main`, thuộc WS0 + batch
   runner. Lưu ý worktree không có `.env`/`.venv`/`output` (gitignored) — luồng cần chạy
   test dùng `E:\Project\OmniCast Engine\implementation\.venv\Scripts\python.exe` với
   `cd` vào worktree. Merge vào `main` chỉ khi `python -m pytest tests/unit/ -q` xanh
   (≥1363 pass) — suite là cổng chung.
2. **Ma trận sở hữu file** (dưới đây) — agent KHÔNG đụng file ngoài phạm vi luồng mình.
3. **Interface đóng băng** (đổi phải qua điều phối, không tự ý):
   - Schema `script.json` sidecar (prosody: pace/pause_after_ms/emphasis)
   - Layout thư mục product (`script.txt`, `narrative_audit.json`, `meta.json`, `variants/`)
   - Schema `channels/*.json` + `NarrativeQualityStrategy`
   - Bảng vault.db hiện có
4. **Không chạy 2 pipeline LLM song song** trên 1 tài khoản Claude (đã đo: throttle chết cả hai).
   Luồng nào cần gen live phải xếp hàng qua batch runner.
5. Mọi thay đổi hành vi → cập nhật `IMPLEMENTATION_STATUS.md` cùng nhánh.

## Các luồng (ưu tiên theo tác động vào chất lượng video cuối)

### WS1 — Visuals / Flow consistency  🔴 khoảng trống lớn nhất
- **Phạm vi:** `media/browser_imagen.py`, `media/providers/` (flow, gemini image),
  `media/consistency_check.py`, `media/prompt_builder.py`, `media/style_guide.py`
- **Bằng chứng non nớt:** nhân vật đổi mặt theo từng frame (user report);
  Flow "Ingredients" (≤14 ảnh tham chiếu = nhân vật đồng nhất) đã research nhưng CHƯA implement;
  `consistency_check` chỉ verify + re-roll bounded, chưa chặn gốc.
- **Mục tiêu:** character consistency end-to-end (Ingredients qua browser automation),
  đo drift định lượng, gate ảnh trước render.
- **Cập nhật 2026-08-01:** đã build `omnicast/storyboard/` — cast registry theo video
  (character/location/prop/costume tách riêng, mỗi entity một reference sheet), token
  binding `[IMAGE n]` + role-separation clause, cổng liên tục fail-closed, rào duyệt
  cast của người, API + trang `/storyboard`. Gemini image provider nay nhận ordered
  reference images. Chi tiết + phần CHƯA làm: `IMPLEMENTATION_STATUS.md` §2 (bullet đầu).
  Còn lại của WS1: nối storyboard vào `render_real_video.py`/`veo_pipeline`, và **đo drift
  định lượng trên ảnh thật** (hiện mới gate ở tầng bố trí, chưa ở tầng pixel).
- **Cập nhật 2026-08-02:** nghiên cứu sâu 13 repo `_refs` bằng Grok Build CLI (7 report
  `docs/research/REFS_SB_01..07` + verify đối kháng `REFS_SB_00_VERIFY.md` + round-2 vá
  verbatim). Tổng hợp + kế hoạch thực thi: **`docs/research/WS1_Storyboard_Blueprint.md`**
  (P0: prompt_compiler ClipContract→prose; Interpolation Chain first+last; scene-only
  location frames; plan.json EDL; demo hoạt hình Short 9:16 + long 16:9 scene-plate).

### WS2 — TTS / giọng đọc
- **Phạm vi:** `media/tts.py`, `media/voice_router.py`, `media/providers/` (edge, kokoro, xtts),
  phần đọc prosody trong `render_real_video.py` (chỉ phần TTS)
- **Bằng chứng:** lịch sử "giọng robot đều đều"; kokoro per-scene speed không ăn;
  Edge chỉ rate/pitch, không SSML; chưa có đánh giá NGHE thật có hệ thống.
- **Mục tiêu:** benchmark nghe (đo pause/emphasis thật ra audio), multi-voice cho thoại,
  per-story voice variation khớp voice_seed của script.

### WS3 — Topic / Discovery pipeline
- **Phạm vi:** `discovery/`, `niche_flow.py`, `content_flow.py`, `agents/cross_video.py` (phần topic)
- **Bằng chứng:** topic đang đút tay; laundromat + ranger CẠN premise-space phải nghỉ hưu thủ công;
  chưa có đo "độ cạn" hay đề xuất topic tự động cho kênh narrative.
- **Mục tiêu:** topic generator cho kênh creepy (đo premise-space còn lại, tránh topic đã cạn,
  bám trend), nối vào batch runner.

### WS4 — Render engine hardening
- **Phạm vi:** `render_real_video.py` (trừ phần TTS của WS2), `media/render_engine.py`,
  `media/ffmpeg*`, `media/music_lib`, `subtitle_sync.py`, `qa_check.py`, `output_audit.py`
- **Bằng chứng:** monolith nghìn dòng đang port dở vào package; từng vỡ storyboard parser,
  WinError subtitle, card-beat phải vá nhiều lần.
- **Mục tiêu:** port vào package + test, EDL re-render per-segment, QA gate video mạnh hơn.

### WS5 — Ops / scheduler / cost
- **Phạm vi:** `pipeline/` (trừ steps.py phần narrative — thuộc WS0), `scripts/run_seq_batch.py`,
  `api/server.py` (endpoints ops), vault cost tables
- **Bằng chứng:** batch runner + quota-aware vừa vá ad-hoc ngoài scheduler chính thức;
  cost tracking notional chưa vào dashboard; máy sleep giết batch đêm.
- **Mục tiêu:** hợp nhất batch/quota logic vào scheduler chính thức, cost dashboard,
  chống máy-sleep (Scheduled Task OS-level).

### WS6 — Channel templating (nhân bản learnings)
- **Phạm vi:** `channels/*.json` (trừ true_dread), `config/narrative_quality.py` (profile MỚI),
  rubric cho forgotten_chronicles
- **Bằng chứng:** forgotten_chronicles cần rubric `narrative_story` riêng (pending từ trước);
  toàn bộ gate creepy là per-profile, kênh mới chỉ cần profile + benchmark.
- **Mục tiêu:** profile v1 cho kênh #2, checklist nhân bản.

### WS0 — Script-gen creepy (ĐANG CHẠY, KHOÁ)
- `agents/narrative_pipeline.py`, `config/narrative_quality.py` (profile true_horror),
  `pipeline/steps.py` phần narrative — vòng lặp live đang sửa liên tục.
  KHÔNG luồng nào khác đụng vào các file này.

### WS7 — Upload/Compliance  ⏸ BLOCKED
- Chờ user tạo Brand Channel + OAuth. Nghiên cứu được, không verify end-to-end được.

## Trình tự

1. Pha NGHIÊN CỨU (read-only, chạy được song song an toàn): mỗi WS một agent đọc sâu
   code + bằng chứng lỗi lịch sử → báo cáo hiện trạng + kế hoạch nâng cấp xếp hạng.
   **✅ XONG 19/07** — báo cáo tại `docs/research/WS2..WS6_*.md`; WS1 do session riêng
   thực thi thẳng (commit 874e471, chờ merge review).
2. Pha THỰC THI: mỗi WS một worktree, TDD, suite xanh mới merge; gen-live xếp hàng.
3. Mỗi WS lặp autopsy như script-gen đã làm.

## Pha thực thi — thứ tự ưu tiên (tổng hợp 19/07 từ 5 báo cáo)

Xếp theo tác động vào chất lượng VIDEO KẾ TIẾP; việc code-only làm được song song
ngay (không đụng quota), việc cần verify bằng render/gen thật thì xếp hàng.

| Ưu tiên | Việc | Nguồn | Effort | Vì sao trước |
|---|---|---|---|---|
| 1 | **WS2 quick wins audio**: bỏ guard-số `_scene_pitch` cho kênh `pacing_flat_ok`; nới atempo floor; script đo pause thực khớp `pause_after_ms`; spike Chatterbox A/B | WS2 §4 | S×4 | emphasis đang CHẾT IM LẶNG — mọi video creepy tới nay chưa từng có từ nhấn ra audio |
| 2 | **WS4-P1 QA thành gate cứng mọi đường exit** (`validate_video` exit non-zero; render_routes gọi `inspect_product`) | WS4 §3 | M | video đen/câm hiện có thể ship nếu render ngoài pipeline |
| 3 | **WS2 per-story narrator voice** (pool Edge + segment ordinal, deterministic) | WS2 §5 | M | 3 giọng-viết distinct thành 3 giọng-nghe distinct — nâng cảm nhận chất lượng rõ nhất |
| 4 | **WS3 quick wins topic**: `creepy_topic_status.py` (death-log + cờ retire); premise-space estimator prototype; generator format A | WS3 §5 | S×3 | vòng lặp gen đang ăn topic đút tay; đo premise-space TRƯỚC khi đốt quota |
| 5 | **WS5 anti-sleep** (Windows Scheduled Task / powercfg) + hợp nhất quota logic | WS5 | S-M | batch từng chết vì máy ngủ — loop phải sống qua đêm |
| 6 | **WS4-P2 characterization tests** bọc monolith render (tiên quyết mọi port; port hiện tại là STUB CHẾT — ffmpeg.py trả kết quả hard-code) | WS4 §1b/§3 | M | không có test thì mọi refactor render đều mù |
| 7 | **WS3 generator đầy đủ + vault wiring** (`upsert_topic status=queued`) | WS3 §3d | M | tự động hoá nguồn topic |
| 8 | **WS6 profile forgotten_chronicles** | WS6 | M-L | sau khi creepy ổn định — nhân bản learnings |

Cảnh báo chéo phải giữ: port render (WS4) PHẢI mang theo logic prosody của monolith —
đường package VoiceRouter hiện nuốt sạch speed/pitch/pause (WS2 §0, WS4-G5).
Ledger premise-space 5 trục (WS3-P7) chạm điểm ghi trong steps.py → điều phối với WS0.

**Bổ sung 25/07 (kiến nghị GPT, đã duyệt hướng):** NotebookLM = "Competitor Script
Research Module" — cohort winner+matched-control vào, evidence packet (hypotheses kèm
winner_frequency/control_frequency/quote) ra, playbook chỉ nhận rule có khác biệt
winner-control; writer vẫn là Narrative Engine. TIÊN QUYẾT: sửa competitor_intel chọn
mẫu theo outlier thay raw views (brief §4.1 — bug đã verify). NotebookLM không có API
công khai → OmniCast build Cohort Packet Exporter + Evidence Packet ingester/validator;
bước NotebookLM là thao tác tay trên web UI (user có Google AI Pro). Nghiệm thu bằng
A/B mù 5-vs-5 script trước khi tích hợp chính thức. Xếp P1 sau competitor-intel P0.

---

### WS8 — Reup video Trung Quốc (Douyin → dịch → lồng tiếng Việt)  🟢 MỚI 2026-08-08

**Mục tiêu:** tải video Douyin (không watermark) → ASR tiếng Trung → dịch zh→vi có ngữ
cảnh → phụ đề → lồng tiếng → mix → xuất. Chủ kênh không biết tiếng Trung nên **chất lượng
dịch + cổng QC là phần giá trị nhất**, không phải phần tải.

**Nguyên tắc:** không tự chế cơ chế. Lấy nguyên các stack đã được kiểm chứng.

#### Nguồn đã harvest

| Repo | License | Vai trò |
|---|---|---|
| `_refs/Tool_Reup_Douyin` (Reup Video) | không có LICENSE — **chủ dự án xác nhận repo cộng đồng, được lấy nguyên** | Toàn bộ pipeline dịch/lồng tiếng zh→vi (~10.7k dòng) |
| `_refs/douyin-downloader` | MIT | **Lớp tải chính** — ký `a_bogus`/`X-Bogus`, chọn URL không watermark |
| `_refs/f2` | Apache-2.0 | Dự phòng: signer thay thế, msToken thật |
| `_refs/Douyin_TikTok_Download_API` | Apache-2.0 | Đối chiếu endpoint, fallback `playwm`→`play` |
| `_refs/TikTokDownloader` | **GPL-3.0** | ⚠️ CHỈ ĐỌC — copy source sẽ lây GPL sang OmniCast |

Báo cáo nghiên cứu (Grok Build CLI, brief tại `docs/research/_briefs/v3/`):
- `docs/research/V3_D1_DouyinDownload.md` — 1306 dòng: chữ ký chống bot, bảng endpoint,
  suy ra URL không watermark, cấu hình transport, 15 cạm bẫy.
- `docs/research/V3_D2_ReupPipeline.md` — 6126 dòng: toàn bộ prompt, ngưỡng semantic QC,
  luật xưng hô, tham số TTS/mixdown, style ASS, project profile.

#### Đã làm (2026-08-08)

- `implementation/src/omnicast/reup/` — port 65 file từ `Tool_Reup_Douyin/src/app`
  (core, project, media, asr, translate, subtitle, tts, audio, ops, exporting).
  Bỏ `ui/` (PySide6). `core/jobs.py` viết lại headless: `Callback` thay Qt Signal,
  `ThreadPoolExecutor` thay `QThreadPool`, có khoá cho state dùng chung.
  26/26 module import sạch.
- `implementation/src/omnicast/ingest/douyin/` — facade + `_vendor/` (52 file MIT).
  `fetch_video(url, DouyinIngestConfig) -> DouyinAsset`. Tắt SQLite riêng của upstream
  (vault.db là SSOT) và bước transcribe OpenAI của nó (reup có ASR riêng).
- Deps mới: extra `reup` trong `implementation/pyproject.toml`.

#### Quyết định kiến trúc — ĐÃ SỬA 2026-08-08

Kết luận đầu phiên ("nhét cả schema reup vào `vault.db`, không phải rewire") **SAI**.
Cơ sở lúc đó là mọi bảng đều có `project_id` + FK, và `ProjectDatabase.__init__` chỉ nhận
một `path`. Nhưng đọc kỹ tầng truy vấn thì `ProjectDatabase.get_project()` là
`SELECT * FROM projects LIMIT 1` (`project/database.py:554`) và `list_job_runs(self)` cũng
không nhận `project_id` — tức code **giả định 1 project / 1 file DB**. Gộp nhiều project
vào vault.db sẽ khiến chúng đọc nhầm hàng của nhau, im lặng.

**Chốt lại:** mỗi job một `project.db` riêng trong workspace của nó (đúng hợp đồng của
code), còn `vault.db` giữ vai trò SSOT cho vòng đời job — bảng `reup_jobs` mới
(`reup/vault_link.py`): nguồn URL, aweme_id, project_root, stage cuối, số dòng chờ duyệt,
đường dẫn video xuất, lỗi. `project.db` là trạng thái làm việc, cùng hạng với thư mục cache
nằm cạnh nó.

#### Đã hoàn thiện (2026-08-08, phiên 2)

- **`reup/runner.py`** — `run_reup_job(url, ...)` chain đủ 10 stage:
  download → probe → extract_audio → asr → translate → subtitles → tts → voice_track →
  mixdown → export. Có `stop_after=<stage>` (dừng sau bất kỳ stage nào — hữu ích để soi
  bản dịch trước khi tốn tiền TTS) và callback `on_stage`. `build_reup_settings()` dựng
  `AppSettings` của reup in-memory từ config OmniCast, **không** đụng `%APPDATA%/ReupVideo`.
- **`reup/vault_link.py`** — bảng `reup_jobs` trong vault.db + `register_job` /
  `update_job` / `list_jobs` / `get_job`. Stage nào cũng ghi lại; job crash ghi
  `status=failed` kèm lỗi thay vì kẹt ở `running`.
- **`api/reup_routes.py`** — `POST /api/reup/run` (chạy nền, trả `job_id` ngay),
  `GET /api/reup/jobs`, `/jobs/{id}`, `/voices`, `/health`. Mount trong `server.py`
  bằng try-block riêng; media xuất serve ở `/reupmedia`.
- **`reup_douyin.py`** — CLI: `run` / `jobs` / `voices`.
- **`media/providers/tts_vieneu.py`** + đăng ký `vieneu` trong registry; pool giọng VN
  trong `voice_router.py` (xem mục TTS bên dưới).

#### Engine dịch — 3 backend, mặc định KHÔNG tốn API (2026-08-08, phiên 3)

Toàn bộ lời gọi LLM của reup đi qua đúng **một** hàm: `OpenAITranslationEngine.
_call_structured_output` → `client.responses.parse(...)` (Responses API + Structured
Outputs, chỉ OpenAI có). `llm_backends.py` khai thác seam đó bằng client giả có cùng
hình dạng `.responses.parse`, nên đổi backend là đổi 1 tham số:

| backend | Cách tính tiền | Ghi chú |
|---|---|---|
| `claude-cli` (**mặc định**) | Gói thuê bao Claude, **không tính token** | Dùng `omnicast/llm/claude_cli.py` sẵn có. Chậm nhất/lượt (spawn process) |
| `groq` | Theo token, rất rẻ + rất nhanh | Endpoint OpenAI-compatible; model open-weight yếu hơn ở xưng hô/ngữ vực → nhiều dòng cần duyệt hơn |
| `openai` | Đắt nhất | Đường gốc của upstream, có prompt caching |

**Bẫy đã gặp và vá:** `ClaudeCLIClient.complete_structured()` chỉ xin "JSON" rồi validate,
KHÔNG ép schema. Test 2 câu zh→vi nó trả `{"1": "...", "2": "..."}` thay vì
`{"lines":[{"id":..,"vi":..}]}` — pipeline khớp segment theo id nên payload đổi hình là
fail cả batch. `_ClaudeCLIResponses.parse` vì vậy tự dựng prompt có nhúng JSON Schema đầy
đủ + retry 1 lần với chính thông báo lỗi validate. Verify thật: 3 câu, đúng schema, và
model tự suy ra quan hệ vợ chồng giữ xưng hô anh/em nhất quán.

#### UI

`frontend_v2/src/pages/Reup.tsx` + mục **“Reup Trung Quốc”** trong nhóm *Sản xuất*
(`App.tsx`, icon `tiktok`). Có: thẻ preflight (ffmpeg / vieneu / faster_whisper /
translate_backend), ô dán link, chọn giọng (14 giọng nạp từ `/api/reup/voices`), chọn
engine dịch, chọn định dạng xuất, **dừng-sau-bước**, và bảng job poll 5s. Đã verify trên
backend thật: `ready:true`, 4/4 check xanh, `/api/reup/jobs` 200.

**Bẫy môi trường:** app chạy bằng `implementation/.venv` (xem `.claude/launch.json`),
không phải Python hệ thống. Đã cài `vieneu / pysubs2 / aiosqlite / gmssl` vào venv đó —
cài nhầm chỗ thì UI báo `✗ vieneu` dù CLI chạy được.

#### Chạy thật lần đầu — 2026-08-08, video `7671126668437720356`

Link test: `douyin.com/jingxuan?modal_id=7671126668437720356` —
《红魔猩猩》 của 沙雕阿豪, hoạt hình kinh dị, **8 phút 20 giây**.

Kết quả từng bước: tải **309 MB, 1920×1080 h264, 5.17 Mbps, không watermark**
(đúng bản gốc uploader nhờ `video_quality="highest"`) → probe → tách audio 16k/48k →
ASR **362 câu**, thoại tiếng Trung sạch → dịch contextual V2.

**Ba lỗi thật lộ ra khi chạy, đã sửa:**

1. **HTTP 200 rỗng = chống bot.** Gọi detail không cookie thì Douyin trả 200 nhưng body
   rỗng (đúng bẫy #4 trong `V3_D1`). Repo vendor ký được request nhưng **không tự tạo
   được cookie** — nó chỉ đọc cookie từ file. Thêm `ingest/douyin/cookie_bootstrap.py`:
   mở `douyin.com` bằng Playwright (OmniCast đã có sẵn cho Flow), nhặt `ttwid` +
   `s_v_web_id` ẩn danh, cache 7 ngày. Không cần đăng nhập. `DouyinIngestConfig.
   auto_cookies=True` là mặc định.
2. **`sync_playwright` trong event loop.** `fetch_video` là coroutine nên Playwright sync
   API từ chối chạy. `_harvest()` giờ tự phát hiện loop đang chạy và nhảy sang worker
   thread, giữ một entry point duy nhất cho cả caller sync lẫn async.
3. **`UNIQUE INDEX` sai trên `reup_jobs.project_id`.** Resume để chạy stage tiếp theo là
   job mới trên cùng project — hoàn toàn hợp lệ, nhưng index unique làm lần chạy thứ hai
   chết bằng `IntegrityError`. Đã đổi thành index thường.

4. **Nhãn cache-key bị dùng làm model id.** Để hai backend không dùng chung cache dịch,
   runner đặt `model = f"{backend}:default"` cho stage hash — nhưng chuỗi đó chảy tiếp
   xuống engine rồi tới `claude -p --model claude-cli:default` và chết vì model không tồn
   tại. Shim giờ `del model` và tự quyết model của mình (đặt ở constructor engine); cùng
   cách xử lý cho Groq.
5. **Resume chạy lại ASR.** `asr/persistence.py` có `build_asr_stage_hash` nhưng **không
   có hàm load** — upstream luôn transcribe lại. Với video 8 phút là mất thêm ~5 phút CPU
   mỗi lần resume. Runner giờ so stage-hash với `cache/asr/<hash>/segments.json` + số
   segment trong DB, khớp thì bỏ qua.

**Thêm `resume_project_root`** (`--resume <aweme_id>`): mở lại project có sẵn thay vì tải
lại. Mọi stage đều key theo stage-hash nên phần đã xong bị nhảy qua. Không có nó thì mỗi
lần muốn xem lại bản dịch phải tải lại 309 MB.

#### UI — bổ sung sau phản hồi "trông sơ sài" (2026-08-08)

Repo gốc có 8155 dòng UI / 7 tab (Dự án · ASR & Dịch · Phụ đề · Lồng tiếng · Xuất bản ·
Cài đặt · Nhật ký). Bản đầu của OmniCast chỉ có 1 form gửi job. Đã bổ sung phần cốt lõi
của vòng lặp thật, không đuổi theo đủ 7 tab:

- **Dải 10 bước** tô theo tiến trình từng job (`StageRail`).
- **Bảng đối chiếu Trung ↔ Việt** từng câu — `GET /jobs/{id}/segments`. Đây mới là thứ
  quyết định: chủ kênh không đọc được tiếng Trung nên nhìn con số không biết dịch đúng sai.
- **Duyệt tại chỗ** — `POST /jobs/{id}/segments/{sid}/review`, sửa text + bỏ cờ review,
  gọi `apply_segment_analysis_outputs` để đẩy bản duyệt xuống canonical segments. Mã lý do
  dịch sang tiếng Việt ("Không rõ ai nói", "Xưng hô chưa chắc") thay cho snake_case.
- **Panel ngữ cảnh** — `GET /jobs/{id}/context`: cảnh, nhân vật, bảng xưng hô mà bước dịch
  tự suy ra. Sai quan hệ ở đây rẻ hơn nhiều so với đọc lại từng dòng nó làm lệch.
- **Artifact** — `GET /jobs/{id}/artifacts`: SRT/ASS/mp4/wav đã sinh, link qua `/reupmedia`.

**Đặc tính cần biết của `claude-cli`:** mỗi lượt gọi = 1 lần spawn process, và contextual
V2 gọi nhiều lượt mỗi scene. Video 362 câu vì vậy chạy hàng chục phút. Đổi lấy: 0 đồng
token. Cần nhanh thì chuyển `--backend groq`.

#### Chất lượng bản dịch — đo thật, không phải suy đoán

16 cảnh / 362 câu, **16 phút** qua `claude-cli` (notional ~$2 nếu tính theo giá API;
thực tế 0đ vì gói thuê bao). **81/362 câu (22%) bị gắn cờ chờ duyệt.**

Điểm mạnh quan sát được — pipeline **tự sửa lỗi ASR bằng ngữ cảnh**:

| ASR nghe nhầm | Bản dịch ra | Nhận xét |
|---|---|---|
| `不属于野兽的清晰人生` (nhân sinh) | "giọng nói ấy rõ ràng không giống tiếng dã thú" | Suy đúng `人声` (tiếng người) từ ngữ cảnh |
| `一只红毛实验星星` (ngôi sao) | "Một sinh vật thí nghiệm lông đỏ" | Né bẫy `猩猩`/`星星` bằng cách nói bao quát thay vì dịch sai |
| `阿豪` | "A Hào" | Hán-Việt, không phải pinyin |
| `吓得我浑身发抖` | "Tôi sợ đến run cầm cập cả người" | Thành ngữ thuần Việt, không dịch chữ |

Phân bố lý do gắn cờ (top): `low_confidence_gate` 24 · `pronoun_without_evidence` 23 ·
`addressee_mismatch` 9 · `source_text_garbled` 7 · `ambiguous_term` 4 ·
`subtitle_tts_divergence` 4 · `honorific_drift` 1 · `asr_error_suspected` 1.

Đáng giá nhất: `pronoun_without_evidence` — nó **tự khai** là đã chọn anh/em/tôi mà chưa
đủ căn cứ, thay vì đoán im lặng. Đúng thứ cần cho người không đọc được tiếng Trung.

#### Cổng duyệt + cache resume — đã thực thi và kiểm chứng

**Cổng duyệt** (`allow_pending_review`, mặc định `False` / CLI `--force`): chặn trước
bước `tts` khi còn câu chờ duyệt. Lý do đặt ở đây chứ không ở `export`: phát hiện dịch sai
sau khi lồng tiếng nghĩa là làm lại TTS + track giọng + hai lượt ffmpeg. Chạy thử không
`--force` trên video thật → dừng đúng chỗ:
`FAILED: 81 câu đang chờ duyệt — duyệt trong tab Reup ... trước khi lồng tiếng.`

**Cache resume** — thiếu 2 chỗ, đã vá, đo thật trên video 8 phút:

| Stage | Trước | Sau |
|---|---|---|
| download | tải lại 309 MB | bỏ qua (`--resume`) |
| asr | transcribe lại ~5 phút CPU | `dùng cache` |
| translate | **dịch lại 16 phút + token** | `dùng cache` |

Cả lượt resume giờ chạy trong vài giây thay vì hơn 20 phút. Cache dịch nằm ở
`cache/translate_contextual/<stage_hash>/contextual_translation.json` (không phải
`cache/translate/` — tên thư mục khác với tên stage, dễ tìm nhầm).

#### Căn tốc độ đọc — vấn đề thật, đo được, đã sửa (2026-08-08)

User phát hiện: giọng đọc lúc nhanh lúc chậm theo độ dài câu. Đo trên video thật:
**tiếng Việt cần 725s nhưng slot tiếng Trung chỉ 490s — dôi 48%.** `build_fit_filter`
của `Tool_Reup_Douyin` ép từng câu vào đúng slot gốc bằng `atempo` **không giới hạn**:

| | Trước |
|---|---|
| Câu bị tua nhanh | 327/362 (90%), mỗi câu một hệ số |
| Hệ số | p50 1.52× · p90 2.07× · **max 3.22×** |
| Câu >2× (méo tiếng) | 38 |

`pyvideotrans/task/_rate.py` giải khác: **chặn tốc độ giọng, giãn video gánh phần dư**
(`setpts`). Luật gốc là ">1.2× thì audio và video mỗi bên gánh một nửa"; ta chặn cứng ở
1.2× để giọng thật sự đều (tham số `max_audio_speed`).

- **`audio/rate_align.py`** — bộ lập kế hoạch thuần (12 test). Nới slot tới đầu câu kế →
  vừa slot thì chèn im lặng → dôi ≤1.2× thì chỉ tua audio → dôi hơn thì giữ audio ở 1.2×,
  phần còn lại đẩy sang `video_pts`.
- **`media/retime.py`** — thực thi: cắt từng đoạn `-ss/-t`, `setpts`, `-g 1`, nối theo lô
  60 (362 input quá dài cho một dòng lệnh ffmpeg). Kèm `shift_subtitle_rows` — **giãn video
  mà không dịch timeline phụ đề thì mọi câu sau chỗ giãn đầu tiên sẽ lệch**.
- **Sai số `setpts` đã bù:** đo trên 8 câu, video ra hụt 160ms so với giọng (~0.9%); qua
  362 câu sẽ dồn thành ~7s. Thêm bước `tpad=stop_mode=clone` giữ khung cuối → lệch còn
  **6ms**.

Kết quả kế hoạch trên video thật: mọi câu **đều 1.2×**, 0 câu >2×, video 8'20" → **10'30"**
(giãn 1.26×). Nới trần lên 1.35× thì còn 9'37". CLI: `--max-audio-speed`, `--no-rate-align`.

**Tiếng nền đã giữ lại (user yêu cầu):** `_stretch_original_bed` cắt bed gốc theo từng
đoạn rồi `atempo=1/video_pts` để nó chậm đúng bằng hình (atempo giữ nguyên cao độ nên nhạc
không bị méo giọng). Đo trên 8 câu: video 18.27s · giọng 18.26s · **bed 18.26s** — ba track
khớp. Mixdown giờ luôn chạy, dùng `retimed.original_bed_path` khi có.

#### Giọng CapCut — `capcut:` chạy được, nhưng KHÔNG phải giọng ByteDance

User tự thêm `media/capcut_voices.py` (catalog 70+ speaker id) + `/api/voices/capcut`.
Đó là **danh mục metadata**, không tổng hợp giọng — docstring của nó ghi rõ là cố ý không
gọi API TikTok không chính thức, và khai `edge_fallback` cho các id có đường hợp lệ.

`media/providers/tts_capcut.py` biến spec `capcut:<id>` thành giọng chạy được. Định tuyến
2 tầng:

1. **Có key Volcengine → giọng ByteDance THẬT.** `media/providers/tts_volcengine.py` port từ
   `_refs/pyvideotrans/videotrans/tts/_doubao2.py`: `POST openspeech.bytedance.com/api/v3/tts/
   unidirectional`, header `X-Api-App-Id` + `X-Api-Access-Key`, model `seed-tts-2.0-standard`,
   stream JSON→base64 PCM→WAV 48kHz. Đây là **API chính thức của ByteDance**, cùng họ engine
   CapCut dùng. Mẹo để đọc tiếng Việt bằng speaker tiếng Trung:
   `additions={"explicit_language":"crosslingual","enable_language_detector":"true"}` —
   đúng cách CapCut phục vụ nhiều ngôn ngữ trên một bộ giọng.
   Cần `VOLCENGINE_TTS_APPID` + `VOLCENGINE_TTS_ACCESS_TOKEN` trong `.env`.
2. **Không key → Edge fallback** như catalog khai. Vẫn ra tiếng, nhưng khác giọng.

**Đính chính catalog:** `BV074_streaming` được gán nhãn "Vietnamese Female" nhưng thực tế
là **giọng nữ Malaysia (马来女声)** của Volcengine. Bản đồ `_VOLCENGINE_EQUIVALENT` trỏ nó
sang `zh_female_vv_uranus_bigtts` (Vivi) đọc chéo ngôn ngữ.

Giọng không có fallback (Ghost Face, preset hát) thì **báo lỗi** thay vì thay giọng khác;
40/70 id có đường hợp lệ.

**Lỗ hổng gốc rễ (phát hiện khi chạy thử):** `reup/tts/factory.py` chỉ biết `sapi` và
`vieneu` rồi `raise` — nghĩa là **toàn bộ registry provider của OmniCast không dùng được
trong job lồng tiếng**, bất kể preset ghi gì. Provider `capcut` có làm xong cũng vô dụng.
Đã bắc cầu `reup/tts/router_engine.py` (`VoiceRouterTTSEngine`) + factory fallthrough: tên
engine nào có trong registry thì route qua `VoiceRouter`. `voice_id` giờ nhận cả spec đầy
đủ (`capcut:BV074_streaming` đổi luôn engine) lẫn tên trần (`Mai Anh` giữ engine cũ).

**Hai bug prosody khi bắc cầu:**
1. Provider `capcut` khai `**prosody` nên router truyền hết, rồi forward thẳng `speed=`
   sang Edge → `TypeError`. Phải `_supported_prosody` lần nữa theo chữ ký provider đích.
2. Router lọc prosody **theo tên chứ không theo kiểu** — Edge nhận `volume` dạng chuỗi SSML,
   preset reup đưa float → `volume must be str`. Cầu nối gửi cả hai quy ước (`speed` số cho
   Kokoro/VieNeu + `rate` chuỗi `-7%` cho Edge/Azure) và **bỏ hẳn `volume`** vì mixdown đã
   set mức giọng, gửi thêm sẽ nhân đôi.

**Bẫy mặc định giọng:** preset ship `voice_id="default"`, và mặc định của VieNeu là
**"Minh Đức" — giọng NAM**. Cả video 10 phút lồng bằng giọng nam mà không log nào báo.
Đã đặt `DEFAULT_VOICE_ID = "Mai Anh"` ở runner/CLI/API — không thừa hưởng mặc định engine nữa.

#### Dịch tiêu đề (user yêu cầu 2026-08-08)

`translate/title.py`: tiêu đề Douyin không phải câu để dịch thẳng mà là hook + đuôi hashtag
dính liền (`一口气看完《红魔猩猩》 #沙雕动画#恐怖故事…`). Nên tách hashtag ra xử lý riêng, và
**viết lại** tiêu đề thay vì dịch chữ. Có truyền vài câu thoại đầu làm ngữ cảnh — khác biệt
rõ rệt:

- Không ngữ cảnh: "xem trọn bộ: hồng ma tinh tinh"
- Có ngữ cảnh: **"Xem trọn Hồng Ma Tinh Tinh: Quái vật thí nghiệm sổng chuồng"**

Tags cũng dịch: `细思极恐` → "Càng nghĩ càng rợn". Dùng chung engine với phần thân nên
`claude-cli` thì tiêu đề cũng 0đ. Lỗi engine **không làm hỏng job** — trả tiêu đề rỗng để
người dùng tự đặt, vì bản dịch và audio vẫn dùng được. Lưu ở `reup_jobs.title_vi/tags_vi`
(có migration ALTER cho DB cũ), hiện lên UI ưu tiên trước tiêu đề gốc.

#### Chọn giọng — đo trực tiếp, cùng video cùng thiết lập (2026-08-08)

| | VieNeu Mai Anh | Edge (qua ô `capcut:`) |
|---|---|---|
| Câu phải giãn video | 274/362 | **360/362** |
| Video ra | **10:30** | **14:50** |
| So với gốc 8:20 | +26% | **+78%** |
| Sample rate | 48 kHz | 24 kHz |
| Độ ổn định | 362/362 | **chết ở clip 255** (rate limit) |
| Lệch hình/tiếng | 6 ms | 13 ms |

Edge đọc chậm hơn **62%** (cùng 9 câu: 25.4s vs 15.7s), nên gần như mọi câu tràn slot và
video phồng gần gấp đôi bản gốc. Với reup thì đó là đổi hẳn nhịp video, không còn là
đăng lại nữa. **VieNeu là mặc định hợp lý; Edge chỉ nên dùng khi cần đúng ô `capcut:`.**

**Edge fragility:** endpoint công cộng từ chối sau ~255 request liên tiếp
(`No audio was received`). Retry cũ 3 lần lùi tuyến tính = 4.5s, quá ngắn. Đã nâng
`_MAX_ATTEMPTS=6` + lùi cấp số nhân 2→4→8→16→32s (`providers/tts_edge.py`). Cache clip
theo nội dung nên lần chạy lại nối tiếp từ chỗ chết, không mất công.

#### Giọng CapCut — trạng thái chốt

CapCut lưu audio đã sinh ở `%LOCALAPPDATA%/CapCut/User Data/Cache/tts/` (có `lru_cache.json`),
nên **đọc ngược lại được**. Đường khả thi: OmniCast xuất draft CapCut (`com.lveditor.draft`,
`draft_content.json` với `materials.texts` + tracks) → người dùng bấm Generate speech →
OmniCast đọc audio từ cache → chạy tiếp. Đây đúng mô hình Cap Assistant dùng. Cần một lần
sinh thật để biết format file/cách map; **chưa làm được vì tài khoản không có Pro**.

Chủ dự án yêu cầu lấy giọng **không cần đăng nhập** — **đã từ chối**: đó là đi vòng qua
kiểm soát truy cập và tường phí của dịch vụ trả tiền. Ba đường hợp lệ còn lại: (a) giọng
free không có vương miện trong chính CapCut của họ, (b) Volcengine API chính thức
(provider đã sẵn, chỉ thiếu 2 biến `.env`), (c) nâng CapCut Pro.

#### Lớp phủ kéo-thả — che chữ Trung, logo, watermark, vị trí phụ đề (2026-08-09)

User yêu cầu: tự tay che dòng chữ Trung còn lại (sub gốc + chữ trên đầu khung), logo kênh
ở góc tuỳ chỉnh, watermark mờ chạy vòng chống ăn cắp, chỉnh được kích thước + độ mờ mọi
lớp, chỉnh cỡ chữ phụ đề Việt, và kéo được cả vị trí phụ đề. **Kéo thả thủ công, không
tự động dò chữ** (user chốt: "là tạo chức năng để tôi kéo thả vị trí che, không cần tự động").

- **`reup/media/overlay.py`** — `CoverRegion` (toạ độ dạng phân số 0–1 nên đổi độ phân giải
  không lệch; mode `blur|pixelate|box` + `strength` + `opacity`), `LogoOverlay`,
  `RoamingWatermark`, `SubtitleStyle`, `OverlayConfig` + `load_config`/`save_config`.
  Ba hàm dựng filter tách riêng để test được mà không cần chạy ffmpeg.
  **Hai bẫy ffmpeg đã ghim bằng test:** `crop`/`drawbox` đọc `iw/ih` nhưng `overlay` chỉ
  biết `W/H` (dùng nhầm → "Undefined constant"), và `drawtext` trên bản Windows không có
  fontconfig nên bắt buộc `fontfile=` với dấu `:` escaped.
- **`subtitle_anchor_from_fraction()`** — libass chỉ neo theo **9 điểm kiểu bàn phím số**,
  nên điểm thả được quy về ô tương ứng rồi lấy khoảng cách tới cạnh của neo đó làm lề.
  Hệ quy chiếu **384×288** — mặc định libass khi ASS không khai `PlayRes`; đó cũng là lý do
  FontSize 12 lại vừa mắt trên 1080p (×3,75).
- **Thứ tự filter:** resolution → cover → `ass=` → logo → roaming. Che TRƯỚC khi in phụ đề,
  vì blur sau sẽ nhoè luôn chữ Việt; đổi lại phụ đề **được phép đè lên vùng che**.
- **`frontend_v2/src/pages/ReupOverlayEditor.tsx`** — kéo/resize khung che trên khung hình
  thật (`GET /jobs/{id}/frame`), marker phụ đề kéo được, slider cho mọi tham số, nút Xem thử
  render 1 khung (~0,5s) và Lưu.
- **Bẫy cache đã vá:** `build_hardsub_stage_hash()` không tính lớp phủ → đổi vùng che rồi
  xuất lại **trả về file cũ tức thì, không có vùng che**. Đã tái hiện bằng số: hash tính lại
  từ input thật khớp đúng manifest cũ `fb27ede…`. Nay key có
  `OverlayConfig.render_fingerprint()`, và **chỉ thêm khi có lớp thật sự vẽ ra pixel** để job
  chưa từng dùng lớp phủ giữ nguyên cache. Style phụ đề cố ý KHÔNG vào key: nó đi trong file
  `.ass`, mà export đã fingerprint file đó rồi.
- **Chi phí xuất, đo thật** (video 9'16", 1080p30, CRF 18, preset medium): **195s = 3,25 phút,
  2,85× realtime**, ra 174,7 MB. Lớp phủ gần như miễn phí — cùng lát 45s: chỉ phụ đề 10,1s →
  +1 vùng che 10,5s → +roaming 11,1s. Lý do: burn-in phụ đề vốn đã bắt re-encode h.264, che
  chỉ là thêm filter vào cùng một lượt. **Cảnh báo đo lường:** đặt `-ss` ở phía OUTPUT làm
  ffmpeg vẫn decode + filter toàn bộ phần bị bỏ, cho ra ước lượng phồng tới 3–5× — phải đo
  bằng lượt xuất đầy đủ hoặc `-ss` phía input.
- **`POST /jobs/{id}/export` MỚI** — trước đó bấm Lưu xong **không có đường nào ra video**:
  chỉ ghi `overlays.json`, muốn thấy kết quả phải chạy lại cả job. Endpoint này chạy đúng
  bước export trên nền: sinh lại `.ass` từ style hiện tại (nếu không, cỡ chữ/vị trí chọn
  trong UI không bao giờ tới bản burn-in) rồi burn với lớp phủ đã lưu — không tải lại,
  không dịch lại, không lồng tiếng lại. Nút "Lưu & xuất video" + poll trạng thái trong editor.
  `vault_link.update_job()` thêm tham số `exported_video` (truyền `result` giả sẽ xoá trắng
  mọi cột khác của hàng job).
- **Bug "không thêm được vùng che"** (user báo 2026-08-09): nút chạy đúng nhưng mọi vùng mới
  đều rơi vào cùng toạ độ mặc định, nằm khuất sau vùng cũ → nhìn như không có gì xảy ra
  (config của user lúc đó đã có 2 vùng chồng nhau mà không biết). Sửa: `nextCover()` xếp bậc
  vùng mới, tự chọn nó, và thêm hàng chip đếm/chọn từng vùng — sân khấu không thể hiện được
  vùng bị vùng khác che kín.
- **Mặc định theo KÊNH (2026-08-09):** trước đó lớp phủ chỉ sống trong `overlays.json` của
  từng project — mỗi video reup phải nhập lại logo, watermark, cỡ chữ; và **job reup chưa
  từng gắn kênh nào** (`channel_id=None` cho cả 18 job) vì form tạo job không có ô chọn.
  Nay: (a) form có ô **Kênh** (đọc `/api/channels`) và gửi `channel_id`; (b) mặc định lưu
  vào chính `channels/<id>.json` khoá `reup_overlays` — **không tạo store mới**, đúng file mà
  renderer đã coi là nguồn sự thật per-channel; (c) runner seed overlays từ kênh ngay lúc
  bootstrap project, nên mọi bước sau chỉ đọc bản copy của job (kéo lại vùng che cho video
  này không đụng kênh); (d) `load_config(root, channel_file)` fallback về kênh cho job cũ;
  (e) nút **"Lưu làm mặc định kênh"** (`as_channel_default`) — promote là hành động rõ ràng,
  vì vùng che thường đặc thù từng video, ghi đè ngầm sẽ sai. `save_channel_defaults()` merge
  vào payload sẵn có (không xoá `voice_profile`/brand của kênh).
- **LỆCH TIMING PHỤ ĐỀ — lỗi của chính endpoint re-export (user báo 2026-08-09, đã vá):**
  `POST /jobs/{id}/export` bản đầu sinh lại `.ass` từ `database.list_segments()` — **sai
  bảng**. Runner dùng `list_subtitle_events()` của active track, và sau khi rate-align nó
  còn `shift_subtitle_rows()` mọi dòng sang timeline đã giãn rồi mới export. Bản re-export
  bỏ qua bước dịch timeline → phụ đề nằm trên timeline GỐC trong khi hình + tiếng đã giãn:
  đo được `track.ass` sai kết thúc ở **8:19.75** trong khi video dài **9:15.82** — cuối phim
  lệch ~56 giây. (Bằng chứng trên đĩa: `68ededb67e/track.ass` mtime 00:45 = bản hỏng do
  re-export sinh ra, `c7fe4f9e6e/track.ass` mtime 23:11 = bản đúng do runner sinh ra.)
  Vá 3 lớp: (1) `retime.py` ghi `cache/retime/timeline.json` (index → start/end đã giãn) —
  trước đó timeline chỉ sống trong RAM của lượt chạy, không ai dựng lại được;
  `load_timeline()` + `shift_rows_to_timeline()` dùng chung với `shift_subtitle_rows()`.
  (2) Re-export lấy đúng subtitle events + `allow_source_fallback=False` (bật sẽ nhét lại
  chữ Trung vào dòng chưa có bản dịch) và shift theo timeline.json. (3) Job cũ chưa có
  timeline.json: **cấm dựng lại events**, thay vào đó `restyle_ass()` lấy chính file `.ass`
  runner đã ghi trong `extra_json.subtitle_paths` và chỉ viết lại dòng Style — giữ nguyên
  timing đã được chứng minh đúng. Không tìm thấy bản nào khớp thì **trả 409**, không xuất
  đại. Đã xuất lại video của user bằng đường (3): phụ đề chạy tới 9:15.82, khung 9:00 có
  thoại đúng cảnh (trước đó trắng vì track hết từ 8:19).
- Test: `tests/unit/test_reup_overlay.py` 35 ca + `test_reup_retime.py` +4. Suite: 2786 pass / 6 skip.

#### Hồ sơ tốc độ end-to-end + 2 tối ưu (2026-08-09)

Đo lại lượt chạy đầy đủ tối 08-08 bằng mtime từng thư mục cache (video 9'16", 362 câu):

| Bước | Thời gian | Ghi chú |
|---|---|---|
| ASR | ~5 ph | faster-whisper |
| Dịch | ~16 ph | claude-cli, tuần tự theo scene |
| **TTS** | **39,3 ph** | **chiếm hơn nửa tổng thời gian** |
| Retime | 12,3 ph | 362 câu × 3 lệnh ffmpeg |
| Mix | <1 ph | |
| Export | 3–6,5 ph | |

**Đã tối ưu:** (1) `retime_to_plan` chạy phần cắt từng câu bằng `ThreadPoolExecutor`
(`_cut_workers()` = nửa số core, chặn 2–8, env `OMNICAST_REUP_CUT_WORKERS`) — trước đó
hơn 1000 tiến trình ffmpeg chạy tuần tự, mỗi cái là một burst ngắn rồi máy nằm không.
Chỉ phần cộng dồn cursor còn tuần tự. (2) **Encoder GPU** cho export: `h264_nvenc` vào
`VIDEO_CODEC_MAP` + nhánh rate-control riêng (**NVENC không nhận `-crf` lẫn tên preset của
libx264** — gửi nhầm là chết giữa lượt encode), `gpu_encoder_available()`, tham số
`POST /jobs/{id}/export?gpu=`, checkbox GPU trong editor (mặc định bật).

**Số đo thật (đừng tin ước lượng cũ):** libx264 `medium/crf18` vs nvenc `p5/cq25` trên cùng
video: **189s → 75s, 182,3 MB → 175,9 MB** (GPU nhanh hơn *và* nhẹ hơn). Chạy qua API thật
trên máy đang tải: **389s → 180s = 2,2×**. Phân biệt encoder bằng `profile`: libx264 ra
`High`, nvenc ra `Main`.

**Hai cạm bẫy đo lường trong đợt này:** (a) `-ss` phía OUTPUT làm ffmpeg vẫn decode+filter
hết phần bị bỏ → ước lượng phồng 3–5×; (b) **page cache**: lượt chạy đầu tiên nạp file 323 MB
vào cache nên lượt sau nhanh giả tạo — đo song song vội vàng ra "2,44×", warm cache xong chỉ
còn **1,2–1,34×**. Luôn warm-up rồi đo, và đo lại theo thứ tự ngược.

**KHÔNG tối ưu (đã đo, không đáng):** thread-pool cho TTS VieNeu chỉ được **1,14×** (6 câu:
19,2s → 16,9s) vì model đã ăn hết CPU. Muốn nhanh phải đổi engine mạng (CapCut/Volcengine
song song được) hoặc chấp nhận ~6,5s/câu — nhưng **song song hoá TTS mạng phải kèm giới hạn
nhịp**: Edge-TTS đã từng chết ở clip 255 vì rate limit khi chạy tuần tự. Dịch: backend Groq
có sẵn và nhanh hơn claude-cli nhiều, chưa đo được vì máy chưa cấu hình key.
  **Chạy thật 2026-08-09:** re-export qua endpoint mới hết ~4 phút (kèm sinh lại phụ đề),
  ra 172,9 MB; khung 62s xác nhận sub Trung dưới đáy bị blur, phụ đề Việt nằm đè lên trên,
  watermark `@Kenh` chạy. Style trong `.ass` sinh ra khớp đúng UI (Arial 16 / Outline 3 /
  Alignment 2 / MarginV 17).

#### Danh sách giọng bị cắt còn 1 engine (user báo 2026-08-09, đã vá)

`GET /api/reup/voices` hardcode `get_tts_provider("vieneu")` → dropdown chỉ có 14 giọng
VieNeu, trong khi registry có **277 giọng / 9 engine**, gồm **capcut 129** và
**volcengine 102** — tức giọng CapCut mà user muốn đã có sẵn trong code nhưng UI không
đường nào chọn. Nay endpoint trả `groups` (theo engine, VieNeu → CapCut → Volcengine → còn
lại) + `voices` phẳng giữ tương thích; engine nào load lỗi thì trả `error` cho riêng nhóm đó
chứ không làm trắng cả danh sách. Dropdown render `<optgroup>` và **value là spec đầy đủ
`engine:voice_id`** — tên trần giữ engine của preset, nên `capcut:` phải đi kèm thì giọng
CapCut mới thật sự chạy CapCut.

#### Lồng tiếng chạy song song cho engine mạng (2026-08-09)

`synthesize_segments` là vòng lặp tuần tự 1 câu/lần. Tách làm 2 pha: pha giải quyết
(cache hit, chọn engine/preset, tính đường dẫn — rẻ, giữ tuần tự) và pha tổng hợp
(`_synthesize_pending`, phần chậm). Pha 2 chạy `ThreadPoolExecutor` **chỉ cho engine mạng**
(`capcut`/`volcengine`/`edge`/`chatterbox`, mặc định 4 luồng, env `OMNICAST_REUP_TTS_WORKERS`);
engine local giữ 1 luồng vì **đã đo VieNeu chỉ được 1,14×** — model ăn hết CPU rồi.
Mỗi clip ghi vào **slot cố định** (`_PendingClip.slot`) chứ không `append`: pool trả kết quả
theo thứ tự hoàn thành, append là lồng tiếng ra sai thứ tự câu. Số luồng để thấp có chủ đích
— Edge-TTS từng dính rate limit chết ở clip 255 ngay cả khi chạy tuần tự. Test: 6 ca
(slotting, pool thật sự chồng lấn, lỗi 1 clip phải nổi lên thay vì để lỗ hổng, override env).

#### Danh sách giọng: mặc định hiển thị sai + API chậm

Ô "Giọng đọc" ghi "VieNeu — mặc định" nhưng preset `vieneu-default-vi` đã đổi
`engine=capcut, voice_id=BV074_streaming` → nhãn sai, giá trị rỗng thật ra là CapCut
Cô Gái Hoạt Ngôn. Đã sửa nhãn và hiện "Đang tải danh sách giọng…" khi chưa có dữ liệu —
trước đó dropdown chỉ có 1 mục nên **trông như không đổi được giọng**. `/api/reup/voices`
thêm cache tiến trình (build nguội ~9s vì import mọi backend TTS).
**Chưa xong:** server đo được 16–48s cho MỌI endpoint (kể cả `/api/reup/jobs` = 1 câu SELECT,
`/api/status`), trong khi gọi thẳng hàm trong tiến trình chỉ 0,03s và vault.db mở tức thì.
Tức nghẽn nằm ở tầng phục vụ HTTP chứ không phải handler — chưa tìm ra, phải điều tra riêng.

#### Ba mặc định sai + job xong vẫn báo "running" (2026-08-09)

Chạy đầy đủ một video mới lộ ra bốn thứ:
1. **`ReupRunRequest.voice_id` mặc định `"Mai Anh"`** — caller nào không nhắc tới giọng thì
   **ghi đè luôn preset CapCut của user**, ra nguyên video giọng VieNeu mà trong request không
   có gì nói vậy (manifest xác nhận: `engine=vieneu, voice_id=Mai Anh, 369/369 clip`). Cùng
   loại bẫy đã ghi trước đó ở CLI `--voice`. Nay mặc định `None` = dùng preset.
2. **`DEFAULT_VIDEO_QUALITY = "highest"`** dò bản gốc của người đăng: đo được 2560×1440 /
   20 Mbps / **1,48 GB**, xuất ra 669 MB — quá nặng cho thứ vẫn giao ở 1080p. Đổi mặc định
   sang `"1080p"`; muốn bản gốc thì truyền `video_quality="highest"`.
3. **Không tải cover.** Vendor có sẵn nhánh `config["cover"]` nhưng facade chưa bật. Nay bật,
   `DouyinAsset.cover_path` mới, và publish đặt thành `thumb.jpg` trong thư mục sản phẩm.
4. **`_announce("done", …)` ghi đè `status` về `"running"`** ngay sau khi `_done("export")` đã
   set done/review — nên **mọi job hoàn thành đều nằm trong danh sách ở trạng thái "running"**
   với đủ chip xanh, không phân biệt được với job treo thật (đúng mấy dòng user thấy hôm nay).
   Nay stage sentinel `done` không đụng vào status. Kèm: `result.exported_video` trỏ vào
   product thay vì bản nháp trong workspace.
Thêm chặn **xuất thủ công khi job đang chạy** (409): pipeline tự xuất ở cuối job, bấm xuất
đè lên là hai ffmpeg ghi cùng file đích và cùng `.partial` — đúng va chạm đã tạo ra video
hỏng NAL. Test +8.

#### Chạy lại video ĐÃ TẢI thì chết ở bước tải (user báo 2026-08-09)

Chip "Tải video" mới thêm đã chỉ đúng chỗ ngay lượt đầu: job fail tại `download` với
`Total: 1, Success: 0, Failed: 0, **Skipped: 1**`. Tức downloader báo "file có sẵn rồi,
không cần tải" — còn facade lại đọc `result.success < 1` là **lỗi**. Nghĩa là mọi lần chạy
lại một video đã tải đều chết ngay bước đầu, đúng lúc người ta đang retry. Vá: coi
`skipped >= 1` là đã có hàng (manifest + file trên đĩa vẫn được kiểm sau đó). Đo: re-fetch
video đã tải xong trong **0,0s**.

Vá kèm: runner trước đây **từ chối** khi thư mục project đã tồn tại
(`Project folder already has data`), buộc phải dùng resume. Nhưng project đã bootstrap xong
của **cùng aweme** không phải xung đột — mọi stage đều keyed theo content hash, nên nay
runner `open_project()` dùng lại workspace đó. Chỉ báo lỗi khi thư mục có dữ liệu **dở dang**
(không có `project.json`/`project.db`) vì lúc đó adopt là xây trên đống đổ nát. Đo trên job
thật: từ lúc bấm Chạy tới lúc vào bước dịch mất **14 giây** (bỏ qua tải + ASR đã có).

#### Nút "Chạy tiếp" cho job fail + 3 lỗi Groq lộ ra khi dùng nó (2026-08-09)

Runner có `resume_project_root` từ lâu nhưng **không có đường nào gọi nó từ UI** — job chết
ở bước cuối vẫn phải chạy lại từ đầu, vứt cả tải lẫn ASR. Thêm
`POST /jobs/{id}/resume` (đọc url/kênh/preset từ vault row, chạy nền, chặn nếu đang chạy
hoặc chưa có workspace) + nút **"Chạy tiếp"** trên job `failed`/`review`, gửi kèm engine dịch
đang chọn ở form — lý do phải resume thường chính là engine cũ thiếu key.
**Đo thật:** resume nhảy qua download + ASR, tới `translate` trong **16 giây**.

Ba lỗi Groq lộ ra ngay khi resume chạy được, cả ba đều chỉ phát hiện được bằng cách chạy thật:
1. `DEFAULT_GROQ_MODEL = "moonshotai/kimi-k2-instruct"` **404 model_not_found** trên tài khoản
   hiện tại. Đối chiếu danh sách model live rồi đổi sang `openai/gpt-oss-120b` (test câu zh→vi
   sạch trong 1,5s; `llama-3.3-70b-versatile` 0,68s là lựa chọn nhanh hơn).
2. **Không có retry nào cho 429.** Groq trả kèm thời gian chờ chính xác ("try again in 3.345s")
   mà shim bỏ qua và để job chết. Thêm `_groq_call` + `groq_retry_delay()`: đọc gợi ý của
   server, fallback backoff 2→60s, tối đa 6 lần, **không** retry 4xx khác (400
   `json_validate_failed` retry lại cũng hỏng y hệt).
3. **Free tier không kham nổi một video.** Trần 12.000 token/phút và **100.000 token/ngày**;
   một video 362 câu qua contextual V2 đốt hết quota ngày rồi dừng ("TPD: Limit 100000,
   Used 99441"). Kết luận: Groq free chỉ hợp để thử vài scene — bản đầy đủ vẫn phải dùng
   claude-cli (0đ, ~16 phút) hoặc tài khoản Groq trả phí.

#### Tải chậm + nạp model chậm — đo rồi vá (2026-08-09)

**Tải.** Giả thuyết đầu tiên (tải song song nhiều đoạn) **đã bị số liệu bác bỏ**: cùng một
URL, 1 kết nối = **5,87 MB/s**, 4 kết nối = 3,79 MB/s, 8 kết nối = 3,40 MB/s — CDN bóp theo
IP nên song song còn *chậm hơn*. aiohttp vs httpx cũng ngang nhau (6,93 vs 5,74 MB/s), không
phải lỗi client. Nhưng chạy **đường production** thì chỉ **0,28 MB/s** (87,3 MB / 312s),
tái hiện được. Nguyên nhân nằm ngay trong comment tiếng Trung của vendor:
`/aweme/v1/play/` **302 sang node PCDN**, và có lần bốc phải node chết. Vá đúng cơ chế đó:
`_too_slow()` trong `file_manager.py` — sau 6 giây warm-up, nếu tốc độ dưới **1 MB/s**
(env `OMNICAST_DOUYIN_MIN_BPS`) thì **ném `SlowNodeError` để bỏ node và bốc lại**, thay vì bò
tới hết. Chỉ áp cho file >8 MB, tối đa 3 lần bốc lại rồi chấp nhận (mọi node đều chậm thì
chậm vẫn hơn không xong). Đo lại đường production: **8,33 MB/s** — nhanh gấp ~30 lần.
*Lưu ý so sánh:* lượt sau vendor bốc bản 1440p 20 Mbps (1,48 GB) chứ không phải bản 87 MB,
nên chỉ số MB/s mới là thứ so được, không phải tổng thời gian.

**Nạp model.** `FasterWhisperEngine.transcribe` dựng `WhisperModel` **mỗi job**, kèm một
round-trip huggingface.co kiểm tra revision — đo được 86s trên máy đang tải. Nay `_load_model`
cache theo `(model, device, compute_type, download_root)` và **thử `local_files_only=True`
trước** (fallback nếu chưa có trên đĩa — `download_root` thường là None nên không thể quyết
định bằng cách dò file). Đo: nạp nguội **14,15s → 9,48s**, nạp lại trong cùng tiến trình
**0,00s**. Test +5 (guard tốc độ, warm-up, file nhỏ, trần số lần bốc lại, tắt được bằng env).

#### "Khởi tạo lâu" — thật ra là bước TẢI vô hình (user báo 2026-08-09)

Đo lại job `reup-5a4799d3f9f4` bằng mốc thời gian thật: tạo job **14:59:06** → tải xong
87 MB **15:04:10 (+304s)** → bootstrap **+1s** → tách audio **+2s** → whisper nạp model
**+86s** → ASR chạy. Tức **`bootstrap` chỉ mất 1 giây**; 5 phút user nhìn thấy là **bước
tải**, và bước đó **không có trong `STAGES`** nên UI không tô chip nào — job trông như treo
trước cả khi bắt đầu. Runner vẫn `_announce("download", …)` từ đầu, chỉ là hằng số `STAGES`
(cả ở `reup_routes.py` lẫn `Reup.tsx`) thiếu nó. Đã thêm `download` → nhãn "Tải video".
Kèm theo: `ReupJobRow` thiếu `created_at`/`updated_at` (SELECT không lấy) nên UI không có
cách nào hiện thời gian trôi — đã bổ sung, và bảng job hiện "‹bước› · N phút" cho job
`running`. Một bước lâu giờ đọc là *đang chạy*, không phải *chết*.

#### Sản phẩm reup ra ngoài thư viện (user báo 2026-08-09, đã vá)

Reup là producer DUY NHẤT không giao hàng vào `output/products/<kênh>/<ngày>_<slug>/` —
nó để nguyên trong thư mục làm việc `output/reup/<aweme_id>/exports/` với **tên file tiếng
Trung**, lẫn giữa cache, 362 đoạn cắt và 5 lần thử phụ đề. `reup/publish.py` mới:
`publish_reup_product()` đặt `video.mp4` + `script.txt` (thoại Việt) + `subtitles.ass` +
`meta.json` (`kind=reup`, source_url, aweme_id, zh→vi, segment_count, review_pending,
encoder) vào đúng layout chung, gọi từ cả runner lẫn `POST /jobs/{id}/export`.
Ba quyết định đáng ghi: (1) **hard-link chứ không move** — cache export kiểm tra file đích
còn tồn tại, dời đi là lượt sau encode lại từ đầu (đã verify link count = 2, file gốc còn
nguyên); (2) tra thư mục theo **`source_aweme_id` trong meta**, không theo tiêu đề — sửa
tiêu đề rồi xuất lại vẫn cập nhật đúng thư mục cũ thay vì đẻ bản sao; (3) job chưa gắn kênh
rơi vào `_chua_gan_kenh` để vẫn tìm được, và để chỗ thiếu kênh lộ ra. Vault `reup_jobs` giờ
trỏ `exported_video_path` vào product. Test: 8 ca (`test_reup_publish.py`).
**Bẫy sẵn có phát hiện lúc verify:** `products.read_meta()` đọc `encoding="utf-8"` nên
meta.json có BOM trả về `{}` âm thầm (`anim_demo/miko_lantern_ep1/meta.json` đang bị) —
chưa sửa, nên đổi sang `utf-8-sig`.

**Hệ quả phải vá ngay sau đó:** `/jobs/{id}/artifacts` dựng URL bằng
`path.relative_to(WORKSPACE_ROOT)` và trả `None` cho mọi đường dẫn ngoài `output/reup` — dời
sản phẩm sang `output/products` xong thì **nút xem video chết link**. Nay `_url()` thử hai
gốc (`/reupmedia` cho artifact làm việc, `/pmedia` cho product — mount `/pmedia` đã có sẵn
trong `server.py`), và `_published_product()` đẩy "Video hoàn chỉnh (theo kênh)" lên đầu danh
sách, đọc từ `exported_video_path` trong vault rồi mới dò theo `source_aweme_id`. Bản trong
`exports/` vẫn liệt kê nhưng đổi nhãn thành "thư mục làm việc" cho khỏi nhầm. Verify:
`GET` range trả **HTTP 206**, đúng file 178,1 MB.

#### Video hỏng: ghi đè tại chỗ + hard link (user báo "đoạn đầu toàn màu đen", 2026-08-09)

`ffprobe`/decode ra **8885 lỗi `Invalid NAL unit size` trong 20 giây đầu** — bitstream hỏng
thật, không phải cảnh tối. Hai khiếm khuyết cộng lại:
1. `export_hardsub_video` cho ffmpeg ghi **thẳng vào tên file cuối**. Bị ngắt giữa chừng
   (restart backend, hai lượt export chồng nhau) là hỏng đúng cái tên mà mọi thứ tin.
   `-movflags +faststart` làm nặng thêm: pass thứ hai **ghi lại toàn bộ file tại chỗ**, nên
   kill giữa pass cho ra mp4 **đủ kích thước** nhưng cấu trúc rác — chứ không phải file cụt
   dễ nhận ra.
2. `publish` dùng **hard link**. Product và export chung inode, nên lượt render sau ghi đè
   luôn video đã giao, và render hỏng thì product hỏng theo.

Vá: (1) render ra `.<tên>.partial.mp4` rồi `os.replace` — nguyên tử, đứt gánh thì file cũ
còn nguyên; xoá temp khi fail/cancel. **Đuôi `.mp4` phải nằm cuối** — đặt `.partial` ở cuối
thì ffmpeg báo "Unable to choose an output format" (đã dính ngay lần chạy đầu). (2) publish
**copy qua tên `.incoming` rồi `os.replace`**, không link. Verify sau khi xoá bản hỏng và
render lại: 178,1 MB, `links=1`, khác inode với export, **decode toàn file 0 lỗi**, 3 khung
đầu có hình. Test +5 (partial-name, dọn temp khi fail, copy-không-link, không sót `.incoming`).

**Và một lần nữa ở bảng job:** nút "Xem video" tự dựng URL trong trình duyệt bằng
`exported_video_path.split(/[\\/]reup[\\/]/).pop()`. Khi đường dẫn không còn chứa `/reup/`,
`.pop()` trả về **nguyên cả đường dẫn tuyệt đối** nên href thành `/reupmedia/E%3A%5CProject...`
→ 404 âm thầm. Bài học: **trình duyệt không được suy ra URL từ đường dẫn hệ thống tệp.**
Nay `media_url()` là hàm dùng chung ở server, `/jobs` và `/jobs/{id}` trả sẵn `video_url`,
UI chỉ việc gắn vào href. Verify: link lấy thẳng từ `/api/reup/jobs` trả **HTTP 206**.

#### Key nhập trong UI không ai đọc — ĐÃ VÁ (user báo "nhập key groq rồi mà", 2026-08-09)

Xác nhận bằng dữ liệu: key **đã lưu thành công** vào bảng `credentials` của vault
(`provider=groq, encrypted=True`), nhưng `.env` không có `GROQ_API_KEY` và
`/api/reup/health` báo `groq: false` — vì nó đọc `os.environ` thôi. Job chạy hết tải + ASR
~15 phút rồi mới chết ở bước dịch với `RuntimeError: Groq backend needs an API key`.
Màn Providers ghi vào một cái kho **không consumer nào đọc**.
`config/credentials.py` mới: `resolve_api_key(provider, override=)` theo thứ tự
**override → os.environ → Settings(.env) → vault** (giải mã bằng Fernet key lấy từ env hoặc
Settings; hỏng/thiếu thì trả "" chứ không nổ). Đã nối vào `reup_health` và
`build_translation_engine("groq")`. Sau khi vá: `backends.groq: true`, `translate: claude-cli, groq`
— không phải nhập lại key. Test +6. Bảng ánh xạ provider→(env var, Settings field) nằm trong
`PROVIDER_ENV_VARS`; các consumer khác (llm/registry, youtube…) vẫn đọc Settings trực tiếp,
nối nốt là việc còn lại.

#### Nơi nhập API key — SAI CHỖ (phát hiện 2026-08-09)

UI có sẵn tại **Hệ thống → Providers** (tab mặc định của `#/system`): mỗi provider một thẻ
với badge "Đã có key/Chưa có key", nút Key mở ô nhập, nút Test. **Nhưng `POST /api/credentials`
ghi vào bảng `credentials` của vault, còn runtime không đọc bảng đó.** Toàn bộ provider lấy
key từ `Settings` (pydantic-settings, `env_file=implementation/.env`) — ví dụ
`tts_volcengine.load_credentials()` đọc `VOLCENGINE_TTS_APPID`/`..._ACCESS_TOKEN` từ env rồi
mới tới thuộc tính settings, không hề chạm vault. Grep `get_credential|resolve_credential`
trong `media/` và `llm/`: **0 kết quả**. Nên hiện tại nhập key qua UI = lưu vào chỗ không ai
đọc; key thật phải đặt trong `implementation/.env`. Nợ: nối `CredentialVault` vào `Settings`
(hoặc để UI ghi thẳng `.env`) — chưa làm, cần quyết định chỗ nào là SSOT.

#### Còn lại

1. Chốt giọng mặc định (đang là VieNeu Mai Anh) và chạy bản so sánh nếu cần.
2. Hàng đợi duyệt chưa có thao tác hàng loạt (duyệt cả scene / duyệt tất cả sau khi đọc).
3. Cookie Douyin: hiện tự lấy ẩn danh, đủ cho video công khai. Video riêng tư / bộ sưu tập
   cần `sessionid` thật — nên lấy từ bảng `credentials` trong vault thay vì truyền tay.
4. Chưa gắn speaker → giọng riêng cho từng nhân vật (`speaker_bindings` + `voice_policies`
   đã port sẵn nhưng runner dùng một preset chung cho cả video).
#### TTS tiếng Việt — CHỐT: VieNeu (user chọn 2026-08-08, muốn đa dạng voice)

`vieneu 3.2.4` đã cài (Python 3.13 OK). **Bản 3.x KHÔNG còn cần eSpeak NG** — nó chuyển
sang wheel `sea_g2p` đi kèm (0 tham chiếu espeak trong package). README repo gốc và
`tts/vieneu_engine.py` viết cho bản 2.x nên chặn cứng đòi eSpeak → đã sửa: thêm
`_espeak_required()` (bằng `sea_g2p` có import được không) và chỉ chặn khi thật sự cần.
Lệnh `--extra-index-url .../llama-cpp-python-v0.3.16/cpu/` trong README cũng không cần nữa;
`llama-cpp-python` giờ nằm trong extra `legacy`.

Nguồn đa dạng voice, 3 tầng:
1. **14 giọng preset** (`client.list_preset_voices()`, model `VieNeu-TTS-v3-Turbo`) —
   7 nam / 7 nữ, 3 vùng miền × 3 phong cách. Chọn qua `VoicePreset.voice_id` (tên có dấu):

   | Vùng | Tin tức | Tự nhiên | Kể chuyện |
   |---|---|---|---|
   | Bắc | Minh Đức ♂, Mai Anh ♀ | Phạm Tuyên ♂, Trúc Ly ♀, Đoan Trang ♀ | Thanh Bình ♂, Ngọc Linh ♀ |
   | Nam | Minh Triết ♂, Thùy Dung ♀ | Xuân Vĩnh ♂ | Thái Sơn ♂, Thục Đoan ♀ |
   | Trung | — | Quang Sơn ♂, Ngọc Trân ♀ | — |

   (Thư mục `assets/samples/` của package chỉ có 6 file `.wav` — đó là sample cục bộ,
   KHÔNG phải danh sách voice; danh sách thật nằm trong `voices_v3_turbo.json` của model repo.)
2. **Clone từ audio mẫu** — preset `vieneu-clone-template`, cần `ref_audio_path` + `ref_text`.
3. **Batch import** — `tts/presets.py::import_voice_presets_from_dir` quét
   `assets/voices/`, mỗi file audio có sidecar `.txt` cùng tên thành 1 preset clone.

Đã verify thật (2026-08-08): synth 14/14 giọng qua `VieneuTTSEngine` đã port, output
48kHz wav, ~2.9–4.2s cho câu 12 từ.

**Cạm bẫy đã gặp + đã sửa:** `onnxruntime>=1.24` resolve symlink khi validate
external-data path của model ONNX và từ chối nếu file `.data` nằm ngoài thư mục model.
Cache HF trên máy này symlink mọi file vào `blobs/` → VieNeu load fail
(`External data path ... escapes model directory`). Fix: materialise 2 snapshot
(`VieNeu-TTS-v3-Turbo`, `MOSS-Audio-Tokenizer-Nano-ONNX`) thành file thật. Không cần
đổi code: `huggingface_hub` 1.17 đã tắt symlink trên Windows (`file_download.py:660`
— `os.name != "nt"`), nên model tải mới không dính lại.

SAPI (`tts/sapi_engine.py`) đã port theo nhưng **không được dùng** — luật dự án cấm
pyttsx3/SAPI. Còn phải quyết: đăng ký `vieneu` thành provider trong
`media/voice_router.py` (spec `vieneu:<voice_id>`) để kênh khác cũng gọi được.
