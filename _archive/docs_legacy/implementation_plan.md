> ⚠️ **LỖI THỜI / ĐÃ VƯỢT QUA (2026-06-18).** Tài liệu này mô tả sai trạng thái: gọi `media/orchestrator.py` là "mock skeleton", `tts_local` Kokoro/Piper là "mock stub", và nhắc "Streamlit dashboard" — thực tế `media/orchestrator.py` là orchestrator thật đang chạy, Kokoro/XTTS đã có impl thật (Piper đã gỡ), dashboard nay là React (`frontend/`). Tin `IMPLEMENTATION_STATUS.md`. Giữ lại chỉ để tham khảo lịch sử.

# OmniCast Engine - Consolidation & Enhancement Plan

This plan details the technical steps to resolve the rendering engine fracture, bridge the missing dashboard UI elements for rendering and uploading, fix database driver warnings, and align the system's OpenAPI specifications.

## User Review Required

> [!IMPORTANT]
> The rendering code is currently split: `src/omnicast/media/orchestrator.py` is a mock skeleton, while `render_real_video.py` is the functional CLI. We propose deprecating the mock `ffmpeg.py` and porting `render_real_video.py`'s functionality into the modular `FFmpegModule` class.

> [!WARNING]
> The database has split storage architectures: `omnicast.db` uses PostgreSQL, and FastAPI endpoints use SQLite `vault.db`. Streamlit dashboard components fail to load PostgreSQL stats because `psycopg2` is missing from the environment. We propose adding `psycopg2-binary` to dependencies, but we need to align on whether PostgreSQL remains a requirement or if SQLite should serve as the unified SSOT.

## Proposed Changes

---

### Component 1: Media Pipeline Unification

#### [MODIFY] [ffmpeg.py](file:///e:/Project/OmniCast%20Engine/implementation/src/omnicast/media/ffmpeg.py)
- Replace mock `_run_ffmpeg` with the subprocess call to the actual FFmpeg compilation logic currently housed in `render_real_video.py`.
- Ensure subtitle burn-in, audio mixing (voice + bgm), and video loop overlays are compiled using the `EZFFMPEG` filter builder.

#### [MODIFY] [tts_local.py](file:///e:/Project/OmniCast%20Engine/implementation/src/omnicast/media/providers/tts_local.py)
- Replace the mock stubs for `KokoroTTSProvider` and `PiperTTSProvider` with functional implementations using `kokoro-onnx` and standard `piper` local execution.

#### [MODIFY] [server.py](file:///e:/Project/OmniCast%20Engine/implementation/src/omnicast/api/server.py)
- Refactor `POST /api/render/{channel_id}` to import and invoke `MediaPipelineOrchestrator` directly instead of executing `subprocess.Popen` on `render_real_video.py`.

---

### Component 2: Dashboard Frontend Completion

#### [MODIFY] [App.jsx](file:///e:/Project/OmniCast%20Engine/frontend/src/App.jsx)
- **New Rendering Tab**: Display live stages, rendering logs, and per-shot image previews fetched from `GET /api/render/status`.
- **New Upload Tab**: Provide a control center to preview the final video metadata, manage YouTube OAuth tokens, and trigger uploads.
- **Active Jobs Fix**: Modify the pipeline columns to display active `"render"` and `"images"` jobs instead of filtering only for discovery and script-gen.

---

### Component 3: Database & Dependencies

#### [MODIFY] [pyproject.toml](file:///e:/Project/OmniCast%20Engine/implementation/pyproject.toml)
- Add `psycopg2-binary>=2.9,<3` to dependencies to resolve connection failures in `DashboardDataService`.

---

## Verification Plan

### Automated Tests
- Run database connection validations:
  ```powershell
  python -c "from omnicast.dashboard.data_service import DashboardDataService; ... verify create_engine works"
  ```
- Run local TTS unit tests:
  ```powershell
  pytest tests/unit/test_media_orchestrator.py
  ```

### Manual Verification
- Launch the backend server:
  ```powershell
  python run_backend.py
  ```
- Rebuild and preview the dashboard:
  ```powershell
  cd frontend
  npm run dev
  ```
- Verify the rendering status matches the visual timeline in the new dashboard tabs.
