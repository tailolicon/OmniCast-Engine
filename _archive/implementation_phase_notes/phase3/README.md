# Phase 3: Topic Discovery Engine — Implementation Guide

> **AI Workflow:** Read `E:\Project\OmniCast Engine\AI_WORKFLOW.md` FIRST.
> **Test-First Spec:** Each TASK_X.md contains complete test files. Worker just makes pytest pass.

## Overview

Build the Topic Discovery Engine: 5 parallel source scanners, scoring system (0-100),
KB novelty check, brief generation, and discovery orchestrator.

Phase 1 (infra) + Phase 2 (agents) are complete. Phase 3 imports from both.

## Dependency Graph

```
TASK_A (Topic Models + BaseScanner) ← MUST COMPLETE FIRST
    ↓
TASK_B (YouTube Competitor Scanner)  ─┐
TASK_C (Google Trends Scanner)        ├── PARALLEL (need A only)
TASK_D (Reddit Scanner)               │
TASK_E (Podcast + News RSS Scanners) ─┘
                                      ↓
TASK_F (Topic Scorer + Brief Generator + Orchestrator) ← needs A-E
```

**TASK_A first → B,C,D,E parallel → F last.**

## New Dependencies (add to pyproject.toml)

```toml
"pytrends>=4.9,<5",          # Google Trends API
"praw>=7.7,<8",              # Reddit API
"feedparser>=6.0,<7",        # RSS feed parsing
"httpx>=0.27,<1",            # Async HTTP client (YouTube Data API, Podcast Index)
```

## File Structure (Phase 3 additions)

```
src/omnicast/
├── discovery/                      ← ALL Phase 3
│   ├── __init__.py
│   ├── models.py                   ← TASK_A (TopicRawData, SourceResult, ScoredTopic)
│   ├── base.py                     ← TASK_A (BaseScanner abstract)
│   ├── youtube_scanner.py          ← TASK_B
│   ├── trends_scanner.py           ← TASK_C
│   ├── reddit_scanner.py           ← TASK_D
│   ├── podcast_scanner.py          ← TASK_E
│   ├── news_scanner.py             ← TASK_E
│   ├── scorer.py                   ← TASK_F (TopicScorer)
│   ├── brief_generator.py          ← TASK_F (BriefGenerator)
│   └── orchestrator.py             ← TASK_F (DiscoveryOrchestrator)
```

## Tests Structure

```
tests/unit/
├── test_discovery_models.py        ← TASK_A
├── test_base_scanner.py            ← TASK_A
├── test_youtube_scanner.py         ← TASK_B
├── test_trends_scanner.py          ← TASK_C
├── test_reddit_scanner.py          ← TASK_D
├── test_podcast_scanner.py         ← TASK_E
├── test_news_scanner.py            ← TASK_E
├── test_scorer.py                  ← TASK_F
├── test_brief_generator.py         ← TASK_F
└── test_orchestrator.py            ← TASK_F
```

## Conventions (same as Phase 1-2)

- Python 3.12+, async-first, Pydantic v2 frozen models
- `structlog` keyword args, no `%s` formatting
- Custom exceptions from `shared/errors.py` (add `DiscoveryError`)
- Max 400 lines/file, max 50 lines/function
- Type hints on ALL functions
- Imports: `from omnicast.xxx.yyy import Zzz`

## Verification Checklist

```bash
# 1. Lint + Type check
uv run ruff check src/omnicast/discovery/
uv run pyright src/omnicast/discovery/

# 2. Unit tests
uv run pytest tests/unit/test_discovery_models.py tests/unit/test_base_scanner.py \
  tests/unit/test_youtube_scanner.py tests/unit/test_trends_scanner.py \
  tests/unit/test_reddit_scanner.py tests/unit/test_podcast_scanner.py \
  tests/unit/test_news_scanner.py tests/unit/test_scorer.py \
  tests/unit/test_brief_generator.py tests/unit/test_orchestrator.py -v

# 3. Import verification
uv run python -c "
from omnicast.discovery.models import TopicRawData, SourceResult, ScoredTopic
from omnicast.discovery.base import BaseScanner
from omnicast.discovery.youtube_scanner import YouTubeScanner
from omnicast.discovery.trends_scanner import TrendsScanner
from omnicast.discovery.reddit_scanner import RedditScanner
from omnicast.discovery.podcast_scanner import PodcastScanner
from omnicast.discovery.news_scanner import NewsScanner
from omnicast.discovery.scorer import TopicScorer
from omnicast.discovery.brief_generator import BriefGenerator
from omnicast.discovery.orchestrator import DiscoveryOrchestrator
print('ALL PHASE 3 IMPORTS OK')
"
```
