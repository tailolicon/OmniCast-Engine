# WS1 — Bản thiết kế nâng cấp Storyboard (tổng hợp từ 13 repo _refs)

> STATUS: ACTIVE (đang tổng hợp — não Claude viết dần theo từng report đã verify)
> Input: `docs/research/REFS_SB_01..07*.md` + `REFS_SB_00_VERIFY.md` (verdict + errata)
> Mục tiêu: storyboard OmniCast hoàn thiện và VƯỢT các repo tham khảo — cả cơ chế lẫn cách viết prompt.
> Errata phải nhớ khi đọc report: E1 ShotStatus Jellyfish có `generating`; E2 tagline
> "Direct the model…" nằm ở README seedance (không phải Soul section); E3 hyperframes có 16
> (không phải 15) caption components; E4 ShotDetail Jellyfish còn ~5 field report bỏ sót.

## 0. Khung ưu tiên (cập nhật dần)

| Ưu tiên | Hạng mục | Nguồn chính | File đích OmniCast |
|---|---|---|---|
| **P0-A** | `storyboard/prompt_compiler.py` — ClipContract → prose | 05 (seedance) | storyboard/ + veo_pipeline.py |
| **P0-B** | `pipeline/edl.py` — plan.json diffable + promise-check | 05 (Orkas) | pipeline/ + products |
| P1 | Retake protocol + chain-depth + re-anchor | 05 | pipeline/retake.py, veo_pipeline |
| P1 | Character bible đa góc nhìn (multi-view portraits) | 05 (+02/03 chờ đọc) | storyboard/refsheet.py |
| P2 | Agent CLI surface (`omnicast plan validate`…) + compose line | 05 | api/, cli mới |
| (chờ) | — bổ sung sau khi đọc 01/02/03/04/06/07 bản đã vá | | |

---

## 1. Chưng cất Report 05 — seedance-2.0 + Orkas (verdict TIN ĐƯỢC, MIT×2)

### 1.1 Tầng ngôn ngữ prompt (P0-A) — "cách nói với model"

**ClipContract (port shape seedance, đổi syntax về OmniCast):** mỗi `Storyboard.Shot` compile ra:
`narrative_job, felt_intent, generation_mode (t2v|i2v|r2v|flf2v), reference_roles (từ binding.py),
current_clip_action, endpoint, already_happened[], reserved_for_later[], continuity_locks[],
planned_start/end_state` → **prose tự nhiên** (CẤM dump JSON vào model — luật cứng seedance).

**Thứ tự compile 9 bước** (prompt-compiler.md:16-27): tags → opening state QUAN SÁT ĐƯỢC
(continuation dùng observed, không dùng planned) → action + endpoint → felt_intent dịch thành
carrier camera/light/performance/sound (CẤM từ cảm xúc trần) → camera → light/audio nếu cần →
exclusions (đã xảy ra + để dành) → endpoint. **Source-carries-state:** có seed image/clip thì
text chỉ chở DELTA, không tả lại identity tĩnh (tả lại = nguyên nhân drift số 1).

**Công thức đạo diễn 7 slot** (Subject + Action + Scene + Camera + Light/Style + Audio +
Constraints — subject/action ĐỨNG ĐẦU vì attention budget; 30–110 từ). Verbatim đầy đủ:
report 05 §4.1–4.3.

**Ngữ pháp clip-scope** (chống replay/leak trong chuỗi Veo): `Begin with… / Continue the
same… / This clip only… / Stop when… / Do not yet…` (§4.8).

