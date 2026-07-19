# UI VideoToolsPro — BÓC TOÀN BỘ GIAO DIỆN TỪ BINARY (không cần license)

> STATUS: ACTIVE (tài liệu tham chiếu Epic I/V1-V2)

> Nguồn: giải nén PyInstaller `VideoToolsPro.exe` → 60+ module `.pyc` → trích 2.343 chuỗi UI tiếng Việt/emoji (2026-07-04). App đòi mua license nên KHÔNG chạy — toàn bộ dưới đây đọc từ code thật, độ phủ đầy đủ hơn chụp màn hình.
> Mục đích: đối chiếu độ đầy đủ chức năng của OmniCast (bảng gap V1–V12 ở §3).
> File chuỗi thô đầy đủ: `docs_refs_extract/vtp_ui_strings.txt` (2.343 dòng, giữ làm bằng chứng cho agent).

---

## 1. KIẾN TRÚC UI (từ tên module)

2 tab chính (`tab_downloader`, `tab_exporter`) + hệ module con:
- `downloader/`: downloader_ui + adapter riêng từng nền tảng: **douyin, tiktok, youtube, facebook, instagram, bilibili, kuaishou, twitter, threads**
- `exporter/`: 55 module — ui chính, ui_batch, ui_settings, ui_subtitle, ui_timeline, ui_preview, preview_engine, ffmpeg_logic + ffmpeg_filters, ocr_*, sub_template_*, visual_sub_editor, parallel_burn, disk_guard, capcut_*, ai_stt_*, ai_translate_* (deepseek/gemini/grok/groq/openai), ai_sub_fix/generate/translate, voice_reuse, batch_naming
- Hạ tầng: license_dialogs (kích hoạt/mua), updater, services_media (yt-dlp wrapper, chuẩn hóa MP4, patch demucs GPU→CPU fallback)

## 2. CHỨC NĂNG THEO MÀN HÌNH (trích từ chuỗi UI thật)

### 2.1 Tab DOWNLOADER — "⬇ Douyin/YT,FB Downloader"
- Nhập **Link Kênh** hoặc **List link lẻ** (bảng dán nhiều dòng, mỗi link 1 dòng, append không xóa list cũ, auto-tick); tự nhận diện nền tảng từ URL; trích URL từ text share Douyin/TikTok.
- Quét kênh → bảng video + tick chọn / **Chọn tất cả**; **Dịch tên** tiêu đề hàng loạt (dropdown ngôn ngữ, mặc định `vi`, dịch 10 luồng song song SAU khi quét xong để không nghẽn).
- **TẢI VIDEO ĐÃ CHỌN** · **TẢI MP3** (chỉ YouTube) · nút **Dừng** abort ngay file đang tải; fallback cookies Chrome → Edge → không cookies; gợi ý sửa lỗi (đóng Chrome, update yt-dlp).
- Tiện ích: **Cắt Tách Video**, **Cắt ghép nhạc**, Mở thư mục, Lưu vào (chọn folder); chuẩn hóa mọi input về MP4 H.264/AAC (remux nhanh nếu h264, re-encode `h264_nvenc` fallback `libx264` nếu codec lạ).

### 2.2 Tab EXPORTER/EDIT — trung tâm biên tập (màn hình lớn nhất)

**(a) Batch list:** chọn từng file (Ctrl+click) hoặc cả thư mục (có exclusion); **natural sort** part1<part2<…<part10; Lọc; sửa 1 video → **"Áp dụng cho tất cả"** → **Xuất hàng loạt** (parallel_burn, batch_naming, disk_guard kiểm dung lượng trước xuất); Ghép Video (≥2 video).

