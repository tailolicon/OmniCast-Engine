# OmniCast Improvement Roadmap — Inspired by AutoVio

> **Mục đích**: Lộ trình chi tiết để vá hai điểm yếu được user xác định: **giao diện người dùng** và **phần sinh video**. Tham chiếu kiến trúc: `E:\Project\autovio-0.1.0`.
>
> **Nguyên tắc**: KHÔNG vứt phần mạnh của OmniCast (niche discovery, debate writer↔critic, vault, scheduler, channel guard). Chỉ thay phần yếu, mượn pattern AutoVio.
>
> **Ledger**: Mỗi task có file/line đích, deliverable, est. effort, blocker.
>
> _Last updated: 2026-05-28_

---

## 0. Snapshot trạng thái hiện tại

### Phần đã làm tốt (giữ nguyên)
- `niche_flow.py` + `src/omnicast/discovery/` — niche discovery với outlier detection, dynamic seed generator, key rotator.
- `content_flow.py` + `src/omnicast/agents/` — debate writer ↔ critic, 100-point scoring.
- `src/omnicast/api/server.py` — FastAPI backend với pipeline state, niche endpoints, runs.
- `src/omnicast/llm/` — multi-provider LLM client (Anthropic + DeepSeek), cost tracking, circuit breaker.

### Phần stub/placeholder (cần sửa)
| File | Vấn đề | Hậu quả |
|------|--------|---------|
| `@e:\Project\OmniCast Engine\implementation\src\omnicast\media\image_gen.py:76-87` | `_queue_prompt` return cứng `"prompt_123"`, `_wait_and_download` không poll thật | Image gen hoàn toàn không chạy |
| `@e:\Project\OmniCast Engine\implementation\src\omnicast\media\video_gen.py:34-57` | Wan21 và Ken Burns đều return path giả, không gọi ComfyUI/FFmpeg | Video gen không chạy |
| `@e:\Project\OmniCast Engine\implementation\src\omnicast\media\ffmpeg.py:66-75` | `_run_ffmpeg` placeholder, return `duration_seconds=300.0` cứng | Render không tạo file thật |
| `@e:\Project\OmniCast Engine\OmniCast Dashboard.html` | 135KB monolithic HTML, React qua CDN Babel in-browser, polling REST | UI không production-grade, khó maintain, không scale |

### Phần AutoVio làm tốt (mượn pattern)
- **Provider abstraction**: `IImageProvider`, `IVideoProvider` interfaces (`@e:\Project\autovio-0.1.0\packages\backend\src\providers\interfaces.ts:29-54`) + registry (`@e:\Project\autovio-0.1.0\packages\backend\src\providers\registry.ts:39-47`).
- **Per-scene approval flow**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\GenerateStep.tsx:99-260` — mỗi scene là card riêng, status `pending → generating_image → image_ready → generating_video → done`, có `approve & generate video` + `edit & regenerate`.
- **Side panel edit prompt**: `ImageEditPanel.tsx`, `VideoEditPanel.tsx` — user can luôn can thiệp prompt trước khi regenerate.
- **5-step wizard + Stepper**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\Stepper.tsx` — Setup → Analyze → Scenario → Generate → Editor.
- **Real Veo/Runway integration**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\video\gemini.ts:14-128` — poll operation, fetch URI with API key, return data URL.
- **Timeline editor + Export**: `@xzdarcy/react-timeline-editor` + `EZFFMPEG` lib với clip/audio/text/image overlay.

---

## 1. Lộ trình tổng thể (5 đợt)

| Đợt | Tên | Effort (ngày-người) | Phụ thuộc | Mục tiêu |
|-----|-----|-------|-----------|----------|
| **W1** | Provider abstraction + Gemini Image/Veo thật | 3 | none | Image gen + Video gen chạy thật cho 1 scene |
| **W2** | FFmpeg render thật + per-scene state SQLite | 3 | W1 | 1 video MP4 final hoạt động end-to-end |
| **W3** | Per-scene approval UX (vẫn trong dashboard.html) | 2 | W1 | User duyệt từng scene, edit prompt, regenerate |
| **W4** | SPA migration foundation (Vite + React + TS + Tailwind + Zustand) | 4 | none (parallel với W1-W3) | Frontend mới chạy song song, port Home + Niches |
| **W5** | SPA Generate Step + Editor Step | 5 | W3, W4 | Wizard đầy đủ, timeline editor cơ bản |

**Tổng**: ~17 ngày-người. Có thể parallel W1+W2 (backend) với W4 (frontend) → ~12 ngày calendar.

---

## 2. ĐỢT W1 — Provider Abstraction + Real Image/Video Gen

### W1.T1 — Tạo provider interface chuẩn
- **File mới**: `implementation/src/omnicast/media/providers/__init__.py`, `interfaces.py`
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\interfaces.ts:29-54`
- **Deliverable**: Python protocol classes
  ```python
  class IImageProvider(Protocol):
      id: str
      name: str
      models: list[ModelOption]
      async def generate(self, prompt: str, negative: str = "",
                          model: str | None = None,
                          resolution: tuple[int,int] | None = None,
                          output_path: str | None = None) -> str: ...

  class IVideoProvider(Protocol):
      id: str
      async def convert(self, image_path: str, prompt: str,
                        duration: int, model: str | None = None,
                        resolution: tuple[int,int] | None = None,
                        output_path: str | None = None) -> str: ...
  ```
