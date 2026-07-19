"""Tests for NicheDedupAgent — prefilter and prompt logic."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.niche_dedup import (
    keyword_prefilter, NicheDedupAgent,
    DUPLICATE_THRESHOLD, BORDERLINE_THRESHOLD, MAX_CANDIDATES,
    _tokenize,
)
from omnicast.llm.client import LLMClient, LLMResponse


# ── _tokenize ────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_removes_stop_words(self):
        tokens = _tokenize("the best finance tips for a retiree")
        assert "the" not in tokens
        assert "for" not in tokens
        assert "a" not in tokens
        assert "finance" in tokens
        assert "tips" in tokens
        assert "retiree" in tokens

    def test_lowercases(self):
        tokens = _tokenize("INSOMNIA Sleep Adults")
        assert "insomnia" in tokens
        assert "sleep" in tokens
        assert "adults" in tokens

    def test_strips_punctuation(self):
        tokens = _tokenize("gut-health, inflammation: adults 50+")
        # hyphen removed → "guthealth" compound token; comma/colon stripped
        assert "guthealth" in tokens or "health" in tokens or "gut" in tokens
        assert "inflammation" in tokens
        assert "adults" in tokens

    def test_filters_short_words(self):
        tokens = _tokenize("a to be or")
        # all are stop words or < 3 chars
        assert len(tokens) == 0

    def test_empty_string(self):
        assert _tokenize("") == set()


# ── keyword_prefilter ─────────────────────────────────────────────────────────

def _make_vault_niche(niche_id: str, name: str, audience: str, category: str = "health") -> dict:
    return {
        "niche_id": niche_id,
        "niche_name": name,
        "audience_description": audience,
        "category": category,
        "status": "watching",
    }


class TestKeywordPrefilter:
    def test_empty_vault_returns_empty(self):
        new = {"niche_name": "Insomnia for Adults", "audience_description": "adults 50+"}
        assert keyword_prefilter(new, []) == []

    def test_returns_at_most_top_n(self):
        vault = [
            _make_vault_niche(f"n{i}", f"Niche {i}", f"audience for topic {i}")
            for i in range(50)
        ]
        new = {"niche_name": "Topic 1 Finance", "audience_description": "adults investors"}
        result = keyword_prefilter(new, vault, top_n=20)
        assert len(result) <= 20

    def test_ranks_similar_niche_higher(self):
        """Sleep-related vault niche should rank higher than unrelated one."""
        vault = [
            _make_vault_niche("sleep_old", "Sleep Difficulty Older Adults", "adults 60+ insomnia"),
            _make_vault_niche("finance_div", "Dividend Investing Retirees", "retired investors income"),
            _make_vault_niche("dog_train", "Dog Training Puppies", "new puppy owners"),
        ]
        new = {
            "niche_name": "Insomnia Solutions Adults 50+",
            "audience_description": "adults 50+ sleep problems",
            "category": "health",
        }
        result = keyword_prefilter(new, vault, top_n=20)
        # sleep_old should be first
        assert result[0]["niche_id"] == "sleep_old"

    def test_unrelated_niches_still_returned_within_top_n(self):
        """Unrelated niches may appear if vault is small — that's OK, LLM filters them."""
        vault = [
            _make_vault_niche("finance", "Stock Market Tips", "young investors 20s"),
        ]
        new = {
            "niche_name": "Belly Fat Loss Women 50+",
            "audience_description": "women 50 weight loss",
            "category": "health",
        }
        result = keyword_prefilter(new, vault, top_n=20)
        # Still returns it — Stage 2 LLM will correctly reject it
        assert len(result) == 1

    def test_semantic_synonym_surfaces_candidate(self):
        """'insomnia' and 'sleep difficulty' share 'sleep' → candidate surfaces."""
        vault = [
            _make_vault_niche("sleep", "Sleep Difficulty in Older Adults", "seniors sleep problems"),
            _make_vault_niche("dog", "Dog Grooming Tips", "dog owners"),
        ]
        new = {
            "niche_name": "Insomnia Remedies for Adults 50+",
            "audience_description": "adults with sleep insomnia issues",
            "category": "health",
        }
        result = keyword_prefilter(new, vault, top_n=20)
        ids = [n["niche_id"] for n in result]
        # "sleep" is shared token — sleep niche must surface
        assert "sleep" in ids

    def test_respects_top_n_parameter(self):
        vault = [
            _make_vault_niche(f"n{i}", f"Finance Investing Tips {i}", f"investors {i}")
            for i in range(100)
        ]
        new = {
            "niche_name": "Finance Investing Adults",
            "audience_description": "adult investors retirement",
            "category": "finance",
        }
        result = keyword_prefilter(new, vault, top_n=5)
        assert len(result) == 5

    def test_no_token_new_niche_returns_first_n(self):
        """New niche with no meaningful tokens → return first top_n as safety net."""
        vault = [_make_vault_niche(f"n{i}", "a to be", "a") for i in range(5)]
        new = {"niche_name": "a to", "audience_description": "the a", "category": ""}
        result = keyword_prefilter(new, vault, top_n=3)
        assert len(result) <= 3


