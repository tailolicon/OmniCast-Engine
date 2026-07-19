"""Temporary claude_only routing while the DeepSeek quota is exhausted.

Operator-confirmed 2026-07-17: DeepSeek quota is gone. OMNICAST_NARRATIVE_CLAUDE_ONLY=1
makes the unit_first flow issue ZERO DeepSeek calls — not a health probe, not a first
primary attempt — by never handing the pipeline a DeepSeek client at all. A call that
cannot be reached cannot be made, which is a stronger guarantee than a fallback that
fires after the first 402.

The switch is temporary and reversible: unset restores DeepSeek-first with no code
change. Nothing here weakens a release gate; the gates read resolved client identity,
not the mode label.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from omnicast.pipeline.steps import _narrative_role_clients, _runtime_flag


_MANDATORY_ROLES = ("planner", "writer", "critic", "plan_audit", "compliance",
                    "annotation", "challenger", "plan_audit_escalation")


class _FakeClient:
    """Stands in for LLMClient with the attributes identity/health read."""

    def __init__(self, provider, model, cli_effort, role):
        self._provider = provider
        self._model = model
        self._effort = cli_effort
        self._role = role

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self._provider}/{self._model} effort={self._effort} role={self._role}>"


class _DeepSeekClient:
    """A DeepSeek client that fails loudly if the flow so much as calls it."""

    def __init__(self, model):
        self._provider = "deepseek"
        self._model = model

    async def complete(self, **kwargs):
        raise AssertionError("a DeepSeek call was made under claude_only")

    async def complete_structured(self, **kwargs):
        raise AssertionError("a DeepSeek call was made under claude_only")


def _factory(provider, *, model=None, db_path=None, cli_effort=None, role=""):
    return _FakeClient(provider, model, cli_effort, role)


def _settings(**overrides):
    base = {
        "claude_model": "claude-sonnet-5",
        "omnicast_narrative_claude_only": "",
        "omnicast_narrative_max_quality": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _resolve(settings, monkeypatch, **env):
    for name in (
        "OMNICAST_NARRATIVE_CLAUDE_ONLY", "OMNICAST_NARRATIVE_MAX_QUALITY",
        "OMNICAST_NARRATIVE_PLANNER_MODEL", "OMNICAST_NARRATIVE_WRITER_MODEL",
        "OMNICAST_NARRATIVE_JUDGE_FALLBACK_MODEL",
        "OMNICAST_NARRATIVE_CHALLENGER_MODEL", "OMNICAST_NARRATIVE_ANNOTATION_MODEL",
        "OMNICAST_NARRATIVE_PLANNER_EFFORT", "OMNICAST_NARRATIVE_JUDGE_EFFORT",
        "OMNICAST_NARRATIVE_WRITER_EFFORT", "OMNICAST_NARRATIVE_CHALLENGER_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return _narrative_role_clients(
        settings,
        deepseek_pro=_DeepSeekClient("deepseek-v4-pro"),
        deepseek_flash=_DeepSeekClient("deepseek-v4-flash"),
        client_factory=_factory,
    )


# ---------------------------------------------------------------------------
# 1. The switch reads .env, not only os.environ.


def test_the_switch_is_read_from_settings_not_only_the_environment(monkeypatch):
    """pydantic-settings reads implementation/.env into the Settings MODEL and does
    NOT populate os.environ; only the API-server path calls load_dotenv. An
    os.environ-only read would make a .env switch silently inert on a CLI run."""
    monkeypatch.delenv("OMNICAST_NARRATIVE_CLAUDE_ONLY", raising=False)
    assert _runtime_flag(
        "OMNICAST_NARRATIVE_CLAUDE_ONLY", "omnicast_narrative_claude_only",
        _settings(omnicast_narrative_claude_only="1"),
    ) is True


def test_the_environment_overrides_settings_for_one_run(monkeypatch):
    monkeypatch.setenv("OMNICAST_NARRATIVE_CLAUDE_ONLY", "1")
    assert _runtime_flag(
        "OMNICAST_NARRATIVE_CLAUDE_ONLY", "omnicast_narrative_claude_only", _settings(),
    ) is True


@pytest.mark.parametrize("raw", ["", "0", "false", "no", "off"])
def test_falsey_values_leave_the_switch_off(monkeypatch, raw):
    monkeypatch.delenv("OMNICAST_NARRATIVE_CLAUDE_ONLY", raising=False)
    assert _runtime_flag(
        "OMNICAST_NARRATIVE_CLAUDE_ONLY", "omnicast_narrative_claude_only",
        _settings(omnicast_narrative_claude_only=raw),
    ) is False


# ---------------------------------------------------------------------------
# 2. claude_only: no DeepSeek client reaches the pipeline at all.


def test_claude_only_passes_a_claude_client_into_every_mandatory_role(monkeypatch):
    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_CLAUDE_ONLY="1")

    assert roles["judge_mode"] == "claude_only"
    for name in _MANDATORY_ROLES:
        client = roles[name]
        assert client is not None, f"{name} has no client"
        assert client._provider == "anthropic", f"{name} is not on Claude"


def test_claude_only_never_hands_the_flow_a_deepseek_client(monkeypatch):
    """The strongest form of 'zero DeepSeek calls': the object is not reachable.
    Every _DeepSeekClient method raises, so any later call would fail loudly."""
    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_CLAUDE_ONLY="1")

    clients = [v for k, v in roles.items()
               if k not in {"judge_mode", "model_roles", "max_quality"} and v is not None]
    assert clients, "sanity: roles were resolved"
    assert not any(isinstance(c, _DeepSeekClient) for c in clients)
    assert not any(getattr(c, "_provider", "") == "deepseek" for c in clients)
    assert "deepseek" not in str(roles["model_roles"]).lower()


def test_claude_only_offers_no_same_domain_fallback(monkeypatch):
    """Within one Anthropic subscription a model swap is not a fallback: one quota,
    one health domain. Offering one would only buy a pointless retry against the
    same dead domain, so the honest encoding is None — and if Claude itself dies
    the run aborts fail-closed, which is correct."""
    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_CLAUDE_ONLY="1")

    assert roles["critic_fallback"] is None
    assert roles["compliance_escalation"] is None
    assert roles["annotation_fallback"] is None


def test_claude_only_keeps_an_escalation_on_a_different_model(monkeypatch):
    """The plan-audit escalation must not be the same client as the primary, or
    _audit_plan refuses to escalate. A different model is a different reader; it is
    not a different account, and the health domain still knows that."""
    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_CLAUDE_ONLY="1")

    assert roles["plan_audit_escalation"]._model != roles["critic"]._model


# ---------------------------------------------------------------------------
# 3. Per-role models and efforts.


def test_max_quality_keeps_the_writer_and_challenger_on_opus_at_max_effort(monkeypatch):
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    for name in ("writer", "challenger"):
        assert roles[name]._model == "claude-opus-4-8", name
        assert roles[name]._effort == "max", name


def test_max_quality_puts_the_planner_on_opus(monkeypatch):
    """Live 2026-07-17 16:03: a Sonnet/medium planner produced premises the auditor
    correctly killed on trade reasoning — a locksmith trapped by a door he had just
    keyed; an apprentice returning alone to a stalker a third night. Those are
    judgement failures, and the plan is the cheapest place in the run to buy
    judgement: one call decides whether three writer calls are worth making.

    'high', not 'max': the failures were reasoning-quality, which the model change
    addresses, and nothing measures max as better here — while the 14:32 run
    measured exactly what plan-stage depth costs (31 minutes, no prose)."""
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    assert roles["planner"]._model == "claude-opus-4-8"
    assert roles["planner"]._effort == "high"


def test_without_max_quality_the_planner_stays_on_the_cheaper_default(monkeypatch):
    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_CLAUDE_ONLY="1")
    assert roles["planner"]._model == "claude-sonnet-5"
    assert roles["planner"]._effort == "medium"


def test_a_per_role_override_still_wins_over_max_quality(monkeypatch):
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
        OMNICAST_NARRATIVE_PLANNER_MODEL="claude-sonnet-5",
        OMNICAST_NARRATIVE_PLANNER_EFFORT="low",
    )
    assert roles["planner"]._model == "claude-sonnet-5"
    assert roles["planner"]._effort == "low"


def test_the_planner_and_the_plan_auditor_stay_different_readers(monkeypatch):
    """The auditor exists to disagree with the planner. Opus planning judged by
    Sonnet is two readers; the same client twice would be one."""
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    assert roles["plan_audit"]._model == "claude-sonnet-5"
    assert roles["plan_audit"]._effort == "medium"
    assert roles["plan_audit"]._model != roles["planner"]._model


def test_plan_audit_is_labelled_as_itself_not_as_the_critic(monkeypatch):
    """The 16:03 log had to be read by inferring the stage: an audit call logged
    role=critic_score because it borrowed the critic's client."""
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    assert roles["plan_audit"]._role == "plan_audit"
    assert roles["critic"]._role == "critic_score"
    # Distinguishable in the artifact too, without claiming they are different models.
    reported = roles["model_roles"]
    assert reported["plan_audit"] == reported["critic_score"]
    # Cost routing: plan repairs and surgical patches run on the cheap tier —
    # every repair is re-validated by preflight + the semantic audit, so the
    # quality floor lives in the checkers, not the repairer.
    assert reported["plan_repair"] == "claude-sonnet-5/medium"
    assert reported["repair_writer"] == "claude-sonnet-5/medium"


