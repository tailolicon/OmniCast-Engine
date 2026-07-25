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
