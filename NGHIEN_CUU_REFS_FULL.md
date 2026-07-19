# NGHIÊN CỨU TOÀN BỘ `_refs/` — Chức năng + Giao diện của 13 repo tham chiếu

> STATUS: ACTIVE (tài liệu tham chiếu Epic I)

> Mục đích: kho tính năng để **kiểm soát hệ thống tốt hơn** — trích từ code/README thật của từng repo (2026-07-04).
> Cách dùng: §3 là ma trận "chức năng → OmniCast đã có chưa → đề xuất". Mỗi đề xuất lớn phải thành Epic/spec riêng trước khi code (không nhét thẳng vào UI).
> Docs liên quan: `PHAN_TICH_1DevTool_va_SuperApp.md`, `PHAN_TICH_VideoToolsPro_1DevTool.md` (phân tích sâu 2 repo), `SPEC_UI_v2.md` (UI hiện tại).

---

## 1. TỔNG QUAN 13 REPO

| Repo | Là gì | Stack UI |
|---|---|---|
| **MoneyPrinterTurbo** | Sinh video ngắn tự động từ topic (copy AI → stock video → TTS → sub → BGM) | Streamlit + FastAPI (MVC, có REST API riêng) |
| **Pixelle-Video** | Engine video ngắn AI (script→ảnh AI→video AI→TTS→ghép), atomic capabilities hoán đổi | Web UI 3 cột (input→config→kết quả preview) + FastAPI |
| **pyvideotrans** | Dịch video end-to-end: ASR→dịch→TTS→ghép; diarization, voice clone | Desktop PySide6, ~70 màn hình cấu hình provider |
| **voice-pro** | Studio lồng tiếng: YouTube DL, tách giọng Demucs, Whisper 4 loại, TTS/clone, dịch realtime | Gradio tabs (Dubbing Studio/Caption/Translation/TTS) |
| **VideoToolsPro** | Tool Việt: reup/dịch/lồng tiếng/OCR hardsub/batch | Desktop (đã phân tích riêng) |
| **1DevTool** | Điều phối AI agents + toolbox dev 90+ module | Electron (đã phân tích riêng) |
| **ChatDev (2.0 DevAll)** | Nền tảng multi-agent zero-code: định nghĩa agent/workflow bằng graph | Vue: workflow graph editor + form động + batch run |
| **ChatDev1** | Bản legacy của ChatDev (tham khảo lịch sử, ít giá trị mới) | — |
| **agent-office** | Đội agent tự lớn trong văn phòng pixel-art, LLM local | React + Colyseus realtime + pixel canvas |
| **pixel-agents** | Character pixel cho từng phiên Claude Code trong VS Code | React 19 + Vite + Tailwind 4 (webview) |
| **hyperframes** | Render video từ HTML thuần (headless Chrome + FFmpeg), deterministic | studio + player + producer + shader-transitions + Lambda/CloudRun |
| **remotion** | Render video từ React components | Studio/player riêng của Remotion |
| **h2dev_flow** | Extension Chrome bulk-prompt cho Google Flow (gõ thật qua chrome.debugger) | Sidepanel: hàng đợi status từng item |

---

## 2. CHI TIẾT: CHỨC NĂNG + GIAO DIỆN TỪNG REPO

### 2.1 MoneyPrinterTurbo
**Chức năng:** copy AI hoặc tự nhập; khổ 9:16 + 16:9; **batch sinh nhiều video 1 lần rồi chọn bản ưng nhất**; đặt thời lượng từng clip (tần suất đổi cảnh); voice đa nguồn + **preview realtime**; subtitle chỉnh font/vị trí/màu/cỡ/viền; BGM random hoặc chỉ định + chỉnh volume; stock từ Pexels/Pixabay/Coverr hoặc **material local**; 15+ LLM provider; có **REST API độc lập** với web UI (chạy headless được).
**UI:** form từng khối theo pipeline; mọi lựa chọn có preview; settings panel chọn preset LLM + nhập key + test.
**Lấy cho OmniCast:** batch-N-chọn-1; cài đặt subtitle style qua UI; chọn nguồn stock + local material qua UI; API-first đã có sẵn.

