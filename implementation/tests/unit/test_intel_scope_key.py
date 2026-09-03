"""Intel scope keys (strategic review §4.2).

The bug in one sentence: playbooks were keyed by `niche`, so every finance
channel in the system read and OVERWROTE the same thumbnail playbook, and the
last learner to run won without telling anyone.
"""

from __future__ import annotations

import pytest

from omnicast.agents import writer as writer_mod
from omnicast.analytics.intel_scope import (
    ANY,
    describe_level,
    fallback_chain,
    scope_key,
)
from omnicast.config.channel import ChannelProfile
from omnicast.models.enums import Market, Niche


def _channel(**overrides) -> ChannelProfile:
    data = dict(channel_id="fin_retirement_us", name="Smart Retirement",
                niche=Niche.FINANCE, market=Market.US)
    data.update(overrides)
    return ChannelProfile(**data)


def test_two_finance_channels_no_longer_share_one_key():
    """The whole point. Before this, both of these were 'finance'."""
    retirement = _channel(channel_id="fin_retirement_us",
                          audience_segment="55plus", content_format="longform")
    crypto = _channel(channel_id="fin_crypto_us",
                      audience_segment="25_35", content_format="shorts")
    assert scope_key(retirement) != scope_key(crypto)


def test_an_undeclared_dimension_is_a_literal_not_a_wildcard():
    """`*` must not collide: a channel that declared no audience segment is not
    'any audience', it is 'we do not know', and it must not silently share a row
    with a channel that did declare one."""
    undeclared = _channel(channel_id="c1")
    declared = _channel(channel_id="c1", audience_segment="55plus")
    assert ANY in scope_key(undeclared)
    assert scope_key(undeclared) != scope_key(declared)


def test_the_pillar_participates_in_the_key():
    channel = _channel(audience_segment="55plus", content_format="longform")
    assert scope_key(channel, pillar_id="annuities") != \
        scope_key(channel, pillar_id="social_security")


def test_an_unclassified_pillar_widens_the_key_rather_than_inventing_one():
    from omnicast.analytics.pillars import UNCLASSIFIED, UNCONFIGURED

    channel = _channel()
    base = scope_key(channel)
    assert scope_key(channel, pillar_id=UNCONFIGURED) == base
    assert scope_key(channel, pillar_id=UNCLASSIFIED) == base


def test_the_chain_runs_from_most_specific_to_the_legacy_niche_key():
    channel = _channel(audience_segment="55plus", content_format="longform")
    chain = fallback_chain(channel, pillar_id="annuities")
    levels = [level for level, _key in chain]
    assert levels[0] == "exact"
    assert levels[-1] == "niche"
    assert chain[-1][1] == "finance"          # the key the old system wrote
    assert len(chain) == len({key for _l, key in chain})   # no duplicate levels


def test_borrowing_a_niche_wide_playbook_is_described_as_borrowing():
    assert "BORROWED" in describe_level("niche")


# ── the writer actually walks the chain ─────────────────────────────────────

class _Brief:
    """Minimal stand-in with the attributes the resolver reads."""

    def __init__(self, channel, required=False):
        self.niche = channel.niche
        self.market = channel.market
        self.channel_id = channel.channel_id
        self.audience_segment = channel.audience_segment
        self.content_format = channel.content_format
        self.competitor_intel_required = required
        self.channel = channel


def test_the_writer_tries_the_specific_key_before_the_niche_key(monkeypatch):
    channel = _channel(audience_segment="55plus", content_format="longform")
    tried: list[str] = []

    def _fake_load(scope, **kw):
        tried.append(scope)
        return None

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _fake_load)
    writer_mod.resolve_competitor_playbook(_Brief(channel))

    assert tried[0] == scope_key(channel)
    assert tried[-1] == "finance"


def test_a_specific_row_wins_and_the_niche_row_is_never_consulted(monkeypatch):
    channel = _channel(audience_segment="55plus", content_format="longform")
    tried: list[str] = []
    specific = scope_key(channel)

    class _Row:
        title_playbook = thumbnail_playbook = script_playbook = "SPECIFIC"
        cohort_meta = "{}"

    def _fake_load(scope, **kw):
        tried.append(scope)
        return _Row() if scope == specific else None

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _fake_load)
    writer_mod.resolve_competitor_playbook(_Brief(channel))
    assert tried == [specific]


def test_a_missing_specific_row_falls_back_instead_of_failing(monkeypatch):
    """Narrowing the key alone would trade one silent failure for another: no
    playbook at all on a channel's first run, with a usable one a row away."""
    channel = _channel(audience_segment="55plus", content_format="longform")

    class _Row:
        title_playbook = thumbnail_playbook = script_playbook = "NICHE WIDE"
        cohort_meta = "{}"

    monkeypatch.setattr(writer_mod, "_load_competitor_intel",
                        lambda scope, **kw: _Row() if scope == "finance" else None)
    decision = writer_mod.resolve_competitor_playbook(_Brief(channel))
    assert decision is not None


def test_a_vault_failure_is_still_its_own_outcome(monkeypatch):
    """The chain must not turn a read error into 'nothing learned yet'."""
    from omnicast.analytics.intel_gate import STATUS_ERROR

    def _boom(scope, **kw):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _boom)
    decision = writer_mod.resolve_competitor_playbook(_Brief(_channel()))
    assert decision.status == STATUS_ERROR


def test_a_required_channel_still_fails_closed_through_the_chain(monkeypatch):
    from omnicast.analytics.intel_gate import CompetitorIntelRequired

    def _boom(scope, **kw):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _boom)
    with pytest.raises(CompetitorIntelRequired):
        writer_mod.resolve_competitor_playbook(_Brief(_channel(), required=True))
