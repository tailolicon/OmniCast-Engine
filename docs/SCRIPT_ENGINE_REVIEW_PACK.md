# OmniCast — Đặc tả đầy đủ hệ thống sinh script narrative (bản cho reviewer ngoài)

> Mục đích tài liệu: đưa cho các AI agent / reviewer độc lập đánh giá thiết kế.
> Tự đứng độc lập — không cần đọc code hay context nào khác.
> Trạng thái: 2026-07-20 (rev 2 — sau vòng external review đầu tiên), ~50 run live + 20+ vòng autopsy. Code: `implementation/src/omnicast/agents/narrative_pipeline.py` (~6.500 dòng) + `pipeline/steps.py` (wiring) + `config/narrative_quality.py` (profile). Unit suite: 1427 pass (2 integration suite cần testcontainers, không chạy trong env này).
>
> **Changelog rev 2 (phản hồi review):** (1) vá bug `_finishing_wave_allowed` lọt structured critical (reviewer tái tạo được); (2) thay monotonic tuyệt-đối bằng acceptance thứ-tự-ưu-tiên có noise band ±1 + đòi tiến bộ đúng blocker được giao (test pin hành vi cũ đã được lật có chủ đích); (3) cross-video freshness hết fail-open im lặng (vẫn fail-open có chủ đích, nhưng log to); (4) sửa các claim quá đà bên dưới.

## 0. Bài toán

Kênh YouTube horror kể chuyện "true encounters" (True Dread Files): mỗi video là một **compilation 3 truyện ngôi thứ nhất** (~750 từ/truyện, tổng 2025-2521 từ), giọng người-thường-kể-lại trên forum, threat là người thật hoặc mơ hồ — KHÔNG monster, KHÔNG siêu nhiên được xác nhận. Mục tiêu: sinh script **không phân biệt được với người viết** — đủ release lên kênh monetized mà không cần người sửa.

Thách thức cốt lõi đã đo được qua ~50 run: LLM không thất bại vì viết dở, mà vì (a) **lặp chính nó** ở mọi tầng (trope, cấu trúc, câu chữ, nhịp), (b) **trôi khỏi hợp đồng** (plan hứa một đằng văn giao một nẻo), (c) **judge chấm không đáng tin** nếu không bị ràng buộc bằng chứng.

## 1. Kiến trúc tổng: generate → verify → repair, fail-closed

```
topic → PLANNER (1 call, structured JSON)
      → deterministic preflight + salvage (voice_seed, cold_open)
      → semantic PLAN AUDIT (judge riêng) — chặn TRƯỚC khi mua prose
      → [nếu block: 1 targeted plan-repair + re-audit; hết budget → concept mới; hết attempts → abort 0 prose]
      → 3 STORY WRITERS (song song, mỗi writer chỉ thấy truyện mình)
      → deterministic recovery (lỗi gate cục bộ sửa trước khi tốn judge)
      → PER-STORY COMPLIANCE (auditor entailment: từng beat của plan phải quote được trên trang)
      → CRITIC scorecard (100 điểm, 7 chiều, forensic grounding)
      → REPAIR WAVES (tối đa 3, có điều kiện) — patch phẫu thuật / rewrite / salvage
      → content_can_lock? → FINAL EDITOR → ADVERSARIAL RELEASE CHALLENGER (model khác)
      → annotation (prosody sidecar) → production_ready
```

Nguyên tắc xuyên suốt:
- **Fail-closed**: verdict thiếu bằng chứng, contract vỡ, judge chết, độc lập không xác minh được → KHÔNG release. Không có đường "chắc là ổn".
- **Chặn sớm nhất có thể**: plan audit chạy trước writer (1 call plan quyết định 3 call writer có đáng không). Gate tất định chạy trước judge ngữ nghĩa.
- **Không bao giờ hạ cấp checker**: cost-optimization chỉ được hạ model của GENERATOR khi có checker đứng sau.
- **Mọi verdict phải quote**: lỗi major/critical phải trích nguyên văn duy nhất từ text. Gate message quote MỌI occurrence (đã đo: message không quote → 7 call sửa mù).

