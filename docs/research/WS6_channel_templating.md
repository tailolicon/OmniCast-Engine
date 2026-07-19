> Sinh boi agent nghien cuu workflow ws-research-456, 2026-07-19. Read-only.

Đã đọc đủ. Dưới đây là báo cáo WS6.

---

# BÁO CÁO WS6 — Channel Templating (nhân bản learnings creepy sang kênh mới)

Phạm vi đọc: `channels/*.json`, `config/narrative_quality.py`, `agents/rubrics/`, `config/channel_styles.py`, `config/niches.py`, `config/channel.py`, `agents/critic.py`, `agents/writer.py` (narrative path), và `agents/narrative_pipeline.py` + `pipeline/steps.py` (chỉ đọc để hiểu contract WS0).

## Kết luận đầu (TL;DR)
Giả định nền của charter WS6 — *"kênh mới chỉ cần profile + benchmark"* — **SAI một phần và là rủi ro lớn nhất của luồng này**. Learnings của creepy KHÔNG nằm gọn trong profile. Chúng nằm rải ở 4 tầng, trong đó **3 tầng bị hard-code cứng theo genre horror và 2/3 nằm ngoài quyền sở hữu của WS6** (WS0). Ngoài ra `forgotten_chronicles_us` **hiện chưa chạy như narrative** — nó đang bị chấm như một explainer finance/tech, tệ hơn cả việc bị chấm nhầm bằng rubric horror.

---

## 1. BẢN ĐỒ HIỆN TRẠNG (có dẫn chứng file:line)

### 1.1 Đường đi thực tế của một kênh narrative (4 tầng, đều genre-coupled)

| Tầng | File:line | Vai trò | Trạng thái với horror | Trạng thái với history |
|---|---|---|---|---|
| Routing | `pipeline/steps.py:564-576` | `content_format=="narrative"` + `script_profile` ⇒ `unit_first` (NarrativeUnitPipeline); ngược lại ⇒ `claude_first` | Chạy thật | **Không kích hoạt** (xem 1.2) |
| Profile | `config/narrative_quality.py:138-245` | Registry chỉ có **đúng 1 profile** `true_horror_strict_v1` | Chạy thật | **Chưa tồn tại** |
| Writer | `agents/writer.py:806-895` (`_build_narrative_system_prompt`) | Prompt narrative generic cho path `claude_first` | Chạy thật | **Hard-code horror 100%** ("master first-person horror storyteller", "7 LAWS OF DREAD", ≥2/3 human threat) |
| Critic rubric | `agents/critic.py:105-111` + `rubrics/narrative_horror.py` | Chọn rubric bằng **boolean** `is_narrative`, chỉ có 1 rubric narrative | Chạy thật | **Chấm sai** (dimension `fear_immersion` "a threat that ACTS") |
| Plan model (WS0) | `narrative_pipeline.py:184-261` | `NarrativeStoryPlan` với axes horror cứng | Chạy thật | **Bất khả thi** (xem 1.4) |

### 1.2 `forgotten_chronicles_us` HIỆN đang bị chấm như EXPLAINER (không phải horror, không phải story)
- Config: `channels/forgotten_chronicles_us.json:5` niche=`mythology`, **không có** `script_profile`, **không có** `niche_config_key`, `channel_style:"storytelling"` (dòng 8).
- `config/niches.py:132-149` — NicheConfig `mythology` **không set** `content_format`, nên mặc định `"explainer"` (`niches.py:38`).
- Resolve: `steps.py:474-481` → không có `niche_config_key` → `get_niche_config("mythology", "untold history…storytelling")` → key con không khớp → rơi về `"mythology"` → `content_format="explainer"`.
- Hệ quả: `steps.py:565-568` chọn `claude_first`; critic dùng rubric explainer (`critic.py:109-111`, `is_narrative=False`) với number-hook, CTA, insider-data, proof-stat. Đây đúng là lỗi lịch sử đã ghi: `IMPLEMENTATION_STATUS.md:118` ("rubric anti-listicle misfit với story channel, flagged task riêng") — chính là task WS6 này.
- **Kết luận:** kênh #2 hiện ở trạng thái tệ nhất trong 3 khả năng (explainer > horror-misscore > đúng). `channel_style:"storytelling"` chỉ tác động phần VISUAL (`channel_styles.py:65-84`), hoàn toàn tách rời khỏi phần script — nên visual đang là minh hoạ AI storytelling còn script lại là explainer. Lệch pha.

