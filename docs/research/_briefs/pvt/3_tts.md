# Agent 3 — Lồng tiếng

## Của pyvideotrans, đọc kỹ

- `videotrans/tts/` — mọi engine và lớp điều phối.
- Task lồng tiếng trong `videotrans/task/` (tên có thể là `_dubbing.py` hoặc tương đương).
- `remove_dubb_silence`, `dubbing_thread`, `dubbing_wait`.
- Cách xử lý khi câu dịch đọc ra dài hơn slot gốc.
- Cách ghép các clip lên timeline và chèn khoảng lặng.
- Retry khi provider lỗi hoặc trả rỗng.

## Của OmniCast, đối chiếu

- `implementation/src/omnicast/reup/tts/pipeline.py`
- `implementation/src/omnicast/reup/audio/voiceover_track.py`

## Câu hỏi phải trả lời

1. Nó có cắt khoảng lặng đầu và cuối mỗi clip TTS không? Ta không làm — hậu quả gì
   với việc căn timing?
2. Nó chạy song song bao nhiêu luồng, và có chặn nhịp để tránh rate limit không?
   (Ta vừa thêm pool 4 luồng cho engine mạng.)
3. Nó ghép clip lên timeline bằng cách nào: pad silence, concat, hay overlay theo
   mốc thời gian tuyệt đối? Cách nào chống trôi tốt hơn?
4. Clip rỗng hoặc provider trả lỗi được xử lý ra sao — bỏ qua, hay chèn im lặng đúng
   độ dài slot? (Bỏ qua sẽ làm lệch mọi câu sau.)
5. Nó có kiểm tra độ dài clip trả về so với dự kiến không?
