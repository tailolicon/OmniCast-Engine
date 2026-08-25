# GAP Audit 1 — Core (ArcReel + AIComic/StoryGen + seedance/Orkas)

> STATUS: ACTIVE (2026-08-02)  
> Vai trò: Kiểm toán viên áp dụng  
> Nguồn research: `REFS_SB_01_ArcReel.md`, `REFS_SB_04_AIComicBuilder_StoryGen.md`, `REFS_SB_05_Seedance_Orkas.md` (gồm §8, §9/§10, ROUND 2)  
> Đối chiếu code: `implementation/src/omnicast/storyboard/*`, `media/veo_pipeline.py`, `media/providers/video_gemini.py`, `media/providers/flow_*.py`, `pipeline/edl.py`, `scripts/demo_anim_short.py`  
> Đối chiếu demo: `implementation/output/products/anim_demo/miko_lantern_ep1/DEMO_STATE.md` + artifact thực tế  
> **Chỉ file này được ghi.** Không sửa code / `_refs`.

---

## 0. Chẩn đoán gốc (demo Miko fail “cắt nhảy thế giới”)

| Quan sát | Bằng chứng |
|----------|------------|
| Pipeline **đúng** (first/last, motion-only, beats_reserved, plan.json) **đã viết** trong `demo_anim_short.py` + `clips.py` + `edl.py` | `plan.json` prompt FLF + “Do not yet show: the lantern lights up” |
| Pipeline **không chạy video có trả phí** | `plan.json` mọi `produced_path: ""`; **không có** thư mục `frames/` hay `clips/` |
| Sản xuất thực tế = **Flow UI thủ công** mode **Thành phần (Ingredients / components R2V)** | `DEMO_STATE.md` L35–37, L40–48, L52–64; `incoming/s*_c0.mp4` |
| Fail s2: model **bịa lại bối cảnh** (đèn bàn/kéo/giấy thay xưởng + cửa sổ tròn) | `DEMO_STATE.md` L56–61 |
| Nguyên nhân kỹ thuật khớp research | Components-mode = R2V multi-chip **không** khóa first-frame pixel; thiếu scene chip / anchors = model vẽ world mới mỗi cut (AIComic §0.1 + seedance R2V role isolation + StoryGen FLF) |
| Tail-carry (Khung hình / i2v) **có** được học sau đó cho s3b/s5 | `DEMO_STATE.md` L30–37, L78–84 — **một phần** seedance chain, làm tay ngoài code path |

**Kết luận một câu:** Nghiên cứu đúng; code package storyboard/clips/edl **đã port nhiều cơ chế**; demo **đi tắt** qua Flow components + prompt tay → đúng anti-pattern “R2V không role/scene plate + re-describe identity/bg” → cắt nhảy thế giới.

---

## 1. Bảng audit đầy đủ

Chú thích trạng thái:

| Mã | Nghĩa |
|----|--------|
| **ĐÚNG** | Có trong code, khớp khuyến nghị, và (nếu liên quan) demo đã dùng hoặc sẵn dùng |
| **MỘT PHẦN** | Có mảnh / có schema / có comment — thiếu wire, thiếu enforce, hoặc demo bypass |
| **BỎ QUA** | Research ghi rõ cần; code không có hoặc không gọi |
| **VI PHẠM** | Làm **ngược** khuyến nghị (demo hoặc code path chính) |

Severity = tác động tới mục tiêu *“phim liền mạch chạy tốt như repo tham chiếu”*: **CAO / TRUNG / THẤP**.

---

### 1.A — REFS_SB_01 ArcReel

#### A. §9 Đề xuất OmniCast (16 mục)