### 1.3 Giải phẫu tầng consume profile (đường `unit_first`, đang chạy thật cho creepy)
- `steps.py:582-586` resolve profile → `NamedChannelStrategy.from_quality_profile()` (`narrative_pipeline.py:91-149`) map profile → gate runtime.
- Các gate thật sự được thực thi (đọc typed plan data):
  - typed mechanism axes diversity: `narrative_pipeline.py:2476-2492` (`_MECHANISM_AXES` = threat/progression/escape/aftermath/threat_identity).
  - `topic_alignment_gate`: `2494-2508`; `safety_response_gate`: `2510-2531`; human-threat fraction: `2532-2536`; evidence budget: `2537-2548`.
  - stylometric texture gate: denylist `1461-1520`, enforce `2053`; forbidden ending: `1864`; plan-fact fidelity: `1874`; scorecard floors: `2147-2160`.
- Scorecard dimensions (`narrative_pipeline.py:983-990`): `continuity_believability/ distinct_authentic_voices/ dread_escalation/ plausible_response/ structural_variety/ originality/ ending_discipline`.

### 1.4 Blocker cứng: plan model + system floors ép mọi narrative phải là horror
- `NarrativeStoryPlan` (`narrative_pipeline.py:234-260`) bắt buộc `threat_type: Literal["human","ambiguous"]`, `threat_mechanism`, `progression_mechanism`, `escape_mechanism`, `aftermath_mechanism`, `threat_identity`, `safety_obligation`. Một câu chuyện lịch sử **không có** "threat_type"; planner sẽ bị ép dán nhãn một sự kiện lịch sử thành mối đe doạ human/ambiguous.
- `validate_plan_preflight` (`narrative_pipeline.py:2532-2536`) ép `≥ ceil(N × 2/3)` story là human threat — bất khả thi cho history.
- **Trong chính file WS6 sở hữu** (`narrative_quality.py`), 3 hằng số CHẶN việc tạo profile history:
  - `strategy: Literal["first_person_true_horror_compilation"]` (dòng 48) — Literal 1 giá trị, không tạo được strategy tag mới.
  - `minimum_human_threat_fraction: Field(ge=SYSTEM_MIN_HUMAN_THREAT_FRACTION=2/3…)` (dòng 19, 65-69) — **sàn hệ thống ép mọi profile ≥2/3 human threat**.
  - `dread_rules: Field(min_length=1…)` (dòng 116) — bắt buộc ≥1 "dread rule"; history không có dread.

---

## 2. LỖ HỔNG (xếp theo tác động vào chất lượng/độ tin cậy video cuối)

**G1 — Kênh #2 bị chấm bằng value system SAI (impact: cao nhất).**
`forgotten_chronicles` chạy nhánh explainer (§1.2). Rubric explainer đòi number-hook/CTA/insider-stat, writer explainer chèn greeting + "according to" + charts. Với fireside history storytelling, đây là mis-score có hệ thống → điểm bị kéo xuống oan (đúng vệt 73/63 lịch sử) và script ra sai format. Ngay cả khi bật `content_format="narrative"`, rubric narrative duy nhất (`narrative_horror`) chấm `fear_immersion` "a threat that ACTS" (`narrative_horror.py:56-58`) — history không có threat → thủng dimension.

**G2 — Không có genre-abstraction: toàn bộ pipeline narrative hard-code horror (impact: cao).**
Writer (`writer.py:817-895`), rubric (chỉ `narrative_horror`), plan model (`narrative_pipeline.py:184-261`) đều nhúng cứng khái niệm threat/dread/safety. Việc "nhân bản kênh" như charter mô tả (chỉ thêm profile) là bất khả thi nếu không tách genre thành module tham số hoá. **Đây là lỗ hổng kiến trúc, không phải config.**

