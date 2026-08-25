# REFS_SB_07 — hyperframes (HeyGen)

> **Repos:** `_refs/hyperframes` (~ monorepo TS: core / engine / producer / cli / player / studio / skills / registry)  
> **Định vị:** Framework **HTML → video deterministic**, **agent-first** (skills + CLI non-interactive). Không phải pipeline gen ảnh/nhân vật AI.  
> **Góc OmniCast:** **contract storyboard ↔ renderer** khi cả hai do agent điều khiển; EDL re-render (WS4); nối storyboard (WS1); overlay HTML/Remotion.  
> **License:** **Apache-2.0** (`_refs/hyperframes/LICENSE`) — học pattern **và** được phép dùng làm dependency npm.  
> **Ngày nghiên cứu:** 2026-08-02  
> **Phương pháp:** đọc code/docs/skills thật trong `_refs/`; không suy từ marketing README.

---

## 0. Tóm tắt điều hành (cho OmniCast)

| Trục | Hyperframes | OmniCast hiện tại | Hành động gợi ý |
|------|-------------|-------------------|-----------------|
| **Source of truth** | HTML + `data-*` + GSAP `window.__timelines` (file text, git-able) | Pydantic storyboard + `render_real_video.py` + ASS/HTML overlay rời | Học **artifact pipeline có tên file** + contract declarative cho EDL/overlay |
| **Storyboard** | `STORYBOARD.md` creative brief (beat/mood/technique) — **không** cast/ref | Cast registry + RefRole + continuity fail-closed | **Không** thay cast; bổ sung **render brief** song song (overlay/caption/transition) |
| **Consistency nhân vật** | N/A (không gen face/scene AI) | Cast + ref sheet + binding | N/A |
| **Re-render từng phần** | Beat = file HTML độc lập; edit `STORYBOARD.md` → rebuild 1 beat; distributed `renderChunk` theo frame range | Re-render full video; storyboard chưa nối render path | Port pattern **beat-as-unit** + **relative timing** + optional PSNR checkpoint |
| **Caption/motion** | 15 caption components + karaoke/kill-guarantee + registry effects | ASS/subtitle_sync + kinetic overlay + Remotion (partial) | Học caption exit hard-kill, tone table, registry-style presets |
| **QA video** | `lint` → `validate` (runtime Chrome + WCAG) → `inspect` (layout) → `snapshot` → **PSNR golden trong Docker** | `qa_check`, visual_match_qc Gemini, freezedetect | Học **lint static + headless runtime gate** trước full render; golden PSNR nếu có template cố định |
| **License** | Apache-2.0 | — | **OK dependency** (`hyperframes`, `@hyperframes/*`) hoặc chỉ học pattern |

**Câu trả lời ngắn cho brief:**

1. **API cho agent** = declarative structure (HTML attributes) + imperative motion (GSAP/script) + skills encode “viết đúng” + CLI gates (`lint`/`validate`).
2. **Frame/scene/timeline** = composition nested, clip `data-start`/`data-duration`/`data-track-index`, relative timing `id + N`, seek `t = frame/fps`.
3. **Overlay primitives** = caption registry + fitText + marker effects + transitions shader/CSS — đáng bổ sung cho OmniCast overlay path.
4. **Test video** = visual regression PSNR + audio correlation + Docker-locked Chrome/FFmpeg.
5. **Tái dùng** = Apache-2.0 → dependency OK; OmniCast Python stack có thể gọi CLI render cho lane motion-graphics / title / caption, không bắt buộc rewrite.

**Lưu ý quan trọng:** Root `DESIGN.md` của hyperframes là **brand design system cho docs Mintlify** (màu/typography site), **không** phải “thiết kế API agent”. Triết lý agent-first nằm ở `AGENTS.md`, `CLAUDE.md`, `skills/hyperframes/SKILL.md`, `docs/guides/prompting.mdx`, `docs/guides/pipeline.mdx`.

---

## 1. Tổng quan kiến trúc

### 1.1 Module map

```
_refs/hyperframes/
├── packages/
│   ├── cli/                 # hyperframes CLI: init, lint, validate, inspect, snapshot,
│   │                        # preview, render, tts, transcribe, add, capture, doctor
│   ├── core/                # types, HTML parsers, generators, linter, runtime,
│   │                        # frame adapters (GSAP/Anime/CSS/Lottie/Three/WAAPI)
│   ├── engine/              # Seekable page-to-video capture (Puppeteer/Chrome + FFmpeg)
│   ├── producer/            # Full pipeline: compile HTML → capture frames → encode →
│   │                        # audio mix; distributed plan/renderChunk/assemble;
│   │                        # regression-harness (PSNR golden)
│   ├── player/              # <hyperframes-player> web component (preview)
│   ├── studio/              # Browser editor (timeline edits → write back data-*)
│   ├── shader-transitions/  # WebGL scene transitions
│   ├── aws-lambda/          # Deploy render cloud
│   └── gcp-cloud-run/
├── registry/
│   ├── blocks/              # 50+ scene/block templates
│   └── components/          # Caption styles, grain, vignette, morph-text, …
├── skills/                  # Agent skills (vercel-labs/skills format)
│   ├── hyperframes/         # Authoring + QA checklist
│   ├── hyperframes-cli/
│   ├── hyperframes-media/   # tts, transcribe, remove-background
│   ├── hyperframes-registry/
│   ├── website-to-hyperframes/  # 7-step pipeline
│   └── gsap/, animejs/, three/, lottie/, …
└── docs/                    # Mintlify concepts + guides
```

Nguồn: `AGENTS.md:46-61`, `CLAUDE.md:5-13`, `README.md:32-60`.

