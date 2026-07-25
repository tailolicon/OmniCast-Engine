"""One component decides what gets made (SSOT resolution).

The defect: `DiscoveryOrchestrator` → `BriefGenerator` briefed only topics the
scorer marked `approve`, while the main API path handed
`ChannelArchitectAgent.analyze(all_raw, ...)` every raw topic and threw the
scoring away. Not two policies — one policy honoured on one path and skipped on
the other, which meant the lanes all the calibration work measures were
deciding nothing on the busier path.

Resolved as: TopicScorer admits, ChannelArchitect ranks."""

from __future__ import annotations

import pytest

from omnicast.discovery import topic_router
from omnicast.discovery.topic_router import (
    ROUTER_ARCHITECT_ONLY,
    ROUTER_SCORER_GATE,
    admit,
)


class _Raw:
    def __init__(self, title):
        self.title = title


class _Scored:
    def __init__(self, title, action):
        self.raw = _Raw(title)
        self.action = action


def _corpus():
    scored = [_Scored("approved", "approve"), _Scored("reviewed", "review"),
              _Scored("discarded", "discard")]
    return scored, [s.raw for s in scored]


def test_discarded_topics_never_reach_the_ranker():
    scored, raw = _corpus()
    result = admit(scored, raw, policy=ROUTER_SCORER_GATE)
    assert [t.title for t in result.admitted] == ["approved", "reviewed"]
    assert result.rejected_titles == ["discarded"]
    assert result.fell_back is False


def test_review_lane_is_admitted_not_discarded():
    """`review` means "a human should look", not "never make this" — gating it
    out would quietly shrink the calendar."""
    scored, raw = _corpus()
    admitted = admit(scored, raw, policy=ROUTER_SCORER_GATE).admitted
    assert "reviewed" in [t.title for t in admitted]


def test_legacy_policy_still_bypasses_the_gate():
    scored, raw = _corpus()
    result = admit(scored, raw, policy=ROUTER_ARCHITECT_ONLY)
    assert len(result.admitted) == 3
    assert result.rejected_count == 0
    assert any("ignored" in n for n in result.notes)


def test_an_all_discard_run_falls_back_loudly_instead_of_producing_nothing():
    """A gate that can empty the content calendar is a worse failure than a
    permissive one — but it must not do it silently."""
    scored = [_Scored("a", "discard"), _Scored("b", "discard")]
    result = admit(scored, [s.raw for s in scored], policy=ROUTER_SCORER_GATE)
    assert len(result.admitted) == 2
    assert result.fell_back is True
    assert any("falling back" in n for n in result.notes)


def test_gate_uses_the_deciding_generation_not_the_uncalibrated_one():
    """`action` reads `total_score`, which in shadow mode is v1's. Admission
    must never be decided by the generation that is not allowed to decide."""
    import asyncio

    from omnicast.discovery.models import TopicRawData
    from omnicast.discovery.scorer import TopicScorer
    from omnicast.models.enums import Market, Niche, TopicSource

    topic = TopicRawData(title="T", source=TopicSource.YOUTUBE_COMPETITOR,
                         niche=Niche.FINANCE, market=Market.US,
                         raw_metrics={"outlier_ratio": 8.0,
                                      "channel_median_views": 2_000_000})
    scored = asyncio.run(TopicScorer(scoring_mode="shadow").score_batch([topic]))
    # v1 = 79 (approve); v2 = 59.5 (review). The gate must see v1's lane.
    assert scored[0].total_score_v1 == 79.0
    assert scored[0].total_score_v2 == 59.65   # v2 revision 2 budget
    assert scored[0].action == "approve"
    assert admit(scored, [topic], policy=ROUTER_SCORER_GATE).rejected_count == 0


def test_empty_input_does_not_crash():
    result = admit([], [], policy=ROUTER_SCORER_GATE)
    assert result.admitted == []
    assert result.fell_back is False


@pytest.mark.parametrize("policy", [ROUTER_SCORER_GATE, ROUTER_ARCHITECT_ONLY])
def test_settings_accepts_both_policies(policy):
    from omnicast.config.settings import Settings

    assert Settings.model_fields["omnicast_topic_router"].default == ROUTER_SCORER_GATE
    validator = Settings.__pydantic_decorators__.field_validators
    assert "validate_topic_router" in validator


def test_unknown_policy_is_rejected_by_settings():
    import pydantic

    from omnicast.config.settings import Settings

    with pytest.raises(pydantic.ValidationError):
        Settings(database_url="postgresql://x", rabbitmq_url="amqp://x",
                 omnicast_topic_router="whatever")


def test_router_default_survives_a_missing_settings_file(monkeypatch):
    """A script with no .env must still get the gated default, not the legacy
    bypass."""
    import omnicast.config.settings as settings_mod

    def _boom():
        raise RuntimeError("no .env")

    monkeypatch.setattr(settings_mod, "get_settings", _boom)
    assert topic_router.configured_router() == ROUTER_SCORER_GATE


def test_api_path_applies_the_gate():
    """Pins the wiring: an audit previously proved the API path could revert to
    `all_raw` with the whole suite still green."""
    import inspect

    from omnicast.api import server

    source = inspect.getsource(server)
    assert "topic_router" in source
    assert "_admission.admitted" in source