| # | Khuyến nghị (cơ chế) | Nguồn | Trạng thái | Bằng chứng file:line | Sev | Việc phải làm |
|---|----------------------|-------|------------|----------------------|-----|---------------|
| A9.1 | Two-step content/visual; `novel_text`/VO không re-LLM khi viết visual | §9#1, §2.3–2.4, R2 | **MỘT PHẦN** | Demo hand-author VO+visual tách (`demo_anim_short.py:97–178`); Writer/extract production **không** two-step merge fail-loud kiểu ArcReel | TRUNG | Writer pipeline: step1 lock voiceover → step2 image/video prompt by shot_id; fail on orphan |
| A9.2 | Structured `ImagePrompt`/`VideoPrompt` → YAML (scene/composition/action/camera/audio) | §9#2, §2.2, §4.2 | **BỎ QUA** | Prompt = free string (`frames.py:199–207`, `clips.py:196–226`); không YAML schema | CAO | Pydantic Image/Video prompt → render YAML cho provider |
| A9.3 | Scene/action writing guides + examples SSOT | §9#3, §4.3–4.4 | **MỘT PHẦN** | `frames._SYSTEM` + `clips` i2v rules; **không** pack writing-guide/examples như ArcReel | TRUNG | Prompt pack SSOT (photographer vs motion-designer roles) |
| A9.4 | Previous-storyboard ref + “composition only” (không identity) | §9#4, §3.2 L224–230 | **BỎ QUA** | `frames.py` chỉ text “Previous shot … Ended:” (`frames.py:377–380`); **không** attach ảnh prev frame làm ref composition | CAO | Khi gen frame shot N: attach last frame shot N−1 với role composition-only / ignore identity |
| A9.5 | Character 4-view sheet layout 16:9 (bust + 3 A-pose) | §9#5, §3.3 | **MỘT PHẦN** | `refsheet.py:48–54` = 3 view rời (front/3q/full), **không** multi-panel 4-ô layout ArcReel | THẤP | Optional layout constants; giữ view1-anchor đã có |
| A9.6 | `@name → [图N]` order = attachment — **giữ OmniCast `[IMAGE n]`** | §9#6, §3.4 | **ĐÚNG** | `binding.py:46–52`, `99–123`, `compose_rendered_prompt` | — | Giữ; harden video path cùng token |
| A9.7 | Ship **RefRole** vào Veo/Flow (ArcReel thiếu; OmniCast advantage) | §9#7 | **MỘT PHẦN / VI PHẠM demo** | Binding+ROLE_IGNORES: `models.py:59–84`, `binding.py:264–282` — **chỉ image frames**. Video clip prompt trong `clips.py`/`veo_pipeline` **không** gắn `[IMAGE n]`/ingredients roles. Demo Flow components **không** dùng RefRole | **CAO** | Video call: ordered refs + role clauses; Flow Ingredients ≤14 map roles; **cấm** demo R2V không scene lock |
| A9.8 | Generation queue + resume by `provider_job_id` | §9#8, §5.4 | **BỎ QUA** | Không worker queue storyboard/video; demo bridge/manual | TRUNG | Task queue + orphan/resume (không double-bill) |
| A9.9 | Provider Protocol + CapacityTable (slots image/video) | §9#9, §6.2–6.4 | **MỘT PHẦN** | `IVideoProvider`/`IImageProvider` interfaces; **không** capacity slots/registry ArcReel | TRUNG | Capacity table per provider×media |
| A9.10 | Negative as **text tail** (cross-backend) | §9#10, §4.2 | **ĐÚNG** | `veo_pipeline.NEGATIVE_TAIL` L42–44, `build_motion_prompt` L74–85; board `negative_prompt` frames | THẤP | Unify tail trên mọi video provider |
| A9.11 | Product fidelity sheet+original stack | §9#11, §3.2 product | **BỎ QUA** | Entity kinds không `product` | THẤP | Future product mode |
| A9.12 | Grid first-last chain | §9#12, §6.1 | **BỎ QUA** | Không grid module | THẤP | Optional sau FLF intra-shot ổn |
| A9.13 | Duration × speech_rate lower bound | §9#13, §7 | **MỘT PHẦN** | `animatic.shot_seconds` ưu tiên audio; video chain `ceil(duration/6)` không so VO length | TRUNG | Gate: clip gen ≥ VO seconds / speech estimate |
| A9.14 | Episode pacing ~4s hook | §9#14, §4.7 | **MỘT PHẦN** | Demo s1=6s hook; không rule pack writer | THẤP | Writer pacing rules YouTube Shorts |
| A9.15 | **Connect storyboard → render** (WS1) | §9#15 Critical | **BỎ QUA / VI PHẠM demo** | `render_real_video.py` storyboard = LLM cells cũ (grep L3020+), **không** import `omnicast.storyboard.clips`. Demo video **ngoài** `stage_video` | **CAO** | Wire `storyboard` → `render_shot_chain` / veo; demo **chỉ** `--go` path |
| A9.16 | Wire Flow Ingredients ≤14 | §9#16 | **MỘT PHẦN** | `flow_browser` attach ingredients L391–447; `convert()` **ignores** `image_path` L1007–1015; `FLOW_ACCEPTS_IMAGE=False` `veo_pipeline.py:40`; `flow_api` endpoints declared **uncalibrated** L27–35 | **CAO** | Calibrate start/end/reference RPCs; flip `FLOW_ACCEPTS_IMAGE`; map RefRole→ingredients |

#### A. §8 Chi tiết nhỏ (14 mục)

