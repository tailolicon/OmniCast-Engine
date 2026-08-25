# Agent 8 — Mọi hằng số và giá trị mặc định

Đây là **quét vét cạn**. Nhiệm vụ của bạn là lập BẢNG ĐỐI CHIẾU đầy đủ, không phải
chọn lọc vài chỗ đáng ngờ.

## Slice của bạn — pyvideotrans

- `videotrans/configure/` — TOÀN BỘ (~1900 dòng, 7 file), đặc biệt khối settings mặc định.
- `videotrans/codes/`
- Mọi hằng số nằm rải trong `videotrans/` mà bạn bắt gặp (ngưỡng, timeout, số luồng,
  kích thước lô, tỉ lệ, cờ bật/tắt).

## Đối chiếu với OmniCast

Tìm hằng số tương ứng ở bất cứ đâu trong `implementation/src/omnicast/reup/` và
`implementation/src/omnicast/ingest/douyin/`.

## Phải trả lời

Xuất một BẢNG: `| Hằng số | pyvideotrans | OmniCast | Lệch? | Hậu quả |`

Phủ tối thiểu các nhóm: ngưỡng VAD và ASR, trần tốc độ audio/pts, số luồng của từng
tầng, timeout mạng và retry, kích thước lô dịch, âm lượng trộn và ducking, tham số
encode (crf/preset/gop), giới hạn ký tự phụ đề, và mọi cờ bật/tắt tính năng.

Chỗ nào ta KHÔNG có hằng số tương ứng (tức đang dùng mặc định của thư viện) thì ghi rõ
"dùng mặc định thư viện: <giá trị>" — vì đó chính là loại bug đã cắn chúng tôi hai lần
(VAD 2000ms, condition_on_previous_text=True).

Sau bảng, liệt kê các lệch NGHIÊM TRỌNG theo định dạng phát hiện trong COMMON.md.
