# Agent 7 — Tầng dịch

Đây là **quét vét cạn** slice của bạn. Đọc HẾT các file trong slice.

## Slice của bạn — pyvideotrans

- `videotrans/translator/` — TOÀN BỘ (~2300 dòng, 27 file).
Chú ý: cách chia lô câu để gửi model, cách giữ ĐÚNG số dòng vào bằng số dòng ra,
xử lý khi model trả thiếu/thừa dòng, retry, giới hạn nhịp, ngữ cảnh giữa các lô,
xử lý ký tự đặc biệt và xuống dòng trong câu.

## Đối chiếu với OmniCast

- `implementation/src/omnicast/reup/translate/` — TOÀN BỘ (~7100 dòng, module lớn nhất
  của chúng tôi; gồm contextual pipeline, semantic QC, checkpoint, llm_backends).

## Phải trả lời

1. **Toàn vẹn số dòng**: pyvideotrans làm gì để đảm bảo mỗi câu gốc có đúng một câu
   dịch? Ta khớp theo id — có lỗ hổng nào khiến một câu bị rơi im lặng không?
2. Nó chia lô theo kích thước nào, và ghép ngữ cảnh giữa các lô ra sao?
3. Khi model trả về sai định dạng, nó làm gì? Bỏ lô, retry, hay chèn nguyên bản gốc?
4. Nó có phát hiện bản dịch rỗng / trùng lặp / còn nguyên tiếng Trung không?
5. So sánh độ phức tạp: pipeline contextual của ta (scene planner, semantic pass,
   QC, review gate) có giải quyết vấn đề gì mà pyvideotrans bỏ qua — hay ngược lại,
   ta phức tạp hoá thứ họ đã làm gọn hơn và chắc hơn?
