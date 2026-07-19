# TASK_B: Script Models + Knowledge Base Client

## Model: haiku
## Estimated time: 30 minutes
## Dependencies: TASK_A (must complete first)

## Overview

Define Pydantic models for the script pipeline (TopicBrief, ScriptDraft, CriticFeedback, etc.)
and the ChromaDB knowledge base client for pattern storage/retrieval.

## Files

| File | Lines | Description |
|------|------:|-------------|
| `src/omnicast/models/script.py` | ~200 | Script pipeline Pydantic models |
| `src/omnicast/kb/__init__.py` | ~5 | Exports |
| `src/omnicast/kb/client.py` | ~120 | ChromaDB async wrapper |
| `src/omnicast/kb/patterns.py` | ~100 | Pattern storage with decay |
| `tests/unit/test_script_models.py` | ~150 | Pre-written tests |
| `tests/unit/test_kb.py` | ~130 | Pre-written tests |

## Context Files

- `src/omnicast/models/schemas.py` — OmnicastSchema base, BrandConfig
- `src/omnicast/models/enums.py` — Niche, Market, TopicSource
- `src/omnicast/shared/errors.py` — AgentError

## Interface Definitions

### src/omnicast/models/script.py

```python
"""Pydantic models for the script production pipeline.

All models are frozen (immutable) and inherit from OmnicastSchema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from omnicast.models.schemas import OmnicastSchema
from omnicast.models.enums import Niche, Market, TopicSource


class TopicBrief(OmnicastSchema):
    """Input brief for Writer Agent. Created from Topic Discovery."""
    title: str
    niche: Niche
    market: Market
    source: TopicSource
    angle: str = ""                          # e.g. "storytelling", "data-driven", "contrarian"
    key_points: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    target_duration_min: int = 10
    brand_voice: str = ""                    # from BrandConfig
    lessons: list[str] = Field(default_factory=list)  # from KB, injected before writing


class ScriptSegment(OmnicastSchema):
    """One segment (section) of a script."""
    index: int
    heading: str
    content: str
    estimated_duration_seconds: int
    has_pattern_interrupt: bool = False


class ScriptDraft(OmnicastSchema):
    """Output of Writer Agent. One variant of a script."""
    variant_id: str                          # e.g. "A", "B", "C"
    brief_title: str
    hook: str                                # first 30s hook text
    segments: list[ScriptSegment] = Field(default_factory=list)
    outro: str = ""
    description_template: str = ""           # YouTube description
    tags: list[str] = Field(default_factory=list)
    estimated_duration_seconds: int = 0
    word_count: int = 0
    thinking_notes: str = ""                 # from ThinkingAgent (private)
    version: int = 1


class CriticDimension(OmnicastSchema):
    """Score for one dimension of critic evaluation."""
    name: str                                # e.g. "hook_quality"
    score: int = Field(ge=0, le=25)          # weighted score for this dimension
    max_score: int
    feedback: str = ""


class CriticFeedback(OmnicastSchema):
    """Structured output from Critic Agent."""
    variant_id: str
    total_score: int = Field(ge=0, le=100)
    dimensions: list[CriticDimension] = Field(default_factory=list)
    approved: bool = False                   # score >= threshold
    rejection_reasons: list[str] = Field(default_factory=list)
    specific_fixes: list[str] = Field(default_factory=list)  # line-level suggestions
    round_number: int = 1


class DebateRound(OmnicastSchema):
    """Record of one debate round (Writer revision + Critic review)."""
    round_number: int
    draft: ScriptDraft
    feedback: CriticFeedback
    thinking_notes: str = ""
    score_delta: int = 0                     # change from previous round


class TournamentMatch(OmnicastSchema):
    """Record of pairwise comparison in tournament."""
    variant_a: str
    variant_b: str
    winner: str
    reason: str


class EloRating(OmnicastSchema):
    """Elo rating for a script variant."""
    variant_id: str
    rating: float = 1000.0
    matches_played: int = 0


class EngagementPattern(OmnicastSchema):
    """Learned pattern from production data, stored in KB."""
    pattern_id: str
    niche: Niche
    market: Market
    finding: str
    confidence: float = Field(ge=0, le=1)
    sample_size: int
    decay_date: datetime                     # pattern expires after this
    source: str = "path_3_context"
```