### 2.2 Pixelle-Video
**Chức năng:** topic→video full-auto; ảnh AI từng câu; video AI (WAN 2.1, Kling, Seedance...); TTS đa nguồn; BGM; **template thị giác chọn qua dropdown + "xem tất cả mẫu"**; khổ dọc/ngang; **atomic capability hoán đổi** (ComfyUI/RunningHub/API trực tiếp — giống CapabilityBus của OmniCast).
**UI (đã xem screenshot):** 3 cột trái→phải = nhập liệu → cấu hình từng bước (mỗi khối có "功能说明" collapsible + nút preview riêng: preview TTS, preview template, preview style) → cột kết quả (nút sinh to đỏ, progress bar, ✅ path output, **video player + stats: thời gian sinh/size/số phân cảnh/độ phân giải**).
**Lấy cho OmniCast:** preview-mọi-thứ-trước-khi-tốn-tiền (TTS/style/template); stats render trên card kết quả; picker template thị giác.

### 2.3 pyvideotrans
**Chức năng:** ASR (Faster-Whisper local/OpenAI/Qwen/Azure/Google...) → dịch LLM (DeepSeek/GPT/Claude/Gemini/Ollama...) → TTS (Edge free/OpenAI/Azure/ChatTTS...) → ghép; **speaker diarization + gán giọng khác nhau cho từng người nói**; voice clone F5/CosyVoice/GPT-SoVITS; **dừng-sửa-tiếp ở TỪNG GIAI ĐOẠN** (proofread sub trước khi TTS); toolkit: tách vocal, merge video/sub, align audio-video; **CLI headless**.
**UI:** ~70 màn hình cấu hình riêng từng provider, mỗi màn có nút Test Connection.
**Lấy cho OmniCast:** **checkpoint có-người-sửa giữa pipeline** (pause sau script/sau TTS để sửa rồi chạy tiếp — khớp HITL sẵn có); dịch đa ngôn ngữ để nhân bản kênh sang thị trường khác.

### 2.4 voice-pro
**Chức năng:** tải YouTube + tách audio; tách giọng/nhạc Demucs/MDX-Net; STT 4 engine (Whisper/Faster/Timestamped/WhisperX); TTS Edge 400+ giọng/E2/F5/CosyVoice/kokoro; **voice clone zero-shot**; dịch realtime; xuất WAV/FLAC/MP3; điều khiển speed/volume/pitch TTS.
**UI:** Gradio tabs; mỗi giọng có nút nghe thử.
**Lấy cho OmniCast:** đã có kokoro/edge/xtts/f5 — bổ sung UI chỉnh speed/pitch/volume per-channel; tính năng "phân tích video đối thủ" (tải + STT + đọc script của video viral làm tham khảo — nối vào competitor_intel).

### 2.5 VideoToolsPro (chi tiết engine: `PHAN_TICH_VideoToolsPro_1DevTool.md` · **UI ĐẦY ĐỦ bóc từ binary 2026-07-04: `UI_VideoToolsPro_FULL.md`** — 2 tab, timeline 4 track tương tác, 28 preset phụ đề + font catalog picker, OCR kéo-vùng, anti-reup/logo/upscale, gap matrix V1–V12)
**Chức năng:** downloader Douyin/YT/TikTok/FB; whisperx word-level; TTS đa engine có tiếng Việt; dịch theo **thể loại phim + khớp khẩu hình**; llama_cpp offline fallback; **OCR bóc hardsub**; demucs; **batch mode + retry lỗi từng file**; thư viện BGM/SFX/font đóng gói.
**Lấy cho OmniCast:** retry-per-item (đã vào Jobs tab); thư viện BGM/SFX quản qua UI; backup key tự xoay (KeyPool đã có — thêm UI xoay).

### 2.6 1DevTool (chi tiết: `PHAN_TICH_1DevTool_va_SuperApp.md`)
**Chức năng nổi bật cho "kiểm soát":** UI **"All Agents"** — danh sách agent + interaction logs + sub-agent history + **risk badge Low/Med/High cho hành động tự động**; **Remote UI điều khiển từ điện thoại** (auth/devices/audit/permission); usage/quota đa provider + key rotation trực quan; universal DB client (xem SQLite vault trực tiếp!); HTTP client kiểu Postman (test API nội bộ); notes/prompt history/templates; diff viewer/markdown preview; i18n 50 ngôn ngữ.
**Lấy cho OmniCast:** risk badge cho hành động agent trước khi auto-execute; **DB browser cho vault.db ngay trong app**; HTTP console test endpoint; prompt history của Writer/Critic.

