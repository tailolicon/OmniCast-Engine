"""Stage-specific effort and role labelling for the Claude CLI delegate.

Live 2026-07-17 14:32 (max-quality fallback run, manually stopped after ~31 minutes
with ZERO writer calls): a Sonnet *planner* call took 7 minutes and burned 11,924
output tokens; a Sonnet *re-audit* took 6 minutes. The CLI was invoked with no
``--effort``, so every stage — including cheap structured planning and auditing —
ran at the CLI's default reasoning depth. Effort is a property of the ROLE, not of
the model, and the pipeline knows the role at the call site.

The log also had to be read by inferring stage from timestamps, which is why the
role label travels with the client and lands in the completion log.
"""

from __future__ import annotations

import json

import pytest

import omnicast.llm.claude_cli as cli
from omnicast.llm import LLMResponse
from omnicast.llm.claude_cli import (
    CLI_EFFORT_LEVELS,
    ClaudeCLIClient,
    ClaudeCLIDeterministic,
    ClaudeCLITransient,
    _classify_result,
)
from omnicast.llm.client import LLMClient


# ---------------------------------------------------------------------------
# 1. Effort is validated locally, because the CLI will not do it for us.


def test_the_allowed_levels_match_the_installed_cli():
    # `claude --help`: "Effort level for the current session (low, medium, high,
    # xhigh, max)".
    assert CLI_EFFORT_LEVELS == ("low", "medium", "high", "xhigh", "max")


@pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
def test_every_supported_level_is_accepted(level):
    assert ClaudeCLIClient(model="claude-sonnet-5", effort=level)._effort == level


def test_an_unsupported_level_is_rejected_at_construction():
    """The CLI answers an unknown --effort with a WARNING on stdout and silently
    uses its default. A typo would therefore buy the 7-minute planner back with no
    error anywhere, so it has to fail here."""
    with pytest.raises(ValueError, match="effort"):
        ClaudeCLIClient(model="claude-sonnet-5", effort="medium-high")
    with pytest.raises(ValueError, match="effort"):
        ClaudeCLIClient(model="claude-sonnet-5", effort="MAX")


def test_effort_is_optional_and_absent_by_default():
    """Every non-unit flow constructs this client without an effort and must keep
    its exact prior command line."""
    assert ClaudeCLIClient(model="claude-sonnet-5")._effort is None


# ---------------------------------------------------------------------------
# 2. Command construction. No shell integration: inspect the argv we would run.


def _argv(**kwargs) -> list[str]:
    return ClaudeCLIClient(model="claude-sonnet-5", **kwargs)._build_command("/exe/claude")


def test_effort_reaches_the_command_line():
    argv = _argv(effort="medium")
    assert "--effort" in argv
    assert argv[argv.index("--effort") + 1] == "medium"


def test_omitting_effort_omits_the_flag_entirely():
    assert "--effort" not in _argv()


def test_the_rest_of_the_command_is_unchanged_by_effort():
    """A flag that shifts argv order would break the callers this must not touch."""
    base = _argv()
    with_effort = _argv(effort="low")
    assert [item for item in with_effort if item not in ("--effort", "low")] == base


def test_model_is_still_pinned_per_client():
    argv = ClaudeCLIClient(model="claude-opus-5", effort="max")._build_command("/exe/claude")
    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[argv.index("--effort") + 1] == "max"


# ---------------------------------------------------------------------------
# 3. Role labelling: the 14:32 log forced stage inference from timestamps.


# ---------------------------------------------------------------------------
# 2b. Tools are OFF. This is an LLM-as-text-client, not an agent.
#
# Live 2026-07-17 15:36 (claude_only run, stopped by hand ~15:48): every
# targeted plan-repair call returned subtype=error_max_turns / num_turns=2.
# --strict-mcp-config disables MCP servers ONLY and leaves Claude Code's
# built-in tools and skills available; Sonnet chose a tool, spent the single
# allowed turn on it, and the client retried the identical failure. Verified
# against the real CLI: without these flags the probe returns
# error_max_turns/num_turns=2; with them, success/num_turns=1.


def test_built_in_tools_are_explicitly_disabled():
    argv = _argv()
    assert "--tools" in argv, "strict-mcp-config does not disable built-in tools"
    assert argv[argv.index("--tools") + 1] == "", '`--tools ""` disables all tools'


def test_skills_are_explicitly_disabled():
    assert "--disable-slash-commands" in _argv()


def test_the_empty_tools_argument_survives_windows_argv_quoting():
    """A list-form argv element is what actually reaches CreateProcess; an empty
    string must render as "" rather than vanish."""
    import subprocess

    argv = _argv()
    i = argv.index("--tools")
    rendered = subprocess.list2cmdline(argv[i:i + 2])
    assert rendered == '--tools ""'


