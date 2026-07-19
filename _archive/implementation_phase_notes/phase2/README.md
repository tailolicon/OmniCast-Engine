# Phase 2: Agent Core — Implementation Guide

> **AI Workflow:** Read `E:\Project\OmniCast Engine\AI_WORKFLOW.md` FIRST.
> **Test-First Spec:** Each TASK_X.md contains complete test files. Worker just makes pytest pass.

## Overview

Build the AI agent system: LLM client, Writer/Critic agents, debate loop,
tournament ranking, compliance checker, budget manager.

Phase 1 (infra) is complete. Phase 2 agents import from Phase 1 modules.

## Dependency Graph

```
TASK_A (LLM Client + Agent Base) ← MUST COMPLETE FIRST
    ↓
TASK_B (Script Models + KB Client)  ─┐
TASK_F (Compliance + Budget)         ├── PARALLEL (need A only)
                                     ↓
TASK_C (Writer Agent)           ─┐
TASK_D (Critic + Evals)          ├── PARALLEL (need A + B)
                                 ↓
TASK_E (Orchestrator + Tournament) ← needs C + D + F
```

**TASK_A first → B,F parallel → C,D parallel → E last.**

## New Dependencies (add to pyproject.toml)

```toml
"anthropic>=0.39,<1",       # Claude API client
"chromadb>=0.5,<1",         # Vector DB for knowledge base
"tiktoken>=0.7,<1",         # Token counting
```

## File Structure (Phase 2 additions)

```
src/omnicast/
├── llm/                        ← TASK_A
│   ├── __init__.py
│   ├── client.py               # Claude API wrapper (rate limit, circuit breaker, cost)
│   ├── fallback.py             # Dry-run / Ollama fallback
│   └── cost.py                 # Token counting + cost calculation
├── agents/                     ← TASK_A base, then C/D/E
│   ├── __init__.py
│   ├── base.py                 # BaseAgent (shared lifecycle: init → execute → log)
│   ├── writer.py               ← TASK_C
│   ├── critic.py               ← TASK_D
│   ├── thinking.py             ← TASK_D
│   ├── evals.py                ← TASK_D (binary eval functions, code-based)
│   ├── compliance.py           ← TASK_F
│   ├── orchestrator.py         ← TASK_E
│   ├── tournament.py           ← TASK_E (Elo ranking)
│   └── evolution.py            ← TASK_E (combine best elements)
├── kb/                         ← TASK_B
│   ├── __init__.py
│   ├── client.py               # ChromaDB wrapper
│   └── patterns.py             # Pattern storage/retrieval with decay
├── services/                   ← TASK_F
│   ├── __init__.py
│   └── budget.py               # Daily LLM spend tracking
└── models/
    └── script.py               ← TASK_B (TopicBrief, ScriptDraft, CriticScore, etc.)
```

## Tests Structure

```
tests/unit/
├── test_llm_client.py          ← TASK_A
├── test_agent_base.py          ← TASK_A
├── test_script_models.py       ← TASK_B
├── test_kb.py                  ← TASK_B
├── test_writer.py              ← TASK_C
├── test_critic.py              ← TASK_D
├── test_evals.py               ← TASK_D
├── test_compliance.py          ← TASK_F
├── test_budget.py              ← TASK_F
├── test_orchestrator.py        ← TASK_E
└── test_tournament.py          ← TASK_E
```

## Conventions (same as Phase 1)

- Python 3.12+, async-first, Pydantic v2 frozen models
- `structlog` keyword args, no `%s` formatting
- Custom exceptions from `shared/errors.py` (AgentError for this phase)
- Max 400 lines/file, max 50 lines/function
- Type hints on ALL functions
- Imports: `from omnicast.xxx.yyy import Zzz`

## Verification Checklist

```bash
# 1. Lint + Type check
uv run ruff check src/omnicast/llm/ src/omnicast/agents/ src/omnicast/kb/ src/omnicast/services/
uv run pyright src/omnicast/llm/ src/omnicast/agents/ src/omnicast/kb/ src/omnicast/services/

# 2. Unit tests
uv run pytest tests/unit/test_llm_client.py tests/unit/test_agent_base.py \
  tests/unit/test_script_models.py tests/unit/test_kb.py \
  tests/unit/test_writer.py tests/unit/test_critic.py tests/unit/test_evals.py \
  tests/unit/test_compliance.py tests/unit/test_budget.py \
  tests/unit/test_orchestrator.py tests/unit/test_tournament.py -v

# 3. Import verification
uv run python -c "
from omnicast.llm.client import LLMClient
from omnicast.llm.fallback import DryRunClient
from omnicast.llm.cost import TokenCounter, CostCalculator
from omnicast.agents.base import BaseAgent
from omnicast.agents.writer import WriterAgent
from omnicast.agents.critic import CriticAgent
from omnicast.agents.thinking import ThinkingAgent
from omnicast.agents.evals import run_binary_evals, WRITER_EVALS
from omnicast.agents.compliance import ComplianceChecker
from omnicast.agents.orchestrator import DebateOrchestrator
from omnicast.agents.tournament import Tournament, EloRating
from omnicast.agents.evolution import EvolutionAgent
from omnicast.kb.client import KBClient
from omnicast.kb.patterns import PatternStore
from omnicast.services.budget import BudgetManager
from omnicast.models.script import TopicBrief, ScriptDraft, CriticFeedback
print('ALL PHASE 2 IMPORTS OK')
"
```