| # | Chi tiết | Nguồn | Trạng thái | Bằng chứng | Sev | Việc |
|---|----------|-------|------------|------------|-----|------|
| A8.1 | Prompt SSOT WebUI+Agent cùng builders | §8.1 | **BỎ QUA** | Prompts rải `frames`/`clips`/`extract`/`writer` | TRUNG | Single prompt pack |
| A8.2 | `extra="forbid"` nested schema | §8.2 | **BỎ QUA** | `OmnicastSchema` frozen only (`models/schemas.py:28`); storyboard Draft không forbid | THẤP | Forbid on LLM draft models |
| A8.3 | SkipJsonSchema ẩn runtime fields | §8.3 | **MỘT PHẦN** | Tách `schemas.py` draft vs `models.py` store (L1–8) — pattern đúng, không SkipJsonSchema | THẤP | Giữ separation |
| A8.4 | VersionManager regenerate/rollback | §8.4 | **MỘT PHẦN** | `_carry_render` giữ path nếu prompt unchanged (`frames.py:128–150`); **không** version history rows | TRUNG | Asset version table or paths |
| A8.5 | Cost snapshot frozen at success | §8.5 | **BỎ QUA** | `billable_generations` plan-time only (`edl.py:163–165`); demo credit note informal | THẤP | Freeze cost per clip on produce |
| A8.6 | path_safety / try_safe_join | §8.6 | **BỎ QUA** | Paths absolute trong plan.json demo | TRUNG | Safe join product dir |
| A8.7 | Reference label = asset name | §8.7 | **ĐÚNG** | `binding.reference_table` name+token | — | — |
| A8.8 | Image edit forks image not prompt | §8.8 | **BỎ QUA** | Không image_edit path storyboard | THẤP | Optional |
| A8.9 | Active multi-key credential switch | §8.9 | **BỎ QUA** | Single settings API key | THẤP | Ops later |
| A8.10 | Agent sandbox orchestration | §8.10 | **BỎ QUA** | N/A OmniCast scope | THẤP | — |
| A8.11 | import-linter layers | §8.11 | **BỎ QUA** | Không | THẤP | — |
| A8.12 | SSE tasks + asset fingerprints | §8.12 | **MỘT PHẦN** | FastAPI events job; không fingerprint asset UI như ArcReel | THẤP | Dashboard later |
| A8.13 | Tag neutralize `</segments>` injection | §8.13 | **BỎ QUA** | Không neutralize tags trong prompts | THẤP | Sanitize LLM fields |
| A8.14 | Product ref: sheet first, photos last | §8.14 | **BỎ QUA** | No product type | THẤP | — |

#### A. §10 Anti-pattern (compliance)

| # | Anti-pattern (KHÔNG học / tránh) | Trạng thái OmniCast | Bằng chứng | Sev |
|---|----------------------------------|---------------------|------------|-----|
| A10.1 | Copy AGPL code | **ĐÚNG** (tránh) | Re-implement concept only | — |
| A10.2 | Weak ref binding (label only, no ignore) | **ĐÚNG** image; video yếu | binding vs clips | CAO video |
| A10.3 | Missing sheet → skip silently | **MỘT PHẦN** | `build_mappings` dropped[] + notes; demo Flow chip missing workshop early | CAO demo |
| A10.4 | No pixel QA | **MỘT PHẦN** | `consistency_check.py` DNA stills; video pixel gate không | TRUNG |
| A10.5–10 | Worker/single-process, enum soft-default, … | N/A / partial | — | THẤP |

#### A. §3–7 cơ chế quan trọng ngoài bảng §9

| Cơ chế | Nguồn | Trạng thái | Bằng chứng | Sev | Việc |
|--------|-------|------------|------------|-----|------|
| Design sheet trước i2v | §3.1 | **MỘT PHẦN** | `refsheet` + pipeline CAST_PENDING; demo **0 file** trong `_storyboard/sb_demo_miko_lantern` | **CAO** | Chạy `stage_sheets` trước mọi gen video |
| Storyboard i2i + sheets | §3.1–3.2 | **MỘT PHẦN** | `generate_frame_image` + refs; demo **không** có `frames/` | **CAO** | `--go` frames trước Flow/Veo |
| i2v start=storyboard | §6.1 | **MỘT PHẦN code / VI PHẠM demo** | `clips.render_shot_chain` + Gemini; demo components không seed first frame | **CAO** | Default gen mode = I2V/FLF, không bare R2V |
| segment_break breaks prev-frame chain | §3.2 | **BỎ QUA** | Không field segment_break; chain depth only | TRUNG | Scene-cut flag |
| Enum camera soft-default OOV | §2.1 | **MỘT PHẦN** | Closed enums + coerce aliases `schemas.py`; không soft Medium Shot default | THẤP | — |
| No silent multi-provider fallback | §6.3 | **MỘT PHẦN** | `veo_pipeline` demote sticky nhưng **có** Flow→Gemini fallback intentional | TRUNG | Document as policy |
| CapCut / compose export | §7 | **BỎ QUA** | FFmpeg only | THẤP | — |
| Voice_Profiles native audio | §6.5 | **MỘT PHẦN** | Demo dùng native AAC Flow; TTS plan separate | THẤP | Dual path policy |

---

### 1.B — REFS_SB_04 AIComicBuilder + StoryGen-Atelier

#### B. §0 + §9 Đề xuất (14 + ưu tiên)

