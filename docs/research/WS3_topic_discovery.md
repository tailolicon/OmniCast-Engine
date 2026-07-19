# WS3 — Topic/Discovery pipeline: Báo cáo hiện trạng & thiết kế topic generator cho kênh creepy

> Sinh bởi agent nghiên cứu WS3, 2026-07-19. Phạm vi: WORKSTREAMS_ParallelUpgrade.md §WS3. Read-only.

## 1. BẢN ĐỒ HIỆN TRẠNG

### 1.1. Discovery pipeline hiện có — xây cho kênh EXPLAINER, không phải narrative

Toàn bộ `src/omnicast/discovery/` là code THẬT, chạy được, nhưng nhắm 100% vào niche thông tin (finance/health/psychology-khoa-học/tech/history):

| Thành phần | File:line | Trạng thái | Ghi chú |
|---|---|---|---|
| `DiscoveryOrchestrator` | `discovery/orchestrator.py:65`, `.for_channel()` `:91`, `.run()` `:116` | REAL | Chạy scanners song song → score → brief |
| Scanner selection | `orchestrator.py:103-113` | REAL | News/Trends/YouTube/Reddit dựng từ `channel.to_discovery_config()` |
| `SeedQueryGenerator` | `seed_generator.py:144` | REAL | 6 kỹ thuật: Reddit pain-point hijack (`:528`), YouTube trending (`:226`), category trending (`:601`), broad-to-specific (`:353`), Google Trends breakout (`:464`), T5 category sweep (`:661`). Tất cả nối YouTube API + Reddit public JSON + pytrends + DeepSeek |
| `NicheScanner` | `niche_scanner.py:282` | REAL | Outlier/supernova signal, `SEED_QUERIES` `:49` toàn finance/health |
| `TopicScorer` | `scorer.py:35` | REAL | 4 chiều: `trend_momentum`/`gap_score`/`rpm_potential`/`novelty` — đều là tín hiệu CẦU thông tin (outlier_ratio, growth_pct, Reddit score) |
| `RedditScanner` | `reddit_scanner.py:22` + `orchestrator.py:112` | **NỬA CHẾT** | `_scan()` `:51` raise nếu không có PRAW client; `for_channel` dựng `RedditScanner(config=config)` KHÔNG client → source fail âm thầm |
| `PodcastScanner`/`NewsScanner`/`TrendsScanner` | tương ứng | REAL nhưng phụ | Cần API key/RSS; kênh creepy `rss_feeds: []` |

Điểm mấu chốt: `Niche` enum (`models/enums.py:43-50`) KHÔNG có `horror`/`narrative` — kênh creepy phải mượn `psychology`. `TopicScorer` không có chiều nào đo "địa điểm liminal nào còn threat-shape chưa cạn". Nên discovery, nếu chạy, chỉ đẻ ra tiêu đề kiểu explainer.

### 1.2. Có đường nào nối discovery → narrative batch không? — KHÔNG

Có hai đường topic tách rời:

- **Đường auto (explainer):** `content_flow.py:144 run_phase1()` → `DiscoveryOrchestrator` → `ChannelArchitectAgent` → best topic. Fallback đẻ ra tiêu đề `"5 {niche} Mistakes..."` (`content_flow.py:197,201,203`). KHÔNG dùng cho kênh creepy.
- **Đường thật của kênh creepy:** `scripts/run_phase2_unit_first.py:28-33` — topic mặc định HARD-CODE / truyền tay qua `--topic`, **bỏ qua hoàn toàn phase 1 discovery**, gọi thẳng `_step_script(...)` (`:47`). `scripts/run_seq_batch.py:55 main(topics)` nhận list topic từ `sys.argv`, mỗi topic một subprocess. → **Topic 100% gõ tay.**

Trong `pipeline/steps.py` (WS0, chỉ đọc):
- `:465` `topic_has_script_product()` = guard chặn chạy lại topic đã có product.
- `:491-507` `recent_avoid()` + `recent_archetypes()` được feed FORWARD vào prompt planner dạng gợi ý mềm `_avoid_kp` ("vary from these").
- `:844-851` sau khi gen, ghi lại archetype `threat_identity/escape_mechanism` qua `check_and_record()`.

### 1.3. Cross-video fingerprint — chỉ 2/5 trục, lưu ngoài vault

