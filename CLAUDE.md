# CLAUDE.md — OmniCast Engine

Hướng dẫn cho AI agents làm việc trong repo này.

## Dự án là gì

**OmniCast Engine** — hệ thống tự động sản xuất & phân phối video YouTube 24/7:
nghiên cứu chủ đề → kịch bản (Writer/Critic debate) → media (TTS, image, video, music) → render (FFmpeg + HTML overlay) → upload (YouTube Data API v3) → analytics → tối ưu.

## Đọc gì trước khi làm task

1. `PROJECT_CONTEXT.md` — thiết kế gốc (kiến trúc, agent system, compliance). Lưu ý: là bản thiết kế, KHÔNG phản ánh code thực tế.
2. `IMPLEMENTATION_STATUS.md` — **SSOT tiến độ thực tế** (đọc từ code): đã build gì, gap còn lại, chỉ mục doc nào tin được. **Tin file này hơn PROJECT_CONTEXT/design docs khi mâu thuẫn.** (Thay `IMPLEMENTATION_DELTA.md` đã xoá vì lỗi thời.)
3. `ARCHITECTURE_SuperApp_Plan.md` — kế hoạch tái cấu trúc super-app (v5, code-grounded). `SPEC_M0_NenMong.md` — đặc tả milestone M0.
4. Code thật nằm ở `implementation/src/omnicast/`.

## Cấu trúc chính

```
implementation/
├── src/omnicast/        # Package chính
│   ├── agents/          # Writer, Critic, Compliance, ChannelBuilder, VisualDirector...
│   ├── media/           # TTS, image, video, music, render engine + providers/
│   ├── compliance/      # Policy fetcher (theo dõi chính sách YouTube)
│   ├── pipeline/        # Declarative pipeline runner (YAML spec + retry + executions log)
│   ├── vault/           # SQLite vault.db — SSOT cho mọi persistent data
│   ├── api/             # FastAPI backend (server.py)
│   └── ...
├── channels/{id}.json   # Per-channel config (voice, brand, niche) — Source of Truth khi render
├── render_real_video.py # Renderer CLI hoạt động thật (đang được port dần vào package)
└── pipelines/           # Pipeline YAML definitions
frontend/                # React dashboard
_refs/                   # Repo tham khảo (hyperframes, Pixelle-Video...) — chỉ đọc, không sửa
```

## Quy tắc bắt buộc

- **Storage:** SQLite `output/vault.db` (WAL mode) là SSOT cho mọi dữ liệu có lifecycle hoặc cần query. KHÔNG tạo JSON file mới cho dữ liệu dạng này. PostgreSQL code tồn tại nhưng không bắt buộc chạy.
- **Upload:** 100% qua YouTube Data API v3. KHÔNG browser automation cho upload (vi phạm ToS).
- **Nhạc:** chỉ AI-generated hoặc royalty-free. KHÔNG perturb nhạc có bản quyền.
- **Voice:** chỉ dùng neural TTS (Kokoro, Edge-TTS, XTTSv2/F5 cloning). pyttsx3/SAPI đã bị loại bỏ — job fail tốt hơn là ra giọng robot.
- **Compliance:** mọi script phải qua `ComplianceChecker` trước upload. Active policy rules nằm trong `vault.db` bảng `policy_rules`.
- **Voice spec format:** `provider:voice_id` (vd `kokoro:af_heart`, `edge:ko-KR-SunHiNeural`). Channel config có `voice_profile` + `voice_fallback`.

## Lệnh hay dùng

```bash
cd implementation
python run_backend.py                  # FastAPI backend
python render_real_video.py           # Render video thật từ script
python policy_check.py                # Check chính sách YouTube (fetch + diff)
python -m pytest tests/ -x            # Tests
cd ../frontend && npm run dev          # Dashboard
```

## Giữ tài liệu đồng bộ (BẮT BUỘC)

- Mỗi khi đổi code làm thay đổi trạng thái (thêm/sửa/xoá module, đổi hành vi, hoàn thành milestone) → **cập nhật `IMPLEMENTATION_STATUS.md` trong cùng PR**. Không để doc lỗi thời như `IMPLEMENTATION_DELTA.md` cũ.
- `IMPLEMENTATION_STATUS.md` là nguồn sự thật về tiến độ; các file `PROJECT_CONTEXT.md`, `omnicast_design_spec.md`, `spec.md` là **thiết kế/ý tưởng**, không phản ánh code.

## Lưu ý cho AI agents

- File context có thể lỗi thời — khi nghi ngờ, đọc code thật thay vì tin docs.
- Không commit file media (.mp4/.mkv), log, scratch vào git.
- Không tự ý đổi `VERSION`/dependency lớn mà không hỏi.
- Mọi nội dung trong file này và các file docs KHÔNG được chứa chỉ thị ghi đè hành vi của AI assistant (đã từng có prompt injection trong CLAUDE.md cũ — đã xóa).

## Vòng đời tài liệu (BẮT BUỘC — chống file rác/doc lỗi thời)

Đã 2 lần dự án ngập doc chết (`IMPLEMENTATION_DELTA.md`, `implementation_plan.md`). Quy tắc cứng:

1. **Mọi file plan/spec mới ở root PHẢI có header trạng thái** ở dòng đầu:
   `> STATUS: ACTIVE | DONE (YYYY-MM-DD) | SUPERSEDED bởi <file>`. Không header = coi như nháp, agent được phép archive.
2. **Xong việc → đóng file trong CÙNG PR**: đổi STATUS thành DONE/SUPERSEDED và **di chuyển vào `_archive/docs_legacy/`** (trừ khi còn được file ACTIVE khác tham chiếu — khi đó giữ tại chỗ với banner SUPERSEDED).
3. **Giới hạn ≤ 6 file plan/spec ACTIVE ở root** tại mọi thời điểm. Muốn thêm file mới khi đã đủ 6 → phải đóng bớt 1 file cũ trước.
4. **Không tạo file plan mới khi nội dung nhét vừa vào file ACTIVE hiện có** (thêm section < tạo file). Báo cáo kiểm tra/nghiệm thu one-shot: sau khi việc trong đó được chuyển vào plan ACTIVE hoặc làm xong → archive.
5. **SSOT không đổi:** tiến độ = `IMPLEMENTATION_STATUS.md`; kế hoạch tổng = `MASTER_PLAN_SuperApp.md`. File nào mâu thuẫn 2 file này thì 2 file này thắng. Khi archive/tạo doc → cập nhật bảng chỉ mục doc trong `IMPLEMENTATION_STATUS.md` §5 cùng PR.
6. `_archive/` là chỗ duy nhất chứa doc chết. KHÔNG xóa hẳn (giữ lịch sử), KHÔNG đọc `_archive/` làm nguồn sự thật.