### 1.2 Luồng dữ liệu end-to-end

Hyperframes **không** có pipeline “script AI drama → gen face → i2v”. Luồng production-agent chuẩn (pipeline 7 bước) là:

```
(source: URL | PDF | brief | blank)
  → capture/              # screenshots, tokens, assets
  → DESIGN.md / frame.md  # brand atoms
  → SCRIPT.md             # narration / on-screen copy
  → STORYBOARD.md         # beat creative plan
  → narration.wav + transcript.json   # TTS + word timestamps
  → compositions/*.html + index.html  # seekable HTML compositions
  → lint / validate / inspect / snapshot
  → hyperframes render → MP4
```

Nguồn: `docs/guides/pipeline.mdx:10-22`, `docs/guides/pipeline.mdx:28-53`.

**Render runtime (deterministic):**

```
Frame clock: t = floor(frame) / fps
  → adapter.seekFrame(frame)   # pause GSAP, seek totalTime
  → Chrome HeadlessExperimental.beginFrame  # pixel buffer
  → FFmpeg encode + audio mix
  → MP4
```

Nguồn: `docs/concepts/determinism.mdx:12-25`, `docs/concepts/frame-adapters.mdx:20-40`.

### 1.3 Hai lớp composition (declarative vs imperative)

| Lớp | Nội dung | Ai sở hữu |
|-----|----------|-----------|
| **HTML primitives** | `<video>` / `<img>` / `<audio>` / nested composition; `data-start`, `data-duration`, `data-track-index` | Framework (lifecycle mount/unmount, media play/seek) |
| **Script** | GSAP tweens, canvas, SVG, shader, dynamic DOM | Author/agent — **không** được play/pause media hay show/hide clip theo time |

Nguồn: `docs/concepts/compositions.mdx:117-126`, `docs/reference/html-schema.mdx:17-31`.

---

## 2. Data model storyboard

### 2.1 Hyperframes “storyboard” ≠ OmniCast StoryboardRecord

| Khái niệm | Hyperframes | OmniCast (`storyboard/models.py`) |
|-----------|-------------|-----------------------------------|
| Unit | **Beat** (shot marketing / motion) | **Shot** + **Entity** cast |
| Identity | Brand palette, assets path | Character/location/prop/costume + RefRole |
| Persistence | Markdown files + HTML | Pydantic frozen schemas + vault/store |
| Output | Animated HTML frame | Image/video gen prompts + binding |

Hyperframes **không** có class `Scene`/`Shot`/`Character` Pydantic. Model runtime chính là **HTML composition + typed timeline elements** trong core.

### 2.2 Timeline element types (core TypeScript) — verbatim

Từ `packages/core/src/core.types.ts:206-262`:

```typescript
export interface TimelineElementBase {
  id: string;
  type: TimelineElementType;
  name: string;
  startTime: number;
  duration: number;
  zIndex: number;
  x?: number;
  y?: number;
  scale?: number;
  opacity?: number;
}

export interface TimelineMediaElement extends TimelineElementBase {
  type: MediaElementType;
  src: string;
  mediaStartTime?: number;
  sourceDuration?: number;
  isAroll?: boolean;
  sourceWidth?: number;
  sourceHeight?: number;
  volume?: number;
  hasAudio?: boolean;
}

export interface TimelineTextElement extends TimelineElementBase {
  type: "text";
  content: string;
  color?: string;
  fontSize?: number;
  textShadow?: boolean;
  fontFamily?: string;
  fontWeight?: number;
  textOutline?: boolean;
  // ... highlight fields
}

export interface TimelineCompositionElement extends TimelineElementBase {
  type: "composition";
  src: string;
  compositionId: string;
  scale?: number;
  sourceDuration?: number;
  variableValues?: Record<string, string | number | boolean>;
  sourceWidth?: number;
  sourceHeight?: number;
}
```

### 2.3 Composition variables (parametrized render)

Khai báo typed variables trên `<html data-composition-variables='[...]' >`, override:

- per-instance: `data-variable-values`
- CLI: `hyperframes render --variables '{...}'` / `--variables-file`
- CI: `--strict-variables`

Types: `string | number | color | boolean | enum` — `packages/core/src/core.types.ts:265-325`, `skills/hyperframes/SKILL.md:194-261`.

**Ý nghĩa cho OmniCast:** đây là contract **template + data bag** (title, brand color, caption text) — giống channel config inject vào Remotion/HTML overlay, không phải cast binding.

### 2.4 STORYBOARD.md schema (artifact, agent-facing)

Không JSON Schema cứng; skill enforce fields. Mỗi beat tối thiểu:

| Field | Ý nghĩa |
|-------|---------|
| Timing | `0.0s–5.8s` từ transcript |
| Narration line | Exact VO words |
| Mood & camera | Feel + shot type |
| Assets | Paths thật từ capture |
| Techniques | 2–4 technique IDs |
| Transitions | CSS vs shader + params |
| SFX | File + time + volume |
| Animation sequence | Events span full beat duration |
| Text effect IDs | Named effects, không “fades in” |

Nguồn: `docs/guides/pipeline.mdx:110-124`, `skills/website-to-hyperframes/references/step-3-storyboard.md:235-381`.

### 2.5 State machine (pipeline gates)

```
capture ──gate──► DESIGN.md
       ──gate──► SCRIPT.md
       ──gate──► STORYBOARD.md (+ user approve, trừ autonomous)
       ──gate──► narration + transcript (update beat timings)
       ──gate──► compositions/*.html (per-beat self-review)
       ──gate──► lint + validate + snapshots = 0 errors
       ──optional──► render MP4
```

