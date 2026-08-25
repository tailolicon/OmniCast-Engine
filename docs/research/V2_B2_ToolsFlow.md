# V2_B2 — Tooling & Flow & Remotion

> STATUS: ACTIVE  
> Chiến dịch V2 · Nhóm B2 · Verbatim harvest + cơ chế  
> Nguồn: `_refs/VideoToolsPro/`, `_refs/KiraAP/`, `_refs/h2dev_flow/`, `_refs/tobyflow/`, `_refs/remotion/` (CHỈ ĐỌC)  
> Đối chiếu OmniCast: `media/providers/flow_browser.py`, `remotion_render.py`, `remotion_studio/src/*`, `animation/*`

---

## Pipeline tóm tắt (Tầng 2 — ngữ cảnh)

### VideoToolsPro
```
Binary Windows app (VideoToolsPro.exe) + bundled ffmpeg + torch models under _rt/
  → KHÔNG có source preset/filter chain đọc được trong repo snapshot
  → Chỉ còn ffmpeg.exe/ffprobe/ffplay + runtime Python site-packages
```

### KiraAP
```
Express + Mongo → agentPlatform.js
  text:  aiplatform generateContent / streamGenerateContent
  image: generateContent + responseModalities IMAGE|TEXT + refImages ≤3
  video: predictLongRunning + fetchPredictOperation (Veo LRO)
         | gemini-omni-flash-preview Interactions API (sync base64 video)
  tts:   generateContent + responseModalities AUDIO + speechConfig
```

### h2dev_flow
```
Chrome MV3 side panel → inject content.js vào labs.google/fx/*
  → DOM: tìm Slate prompt → type → ENTER/click generate
  → poll img ≥256px mới → download qua chrome.downloads
  → delay ngẫu nhiên 5–15s giữa prompt (anti-bot)
  → Dùng chrome.debugger (thanh vàng) — UI-only, không gọi API Flow
```

### tobyflow
```
Chrome extension (sidebar + content inject Flow)
  MODE A — DOM (web/ui): MessageBridge → content.js selectors
           (remote config từ labs.toby.vn api-configs + dom-selectors)
  MODE B — API (flow_api_enabled + BridgeClient):
           FlowApiAdapter → chrome.runtime.sendMessage(BRIDGE_ID)
           commands: flow_generate / flow_upload_ref / flow_poll_video /
                     flow_create_project / flow_resolve_tier / flow_upscale_*
           Token + tab Flow mở = sẵn sàng; poll video 10s / timeout 420s
  Cấu hình model/ratio/endpoint map **server-side** (không hardcode URL Google
  trong extension public) — bridge extension riêng ID heieobedadlfdkppgagnhfakcdapbfka
```

### remotion
```
Composition tree (Sequence / Series / TransitionSeries)
  → spring/interpolate animation → renderMedia / CLI remotion render
  → ffmpeg encode (default codec h264, crf 18) + optional audio
```

### OmniCast (hiện trạng)
```
flow_browser.py: Playwright persistent Chrome → UI Flow (vi locale)
  image: Ingredients attach + Nano Banana / Imagen chips
  video FLF: localStorage state + Bắt đầu/Kết thúc slots + gen
  video text: gen_video (image_path ignored in convert())
remotion_studio: IntroCard / StatPop / OutroCTA → remotion_render.py CLI
animation/: bible + lipsync + timing (không timeline Remotion)
```

---

## Bảng VERBATIM

### 1. h2dev_flow — CONFIG poll / submit

| field | value |
|-------|--------|
| **repo** | h2dev_flow |
| **file:line** | `content.js:13-31` |
| **loại** | config |
| **tóm tắt** | Ngưỡng ảnh, poll 2s, timeout 4 phút, settle 1.8s, submit ENTER |
| **OmniCast** | `flow_browser.py` wait loops tương tự (5s steps, FLF wait_s=480, video 600s) — tự chế, không có settleMs riêng |
| **khuyến nghị** | **GHÉP** `settleMs` + `minImageSize` khi poll DOM fallback |

```javascript
const CONFIG = {
  promptSelector: "",
  generateSelector: "",
  submitWithEnter: true,
  minImageSize: 256,
  pollMs: 2000,
  maxWaitMs: 240000,         // 4 phút / 1 ảnh
  settleMs: 1800,
};
```

### 2. h2dev_flow — selector fallback ô prompt (Slate)

| field | value |
|-------|--------|
| **repo** | h2dev_flow |
| **file:line** | `content.js:63-95` |
| **loại** | config |
| **tóm tắt** | Cascade selector Slate/contenteditable; hint đa ngôn ngữ |
| **OmniCast** | `_PROMPT_SEL = '[contenteditable="true"]'` (`flow_browser.py:35`) — yếu hơn cascade |
| **khuyến nghị** | **THAY** cascade + wake-click (h2dev `wakePromptBox`) |

