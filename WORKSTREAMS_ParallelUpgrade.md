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
2. Pha THỰC THI: mỗi WS một nhánh, TDD, suite xanh mới merge; gen-live xếp hàng.
3. Mỗi WS lặp autopsy như script-gen đã làm.