Mỗi artifact = **checkpoint re-entry**: sửa storyboard 1 beat → rebuild 1 HTML, không regenerate cả project.

Nguồn: `docs/guides/pipeline.mdx:183-192`, `skills/website-to-hyperframes/SKILL.md:17-101`.

### 2.6 HTML clip contract (SSOT render)

| Attribute | Required | Semantics |
|-----------|----------|-----------|
| `id` | Yes | Unique; relative timing target |
| `class="clip"` | Visible non-video | Runtime visibility |
| `data-start` | Yes | Absolute seconds **or** `"otherId + 2"` |
| `data-duration` | img/div required; media optional | Seconds |
| `data-track-index` | Yes | Track row; same-track no overlap |
| `data-media-start` | Optional | Trim source |
| `data-volume` | Optional | 0–1 |
| `data-composition-id` | Composition root | Timeline key |
| `data-composition-src` | Nested | External HTML file |
| `data-width` / `data-height` | Composition | Viewport |

Nguồn: `docs/reference/html-schema.mdx:48-63`, `docs/concepts/data-attributes.mdx:8-34`.

**Relative timing** (critical for EDL-style re-time):

```html
<video id="intro" data-start="0" data-duration="10" ...></video>
<video id="main" data-start="intro + 2" data-duration="20" ...></video>
```

Đổi duration `intro` → downstream shift tự động. Constraints: same composition only, no cycles, known duration on referent — `docs/concepts/data-attributes.mdx:46-88`.

---

## 3. Cơ chế consistency nhân vật/bối cảnh/props

**N/A cho hyperframes.**

Framework này **không** sinh ảnh nhân vật, không reference sheet, không IP-Adapter/LoRA, không seed diffusion, không re-roll face.

“Consistency” trong hyperframes = **determinism render**:

| Rule | Mục đích |
|------|----------|
| No `Date.now()` / unseeded `Math.random()` | Same input → same pixels |
| No render-time network fetch | Assets preloaded |
| Seek-driven, not wall-clock | GSAP paused + `totalTime(frame/fps)` |
| Docker Chrome + fonts + FFmpeg | Cross-host pixel parity |
| `window.__timelines` registered, paused | Engine can seek |

Nguồn: `docs/concepts/determinism.mdx:40-47`, `AGENTS.md:70`, `skills/hyperframes/SKILL.md:295-305`.

**Brand consistency** (không phải face):

- `frame.md` / `design.md` / `DESIGN.md` — palette, fonts, don'ts
- Design adherence checklist sau authoring (`SKILL.md:424-440`)
- Prompt expansion cites **exact hex**, không invent color (`references/prompt-expansion.md:9-12`)

---

## 4. PROMPT ENGINEERING — VERBATIM

Hyperframes **không** có LLM system-prompt Python kiểu Writer/Critic. “Prompt system” = **agent skills** (markdown inject vào Claude/Cursor) + user prompt guide. Dưới đây chép **nguyên văn** các block quan trọng.

### 4.1 Skill approach + hard gate (composition authoring)

Từ `skills/hyperframes/SKILL.md:10-62`:

```markdown
## Approach

### Discovery (exploratory requests only)
...
### Step 1: Design system
If a design spec exists in the project, read it first. Look in precedence order:
`frame.md` → `design.md` → `DESIGN.md` ...
...
### Step 2: Prompt expansion
Always run on every composition (except single-scene pieces and trivial edits).
...
### Step 3: Plan
Before writing HTML, think at a high level:
1. **What** — what should the viewer experience? ...
2. **Structure** — how many compositions, which are sub-compositions vs inline, what tracks ...
3. **Rhythm** — declare your scene rhythm before implementing. ...
4. **Timing** — which clips drive the duration ...
5. **Layout** — build the end-state first. ...
6. **Animate** — then add motion ...

**Build what was asked.** A request for "a title card" is not a request for
"a title card + 3 supporting scenes + ambient music + captions." ...

<HARD-GATE>
Before writing ANY composition HTML — verify you have a visual identity from Step 1.
If you're reaching for `#333`, `#3b82f6`, or `Roboto`, you skipped it.
</HARD-GATE>
```

**Vì sao hiệu quả:** ép agent **tách design → expansion → plan → layout static → animate**, tránh nhảy thẳng vào CSS random. HARD-GATE chặn palette “AI default”.

### 4.2 Layout-before-animation process

Từ `skills/hyperframes/SKILL.md:64-75`:

```markdown
## Layout Before Animation

Position every element where it should be at its **most visible moment** — the
frame where it's fully entered, correctly placed, and not yet exiting. Write
this as static HTML+CSS first. No GSAP yet.

**Why this matters:** If you position elements at their animated start state
(offscreen, scaled to 0, opacity 0) and tween them to where you think they
should land, you're guessing the final layout. Overlaps are invisible until
the video renders. By building the end state first, you can see and fix layout
problems before adding any motion.
```

**Vì sao hiệu quả:** layout bugs lộ sớm; animation chỉ mô tả **journey** tới CSS ground truth (`from` / `fromTo`).

### 4.3 Timeline contract + never-do list

Từ `skills/hyperframes/SKILL.md:287-319`:

```markdown
## Timeline Contract
- All timelines start `{ paused: true }` — the player controls playback
- Register every timeline: `window.__timelines["<composition-id>"] = tl`
- Framework auto-nests sub-timelines — do NOT manually add them
- Duration comes from `data-duration`, not from GSAP timeline length
- Never create empty tweens to set duration

