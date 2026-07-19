---
version: 1.0
name: OmniCast-Cockpit-DESIGN
description: "Buồng lái vận hành 24/7 cho dây chuyền sản xuất video AI. Triết lý: near-black canvas kiểu Linear/Raycast — dense, technical, quietly luxurious. Màu CHỈ dùng cho trạng thái/hành động, không trang trí. Một accent tím-xanh duy nhất cho focus/CTA. Hairline 1px. Số liệu dùng mono. Ưu tiên mật độ thông tin > khoảng trắng (đây là công cụ ops, không phải landing page)."
---

# OmniCast Cockpit — DESIGN.md

> File này là design system BẮT BUỘC cho `frontend_v2/`. Mọi màn hình đọc file này để giữ nhất quán. Format theo chuẩn awesome-design-md (Google Stitch). Agent build: "làm màn X theo DESIGN.md" → phải khớp token + component + layout rule dưới đây.

## 0. Triết lý (đọc trước khi vẽ)
1. **Dark-first cockpit.** Người vận hành nhìn màn hình hàng giờ, 24/7 → near-black giảm mỏi mắt, làm số liệu/video nổi bật. Light mode là tùy chọn phụ (toggle), KHÔNG phải mặc định.
2. **Màu = tín hiệu, không trang trí.** Canvas + surface toàn thang xám. Xanh lá = OK/tiền, đỏ = lỗi/nguy, amber = chờ/cảnh báo, accent tím-xanh = hành động chính + focus. Cấm gradient trang trí, cấm bóng nhiều lớp, cấm emoji làm icon.
3. **Mật độ có kiểm soát.** Row 36-40px, card padding 16px, gap 12-16px. Bảng > card khi liệt kê >5 mục. Số liệu quan trọng = font mono, cỡ lớn.
4. **1 hành động chính mỗi màn.** Nút primary (accent) chỉ 1 cái nổi bật; còn lại secondary/ghost. Không để 4 nút primary cạnh nhau (lỗi Studio cũ).
5. **Không nhồi.** Panel cấu hình ít dùng → Drawer/Modal, không đặt inline chiếm chỗ. Mỗi màn có 1 nhiệm vụ rõ.

## 1. Colors

### Canvas & Surface (thang tối, Linear-style)
```
--canvas:        #0a0b0d   /* nền trang sâu nhất */
--surface-1:     #111316   /* card, panel */
--surface-2:     #16181c   /* card lồng, header bảng */
--surface-3:     #1c1f24   /* hover row, input */
--hairline:      #24272e   /* viền mặc định 1px */
--hairline-strong:#31353d  /* viền hover/active */
```
### Text (thang mực)
```
--ink:        #eceef2   /* tiêu đề, số liệu chính */
--ink-muted:  #a4abb8   /* body */
--ink-subtle: #6b7280   /* caption, label phụ */
--ink-faint:  #4a4f59   /* placeholder, disabled */
```
### Accent (1 màu — focus, CTA chính, tab active)
```
--accent:        #6366f1   /* indigo-lavender */
--accent-hover:  #7c7ff5
--accent-press:  #5457d6
--accent-soft:   rgba(99,102,241,0.12)
--accent-ring:   rgba(99,102,241,0.45)   /* focus ring */
```
### Semantic (trạng thái)
```
--green:  #22c55e   --green-soft: rgba(34,197,94,0.12)    /* OK, đã đăng, doanh thu */
--amber:  #f59e0b   --amber-soft: rgba(245,158,11,0.12)   /* chờ duyệt, cảnh báo, đang chạy */
--red:    #ef4444   --red-soft:   rgba(239,68,68,0.12)     /* lỗi, dừng, destructive */
--blue:   #3b82f6   --blue-soft:  rgba(59,130,246,0.12)    /* info, remote provider */
--purple: #a855f7   --purple-soft:rgba(168,85,247,0.12)    /* GPU/slot đặc biệt */
```
### Light mode (`.light` — tùy chọn, warm-neutral)
```
--canvas:#f7f8fa --surface-1:#ffffff --surface-2:#f2f4f7 --surface-3:#eaedf1
--hairline:#e2e6eb --hairline-strong:#cfd5dd
--ink:#0f1115 --ink-muted:#4a515c --ink-subtle:#8a919c --ink-faint:#b3b9c2
/* accent + semantic giữ nguyên hue, đậm hơn 1 bậc cho nền sáng */
```

## 2. Typography
```
--font-sans: 'Be Vietnam Pro', 'Inter', system-ui, sans-serif;  /* UI + tiếng Việt */
--font-mono: 'IBM Plex Mono', 'SF Mono', monospace;             /* số liệu, id, log, code */
```
| Vai trò | size / weight / tracking / lh |
|---|---|
| page-title | 20px / 700 / -0.02em / 1.25 |
| section | 15px / 600 / -0.01em / 1.3 |
| card-title | 14px / 600 / -0.005em / 1.35 |
| body | 13px / 400 / 0 / 1.55 |
| caption | 12px / 400 / 0 / 1.4 |
| label (uppercase eyebrow) | 11px / 600 / 0.06em / 1.3 · UPPERCASE · màu ink-subtle |
| metric (số lớn) | 24-28px / 700 / mono / 1.1 |
| mono-sm (id/log) | 11.5px / 400 / mono / 1.5 |

