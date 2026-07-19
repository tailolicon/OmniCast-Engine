"""Named narrative quality profiles are isolated and cannot weaken system gates."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from omnicast.agents.narrative_pipeline import NamedChannelStrategy
from omnicast.config.channel import ChannelProfile, ChannelProfileLoader
from omnicast.config.narrative_quality import (
    NarrativeQualityStrategy,
    resolve_script_profile,
)
from omnicast.models.enums import Niche


def _profile_payload(**overrides):
    payload = {
        "profile_id": "test_horror_profile",
        "strategy": "first_person_true_horror_compilation",
        "channel_promise": "Restrained first-person danger.",
        "planning_rules": ("Keep plans distinct.",),
        "voice_rules": ("Use ordinary speech.",),
        "dread_rules": ("Escalate through physical choices.",),
        "ending_rules": ("End without neat proof.",),
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("editorial_floor", 81),
        ("continuity_floor", 21),
        ("dimension_floor_ratio", 0.59),
        ("minimum_human_threat_fraction", 0.60),
        ("maximum_numeric_anchors", 5),
        ("maximum_precise_clock_times", 2),
        ("patch_candidate_count", 3),
    ],
)
def test_profile_cannot_weaken_or_change_release_contract(field, value):
    with pytest.raises(ValidationError):
        NarrativeQualityStrategy(**_profile_payload(**{field: value}))


def test_resolver_returns_fresh_frozen_profiles_and_runtime_adapter_preserves_floors():
    first = resolve_script_profile("true_horror_strict_v1")
    second = resolve_script_profile("true_horror_strict_v1")
    runtime = NamedChannelStrategy.from_quality_profile(first)

    assert first is not second
    assert runtime.strategy_id == "true_horror_strict_v1"
    assert runtime.approval_score == 84
    assert runtime.continuity_min == 23
    assert runtime.voice_min == 13
    assert runtime.plausible_response_min == 7
    assert runtime.structural_variety_min == 7
    assert "camera static" in runtime.writer_rules
    with pytest.raises(ValidationError):
        first.editorial_floor = 82


def test_runtime_adapter_accepts_stricter_zero_numeric_and_evidence_budgets():
    profile = NarrativeQualityStrategy(**_profile_payload(
        maximum_numeric_anchors=0,
        maximum_evidence_beats_per_story=0,
    ))
    runtime = NamedChannelStrategy.from_quality_profile(profile)
    assert runtime.numeric_anchor_limit == 0
    assert runtime.evidence_beat_limit == 0


def test_unknown_profile_fails_channel_validation_before_generation():
    with pytest.raises(ValidationError, match="Unknown script_profile"):
        ChannelProfile(
            channel_id="future_channel",
            name="Future Channel",
            niche=Niche.PSYCHOLOGY,
            script_profile="missing_profile",
        )


def test_true_dread_channel_explicitly_selects_horror_profile():
    channels = Path(__file__).parents[2] / "channels"
    profile = asyncio.run(ChannelProfileLoader(channels).load("true_dread_files_us"))
    assert profile.script_profile == "true_horror_strict_v1"


def test_channel_without_profile_remains_unaffected():
    channel = ChannelProfile(
        channel_id="plain_narrative",
        name="Plain Narrative",
        niche=Niche.PSYCHOLOGY,
    )
    assert channel.script_profile == ""