```javascript
const selectors = [
  '[data-slate-editor="true"]',
  '[contenteditable="true"][role="textbox"]',
  '[role="textbox"][aria-multiline="true"]',
  'div[role="textbox"]',
  '[contenteditable="true"]',
  '[contenteditable=""]',
  "textarea",
];
const hint = /create|prompt|imagine|describe|tạo|生成|描述|생성|作成/i;
```

### 3. h2dev_flow — delay batch anti-bot

| field | value |
|-------|--------|
| **repo** | h2dev_flow |
| **file:line** | `sidepanel.html:58-65`, `sidepanel.js:193-197` |
| **loại** | config |
| **tóm tắt** | Nghỉ ngẫu nhiên 5–15s giữa ảnh |
| **OmniCast** | Có jitter rải rác; không preset delayMin/Max user-facing |
| **khuyến nghị** | **GHÉP** env `FLOW_DELAY_MIN/MAX` |

```html
<label>Nghỉ ngẫu nhiên giữa các ảnh (giây)</label>
<input id="delayMin" type="number" min="0" value="5" />
<span>đến</span>
<input id="delayMax" type="number" min="0" value="15" />
```

```javascript
function randDelay() {
  const a = Math.max(0, parseInt(els.delayMin.value) || 0);
  const b = Math.max(a, parseInt(els.delayMax.value) || 0);
  return (a + Math.random() * (b - a)) * 1000;
}
```

### 4. tobyflow — BridgeClient → extension bridge (API mode)

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `src/core/BridgeClient.js` (toàn file, ~đầu) |
| **loại** | config |
| **tóm tắt** | Bridge ID cố định; ping/status tokenReady+flowTabOpen; TTL cache 30s/5s |
| **OmniCast** | Không có bridge — Playwright direct UI |
| **khuyến nghị** | **GHÉP** mô hình: session token intercept + API calls (lộ trình Tầng 2) |

```javascript
const BRIDGE_ID = "heieobedadlfdkppgagnhfakcdapbfka";
const PING_TTL_MS = 3e4;   // 30s
const STATUS_TTL_MS = 5e3; // 5s
// getStatus → { tokenReady, tokenAgeMs, flowTabOpen, version }
// request(method, params) → chrome.runtime.sendMessage(BRIDGE_ID, {method, params})
```

### 5. tobyflow — FlowApiAdapter: gen types + endpoint keys (video)

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `src/core/providers/FlowApiAdapter.js` — `_computeVideoGenType` |
| **loại** | config |
| **tóm tắt** | Map refCount/isFrames/refVideo → genType + endpointKey server |
| **OmniCast** | FLF qua UI slots Bắt đầu/Kết thúc; chưa API genType |
| **khuyến nghị** | **THAY** lõi `convert_flf` sang API mode khi port bridge |

```javascript
// _computeVideoGenType(item, refCount):
// refVideoIds → { genType: "video_edit_video", endpointKey: "video_edit" }
// refCount===0 → { genType: "text_2_video", endpointKey: "video_text" }
// isFrames && refCount>=2 → { genType: "start_end_frame_2_video", endpointKey: "video_start_end" }
// !isFrames && refCount>=1 → { genType: "reference_frame_2_video", endpointKey: "video_references" }
// else → { genType: "frame_2_video", endpointKey: "video_generate" }
```

### 6. tobyflow — FlowApiAdapter: enums / defaults model-ratio

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `FlowApiAdapter.js` — `_imageRatio`, `_videoRatio`, `_imageModel`, `_videoResolutionEnum`, `_imageInputType` |
| **loại** | config |
| **tóm tắt** | Fallback enum Google Flow khi map server thiếu |
| **OmniCast** | Label UI: "Nano Banana Pro", "9:16", localStorage aspectRatio PORTRAIT/LANDSCAPE |
| **khuyến nghị** | **GHÉP** bảng enum khi gọi API |

```javascript
// defaults khi map server empty:
IMAGE_ASPECT_RATIO_LANDSCAPE
VIDEO_ASPECT_RATIO_LANDSCAPE
GEM_PIX_2                          // image model key
VIDEO_RESOLUTION_1080P
IMAGE_INPUT_TYPE_BASE_IMAGE        // kind base
IMAGE_USAGE_TYPE_ASSET             // kind asset
IMAGE_INPUT_TYPE_REFERENCE         // kind reference
// upscale keys:
veo_3_1_upsampler_4k | veo_3_1_upsampler_1080p
// tier cache: PAYGATE_TIER_* (default PAYGATE_TIER_ONE), TTL 300_000 ms
// max concurrent API jobs: ExecutionConfig.getQueueMaxMonitor() || 4
// max video refs: 3 (fallback)
```

