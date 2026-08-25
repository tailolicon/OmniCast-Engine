# Agent 5 — Phụ đề, burn-in, và thứ tự pipeline

## Của pyvideotrans, đọc kỹ

- Cách nó ghi ASS và SRT: style mặc định, có khai `PlayResX`/`PlayResY` không.
- Lệnh ffmpeg nó dùng để burn phụ đề, và thứ tự các filter.
- `videotrans/task/` — thứ tự các bước end-to-end của một job.
- Mọi guard và kiểm tra trước khi coi một job là hoàn thành.
- Cách nó xử lý câu phụ đề quá dài (xuống dòng, giới hạn ký tự mỗi dòng).

## Của OmniCast, đối chiếu

- `implementation/src/omnicast/reup/subtitle/export.py`
- `implementation/src/omnicast/reup/subtitle/hardsub.py`
- `implementation/src/omnicast/reup/runner.py` — thứ tự stage

## Câu hỏi phải trả lời

1. Nó có khai `PlayRes` trong file ASS không? Ta KHÔNG khai, nên libass rơi về hệ quy
   chiếu mặc định 384x288 — mọi con số cỡ chữ và lề của ta đều nằm trong hệ đó. Nếu
   pyvideotrans khai PlayRes theo đúng kích thước video thì cách làm nào đúng hơn,
   và hệ quả khi đổi độ phân giải nguồn là gì?
2. Style mặc định của nó: font, cỡ, viền, bóng, lề — so với ta.
3. Nó ngắt dòng phụ đề theo luật nào (số ký tự tối đa mỗi dòng, ưu tiên dấu câu)?
4. Thứ tự stage của nó khác ta chỗ nào? Có bước nào ta thiếu hẳn?
5. Nó kiểm tra gì trước khi tuyên bố job thành công — độ dài output, số dòng phụ đề,
   có track audio hay không?