- **Effort**: 0.5 ngày
- **Test**: `tests/media/test_providers_interfaces.py` — kiểm tra protocol khớp.

### W1.T2 — Implement GeminiImageProvider thật
- **File mới**: `implementation/src/omnicast/media/providers/image_gemini.py`
- **API**: Gemini Image API (đã có `settings.google_api_key`), endpoint `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent`
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\image\gemini.ts`
- **Deliverable**: Class implement `IImageProvider`, return absolute path tới file PNG đã ghi vào `output_dir`.
- **Effort**: 0.5 ngày
- **Test**: integration test với real key (skip if `GOOGLE_API_KEY` empty).

### W1.T3 — Implement GeminiVideoProvider (Veo 3) thật
- **File mới**: `implementation/src/omnicast/media/providers/video_gemini.py`
- **API**: Gemini Veo 3, model `veo-3.0-generate-001`, dùng Python SDK `google-genai` (poll operation 5s/lần, max 120 attempts).
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\video\gemini.ts:14-128` (port logic poll + fetch URI sang Python).
- **Deliverable**: Class implement `IVideoProvider`, poll `operation.done`, download video qua URI với header `x-goog-api-key`, ghi MP4 vào `output_path`.
- **Effort**: 1 ngày (poll logic + edge case `videoBytes` vs `uri`).
- **Test**: smoke test với 1 image + duration=4s.

### W1.T4 — Implement ComfyUIImageProvider (alternative)
- **File mới**: `implementation/src/omnicast/media/providers/image_comfyui.py`
- **Note**: Code hiện có `image_gen.py` đã có skeleton ComfyUI. Refactor thành provider class, implement `_queue_prompt` thật (POST `/prompt`), `_wait_and_download` thật (poll `/history/{id}`, GET `/view?filename=...`).
- **Effort**: 1 ngày (cần ComfyUI server chạy local để test).
- **Optional**: có thể defer sang W2 nếu Gemini đủ dùng.

