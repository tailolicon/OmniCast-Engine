# SPEC UI v3 — Full-Control Cockpit Giao diện OmniCast

## Giao diện Gốc & Yêu cầu
Hoàn thiện giao diện OmniCast Engine phiên bản V3 để hiển thị đầy đủ thông tin hệ thống, tối ưu mật độ thông tin, loại bỏ các khoảng trắng dư thừa, và tích hợp các bảng thông số QC và platform metrics.

## Key Upgrades
1. **Studio Workflow Upgrade:**
   - Cấu hình thông số chi tiết qua SectionAccordion collapsible panels.
   - VoicePicker lọc ngôn ngữ, tìm kiếm và nghe thử giọng đọc thực tế từ server.
   - QC Manifest details (thời lượng, phân giải, dung lượng, QA status).
   - Interactive scene timeline hiển thị kịch bản chi tiết, phát thử audio phân cảnh.
   - DataTable lịch sử render, xem trực tiếp video, tải video/thumb.
2. **Duyệt & Đăng (Approvals):**
   - Multi-platform indicators (badges: YouTube, TikTok, Facebook).
   - Destinations Toggle Manager inside Approve Modal.
   - Platform conversions metrics table.
3. **Hệ thống (System config):**
   - Autopilot tab điều khiển trạng thái tự động và monitor logs.
   - Scheduler tab cấu hình giờ vàng (Prime UTC) và tuần này.
   - Kestra-lite pipeline executions trigger & history table.
   - Buffer logs lỗi hệ thống & action clear buffer.
4. **Kênh & Cấu hình (Channels):**
   - DataTable listing channels, niche, voice, cadence.
   - Full JSON Configuration Editor (`PUT /api/channels/{channel_id}`) inside drawer.
5. **Dashboard & Thư viện (Widgets & Grid):**
   - Traffic trends & Revenue growth charts using custom SVG line chart.
   - Library card QA badges, detailed QC badges, and Backfill/meta consolidator button.

## Stack & Component Verification
- Compiled using TypeScript 6.0 + Vite + React 19 + Tailwind v4.
- All layouts verified for scrollable containers (`scrollbar-thin`) and fit viewport constraints (`max-h-[82vh]`).
