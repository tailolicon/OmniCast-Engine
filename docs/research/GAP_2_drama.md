# GAP Audit 2 — Drama pipeline (Jellyfish / LocalMiniDrama + waoowaoo) vs THỰC TẾ

> STATUS: ACTIVE  
> Vai trò: KIỂM TOÁN VIÊN ÁP DỤNG  
> Ngày: 2026-08-02  
> Nguồn: `REFS_SB_02_Jellyfish_LocalMiniDrama.md` + `REFS_SB_03_waoowaoo.md` (cả §8, §9, ROUND 2 / phụ lục)  
> Đối chiếu: `implementation/src/omnicast/storyboard/*`, `media/*`, `scripts/demo_anim_short.py`,  
> `implementation/output/products/anim_demo/miko_lantern_ep1/DEMO_STATE.md`

---

## 0. Kết luận điều hành (đọc 90 giây)

| Trục drama liền mạch | Repo tham chiếu | OmniCast **code package** | Demo Miko **thực thi** |
|----------------------|-----------------|---------------------------|-------------------------|
| Multi-phase plan→cine→acting→detail | waoowaoo 4 phase | **BỎ QUA** — extract one-shot | FILM PLAN v3 *mô tả* 3-pass tay, không có module |
| photography_rules / actingNotes per panel | waoowaoo | **BỎ QUA** | Acting 1 câu/shot chỉ trong `DEMO_STATE` prose |
| Slot / available_slots bối cảnh | waoowaoo | **BỎ QUA** | Position lock Miko TRÁI/đèn PHẢI chỉ text plan |
| first/last + tail-carry | Jellyfish + waoowaoo + LMD | **MỘT PHẦN** — `clips.py` + Gemini FLF; Flow `convert()` bỏ image | v2/v3 **manual** Khung hình + bridge upload — hoạt động |
| Candidate 1–4 + undo | waoowaoo | **BỎ QUA** (chỉ `attempts` counter) | Re-roll tay trong Flow UI |
| Base vs rendered prompt | Jellyfish | **ÁP DỤNG ĐÚNG** (`base_prompt`/`rendered_prompt` + cấm token leak) | Demo Flow **bỏ qua** binding — prompt tay + @chip |
| Identity anchors 6 lớp + industrial sheet | LMD | **BỎ QUA** / sheet đơn giản | Miko chip + description free-text |
| layout_description + continuity_snapshot | LMD | **BỎ QUA** field; continuity **text-axis** khác | s2 **FAIL bối cảnh trôi** = đúng gap này |
| ShotDetail camera full + dialogue lines | Jellyfish | Camera enums **ĐÚNG**; dialogue multi-line **BỎ QUA** | Silent-cute, không multi-speaker |
| Scene-first `@图片1` | LMD omni | **VI PHẠM hướng** — `_KIND_PRIORITY` face-first | s2 thiếu workshop chip → drift |

**Chẩn đoán root cho “demo fail”:**  
Package storyboard đã có một phần kỷ luật drama (base/rendered, cast gate, neighbor frame prompt, clip chain, continuity fail-closed, motion-only i2v). **Demo Miko không chạy end-to-end qua package đó** — gen trên Flow UI (components + manual tail), prompt tay, thiếu scene entity/anchors tự động → s2 trôi bối cảnh; v2/v3 bù bằng tay (tail-carry, film plan) chứ không đóng gap code.

---

## 1. Thang phân loại & severity

| Nhãn | Nghĩa |
|------|--------|
| **ÁP DỤNG ĐÚNG** | Cơ chế có trong code, đúng tinh thần khuyến nghị, demo không làm ngược |
| **MỘT PHẦN** | Có skeleton / nửa đường / provider này được provider kia không |
| **BỎ QUA** | Khuyến nghị rõ, code không có (hoặc chỉ doc/plan) |
| **VI PHẠM** | Code hoặc demo làm **ngược** khuyến nghị (gây đúng class lỗi Miko) |

Severity = tác động tới mục tiêu *phim drama liền mạch chạy tốt như repo*:

- **CAO** — face/bối cảnh/hành động nhảy cut, hoặc không wire first/last  
- **TRUNG** — chất lượng shot / UX / multi-voice / maintainability  
- **THẤP** — polish, anti-pattern tránh được, ops phụ

