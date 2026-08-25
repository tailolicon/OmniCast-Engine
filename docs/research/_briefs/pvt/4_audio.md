# Agent 4 — Trộn tiếng và âm thanh nền

## Của pyvideotrans, đọc kỹ

- Tách giọng khỏi nhạc nền (uvr / demucs / bất cứ thứ gì nó dùng) — có bật mặc định không.
- Phần mixdown trong `videotrans/task/`.
- Hệ số ducking, chuẩn hoá loudness, chống clipping.
- Cách giữ tiếng nền đồng bộ khi video bị giãn thời gian.

## Của OmniCast, đối chiếu

- `implementation/src/omnicast/reup/audio/mixdown.py`
- `implementation/src/omnicast/reup/media/retime.py`, hàm `_stretch_original_bed`

## Câu hỏi phải trả lời

1. Nó có tách giọng gốc khỏi nhạc nền trước khi trộn không? Ta chỉ hạ âm lượng cả
   track gốc xuống khoảng 0.07 — nghĩa là giọng Trung vẫn còn lẫn dưới giọng Việt.
   pyvideotrans giải quyết thế nào?
2. Hệ số ducking và loudness target cụ thể của nó là bao nhiêu?
3. Khi video bị giãn, nó xử lý tiếng nền ra sao — giãn theo, hay dựng lại từ đầu?
4. Có chuẩn hoá loudness ở bước cuối không, theo chuẩn nào?
