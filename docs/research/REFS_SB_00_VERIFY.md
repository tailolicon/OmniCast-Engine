# REFS_SB_00 — Nghiệm thu chéo 7 report REFS_SB (adversarial verify)

> STATUS: DONE (2026-08-02)  
> Vai trò: VERIFIER đối kháng — không tin report; chỉ tin code trong `_refs\` (và OmniCast khi report claim “đã port”).  
> Input: `docs/research/REFS_SB_01..07*.md`  
> Quy tắc: chỉ ghi file này; không sửa report gốc; không sửa `_refs\`.

---

## 0. Phương pháp

Với **mỗi report**:

1. Chọn ≥8 claim quan trọng (≥3 khối “prompt verbatim”) → mở đúng `file:line` trong `_refs\` → đối chiếu chữ / cơ chế.
2. Coverage: đủ 10 mục COMMON_CONTEXT? Mục 4 CHÉP ĐỦ prompt chính?
3. LICENSE report vs `LICENSE` thật.

**Thang verdict**

| Verdict | Ý nghĩa |
|---------|---------|
| **TIN ĐƯỢC** | Cơ chế + schema + license đúng; verbatim chính khớp; lỗi nhỏ/tóm tắt phụ |
| **TIN CÓ ĐIỀU KIỆN** | Nền đúng nhưng có lỗi factual, suy diễn, hoặc mục 4 không đủ “verbatim đầy đủ” |
| **PHẢI LÀM LẠI** | Bịa / sai hàng loạt / license sai / coverage vỡ mục cốt lõi |

---

## 1. Bảng tổng hợp

| Report | Claims kiểm | Khớp | Sai / lệch | Bịa / suy quá | License | §1–10 | Verdict |
|--------|-------------:|-----:|------------:|--------------:|---------|:-----:|---------|
| **01 ArcReel** | 12 | 10 | 2 (tóm tắt “verbatim”) | 0 | AGPL-3.0 ✓ | ✓ | **TIN ĐƯỢC** |
| **02 Jellyfish + LocalMiniDrama** | 11 | 7 | 3 | 1 (status enum) | Apache-2.0 + MIT ✓ | ✓ | **TIN CÓ ĐIỀU KIỆN** |
| **03 waoowaoo** | 11 | 6 | 4 (verbatim = paraphrase) | 0 | CC BY-NC-SA 4.0 ✓ | ✓ | **TIN CÓ ĐIỀU KIỆN** |
| **04 AIComicBuilder + StoryGen** | 11 | 7 | 3 | 0 | Apache-2.0 ×2 ✓ | ✓ | **TIN CÓ ĐIỀU KIỆN** |
| **05 seedance-2.0 + Orkas** | 12 | 10 | 2 (mis-cite Soul; renumber §) | 0 | MIT ×2 ✓ | ✓* | **TIN ĐƯỢC** |
| **06 Pixelle + MPT + SVF** | 11 | 8 | 3 (Pixelle prompts rút gọn) | 0 | Apache / MIT / AGPL ✓ | ✓ | **TIN CÓ ĐIỀU KIỆN** |
| **07 hyperframes** | 10 | 8 | 2 (15 vs 16 caption) | 0 | Apache-2.0 ✓ | ✓ | **TIN ĐƯỢC** |

\* Report 05 đánh số §9 = câu hỏi brief, §10 = đề xuất, §11 = license — **nội dung 10 mục có đủ**, chỉ lệch số thứ tự COMMON_CONTEXT.

**Không report nào đạt PHẢI LÀM LẠI toàn phần.** Yếu nhất: **03** (verbatim prompt) và **02** (lỗi enum status cứng). Round 2 nên **bổ sung prompt bỏ sót + vá lỗi listed**, không rewrite 0→1.

---

## 2. Chi tiết từng report

### 2.1 REFS_SB_01_ArcReel.md — **TIN ĐƯỢC**

#### Claims đã đối chiếu

| # | Claim (tóm) | Cite report | Thực tế code | Kết quả |
|---|-------------|-------------|--------------|---------|
| 1 | `ShotType` / `CameraMotion` / `TransitionType` literal lists | §2.1 `script_models.py:29-66` | Khớp từng giá trị `_refs/ArcReel/lib/script_models.py:29-66` | **KHỚP** |
| 2 | OOV enum → `Medium Shot` / `Static` | `script_models.py:76-107` | `_DEFAULT_SHOT_TYPE` / `_DEFAULT_CAMERA_MOTION` + normalize | **KHỚP** |
| 3 | `ImagePrompt` / `VideoPrompt` / `DramaVideoPrompt` / status `pending\|storyboard_ready\|completed` | §2.2–2.3 | `script_models.py:123-189` | **KHỚP** |
| 4 | `Shot.duration` 1–15; unit 1–4 shots; refs order = `[图N]` | `script_models.py:830-870` | `REFERENCE_SHOT_DURATION_RANGE=(1,15)`; `min_length=1,max_length=4` | **KHỚP** |
| 5 | Product `in_global_library=False` | §2.7 | `asset_types.py:102-103` comment + flag | **KHỚP** |
| 6 | Previous-frame label + description soft role | `storyboard_sequence.py:26-29` | Label exact; description **1 dòng** (report ngắt dòng — whitespace only) | **KHỚP*** |
| 7 | **Verbatim** `_CHARACTER_LAYOUT` … `_NEGATIVE_TAIL_VIDEO` | `prompt_builders.py` | Khớp từng chuỗi hằng số `prompt_builders.py:24-65` | **KHỚP** |
| 8 | **Verbatim** `_SCENE_WRITING_GUIDE` / `_ACTION_WRITING_GUIDE` | `prompt_builders_script.py:129-149` | Khớp nguyên văn | **KHỚP** |
| 9 | **Verbatim** `_NORMALIZE_TASK_NOVEL/SCREENPLAY` | `:162-170` | Khớp `prompt_builders_script.py:162-170` | **KHỚP** |
| 10 | YAML image keys Style/Scene/Composition | `prompt_utils.py:35-99` | `image_prompt_to_yaml` order đúng | **KHỚP** |
| 11 | Retry `DEFAULT_MAX_ATTEMPTS=3`, backoff `(2,4,8)` | §5.2 | `lib/retry.py:55-60` | **KHỚP** |
| 12 | Project asset dirs gồm `grids` | `project_manager.py:168-180` | List đúng | **KHỚP** |

#### Lỗi / lệch

| Report | Claim | Thực tế | Severity |
|--------|-------|---------|----------|
| 01 §4.4 | “Narration step2 visual prompt skeleton” trình bày như verbatim | `build_narration_prompt` dài hơn nhiều (`prompt_builders_script.py:277+`); report chỉ khung bullet | **Trung** — không bịa, **không CHÉP ĐỦ** |
| 01 §4.10 | Grid prompt block với `…` | `lib/grid/prompt_builder.py` đầy đủ hơn; report rút | **Thấp** |

#### Coverage §1–10 + license

- Đủ 10 mục (+ §11 câu hỏi riêng, §Đã đọc).
- Mục 4: **tốt hơn các report khác** trên constants + writing guides; vẫn còn skeleton cho narration/grid/ad full builders.
- **License AGPL-3.0** khớp `_refs/ArcReel/LICENSE` — khuyến nghị “cấm chép code” đúng.

---

### 2.2 REFS_SB_02_Jellyfish_LocalMiniDrama.md — **TIN CÓ ĐIỀU KIỆN**

#### Claims đã đối chiếu

| # | Claim | Cite | Thực tế | Kết quả |
|---|-------|------|---------|---------|
| 1 | Shot fields id/chapter/index/title/script_excerpt/… | `studio_shots.py:24-128` | Class `Shot` khớp khoảng dòng | **KHỚP** |
| 2 | **`status` chỉ `pending \| ready` (2 trạng thái)** | §2.1 L133 | `ShotStatus` = `pending`, **`generating`**, `ready` — `backend/app/models/types.py:34-39` | **SAI / BỊA enum** |
| 3 | ShotDetail camera_shot/angle/movement/duration/prompts | `studio_shots.py:131-218` | Field chính đúng; **thiếu** `override_video_ratio`, `follow_atmosphere`, `has_bgm`, `description`, `prompt_template_id` (vẫn trong class) | **LỆCH** (thiếu field) |
| 4 | **Verbatim** ScriptDivider system | `script_divider_agent.py:13-22` | Khớp `_SCRIPT_DIVIDER_SYSTEM_PROMPT` | **KHỚP** |
| 5 | **Verbatim** ConsistencyChecker system | `consistency_checker_agent.py:12-20` | Khớp | **KHỚP** |
| 6 | **Verbatim** LocalMiniDrama character extract | `promptI18n.js:71-89` | Nội dung khớp; report **bỏ** markdown bold `**【语言要求】…**` và rút dòng JSON output | **LỆCH verbatim** |
| 7 | **Verbatim** identity anchors 6 keys | `promptI18n.js:1492-1515` | Khớp full `getIdentityAnchorsPrompt` | **KHỚP** |
| 8 | identity_anchors 6 lớp + color_palette Hex | migrate + service | `migrate.js` comment 6 lớp; service ghi JSON | **KHỚP** |
| 9 | Base prompt cấm `## 图片内容说明` / 图N | shot_frame agents | Pattern base vs rendered tách — cơ chế đúng | **KHỚP** (cơ chế) |
| 10 | Actor+Costume → Character image refs | §3.1 | Có trong SQL templates / asset pipeline | **KHỚP** (cơ chế) |
| 11 | License Apache-2.0 + MIT | §10 | Khớp cả hai `LICENSE` | **KHỚP** |