---

## 2. Bảng đầy đủ — REFS_SB_02 (Jellyfish + LocalMiniDrama)

### 2.1 Mục 9 — 16 đề xuất

| # | Khuyến nghị | Nguồn | Trạng thái | Bằng chứng file:line | Severity | Việc phải làm |
|---|-------------|-------|------------|----------------------|----------|---------------|
| J1 | Candidate confirm → ready gate (asset/dialogue linked\|ignored trước gen) | §9 #1, §1.1, shot-status-flow | **MỘT PHẦN** | Cast gate: `pipeline.py:1-19`, `models.py:224-231` (`CAST_PENDING`→`CAST_APPROVED`). **Không** có per-shot candidate table (character/scene/prop/dialogue pending→linked\|ignored) kiểu Jellyfish. Demo: `DEMO_STATE` gen Flow không qua cast/shot ready. | CAO | Shot-level readiness + candidate link/ignore API trước unlock video gen |
| J2 | Base vs rendered prompt split; agent cấm `图N` / `[IMAGE n]` | §9 #2, §8.1, R2.4 rules 5–6 | **ÁP DỤNG ĐÚNG** (package) | `models.py:439-451`; `binding.compose_rendered_prompt` `binding.py:285+`; strip leak `frames.py:45-47,77-81`; system “NEVER write [IMAGE…]” `frames.py:301-302`. **Demo Flow:** prompt tay + @chip — **không** dùng split. | TRUNG | Bắt mọi path gen (kể Flow demo) qua `compose_rendered_prompt` |
| J3 | `@图片1`/图1 = scene only; order scene-first | §9 #3, §3 LMD omni, §11.2 | **VI PHẠM hướng** | Order **face-first**: `_KIND_PRIORITY` character=0, location=2 — `binding.py:54-61,116-137`. Roles có ENVIRONMENT nhưng không slot-1 scene. Demo s2 thiếu workshop: `DEMO_STATE.md:57-61`. | CAO | Option drama: scene/location token đầu; budget multi-ref vẫn ưu tiên face sau scene |
| J4 | Identity anchors 6-layer Hex | §9 #4, §3, R2 identity anchors | **BỎ QUA** | `Entity` chỉ `description` + `traits: dict[str,str]` free — `models.py:276-297`. Không schema `facial_features` / Hex palette 6 khóa. | CAO | Thêm `identity_anchors` structured + extract pass; inject khi model yếu / thiếu ref |
| J5 | Industrial character sheet (FACE HERO + FRONT/BACK + SIDE + COSTUME DETAIL) | §9 #5, R2 getRolePolish | **MỘT PHẦN** | `refsheet.py:47-55` — front / three_quarter / full_body; backdrop plain; **không** layout industrial 1 canvas FACE+BACK+SIDE+COSTUME. | TRUNG | Prompt sheet LMD-style (paraphrase) + optional single-canvas multi-panel cấm |
| J6 | `layout_description` spatial contract | §9 #6, §8.6, LMD storyboard fields | **BỎ QUA** | Không field `layout_description` trên `Shot` (`models.py:359-413`). Có `screen_direction`/`eyeline` nhưng không standing L/C/R + prop scale contract. Demo v3 position lock chỉ prose `DEMO_STATE.md:6-7`. | CAO | Field + gate + inject prompt: “Miko left third / lantern right / real-world scale” |
| J7 | `continuity_snapshot` clothing/posture/screen_position | §9 #7 | **BỎ QUA** | Continuity so sánh **board fields** (wardrobe axis via `declared_changes`, bindings) — `continuity.py:1-25,53-70`. Không snapshot JSON sau mỗi frame image. | CAO | Sau gen still: snapshot → inject shot kế; hard-fail wardrobe silent change |
| J8 | Cấm clothing/face text khi đã có ref | §9 #8, §11.4 | **MỘT PHẦN** | RefRole ignore clauses: `models.py:77-84`, `binding.py:264-272`. Frame agent **không** cấm viết ngoại mạo khi ref attach; entity description vẫn vào cast block `frames.py:361-363`. i2v path tốt hơn: motion-only `clips.py:171-178`. | CAO | Rule: nếu entity có approved image → strip appearance prose khỏi base; chỉ token + action |
| J9 | action_beats 2–4 + frame phase pick (first/key/last consume phase) | §9 #9, R2.4 `selected_action_beat_phase` | **MỘT PHẦN** | `action_beats` trên Shot + extract (`schemas.py:184-187`, `models.py:381`). `plan_frame_types` FIRST+LAST khi movement/beats (`frames.py:58-70`). Agent nhận list beats nhưng **không** map phase→first/last text như Jellyfish `action_beat_phases`. | TRUNG | Phase picker deterministic: first=beat[0] incomplete, last=beat[-1] settled |
| J10 | first_last video mode | §9 #10, Jellyfish generated_video | **MỘT PHẦN** | Plan+prompt FLF: `clips.py:73-77,180-206,243-268`. Gemini: `video_gemini.py:25-30,85-91`. Flow browser `convert` **bỏ** image: `flow_browser.py:997-1015`. `veo_pipeline.FLOW_ACCEPTS_IMAGE = False` `veo_pipeline.py:18-21,40`. Demo: FLF **manual** Khung hình `DEMO_STATE.md:30-38,79-84`. | **CAO** | Wire Flow start/end slots (đã note `flow_api.py:164-184`) hoặc API `start_end_image`; flip `FLOW_ACCEPTS_IMAGE` khi calibrate |
| J11 | ShotDialogLine speaker/target/mode | §9 #11 | **BỎ QUA** | Chỉ `voiceover: str` (`models.py:374`, `schemas.py:164`). Không dialogue lines multi-speaker. | TRUNG | Model lines + TTS router multi-voice (drama mode) |
| J12 | Narration + SRT burn path | §9 #12, LMD TTS/SRT | **MỘT PHẦN** | YouTube path: `subtitle.py`, `orchestrator.py:178-181`, `ffmpeg` burn. Storyboard drama không có per-shot dialogue→SRT. Demo: silent-cute + optional VO sau `DEMO_STATE.md:88-89`. | THẤP | Drama mode optional SRT từ dialogue lines |
| J13 | UI prep page ≠ gen studio | §9 #13, §11.5 | **BỎ QUA** | Không frontend storyboard routes trong workspace (no `frontend/`). Pipeline stages backend-only `pipeline.py:11-19`. | TRUNG | `/storyboard` tabs Chuẩn bị / Sinh media + readiness panel |
| J14 | Prompt override store (user-editable templates) | §9 #14 | **BỎ QUA** | Prompts hard-code module (`frames.py:_SYSTEM`, extract system). Vault policy khác domain. | THẤP | vault `prompt_templates` + version |
| J15 | Truncation continuation long extract | §9 #15, LMD storyboard | **BỎ QUA** | Một `call_llm_structured` `max_tokens=16000` (`extract.py:461`) — không continuation on truncate. | TRUNG | Detect truncated JSON → continue prompt |
| J16 | Emotion intensity / segment_index grouping | §9 #16 | **BỎ QUA** | Không emotion arrows 3/2/1/0/-1; không `segment_index`/`segment_title` trên Shot. | THẤP | Optional rhythm fields cho short-drama |

