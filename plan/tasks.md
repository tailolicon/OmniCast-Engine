# Tasks Dispatch — OmniCast Improvement

> **Cách dùng**: Mỗi task atomic, đủ context để spawn 1 Sonnet/Haiku session độc lập. Đọc cùng `plan/improvement_roadmap.md` (chi tiết) và `AGENTS.md` (protocol).
>
> **Model routing**:
> - **sonnet** — implement feature, integrate API
> - **haiku** — types/interfaces, scaffolding, scripts cấu hình, docs/comments, simple tests
>
> _Last updated: 2026-05-28_

---

## ⛔ GLOBAL GUARDRAILS — KHÔNG ĐƯỢC SỬA

Mọi task bên dưới chỉ thêm/sửa file ghi rõ trong "Outputs". **Không được chạm** các module sau (đây là moat của OmniCast):

| Module | Path | Lý do |
|---|---|---|
| Niche discovery | `implementation/src/omnicast/discovery/` | Đã verify chạy < 30s sau parallel fix gần đây |
| Debate writer↔critic | `implementation/src/omnicast/agents/orchestrator.py`, `writer.py`, `critic.py` | Logic 100-point scoring đã calibrated |
| LLM client | `implementation/src/omnicast/llm/` | Cost tracking, rate limit, circuit breaker đã wire |
| Vault SQLite | `implementation/src/omnicast/vault/`, `output/vault.db` schema cũ | Single source of truth — chỉ ADD bảng mới, không alter bảng cũ |
| YouTube key rotator | `implementation/src/omnicast/discovery/key_rotator.py` | Quota safety |
| Niche scanner | `implementation/src/omnicast/discovery/niche_scanner.py` | Đã có per-query progress callback, parallel semaphore |
| FastAPI endpoint cũ | `server.py` các route hiện có (`/api/niches`, `/api/pipeline`, etc.) | Chỉ ADD route mới, không sửa route cũ |
| Dashboard.html cũ | `OmniCast Dashboard.html` | Giữ nguyên cho ops; SPA mới chạy song song |

**Quy tắc edit**: nếu task đụng file ngoài "Outputs", DỪNG, hỏi user trước.

---

## ĐỢT W1 — Provider Abstraction + Real Image/Video Gen

### T1.1 — Provider interfaces  [haiku]
- **Outputs**: `implementation/src/omnicast/media/providers/__init__.py`, `interfaces.py`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\interfaces.ts:29-54`
- **Spec**:
  ```python
  # interfaces.py
  from typing import Protocol, NamedTuple

  class ModelOption(NamedTuple):
      id: str
      name: str
      description: str = ""

  class IImageProvider(Protocol):
      id: str
      name: str
      models: list[ModelOption]
      async def generate(self, prompt: str, *, negative: str = "",
                         model: str | None = None,
                         resolution: tuple[int, int] | None = None,
                         output_path: str) -> str: ...

  class IVideoProvider(Protocol):
      id: str
      name: str
      models: list[ModelOption]
      async def convert(self, image_path: str, prompt: str, *,
                        duration: int = 5, model: str | None = None,
                        resolution: tuple[int, int] | None = None,
                        output_path: str) -> str: ...
  ```
- **Test**: `tests/media/test_providers_interfaces.py` — kiểm `isinstance` không cần (Protocol structural), chỉ assert import OK.
- **Effort**: 30 phút

### T1.2 — GeminiImageProvider  [sonnet]
- **Outputs**: `implementation/src/omnicast/media/providers/image_gemini.py`
- **Dep**: T1.1, `pip install google-genai>=0.3.0`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\image\gemini.ts`
- **Spec**:
  - Class `GeminiImageProvider` implement `IImageProvider`
  - `id="gemini"`, `name="Google Gemini Image"`, models=`[ModelOption("gemini-2.5-flash-image-preview", "Gemini 2.5 Flash Image")]`
  - `generate()`: gọi `google.genai` SDK với `settings.google_api_key`, save bytes ra `output_path`, return absolute path
  - Handle: response không có image bytes → raise `MediaError`