**G3 — System floors trong `narrative_quality.py` từ chối mọi genre phi-horror (impact: cao).**
`SYSTEM_MIN_HUMAN_THREAT_FRACTION=2/3` + `dread_rules` bắt buộc + `strategy` Literal đơn (§1.4). File này **thuộc WS6**, nên WS6 phải refactor schema trước khi profile thứ 2 khả thi — nhưng runtime consume nó (`narrative_pipeline.py`) thuộc WS0 ⇒ đổi schema phải đồng bộ hai luồng (interface đóng băng theo charter §3).

**G4 — Rubric selection là boolean, không phải theo genre (impact: trung bình-cao).**
`critic.py:105-111` `_rubric_dims(is_narrative)` chỉ 2 nhánh (explainer | horror). Không có trục thứ 3 cho story. Thêm rubric `narrative_story` mà không sửa selector thì rubric mới không bao giờ được chọn.

**G5 — Stylometric denylist trộn lẫn craft phổ quát với nội dung horror (impact: trung bình).**
`_CLICHE_TELLS`/`_RATIONED_TICS`/`_STILL_WATCHER` (`narrative_pipeline.py:1461-1520`) vừa chứa tic phổ quát (negation-reversal, "the way X", soma cliché) vừa chứa horror-only ("still watcher", "I like the night shift"). Kênh history dùng lại nguyên si sẽ bỏ sót tic riêng của history (vd "Little did they know…", "history forgot", "But fate had other plans") và áp nhầm luật still-watcher.

**G6 — `niche_config_key` của kênh #2 bị bỏ trống ⇒ phụ thuộc fallback mong manh (impact: thấp-trung bình).**
`true_dread` dùng `niche_config_key:"psychology.horror"` để bind đúng config (`steps.py:471-479`); `forgotten_chronicles` không có → phụ thuộc fallback chuỗi và ăn nhầm config. Đây chính là lớp lỗi đã từng gây "script 73/63" cho horror (`IMPLEMENTATION_STATUS.md:118`).

---

## 3. Câu hỏi trọng tâm (a): Bảng phân loại UNIVERSAL vs HORROR-SPECIFIC từng gate/field

Nguồn: `narrative_quality.py` (field) + `narrative_pipeline.py` (nơi thực thi).