Quy tắc: **mọi con số liệu (views, $, %, thời lượng, id, timestamp) = font-mono.** Nhãn nhóm = eyebrow uppercase.

## 3. Shape · Elevation · Motion
```
--r-sm:6px  --r-md:8px  --r-lg:12px  --r-xl:16px  --pill:9999px
```
- **Elevation:** 1 mức duy nhất cho card nổi: `0 1px 2px rgba(0,0,0,.3), 0 2px 8px rgba(0,0,0,.24)`. Overlay/drawer/modal thêm 1 mức: `0 12px 32px rgba(0,0,0,.5)`. KHÔNG glow, KHÔNG bóng màu.
- **Border:** mặc định `1px solid var(--hairline)`; hover → `--hairline-strong`; focus input → `1px solid var(--accent)` + ring `0 0 0 3px var(--accent-ring)`.
- **Motion:** 120-160ms ease-out cho hover/expand; 200ms cho drawer slide; `prefers-reduced-motion` tôn trọng. Trạng thái `running` = pulse nhẹ (opacity 0.6↔1, 1.5s). KHÔNG animation trang trí.

## 4. Spacing & Density
```
--sp-1:4  --sp-2:8  --sp-3:12  --sp-4:16  --sp-6:24  --sp-8:32
```
- Card padding: 16px (nội dung), 12-16px header. Gap grid: 16px. Gap trong nhóm: 8-12px.
- Table row height 40px, header 36px sticky. Zebra KHÔNG dùng; phân cách bằng hairline dưới mỗi row. Hover row = surface-3.
- Sidebar width 232px (icon-only 60px < 1000px). Topbar 56px. Right rail (nếu có) 300-340px. Drawer 420-520px.

## 5. Components (spec ngắn — dựng trong `components/ui`)
- **Button:** primary (bg accent, ink trắng), secondary (bg surface-2, viền hairline), ghost (trong suốt, hover surface-2), danger (viền/red text, hover red-soft). Size sm=28px/md=34px. Icon 14px trước label. **Chỉ 1 primary/màn.**
- **Card:** bg surface-1, viền hairline, r-lg, padding 16. CardHeader = title (card-title) + sub (caption ink-subtle) + slot actions phải.
- **KPI:** label (eyebrow) + value (metric mono) + delta (caption, green/red có mũi tên). Nền surface-1, viền hairline.
- **Badge/StatusTag:** pill, 11px 600, {semantic}-soft bg + {semantic} text. Trạng thái job: idle(ink-subtle), running(amber + pulse), success(green), failed(red), waiting(amber).
- **Table:** header surface-2 sticky, uppercase eyebrow, row 40px hairline-bottom, hover surface-3. Cột số căn phải mono.
- **Drawer (phải):** dùng cho cấu hình/chi tiết ít dùng. Header sticky (title + X). Overlay scrim rgba(0,0,0,.5). ESC đóng.
- **Modal:** xác nhận hành động nguy hiểm; ConfirmModal (title/desc/ok danger). Bulk actions cũng dùng modal.
- **Skeleton:** shimmer surface-2→surface-3. **EmptyState:** icon 32px ink-faint + title + desc + CTA — mọi bảng/card rỗng PHẢI có.
- **StepFlow (mới, quan trọng):** dải 4 chip ngang "① Ý tưởng → ② Kịch bản → ③ Dựng → ④ Duyệt" với trạng thái ✓/▶(pulse)/○/✗, đường nối hairline. Đặt đầu Xưởng + Dashboard.
- **Icon:** lucide SVG 14-18px, stroke 2, currentColor. Tuyệt đối không emoji.

## 6. Layout patterns (học từ _refs)
- **3-cột "editor" (Xưởng — học VideoToolsPro/Pixelle):** rail trái hẹp (kênh + 4 nút hành động lớn + StepFlow + job status) · giữa rộng (preview video + timeline 4-track) · rail phải (live log + lịch sử). Cấu hình sản xuất → **Drawer** mở bằng nút ⚙, KHÔNG nhồi inline (lỗi cũ).
- **List + drawer detail (Thư viện, Kênh, Duyệt):** danh sách/grid bên trái, click → drawer chi tiết phải. Không mở trang mới.
- **Sub-tab trong trang (Hệ thống, Phân phối):** tab ngang dưới page-title, không tạo route con rối.
- **Dashboard:** hàng KPI (4 cột) → StepFlow job đang chạy → 2 cột (số liệu kênh thật | hoạt động+lỗi). Cấm số liệu bịa.

## 7. Cấm (rút từ 3 vòng QA)
- ❌ Nhồi mọi thứ 1 cột đến mức nút hành động bị chôn dưới scroll.
- ❌ Emoji làm icon · số float thô (8m 53.700...s) · JSON editor làm form chính · player câm không báo lỗi · chart hardcode số giả.
- ❌ >1 nút primary cạnh nhau · bảng/card rỗng không empty-state · lỗi kỹ thuật thô không dịch ra tiếng người.
- ❌ Panel cấu hình ít dùng đặt inline · thumbnail bé vô dụng thay cho nút.