### 2.7 ChatDev 2.0 (DevAll)
**Chức năng:** định nghĩa **agent + workflow bằng graph editor** không cần code; **BatchRunView** chạy hàng loạt workflow; form sinh động từ schema (`DynamicFormField`/`FormGenerator`); SettingsModal; tutorial view.
**UI:** Vue + workflow canvas (node/edge), workbench chỉnh node, danh sách workflow.
**Lấy cho OmniCast:** **trực quan hóa pipeline dạng graph** (discovery→script→render→publish với node trạng thái realtime — pipeline YAML đã có, chỉ cần vẽ); form-từ-schema đã nằm trong spec E1.

### 2.8 agent-office
**Chức năng:** agent có tính cách + **nói chuyện với nhau tự động**; **click-to-follow camera**; giao task từ TaskBoard UI + agent tự giao task cho nhau; agent tự tuyển thêm agent; tool execution sandbox; **memory SQLite + semantic search (embeddings)**; layout editor kéo-thả; **System Activity Log realtime có dedup**; emote bubbles theo hành động.
**Lấy cho OmniCast:** tab Văn phòng đang là iframe tĩnh — nâng cấp: click-follow từng agent (Writer/Critic/Compliance), speech bubble hiện việc đang làm thật (từ SSE), TaskBoard giao topic thẳng trong office.

### 2.9 pixel-agents
**Chức năng:** 1 terminal agent = 1 nhân vật; animate theo hành động thật (đọc/ghi/chạy lệnh); speech bubble khi chờ input/cần quyền; **sound notification khi agent xong việc**; sub-agent spawn nhân vật con nối với cha; layout editor; asset pack ngoài.
**Lấy cho OmniCast:** **chuông/sound khi render xong hoặc chờ duyệt** (rất hợp vận hành 24/7); sub-agent visualization cho debate (Writer đẻ Critic/Thinking).

### 2.10 hyperframes
**Chức năng:** composition = **HTML thuần + data attributes** (agent viết dễ); deterministic (same input→same output — hợp CI/test); không build step; adapter animation (GSAP/CSS/Lottie/Three); **studio + player (preview iframe realtime) + producer**; shader transitions; render phân tán Lambda/CloudRun.
**Lấy cho OmniCast:** renderer đã dùng HTML overlay (`html_overlay.py`) — chuẩn hóa theo hướng hyperframes để preview overlay/intro/outro trong UI trước khi render thật; shader transitions cho chuyển cảnh.

### 2.11 remotion
**Chức năng:** video = React component; studio timeline; Lambda render trưởng thành. Repo `implementation/remotion_studio` + `remotion_render.py` ĐÃ tích hợp một phần.
**Lấy cho OmniCast:** giữ làm đường render component-based (bumper/intro/outro đã dùng); không mở rộng thêm nếu hyperframes-style rẻ hơn.

### 2.12 h2dev_flow
**Chức năng:** bulk prompt → tự gõ vào Flow (chrome.debugger vì Slate.js cần input thật) → chờ ảnh → tự tải về thư mục → item tiếp; **hàng đợi có status tag từng item (Chờ/Đang tạo/Xong/Lỗi/Quá giờ)**; cảnh báo vận hành rõ ràng (đóng DevTools, đừng bấm Hủy).
**Lấy cho OmniCast:** `flow_browser` provider đã cùng cơ chế — thêm **panel hàng đợi ảnh Flow trong Studio** (từng prompt 1 dòng status + retry) thay vì log chữ.

### 2.13 ChatDev1 — legacy, bỏ qua (giá trị đã nằm trong ChatDev 2.0).

---

## 3. MA TRẬN CHỨC NĂNG → OMNICAST (để kiểm soát hệ thống tốt hơn)

> ✅ = OmniCast đã có · 🟠 = có một phần · ❌ = chưa có. Ưu tiên P1 = tăng khả năng KIỂM SOÁT/ra tiền ngay; P2 = chất lượng vận hành; P3 = mở rộng.