### 7. tobyflow — Bridge commands + payload shapes (nguyên văn schema adapter)

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `FlowApiAdapter.js` — `uploadRef`, `_submitImage`, `_submitVideo`, `_pollVideoById`, `upscaleVideo`, `_resolveProjectId`, `_resolveTier` |
| **loại** | config |
| **tóm tắt** | Toàn bộ command bridge + input fields (URL HTTP thật nằm trong bridge riêng / server config `api_endpoints`) |
| **OmniCast** | UI-only; không command layer |
| **khuyến nghị** | **THAY** skeleton `FlowApiClient` mirror các command này |

```javascript
// --- CREATE PROJECT ---
_bridgeFlow("flow_create_project", {
  config: rawApiConfig,   // from ProviderConfigManager.getRawApiConfig("flow")
  input: { title: string }
});
// response: { ok, projectId }

// --- RESOLVE TIER ---
_bridgeFlow("flow_resolve_tier", { config });
// response: { tier: "PAYGATE_TIER_ONE" | ... }

// --- UPLOAD REF IMAGE ---
_bridgeFlow("flow_upload_ref", {
  config,
  input: {
    imageBytes: string,   // base64 bare (strip data: prefix)
    mimeType: "image/jpeg",
    fileName: "ref.jpg",
    projectId: uuid
  }
});
// response: { ok, uuid }  // media UUID

// --- GENERATE IMAGE ---
_bridgeFlow("flow_generate", {
  kind: "image",
  config,
  input: {
    projectId, tier,
    prompt: string,
    refUuids: string[],
    aspect: "IMAGE_ASPECT_RATIO_*",
    model: "GEM_PIX_2" | mapped,
    isEdit: boolean,
    quantity: number,
    inputTypeBase: "IMAGE_INPUT_TYPE_BASE_IMAGE",
    inputTypeRef: "IMAGE_INPUT_TYPE_REFERENCE"
  }
});
// response: { ok, media: [{ name: uuid, image: { generatedImage: { fifeUrl }, fifeUrl }, durable_url }] }

// --- GENERATE VIDEO ---
_bridgeFlow("flow_generate", {
  kind: "video",
  config,
  input: {
    projectId, tier,
    prompt: string,
    refUuids: string[],           // image refs only when edit
    ratioEnum: "VIDEO_ASPECT_RATIO_*",
    videoModelKey: string,        // from api_video_model_keys[model][genType]
    genType: "text_2_video" | "start_end_frame_2_video" | "reference_frame_2_video"
            | "frame_2_video" | "video_edit_video",
    endpointKey: "video_text" | "video_start_end" | "video_references"
               | "video_generate" | "video_edit",
    maxRefs: number,
    inputTypeAsset: "IMAGE_USAGE_TYPE_ASSET",
    // only video_edit_video:
    editVideoUuid, editStartFrame, editEndFrame
  }
});
// response: { ok, mediaId }

// --- POLL VIDEO ---
// interval: api_rate_limits.poll_interval_ms (>=5000) else 10000
// timeout:  api_rate_limits.video_timeout_ms || 420000 (7 min)
_bridgeFlow("flow_poll_video", { config, mediaId, projectId });
// response: { ok, status: "done"|"failed"|pending,
//   videoUrl, videoBase64, durableUrl,
//   failureReason, failureReasons, rawStatus, rawMetadataKeys }

// --- UPSCALE VIDEO ---
_bridgeFlow("flow_upscale_video", {
  config,
  input: { mediaId, projectId, tier, ratioEnum, resolutionEnum, upModelKey }
});

// --- UPSCALE IMAGE ---
_bridgeFlow("flow_upscale_image", {
  config,
  input: { mediaId, projectId, tier, targetResolution }
});
```

### 8. tobyflow — start/end frame = refUuids + isFrames (API path)

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `FlowApiAdapter.js` `_computeVideoGenType` + `_submitVideo` |
| **loại** | config |
| **tóm tắt** | Ảnh bắt đầu/kết thúc = upload UUID → `refUuids` length≥2 + `settings.isFrames===true` → genType `start_end_frame_2_video` |
| **OmniCast** | UI slot click + file input (`flow_browser.py:1603-1640`) |
| **khuyến nghị** | **THAY** FLF: upload 2 still → API start_end (bỏ picker giòn) |

```javascript
// item.refFileIds / item.refFileNames map local id → UUID
// item.settings.isFrames === true && refCount >= 2
//   → genType "start_end_frame_2_video", endpointKey "video_start_end"
// Thứ tự refUuids = thứ tự frame (start rồi end) — adapter gửi mảng imageRefUuids nguyên
```