## 2. Hợp đồng plan (typed, machine-checkable)

Mỗi truyện trong plan khai:

**5 trục mechanism đóng (closed vocabulary), không truyện nào được trùng nhau trên BẤT KỲ trục nào:**
- `threat_mechanism` (8): blocks_path, pursues, intrudes_space, lures_or_deceives, traps_or_confines, watches_without_approach, ambush_reveal, environmental_anomaly
- `progression_mechanism` (8): silent_stillness, steady_approach, sudden_rush, repeat_sightings, escalating_contact, discovery_of_evidence, exits_close_one_by_one, impersonation_or_mimicry
- `escape_mechanism` (9), `aftermath_mechanism` (8), `threat_identity` (5: lone_stranger, known_regular, group, unseen_ambiguous, vehicle_mediated)

Lý do typed: diversity check trên prose bị lách ("gã im lặng chặn đường" vs "bóng người đột ngột đứng chắn lối" = một beat, hai câu chữ). Fingerprint concept = sha256 của multiset signature → outer retry cấm tái dùng concept đã tiêu trong run.

**Các field hợp đồng khác:**
- `escape_action`: chuỗi TRÌNH DIỄN 2-3 sự kiện bấm-giờ-được, đúng thứ tự; trạng thái liên tục ("giữ bình tĩnh") bị cấm nằm trong chuỗi; escape và ending KHÔNG được chia sẻ cùng một khoảnh khắc (một span văn không thể phục vụ 2 beat).
- `continuity_ledger` (5 entry, prefix cố định, ≤24 từ): toạ độ bất biến — địa điểm, thời điểm, thứ tự, TRẠNG THÁI ĐẠO CỤ, AI-ĐI-VỚI-AI. Mọi prop mà escape/ending phụ thuộc PHẢI được trồng ở đây hoặc setup.
- `voice_seed`: planner viết mẫu 2-3 câu ĐÚNG giọng narrator; writer CONTINUE giọng đó (không phải adopt tính từ). Seed nhiễm (số liệu/banned phrase) bị salvage field-level (blank) thay vì giết cả plan.
- `distinguishing_turn` (4-25 từ, ba truyện ba turn khác nhau): nêu đích danh điều làm premise này KHÔNG phải bản stock. Writer nhận nó như lời hứa; audit kiểm lời hứa có được xây thật trong các field khoá không. (Bằng chứng hiệu quả: **before/after quan sát, n=2** — originality 6.21 trung bình 14 run trước → 8 và 7 ở 2 run sau; CHƯA phải A/B có kiểm soát — planner/premise/lượt chấm đều đổi cùng lúc.)
- `evidence_allowance` (none/witness/physical...): "none" = KHÔNG GÌ xác nhận sau đó — kể cả lời hứa điều tra ("someone would look into it" = corroboration-by-authority). Mỗi compilation ≥1 truyện evidence-free.
- `safety_obligation` (authorities/trusted_adult/concrete_reason/not_applicable): human threat lặp qua nhiều đêm cấm not_applicable; đường khai nào trang phải GIAO đường đó, check ở aftermath (3 đoạn cuối); người-có-tư-cách được định nghĩa regex (parent/boss/shift lead/spouse-có-possessive...).
- Narrator mặc định NGƯỜI LỚN; minor chỉ khi tuổi LÀ premise kèm trọn reporting chain.

**Plan audit (semantic judge):** tri-state valid/blocked/infra_failed. Mọi major/critical chặn. Objection phải quote đúng nguyên văn plan + khai `knowledge_scope` (universal|site_specific — site_specific tự hạ xuống advisory, tránh overclaim giết concept). Audit cũng là probe sống của judge path. Đã chứng minh giết đúng: geometry bất khả thi, egress vi phạm fire-code, hành vi người không hợp lý (không báo ai sau 3 đêm bị theo), trope tự nhận diện.