**Mode templates:** I2V 2 chế độ Hold (3-4 micro-action + double-lock "does not stand, turn,
or leave frame") / React (1 cảm xúc → sub-beats ≥2s); FLF2V template (§4.5) — khớp đường
first/last-frame của Flow; R2V role-isolation câu mẫu "@X controls Y only; ignore its Z"
(§4.6/4.9) — map thẳng vào mệnh đề RefRole của `binding.py`, và là NGÔN NGỮ cho Flow
Ingredients ≤14 ảnh.

**Anti-slop 6 lớp** (§4.17): empty evaluators / borrowed image tokens (8K, masterpiece) /
tag salad / negation slop (chỉ negate trong constraint slot) / adjective stacking /
feel-suffix (điện ảnh感 → nguyên nhân vật lý). Test khả kiến: "camera/light-meter/mic/
stopwatch có đo được cụm này không?". → Mở rộng `storyboard/slop.py` + bảng thay thế.

**Từ vựng an toàn filter** (§4.18): bảng risky→safer (violent impact → high-energy
collision…) + bẫy false-positive tiếng Anh (shoot the scene → film the scene). → nạp vào
prompt_compiler + ComplianceChecker.

**Camera/Lighting/Motion/Audio phrase tables** (§4.10–4.13): mỗi nhu cầu một cụm MẠNH kèm
cụm CẤM ("slow dolly-in from medium close-up…" thay "dramatic cinematic zoom"). 1 primary
move/clip; phát biểu start/speed/subject-relation/endpoint. Emotion → đúng 1 gesture nhìn
thấy được. Multi-person: 3 tier (nền micro-motion / 1 phản ứng có time-window / large action
cấm mặc định).

**Feeling→film mapping** (§4.19): "epic" → wide establishing + slow push-in + low warm sun…
— dùng cho bước dịch tone kịch bản → chỉ đạo hình.

### 1.2 Tầng IR kế hoạch (P0-B) — "video là plan diff được"

**OmniCast VideoEdl mỏng** (Pydantic, `output/products/{id}/plan.json`): aspect,
total_target_sec, delivery_promise {type, source_required, motion_min_ratio}, segments
[{id, order, role hook|body|proof|cta|transition, layer, source generate|edit|compose|provided,
target_sec, spec, status, produced_path}], tracks {narration per-line + produced_path, music,
captions as DATA}, cost_estimate.billable_generations.

- **Resume/re-render:** đổi 1 segment/1 dòng narration → re-produce đúng node + re-assemble
  phụ thuộc (checkpoint = plan.json, giống stage-assemble Orkas).
- **promise-check chống slideshow:** motion_ratio đo trên primary track, compose card ≠
  motion; floors: motion_led 0.7 / source_led 0.3 / hybrid 0.2; run ≥3 cùng source → warn.
  Port `assessDelivery` (edl.ts:883-948) vào `qa_check`/plan gate.
- **Narration mix ĐÚNG 1 LẦN** ở assemble; caption burn 1 lần cuối (sửa typo = sửa data
  + re-burn, không re-render hình).
- Gate C ký ĐÚNG số billable_generations trước khi gen trả tiền.

### 1.3 Consistency (P1)

- **Character bible** `characters/bible.json`: static vs dynamic features; **front portrait
  sinh 1 lần rồi KHÓA** — không bao giờ regen anchor; side/back suy từ edit. Per-shot refs:
  portrait khớp góc nhìn + frame gần nhất cùng camera (ưu tiên recent-same-camera > older >
  portrait-only). Tả chuyển động bằng đặc điểm thị giác, không bằng tên.
- **Verify keyframe TRƯỚC khi trả tiền animate** (re-roll ảnh rẻ, không re-roll video).
- **Chain policy:** extension_depth cap 2–3 rồi RE-ANCHOR về canonical refs; take bị reject
  không bao giờ vào canon; observed end-state override planned.
- Caps lành mạnh: ≤3 nhân vật, ≤3 bối cảnh, ≤6 shot mặc định.

### 1.4 Retake/QA (P1)

**Retake protocol** (§5.1): 5 verdict Keep / Fix-in-post / Edit-don't-regen / Re-roll (max
2-3 rồi rewrite) / Rewrite (cùng flaw ≥2 take → đổi cơ chế). **Luật 1 biến/retake** (1 mệnh
đề HOẶC seed HOẶC mode HOẶC 1 ref). Budget đặt TRƯỚC take 1 (mặc định 5); nửa budget không
tiến bộ → đổi chiến lược. Take log: `Take N · changed · seed · verdict · evidence` → ghép
`RepairBudget` hiện có. Troubleshoot tree (§5.2): drift→strengthen preserve; camera jump→1
move; replay→completed-beat exclusion; leak→reserved exclusion.

### 1.5 Pacing (nạp vào storyboard planner)

Hook 1–3s; hold explainer 4–8s, social 1–3s, cinematic 10–20s; narration 150–160 wpm,
EN ~2.2–2.7 từ/s; lip-sync EN tin cậy ~16–20 từ/15s; loudness −14 LUFS TP ≤−1. 1 beat nhìn
thấy được + 1 endpoint mỗi clip ngắn.

### 1.6 Chi tiết nhỏ đáng bê nguyên (§8)

Authority order 9 tầng khi mâu thuẫn chỉ đạo; "never invent observation" (không mở được
attachment thì nói rõ, confidence low); fast-lane cho clip đơn giản; thứ tự nén khi thiếu
budget từ; stdout=JSON/stderr=progress; MCP mirror CLI 1:1; skill tự mô tả (`ovs skill X`
dump kiến thức); ingest-from-evidence (probe/OCR trước khi plan); slideshow fail bằng SỐ
không bằng LLM judgment.

