# 1DevTool — bóc tách đầy đủ + lộ trình "siêu ứng dụng" cho OmniCast

> Nguồn: đã giải nén `C:\Program Files\1DevTool\resources\app.asar` (440 MB, Electron). Dữ liệu dưới đây lấy từ `package.json`, **90+ module backend** (`dist/main/main/*.js`), kênh IPC, và chuỗi UI trong renderer bundle. Mức tin cậy: **danh mục chức năng = chắc chắn** (đọc trực tiếp module + dependency); **nhãn nút/thông báo = mẫu lớn** trích từ bundle đã minify (không phải 100% từng nhãn, nhưng đủ để bạn đối chiếu).

## 0. Đính chính quan trọng — 1DevTool KHÔNG phải app video

`package.json`: tên **`1devtool`**, version **1.29.0**, tác giả **StoicSoft**, mô tả **"One workspace. Every AI agent. Every project."**, license **MIT**, web 1devtool.com. Đây là **IDE/cockpit cho AI dev agent** — môi trường làm việc cho lập trình viên điều phối nhiều AI coding agent. Nó **không liên quan gì tới sản xuất video**.

Hệ quả: yêu cầu "OmniCast làm **toàn bộ** chức năng như cả 2 ref" đang ghép **hai lĩnh vực khác hẳn nhau**: VideoToolsPro = hậu kỳ video; 1DevTool = IDE lập trình AI. Bê nguyên SSH/DB client/simulator iOS… vào một pipeline YouTube là vô nghĩa. Phần "đáng học" của 1DevTool cho OmniCast là **kiến trúc & UX của một cockpit vận hành**, không phải tính năng dev (mục 4). Vì 1DevTool khai báo MIT (khác VTP đóng & cấm dịch ngược) nên **học mẫu kiến trúc/code thoải mái hơn**.

---

## 1. Bản đồ chức năng 1DevTool (từ 90+ module backend)

| Nhóm | Chức năng | Bằng chứng (module/dep) |
|---|---|---|
| **Đa AI agent** | Quản lý & chạy nhiều coding agent: **Claude Code, Codex, Gemini CLI, Qwen Code, OpenCode, Cursor, Aider, Cline, Amp, Happy**; chạy headless; chữ ký agent; lịch sử sub-agent | `aiAccounts/*`, `cliRegistry/knownClis`, `externalAgentScanner`, `orchestration/runHeadlessAgent`, `subAgentHistory` |
| **Theo dõi usage/quota AI** | Đọc usage từ Claude/Codex/Gemini/Qwen/OpenCode (parse JSONL), bảng quota theo nhà cung cấp, API usage | `aiUsage/parsers/*`, `aiAccounts/quotaProviders`, `usageApi`, `status` |
| **AI Diff / review** | Xem diff do AI tạo, keep/undo từng thay đổi, preview state | `aiDiff.js`, `aiPreviewState`, "Agent Output Diff" |
| **MCP servers** | Host MCP (server 1.4 MB), tool registry, bridge, tool DB/HTTP | `mcp-servers/server.js`, `tools/databaseTools`, `tools/httpTools` |
| **Terminal** | Đa terminal (node-pty + xterm), default terminal type, scrollback | `pty.js`, `node-pty`, `xterm*` |
| **Code editor** | Monaco editor + **Code Intelligence (LSP)**: cài/registry/host language server | `monaco-editor`, `lsp/host`, `lsp/installer`, `lsp/registry` |
| **Git** | Trạng thái repo, commit, publish, GitHub/GitLab, "git stack" | `git.js`, `gitHost/github`, `gitHost/gitlab`, `gitStateWatcher`, `gstack` |
| **Database (universal client)** | 14 hệ: Postgres, MySQL, MSSQL, MongoDB, Redis, Cassandra, ClickHouse, CouchDB, Elasticsearch, InfluxDB, Kafka, SQLite, SurrealDB, Weaviate; import/export | `database/adapters/*`, `database/export|import` |
| **HTTP client** | Gửi request, import/export (kiểu Postman), HTTP tools | `http.js`, `httpImport`, `httpExport` |
| **Deploy** | Build & deploy **Vercel/Cloudflare**, Cloudflare Tunnel (cloudflared), secret store | `deploy/providers/*`, `cloudflared/*`, `deploy/secretStore` |
| **Docker** | Quản lý Docker (image/container/log) | `docker.js` |
| **Mô phỏng thiết bị** | Simulator **iOS & Android** (build-run, idb, WebDriverAgent stream) | `simulator/ios-adapter`, `android-adapter`, `idb` |
| **Remote control** | Điều khiển từ xa qua web/điện thoại: auth, devices, audit, permission, handlers (dashboard/files/git/terminal/resume) | `remote/*`, `dist/remote-ui` |
| **Diagram/Design** | Mermaid, Excalidraw, Graphviz (viz), prototype/design qua AI | `mermaid`, `@excalidraw`, `@viz-js`, `design.js`, `prototype.js` |
| **Bộ tiện ích dev** | Regex Tester, Hash Generator, JWT/Base64, **Number Base / Timestamp / Color / String Case Converter**, Lorem Ipsum, Markdown Preview, Diff Viewer, QR | `qrcode`, chuỗi UI "Testers/Converters/Generators/Formatters" |
| **Ghi chú / bộ nhớ** | Notes, Sticky Notes, memory manager, prompt history, templates | `notes`, `memoryManager`, `promptHistory`, `templates` |
| **Skills** | Hệ skill (giống skill của Cowork/Claude Code) | `skills.js`, `orchestration/skillContent` |
| **Hạ tầng app** | Auto-update, store cấu hình, tray, license **LemonSqueezy**, analytics (Aptabase), crash (Sentry), resume phiên, Rust sidecar | `updater`, `electron-store`, `tray`, `services/LicenseService`, `LemonSqueezyService`, `resumeManager`, `rustSidecar` |
| **Đa ngôn ngữ** | i18n **~50 ngôn ngữ** (có **vi-VN**) | `dist/renderer/assets/<lang>-*.js` |

