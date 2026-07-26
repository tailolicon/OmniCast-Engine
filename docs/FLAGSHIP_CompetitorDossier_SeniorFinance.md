> STATUS: ACTIVE — Phase A artifact của FLAGSHIP_SeniorFinance_Channel.md

# Competitor Dossier — Senior Finance/Retirement (US), 26/07/2026

**Nguồn dữ liệu (100% thật, có provenance):**
- Scan: 7 kênh × 40 video qua YouTube Data API (`scripts/flagship_research.py`)
- Cohort: `analytics/cohort.py` — 12 winners / 7 matched controls, coverage 0.583
- Transcript: 19/19 video (auto-caption, `scripts/fetch_transcripts.py`)
- Artifacts: `implementation/output/research/senior_wealth_us/` (cohort_packet.json,
  raw_videos.json, transcripts/, discovery_run_00b328d51018.json)

**Giới hạn dữ liệu (đọc trước khi tin bất kỳ kết luận nào):** 5/12 winner không có
control khớp → mọi so sánh winner-vs-control chỉ hợp lệ trên 7 cặp matched; 2 cặp
lệch title-format (selector tự ghi chú). Views công khai ≠ retention/CTR (không có
analytics nội bộ của đối thủ).

## 1. Bảy kênh đối thủ

| Handle | Trục nội dung | Ghi chú |
|---|---|---|
| @HolySchmidt | Chi tiêu hưu trí, scam, 401k | Host lớn tuổi, uy tín; 3 winner trong cohort — nhiều nhất |
| @DevinCarroll | Social Security chuyên sâu | Rule-change news là vũ khí chính; 3 winner |
| @foundryfinancial | Thuế + news + scam (Kevin Lum CFP) | 3 winner; engagement cao nhất cohort (5.6% trên video scam) |
| @RootFP | "Advisor kể chuyện nghề" | Winner x12.8 dùng advisor-persona — **mẫu KHÔNG copy được (YMYL/AI-persona ban)** |
| @AzulWells | Tâm lý nghỉ hưu, "your number" | Đăng dày, nhiều video <10 phút |
| @joekuhnlovesretirement | Hưu trí thực dụng, câu chuyện cá nhân | 11 outlier ở scan 2.5× nhưng không vào top-12 cohort |
| @rob_berger | Đầu tư/danh mục cho người sắp hưu | Dài (19'), sâu, Q&A từ viewer |

## 2. Winner cohort — cái gì thắng thật (velocity outlier ≥2×, đã settle ≥7 ngày)

**Phân bố chủ đề của 12 winner:**
- **Scam bảo vệ người cao tuổi: 2/12 nhưng chiếm #1 tuyệt đối** (x132.65 voice-impersonation
  — outlier lớn nhất toàn corpus; x13.49 với engagement 5.6% cao nhất cohort)
