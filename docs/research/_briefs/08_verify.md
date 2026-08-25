Đọc trước: `E:\Project\OmniCast Engine\docs\research\_briefs\COMMON_CONTEXT.md` (phần bối cảnh; nhiệm vụ của bạn KHÁC — bạn là VERIFIER đối kháng).

# Brief 08 — Nghiệm thu chéo 7 report REFS_SB (adversarial verify)

Các report `docs/research/REFS_SB_01..07*.md` do agent khác viết bằng cách đọc `_refs\`.
Nhiệm vụ: TÌM CÁCH BÁC BỎ chúng — bắt bịa đặt, trích sai, và lỗ hổng coverage. Không tin
report; chỉ tin code.

Với TỪNG report (cả 7):
1. Chọn ≥8 claim quan trọng (ưu tiên: cơ chế consistency, schema, số liệu cụ thể) trong đó
   ≥3 là khối "prompt verbatim". Mở đúng `file:line` được cite trong `_refs\` và đối chiếu:
   - Khối verbatim có KHỚP TỪNG CHỮ với code thật không (bỏ qua khác biệt whitespace)?
   - Claim cơ chế có đúng với code không, hay suy diễn quá đà?
2. Kiểm coverage: report có đủ 10 mục bắt buộc của COMMON_CONTEXT không? Mục 4 (prompt
   verbatim) có CHÉP ĐỦ các prompt chính của repo không — grep nhanh trong repo các file
   prompt/template lớn xem report có bỏ sót file prompt quan trọng nào.
3. Kiểm license ghi trong report với LICENSE thật của repo.

Output: `E:\Project\OmniCast Engine\docs\research\REFS_SB_00_VERIFY.md` gồm:
- Bảng mỗi report: số claim kiểm / khớp / sai / bịa; verdict TIN ĐƯỢC | TIN CÓ ĐIỀU KIỆN | PHẢI LÀM LẠI.
- Danh sách CỤ THỂ từng lỗi tìm thấy (report nào, claim gì, thực tế trong code là gì, file:line).
- Danh sách prompt/file quan trọng bị BỎ SÓT cần bổ sung (để round 2 chạy đúng chỗ).
Chỉ được ghi file này; cấm sửa mọi file khác; cấm sửa `_refs\`.