| Field/Gate | file:line | Loại | Ghi chú tái dùng cho history |
|---|---|---|---|
| `editorial_floor`, `continuity_floor`, `dimension_floor_ratio` | nq:54-64 | **UNIVERSAL** | Giữ nguyên cơ chế; chọn ngưỡng riêng |
| `maximum_plan_attempts/repairs`, `patch_candidate_count`, `final_compilation_editor_required` | nq:90-95 | **UNIVERSAL** | Giữ nguyên |
| `require_distinct_mechanisms` | nq:100 | **UNIVERSAL (khái niệm)** nhưng **axes bị horror-hoá** | Cơ chế "mỗi story khác nhau" phổ quát; nhưng `_MECHANISM_AXES` (np:217) là threat-axes → cần history axes |
| `topic_alignment_gate` | nq:102, np:2494 | **UNIVERSAL** | Rất cần cho history (mỗi story giao đúng chủ đề) — giữ |
| `forbidden_ending_gate` | nq:104, np:1864 | **UNIVERSAL (cơ chế)**, denylist horror | Giữ cơ chế, thay `_FORBIDDEN_ENDING_RE` |
| `release_challenger_required` | nq:105 | **UNIVERSAL** | Giữ — reader đối kháng cuối |
| `stylometric_texture_gate` | nq:107, np:2053 | **UNIVERSAL (cơ chế: texture budget)**, denylist trộn | Giữ gate; tách denylist theo genre (G5) |
| `plan_self_audit_rules`, `planning_rules`, `voice_rules`, `ending_rules`, `avoid_tropes` | nq:113-118 | **Field UNIVERSAL**, nội dung theo genre | Craft phổ quát bên trong (vd voice: "khác nhịp câu/từ vựng mỗi narrator" nq:202-204; ending: "kết trong 2 beat của hình ảnh mạnh nhất" nq:231-234) → **giữ dạng, viết lại nội dung** |
| `channel_promise` | nq:49-52 | **Field UNIVERSAL**, nội dung horror | Viết lại |
| Texture budgets (`_RATIONED_TICS` ≤1/compilation, `_CLICHE_TELLS`=0) | np:1462-1496 | **UNIVERSAL craft** (đúng thứ user gọi "texture budget", "quote-mọi-occurrence") | Giữ cơ chế đếm; đổi danh sách |
| Scorecard `continuity_believability`, `structural_variety`, `originality`, `ending_discipline` | np:984-990 | **UNIVERSAL** | Giữ |
| Scorecard `distinct_authentic_voices` | np:985 | **UNIVERSAL craft** (giọng narrator riêng) | Giữ, reframe (fireside vs shaken) |
| `strategy` Literal | nq:48 | **HORROR-SPECIFIC (blocker)** | Phải nới thành Literal đa giá trị |
| `minimum_human_threat_fraction` + SYSTEM floor 2/3 | nq:19,65 | **HORROR-SPECIFIC (blocker)** | Bỏ khỏi sàn hệ thống / cho phép 0 |
| `maximum_evidence_beats_per_story`, `minimum_evidence_free_stories` | nq:70-79 | **HORROR-SPECIFIC (nghịch cực)** | Horror muốn *under-confirm*; history muốn *over-source* → phải đảo |
| `maximum_numeric_anchors`, `maximum_precise_clock_times` | nq:80-89 | **HORROR-SPECIFIC (nghịch cực)** | Horror cấm số giả; history CẦN năm/ngày → nới cao |
| `safety_response_gate` | nq:103, np:2510 | **HORROR-SPECIFIC** | Tắt cho history |
| `promote_impossibility_to_major` | nq:106 | **HORROR-SPECIFIC** ("impossibility"=siêu nhiên) | Không áp dụng |
| `dread_rules` (min_length=1) | nq:116 | **HORROR-SPECIFIC (blocker)** | Phải cho phép rỗng / đổi tên `tension_rules` |
| `plan_fact_fidelity_gate` | nq:103, np:1874 | **SEMI → CORE cho history** | Horror dùng nhẹ; history đây là gate TRUNG TÂM (cite hoặc gắn nhãn legend) |
| Scorecard `dread_escalation`, `plausible_response` | np:986-987 | **HORROR-SPECIFIC** | Thay bằng `dramatic_tension` + `historical_grounding` |
| Plan axes threat/safety (`NarrativeStoryPlan`) | np:234-260 | **HORROR-SPECIFIC (blocker WS0)** | Cần history axes |

---

## 4. Câu hỏi trọng tâm (b): Thiết kế profile v1 cho `forgotten_chronicles` (history narrative)

### 4.1 Trục mechanism thay threat axes (analog của `_MECHANISM_AXES`)
Giữ nguyên **cơ chế** "typed closed-vocabulary axes, diversity-checked" (đúng insight creepy: prose khác chữ vẫn là "một chuyện kể 3 lần" — np:178-183). Thay nội dung:

- `reveal_mechanism` (cách sự thật bị lãng quên lộ ra) ← thay `threat_mechanism`: `buried_record | eyewitness_testimony | archaeological_find | contradiction_in_sources | reinterpretation | overlooked_figure_surfaces | translation_error_corrected`.
- `turning_point_mechanism` (bản lề kịch tính) ← thay `progression_mechanism`: `single_decision | betrayal | accident_of_timing | technological_edge | natural_disaster | miscommunication | slow_erosion`.
- `consequence_mechanism` (hệ quả/stakes) ← thay `escape_mechanism`: `empire_falls | discovery_lost | legacy_erased | life_spared_or_taken | chain_reaction_downstream | quiet_footnote`.
- `resolution_mechanism` (đóng câu chuyện) ← thay `aftermath_mechanism`: `vindicated_by_later_evidence | remains_disputed | forgotten_again | reinterpreted_today | monument_or_trace_remains | lesson_for_present`.
- `vantage_identity` (POV) ← thay `threat_identity`: `overlooked_participant | losing_side | bystander_witness | modern_excavator | ruler_or_leader | ordinary_life`.
- `source_fidelity` (analog `evidence_allowance`, **đảo cực**): `documented | reconstructed | contested | legend` — với **`fact_fidelity_gate` bật** và bắt mỗi claim mạnh phải `documented|reconstructed`, còn `legend` phải được gắn nhãn trong prose (thay cho luật "under-confirm/no proof-stacking" của horror).

### 4.2 Gate stylometric giữ nguyên vs thay
- **Giữ (cơ chế + hầu hết nội dung phổ quát):** `_NEGATION_REVERSAL_RE`, `_THE_WAY_COMPARISON_RE`, `_CLICHE_TELLS` phần soma chung; texture budget `_RATIONED_TICS` (đếm ≤1/compilation).
- **Thay bằng history denylist:** bỏ `_STILL_WATCHER_RE`, "I like the night shift"; thêm history-slop: "Little did they know", "history forgot / lost to history", "But fate had other plans", "as we know today", "changed the course of history forever", "shrouded in mystery".
- **Giữ:** `topic_alignment_gate`, `forbidden_ending_gate` (đổi regex: cấm kết bằng câu triết lý sáo "and that is why history matters"), `release_challenger_required`, `require_distinct_mechanisms` (trên history axes), `stylometric_texture_gate`.

### 4.3 Rubric `narrative_story` (dimension mới, giữ ngân sách 70/30 để routing `critic.py`/`steps.py` không đổi)
- `continuity` (20) — **giữ** (universal, tính khả tín/nhất quán timeline).
- `narrator_craft` (18) ← reframe `authentic_voice`: giọng fireside cuốn hút, không listicle, không "according to".
- `dramatic_tension` (12) ← thay `fear_immersion`: stakes, momentum, "what it felt like to be there".
- `historical_grounding` (8, tách bớt từ originality) — **DIMENSION MỚI cốt lõi**: tên/năm/địa danh thật, không anachronism, phân biệt fact vs legend. Đây là cực ngược của horror "under-confirm".
- `structural_variety` (12) — **giữ**.
- Production dims (`visual_concreteness` 25, `sfx_appropriateness` 5) — **giữ nguyên** contract `rubrics/__init__.py:9-14`.

---

## 5. Câu hỏi trọng tâm (c): CHECKLIST nhân bản kênh mới (config → profile → benchmark → autopsy)

**Bước 0 — Quyết định điều phối (BẮT BUỘC trước khi code):** Vì learnings nằm ở WS0 (`narrative_pipeline.py`, `writer.py` narrative, plan model) lẫn WS6, phải chốt với điều phối: **hoặc** (A) WS0 tách genre thành module tham số (mở khoá history thật), **hoặc** (B) WS6 chỉ ship phần config + rubric + profile-schema-relax và history tạm chạy qua path `claude_first` với một writer prompt narrative-story mới. Khuyến nghị (A) dài hạn, (B) làm quick-win.

**Bước 1 — Channel config** (`channels/forgotten_chronicles_us.json`): thêm `script_profile:"history_story_v1"`, thêm `niche_config_key` trỏ tới NicheConfig narrative (tránh fallback G6).

**Bước 2 — NicheConfig** (`config/niches.py`): thêm key (vd `mythology.history` hoặc `storytelling`) với `content_format="narrative"`, insider_angle="fireside historian", `proof_sources` history. *(coordination: file config chung; xác nhận ranh giới với WS0/điều phối.)*