- **Social Security rule-change/news: 4/12** (x35.7, x20.4, x10.6 + IRS refund x17.8)
- **Con số cụ thể/ngưỡng: 3/12** ("This Number" x39.2, "5 Expenses" x21.1, "What I Tell
  Every Client At 62" x12.8)
- **Đọc-hộ-tài-liệu: 1/12** ("I Read Vanguard's 51-Page Report" x16.0)
- **Đầu tư vĩ mô: 1/12** ("Is The Market Too Expensive" x18.2)

**Title patterns (từ `shared/title_patterns.py`):** number 6/12, second_person 4/12,
question 4/12 — khớp packaging brief §10: con số cụ thể trên title/thumbnail.

## 3. Ngữ pháp hook (90 từ đầu, 12 winner)

Bốn khuôn lặp lại:
1. **Promise định lượng ngay 15s đầu:** "cut your retirement expenses by 20% over the
   next 12 months" / "calculate your number... never have to worry again"
2. **News + deadline + cơ quan quyền lực:** IRS press release + "file one form by July
   10th" / "Senior Citizens Freedom to Work Act of 2026" / FBI IC3 Report 2025
3. **Chuyện thật ngôi thứ nhất:** "I was scammed the other day" / "a viewer named Sam
   emailed me"
4. **Đảo kỳ vọng:** "the thing they regret most has almost nothing to do with a bad
   investment"

**Phát hiện quan trọng nhất cho kênh faceless YMYL:** authority đến từ NGUỒN được trích
(FBI, IRS, SSA, Vanguard), không phải từ danh xưng host. Đây chính là khuôn hợp lệ cho
kênh của ta: narrator = người giải thích tài liệu công khai, nguồn = chuyên gia. Khuôn
"I'm a retirement advisor" (RootFP x12.8) là khuôn DUY NHẤT ta bị cấm dùng.

**Nhịp đọc:** 167-206 wpm, trung vị ~180 wpm — KHÔNG chậm hoá giọng cho "người già";
các kênh thắng nói nhịp bình thường, rõ ràng, câu ngắn.

## 4. Matched pairs — bằng chứng đối chứng (chỉ 7 cặp hợp lệ)

| Winner | Control cùng kênh/cửa sổ | Tín hiệu |
|---|---|---|
| "Once Your Portfolio Hits This Number" x39.2 | "Your Spouse Dies. What Happens..." 0.45 | Promise tích cực + con số > lo âu u ám |
| "IRS Owes Millions... Until July 10th" x17.8 | "You Don't Know When Enough Is Enough" 0.46 | News hành động được + deadline > tuỳ bút chiêm nghiệm |
| "New SCAM Draining Bank Accounts" x13.5 | "He Made the 'Wrong' Financial Decision..." 0.37 | Đe doạ cụ thể hiện tại > chuyện ngụ ngôn (cặp lệch format — tin yếu hơn) |
| "Working While Collecting SS? Rule May Be Going Away" x35.7 | "Medicare Premiums Could Double" 0.53 | Cùng là news; SS earnings-limit ăn hơn Medicare (cặp lệch format) |

## 5. Hệ quả cho `senior_wealth_us`

- **Pillar xếp theo bằng chứng velocity:** (1) Scam protection, (2) Social Security
  rules/news, (3) Con số quyết định (your number / cut expenses / at 62), (4) Thuế +
  deadline theo năm hiện hành, (5) Đọc-hộ-tài-liệu (report walkthrough — hợp faceless
  nhất). Config đã phản ánh đúng các pillar này.
- **Recency là moat:** 6/12 winner phụ thuộc "năm nay/tuần này" → fact-citation ledger
  + recency gate (Phase B) không chỉ là compliance mà là lợi thế cạnh tranh.
- **Shorts native Q&A** ăn khớp khuôn #2: một câu hỏi cụ thể ("Làm việc khi nhận SS năm
  2026 — mất bao nhiêu?") trả lời trong 45s, CTA về long-form.
- **Voice:** nhịp ~180 wpm, câu ngắn, không giật gân hoá scam (control u ám thua).

## 6. Trạng thái scoring v2 (Phase A bước 3 — từ run thật `00b328d51018`)

75 topics thật một lần chạy: 23 approve / 37 review / 15 discard (v1 routing).
Corpus calibration: 75/75 usable, 75 youtube_competitor rows (vượt mốc 50).
- **Decoupling: ĐẠT** (không note vi phạm corr/eta)
- **Lane churn 30.7% > ngưỡng 25%** → theo đúng thiết kế, promote v2 cần quyết định
  con người (nó sẽ re-plan nội dung thấy được)
- **Quality evidence: 0 rows có label/outcome** → `ready_to_promote=False` fail-closed
  đúng luật. Label sẽ tích luỹ khi operator/router chọn topic thật trong production.
- Kết luận: v2 Ở LẠI SHADOW; corpus tiếp tục tích luỹ mỗi lần `scripts/run_discovery.py`
  chạy. Không có đường tắt hợp lệ.

## 7. Việc còn lại của Phase A

- [ ] A4: gói nhận diện kênh (3-5 phương án tên/handle/avatar/banner/About) → user chọn
- [ ] Backlog 23 approved topics từ discovery run cần lọc tay lần đầu (chưa có
  channel-fit filter cho senior 60-75 — vài topic có thể lệch tuổi)
- [ ] Reddit scanner cần praw credentials (fail có ghi chú, không chặn)