`agents/cross_video.py`: rolling window 20 script/kênh, lưu ở **`output/_script_fingerprints.json`** (`:17`, một JSON file — technically lệch luật "vault là SSOT" nhưng là pattern có sẵn). `recent_archetypes()` (`:121`) chỉ trả chuỗi `threat_identity/escape_mechanism` = **2 trong 5 trục** premise-space.

### 1.4. Premise-space "primitives" ĐÃ TỒN TẠI (trong WS0) nhưng chưa được đo across-video

Phát hiện quan trọng nhất. `agents/narrative_pipeline.py` đã có sẵn **5 closed-vocabulary axes** — chính là hệ toạ độ của premise-space:

- `ThreatMechanism` (8): `blocks_path, pursues, intrudes_space, lures_or_deceives, traps_or_confines, watches_without_approach, ambush_reveal, environmental_anomaly` (`:184`)
- `ProgressionMechanism` (8): `silent_stillness, steady_approach, sudden_rush, repeat_sightings, escalating_contact, discovery_of_evidence, exits_close_one_by_one, impersonation_or_mimicry` (`:189`)
- `EscapeMechanism` (9) (`:194`), `AftermathMechanism` (8) (`:207`), `ThreatIdentity` (5): `lone_stranger, known_regular, group, unseen_ambiguous, vehicle_mediated` (`:203`)

Và các hàm: `story_mechanism_signature()` `:758` = tuple 5 trục/story; `plan_concept_fingerprint()` `:763` = sha256 của multiset signatures; `plans_are_materially_equivalent()` `:789`, `_plan_freshness_errors()` `:3765`.

**GAP quyết định:** `spent_concepts` khởi tạo RỖNG mỗi run (`narrative_pipeline.py:4569`) — chỉ tích luỹ trong vòng retry của MỘT run, KHÔNG nạp từ các video trước của cùng topic. `steps.py` không bao giờ truyền `forbidden_plan_fingerprints` từ vault. → **Freshness gate là per-run, KHÔNG phải per-topic-across-videos.** Đây chính là lý do premise-space cạn dần mà hệ thống không "biết".

### 1.5. Vault — bảng gì lưu lịch sử topic/product

`vault/db.py`:
- `topics` table (`:110`): `topic_id, channel_id, title, score, status(queued/used), ...`. `make_topic_id()` `:725`, `upsert_topic()` `:789`, `get_next_topic()` `:827`, `mark_topic_used_by_title()` `:753`, `topic_has_script_product()` `:737`.
- `scripts` table (`:66`) — script đã gen.
- `niches` + `health_logs` (`:35,:49`) — health/decay cho niche EXPLAINER (`list_niches` `:397`), **không** dùng cho topic narrative.
- **Không có bảng nào lưu mechanism signature/premise-space consumption theo topic.** `meta.json` của product (`storage/products.py:223-305`) cũng KHÔNG lưu typed axes. Toàn bộ dấu vết cross-video của axes = 2 trục trong JSON của `cross_video.py`.

Lịch sử "chết" hiện chỉ nằm ở `output/_seq_batch/<stamp>/summary.txt` (dòng REJECTED/ACCEPTED, `run_seq_batch.py:83-88`) — không cấu trúc.

## 2. LỖ HỔNG cho kênh narrative

**Vì sao topic phải đút tay:**
1. Discovery là **demand/trend-driven** — hợp niche thông tin, vô nghĩa với horror evergreen. Topic của kênh creepy KHÔNG phải "chủ đề đang hot" mà là **một FRAME địa điểm/tình huống** ("3 True Encounters [đêm-một-mình ở X]"). Không component nào sinh ra frame địa điểm.
2. `TopicScorer` không có trục "premise-space còn lại". `ChannelArchitect` đẻ tiêu đề explainer, không đẻ location frame.
3. Không có bộ đo độ cạn → laundromat/ranger phải nghỉ hưu THỦ CÔNG bằng mắt người vận hành.

**Thiếu gì để tự đề xuất "3 True Encounters ..." mới:** (a) bộ sinh candidate location/situation frame; (b) bộ ước lượng premise-space cho một frame TRƯỚC khi đốt quota, dùng chính 5 trục typed mà release-gate đã dùng; (c) bộ theo dõi cạn/nghỉ hưu persist theo topic-family; (d) nối vào batch đúng format `--topic`.