| # | Khuyến nghị | Nguồn | Trạng thái | Bằng chứng | Sev | Việc |
|---|-------------|-------|------------|------------|-----|------|
| B0.1 | Hai mode: **keyframe** (first+last) vs **reference** (multi-ref R2V) | §0.1 | **MỘT PHẦN** | `clips` FLF/i2v; **không** generationMode enum hay shot_assets dual mode | CAO | Explicit mode per shot; default FLF when stills exist |
| B0.2 | Scene ref = **pure environment, 0 people**; char inject **lúc video** | §0.1, §9#1, §9#6, A1 prompt | **MỘT PHẦN** | Location sheet “no people” `refsheet.py:68–72`; ENVIRONMENT ignore person `models.py:81`. Frame gen shot **vẫn** vẽ người+địa điểm cùng lúc với char refs — **không** phase “scene plate only” rồi video | **CAO** | Path gen location plate (0 human) → video attach char+scene ordered |
| B0.3 | Ordered refs: **chars trước, scenes sau** | §0.1 L40–46 | **MỘT PHẦN** | `binding` cast first then location (`binding.py:116–123`) — khớp; **không** wire video provider multi-ref | CAO | Video package same order |
| B0.4 | `@图片N（名）` prose embed (Seedance); map `[IMAGE n]` | §0.1, §9#3 | **BỎ QUA** Seedance | Không `seedance.py`; Gemini image dùng `[IMAGE n]` table | TRUNG | Adapter nếu bật Seedance |
| B0.5 | Seedance multi-ref API (1–9 `reference_image`) | §0.3, §9#3 | **BỎ QUA** | Không provider | TRUNG | Optional roadmap |
| B0.6 | **Interpolation Chain** inter-shot (S1→S2→S3) + Gemini transition prompt | §0.4, §9#2 **Rất cao** | **MỘT PHẦN** | **Intra-shot** first→last trong `clips.py:180–206`, `video_gemini` last_frame L115–118. **Không** sliding window giữa shot consecutive như StoryGen. Demo s3b/s5 = manual tail→Khung hình | **CAO** | Inter-shot optional + keep intra-shot; auto tail extract between cuts when intentional_next_shot |
| B0.7 | Veo `image` + `lastFrame` + duration ∈{4,6,8} | §0.4 | **ĐÚNG** (API path) | `video_gemini.py:30,85–118,193–196` | — | Dùng path này cho demo, không components bare |
| B0.8 | Per-shot 1–4 scene frames khi đổi địa điểm/ánh sáng | §0.1, §9#4 | **BỎ QUA** | Một `location_id` / shot | TRUNG | Multi environment refs on beat jump |
| B0.9 | `characters[]` on asset → subset cast (không dump all / first-3) | §0.2, §9#5, anti-pattern | **ĐÚNG** | `build_mappings` từ `shot.cast`; anti first-3 | — | Giữ; cấm fallback first-N |
| B0.10 | Duration micro-beats 2–3s trong video prompt | §9#7, §7 AIComic | **ĐÚNG** | `clips.py:186–191` “two to three seconds” | — | — |
| B0.11 | Subtitle safe zone bottom 20% | §8.7, §9#8 | **MỘT PHẦN** | Stills: top/bottom **fifths** `frames.py:153–159`; **video** prompt không safe-zone 20% | TRUNG | Append video suffix for Shorts |
| B0.12 | Fail-closed continuity (đừng học soft QA AIComic) | §9#9, §10 | **ĐÚNG** module / **VI PHẠM demo** | `continuity.py` blocked; demo Flow **không** chạy gate trước gen | CAO | Bắt buộc `check_continuity` trước bill |
| B0.13 | Character 4-view + **name label on canvas** | §9#10, §8.4 | **BỎ QUA** name-on-image | refsheet không in tên lên pixel | THẤP | Optional label burn for Flow |
| B0.14 | Style presets library | §0.5, §9#11 | **MỘT PHẦN** | Channel style string; không 15-preset UI | THẤP | Preset list |
| B0.15 | Closing hold clip (last frame only) | §9#12, StoryGen | **BỎ QUA** | Không closing clip pattern | THẤP | Optional coda |
| B0.16 | Prompt slot 3-level override | §9#13 | **BỎ QUA** | Hardcoded system prompts | THẤP | Later |
| B0.17 | `generate_audio` + quoted dialogue Seedance | §9#14 | **BỎ QUA** / N/A Veo | Veo native audio possible; dual path not formalized | THẤP | Policy |
| B0.18 | Costume overrides per shot | §3.A | **MỘT PHẦN** | EntityKind.COSTUME + WARDROBE role; demo không dùng | THẤP | Wire costume cast |
| B0.19 | Height list multi-char | §3.A | **BỎ QUA** | Không | THẤP | When multi-char |
| B0.20 | Staleness flags script hash | §3.A | **MỘT PHẦN** | `script_hash` resume board; no per-shot isStale | TRUNG | Invalidate frames on script change |
| B0.21 | Color palette mandatory suffix | §3.A | **MỘT PHẦN** | style_prompt board-level | THẤP | Explicit palette field |
| B0.22 | heroSubject only shot 1 (StoryGen) | §8.9, §3.B | **ĐÚNG** (via sheets) | Identity from refs not re-prose; i2v motion-only | — | — |
| B0.23 | ffmpeg concat `-c copy` | §0.4, §8.8 | **MỘT PHẦN** | Demo planned concat; `ep1_draft.mp4` exists; code assemble path partial | TRUNG | Assemble from plan.produced_path |
| B0.24 | Parallel clips + per-clip retry (đừng Promise.all fail-all) | §5 StoryGen anti | **MỘT PHẦN** | `render_shot_chain` continues on fail clip; serial | TRUNG | Resume pending segments |