## Rules (Non-Negotiable)
**Deterministic:** No `Math.random()`, `Date.now()`, or time-based logic. ...
**GSAP:** Only animate visual properties (...). Do NOT animate `visibility`,
`display`, or call `video.play()`/`audio.play()`.
...
**Never do:**
1. Forget `window.__timelines` registration
2. Use video for audio — always muted video + separate `<audio>`
3. Nest video inside a timed div — use a non-timed wrapper
4. Use `data-layer` (use `data-track-index`) or `data-end` (use `data-duration`)
5. Animate video element dimensions — animate a wrapper div
6. Call play/pause/seek on media — framework owns playback
7. Create a top-level container without `data-composition-id`
8. Use `repeat: -1` on any timeline or tween — always finite repeats
9. Build timelines asynchronously (inside `async`, `setTimeout`, `Promise`)
10. Use `gsap.set()` on clip elements from later scenes — they don't exist in
    the DOM at page load. Use `tl.set(selector, vars, timePosition)` inside the
    timeline at or after the clip's `data-start` time instead.
11. Use `<br>` in content text — forced line breaks don't account for actual
    rendered font width. ...
```

**Vì sao hiệu quả:** list “Never do” map 1:1 với failure mode capture engine (seek, DOM presence, infinite loop, race async).

### 4.4 Scene transitions (non-negotiable)

Từ `skills/hyperframes/SKILL.md:321-348`:

```markdown
## Scene Transitions (Non-Negotiable)
1. **ALWAYS use transitions between scenes.** No jump cuts. No exceptions.
2. **ALWAYS use entrance animations on every scene.** ...
3. **NEVER use exit animations** except on the final scene. ... The transition
   IS the exit. The outgoing scene's content MUST be fully visible at the moment
   the transition starts.
4. **Final scene only:** The last scene may fade elements out ...
```

**Vì sao hiệu quả:** agents hay fade-out scene trước transition → frame trống. Rule 3 loại hẳn class bug đó.

### 4.5 Prompt expansion — output contract

Từ `skills/hyperframes/references/prompt-expansion.md:19-66`:

```markdown
## Why always run it
**The expansion is never pass-through.** Every user prompt — no matter how
detailed — is a _seed_. The expansion's job is to enrich it into a fully-realized
per-scene production spec that the scene subagents can build from directly.
...
## What to generate
1. **Title + style block** — cite the spec's exact hex values ...
2. **Rhythm declaration** — name the scene rhythm before detailing any scene.
3. **Global rules** — parallax layers, micro-motion requirements, transition style ...
4. **Per-scene beats** — concept, mood, depth layers, choreography verbs, transition out
5. **Recurring motifs**
6. **Negative prompt** — what to avoid ...

## Output
Write the expanded prompt to `.hyperframes/expanded-prompt.md` in the project
directory. Do NOT dump it into the chat — it will be hundreds of lines.
```

**Vì sao hiệu quả:** intermediate artifact shared giữa sub-agents; tránh “mỗi scene một palette”.

### 4.6 User-facing prompt shapes (docs)

Từ `docs/guides/prompting.mdx:46-77` (cold vs warm start):

```markdown
### Cold start — describe the video
> Using `/hyperframes`, create a 10-second product intro with a fade-in title
> over a dark background and subtle background music.

### Warm start — turn context into a video
> Take a look at this GitHub repo https://github.com/heygen-com/hyperframes and
> explain its uses and architecture to me using `/hyperframes`.
```

Vocabulary tables (motion → GSAP ease, caption tones, audio-reactive bands): `docs/guides/prompting.mdx:95-196`.

### 4.7 STORYBOARD concept block template

Từ `skills/website-to-hyperframes/references/step-3-storyboard.md:11-17`:

```markdown
**Message:** [the ONE thing this video must communicate — one sentence]
**Arc:** [Problem→Solution / Reveal / Demonstration / Vibe / Comparison — ...]
**Audience:** [who's watching, where they're watching — ...]
**Brand voice:** [confident / playful / clinical / urgent / premium — ...]
**Why this matters now:** [GTM context if relevant — ...]
```

### 4.8 Caption hard rules (verbatim excerpt)

Từ `skills/hyperframes/references/captions.md:94-117`:

```javascript
// Every group must have a hard kill after exit animation:
tl.to(groupEl, { opacity: 0, scale: 0.95, duration: 0.12, ease: "power2.in" }, group.end - 0.12);
tl.set(groupEl, { opacity: 0, visibility: "hidden" }, group.end); // deterministic kill

// Self-lint before window.__timelines[id] = tl:
GROUPS.forEach(function (group, gi) {
  var el = document.getElementById("cg-" + gi);
  if (!el) return;
  tl.seek(group.end + 0.01);
  var computed = window.getComputedStyle(el);
  if (computed.opacity !== "0" && computed.visibility !== "hidden") {
    console.warn(
      "[caption-lint] group " + gi + " still visible at t=" + (group.end + 0.01).toFixed(2) + "s",
    );
  }
});
tl.seek(0);
```

**Vì sao hiệu quả:** caption ghosting là bug kinh điển agent; hard `tl.set` + self-lint seekable.

### 4.9 Frame adapter contract (host API)

Từ `docs/concepts/frame-adapters.mdx:45-60`:

```typescript
type FrameAdapterContext = {
  compositionId: string;
  fps: number;
  width: number;
  height: number;
  rootElement?: HTMLElement;
};

type FrameAdapter = {
  id: string;
  init?: (ctx: FrameAdapterContext) => Promise<void> | void;
  getDurationFrames: () => number;
  seekFrame: (frame: number) => Promise<void> | void;
  destroy?: () => Promise<void> | void;
};
```

### 4.10 Agent anti-patterns (user prompts)

Từ `docs/guides/prompting.mdx:244-252`:

```markdown
- **Don't ask for React / Vue components.** Hyperframes compositions are plain HTML ...
- **Don't ask for 4K or 60fps unless you need it.** ...
- **Don't skip the slash command.** Without `/hyperframes`, the agent may guess ...
- **Don't paste long error logs into the prompt without context.** Run
  `npx hyperframes lint` and `npx hyperframes validate` first ...
