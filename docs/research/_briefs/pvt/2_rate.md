# Agent 2 — Căn tốc độ và giãn hình

## Của pyvideotrans, đọc kỹ

- `videotrans/task/_rate.py` — trọng tâm.
- Chỗ dùng `max_audio_speed_rate`, `max_video_pts_rate`.
- Cách nó tính lại timeline sau khi đổi tốc độ.
- Xử lý câu đầu tiên, câu cuối cùng, và khoảng lặng.
- Cách ghép lại video sau khi đổi pts.

## Của OmniCast, đối chiếu

- `implementation/src/omnicast/reup/audio/rate_align.py`
- `implementation/src/omnicast/reup/media/retime.py`

## Câu hỏi phải trả lời

1. Nó phủ TOÀN BỘ timeline hay chỉ những đoạn có thoại? (Ta vừa vá lỗi mất 6,1 giây
   đầu vì không ô nào phủ phần trước câu thoại đầu tiên — hãy kiểm tra xem còn lỗ
   hổng cùng loại nào nữa không, ví dụ đoạn sau câu cuối.)
2. Hằng số trần tốc độ audio và trần pts video của nó là bao nhiêu? Khác ta thế nào?
3. Nó có gộp các đoạn liền kề không cần đổi tốc độ để giảm số lần cắt và encode không?
   (Ta cắt 369 đoạn rồi ghép — mỗi đoạn một lần encode.)
4. Nó chống trôi timestamp bằng cách gì?
5. Nó xử lý ra sao khi một câu dịch dài gấp nhiều lần slot gốc?
