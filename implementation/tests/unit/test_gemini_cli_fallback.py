"""Gemini CLI as the independent judge fallback (operator's Google account).

In claude_only mode every judge shares one Anthropic account; runs aborted live
with "no independent fallback configured". A different company is a genuinely
different failure domain — these tests pin the wiring and the client contract."""

from __future__ import annotations

import subprocess
import types

import pytest

from omnicast.llm.gemini_cli import GeminiCLIClient


def _fake_run(stdout: str, rc: int = 0, stderr: str = ""):
    def run(cmd, **kwargs):
        return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)
    return run


@pytest.mark.asyncio
async def test_complete_returns_stdout_and_zero_cost(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:/npm/gemini.cmd")
    monkeypatch.setattr(subprocess, "run", _fake_run('{"approved": true}'))
    client = GeminiCLIClient(model="gemini-2.5-pro", role="judge_fallback")
    resp = await client.complete(system="sys", messages=[{"role": "user", "content": "u"}])
    assert resp.content == '{"approved": true}'
    assert resp.cost_usd == 0.0


@pytest.mark.asyncio
async def test_structured_parses_object_even_with_preamble(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:/npm/gemini.cmd")
    monkeypatch.setattr(
        subprocess, "run",
        _fake_run('Here is the verdict:\n{"issues": [], "summary": "clean"}'),
    )
    from omnicast.agents.narrative_pipeline import PlanPlausibilityReview

    client = GeminiCLIClient()
    _, parsed = await client.complete_structured(
        system="s", messages=[{"role": "user", "content": "u"}],
        output_schema=PlanPlausibilityReview,
    )
    assert parsed.issues == []


@pytest.mark.asyncio
async def test_auth_failure_raises_immediately_without_retry(monkeypatch):
    calls = {"n": 0}

    def run(cmd, **kwargs):
        calls["n"] += 1
        return types.SimpleNamespace(
            stdout="", returncode=1,
            stderr="Please set an Auth method ... GEMINI_API_KEY",
        )

    monkeypatch.setattr("shutil.which", lambda name: "C:/npm/gemini.cmd")
    monkeypatch.setattr(subprocess, "run", run)
    client = GeminiCLIClient()
    with pytest.raises(RuntimeError):
        await client.complete(system="", messages=[{"role": "user", "content": "u"}])
    assert calls["n"] == 1  # login problems never fix themselves mid-run


def test_health_bookkeeping_sees_a_different_provider():
    client = GeminiCLIClient()
    # The pipeline's health identity reads `_provider`/`_model` attributes; a
    # fallback only counts as independent when the provider string differs.
    assert client._provider == "google"
    assert client._model.startswith("gemini")


def test_claude_only_roles_use_gemini_for_the_three_stranded_fallbacks(monkeypatch):
    from omnicast.pipeline.steps import _narrative_role_clients

    class _Settings:
        claude_model = "claude-sonnet-5"

    monkeypatch.setenv("OMNICAST_NARRATIVE_CLAUDE_ONLY", "1")
    monkeypatch.setenv("OMNICAST_NARRATIVE_GEMINI_FALLBACK", "1")
    roles = _narrative_role_clients(
        _Settings(),
        client_factory=lambda *a, **k: types.SimpleNamespace(
            _provider="anthropic", _model=k.get("model", ""),
        ),
    )
    for slot in ("critic_fallback", "compliance_escalation", "annotation_fallback"):
        assert isinstance(roles[slot], GeminiCLIClient), slot
    assert "judge_fallback" in roles["model_roles"]
    assert "google" in roles["model_roles"]["judge_fallback"]


def test_gemini_fallback_defaults_off(monkeypatch):
    from omnicast.pipeline.steps import _narrative_role_clients

    class _Settings:
        claude_model = "claude-sonnet-5"

    monkeypatch.setenv("OMNICAST_NARRATIVE_CLAUDE_ONLY", "1")
    monkeypatch.delenv("OMNICAST_NARRATIVE_GEMINI_FALLBACK", raising=False)
    roles = _narrative_role_clients(
        _Settings(),
        client_factory=lambda *a, **k: types.SimpleNamespace(
            _provider="anthropic", _model=k.get("model", ""),
        ),
    )
    assert roles["critic_fallback"] is None