# ── NicheDedupAgent ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    return AsyncMock(spec=LLMClient)


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="deepseek-flash",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0002,
        stop_reason="end_turn",
    )


class TestNicheDedupAgent:
    async def test_empty_vault_returns_unique(self, mock_llm):
        agent = NicheDedupAgent(llm=mock_llm)
        result = await agent.check_one(
            {"niche_id": "new", "niche_name": "Test"},
            [],
        )
        assert result["verdict"] == "unique"
        assert result["top_match_score"] == 0.0
        mock_llm.complete.assert_not_called()  # LLM not called for empty vault

    async def test_duplicate_verdict(self, mock_llm):
        mock_llm.complete.return_value = _llm_response(
            '{"results": [{"existing_niche_id": "sleep_old", "similarity_score": 0.92, '
            '"is_duplicate": true, "reason": "Same audience and topic"}], '
            '"verdict": "duplicate", "top_match_id": "sleep_old", "top_match_score": 0.92}'
        )
        agent = NicheDedupAgent(llm=mock_llm)
        vault = [_make_vault_niche("sleep_old", "Sleep Difficulty Older Adults", "seniors sleep")]
        new = {"niche_id": "insomnia_new", "niche_name": "Insomnia Adults 50+",
               "audience_description": "adults 50 sleep problems", "category": "health"}

        result = await agent.check_one(new, vault)
        assert result["verdict"] == "duplicate"
        assert result["top_match_score"] == pytest.approx(0.92)
        assert result["top_match_id"] == "sleep_old"

    async def test_unique_verdict(self, mock_llm):
        mock_llm.complete.return_value = _llm_response(
            '{"results": [{"existing_niche_id": "finance_n", "similarity_score": 0.12, '
            '"is_duplicate": false, "reason": "Different topic entirely"}], '
            '"verdict": "unique", "top_match_id": null, "top_match_score": 0.12}'
        )
        agent = NicheDedupAgent(llm=mock_llm)
        vault = [_make_vault_niche("finance_n", "Dividend Investing", "retiree investors",
                                   category="finance")]
        new = {"niche_id": "belly_fat", "niche_name": "Belly Fat Loss Women 50+",
               "audience_description": "women 50 weight loss", "category": "health"}

        result = await agent.check_one(new, vault)
        assert result["verdict"] == "unique"

    async def test_borderline_verdict(self, mock_llm):
        mock_llm.complete.return_value = _llm_response(
            '{"results": [{"existing_niche_id": "sleep_n", "similarity_score": 0.72, '
            '"is_duplicate": false, "reason": "Similar audience, different angle"}], '
            '"verdict": "borderline", "top_match_id": "sleep_n", "top_match_score": 0.72}'
        )
        agent = NicheDedupAgent(llm=mock_llm)
        vault = [_make_vault_niche("sleep_n", "Sleep Quality Adults", "adults sleep")]
        new = {"niche_id": "insomnia_n", "niche_name": "Insomnia Adults",
               "audience_description": "adults insomnia", "category": "health"}

        result = await agent.check_one(new, vault)
        assert result["verdict"] == "borderline"
        assert BORDERLINE_THRESHOLD <= result["top_match_score"] < DUPLICATE_THRESHOLD

    async def test_llm_parse_error_fails_open(self, mock_llm):
        """If LLM returns garbage, fail open (keep niche, don't crash)."""
        mock_llm.complete.return_value = _llm_response("not json at all")
        agent = NicheDedupAgent(llm=mock_llm)
        vault = [_make_vault_niche("n1", "Some Niche", "some audience")]
        new = {"niche_id": "new", "niche_name": "New Niche", "audience_description": "some"}

        result = await agent.check_one(new, vault)
        assert result["verdict"] == "unique"  # fail open

    async def test_prefilter_limits_llm_context(self, mock_llm):
        """LLM prompt must contain at most MAX_CANDIDATES niches, not all 200."""
        mock_llm.complete.return_value = _llm_response(
            '{"results": [], "verdict": "unique", "top_match_id": null, "top_match_score": 0.0}'
        )
        agent = NicheDedupAgent(llm=mock_llm)
        # 200 vault niches
        vault = [
            _make_vault_niche(f"n{i}", f"Niche {i} Finance Money", f"investors {i}")
            for i in range(200)
        ]
        new = {"niche_id": "new", "niche_name": "Dividend Investing Retirees",
               "audience_description": "retirees dividend income", "category": "finance"}

        await agent.check_one(new, vault)

        # Verify LLM was called with prompt containing <= MAX_CANDIDATES entries
        call_args = mock_llm.complete.call_args
        prompt_content = call_args.kwargs["messages"][0]["content"]
        # Count how many niche_id entries appear in prompt
        import re
        niche_ids_in_prompt = re.findall(r'"niche_id":', prompt_content)
        assert len(niche_ids_in_prompt) <= MAX_CANDIDATES

    async def test_returns_prefilter_stats(self, mock_llm):
        mock_llm.complete.return_value = _llm_response(
            '{"results": [], "verdict": "unique", "top_match_id": null, "top_match_score": 0.0}'
        )
        agent = NicheDedupAgent(llm=mock_llm)
        vault = [_make_vault_niche(f"n{i}", f"Niche {i}", f"audience {i}") for i in range(50)]
        new = {"niche_id": "new", "niche_name": "Test Finance", "audience_description": "adults"}

        result = await agent.check_one(new, vault)
        assert "prefilter_candidates" in result
        assert result["prefilter_candidates"] <= MAX_CANDIDATES
        assert result["vault_total"] == 50

    async def test_filter_niches_batch(self, mock_llm):
        """filter_niches processes multiple new niches, returns 3 groups."""
        def _resp(verdict: str, score: float) -> LLMResponse:
            return _llm_response(
                f'{{"results": [], "verdict": "{verdict}", '
                f'"top_match_id": null, "top_match_score": {score}}}'
            )

        call_count = 0
        scores = [0.92, 0.35, 0.70]  # duplicate, unique, borderline

        async def side_effect(**kwargs):
            nonlocal call_count
            s = scores[call_count % len(scores)]
            call_count += 1
            if s >= DUPLICATE_THRESHOLD:
                return _resp("duplicate", s)
            elif s >= BORDERLINE_THRESHOLD:
                return _resp("borderline", s)
            else:
                return _resp("unique", s)

        mock_llm.complete.side_effect = side_effect

        agent = NicheDedupAgent(llm=mock_llm)
        new_niches = [
            {"niche_id": f"new_{i}", "niche_name": f"Niche {i}", "audience_description": f"audience {i}"}
            for i in range(3)
        ]
        vault = [_make_vault_niche("existing", "Existing Niche", "existing audience")]

        kept, duplicates, borderline = await agent.filter_niches(new_niches, vault)

        assert len(duplicates) == 1
        assert len(kept) == 1
        assert len(borderline) == 1


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_thresholds_ordered(self):
        assert 0 < BORDERLINE_THRESHOLD < DUPLICATE_THRESHOLD <= 1.0

    def test_max_candidates_reasonable(self):
        assert 10 <= MAX_CANDIDATES <= 50
