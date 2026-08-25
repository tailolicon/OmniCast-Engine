# GAP Audit 3 — Lớp hoàn thiện phim (ASSEMBLY / EDITING / AUDIO / DELIVERY)

> STATUS: ACTIVE (kiểm toán áp dụng 2026-08-02)  
> Vai trò: **KIỂM TOÁN VIÊN ÁP DỤNG**  
> Input: `REFS_SB_06_ShortVideoEngines.md`, `REFS_SB_07_hyperframes.md`,
> `WS1_Storyboard_Blueprint.md` (§0 P0/P1/P2, §1.2–1.5, §2.3, §3 dual-aspect,
> §5 bảng thực thi, §6 build-state) + code + demo Miko  
> Output duy nhất: file này. Không sửa code / `_refs`.

---

## 0. Kết luận điều hành (đọc trước)

**Demo Miko dừng đúng ở “concat clip thô”.**  
Có `ep1_draft.mp4` + `concat.txt` (6 clip KEEP ghép `-c copy`) + thư mục `cuts/*_pair.jpg`
(đã bóc cặp frame tại mối cắt bằng tay). **Không** chạy lớp finishing mà
`render_real_video.py` đã có sẵn cho kênh VO (BGM mood → caption burn → SFX →
loudnorm −14 LUFS → QA), và **không** đóng vòng EDL (`plan.json` vẫn `status: planned`,
`produced_path: ""`, `tracks.music: {}`).

| Lớp | Stack production (`render_real_video.py`) | Demo Miko (`miko_lantern_ep1`) | Gap |
|-----|-------------------------------------------|--------------------------------|-----|
| EDL / plan.json | Schema `pipeline/edl.py` + demo runner ghi plan | plan tồn tại nhưng **không write-back** clip KEEP | MỘT PHẦN |
| Trim-on-action | VO path trim silence TTS; **không** trim action video | Plan v3 yêu cầu; **chưa làm** (dùng nguyên clip) | BỎ QUA |
| Concat | `concat_scenes` demuxer `-c copy` | `concat.txt` 6 file — tương đương thô | MỘT PHẦN (chỉ bước 1/N) |
| BGM mood map | `music_lib.apply_to_video` + sidechain duck | Plan v3: music-box/lofi — **chưa mix** | BỎ QUA trên demo |
| SFX | Whoosh/ting + diegetic horror; native clip audio copy | Clip Flow có AAC native; **không duck/mix có chủ đích** | MỘT PHẦN |
| Caption | `subtitle_sync` ASS word-level (mạnh) | Silent-cute: caption **không bắt buộc**; plan vẫn có VO text | MỘT PHẦN / sai product mode |
| Loudness −14 LUFS | 2-pass loudnorm cuối render | **Không master** draft | BỎ QUA trên demo |
| promise-check | `edl.assess_delivery` + `qa_check.assess_motion` | Dry-run in demo script; **không gate ep1_draft** | MỘT PHẦN |
| QA cut-seam | Contact sheet 3×2; **không** pair-at-cut | `cuts/B*_pair.jpg` **bằng tay**, không pipeline | MỘT PHẦN |
| Dual-aspect 16:9 | Blueprint §3 | Chưa | BỎ QUA |
| PSNR golden / caption registry | hyperframes | Chưa | BỎ QUA |

**Câu trả lời ngắn cho user:** để Miko “chạy tốt như repo short-engine”,
không cần rewrite gen — cần **finishing pipeline silent-cute** theo thứ tự §3 dưới đây,
tái dùng 70% code đã có ở `render_real_video` / `music_lib` / `qa_check` / `edl`,
chỉ thiếu **nhánh silent** (trim action, BGM cute, SFX-native priority, cut-pair QA, đóng plan).

---

## 1. Nguồn đã rà (bằng chứng)

### 1.1 Research

| File | Trục finishing đã trích |
|------|-------------------------|
| `REFS_SB_06` | TTS-first duration; subtitle (Edge/Whisper/correct); BGM+loudnorm SVF; concat fill audio; social metadata MPT; stop_at; hook; #9 đề xuất bảng |
| `REFS_SB_07` | EDL/timing contract; tracks; caption hard-kill + 16 presets; transitions non-negotiable; PSNR golden; lint→validate→snapshot; narration-first timing; muted video + separate audio |
| `WS1_Storyboard_Blueprint` | P0-B `pipeline/edl.py`; promise-check; narration mix 1 lần; caption DATA; −14 LUFS; §3 dual-aspect; §5 #4/#6; §6 “edl chưa tồn tại” (đã lỗi thời — code đã có schema) |

### 1.2 Code (đọc thật)