def test_max_turns_stays_at_one():
    """One turn is all a text completion needs once tools are truly gone. Raising
    it would only buy room for the agent behaviour this call must not have."""
    argv = _argv()
    assert argv[argv.index("--max-turns") + 1] == "1"


def test_mcp_is_still_locked_down():
    argv = _argv()
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'


# ---------------------------------------------------------------------------
# 2c. Retry classification: retry only what a retry can fix.


@pytest.mark.parametrize("subtype,text,expected", [
    ("error_max_turns", "", "deterministic"),          # the 15:36 failure
    ("error", "Invalid model name", "deterministic"),
    ("error", "permission denied", "deterministic"),
    ("error", "something nobody has classified yet", "deterministic"),
    ("error", "rate limit exceeded", "transient"),
    ("error", "Error 429: too many requests", "transient"),
    ("error", "service temporarily unavailable", "transient"),
    ("error", "API Error 401 Unauthorized", "auth"),
])
def test_result_classification(subtype, text, expected):
    assert _classify_result(subtype, text) == expected


def _fake_proc(stdout: str, stderr: str = "", rc: int = 0):
    class _P:
        pass
    p = _P()
    p.stdout, p.stderr, p.returncode = stdout, stderr, rc
    return p


def _result_json(**kw) -> str:
    payload = {"type": "result", "result": "ok", "usage": {}, "total_cost_usd": 0.0}
    payload.update(kw)
    return json.dumps(payload)


@pytest.fixture
def _spy(monkeypatch, tmp_path):
    """Count subprocess calls and sleeps without running a CLI or waiting."""
    calls, sleeps = [], []

    async def _no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(cli.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(cli.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(cli, "_sync_credentials", lambda force=False: None)
    monkeypatch.setattr(cli, "_sync_credentials_back", lambda: None)
    monkeypatch.setattr(cli, "_clean_env", lambda: {})
    return calls, sleeps


@pytest.mark.asyncio
async def test_max_turns_reached_fails_after_exactly_one_subprocess_call(_spy, monkeypatch):
    """The 15:36 loop: four calls and ~6 minutes of sleeps re-asking a settled
    question. A deterministic failure must cost one call and zero waiting."""
    calls, sleeps = _spy
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc(_result_json(is_error=True, subtype="error_max_turns",
                                                 result=None)))[1])

    with pytest.raises(ClaudeCLIDeterministic, match="max_turns"):
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])

    assert len(calls) == 1, "a settled failure was re-asked"
    assert sleeps == [], "no waiting for a result that cannot change"


@pytest.mark.asyncio
async def test_the_max_turns_message_names_the_actual_cause(_spy, monkeypatch):
    calls, _sleeps = _spy
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc(_result_json(is_error=True, subtype="error_max_turns",
                                                 result=None)))[1])
    with pytest.raises(ClaudeCLIDeterministic) as excinfo:
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])
    assert "--tools" in str(excinfo.value)
    assert "tool call" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_unknown_error_fails_fast_and_carries_its_message(_spy, monkeypatch):
    calls, sleeps = _spy
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc(_result_json(is_error=True, subtype="error",
                                                 result="a brand new failure")))[1])
    with pytest.raises(ClaudeCLIDeterministic, match="a brand new failure"):
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_bad_arguments_fail_fast_rather_than_waiting_out_a_throttle(_spy, monkeypatch):
    """Empty stdout is the same symptom for a bad flag and a throttle. stderr is
    what tells them apart, so it is read before deciding to wait 20 seconds."""
    calls, sleeps = _spy
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc("", stderr="error: unknown option '--nope'", rc=1))[1])
    with pytest.raises(ClaudeCLIDeterministic, match="rejected its arguments"):
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_and_bounded(_spy, monkeypatch):
    """A subscription throttle returning empty stdout was measured live; losing a
    15-minute run to one blip is worse than one wasted retry."""
    calls, sleeps = _spy
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc("", stderr="", rc=0))[1])

    with pytest.raises(ClaudeCLITransient):
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])

    assert len(calls) == cli._MAX_ATTEMPTS, "bounded, and it did use its retries"
    # Three waits for four tries: never a wait after the last one.
    assert len(sleeps) == cli._MAX_ATTEMPTS - 1
    assert sleeps == [20, 40, 60]


@pytest.mark.asyncio
async def test_a_transient_failure_that_clears_succeeds(_spy, monkeypatch):
    calls, sleeps = _spy
    outputs = ["", _result_json(is_error=False, result="recovered")]

    def _run(*a, **k):
        calls.append(1)
        return _fake_proc(outputs[min(len(calls) - 1, len(outputs) - 1)])

    monkeypatch.setattr(cli.subprocess, "run", _run)
    response = await ClaudeCLIClient(model="claude-sonnet-5").complete(
        system="", messages=[]
    )
    assert response.content == "recovered"
    assert len(calls) == 2
    assert sleeps == [20], "one wait, then success"