- **Test**: `tests/media/test_image_gemini.py` — skip nếu không có `GOOGLE_API_KEY`, chỉ test happy path 1 prompt nhỏ "a red cube"
- **Don't touch**: image_gen.py cũ (xóa ở T1.6)
- **Effort**: 2-3h

### T1.3 — GeminiVideoProvider (Veo 3)  [sonnet]
- **Outputs**: `implementation/src/omnicast/media/providers/video_gemini.py`
- **Dep**: T1.1, T1.2 (cùng SDK)
- **Reference**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\video\gemini.ts:14-128` (đọc kỹ logic poll + fetch URI)
- **Spec**:
  - Class `GeminiVideoProvider`, models `veo-3.0-generate-001`, `veo-3.1-generate-preview`
  - `convert()`:
    1. Load image_path, encode base64 + mime type
    2. Clamp duration vào {4, 6, 8}
    3. Aspect ratio từ resolution (9:16 / 16:9 / 1:1)
    4. `ai.models.generate_videos(...)` → operation
    5. Poll `ai.operations.get_videos_operation(operation)` mỗi 5s, max 120 attempts
    6. Khi done: lấy `response.generated_videos[0]`, prefer `videoBytes` over `uri`
    7. Nếu `uri`: fetch với header `x-goog-api-key`, save bytes ra `output_path`
    8. Return absolute path MP4
- **Test**: `tests/media/test_video_gemini.py` — skip mặc định (Veo paid tier), document cách bật manual
- **Effort**: 4-6h (port logic AutoVio + edge case)

### T1.4 — Provider registry  [haiku]
- **Outputs**: `implementation/src/omnicast/media/providers/registry.py`
- **Dep**: T1.2, T1.3
- **Reference**: `@e:\Project\autovio-0.1.0\packages\backend\src\providers\registry.ts:39-71`
- **Spec**:
  ```python
  _IMAGE: dict[str, IImageProvider] = {"gemini": GeminiImageProvider()}
  _VIDEO: dict[str, IVideoProvider] = {"gemini": GeminiVideoProvider()}

  def get_image_provider(id: str) -> IImageProvider: ...   # raise if missing
  def get_video_provider(id: str) -> IVideoProvider: ...
  def list_providers() -> list[dict]: ...                  # for /api/providers
  ```
- **Test**: `tests/media/test_registry.py` — assert `get_image_provider("gemini")` not None
- **Effort**: 30 phút

### T1.5 — Settings keys  [haiku]
- **Outputs**: edit `implementation/src/omnicast/config/settings.py` + `.env.example`
- **Spec**: thêm 4 fields:
  ```python
  media_image_provider: str = Field(default="gemini")
  media_video_provider: str = Field(default="gemini")
  media_image_model: str = Field(default="gemini-2.5-flash-image-preview")
  media_video_model: str = Field(default="veo-3.0-generate-001")
  ```
  Update `.env.example` với 4 dòng tương ứng
- **Don't touch**: existing fields (claude, deepseek, youtube)
- **Effort**: 15 phút

### T1.6 — Scene schema upgrade (additive, backward-compat)  [haiku]
- **Outputs**: edit `implementation/src/omnicast/models/script.py:80-90` (chỉ ADD field, không xóa)
- **Spec**: thêm 5 field optional vào `ScriptScene`:
  ```python
  class ScriptScene(OmnicastSchema):
      voiceover: str
      visual_prompt: str          # GIỮ NGUYÊN — stock footage query (legacy)
      sfx: str | None = None
      duration_s: float = 0.0
      # === MỚI — AI media gen fields (optional, populate by VisualDirectorAgent) ===
      image_prompt: str = ""           # detailed prompt for image generation
      negative_prompt: str = ""        # what to avoid
      video_prompt: str = ""           # camera/motion for image-to-video
      text_overlay: str = ""           # text to display on scene
      transition: str = "cut"          # cut | fade | dissolve | whip-pan
  ```
- **Don't touch**: existing fields, ScriptDraft, ScriptSegment structure
- **Don't break**: WriterAgent output parsing — vì field default=`""`, draft cũ vẫn parse OK
- **Test**: `tests/models/test_script_scene_compat.py` — load ScriptDraft cũ từ vault.db, assert không raise validation error
- **Effort**: 30 phút

### T1.7 — StyleGuide model + prompt builder  [sonnet]
- **Outputs**:
  - `implementation/src/omnicast/media/style_guide.py`
  - `implementation/src/omnicast/media/prompt_builder.py`
- **Reference**:
  - StyleGuide format: `@e:\Project\autovio-0.1.0\packages\backend\src\prompts\scenario.ts:7-33`
  - Image prefix: `@e:\Project\autovio-0.1.0\packages\backend\src\prompts\image.ts:7-68`
  - Video prefix: `@e:\Project\autovio-0.1.0\packages\backend\src\prompts\video.ts:6-35`
- **Spec**:
  ```python
  # style_guide.py
  class StyleGuide(BaseModel):
      tone: str = ""              # "energetic" | "professional" | "calm" | "playful"
      color_palette: list[str] = []   # hex codes ["#FF0000", "#00FF00"]
      tempo: str = ""             # "fast" | "medium" | "slow"
      camera_style: str = ""      # "static documentary" | "dynamic handheld" | etc
      brand_voice: str = ""       # free text
      must_include: list[str] = []
      must_avoid: list[str] = []

  # prompt_builder.py — port từ AutoVio
  DEFAULT_IMAGE_INSTRUCTION = (
      "Generate a high-quality photorealistic image. Cinematic composition, "
      "natural lighting, sharp focus, professional photography quality."
  )
  DEFAULT_VIDEO_INSTRUCTION = (
      "Animate this image into a smooth 5-second video clip. Subtle natural "
      "motion, cinematic camera movement, no jarring cuts."
  )

  def build_image_style_prefix(guide: StyleGuide) -> str:
      # Port y AutoVio image.ts:7-27 — ghép "Professional photography...",
      # "rich {colors} color palette", tone→style, tempo→composition
      ...

  def build_video_style_prefix(guide: StyleGuide) -> str:
      # Port y AutoVio video.ts:6-19 — ghép camera_style, tempo→motion, tone→cinematic
      ...

  def build_full_image_prompt(scene_image_prompt: str, guide: StyleGuide,
                              extra_instruction: str = "") -> str:
      """Format: [style_prefix]\n\n[default_or_custom_instruction]\n\n[scene_prompt]"""
      parts = []
      prefix = build_image_style_prefix(guide)
      if prefix: parts.append(prefix)
      parts.append(extra_instruction or DEFAULT_IMAGE_INSTRUCTION)
      parts.append(scene_image_prompt)
      return "\n\n".join(parts)

  def build_full_video_prompt(scene_video_prompt: str, guide: StyleGuide,
                              extra_instruction: str = "") -> str:
      # tương tự
      ...
  ```
- **Test**: `tests/media/test_prompt_builder.py` — golden output cho 3 case (empty guide, partial guide, full guide)
- **Effort**: 3-4h

### T1.8 — VisualDirectorAgent (sinh image_prompt/video_prompt từ ScriptDraft)  [sonnet]
- **Outputs**: `implementation/src/omnicast/agents/visual_director.py`
- **Dep**: T1.6, T1.7. Existing `BaseAgent` ở `implementation/src/omnicast/agents/base.py`, LLMClient ở `implementation/src/omnicast/llm/client.py`
- **Reference**: `CriticFeedback.visual_fixes` ở `script.py:152` đã hint design này từ trước
- **Don't touch**: writer.py, critic.py, orchestrator.py (debate)
- **Spec**:
  - Class `VisualDirectorAgent(BaseAgent)` với method `enrich(draft: ScriptDraft, guide: StyleGuide) -> ScriptDraft`
  - Cho mỗi scene trong mỗi segment: gọi LLM (DeepSeek chat hoặc Claude Haiku — model rẻ vì task formulaic) để convert `voiceover + visual_prompt + sfx` → `(image_prompt, negative_prompt, video_prompt, transition)`
  - Batching: 1 LLM call per segment (~5-10 scene), không phải 1 call per scene
  - Output: ScriptDraft mới với scenes đã populated 5 field mới
- **System prompt template** (cho Sonnet implement chính xác):
  ```
  You are a Visual Director. Convert each scene's narration + b-roll query
  into AI generation prompts for image and image-to-video models.

  For EACH scene, output JSON:
  {
    "scene_idx": <int>,
    "image_prompt": "Detailed visual description for AI image generation.
                    Concrete subjects, setting, lighting, composition.
                    50-80 words. NO camera motion (that's video_prompt's job).",
    "negative_prompt": "Things to avoid: blurry, distorted, watermark, text,
                       low quality, deformed faces, extra limbs",
    "video_prompt": "Camera and motion description for image-to-video.
                    Subject motion, camera move (pan/zoom/dolly), pacing.
                    20-40 words. References the image.",
    "transition": "cut | fade | dissolve | whip-pan"
  }

  Style guide context:
  {style_guide_markdown}

  Continuity rule: each scene continues from the previous (same world,
  same characters, same lighting unless scene change). Use transition to
  signal scene breaks.
  ```
- **User prompt template**:
  ```
  Brief: {brief.title}
  Niche: {brief.niche}
  Brand voice: {brief.brand_voice}

  Process this segment ({segment.heading}):
  {scenes_as_numbered_list}

  Output a JSON array of {len(scenes)} objects in scene order.
  ```
- **Test**: `tests/agents/test_visual_director.py` — mock LLM, feed 3-scene draft, assert all 5 new fields populated, scene_idx khớp
- **Effort**: 1 ngày

### T1.9 — Wire orchestrator → VisualDirector → providers  [sonnet]
- **Outputs**: edit `implementation/src/omnicast/media/orchestrator.py`
- **Dep**: T1.7, T1.8, T1.4, T1.5
- **Spec**:
  - Thêm param `style_guide: StyleGuide | None = None` vào `MediaPipelineOrchestrator.run()`
  - Thêm step 0 (trước TTS): nếu scenes chưa có `image_prompt` → gọi `VisualDirectorAgent.enrich(draft, guide)` để populate
  - `_run_images`:
    ```python
    provider = get_image_provider(brand.image_provider or settings.media_image_provider)
    for i, scene in enumerate(all_scenes):
        full_prompt = build_full_image_prompt(scene.image_prompt, guide)
        results.append(await provider.generate(
            prompt=full_prompt,
            negative=scene.negative_prompt,
            model=settings.media_image_model,
            output_path=f"{output_dir}/scene_{i:03d}.png",
        ))
    ```
  - `_run_video_gen`: tương tự với `build_full_video_prompt(scene.video_prompt, guide)`, image_path từ image gen step
  - Bỏ `ImageGenModule` / `VideoGenModule` (deprecated, có thể giữ class shell trống cho backward compat)
- **Don't break**: `MediaPipelineState` flow, `parallel gather`, signature `run()` chỉ ADD param mới optional
- **Test**: `tests/media/test_orchestrator_e2e.py` — full pipeline mock provider + mock visual director, 3 scene → assert image+video paths return non-empty
- **Effort**: 4h

---

## ĐỢT W2 — FFmpeg Real Render + Per-Scene State

### T2.1 — FFmpeg real implementation  [sonnet]
- **Outputs**: rewrite `implementation/src/omnicast/media/ffmpeg.py:45-75`
- **Dep**: `pip install ffmpeg-python>=0.2.0`
- **Spec**:
  - `_build_command(job)` build filter graph:
    - Concat video layers với `xfade` (transition 0.5s)
    - amix voiceover + music; sidechaincompress duck music khi voiceover present
    - Burn subtitle: `subtitles=path.srt`
    - Output: `-c:v libx264 -c:a aac -preset medium`, `-y` overwrite
  - `_run_ffmpeg`: `asyncio.create_subprocess_exec`, capture stderr, parse `Duration: HH:MM:SS.SS` cho duration thật
  - Validate output file exists + size > 0 trước khi return `RenderResult`
  - `_get_file_size_mb`: `os.stat(path).st_size / 1024 / 1024`
- **Don't break**: signature `_process(request: RenderJob) -> RenderResult`, dry-run path `_dry_run_result`
- **Test**: `tests/media/test_ffmpeg_real.py` — render synthetic 3-scene (color cards) + 5s sine wave audio, assert MP4 hợp lệ qua `ffprobe`
- **Effort**: 1-2 ngày (filter graph nhất là edge case ít clip)

### T2.2 — SQLite scene_renders table  [haiku]
- **Outputs**:
  - Migration mới: `implementation/alembic/versions/<id>_add_scene_renders.py`
  - Module mới: `implementation/src/omnicast/vault/scene_renders.py`
- **Spec**:
  - Schema:
    ```sql
    CREATE TABLE scene_renders (
        id INTEGER PRIMARY KEY,
        script_id TEXT NOT NULL,
        scene_index INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN
            ('pending','generating_image','image_ready',
             'generating_video','done','error')),
        image_path TEXT, image_prompt TEXT, image_provider TEXT,
        video_path TEXT, video_prompt TEXT, video_provider TEXT,
        error_msg TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(script_id, scene_index)
    );
    CREATE INDEX idx_scene_renders_script ON scene_renders(script_id);
    ```
  - Module API:
    ```python
    def upsert_scene(script_id, scene_index, **fields) -> None
    def get_scenes(script_id) -> list[dict]
    def get_scene(script_id, scene_index) -> dict | None
    ```
- **Don't touch**: bảng `niches`, `health_logs`, `scripts` đã có
- **Test**: `tests/vault/test_scene_renders.py`
- **Effort**: 1h

### T2.3 — Per-scene API endpoints  [sonnet]
- **Outputs**: edit `implementation/src/omnicast/api/server.py` (chỉ ADD routes)
- **Dep**: T2.2, T1.6
- **Spec**: 5 endpoints mới:
  ```
  GET    /api/scripts/{script_id}/scenes
         → list[scene] với status
  POST   /api/scripts/{script_id}/scenes/{idx}/generate-image
         body: {prompt: str, negative?: str}
         → 202 + background task gọi image_provider.generate
  POST   /api/scripts/{script_id}/scenes/{idx}/approve
         → 202 + background task gọi video_provider.convert
  POST   /api/scripts/{script_id}/scenes/{idx}/regenerate
         body: {image_prompt?: str, video_prompt?: str}
         → re-run từ state thích hợp
  POST   /api/scripts/{script_id}/render
         → 202 + background task gọi ffmpeg.process khi tất cả scene `done`
  ```
- **Pattern**: dùng `BackgroundTasks` của FastAPI giống `/api/discover-niches` đã có
- **Don't touch**: route cũ, `set_active_job`, `state.py`
- **Test**: `tests/api/test_scenes_endpoints.py`
- **Effort**: 4h

---

## ĐỢT W3 — Per-Scene UX trong Dashboard.html cũ (optional, có thể skip nếu W4 ưu tiên)

### T3.1 — Tab "Scenes" trong dashboard.html  [sonnet]
- **Outputs**: edit `OmniCast Dashboard.html` (thêm tab + component, không sửa tab cũ)
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\GenerateStep.tsx:99-260`
- **Spec**: render React component (CDN Babel) với:
  - Grid card per scene (image preview + video preview)
  - Status badge (`StatusBadge` từ AutoVio:326-371)
  - Action buttons theo status (Generate Image / Approve / Edit & Regen / Retry)
  - Polling `/api/scripts/{id}/scenes` 2s khi tab active