| # | Chức năng (nguồn) | OmniCast | Ưu tiên | Ghi chú triển khai |
|---|---|---|---|---|
| C1 | Pause-sửa-tiếp từng giai đoạn pipeline (pyvideotrans) | 🟠 HITL chỉ ở publish | **P1** | Thêm gate tùy chọn sau script + sau TTS: trạng thái `WAITING_EDIT`, UI sửa text rồi Resume (JobEngine checkpoint đã có) |
| C2 | Batch sinh N video → chọn bản tốt nhất (MPT) | 🟠 debate chọn script, render thì 1 bản | P2 | Render N biến thể thumbnail/hook (A/B đã có cho thumbnail — mở rộng cho hook đầu 15s) |
| C3 | Preview trước khi tốn tiền: TTS/style/template (Pixelle, voice-pro) | 🟠 có /api/voice/preview | **P1** | UI: nút nghe giọng + xem style ảnh + preview overlay HTML trong Studio trước khi bấm Render |
| C4 | Hàng đợi Flow-image per-prompt status + retry (h2dev_flow) | ❌ (chỉ log chữ) | **P1** | Panel trong Studio đọc render status.json chi tiết từng scene: Chờ/Đang tạo/Xong/Lỗi + retry scene lỗi |
| C5 | Risk badge cho hành động tự động (1DevTool) | ❌ | **P1** | Mỗi approval/auto-action gắn Low/Med/High (public=High, unlisted=Med, dry-run=Low) hiện trong Duyệt & Đăng |
| C6 | Remote control từ điện thoại + audit (1DevTool) | ❌ | P2 | Đã có Epic G trong MASTER_PLAN — giữ thứ tự sau D6 |
| C7 | DB browser vault.db trong app (1DevTool universal DB client) | ❌ | P2 | Tab Hệ thống: bảng đọc-chỉ (niches/scripts/approvals/usage) — SELECT only, cấm write |
| C8 | Pipeline dạng graph node trực quan (ChatDev) | ❌ (steps dạng list) | P2 | Vẽ graph 4 node + trạng thái SSE; YAML pipeline đã là DAG |
| C9 | Sound notification khi xong/chờ duyệt (pixel-agents) | ❌ | **P1** (rẻ) | Web Audio chime khi SSE bắn `job.finished` / approval mới |
| C10 | Office sống: speech bubble + click-follow + TaskBoard (agent-office) | 🟠 office pixel tĩnh | P3 | Nối SSE thật vào office_app; TaskBoard giao topic |
| C11 | Subtitle style editor (font/màu/vị trí/viền) per-channel (MPT) | ❌ (hardcode render) | P2 | Form trong tab Kênh ghi vào channels/{id}.json → render đọc |
| C12 | BGM/SFX library quản qua UI (VideoToolsPro) | 🟠 music_lib CLI | P2 | Tab Thư viện: list nhạc + nghe thử + gán kênh |
| C13 | Dịch đa ngôn ngữ nhân bản kênh (pyvideotrans/voice-pro) | ❌ | P3 | Kênh vệ tinh thị trường khác — sau khi kênh gốc ra tiền |
| C14 | OCR hardsub + phân tích video đối thủ (VideoToolsPro/voice-pro) | 🟠 competitor_intel text | P3 | Tải video đối thủ → STT → phân tích hook/pacing nạp vào KB |
| C15 | Preview overlay HTML deterministic (hyperframes) | 🟠 html_overlay có sẵn | P2 | Nút "Preview overlay" render 1 frame trong Studio |
| C16 | Prompt history + templates của agent (1DevTool) | ❌ | P3 | Lưu prompt Writer/Critic từng run vào vault, xem lại trong Thư viện |
| C17 | HTTP console test endpoint nội bộ (1DevTool) | ❌ | P3 | Dev-only, ẩn sau flag |
| C18 | i18n UI (1DevTool 50 ngôn ngữ) | ❌ (VN only) | P3 | Chưa cần |

**Đề xuất gói triển khai kế tiếp (Epic I — "Control Pack", sau P7 của SPEC_UI_v2):**
- **I1 (P1):** C1 pause-sửa-tiếp + C3 preview-trước-khi-tốn-tiền + C4 per-scene queue status/retry + C5 risk badge + C9 sound chime. → Đây là 5 thứ tăng KIỂM SOÁT trực tiếp nhất, đều dựa hạ tầng sẵn có (JobEngine checkpoint, voice/preview API, status.json, approvals, SSE).
- **I2 (P2):** C7 vault browser read-only + C8 pipeline graph + C11 subtitle style editor + C12 BGM library + C15 overlay preview + C2 A/B hook.
- **I3 (P3):** C6 remote (Epic G), C10 office sống, C13 đa ngôn ngữ, C14 competitor video, C16-C18.

> Mỗi mục I1/I2 khi làm phải có spec nhỏ kiểu SPEC_UI_v2 §4 (màn hình + endpoint + nghiệm thu). Backend thiếu endpoint nào thì agent backend bổ sung TRƯỚC, agent UI chỉ gọi.