### 2.2 Mục 8 — chi tiết nhỏ (không trùng hoàn toàn mục 9)

| # | Chi tiết | Trạng thái | Bằng chứng | Severity | Việc |
|---|----------|------------|------------|----------|------|
| J8a | PreparationState API aggregated | **BỎ QUA** | Không API `ready_for_generation` aggregate per shot | TRUNG | Thêm response sau mọi link/ignore |
| J8b | `skip_extraction` escape hatch | **BỎ QUA** | Board luôn extract/hand-build; không flag per-shot skip | THẤP | Flag hand-crafted shot → ready |
| J8c | Actor ≠ Character composition | **MỘT PHẦN** | `EntityKind` character/costume + `costume_id` (`models.py:42-54,292-295`) — **không** Actor global multi-view tách Character project | TRUNG | Optional Actor pool khi multi-costume series |
| J8d | Name existence check / encourage reuse | **MỘT PHẦN** | `reconcile_draft` + merge + VERBATIM (`extract.py:1-23`, `merge.py`) | TRUNG | API check duplicate names UX |
| J8e | First-frame as layout lock ref for last | **MỘT PHẦN** | Sheet views chain ref anchor `refsheet.py:11-15`; last frame gen **không** auto attach first image như LMD imageService | CAO | `generate_frame_image` LAST: attach FIRST path làm layout lock |
| J8f | `@图片N` never `@姓名` for omni | **ÁP DỤNG ĐÚNG** (package) | Token substitute names → `[IMAGE n]` `binding.py:180-194` | TRUNG | Giữ; áp cho Flow video prompt path |
| J8g | Canvas workflow LMD | **BỎ QUA** | Không canvas node pipeline | THẤP | UX sau core |
| J8h | Video aspect normalize ffmpeg multi-provider | **MỘT PHẦN** | `animatic`/EDL concat; demo concat note `DEMO_STATE.md:86-87` | THẤP | Normalize 720×1280 trước concat |
| J8i | File usages / task links provenance | **BỎ QUA** | Mappings lưu path nhưng không task-link graph | THẤP | Trace asset→frame→clip |

