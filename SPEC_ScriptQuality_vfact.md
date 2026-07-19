> STATUS: ACTIVE (2026-07-08) — work-order nâng chất video lên chuẩn vfact
> TIẾN ĐỘ 2026-07-08: mục 1 ✅ (schema pace/pause_after_ms/emphasis + Writer prompt + Critic chấm prosody + renderer/TTS per-scene rate/pitch/pause; kokoro/piper nhận speed) · mục 2 ✅ (`implementation/docs/vfact_benchmark.json` máy đo + Critic PROSODY STATS/MACHINE FLAGS) · mục 3 ✅ (beat-words 18→12; SFX marker tự động tại twist/số liệu + zoom-in punch tại stat/emphasis/twist — làm 2026-07-08 vòng 2) · mục 4 ✅ đã có sẵn (music_lib sidechaincompress) · mục 5 ✅ (`output_audit.inspect_pacing()` fail QA khi flat/thiếu pause, wire vào inspect_product).
> TIẾN ĐỘ 2026-07-08 (vòng 2 — "Việc còn lại" mục 1+2+3): word-floor ÉP ở nhánh evolution (evolved winner giờ qua `WriterAgent.ensure_length` → hết cảnh script 5 phút; evolution prompt+parser giữ prosody, max_tokens 4000→8000 vì 4000 cắt cụt = nguyên nhân 748 từ) · Critic MACHINE FLAGS thêm hook-payoff ($/%/số-nghìn ở hook phải trở lại body — rule 12a) + detect listicle đếm số (rule 10a) · renderer tự chèn SFX (whoosh tại twist/pause, ting tại emphasis) + zoom-in tại stat/twist. Verify: 4 test offline PASS + suite agent 75 passed/2 skip. **CÒN LẠI: render 1 video thật để nghiệm thu A/B (mục Nghiệm thu — cần restart backend + provider credit), shader transitions hyperframes (mục còn lại #4), meme clip pattern-interrupt (#5 — gap nguồn asset).**

# SPEC — Nâng chất script→video theo chuẩn vfact

Video mẫu: `YTDown.com_YouTube_1093-Bat-ChatGPT...ucqR7A7BelQ...1080p.mp4` (root). Đối chiếu thêm `video_analysis.md` (đã phân tích script/voice/pacing 1 video mẫu trước đó — ĐỌC TRƯỚC).

## Việc theo thứ tự (mỗi mục 1 PR, chạy thử 1 video sau mỗi PR)
1. **Prosody per-câu (nhấn nhá nhanh/chậm) — QUAN TRỌNG NHẤT.**
   - Script schema: mỗi scene thêm `"pace": "slow|normal|fast"` + `"pause_after_ms"` + `"emphasis": [từ]`. Writer prompt yêu cầu LLM gắn pace theo vai trò câu (hook/twist=fast, số liệu/kết luận=slow, chuyển đoạn=pause 400-700ms).
   - TTS: Edge-TTS nhận `rate=+15%/-15%` per-segment (đã hỗ trợ SSML prosody); Kokoro: điều chỉnh `speed` param per-scene. Ghép: chèn silence đúng `pause_after_ms` giữa các đoạn thay vì khoảng lặng đều.
2. **Phân tích video vfact làm chuẩn số** (agent chạy local): ffprobe + whisperx video mẫu → đo: WPM trung bình/theo đoạn, phân bố độ dài câu, mật độ cắt cảnh (giây/cảnh), thời điểm SFX/zoom. Ghi thành `docs/vfact_benchmark.json` → Critic chấm script mới theo các số này (WPM variance ≥ X, câu ngắn xen dài...).
3. **VFX/hình:** mật độ cắt cảnh vfact thường 2-4s/shot với zoom-pan liên tục — tăng `beat-words` xuống (~10-12 từ/beat), bật kenburns đa hướng + shader transitions (hyperframes đã có trong _refs); chèn SFX marker tự động tại twist/số liệu (assets/sfx đã có từ VideoToolsPro pattern, timeline SFX track UI đã có).
4. **Âm thanh:** BGM sidechain-duck theo VO (ffmpeg `sidechaincompress`), SFX whoosh tại chuyển cảnh lớn; giữ loudnorm -14 LUFS đã có.
5. **Vòng hiệu chỉnh tự động:** render → output_audit thêm chỉ số pacing (WPM per đoạn từ words.json, số cắt cảnh/phút) so với benchmark → nếu lệch >20% thì fail QA kèm gợi ý.

## Đánh giá script baseline (2026-07-08 02:57 — "Stop Starving: 5 Anti-Nausea Snacks", variant evolved, score 90, prompt CŨ)

Sản phẩm: `implementation/output/products/beat_glp1_nausea/20260708_0256_stop_starving_5_anti_nausea_snacks_that_keep_you_n/`

**Mạnh:** hook số cụ thể ($450 lãng phí, 44% người dùng) pain-first; 2 open loop đều resolve; insight insider thật (peppermint chặn 5-HT3 = cùng cơ chế thuốc kê đơn); visual prompt cụ thể; 17 SFX marker hợp lý.

**Yếu (theo mức thiệt hại):**
1. **748 từ ≈ 5 phút** — dưới sàn 8 phút mid-roll → `_ensure_length` không chạy/fail im lặng trên nhánh evolved. Lỗi pipeline nặng nhất còn lại.
2. **Hook không trả nợ:** $450 ở hook không được giải thích trong body (vi phạm rule 12a — clickbait).
3. **Listicle:** "First snack… Snack three… four… five" — vi phạm rule 10a (phải nhóm theo cơ chế có tên).
4. **3 vi phạm câu chữ:** "keeps this channel going"; "I publish every week…" trong outro; đọc "The STEP 1 trial found" thành lời.
5. **0 prosody** → giọng đều đều (đã fix hệ thống 2026-07-08; script kế tiếp sẽ có).
6. Critic LLM chấm 90 và BỎ SÓT mục 2-4 → đã thêm MACHINE FLAGS deterministic vào Critic (bắt được mục 4 + thiếu độ dài).

## Chạy thử #2 (2026-07-08 chiều — sau khi hệ thống "hoàn thiện") — PHÁT HIỆN & FIX

Run 17:28 ("7 Foods", score 67 — Critic mới nghiêm hơn 90→67 đúng kỳ vọng) lộ ra chuỗi đứt gãy prosody KHÔNG nằm ở prompt:
1. **Serializer nuốt prosody:** `steps.py` whitelist 5 field cũ khi ghi variant JSON → pace/pause/emphasis biến mất; hook/outro scenes cũng không được lưu. → FIX: serialize đủ + thêm `variant_X.raw.txt` (raw LLM output để truy vết model có tuân thủ không).
2. **script.txt canonical là prose** → renderer không bao giờ nhận scene JSON → prosody chết ở render. → FIX: phase-2 ghi thêm sidecar `script.json` (storyboard đầy đủ kèm prosody) cho best draft; `render_real_video` ưu tiên đọc sidecar; nếu expand-prose fires thì xoá sidecar (tránh render storyboard cũ ngắn hơn).
3. **LLM sinh JSON hỏng:** dấu `"` không escape trong string (`circular "anxiety" loop`) → rớt nguyên block scene của segment. → FIX: `_repair_inner_quotes()` (state-machine escape) làm fallback thứ 3 trong `_parse_scenes_json`; đồng thời strip ```json fence.
4. **Variant dưới sàn từ:** `_ensure_length` chỉ chạy lúc generate; revise() làm ngắn lại (883 từ). → FIX: revise() gọi lại `_ensure_length(max_passes=1)`.
5. **Step timeout 2100s không đủ** cho debate nặng hơn (revise+expand, deepseek reasoning 14k tokens) — run test #2a chết vì timeout. → FIX: 3900s (content_flow + runner default).
6. Backend chạy code cũ trong RAM — **mọi lần sửa agents/pipeline phải restart backend** (hoặc chạy `run_phase2_test.bat` — process mới, file tạm ở implementation/, xoá được).

## Chạy thử #3 (2026-07-08 18:55 — "Why Your GLP-1 Nausea Peaks at Night", evolved score 71) — PROSODY THÔNG SUỐT

- LLM sinh prosody trên **65/65 scene** (xác nhận qua variant_*.raw.txt); parse + serialize giữ nguyên; JSON-repair chạy (0 lỗi parse so với 4 ở run #2).
- Evolved: 1374 từ (~9.2 phút, trên sàn), pace mix **23% slow / 31% fast** — đúng target benchmark; per-scene rate map: slow=-5%, normal=+10%, fast=+22%.
- Lỗi mới phát hiện + đã fix ngay: (a) expand-prose fired ở 1245<1300 và xoá sidecar → giờ skip expand khi có script.json và vo≥1200 (đã rebuild script.json cho product này từ evolved variant); (b) PAUSE INFLATION 14-22 pause ≥400ms và (c) EMPHASIS INFLATION 100% scene → thêm 2 MACHINE FLAGS vào Critic + renderer chỉ pitch-lift khi emphasis kèm số liệu (8/65 scene thay vì 65/65 — giữ tương phản).
- Test tĩnh sidecar→renderer: PASS. Còn lại để nghiệm thu trọn: render video thật từ product 18:55 và chạy `inspect_pacing` trên MP4.

## Chạy thử #4 + #5 (2026-07-08 tối) — CLAUDE POLISH PASS (chuẩn thương mại)

- **Cơ chế mới trong `steps.py`:** sau debate, nếu best <82 điểm HOẶC chưa approved → bản thắng được Claude (sonnet) revise 1 lần theo feedback Critic mới nhất, re-chấm, chỉ giữ nếu điểm cao hơn hoặc chuyển từ unapproved→approved. Lưu `variant_polished_*.{json,txt,raw.txt}`. Chi phí +$0.10-0.20/run.
- **Run #4 ("Morning Routine"):** polish 65→**73** (kept). Lộ 2 bug đã fix: (a) `base.call_llm` nhét system-role vào messages → Anthropic 400 → expand của Claude fail → script ngắn; đã hoist system lên param (fix cho MỌI agent dùng Claude); (b) pause inflation 23 → thêm `_clamp_pauses` khi ghi script.json (giữ ~6 pause dài nhất/10min, còn lại hạ 250ms).
- **Run #5 ("Doctors Keep Missing"):** variant B đạt **84 APPROVED ngay trong debate** (lần đầu chạm ngưỡng thương mại; polish tự skip vì ≥82). NHƯNG script chỉ 692 từ (~4.6min) mà Critic LLM vẫn approve bất chấp machine flag → thêm **HARD GATE độ dài trong `critic.execute`**: dưới 90% word-floor thì KHÔNG BAO GIỜ approved (deterministic, kèm rejection reason), route về Writer; polish giờ cũng chạy khi best unapproved bất kể điểm.
- Trạng thái: chuỗi thương mại = debate → hard gates (điểm + 2 nhóm + độ dài) → Claude polish khi cần → sidecar prosody (đã clamp pause). Run kế tiếp của scheduler sẽ xác nhận trọn chuỗi sau các gate mới.

## Tối ưu tốc độ/chi phí (2026-07-08 tối — đo thật: ~34min/$0.27/script, ~20 call)

Thủ phạm đo được: deepseek-v4-pro đốt 7-14k reasoning tokens/call (~2-4min/call, ~85% thời gian); variant thua ngốn ~7 call; vòng revise 3+ luôn tụt điểm; tournament Elo tốn call riêng (và từng xếp 66 trên 84); evolution chạy cả khi đã có bản approved. Fix (steps.py + orchestrator.py):
1. **Writer → deepseek-chat** (non-reasoning, nhanh 3-5x, rẻ hơn/token) — Critic giữ v4-pro; chất lượng neo bằng hard gates + Claude polish. Rollback = 1 dòng (`llm_writer`).
2. **max_rounds 7→2** (dữ liệu: vòng 3+ chỉ giảm điểm).
3. **run_tournament=False** — chọn theo điểm Critic; evolution tự sort theo score.
4. **Evolution chỉ chạy khi KHÔNG có variant approved** (đỡ 1 call Claude + 2-3 call expand 14k-token mỗi run có bản đạt chuẩn).
**Đo thật run #6 ("Protein Without the Gag", 22:08→22:34): 26 phút, score 92 (polished — CAO NHẤT từ trước tới nay), sidecar script.json GIỮ NGUYÊN (1722 từ ~11.5min, 7 pause sau clamp, writer chat-model vẫn ra A=75 vòng 1).** Chi phí $0.51: phần debate deepseek giảm còn ~$0.155 (từ ~$0.20) NHƯNG Claude polish giờ chạy trọn (revise+expand, $0.35) vì cả 3 variant <82 — đây là giá của yêu cầu "Claude bản cuối, chuẩn thương mại". Khi debate tự ra bản approved ≥82 (như run #5) polish tự skip → ~13-16 phút/$0.16. Knob giảm chi phí nếu muốn: hạ `_POLISH_MIN` 82→78 (polish ít kích hoạt hơn) hoặc cap max_tokens expand của Claude.

## Claude-first flow (2026-07-08 khuya — tối ưu chi phí + chất lượng đồng thời)

Vấn đề cấu trúc đo được: debate trả deepseek ~$0.15 cho nháp mà Claude polish viết lại gần hết (~$0.35, 69→92) = trả tiền 2 lần. Fix trong `steps.py`: **`OMNICAST_SCRIPT_FLOW=claude_first` (mặc định)** — Claude viết 1 bản trực tiếp (đủ prompt prosody/GHP/premium-editorial), deepseek-v4-pro chỉ chấm (~$0.01), revise 1 lần bằng Claude nếu <82/unapproved; giữ bản tốt hơn; polish-block cũ tự skip ở flow này. `OMNICAST_SCRIPT_FLOW=debate` để quay lại flow cũ (deepseek-chat writer + max_rounds 2 + evolution-khi-cần). **Run #7 đo ("3-Bite Rule"): 11 phút (26→11) nhưng $0.50 và score 71** — nguyên nhân đo được: (a) `max_tokens=12000` cắt cụt draft Claude (scene JSON overhead ~5x số từ) → dưới sàn → 2 call expand thừa ($0.28); (b) prompt revise chỉ đưa TÓM TẮT 40 ký tự/scene → Claude "sửa mù", hook drift + độ dài sập; (c) critic v4-pro variance lớn (cùng chất lượng chấm 63↔84). ĐÃ FIX: max_tokens 22000 cho Claude ở generate/revise/expand (1 call ra đủ độ dài, hết expand thừa → kỳ vọng ~$0.16-0.20 draft + $0.01 critic); revise nhận TOÀN VĂN script + lệnh "không viết lại từ đầu, không ngắn hơn bản gốc"; `llm/client.py` chuyển sang **streaming** khi max_tokens>8192 (SDK Anthropic từ chối non-streaming call >10 phút — run #8 fail vì lỗi này trước khi fix). **CẦN 1 RUN ĐO LẠI** (`run_phase2_test.bat`, topic "Your Coffee Order..." đã đặt) — kỳ vọng ~$0.20-0.35, ~8-11 phút, score cao hơn nhờ revise thấy toàn văn. Việc kế: giảm variance critic (chấm 2 lần lấy trung bình khi điểm sát ngưỡng 78-84, hoặc chuyển phần rubric cảm tính sang machine-check).

## Đo cuối + Observability (2026-07-09 rạng sáng)

**Run #9 đo cuối claude_first sau 3 fix ("Your Coffee Order", 00:18→00:27): 8.8 PHÚT (từ 34-40 phút gốc = nhanh ~4x), 5 call LLM, score 77, $0.46, sidecar prosody GIỮ (1564 từ, expand skip đúng).** Breakdown: draft Claude 1 call $0.145 (hết cảnh cắt cụt) + critic $0.009 + revise $0.125 + expand-sau-revise $0.174 + critic $0.010. Cost chưa xuống $0.25 vì: (a) critic v4-pro chấm gắt (draft 69→revise 77, vẫn <82 nên revise luôn chạy); (b) revise vẫn tự co chữ → ensure_length thêm 1 call $0.17. Knob nếu ưu tiên rẻ: hạ ngưỡng revise 82→78 (nhiều run dừng ở draft+critic = ~$0.16/5min, đổi lấy một số script 78-81). Việc kế đã ghi: giảm variance critic.

**Observability dashboard (steps.py + runner.py + server.py + state.py):** `_step_script` giờ tự ghi started/completed event (kèm score + cost_usd) và `accumulate_cost` → "Chi phí hôm nay" hết $0.00; CLI run cũng hiện trong Hoạt động gần đây (trước vô hình); debate/claude_first emit từng bước agent vào live log (Live Monitor thấy Writer/Critic/score/revise real-time) + `set_active_job_progress` các mốc 30/55/72/92% → ETA chuẩn hơn; runner ghi event "failed" + clear job khi step lỗi (hết hàng "Đang chạy" ma); server bỏ event completed trùng, API timeout 2100→3900; `read_cost_state` thêm daily rollover (trước đây today_usd không bao giờ reset). `reset_session_cost()` đầu mỗi step để meta không cộng dồn trong backend sống lâu. **CẦN RESTART APP** để backend nạp code mới — sau đó mọi run (kể cả scheduler) sẽ hiện đủ cost/lịch sử/live.

## Hiệu chỉnh đánh giá chất lượng (2026-07-09 — từ việc đọc tay bản "Your Coffee Order" 77đ)

Đọc tay cho thấy bản 77đ thực chất đáng 82-85 (metaphor filmable, insider insight thật, trả nợ lời hứa tường minh) — lộ 3 lỗ ở bộ chấm, đã fix:
1. **Hook-payoff mở rộng** (critic): bắt cả "60-second fix"/"7 foods"/"3-bite rule" (số-gạch-nối + số trước danh từ hứa hẹn), không chỉ $/%; phía body nới lỏng (mọi cụm số đều tính là trả nợ) để không flag oan. Bản Coffee sẽ bị flag đúng: hứa "60-second" nhưng body chỉ có 90-minute/16-oz.
2. **Critic double-score** (variance ±8-10 đo được, 63↔84 cùng bản): điểm rơi vào band 68-88 → chấm lần 2 (+$0.01), lấy trung bình subtotal VO/prod — quyết định revise($0.15-0.30)/approve chính xác hơn.
3. **Emphasis clamp tại nguồn** (writer parse): emphasis chỉ giữ khi scene có số/từ chỉ độ lớn (digit|billion|percent|half|double…) — models đánh 85-100% scene bất chấp prompt; giờ khớp luật pitch-lift của renderer.
Cách đánh giá chất lượng hiện có 3+1 lớp: (i) machine flags + hard gates deterministic; (ii) Critic LLM 8 chiều (đã giảm variance); (iii) `inspect_pacing` trên MP4 render vs benchmark; (iv) đọc tay chọn lọc khi hiệu chỉnh. Các thay đổi cần restart app (backend giữ code cũ) hoặc chạy qua run_phase2_test.bat.

## NGHIỆM THU VIDEO ĐẦU TIÊN (2026-07-09 03:26 — "Shot Day Dinner", 646.8s/188MB/1817 từ)

Chuỗi trọn: claude_first script 71đ ($0.61 — revise+expand đều chạy) → render all-stock 119 shots (**renderer đọc sidecar: "72 scenes with prosody" ✅**) → BGM sidechain → QA nội bộ PASS → title/thumb tự sinh. Sự cố giữa chừng: venv thiếu edge-tts/soundfile (bị rebuild lúc nào đó) → đã cài lại; content_flow `--topic` override luôn dừng sau phase 2 → render chạy riêng (`run_render_test.bat`).

**Đo MP4 cuối vs benchmark:** syll-rate 208±24/min, variance 0.114 (vfacts 0.109) — **giọng có nhấn nhá thật, QA variance PASS**; outro chậm rõ (164 vs body 210) ✅; hook chưa chậm hơn body (warning). **PHÁT HIỆN LỚN CUỐI: 188 pause ≥250ms / 82 ≥400ms so với vfacts 17/9** — KHÔNG phải prosody pause (đã clamp ~6) mà là **gap giữa 119 shot khi concat** (trim pad 0.08s×2/biên + biên shot). vfacts cắt sạch, inter-sentence 0.15-0.23s. → Việc hiệu chỉnh kế tiếp (ưu tiên 1 mới): renderer giảm trim pad 0.08→0.03-0.04 + concat audio khít biên shot (hoặc acrossfade ~30ms), mục tiêu <30 pause ≥250ms/10min. Lưu ý phụ: channel preset beat_words=18 override CLI 12 (vì 12 == default mới) — nên đổi channel JSON sang 12.

## Vòng "da thịt" (2026-07-09 rạng sáng — từ feedback operator: thumb tệ, giọng uể oải, BGM sai mood)

Chẩn đoán + fix:
1. **Giọng uể oải:** kokoro chỉ có ở Python GLOBAL, venv render rơi xuống edge Jenny (phẳng) + 188 gap concat. Fix: cài kokoro vào venv — pip vỡ 3 lần (blis build lỗi py3.13; resolution-too-deep; kokoro 0.7.16 đòi misaki≥0.7.16 trong khi bộ GLOBAL đang chạy misaki 0.7.4 off-spec) → chốt bằng `setup_voice5.bat`: `--no-deps kokoro==0.7.16 misaki==0.7.4` + deps runtime tường minh → **VENV kokoro OK + SMOKE OK**. `channels/beat_glp1_nausea.json` sửa voice_profile `kokoro_en_us_v1`→`kokoro:af_heart` (spec format).
2. **Thumb tệ:** KHÔNG phải Flow hết session — run trước đặt FLOW_SKIP=1 (tránh mở browser lúc operator chơi game) nên Flow không được thử; fallback ảnh web crash "Playwright Sync API inside asyncio loop" → thumb rơi xuống frame stock + chữ generic. Fix: web-thumb chạy trong ThreadPoolExecutor riêng (render_real_video). Render có Flow thật: chạy KHÔNG FLOW_SKIP.
3. **BGM sai mood + kho mỏng:** map cứng health→"uplifting" ("Carefree" cho video cảnh báo!) + 16 track. Fix: music_lib health/nutrition→ambient + channel `music_mood:"ambient"`; FreePD đã đóng cửa (2025) → `harvest_incompetech.py` tải **30 track MacLeod CC-BY mới** (ambient/tense/cinematic/dramatic/calm, 46 tổng). **LƯU Ý CC-BY: description video PHẢI ghi "Music: Kevin MacLeod (incompetech.com), CC BY 4.0" — cần wire tự động vào upload description (VIỆC MỚI).**
**A/B render lại "Shot Day Dinner" (kokoro af_heart + nhạc ambient, 05:19→~05:55, 573s):**
- **Gap cải thiện mạnh: 188→68 pause ≥250ms, 82→12 ≥400ms** (vfacts 17/9) — kokoro audio liền mạch hơn edge nhiều, mạch nói hết "uể oải" phần lớn. 0 voice fallback (kokoro chạy 100% shots).
- **NHƯNG variance nhịp tụt còn 0.062 (< ngưỡng QA 0.08; bản Jenny 0.114):** per-scene `speed` trên kokoro path KHÔNG tạo ra chênh lệch đo được (hook 224 ≈ body 222) — nghi `KPipeline(speed=)` không ăn hoặc bị nuốt ở provider. **BUG MỚI cần debug:** trace speed từ `_render_voice_provider` → `KokoroTTSProvider.generate` → `pipe(...)`; nếu KPipeline speed không tin được thì hậu xử lý bằng ffmpeg `atempo` per-scene (chắc chắn ăn, chất lượng ổn trong ±15%). Base rate 222/min cũng hơi nhanh so 197 chuẩn → cân nhắc bỏ +10% base cho kokoro.

## Video hoàn thiện v2 (2026-07-09 trưa — sau feedback "slide chữ + âm thanh lạ")

Nguyên nhân bản slide-chữ: storyboard LLM trả JSON hỏng (unescaped quote) → code cũ vứt cả board → mất luôn nhánh stock → 119 text-card. FIX: (1) storyboard parser dùng `_repair_json_quotes` + salvage từng cell; (2) board chết vẫn chạy all-stock từ heading; (3) clickbait prompt cấm thumb-text generic không neo chủ thể (model từng nhại ví dụ "STOP THIS!"); (4) `_replace_retry` cho BGM/kinetic/SFX khi video.mp4 bị player khóa (WinError 5 — nguyên nhân bản kokoro đầu mất cả 3 pass hậu kỳ).

**Kết quả render 13:09 ("Shot Day Dinner" v2): 573s/174.6MB — footage Pexels thật 119 shot (storyboard query chất: "side by side avocado and fried chicken macro"…), giọng kokoro af_heart 0 fallback, thumb nền ảnh web thật + chữ "TONIGHT MATTERS" (anchored), title "Why Your Shot Day Dinner is a Nausea Trap (Do This Instead)", QA PASS.** Còn thiếu DUY NHẤT: BGM/kinetic/SFX — VLC của operator mở video suốt lúc render nên replace bị khóa cả sau retry. → Chạy `apply_bgm_only.bat` (1 lệnh, không re-render) SAU KHI đóng player; kinetic/SFX sẽ có ở lượt render tự nhiên kế tiếp.

## Thumbnail v2 (2026-07-09 chiều — "thumb vẫn tệ")

Gốc rễ: fallback thumb đi search ẢNH WEB theo title → vớ thumbnail người khác/ảnh Etsy (rủi ro bản quyền + chữ lạ dính sẵn). ĐÃ SỬA: (1) render_real_video — nguồn thumb fallback giờ là **frame từ chính stock footage đã license của video**, ưu tiên scene có mặt người/cảm xúc (regex woman|face|clutching|nauseous…); web-image search BỎ HẲN khỏi thumb; (2) clickbait — thumb_text bắt buộc chứa DANH TỪ CỤ THỂ (DINNER/COFFEE/SHOT/NAUSEA…), cấm cụm trừu tượng ("TONIGHT MATTERS" = FAIL); (3) `make_thumb.py` — regen thumb riêng không cần re-render. Kết quả sản phẩm hiện tại: mặt phụ nữ 50s trong bếp + "WRONG DINNER?" (chuẩn face+noun+question). Polish tiếp theo (nhỏ): compose_thumbnail nên đặt chữ né mặt (hiện chữ đè cằm nhẹ); về lâu dài Flow AI-gen cho mặt biểu cảm kịch tính hơn.

## STRICT MODE (2026-07-09 — chỉ thị operator: "không fallback ở bất kỳ khâu nào")

Triết lý: **fail to > lặng lẽ ra video kém** (mở rộng nguyên tắc vốn có của TTS "job fail tốt hơn giọng robot"). `OMNICAST_STRICT=1` (MẶC ĐỊNH BẬT; =0 chỉ để debug). Dưới STRICT:
- **Voice:** chỉ dùng giọng CHÍNH của kênh (kokoro:af_heart) — cắt chain fallback xuống edge (từng gây bản "uể oải").
- **Storyboard:** fail → retry 1 lần (LLM gọi lại, không hạ cấp) → vẫn fail = DỪNG render (không heading-query, không text card).
- **Stock:** all-stock thiếu footage bất kỳ scene nào = DỪNG, in rõ danh sách query fail.
- **Thumb (siết thêm theo chỉ thị 07-09): FLOW-ONLY.** Frame stock cũng bị loại ("lấy 1 frame quá xấu") — Flow không có/fail = DỪNG render với hướng dẫn đăng nhập (`scripts/flow_login.py` tạo browser profile một lần). `make_thumb.py` hạ cấp thành tool khẩn cấp thủ công, không nằm trong pipeline. **Điều kiện vận hành mới: Flow session phải sống thì render mới hoàn thành** — thumb của video "Shot Day Dinner" hiện tại muốn lên chuẩn Flow thì đăng nhập Flow rồi render lại (hoặc chờ video kế).
- **BGM/kinetic/SFX:** thiếu/lỗi/file bị khóa = DỪNG với thông báo hành động (đóng player, kiểm assets/music).
- **Script step:** cấm expand-prose phá sidecar prosody — script ngắn + có storyboard = DỪNG (lỗi thuộc về writer gates, sửa ở gốc).
PHÂN BIỆT giữ lại: retry (fresh attempt), JSON-repair (khôi phục đúng nội dung), `_replace_retry` chờ file mở khóa — đây KHÔNG phải fallback hạ cấp. Hệ quả vận hành: tỉ lệ render fail sẽ tăng — đó là chủ đích; scheduler retry và operator sửa nguyên nhân gốc thay vì đăng video kém.

## Thumb Studio (2026-07-09 chiều — tách sinh thumb ra riêng, operator chọn)

Theo chỉ thị: thumb tách khỏi render, human-curated, có ô nhập yêu cầu, clickbait hơn.
- **`thumb_studio.py`** (root): `generate_candidates(product_dir, note, count)` sinh N ứng viên Flow theo **4 góc clickbait khác nhau** (shock_face cận mặt kinh hãi / culprit_redmark món ăn + gạch đỏ / consequence_split trước-sau + mũi tên / pointing_panic chỉ tay cảnh báo), style đẩy drama mạnh hơn (EXTREME expression, sáng, bão hòa); `note` của operator chèn vào prompt với ưu tiên MUST-FOLLOW; `select()` promote ứng viên thành `video_thumb.png` + cập nhật title. Lưu tại `<product>/thumbs/` + meta.json. FLOW-ONLY, fail to đúng STRICT.
- **API + trang `/thumbs`** (server.py): gallery ứng viên theo product, nút "Dùng làm thumb chính thức", nút "Tạo 4 thumb mới" kèm **textarea yêu cầu** → truyền vào agent. Trang server-rendered (không cần rebuild webui_v2; tích hợp vào tab Studio React sau). Ảnh serve qua /pmedia có sẵn. **Cần restart app để endpoint sống.**
- **Batch mode NATIVE x4:** flow_browser thêm `_set_output_count` (click tab 1x/x2/x3/x4 trong popover model — 0 tín dụng) + `gen_image_multi`/`generate_multi`: **1 submit → tối đa 4 biến thể**, tự reset về 1x sau khi xong (không ảnh hưởng gen thường). thumb_studio dùng generate_multi khi per_angle>1 (4 góc × 4 = 16 ảnh chỉ với 4 submit — nhẹ anti-abuse hơn 16 submit rời), fallback generate_batch nếu provider không hỗ trợ. CLI: `--count 4 --per-angle 4`; API/trang /thumbs có selector Ảnh/góc. Verify thật 2026-07-09: log "[flow] outputs per prompt -> x4" → 4/4 ảnh từ 1 submit.

## Phụ đề + Tab Xưởng (2026-07-09 chiều — feedback: caption dày/thiếu, Xưởng script/duyệt trống)

**Phụ đề:** (a) "thiếu/lệch" = kokoro không có word-boundary, words.json chỉ là ước lượng chia đều → caption trôi. Fix: words proportional đánh dấu `approx:true`; renderer nếu >50% approx → BẮT BUỘC whisper alignment trên audio final (faster-whisper đã cài vào venv); STRICT fail nếu không align được. (b) "dày đặc": chunk 5từ/32ký-tự → 7từ/42; fill_gaps 2.5s→1.0s (pause kịch tính giờ để trống màn hình); whisper chunk 4→6.
**Tab Xưởng (frontend_v2/Studio.tsx, build deploy `index-CHwwYMqM.js`):** Bước Script trước đây CHỈ hoạt động ở chế độ WAITING_EDIT → flow tự động luôn trống. Giờ: đang sinh script → feed debate live từ `/api/run/{ch}/log`; xong → hiển thị script.txt sản phẩm + badge điểm. Bước Duyệt: hàng chờ `/api/approvals` inline + nút Duyệt/Từ chối (trước chỉ là link). Live Monitor: thêm sự kiện debate khi phase script. Cột phải thêm panel **Thumbnail**: bản chính thức + gallery ứng viên (click = chọn), textarea yêu cầu + nút tạo batch Flow 4góc×2. **Cần restart app** để cả backend endpoints (thumbs/observability) lẫn bundle mới cùng sống.

## Xưởng product-centric + DEPLOY (2026-07-09 tối — feedback: "chỉ hiển thị cái mới nhất… sai sai")

Studio.tsx tái cấu trúc thành workspace THEO SẢN PHẨM: dropdown chọn sản phẩm ở header Bước Script + Bước Render (đổi sản phẩm từ bất kỳ bước nào, mọi panel Script/Render/Thumb theo sản phẩm đang chọn); panel phải "Sản phẩm trong xưởng" hiển thị chip trạng thái từng sản phẩm `S:{score} · R:✓/FAIL/— · D:⏳/·/—` — cuối ngày duyệt lần lượt từng video autopilot sinh ra. Fix TS2448 (products dùng trước khai báo) → build OK, bundle mới **`index-Co_0pVM0.js`**. **ĐÃ RESTART APP** (restart_omnicast.bat: kill pythonw cũ → relaunch OmniCast.bat). Verify check_backend.bat: `/` 200, bundle mới 200, `/thumbs` 200, `/api/channels` + `/api/approvals` JSON OK → toàn bộ backend endpoints (Thumb Studio, observability, STRICT steps, claude_first) + UI mới ĐÃ SỐNG.

## Xưởng v2 — product-centric THẬT SỰ (2026-07-09 tối, feedback "không biết tình trạng product")

**Discovery (Bước 1):** chỉ hiện topic `queued` có điểm >0 (topic đã sản xuất/`used` tự biến mất — sản phẩm của nó nằm ở board). Bấm topic → mở chi tiết: điểm màu theo ngưỡng, Khán giả / Nỗi đau / Góc khai thác / Nguồn (link) / ngày phát hiện + **check trùng lặp tự động** (`/api/dedup/check`: ⛔ block / ⚠ warn / ✓ ok) + nút **▶ Tạo script từ topic này** (POST `/api/topics/{ch}/{id}/script`, xử lý 409 duplicate với confirm force) + Bỏ qua. Topic thô score-0 (tiêu đề đối thủ quét verbatim) gom vào mục thu gọn "KHÔNG nên dùng trực tiếp".
**WIP vs Thư viện:** Xưởng chỉ chứa sản phẩm CHƯA upload (`!meta.youtube_id`); publish flow giờ ghi `youtube_id/youtube_url/uploaded_at/status=uploaded` vào meta.json sản phẩm → sản phẩm rời Xưởng, vào Thư viện (Library.tsx thêm tab "Đã đăng" (mặc định) / "Tất cả"). Board phải "Sản phẩm trong xưởng": badge trạng thái rõ chữ (Đang sinh script / Chờ render / Sẵn sàng duyệt / Chờ duyệt / QA FAIL) + điểm + chi phí; bấm → nhảy thẳng tới bước sản phẩm đang chờ. Dropdown picker cũng in `[trạng thái · điểm]` trước tiêu đề. Stepper hiện đếm topic sẵn sàng / số chờ duyệt.
**Backend:** (a) junk guard 2 chỗ upsert topic (score≤0 + không metadata → không ghi vault; đã dọn 12 rác cũ = skipped, còn 3 topic thật); (b) `_run_channel_phase2` khi topic được chỉ định giờ tra vault lấy đủ brief (audience/pain/angle) cho writer — trước đây chỉ truyền title trần; (c) publish ghi meta uploaded như trên.
**Đánh giá cơ chế tìm topic:** thiết kế tốt (4 nguồn song song News/Trends/YouTube-competitor/Reddit → chấm 4 chiều trend 30 + gap 40 + RPM 20 + novelty 10, ≥70 auto-approve + LLM brief; dedup khi dùng). Điểm yếu thật: (1) topic thô lọt vault — ĐÃ CHẶN; (2) novelty check luôn neutral vì không truyền kb_client — cải thiện tương lai; (3) brief metadata bị rơi khi operator chọn topic — ĐÃ VÁ. Deploy: bundle `index-DRL826G3.js`, app restart, verify: `/api/topics` 3 queued sạch, dedup ok.

## Việc còn lại (theo thứ tự ưu tiên)
1. ✅ **Ép word-floor ở nhánh evolution/expand** (2026-07-08) — `EvolutionAgent.execute` sinh evolved draft → `orchestrator` gọi `WriterAgent.ensure_length()` (serialize draft→script text + reuse `_ensure_length` expand loop) trước khi insert thành winner. Bonus: evolution prompt+parser giờ giữ prosody (pace/pause/emphasis) + `hook_scenes`/`outro_scenes` set trên ScriptDraft; max_tokens 4000→8000 (4000 cắt cụt output = nguyên nhân gốc 748 từ).
2. ✅ **Mở rộng MACHINE FLAGS trong Critic** (2026-07-08) — (a) hook-payoff: mọi `$`/`%`/số-có-dấu-phẩy ở hook phải tái xuất trong body, nếu không → flag deterministic (rule 12a); (b) listicle: ≥3 marker đếm ("snack one/number two/step 3" hoặc first/second/third…) → flag (rule 10a). Deduction hint cập nhật.
3. ✅ **SFX/zoom marker tự động tại twist/số liệu khi render** (2026-07-08) — `_scene_motion(i)` ép ken-burns ZOOM-IN (motion 0) tại scene có stat/emphasis/pause≥400ms; `_mix_sfx` thêm whoosh tại twist-pause + ting tại emphasis (ngoài heading-flip/stat cũ).
4. **Shader transitions hyperframes** (_refs, chỉ đọc) cho chuyển cảnh lớn — CHƯA làm.
5. **Pattern-interrupt hài hước (meme clip xen kẽ)** — vfact dùng dày đặc, pipeline chưa có nguồn asset loại này (gap lớn nhất về b-roll, cần thiết kế nguồn + license an toàn) — CHƯA làm.

## Nghiệm thu
Render 1 video mới: WPM có variance rõ (không đều đều), pause có chủ đích ở twist, ≥15 shots/phút, SFX ≥5 điểm, QA pass (gồm `inspect_pacing`), nghe A/B với video vfact không bị "giọng robot đều". **Điều kiện trước khi chạy: restart backend/desktop app để nạp code mới.**