#### B. §8 Chi tiết nhỏ còn lại

| # | Chi tiết | Trạng thái | Bằng chứng | Sev | Việc |
|---|----------|------------|------------|-----|------|
| B8.1 | shot_assets versioning is_active | **BỎ QUA** | Frame path overwrite | TRUNG | Version paths |
| B8.2 | sceneName meta label | **MỘT PHẦN** | Entity.name location | THẤP | — |
| B8.3 | Seedance doctrine: motion not looks | **ĐÚNG** code / **VI PHẠM** demo prompt s1v2 vẫn re-describe lantern/bg dài | `clips.py:172–178` vs `DEMO_STATE.md` L66–74 | **CAO** | Demo/production: I2V seed + motion-only |
| B8.4 | isCharacterOnScreen → voiceover not lip-sync | **BỎ QUA** | Không | THẤP | Drama path |
| B8.5 | Forbidden real celebrity names image API | **BỎ QUA** | Compliance separate | TRUNG | Gate image prompts |
| B8.6 | Episode continue last→first | **BỎ QUA** | Không | THẤP | Series |
| B8.7 | UCloud vs Ark envelope | N/A | — | — | — |

#### B. §10 Anti-pattern

| Anti-pattern | Trạng thái | Ghi chú |
|--------------|------------|---------|
| Soft-pass continuity/quality | **ĐÚNG tránh** trong module; demo manual review soft | Giữ fail-closed |
| Fallback first 3 chars | **ĐÚNG tránh** | binding cast-only |
| God-file generate route | **ĐÚNG tránh** | modules nhỏ |
| Placeholder image on fail | **ĐÚNG tránh** | fail notes |
| Promise.all all-or-nothing | **ĐÚNG tránh** partial | clips continue |
| Single hero only | **ĐÚNG tránh** | multi entity |
| Hard 4/6/8 only | **ĐÚNG cho Veo** | clamp ok |
| Double initialImage in referenceImages | N/A | verify on Seedance port |
| Soft “Cinematic transition” fallback | **ĐÚNG tránh** | no generic transition soft |

#### B. ROUND 2 prompt inventory (áp dụng)

ROUND 2 chép FULL registry/prompt files — **không port nguyên văn** (đúng). Cơ chế cần port đã map ở trên. **Không** thiếu “vì dài”: các rule vận hành (scene 0 people, @引用 order, micro-beat, safe zone, FLF) đã audit từng dòng §0/§4/§8/§9.

---

### 1.C — REFS_SB_05 seedance-2.0 + Orkas-VideoStudio

#### C. §10 Đề xuất (18 mục)