@pytest.mark.asyncio
async def test_an_auth_error_resyncs_and_does_not_sleep_after_the_last_try(_spy, monkeypatch):
    calls, sleeps = _spy
    resyncs = []
    monkeypatch.setattr(cli, "_sync_credentials",
                        lambda force=False: resyncs.append(force))
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc(_result_json(is_error=True, subtype="error",
                                                 result="API Error 401")))[1])

    with pytest.raises(ClaudeCLITransient):
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])

    assert len(calls) == cli._MAX_ATTEMPTS
    assert any(resyncs), "a stale copied token is resynced before retrying"
    assert len(sleeps) == cli._MAX_ATTEMPTS - 1, "no pointless final wait"


@pytest.mark.asyncio
async def test_credential_sync_back_still_runs_on_a_deterministic_failure(_spy, monkeypatch):
    """A token the CLI just rotated must survive even a failed call, or the whole
    machine loses auth until a manual re-login."""
    calls, _sleeps = _spy
    synced = []
    monkeypatch.setattr(cli, "_sync_credentials_back", lambda: synced.append(True))
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (
        calls.append(1), _fake_proc(_result_json(is_error=True, subtype="error_max_turns",
                                                 result=None)))[1])
    with pytest.raises(ClaudeCLIDeterministic):
        await ClaudeCLIClient(model="claude-sonnet-5").complete(system="", messages=[])
    assert synced == [True]


def test_role_is_carried_on_the_client_and_defaults_to_empty():
    assert ClaudeCLIClient(model="claude-sonnet-5", role="planner")._role == "planner"
    assert ClaudeCLIClient(model="claude-sonnet-5")._role == ""


def test_the_response_carries_role_effort_and_notional_cost():
    """Notional subscription cost is reported separately from marginal cost, which
    stays 0.0: a subscription call is not billed per token, and polluting the
    ledger with a notional figure would make budgets lie in the other direction."""
    response = LLMResponse(
        content="{}", model="claude-sonnet-5", input_tokens=1, output_tokens=2,
        cost_usd=0.0, stop_reason="end_turn",
        notional_cost_usd=0.1909, role="planner", effort="medium",
    )
    assert response.cost_usd == 0.0
    assert response.notional_cost_usd == 0.1909
    assert response.role == "planner"
    assert response.effort == "medium"


def test_llm_response_stays_constructible_without_the_new_fields():
    """Every existing call site builds this positionally or by keyword without
    them; they must remain optional."""
    response = LLMResponse(
        content="x", model="m", input_tokens=1, output_tokens=1,
        cost_usd=0.5, stop_reason="stop",
    )
    assert response.notional_cost_usd == 0.0
    assert response.role == "" and response.effort == ""


# ---------------------------------------------------------------------------
# 4. LLMClient plumbs the options through without touching other providers.


def test_llm_client_passes_effort_and_role_to_the_cli_delegate(monkeypatch):
    monkeypatch.setenv("OMNICAST_CLAUDE_BACKEND", "cli")
    client = LLMClient(
        provider="anthropic", model="claude-opus-5",
        cli_effort="max", role="writer",
    )
    assert isinstance(client._delegate, ClaudeCLIClient)
    assert client._delegate._effort == "max"
    assert client._delegate._role == "writer"
    assert client._role == "writer"
    assert client._cli_effort == "max"


def test_llm_client_rejects_a_bad_effort_before_any_call(monkeypatch):
    monkeypatch.setenv("OMNICAST_CLAUDE_BACKEND", "cli")
    with pytest.raises(ValueError, match="effort"):
        LLMClient(provider="anthropic", model="claude-sonnet-5", cli_effort="huge")


def test_effort_on_a_non_cli_provider_is_inert(monkeypatch):
    """DeepSeek has no --effort. Passing one must not crash or leak into its
    backend; the option is Claude-CLI-specific by construction."""
    monkeypatch.delenv("OMNICAST_CLAUDE_BACKEND", raising=False)
    client = LLMClient(provider="deepseek", model="deepseek-v4-pro", cli_effort="max")
    assert not isinstance(client._delegate, ClaudeCLIClient)
    assert client._cli_effort == "max"


def test_options_are_immutable_per_client(monkeypatch):
    """Effort is set once per role-client and never mutated per call, so two
    channels sharing a process cannot race each other's reasoning depth — the
    reason this is not an env var."""
    monkeypatch.setenv("OMNICAST_CLAUDE_BACKEND", "cli")
    planner = LLMClient(provider="anthropic", model="claude-sonnet-5",
                        cli_effort="medium", role="planner")
    writer = LLMClient(provider="anthropic", model="claude-opus-5",
                       cli_effort="max", role="writer")
    assert planner._delegate._effort == "medium"
    assert writer._delegate._effort == "max"
    assert planner._delegate._model != writer._delegate._model