**AI agent hỗ trợ (xác nhận):** Claude Code, Codex, Gemini CLI, Qwen Code, OpenCode, Cursor, Aider, Cline, Amp, Happy.

---

## 2. Nhãn nút / mục giao diện (mẫu trích — phân nhóm)

- **Khung làm việc:** New Tab · Add Project · All Projects · Add Terminal · New Terminal · Add Connection · New Request · New Group · File Tree · Left/Right Sidebar · Expand Sidebar · Panel Arrangement · Exit Fullscreen · Reader Mode · Markdown Preview · Sticky Notes
- **AI/Agent:** All Agents · Claude Code · Qwen Code · Coming Soon · Change AI · Prompt History · Interaction Logs · Code Intelligence (Enable Code Intelligence)
- **Git/Deploy:** Publish Repository · Open Git Settings · Copy Path/File Path · Cloudflare Tunnel · Dev Servers · Port Manager
- **DB/HTTP:** New Connection · Connection Name/URI/Mode · Connection Details (host, port, user) · Set Default · Regex Tester · Hash Generator
- **Thiết bị/Remote:** Paired Devices · Remote Control · Remote Path · Take Screenshot · Private Key · Connect SSH (Project)
- **Tiện ích:** Diff Viewer · Number Base/Timestamp/Color/String Case Converter · Lorem Ipsum Generator · Quick Commands · Environment Variables
- **Cấu hình:** Import/Export App Configuration · Reset Settings · Accent Color · Stoic Light/Dark (theme) · Keyboard Shortcuts · Default Terminal Type · Purchase License
- **Risk badge:** Low/Medium/High Risk (đánh dấu mức rủi ro lệnh agent)

## 3. Thông báo (mẫu trích nguyên văn — tiếng Anh)

- **Kết nối:** `Connected` · `Connecting...` · `Connection failed` · `Cannot connect` · `Connection error` · `Connection removed` · `Connection is closed.` · `Cannot connect to the Docker daemon`
- **AI/Diff:** `AI Diff: failed to load diff` · `AI Diff: keep failed` · `AI Diff: undo failed` · `Change AI failed:` · `Action failed`
- **Build/Run/Simulator:** `Building and running app...` · `Build and run failed` · `Boot failed` · `Auto-detect failed.` · `Connecting to simulator/emulator stream...` · `Connect to see the simulator`
- **Lưu/Cấu hình:** `Auto-save failed` · `Config saved to …` · `Bundle saved to …` · `All variables already exist`
- **License:** `Activation failed. Try again.` · `Purchase License` · `Checkout URL not configured…`
- **Khác:** `Close Unsaved Query` · `Commit not found.` · `At least one AVD created.`

> Lưu ý: chuỗi UI gốc tiếng Anh; file `vi-VN` trong app chủ yếu là bản dịch của Excalidraw (component nhúng), không phải toàn bộ nút của 1DevTool. Nếu cần **đủ 100% nhãn**, mình có thể chạy thêm pass trích xuất sâu trên `r_eGq1C-sE.js` (4 MB) hoặc bạn mở app chụp từng màn.