**Chống trope ở tầng plan:** slot still-watcher duy nhất phải TỰ CHỨNG MINH góc mới (một mệnh đề nêu được điều khác bản stock, "chuyển địa điểm không phải góc mới"); AMBIGUOUS-THREAT STOCK LIST liệt kê đích danh các beat đã bị audit giết ≥2 lần (cửa đóng dây chuyền sau lưng, đèn tắt đón đầu, thang máy tự đi tầng cấm, tiếng gõ ngừng khi nhìn, môi trường "diễn lại" narrator, giả hỏng xe, điện thoại chết vẫn reo); NO-RECORD aftermath (tra cứu ra số không) tối đa 1 truyện/compilation.

## 3. Gate tất định (chạy trước và sau mọi judge)

**Cấm tuyệt đối (0 lần):** self-reassurance ("I told myself" mọi biến thể kể cả phủ định), CTA/meta, soma cliché stock (heart pounded in my chest...), forbidden endings ("I never went back to find out..." — anchor first-person, không bắt oan "They never found him").

**Rationed (≤1/compilation, truyện thứ 2 bị nêu tên):** out of habit, body-acted-before-mind (cả họ paraphrase), "I like the ___" preference declaration, "I don't spook/scare" composure claim, no-record device wordings, pulse in my ears, un-hurried...

**Per-story caps:** "the way you/he/she/something..." ≤1; one-word beat ≤2; negation-reversal ≤1; negation-triad ≤1 và cấm share cross-story (message quote cả 2 nơi).

**Cross-story structure:** coda family ("I still.../Now I always.../Ever since...") ≤1 compilation — slot được CHIA TĨNH lúc viết: chỉ story_1 được dùng, truyện sau bị dặn không mở câu cuối bằng "I still" dưới mọi nghĩa; still-watcher pose chỉ ở đúng truyện lone_stranger; `shared_phrase`: mọi chuỗi 5 từ hiếm (lọc stopword + từ vựng domain của plan) xuất hiện y hệt ở 2 narrator → fail truyện sau, quote trọn run.

**Độ dài:** per-story 90-112% target, tổng 2025-2521 từ. Lỗi độ dài route THẲNG tới rewrite (patch phẫu thuật không thể thêm 115 từ).

Story prompt khai báo TRƯỚC toàn bộ texture budget (đo được: recovery 3 lần không sửa nổi tic writer không biết trước), luật "mỗi beat một câu riêng" (beat gộp = auditor không quote được 2 span không chồng nhau = zero-score), luật COORDINATES (landmark/giờ/thứ tự/trạng thái prop là toạ độ, không phải gợi ý — trôi 1 landmark vỡ 3 beat).

## 4. Tầng judge (3 lớp độc lập về vai)

**Per-story compliance (entailment auditor, temperature 0):** từng beat khoá (setup/threat_confirmation/decision/completed_escape/completed_ending) phải có quote NGUYÊN VĂN, ĐÚNG THỨ TỰ, KHÔNG CHỒNG NHAU từ prose; plan_facts preserved/contradicted kèm quote. Contract fail 2 lần → nếu lỗi thuộc lớp "beat không quote tách được" → 1 bounded rewrite + re-audit; lớp khác → zero-score fail-closed.

**Critic scorecard (100đ):** continuity_believability/25, distinct_authentic_voices/20, dread_escalation/20, plausible_response/10, structural_variety/10, originality/10, ending_discipline/5. Sàn release: **tổng ≥84** VÀ **mỗi chiều ≥65% max**. Forensic contract: major/critical phải quote duy nhất; chiều groundable dưới sàn mà 0 major → 1 lần grounding re-score, vẫn không có căn cứ → fail-closed; **originality được miễn contract này** (phán quyết holistic "quen thuộc" không thể quote — nhưng SÀN của nó vẫn chặn release; chỉ là chấm 6 trung thực không còn tắt máy repair). Severity calibration: critic tự ghi "physically impossible" mà dán nhãn minor → tự động promote major. Compliance findings được merge vào scorecard làm major (dedupe theo issue_id).

