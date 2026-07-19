# Phân tích VideoToolsPro & 1DevTool — chức năng, thông báo, và đề xuất cải thiện

> Phạm vi: phân tích hai tham chiếu trong `_refs/` để xem có gì áp dụng/mở rộng cho OmniCast, **đặc biệt phần giao diện vận hành**. Liệt kê chức năng nút bấm + thông báo để bạn đối chiếu mức độ dùng được.
>
> **Lưu ý trung thực về phương pháp:** cả hai đều là phần mềm đóng (closed-source).
> - VideoToolsPro: gói PyInstaller, code chính biên dịch bằng mypyc (`.pyd`). Mình **không chạy** app mà chỉ đọc tĩnh: disclaimer, file cấu hình/JSON không mã hoá, danh sách thư viện đóng gói, và chuỗi văn bản trích từ module biên dịch. Vì vậy **nhãn nút bên trong từng tab** chỉ trích được một phần — engine/tính năng thì xác định chắc chắn qua thư viện đi kèm; **thông báo hệ thống/license** thì trích được gần như đầy đủ (verbatim bên dưới).
> - 1DevTool: là **bộ cài NSIS** (`1DevTool` v1.29.0), payload nén LZMA bên trong. Sandbox không có 7‑Zip/mạng để giải nén, nên **không đọc được nút/thông báo của nó**. Mục riêng bên dưới nêu cách bạn tự kiểm tra.
> - Đề xuất bên dưới là **mượn ý tưởng UX**, KHÔNG sao chép code/asset (disclaimer của VTP cấm dịch ngược; nhạc/SFX/font đi kèm là IP bên thứ ba — OmniCast chỉ dùng nhạc AI/royalty-free).

---

## A. VideoToolsPro là gì

Bộ công cụ **hậu kỳ video desktop (GUI Tkinter, Windows)** của tác giả "Nguyễn Vinh Ka", có bản quyền + khoá theo license (HWID, phân biệt **key App** và **key Sub**, có chế độ **dùng thử/trial**). Đóng gói kèm `ffmpeg/ffprobe/ffplay`, thư viện AI nặng, nhạc nền + hiệu ứng âm thanh + font.

### Tính năng (xác định từ disclaimer + thư viện đóng gói + config)

| Nhóm | Engine/thư viện đi kèm (bằng chứng) | Ghi chú |
|---|---|---|
| **Tải video** | `yt_dlp`, `playwright` | Tab xác nhận: **"⬇ Douyin/YT,FB Downloader"**. Disclaimer ghi Douyin/YouTube/TikTok/Facebook |
| **STT / tạo phụ đề** | `faster_whisper`, `whisperx` | whisperx = canh từ (word-level). Config `whisper_model: medium` |
| **TTS / lồng tiếng** | `edge_tts` (mặc định), `piper`, `supertonic`, `vieneu`, `neucodec`, `sea_g2p` | Đa engine neural; `sea_g2p` = G2P tiếng Việt. Disclaimer nhắc thêm CapCut, NgocHuyen, Piper |
| **Dịch phụ đề** | API: `gemini` (mặc định `gemini-3.1-flash-lite`), `openai` (`gpt-4o-mini`), `groq` (`gpt-oss-120b`); có **backup keys**; disclaimer thêm DeepSeek, Grok | Prompt template trong `exporter/prompts/prompts.json` — **nhận diện thể loại** (cổ trang/hiện đại/anime…) + dịch **khớp khẩu hình** |
| **LLM nội bộ (offline)** | `llama_cpp` | Chạy LLM cục bộ — fallback khi hết quota API |
| **OCR (bóc hardsub)** | `rapidocr_onnxruntime` | Nhận chữ cháy cứng trên video |
| **Tách nhạc/giọng** | `demucs`, `librosa`, `soxr`, `soundfile`, `lameenc` | Tách vocal/nhạc nền |
| **Render/Xuất bản** | `ffmpeg`, `av` (PyAV), `cv2` (OpenCV) | Burn phụ đề, ghép nhạc/hiệu ứng |
| **Xử lý hàng loạt** | — | "Batch mode" theo disclaimer |
| **Thư viện media kèm** | 15 nhạc nền (`assets/bgm`), 26 SFX (`assets/sfx`: vỗ tay, swoosh, ding, vine boom…), nhiều font (Be Vietnam Pro, Bangers, Lobster…) | |

### Chi tiết giao diện (trích từ tên hàm/biến trong module biên dịch)

Giao diện dạng **notebook nhiều tab** (`_on_tab_changed`), kèm các tiện ích vận hành đã xác nhận tồn tại:

- **Thanh tiêu đề tối** (`_set_dark_titlebar`), style notebook tuỳ biến (`_style_notebook`), theme `dark-blue`.
- **Trình phát nhạc nền trong app** có nút bật/tắt: `_toggle_bgm`, `_start_bgm`, `_load_bgm_muted`/`_save_bgm_muted` (ghi nhớ trạng thái mute).
- **Hiệu ứng nút bấm**: `_setup_button_animations` + `_on_enter/_on_leave/_on_press/_on_release` (hover/nhấn), `_animate_rainbow`.
- **Vẽ speaker/waveform**: `_draw_speaker`.
- **Nhãn đếm ngày license/trial** tự cập nhật: `_update_days_label`, `_update_sub_days_label`, `_update_sub_trial_label`, `_init_sub_days_label`.
- **Tự kiểm tra license định kỳ** (chống share key): `_license_recheck`, `_license_recheck_kick`.
- **Nhắc nâng cấp**: `_prompt_dl_license`, `_prompt_sub_upgrade` (nút "Nâng cấp ↗").
- **Màn splash** (`splash_bg.jpg`) với các bước nạp; **preview** (`preview_placeholder_bg.jpg`).
- **Tuỳ chọn mật độ**: `timeline_visible` (ẩn/hiện timeline), `compact_mode` (chế độ gọn) — lưu trong config.

> Chưa trích được đầy đủ nhãn nút bên trong từng tab xử lý (Tải/Tạo sub/Dịch/Lồng tiếng/Render) vì chúng nằm trong module mypyc đóng gói. Nếu bạn cần đủ 100%, xem mục **D — cách kiểm tra trực tiếp**.

---

## B. Thông báo của VideoToolsPro (trích nguyên văn)

Đây là phần trích được **gần như đầy đủ** — chủ yếu là lớp khởi động, license và mạng. Bạn có thể dùng để đối chiếu trải nghiệm.

**Khởi động / nạp app**
- `Đang khởi động hệ thống...`
- `Đang kiểm tra license...`
- `Đang nạp module xử lý...`
- `Đang chuẩn bị giao diện...`
- `Đang hoàn tất...`

**License / tài khoản**
- `🎉 Chào mừng dùng thử Video Tools Pro!`
- `⏰ Còn N ngày dùng thử` · `📥 Dùng thử: …` · `📥 Sub: VIP MAX`
- `Đăng nhập thành công! Còn …`
- `License hợp lệ, còn N ngày` · `License hợp lệ (0 ngày)`
- `License không hợp lệ.`
- `Không thể xác thực license. Kiểm tra kết nối mạng.`
- `Đây là key App, không phải key Sub.` · `Đây là key Sub, không phải key App.`
- `⚠️ Tài khoản đã hết hạn.` · `Tài khoản hết hạn`
- `⚠️ Tài khoản đã đăng nhập trên thiết bị khác.`
- `❌ Tài khoản đã bị vô hiệu hóa.` · `Tài khoản bị khóa`
- `Phiên đăng nhập …` · `Vui lòng đăng nhập lại.`
- nút: `… ngày  •  Nâng cấp ↗` · `… để gia hạn.` · `… để mua bản quyền`

**Mạng / server**
- `❌ Không thể kết nối server xác thực.`
- `❌ Không thể kết nối server xác thực (2 lần liên tiếp).`
- `Vui lòng kiểm tra kết nối mạng và thử lại.` · `Vui lòng kiểm tra kết nối mạng.`
- `Mất kết nối` · `Không thể kết nối server: …` · `… giờ (offline)`

**File / bảo mật**
- `Thiếu file cần thiết` / `THIẾU FILE CẦN THIẾT`
- `Thiếu ffplay.exe` · `Không tìm thấy ffplay.exe` · `Đặt ffplay.exe vào: …` · `Tải tại: https://ffmpeg.org/download.html`
- `Lỗi bảo mật` · `Phát hiện file bị thay đổi! … Vui lòng tải lại bản gốc từ nhà phát triển.`
- `Lỗi khởi động` · `Lỗi set icon: …` · `Import lỗi: …` · `Ứng dụng sẽ đóng.`

**Liên hệ**
- `📞 Liên hệ Zalo/ĐT: 0975670347 | Nguyễn Vinh Ka`

> Nhận xét: bộ thông báo **rất mạnh ở license/mạng** nhưng **gần như không có thông báo lỗi theo từng job xử lý** (file nào lỗi ở bước nào, vì sao). Đây chính là khoảng trống UX để cải thiện (mục C).

---

## C. Đề xuất mở rộng/cải thiện — đặc biệt phần giao diện vận hành

### C.1. Mượn cho **dashboard OmniCast** (giúp người vận hành dễ dùng hơn)

1. **Hàng đợi batch có trạng thái từng file + nút "retry lỗi"** — VTP có batch nhưng thông báo lỗi nghèo. OmniCast nên hiển thị mỗi job/scene: chờ → đang chạy → xong/lỗi/timeout, kèm lý do lỗi và nút **chỉ chạy lại cái lỗi** (khớp đúng phần per-image retry Flow vừa làm). Đây là cải thiện UX giá trị nhất.
2. **Thư viện nhạc nền + SFX có sẵn, chọn nhanh + nút mute** — VTP ship 15 BGM + 26 SFX và có trình phát trong app. OmniCast nên có bộ **nhạc/SFX royalty-free hoặc AI-gen** chọn theo kênh ngay trên dashboard (KHÔNG copy file của VTP — IP bên thứ ba).
3. **Khung Preview trước khi render** — VTP có preview placeholder. Dashboard nên xem trước 1 scene/khung hình + phụ đề trước khi tốn thời gian render cả video.
4. **Tuỳ chọn mật độ giao diện**: `compact_mode` + ẩn/hiện timeline. Hữu ích khi vận hành nhiều kênh trên một màn hình.
5. **Đếm tiến độ khởi động/giai đoạn rõ ràng** ("Đang nạp module…") — áp cho các pipeline dài để người vận hành biết đang ở bước nào thay vì "đang chạy".
6. **Xoay vòng nhiều API key (backup keys)** cho Gemini/Groq/OpenAI — VTP có `gemini_backup_keys`, `groq_backup_keys`. OmniCast đã có `voice_fallback`; nên thêm **LLM key rotation** để không gãy khi 1 key hết quota.