| # | Khuyến nghị | Nguồn | Trạng thái | Bằng chứng | Sev | Việc |
|---|-------------|-------|------------|------------|-----|------|
| C10.1 | Director formula + prompt_compiler clip-contract → NL | §10#1, §4.1, §4.22, §9.2A | **MỘT PHẦN** | `build_clip_prompt` ≈ I2V/FLF template; **không** `prompt_compiler.py`, không clip-contract schema (narrative_job/felt_intent/…) | **CAO** | Compiler module + contract fields on Shot/ClipPlan |
| C10.2 | I2V motion-only + Hold/React | §10#2, §4.2–4.4 | **ĐÚNG** code | `clips.py:123–131,185–194`; `veo_pipeline.build_motion_prompt` | — | **Enforce** mọi path kể Flow demo |
| C10.3 | Role isolation preserve/may_change prose | §10#3, §3.1 | **MỘT PHẦN** | binding image; video thiếu | **CAO** | Video role sentences |
| C10.4 | Anti-slop 6 classes + opening | §10#4, §4.17 | **ĐÚNG** | `slop.py` EMPTY/BORROWED/TAG_SALAD/NEGATION/STACK/FEEL; opening_span | TRUNG | Wire fail-closed pre-video (hiện notes on frames) |
| C10.5 | completed/reserved beat exclusions | §10#5, §4.22 | **ĐÚNG** code / **VI PHẠM** s1 v1 | `_scope_clauses` `clips.py:149–168`; DEMO s1 FAIL reserved beat lights early L54–55 | **CAO** | Always fill beats_reserved; re-roll gate |
| C10.6 | Retake one-variable + take log | §10#6, §5.1 | **MỘT PHẦN** | Demo informal “1 biến” L66; `repair_budget.py` content-key max 3 — **không** retake protocol creative triage | TRUNG | `pipeline/retake.py` log Take N |
| C10.7 | Three-tier multi-person action | §10#7, §3.1 | **BỎ QUA** | Không | THẤP | Extract prompts |
| C10.8 | max_chain_depth + re-anchor canonical | §10#8, §3.1, clips header | **ĐÚNG** code | `MAX_CHAIN_DEPTH=2` `clips.py:57–59,255–256` | — | Demo s3b depth1 manual ok |
| C10.9 | **plan.json VideoEdl** + validate + promise-check | §10#9 **Rất cao** | **ĐÚNG** schema / **VI PHẠM** write-back | `pipeline/edl.py` full VideoPlan/validate/assess_delivery; demo plan **không** cập nhật produced_path sau Flow | **CAO** | After mỗi clip: `with_produced`; resume `pending()` |
| C10.10 | Captions/narration data + per-line path | §10#10, §8 Orkas | **MỘT PHẦN** | NarrationLine schema; demo chưa TTS produced_path | TRUNG | TTS stage write-back |
| C10.11 | Delivery promise anti-slideshow | §10#11, §5.3 | **ĐÚNG** API | `assess_delivery` `edl.py:273–307`; dry-run prints ok | TRUNG | Gate ship assemble |
| C10.12 | Character bible + view-matched portraits | §10#12, §3.2 Orkas | **MỘT PHẦN** | `animation/bible.py` declared; storyboard refsheet views; **không** bible.json per product + view-match pick | TRUNG | Wire bible ↔ entity images |
| C10.13 | Gate B/C billable confirm | §10#13, §8 Orkas.5 | **ĐÚNG** dry-run | `demo_anim_short` default no-gen L9–16,368–376 | — | Force for paid Flow too |
| C10.14 | IP-safe rewrite / filter vocab | §10#14, §4.16–18 | **MỘT PHẦN** | Demo STYLE hand IP-safe L18–20; ComplianceChecker không full rewrite craft | TRUNG | Compiler IP rewrite |
| C10.15 | Compose HTML/GSAP | §10#15 | **MỘT PHẦN** | FFmpeg+HTML overlay elsewhere; not EDL compose source | THẤP | Later |
| C10.16 | Agent CLI/MCP 1:1 | §10#16, §9.2C | **BỎ QUA** | Không `omnicast plan validate` CLI surface | THẤP | Dev velocity |
| C10.17 | video-craft hook/pacing/safe zones | §10#17 | **MỘT PHẦN** | Manual beat sheet DEMO v3; not plan craft checks | TRUNG | QA craft |
| C10.18 | Flow Ingredients ≤14 roles | §10#18 | **MỘT PHẦN** | Same as A9.16 | **CAO** | Calibrate + roles |

#### C. §8 Chi tiết nhỏ seedance (10) + Orkas (10)

| # | Chi tiết | Trạng thái | Bằng chứng | Sev | Việc |
|---|----------|------------|------------|-----|------|
| S8.1 | Authority order 9 tiers | **BỎ QUA** formal | Ad-hoc prompt order | TRUNG | Document compiler order |
| S8.2 | Never invent observation | **VI PHẠM risk** | Demo manual; no observation record | CAO | Observation confidence on tails |
| S8.3 | Fast lane simple clips | **BỎ QUA** | — | THẤP | — |
| S8.4 | Compression order tags→… | **MỘT PHẦN** | clip prompt sections fixed order | THẤP | Align compiler |
| S8.5 | prompt_lint golden NL not JSON | **MỘT PHẦN** | slop lint; no golden suite | THẤP | Tests |
| S8.6 | extract_last_frame handoff | **ĐÚNG** | `clips.py:101–116`, `veo_pipeline:88–102`; demo tails/ | — | Auto wire inter-shot |
| S8.7 | Source-look lock artifacts | **BỎ QUA** | — | THẤP | — |
| S8.8 | Negation summons → positive constrain | **ĐÚNG** | slop NEGATION; refsheet positive rules L76–84 | — | — |
| S8.9 | felt_intent → craft not emotion word | **BỎ QUA** field | Không felt_intent field | TRUNG | Add to extract |
| S8.10 | Progressive skill disclosure | N/A skill-OS | — | THẤP | — |
| O8.1 | plan checkpoint produced_path | **VI PHẠM demo** | plan.json empty paths; clips in `incoming/` only | **CAO** | Write-back |
| O8.2 | Captions as data | **MỘT PHẦN** | CaptionLine schema unused demo | TRUNG | — |
| O8.3 | Narration mix once | **MỘT PHẦN** | validate double-voice `edl.py:237–243` | TRUNG | Assemble honor |
| O8.4 | on-existing-audio reject | **MỘT PHẦN** | same validate | TRUNG | FFmpeg flag |
| O8.5 | Gate C billable match | **ĐÚNG** dry | validate_plan L245–250 | — | Live Flow count |
| O8.6 | stdout JSON / stderr progress | **BỎ QUA** | print human | THẤP | CLI |
| O8.7 | MCP=CLI 1:1 | **BỎ QUA** | — | THẤP | — |
| O8.8 | skill dump router | **BỎ QUA** | — | THẤP | — |
| O8.9 | Ingest evidence before plan | **BỎ QUA** anim path | — | THẤP | Explainer line |
| O8.10 | Slideshow hard-fail numbers | **ĐÚNG** code | assess_delivery | TRUNG | Enforce ship |