### 2.3 ROUND 2 / cơ chế “full field” (trọng tâm brief)

| # | Cơ chế | Trạng thái | Bằng chứng | Severity | Việc |
|---|--------|------------|------------|----------|------|
| JR1 | ShotDetail full (camera, angle, movement, duration, mood, atmosphere, vfx, action_beats, first/last/key prompts) | **MỘT PHẦN** | Có camera/angle/movement/duration/mood/action_beats + Frame prompts tách file (`models.py:377-382`, `Frame` 438-456). **Thiếu** atmosphere, mood_tags[], vfx_type/note, follow_atmosphere, has_bgm, override_video_ratio, prompt_template_id | TRUNG | Bổ sung fields drama-only nếu cần; không block WS1 |
| JR2 | getStoryboardSystemPrompt pacing 5–15s, dynamic camera ≥80% | **BỎ QUA** | Extract không enforce duration 5–15 hay % dynamic camera (`extract.py` system ~line 400+). Demo tự gán 4–8s plan. | TRUNG | Drama channel policy: duration clamp + monotony already `_MONOTONY_RUN=3` `continuity.py:72-74` — mở rộng % movement |
| JR3 | universalSegmentPromptBundle (@图片N omni, dialogue says:) | **BỎ QUA** | Không bundle omni video multi-ref `@图片`; Flow ingredients ≤3 `flow_browser.py:91-93` | CAO | Video prompt builder omni-order + dialogue attach |
| JR4 | Neighbor continuity in frame agent (“承接上一镜头”) | **ÁP DỤNG ĐÚNG** (package) | `frames.py:16-19,333-335,377-386`; Jellyfish R2.4 rules 13–14 mirrored loosely | CAO | **Bắt demo dùng FramePromptAgent** thay prompt tay |
| JR5 | Element extract + VERBATIM names + global dict check | **ÁP DỤNG ĐÚNG** | `extract.py:1-23`, reconcile auto-create missing; `frames.py:297-299` | TRUNG | Giữ |
| JR6 | Entity merger + variant analyzer costume timeline | **MỘT PHẦN** | `merge.py` conflicts; **không** costume timeline / variant_analyzer shot-indexed | TRUNG | Variant timeline khi multi-outfit |

### 2.4 Anti-patterns §10 — OmniCast có dẫm không?

| Anti-pattern (không nên học) | OmniCast | Ghi chú |
|------------------------------|----------|---------|
| Hardcode fixed lens ≤20% mọi niche | **Tránh được** | Không copy rule LMD cứng |
| Hallucinate portrait age/face | **MỘT PHẦN** | Sheet gen từ description; fail-closed cast tốt hơn |
| Một voice TTS mọi character | N/A drama demo silent | YouTube VO single-voice common |
| Lip-sync chỉ bằng prompt | **Tránh over-promise** | Avatar RMS mouth `avatar.py` — không claim lip-sync drama |
| EntityMerger trước human confirm | **OK** | Cast barrier sau sheet |
| ComfyUI default identity | **OK** | Cloud + ref |
| BGM per-shot | **OK** | Track-level |

---

## 3. Bảng đầy đủ — REFS_SB_03 (waoowaoo)

