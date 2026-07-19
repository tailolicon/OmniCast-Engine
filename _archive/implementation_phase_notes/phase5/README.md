# Phase 5: Upload Pipeline — Implementation Guide

> **AI Workflow:** Read `E:\Project\OmniCast Engine\AI_WORKFLOW.md` FIRST.
> **Test-First Spec:** Each TASK_X.md contains complete test files. Worker just makes pytest pass.

## Overview

Build the YouTube upload pipeline: OAuth2 token management, video upload via
YouTube Data API v3, compliance gate, upload scheduler (rate limiting + prime time),
thumbnail management, and A/B testing.

Phase 1 (infra) + Phase 2 (agents) + Phase 3 (discovery) + Phase 4 (media) are complete.

## Dependency Graph

```
TASK_A (Upload Models + OAuth2 Manager) ← MUST COMPLETE FIRST
    ↓
TASK_B (Compliance Gate)            ─┐
TASK_C (Upload Scheduler)           ├── PARALLEL (need A only)
TASK_D (YouTube API Uploader)       ─┘
                                     ↓
TASK_E (Thumbnail Manager + A/B)    ← needs A,D
    ↓
TASK_F (Upload Pipeline Orchestrator) ← needs A-E
```

**TASK_A first → B,C,D parallel → E → F last.**

## New Dependencies (add to pyproject.toml)

```toml
"google-auth>=2.29,<3",              # OAuth2
"google-auth-oauthlib>=1.2,<2",      # OAuth2 consent flow
"google-api-python-client>=2.130,<3", # YouTube Data API v3
"cryptography>=42,<44",              # Token encryption
```

## File Structure (Phase 5 additions)

```
src/omnicast/
├── upload/                          ← ALL Phase 5
│   ├── __init__.py
│   ├── models.py                    ← TASK_A
│   ├── oauth.py                     ← TASK_A (OAuth2Manager)
│   ├── compliance.py                ← TASK_B
│   ├── scheduler.py                 ← TASK_C
│   ├── youtube_api.py               ← TASK_D
│   ├── thumbnail.py                 ← TASK_E
│   └── orchestrator.py              ← TASK_F
```

## Conventions

- Python 3.12+, async-first, Pydantic v2 frozen models
- All YouTube API calls via `google-api-python-client` (NOT HTTP manually)
- Dry-run mode returns mock API responses
- `structlog` keyword args
- Add `UploadPipelineError(OmnicastError)` to shared/errors.py
- Max 400 lines/file
- NEVER log token values — log token_id or channel_id only

## Verification Checklist

```bash
uv run pytest tests/unit/test_upload_models.py tests/unit/test_oauth.py \
  tests/unit/test_compliance.py tests/unit/test_upload_scheduler.py \
  tests/unit/test_youtube_api.py tests/unit/test_upload_thumbnail.py \
  tests/unit/test_upload_orchestrator.py -v
```