## 3. THIẾT KẾ ĐỀ XUẤT — "topic generator cho kênh creepy" (xếp hạng)

Nguyên tắc: **KHÔNG đụng WS0**. Generator là module/script MỚI, chỉ ĐỌC vault + `_script_fingerprints.json` + `_seq_batch` logs, GHI candidate topic qua interface sẵn có. Import vocab enum từ `narrative_pipeline` (không sửa).

### 3a. Đo "premise-space còn lại" TRƯỚC khi đốt quota (ưu tiên #1)

Premise-space của một location = tập **plausible triples** `(threat_identity × threat_mechanism × progression_mechanism)` mà địa điểm đỡ được về vật lý/xã hội (escape/aftermath ít bị location ràng buộc). Không gian lý thuyết 5×8×8 = 320, địa điểm thật chỉ đỡ một nhúm.

`estimate_premise_space(frame)`:
1. Inject nguyên văn 3 closed vocab + frame + tóm tắt rubric plan-audit vào LLM **offline-batch** (không cần reasoning).
2. LLM liệt kê các triple PLAUSIBLE cho "một người thường, một mình, ban đêm, tại <location>" đủ khác nhau để qua plan-audit → `N_plausible`.
3. Trừ signature đã tiêu (`spent`) từ lịch sử topic-family → `N_remaining`.
4. **Retire nếu** `N_remaining < 3` (một compilation cần 3 story tươi) HOẶC ≥2 plan-audit death liên tiếp (không do quota).

Khớp thực tế: laundromat (static, enclosed, solo) chỉ đỡ ~10-12 triple non-redundant; sau 6 run × 3 story ≈ 18 story là lặp sâu → audit giết. County-road / apartment-nhiều-căn là mobile/multi-space → mở khoá `pursues, vehicle_mediated, group, lures` → premise-space lớn hơn nhiều.

### 3b. Tránh vùng đã cạn — location-profile

Chấm mỗi candidate theo profile: `spatial_class` (static_enclosed | static_open | transitional | mobile | multi_unit), `cast_plausibility` (solo_only | solo_plus_incidental | plausibly_multiple), `threat_channel_count` (0-8), `exit_topology` (single | few | many). Laundromat + ranger-station đều = `static_enclosed + solo_only + threat_channel_count thấp`. **Luật: hard-avoid candidate trùng retired-profile; rank còn lại theo `threat_channel_count × cast_plausibility`.**

### 3c. Nguồn ý tưởng — LLM offline-batch, KHÔNG web trend

- **Chính:** LLM offline-batch, seed bằng `channel.audience.content_triggers` (`true_dread_files_us.json:39-43`) + brand_voice + rubric location-profile + danh sách retired. Evergreen → không cần trend.
- **Enrichment tuỳ chọn (S):** reuse pattern Reddit public JSON không cần key (`seed_generator.py:528`) trỏ vào subreddits của kênh (`true_dread_files_us.json:57-61`) — ưu tiên r/LetsNotMeet (thật) hơn r/nosleep (hư cấu) — mót location frame thật làm grounding.
- **Web/trend: BÁC BỎ** — trend chỉ ra setting đang ĐÔNG (đối thủ nhiều), ta cần premise-space CHƯA CẠN.

### 3d. Nối vào batch runner

- Script mới `scripts/gen_creepy_topics.py` (ĐỌC vault + fingerprints + logs; GHI candidate).
- **Format A (nhanh):** in ranked topic thành argv dán vào `run_seq_batch.py` (guard ≥3 từ khớp `run_phase2_unit_first.py:37`).
- **Format B (ưu tiên, đúng SSOT):** `upsert_topic()` vào bảng `topics` sẵn có, `status=queued`, `score=premise_space_estimate`; pull qua `get_next_topic()`. **Không cần đổi schema.**
- **Ledger premise-space (bảng mới) — QUA ĐIỀU PHỐI:** persist full 5-trục signature/story + đếm plan-audit death. Lựa chọn: (1) bảng vault mới `topic_premise_ledger`; (2) mở rộng `cross_video.record()` ghi đủ 5 trục (điểm ghi `steps.py:844-851` thuộc WS0 → phối hợp). **Interim không đụng WS0:** parse `_seq_batch/*/summary.txt` + approximate `spent` bằng 2-trục `recent_archetypes()`.