### src/omnicast/kb/client.py

```python
"""ChromaDB async wrapper for OmniCast knowledge base."""

from __future__ import annotations

import structlog

from omnicast.shared.errors import AgentError

logger = structlog.get_logger()


class KBClient:
    """Async ChromaDB client for storing/retrieving embeddings.

    Collections:
    - "scripts": past script texts + metadata
    - "patterns": engagement patterns with decay
    - "lessons": agent lessons (per agent_name)
    """

    def __init__(self, persist_directory: str = "./chromadb_data") -> None:
        """Initialize ChromaDB client. Lazy — creates on first use."""
        raise NotImplementedError

    async def add_document(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict | None = None,
    ) -> None:
        """Add or update a document in a collection.
        Raises: AgentError on failure."""
        raise NotImplementedError

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Query similar documents.
        Returns list of {id, text, metadata, distance}."""
        raise NotImplementedError

    async def delete_document(self, collection: str, doc_id: str) -> None:
        """Delete a document by ID."""
        raise NotImplementedError

    async def count(self, collection: str) -> int:
        """Return document count in collection."""
        raise NotImplementedError
```

### src/omnicast/kb/patterns.py

```python
"""Pattern storage with decay for engagement patterns."""

from __future__ import annotations

from datetime import datetime

import structlog

from omnicast.kb.client import KBClient
from omnicast.models.script import EngagementPattern
from omnicast.models.enums import Niche

logger = structlog.get_logger()


class PatternStore:
    """Store and retrieve engagement patterns with automatic decay."""

    def __init__(self, kb: KBClient) -> None:
        raise NotImplementedError

    async def store_pattern(self, pattern: EngagementPattern) -> None:
        """Store pattern in KB. Raises AgentError on failure."""
        raise NotImplementedError

    async def get_patterns_for_niche(
        self,
        niche: Niche,
        limit: int = 10,
    ) -> list[EngagementPattern]:
        """Get active (non-expired) patterns for a niche, sorted by confidence."""
        raise NotImplementedError

    async def get_patterns_for_brief(
        self,
        brief_text: str,
        niche: Niche,
        limit: int = 5,
    ) -> list[EngagementPattern]:
        """Semantic search: find patterns relevant to a specific brief."""
        raise NotImplementedError

    async def expire_old_patterns(self) -> int:
        """Delete patterns past their decay_date. Returns count deleted."""
        raise NotImplementedError
```

## DO NOT

- ❌ Do not use mutable Pydantic models — all frozen via OmnicastSchema
- ❌ Do not create real ChromaDB connections in tests — mock KBClient
- ❌ Do not add fields not listed above — keep models minimal
- ❌ Do not import from agents/ — models are dependency-free

## Pre-Written Tests

### tests/unit/test_script_models.py