| Path | Vai trò |
|------|---------|
| `implementation/src/omnicast/pipeline/edl.py` | VideoPlan / Segment / Tracks / validate_plan / assess_delivery / save·load |
| `implementation/music_lib.py` | Mood folder → pick track → sidechaincompress duck + amix |
| `implementation/subtitle_sync.py` | Whisper/edge words → ASS → burn; presets màu; fill_gaps |
| `implementation/qa_check.py` | stream/silence/blank/hook/freeze/motion_ratio/contact sheet |
| `implementation/render_real_video.py` | concat → BGM → captions → SFX → story cards → **loudnorm −14** → QA |
| `implementation/scripts/demo_anim_short.py` | plan + gen; **không assemble finishing** |
| `implementation/src/omnicast/storyboard/animatic.py` | xfade map + optional music bed (animatic only) |
| `implementation/src/omnicast/media/output_audit.py` | publish audit LUFS −14±2, stereo, sample rate |
| `implementation/src/omnicast/media/music.py` | Module skeleton (placeholder sources) — **không** path production |

### 1.3 Demo artifact

| Path | Quan sát |
|------|----------|
| `.../miko_lantern_ep1/DEMO_STATE.md` | FILM PLAN v3: silent + BGM/SFX, trim-on-action; v2: concat sau s5; vẫn ghi “TTS thuyết minh” mâu thuẫn v3 |
| `.../concat.txt` | 6 KEEP: s1v2…s5 — demuxer list |
| `.../ep1_draft.mp4` | Draft thô (tồn tại theo listing) |
| `.../plan.json` | 5 segment generate, **produced_path rỗng**, music `{}`, captions `[]`, narration 4 dòng VO (product mode cũ) |
| `.../cuts/B{1..5}_{in,out,pair}.jpg` | Bằng chứng operator **đã soi cut-pair thủ công** — đúng hướng QA hyperframes/seedance, chưa code hoá |
| `.../incoming/*.mp4` | Clip KEEP + native audio |

---

## 2. Bảng kiểm toán khuyến nghị / lớp

**Cột trạng thái:**  
`ÁP DỤNG ĐÚNG` · `MỘT PHẦN` · `BỎ QUA` · `VI PHẠM`  
**Severity:** CAO / TRUNG / THẤP — theo tác động “phim silent-cute Shorts chạy tốt như repo”.

### 2.A — Từ REFS_SB_06 (Short video engines)