- **Don't assume the agent knows your assets.** Mention file paths explicitly ...
```

---

## 5. Vòng QA / retry / repair

### 5.1 Multi-layer gates (agent loop)

| Layer | Command | Detects | Khi nào |
|-------|---------|---------|---------|
| Static structure | `hyperframes lint` | Missing attrs, timeline registration, tween conflicts | Immediate, blocking |
| Runtime Chrome | `hyperframes validate` | JS errors, missing assets, **WCAG contrast** sampling | Immediate |
| Layout geometry | `hyperframes inspect` | Overflow, off-canvas text, bbox + fix hints | After lint/validate |
| Visual frames | `hyperframes snapshot --at t1,t2` | Eyeball mid-beat PNGs | Before deliver |
| Animation map | `animation-map.mjs` | Dead zones, collisions, stagger, pace flags | New compositions |
| Design adherence | Manual checklist vs design.md | Invented colors/fonts | After author |
| Pixel regression | Producer harness PSNR | Golden MP4 drift | CI |

Nguồn: `skills/hyperframes/SKILL.md:376-463`, `docs/guides/pipeline.mdx:161-181`.

### 5.2 Caption / contrast repair

- Contrast fail → brighten/darken **within palette family**, re-run validate (`SKILL.md:406-422`).
- Caption ghost → hard kill at `group.end` (`captions.md:94-117`).
- Overflow → `fitTextFontSize` or mark `data-layout-allow-overflow` (`SKILL.md:391-402`).

### 5.3 Budget / abandon

- Không có “retry budget N times” kiểu Orkas image re-roll.
- Pattern = **fail gate → fix source → re-gate**.
- Autonomous mode website-to-hyperframes: **không skip quality gates** (asset audit, DoD, honest disclosure) — chỉ skip user preference questions (`skills/website-to-hyperframes/SKILL.md:19-26`).

### 5.4 Preview vs producer parity harness

`packages/producer/src/parity-harness.ts` — so sánh frame preview URL vs producer URL tại checkpoints, generate `diff.png` (ffmpeg blend difference). Dùng bắt regression border-radius / capture path.

---

## 6. Tích hợp video-gen

**Hầu hết N/A.**

| Capability | Hyperframes | Ghi chú |
|------------|-------------|---------|
| t2v / i2v / ref-to-video | Không | Embed `<video src>` đã có sẵn |
| First/last frame gen | Không | |
| Provider fallback AI video | Không | |
| TTS | Có: Kokoro / ElevenLabs / HeyGen via CLI media skill | Local Kokoro no key |
| Transcribe | Whisper-style CLI (`transcribe`) | Word timestamps |
| Remove background | CLI media skill | Transparent overlays |
| Distributed render | `plan` → `renderChunk` → `assemble` | Frame chunks, not AI shots |
| Cloud | AWS Lambda, GCP Cloud Run packages | |

TTS voices table (docs): product demo `af_heart`/`af_nova` — `docs/guides/prompting.mdx:198-212`.

**Liên hệ OmniCast:** hyperframes là **compositor/renderer**, không thay `veo_pipeline` / Flow. Hữu ích cho lane **motion graphics, title cards, kinetic captions, data viz** trên footage/AI clip đã có.

---

## 7. Pacing / timing

### 7.1 Ai quyết định duration

1. **Narration-first (pipeline đầy đủ):** TTS → `transcript.json` `[{text,start,end}]` → cập nhật beat boundaries trong STORYBOARD → `data-start`/`data-duration` trên compositions (`pipeline.mdx:129-147`).
2. **Manual / music-driven:** beat timings trong storyboard; script là on-screen copy.
3. **Relative chain:** clip B starts when A ends (+ offset) — auto reflow.

### 7.2 Pacing templates (storyboard step)

Từ `step-3-storyboard.md:29-36`:

| Pacing | Beat count | Beat duration | Architecture |
|--------|------------|---------------|--------------|
| Fast | 8–15 | 0.7–1.8s | Single-file stacked, hard cuts |
| Moderate | 4–6 | 3–5s | Sub-comps, CSS crossfades |
| Slow | 3–4 | 5–8s | Sub-comps, long crossfades |
| Arc | 5–7 | varies | Slow opener → peak → resolve |

Script length heuristic: ~2.5 words/sec (`step-3-storyboard.md:531-532`).

### 7.3 Beat internal life

- Không hold > ~1.5–2s không motion (`step-3-storyboard.md:277`, `383-387`).
- VO start relative to first visual declared in Global Direction (`step-3-storyboard.md:326`).
- Video duration ≈ narration + short CTA hold — cấm dead silence dài (`step-3-storyboard.md:316`).

### 7.4 Track model

- Same `data-track-index` → clips **cannot overlap in time**.
- Visual z-order: Studio maps row order → inline `z-index` (`docs/guides/timeline-editing.mdx:87-94`). Skill note: track index **không** thay CSS z-index (`SKILL.md:147`).

---

## 8. Chi tiết nhỏ đáng học

1. **HTML is both render layer and edit layer** — Studio timeline writes back `data-*`; no separate project binary (`timeline-editing.mdx:6-28`). Round-trip agent ↔ human editor.
2. **Muted video + separate `<audio>`** — engine mixes audio; avoids Chrome video-audio seek hell (`SKILL.md:263-285`).
3. **Never animate width/height on `<video>`** — wrap and animate wrapper (`html-schema.mdx:89-91`).
4. **Finite repeats only** — `repeat: -1` breaks capture (`SKILL.md:303`).
5. **Docker for golden baselines** — host Chrome ≠ CI Chrome (`CLAUDE.md:48-66`, `Dockerfile.test:1-11`).
6. **PSNR checkpoints + audio correlation + residual RMS** — multi-signal regression (`regression-harness.ts:67-83`, `:542-579`).
7. **Distributed chunk seam tests** — animations crossing chunk boundaries (`producer/tests/README.md:139-175`).
8. **`fitTextFontSize` runtime helper** — dynamic caption sizing without overflow (`captions.md:75-86`).
9. **Prompt expansion file on disk** — `.hyperframes/expanded-prompt.md` not chat dump.
10. **Per-beat sub-agents** with fresh context + only their STORYBOARD section (`pipeline.mdx:155`).
11. **Vocabulary maps** natural language → GSAP ease / caption tone / shader energy (`prompting.mdx:95-158`).
12. **Honest disclosure** in delivery (“What I did NOT verify”) — website skill Step 6.
13. **Fps as rational** `{num, den}` for NTSC exact (`core.types.ts:7-49`).
14. **vs Remotion thesis:** HTML training data depth for agents; library clocks seekable; Remotion commercial license vs Apache (`docs/guides/hyperframes-vs-remotion.mdx:14-43`).

---

## 9. ĐỀ XUẤT CHO OMNICAST

| # | Phát hiện hyperframes | Gap OmniCast | File đích gợi ý | Impact (video quality) | Effort |
|---|----------------------|--------------|-----------------|------------------------|--------|
| 1 | **Artifact pipeline có tên** (DESIGN/SCRIPT/STORYBOARD/transcript/compositions) + re-entry per step | Storyboard Pydantic mạnh nhưng **chưa nối** `render_real_video` / thiếu “render brief” song song | `storyboard/pipeline.py`, `render_real_video.py`, docs WS1 | Cao — agent/human biết checkpoint nào rebuild | M |
| 2 | **Beat = independent composition file** → rebuild 1 scene không full re-encode | Full re-render; EDL re-render WS4 chưa có unit file | New: `render/edl.py` or scene segments dir; `animatic.py` pattern | Cao — iterate caption/grade rẻ | L |
| 3 | **Declarative timing contract** (`data-start`, relative `id+N`, tracks) | Timing rải rác trong MoviePy/FFmpeg filters | EDL schema JSON (start/dur/track/src) map từ Shot | Cao — re-time VO không đụng visual | M |
| 4 | **Layout-before-animation + lint/validate gates** cho agent-written overlay | Agent/Remotion overlay dễ overlap/ghost caption | Overlay HTML templates + static linter | Trung — ít “AI slop layout” | M |
| 5 | **Caption exit hard-kill + tone table + 15 presets** | ASS tốt nhưng kinetic/social caption còn mỏng | `subtitle_sync.py`, channel caption style presets, registry-like packs | Trung–Cao (CTR social) | M |
| 6 | **Seek-driven determinism rules** cho HTML overlay path | Overlay re-render có thể non-deterministic nếu random | Remotion/HTML overlay guidelines in agents docs | Trung | S |
| 7 | **PSNR golden + Docker lock** cho template cố định | QC semantic Gemini / freeze; thiếu pixel regression template | `tests/` golden for channel title cards / lower-thirds | Trung (regression) | L |
| 8 | **Prompt expansion intermediate** (rich brief before gen) | Writer/storyboard prompts dài nhưng chưa “expand → per-shot production spec” file | `storyboard/extract.py` or new `storyboard/expand.py` | Trung | M |
| 9 | **Variables inject** template without rewrite HTML | Channel brand inject exists; Remotion props partial | Channel → overlay variables JSON | Trung | S |
| 10 | **Optional dependency** `hyperframes` CLI for motion-graphics lane | Toàn FFmpeg+Python+Remotion partial | `media/` optional subprocess wrapper | Cao nếu ship data-viz/launch style | L (integration) |
| 11 | **Vocabulary NL → motion params** | VisualDirector free text | `visual_director` + channel style maps | Trung | S |
| 12 | **Sub-agent per beat** isolation | Storyboard chunk LLM already; render stages not | Pipeline YAML stages | Thấp–Trung | S |

### 9.1 Contract storyboard ↔ renderer đề xuất (rút từ hyperframes)

Khi **cả storyboard agent và render agent** do LLM điều khiển, hyperframes cho thấy contract nên là:

```
1. CREATIVE LAYER (editable, human-readable)
   STORYBOARD.md / StoryboardRecord (OmniCast) — WHO/WHAT/WHY, timing intent

