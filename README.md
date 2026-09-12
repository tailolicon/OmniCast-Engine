<div align="center">

# OmniCast Engine

### AI-assisted content operations from idea to publish-ready video

OmniCast is an end-to-end production engine for running multiple video channels from one control plane. It connects topic discovery, research, script generation, editorial review, media creation, rendering, quality control, publishing, analytics, and feedback-driven optimization into a resumable workflow.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./implementation/pyproject.toml)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111)](./implementation/frontend_v2/package.json)
[![Mobile](https://img.shields.io/badge/Mobile-Capacitor%207-119EFF?logo=capacitor&logoColor=white)](./mobile/README.md)
[![Status](https://img.shields.io/badge/Status-Active%20development-7C3AED)](./IMPLEMENTATION_STATUS.md)

</div>

## What OmniCast does

OmniCast treats content production as a pipeline rather than a collection of disconnected scripts:

```text
Discover topics
      ↓
Research + deduplicate
      ↓
Plan + write
      ↓
Critic / compliance / release gates
      ↓
Voice + images + footage + music + subtitles
      ↓
Render + thumbnail
      ↓
Frame / audio / output audit
      ↓
Human approval
      ↓
Publish
      ↓
Analytics → channel health → strategy feedback
```

The goal is not simply to generate more media. The engine is designed to preserve editorial quality, make failures observable, resume interrupted work safely, and stop low-confidence output before it reaches a publishing step.

## Highlights

| Area | What is built |
| --- | --- |
| **Discovery** | Niche scanning, topic discovery, trend/research inputs, duplicate prevention, topic vaults and channel-aware selection. |
| **Writing** | Structured planning, multi-role LLM routing, narrative and explainer flows, writer/critic loops, bounded repair, compliance checks and release challengers. |
| **Media** | TTS, generated imagery, stock footage, video generation, music/SFX, subtitles, thumbnails, character consistency and channel-specific visual policies. |
| **Rendering** | FFmpeg-based assembly, scene timing, pacing/prosody, transitions, captions, audio mastering and resumable render stages. |
| **Quality control** | Image gates, final-frame inspection, duplicate checks, story/world-fact checks, output audit, visual consistency checks and fail-closed STRICT paths. |
| **Publishing** | YouTube OAuth + Data API publishing, scheduling, thumbnail handling, approval gates and channel guardrails. |
| **Analytics** | YouTube Analytics collection, retention/health/ROI signals, diagnostics and strategy feedback. |
| **Operations** | Desktop cockpit, web UI, Android/mobile controller, job engine, checkpoints, provider capability routing, budgets, alerts and persistent run evidence. |

## Built for multi-channel operation

A channel is more than a title and an API key. OmniCast can keep channel-specific configuration for content format, voice, visual language, sourcing policy, quality thresholds, publishing destinations and brand assets.

That makes it possible to run very different formats through the same engine without forcing them into one template. A footage-heavy finance channel, an illustrated history channel and a slow-burn horror channel can use different production policies while sharing orchestration, observability, storage and analytics infrastructure.

## Quality is part of the pipeline

OmniCast has explicit gates between expensive or irreversible stages. Depending on the selected flow, these include:

- structured plan validation before prose is generated;
- critic, compliance and release checks with bounded repair instead of unlimited retry loops;
- image-level acceptance checks before assets reach the compositor;
- stock-footage relevance, orientation, duplication and style checks;
- final-frame inspection after the video has actually been muxed;
- audio/output checks including duration, stream validity and mastering targets;
- resumable evidence files so a failure can be audited instead of guessed at;
- human approval before a production publish path.

The render stack targets a mastered final output around **-14 LUFS**, **48 kHz stereo**, and **AAC 192 kbps** where the production renderer owns the final audio pass.

## Operator interfaces

### Desktop cockpit

`implementation/omnicast_desktop.py` launches the desktop operator experience and connects it to the local backend. On Windows, the repository includes a one-click launcher:

```text
Start OmniCast.bat
```

### Web UI

The main dashboard is a React 19 + TypeScript application in [`implementation/frontend_v2`](./implementation/frontend_v2). Its production build is served by the FastAPI backend at:

```text
http://127.0.0.1:8767
```

Interactive API documentation is available at:

```text
http://127.0.0.1:8767/docs
```

### Mobile controller

[`mobile/`](./mobile) contains the React + Capacitor Android controller. It provides operational views for channels, approvals, costs, pipeline controls and settings, and the web build is also designed to be served as the mobile UI.

## Quick start

### Requirements

For the core backend and local development:

- **Python 3.12+**
- **uv**
- **FFmpeg + ffprobe**
- **Docker / Docker Compose** for the default PostgreSQL, RabbitMQ and Redis development stack
- **Node.js + npm** only when rebuilding the React frontends

Media and model providers have their own requirements. Configure only the providers you plan to use; local, API, CLI and browser-backed routes are intentionally separated behind provider/capability layers.

### 1. Create the environment

```bash
cd implementation
cp .env.example .env
uv sync --extra dev
```

On Windows PowerShell, use:

```powershell
cd implementation
Copy-Item .env.example .env
uv sync --extra dev
```

Review `.env` before enabling production integrations. Never commit real provider keys, OAuth material or private credentials.

### 2. Start local infrastructure

```bash
docker compose up -d
```

The development compose file starts:

- PostgreSQL 16 on `5432`
- RabbitMQ 3.13 on `5672` with management UI on `15672`
- Redis 7 on `6379`

### 3. Start OmniCast

Cross-platform backend:

```bash
uv run python -X utf8 run_backend.py
```

Then open `http://127.0.0.1:8767`.

On Windows, after the environment has been created, you can launch the desktop app from the repository root with:

```text
Start OmniCast.bat
```

### 4. Rebuild the desktop web UI when needed

```bash
cd implementation/frontend_v2
npm install
npm run build
```

Vite writes the production bundle directly into the backend's `webui_v2` directory, so the next backend start serves the new build.

## Configuration

The checked-in [`implementation/.env.example`](./implementation/.env.example) documents the current runtime switches. Configuration is grouped around a few concepts:

| Group | Examples |
| --- | --- |
| **Infrastructure** | PostgreSQL, RabbitMQ, Redis, storage paths |
| **LLM routing** | model/provider selection, role-specific effort, fallback modes |
| **Media providers** | image/video/TTS providers and model choices |
| **Publishing** | YouTube OAuth, channel credentials and destination settings |
| **Quality** | STRICT behavior, narrative quality profiles, consistency and audit gates |
| **Operations** | Telegram alerts, job/runtime behavior, budgets and provider availability |

Provider selection is not hard-wired into the business logic. OmniCast has capability and runtime routing layers so providers can be changed without rewriting the entire production pipeline.

## Architecture

The Python application lives under `implementation/src/omnicast/` and is split by responsibility rather than by one giant orchestration module.

```text
OmniCast Engine/
├── implementation/
│   ├── src/omnicast/
│   │   ├── agents/          # writing, critic, compliance and editorial agents
│   │   ├── analytics/       # metrics, health, retention, ROI and strategy
│   │   ├── api/             # FastAPI backend + built web UI
│   │   ├── capabilities/    # provider/capability resolution
│   │   ├── media/           # TTS, image/video providers, render support, QA
│   │   ├── pipeline/        # pipeline execution and step orchestration
│   │   ├── platforms/       # publishing platform adapters
│   │   ├── upload/          # YouTube publishing and scheduling
│   │   └── ...
│   ├── frontend_v2/         # React operator cockpit
│   ├── channels/            # channel profiles
│   ├── scripts/             # operational and audit utilities
│   ├── specs/               # production-flow specifications
│   ├── tests/               # Python test suite
│   ├── render_real_video.py # primary production render entry point
│   └── run_backend.py       # local API/UI launcher
├── mobile/                  # mobile web + Capacitor Android app
├── scriptfarm/              # script-production workflow tooling
├── docs/                    # project documentation
└── IMPLEMENTATION_STATUS.md # current implementation source of truth
```

## Publishing and platform support

The mature production publishing path is **YouTube**. Uploads use the YouTube Data API with OAuth rather than browser form automation, and the pipeline includes approval and compliance gates around the publish step.

A broader platform abstraction is also present, including additional destination adapters and vertical-video export infrastructure. Those paths are still evolving, so check [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md) before treating a non-YouTube integration as production-ready.

## Development

Run the Python test suite from `implementation/`:

```bash
uv run pytest
```

Useful focused checks can be run with normal pytest filters, for example:

```bash
uv run pytest tests/unit -q
```

Frontend checks:

```bash
cd implementation/frontend_v2
npm run build
npm run lint
```

When adding a new media provider, start with [`implementation/docs/ADD_NEW_PROVIDER.md`](./implementation/docs/ADD_NEW_PROVIDER.md) so the adapter participates in capability discovery, health checks and fallback routing instead of bypassing the provider system.

## Project status

OmniCast is under active development and contains both stable production paths and experimental integrations. The repository intentionally keeps implementation status separate from long-range design documents.

For the most accurate view of what is implemented **right now**, read:

- [`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md) — current code-grounded status and known gaps;
- [`Plans.md`](./Plans.md) — active task tracking;
- [`implementation/specs/`](./implementation/specs) — detailed contracts for specialized production flows;
- [`mobile/README.md`](./mobile/README.md) — mobile controller setup;
- [`implementation/docs/ADD_NEW_PROVIDER.md`](./implementation/docs/ADD_NEW_PROVIDER.md) — provider integration guide.

## Responsible operation

OmniCast is automation infrastructure, not a substitute for editorial responsibility. Production operators should verify source rights, platform rules, disclosure requirements, factual claims, account permissions and all generated media before publication.