> License CC BY-NC-SA 4.0 — **chỉ học pattern**, cấm chép code/prompt nguyên văn.

### 3.1 Mục 9 — 15 đề xuất

| # | Khuyến nghị | Nguồn | Trạng thái | Bằng chứng file:line | Severity | Việc phải làm |
|---|-------------|-------|------------|----------------------|----------|---------------|
| W1 | Multi-phase storyboard plan→cine→acting→detail | §9 #1, §0.1, phases | **BỎ QUA** | `StoryboardExtractorAgent` one-shot draft (`extract.py`, `pipeline.start_board`). Không `storyboard-phases` 4 bước. Demo FILM PLAN v3 “waoowaoo 3-pass” = **text only** `DEMO_STATE.md:6-8`. | CAO | Modules: plan beats → cinematography → acting notes → detail prompts (paraphrase) |
| W2 | `video_prompt` age+gender + dynamic verbs; names only in still | §9 #2, §8.3 | **MỘT PHẦN** | i2v motion-only `clips.build_clip_prompt` `clips.py:171-226`; `veo_pipeline.build_motion_prompt` `veo_pipeline.py:74-85`. **Không** age/gender fields; still prompts vẫn full names+description. | CAO | Split still-identity vs video-motion schemas; age/gender traits on Entity |
| W3 | Ordered refs sketch→chars→location + **labels** (bar text) | §9 #3, §8.1 | **MỘT PHẦN** | Ordered mappings + `reference_labels=[token]` `frames.py:269`; Gemini accepts labels `image_gemini.py:140-143`. **Không** bake text bar tên asset lên pixel ref (waoowaoo label bar). Order ≠ sketch→char→loc. | TRUNG | Optional labeled strip on ref images; document order policy |
| W4 | photography_rules + acting_notes inject image prompt | §9 #4, panel JSON Phụ lục B | **BỎ QUA** | Không fields; Frame agent gộp camera+action một prompt. Demo acting 1 câu/shot chỉ plan `DEMO_STATE.md:7`. | CAO | `photography_rules` + `acting_notes` per shot → append still prompt |
| W5 | Location `available_slots` + panel `slot` | §9 #5, §8.4, location create | **BỎ QUA** | Location entity description free-text; không slots 2–6. Continuity không so slot. Demo position lock prose only. | CAO | Entity location.available_slots[]; Shot cast.slot; soft gate |
| W6 | first/last i2v between panels | §9 #6 **Critical** | **MỘT PHẦN / VI PHẠM default path** | Code path: `clips.render_shot_chain` + Gemini FLF. Flow default demo: components t2v-like + ingredients; `FLOW_ACCEPTS_IMAGE=False`. Demo **sau** v2 mới manual FLF — chứng minh pattern đúng nhưng **pipeline auto chưa**. | **CAO** | Ưu tiên #1: automate Flow Bắt đầu/Kết thúc hoặc Gemini FLF as default drama path |
| W7 | Candidate images 1–4 + previousImageUrl undo | §9 #7, §8.6 | **BỎ QUA** | `Frame.attempts` only `models.py:456`. Không `candidateImages[]` / `previous_*`. | TRUNG | Store N candidates + undo pointer |
| W8 | Per-user concurrency + 4 queues | §9 #8, §0.5 | **BỎ QUA** | Không BullMQ-style media queues per type/user gate. | THẤP | Batch runner policy khi scale |
| W9 | Billing freeze / cost quote | §9 #9 | **MỘT PHẦN** | `demo_anim_short` dry-run bill `demo_anim_short.py:9-16`; Flow `preflight_video` `flow_browser.py:1023-1038`. Không freeze ledger OFF/SHADOW/ENFORCE. | TRUNG | Quote credits before batch; hard stop |
| W10 | Exact VERBATIM entity names | §9 #10 | **ÁP DỤNG ĐÚNG** | Cast registry + bind longest-first `binding.py:184-194`; extract notes. | TRUNG | Giữ |
| W11 | Lip-sync-aware dialogue shot split (speaker + reaction ≥2) | §9 #11, §7 | **BỎ QUA** | Extract không force dialogue→2 shots. Demo silent. | TRUNG | Drama dialogue splitter khi có lines |
| W12 | Global asset hub cross-project | §9 #12 | **BỎ QUA** | Board-scoped entities; channel `reference_images` partial `character_anchor.py:108-126`. | THẤP | Channel/global cast library |
| W13 | Editor transitions dissolve default | §9 #13 | **MỘT PHẦN** | `animatic` xfade optional; EDL hard-cut common. Demo concat `-c copy` `DEMO_STATE.md:86-87`. | THẤP | Default short dissolve 0.3–0.5s drama |
| W14 | Prompt canary / semantic regression guards | §9 #14, §8.13 | **MỘT PHẦN** | `slop.py` lint blocking evaluators; không canary suite prompt files. | TRUNG | Tests: base must not contain `[IMAGE`; motion must not restate wardrobe |
| W15 | No negative prompt — positive hard rules | §9 #15, §8 | **MỘT PHẦN / lệch** | Frame system “NEVER NEGATE” `frames.py:319-321` **đúng pattern**. Nhưng `board.negative_prompt`, `NEGATIVE_TAIL` veo `veo_pipeline.py:44-45,85`, channel negatives — vẫn phụ thuộc negative. | THẤP | Drama stills: positive-only; negatives chỉ provider channel |

