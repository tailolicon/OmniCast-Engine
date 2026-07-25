# Gửi session WS1 (visuals-flow) — từ session WS0 (vòng lặp script)

> File này do session WS0 để lại 19/07 15:00. Đọc xong, làm theo, rồi XOÁ file này (nó untracked, không được commit).

Commit `874e471` (Flow Ingredients + character anchors + drift gate) của bạn ĐÃ ĐƯỢC GHI NHẬN — đúng phạm vi WS1, giữ nguyên.

Nhưng việc `git checkout ws/visuals-flow` **tại thư mục gốc** lúc 14:31 đã gây sự cố thật:
- Đổi code trên đĩa dưới chân batch script-gen LIVE đang chạy (batch đọc code từ đĩa mỗi lần spawn run mới).
- Commit `855ad3c` của session WS0 dính chéo vào nhánh của bạn (nội dung trùng `06f5568` trên main — merge sau vẫn sạch, không cần sửa).

**Luật 1 của charter đã được nâng cấp trên `main` (commit `4a76265`) — đọc lại `WORKSTREAMS_ParallelUpgrade.md`:**

1. Mỗi workstream làm việc trong **git worktree riêng NGOÀI repo gốc**:
   ```
   git worktree add ..\omnicast-ws-visuals-flow ws/visuals-flow
   ```
   rồi mọi edit/commit thực hiện TRONG `E:\Project\omnicast-ws-visuals-flow`.
2. **KHÔNG checkout/switch nhánh tại `E:\Project\OmniCast Engine` nữa.** Khi bạn đã chuyển sang worktree, hãy trả thư mục gốc về main: `git checkout main` (chỉ khi working tree sạch — commit hết trước).
3. Worktree không có `.env`/`.venv`/`output` (gitignored). Chạy test bằng:
   ```
   E:\Project\OmniCast Engine\implementation\.venv\Scripts\python.exe -m pytest tests/unit/ -q
   ```
   với PYTHONPATH trỏ vào `src` của worktree (editable install trỏ về repo gốc, không tự thấy code worktree):
   ```
   $env:PYTHONPATH = "E:\Project\omnicast-ws-visuals-flow\implementation\src"
   ```
4. Nhánh của bạn merge vào main chỉ khi suite xanh (hiện main mốc ≥1366; tree của bạn 1387 pass lúc 14:55 — tốt).
5. Batch script-gen đang CHẠY LIVE (20260719_1456, mall + self-storage) — tránh phóng thêm pipeline LLM song song (Luật 4).

Cảm ơn — WS0.
