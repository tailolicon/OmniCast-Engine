# Phase 4: Media Pipeline — Implementation Guide

> **AI Workflow:** Read `E:\Project\OmniCast Engine\AI_WORKFLOW.md` FIRST.
> **Test-First Spec:** Each TASK_X.md contains complete test files. Worker just makes pytest pass.

## Overview

Build the media production pipeline: TTS, image gen, music, video gen, subtitles,
thumbnails, FFmpeg render, content fingerprinting, asset management + character registry.
All modules are async wrappers around external tools (Kokoro, ComfyUI, WhisperX, FFmpeg, etc.).

Phase 1 (infra) + Phase 2 (agents) + Phase 3 (discovery) are complete.

## Dependency Graph

```
TASK_A (Media Models + Pipeline Base)    ← MUST COMPLETE FIRST
    ↓
TASK_B (TTS Module)                  ─┐
TASK_C (Image Gen Module)             ├── PARALLEL (need A only)
TASK_D (Music Module)                 │
TASK_E (Video Gen + Subtitle + Thumb) │
TASK_H (Asset Manager + Characters)  ─┘
                                      ↓
TASK_F (FFmpeg Render + Fingerprint)  ← needs A-E,H
    ↓
TASK_G (Media Pipeline Orchestrator)  ← needs A-F,H
```

**TASK_A first → B,C,D,E,H parallel → F → G last.**

## New Dependencies (add to pyproject.toml)

```toml
"kokoro>=0.9,<1",              # TTS primary
"soundfile>=0.12,<1",          # Audio I/O
"numpy>=1.26,<3",              # Audio processing
"Pillow>=10,<12",              # Image/thumbnail processing
"imagehash>=4.3,<5",           # Perceptual hashing
"librosa>=0.10,<1",            # Audio analysis (fingerprint)
```

## File Structure (Phase 4 additions)

```
src/omnicast/
├── media/                          ← ALL Phase 4
│   ├── __init__.py
│   ├── models.py                   ← TASK_A
│   ├── base.py                     ← TASK_A (BaseMediaModule)
│   ├── tts.py                      ← TASK_B
│   ├── image_gen.py                ← TASK_C
│   ├── music.py                    ← TASK_D
│   ├── video_gen.py                ← TASK_E
│   ├── subtitle.py                 ← TASK_E
│   ├── thumbnail.py                ← TASK_E
│   ├── ffmpeg.py                   ← TASK_F
│   ├── fingerprint.py              ← TASK_F
│   ├── asset_manager.py            ← TASK_H
│   └── orchestrator.py             ← TASK_G
```

## Conventions

- Python 3.12+, async-first, Pydantic v2 frozen models
- All external tool calls via `asyncio.create_subprocess_exec` (not `os.system`)
- Dry-run mode returns mock outputs (no actual GPU/TTS calls)
- `structlog` keyword args
- Add `MediaError(OmnicastError)` to shared/errors.py
- Max 400 lines/file

## Verification Checklist

```bash
uv run pytest tests/unit/test_media_models.py tests/unit/test_media_base.py \
  tests/unit/test_tts.py tests/unit/test_image_gen.py tests/unit/test_music.py \
  tests/unit/test_video_gen.py tests/unit/test_subtitle.py tests/unit/test_thumbnail.py \
  tests/unit/test_ffmpeg.py tests/unit/test_fingerprint.py tests/unit/test_asset_manager.py \
  tests/unit/test_media_orchestrator.py -v
```
