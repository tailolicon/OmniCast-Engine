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

## 7. Khung xương kịch bản — bóc tách 12 yếu tố (01/08/2026)

**Nguồn:** 19/19 transcript cohort phân tích theo framework 12 yếu tố (macro: insight/
problem/viral/emotional-arc/pacing — micro: micro-hooks/bridging/rhythm/density/
triggers/visual-cues/kicker). Chi tiết từng video + quote verbatim:
`implementation/output/research/senior_wealth_us/skeleton/group_{A,B,C}*.md`.

**Khung xương chuẩn "The Retirement Desk Skeleton v1"** (mọi script phải đo được):

1. **Cold open 5–13% tổng từ:** câu hỏi bằng đúng lời người xem + spec vật thể ngoài
   (trang SSA/report — số trang, cơ quan, năm) + MỘT mồi lớn giữ đến cuối, hẹn giờ
   công khai ("I'll get there"). Không greeting. Winner hook nhỏ, payoff trải đều.
2. **Empathy trước math, mọi lần sửa sai:** hợp thức hoá hiểu lầm trước ("it does
   make sense to wonder…"), rồi mới sửa → sửa sai đọc thành RELIEF, không phải lecture.
   Cấm bảo người xem "gạt nỗi sợ sang một bên".
3. **Hệ thống là villain, người xem không bao giờ là villain** ("designed to be
   confusing"). Flop điển hình: trách người xem ("you are obsessed with…").
4. **Payoff ladder:** một relief/reveal mỗi ~90 giây. Không có đoạn nào chỉ re-argue
   điểm đã xong (lỗi chính của script 20260730: lặp deduction-vs-penalty ~6 lần).
5. **Số liệu metered:** tối đa 2 con số thô trước khi có 1 worked example bằng lịch/
   đời thường; không bao giờ 3 fact liền không câu chuyện. Dùng chính ví dụ chính
   thức của tài liệu khi có (SSA example $800/tháng — tự nó là nguồn).
6. **Myth-bust ≥3, mỗi cái kết bằng relief** (joint income? No. Gone forever? No.
   Pension counts? No). Fear dùng đúng 1 lần, có fix ngay sau (pre-inoculation:
   "lá thư overpayment sẽ đến — đây là thủ tục chuẩn, làm X trước").
7. **"Withheld ≠ lost" honesty-first:** thừa nhận thiếu hụt hiện tại TRƯỚC → cơ chế
   recalculate sau → napkin math kèm permission to be imprecise. Không oversell.
8. **Ngôi "tôi" desk-editor:** reaction TRƯỚC/CẠNH fact ("that stopped me", "here's
   my problem with this page"), opinion có thật, KHÔNG credential/clients (ban giữ
   nguyên). Authority mượn từ tài liệu (readthrough formula: bán reaction trước info,
   quote → translate → escalate).
9. **Disagree with the document đúng 1 lần** — biến messenger thành analyst
   (Lum: "no giant red warning…"; ta: chỉ ra chỗ trang SSA dừng lại).
10. **Domino ở TRONG hệ thống evidence cho phép:** SS: check → gia đình → claiming
    age. KHÔNG sprawl sang IRMAA/Roth khi evidence pack không có (2 winner SS đều
    không đụng IRMAA). Hệ quả pipeline: **brief phải cấp domino-pack đa fact — root
    cause script silo/lặp là evidence pack 9 entry từ đúng 1 trang.**
11. **Kicker chuẩn:** recap verdict staccato → earned subscribe gắn channel promise
    → (cho phép MỘT) self-deprecating algorithm ask kiểu Lum → comment assignment
    gắn thesis, trả lời được bằng 1 câu ("over hay under $24,480 năm nay?") + "I
    read every one" → câu hỏi cuối là dòng nói cuối. Monetize/quảng bá chỉ SAU payoff.
12. **Packaging:** title/thumb có số + tổ chức + vật thể ngoài. Không point vào nội
    tâm người xem (2 flop triết lý cùng kênh chết vì packaging, không phải craft).

**Anti-checklist (reject nếu):** hứa "why" thay vì "what changed/what to do"; không
date/rule/dollar đứng được; 3+ fact trừu tượng liền; payoff là homework; "you can't
control this" không kèm lever; 0 câu hỏi comment, 0 "tôi", 0 opinion; kết bằng pitch.

**Bằng chứng A/B sạch nhất:** cùng host cùng CTA — Azul x38.1 vs x0.44, Carroll
x36.6 vs x0.54, Lum x15.97 (Vanguard PDF) vs x0.37 (Reddit post): thắng thua nằm ở
hook/arc/payoff/artifact, không nằm ở người nói hay CTA.

### 7.1 Delta từ corpus top all-time (42 video, 01/08/2026)

Nguồn: 42 transcript top-view của 7 kênh (`output/competitor_scripts/senior_wealth_us/`),
phân tích tại `skeleton/group_{D,E,F}*.md`. Bổ sung/chỉnh khung xương v1:

1. **Double-reveal thay vì single reveal** (F): video anxiety-format xếp gut-punch
   "tệ hơn bạn tưởng" ở ~30-45% rồi correction "đỡ hơn bạn sợ" ở ~55-90%.
2. **Cascade 3 tầng trên MỘT con số** (D, video 2.6M): $X → phần vượt → phần giữ →
   phần còn nhận — nhiều micro-payoff nén trong ~90s, không cần nhiều reveal rời.
3. **Concession-before-pivot** (D): đồng ý hẳn với phe đối lập trước ("at face
   value I agree 100%... but") — giàu hơn luật "disagree once".
4. **CTA không phải yếu tố thắng** (D): 3/6 video top (gồm bản 2.6M) KHÔNG có
   subscribe/like CTA — thay bằng lead-magnet bookend hoặc next-video chaining.
   Video news dùng "subscribe-as-insurance" ("I'll keep tracking this bill").
5. **Các CTA đồn thổi KHÔNG tồn tại trong 54 transcript đã kiểm** (E, F): "love
   language", "Emperor for a day", "confession booth" = 0 match. "Third video"
   của Kuhn có thật nhưng 1/6 video, đặt ở ~53s dạng khẳng định. KHÔNG encode
   các device chưa verify thành luật.
6. **Time-scarcity là taxonomy thương hiệu của Azul** ("youth of your senior
   years", "1,000 Saturdays" tagline lặp nguyên văn giữa các video) — trong kênh
   Azul, video tâm lý thắng video tactical 6-13x, NHƯNG mọi video tâm lý đều neo
   ≥1 nguồn thật (WHO/Fidelity/SSA). Không có "triết lý thuần".
7. **Padding giết format** (F): Schmidt remake video #1 của chính mình, 7.4→12.3
   phút, mất 59% view. Củng cố: không độn cho đủ 14 phút.
8. **Toy-example được miễn luật metered-numbers** (F): dataset 5 người tự bịa để
   dạy mean/median trước khi vào data thật — khán giả tự xếp loại "ví dụ".
9. **Case study compliant 2 lớp** (F, Roth-trap 1.36M): teaser ẩn danh KHÔNG phát
   triển tiếp + demo phần mềm gắn nhãn hypothetical rõ ("Phil and Claire") —
   lớp 2 dùng được cho kênh faceless, lớp 1 không.
10. **Emotional engine của Kuhn cho chủ đề làm-việc-khi-hưu** (D, 968k): confession
    → grief → gratitude → identity-revelation, gần zero số liệu — trần cảm xúc
    của ngách; kênh accuracy-first mượn 1 beat (vì sao người ta đi làm), không
    mượn cả kiến trúc.
11. **Benchmark-anxiety** ("Average Savings at 60", 2 bản >1.5M cùng đề tài) là
    evergreen lớn nhất ngách — ứng viên topic mạnh cho kênh, ground bằng Fed SCF
    (mẫu quốc gia thật; cả 2 master đều KHÔNG khai báo bias mẫu Vanguard/Fidelity
    — điểm rigor khác biệt miễn phí cho kênh ta).

Script mẫu áp delta: `variants/skeleton_v3_final.txt` (1.909 từ ≈ 10.6 phút,
0 machine flags; double-reveal + cascade 3 tầng + concession-before-pivot +
1 beat identity, evidence pack 16 entries đã merge).

## 8. Việc còn lại của Phase A

- [ ] A4: gói nhận diện kênh (3-5 phương án tên/handle/avatar/banner/About) → user chọn
- [ ] Backlog 23 approved topics từ discovery run cần lọc tay lần đầu (chưa có
  channel-fit filter cho senior 60-75 — vài topic có thể lệch tuổi)
- [ ] Reddit scanner cần praw credentials (fail có ghi chú, không chặn)