---

## 4. Lộ trình "siêu ứng dụng" cho OmniCast

OmniCast = pipeline tự động sản xuất video YouTube 24/7. Để thành siêu app, hợp lý nhất là gộp **năng lực media của VideoToolsPro** + **mô hình cockpit/điều phối của 1DevTool**, bỏ phần dev không liên quan.

### 4A. Lấy từ VideoToolsPro (đúng lĩnh vực — ưu tiên cao)
Tải đa nền tảng (yt-dlp/playwright), STT WhisperX (canh từ), TTS đa engine (edge/piper/supertonic/vieneu), dịch nhận-diện-thể-loại + khớp khẩu hình, LLM offline (llama_cpp), OCR hardsub (rapidocr), tách nhạc/giọng (demucs), render burn-sub, thư viện BGM/SFX, batch. → **Đây là "mọi chức năng video" cần có.**

### 4B. Lấy từ 1DevTool (kiến trúc/UX cockpit — rất hợp OmniCast)
1. **Bảng usage/quota đa nhà cung cấp** (Claude/Gemini/Groq/OpenAI/Flow): đọc mức dùng, cảnh báo sắp hết, xoay vòng key. 1DevTool làm chuẩn việc này — OmniCast đang xài nhiều provider nên rất cần.
2. **Điều phối nhiều agent + lịch sử** (Writer/Critic/Compliance…): UI "All Agents", interaction logs, sub-agent history, **risk badge Low/Med/High** cho hành động tự động — hợp với khâu compliance/upload.
3. **Remote UI điều khiển từ điện thoại**: theo dõi/duyệt/khởi chạy render khi không ở máy — cực hợp app chạy 24/7.
4. **Terminal/log console nhúng (xterm)** + **resumeManager** (resume job) — khớp đúng cache/resume của Flow bạn vừa làm.
5. **Monaco editor nhúng** để sửa `channels/{id}.json`, pipeline YAML, script ngay trong app.
6. **Mermaid** để vẽ trực quan pipeline/trạng thái.
7. **Hạ tầng app**: electron-store (config), electron-updater (tự cập nhật), Sentry (crash), Aptabase (analytics), **MCP server registry**, **skills** — OmniCast đã hợp với MCP/skills sẵn.
8. **Import/Export App Configuration**, Keyboard Shortcuts, theme sáng/tối, đa ngôn ngữ (i18n).

### 4C. Bỏ qua (không thuộc lĩnh vực OmniCast)
DB client 14 hệ, HTTP client, Docker, deploy Vercel/Cloudflare, SSH, simulator iOS/Android, LSP/code intelligence. (Chỉ thêm nếu sau này OmniCast mở rộng thành nền tảng dev — hiện không.)

### 4D. Đề xuất kiến trúc gộp
OmniCast lõi (Python pipeline + FastAPI + vault.db) giữ nguyên là "engine". Bọc một **shell cockpit kiểu Electron/desktop** (như 1DevTool) lên trên, trong đó:
- Tab **Sản xuất** (pipeline + hàng đợi batch có trạng thái từng cảnh + nút retry-lỗi — nối thẳng phần Flow),
- Tab **Media tools** (tải/STT/TTS/dịch/tách nhạc/OCR — port dần năng lực VTP),
- Tab **Agents & Usage** (điều phối + quota/key rotation),
- Tab **Kênh** (Monaco sửa config), **Remote** (điều khiển từ xa), **Cài đặt** (theme/i18n/shortcut/update).

> Cảnh báo bản quyền: với VideoToolsPro (đóng, cấm dịch ngược) chỉ **mượn ý tưởng UX + dùng engine open-source tương đương** (whisperx/demucs/piper… đều có bản quyền riêng cho phép). Với 1DevTool (MIT) có thể tham khảo mẫu kiến trúc, nhưng **không copy asset/thương hiệu** và không bê license/activation của họ.

---

## 5. Một dòng
1DevTool là **IDE đa-AI-agent** (không phải app video) — giá trị cho OmniCast nằm ở **mô hình cockpit**: usage/quota đa provider, điều phối agent + risk badge, remote control từ điện thoại, terminal/resume, Monaco, MCP/skills, auto-update. Gộp cái đó với **năng lực media của VideoToolsPro** chính là con đường biến OmniCast thành siêu app. Muốn mình bắt đầu từ **bảng usage/quota + key rotation** hay **hàng đợi batch có trạng thái + retry** trước?
