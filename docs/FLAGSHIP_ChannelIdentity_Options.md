> STATUS: ACTIVE — chờ USER CHỌN (Phase A4 của FLAGSHIP_SeniorFinance_Channel.md)

# Gói nhận diện kênh flagship — 4 phương án (user quyết)

Handle đã check qua YouTube Data API 26/07/2026 (`forHandle` không trả kết quả =
nhiều khả năng trống; xác nhận cuối cùng chỉ có được lúc tạo kênh thật).
Nguyên tắc rút từ dossier: tôn trọng người xem (không "senior/golden years" trong tên
— khán giả ghét bị coi là già), authority từ nguồn trích dẫn chứ không từ persona,
không scam-vibe, typography to rõ.

## Phương án 1 — The Retirement Desk (@TheRetirementDesk) ★ ĐỀ XUẤT

- **Định vị:** "bàn biên tập" đọc-hộ và giải thích tài liệu chính thống (SSA, IRS, FBI,
  Vanguard) — khớp nhất với kênh faceless: thương hiệu là CÁI BÀN TIN TỨC, không phải
  một con người, nên không bao giờ va YMYL/AI-persona ban.
- **Khớp pillar:** news/rule-change (4/12 winner) + đọc-hộ-tài-liệu + recency moat.
- **Tagline:** "Retirement rules, explained plainly."
- **Avatar (Google Flow):** emblem phẳng tối giản — bàn làm việc + ngọn đèn đọc sách
  nhìn nghiêng, 2 màu navy `#1B3A5C` nền + vàng ấm `#E8B84B` nét, không chữ, hình khối
  to đọc được ở 98px.
- **Banner (Flow):** nền navy phẳng, chữ serif trắng lớn "The Retirement Desk" + tagline,
  góc phải mô-típ chồng tài liệu + đèn bàn, khoảng trống an toàn theo safe-area YouTube.

## Phương án 2 — Retirement Clarity (@RetirementClarity)

- **Định vị:** promise thẳng = thesis kênh ("hiểu rõ tiền hưu trí trong 15 phút").
  Tên dễ nhớ, SEO tốt, hơi generic hơn P1.
- **Tagline:** "Know exactly where you stand."
- **Avatar:** chữ lồng "RC" serif trắng trên navy, vòng tròn vàng mảnh bao quanh.
- **Banner:** navy → xanh nhạt gradient nhẹ, headline "Your retirement, made clear."

## Phương án 3 — Plain Retirement (@PlainRetirement)

- **Định vị:** chống-hype tuyên ngôn: "plain English, plain numbers." Cá tính nhất,
  phân hoá mạnh với đối thủ advisor-persona; rủi ro: "plain" có thể đọc nhầm là nhạt.
- **Tagline:** "No hype. No jargon. Just the numbers."
- **Avatar:** chữ "P" serif lớn màu kem trên nền navy phẳng tuyệt đối, không trang trí.
- **Banner:** trắng kem, chữ navy đậm cực lớn, một đường gạch vàng.

## Phương án 4 — Retire Steady (@RetireSteady)

- **Định vị:** promise cảm xúc (vững vàng) hơn là thông tin; mềm nhất, hợp nếu muốn
  thiên tâm lý nghỉ hưu kiểu @AzulWells. Ít khớp pillar news/scam nhất.
- **Tagline:** "Steady money for the years that matter."
- **Avatar:** ngọn hải đăng tối giản 2 màu navy/vàng.
- **Banner:** đường chân trời biển tĩnh, chữ serif "Retire Steady."

*(Dự phòng đã check trống: @ClearRetirement)*

## About chung (điền tên kênh đã chọn)

> {NAME} breaks down the rules that shape your retirement — Social Security, taxes,
> 401(k)s, and the scams that target retirees — in plain English, with every number
> sourced and dated. New in-depth video every few days, plus one-question Shorts.
>
> This channel is educational only and is not financial, tax, or legal advice. Rules
> change — verify current figures at ssa.gov / irs.gov or with a licensed professional.

## Việc sau khi user chọn

1. User tạo account/Brand Channel (WS7: SMS verify + OAuth — nút chặn operator từ 10/07).
2. Cập nhật `channels/senior_wealth_us.json`: `name`, handle, giữ `channel_id` nội bộ.
3. Gen avatar/banner qua Google Flow theo prompt của phương án được chọn (luật: không
   gen ảnh qua API), review độ đọc ở 98px/2560px rồi upload thủ công lúc tạo kênh.
