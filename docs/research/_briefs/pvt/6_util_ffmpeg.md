# Agent 6 — Lớp tiện ích & mọi lệnh ffmpeg

Đây là **quét vét cạn** slice của bạn, không phải soi theo nghi vấn có sẵn. Đọc HẾT
các file trong slice, đừng bỏ file nào vì tưởng không liên quan.

## Slice của bạn — pyvideotrans

- `videotrans/util/` — TOÀN BỘ (~4600 dòng, 16 file).
Đặc biệt chú ý: mọi chỗ dựng lệnh ffmpeg/ffprobe, đo thời lượng, kiểm tra file hợp lệ,
xử lý đường dẫn có ký tự Trung/khoảng trắng, tạo file tạm, dọn file tạm, và mọi hàm
"kiểm tra trước khi làm" (guard).

## Đối chiếu với OmniCast

- `implementation/src/omnicast/reup/media/` — toàn bộ
- `implementation/src/omnicast/reup/exporting/`
- `implementation/src/omnicast/reup/subtitle/hardsub.py` (phần dựng lệnh ffmpeg)

## Phải trả lời

1. Liệt kê MỌI cờ ffmpeg pyvideotrans dùng mà ta không dùng, và ngược lại. Cờ nào ảnh
   hưởng chất lượng hoặc tính đúng đắn?
2. Nó đo thời lượng / kiểm tra file đầu ra bằng cách nào sau mỗi bước? Ta gần như không
   kiểm tra gì.
3. Nó xử lý đường dẫn có ký tự phi-ASCII và ký tự đặc biệt ra sao?
4. Có hàm tiện ích nào giải quyết đúng một lớp bug mà ta đang tự xoay xở không?
5. Nó dọn file tạm khi lỗi thế nào?