#### Lỗi cụ thể

1. **Sai cứng — ShotStatus**  
   - Report: ``pending | ready`` (chỉ 2).  
   - Code: `pending | generating | ready` (`types.py:34-39`).  
   - Ảnh hưởng: mọi diagram state machine “pending→ready” thiếu bước generating.

2. **ShotDetail incomplete** — report trình bày như “verbatim fields quan trọng” nhưng bỏ field production-relevant (`has_bgm`, `description`, `override_video_ratio`, …) trong `studio_shots.py:174-208`.

3. **LocalMiniDrama character prompt** — không khớp từng chữ (thiếu `**` bold; cắt “输出格式” cuối).

4. **ElementExtractor / frame agents** — report thừa nhận “rút lõi”; không đủ CHÉP ĐỦ theo COMMON_CONTEXT mục 4 cho agent dài nhất.

#### Coverage

- §1–10 có.  
- Jellyfish: hầu hết agent file được **kể tên**; full system prompt của `element_extractor_agent`, `entity_merger`, `variant_analyzer` **không** chép đủ.  
- LocalMiniDrama: `promptI18n.js` là SSOT khổng lồ — report excerpt tốt nhưng storyboard system (zh full ~100+ dòng), TTS, video omni bundle chỉ một phần.

#### License: **OK**