### 9. tobyflow — server config endpoints (Toby control plane)

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `ProviderConfigManager.js` `_doFetchApiConfigs`, `_BOOTSTRAP_URLS`; `background.js` API_BASE |
| **loại** | config |
| **tóm tắt** | Config remote; Flow UI base URL bootstrap |
| **OmniCast** | Hardcode `_FLOW_HOME = "https://labs.google/fx/vi/tools/flow"` |
| **khuyến nghị** | **GHÉP** remote selector store nếu giữ DOM fallback |

```javascript
// background.js
const API_BASE_DEFAULT = "https://labs.toby.vn/api/v1";

// ProviderConfigManager
`${baseUrl}/api/v1/providers/api-configs`     // GET, headers: Accept, X-Extension-Id, signed
`${baseUrl}/api/v1/providers/dom-selectors`   // GET
// cache TTL: 4h; grace 24h; headers RequestSigner
_BOOTSTRAP_URLS.flow = {
  base: "https://labs.google/fx/tools/flow",
  tabQuery: "https://labs.google/fx/*"
};
// keys đọc runtime:
// api_endpoints, api_model_mapping, api_video_model_keys,
// api_image_ratio_mapping, api_video_ratio_mapping,
// api_video_resolutions, api_image_input_types,
// api_image_upsample_resolutions, api_rate_limits,
// api_error_codes, api_video_edit {start_frame_index, end_frame_index},
// flow_api_key, captcha_config, error_patterns, download_resolutions
```

### 10. tobyflow — timing / humanize / retry defaults (content)

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `content.js` helpers `getInputTimeoutMs2`, `getDelayBetweenPromptsMs2`, `getRandomDelay2`, `getExponentialBackoffMs2`, `isHumanizedEnabled2` |
| **loại** | config |
| **tóm tắt** | Timeout nhập 1200ms; delay giữa prompt 5s; random 3–10s; backoff 30s base → 300s max, jitter 20% |
| **OmniCast** | Không exponential backoff Flow; abort khi block |
| **khuyến nghị** | **GHÉP** backoff + humanized delay vào flow_browser |

```javascript
// inputTimeout default 1200
// clearEditorDelay = inputTimeout * 0.4
// submitDelay = inputTimeout * 0.5
// afterSubmitDelay = inputTimeout * 0.8
// settingsStepDelay = inputTimeout * 0.3
// delay_between_prompts_sec default 5
// randomDelayMin/Max default 3..10 (seconds)
// humanizedSpeed default 0.5; jitter ±30% of adjusted
// flowBackoffBaseSec=30, flowBackoffMaxSec=300, flowBackoffJitterPercent=20
//  → ms = min(base*2^retry, max) * (1 ± jitter)
// EditorExecutor: _batchSize=4, _restMin=5000, _restMax=15000
// zoom guard heartbeat 20000ms; session deadline constant _ZOOM_SESSION_DEADLINE_MS
// oneShot poll agent-ready: 1500ms × 60s
// selector wait max: _SELECTOR_WAIT_MAX_MS
```

### 11. tobyflow — captcha / quota / rate_limit classification

| field | value |
|-------|--------|
| **repo** | tobyflow |
| **file:line** | `content.js` `_classifyFlowErrorText2`, `_getFlowErrorState2`, `_showCaptchaOverlay2` |
| **loại** | config |
| **tóm tắt** | Phân loại toast/widget → captcha|quota|rate_limit|policy; pause workflow |
| **OmniCast** | `FlowBlocked` / `FlowModelQuota` exceptions — tốt nhưng thiếu captcha resume UX |
| **khuyến nghị** | **GHÉP** category map + pause-resume |

```javascript
// error_patterns keys (server strings pipe-separated):
// captcha_text | quota_text | rate_limit_text | policy_text | upload_blocked_text
// recaptcha widget selectors:
// iframe[src*="google.com/recaptcha"]
// iframe[src*="recaptcha/api2/bframe"]
// iframe[src*="recaptcha/enterprise"]
```

### 12. KiraAP — system prompt chat default

| field | value |
|-------|--------|
| **repo** | KiraAP |
| **file:line** | `server/seed.js:36-42` |
| **loại** | prompt |
| **tóm tắt** | System prompt VI cho Kira Agent Platform |
| **OmniCast** | Writer/Critic có prompt riêng — không liên quan tooling Flow |
| **khuyến nghị** | **BỎ QUA** (không thuộc media pipeline OmniCast) |

```
Bạn là Kira Agent Platform, một trợ lý AI thông minh, thân thiện và hữu ích. Trả lời bằng tiếng Việt khi người dùng hỏi bằng tiếng Việt.
```

### 13. KiraAP — model seed + parameters

| field | value |
|-------|--------|
| **repo** | KiraAP |
| **file:line** | `server/seed.js:34-173` |
| **loại** | config |
| **tóm tắt** | Model IDs + temperature/aspect/duration/voice defaults |
| **OmniCast** | providers video_gemini / TTS riêng; có thể đối chiếu model ids |
| **khuyến nghị** | **GHÉP** Veo duration sets + omni model id vào provider registry |

