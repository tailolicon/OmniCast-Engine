# WS1 — CHECKLIST THỰC THI TRÓI BUỘC (chống đi tắt)

> STATUS: ACTIVE
> Nguồn: GAP_1_core.md + GAP_2_drama.md + GAP_3_finishing.md (đại kiểm toán 2026-08-02,
> đối chiếu 830KB nghiên cứu vs code vs nhật ký demo). Luật: KHÔNG bước nào được thực thi
> nếu không chỉ được vào mục checklist tương ứng. Vi phạm = dừng, quay lại gate.

## GATE A — THIẾT KẾ (trước khi gen bất kỳ thứ gì)
- [ ] A1 Beat sheet chuỗi nhân-quả MỘT mạch; mọi biến đổi đạo cụ diễn ra TRÊN HÌNH;
      mỗi shot: action 1 câu nhìn-thấy-được + start_state/end_state + duration theo beat.
- [ ] A2 Thiết kế nhân vật/đạo cụ phải ĐỌC ĐƯỢC TRONG 1 GIÂY (test: người lạ gọi đúng tên
      vật thể). Bài học: đèn-nửa-gấp-nằm-nghiêng bị đọc thành "chiếc ô".
- [ ] A3 DoP pass (waoowaoo): per shot — hướng sáng, screen_position (AXIS LOCK toàn phim:
      Miko trái / đèn phải), DoF theo cỡ cảnh, tone.
- [ ] A4 Acting pass (waoowaoo): 1 câu biểu diễn thấy được / nhân vật / shot; cấm từ cảm xúc trần.

## GATE B — TẦNG STILL (ảnh free — phải khoá xong TRƯỚC video)
- [ ] B1 Keyframe cho TỪNG boundary bằng image mode + đủ ref entity; keyframe N+1 LUÔN đính
      keyframe N làm ref "composition only — ignore identity" (ArcReel A9.4; GAP_2 #8
      "LAST frame attach FIRST làm layout lock").
- [ ] B2 Duyệt từng still BẰNG MẮT theo CẶP với still trước (vị trí/đạo cụ/ánh sáng/style).
      Sai → re-roll ẢNH (free). CẤM vá thế giới lệch bằng video.
- [ ] B3 Prompt still: cấm tả lại mặt/áo khi đã có ref (GAP_2 #5); qua slop-lint; camera do
      record quyết, không do model.

## GATE C — TẦNG VIDEO (mỗi clip = tiền)
- [ ] C1 Mặc định I2V/FLF từ still ĐÃ DUYỆT: Bắt đầu = still N; Kết thúc = still N+1 khi
      chuyển động cho phép. **CẤM components/R2V trần không scene-lock** (GAP_1 A9.7/§6.1 —
      chính là lỗi giết demo v2).
- [ ] C2 Prompt video = motion-only DELTA (source-carries-state) + exclusions
      beats_completed/reserved + đúng 1 camera move.
- [ ] C3 Keep clip → ghi NGAY produced_path + seed + model vào plan.json (GAP_3 C-9).
- [ ] C4 Retake: 1 biến/lần, budget đặt trước (5), log take.

## GATE D — QA MỐI CẮT (sau MỖI clip, và cuối phim)
- [ ] D1 Ghép cặp tail(N)|head(N+1) MỌI boundary (ffmpeg hstack) — soi mắt; lệch thế giới
      = reject tức thì.
- [ ] D2 Xem CẢ clip đầu-cuối (cấm duyệt bằng 1 frame giữa — s2 tai-cún đã lọt kiểu đó).

## GATE E — FINISHING (GAP_3 §3.2, thứ tự bắt buộc)
- [ ] E1 Trim-on-action từng clip (không bê nguyên 6s).
- [ ] E2 BGM 1 bản xuyên phim (music_lib mood map, CC-BY) mix DƯỚI SFX native.
      Phim silent: **CẤM narration** (double-voice ban — edl.validate_plan).
- [ ] E3 Master loudness −14 LUFS, TP ≤ −1 dBTP, audio 48k stereo chuẩn hoá.
- [ ] E4 promise-check motion_ratio ≥ floor (edl.assess_delivery) trước khi ship.
- [ ] E5 QA cuối: XEM TOÀN PHIM + toàn bộ cặp boundary một lượt nữa.

## NỢ CODE CAO (từ GAP — làm sau demo, trước production)
1. A9.15 Nối storyboard → render_real_video/veo_pipeline (render chưa import storyboard.clips).
2. ~~A9.16 FLF qua Flow~~ **TRẢ 2026-08-02**: `flow_browser.gen_video_flf` (Khung hình 2 slot,
   duration, trpc pull) + `convert_flf` + `supports_last_frame=True`. Còn lại của A9.16:
   flow_api RPC thuần (không UI) — sau.
3. A9.4 frames.py: attach ảnh prev-frame role composition-only (hiện chỉ text) —
   **một phần**: film_runner.gate_stills đính [anchor]+extra_refs khi regen still.
4. A9.2 ImagePrompt/VideoPrompt YAML schema thay free-string — **một phần**: film.yaml
   spec (stills+shots+style clauses) cho film path.
5. GAP_2: layout_description + available_slots/slot vào Shot/continuity; identity anchors 6 lớp
   + industrial sheet vào refsheet; scene-early binding; candidate confirm UI.
6. ~~GAP_3 plan.json write-back nhánh Flow~~ **TRẢ 2026-08-02**: film_runner ghi plan.json
   sau MỖI clip (edl.VideoPlan.with_produced + save_plan) + qa_report.json + assembly.json.
   Còn: segment_break flag; VO-length duration gate (không áp cho phim silent).

## STYLE LOCK (bổ sung 2026-08-02 — từ user reject v4 "style frame đầu ≠ frame cuối")
- [x] SL1 Metric lineart contrast-normalized + STILL_GATE 0.030 / BOUNDARY_GATE 0.07
      (`storyboard/style_lock.py`, calibrate trên data v4: good ≤0.022, bad ≥0.042).
- [x] SL2 Kiến trúc still-to-still FLF: CẤM tail-carry làm input (neural softening
      tích lũy — tail(F1) đã 0.22 vs head(F1) trong 1 clip). Mọi clip = FLF(K_N→K_N+1).
- [x] SL3 Fixed anchor (StoryGen): mọi still so/regen với CÙNG anchor K1 + style clause
      "không thương lượng" (AIComicBuilder LAST_FRAME_STYLE_MATCHING) + style string
      cố định mọi prompt (ArcReel).
- [x] SL4 Gate thứ tự Orkas: verify still (free) TRƯỚC khi trả tiền video; reroll bounded 3.
- [ ] SL5 Vision-LLM continuity QA non-blocking (AIComicBuilder) — nâng cấp sau.
