"""Tests for Tournament and Elo rating."""

import pytest
from unittest.mock import AsyncMock

from omnicast.agents.tournament import Tournament, calculate_elo, K_FACTOR
from omnicast.agents.critic import CriticAgent
from omnicast.models.script import (
    ScriptDraft, TopicBrief, TournamentMatch, EloRating,
)
from omnicast.models.enums import Niche, Market, TopicSource
from omnicast.shared.errors import AgentError


class TestCalculateElo:
    def test_equal_ratings(self):
        new_w, new_l = calculate_elo(1000, 1000)
        assert new_w > 1000
        assert new_l < 1000
        assert new_w + new_l == pytest.approx(2000, abs=0.01)  # zero-sum

    def test_underdog_wins(self):
        new_w, new_l = calculate_elo(800, 1200)
        # Underdog wins more than expected
        gain = new_w - 800
        assert gain > K_FACTOR / 2  # gains more than half K

    def test_favorite_wins(self):
        new_w, new_l = calculate_elo(1200, 800)
        gain = new_w - 1200
        assert gain < K_FACTOR / 2  # gains less than half K

    def test_k_factor_applied(self):
        new_w, _ = calculate_elo(1000, 1000, k=16)
        assert new_w == pytest.approx(1008, abs=0.1)  # K/2 for equal ratings


class TestTournament:
    @pytest.fixture
    def mock_critic(self) -> AsyncMock:
        return AsyncMock(spec=CriticAgent)

    @pytest.fixture
    def variants(self) -> list[ScriptDraft]:
        return [
            ScriptDraft(variant_id="A", brief_title="T", hook="Hook A",
                        word_count=1500, estimated_duration_seconds=600),
            ScriptDraft(variant_id="B", brief_title="T", hook="Hook B",
                        word_count=1400, estimated_duration_seconds=550),
            ScriptDraft(variant_id="C", brief_title="T", hook="Hook C",
                        word_count=1600, estimated_duration_seconds=650),
        ]

    @pytest.fixture
    def brief(self) -> TopicBrief:
        return TopicBrief(
            title="Test", niche=Niche.TECH, market=Market.US,
            source=TopicSource.MANUAL,
        )

    async def test_run_round_robin(self, mock_critic, variants, brief):
        # A beats B, B beats C, A beats C
        mock_critic.compare_variants.side_effect = ["A", "B", "A"]
        tournament = Tournament(critic=mock_critic)
        ratings, matches = await tournament.run(variants, brief)
        assert len(ratings) == 3
        assert len(matches) == 3  # 3 choose 2 pairs
        assert all(isinstance(r, EloRating) for r in ratings)
        assert all(isinstance(m, TournamentMatch) for m in matches)

    async def test_winner_has_highest_elo(self, mock_critic, variants, brief):
        mock_critic.compare_variants.side_effect = ["A", "A", "B"]
        tournament = Tournament(critic=mock_critic)
        ratings, _ = await tournament.run(variants, brief)
        winner = tournament.get_winner(ratings)
        assert winner == "A"  # A won 2 matches

    async def test_too_few_variants(self, mock_critic, brief):
        single = [ScriptDraft(variant_id="A", brief_title="T", hook="H")]
        tournament = Tournament(critic=mock_critic)
        with pytest.raises(AgentError, match="at least 2"):
            await tournament.run(single, brief)

    async def test_ratings_sorted_descending(self, mock_critic, variants, brief):
        mock_critic.compare_variants.side_effect = ["B", "C", "C"]
        tournament = Tournament(critic=mock_critic)
        ratings, _ = await tournament.run(variants, brief)
        assert ratings[0].rating >= ratings[1].rating >= ratings[2].rating

    async def test_matches_record_reason(self, mock_critic, variants, brief):
        mock_critic.compare_variants.return_value = "A"
        tournament = Tournament(critic=mock_critic)
        _, matches = await tournament.run(variants[:2], brief)
        assert len(matches) == 1
        assert matches[0].winner == "A"