### W1.T5 — Provider registry + config
- **File mới**: `implementation/src/omnicast/media/providers/registry.py`
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\registry.ts`
- **Deliverable**: `get_image_provider(id)`, `get_video_provider(id)`, `list_providers()`. Default từ `settings.media_image_provider`, `settings.media_video_provider`.
- **Settings mới** trong `@e:\Project\OmniCast Engine\implementation\src\omnicast\config\settings.py`:
  ```python
  media_image_provider: str = Field(default="gemini")
  media_video_provider: str = Field(default="gemini")
  media_image_model: str = Field(default="gemini-2.5-flash-image-preview")
  media_video_model: str = Field(default="veo-3.0-generate-001")
  ```
- **Effort**: 0.5 ngày

### W1.T6 — Wire vào MediaPipelineOrchestrator
- **File sửa**: `@e:\Project\OmniCast Engine\implementation\src\omnicast\media\orchestrator.py:179-189` (`_run_images`), `:198-214` (`_run_video_gen`)
- **Thay đổi**: Bỏ gọi trực tiếp `ImageGenModule.process()`, thay bằng `provider = get_image_provider(brand.image_provider or settings.media_image_provider); await provider.generate(...)`.
- **Backwards compat**: Giữ class `ImageGenModule` cũ làm wrapper deprecation (xóa sau W2).
- **Effort**: 0.5 ngày
- **Test**: end-to-end test 1 scene với dry-run mode.

**Tổng W1**: ~3 ngày.

---

## 3. ĐỢT W2 — FFmpeg Real Render + Per-Scene State

### W2.T1 — Implement FFmpegModule thật
- **File sửa**: `@e:\Project\OmniCast Engine\implementation\src\omnicast\media\ffmpeg.py:45-75`
- **Approach**: Dùng `ffmpeg-python` (`uv add ffmpeg-python`) hoặc subprocess trực tiếp.
- **Filter graph cần build**:
  - Concat video clips với `xfade=transition=fade:duration=0.5:offset=...`
  - Overlay voiceover (TTS) làm audio chính
  - Mix background music với `sidechaincompress` ducking khi voiceover present
  - Burn subtitle từ `.srt` qua filter `subtitles=path.srt`
  - Optional intro/outro concat trước/sau
- **Pattern tham khảo**: `@e:\Project\autovio-0.1.0\packages\backend\src\routes\export.ts:99-126` (EZFFMPEG abstraction).
- **Deliverable**: `_run_ffmpeg` thực thi `asyncio.create_subprocess_exec`, parse stderr cho duration, return `RenderResult` thật với `output_path` tồn tại + `file_size_mb` tính từ `os.stat`.
- **Effort**: 1.5 ngày (filter graph phức tạp, cần test thật).
- **Test**: render 3-scene script với placeholder images → verify MP4 hợp lệ.

### W2.T2 — Per-scene SQLite state
- **File sửa**: `@e:\Project\OmniCast Engine\implementation\src\omnicast\vault\` (đã có `vault.db`)
- **Schema mới**: bảng `scene_renders`:
  ```sql
  CREATE TABLE scene_renders (
      id INTEGER PRIMARY KEY,
      script_id TEXT NOT NULL,
      scene_index INTEGER NOT NULL,
      status TEXT NOT NULL,  -- pending|generating_image|image_ready|generating_video|done|error
      image_path TEXT, image_prompt TEXT, image_provider TEXT,
      video_path TEXT, video_prompt TEXT, video_provider TEXT,
      error_msg TEXT,
      created_at TIMESTAMP, updated_at TIMESTAMP,
      UNIQUE(script_id, scene_index)
  );
  ```
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\GenerateStep.tsx:326-371` (status enum).
- **Deliverable**: Module `vault/scene_renders.py` với `upsert_status`, `get_by_script`, `get_pending`.
- **Effort**: 0.5 ngày
- **Lý do**: Cho phép resume khi crash, hiển thị real-time status trong UI, cho phép user re-generate 1 scene mà không phải re-render toàn bộ.

### W2.T3 — Endpoint per-scene
- **File sửa**: `@e:\Project\OmniCast Engine\implementation\src\omnicast\api\server.py`
- **Endpoint mới**:
  - `POST /api/scripts/{script_id}/scenes/{idx}/generate-image` — trigger image gen 1 scene
  - `POST /api/scripts/{script_id}/scenes/{idx}/approve` — approve image, trigger video gen
  - `POST /api/scripts/{script_id}/scenes/{idx}/regenerate` (body: new prompt) — edit + regenerate
  - `GET /api/scripts/{script_id}/scenes` — list tất cả scene + status
  - `POST /api/scripts/{script_id}/render` — assemble final khi tất cả scene done
- **Effort**: 1 ngày
- **Test**: integration test full per-scene flow.

**Tổng W2**: ~3 ngày.

---

## 4. ĐỢT W3 — Per-Scene UX (vẫn trong dashboard.html)