```javascript
// text defaults
parameters: { temperature: 0.7, maxOutputTokens: 65536 }
// models: gemini-3.6-flash (default), 3.5-flash, 3.5-flash-lite, 3.1-pro,
//         gemini-3-flash-preview, gemini-2.5-flash, gemini-2.5-pro

// image defaults
parameters: { aspectRatio: '1:1' }
// gemini-3.1-flash-image (default), 3.1-flash-lite-image, 3-pro-image, 2.5-flash-image

// video defaults
// veo-3.1-lite-generate-001 (default): { aspectRatio: '16:9', durationSeconds: 4 }
// veo-3.0-generate-001: durationSeconds 4
// veo-2.0-generate-001: durationSeconds 5
// gemini-omni-flash-preview: durationSeconds 4

// tts defaults
// gemini-3.1-flash-tts-preview: { voiceName: 'alloy' }
// voice map alloy→Kore, echo→Fenrir, fable→Aoede, onyx→Charon, ...
```

### 14. KiraAP — image generate payload

| field | value |
|-------|--------|
| **repo** | KiraAP |
| **file:line** | `server/services/agentPlatform.js:288-330` (+ skill payload) |
| **loại** | config |
| **tóm tắt** | Endpoint + parts + generationConfig image |
| **OmniCast** | `media/providers/image_gemini.py` (tương đương Vertex) |
| **khuyến nghị** | **GHÉP** refImages ≤3 + aspectRatio imageConfig nếu thiếu |

```javascript
const endpoint = `https://aiplatform.googleapis.com/v1/publishers/google/models/${model.modelId}:generateContent?key=${apiKey}`;
// parts: [{ text: prompt }, ...{ inlineData: { mimeType, data } } max 3 refs]
// generationConfig (skill doc):
{
  imageConfig: { aspectRatio },  // '1:1'|'16:9'|'9:16'|'4:3'
  responseModalities: ['IMAGE', 'TEXT']
}
```

### 15. KiraAP — video LRO payload + poll

| field | value |
|-------|--------|
| **repo** | KiraAP |
| **file:line** | `agentPlatform.js:449-625` |
| **loại** | config |
| **tóm tắt** | Veo predictLongRunning + instance image/video ref + poll fetchPredictOperation |
| **OmniCast** | Có `video_gemini` API path; Flow UI path riêng |
| **khuyến nghị** | **GHÉP** instance.image/video bytes + sampleCount=1 chuẩn |

```javascript
// INIT
`https://us-central1-aiplatform.googleapis.com/v1/projects/${projectNumber}/locations/us-central1/publishers/google/models/${modelId}:predictLongRunning?key=${apiKey}`

const instance = { prompt };
// optional ref:
instance.image = { bytesBase64Encoded, mimeType };  // or
instance.video = { bytesBase64Encoded, mimeType };

const payload = {
  instances: [instance],
  parameters: {
    aspectRatio: aspectRatio || '16:9',
    durationSeconds: parseInt(durationSeconds || 6),
    sampleCount: 1
  }
};
// response: { name: operationName }

// POLL
`.../models/${modelId}:fetchPredictOperation?key=${apiKey}`
body: { operationName }
// done → response.videos | response.generatedVideos
//   bytesBase64Encoded | video.bytesBase64Encoded

