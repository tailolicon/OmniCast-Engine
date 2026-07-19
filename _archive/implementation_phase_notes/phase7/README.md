# Phase 7: Analytics Loop + Video Intelligence — Implementation Guide

> **AI Workflow:** Read `E:\Project\OmniCast Engine\AI_WORKFLOW.md` FIRST.
> **Test-First Spec:** Each TASK_X.md contains complete test files. Worker just makes pytest pass.

## Overview

Closed-loop analytics: YouTube metrics → health scoring → diagnosis → auto-correction → learning.
Plus Video Intelligence: analyze competitor production style → ProductionBlueprint.

Phase 1-6 complete. This phase requires real YouTube data from published videos.

## Dependency Graph

```
TASK_A (Analytics Models) ← MUST COMPLETE FIRST
    ↓
TASK_B (YouTube Analytics Crawler)    ─┐
TASK_C (Health Score + Trend Analyzer) ├── PARALLEL (need A only)
TASK_F (ROI Calculator + KB Decay)     ─┘
    ↓
TASK_D (Retention Analyst + Content Quality Scorer) ← needs A,B
TASK_H (Video Intelligence + ProductionBlueprint)   ← needs A,B
    ↓
TASK_E (Diagnostic Engine + Auto-Corrector) ← needs A,B,C,D
    ↓
TASK_G (Strategist Agent) ← needs A-F
```

**A first → B,C,F parallel → D,H parallel → E → G last.**

## New Dependencies (add to pyproject.toml)

```toml
"google-api-python-client>=2.130,<3",  # YouTube Analytics API (already in Phase 5)
"scipy>=1.13,<2",                      # Statistical tests (t-test, chi-squared)
"librosa>=0.10,<1",                    # Audio analysis (music energy curve)
```

## File Structure (Phase 7 additions)

```
src/omnicast/
├── analytics/
│   ├── __init__.py
│   ├── models.py            ← TASK_A
│   ├── crawler.py           ← TASK_B
│   ├── health.py            ← TASK_C (HealthScorer + TrendAnalyzer)
│   ├── retention.py         ← TASK_D (RetentionAnalyst)
│   ├── quality_scorer.py    ← TASK_D (ContentQualityScorer)
│   ├── diagnostic.py        ← TASK_E (DiagnosticEngine)
│   ├── corrector.py         ← TASK_E (AutoCorrector)
│   ├── roi.py               ← TASK_F
│   ├── kb_decay.py          ← TASK_F
│   ├── strategist.py        ← TASK_G
│   └── video_intel.py       ← TASK_H
```

## Conventions

- Python 3.12+, async-first, Pydantic v2 frozen models
- YouTube Analytics API via `google-api-python-client`
- Dry-run mode returns mock metrics
- `structlog` keyword args
- Add `AnalyticsError(OmnicastError)` to shared/errors.py
- Max 400 lines/file
- All scorers return 0-10 scale, health 0-100

## Verification Checklist

```bash
uv run pytest tests/unit/test_analytics_models.py tests/unit/test_analytics_crawler.py \
  tests/unit/test_health.py tests/unit/test_retention.py tests/unit/test_quality_scorer.py \
  tests/unit/test_diagnostic.py tests/unit/test_corrector.py tests/unit/test_roi.py \
  tests/unit/test_kb_decay.py tests/unit/test_strategist.py tests/unit/test_video_intel.py -v
```