| # | Khuyến nghị / lớp (nguồn) | Trạng thái | Severity | Bằng chứng | Việc phải làm |
|---|---------------------------|------------|----------|------------|---------------|
| 06-1 | **Subtitle word/sentence sync** (06 §7.2; OmniCast đã lead) | **ÁP DỤNG ĐÚNG** (VO path) | THẤP cho Miko silent | `subtitle_sync.py` whisper + `words_to_segments` + ASS + channel presets; wire `render_real_video.py:4071-4134` | Silent-cute: **tắt** burn caption mặc định; optional title/end card DATA trong EDL |
| 06-2 | **MPT `correct()` force script text** khi ASR lệch (06#5) | **BỎ QUA** | THẤP | Không có Levenshtein merge trong `subtitle_sync.py` | Port khi kênh VO; không ưu tiên Miko silent |
| 06-3 | **Edge cues → sentence aggregate** calm captions (06#6) | **MỘT PHẦN** | THẤP | `words_to_segments` chunk 7 từ/42 ký tự — gần sentence, không match script punct MPT | Optional mode `sentence` sau |
| 06-4 | **TTS-first duration → media** (Pixelle; 06#8, §6.1, §7.1) | **MỘT PHẦN** | TRUNG (VO); N/A silent | VO: scene duration theo audio probe; Miko: duration = clip gen 4–8s, plan `target_sec` | Silent: duration = **action window** sau trim, không TTS |
| 06-5 | **Concat fill to audio length** (MPT/SVF) | **MỘT PHẦN** | TRUNG | `concat_scenes` nối clip có sẵn; không pad/trim khớp VO toàn phim cho anim | Silent: concat sau trim; tổng ≈ beat sheet 34s |
| 06-6 | **BGM + loudnorm voice/BGM levels** (SVF I=-16 voice / I=-25 BGM; 06#12, §8.3) | **MỘT PHẦN** | **CAO** | Production: `music_lib.mix_bgm` volume~0.10 + sidechain; **cuối** `loudnorm=I=-14` (`render_real_video.py:4178-4207`). Demo Miko: **không gọi** | Áp finishing silent: BGM cute + master −14; duck **SFX peaks** (không VO) |
| 06-7 | **Mood-mapped BGM library** (MPT random folder / OmniCast moods) | **MỘT PHẦN** | **CAO** | `music_lib.MOODS` = cinematic/ambient/calm/horror… — **không** `cute` / `music_box` / `lofi` | Thêm mood `cute` (hoặc map silent-anim → calm+handpick) + seed channel |
| 06-8 | **Hook đầu phim** (pacing; 06 + blueprint 1–3s) | **MỘT PHẦN** | TRUNG | QA `hook_frame` hard-fail 0.2/1.0/2.0s (`qa_check.py:279-293`); EDL `SegmentRole.HOOK` | Gán s1 role=hook (plan đã có); enforce duration trim ≤6s opener |
| 06-9 | **Social metadata JSON per platform** (MPT §4.2.3; 06#13) | **MỘT PHẦN** | THẤP | Upload YouTube metadata có; **không** generator title/caption/hashtag multi-platform như MPT | Delivery phase sau khi phim đạt |
| 06-10 | **`stop_at` partial pipeline** (06#9) | **MỘT PHẦN** | THẤP | Pipeline YAML stages; demo `--skip-video`; **không** stop_at=assemble | `demo_anim_short --assemble-only` hữu ích |
| 06-11 | **Batch multi-topic / autoBatch** (06#10–11) | **BỎ QUA** | THẤP | Không liên finishing 1 ep | Ops sau |
| 06-12 | **HTML template library burn** (Pixelle; 06#7) | **MỘT PHẦN** | THẤP | `html_overlay.py` / Remotion partial; Miko không dùng | Optional end-card cute |
| 06-13 | **match_materials_to_script** stock order (06#3–4) | **BỎ QUA** (N/A gen AI drama) | — | Miko không stock B-roll | Không áp |
| 06-14 | **Narration→image 1:1** (06#1) | N/A finishing | — | Lớp gen (GAP 1/2) | — |

### 2.B — Từ REFS_SB_07 (hyperframes)

| # | Khuyến nghị / lớp (nguồn) | Trạng thái | Severity | Bằng chứng | Việc phải làm |
|---|---------------------------|------------|----------|------------|---------------|
| 07-1 | **Declarative EDL timing** `start/dur/track` + relative `id+N` (07 §2.6, §9.1) | **MỘT PHẦN** | **CAO** | `edl.VideoPlan` có order/target_sec/layer/tracks; **không** absolute start chain, **không** relative ref, **không** assembler đọc plan → MP4 | `assemble_from_plan(plan)`: trim spec → concat → mix tracks |
| 07-2 | **Tracks = DATA** (narration/music/captions tách pixel) (07 + blueprint §1.2) | **MỘT PHẦN** | **CAO** | Schema `Tracks` + `NarrationLine.produced_path`; Miko plan: music `{}`, captions `[]`, narration text **không** mix; gen Flow **bake** audio vào MP4 | Silent: music path + SFX gain trong tracks; **cấm** bake VO nếu product silent |
| 07-3 | **Narration mix đúng 1 lần** ở assemble (blueprint §1.2; 07 muted video+audio) | **MỘT PHẦN** / **VI PHẠM** risk | TRUNG | `validate_plan` chặn double-voice (`edl.py:237-243`); demo v2 từng tính “TTS + native audio” = **double-voice** nếu làm | FILM PLAN v3 silent = đúng hướng; **xoá** kế hoạch TTS post-concat trong DEMO_STATE |
| 07-4 | **Caption exit hard-kill + tone table + 16 presets** (07 §4.8, Phụ lục B; errata E3=16) | **MỘT PHẦN** | THẤP silent | ASS end time + fill_gaps; 9 preset màu VN (`SUBTITLE_PRESETS`); **không** karaoke kill GSAP / 16 registry | Silent: skip; VO social sau |
| 07-5 | **ALWAYS transitions; NEVER exit-before-transition** (07 §4.4) | **MỘT PHẦN** / chọn lọc | TRUNG | `animatic.py` xfade map fade/dissolve/wipe; `render_real_video.concat_scenes` = **hard cut only**; silent-cute Shorts **cố ý cut-on-action** (đúng seedance grammar) | Miko: hard cut OK; cấm fade-to-black rỗng giữa beat; optional 2–4f soft chỉ seam s3a→s3b nếu cần |
| 07-6 | **Layout-before-animation + lint/validate gates** overlay (07 §5.1) | **BỎ QUA** (Miko path) | THẤP | Không lint HTML composition cho demo | Khi kinetic/title card |
| 07-7 | **PSNR golden + Docker lock** (07 §5, Phụ lục C) | **BỎ QUA** | TRUNG (regression) | Không harness PSNR; có contact sheet + freezedetect soft | Phase sau cho title card cố định |
| 07-8 | **Snapshot mid-beat / inspect geometry** (07 §5.1) | **MỘT PHẦN** | **CAO** (demo) | `review/*.jpg` + `cuts/*_pair.jpg` **thủ công**; `qa_check.write_contact_sheet` có nhưng không pair-at-cut | Code hoá: extract frame t=end−ε / t=start+ε mỗi seam → `cuts/` + fail soft nếu Δ identity proxy |
| 07-9 | **Beat = unit rebuild** (07 §9 #2) | **MỘT PHẦN** | TRUNG | `with_produced` / `pending()`; demo **không** re-assemble partial | Assemble chỉ pending segments |
| 07-10 | **Muted video + separate audio mix** (07 Never-do #2) | **VI PHẠM** nhẹ (stack AI video) | TRUNG | Flow `abra_r2v_6s` embed AAC native; concat `-c copy` giữ multi audio quirks | Finishing: optional strip → remix BGM+SFX chuẩn hoá 48k stereo |
| 07-11 | **Distributed renderChunk / assemble** | **BỎ QUA** | THẤP | Không cần 34s Short | — |
| 07-12 | **Vocabulary NL → motion params** | N/A finishing | — | VisualDirector | GAP gen |

### 2.C — Từ WS1_Storyboard_Blueprint (P0/P1/P2 + §3 + §5 + §6)

| # | Hạng mục blueprint | Trạng thái | Severity | Bằng chứng | Việc phải làm |
|---|-------------------|------------|----------|------------|---------------|
| BP-P0A | `prompt_compiler` ClipContract | Ngoài scope finishing (gen) | — | GAP 1/2 | — |
| BP-P0B | **`pipeline/edl.py` plan.json + promise-check** | **MỘT PHẦN** | **CAO** | File **đã có** (~326 dòng): PromiseType floors, assess_delivery, validate_plan. Blueprint §6 dòng 275 “chưa tồn tại” = **lỗi thời**. Thiếu: **assemble stage**, write-back demo KEEP, music track fill | Wire assemble + cập nhật blueprint status |
| BP-§1.2 | Resume re-render 1 segment | **MỘT PHẦN** | TRUNG | `pending()` + `with_produced`; demo Flow bridge thủ công, plan không cập nhật path `incoming/*` | `plan.with_produced("s1_c0", "incoming/s1v2_c0.mp4")` cho mọi KEEP |
| BP-§1.2 | **promise-check motion_ratio** floors 0.7/0.3/0.2 | **MỘT PHẦN** | **CAO** | `assess_delivery` + `qa_check.assess_motion`; channel default `motion_min_ratio=0` → **report-only**; Miko plan `MOTION_LED` floor 0.7 nhưng **không chạy** trên draft | Gate `ok` trước ship; silent gen = motion_led gần 1.0 nếu mọi segment generate |
| BP-§1.2 | Caption burn 1 lần cuối (data) | **MỘT PHẦN** | THẤP silent | Render path burn 1 lần; Miko không | Optional |
| BP-§1.2 | Gate C billable_generations | **ÁP DỤNG ĐÚNG** (plan time) | TRUNG | `validate_plan` so khớp count; demo dry-run default | Giữ |
| BP-§1.5 | Pacing hook / hold / **loudness −14 LUFS TP≤−1** | **MỘT PHẦN** | **CAO** | Master trong `render_real_video`; `output_audit.AUDIO_TARGET_LUFS=-14`; **Miko draft không master** | Bắt buộc bước master finishing |
| BP-§2.3 | Duration ≥ VO; TTS-first i2v; hook ~4s; subtitle safe-zone bottom 20% | **MỘT PHẦN** | TRUNG | VO path; ASS margin_v; silent khác driver | Silent: action-first duration |
| BP-§3 | **Dual-aspect Shorts 9:16 → Long 16:9 scene-plate** | **BỎ QUA** | TRUNG (demo phần 2) | Không long composer; DEMO_STATE ghi “long 16:9 scene-plate” chưa làm | Sau ep1 9:16 đạt |
| BP-§4 DoD | plan re-render 1 segment; long từ plate | **BỎ QUA** / fail DoD | **CAO** | produced_path rỗng → re-render plan **không** biết file KEEP | Write-back + assemble |
| BP-§5 #4 | plan.json EDL + promise-check | **MỘT PHẦN** | **CAO** | Schema có; runtime demo lỏng | Hoàn thiện assembler |
| BP-§5 #5 | Demo runner end-to-end Short | **MỘT PHẦN** | **CAO** | Gen/plan có; **finishing vắng** → user thấy “vài video đặt cạnh nhau” (reject v2) | Thêm stage `assemble_silent_short` |
| BP-§5 #6 | Long composer | **BỎ QUA** | TRUNG | — | Sau |
| BP-P1 | Retake / refsheet / continuity | Gen layer | — | GAP 1/2 | — |
| BP-P2 | Agent CLI `omnicast plan validate` | **BỎ QUA** | THẤP | validate_plan chỉ gọi trong demo script | CLI sau |

### 2.D — Code production vs demo (lớp dựng/âm thanh cụ thể)

| # | Lớp | Production code | Demo Miko | Trạng thái | Severity |
|---|-----|-----------------|-----------|------------|----------|
| C-1 | **Concat demuxer** | `concat_scenes` 1573–1584 | `concat.txt` + draft | **ÁP DỤNG ĐÚNG** (bước thô) | — |
| C-2 | **Trim-on-action / cut-on-action** | Không có video action-trim generic; TTS silence trim 1280+ | Plan v3 yêu cầu; clip full length | **BỎ QUA** | **CAO** |
| C-3 | **Normalize stream trước concat** | Bumper normalize; scene compose chung spec | `-c copy` — lệch fps/audio risk | **MỘT PHẦN** | TRUNG |
| C-4 | **BGM mix + duck** | `music_lib.mix_bgm` sidechaincompress | Không | **BỎ QUA** demo / **ÁP DỤNG ĐÚNG** production | **CAO** |
| C-5 | **SFX native keep + mix** | Copy audio scene; `_mix_sfx` / diegetic | Native còn trong clip; không balance vs BGM | **MỘT PHẦN** | **CAO** |
| C-6 | **Loudnorm −14 linear 2-pass** | `render_real_video.py:4186-4207` | Không | **BỎ QUA** demo | **CAO** |
| C-7 | **QA validate_video** | Wire sau render 4230–4256 | Không trên ep1_draft | **BỎ QUA** demo | **CAO** |
| C-8 | **Cut-pair QA** | Không automated | `cuts/*_pair.jpg` tay | **MỘT PHẦN** | **CAO** |
| C-9 | **plan.json write-back** | API có; demo_anim `with_produced` khi `--go` Gemini path | Flow bridge KEEP **không** ghi plan | **VI PHẠM** contract EDL | **CAO** |
| C-10 | **Product mode silent vs VO** | Render assume narration | Plan JSON vẫn VO 4 dòng; DEMO_STATE v3 silent vs v2 TTS | **VI PHẠM** consistency | **CAO** |
| C-11 | **music.py package** | Placeholder ACE/MusicGen | Không dùng | **BỎ QUA** (dead path) | THẤP |
| C-12 | **animatic xfade + music bed** | `animatic.py` cho board stills | Không dùng cho Veo clips | **BỎ QUA** path phim | TRUNG (có thể học) |

### 2.E — Vi phạm / mâu thuẫn quy trình demo (đáng ghi)

| ID | Mô tả | Severity | Bằng chứng |
|----|-------|----------|-----------|
| V1 | User reject v2 “clip vô nghĩa cạnh nhau” → v3 silent+BGM+trim — **finishing vẫn chưa chạy** sau khi đủ KEEP | **CAO** | DEMO_STATE v3 vs chỉ có concat demuxer |
| V2 | `plan.json` tuyên bố motion_led + 5 generate nhưng `produced_path=""` trong khi `incoming/*` đầy | **CAO** | plan.json vs listing incoming/ |
| V3 | DEMO_STATE vừa “KHÔNG narration” (v3) vừa “TTS thuyết minh + mix dưới native” (v2/đoạn sau) | **CAO** | DEMO_STATE dòng 19–20 vs 88–89, 95–96 |
| V4 | `tracks.music: {}` trong khi beat sheet bắt BGM music-box xuyên phim | **CAO** | plan.json + DEMO_STATE v3 |
| V5 | Blueprint §6 “edl.py chưa tồn tại” trong khi code đã ship — doc audit lệch | TRUNG | WS1 §6 vs `pipeline/edl.py` |
| V6 | `not_silent` QA hard-fail trên video **cố ý silent VO** nếu không BGM — silent-cute **phải** có bed nhạc nếu bật QA production | TRUNG | `qa_check.validate_video` hard: not_silent |

---

## 3. Quy trình dựng chuẩn cho demo Miko (silent-cute Shorts)

Chuẩn “chạy tốt như repo” = **đủ lớp** Pixelle/MPT/SVF/Orkas/hyperframes **đã map** sang silent product, không copy narration-first mù.

### 3.1 Tiền điều kiện (đã có từ gen — không thuộc finishing nhưng chặn ship)

1. KEEP list có thứ tự nhân-quả (v2/v3): s1v2 → s2v2 → s3a → s3b → s4 → s5.  
2. Mỗi continuation seam đã verify tail≈head (s3a→s3b đã KEEP verified).  
3. Identity/axis-lock đạt retake (GAP gen).  
4. **Chốt product mode: SILENT** — không TTS, không burn caption word-level, không double-voice.

### 3.2 Pipeline finishing — **thứ tự bắt buộc**

```
[0] LOAD EDL
    load plan.json → map KEEP files → with_produced(segment_id, path)
    validate_plan (orders, ids, billable)
    điền tracks.music = {mood: "cute"|"calm", path: "...", volume: 0.12}
    xoá / ignore tracks.narration nếu silent (hoặc flag delivery_mode=silent)

[1] PROBE + NORMALIZE mỗi clip
    ffprobe: w/h/fps/audio
    re-encode canonical Shorts: 1080×1920 (hoặc 720×1280 nguồn Flow), 30fps hoặc 24fps cố định,
    yuv420p, aac 48k stereo (upmix mono native)
    → work/norm/sN.mp4
    Lý do: concat -c copy trên raw Flow dễ lệch seam âm thanh (hyperframes: separate audio).

[2] TRIM-ON-ACTION (cut-on-action)
    Với mỗi clip, cắt cửa sổ hành động theo beat sheet — KHÔNG giữ full 6s nếu thừa:
      S1: head settle bỏ nếu pad; giữ push-in + nghiêng đầu
      S2: CU spring-back (ngắn ~3–4s)
      S3a/b: giữ từ head match tail; bỏ dead hold >1.5–2s (hyperframes pacing)
      S4: từ khép nếp → glow peak → start dolly-out
      S5: coda 3–4s
    Ghi in_sec/out_sec vào segment.spec (SegmentSource.EDIT semantics) hoặc evidence.
    Output: work/trim/sN.mp4 + duration thật.

[3] (Optional) MICRO-TRANSITION
    Mặc định HARD CUT (silent-cute + cut-on-action).
    Chỉ s3a|s3b nếu residual jump: xfade 2–4 frames HOẶC chấp nhận cut (đã seamless).
    CẤM: fade-to-black giữa body; CẤM invent “cinematic transition” generic (blueprint anti-pattern).

[4] CONCAT PRIMARY PICTURE
    concat demuxer hoặc filter-concat đã normalize
    → work/picture.mp4 (video + native SFX/room tone còn trong audio)

[5] AUDIO GRAPH (silent-cute) — một pass có chủ đích
    Inputs:
      A0 = audio từ picture (native SFX: paper/spring/glow) — gain ~0.9, highpass nhẹ nếu ầm
      A1 = BGM mood cute/lofi/music-box loop trim = dur, fade in 1.5s / out 2.5s, base vol ~0.12–0.18
    Mix:
      sidechaincompress: A1 duck khi A0 peak (SFX native) — cùng pattern music_lib nhưng
      “voice” = SFX bus, không narration
      amix duration=first
    KHÔNG: whoosh/ting transition SFX (sfx_style=off) — phá silent-cute như horror diegetic policy
    KHÔNG: TTS layer
    → work/mixed.mp4

[6] CAPTION / TEXT (optional, tối thiểu)
    Silent-cute Shorts thường:
      - 0 caption, HOẶC
      - 1 title card 0.0–1.2s + 1 end slate (tên ep / series) — DATA trong EDL compose segment
    Nếu burn text: full-line ngắn, safe-zone bottom 20% HOẶC center title; không karaoke.
    subtitle_sync word-level = OFF.

[7] LOUDNESS MASTER (bắt buộc)
    loudnorm I=-14 TP=-1.5 LRA=11 linear 2-pass (copy y hệt render_real_video)
    aac 192k 48k stereo
    → ep1.mp4 (ship candidate)

[8] PROMISE-CHECK
    assess_delivery(plan): motion_ratio ≥ floor MOTION_LED 0.7
    (mọi primary generate đã trim vẫn is_motion=True)
    warn nếu 3 segment cùng prompt/source liên tiếp

[9] QA CUỐI — 2 tầng
    A. Máy (qa_check.validate_video):
       - video_stream, audio_stream, duration_ok
       - not_silent (BGM bed phải audible; min_audio_db điều chỉnh nếu bed rất êm)
       - not_blank, hook_frame hard
       - frozen_frames soft
       - motion_ratio soft/hard theo channel
       - contact_sheet 3×2
    B. Soi CẶP FRAME TẠI MỖI MỐI CẮT (bắt buộc human+auto):
       for i in seams:
         out = frame at end-0.04s of clip i
         in  = frame at start+0.04s of clip i+1
         pair = hstack(out, in) → cuts/B{i}_pair.jpg
       Checklist mắt: cùng xưởng / cùng axis Miko-trái·đèn-phải / không flash identity /
       hành động nối (tail pose ≈ head pose hoặc intentional cut jump chỉ ở S1→S2 CU)
       Đây là “PSNR-lite” vận hành — hyperframes snapshot-at-boundary, không cần Docker golden.

[10] CLOSE EDL + DELIVERY STUB
     save_plan: mọi produced_path, tracks.music.path, total duration evidence
     meta.json: aspect 9:16, delivery_mode=silent_cute, bgm attribution (CC-BY nếu MacLeod)
     (Social metadata / upload = sau khi QA PASS — 06#13)
```

### 3.3 Sơ đồ phụ thuộc (không được đảo)

```
normalize → trim-on-action → concat picture
                                ↓
              native SFX bus ──┤
              BGM mood bed   ──┼→ mix/duck → loudnorm → QA(stream+hook+cut-pairs)
              (no VO)          │
EDL write-back ◄───────────────┘
```

Đảo BGM trước trim → duck sai cửa sổ.  
QA trước loudnorm → false not_silent / false loudness.  
Caption (nếu có) trước master audio (copy-a) hoặc burn rồi master — production hiện burn trước master: **giữ thứ tự** BGM → (optional text) → master → QA.

### 3.4 Map “repo có gì” → bước Miko

| Repo pattern | Bước Miko |
|--------------|-----------|
| SVF/MPT concat + BGM + loudnorm | [4][5][7] |
| Pixelle TTS-first | Thay bằng **action-first** trim [2] |
| Orkas plan + assessDelivery | [0][8] |
| hyperframes snapshot/PSNR | [9B] cut-pair (PSNR full = sau) |
| hyperframes tracks DATA | [0][5] music path trong plan |
| OmniCast `render_real_video` finishing chain | Tái dùng music_lib + loudnorm + qa_check; **tắt** subtitle/whoosh; **thêm** trim+cut-pair |

---

## 4. Ma trận “đã có code / thiếu wire / thiếu feature”

| Capability | Code tồn tại? | Wired production VO? | Wired demo Miko? | Effort hoàn thiện silent |
|------------|---------------|----------------------|------------------|--------------------------|
| EDL schema + validate + promise | Có `edl.py` | Partial (demo plan) | Plan ghi, không assemble | **S** wire |
| Assemble from plan | **Không** | No | No | **M** |
| Trim-on-action video | **Không** (chỉ TTS silence) | No | No | **M** |
| Concat | Có | Yes | Manual demuxer | **S** |
| BGM mood pick+duck | Có `music_lib` | Yes | No | **S** (+ mood cute) |
| SFX policy silent | Partial (`sfx_style=off`) | Horror/explainer | No | **S** |
| Loudnorm −14 | Có | Yes | No | **S** |
| subtitle_sync | Có (dư thừa silent) | Yes | No (đúng nếu silent) | — |
| QA streams/hook/motion | Có | Yes | No | **S** |
| Cut-pair extract | **Không** auto (folder tay) | No | Manual | **S** |
| PSNR golden | Không | No | No | **L** |
| Dual-aspect long | Không | No | No | **L** |
| Social metadata LLM | Partial upload | Partial | No | **S–M** |

---

## 5. TOP-10 việc sửa ngay (xếp hạng impact finishing)

| Hạng | Việc | Severity | Effort | File đích gợi ý | Xong khi |
|------|------|----------|--------|-----------------|----------|
| **1** | **Stage `assemble_silent_short`**: normalize → trim windows → concat → BGM duck SFX → loudnorm −14 → out | CAO | M | `scripts/demo_anim_short.py` hoặc `pipeline/assemble.py` + tái dùng `music_lib`/`qa_check` | `ep1.mp4` ≠ raw concat; ffprobe stereo 48k; loudness ~−14 |
| **2** | **Write-back plan.json** mọi KEEP (`incoming/*` → `produced_path`, status=produced) + `tracks.music` | CAO | S | `edl.save_plan` sau bridge/assemble | `load_plan` → `pending()==[]` |
| **3** | **Trim-on-action table** theo beat sheet v3 (in/out sec per shot) trong plan.spec | CAO | M | plan segments + ffmpeg trim | Phim ~30–34s, không dead-hold |
| **4** | **BGM mood cute/lofi** (folder hoặc map calm + curated track) mix xuyên phim, sfx_style=off | CAO | S | `music_lib.py` MOODS + assets/music/cute/ | Nghe bed ấm; SFX native vẫn đọc được |
| **5** | **QA cut-pair tự động** tại mọi seam + gate soft/human checklist | CAO | S | `qa_check.py` + `cuts/` | `B*_pair.jpg` sinh từ pipeline; không ship nếu operator reject seam |
| **6** | **Chạy `validate_video` + `assess_delivery` trên artifact cuối** (silent: not_silent = BGM) | CAO | S | demo assemble tail | status.json / log PASS |
| **7** | **Chốt product mode silent** trong plan + DEMO_STATE: xoá TTS post-concat; narration track empty hoặc `delivery_mode` | CAO | S | plan.json schema note / demo fixture | Không double-voice; doc một nguồn |
| **8** | **Normalize audio/video trước concat** (tránh `-c copy` lệch) | TRUNG | S | assemble | 1 audio stream sạch |
| **9** | Optional **title/end compose card** (không karaoke) | THẤP–TRUNG | S | EDL compose segment / bumper | Series brand |
| **10** | **Dual-aspect long 16:9 scene-plate** (blueprint §3/#6) — sau khi 9:16 PASS | TRUNG | L | edl + plate gen | Demo phần 2 DoD |

**Không vào TOP-10 finishing (để GAP khác):** prompt_compiler, FLF identity, PSNR Docker, social hashtag LLM, autoBatch, stock match.

---

## 6. Phân loại tổng hợp theo “lớp phim”

| Lớp | Verdict tổng | Ghi chú 1 dòng |
|-----|--------------|----------------|
| **ASSEMBLY (EDL + concat)** | **MỘT PHẦN** | Schema Orkas-grade; assembler + write-back demo thiếu |
| **EDITING (trim, transition, cut grammar)** | **BỎ QUA** trên demo | Plan v3 đúng; code trim-action chưa; hard cut thô |
| **AUDIO (BGM/SFX/loudnorm)** | **ÁP DỤNG ĐÚNG** production VO; **BỎ QUA** demo | music_lib + −14 có sẵn — không gọi cho Miko |
| **CAPTION** | **ÁP DỤNG ĐÚNG** VO; **đúng khi tắt** silent | Đừng burn subtitle_sync lên silent-cute |
| **DELIVERY (promise, QA, metadata)** | **MỘT PHẦN** | QA/promise code có; cut-pair tay; social mỏng; dual-aspect chưa |
| **Hiperframes contract hoàn chỉnh** | **MỘT PHẦN** | Thiếu relative timing, lint overlay, PSNR |
| **Short-engine parity (06)** | **MỘT PHẦN** | Production gần MPT/SVF; demo lùi về pre-BGM |

---

## 7. Anti-pattern phải tránh khi “vá finishing” (từ 06/07 + demo)

| Anti-pattern | Nguồn | Vì sao |
|--------------|-------|--------|
| TTS + native clip voice cùng lúc | Orkas/blueprint double-voice; DEMO_STATE v2 | Phim ồn, sai silent-cute |
| Random BGM không mood | 06 anti-pattern | Cute short + horror bed = vỡ genre |
| Whoosh transition trên silent acting | render sfx full; hyperframes grammar | Phá diegesis |
| Fade/xfade generic “cinematic” che jump identity | blueprint §2.4 | Mushy; che lỗi gen |
| Ship concat `-c copy` không loudnorm/QA | demo hiện tại | “Như repo” = có master + gate |
| Coi contact sheet 3×2 thay cut-pair | hyperframes mid-beat ≠ boundary | Lỗi seam nằm **giữa** 2 shot |
| Port AGPL SVF code loudnorm | 06 license | Chỉ concept; OmniCast đã có loudnorm MIT/Apache stack |
| PSNR golden host-Chrome | 07 | False fail; chưa cần cho ep1 |

---

## 8. Định nghĩa xong (Definition of Done) — finishing Miko ep1

- [ ] `plan.json`: mọi primary segment `produced_path` trỏ file thật; `tracks.music.path` set; silent mode rõ  
- [ ] `ep1.mp4` (không chỉ `ep1_draft`): đã trim-on-action, BGM cute, SFX native audible, **không** VO  
- [ ] ffprobe: video 9:16, audio stereo ~48 kHz; loudness ≈ −14 LUFS (±2)  
- [ ] `assess_delivery.ok == True` (motion_led)  
- [ ] `validate_video.ok == True` (hook/not_blank/not_silent với BGM)  
- [ ] `cuts/B*_pair.jpg` đủ mọi seam; operator (hoặc gate) PASS continuity axis  
- [ ] DEMO_STATE một dòng: “FINISHING PASS” + path artifact — không còn kế hoạch TTS mâu thuẫn  

---

## 9. Đã đọc (index kiểm toán)

**Research:**  
`docs/research/_briefs/COMMON_CONTEXT.md`, `_briefs/g3_audit_finishing.md`,  
`REFS_SB_06_ShortVideoEngines.md` (§0, §5–9, §11–12),  
`REFS_SB_07_hyperframes.md` (§0, §2, §4.4–4.8, §5, §7, §9, Phụ lục A–C),  
`WS1_Storyboard_Blueprint.md` (toàn file §0–§6).

**Code:**  
`implementation/src/omnicast/pipeline/edl.py` (full),  
`implementation/music_lib.py` (full),  
`implementation/subtitle_sync.py` (full),  
`implementation/qa_check.py` (full),  
`implementation/render_real_video.py` (concat 1573+, SFX 853–1185, finishing 4040–4258),  
`implementation/scripts/demo_anim_short.py` (plan/assemble absence),  
`implementation/src/omnicast/storyboard/animatic.py` (xfade/music head),  
`implementation/src/omnicast/media/music.py` (placeholder),  
`implementation/src/omnicast/media/output_audit.py` (LUFS),  
`implementation/src/omnicast/media/render_engine.py` (AUDIO_MASTER_FILTER grep).

**Demo:**  
`implementation/output/products/anim_demo/miko_lantern_ep1/DEMO_STATE.md`,  
`plan.json`, `concat.txt`, listing `incoming/`, `cuts/`, `review/`, `tails/`.

**Không đọc / không cần cho audit này:** toàn bộ `_refs/*` source (đã tin reports 06/07), gen-side GAP 1/2 chi tiết.

---

*File kiểm toán áp dụng — chỉ `docs/research/GAP_3_finishing.md`. Không sửa code, không sửa `_refs`.*