**Bước 3 — Relax profile schema** (`config/narrative_quality.py`, thuộc WS6): (i) nới `strategy` thành Literal đa giá trị; (ii) gỡ `minimum_human_threat_fraction` khỏi sàn hệ thống (cho ge=0) hoặc chuyển thành field không-sàn; (iii) cho `dread_rules` default rỗng (đổi/bổ sung `tension_rules`); (iv) thêm profile `_HISTORY_STORY_V1`. **Không đụng** `_TRUE_HORROR_STRICT_V1`.

**Bước 4 — Rubric** (`agents/rubrics/narrative_story.py` + đăng ký ở `__init__.py`): dims §4.3, đúng contract VO_DIMS/PROD_DIMS/VO_PASS/PROD_PASS/`dimension_rubric()`/`json_template()`/`slop_cap_dims`.

**Bước 5 — Rubric selection** (`agents/critic.py:105-111`): đổi `_rubric_dims(is_narrative: bool)` → chọn theo genre (map từ `content_format`/`script_profile`), thêm nhánh `narrative_story`. *(coordination với WS0 nếu critic dùng chung.)*

**Bước 6 — Plan model + writer genre-parametric** (WS0 — `narrative_pipeline.py` axes, `writer.py:806-895`): tách horror axes/prompt thành module theo genre. **Ngoài phạm vi WS6 — phải WS0 làm.**

**Bước 7 — Benchmark topic đầu:** chọn 1 topic history "an toàn" (vd một nhân vật/biến cố có nguồn rõ) để chạy autopsy, giống creepy chọn house-sitting/gas-station.

**Bước 8 — Vòng autopsy:** chạy live → autopsy → mỗi lớp lỗi thành 1 gate vĩnh viễn (đúng phương pháp charter). Số vòng dự kiến: xem §6.

---

## 6. Câu hỏi trọng tâm (d): Chi phí đưa kênh #2 tới parity với creepy

Cơ sở: creepy tốn **~15 vòng, 74→88** (charter dòng 5-6; các bullet autopsy `IMPLEMENTATION_STATUS.md:60-64,118`).

- **Phần tái dùng miễn phí (~40-50% learnings):** universal gates §3 (continuity/topic-alignment/forbidden-ending/stylometric-mechanism/challenger/self-audit) đã ổn định qua 15 vòng creepy → history thừa hưởng ngay. Đây là lý do history **không** cần lại full 15 vòng.
- **Phần phải làm lại từ đầu:** history axes (§4.1), rubric dims (§4.3), source-fidelity đảo cực (over-source thay under-confirm), history-slop denylist (§4.2). Đây là các lớp lỗi mới, chưa từng thấy.
- **Ước lượng vòng autopsy:** **8-11 vòng** để đạt ổn định tương đương (so với 15), với điểm khởi điểm cao hơn (~78-80 nhờ tái dùng gate craft phổ quát) tiến tới ~88. Rủi ro tăng thêm 3-4 vòng nếu Bước 6 (WS0 genre-parametric) bị trì hoãn ⇒ phải làm việc qua path `claude_first` (writer prompt riêng) rồi mới port sang unit_first.
- **Chi phí kỹ sư (không tính LLM):** schema-relax (S) + profile (S) + rubric (M) + selector (S) = ~**M tổng** cho phần WS6; WS0 genre-parametric refactor = **L** (blocker parity thật).
- **Chi phí LLM live:** mỗi build unit_first ~$0.20-0.30, ~8-12 phút (`steps.py:556-561`); ×8-11 vòng ×(1-2 build/vòng) ≈ **$4-7 và ~3-5 giờ gen** (xếp hàng batch, không song song tài khoản — charter §4).

---

## 7. KẾ HOẠCH NÂNG CẤP (xếp theo tác động)