### Lý do vẫn dùng dashboard.html ở đợt này
- SPA migration (W4) tốn 4 ngày, song song với W1-W2 nhưng W3 cần ship sớm để có feedback.
- Pattern AutoVio có thể implement trong vanilla React + CDN (giữ kiến trúc hiện tại).

### W3.T1 — Component `ScenesPanel` mới
- **File sửa**: `@e:\Project\OmniCast Engine\OmniCast Dashboard.html`
- **Thêm tab mới**: "Scenes" (sau "Pipeline", trước "Vault").
- **UI elements** (mượn từ `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\GenerateStep.tsx:104-176`):
  - Mỗi scene là 1 card grid 2-cột: trái = image preview, phải = video preview
  - Status badge: pending / generating_image (loader) / image_ready (blue dot) / generating_video / done (green check) / error
  - Action buttons theo status:
    - `pending` → "Generate Image"
    - `image_ready` → "Approve & Generate Video" + "Edit & Regenerate"
    - `done` → "Regenerate Video" + "Back to Image"
    - `error` → "Retry" + "Edit Prompt"
- **Effort**: 1 ngày

### W3.T2 — Side panel edit prompt
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\ImageEditPanel.tsx`
- **Deliverable**: Modal/drawer để edit `image_prompt` / `negative_prompt` / `video_prompt`, click "Regenerate" → POST `.../regenerate`.
- **Effort**: 0.5 ngày

### W3.T3 — Polling status real-time
- **Approach**: Dashboard hiện tại đã có polling `/api/pipeline` 2s/lần. Thêm polling `/api/scripts/{id}/scenes` khi user ở tab Scenes.
- **Effort**: 0.5 ngày

**Tổng W3**: ~2 ngày.

---

## 5. ĐỢT W4 — SPA Foundation

### W4.T1 — Init monorepo structure
- **Thư mục mới**: `frontend/` (peer của `implementation/`)
- **Stack**: Vite 5 + React 18 + TS 5.7 + TailwindCSS 3 + Zustand 4 (đúng stack AutoVio)
- **Files khởi tạo**:
  ```
  frontend/
    package.json (npm/bun workspace)
    vite.config.ts
    tsconfig.json
    tailwind.config.js
    postcss.config.js
    index.html
    src/
      main.tsx
      App.tsx
      api/client.ts (axios với baseURL từ env)
      store/usePipelineStore.ts (Zustand)
      components/Layout.tsx
      components/ui/ (Button, Card, Toast — copy AutoVio)
  ```
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\` toàn bộ structure.
- **Effort**: 1 ngày

### W4.T2 — Layout + nav
- **File mới**: `frontend/src/components/Layout.tsx`
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\Layout.tsx:44-137`
- **Deliverable**: Header với gradient logo, breadcrumb, settings dropdown. Sidebar nav với Lucide icons (Home, Channels, Niches, Scripts, Renders, Vault, Budget).
- **Effort**: 0.5 ngày

### W4.T3 — Port Home tab
- **Source**: code React hiện tại trong `OmniCast Dashboard.html` (tab Home — KPI cards, active jobs, recent results)
- **Target**: `frontend/src/pages/HomePage.tsx`
- **Effort**: 1 ngày

### W4.T4 — Port Niches tab
- **Source**: tab Niches từ HTML
- **Target**: `frontend/src/pages/NichesPage.tsx`
- **Effort**: 1 ngày

### W4.T5 — Auth (defer hoặc minimal)
- **Decision**: OmniCast hiện single-user local, có thể skip auth trong MVP. Nếu cần multi-user → port pattern JWT từ AutoVio.
- **Effort**: 0 ngày (skip) hoặc 1 ngày (minimal token).

### W4.T6 — Build + serve config
- **Approach**: Vite build → static files vào `implementation/static/`. FastAPI mount `StaticFiles` ở `/`. Hoặc dev mode: Vite proxy `/api/*` về FastAPI port 8765.
- **Effort**: 0.5 ngày

**Tổng W4**: ~4 ngày (có thể parallel với W1-W3).

---

## 6. ĐỢT W5 — SPA Generate + Editor Steps