---

### 2.3 REFS_SB_03_waoowaoo.md — **TIN CÓ ĐIỀU KIỆN**

#### Claims đã đối chiếu

| # | Claim | Cite | Thực tế | Kết quả |
|---|-------|------|---------|---------|
| 1 | `collectPanelReferenceImages`: sketch → chars → location | `image-task-handler-shared.ts:225-263` | Thứ tự đúng | **KHỚP** |
| 2 | Character sheet suffix left 1/3 + right tri-view | `constants.ts:192` | `CHARACTER_PROMPT_SUFFIX` đúng ý; report **rút `…`** | **LỆCH verbatim** |
| 3 | ART_STYLES `american-comic` → promptZh `日式动漫风格` | `constants.ts:137-144` | Đúng (quirk label≠prompt) | **KHỚP** |
| 4 | VIDEO_MODELS Seedance/Kling/Veo/Wan/Sora | `constants.ts:68-85` | Khớp catalog | **KHỚP** |
| 5 | Atomic retry max 3 / delay 10s | `script-to-storyboard-atomic-retry.ts:63-64` | `MAX_STEP_ATTEMPTS=3`, `MAX_RETRY_DELAY_MS=10_000` | **KHỚP** |
| 6 | **“Verbatim”** `agent_clip.zh.txt` | §4.1 | File thật dài; report chỉ 1 đoạn + `…` + tóm rule — **không** full text | **SAI tiêu chí verbatim** |
| 7 | **“Verbatim”** storyboard plan / cinematographer / detail | §4.2–4.5 | Toàn paraphrase + bullet, không chép đủ file | **SAI tiêu chí verbatim** |
| 8 | **“Verbatim”** `single_panel_image.zh.txt` (FULL) | §4.6 | Vẫn rút với `…`; không full | **LỆCH** (không FULL) |
| 9 | Không seed/LoRA/IP-Adapter trên gen path | §3.5 | Không thấy trong handler path đã đọc | **KHỚP** (cơ chế) |
| 10 | Video i2v primary; first-last capability gate | §6 | Khớp design constants + worker pattern | **KHỚP** (cơ chế) |
| 11 | License CC BY-NC-SA 4.0 | header §10 | Khớp `LICENSE` | **KHỚP** |