#### C. §11 Anti-pattern

| Anti-pattern | Trạng thái demo/code | Sev |
|--------------|----------------------|-----|
| Dump JSON vào video prompt | **ĐÚNG tránh** | — |
| Re-describe seed static identity | **VI PHẠM** demo components + s1v2 prose dài identity/bg | **CAO** |
| Stack many camera moves 5s | **ĐÚNG** one move clips; DEMO v3 discipline | TRUNG |
| Emotion nouns no gesture | **MỘT PHẦN** acting rules DEMO v3 | TRUNG |
| Assume rights uploaded likeness | N/A | — |
| Silent primary-axis switch | **MỘT PHẦN** | TRUNG |
| Bake narration compose+assemble | guarded validate | TRUNG |
| Guess OCR without looking | N/A | — |
| Infinite re-roll same flaw | repair_budget; demo re-roll limited | TRUNG |
| Port `@Image1` raw vào Gemini | **ĐÚNG tránh** `[IMAGE n]` | — |

#### C. §3–7 / §9.2 map

| Cơ chế | Trạng thái | Bằng chứng | Sev |
|--------|------------|------------|-----|
| Reference role map before adjectives | **MỘT PHẦN** image only | binding | CAO video |
| Dimension authority one winner / drop | **MỘT PHẦN** max_refs drop | binding | TRUNG |
| Character tags no ambiguous pronouns | **MỘT PHẦN** names→tokens image | — | TRUNG |
| I2V do not re-describe identity | **ĐÚNG** clips / **VI PHẠM** Flow components | — | **CAO** |
| Orkas carry-forward last frame | **ĐÚNG** helper / **MỘT PHẦN** demo hand | tails/ | CAO |
| Verify still before pay animate | **BỎ QUA** demo | no frames/ before video | **CAO** |
| Caps ≤3 char ≤6 shot default Orkas | **MỘT PHẦN** demo 3 entity 4–6 shot | — | THẤP |
| sequence_relation enum (seamless / intentional_next) | **MỘT PHẦN** DEMO language; no field code | DEMO L25–34 | CAO |
| Director's Read before prompt | **BỎ QUA** process | — | TRUNG |

---

## 2. Demo Miko — checklist quyết định vs research

| Quyết định trong `DEMO_STATE.md` | Khớp research? | Kết quả |
|----------------------------------|----------------|---------|
| Mode Thành phần + chip Miko/lantern/(workshop muộn) | R2V không first-frame lock | **s2 world jump** |
| Prompt tay thiếu continuity anchors (trước v2) | continuity_line / scene lock | **FAIL s2** |
| s1 đèn tự sáng (reserved s4) | beats_reserved / completed exclusions | **FAIL s1 v1** → re-roll positive language |
| s1v2 re-describe full identity+room trong text | I2V motion-only / source-carries-state | Chạy được vì **không** có seed frame — vẫn R2V-ish |
| s3b/s5 Khung hình + tail frame | seedance chain / FLF / extract_last_frame | **KEEP** liền mạch |
| plan.json dry-run, video ngoài plan | Orkas produced_path checkpoint | **VI PHẠM** ops |
| Không gen frames/ từ `demo_anim_short --go` | StoryGen/AIComic still→video | **BỎ QUA** core path |
| ep1_draft.mp4 concat incoming | stitch | Draft có; continuity cut pair trong `cuts/` cho thấy gap còn |

---

## 3. Tổng hợp thống kê (ước lượng audit rows)

| Report | ĐÚNG | MỘT PHẦN | BỎ QUA | VI PHẠM (code hoặc demo) |
|--------|------|----------|--------|---------------------------|
| ArcReel §8–10 + §9 + core | ~4 | ~14 | ~18 | ~3 (demo/WS1/Flow image) |
| AIComic/StoryGen | ~8 | ~16 | ~12 | ~4 (demo R2V, no frames, soft gate, re-describe) |
| seedance/Orkas | ~10 | ~18 | ~12 | ~5 (demo components, plan write-back, re-describe, no still-first, observation) |

**Đã port tốt (giữ):** binding RefRole, slop 6 classes, beats_completed/reserved in clip prompts, chain depth re-anchor, FLF Gemini, edl validate/promise, dry-run gate C, location sheet no-people, motion-only i2v templates, continuity fail-closed module, cast-subset mappings.