```python
"""Tests for script pipeline models."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from omnicast.models.script import (
    TopicBrief,
    ScriptSegment,
    ScriptDraft,
    CriticDimension,
    CriticFeedback,
    DebateRound,
    TournamentMatch,
    EloRating,
    EngagementPattern,
)
from omnicast.models.enums import Niche, Market, TopicSource


class TestTopicBrief:
    def test_create_minimal(self):
        brief = TopicBrief(
            title="5 Investment Tips",
            niche=Niche.FINANCE,
            market=Market.US,
            source=TopicSource.GOOGLE_TRENDS,
        )
        assert brief.title == "5 Investment Tips"
        assert brief.angle == ""
        assert brief.lessons == []

    def test_create_full(self):
        brief = TopicBrief(
            title="Crypto Regulation 2026",
            niche=Niche.FINANCE,
            market=Market.US,
            source=TopicSource.REDDIT,
            angle="contrarian",
            key_points=["SEC ruling", "DeFi impact"],
            source_urls=["https://reddit.com/r/crypto/123"],
            target_duration_min=12,
            brand_voice="authoritative",
            lessons=["Avoid rhetorical questions in hook"],
        )
        assert len(brief.key_points) == 2
        assert brief.target_duration_min == 12

    def test_frozen(self):
        brief = TopicBrief(
            title="Test", niche=Niche.TECH, market=Market.UK,
            source=TopicSource.MANUAL,
        )
        with pytest.raises(ValidationError):
            brief.title = "Changed"


class TestScriptDraft:
    def test_create_with_segments(self):
        draft = ScriptDraft(
            variant_id="A",
            brief_title="Investment Tips",
            hook="Did you know 90% of traders lose money?",
            segments=[
                ScriptSegment(
                    index=0, heading="Intro", content="...",
                    estimated_duration_seconds=30, has_pattern_interrupt=True,
                ),
                ScriptSegment(
                    index=1, heading="Tip 1", content="...",
                    estimated_duration_seconds=90,
                ),
            ],
            word_count=1500,
            estimated_duration_seconds=600,
        )
        assert len(draft.segments) == 2
        assert draft.segments[0].has_pattern_interrupt is True

    def test_default_version(self):
        draft = ScriptDraft(variant_id="B", brief_title="Test", hook="Hook")
        assert draft.version == 1


class TestCriticFeedback:
    def test_create_approved(self):
        fb = CriticFeedback(
            variant_id="A",
            total_score=85,
            dimensions=[
                CriticDimension(name="hook_quality", score=22, max_score=25),
                CriticDimension(name="anti_ai_cliche", score=18, max_score=20),
            ],
            approved=True,
        )
        assert fb.approved is True
        assert fb.total_score == 85

    def test_create_rejected(self):
        fb = CriticFeedback(
            variant_id="A",
            total_score=55,
            approved=False,
            rejection_reasons=["Hook too generic", "AI cliches detected"],
            specific_fixes=["Replace hook with bold statement"],
        )
        assert fb.approved is False
        assert len(fb.rejection_reasons) == 2

    def test_score_range_validation(self):
        with pytest.raises(ValidationError):
            CriticFeedback(variant_id="A", total_score=101)
        with pytest.raises(ValidationError):
            CriticFeedback(variant_id="A", total_score=-1)


class TestDebateRound:
    def test_create(self):
        draft = ScriptDraft(variant_id="A", brief_title="Test", hook="Hook")
        feedback = CriticFeedback(variant_id="A", total_score=72)
        rnd = DebateRound(
            round_number=1,
            draft=draft,
            feedback=feedback,
            score_delta=0,
        )
        assert rnd.round_number == 1
        assert rnd.feedback.total_score == 72


class TestEloRating:
    def test_default_rating(self):
        rating = EloRating(variant_id="A")
        assert rating.rating == 1000.0
        assert rating.matches_played == 0


class TestEngagementPattern:
    def test_create(self):
        pattern = EngagementPattern(
            pattern_id="EP-2026-0001",
            niche=Niche.FINANCE,
            market=Market.US,
            finding="Numbered lists improve retention by 22%",
            confidence=0.75,
            sample_size=12,
            decay_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        assert pattern.confidence == 0.75

    def test_confidence_range(self):
        with pytest.raises(ValidationError):
            EngagementPattern(
                pattern_id="X", niche=Niche.TECH, market=Market.US,
                finding="test", confidence=1.5, sample_size=1,
                decay_date=datetime.now(timezone.utc),
            )
```

### tests/unit/test_kb.py