#### Lỗi cụ thể

1. **Mục 4 FAIL soft:** COMMON_CONTEXT yêu cầu *CHÉP ĐỦ, đừng tóm tắt*. Report 03 **tự ghi** “một số file rất dài — giữ rule block” nhưng vẫn gắn nhãn VERBATIM. So với `agent_clip.zh.txt` (định nghĩa content elements, đếm 20, …) report chỉ còn skeleton.

2. **Coverage prompt files:** `lib/prompts/` có **62** file `.txt`; ~40 không được mention (xem §3 dưới).

3. `CHARACTER_PROMPT_SUFFIX` cite line 192 đúng, nhưng block “verbatim” trong report **không** full string (thiếu chi tiết animal/生物 branch).

#### License: **OK** (và anti-commercial đúng hướng)

---

### 2.4 REFS_SB_04_AIComicBuilder_StoryGen.md — **TIN CÓ ĐIỀU KIỆN**

#### Claims đã đối chiếu

| # | Claim | Cite | Thực tế | Kết quả |
|---|-------|------|---------|---------|
| 1 | `shot_assets` types + versioning comment | `schema.ts:126-177` | Khớp enum + comment “two modes coexist” | **KHỚP** |
| 2 | Shot duration default 10; status pending/generating/completed/failed | `schema.ts:179-212` | Khớp | **KHỚP** |
| 3 | **Verbatim** REF_IMAGE role (no people) | `registry.ts:1829+` | Khớp `REF_IMAGE_PROMPTS_ROLE` | **KHỚP** |
| 4 | Scene count default 1 max 4 + 2 điều kiện | `registry.ts:1843-1848` | Khớp | **KHỚP** |
| 5 | **Verbatim** ref-video user builder `@图片N` | `ref-video-prompt-generate.ts:37-46` | Khớp **cả** chuỗi mâu thuẫn trong source (`必须…@图片N` / `不能…@图片N` — **bug upstream**, report chép đúng) | **KHỚP** (với source) |
| 6 | Ordered refs chars trước scenes | §0.1 | Pattern trong generate route comments/code | **KHỚP** (cơ chế) |
| 7 | **Verbatim** motion rules A3 | `registry.ts:1628-1693` | Report **rút mạnh** (bỏ rhythm table, quality examples, …) | **LỆCH verbatim** |
| 8 | StoryGen transition JSON duration 4\|6\|8 | `llmService.js:131-156` | Khớp task + normalize | **KHỚP** |
| 9 | StoryGen BASE_IMAGE_STYLE + heroSubject consistency | §3.B | Có trong `llmService.js` / image path | **KHỚP** |
| 10 | Continuity/video QA non-blocking | §3.A | Report claim; pattern “best-effort” phổ biến — không re-verify từng file gate | **KHỚP*** (không adversarial-disprove) |
| 11 | License Apache-2.0 cả hai | §10 | Khớp | **KHỚP** |

#### Lỗi / coverage

1. **A3 / A4 / A5** ghi “rút gọn” / excerpt — không đạt CHÉP ĐỦ cho `REF_VIDEO_PROMPT_MOTION_RULES` đầy đủ + benchmark examples.  
2. **Prompt modules thiếu / chưa chép** trong `src/lib/ai/prompts/`:
   - `script-generate.ts` / slots `script_generate` trong registry (role + visual_style + character + scene sections)
   - `script-parse.ts`, `script-split.ts`, `shot-split` related
   - `character-extract.ts`, `import-character-extract.ts`, `character-image.ts`
   - `keyframe-prompts.ts`, `scene-frame-generate.ts`, `frame-generate.ts` (partial via registry only)
   - `video-generate.ts`, `presets.ts`, `blocks.ts`
3. StoryGen: `guide/VideoGenerationPromptGuide.md` được load vào transition prompt — report mention safety guide nhưng **không chép** nội dung guide (có thể dài; nên cite + extract rules chính).

#### License: **OK**

---

### 2.5 REFS_SB_05_Seedance_Orkas.md — **TIN ĐƯỢC**

#### Claims đã đối chiếu

