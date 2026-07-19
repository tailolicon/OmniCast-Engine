# BÁO CÁO NGHIÊN CỨU WS2 — TTS / GIỌNG ĐỌC (READ-ONLY)

> Sinh bởi agent nghiên cứu WS2, 2026-07-19. Phạm vi: WORKSTREAMS_ParallelUpgrade.md §WS2.
> Kênh trọng tâm: `true_dread_files_us` — giọng kể chuyện đêm khuya, `edge:en-US-ChristopherNeural`, all-edge, pause + pacing là linh hồn thể loại.

## 0. Phát hiện cấu trúc quan trọng nhất (đọc trước khi đi tiếp)

Có **HAI đường TTS song song, không dùng chung code prosody**:

- **Đường A — monolith render** (`render_real_video.py`): đây là đường THẬT SỰ render video. Nó có logic prosody riêng (`render_voice` → `_render_voice_edge` / `_render_voice_provider`), tự map pace/emphasis/pause thành rate/pitch/apad.
- **Đường B — package** (`media/tts.py` `TTSModule` → `media/voice_router.py` `VoiceRouter`): dùng bởi pipeline/API. Đường này **hoàn toàn mù prosody** — `VoiceRouter.synthesize()` gọi `provider.generate(text, model=, voice_clone_path=, output_path=)` (voice_router.py:226-231), **không bao giờ truyền speed/rate/pitch/pause**. Protocol `ITTSProvider.generate` (interfaces.py:139-146) thậm chí không khai báo các tham số đó, dù provider Kokoro/Piper/Chatterbox có nhận `speed`.

Hệ quả: mọi thứ "prosody có tác dụng" chỉ đúng cho đường A. Khi WS4 port render vào package, nếu không mang theo logic này, prosody sẽ **biến mất im lặng**.

---

## 1. BẢN ĐỒ HIỆN TRẠNG — script.json prosody sidecar → provider → audio

### 1.1 Nơi SINH (WS0, chỉ để hiểu contract — không đụng)
- `agents/narrative_pipeline.py:1038-1043` — `StoryScene`: `pace` (slow/normal/fast), `pause_after_ms` (0-1500), `emphasis: list[str]`.
- `narrative_pipeline.py:3450-3459` — prompt annotation: `pause_after_ms` "thường 0-250, chỉ hiếm khi 400-900"; emphasis chỉ chứa từ có mặt trong beat.
- `narrative_pipeline.py:3649-3654` — emphasis được lọc chỉ giữ từ thật sự xuất hiện trong voiceover; `narrative_pipeline.py:3684-3685` — hook mặc định `pace="slow", pause_after_ms=500`.
- `models/script.py:114-117` — `ScriptScene`: schema đóng băng của interface.

### 1.2 Nơi TIÊU THỤ (đường A, render thật)
- Load sidecar: `render_real_video.py:2190-2206` (ưu tiên `script.json` hơn prose) → `_parse_json_script` (196-211) đọc `pace` (validate slow/normal/fast, else ""), `pause_after_ms` (clamp 0-2000), `emphasis`, `segment` vào `Scene` (80-88).

### 1.3 Bảng: field prosody nào được TÔN TRỌNG / bị NUỐT