| # | Mục | File đụng | Effort | Rủi ro | Đo thành công khách quan |
|---|---|---|---|---|---|
| P1 | **Genre-parametric hoá pipeline narrative** (tách threat/dread axes khỏi plan model + writer + critic thành module theo genre) | `narrative_pipeline.py`, `writer.py:806-895`, `critic.py:105-111` — **WS0, cần điều phối** | **L** | Cao (đụng interface đóng băng, WS0 đang live) | Suite ≥1363 pass; horror build vẫn ra điểm cũ (regression 0); history build tạo plan hợp lệ không cần dán nhãn threat |
| P2 | **Relax `narrative_quality.py` schema + thêm `history_story_v1`** (nới `strategy` Literal, gỡ sàn 2/3 human-threat, cho `dread_rules` rỗng) | `config/narrative_quality.py` (WS6) | **M** | Trung bình (schema là interface đóng băng, đồng bộ với `from_quality_profile` np:91-149) | `resolve_script_profile("history_story_v1")` pass; `_TRUE_HORROR_STRICT_V1` bất biến (test snapshot); channel validator `channel.py:102-110` pass |
| P3 | **Rubric `narrative_story` + selector theo genre** (§4.3, G1/G4) | `agents/rubrics/narrative_story.py`, `rubrics/__init__.py`, `critic.py:105-111` | **M** | Trung bình | Cùng 1 script history: điểm rubric_story > rubric_horror ≥ +10; production dims 70/30 giữ nguyên → routing test pass |
| P4 | **Bind kênh #2 vào narrative** (niche `content_format`, `niche_config_key`, `script_profile`) | `channels/forgotten_chronicles_us.json`, `config/niches.py` | **S** | Thấp | `steps.py` resolve ra `content_format="narrative"` + `unit_first`; không còn rơi explainer (assert trong test) |
| P5 | **History axes + source-fidelity gate + history-slop denylist** (§4.1-4.2) | profile mới + (nếu P1 xong) plan module history | **M** | Trung bình | Gate chặn được ≥1 fixture "legend không gắn nhãn" và ≥1 anachronism; diversity-check trên history axes hoạt động |

---

## 8. QUICK WINS (1 buổi, trong phạm vi WS6, không đụng WS0)

1. **Sửa G6 ngay:** thêm `niche_config_key` vào `channels/forgotten_chronicles_us.json` — bỏ phụ thuộc fallback (lớp lỗi đã từng gây 73/63 cho horror). Effort S, rủi ro ~0.
2. **Bật narrative cho history ở tầng niche:** thêm NicheConfig `content_format="narrative"` cho history trong `config/niches.py` — chấm dứt tình trạng explainer-misscore (G1) ngay lập tức, kể cả trước khi có profile (path `claude_first` narrative). *(Xác nhận ranh giới file với điều phối.)*
3. **Viết sẵn `rubrics/narrative_story.py`** (dims §4.3) đúng contract `rubrics/__init__.py:9-14` — chưa cần wire selector, nhưng có sẵn để P3 chỉ còn 1 dòng chọn genre. Effort S, rủi ro 0 (module chưa được gọi).
4. **Test snapshot bất biến cho `_TRUE_HORROR_STRICT_V1`** — chốt profile creepy không bị regress khi P2 sửa schema. Effort S; là lưới an toàn cho toàn bộ WS6.

---

## 9. Cảnh báo điều phối (đọc trước khi thực thi)
- **`narrative_quality.py` (WS6) và `narrative_pipeline.py` (WS0) là hai đầu của một interface đóng băng** (charter §3: "Schema … `NarrativeQualityStrategy`"). Mọi thay đổi field trong P2 phải đồng bộ `from_quality_profile` (np:91-149). WS6 **không được** tự đổi một mình.
- **`config/niches.py`, `critic.py`, `writer.py`** không nằm rõ trong danh sách phạm vi WS6 (charter dòng 63-68 liệt kê `channels/*.json`, `config/narrative_quality.py`, "rubric cho forgotten_chronicles"). P3/P4/P1 chạm chúng ⇒ **cần điều phối chốt ownership** trước khi mở nhánh, tránh va WS0 đang live.
- Không chạy gen-live history song song với creepy trên cùng tài khoản Claude (charter §4: throttle chết cả hai) — xếp hàng qua batch runner.