| # | Claim | Cite | Thực tế | Kết quả |
|---|-------|------|---------|---------|
| 1 | Repo = Skill OS, không runtime gen API | §1.1 | Tree skills/references/schemas — đúng định vị | **KHỚP** |
| 2 | **Verbatim** Director Formula slot table | `seedance-prompt/SKILL.md:35-46` | Khớp patterns perfume bottle… | **KHỚP** |
| 3 | **Verbatim** Mode gate table T2V…Extend | `:48-59` | Khớp | **KHỚP** |
| 4 | Clip-contract required fields + status enum | `schemas/clip-contract.schema.json` | Khớp required + status enum | **KHỚP** |
| 5 | Orkas `DeliveryPromiseType` / `SegmentRole` / `VideoReferenceRole` | `edl.ts:26-60` | Khớp | **KHỚP** |
| 6 | stage-consistency: front portrait LOCK, caps ≤3/3/6 | `stage-consistency/SKILL.md` | Khớp § caps + rules | **KHỚP** |
| 7 | OmniCast đã port repair_budget / slop / binding / consistency_check | §3.3 | `implementation/consistency_check.py`, `pipeline/repair_budget.py`, `storyboard/slop.py`, `binding.py` **tồn tại** | **KHỚP** |
| 8 | Soul quote “Direct the model…” gán “root SKILL” | §1.1 | **Soul thật** trong `SKILL.md:15-21` là “feeling leaves with a film…”. Tagline “Direct the model…” nằm **README/hero assets**, không phải section Soul | **SAI attribution** |
| 9 | Authority order 9 tiers | root `SKILL.md:59-71` | Khớp 9 tiers | **KHỚP** |
| 10 | Licenses MIT + MIT | §11 | Khớp | **KHỚP** |
| 11 | R2V role isolation / I2V preserve patterns | §4.x | Files cited exist; samples khớp hướng | **KHỚP** |
| 12 | § numbering vs COMMON | — | §9=brief Q, §10=đề xuất, §11=license | **LỆCH form** (nội dung đủ) |

#### Lỗi cụ thể

1. **Mis-cite Soul** — không bịa rule craft, nhưng gán sai “verbatim root Soul”.  
2. Một số bảng anti-slop / filter / interview có thể compress từ nhiều file — không phát hiện bịa số liệu khi spot-check.

#### Coverage

- Mục 4 seedance: **rất dày** (đúng trọng tâm repo).  
- Orkas: EDL + stage-consistency + craft skills covered; composition-design / design-system-importer / frontend-design skills **ít** (thứ yếu cho storyboard).

#### License: **OK**

---

### 2.6 REFS_SB_06_ShortVideoEngines.md — **TIN CÓ ĐIỀU KIỆN**

#### Claims đã đối chiếu

| # | Claim | Cite | Thực tế | Kết quả |
|---|-------|------|---------|---------|
| 1 | Pixelle `StoryboardFrame` + `is_completed` = all `video_segment_path` | `storyboard.py:58-122` | Khớp | **KHỚP** |
| 2 | `IMAGE_STYLE_PRESETS` stick/minimal/concept | `image_generation.py:26-44` | Khớp descriptions | **KHỚP** |
| 3 | **Verbatim** `IMAGE_PROMPT_GENERATION_PROMPT` structure | §4.1.3 | Core sentences khớp; report **rút** vocab/coordination/reminders | **LỆCH** (không đủ full) |
| 4 | **Verbatim** topic narration structure | §4.1.1 | Rút mạnh so `topic_narration.py:20+` (citation lists, language rules dài) | **LỆCH** |
| 5 | **Verbatim** MPT `DEFAULT_SCRIPT_SYSTEM_PROMPT` | `llm.py:23-38` | Khớp **từng chữ** (kể cả typo *Constrains*) | **KHỚP** |
| 6 | MPT Initialization append + custom override limits | `llm.py:613-626`, max 2000/8000 | Khớp | **KHỚP** |
| 7 | Không character consistency 3 repo | §3 | Đúng định vị B-roll/short auto | **KHỚP** |
| 8 | SVF `autoBatch` + `RenderStatus` enum | `store/app.ts` | Có `autoBatch`, `RenderStatus.GenerateText`… | **KHỚP** |
| 9 | Licenses Apache / MIT / AGPL | header | Khớp 3 `LICENSE` | **KHỚP** |
| 10 | MPT match_script_order search terms | §4.2.2 | Có nhánh ordered trong `llm.py` | **KHỚP** (cơ chế) |
| 11 | Pixelle linear pipeline steps | `standard.py` | Map đúng high-level | **KHỚP** |

#### Lỗi