def test_judges_and_annotation_are_sonnet_at_medium_effort(monkeypatch):
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    for name in ("critic", "plan_audit", "compliance", "annotation"):
        assert roles[name]._model == "claude-sonnet-5", name
        assert roles[name]._effort == "medium", name


def test_the_challenger_model_differs_from_every_judge_model(monkeypatch):
    """The independent-challenger release rule survives claude_only: Opus over
    Sonnet judges is a real second reader, and identity is resolved, not named."""
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    judges = {roles[name]._model for name in ("critic", "compliance")}
    assert roles["challenger"]._model not in judges


def test_model_roles_report_the_actual_model_and_effort(monkeypatch):
    roles = _resolve(
        _settings(), monkeypatch,
        OMNICAST_NARRATIVE_CLAUDE_ONLY="1", OMNICAST_NARRATIVE_MAX_QUALITY="1",
    )
    reported = roles["model_roles"]
    assert reported["writer"] == "claude-opus-4-8/max"
    assert reported["release_challenger"] == "claude-opus-4-8/max"
    assert reported["planner"] == "claude-opus-4-8/high"
    assert reported["critic_score"] == "claude-sonnet-5/medium"
    assert reported["story_compliance"] == "claude-sonnet-5/medium"
    assert reported["annotation"] == "claude-sonnet-5/medium"