2. TIMING LAYER (machine, from VO)
   transcript / words.json — absolute times SSOT

3. DECLARATIVE EDL / COMPOSITION LAYER (git-able, lintable)
   list of clips: {id, src|template, start, duration, track, variables}
   + relative refs optional
   NO free-form "play video in code" in agent prompts

4. IMPERATIVE LAYER (isolated, per unit)
   GSAP / FFmpeg filter / Remotion component — only motion/effect
   Framework owns media clock

5. GATES (machine, non-optional for agent)
   lint schema → runtime validate → snapshot/PSNR → deliver
```

**Declarative cái gì / imperative cái gì (checklist):**

| Declarative (agent khai báo) | Imperative (agent code / framework) |
|------------------------------|-------------------------------------|
| Clip list, start/duration/track | Seek loop, encode, audio mix |
| Composition variables (title, color) | Applying variables into DOM |
| Transition type + time | Shader GLSL / CSS implementation |
| Caption groups + word times | Tween code for karaoke |
| Brand tokens from design.md | Pixel paint |
| Determinism constraints as rules | Seeded PRNG if needed |

### 9.2 Agent API checklist (rút DESIGN philosophy từ AGENTS + skills)

> Lưu ý: root `DESIGN.md` = brand docs site only. Checklist dưới từ `AGENTS.md` + `SKILL.md` + `prompting.mdx`.

- [ ] **SSOT text files** agents can read/write (HTML/MD/JSON), not binary project.
- [ ] **Skills / slash commands** load framework rules before generation.
- [ ] **HARD-GATE** visual identity before first HTML/CSS.
- [ ] **Layout static first**, then animate `from` end-state.
- [ ] **Register seekable timelines**; paused; finite duration.
- [ ] **Never duplicate framework ownership** (media play/visibility).
- [ ] **lint + validate** before “done”; inspect/snapshot for visual.
- [ ] **Per-unit files** (beat/shot) for partial rebuild.
- [ ] **Named intermediate expansion** for multi-agent fan-out.
- [ ] **Determinism ban list** (random, wall clock, network at render).
- [ ] **Vocabulary tables** NL → technical params.
- [ ] **User iteration** = small targeted edits, not full re-spec.
- [ ] **Quality gates not skippable** in autonomous mode.
- [ ] **Variables + strict mode** for template pipelines / CI.

---

## 10. KHÔNG nên học + LICENSE

### 10.1 Anti-patterns / không port mù

| Anti-pattern | Lý do cho OmniCast |
|--------------|-------------------|
| Thay cast/RefRole bằng STORYBOARD.md prose | OmniCast drama/storytelling **cần** structured cast; hyperframes marketing motion |
| Rewrite toàn bộ renderer sang HTML/GSAP | FFmpeg path + Veo/Flow đã sunk cost; chỉ lane phụ |
| Copy skill markdown dài làm system prompt mù | Phải adapt vocabulary sang VO documentary / horror_real |
| Exit animations trước transition (agent hay làm) | Học rule hyperframes **để tránh**, không copy bug |
| Host golden PSNR without Docker | Drift Chrome/FFmpeg → false fail |
| Dùng contact-sheet screenshots làm B-roll | Hyperframes **cấm** — OmniCast stock khác nhưng vẫn tránh “grid labels in frame” |
| Infinite GSAP repeat | Breaks seek engines if ever used |

### 10.2 License + mức tái dùng

| Item | Value |
|------|-------|
| License | **Apache License 2.0** (`LICENSE` full text) |
| npm packages | `hyperframes` (CLI), `@hyperframes/core`, `engine`, `producer`, `player`, … |
| Dùng làm dependency? | **Có** — Apache-2.0 permissive, phù hợp commercial OmniCast |
| Chỉ học pattern? | Cũng OK nếu không muốn Node 22+ / Chrome headless trong stack Python |
| Remotion note | Hyperframes docs: Remotion **commercial license**; HF Apache — `hyperframes-vs-remotion.mdx:43` |

**Khuyến nghị thực tế OmniCast:**

- **Phase A (học pattern, effort S–M):** EDL schema, artifact gates, caption kill, relative timing — re-implement in Python/FFmpeg.
- **Phase B (optional dependency, effort L):** spawn `npx hyperframes render` cho channel style `motion_graphics` / launch teaser / chart-heavy; feed VO audio + brand variables.
- **Không:** fork monorepo vào OmniCast core; không sửa `_refs/`.

---

## Phụ lục A — Frame/scene/timeline abstraction (brief Q2)

### Composition model

```
index.html (root composition)
  ├── <audio> VO / BGM tracks
  ├── compositions/beat-1.html  (nested via data-composition-src)
  ├── compositions/beat-2.html
  ├── compositions/captions.html  (data-timeline-role="captions")
  └── GSAP master timeline + optional HyperShader transitions