1. Pixelle mục 4: nhiều block “VERBATIM” thực chất **outline có `…`** — không copy full `TOPIC_NARRATION_PROMPT` / `IMAGE_PROMPT_GENERATION_PROMPT`.  
2. short-video-factory: prompts LLM (nếu có) **mỏng** so 2 repo kia — report thừa nhận schema không domain; OK nhưng coverage prompt SVF thấp (có thể đúng vì ít template).

#### License: **OK** (AGPL SVF cảnh báo đúng)

---

### 2.7 REFS_SB_07_hyperframes.md — **TIN ĐƯỢC**

#### Claims đã đối chiếu

| # | Claim | Cite | Thực tế | Kết quả |
|---|-------|------|---------|---------|
| 1 | Root `DESIGN.md` = brand Mintlify docs, không agent API | §0 | `DESIGN.md` mở đầu “Design System & Style Guide” / Mintlify | **KHỚP** (insight tốt) |
| 2 | TimelineElementBase/Media/Text/Composition fields | `core.types.ts:206-262` | Khớp | **KHỚP** |
| 3 | Composition variable types string\|number\|color\|boolean\|enum | `:265+` | Khớp | **KHỚP** |
| 4 | **Verbatim** Approach / Layout Before Animation / Timeline Contract | skills `hyperframes/SKILL.md` | Headers tồn tại L10/L64/L287; nội dung skill-aligned | **KHỚP*** (spot-check structure) |
| 5 | **“15 caption components”** | §0 / phụ lục | `registry/components/caption-*` = **16** dirs | **SAI số** |
| 6 | Pipeline artifacts STORYBOARD.md → HTML → lint/validate → render | pipeline.mdx | Định vị đúng cho agent pipeline | **KHỚP** |
| 7 | Không cast/ref AI character | §3 | Repo HTML deterministic — đúng | **KHỚP** |
| 8 | License Apache-2.0, dependency OK | §10 | Khớp | **KHỚP** |
| 9 | Relative timing `data-start="intro + 2"` | docs concepts | Pattern documented | **KHỚP** |
| 10 | PSNR golden / Docker regression | producer harness claims | Có trong module map producer; không re-read full harness | **KHỚP*** |

#### Lỗi

1. **Caption count 15 → 16** (`caption-blend-difference` … `caption-weight-shift`).  
2. Skill references (palettes ×9, transitions catalog, css-patterns) **hầu như không chép** — chấp nhận được nếu scope = contract/agent API, nhưng round 2 có thể index transitions nếu OmniCast học motion overlay.

#### License: **OK**

---

## 3. Danh sách lỗi cụ thể (gom, ưu tiên fix)

### 3.1 Sai factual / bịa (phải sửa nếu reuse report)

| ID | Report | Claim | Thực tế | File:line code |
|----|--------|-------|---------|----------------|
| E1 | **02** | Shot `status` chỉ `pending\|ready` | Thêm **`generating`** | `_refs/Jellyfish/backend/app/models/types.py:34-39` |
| E2 | **05** | Soul verbatim root = “Direct the model…” | Soul = feeling→film principles; tagline ở README/hero | `_refs/seedance-2.0/SKILL.md:15-21` vs `README.md` |
| E3 | **07** | 15 caption components | **16** `caption-*` | `_refs/hyperframes/registry/components/` |
| E4 | **02** | ShotDetail “131-218” như đủ fields quan trọng | Thiếu ≥5 field trong class | `studio_shots.py:174-208` |

### 3.2 Verbatim không đạt CHÉP ĐỦ (không hẳn bịa, nhưng fail brief mục 4)

| ID | Report | Khối | Vấn đề |
|----|--------|------|--------|
| V1 | **03** | §4.1–4.9 hầu hết | Paraphrase + `…`; không full `.txt` |
| V2 | **03** | `single_panel_image` “FULL” | Vẫn có ellipsis |
| V3 | **01** | §4.4 narration step2 skeleton | Khung, không full `build_narration_prompt` |
| V4 | **04** | A3 motion rules, A4 keyframe | Rút gọn so registry full |
| V5 | **06** | Pixelle topic/image prompts | Outline thay vì full string |
| V6 | **02** | character extract LMD | Thiếu `**` bold / cắt tail |
| V7 | **02** | ElementExtractor + frame agents | “rút lõi” có chủ đích — ghi rõ NON-VERBATIM |

### 3.3 Suy diễn / overclaim (nhẹ)