| Field | Đường edge (dùng bởi horror) | Đường non-edge (kokoro/piper/chatterbox/xtts) | Đường package B |
|---|---|---|---|
| **pace** | ✅ TÔN TRỌNG. `_scene_rate` (2761-2780): slow→base−15%, fast→base+12%; truyền `rate` vào `edge_tts.Communicate(rate=)` (1162) — edge honor natively | ⚠️ MỘT PHẦN. Native `speed` provider bị **cố ý bỏ** (comment 1209-1213 "kokoro speed không land"); thay bằng ffmpeg `atempo` post-pass (1214-1223), **clamp 0.85-1.15** → slow tính ra −23% (0.77) bị chặn ở 0.85, mất bớt độ chậm | ❌ NUỐT — không truyền speed |
| **emphasis** | ❌ **NUỐT IM LẶNG cho horror.** `_scene_pitch` (2789-2808) chỉ nâng pitch +8Hz cho CẢ dòng, và **chỉ khi** narration khớp `_num_re` (số ≥3 chữ số/%/scale word) HOẶC từ emphasis chứa digit (2795-2799). Truyện creepy không có số → emphasis KHÔNG ra audio. Và ngay cả khi fire cũng là pitch cả câu, **không bao giờ per-word** | ❌ NUỐT HOÀN TOÀN. `_render_voice_provider` nhận tham số `pitch` (1194) nhưng **không dùng** — thân hàm chỉ xử lý rate→atempo, pitch bị bỏ | ❌ NUỐT |
| **pause_after_ms** | ✅ TÔN TRỌNG. `_compose` (2870-2880) apad=pad_dur nối im lặng SAU scene | ✅ TÔN TRỌNG (cùng code path, apply trên mp3 sau synth) | ❌ NUỐT |

Ghi chú bổ sung:
- Có thêm pause **heuristic** không từ sidecar: `_lead_silence` (2813-2822) chèn ~1s TRƯỚC scene là câu hỏi tu từ.
- `_trim_silence` (1052-1082, gọi ở 1229) và edge `_trim_to_span` (1108-1148, pad 0.08s) **cắt sạch** im lặng đầu/cuối clip → mọi "breath"/hold do TTS tự tạo bị xoá, chỉ còn pause do apad scripted. Kiểm soát tốt nhưng nghĩa là pause CHỈ nằm ở ranh giới scene.
- Master cuối dùng loudnorm **linear 2-pass** (3127-3143) để không "bơm" im lặng dramatic — đúng hướng, tôn trọng pause.

### 1.4 Nghịch lý horror lớn nhất
`tts_chatterbox.py:4-6` nói rõ Chatterbox có `exaggeration` dial "lý tưởng cho measured dread kênh horror cần, thứ Kokoro không tạo được". **Nhưng** `channels/true_dread_files_us.json:15-19` để voice chain 100% edge (`ChristopherNeural` + 2 fallback edge). Provider biểu cảm được xây RIÊNG cho horror **không nằm trong chain của kênh horror**.

---

## 2. DANH SÁCH LỖ HỔNG — xếp theo tác động NGHE với creepy-storytelling

**G1 (Critical) — emphasis bị nuốt im lặng cho horror.** `_scene_pitch` guard số (2795-2799) khiến từ nhấn creepy ("still there", "it hadn't moved", "behind me" — không digit) tạo ZERO thay đổi audio. Thiết bị prosodic quan trọng nhất của kể chuyện đêm khuya (dồn sức nặng vào đúng từ rợn người) không bao giờ ra tiếng. Ngay cả khi fire cũng chỉ là pitch cả dòng, không per-word.

**G2 (Critical) — delivery trong-scene phẳng; chỉ rate giữa các scene đổi.** Mọi provider chỉ có một scalar rate/scene (edge rate hoặc atempo). Không có động lực trong câu — không chậm dần vào khoảnh khắc reveal, không rise/fall. vfact benchmark ghi target pitch std ~102Hz "very expressive" (docs/vfact_benchmark.json:60); edge rate/pitch cố định phẳng hơn nhiều. Công cụ DUY NHẤT làm được (Chatterbox exaggeration) không được kênh horror dùng (xem 1.4).

**G3 (High) — pause thô và tách rời với audit chấm nó.** pause_after_ms honor như apad phẳng; nhưng (a) writer đặt default 0-250ms (narrative_pipeline:3458) → ít pause chạm ngưỡng 400ms "dramatic"; (b) `_trim_silence` xoá mọi hold tự nhiên → pause chỉ ở ranh giới scene; (c) **không có kiểm tra** silence thực trong waveform khớp pause_after_ms. `inspect_pacing` (output_audit.py:201-311) chỉ đếm pause≥400ms toàn video, không đối chiếu per-scene.

