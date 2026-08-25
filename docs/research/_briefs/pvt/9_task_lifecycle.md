# Agent 9 — Vòng đời job đầy đủ

Đây là **quét vét cạn**. Wave trước chỉ đọc `task/_rate.py`; bạn phải đọc HẾT `task/`.

## Slice của bạn — pyvideotrans

- `videotrans/task/` — TOÀN BỘ 15 file (~4200 dòng), TRỪ `_rate.py` (đã có agent khác).
- `videotrans/process/` — phần điều phối, không phải stt.

Chú ý: thứ tự bước, điều kiện bỏ qua bước, xử lý lỗi từng bước, dọn dẹp khi hỏng,
tiếp tục job dở, trạng thái job, và mọi kiểm tra "đã xong thật chưa".

## Đối chiếu với OmniCast

- `implementation/src/omnicast/reup/runner.py` — chain 11 stage của ta
- `implementation/src/omnicast/reup/queue.py` — hàng đợi + retry (mới viết hôm nay)
- `implementation/src/omnicast/reup/core/` — jobs, hashing
- `implementation/src/omnicast/reup/project/` — bootstrap, database, profiles

## Phải trả lời

1. Liệt kê ĐẦY ĐỦ các bước của pyvideotrans theo thứ tự, đối chiếu với 11 stage của ta.
   Bước nào ta thiếu hẳn? Bước nào ta làm sai thứ tự?
2. Nó xử lý lỗi giữa chừng ra sao — bỏ job, giữ lại phần đã làm, hay dọn sạch?
3. Nó có cơ chế cache/skip theo nội dung như stage-hash của ta không, hay làm cách khác?
4. Nó kiểm tra gì để kết luận một job THÀNH CÔNG? (Ta gần như không kiểm tra output.)
5. Có bước hậu xử lý nào ta bỏ qua hoàn toàn không — ví dụ ghép lại video gốc,
   chèn intro/outro, xuất nhiều định dạng, ghi metadata?