- **Don't touch**: tab Home, Pipeline, Niches, Vault, Budget hiện có
- **Effort**: 1 ngày
- **Note**: nếu user prefer bỏ qua W3 và đi thẳng W4 (SPA), skip task này

### T3.2 — Side panel edit prompt  [sonnet]
- **Outputs**: tiếp tục edit `OmniCast Dashboard.html`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\ImageEditPanel.tsx`
- **Spec**: drawer/modal với textarea cho `image_prompt` + `negative_prompt`, nút "Regenerate" → POST `.../regenerate`
- **Effort**: 3h

---

## ĐỢT W4 — SPA Foundation

### T4.1 — Vite project init  [haiku]
- **Outputs**: tạo `frontend/` (peer của `implementation/`)
  - `package.json`, `vite.config.ts`, `tsconfig.json`, `tailwind.config.js`, `postcss.config.js`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/styles/globals.css`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\` (copy structure)
- **Spec**:
  - Stack: React 18 + Vite 5 + TS 5.7 + TailwindCSS 3 + Zustand 5 + axios + lucide-react
  - `vite.config.ts`: dev proxy `/api/*` → `http://127.0.0.1:8765`
  - `App.tsx` placeholder render "OmniCast SPA"
- **Test**: `npm run dev` mở localhost:5173 hiển thị placeholder
- **Effort**: 1h

### T4.2 — API client + Zustand store  [haiku]
- **Outputs**: `frontend/src/api/client.ts`, `frontend/src/store/usePipelineStore.ts`
- **Spec**:
  - `client.ts`: axios instance baseURL `/api`, interceptor cho error toast
  - `usePipelineStore`: state cho `niches`, `scripts`, `scenes`, `activeJob`, actions `fetchNiches`, `fetchScenes`, etc.
- **Effort**: 1-2h

### T4.3 — Layout + Sidebar  [sonnet]
- **Outputs**: `frontend/src/components/Layout.tsx`, `Sidebar.tsx`, `Topbar.tsx`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\Layout.tsx:44-137`
- **Spec**: gradient logo "OmniCast", sidebar items (Home, Niches, Scripts, Scenes, Vault, Budget) với Lucide icons; topbar status (server health từ `/api/status`)
- **Effort**: 4h

### T4.4 — Home page (port từ HTML)  [sonnet]
- **Outputs**: `frontend/src/pages/HomePage.tsx`
- **Reference**: tab Home trong `OmniCast Dashboard.html` (logic React đã có sẵn, chỉ port sang TS)
- **Spec**: KPI cards (channels, scripts pending, scripts done, budget spent), active jobs list, recent results table
- **Don't reinvent**: copy data shape từ `/api/pipeline`, `/api/status`, `/api/budget` đã có
- **Effort**: 4h

### T4.5 — Niches page  [sonnet]
- **Outputs**: `frontend/src/pages/NichesPage.tsx`, components con
- **Reference**: tab Niches trong HTML
- **Spec**: niche list với score, evidence channels, "Create channel" button gọi `/api/niches/{id}/create`
- **Effort**: 4-6h

### T4.6 — Build + serve  [haiku]
- **Outputs**: edit `frontend/package.json` build script + edit `implementation/src/omnicast/api/server.py` mount static
- **Spec**:
  - `npm run build` → `frontend/dist/`
  - server.py: `app.mount("/", StaticFiles(directory=Path(__file__)/.../frontend/dist, html=True))` SAU TẤT CẢ route `/api/*`
  - Dev mode: vite proxy như T4.1
- **Don't touch**: route /api/* hiện có
- **Effort**: 1h

---

## ĐỢT W5 — SPA Generate + Editor

### T5.1 — Stepper + ScriptDetail layout  [sonnet]
- **Outputs**: `frontend/src/pages/ScriptDetailPage.tsx`, `frontend/src/components/Stepper.tsx`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\Stepper.tsx`
- **Spec**: 4 steps (Brand / Script / Generate / Export), điều hướng theo state script
- **Effort**: 3h

### T5.2 — GeneratePage (per-scene)  [sonnet]
- **Outputs**: `frontend/src/pages/GeneratePage.tsx`, `SceneCard.tsx`, `ImageEditPanel.tsx`, `VideoEditPanel.tsx`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\steps\GenerateStep.tsx` (port toàn bộ)
- **Spec**: status enum y hệt AutoVio, polling 2s qua React Query (`@tanstack/react-query`), action buttons gọi endpoints T2.3
- **Effort**: 1.5 ngày

### T5.3 — Export modal  [sonnet]
- **Outputs**: `frontend/src/components/ExportDialog.tsx`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\editor\ExportDialog.tsx`
- **Spec**: modal chọn resolution (1080p/720p/4K), fps (24/30/60), gọi `POST /api/scripts/{id}/render`, poll progress, download link khi xong
- **Effort**: 4h

### T5.4 — Timeline editor  [sonnet, OPTIONAL]
- **Outputs**: `frontend/src/pages/EditorPage.tsx`, `Timeline.tsx`, `PropertiesPanel.tsx`
- **Reference**: `@e:\Project\autovio-0.1.0\packages\frontend\src\components\editor\Timeline.tsx`
- **Dep**: `npm install @xzdarcy/react-timeline-editor`
- **Spec**: drag-drop scene clip, transition picker, text overlay
- **Note**: defer P3, không bắt buộc cho MVP
- **Effort**: 2 ngày

---

## Kiểm tra cuối mỗi đợt

### Sau W1 (mốc partial)
```bash
.venv\Scripts\python.exe -m pytest tests/media/ -v
.venv\Scripts\python.exe -c "from omnicast.media.providers.registry import get_image_provider, get_video_provider; print(get_image_provider('gemini').name, get_video_provider('gemini').name)"
```
Pass criteria: import OK, không còn string `prompt_123` / `wan21_output.mp4` trong codebase (`grep -r "prompt_123" implementation/src/`)

### Sau W2 (mốc 1 — video gen e2e)
```bash
.venv\Scripts\python.exe -m pytest tests/media/test_ffmpeg_real.py tests/api/test_scenes_endpoints.py -v
.venv\Scripts\python.exe -m omnicast.media.smoke_render  # script test 3 scene synthetic
ffprobe output/test_render.mp4   # verify hợp lệ
```

### Sau W4 (mốc partial SPA)
```bash
cd frontend && npm run build
# Mở browser http://localhost:8765 → Home + Niches hiển thị từ FastAPI
```

### Sau W5 (mốc 2 — SPA production)
End-to-end manual test:
1. Chọn channel → review script → generate scene 1 → approve → video gen → approve → render → download MP4
2. Edit prompt scene 2 → regenerate → confirm thay đổi
3. Resume sau crash: tắt server giữa chừng, restart, verify state SQLite còn

---

## Quy tắc spawn worker

Khi spawn Sonnet session làm task TX.Y, prompt mẫu:
```
Task: TX.Y from plan/tasks.md
Read first: AGENTS.md, plan/tasks.md (section "GLOBAL GUARDRAILS"), plan/improvement_roadmap.md (section TX.Y)
Reference repo: E:\Project\autovio-0.1.0
Don't touch files outside the task's "Outputs" list.
Run the test in "Test:" section before reporting done.
```

Cho Haiku task scaffold/types/migration: prompt ngắn hơn, chỉ cần "Outputs" + "Spec" + "Test".
