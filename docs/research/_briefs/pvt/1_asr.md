# Agent 1 — ASR và dựng phụ đề

## Của pyvideotrans, đọc kỹ

- `videotrans/recognition/` — mọi engine nhận dạng.
- `videotrans/process/stt_fun.py` — tham số truyền vào whisper.
- `videotrans/configure/config.py` — khối settings mặc định (VAD, ngưỡng).
- Chỗ nào cắt câu, gộp câu, dựng `SrtItem`, xử lý `speech_timestamps`.
- `merge_short_sub`, `max_speech_duration_s`, `min_speech_duration_ms`, silero VAD.

## Của OmniCast, đối chiếu

- `implementation/src/omnicast/reup/asr/faster_whisper_engine.py`
- `implementation/src/omnicast/reup/asr/models.py`
- `implementation/src/omnicast/reup/asr/persistence.py`

## Câu hỏi phải trả lời

1. pyvideotrans làm gì để KHÔNG sót đoạn nói mà ta không làm?
2. Nó cắt và gộp câu theo luật nào? Ta có luật đó không, hay chỉ nhận nguyên
   segment whisper trả về?
3. Đoạn nói quá dài hoặc quá ngắn được xử lý ra sao?
4. Có bước hậu kiểm nào so transcript với độ dài audio để phát hiện sót không?
5. Nó chạy nhận dạng nhiều lần / nhiều chế độ rồi hợp nhất, hay một lượt duy nhất?