**G4 (High) — không có benchmark NGHE hệ thống; pacing gate phẳng & explainer-tuned.** `inspect_pacing` tồn tại nhưng calibrate cho vfact EXPLAINER (nhanh, info-dense). Horror **opt-out hoàn toàn** khỏi flat-delivery gate qua `pacing_flat_ok:true` (true_dread_files_us.json:14; output_audit.py:159-163). Nghĩa là kênh horror **không có gate chất lượng delivery nào** — giọng phẳng pass im lặng. Không đo per-scene (rate thực vs pace ý định) hay (silence thực vs pause_after_ms).

**G5 (Medium) — non-edge nuốt pitch & atempo không chậm quá 0.85.** `_render_voice_provider` nhận nhưng bỏ `pitch` (1194-1239); atempo clamp floor 0.85 (1216) chặn slow sâu. Chỉ ảnh hưởng nếu horror rời edge — nhưng đúng là rào cản khi muốn nhận Chatterbox (G2).

**G6 (Medium) — đường package mù prosody + trùng lặp logic.** VoiceRouter/TTSModule không truyền prosody (xem §0). Logic prosody chỉ sống trong monolith. Rủi ro: khi port sang package (WS4) prosody mất im lặng nếu không mang theo.

**G7 (Low/Structural) — một giọng cho cả compilation.** `voice_chain` resolve một lần (2084-2098), dùng cho mọi scene; `Scene.segment` (story title) tồn tại và dùng cho story cards (456-537) nhưng **không** có mapping voice per-story. Compilation 3 truyện đọc bằng MỘT narrator. `voice_seed` là thiết bị **idiolect chữ viết** (test_craft_upgrades.py:191-251), không nối với voice TTS nào.

---

## 3. KẾ HOẠCH NÂNG CẤP — xếp hạng

Nguyên tắc đo khách quan (dùng lại phương pháp signal của `inspect_pacing`): với mỗi scene synth ra, đo (a) trailing silence bằng `silencedetect` khớp `pause_after_ms` ±80ms; (b) syllable-rate/scene qua band-pass envelope peak-picking, assert scene slow < body×0.85, fast > body×1.10; (c) với emphasis: dùng per-word timing trong `.words.json` (edge phát WordBoundary chính xác, 1167-1170) đo f0/energy spike quanh từ nhấn vs baseline. Giữ một dread test line cố định (đã có: gen_voice_refs.py:18-21) để snapshot metric per-provider, bắt regression.

**P1 — Benchmark NGHE khách quan per-scene + per-provider (nền tảng cho mọi mục sau).**
File: mới `scripts/tts_bench.py` + có thể mở rộng `media/output_audit.py`. Effort **M**. Rủi ro thấp (read-only đo lường). Đo: 3 assertion (a)(b)(c) ở trên; xuất JSON metric + so vfact targets (docs/vfact_benchmark.json:39-43,67-76). Đây là "tai khách quan" WS2 thiếu.

**P2 — Cho emphasis ra audio thật cho kênh pacing_flat_ok (sửa G1).**
File: `render_real_video.py` (`_scene_pitch`, và tách dòng quanh từ nhấn trong `_compose`). Effort **M**. Rủi ro trung bình (seam artifact khi splitting). Cách khả thi vì edge KHÔNG hỗ trợ SSML `<emphasis>`: bỏ guard-số cho channel `pacing_flat_ok`, và hiện thực nhấn bằng **micro-beat ~120-200ms trước từ nhấn + dip rate cục bộ** (split narration tại từ nhấn, synth 2-3 mảnh, nối) HOẶC tối thiểu nâng volume (edge hỗ trợ `volume`) + pitch cả cụm. Đo bằng (c) của P1: f0/energy spike tại timestamp từ nhấn.

