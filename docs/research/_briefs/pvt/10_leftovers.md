# Agent 10 — Phần còn lại, và cái ta có mà họ không có

Đây là agent **quét nốt** để không còn vùng trắng. Slice của bạn là mọi thứ chưa ai đọc.

## Slice của bạn — pyvideotrans

- `videotrans/component/` (~5400 dòng) — phần LOGIC, bỏ qua code dựng giao diện Qt.
- `videotrans/winform/` — chỉ phần logic nghiệp vụ và validate đầu vào.
- `videotrans/mosstts/`
- `videotrans/mainwin/` — chỉ phần điều phối, bỏ layout.

Cái đáng tìm ở đây là **những rào chắn và kiểm tra đầu vào** mà một ứng dụng desktop
trưởng thành tích luỹ được: cảnh báo trước khi chạy, phát hiện cấu hình sai, kiểm tra
file nguồn, giới hạn an toàn. Backend của ta không có UI nên rất dễ bỏ sót lớp này.

## Đối chiếu với OmniCast

- `implementation/src/omnicast/reup/ops/` (~1300 dòng — doctor, preflight?)
- `implementation/src/omnicast/api/reup_routes.py` — phần validate request
- Bất cứ chỗ nào ta kiểm tra điều kiện trước khi chạy

## Phải trả lời

1. Nó chặn những cấu hình sai nào TRƯỚC khi chạy? Ta chặn được bao nhiêu trong số đó?
2. Nó cảnh báo người dùng điều gì mà ta im lặng bỏ qua?
3. `mosstts` là gì, có gì đáng lấy không?
4. **Ngược lại**: OmniCast có gì pyvideotrans KHÔNG có mà thực sự tốt hơn? Nói thẳng,
   đừng nịnh — chỉ kể thứ giải quyết vấn đề thật.
5. Có phần nào của pyvideotrans rõ ràng KHÔNG nên bắt chước không, và vì sao?