### 3.2 Mục 0 / 8 — rule ROUND 2 trọng tâm brief

| # | Rule | Trạng thái | Bằng chứng | Severity | Việc |
|---|------|------------|------------|----------|------|
| WR1 | “上一镜头动作在下一镜头承接” (plan + frame) | **MỘT PHẦN** | Frame agent CONTINUE FROM PREVIOUS `frames.py:333-335`. Clip chain tail `clips.py:336-337`. **Không** photography/acting phase rule. Demo v3 “shot sau thừa kế” plan-only `DEMO_STATE.md:7-8`; s1→s2 **cut components** từng fail continuity. | CAO | Encode inheritance: planned_start_state **bắt buộc** = prev observed_end; block gen nếu trống |
| WR2 | 4-phase atomic retry max 3 | **BỎ QUA** | Không phase retry machine | TRUNG | Retry per phase storyboard text |
| WR3 | profileConfirmed asset gate | **MỘT PHẦN** | `approve_cast` ≈ profile confirm `pipeline.py:208-231` | TRUNG | Per-appearance confirm như multi look |
| WR4 | firstLastFramePrompt field riêng panel | **MỘT PHẦN** | Frame FIRST/LAST prompts; clip `end_frame`; **không** field `firstLastFramePrompt` video-specific | CAO | Explicit video FLF prompt field (path-only motion) |
| WR5 | linkedToNextPanel schema | **BỎ QUA** | `parent_shot_id` chain có `models.py:398-401` — gần; không flag linked UI | THẤP | Alias/flag seamless pair |
| WR6 | Capability catalog firstlast/duration/audio | **MỘT PHẦN** | `supports_last_frame` Gemini; Flow ops list `flow_api.py:65-77` chưa calibrated gen | CAO | Capability table runtime trước enqueue |
| WR7 | Default duration 3s anti-pattern waoowaoo | **Tránh** | Demo 4–8s; `CLIP_SECONDS=6` `clips.py:56` | — | Không copy default 3s |
| WR8 | No automated visual QA (waoowaoo anti) | **MỘT PHẦN** | `visual_match_runner.py` exists; demo review **human** only `DEMO_STATE` | TRUNG | Bật pixel check giữa stills/clips drama |

### 3.3 Phụ lục C mapping sanity

| OmniCast | waoowaoo | Audit |
|----------|----------|-------|
| Entity + refsheet | CharacterAppearance / LocationImage | **MỘT PHẦN** — thiếu slots, multi-appearance index, previous undo |
| binding RefRole | Labeled refs weaker | OmniCast **mạnh hơn** formal binding; demo **không dùng** |
| continuity fail-closed | Soft prompt rules | OmniCast gate **mạnh hơn** trên paper; demo **bypass** |
| Veo pipeline | VIDEO_PANEL i2v+FLF | **Gap critical** Flow image path |
| Pixel drift measure | also missing waoowaoo | **Cả hai thiếu** — không lấy làm cớ bỏ layout contract text |