### W5.T1 — Stepper component
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\Stepper.tsx`
- **Adapt cho OmniCast**: 4 step thay vì 5 (vì niche/script đã làm xong ở backend):
  - 1 Brand (chọn channel + style preset)
  - 2 Script (review/edit script đã debate xong)
  - 3 Generate (per-scene image+video)
  - 4 Editor (timeline + export)
- **Effort**: 0.5 ngày

### W5.T2 — Generate Step (port từ W3)
- **Source**: code W3 đã làm trong dashboard.html
- **Target**: `frontend/src/pages/GeneratePage.tsx`
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\GenerateStep.tsx` toàn bộ
- **Deliverable**: Per-scene cards, status badges, side panel edit, real-time polling qua React Query (cache + refetch).
- **Effort**: 1.5 ngày

### W5.T3 — Editor Step (timeline)
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\editor\Timeline.tsx` + `EditorTimeline.tsx`
- **Library**: `@xzdarcy/react-timeline-editor` (đã có trong AutoVio)
- **Deliverable**: Drag-drop clip timeline, transition picker, audio waveform, text overlay, image overlay.
- **Effort**: 2 ngày (lib này có learning curve)
- **Note**: MVP có thể skip timeline editor, chỉ cần "Export" button gọi `/api/scripts/{id}/render`.

### W5.T4 — Export modal
- **Pattern mượn**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\editor\ExportDialog.tsx`
- **Deliverable**: Modal chọn resolution/fps, progress bar, download MP4.
- **Effort**: 1 ngày

**Tổng W5**: ~5 ngày.

---

## 7. Quyết định kiến trúc cần xác nhận

| # | Câu hỏi | Default đề xuất | Lý do |
|---|---------|----------------|-------|
| Q1 | Image provider mặc định? | **Gemini Image** | Cùng API key Veo, free tier rộng, không cần ComfyUI server local |
| Q2 | Video provider mặc định? | **Gemini Veo 3** | Cùng API key, OmniCast đã có `google_api_key` setting |
| Q3 | Có giữ ComfyUI integration không? | **Có, P3** | Cho user muốn on-prem/free, defer sang W2 |
| Q4 | SPA framework? | **Vite + React + TS** | Khớp AutoVio, ecosystem mature |
| Q5 | State management? | **Zustand** | Khớp AutoVio, nhẹ hơn Redux, dễ port logic |
| Q6 | Styling? | **Tailwind** | Khớp AutoVio, nhanh prototype |
| Q7 | Bun hay npm? | **npm** (đề xuất) | Bun = thêm dependency cho Windows; npm đủ dùng |
| Q8 | Auth trong SPA? | **Skip MVP** | OmniCast single-user local, thêm sau nếu deploy multi-user |
| Q9 | Timeline editor có làm MVP không? | **Defer P3** | Phức tạp 2 ngày; MVP chỉ cần export button |
| Q10 | Giữ `OmniCast Dashboard.html` cũ? | **Có, song song** | Dashboard cũ cho ops; SPA mới cho production user |

---

## 8. Rủi ro

| Rủi ro | Mức | Mitigation |
|--------|-----|------------|
| Gemini Veo 3 quota giới hạn ở free tier | Cao | Check quota trước W1.T3, fallback Runway/Kling provider |
| FFmpeg filter graph phức tạp gây bug | Cao | W2.T1 dành 1.5 ngày, có buffer; viết test render với synthetic input |
| Polling per-scene quá nặng (poll 50 scenes × 2s) | Trung | Server-Sent Events thay polling (defer P3) |
| Migration HTML→SPA gây regression cho ops users | Trung | Giữ HTML cũ (Q10), SPA chạy port khác |
| Timeline editor library learning curve | Trung | Defer P3 (Q9), MVP không cần |
| AGENTS.md max 3 files/session vs scope lớn | Cao | Chia thành nhiều session, mỗi đợt là 1 PR |

---

## 9. Phụ thuộc kỹ thuật

### Python deps mới
```
ffmpeg-python>=0.2.0       # W2.T1
google-genai>=0.3.0        # W1.T2, W1.T3 (đã có thể đã trong project)
```