| ID | Report | Ghi chú |
|----|--------|---------|
| S1 | **04** | User builder `@图片N` self-contradiction: **source bug**, không phải report bịa — nên footnote “upstream typo/unicode” |
| S2 | **01/05/07** | So sánh “OmniCast mạnh/yếu hơn” là judgment — chấp nhận nếu schema/mechanism base đúng |

---

## 4. Prompt / file quan trọng BỎ SÓT (round 2)

### 4.1 waoowaoo (03) — ưu tiên cao

Chưa mention hoặc chưa chép (từ `lib/prompts/`):

| File / nhóm | Vì sao quan trọng |
|-------------|-------------------|
| `agent_character_profile.zh.txt` / `agent_character_visual.zh.txt` | Profile vs visual split — map cast registry |
| `agent_shot_variant_analysis/generate.zh.txt` | Variant / re-roll path |
| `agent_storyboard_insert.zh.txt` | Insert panel mid-edit |
| `episode_split.zh.txt` | Episode boundary |
| `ai_story_expand.zh.txt` | Novel expand |
| `character_modify/regenerate/description_update` (+ location/prop counterparts) | Asset edit loops |
| `storyboard_edit.zh.txt` | Human edit path |
| `select_location/select_prop.zh.txt` | Asset binding |
| `character_image_to_description` | Reverse: image→text |
| `image_prompt_modify.zh.txt` | Repair stills |

**Round 2:** chép **full zh** (en optional) cho pipeline core: clip → plan → cine → acting → detail → single_panel → character/location create → sheet.

### 4.2 AIComicBuilder (04)

| File | Vì sao |
|------|--------|
| `registry.ts` slots `script_generate` / `script_parse` / `script_split` full | Script path trước storyboard |
| `character-extract.ts`, `import-character-extract.ts` | Cast extract |
| `character-image.ts` / character 4-view full (không chỉ excerpt) | Refsheet |
| `keyframe-prompts.ts`, `frame-generate.ts`, `scene-frame-generate.ts` | Keyframe mode |
| `video-generate.ts` | Provider-facing video prompt assembly |
| `presets.ts`, `blocks.ts` | Style/slots reuse |
| StoryGen `guide/VideoGenerationPromptGuide.md` | Safety rules inject transition |

### 4.3 Jellyfish / LocalMiniDrama (02)

| File | Vì sao |
|------|--------|
| `element_extractor_agent.py` **full** system | Hard name dictionary — core consistency |
| `entity_merger_agent.py`, `variant_analyzer_agent.py` | Alias / costume timeline |
| `shot_frame_prompt_agents.py` full template (không chỉ rút) | Base vs 图N |
| LocalMiniDrama `getStoryboardSystemPrompt` **full zh+en** | Pacing 5–15s, dynamic camera ≥80% |
| `universalSegmentPromptBundle.js` full | `@图片N` omni video |
| `getRolePolishPrompt` full industrial sheet | Identity sheet |

### 4.4 ArcReel (01) — bổ sung partial

| File | Vì sao |
|------|--------|
| Full `build_narration_prompt` / drama visual builders | Step2 production prompts |
| Full grid `prompt_builder.py` | First-last chain |
| Full `prompt_builders_ad.py` tier tables | Ad funnel |
| `prompt_builders_reference.py` step1+2 full | R2V |

### 4.5 seedance / Orkas (05) — ổn; optional

| File | Vì sao |
|------|--------|
| Full `anti-slop-lexicon.md`, `prompt-compiler.md` | Nếu OmniCast port compiler |
| Orkas `stage-compose` / `stage-edit` skill bodies | WS4 EDL |

### 4.6 Short engines (06)

| File | Vì sao |
|------|--------|
| Full `topic_narration.py`, `content_narration.py`, `image_generation.py`, `video_generation.py` strings | Đúng nghĩa verbatim |
| MPT full search-terms + social metadata prompts (`llm.py` lower sections) | Metadata path |
| SVF: grep mọi template string trong `src/` nếu có | Xác nhận “không prompt domain” |

### 4.7 hyperframes (07) — optional

| Path | Vì sao |
|------|--------|
| `skills/hyperframes/references/transitions/*` | Overlay transition catalog |
| `skills/hyperframes/palettes/*` | Brand kits |
| Caption component README/source of each of **16** | Overlay lane |

---

## 5. Coverage checklist 10 mục COMMON_CONTEXT

