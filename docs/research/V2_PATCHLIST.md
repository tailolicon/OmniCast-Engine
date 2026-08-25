> STATUS: ACTIVE

# V2 PATCH LIST — Tổng hợp đại chiến dịch V2 (2026-08-08)

Nguồn: 6 báo cáo Grok `docs/research/V2_{A1,A2,B1,B2,C,D}_*.md` + 6 digest kiểm chứng độc lập (Claude Sonnet subagents, mỗi digest spot-verify 5–9 trích dẫn với `_refs/` + kiểm file đích OmniCast).

**Độ tin cậy tổng:** 38 spot-verify → **0 SAI-BỊA**. Ngoại lệ phải nhớ khi thực thi:
- **A2:** ~13 mục giá trị cao trích từ chuỗi trong `.exe` của Cap Assistant. **Chủ dự án xác nhận (2026-08-08): TÁC GIẢ ĐÃ CHO PHÉP dùng nguyên văn hoặc tinh chỉnh** → rào "chỉ paraphrase" được gỡ; đang giải nén lại `.rar` để harvest đầy đủ vào `docs/research/V2_A2_CapVerbatim.md`.
- **B1:** 2 mục (`llm.py:721-783`, `llm.py:965-988`) trộn verbatim với paraphrase không đánh dấu → khi patch phải tự mở file nguồn trích lại, không copy từ báo cáo.
- **C:** khối `Orkas composition-qa.ts` (~58 mục) là error-string của gate riêng Orkas, chỉ tham khảo cấu trúc; 1 cặp mục trùng/gãy tại `:1788` (artifact extract).
- **voice-pro:** kiểm license trước khi copy verbatim code/regex (tiền lệ OmniVoice-Studio là AGPL — chỉ mượn concept).

Quy ước loại patch: **THAY** = thay verbatim prompt/config; **GHÉP** = thêm vào chỗ hiện có; **SỬA** = sửa cơ chế.

---

## TRẠNG THÁI THỰC THI (cập nhật 2026-08-08)

**Đợt 1 XONG** (chi tiết trong `IMPLEMENTATION_STATUS.md` §mục 2026-08-08): P0-1 ✅ (subtitle thật, thang 3 nguồn + fail-closed), P0-2 ✅ (`estimate_duration` âm tiết), P0-3 ✅ (`media/tts_normalize.py`), P0-8 ✅ (`pack_captions` 15/40 + cap 150 = khớp luôn ngưỡng Cap Assistant), P0-5 ✅ (`flf_clip_prompt` nối vào `gate_clips`), P0-6 ✅ (slop gate ở `load_film_spec`), P1-1 ✅ (Edge retry 3×), P1-2 ✅ (prosody lọc theo signature), P1-20 ✅ một phần (`IP_RISK`/`FILTER_RISK`), +`LAZY_MOTION` từ Cap I2V rule. **P1-3 hoãn có chủ đích**: trim-silence làm lệch `.words.json` → phụ đề trôi (phải dịch offset sidecar cùng lúc mới đúng).

**Cap Assistant đã harvest xong** → `docs/research/V2_A2_CapVerbatim.md` (496 dòng: Master Film Director ~1900 từ, SRT 150/60-140, Unified Scene schema SRT+ảnh+I2V 1:1, I2V GOOD/BAD, Character/Style DNA + 3 prompt vision-extraction, config 2.5 từ/giây…). Cảnh báo: **TikTok session token sót trong `_refs/Cap Assistant - REUP/.../user_config.json`** (đã redact trong báo cáo, nên xoá khỏi `_refs`); prompt dịch của REUP có khung né kiểm duyệt → **KHÔNG port**.

**Phát hiện quan trọng của audit (đổi bản chất P0-4/5/6/7):** `slop.py` (anti-slop seedance) và wording FLF trong `clips.py` **đã tồn tại sẵn** — vấn đề là `film_runner.py`, pipeline duy nhất tiêu credit và ra `final.mp4`, **không gọi cái nào**. Nên đây là gap NỐI DÂY (rẻ, đã làm) chứ không phải port. Còn lại:
- P0-4 (compile-order + nén theo budget của prompt-compiler): audit đánh giá **giá trị thấp** ở quy mô film hiện tại (6-8 shot soạn tay) — hoãn.
- P0-7 (eval rubric 0-3/0-4): **chưa có gì trong repo**; audit khuyến nghị làm harness offline (regression test cho prompt) thay vì gate runtime, vì `continuity.py` đã chặn cứng theo issue — hoãn sang đợt 2.

## P0 — Đề xuất làm ngay (tác động cao, nguồn đã verify, rủi ro thấp)

