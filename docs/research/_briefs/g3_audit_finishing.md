Đọc trước: `docs/research/_briefs/COMMON_CONTEXT.md`. Vai trò: KIỂM TOÁN VIÊN ÁP DỤNG.

# Gap Audit 3 — LỚP HOÀN THIỆN PHIM: Reports 06 + 07 + blueprint + lớp dựng/âm thanh

Demo Miko hiện dừng ở "concat clip thô" — thiếu toàn bộ lớp hoàn thiện mà các repo có.
Nhiệm vụ: kiểm toán lớp ASSEMBLY/EDITING/AUDIO/DELIVERY.

Nguồn phải rà: `docs/research/REFS_SB_06_ShortVideoEngines.md` (subtitle sync, BGM/loudnorm,
TTS-first duration, hook, metadata), `REFS_SB_07_hyperframes.md` (EDL/timing contract,
caption presets, transitions catalog, PSNR golden), `docs/research/WS1_Storyboard_Blueprint.md`
(mọi mục P0/P1/P2 + §3 dual-aspect + §5 bảng thực thi + §6 build-state),
và code: `pipeline/edl.py`, `media/music_lib.py`, `subtitle_sync.py` (nếu có),
`qa_check.py`, `render_real_video.py` (phần assemble), demo log DEMO_STATE.md.

Với từng khuyến nghị/lớp: phân loại ÁP DỤNG ĐÚNG / MỘT PHẦN / BỎ QUA / VI PHẠM + severity
+ bằng chứng. Đặc biệt trả lời: để phim Miko (silent + nhạc/SFX, chuẩn silent-cute Shorts)
"chạy tốt như repo", lớp dựng cần đúng những bước nào theo thứ tự nào (trim-on-action,
BGM mood map, duck/mix SFX native, caption?, loudness -14 LUFS, promise-check motion_ratio,
QA cuối = soi CẶP FRAME TẠI MỖI MỐI CẮT).

Output: `docs/research/GAP_3_finishing.md` — bảng + quy trình dựng chuẩn cho demo + TOP-10.
Chỉ ghi file đó. Cấm sửa code, cấm sửa `_refs`.