| Mục | 01 | 02 | 03 | 04 | 05 | 06 | 07 |
|-----|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 Kiến trúc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2 Data model | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 3 Consistency | ✓ | ✓ | ✓ | ✓ | ✓ | ✓* | ✓* |
| 4 Prompt verbatim **đủ** | ~ | ~ | **✗** | ~ | ✓ | ~ | ✓** |
| 5 QA/retry | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 6 Video-gen | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓*** |
| 7 Pacing | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 8 Chi tiết nhỏ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 9 Đề xuất OmniCast | ✓ | ✓ | ✓ | ✓ | ✓**** | ✓ | ✓ |
| 10 Anti + LICENSE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

\* 06/07: “không có cast consistency” — đúng, mục vẫn có.  
\** 07 prompts = skill authoring, không LLM drama — phù hợp repo.  
\*** 07 video = HTML capture, không i2v AI.  
\**** 05 đề xuất ở §10 (số lệch).

---

## 6. LICENSE — xác nhận chéo

| Repo | Report ghi | LICENSE file | Match? |
|------|------------|--------------|:------:|
| ArcReel | AGPL-3.0 | AGPL-3.0 | ✓ |
| Jellyfish | Apache-2.0 | Apache-2.0 | ✓ |
| LocalMiniDrama | MIT (© 2026 xuanyustudio) | MIT | ✓ |
| waoowaoo | CC BY-NC-SA 4.0 | CC BY-NC-SA 4.0 | ✓ |
| AIComicBuilder | Apache-2.0 | Apache-2.0 | ✓ |
| StoryGen-Atelier | Apache-2.0 | Apache-2.0 | ✓ |
| seedance-2.0 | MIT | MIT | ✓ |
| Orkas-VideoStudio | MIT | MIT | ✓ |
| Pixelle-Video | Apache-2.0 | Apache-2.0 | ✓ |
| MoneyPrinterTurbo | MIT | MIT | ✓ |
| short-video-factory | AGPL-3.0 | AGPL-3.0 | ✓ |
| hyperframes | Apache-2.0 | Apache-2.0 | ✓ |

**Không license sai.** Cảnh báo AGPL (01, 06-SVF) và NC (03) **đúng hướng**.

---

## 7. Kết luận điều hành (cho round 2 / OmniCast consumers)

1. **Được tin để map kiến trúc & license:** 01, 05, 07 (ưu tiên đọc trước).  
2. **Được tin có điều kiện (vá enum + bổ sung prompt full):** 02, 04, 06.  
3. **Cơ chế OK nhưng mục 4 prompt phải làm lại theo nghĩa CHÉP ĐỦ:** **03**.  
4. **Không** cần scrap toàn bộ 7 report — patch list §3–§4 đủ cho research round 2.  
5. Khi port pattern vào OmniCast: **ưu tiên code cite trong report đã verify KHỚP**; **không** copy AGPL/NC strings; re-implement Apache/MIT patterns với attribution.

---

## 8. Đã kiểm (verifier)

- `_refs/*/LICENSE` (12 repo)  
- ArcReel: `script_models.py`, `prompt_builders.py`, `prompt_builders_script.py`, `prompt_utils.py`, `storyboard_sequence.py`, `retry.py`, `asset_types.py`, `project_manager.py`  
- Jellyfish: `types.py`, `studio_shots.py`, `script_divider_agent.py`, `consistency_checker_agent.py`  
- LocalMiniDrama: `promptI18n.js` (extract + identity anchors), migrate identity fields  
- waoowaoo: `constants.ts`, `image-task-handler-shared.ts`, `agent_clip.zh.txt`, atomic-retry, prompt file inventory  
- AIComicBuilder: `schema.ts`, `registry.ts` (ref image + ref video), `ref-video-prompt-generate.ts`  
- StoryGen: `llmService.js` transition  
- seedance: `skills/seedance-prompt/SKILL.md`, `schemas/clip-contract.schema.json`, root `SKILL.md` Soul  
- Orkas: `edl.ts`, `stage-consistency/SKILL.md`  
- Pixelle: `storyboard.py`, `image_generation.py`, `topic_narration.py`  
- MPT: `llm.py` DEFAULT_SCRIPT  
- SVF: `store/app.ts`  
- hyperframes: `core.types.ts`, `DESIGN.md`, caption component dirs, skill headers  
- OmniCast: `implementation/consistency_check.py`, `repair_budget.py`, `storyboard/{slop,binding}.py`