| # | Patch | Nguồn (đã verify) | Đích OmniCast | Loại | Sức |
|---|-------|------------------|---------------|------|-----|
| P0-1 | **SubtitleModule thật** — hiện là stub trả 2 segment cứng "Hello world" (A1+B1 xác nhận độc lập trong code). Bước 1: wire `.words.json` sẵn có từ `tts_edge.py` (word-timing thật, không cần ASR). Bước 2 (sau): WhisperX theo `pyvideotrans/_whisper.py:62-83` + `VideoLingo/whisperX_local.py:85-133` | pyvideotrans + VideoLingo | `media/subtitle.py:17-58` | SỬA | M→L |
| P0-2 | **Pre-TTS duration estimator** thay `len(text.split())*0.4` — syllable-based per-lang (`duration_params en 0.225…`) + prompt trim khi quá dài (`prompts.py:302-339`) | VideoLingo | `media/tts.py:60-61` | SỬA+GHÉP | M |
| P0-3 | **Text-normalize + sentence-chunk trước TTS** — normalize số/ký hiệu/corner-mark, chunk 80-token (min 60, merge 20), sentence-split regex đa ngôn ngữ | voice-pro `abus_text.py:245-289,178-201` + cosyvoice `frontend_utils.py` (⚠ check license voice-pro) | `media/tts_normalize.py` (mới) + `voice_router.py` | THAY/GHÉP | M |
| P0-4 | **Seedance prompt-compiler grammar** — "source-carries-state" (không mô tả lại thứ ref đã show), thứ tự compress khi hết budget | `seedance-2.0/references/prompt-compiler.md` (verify KHỚP) | `storyboard/clips.py`, `frames.py`, `prompt_compiler` | GHÉP | M |
| P0-5 | **Seedance FLF guide** — quy ước `@Image1 first / @Image2 last`, identity-lock wording, "chỉ mô tả transition logic" | `seedance-2.0/references/first-last-frame-guide.md` | `media/prompt_builder.py`, `storyboard/film_runner.py` | GHÉP | S |
| P0-6 | **Anti-slop lexicon** post-process prompt trước khi gửi Flow/Veo — 6 lớp slop + bảng thay thế + filter-vocab | `seedance-2.0/references/anti-slop-lexicon.md` | prompt path chung (prompt_builder / prompt_compiler) | GHÉP | S |
| P0-7 | **Seedance eval rubric 0-3/0-4** (continuity, reference-binding, endpoint quality, ngưỡng pass) → QA ảnh/clip + trả nợ SL5 vision-QA | `seedance-2.0/references/eval-rubric.md` | `agents/critic.py`, `storyboard/` QA | GHÉP | M |
| P0-8 | **Caption line-packer** cjk_len=15/other_len=40 + hard-cap ký tự (ngưỡng 150 của Cap exe → tự đo lại, không tin nguyên) | pyvideotrans `config.py:446-447` + VideoLingo weight-char | `media/subtitle.py` | GHÉP | S |

## P1 — Đợt kế (giá trị vừa–cao, công sức nhỏ)

**TTS/Voice**
- P1-1 Edge retry/semaphore (10 concurrent, 3 retry, 30s timeout) — pyvideotrans `_edgetts.py:18-71` → `providers/tts_edge.py`.
- P1-2 Prosody expose: `voice_prosody` rate/pitch/volume trong `channels/*.json` → VoiceRouter → tts_edge (hiện hardcode `+0%/+0Hz`); kèm Kokoro speed 0.3–2.0.
- P1-3 Trim silence per segment −50dBFS/pad 100ms — voice-pro `abus_audio.py:35-97` → `media/tts.py` (hiện chỉ loudnorm global).

**Agents (writer↔critic, từ ChatDev/agent-office — D verify 5/5)**
- P1-4 Priority-fix rank-1: critic nêu 1 comment ưu tiên cao nhất (giữ `specific_fixes[]` đầy đủ song song) — `PhaseConfig.json:145-152` → `agents/critic.py`.
- P1-5 Thinking → Reflexion Evaluator (Score/Reason/Next Focus/Verdict) — `reflexion_loop.yaml` → `agents/thinking.py`.
- P1-6 Blackboard giữa debate rounds (max_items, memory_cue) — → `agents/orchestrator.py` (audit call-site trước, đổi schema draft.meta).
- P1-7 Post-revise fix-coverage check (+1 LLM call/round — chấp nhận cost) — → `agents/writer.py` sau revise ~:2018.
- P1-8 Temperature 0.2 cho debate/revise (không áp generation) — `camel/configs.py:67` → critic.py + writer revise + `base.py`.
- P1-9 Single-topic lock kiểu "ONLY discuss the product modality" — `PhaseConfig.json:17` → `editorial_angle.py`, `channel_name_debate.py`.