// OMNI (alternate):
// POST https://aiplatform.googleapis.com/v1beta1/projects/${projectNumber}/locations/global/interactions
// headers: Authorization: Bearer ${apiKey}
// body: { model: 'gemini-omni-flash-preview', input: [{type:'text',text}, {type:'image'|'video', data, mime_type}] }
```

### 16. KiraAP skill — durationSeconds rules + TTS voices

| field | value |
|-------|--------|
| **repo** | KiraAP |
| **file:line** | `.agents/skills/agent-flatform-api/SKILL.md:29-47`, `279-341` |
| **loại** | config |
| **tóm tắt** | Duration set theo model; TTS PCM 24kHz + WAV header |
| **OmniCast** | TTS neural khác (Kokoro/Edge); video duration film_runner |
| **khuyến nghị** | **GHÉP** duration allowlist per model |

```
veo-3.1-lite-generate-001 & veo-3.0-generate-001: [4, 6, 8] giây
veo-2.0-generate-001: [5, 6, 7, 8] giây
// TTS voices: Alloy,Fable,Nova,Shimmer,Kore,Aoede (F) / Echo,Onyx,Puck,Charon,Fenrir (M)
// PCM sampleRate 24000, channels 1, bits 16 → 44-byte WAV header
// generationConfig temperature text example: 0.7, maxOutputTokens 4096
// timeouts khuyến cáo: 60–90s
// default projectNumber example in skill: '640527817992'
```

### 17. remotion — encode CRF defaults

| field | value |
|-------|--------|
| **repo** | remotion |
| **file:line** | `packages/renderer/src/crf.ts:8-45`, `codec.ts` DEFAULT_CODEC |
| **loại** | config |
| **tóm tắt** | CRF map theo codec; h264 default 18 |
| **OmniCast** | `remotion_render.py` chỉ `--codec=h264`, **không set crf** → nhận default 18 (ok) nhưng im lặng |
| **khuyến nghị** | **GHÉP** explicit `--crf=18` + document; tuỳ channel `--crf=15` master |

```typescript
const defaultCrfMap = {
  h264: 18, h265: 23, vp8: 9, vp9: 28, av1: 30,
  prores: null, gif: null,
  'h264-mkv': 18, 'h264-ts': 18,
  aac: null, mp3: null, wav: null,
};
// ranges h264: [1,51]
export const DEFAULT_CODEC: Codec = 'h264';
```

### 18. remotion — spring numbers dùng thật (brand package)

| field | value |
|-------|--------|
| **repo** | remotion |
| **file:line** | `packages/brand/src/video-elements/UpperThird.tsx:25-40`, `ExplodingLogo.tsx:26-61`, `Showcase/index.tsx:9-26` |
| **loại** | config |
| **tóm tắt** | damping 200 = “smooth no bounce”; mass biến thiên; out spring 20f trước hết duration |
| **OmniCast** | Intro/Stat/Outro đều `damping: 200` — **đã đúng** brand Remotion |
| **khuyến nghị** | **BỎ QUA** đổi damping; **GHÉP** mass/out-exit pattern |

```typescript
// UpperThird entry
spring({ fps, frame: frame - delay, config: { mass: 0.5 } });
// UpperThird exit
spring({ fps, frame: frame - durationInFrames + 20, config: { damping: 200 } });

// ExplodingLogo
implode: { mass: 1, damping: 200 }, durationInFrames: 12
spr:     { mass: 1.7 }, durationInFrames: 20
align:   { mass: 1.1, damping: 15 }, durationInFrames: 20  // bounce-y
oInner:  { mass: 1, damping: 200 }, durationInFrames: 5

// Showcase heavy
{ mass: 20, damping: 500 }
{ mass: 2,  damping: 500 }
```

### 19. remotion — TransitionSeries timing API

| field | value |
|-------|--------|
| **repo** | remotion |
| **file:line** | `packages/transitions/src/timings/spring-timing.ts`, `presentations/*` |
| **loại** | config |
| **tóm tắt** | springTiming + linearTiming; 18 presentation (fade, wipe, flip, …) |
| **OmniCast** | Không TransitionSeries; concat ffmpeg hard cut |
| **khuyến nghị** | **GHÉP** fade/wipe 12–20f giữa intro→body |

```typescript
export const springTiming = (options: {
  config?: Partial<SpringConfig>;
  durationInFrames?: number;
  durationRestThreshold?: number;
  reverse?: boolean;
} = {}): TransitionTiming => { /* measureSpring if no duration */ };

// presentations: book-flip, clock-wipe, cross-zoom, crosswarp, dissolve,
// dreamy-zoom, fade, film-burn, flip, iris, linear-blur, none, ripple,
// slide, swap, wipe, zoom-blur, zoom-in-out
```

### 20. OmniCast Remotion templates (baseline hiện có)

| field | value |
|-------|--------|
| **repo** | OmniCast |
| **file:line** | `remotion_studio/src/{IntroCard,StatPop,OutroCTA,Root}.tsx`, `remotion_render.py:22-67` |
| **loại** | config |
| **tóm tắt** | 3 comps; fps 30; 1920×1080; concurrency cpu/2; silent h264 |
| **OmniCast** | (chính nó) |
| **khuyến nghị** | baseline — so Tầng 2 gaps |

```typescript
// Root.tsx
FPS=30, W=1920, H=1080
IntroCard default duration FPS*4
StatPop  FPS*3
OutroCTA FPS*5
// springs: damping 200; Intro durationInFrames 24/26; Stat fps*1.1; Outro 22
// remotion_render.py:
// --codec=h264 --log=error --concurrency=max(1, cpu_count//2)
// NO --crf, NO audio, NO pixelFormat
```

### 21. VideoToolsPro — limitation

| field | value |
|-------|--------|
| **repo** | VideoToolsPro |
| **file:line** | root listing |
| **loại** | config |
| **tóm tắt** | Chỉ binary + `_rt/` runtime; **không harvest được** ffmpeg filter chain/preset/source |
| **OmniCast** | N/A |
| **khuyến nghị** | **BỎ QUA** snapshot này; nếu cần reverse: dynamic analysis binary (ngoài scope) |

```
VideoToolsPro/
  VideoToolsPro.exe
  ffmpeg.exe, ffplay.exe, ffprobe.exe
  install_fonts.bat
  models/torch_cache/...
  _rt/   # huge site-packages (ctranslate2, etc.) — not app source
