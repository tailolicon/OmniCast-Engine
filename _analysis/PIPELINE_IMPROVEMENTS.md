# Cải thiện OmniCast pipeline — rút từ video AMV Factor (phân tích của tôi + Gemini)

Gộp 2 phân tích → các thay đổi cụ thể, map vào file. Đánh dấu: ✅ đã có | ⚠️ một phần | ❌ chưa.

**TIẾN ĐỘ (2026-06-17):**
✅ DONE & verified: 1.1 nhịp đọc biến thiên · 1.2 pitch climax · 1.3 writer small→staggering+equivalence · 1.4 overlay số hero full-screen · 2.3 two-speed editing · 3.1 SFX whoosh/ting (synth assets/sfx/*.wav, _mix_sfx, 24-cue cap) · 4.1 pause 1s trước câu hỏi chương (shift words.json giữ caption sync) · 4.2 kết luận 2 chiều.
🔶 3.2: ducking đã có sẵn (music_lib sidechaincompress); section-intensity defer (cần multi-track, low ROI).
🛠 2.1 chart_gen.py: tool BUILT+verified (bar chart + mũi tên đỏ + credit). Wiring opt-in qua cell `chart_data` — KHÔNG auto-emit (tránh LLM bịa số liệu).
⏳ Defer (polish, optional): 2.2 credit lower-third (cần web_assets trả domain) · 2.4 framing ChapterCard.

## TIER 1 — đòn bẩy cao, ít rủi ro

### 1.1 Nhịp đọc biến thiên theo đoạn (❌ → lớn nhất)
Hiện: rate gần như cố định, chỉ hook 2 shot đầu −6%. Tham chiếu: **hook chậm (~80wpm) → thân nhanh (165–175) → cao trào nhanh hơn → outro chậm (~60)**.
- `render_real_video.py` `render_voice`: nhận **rate theo vai trò scene** (hook/body/climax/outro) thay vì 1 rate. Map section → edge `rate`: hook `-12%`, body `+0%`, climax `+8%`, outro `-10%`.
- Nguồn vai trò: heading scene (HOOK/OUTRO) + vị trí (đoạn liệt kê số liệu = climax). writer.py đã có HOOK/SEGMENT/OUTRO → đủ tag.

### 1.2 Emphasis cao độ ở từ số/tính từ mạnh (⚠️)
Tham chiếu: pitch spike ở "hàng tỷ", "khổng lồ", "bẩn". Edge TTS hỗ trợ SSML `<prosody pitch=>` / emphasis.
- `voice_router`/`render_voice`: với scene chứa số lớn hoặc từ nhấn, bọc token bằng SSML emphasis (edge: `pitch=+15%` cho cụm số). Fallback nếu provider không hỗ trợ.

### 1.3 "Small→staggering" + quy đổi đời thường (⚠️ → writer rule)
Tham chiếu: luôn số nhỏ trấn an → đập số tổng + quy đổi ("= 2.5tr bể bơi", "= thị trấn 50k", "= 1 điều hòa 9000BTU").
- `writer.py` system prompt: thêm RULE — mỗi cụm số lớn PHẢI đi kèm (a) một mốc nhỏ tương phản trước đó và (b) một phép quy đổi sang vật quen thuộc. Critic chấm điểm tiêu chí này.

### 1.4 Overlay SỐ khổng lồ toàn màn (⚠️)
Hiện: kinetic stat = callout nhỏ. Tham chiếu: **số trắng bold cực lớn căn giữa trên b-roll tối**, count-up.
- Dùng Remotion `StatPop` (đã có count-up) ở chế độ **full-screen bignum**: thêm prop `mode:"fullscreen"` (số chiếm ~40% chiều cao, b-roll mờ phía sau). Storyboard route scene có `stat_number` lớn → `template:"remotion:StatPop"` thay vì kinetic overlay khi con số là "cú sốc quy mô".

### 1.5 Outro hard-cut + 1 khối (✅ vừa fix) — chỉ verify
Đã gộp CTA → OutroCTA card. Thêm: cắt đen <0.5s sau từ cuối (kiểm tra tail nhạc không kéo dài).

## TIER 2 — chất lượng hình ảnh/uy tín

### 2.1 Chart data-viz có nguồn + mũi tên đỏ annotate (❌)
Tham chiếu: bar chart Epoch AI + **mũi tên đỏ vẽ tay** trỏ giá trị + credit "epoch.ai CC-BY".
- Thêm `media/providers/chart_gen.py`: matplotlib render bar/line chart từ `stat`-scene data (label+value), style sạch (sans, nền sáng), **annotate mũi tên đỏ** ô quan trọng, watermark nguồn. Storyboard `visual_type:"chart"` → gọi nó. Thay cho web_search_image khi có ≥3 data point.

### 2.2 Credit nguồn on-screen (❌)
Tham chiếu: lower-third "Credit: …", "CC-BY".
- `render_real_video.py` compose: nếu cell có `source_credit` (từ web_assets domain hoặc chart) → vẽ lower-third nhỏ góc dưới-trái. web_assets trả về domain nguồn.

### 2.3 Hai tốc độ dựng (⚠️)
Hiện beat_words=18 đồng đều. Tham chiếu: liệt kê → shot <2s burst; giải thích → 5–8s + Ken Burns.
- `split_into_shots`: scene heading/ý "liệt kê" (phát hiện dấu phẩy chuỗi / từ "như:,gồm") → chunk nhỏ (beat_words ~8); scene giải thích → giữ 18 + đảm bảo Ken Burns. (Ken Burns đã có.)

### 2.4 Framing device lặp giữa chương (❌)
Tham chiếu: UI chat tái xuất mở mỗi chương.
- Thêm Remotion `ChapterCard` (motif kênh, nhận `question` text) chèn đầu mỗi SEGMENT lớn. Per-channel bật/tắt qua config (`framing_device`).

## TIER 3 — âm thanh & sắc thái

### 3.1 SFX whoosh + ting (❌)
- `render_real_video.py`: chèn `whoosh.wav` tại scene-cut lớn (đổi chủ đề), `ting.wav` khi overlay số/kinetic xuất hiện. Mix nhẹ (−18dB). Asset trong `assets/sfx/`.

### 3.2 Music bed chuẩn + ducking −18→−22dB (⚠️)
Hiện duck 0.10. Tham chiếu: nhạc tăng tiết tấu ở thân, trầm ở hook. `music_lib`: chọn intensity theo section (hook=ambient trầm, body=mid-tempo bass). Duck giữ −18→−22dB.

### 3.3 Cắt hơi thở / gap 0.15–0.23s (✅ edge gần đạt)
Edge TTS gap ngắn sẵn; thêm trim khoảng lặng đầu/cuối mỗi clip VO khi concat (đảm bảo ≤0.23s).

## TIER 4 — kịch bản/biên tập (writer/critic)

### 4.1 Pause kịch tính 2s trước câu hỏi chương (❌)
- writer đánh dấu scene "chapter_question"; render chèn 1.5–2s im lặng (b-roll giữ) trước scene đó.

### 4.2 Kết luận 2 chiều cân bằng (⚠️)
- writer rule: trước CTA, BẮT BUỘC 1 đoạn "mặt tốt vs mặt xấu" để khơi tranh luận (tăng comment). Critic kiểm.

### 4.3 Pattern interrupt giải trí mỗi 60–90s (❌, tùy chọn)
- Storyboard chèn 1 scene "comic_relief" (ảnh AI-gen absurd hoặc stock hài) mỗi ~75s. Tránh meme bản quyền; dùng AI-gen. Rủi ro lạc tông → để per-channel opt-in.

## Lệch số cần nhớ
Cut count phụ thuộc ngưỡng scene-detect (tôi 130@0.3 / Gemini 200). Bài học chung không đổi: **2 tốc độ + montage burst + Ken Burns trên shot dài**.