**P3 — A/B Chatterbox cho giọng horror (sửa G2), gate bằng P1.**
File: chạy `scripts/chatterbox_spike.py` + `channels/true_dread_files_us.json` (thêm `chatterbox:...` vào chain thử nghiệm) + `_render_voice_provider` (áp pitch/clamp). Effort **M** (code) / **S** (spike đã có). Rủi ro: Chatterbox chạy trong `.venv_chatterbox` qua persistent worker (tts_chatterbox.py:57-93), CPU ~RTF cao, cần đo throughput. Đo: pitch std, dramatic feel bằng P1 so edge:Christopher. Nếu Chatterbox thắng rõ → cân nhắc làm primary với edge fallback (giữ luật neural-only, fail > robot).

**P4 — Bỏ atempo floor cho slow + áp pitch ở non-edge (sửa G5).**
File: `render_real_video.py:1214-1223`. Effort **S**. Rủi ro thấp (atempo tới 0.5 vẫn preserve pitch). Đo: (b) của P1 xác nhận slow-scene rate giảm đủ sâu.

**P5 — Per-scene pause verification gate (sửa G3).**
File: `media/output_audit.py` (thêm check per-scene, đọc từ `_assets/scene_XX.words.json` + product sidecar). Effort **M**. Rủi ro thấp. Đo: assert silence thực đuôi scene ≈ pause_after_ms; cảnh báo nếu tất cả gap đồng đều (max_uniform_gap_share, đã có threshold vfact:75).

**P6 — Prosody-aware gate cho horror thay vì opt-out phẳng hoàn toàn (sửa G4).**
File: `media/output_audit.py:159-163` + `docs/vfact_benchmark.json` (thêm profile ngưỡng "narrative_slowburn"). Effort **M**. Rủi ro trung bình (tinh chỉnh ngưỡng để không false-fail deadpan). Thay vì tắt sạch, dùng ngưỡng riêng: vẫn đòi ≥N dramatic pause, vẫn đòi hook chậm hơn body, chỉ nới flat-delivery std/mean. Đo: gate chạy trên render horror thật, không false-positive.

**P7 — Mang prosody vào đường package khi port (sửa G6).**
File: `media/voice_router.py`, `media/tts.py`, `media/providers/interfaces.py` (mở rộng `generate` nhận `speed/rate/pitch` optional), `media/models.py` (`TTSRequest`). Effort **L**. Rủi ro cao (đụng interface chung, cần suite xanh). Chỉ làm khi WS4 port render — nếu không, prosody hiện chỉ sống ở monolith. **Cảnh báo**: đây là interface được nhiều nơi dùng, phải qua điều phối.

---

## 4. QUICK WINS (1 buổi)

1. **Chạy spike Chatterbox vs edge:Christopher** trên dread line cố định (`scripts/chatterbox_spike.py`, `scripts/gen_voice_refs.py` đã sẵn) → nghe A/B ngay, không đổi code. Trả lời câu "Chatterbox có đáng không" bằng bằng chứng.
2. **Script đo pause thực khớp pause_after_ms**: synth vài scene, `silencedetect` đuôi, assert ≈ script. ~40 dòng, dùng lại pattern output_audit.py:236-242. Effort S.
3. **Bỏ guard-số trong `_scene_pitch` cho channel `pacing_flat_ok`** (render_real_video.py:2795-2799): để emphasis nâng pitch/volume cả cụm cho horror thay vì zero. 1 điều kiện `if`. Đo bằng f0 quanh WordBoundary. Effort S.
4. **Nới atempo floor 0.85→0.80** và **áp `pitch` trong `_render_voice_provider`** (1216, 1222) để non-edge nhận slow sâu + pitch. Effort S.
5. **Giảm độ hung của trim cho horror** (`_trim_silence` pad 0.08→lớn hơn có điều kiện) để hold tự nhiên sống sót. Effort S, cần nghe kiểm chứng.

---

## 5. MULTI-VOICE cho thoại + per-story voice variation (khớp voice_seed)

