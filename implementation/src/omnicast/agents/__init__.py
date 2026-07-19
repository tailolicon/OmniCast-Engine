"""Agents module for OmniCast Engine."""

from omnicast.agents.base import BaseAgent
from omnicast.agents.writer import WriterAgent
from omnicast.agents.critic import CriticAgent
from omnicast.agents.thinking import ThinkingAgent
from omnicast.agents.compliance import ComplianceChecker
from omnicast.agents.orchestrator import DebateOrchestrator, DebateConfig, DebateResult
from omnicast.agents.tournament import Tournament, calculate_elo
from omnicast.agents.evolution import EvolutionAgent
from omnicast.agents.evals import run_binary_evals, WRITER_EVALS

__all__ = [
    "BaseAgent",
    "WriterAgent",
    "CriticAgent",
    "ThinkingAgent",
    "ComplianceChecker",
    "DebateOrchestrator",
    "DebateConfig",
    "DebateResult",
    "Tournament",
    "calculate_elo",
    "EvolutionAgent",
    "run_binary_evals",
    "WRITER_EVALS",
]