```

- Nested comps: duration from GSAP / `data-duration` (docs slightly differ: html-schema says comps don't use data-duration; skill says data-duration takes precedence — **follow runtime + skill for agents**).
- Variables layer: defaults < host `data-variable-values` < CLI `--variables`.

### Diff / re-render từng phần

| Mức | Cơ chế hyperframes | Map OmniCast WS4 |
|-----|--------------------|------------------|
| Creative | Edit 1 beat section in STORYBOARD.md | Patch 1 Shot in board |
| Source | Rewrite `compositions/beat-N.html` only | Rewrite 1 scene segment filter graph |
| Preview | `preview` live reload | Studio / frame scrub |
| Encode full | `render` all frames | Current full render |
| Encode parallel | `renderChunk` by frame range (distributed) | Segment encode + concat |
| Visual QA | `snapshot --at mid-beat` | extract frame mid-shot |
| Regression | PSNR vs golden MP4 | Future golden for fixed templates |

**Không** có “HTML AST diff → only dirty frames” automatic cho agent edits; dirty unit = **file composition**. Engine vẫn seek toàn composition khi render file đó; distributed chunks theo **frame index**, không theo DOM diff.

Studio timeline: move/trim persist `data-start`/`data-duration`/`data-media-start`/`z-index` — limited (no front-trim for pure GSAP motion yet) — `timeline-editing.mdx:96-103`.

---

## Phụ lục B — Text overlay / caption / motion primitives (brief Q3)

### Registry components (install `hyperframes add`)

Caption styles (15): `caption-highlight`, `caption-pill-karaoke`, `caption-editorial-emphasis`, `caption-glitch-rgb`, `caption-kinetic-slam`, `caption-neon-glow`, `caption-neon-accent`, `caption-clip-wipe`, `caption-gradient-fill`, `caption-matrix-decode`, `caption-emoji-pop`, `caption-parallax-layers`, `caption-particle-burst`, `caption-texture`, `caption-weight-shift` — `captions.md:120-145`.

Effects: `grain-overlay`, `vignette`, `morph-text`, `motion-blur`, `parallax-zoom`/`unzoom`, `shimmer-sweep`, `texture-mask-text`, `grid-pixelate-wipe`.

### Primitives đáng bổ sung OmniCast

| Primitive | OmniCast hiện | Đề xuất |
|-----------|---------------|---------|
| Hard kill caption groups | ASS/line end partial | Explicit off at word end |
| Tone → typography/animation table | Channel ASS style | Extend per channel_style social/hype |
| `fitTextFontSize` | Fixed font sizes | Dynamic scale for kinetic stats |
| Marker highlight (circle/burst/scribble) | Limited | Optional HTML overlay effects |
| Per-word brand/number emphasis | Partial kinetic | Formalize in storyboard cells |
| Transparent caption comps | Burn-in ASS | Separate overlay pass |
| Shader transitions between AI clips | xfade limited set | Optional between shots |
| HTML-in-Canvas device mockups | N/A | Only if product-demo channels |

**Remotion vs HF:** OmniCast đã partial Remotion — HF docs argue HTML+GSAP easier for agents; nếu Remotion license/ops ổn, **học caption rules**, không bắt buộc migrate engine.

---

## Phụ lục C — Ecosystem testing / CI video (brief Q4)

### Producer regression fixture layout

```
tests/<fixture>/
  meta.json      # minPsnr, maxFrameFailures, minAudioCorrelation, renderConfig.fps
  src/index.html
  output/compiled.html
  output/output.mp4   # golden — MUST be generated inside Dockerfile.test