---

## 4. Đối chiếu quy trình DEMO Miko (bằng chứng fail)

Nguồn: `DEMO_STATE.md` + `scripts/demo_anim_short.py`.

| Sự kiện demo | Liên hệ khuyến nghị | Phân loại |
|--------------|---------------------|-----------|
| s1 FAIL: đèn tự sáng (reserved beat s4) | beats_reserved / scope firewall Jellyfish+seedance; OmniCast **có** `beats_reserved` field | Package **ĐÚNG field**; demo prompt tay **VI PHẠM** — không inject “Do not yet show” `clips.py:165-168` |
| s2 FAIL: bối cảnh trôi, thiếu workshop anchors | layout_description, scene ref, continuity_line, scene-first | **VI PHẠM** — `DEMO_STATE.md:57-61` thừa nhận prompt tay thiếu anchors; `continuity_line` có trong frames package nhưng **không chạy** |
| v2: thêm workshop entity + anchors | J3/J6/W5 | **Sửa tay** — chứng minh gap real |
| v2/v3: Khung hình = tail frame Bắt đầu | W6/J10 first-last | **Áp dụng pattern đúng bằng tay** — code Flow `convert` vẫn ignore image |
| FILM PLAN v3 “waoowaoo 3-pass” position/acting/inherit | W1/W4/W5/WR1 | **BỎ QUA trong code** — chỉ markdown plan |
| Bridge pull clip + ffmpeg concat | LMD merge / editor | Ops demo; không storyboard store |
| `demo_anim_short.py` hand-authored board + dry-run | Cast registry path | Script **đúng hướng package** nhưng DEMO_STATE live path = Flow UI, không log `--go` package |

**Kết luận audit demo:** fail không chứng minh “storyboard package vô dụng” — chứng minh **đường gen thật chưa bắt buộc đi qua package + Flow FLF chưa automate**.

---

## 5. Tổng hợp đếm

| Trạng thái | SB_02 (mục 9+8+R2 chính) | SB_03 (mục 9+8 chính) | Gộp (unique cơ chế) |
|------------|--------------------------|------------------------|---------------------|
| ÁP DỤNG ĐÚNG | ~5 | ~2 | ~6 |
| MỘT PHẦN | ~12 | ~10 | ~16 |
| BỎ QUA | ~14 | ~12 | ~18 |
| VI PHẠM (code hoặc demo) | ~2 (scene order; demo bypass anchors) | ~1 (default Flow no-image) | ~3 critical |

---

## 6. TOP-10 việc sửa ngay (xếp hạng)

Thứ tự = impact drama liền mạch × gap đã **tự bộc lộ** trên demo Miko.

| Hạng | Việc | Gap gốc | File đích | Effort | Vì sao ngay |
|------|------|---------|-----------|--------|-------------|
| **1** | **Wire first-frame / first-last vào path gen mặc định (Flow slots hoặc Gemini FLF); cấm silent t2v khi cần continuity** | W6, J10 | `flow_browser.py` / `flow_api.py`, `veo_pipeline.py` (`FLOW_ACCEPTS_IMAGE`), `clips.render_shot_chain` | L | Demo chỉ liền mạch khi manual Khung hình; `convert()` đang ignore image |
| **2** | **Bắt mọi shot prompt qua `continuity_line` + layout contract + scene ref** — không cho path “prompt tay thuần” lên production | J6, J3, demo s2 | `frames.py`, `binding.py`, demo/Flow bridge | S–M | s2 FAIL đúng class này (`DEMO_STATE.md:57-61`) |
| **3** | **Scene/location trong binding order policy cho drama** (scene early + character identity) | J3, LMD @图片1 | `binding.py` `_KIND_PRIORITY` / mode flag | S | Face-first bỏ rơi room → trôi thế giới |
| **4** | **`layout_description` + optional `available_slots`/`slot`** persist + inject + soft gate | J6, W5 | `models.py`, `continuity.py`, extract schemas | M | Position lock v3 đang chỉ prose |
| **5** | **Cấm re-describe face/clothes khi đã có approved ref** (still + i2v) | J8, W2, LMD | `frames.py` agent + stripper; `clips.py` đã gần đúng | S | Giảm conflict ref vs text (Miko identity ok nhưng prop/scene không) |
| **6** | **`beats_reserved` / `beats_completed` bắt buộc inject mọi video prompt** (kể Flow) | J scope, clips already | `clips.py:160-168` → outbound Flow prompt builder | S | s1 đèn sáng sớm = reserved beat leak |
| **7** | **Multi-phase (hoặc 3-pass tối thiểu): plan spatial → acting visible → detail camera** | W1, W4, DEMO v3 | new `storyboard/phases*.py` (paraphrase, không copy waoowaoo) | L | One-shot extract không sinh photography/acting notes |
| **8** | **LAST frame gen attach FIRST image làm layout lock** | J8e, LMD | `frames.generate_frame_image` | S | Ổn định first→last still trước i2v |
| **9** | **Shot ready gate + candidate confirm (cast/location/prop) trước video $** | J1, W3 profile | `pipeline.py` + API | M | Tránh gen khi thiếu workshop entity như s2 early |
| **10** | **Identity anchors 6-layer + industrial sheet prompt** cho model yếu / multi-ep | J4, J5 | `models`/`refsheet`/`extract` | M | Face ổn Miko nhờ chip; scale series sẽ gãy không anchors |

