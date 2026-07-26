> STATUS: ACTIVE

# FLAGSHIP — Kênh Tài chính/Sức khoẻ/Hưu trí cho người cao tuổi (US)

**Nhiệm vụ (chỉ đạo operator 26/07/2026):** hoàn thiện MỘT kênh chất lượng cao nhất,
đủ sức cạnh tranh với các kênh hàng đầu trong lĩnh vực retirement finance cho khán giả
65+, kèm hệ thống Shorts lôi kéo subscriber. **Kênh này là điều kiện tiên quyết** —
hoàn thành nó rồi mới nâng cấp dự án cho các kênh khác.

Nhịp mục tiêu: **10 video long-form/tháng + 1 Short mỗi 2 ngày.**

## Tiêu chuẩn hoàn thành (áp cho TỪNG capability — không nhân nhượng)

```
Module tồn tại → có caller production → nhận dữ liệu thật → tạo artifact có
provenance → có gate fail-closed → có regression test → có end-to-end test thật
→ manual review không còn critical/major → phản ánh đúng trong IMPLEMENTATION_STATUS.md
```

Unit test + module ≠ hoàn thành. "Hoàn thành" = video thật chạy qua toàn pipeline.

## Phạm vi: 8 khối brief ánh xạ vào kênh này

| Khối | Trạng thái hiện tại | Với flagship |
|---|---|---|
| 1. Niche scoring v2 → production | Shadow mode, chưa calibrate | **CẦN** — calibrate bằng corpus senior-finance (≥50 topic từ competitor thật), bật v2 có rollback |
| 2. Competitor AV intelligence | Cohort selector xong (P0.1), AV forensics chưa bật | **CẦN** — dossier từ 5-7 kênh retirement hàng đầu; transcript + comment + schedule + AV grammar |
| 3. Renderer per production mode | Router phân loại đúng, backend thiếu | **CẦN SUBSET**: infographic/chart THẬT (finance = con số; cấm ảnh-AI-vẽ-biểu-đồ), real-evidence có license, stock footage (có sẵn). Talking-head: KHÔNG cần lúc launch (faceless) |
| 4. Channel OS | Chưa có | **CẦN TRỌN**: thesis, pillars, series, packaging 65+ (trust/typography/số cụ thể — brief §10), **Shorts→Long funnel** (yêu cầu tường minh của operator) |
| 5. Quality/benchmark gates | Script gates mạnh (horror); video gates một phần | **CẦN** — golden set từ video top của niche; YMYL bắt buộc human review gắn SHA-256 video cut |
| 6. Animation subsystem | Foundation chưa render frame | **CẮT khỏi flagship** — senior finance không cần character animation; làm sau |
| 7. Multilingual engine | Chưa có | **CẮT khỏi launch** — stage-gate của chính brief nói prove US trước; localize là bước sau khi kênh chạy |
| 8a. Script engine finance | unit_first hardened là HORROR; explainer path (claude_first) là QA thế hệ cũ | **CẦN** — profile `senior_finance_explainer_v1`: chuyển learnings phổ quát (per WS6: texture budgets, distinct voice, forbidden endings cơ chế, originality) + rubric riêng (accuracy/trust/clarity thay dread) |
| 8b. Policy/provenance | AI-disclosure đã nối; disclaimer config có | **CẦN TRỌN cho YMYL**: citation/fact ledger per claim, recency check, không AI-expert, giáo dục thuần + disclaimer, provenance package mỗi video |

## Trình tự thực thi

### Phase A — Nền nghiên cứu (tuần 1)
1. **Channel thesis + config** `senior_wealth_us` (tên làm việc): audience 60-75 US,
   promise "hiểu rõ tiền hưu trí của mình trong 15 phút", pillars: Social Security /
   401k-IRA / chống scam nhắm người cao tuổi / chi tiêu-lạm phát / tâm lý nghỉ hưu.
   Packaging 65+: typography to rõ, số cụ thể trên thumbnail, không giật gân scam-vibe.
2. **Competitor dossier THẬT**: chọn 5-7 kênh top niche; chạy cohort selector (đã có)
   trên dữ liệu thật → winner/control; transcript đầy đủ; đây vừa là playbook vừa là
   corpus calibrate scoring v2 (khối 1) — một công đôi việc.
3. **Scoring v2 calibration** trên corpus đó → bật `omnicast_scoring_mode="v2"` với
   monitoring + rollback.

### Phase B — Content engine (tuần 1-2, song song A)
4. **Profile script** `senior_finance_explainer_v1` + rubric (accuracy_trust/
   clarity_for_65plus/actionability/retention_structure/originality) + **fact-citation
   ledger**: mọi con số/luật/ngưỡng thuế phải có nguồn + ngày; gate chặn claim không
   nguồn. Số liệu 2026 phải đúng NĂM HIỆN HÀNH (recency gate).
5. **Chart/infographic renderer thật** (matplotlib/motion template — không ảnh AI):
   caller từ storyboard, số liệu lấy từ fact ledger — biểu đồ sai số = gate chặn.
6. **YMYL guardrails**: educational-only framing, disclaimer tự động, cấm AI-expert
   persona, ComplianceChecker rule set riêng cho finance claim.

### Phase C — Sản xuất + Shorts (tuần 2-3)
7. **Video e2e đầu tiên**: script → render (chart + stock + đồ hoạ) → quality gates →
   **operator review** (human gate YMYL, gắn SHA-256) → sửa → đạt.
8. **Shorts system** (2 chế độ): (a) cắt highlight 45-60s từ long-form, re-frame 9:16,
   caption to, hook lại đầu; (b) Shorts gốc trả lời 1 câu hỏi cụ thể ("Nhận Social
   Security ở 62 mất bao nhiêu?") có CTA về video dài. Lịch: 1 Short/2 ngày, mỗi Short
   trỏ về đúng 1 long-form (funnel đo được).
9. **Benchmark gate**: so video e2e với golden set (2-3 video top niche) theo từng
   chiều đo được; thiếu chiều nào ghi "chưa đo" — cấm tuyên bố %.

### Phase D — Vận hành + stage gate (tuần 3-4)
10. Nhịp production 10 long/tháng + 15 Shorts/tháng; analytics thật (retention,
    returning viewers, Shorts→Long conversion); stage gate: đạt ngưỡng → nhân bản
    learnings cho kênh kế; không đạt → chẩn đoán trước khi mở rộng.

### Nút chặn NGOÀI code (không ai làm thay được operator)
- **WS7: verify SMS tạo Brand Channel + OAuth consent** — không có thì không upload.
- Human review từng video YMYL (theo chính checklist 8 khối: bắt buộc).
- Bản tow-truck 89 lockable của kênh creepy vẫn chờ duyệt (độc lập với flagship).

## Nguyên tắc kế thừa
- Kênh creepy TẠM DỪNG gen mới (giữ nguyên trạng, không mất gì) — mọi learnings phổ
  quát (gate texture, cohort, policy, provenance) chảy vào flagship.
- Mọi capability xây cho flagship phải genre-agnostic ở phần lõi (bài học WS6) để
  kênh sau chỉ trả chi phí profile, không trả chi phí engine.