**(b) Preview + TIMELINE tương tác** (điểm mạnh nhất): click lane→seek; wheel zoom (tâm con trỏ); middle-drag pan; cursor A/B kéo-gim; 4 track:
- **Sub**: block per câu — click sửa popup, sửa inline TRÊN preview (Entry overlay), xóa câu (giữ timecode), drag block, lưu SRT khi thả;
- **Giọng (TTS)**: quét disk tìm mp3 TTS đã sinh, xóa giọng đoạn riêng;
- **Tách giọng** (vocal remove): đặt 2 thanh vàng-xanh chọn đoạn → right-click exclude/bỏ exclude từng đoạn (demucs);
- **SFX**: double-click thêm marker, right-click menu (▶ Nghe thử / chỉnh volume / xóa), preset từ `assets/sfx`, browse file ngoài, persist JSON cạnh video, phát ffplay đúng delay khi preview.

**(c) Phụ đề (ui_subtitle):**
- STT đa nguồn: whisperx (word-level), **Groq**, **CapCut ASR** (workflow: Lấy Audio → CapCut Auto Sub → Tách SRT tự động, có theo dõi CapCut), **BCut ASR**;
- Dịch sub: Gemini / DeepSeek / Grok / Groq / OpenAI + **Prompt Dịch theo thể loại** (dropdown, auto-mở khi chưa chọn); quota token DeepSeek hiện "còn/tổng" + popup nâng gói (QR sepay tự kích hoạt — đây là monetization CỦA tool, bỏ qua);
- **AI Sửa Sub**: quét timeline quá dày/câu quá dài → sửa local (xóa từ đệm) + sửa bằng Gemini, báo thống kê từng loại; Tìm/Thay tất cả;
- **Style phụ đề**: 28 preset màu đặt tên (Classic Vàng, Neon Hồng/Tím/Đỏ/Xanh, Bạc Ánh Kim, Ngọc Trai, pastel…), 10+ hiệu ứng chữ (Viền cơ bản/dày/kép, Glow, Shadow, Nổi 3D, Bóng dài TikTok, Chữ rỗng, Bóng mềm, Retro VHS), Nền sub, Cỡ, Đậm, vị trí (Không/Dưới/Trên-trái/phải…);
- **Catalog template font**: nhóm "Năng động/Sang trọng/…", popup picker **grid card 3 cột, preview render bằng chính font**, nút "Áp dụng"/"Tải & Dùng" (font Google Fonts lazy-download 1 lần, cache, sync vào fontsdir cho libass; thử nhiều mẫu không đóng popup); chọn font theo chữ CHIẾM ĐA SỐ (CJK/Thái/Nga/Ả-rập… tránh ô vuông).

**(d) OCR Sub Cứng (bóc hardsub):** bật OCR mode → **kéo 4 thanh guide trên preview** chọn vùng → bóc SRT (rapidocr); phát hiện GPU NVIDIA → mời tải **GPU pack ~210MB 1 lần, OCR nhanh 3-5x**, tự restart sau cài; guide vẽ bằng coords() move tránh flicker ở 24-30fps.

**(e) Chống trùng / Reup (ui_settings):** Phản chiếu; **logo/watermark** (4 góc + tùy chỉnh vị trí, kích thước, độ trong, **xóa nền logo** bằng luminance+saturation khớp preview); **hiệu ứng video**: Sọc nhiễu (Anti-reup), Vignette, Vintage, Film grain, Light leak, Glow, CRT, Camera REC + slider cường độ (cảnh báo xuất chậm — CPU filter, encode vẫn GPU); **Nền 2 bên** (video dọc → xuất ngang, kiểu nền: Mờ video/Đen/Trắng/Xám/Gradient/Tự chọn ảnh-video + Độ mờ); Tắt nhạc nền; **chữ phủ** (text overlay + màu + 13 hiệu ứng); **Upscale 720p→1080p→2K→4K** (Trung bình/Mạnh).

**(f) Khác:** xuất SRT cho DaVinci Resolve; Compact mode cho màn nhỏ/DPI cao (đảo + yêu cầu restart); Ẩn/Hiện Timeline; log CPU/GPU/RAM khi mở app; Giọng Đọc TTS per video + voice_reuse (tái dùng giọng đã sinh).