### Việc ngay lập tức *không* vào top 10 nhưng nên queue

- Candidate 1–4 + undo (W7)  
- ShotDialogLine + multi-TTS (J11)  
- UI prep vs studio (J13)  
- Truncation continuation (J15)  
- Prompt canary tests (W14)  
- Global asset hub (W12)

---

## 7. Việc **không** sửa theo anti-pattern

1. **Không** copy prompt/file waoowaoo nguyên văn (CC BY-NC-SA).  
2. **Không** hardcode “dynamic camera ≥80%” cho mọi YouTube explainer.  
3. **Không** promise lip-sync chỉ bằng video_prompt.  
4. **Không** thay fail-closed continuity bằng “chỉ re-roll người” (waoowaoo thiếu visual QA — OmniCast đã có hướng `visual_match_runner`).  
5. **Không** default panel 3s (waoowaoo) — bám VO/action duration.

---

## 8. Ma trận “package vs demo” (tránh nhầm audit)

| Cơ chế đã có trong package | Dùng trong DEMO_STATE live? |
|----------------------------|-----------------------------|
| base/rendered + RefRole | **Không** (Flow @chip) |
| continuity_line / anchors fields | **Không** (s2 thừa nhận thiếu) |
| cast_ready / approve_cast | **Không** log |
| clips FLF + motion-only | **Một phần tay** (Khung hình), không `render_shot_chain` |
| beats_reserved inject | **Không** (s1 fail) |
| FramePromptAgent neighbor | **Không** |

→ Audit “BỎ QUA” = thiếu code.  
→ Audit “VI PHẠM demo” = code có / path thật không dùng.

---

## 9. Đã đọc (audit trail)

**Reports**

- `docs/research/_briefs/COMMON_CONTEXT.md`  
- `docs/research/_briefs/g2_audit_drama.md`  
- `docs/research/REFS_SB_02_Jellyfish_LocalMiniDrama.md` (§0–12, §8–11, ROUND 2 header + R2.1–R2.4 samples)  
- `docs/research/REFS_SB_03_waoowaoo.md` (§0, §7–10, Phụ lục B–C, ROUND 2 rules photography/slots/承接)

**Code OmniCast**

- `storyboard/models.py`, `binding.py`, `frames.py`, `clips.py`, `continuity.py`, `extract.py`, `schemas.py`, `refsheet.py`, `pipeline.py`, `store.py` (grep), `merge.py` (grep)  
- `media/veo_pipeline.py`, `providers/flow_browser.py`, `flow_api.py`, `video_gemini.py`, `image_gemini.py`, `character_anchor.py`, `subtitle.py`, `orchestrator.py` (subtitle path)  
- `scripts/demo_anim_short.py`  
- `implementation/output/products/anim_demo/miko_lantern_ep1/DEMO_STATE.md`

**Không đụng:** code production, `_refs/*`, report research khác ngoài đọc.

---

*Hết GAP Audit 2. Output duy nhất: `docs/research/GAP_2_drama.md`.*
