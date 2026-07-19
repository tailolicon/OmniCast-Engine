# Specification - UI v3 Cockpit Redesign

This specification outlines the requirements for restructuring the operator cockpit interface (v3) as defined in `SPEC_UI_v3_Redesign.md` and `DESIGN.md`.

## 1. Information Architecture & Sidebar Navigation (v3)
- Restructure the sidebar in `App.tsx` into grouped category sections:
  - **SẢN XUẤT**
    - `Bảng điều khiển` -> `/dashboard` (Dashboard.tsx)
    - `Xưởng` -> `/studio` (Studio.tsx)
    - `Thư viện` -> `/library` (Library.tsx)
  - **KÊNH**
    - `Kênh & Niche` -> `/channels` (Channels.tsx)
    - `Lịch & Tự động` -> `/scheduler` (Scheduler.tsx [NEW])
  - **PHÂN PHỐI**
    - `Duyệt & Đăng` -> `/approvals` (Approvals.tsx)
    - `Nền tảng & Đích` -> `/platforms` (PlatformsDestinations.tsx [NEW])
    - `Phân tích` -> `/analytics` (Analytics.tsx [NEW])
  - **KIẾM TIỀN**
    - `Doanh thu & Affiliate` -> `/monetization` (Monetization.tsx)
  - **HỆ THỐNG**
    - `Hệ thống` -> `/system` (System.tsx)
  - **VĂN PHÒNG** (Separator)
    - `Văn phòng` -> `/studio/office` (FullscreenOffice)

- Ensure the entire sidebar list row is wrapped inside the `Link` component to solve Đ14 (hit-area navigation issue).

## 2. New Standalone Pages
### 2.1 Standalone Scheduler (`/scheduler` - Scheduler.tsx)
- Extract the entire Autopilot/Scheduler tab from `System.tsx` and turn it into a dedicated page.
- Features: Autopilot master control card, Scheduler Lịch đăng control card, Cấu hình lịch đăng kênh table, and Kestra pipeline execution histories.

### 2.2 Standalone Platforms & Destinations (`/platforms` - PlatformsDestinations.tsx)
- Extract the Platforms and Destinations tables from `Monetization.tsx` into a dedicated page.
- Features: Cấu hình Nền tảng table (loading `/api/platforms`) and Đích đăng hoạt động table (loading `/api/destinations`).

### 2.3 Standalone Analytics (`/analytics` - Analytics.tsx)
- Extract the Video Performance table from `Monetization.tsx` into a dedicated page.
- Features: Dropdown selector for active channel, and detail table of video stats loading `/api/platforms/metrics?channel_id={channel_id}`.

## 3. Defect Resolutions
- **Đ1: Policy Scan Result Feedback (System.tsx):** Display the last scan timestamp and rule summary under the "Quét chính sách YouTube" button.
- **Đ10: Voice Profile Parsing (Channels.tsx):** Fix column parsing for voice profiles without a `:` character (use full string as fallback).
- **Đ11: Scheduler Active Status Tooltips (Channels.tsx):** Display customized tooltips and update status labels to "Lịch tắt" when disabled.
- **Đ16: Channel Edit Form-First (Channels.tsx):** Replace raw JSON editor-first with visual form inputs (Name, Niche, VoicePicker, Cadence, Checkboxes), with the JSON editor collapsable under "Nâng cao".

## 4. Constraints & Safety
- **Max Files limit:** Limit modified files to exactly 3: `App.tsx`, `System.tsx`, and `Channels.tsx`.
- Create new page files `Scheduler.tsx`, `PlatformsDestinations.tsx`, and `Analytics.tsx` cleanly.