**Lỗ hổng gây fail phim:** (1) demo/production **không** dùng still→FLF/I2V path đã viết; (2) Flow convert/image/ingredients **chưa** calibrate; (3) scene-plate 0-people **chưa** phase riêng cho R2V; (4) plan **không** checkpoint produced; (5) prev-frame composition ref **chưa** attach; (6) storyboard package **chưa** nối `render_real_video`.

---

## 4. TOP-10 việc sửa ngay (xếp hạng)

| Hạng | Việc | Vì sao (map fail Miko) | Severity | Nơi đụng |
|------|------|------------------------|----------|----------|
| **1** | **Cấm / chặn gen video components-R2V khi chưa có first-frame (hoặc scene plate) khóa bối cảnh** — default **I2V/FLF** | s2 nhảy world vì components bịa bg | CAO | `flow_*`, `veo_pipeline`, demo SOP |
| **2** | **Chạy đúng `demo_anim_short.py --go`**: sheets → frames (binding) → `render_shot_chain` Gemini FLF → write `produced_path` | Code path đúng chưa từng ship artifact frames/clips | CAO | `demo_anim_short.py`, `edl.save_plan` |
| **3** | **Calibrate Flow** `start_image` / `start_and_end_image` / `reference_images`; `FLOW_ACCEPTS_IMAGE=True`; `convert(image_path)` không ignore | Free credits nhưng mất lock pixel | CAO | `flow_api.py`, `flow_browser.py`, `veo_pipeline.py:40` |
| **4** | **Scene-only plate path** (0 people) + video ordered char→scene refs + RefRole clauses trên **video** prompt | Identity/bg bleed; thiếu AIComic §0.1 | CAO | `frames.py`, `binding.py`, video providers |
| **5** | **Wire storyboard → render** (WS1): `render_real_video` / product runner gọi `clips.render_shot_chain`, không LLM cell rời | Package storyboard “đảo” | CAO | `render_real_video.py`, `storyboard/pipeline.py` |
| **6** | **Prev-shot last still** attach frame gen (composition-only description) + inter-shot tail policy khi `intentional_next_shot` | Cut slideshow / world reset | CAO | `frames.py`, `clips.py` |
| **7** | **plan.json write-back + resume pending** sau mọi clip (kể bridge Flow) | Orkas checkpoint; demo incoming mồ côi | CAO | `edl.py` usage, demo bridge |
| **8** | **YAML / structured VideoPrompt** + enforce motion-only khi có seed (fail-closed) | Prompt ad-hoc; re-describe drift | CAO | `storyboard/schemas` or `prompt_compiler.py` |
| **9** | **Pre-bill gates:** continuity blocked → stop; slop opening hard; assess_delivery before ship; stills verified before animate | s1 reserved-beat, soft demo review | TRUNG–CAO | `continuity.py`, `slop.py`, `consistency_check`, assemble |
| **10** | **Formal retake log + one-variable** + beats_reserved always populated from plan | Re-roll tốn credit không hệ thống | TRUNG | `pipeline/retake.py`, extract |

---

## 5. Việc “nhỏ” user đòi — không được gác

Dù severity THẤP/TRUNG, research bắt buộc mang theo khi harden:

1. Writing guides photographer/action (A9.3)  
2. Duration vs VO speech bound (A9.13)  
3. Safe zone **video** 20% (B9.8 / B8)  
4. Asset versioning / is_active (B8.1 / A8.4)  
5. path_safety on plan paths (A8.6)  
6. Name-on-sheet optional for Flow (B8.4)  
7. segment_break / sequence_relation fields (A + C)  
8. felt_intent compile (S8.9)  
9. Gate C live credit match Flow (O8.5)  
10. Anti first-3 / soft QA — **giữ** fail-closed (đã đúng)

---

## 6. Đã đọc (audit)

**Research:** `REFS_SB_01_ArcReel.md` (§0–11 + ROUND 2 headers), `REFS_SB_04_…md` (§0–10 + phụ lục + ROUND 2 map), `REFS_SB_05_…md` (§0–13 + map port), `_briefs/COMMON_CONTEXT.md`, `_briefs/g1_audit_core.md`.

**Code:** `storyboard/{binding,clips,frames,refsheet,continuity,slop,models,extract,pipeline,schemas,store,animatic}.py`, `media/veo_pipeline.py`, `media/providers/{video_gemini,flow_browser,flow_api,image_gemini,interfaces}.py`, `pipeline/{edl,repair_budget}.py`, `scripts/demo_anim_short.py`, `animation/bible.py`, `consistency_check.py`, grep `render_real_video.py`.

**Demo artifacts:** `DEMO_STATE.md`, `plan.json`, `incoming/*`, `tails/*`, `cuts/*`, `ep1_draft.mp4`, (không có `frames/`, `clips/`, sheet files under `sb_demo_miko_lantern`).

---

*Kết thúc GAP_1_core. Không chỉnh code trong audit này.*
