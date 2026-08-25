Đọc trước: `docs/research/_briefs/v2/COMMON_V2.md` và tuân đủ 2 tầng + chuẩn output.

# Nhóm A1 — DỊCH & LỒNG TIẾNG: `_refs/VideoLingo` + `_refs/pyvideotrans`

Đây là 2 repo dịch/dub video trưởng thành. OmniCast có `media/tts.py`,
`media/voice_router.py`, `media/subtitle.py` phần lớn TỰ CHẾ. Trọng tâm moi:

Tầng 1 VERBATIM — đặc biệt săn:
- Prompt dịch thuật/tách câu/hiệu đính của VideoLingo (nó nổi tiếng vì chuỗi prompt dịch
  nhiều bước: split, summarize, translate, reflect, adapt cho phụ đề). Chép NGUYÊN VĂN
  từng bước + config chunk/độ dài dòng phụ đề.
- Mọi tham số TTS từng engine (edge-tts, azure, openai, gpt-sovits, fish, cosyvoice...):
  rate/pitch/volume mặc định, retry, giới hạn ký tự mỗi lượt, cách chèn nghỉ, xử lý số/
  viết tắt, sample rate xuất.
- Tham số align/ghép audio-video: cách 2 repo co giãn thời lượng khi bản dịch dài/ngắn hơn
  (tempo atempo? cắt nghỉ? ép tốc độ TTS?), ngưỡng chấp nhận lệch, tham số ffmpeg nguyên văn.
- Whisper/ASR config (model, vad, beam, ngôn ngữ), và mọi bộ lọc hậu xử lý phụ đề.

Tầng 2 CƠ CHẾ — nghi vấn phải trả lời:
- Chuỗi dịch nhiều bước của VideoLingo hơn gì cách OmniCast viết thẳng script? Bước nào
  đáng ghép vào writer/critic khi làm kênh đa ngôn ngữ?
- pyvideotrans quản lý hàng chục engine TTS bằng cấu trúc nào (registry? per-engine caps?)
  — so với `voice_router.py` của OmniCast, thiếu/yếu gì (fallback chain, timing proportional,
  per-voice limits)?
- Cách họ đồng bộ phụ đề ↔ audio ↔ video (SRT timing chuẩn hoá) so với `media/subtitle.py`.

Output: `docs/research/V2_A1_TTSDub.md`.