```python
"""Tests for Knowledge Base client and pattern store."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from omnicast.kb.client import KBClient
from omnicast.kb.patterns import PatternStore
from omnicast.models.script import EngagementPattern
from omnicast.models.enums import Niche, Market
from omnicast.shared.errors import AgentError


class TestKBClient:
    @pytest.fixture
    def mock_chromadb(self):
        """Mock chromadb.Client."""
        with patch("omnicast.kb.client.chromadb") as mock_chroma:
            mock_client = MagicMock()
            mock_chroma.PersistentClient.return_value = mock_client
            mock_collection = MagicMock()
            mock_client.get_or_create_collection.return_value = mock_collection
            yield mock_client, mock_collection

    def test_init(self, mock_chromadb):
        client = KBClient(persist_directory="/tmp/test_kb")
        assert client is not None

    async def test_add_document(self, mock_chromadb):
        _, mock_collection = mock_chromadb
        client = KBClient(persist_directory="/tmp/test_kb")
        await client.add_document(
            collection="scripts",
            doc_id="doc_001",
            text="Script about finance",
            metadata={"niche": "finance"},
        )
        mock_collection.upsert.assert_called_once()

    async def test_query(self, mock_chromadb):
        _, mock_collection = mock_chromadb
        mock_collection.query.return_value = {
            "ids": [["doc_001"]],
            "documents": [["Script text"]],
            "metadatas": [[{"niche": "finance"}]],
            "distances": [[0.1]],
        }
        client = KBClient(persist_directory="/tmp/test_kb")
        results = await client.query(
            collection="scripts",
            query_text="investment tips",
            n_results=3,
        )
        assert len(results) == 1
        assert results[0]["id"] == "doc_001"

    async def test_query_empty(self, mock_chromadb):
        _, mock_collection = mock_chromadb
        mock_collection.query.return_value = {
            "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]],
        }
        client = KBClient(persist_directory="/tmp/test_kb")
        results = await client.query("scripts", "nonexistent", n_results=5)
        assert results == []

    async def test_delete_document(self, mock_chromadb):
        _, mock_collection = mock_chromadb
        client = KBClient(persist_directory="/tmp/test_kb")
        await client.delete_document("scripts", "doc_001")
        mock_collection.delete.assert_called_once()

    async def test_count(self, mock_chromadb):
        _, mock_collection = mock_chromadb
        mock_collection.count.return_value = 42
        client = KBClient(persist_directory="/tmp/test_kb")
        count = await client.count("scripts")
        assert count == 42


class TestPatternStore:
    @pytest.fixture
    def mock_kb(self) -> AsyncMock:
        kb = AsyncMock(spec=KBClient)
        kb.query.return_value = []
        return kb

    @pytest.fixture
    def store(self, mock_kb) -> PatternStore:
        return PatternStore(kb=mock_kb)

    @pytest.fixture
    def sample_pattern(self) -> EngagementPattern:
        return EngagementPattern(
            pattern_id="EP-001",
            niche=Niche.FINANCE,
            market=Market.US,
            finding="Numbered lists improve retention",
            confidence=0.8,
            sample_size=15,
            decay_date=datetime.now(timezone.utc) + timedelta(days=90),
        )

    async def test_store_pattern(self, store, mock_kb, sample_pattern):
        await store.store_pattern(sample_pattern)
        mock_kb.add_document.assert_called_once()
        call_args = mock_kb.add_document.call_args
        assert call_args.kwargs["collection"] == "patterns"
        assert call_args.kwargs["doc_id"] == "EP-001"

    async def test_get_patterns_for_niche(self, store, mock_kb, sample_pattern):
        mock_kb.query.return_value = [
            {
                "id": "EP-001",
                "text": sample_pattern.finding,
                "metadata": {
                    "niche": "finance",
                    "market": "US",
                    "confidence": 0.8,
                    "sample_size": 15,
                    "decay_date": sample_pattern.decay_date.isoformat(),
                    "pattern_id": "EP-001",
                    "source": "path_3_context",
                },
                "distance": 0.1,
            }
        ]
        patterns = await store.get_patterns_for_niche(Niche.FINANCE, limit=5)
        assert len(patterns) == 1
        assert patterns[0].pattern_id == "EP-001"

    async def test_get_patterns_filters_expired(self, store, mock_kb):
        expired_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_kb.query.return_value = [
            {
                "id": "EP-OLD",
                "text": "Old pattern",
                "metadata": {
                    "niche": "finance", "market": "US",
                    "confidence": 0.5, "sample_size": 3,
                    "decay_date": expired_date,
                    "pattern_id": "EP-OLD", "source": "path_3_context",
                },
                "distance": 0.2,
            }
        ]
        patterns = await store.get_patterns_for_niche(Niche.FINANCE)
        assert len(patterns) == 0  # expired patterns filtered out

    async def test_expire_old_patterns(self, store, mock_kb):
        mock_kb.query.return_value = [
            {
                "id": "EP-EXPIRED",
                "text": "expired",
                "metadata": {
                    "niche": "tech", "market": "US",
                    "confidence": 0.3, "sample_size": 2,
                    "decay_date": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                    "pattern_id": "EP-EXPIRED", "source": "path_3_context",
                },
                "distance": 0.0,
            }
        ]
        count = await store.expire_old_patterns()
        assert count >= 0
```

## Verify

```bash
uv run pytest tests/unit/test_script_models.py tests/unit/test_kb.py -v
uv run ruff check src/omnicast/models/script.py src/omnicast/kb/
uv run pyright src/omnicast/models/script.py src/omnicast/kb/
```