**Final editor + Release challenger:** chỉ chạy khi content_can_lock (điểm + sàn + 0 major tồn đọng + contracts valid + compliance approved). Challenger là Opus (khác model judge Sonnet), prompt "giả định approval trước mặt mày là SAI", 7 trục typed (physical/timeline/semantic-repetition/topic/safety/plan-fidelity/forbidden-ending); veto phải quote duy nhất; không quote/không với tới/contract vỡ = fail-closed; độc lập đo theo (provider, model) THỰC SỰ chạy, ghi vào artifact, không tin nhãn.

## 5. Máy sửa (mua cơ hội cho ứng viên tốt, không nhân nhượng chuẩn)

- **Wave 1**: mọi truyện có gate failure hoặc major. Mỗi truyện: writer đề xuất CẶP patch ứng viên (JSON find/replace nguyên văn, atomic, 1 contract retry); ứng viên phải GIẢM số lỗi tất định của truyện (không chỉ "không thêm mới") — không giảm → rewrite fallback; blind selector (judge, thứ tự shuffle theo hash, có baseline) chọn với confidence + 6 cờ chất lượng, thiếu tin cậy → giữ baseline.
- **Chấp nhận wave**: re-audit compliance các truyện đổi + re-score; **monotonic** (không chiều nào tụt, blocker không tăng, gate không tăng, VÀ có tiến bộ). Wave bị bác → **salvage xếp chồng**: đắp lại từng patch một (blocker nặng trước, tối đa 2 vòng), mỗi vòng re-judge so với trạng thái đã-nhận gần nhất; vòng trượt bị bỏ qua, không giết cả rescue.
- **Wave 2**: chỉ cho compilation đã mạnh (gate pass, tổng ≥ sàn, 0 critical, ≤3 truyện lỗi).
- **Wave 3 (finishing)**: chỉ cho ứng viên ĐỨNG TRƯỚC CỬA release — tổng ≥ sàn−2, gate pass, 0 critical, ≤2 truyện lỗi, MỌI blocker còn lại có quote. Lý do: regen từ đầu tốn ~6 lần một wave; ứng viên đã chứng minh giá trị thì mua thêm cơ hội sửa.
- **Near-miss minor wave**: gate sạch + 0 major + tổng cách sàn ≤3 → minor có quote được đúng 1 wave (trước đây minor không bao giờ được sửa → bản 83 chết oan thiếu 1 điểm).
- **Outer retry**: 2 attempt/run; attempt sau bị cấm concept đã tiêu; attempt abort vẫn ghi đủ bill + lý do (`attempt_summaries`, `plan_rejections` typed 1-1, `narrative_failure_audit.json` cho run 0-prose).

## 6. Model routing & vận hành

- **Roles (ghim trong batch runner, không phụ thuộc env của shell phóng):** planner + writer = claude-sonnet-5/high (A/B: −36% cost, điểm cao nhất); mọi judge = sonnet/medium; plan-repair + patch = sonnet/medium (generator có checker sau lưng); challenger + audit-escalation = opus. CLI gọi với `--tools ""` + `--max-turns 1` (đã đo: không tắt tool → model tiêu turn vào tool call → error_max_turns).
- **1 tài khoản = 1 health domain**: không fallback nội-account (đổi model không phải fallback); account chết → abort fail-closed trước writer. Không chạy 2 pipeline song song (đo được: throttle giết cả hai).
- **Batch runner detached**: quota-aware (bắt "session limit · resets X" → ngủ tới reset + 5' → retry đúng topic ≤3 lần; verdict 0 điểm + limit marker = quota-poisoned → retry; verdict có điểm thật → không bao giờ re-run), sống qua đêm, cron 3h làm lưới an toàn với giao thức stand-down (main có commit <90' → không tự lái).
- **Topic lifecycle**: nghỉ hưu khi chết plan-audit 2 lần liên tiếp HOẶC originality dưới sàn khi mọi thứ khác sạch (hệ tự đo premise-space cạn); chọn topic mới theo profile: di động/nhiều-điểm-dừng/nhiều-người-hợp-lý > địa-điểm-tĩnh-một-người (mô hình premise-space = số triple threat×progression×identity mà địa điểm đỡ được). Cross-video: fingerprint archetype (threat_identity/escape) 20 video gần nhất feed vào plan prompt.

## 7. Kết quả đo được

