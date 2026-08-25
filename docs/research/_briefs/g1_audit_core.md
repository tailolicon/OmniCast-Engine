Đọc trước: `docs/research/_briefs/COMMON_CONTEXT.md` (bối cảnh). Vai trò của bạn: KIỂM TOÁN VIÊN ÁP DỤNG.

# Gap Audit 1 — Reports 01 (ArcReel) + 04 (AIComic/StoryGen) + 05 (seedance/Orkas) vs THỰC TẾ

Bối cảnh: nghiên cứu đã xong và ĐÚNG, nhưng thực thi đi tắt. Demo phim Miko vừa fail vì
cut nhảy thế giới (video model tự bịa lại bối cảnh ở mỗi cut components-mode). User yêu cầu:
liệt kê MỌI THỨ trong kho nghiên cứu còn bị bỏ qua/làm sai.

Nhiệm vụ — với TỪNG khuyến nghị trong `docs/research/REFS_SB_01_ArcReel.md`,
`REFS_SB_04_AIComicBuilder_StoryGen.md`, `REFS_SB_05_Seedance_Orkas.md` (đọc CẢ phụ lục
ROUND 2, cả mục 8 "chi tiết nhỏ", cả mục 10 anti-pattern):
1. Trích cơ chế/prompt-rule/kỷ luật (ngắn gọn, kèm section gốc).
2. Đối chiếu THẬT (grep/đọc code): `implementation/src/omnicast/storyboard/*.py`,
   `media/veo_pipeline.py`, `media/providers/video_gemini.py`, `pipeline/edl.py`,
   `scripts/demo_anim_short.py`.
3. Đối chiếu quy trình demo: `implementation/output/products/anim_demo/miko_lantern_ep1/DEMO_STATE.md`
   (log toàn bộ những gì đã làm/quyết định).
4. Phân loại: ÁP DỤNG ĐÚNG / MỘT PHẦN / BỎ QUA / VI PHẠM (làm ngược khuyến nghị).
5. Severity theo tác động vào mục tiêu "phim liền mạch chạy tốt như repo" (CAO/TRUNG/THẤP).

Output: `docs/research/GAP_1_core.md` — bảng đầy đủ (khuyến nghị | nguồn | trạng thái |
bằng chứng file:line | severity | việc phải làm) + cuối bài TOP-10 việc sửa ngay xếp hạng.
KHÔNG bỏ sót mục nào của report vì "có vẻ nhỏ" — chi tiết nhỏ chính là thứ user đòi.
Chỉ được ghi file output đó. Cấm sửa code, cấm sửa `_refs`.
