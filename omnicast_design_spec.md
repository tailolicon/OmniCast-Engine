# OmniCast Engine — Design Specification for Claude Design

> **Mục đích file này:** Copy toàn bộ nội dung dưới đây → paste vào Claude Design → để nó thiết kế UI mockup cho OmniCast Engine Dashboard.

---

## 🎯 BỐI CẢNH DỰ ÁN

**OmniCast Engine** là hệ thống tự động sản xuất và phân phối video YouTube 24/7, bao gồm: nghiên cứu chủ đề → kịch bản (script) → sinh media (TTS + hình ảnh + video) → render → upload → phân tích → tối ưu.

Hệ thống sử dụng kiến trúc **Multi-Agent AI** với nhiều Agent chuyên biệt (Writer, Critic, Visual Director, Research, Compliance, Media Engineer, v.v.) hoạt động phối hợp qua pipeline nhiều giai đoạn. Mỗi Agent tiêu thụ LLM token khi hoạt động.

---

## 🎨 TRIẾT LÝ THIẾT KẾ — HAI NGUỒN THAM KHẢO

> **⚠️ QUAN TRỌNG — ĐỌC KỸ TRƯỚC KHI THIẾT KẾ:**

### Marvis = THIẾT KẾ CHỦ ĐẠO (Visual Design Language)

**Toàn bộ ngôn ngữ thiết kế, visual, layout, tông màu, phong cách card, typography, spacing đều học từ Marvis.** Cụ thể:

- **Tông màu:** Nền trắng/sáng sạch sẽ (white/light gray), KHÔNG phải dark theme. Marvis dùng nền trắng cho main area, sidebar nhạt, card có shadow nhẹ trên nền sáng.
- **Layout:** Sidebar trái gọn gàng, phân nhóm rõ ràng theo section, có thanh search phía trên, avatar/user info phía dưới — giống y Marvis.
- **Card style:** Card nền trắng, bo tròn mềm mại, shadow nhẹ `0 1px 4px rgba(0,0,0,0.08)`. Không viền cứng, cảm giác floating trên nền xám nhạt.
- **Typography:** Font sans-serif hiện đại, sạch sẽ, thoáng. Headings weight 600-700, body weight 400. Khoảng cách thoáng đãng.
- **Isometric Office View:** Trang Pipeline Office — học trực tiếp từ Marvis Office View — bàn làm việc isometric, agent sprite pixel-art, tương tác sống động.
- **Feel tổng thể:** Sạch sẽ, hiện đại, professional nhưng không lạnh lùng. Có chút playful từ pixel-art agents. Giống một ứng dụng desktop cao cấp (macOS native feel).

### AutoVio = CHỈ THAM KHẢO CHỨC NĂNG (Feature Reference)

AutoVio **chỉ** là nguồn tham khảo về **những tính năng/chức năng cần có**, KHÔNG phải phong cách thiết kế. Cụ thể lấy từ AutoVio:
- Master-detail pattern cho trang Channels (danh sách trái, chi tiết phải).
- Script viewer với scenes table, debate log, variant management.
- Pipeline step-based workflow (Phase 1 → 2 → 3 → 4).
- Settings/configuration forms cho channel.

**Tất cả những chức năng trên phải được thiết kế lại theo ngôn ngữ visual của Marvis** — nền sáng, card trắng, shadow nhẹ, font sạch — KHÔNG copy dark theme của AutoVio.

---

## 🎨 DESIGN TOKENS (Theo phong cách Marvis — Light Theme)

### Color Palette:

```css
/* Backgrounds — SÁNG, SẠCH như Marvis */
--bg:        #f5f5f7;     /* App background — xám rất nhạt */
--bg-sidebar: #ffffff;     /* Sidebar background — trắng */
--surface:   #ffffff;      /* Card background — trắng */
--surface2:  #f0f0f3;      /* Nested surfaces, input backgrounds */
--surface3:  #e8e8ec;      /* Hover states, active backgrounds */

/* Text — tối trên nền sáng */
--text:      #1a1a2e;      /* Primary text — gần đen */
--text2:     #6b6b80;      /* Secondary text — xám trung */
--text3:     #9d9db0;      /* Muted/disabled text — xám nhạt */

/* Accents — giữ nguyên cho semantic meaning */
--blue:      #3b82f6;      /* Primary actions, links, active states */
--green:     #22c55e;      /* Success, healthy, approved */
--amber:     #f59e0b;      /* Warning, in-progress, watching */
--red:       #ef4444;      /* Error, critical, HOT */
--purple:    #a855f7;      /* Special/brand accent */

/* Borders — nhẹ nhàng trên nền sáng */
--border:    rgba(0, 0, 0, 0.08);
--border-hover: rgba(0, 0, 0, 0.15);

/* Shadows — Marvis style: nhẹ, floating */
--shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.08);
--shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.12);
--shadow-glow-blue: 0 0 20px rgba(59, 130, 246, 0.15);
```

