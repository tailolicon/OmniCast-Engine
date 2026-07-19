# Phase 6: Dashboard + Alerts — Implementation Guide

> **AI Workflow:** Read `E:\Project\OmniCast Engine\AI_WORKFLOW.md` FIRST.
> **Test-First Spec:** Each TASK_X.md contains complete test files. Worker just makes pytest pass.

## Overview

Streamlit MVP dashboard (7 tabs) + Cloudflare Tunnel auth + Telegram Bot extensions.
Phase 1-5 complete. This phase provides monitoring UI over existing data.

## Dependency Graph

```
TASK_A (Dashboard Models + Data Service) ← MUST COMPLETE FIRST
    ↓
TASK_B (Streamlit App Shell + Auth)  ─┐
TASK_C (Home + Production + Channel) ├── PARALLEL (need A only)
TASK_D (Infra + DLQ + Token tabs)    ─┘
    ↓
TASK_E (Compliance Audit + Telegram Extensions) ← needs A-D
```

**TASK_A first → B,C,D parallel → E last.**

## New Dependencies (add to pyproject.toml)

```toml
"streamlit>=1.35,<2",
"plotly>=5.22,<6",
"streamlit-autorefresh>=1.0,<2",
```

## File Structure (Phase 6 additions)

```
src/omnicast/
├── dashboard/
│   ├── __init__.py
│   ├── models.py          ← TASK_A
│   ├── data_service.py    ← TASK_A
│   ├── app.py             ← TASK_B (Streamlit entry)
│   ├── auth.py            ← TASK_B
│   ├── tabs/
│   │   ├── __init__.py
│   │   ├── home.py        ← TASK_C
│   │   ├── production.py  ← TASK_C
│   │   ├── channels.py    ← TASK_C
│   │   ├── infra.py       ← TASK_D
│   │   ├── dlq.py         ← TASK_D
│   │   ├── tokens.py      ← TASK_D
│   │   └── compliance.py  ← TASK_E
│   └── components/
│       ├── __init__.py
│       └── charts.py      ← TASK_C (shared chart helpers)
```

## Conventions

- Python 3.12+, Pydantic v2 frozen models
- `structlog` keyword args
- Streamlit multi-page via tabs, NOT separate pages
- Auto-refresh every 30s via streamlit-autorefresh
- Max 400 lines/file
- All data via DashboardDataService (no direct DB in tabs)

## Verification Checklist

```bash
uv run pytest tests/unit/test_dashboard_models.py tests/unit/test_data_service.py \
  tests/unit/test_dashboard_auth.py tests/unit/test_dashboard_tabs.py \
  tests/unit/test_telegram_dashboard.py -v
```