**Làm rõ `voice_seed`**: đây là **idiolect chữ viết** (mẫu câu first-person để writer giữ mỗi truyện một giọng-viết riêng, exempt khỏi freshness dedup — test_craft_upgrades.py:191-251), **KHÔNG phải** timbre TTS. Nên "khớp voice_seed" = gán mỗi story một **timbre TTS khác nhau, ổn định** để 3 giọng-viết distinct nghe thành 3 narrator distinct.

**Khả thi ngay — không cần dep mới (khuyến nghị):** edge có hàng trăm giọng nam narrator distinct (`en-US-Christopher/Guy/Andrew/Eric/Brian/Davis/Roger/Steffan/Tony...` — đã liệt kê ở voice_router.py:76-80). `Scene.segment` + `_detect_story_segments` (render_real_video.py:456) đã cho ordinal mỗi story. Chỉ cần:
- Thêm chọn voice per-story trong `_compose`: `hash(story_id/voice_seed) % pool` → timbre ổn định (deterministic → cùng story cùng giọng mỗi render).
- Plumb voice override xuống `render_voice` (hiện dùng một `voice_chain` cho tất cả — 2846-2848).
- File đụng: `render_real_video.py` (`_compose`, `Scene` thêm field voice hoặc derive từ segment ordinal). Effort **M**, rủi ro thấp, giữ neural-only.
- Đo: mỗi story một voice_id khác nhau trong log; nghe xác nhận chuyển narrator ở ranh giới story card (2870-2880 đã có pause để "landing" chuyển giọng).

**Nâng cao — clone timbre khớp giọng-viết (xtts/f5/chatterbox):** clone 3 reference distinct/story. `gen_voice_refs.py` đã sinh ref edge deep-male có thể seed clone Chatterbox (timbre edge + emotion Chatterbox). Nặng hơn (cần ref clips, RTF CPU cao), rủi ro chất lượng clone không đều. Chỉ nên sau khi P3 chứng minh Chatterbox thắng. Effort **L**.

**Multi-voice cho THOẠI nhân vật trong 1 truyện (dialogue):** hiện **không biểu đạt được** — narration là first-person monolithic, sidecar không có speaker tag, schema đóng băng. Muốn có phải writer đánh dấu speaker (WS0) — ngoài phạm vi WS2, chỉ nêu để biết giới hạn. Per-story narrator (ở trên) là phần khả thi và đáng làm nhất.

---

## Phụ lục — file liên quan (absolute path)
- `E:\Project\OmniCast Engine\implementation\render_real_video.py` — đường TTS thật (prosody consumption): 80-88, 196-211, 1050-1284, 2750-2880, 3123-3157
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\voice_router.py` — routing + fallback (226-231 nuốt prosody)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\tts.py` — TTSModule (đường package)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\providers\tts_edge.py`, `tts_local.py` (Kokoro/Piper/XTTS/F5), `tts_chatterbox.py`, `interfaces.py:139-146`, `registry.py:75-82`
- `E:\Project\OmniCast Engine\implementation\src\omnicast\media\output_audit.py:159-311` — `inspect_pacing` (nền benchmark)
- `E:\Project\OmniCast Engine\implementation\docs\vfact_benchmark.json` — targets pause/rate khách quan
- `E:\Project\OmniCast Engine\implementation\channels\true_dread_files_us.json:14-22` — voice chain horror (all-edge, pacing_flat_ok)
- `E:\Project\OmniCast Engine\implementation\src\omnicast\agents\narrative_pipeline.py:1038-1043,3450-3459,3649-3685` — nơi SINH prosody; `models/script.py:114-117` — schema đóng băng
- `E:\Project\OmniCast Engine\implementation\scripts\chatterbox_worker.py`, `chatterbox_spike.py`, `gen_voice_refs.py` — hạ tầng expressive/clone đã có
- `E:\Project\OmniCast Engine\implementation\tests\unit\test_tts.py`, `tests\media\test_f5tts.py` — test hiện có (không test prosody realization)