### Typography:
- Font chính: **Inter** hoặc **SF Pro Display** — sans-serif hiện đại, sạch sẽ.
- Body: 13-14px, line-height 1.6.
- Headings: weight 600-700 (không quá đậm như dark theme).
- Monospace (code/IDs): JetBrains Mono hoặc SF Mono.
- Letter-spacing: -0.01em cho headings (cảm giác compact, premium).

### Border Radius (bo tròn mềm mại — Marvis style):
- Small: 8px (buttons, tags, inputs)
- Medium: 12px (cards, panels)
- Large: 16px (modals, dialog)
- XLarge: 20px (sidebar groups, special containers)

### Spacing:
- Thoáng đãng — padding cards: 16-20px.
- Gap giữa các cards: 16px.
- Sidebar items: height 36px, padding vertical 8px.

---

## 📐 LAYOUT TỔNG THỂ (Marvis-inspired)

### Cấu trúc chính:

```
┌──────────────────────────────────────────────────────────────┐
│ [SIDEBAR]  │         [MAIN CONTENT AREA]         │ [RIGHT]  │
│  240px     │              flex-1                  │ 320px    │
│  nền trắng │        nền xám nhạt #f5f5f7         │ optional │
│            │                                      │          │
│ 🔍 Search  │  ┌──────────────────────────────┐    │ Token    │
│ ─────────  │  │  Tiêu đề trang              │    │ Stats    │
│ 📊 Tổng    │  ├──────────────────────────────┤    │          │
│  quan      │  │                              │    │ Task     │
│ 🏭 Sản     │  │  Cards trắng floating trên   │    │ Counter  │
│  xuất      │  │  nền xám nhạt                │    │          │
│ 🔍 Khám    │  │                              │    │ Activity │
│  phá       │  │  (shadow nhẹ, bo tròn 12px)  │    │ Feed     │
│ ⚙️ Hệ      │  │                              │    │          │
│  thống     │  └──────────────────────────────┘    │          │
│ ─────────  │                                      │          │
│ 👤 User    │                                      │          │
└──────────────────────────────────────────────────────────────┘
```

---

## 🧭 SIDEBAR (Marvis Design — Light, Clean)

### Thiết kế chi tiết:

**Nền:** Trắng `#ffffff`, viền phải `1px solid rgba(0,0,0,0.06)`. Không shadow nặng.

**Phần đầu — Logo:**
- Logo text "OmniCast" — font weight 700, size 18px, màu `--text`.
- Subtitle "Engine v2" bên dưới — font size 11px, màu `--text3`.
- Có thể kèm icon nhỏ bên trái (chữ "O" trong vòng tròn gradient xanh-tím).