```

### 22. OmniCast flow_browser — selectors + FLF (đối chứng)

| field | value |
|-------|--------|
| **repo** | OmniCast |
| **file:line** | `flow_browser.py:34-40`, `1566-1658`, `1889-1920` |
| **loại** | config |
| **tóm tắt** | UI vi-locale; FLF localStorage; convert() bỏ image_path |
| **OmniCast** | (chính nó) |
| **khuyến nghị** | điểm yếu so tobyflow API |

```python
_PROMPT_SEL = '[contenteditable="true"]'
_GENERATE_SEL = 'button:has-text("arrow_forward")'
_RESULT_IMG_SEL = 'img[alt="Hình ảnh được tạo"]'
_FLOW_HOME = "https://labs.google/fx/vi/tools/flow"
_NEW_PROJECT_SEL = 'button:has-text("Dự án mới")'
# FLF: imageOrVideoMode="VIDEO", selectedVideoModelFamily="abra",
#      selectedVideoDuration=seconds, slots "Bắt đầu"/"Kết thúc"
# convert(): image_path currently ignored
# FLOW_VEO_COST default 20
# max ingredients ~3
```

---

## Cơ chế OmniCast thiếu hoặc yếu hơn

| cơ chế | repo nguồn (file:dòng) | hiện trạng OmniCast (file:dòng) | mức | việc phải làm |
|--------|------------------------|----------------------------------|-----|----------------|
| **Flow API mode (non-UI)** — upload UUID + generate + poll mediaId | tobyflow `FlowApiAdapter.js` + BridgeClient | Chỉ Playwright UI `flow_browser.py:1-18` | **CAO** | Port client: intercept cookie/token từ profile Playwright → POST theo `api_endpoints` map; mirror genTypes |
| **Start/end frame qua API** (`start_end_frame_2_video` + 2 refUuids) | tobyflow `_computeVideoGenType` | UI picker slots `gen_video_flf` 1642–1658 | **CAO** | Upload 2 still → API; giữ UI fallback |
| **Remote DOM/API config** (SSE refresh selectors, cache 4h/grace 24h) | `ProviderConfigManager.js` | Hardcode selector 2026-05 | **CAO** | JSON selector vault + hot reload khi Google đổi DOM |
| **Token readiness gate** (tokenReady ∧ flowTabOpen) | BridgeClient + FlowBridgeStatusDot | Profile dir “đăng nhập rồi” mù | **CAO** | Healthcheck session: cookie age + reload project |
| **Concurrent queue + rate limit** (max 4, poll 10s, video TO 420s) | FlowApiAdapter `_maxConcurrent`, `_pollVideoById` | Single-thread executor + xlock cross-process | **TRUNG** | Cho phép N job API song song khi rời UI; giữ xlock cho DOM mode |
| **Exponential backoff + humanize** | content.js backoff/humanized | Abort on block; jitter rời rạc | **TRUNG** | Backoff 30→300s; delay 5–15s batch |
| **Captcha pause/resume overlay** | content.js captcha overlay | FlowBlocked stop — không resume path | **TRUNG** | Pause queue, notify operator, resume |
| **Video edit / upscale API** | FlowApiAdapter upscale + video_edit frames | Không | **THẤP** | Sau API mode ổn định |
| **Last-frame extract re-upload** (continuity) | FlowApiAdapter after video done | film_runner/continuity riêng | **TRUNG** | Extract last frame → uploadRef → next clip ref |
| **I2V convert uses image** | KiraAP instance.image bytes | `convert()` ignores image_path `flow_browser.py:1901-1902` | **CAO** | Wire first-frame API/UI |
| **Veo duration allowlist** | KiraAP skill [4,6,8]/[5–8] | seconds arbitrary FLF | **TRUNG** | Validate duration per model |
| **Cascade prompt selectors + wake** | h2dev content.js | single selector | **TRUNG** | Port cascade |
| **Remotion TransitionSeries** | remotion transitions package | hard-cut ffmpeg only | **TRUNG** | Comp bridge intro→stat fade 12–20f |
| **Remotion audio/subtitle comps** | remotion Audio + templates ecosystem | silent render; subtitle module riêng | **TRUNG** | SubtitleComp + optional Audio viz |
| **Explicit CRF / audioBitrate** | remotion crf.ts defaults | codec only | **THẤP** | Pass --crf=18 |
| **VideoToolsPro presets** | N/A (binary) | N/A | **THẤP** | Bỏ qua snapshot |

### Lộ trình nâng cấp Flow (từng bước)

1. **Instrument** profile Playwright: log network requests trên `labs.google` khi gen 1 image + 1 FLF video (DevTools HAR). Đối chiếu field names với `FlowApiAdapter` input (projectId, mediaId, ratioEnum, videoModelKey).
2. **Extract session**: cookie / `Authorization` / sapisidhash / recaptcha token từ context Playwright đã login (cùng profile `flow_login.py`).
3. **Implement `FlowApiClient`** (Python) mirror bridge commands: create_project → upload_ref → generate → poll_video; config enums hardcoded tạm từ mục 6–7; rate limits 10s/420s.
4. **FLF path**: `convert_flf` ưu tiên API `start_end_frame_2_video`; DOM fallback nếu API fail.
5. **I2V path**: `convert(image_path=…)` → `frame_2_video` / `reference_frame_2_video` (hết “image ignored”).
6. **Resilience**: backoff, captcha pause, concurrency semaphore, last-frame re-upload.
7. **Giữ UI mode** cho account free / captcha / khi API map gãy (tobyflow cũng dual-mode `web|api|auto`).
8. **Remote config** (tuỳ chọn): file vault `flow_api_map.json` cập nhật khi Google đổi model keys — đừng hardcode vĩnh viễn.

### Remotion vs OmniCast patterns

| pattern Remotion | OmniCast | gap |
|------------------|----------|-----|
| TransitionSeries + fade/wipe/springTiming | ffmpeg concat hard cut | port fade 12–20f giữa bumper |
| UpperThird / lower-third brand | không | lower-third kinetic cho documentary |
| Audio viz / waveform comps | không | optional music reactive bars |
| Subtitle composition (captions timed) | `media/subtitle.py` burn ffmpeg | Remotion caption comp cho kinetic text |
| Series multi-scene single render | 1 comp / scene → concat | optional full-timeline render |
| spring mass/bounce variants | only damping 200 | ok cho premium doc; thêm bounce cho social |
| audio in render | silent mp4 | ok (narration mix ngoài) |

---

## TOP-15 PATCH

1. **FlowApiClient skeleton** — mirror `flow_generate`/`flow_upload_ref`/`flow_poll_video` payloads; file: `implementation/src/omnicast/media/providers/flow_api.py` (mới) + wire từ `flow_browser.py` dual-mode.  
2. **FLF API path** — 2× upload_ref + `start_end_frame_2_video`; file: `flow_browser.py` `gen_video_flf` / `convert_flf`.  
3. **Wire image→video** — `convert()` dùng `image_path` (frame_2_video); file: `flow_browser.py:1889-1907`.  
4. **Session healthcheck** — cookie/token age + project URL alive trước batch; file: `flow_browser.py` `_ensure_page`.  
5. **Selector cascade + wake** — port h2dev selectors; file: `flow_browser.py` `_PROMPT_SEL` / `_type_prompt`.  
6. **Backoff + delay batch** — 30s×2^n / 5–15s jitter; file: `flow_browser.py` + env settings.  
7. **Captcha/quota categories** — map toast text → pause vs model-switch; file: `FlowBlocked` handlers.  
8. **Last-frame reupload** — sau mỗi clip API, extract frame → ref next; file: film_runner / continuity.  
9. **Duration allowlist** — [4,6,8] Veo-class; file: film_runner + flow provider.  
10. **Remote/local flow_api_map.json** — enums model/ratio/endpoint; file: `config/` + loader.  
11. **Remotion TransitionSeries fade** — intro/outro soft join; file: `remotion_studio` + `remotion_render.py`.  
12. **Explicit `--crf=18`** (+ optional audio later); file: `remotion_render.py:60-67`.  
13. **SubtitleComp kinetic** — port caption spring; file: `remotion_studio/src/SubtitleComp.tsx`.  
14. **LowerThird template** — UpperThird pattern mass 0.5 / exit damping 200; file: `remotion_studio/src/LowerThird.tsx`.  
15. **KiraAP-style LRO client polish** — nếu dùng Vertex Veo song song Flow: instance.image + sampleCount=1 + poll; file: `media/providers/video_gemini.py`.

---

## Ghi chú phương pháp

- **tobyflow bridge** (`heieobedadlfdkppgagnhfakcdapbfka`) **không có source trong snapshot** — URL HTTP Google thật + header chính xác nằm trong extension bridge / server `api_endpoints`. Harvest ở đây là **schema adapter + command names + field names** (đủ để reverse bằng HAR từ session login).
- **h2dev_flow** thuần UI; giá trị chính: selector cascade, poll/settle, anti-bot delay.
- **VideoToolsPro** không extract được preset — báo cáo trung thực, không bịa filter chain.
- **KiraAP** = Vertex/Agent Flatform public API (khác Google Flow consumer UI); dùng cho path metered, không thay Flow credit path.
- Không sửa `_refs/` hay code production trong task này.
)