### 1.7 Anti-pattern phải né (§11)

Dump JSON vào prompt model; tả lại identity khi đã có seed; nhiều camera move/5s; danh từ
cảm xúc không gesture; đổi trục chính giữa run không hỏi; narration bake 2 lần (double-voice);
re-roll vô hạn cùng prompt; port syntax `@Image1` nguyên xi vào Gemini (phải dùng `[IMAGE n]`).

---

## 2. Chưng cất 01/02/03/04/06/07 (từ bảng ĐỀ XUẤT đã verify)

### 2.1 Cơ chế consistency đáng lấy (theo mức ưu tiên)

1. **Interpolation Chain của StoryGen** (04#2 — "Rất cao"): frame liên tiếp → Gemini viết
   transition prompt → Veo **first+last frame** → ffmpeg concat. ĐÚNG stack Gemini/Veo của
   mình → là xương sống đường video demo. Kết hợp 03#6 (first/last giữa panel) + 01#4
   (previous-frame ref, mô tả "composition only").
2. **Scene-only location frames** (04#1): ảnh bối cảnh gen **0 người** rồi mới gắn char refs
   ở bước video → chặn identity bleed (root cause "đổi mặt" user report). Ghép với RefRole
   ENVIRONMENT sẵn có của `binding.py` (04#6: OmniCast đã có ignore-clause — ArcReel còn
   thiếu, 01#7 xác nhận mình ĐI TRƯỚC — phải ship nó vào đường Veo).
3. **Tách identity vs motion prompt** (03#2): video prompt chỉ age+gender+động từ động tác,
   TÊN chỉ ở still prompt → giảm freeze/sai tên. Khớp luật I2V motion-only seedance.
4. **Identity anchors 6 lớp + Hex palette** (02#4) + **industrial character sheet prompt**
   (02#5) + **4-view turnaround có nhãn** (04#10, 01#5) → nâng `refsheet.py`.
5. **Spatial slots bối cảnh** (03#5: location `available_slots`, panel `slot`) +
   **continuity_snapshot** trang phục/tư thế (02#7) + **layout_description** (02#6) →
   nâng `continuity.py` chặn flip trái-phải/đổi áo.
6. **Ordered refs có label bar** (03#3): sketch→chars→location, mỗi ảnh dán nhãn tên khi
   gửi model — multi-char hết nhầm.

### 2.2 Prompt-craft bổ sung (ngoài seedance §1.1)

- **Two-step content/visual** (01#1): khoá VO text TRƯỚC, visual prompt sau — VO không drift.
- **YAML structured prompt** (01#2: Style/Scene/Composition keys) — prompt có cấu trúc, dễ diff.
- **Writing guides làm SSOT** (01#3) + **prompt override store trong vault** (02#14) để A/B.
- **Multi-phase storyboard** (03#1: plan→cinematographer→acting→detail) — chất lượng ống kính;
  làm dạng optional pass sau MVP.
- **Narration→image_prompt 1:1 EN symbolic** (06#1) cho kênh footage/B-roll.
- **Đừng lạm dụng negative** (03#15): luật dương tính, negative chỉ ở constraint slot.

### 2.3 Pacing/timing

- **Duration ≥ VO length soft-bound** (01#13) + **TTS-first duration cho i2v** (06#8).
- Micro-beats 2–3s trong video prompt (04#7); hook ~4s đầu (01#14); subtitle safe-zone
  bottom 20% (04#8); action_beats 2–4/shot + chọn frame ở climax phase (02#9).

### 2.4 Anti-pattern toàn cụm (né tuyệt đối)

Soft-pass QA khi lỗi (AIComic) — giữ fail-closed; fallback "first 3 chars" khi thiếu ref;
placeholder image giả success (StoryGen); `Promise.all` 1 fail = chết cả batch không resume;
transition fallback chung chung "Cinematic transition" → Veo ra mushy; God-file 3k dòng;
1 voice cho mọi nhân vật; lip-sync chỉ bằng prompt; random B-roll không khớp semantic.

### 2.5 License map (verify 12/12 đúng)

Apache/MIT (được port + attribution): Jellyfish, LocalMiniDrama, AIComicBuilder,
StoryGen-Atelier, seedance, Orkas, Pixelle, MPT, hyperframes.
**AGPL (chỉ học concept):** ArcReel, short-video-factory. **CC BY-NC-SA (cấm thương mại):**
waoowaoo — học ý tưởng, KHÔNG chép prompt nguyên văn vào sản phẩm.

---

## 3. THIẾT KẾ DUAL-ASPECT: Shorts 9:16 → Long 16:9 (trả lời câu hỏi user)

**Quyết định: Shorts-first 9:16 native; video long = EDL re-assembly trên "sân khấu" 16:9
dựng từ chính location refsheet.** Vì sao không làm ngược (master 16:9 rồi crop 9:16):
crop dọc từ 1080p 16:9 chỉ còn 608px ngang → phải upscale 1.78× cho Shorts = mềm nhòe,
trong khi Shorts là nguồn tiền chính, phải nét nhất.

Cách ghép long 16:9 từ tài sản 9:16 (3 tầng, rẻ → đắt):

1. **Scene plate 16:9 per-location** (CỐT LÕI): mỗi location trong cast registry gen THÊM
   1 ảnh nền 16:9 (không người — luật scene-only 04#1, cùng style/palette với refsheet).
   Clip 9:16 đặt giữa plate (full-height, chiếm ~32% ngang; hoặc crop nhẹ 9:16→3:4 còn
   ~42%), viền soft-shadow/edge-blend. KHÔNG blur-fill rác — plate là art thật, đồng nhất
   với thế giới phim vì sinh từ CÙNG reference sheet. Chi phí: 1 ảnh/location, tái dùng
   mọi tập.
2. **Đầu/cuối + chuyển chương gen 16:9 native**: intro, chapter card, establishing shot
   mỗi chương — vài clip Veo 16:9 thật (ClipContract + refs giữ identity xuyên aspect).
3. **(Nâng cấp sau) Re-gen hero clips 16:9**: cảnh đinh của video long re-gen từ ĐÚNG
   ClipContract + reference images cũ — cast registry làm identity portable qua aspect.
   Chỉ làm cho flagship, có gate chi phí.

**EDL làm được điều này vì:** narration/caption là DATA (re-layout theo aspect, không nướng
vào pixel); mỗi tập là segments có produced_path — long plan chỉ TRỎ tài sản cũ, bỏ
hook/CTA per-short, thêm throughline narration + chương; promise-check chạy riêng cho
bản long. Prompt compiler thêm **staging clause** cho mọi shot 9:16: chủ thể + hành động
chính nằm giữa khung (an toàn nếu sau này cần crop 3:4/1:1 cho nền tảng khác).

---

## 4. ĐỊNH NGHĨA DEMO (mục tiêu user 2026-08-02)

**Sản phẩm:** 1 tập phim hoạt hình Short 9:16 (~30–40s, 4–6 shot) nhân vật + bối cảnh đồng
nhất tuyệt đối; sau đó bản long 16:9 ghép ≥2 tập bằng scene-plate. Kênh style: hand-painted
2D an toàn IP (bảng style-safe seedance §4.15).

**Fixture:** script demo VIẾT TAY (không đốt quota Claude batch — WS0 đang giữ); cast 1 hero
+ 1 location + 1 prop; refsheet qua Gemini ordered refs (đường sẵn có).

**Đường chạy demo:** cast registry → refsheet (+plate 16:9) → per-shot keyframe (scene-only
rồi cast-in, ordered refs + label) → ClipContract → prompt_compiler → Veo/Flow (ưu tiên
first+last Interpolation Chain; fallback i2v motion-only) → continuity + consistency_check
fail-closed → assemble 9:16 (TTS + caption data) → plan.json ghi lại toàn bộ.

**Definition of done:** (a) cùng mặt/cùng phục trang/cùng bối cảnh qua mọi shot theo
consistency_check + mắt người; (b) plan.json re-render được 1 segment đơn lẻ; (c) bản long
16:9 dựng từ tài sản tập + plate không re-gen video.

---

## 5. KẾ HOẠCH THỰC THI WS1 (thứ tự build)

| # | Việc | File | Nguồn | Ghi chú |
|---|---|---|---|---|
| 1 | `storyboard/prompt_compiler.py` — ClipContract + compile 9 bước + mode templates (I2V hold/react, FLF2V, R2V role prose) + staging clause + anti-slop mở rộng | storyboard/ | 05 §1.1 | P0-A |
| 2 | Nối storyboard → `veo_pipeline`: Interpolation Chain (first+last) + i2v motion-only fallback + chain-depth cap 2–3 + re-anchor | media/veo_pipeline.py, storyboard/clips.py | 04#2, 05 | P0 demo |
| 3 | Scene-only location frames + cast-in bước video + label bar refs | storyboard/frames.py, binding.py | 04#1, 03#3 | P0 demo |
| 4 | plan.json EDL mỏng (segments/tracks/promise/produced_path) + promise-check | pipeline/edl.py mới | 05 §1.2 | P0-B |
| 5 | Demo runner: fixture script → tập Short end-to-end | scripts/demo_anim_short.py | §4 | Demo |
| 6 | Long composer: scene-plate 16:9 + đặt clip + chapter re-assembly | pipeline/edl.py + render | §3 | Demo phần 2 |
| 7 | refsheet nâng cấp: 6-layer anchors + 4-view + industrial sheet prompt | storyboard/refsheet.py | 02#4/5, 04#10 | P1 |
| 8 | continuity nâng cấp: spatial slots + wardrobe snapshot | storyboard/continuity.py | 03#5, 02#6/7 | P1 |
| 9 | Retake protocol + take log (1 biến/lần, budget 5) | pipeline/retake.py | 05 §1.4 | P1 |
| 10 | Two-step VO-lock + YAML prompt + guides SSOT + vault override | storyboard/, vault | 01#1/2/3, 02#14 | P1 |

Mỗi bước: TDD, suite unit xanh mới merge (luật WORKSTREAMS); gen thật xếp hàng tránh đụng
WS0. Verbatim prompt tham khảo khi code: mở đúng section report (01§4, 02§4+R2, 03§R2,
04§4+R2, 05§4, 06§4+R2).

---

## 6. TRẠNG THÁI BUILD (audit code 2026-08-02 — đọc thật, không đoán)

**ĐÃ CÓ SẴN (không viết lại):**
- `storyboard/models.py`: RefRole+ROLE_IGNORES (ignore-clause per role), CameraShot/Angle/
  Movement + gloss tables, ScreenDirection+OPPOSITE, FrameType FIRST/KEY/LAST, BoardStatus
  (CAST_PENDING barrier), Entity (aliases, all_spellings longest-first), ShotEntityRef
  (role override per shot), **Shot có đủ continuity anchors** (screen_direction, eyeline,
  light_key, motion_vector, parent_shot_id, planned_start_state, observed_end_state,
  **beats_completed/beats_reserved/declared_changes**), RefMapping, Frame (base_prompt vs
  rendered_prompt + mappings ordered), Storyboard.cast_ready.
- `storyboard/clips.py`: ClipPlan/ChainResult, plan_shot_chain (re-anchor khi depth ≥2,
  CLIP_SECONDS=6), build_clip_prompt (i2v MOTION-ONLY đúng seedance: hold-beats 4 mẫu /
  react ≥2s, 1 camera move chỉ ở clip đầu, "End on a settled, continuable pose", constraint
  no-new-chars/no-cut/no-text), extract_last_frame (-sseof -0.2), render_shot_chain
  (provider.convert(start_image, prompt, duration, model, output_path, resolution)).

**GAP XÁC NHẬN TỪ CODE (việc thật của bước 1–2):**
1. **FLF2V chưa có**: render_shot_chain chỉ truyền first frame; không tham số last_frame →
   chưa làm được Interpolation Chain kiểu StoryGen/Jellyfish (first+last). Cần: mở rộng
   provider signature + plan clip theo cặp frame liên tiếp khi shot có FIRST+LAST frames.
2. **build_clip_prompt CHƯA dùng beats_completed/beats_reserved** (field có, prompt không
   chèn "This clip only…/Do not yet…" exclusions) — vá nhỏ, impact cao (replay/leak).
3. **Chưa có staging clause 9:16** (chủ thể giữa khung) trong prompt still/video.
4. `pipeline/edl.py` chưa tồn tại (P0-B).
5. Wiring storyboard→render_real_video/veo_pipeline vẫn là gap chính (biết từ trước).
6. CHƯA audit: `frames.py` (prompt still + scene-only?), `binding.py` chi tiết,
   `pipeline.py` (orchestration), provider Flow/Gemini có nhận last_frame không
   (memory: Flow convert() chưa nhận cả first image — FLOW_ACCEPTS_IMAGE=false;
   đường Gemini/Vertex Veo là ứng viên FLF).

**Bước kế của builder:** audit nốt frames.py/binding.py/pipeline.py + veo_pipeline provider
→ vá gap 2+3 (nhỏ, TDD) → thiết kế FLF2V path (gap 1) → edl.py (gap 4) → demo runner.