### Frontend deps mới
```json
{
  "react": "^18.3.0",
  "react-dom": "^18.3.0",
  "vite": "^5.4.0",
  "typescript": "^5.7.0",
  "tailwindcss": "^3.4.0",
  "zustand": "^5.0.0",
  "@tanstack/react-query": "^5.59.0",
  "lucide-react": "^0.468.0",
  "axios": "^1.7.0",
  "@xzdarcy/react-timeline-editor": "^0.1.x"  // W5.T3 only
}
```

### Env mới (`.env.example`)
```
# === Media Pipeline ===
MEDIA_IMAGE_PROVIDER=gemini      # gemini | comfyui | dalle
MEDIA_VIDEO_PROVIDER=gemini       # gemini | runway | comfyui
MEDIA_IMAGE_MODEL=gemini-2.5-flash-image-preview
MEDIA_VIDEO_MODEL=veo-3.0-generate-001

# Optional alternative providers
COMFYUI_URL=http://127.0.0.1:8188
RUNWAY_API_KEY=
```

---

## 10. Thứ tự thực thi đề xuất (single dev)

```
Week 1: W1.T1 → W1.T2 → W1.T3 → W1.T5 → W1.T6  (3 ngày)
Week 1-2: W2.T1 → W2.T2 → W2.T3                 (3 ngày)
Week 2: W3.T1 → W3.T2 → W3.T3                   (2 ngày)
                                                ─────────
                          Mốc 1: Video gen thật end-to-end (8 ngày)

Week 3: W4.T1 → W4.T2 → W4.T3 → W4.T4 → W4.T6   (4 ngày)
Week 3-4: W5.T1 → W5.T2 → W5.T4                 (3 ngày)
                                                ─────────
                          Mốc 2: SPA production (15 ngày)

Week 4-5: W5.T3 (timeline editor — optional)    (2 ngày)
                                                ─────────
                          Mốc 3: Full editor (17 ngày)
```

**Khuyến nghị MVP**: dừng ở Mốc 2 (15 ngày), Timeline editor defer.

---

## 11. Acceptance criteria

### Mốc 1 — Video gen thật
- [ ] `python -X utf8 -m omnicast.media.providers.image_gemini --test "a cat"` ghi PNG hợp lệ
- [ ] Pipeline orchestrator render 3-scene script → MP4 mở được trong VLC
- [ ] Tất cả test trong `tests/media/` pass
- [ ] Không còn placeholder string "prompt_123" hoặc "wan21_output.mp4" trong codebase

### Mốc 2 — SPA production
- [ ] `cd frontend && npm run dev` mở browser localhost:5173, hiển thị Home + Niches từ FastAPI
- [ ] User tạo 1 video end-to-end qua wizard: chọn channel → review script → generate per-scene → approve → export MP4
- [ ] Per-scene status sync real-time với SQLite
- [ ] Build production: `npm run build` → static files serve qua FastAPI ở `/`

### Mốc 3 — Timeline editor
- [ ] Drag scene clip trên timeline, đổi thứ tự, đổi duration
- [ ] Add text overlay với position + duration
- [ ] Export modal có progress bar, download MP4 thật

---

## 12. Câu hỏi mở cho user

1. Có muốn giữ ComfyUI integration không (offline alternative)? Hay chỉ Gemini cloud?
2. Quota Gemini Veo 3 đã verify chưa? (Veo 3 thuộc paid tier)
3. Có cần multi-user auth ngay không?
4. Timeline editor có thực sự cần cho MVP không? (Phần lớn user chỉ cần generate + export)
5. Có muốn migration toàn bộ sang frontend mới và xóa `OmniCast Dashboard.html` không, hay chạy song song?

---

## Tham chiếu

- `@e:\Project\OmniCast Engine\AGENTS.md` — protocol ràng buộc
- `@e:\Project\OmniCast Engine\IMPLEMENTATION_DELTA.md` — trạng thái thực tế hiện tại
- `@e:\Project\OmniCast Engine\PROJECT_CONTEXT.md` — thiết kế gốc (single source of truth kiến trúc)
- `@e:\Project\OmniCast Engine\plan\current_plan.md` — plan ngắn (file này expand từ đó)
- `@e:\Project\autovio-0.1.0\` — hệ tham chiếu UI/Media