- Điểm theo thời gian: 74 → 77 → 80 → 83 → 84/85 (hiện dao động 79-85; sàn 84).
- Released tự động: diner 89/100 (production_ready, lineup-test 3 giọng pass) — **lưu ý trung thực: released dưới policy CŨ; replay bằng gate hiện tại fail 3 hard failure (body-before-mind, the-way ×2, one-word beat ×3), tức CHƯA có artifact nào production_ready dưới policy hiện hành** — policy đã siết nhanh hơn tốc độ release. Pre-campaign: newspapers 93 (audit tay phát hiện là false-positive của hệ chấm CŨ — sự cố này đẻ ra toàn bộ tầng release-integrity).
- Ứng viên trong tầm: mall 84 (content_valid — nghỉ hưu topic ở đỉnh), hotel 85 (chết vì bug contract đã vá), courier 84/originality 8 (2 major writer-drift).
- Chi phí notional/run: $2.5-4.5 (28-55 call); trước cost-routing $6.78.
- Mỗi lớp lỗi live → 1 luật vĩnh viễn + test: suite 1363 → 1425 trong 48h; 5 autopsy gần nhất không còn lớp hệ mới.

## 8. Điểm yếu đã biết (mời reviewer mổ)

1. **Originality floor lượng tử hoá**: sàn 6.5 trên thang nguyên = thực tế đòi 7/10; chiều 5 điểm (ending) sàn 3.25 = đòi 4/5 = 80%. Ratio 0.65 cắn không đều theo scale.
2. **Độc lập judge chỉ ở mức model, không provider**: claude_only mode — challenger Opus vs judge Sonnet cùng account Anthropic. Điểm mù chung của họ model là rủi ro chưa đo được (đã từng: 2 judge cùng provider cho 93 điểm bản ~60).
3. **Freshness xuyên-video mới nhớ 2/5 trục** (threat_identity + escape); spent_concepts reset mỗi run — topic cạn dần hệ chỉ phát hiện GIÁN TIẾP qua originality/audit.
4. **Không có candidate resume**: bản trượt lưu đầy đủ (văn + lỗi kèm quote) nhưng không cơ chế offline nhặt lại sửa tiếp — mỗi run sinh mới từ đầu (finishing wave mới chỉ vá trong-run).
5. **Beat partial là killer ngẫu nhiên số 1 còn lại**: writer giao thiếu mệnh đề 2 của beat đa mệnh đề; repair sửa được ~50%.
6. **Auditor đôi khi tự mâu thuẫn giữa 2 attempt** (cửa cuốn kho: lần 1 "không có mô-tơ", lần 2 "có mô-tơ + cảm biến UL 325") — cả 2 lần đều giết premise yếu thật, nhưng tính nhất quán kiến thức chưa được kiểm.
7. **Gate regex tiếng Anh cứng**: mở rộng kênh/ngôn ngữ khác cần viết lại denylist (cơ chế giữ, nội dung theo genre).
8. **Chi phí ~11 call backbone + 15-40 call sửa/run** — throughput bị trói vào quota subscription một account.

## 9. Câu hỏi cụ thể cho reviewer

1. Bộ ration/texture budget có nguy cơ ép văn về "median an toàn" không? Bằng chứng hiện tại (voices 14-17 dao động, originality tăng khi thêm luật) đã đủ bác lo ngại này chưa?
2. Monotonic acceptance (không chiều nào được tụt) có quá chặt không — patch tốt có thể đánh đổi −1 chiều này +3 chiều kia?
3. Finishing wave (wave 3) có mở đường degenerate loop nào mà guard hiện tại chưa chặn?
4. Sàn originality per-dimension có nên thay bằng cơ chế khác (vd trọng số vào tổng) khi nó là chiều chủ quan nhất?
5. Thiết kế "distinguishing_turn" — bắt planner tự khai điểm mới rồi audit kiểm — có lỗ hổng self-fulfilling nào (planner học cách viết turn nghe-có-vẻ-mới)?
6. Với mục tiêu scale đa kênh: những gì nên tách thành genre-module ngay bây giờ thay vì để hard-code thêm?
