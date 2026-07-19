"""Elo-based tournament ranking for script variants."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from omnicast.agents.critic import CriticAgent
from omnicast.models.script import (
    ScriptDraft, TopicBrief, TournamentMatch, EloRating,
)
from omnicast.shared.errors import AgentError

logger = structlog.get_logger()

K_FACTOR = 32


def calculate_elo(
    winner_rating: float,
    loser_rating: float,
    k: int = K_FACTOR,
) -> tuple[float, float]:
    """Calculate new Elo ratings after a match.

    Returns: (new_winner_rating, new_loser_rating)
    """
    expected_winner = 1.0 / (1.0 + 10 ** ((loser_rating - winner_rating) / 400))
    expected_loser = 1.0 - expected_winner

    new_winner = winner_rating + k * (1.0 - expected_winner)
    new_loser = loser_rating + k * (0.0 - expected_loser)

    return new_winner, new_loser


class Tournament:
    """Run pairwise tournament between script variants."""

    def __init__(self, critic: CriticAgent) -> None:
        self._critic = critic

    async def run(
        self,
        variants: list[ScriptDraft],
        brief: TopicBrief,
    ) -> tuple[list[EloRating], list[TournamentMatch]]:
        """Run round-robin tournament."""
        if len(variants) < 2:
            raise AgentError("Tournament requires at least 2 variants")

        # Initialize Elo ratings
        ratings = {v.variant_id: EloRating(variant_id=v.variant_id) for v in variants}
        matches = []

        # Round-robin: compare each pair
        for i in range(len(variants)):
            for j in range(i + 1, len(variants)):
                variant_a = variants[i]
                variant_b = variants[j]

                try:
                    winner_id = await self._critic.compare_variants(variant_a, variant_b, brief)
                except Exception as exc:
                    raise AgentError(f"Variant comparison failed: {exc}") from exc

                # Update Elo ratings
                rating_a = ratings[variant_a.variant_id]
                rating_b = ratings[variant_b.variant_id]

                if winner_id == variant_a.variant_id:
                    new_a, new_b = calculate_elo(rating_a.rating, rating_b.rating)
                    ratings[variant_a.variant_id] = EloRating(
                        variant_id=variant_a.variant_id,
                        rating=new_a,
                        matches_played=rating_a.matches_played + 1,
                    )
                    ratings[variant_b.variant_id] = EloRating(
                        variant_id=variant_b.variant_id,
                        rating=new_b,
                        matches_played=rating_b.matches_played + 1,
                    )
                else:
                    new_b, new_a = calculate_elo(rating_b.rating, rating_a.rating)
                    ratings[variant_b.variant_id] = EloRating(
                        variant_id=variant_b.variant_id,
                        rating=new_b,
                        matches_played=rating_b.matches_played + 1,
                    )
                    ratings[variant_a.variant_id] = EloRating(
                        variant_id=variant_a.variant_id,
                        rating=new_a,
                        matches_played=rating_a.matches_played + 1,
                    )

                matches.append(TournamentMatch(
                    variant_a=variant_a.variant_id,
                    variant_b=variant_b.variant_id,
                    winner=winner_id,
                    reason=f"Critic selected {winner_id}",
                ))

        # Sort ratings descending
        sorted_ratings = sorted(ratings.values(), key=lambda r: r.rating, reverse=True)
        return sorted_ratings, matches

    def get_winner(self, ratings: list[EloRating]) -> str:
        """Return variant_id with highest Elo."""
        if not ratings:
            raise AgentError("No ratings available")
        return ratings[0].variant_id