```

Harness: `packages/producer/src/regression-harness.ts`

- Extract frame at checkpoint → ffmpeg `psnr` filter → average dB (`:542-579`).
- Audio: RMS envelope correlation + lag windows; optional residual RMS dBFS.
- Modes: `in-process` (CLI path SSOT) | `distributed-simulated` | lambda-local.
- Absolute floor 10 dB for black-frame pathology; fixtures author own `minPsnr`.

CI practice:

- Same Chromium + fonts + FFmpeg as production (`Dockerfile.test`).
- Never commit host-generated goldens (`CLAUDE.md:64-66`).
- Unit tests: vitest across packages; oxlint/oxfmt; lefthook pre-commit.

Agent-level (not CI): lint/validate/inspect/snapshot per composition before deliver.

---

## Phụ lục D — So sánh nhanh OmniCast storyboard vs hyperframes beat

| Dimension | OmniCast Shot | Hyperframes Beat |
|-----------|---------------|------------------|
| Identity | Entity IDs + RefRole + ref sheets | Brand asset paths |
| Camera | Enum CameraShot/Angle/Movement + gloss | Prose shot type + camera verb |
| Prompt | Fail-closed binding clauses | GSAP choreography verbs |
| Continuity | `continuity.py` gates | Determinism + design.md |
| Visual type | stock / generated / chart / veo | HTML/CSS/WebGL always |
| Duration source | duration_s clamp / TTS scene | transcript word times |
| Repair | Re-gen image / re-bind | Edit HTML / re-lint |

**Kết luận map:** học hyperframes cho **render contract & agent QA**, **không** thay WS1 cast consistency.

---

## Đã đọc

- `docs/research/_briefs/COMMON_CONTEXT.md`, `_briefs/07_hyperframes.md`
- `_refs/hyperframes/LICENSE`, `package.json`, `README.md` (partial)
- `_refs/hyperframes/DESIGN.md` (brand site — not agent API)
- `_refs/hyperframes/AGENTS.md`, `CLAUDE.md`
- `_refs/hyperframes/docs/concepts/compositions.mdx`, `data-attributes.mdx`, `determinism.mdx`, `frame-adapters.mdx`
- `_refs/hyperframes/docs/reference/html-schema.mdx`
- `_refs/hyperframes/docs/schema/hyperframes.json`
- `_refs/hyperframes/docs/guides/prompting.mdx`, `pipeline.mdx`, `timeline-editing.mdx`, `hyperframes-vs-remotion.mdx`
- `_refs/hyperframes/skills/hyperframes/SKILL.md`
- `_refs/hyperframes/skills/hyperframes/references/prompt-expansion.md`, `captions.md`, `beat-direction.md` (partial)
- `_refs/hyperframes/skills/website-to-hyperframes/SKILL.md`
- `_refs/hyperframes/skills/website-to-hyperframes/references/step-3-storyboard.md` (large)
- `_refs/hyperframes/packages/core/src/core.types.ts` (Fps + Timeline types)
- `_refs/hyperframes/packages/producer/tests/README.md`
- `_refs/hyperframes/packages/producer/src/regression-harness.ts` (types + PSNR)
- `_refs/hyperframes/packages/producer/src/parity-harness.ts` (grep/partial)
- `_refs/hyperframes/Dockerfile.test` (header)
- `implementation/src/omnicast/storyboard/models.py` (header enums for gap map)
- `IMPLEMENTATION_STATUS.md` (grep storyboard/render context)

### Chưa đọc sâu (round sau nếu cần)

- Toàn bộ `packages/engine` seek implementation
- `packages/cli` lint rule source files
- `registry/components/*` HTML implementations từng caption
- `packages/studio` timeline mutation code
- `skills/remotion-to-hyperframes/*`
- GitHub Actions workflows full
- Every producer test fixture `meta.json`

---

*Report only under `docs/research/`. Không sửa `_refs/` hay code OmniCast.*