## 3. GAP MATRIX — OmniCast đã đủ chưa? (V1–V12)

> OmniCast = dây chuyền AUTO (topic→script→render→đăng). VideoToolsPro = bộ EDIT THỦ CÔNG mạnh. Phần OmniCast thiếu nhất chính là **lớp sửa-tay-khi-cần** — khớp với C1/C3/C4 đã đề xuất trong `NGHIEN_CUU_REFS_FULL.md`.

| # | Chức năng VideoToolsPro | OmniCast | Ưu tiên | Ghi chú |
|---|---|---|---|---|
| V1 | **Timeline tương tác** (seek/zoom/4 track/sửa sub inline/xóa giọng đoạn) | ❌ chỉ có list 46 phân cảnh | **P1-lớn** | Đích đến của Studio: gộp với C1 (pause-sửa) — sửa sub/giọng TRƯỚC render burn. Làm theo phase: (1) track Sub đọc words.json + click-seek trên player; (2) edit inline + save; (3) track TTS/SFX |
| V2 | **Style phụ đề**: 28 preset + 10 hiệu ứng + template font catalog picker | ❌ hardcode trong render | **P1** | = C11 mở rộng. Per-channel: preset + font + vị trí + nền, lưu channels/{id}.json; picker card có preview font là pattern đáng port nguyên |
| V3 | AI Sửa Sub (timeline dày/câu dài, local+LLM) | 🟠 subtitle_sync có | P2 | Thêm bước auto-fix sau STT align, log thống kê sửa |
| V4 | SFX track + thư viện SFX nghe thử | 🟠 music có, SFX ❌ | P2 | = C12 mở rộng: bảng SFX marker theo scene trong Studio |
| V5 | Logo/watermark + xóa nền logo | ❌ | P2 | Branding kênh — channels/{id}.json đã có brand fields |
| V6 | Hiệu ứng video (grain/vignette/glow/CRT…) + upscale 2K/4K | ❌ | P3 | Nội dung gốc AI không cần anti-reup; grain/vignette nhẹ tăng chất điện ảnh — optional |
| V7 | Nền 2 bên (dọc→ngang) | 🟠 RenderVariantExporter 9:16 có chiều ngược | P3 | Thêm mode letterbox-blur khi convert variant |
| V8 | Downloader đa nền tảng + dịch tiêu đề hàng loạt | ❌ | P3 | Chỉ phục vụ nghiên cứu đối thủ (C14) — không tải để reup |
| V9 | OCR hardsub + GPU pack on-demand | ❌ | P3 | Ít cần cho pipeline gốc; pattern "tải pack GPU 1 lần" hay cho local-SD/XTTS |
| V10 | CapCut/BCut ASR free | ❌ | P3 | Đường STT miễn phí dự phòng — thêm provider stt vào manifest sau |
| V11 | Batch "Áp dụng cho tất cả" + natural sort + disk_guard | 🟠 JobEngine có queue | P2 | "Áp style 1 video cho cả batch" + check dung lượng đĩa trước render (disk_guard ~20 dòng, làm ngay được) |
| V12 | Nghe thử TTS/SFX per đoạn ngay trên preview | 🟠 /api/voice/preview có | **P1** | = C3: nút ▶ trên từng dòng phân cảnh trong Studio (audio scene đã có sẵn `_assets/scene_XX.mp3`) |

**Kết luận độ đầy đủ:** OmniCast KHÔNG thiếu về pipeline tự động (hơn hẳn VideoToolsPro: discovery/debate/compliance/publish/analytics), nhưng **thiếu lớp kiểm soát biên tập thủ công**: V1 (timeline) + V2 (style phụ đề) + V12 (nghe thử per-scene) là 3 việc P1 — gộp vào Epic I/I1 (cùng nhóm C1/C3/C4 của `NGHIEN_CUU_REFS_FULL.md`), V11-disk-guard + V3 + V4 + V5 vào I2.