**Character/Storyboard consistency (C verify KHỚP)**
- P1-10 Orkas stage-consistency: LOCK front-portrait, derive side/back qua reference-edit; motion mô tả bằng đặc điểm nhìn thấy — → `storyboard/style_lock.py`/refsheet.
- P1-11 waoowaoo `character_reference_to_sheet` (style-priority rule + missing-part completion) + ArcReel `_CHARACTER_LAYOUT`/`_PRODUCT_GUARD` multi-view sheet — → refsheet prompts.
- P1-12 Jellyfish anti-vague agent chain (cấm từ mơ hồ, tách vai phân tích thiếu-thông-tin) — → `agents/writer.py`/`storyboard/frames.py`.

**Flow browser hardening (không đụng API nội bộ)**
- P1-13 Selector cascade + wake — `h2dev_flow/content.js:69-96` → `flow_browser.py` `_PROMPT_SEL`.
- P1-14 Backoff 30→300s + jitter 20% + batch delay 5–15s — tobyflow/h2dev_flow → flow_browser + settings.
- P1-15 Wire `convert()` image→video (gap FLOW_ACCEPTS_IMAGE đã biết, B2 xác nhận docstring "image_path is currently ignored").

**Khác**
- P1-16 Writer system constraints raw-spoken/no-markdown — MPT `llm.py:23-38` (verbatim 100%) → `agents/writer.py`.
- P1-17 BGM volume chuẩn hoá (~0.2 linear vs −20dB hiện tại) — → `media/orchestrator.py:393`.
- P1-18 Encoder fallback nvenc→libx264 — MPT `video.py` → `render_real_video.py`.
- P1-19 Default negative prompt "no text, no watermark" — → `media/models.py:70`.
- P1-20 Compliance blocklist tài liệu hoá (fingerprint-bypass/CapCut backdoor/RVC/TikTok-TTS-unofficial — phát hiện từ Cap REUP, mục đích NGĂN chặn) — → `compliance/` docs/rules.

## P2 — Lớn hoặc chờ quyết định

- P2-1 **FlowApiClient API-first** (tobyflow schema đầy đủ NHƯNG thiếu URL/auth thật của Google — phải HAR-trace; **RỦI RO ToS Google** gọi internal API) — CẦN USER QUYẾT. Nếu không làm, P1-13/14 đã cứng hoá UI path.
- P2-2 Stock compilation engine (Pexels/Pixabay match-to-script) — MPT `material.py:55-470` → `media/stock_clips.py` (mới). L effort; check license stock.
- P2-3 2-pass localize (faithfulness→expressiveness) + glossary — VideoLingo `prompts.py:144-247` → `agents/localize.py` (mới); glossary lưu **bảng `vault.db`**, KHÔNG JSON (rule SSOT).
- P2-4 Unified Scene schema SRT+Prompts+I2V 1:1 + I2V motion GOOD/BAD rules — nguồn Cap `.exe` **chưa tái kiểm + rủi ro bản quyền** → nếu làm: re-verify (giải nén rar) rồi paraphrase.
- P2-5 Social metadata platform caps — MPT `llm.py:835-988`; đích upload path chưa xác định + hashtag mặc định `#viral #fyp` phải qua compliance.
- P2-6 Critic evidence-ceiling toàn cục (chống critic vượt evidence/compliance) — vùng YMYL nhạy cảm, **PR riêng, review kỹ** (làm sai = nới gate).
- P2-7 Dubbing-safe pacing prompt (CJK 2.5–3.5 syl/s) — chỉ khi mở nhánh multi-lang.
- P2-8 Piper offline VN provider — thấp, chờ nhu cầu.

## LOẠI — không làm (vi phạm chính sách/quy tắc)

Fingerprint-bypass, CapCut backdoor, RVC/AI-cover giọng, TikTok TTS unofficial, multi-account Gemini farm (đều từ Cap REUP) — các báo cáo đã tự loại đúng; chỉ giữ làm blocklist (P1-20). Không có patch nào còn lại mâu thuẫn 4 quy tắc cứng (SQLite SSOT / upload API-only / neural-TTS-only / nhạc sạch).

## Câu hỏi cần chủ dự án quyết trước khi thực thi

1. **Flow API-first (P2-1):** chấp nhận rủi ro ToS + công HAR-trace, hay ở lại UI-automation đã cứng hoá?
2. **Nguồn Cap Assistant Pro (.exe decompile):** chỉ port ý tưởng/ngưỡng số (khuyến nghị) hay muốn re-verify + cân nhắc dùng nguyên văn?
3. **Phạm vi đợt 1:** chốt P0-1…P0-8 như đề xuất? (Ước lượng: ~6–8 PR nhỏ, mỗi PR kèm test + cập nhật IMPLEMENTATION_STATUS.)