**Thanh Search:**
- Ngay dưới logo, cách 16px.
- Input bo tròn 8px, nền `--surface2` (#f0f0f3).
- Icon 🔍 bên trái, placeholder "Tìm kiếm..." (tiếng Việt, hoặc "Search...").
- Height: 34px.

**Navigation — Chia nhóm theo section (GIỐNG MARVIS):**

Mỗi nhóm có label section nhỏ, in hoa, font 11px, weight 600, màu `--text3`, margin-bottom 4px.

```
── Tổng quan ──────────
   📊 Dashboard              (Trang chủ, KPIs)

── Sản xuất ──────────
   🏢 Văn phòng              (★ Office View isometric)  
   📺 Kênh                   (Channels — quản lý kênh)
   📄 Kịch bản               (Scripts — thư viện script)

── Khám phá ──────────
   🔍 Niche Scanner          (Kết quả scan niche)
   🏦 Niche Vault            (Kho niche + health)

── Hệ thống ──────────
   🖥️ Hạ tầng                (Infrastructure)
   💰 Chi phí                 (Budget & Cost)
```

**Mỗi nav item:**
- Height: 36px. Padding: 8px 12px.
- Icon bên trái (16x16, stroke style, màu `--text2`).
- Text label — font 13px, weight 500, màu `--text2`.
- Badge tròn bên phải (nếu có) — ví dụ:
  - Văn phòng: badge amber hiển thị số job đang chạy.
  - Niche Vault: badge đỏ hiển thị số niche HOT.
  - Hạ tầng: badge đỏ hiển thị số component offline.
- **Hover:** nền `--surface2`, transition 150ms.
- **Active/Selected:** nền `--surface2`, border-left 3px solid `--blue`, text weight 600 màu `--blue`.

**Phần dưới cùng — User Info (giống Marvis):**
- Separator line `1px solid --border`.
- Avatar vòng tròn 32px (chữ cái đầu, nền gradient nhẹ).
- Tên user (font 13px, weight 600) + role/status nhỏ bên dưới (font 11px, `--text3`).
- Icon chat/notification nhỏ bên phải.

---

## 🏢 TRANG VĂN PHÒNG / PIPELINE OFFICE (★ Trang đặc biệt — trọng tâm)

### Concept: "OmniCast Office" — Isometric AI Agent Workspace

Đây là trang signature, lấy cảm hứng TRỰC TIẾP từ **Marvis Office View** — nhưng custom cho OmniCast.

### Tham khảo visual Marvis Office (ảnh đính kèm):
- Nền chính: trắng/xám rất nhạt.
- Tiêu đề "OmniCast Office" ở phía trên trung tâm — font weight 600, size 16px.
- Khu vực office: Isometric top-down view, bàn làm việc xám nhạt, ghế đen, monitor đen.
- Agent sprites: pixel-art nhỏ, có tên + trạng thái label phía trên.
- Right panel: Card nền trắng, thống kê token + active tasks + activity log.

### Layout:

```
┌──────────────────────────────────────────────────────────────┐
│ [SIDEBAR]  │     "OmniCast Office"                │[R-PANEL]│
│            │                                       │         │
│            │  ┌─────────────────────────────┐      │ Token   │
│            │  │   ISOMETRIC OFFICE VIEW      │      │ Usage   │
│            │  │   Nền trắng/xám nhạt         │      │ ──────  │
│            │  │                              │      │ 0/10M 🔥│
│            │  │  [☕] [Desk1] [Desk2] [Desk3]│      │ $0.47   │
│            │  │       Writer  Critic  Visual │      │         │
│            │  │                              │      │ ──────  │
│            │  │  [📚] [Desk4] [Desk5] [Desk6]│      │ Đang    │
│            │  │       Research Comply  Media │      │ thực    │
│            │  │                              │      │ hiện    │
│            │  │  [🖨️] [Desk7] [Desk8] [🗑️]  │      │ ──────  │
│            │  │       Upload  Analyt.       │      │ Hoạt    │
│            │  │                              │      │ động    │
│            │  └─────────────────────────────┘      │ gần đây │
└──────────────────────────────────────────────────────────────┘
```

### Mỗi "bàn làm việc" (Agent Desk) — GIỐNG MARVIS:

**Khi Agent đang IDLE:**
- Bàn trắng/xám nhạt, isometric 3D perspective giống Marvis.
- Monitor đen (tắt). Ghế xoay đen, trống.
- Tên agent label nhỏ phía trên — font 11px, màu `--text3`, opacity 0.6.
- Toàn bộ desk khu vực opacity ~0.5, desaturated.

**Khi Agent đang ACTIVE (đang xử lý):**
- Agent sprite (pixel-art style Y HỆT Marvis — nhân vật nhỏ ~32-48px, ngồi đối mặt monitor).
- Monitor sáng — hiển thị mini icon:
  - Writer: icon ✍️ bút
  - Critic: icon ✅/❌ checkmark
  - Visual Director: icon 🎨 palette
  - Media Engineer: icon 🎬 clapperboard
  - Research: icon 🔍 kính lúp
- Label phía trên agent: Tên + trạng thái. Ví dụ:
  ```
  Writer Agent
  Đang viết 1 script
  ```
  (Giống Marvis: "Marvis — 正在执行1个项目")

- **TOKEN DRAIN ANIMATION ★:**
  - Text floating `-1 🪙` hoặc `-5` bay lên từ đầu agent.
  - CSS keyframe: translateY(0→-30px), opacity(1→0), duration 1.5s.
  - Frequency: mỗi 0.5-2s tùy token consumption rate thực tế.
  - Giống damage numbers trong RPG — nhưng phong cách nhẹ nhàng, font size nhỏ (10px), màu `--red` hoặc `--amber`.

- Shadow nhẹ glow quanh bàn: `0 0 15px rgba(59,130,246,0.12)`.

**Khi Agent HOÀN THÀNH → Handoff (chuyển giao):**
- Agent sprite đứng dậy, cầm tập tài liệu (📄 sprite nhỏ).
- **ANIMATION BÊ TÀI LIỆU:** Agent di chuyển (CSS translate) từ bàn mình → bàn agent tiếp theo.
  - Ví dụ: Writer → Critic, Critic → Visual Director, Media → Upload.
  - Duration: 2-3s. Easing: cubic-bezier(0.25, 0.46, 0.45, 0.94).
- Khi đến nơi: tài liệu "đặt xuống" → agent mới activate.
- Agent gốc quay về bàn, ngồi xuống → IDLE.

**Khi Critic REJECT:**
- Tài liệu bay theo đường cong (arc) từ bàn Critic → thùng rác 🗑️.
- Thùng rác mini shake animation 0.3s.
- Critic label đổi thành "❌ Rejected — Score 45/100".

### Deco Objects (giống Marvis — có đồ trang trí văn phòng):
- ☕ **Máy pha café** (góc trên trái) — hơi nước bay lên animation nhẹ.
- 📚 **Kệ sách** (gần Research) — đại diện Knowledge Base.
- 🖨️ **Máy in** (gần Media Engineer) — nhấp nháy khi render.
- 🗑️ **Thùng rác** (gần Critic) — nhận tài liệu bị reject.
- 📋 **Whiteboard** (gần Row 1) — vẽ mini chart.
- 🖥️ **Server rack** (góc dưới phải) — đèn LED nhấp nháy xanh/đỏ.

### Pipeline Flow Arrows:
Mũi tên mờ (opacity 0.1) nối các bàn theo thứ tự pipeline:
```
Research → Writer → Critic → Visual Director → Media Engineer → Quality Check → Upload → Analytics
```

### Right Panel (nền trắng, giống Marvis):

**Token Usage (trên cùng):**
```
┌─────────────────────────┐  Card trắng,
│ Hôm nay                 │  shadow nhẹ
│                         │
│  Token:  0 / 10,000,000 │  🔥 icon nếu > 80%
│  ████████░░░░░           │  progress bar
│                         │
│  Chi phí:   $0.47       │  / $5.00 cap
│  ██████░░░░░░░░░         │
└─────────────────────────┘
```

**Task Counter:**
```
┌─────────────────────────┐
│  🟢 1   Đang chạy       │
│  ⏳ 0   Chờ xử lý       │
│  ✅ 3   Hoàn thành       │
└─────────────────────────┘
```
(Giống Marvis: "进行中 1 / 已完成 0 / 已计 1")

**Activity Feed (timeline mới nhất trên):**
```
12:10  Writer Agent bắt đầu viết
       "5 crypto whales..." 🟢 Đang chạy
       🪙 Token: đang tính...

12:08  Critic Agent approved
       Score: 82/100 ✅
       🪙 Dùng: 1,847 tokens

12:05  Research Agent xong
       🪙 Dùng: 523 tokens         12:05 05/29
```
(Giống Marvis: timestamp bên phải, trạng thái bên trái, có nút "进行中 >" linkable)

Mục "没有更多了" = "Không có hoạt động nào thêm" ở cuối feed.

---

## 📊 TRANG DASHBOARD (Home)

Phong cách Marvis — nền xám nhạt, card trắng floating, KPIs rõ ràng.

### KPI Row (4 cards trắng ngang hàng, shadow nhẹ):

| Card | Nội dung |
|------|----------|
| **Đang chạy** | Số pipeline active. Khi > 0: số màu amber + spinner. Khi 0: "Tất cả rảnh" màu xanh lá. |
| **Script hôm nay** | Số script đạt score ≥ 70. |
| **Chi phí hôm nay** | $X.XX / $100 cap. Progress bar phía dưới: xanh (< 50%), amber (50-80%), đỏ (> 80%). |
| **Kênh** | Tổng kênh đã config. Subtitle: "X niches discovered". |

### Active Pipeline Jobs:
- Card trắng, list dọc, mỗi job:
  - Spinner + channel name (weight 600)
  - Stage hiện tại (màu `--blue`)
  - Progress bar
  - Elapsed time ⏱ + ETA (màu `--amber`)
  - Collapse Stage History (timeline timestamps)

### Recent Errors:
- Card trắng, border-left đỏ khi có lỗi.
- Expand xem Python traceback.
- "✓ Không có lỗi" màu xanh lá khi trống.

### Recent Activity:
- List view: topic, channel, phase, score badge, status tag.

---

## 📺 TRANG KÊNH (Channels — Master-Detail)

*Chức năng từ AutoVio, thiết kế theo Marvis.*

### Layout 2 cột — nền xám nhạt:

**Cột trái (300px) — Danh sách kênh:**
- Header: "Danh sách kênh" + nút "+ Kênh mới" (primary button, bo tròn 8px).
- List card dọc (nền trắng, shadow nhẹ):
  - Tên kênh (weight 600, 14px).
  - Channel ID + niche (11px, `--text3`).
  - Status dot + text.
- Card selected: border `--blue`, shadow tăng nhẹ.

**Cột phải (flex-1) — Chi tiết kênh:**
- Card trắng lớn, padding 24px, shadow nhẹ.
- Empty state: icon + "Chọn một kênh" khi chưa chọn.
- Editor mode: 4 section cards (grid 2x2, nền `--surface2`):

| Section | Nội dung |
|---------|----------|
| **🆔 Danh tính** | Channel ID, Name, Niche, Sub Niche, Market, RPM Floor |
| **🎨 Thương hiệu** | Voice Persona, Brand Voice, Tone, Hook Format |
| **🎬 Sản xuất** | Visual Style, Brand Color (picker), Font Vibe, Voice Profile, Target Duration |
| **📊 Metadata** | Competitor Handles, Trends Keywords, Subreddits |

- Header detail: Tên kênh lớn + nút actions:
  - 🗑️ Xóa (ghost, đỏ)
  - ▶ Phase 1 (ghost)
  - ✍️ Phase 2 — Script (primary blue)
  - 💾 Lưu (green)

---

## 📄 TRANG KỊCH BẢN (Scripts)

*Chức năng từ AutoVio, thiết kế theo Marvis.*

### Channel Selector:
Card trắng nhỏ — dropdown + spinner + badges (X scripts, X topics).

### Discovered Topics (card trắng, header amber):
- "🔍 Chủ đề khám phá" + subtitle.
- List topics: title + audience tag + score badge + nút "✍️ Viết script".

### Script Variants (grouped by topic):
- Mỗi topic = card trắng, header collapsible.
- Variant header: `variant_X` mono + score tag + scenes count + ▲/▼.
- Expand:
  - **Hook block:** nền xanh nhạt `rgba(59,130,246,0.06)`, border-left xanh 3px.
  - **Scenes table:** bảng sạch, nền alternating rows nhẹ.
  - **Outro block:** nền `--surface2`.
  - **Debate Log toggle:** Hiện rounds Writer ↔ Critic với score + fixes.

---

## 🔍 TRANG NICHE SCANNER

KPI cards + card list các niche đã discover. Mỗi niche card:
- Tên + market + category + score (0-100).
- Top video evidence.
- Actions: "⚡ Tạo kênh" + "📦 Lưu vào Vault".

---

## 🏦 TRANG NICHE VAULT

### KPI Row: Total Niches | 🔴 HOT | 🟡 Watching | 🔘 Stale

### HOT Panels (card trắng, border-left đỏ):
- Ranking #, tên, score/100, market, RPM.
- Health notes. Top breakout video.
- Actions: Archive, Auto-Create Channel.

### Table View: Bảng data sạch — nền trắng, header nhẹ.

---

## 🖥️ TRANG HẠ TẦNG (Infrastructure)

Component status cards (grid) — mỗi card trắng:
- Icon + tên component + status dot green/red.
- Metrics: latency, version, uptime.
- Error Log panel + Raw JSON viewer.

---

## 💰 TRANG CHI PHÍ (Budget)

KPI cards: Today's Spend | % cap | All Time Total.
Cost Breakdown table theo category.

---

## 🗺️ AGENT DESK MAP (Pipeline Office)

Sắp xếp theo luồng pipeline (trái → phải, trên → dưới):

```
Row 1 (Khám phá & Nghiên cứu):
  [☕ Café]  [Desk 1: Research]  [Desk 2: Topic Scorer]  [Desk 3: Competitor Scanner]

Row 2 (Sáng tạo nội dung — BÀN LỚN):
  [📚 Kệ sách]  [Desk 4: Writer ✍️]    [Desk 5: Critic ✅]   [Desk 6: Visual Director 🎨]

Row 3 (Sản xuất):
  [🖨️ Máy in]  [Desk 7: Media Engineer 🎬]  [Desk 8: Compliance ⚖️]  [Desk 9: Quality Check 🔍]

Row 4 (Phân phối):
  [Desk 10: Upload 📤]  [Desk 11: A/B Test 📊]  [Desk 12: Analytics 📈]  [🖥️ Server Rack]
                                                                           [🗑️ Thùng rác]
```

---

## 📝 AGENT SPRITES (giống Marvis pixel-art style)

| Trạng thái | Mô tả |
|------------|-------|
| **IDLE** | Bàn trống, monitor tắt, ghế đen trống. Label tên agent mờ. Opacity 0.5. |
| **ACTIVE** | Nhân vật pixel-art ngồi, monitor sáng với icon chức năng. Label tên + "Đang xử lý X". Token drain floating. Glow nhẹ. |
| **WALKING** | Nhân vật đứng, cầm 📄 tài liệu, di chuyển sang bàn khác. |

**Phân biệt bằng màu (giống Marvis — mỗi agent có highlight color riêng):**
- Writer: xanh dương 🔵
- Critic: đỏ/cam 🔴 (adversarial)
- Visual Director: tím 🟣
- Research: xanh lá 🟢
- Media Engineer: vàng 🟡
- Compliance: trắng ⚪
- Upload/Analytics: xám

---

## 🔔 TOPBAR & NOTIFICATIONS

### Topbar (phía trên main content, nền trắng hoặc trong suốt):
- Breadcrumb trái: "Sản xuất > Văn phòng" — font 14px, `--text2`.
- Status pills phải:
  - 🟢 "Hệ thống đang chạy" — pill xanh lá nhẹ.
  - 🔴 "TẠM DỪNG từ HH:MM" — pill đỏ, animation pulse.
  - 🟡 "Trạng thái không rõ" — pill amber.
- Bell icon 🔔 (notification count badge).

### Toast Notifications (góc phải dưới):
- Card trắng nhỏ, shadow medium, slide-up.
- Border-left: xanh lá/amber/đỏ tùy loại.
- Auto-dismiss 5s + nút X.

---

## ✨ MICRO-ANIMATIONS

1. **Token Drain:** Float up 30px + fade out 1.5s. Easing: ease-out. Font 10px, màu `--amber`.
2. **Agent Walk (Handoff):** Translate desk-to-desk, 2-3s, cubic-bezier.
3. **Trash Throw:** Arc path + shake 0.3s on thùng rác.
4. **Monitor Boot:** Opacity 0→1, 0.5s, hiện icon.
5. **Glow Pulse:** Box-shadow blue oscillate, 2s infinite.
6. **Card Hover:** TranslateY(-2px) + shadow tăng, 200ms ease.
7. **Nav Item Hover:** Background-color transition 150ms.
8. **Progress Bar:** Width transition 300ms, color gradient green→amber→red.

---

## 📱 RESPONSIVE

- **Desktop (≥ 1280px):** Sidebar + Main + Right Panel.
- **Tablet (768-1279px):** Sidebar icon-only 48px. Right panel toggle.
- **Mobile (< 768px):** Sidebar ẩn, hamburger. Office scroll ngang. Right = bottom sheet.

---

## 📐 TÓM TẮT — 6 TRANG MOCKUP CẦN THIẾT KẾ

1. **🏢 Văn phòng (Pipeline Office)** ★ QUAN TRỌNG NHẤT — Isometric office 12 bàn, agents pixel-art đang làm việc, token drain `-1🪙` floating, 1 agent đang bê tài liệu handoff, right panel token meter + activity. NỀN SÁNG như Marvis.

2. **📊 Dashboard Home** — 4 KPI cards trắng + Active Jobs + Errors + Activity feed. Nền xám nhạt, cards floating.

3. **📺 Kênh (Channels)** — Master-detail: list trái, editor phải với 4 sections. 1 channel selected.

4. **📄 Kịch bản (Scripts)** — Channel selector + Discovered Topics + Script variants expanded với scenes table + debate log.

5. **🏦 Niche Vault** — 4 KPIs + HOT panels hoặc table view.

6. **🖥️ Hạ tầng (Infrastructure)** — Component cards + Error log.

**Tone:** Marvis-inspired — sạch sẽ, sáng, hiện đại, professional. Card trắng floating trên nền xám nhạt. Shadow nhẹ. Font clean. Pixel-art agents tạo điểm nhấn playful. Cảm giác: macOS native app điều hành AI factory.
