Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` — tuân thủ toàn bộ.

# Brief 02 — Jellyfish + LocalMiniDrama (2 studio "short drama")

- `_refs\Jellyfish` (~608 file) — "AI Short Drama Studio", Apache-2.0, React+Vite.
- `_refs\LocalMiniDrama` (~146 file) — "本地短剧助手" local AI short-drama/manhua tool, MIT.

Đây là 2 repo GẦN use-case OmniCast nhất (kịch bản → tập phim nhiều cảnh, nhân vật lặp lại
xuyên suốt). Mổ cả hai, so sánh chéo.

Câu hỏi riêng (ngoài 10 mục chuẩn):
- Pipeline kịch bản → phân cảnh (分镜/storyboard) → shot: LLM nào, mấy bước, prompt từng bước VERBATIM.
- Quản lý nhân vật: character card/sheet gồm field gì, ảnh chuẩn sinh thế nào, gắn vào từng shot ra sao (đây là chỗ OmniCast cần đối chiếu cast-registry + RefRole của mình).
- Drama pacing: thoại/hội thoại xử lý thế nào (multi-voice?), lip-sync có không, subtitle.
- LocalMiniDrama chạy local: model gì, và cách họ giữ consistency khi model yếu hơn cloud.
- UI workflow của Jellyfish: người dùng duyệt/sửa storyboard ở bước nào — học gì cho trang `/storyboard` của OmniCast.

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_02_Jellyfish_LocalMiniDrama.md`