# ---------------------------------------------------------------------------
# 4. Unset preserves the previous routing, so DeepSeek can be restored later.


def test_the_switch_unset_preserves_deepseek_first_routing(monkeypatch):
    roles = _resolve(_settings(), monkeypatch)

    assert roles["judge_mode"] == "deepseek_first"
    assert isinstance(roles["critic"], _DeepSeekClient)
    assert isinstance(roles["compliance"], _DeepSeekClient)
    assert isinstance(roles["annotation"], _DeepSeekClient)
    assert roles["critic"]._model == "deepseek-v4-pro"
    assert roles["compliance"]._model == "deepseek-v4-flash"


def test_the_switch_unset_keeps_the_sonnet_fallbacks(monkeypatch):
    roles = _resolve(_settings(), monkeypatch)

    for name in ("critic_fallback", "compliance_escalation", "plan_audit_escalation"):
        assert roles[name]._provider == "anthropic", name
        assert roles[name]._model == "claude-sonnet-5", name
    # Still NOT deepseek-v4-pro: same account as the primary, one balance, one
    # outage. A fallback that dies with its primary is not a fallback.
    assert roles["compliance_escalation"]._provider != "deepseek"


def test_the_switch_unset_still_writes_and_challenges_on_claude(monkeypatch):
    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_MAX_QUALITY="1")
    assert roles["writer"]._provider == "anthropic"
    assert roles["challenger"]._model == "claude-opus-4-8"


# ---------------------------------------------------------------------------
# 5. The mode is descriptive; the gates are not weakened by it.


def test_the_pipeline_records_the_mode_without_letting_it_decide_anything(monkeypatch):
    """judge_mode is the caller's account of the wiring, for the artifact. Every
    gate reads resolved client identity, which cannot be misdescribed by a label."""
    from omnicast.agents.narrative_pipeline import NarrativeUnitPipeline

    sonnet = _FakeClient("anthropic", "claude-sonnet-5", "medium", "critic_score")
    opus = _FakeClient("anthropic", "claude-opus-4-8", "max", "release_challenger")
    pipe = NarrativeUnitPipeline(
        planner_llm=sonnet, writer_llm=opus, critic_llm=sonnet, annotation_llm=sonnet,
        compliance_llm=sonnet, release_challenger_llm=opus,
        judge_mode="claude_only", model_roles={"writer": "claude-opus-4-8/max"},
    )
    assert pipe.judge_mode == "claude_only"
    # A lying label cannot make a same-model challenger independent.
    assert pipe._is_independent_of(opus, sonnet) is True
    assert pipe._is_independent_of(sonnet, sonnet) is False
    # One Anthropic subscription is ONE health domain regardless of model.
    assert pipe._health_domain(sonnet) == pipe._health_domain(opus)


def test_claude_only_roles_share_one_health_domain(monkeypatch):
    """Which is why there is no same-domain fallback: if the subscription dies,
    every role dies with it and the run must abort rather than loop."""
    from omnicast.agents.narrative_pipeline import NarrativeUnitPipeline

    roles = _resolve(_settings(), monkeypatch, OMNICAST_NARRATIVE_CLAUDE_ONLY="1")
    domains = {
        NarrativeUnitPipeline._health_domain(roles[name]) for name in _MANDATORY_ROLES
    }
    assert domains == {("provider", "anthropic")}