### C.2. Mượn cho **media pipeline OmniCast** (engine/kỹ thuật)

7. **Prompt dịch nhận-diện-thể-loại + khớp khẩu hình** (`prompts.json`) — nếu OmniCast làm bản đa ngữ/lồng tiếng, mẫu prompt của VTP (suy luận cổ trang/hiện đại/anime, chọn đại từ Hán-Việt, giữ tên riêng) rất đáng tham khảo cho agent Writer/Dub.
8. **LLM nội bộ `llama_cpp` làm fallback offline** — khi hết quota API dịch/biên tập, có đường chạy cục bộ.
9. **WhisperX (canh từ)** — OmniCast đã làm phụ đề word-synced bằng whisper/ASS; whisperx là bộ căn chỉnh mạnh hơn, đáng cân nhắc nâng cấp.
10. **Demucs tách vocal/nhạc** — làm sạch audio nguồn hoặc bóc nhạc nền khi tái sử dụng tư liệu.
11. **TTS bổ sung: piper/supertonic/vieneu (offline, có tiếng Việt)** — thêm voice fallback offline cho `voice_fallback`, đúng nguyên tắc "neural-only" của OmniCast.
12. **OCR bóc hardsub (rapidocr)** — khi nguồn có chữ cháy cứng cần lấy lại.
13. **Mở rộng nguồn tải bằng yt-dlp + playwright** — OmniCast đã dùng yt-dlp cho stock; có thể mở thêm Douyin/FB như VTP nếu cần tư liệu.

### C.3. Nếu mục tiêu là **cải thiện chính VideoToolsPro** (góc người vận hành)
- Bảng **log/lịch sử job** + thông báo lỗi theo từng bước (hiện chỉ mạnh ở license/mạng).
- **Resume sau crash** (cache kết quả từng bước) — như cơ chế OmniCast.
- **Kéo-thả thư mục input**, phím tắt, chỉ báo **chế độ offline** rõ ràng (đã thấy chuỗi "offline").
- **Nút "chạy lại các file lỗi"** sau batch.

---

## D. 1DevTool — trạng thái & cách bạn tự kiểm tra

Từ file chỉ xác định được: **bộ cài NSIS**, tên sản phẩm **`1DevTool`**, **phiên bản 1.29.0**, ~187 MB. Toàn bộ ứng dụng nằm nén bên trong; trong môi trường này không có công cụ giải nén nên **không liệt kê được nút/thông báo của nó** (các chuỗi "TTS/SUB/KEY" thấy lúc quét chỉ là nhiễu do dữ liệu nén). Tra web cũng không ra sản phẩm cụ thể tên này (kết quả chỉ là các tool sub/TTS chung chung), nên mình **không suy đoán** chức năng để tránh sai.

Cách kiểm tra trực tiếp (chọn 1):
1. **Giải nén không cài**: chuột phải file → mở bằng **7‑Zip** (`7z x 1DevTool-...exe -o1devtool_extract`). Sẽ thấy `$PLUGINSDIR`, các thư mục `resources/` (nếu Electron có `app.asar`) hoặc `_internal/*.pyd` (nếu PyInstaller). Cho mình biết cấu trúc, mình phân tích tiếp.
2. **Cài vào máy ảo / thư mục portable** rồi chụp màn hình từng tab gửi mình — mình ghi ra toàn bộ nhãn nút + thông báo như đã làm với VTP.
3. Nếu bạn copy thư mục đã cài (giống `_rt` của VTP) vào `_refs/`, mình trích chuỗi UI tương tự.

> Lưu ý an toàn: chỉ chạy/cài nếu bạn tin nguồn file. Cả hai sản phẩm đều khoá license và disclaimer cấm dịch ngược — mình chỉ giúp **kiểm kê chức năng & lấy ý tưởng UX**, không bẻ khoá/qua mặt bản quyền.

---

## E. Tổng kết 1 dòng
VideoToolsPro = kho **ý tưởng UX cho người vận hành** (hàng đợi batch có trạng thái, thư viện BGM/SFX, preview, compact mode, key rotation, prompt dịch theo thể loại) và **danh mục engine** (whisperx, demucs, piper/vieneu TTS, llama_cpp, rapidocr) đáng cân nhắc cho OmniCast — lấy ý tưởng, không lấy code/asset. 1DevTool cần bạn giải nén/cài rồi mình mới kiểm kê được.