## 4. Bảng đề xuất: file · effort · rủi ro · đo thành công

| # | Đề xuất | File đụng (MỚI trừ khi ghi rõ) | Effort | Rủi ro | Đo thành công |
|---|---|---|---|---|---|
| P1 | `estimate_premise_space()` (3a) | `scripts/gen_creepy_topics.py` hoặc `src/omnicast/discovery/creepy_topics.py` (mới) | **M** | LLM ước lượng lệch; backtest để hiệu chỉnh | Backtest: laundromat/ranger < 3 (đã chết); mall/county-road ≥ 3. Tỉ lệ plan-qua-audit attempt-1 của topic P1 > baseline gõ tay |
| P2 | Location-profile + hard-avoid retired (3b) | cùng module P1 | **S** | Profile thô bỏ sót thuộc tính | Không đề xuất lại profile `static_enclosed+solo_only`; số run tới release giảm |
| P3 | LLM offline-batch generator + rank (3c) | cùng module P1 | **M** | Setting AI-generic, trùng released | Overlap archetype với 20 video gần nhất = 0; bị `topic_has_script_product` chặn = 0 |
| P4 | Reddit LetsNotMeet grounding | cùng module (reuse `_reddit_pain_points` pattern) | **S** | Lẫn fiction | Đánh giá tay % setting "cảm giác thật"; không tăng compliance flag |
| P5 | Wiring format B — `upsert_topic(status=queued)` | dùng `vault/db.py` API sẵn có (KHÔNG sửa) | **S** | Trùng topic queued cũ | `get_next_topic()` trả đúng ranked; qua guard ≥3 từ 100% |
| P6 | Auto-retire — parse `_seq_batch/summary.txt` | cùng module (chỉ đọc log) | **S** | Nhầm quota-death | Reuse `_LIMIT_RE` (`run_seq_batch.py:32`); retire đúng laundromat/ranger, KHÔNG retire mall |
| P7 | Ledger premise-space đầy đủ 5 trục | bảng vault mới HOẶC mở rộng `cross_video.record` → **QUA ĐIỀU PHỐI** | **M-L** | Va chạm cách ly WS0 | Non-repeat đo trên đủ 5 trục thay vì 2 |

Metrics nghiệm thu: tỉ lệ plan qua audit attempt 1 ↑; số run tới release/topic ↓; archetype overlap 20 video gần nhất = 0; retirement precision (bắn đúng laundromat/ranger, không bắn mall).

## 5. QUICK WINS (1 buổi)

1. **Death-log structuring (P6 lõi):** `scripts/creepy_topic_status.py` chỉ ĐỌC summary.txt + fingerprints, gộp theo topic-family, loại quota-death bằng `_LIMIT_RE`, in bảng: topic-family · số run · death liên tiếp · archetype đã tiêu · cờ RETIRE. Nghỉ hưu thủ công → 1 lệnh.
2. **Premise-space estimator một-shot (P1 prototype):** 1 frame + import 3 enum + 1 call LLM offline → `N_plausible`/`N_remaining`. Backtest laundromat/ranger/mall/county-road hiệu chỉnh ngưỡng `<3`.
3. **Generator + emit format A (P3+P5 tối thiểu):** LLM sinh 10 candidate frame từ `content_triggers`, kèm chuỗi `--topic` ≥3 từ, lọc `topic_has_script_product()`, in sẵn dòng `run_seq_batch.py "..." "..."`.

### File liên quan
- Discovery: `implementation/src/omnicast/discovery/{orchestrator,scorer,seed_generator,niche_scanner,reddit_scanner,models}.py`
- Topic→batch: `implementation/content_flow.py`, `implementation/scripts/run_phase2_unit_first.py`, `implementation/scripts/run_seq_batch.py`
- Cross-video/premise primitives: `implementation/src/omnicast/agents/cross_video.py`, `implementation/src/omnicast/agents/narrative_pipeline.py` (WS0, đọc-only)
- Pipeline glue (WS0, đọc-only): `implementation/src/omnicast/pipeline/steps.py`
- Vault SSOT: `implementation/src/omnicast/vault/db.py`
- Channel config: `implementation/channels/true_dread_files_us.json`
