"""Evidence grading — the gate between "a difference showed up" and "a rule".

The first version called a metric `discriminating` when the winner median sat
15% away from the control median. An external audit re-tested those five
"findings": none survived multiple-comparison correction, and one reversed
direction inside the channel that dominated the pool (Simpson's paradox). The
grade now needs a bootstrap CI that excludes zero, a non-negligible effect
size, AND the same direction in at least three channels.
"""

from __future__ import annotations

from omnicast.analytics.craft_forensics import VideoCraft, compare_cohort


def _rows(spec: list[tuple[str, str, float]]) -> list[VideoCraft]:
    """(channel, role, value) → craft rows carrying that value in one field."""
    return [VideoCraft(video_id=f"v{i}", channel=ch, role=role,
                       invitations_per_1k=val, words=1000)
            for i, (ch, role, val) in enumerate(spec)]


def test_pooled_difference_without_channel_agreement_is_not_a_rule():
    """Simpson's paradox guard: the pooled gap comes from channel mix."""
    spec: list[tuple[str, str, float]] = []
    # Channel A: winners LOWER than controls
    spec += [("@a", "winner", v) for v in (1.0, 1.1, 0.9, 1.0, 1.2)]
    spec += [("@a", "control", v) for v in (3.0, 3.2, 2.8, 3.1, 3.0)]
    # Channel B: winners HIGHER than controls (opposite direction)
    spec += [("@b", "winner", v) for v in (4.0, 4.2, 3.9, 4.1, 4.0)]
    spec += [("@b", "control", v) for v in (2.0, 2.1, 1.9, 2.0, 2.2)]
    out = compare_cohort(_rows(spec))["metrics"]["invitations_per_1k"]
    assert out["evidence_grade"] != "rule"
    assert out["channels_same_direction"] < 3


def test_consistent_large_effect_across_three_channels_is_a_rule():
    spec: list[tuple[str, str, float]] = []
    for ch in ("@a", "@b", "@c"):
        spec += [(ch, "winner", v) for v in (4.0, 4.3, 4.1, 3.9, 4.2)]
        spec += [(ch, "control", v) for v in (1.0, 1.2, 0.9, 1.1, 1.0)]
    out = compare_cohort(_rows(spec))["metrics"]["invitations_per_1k"]
    assert out["evidence_grade"] == "rule"
    assert out["channels_same_direction"] >= 3
    lo, hi = out["ci95_of_median_diff"]
    assert lo > 0 and hi > 0            # CI excludes zero


def test_noise_with_a_15_percent_median_gap_is_no_longer_promoted():
    """The exact shape the old threshold rewarded: a small median gap swamped
    by spread."""
    spec: list[tuple[str, str, float]] = []
    for ch in ("@a", "@b", "@c"):
        spec += [(ch, "winner", v) for v in (1.0, 9.0, 2.0, 8.0, 1.15)]
        spec += [(ch, "control", v) for v in (1.0, 9.0, 2.0, 8.0, 1.0)]
    out = compare_cohort(_rows(spec))["metrics"]["invitations_per_1k"]
    assert out["evidence_grade"] != "rule"


def test_tiny_samples_cannot_reach_rule_grade():
    spec = [("@a", "winner", 5.0), ("@a", "control", 1.0),
            ("@b", "winner", 5.0), ("@b", "control", 1.0)]
    out = compare_cohort(_rows(spec))["metrics"]["invitations_per_1k"]
    assert out["ci95_of_median_diff"] is None      # bootstrap refuses n<5
    assert out["evidence_grade"] != "rule"


def test_grades_are_exposed_for_every_metric():
    spec = [("@a", "winner", 2.0)] * 6 + [("@a", "control", 1.0)] * 6
    metrics = compare_cohort(_rows(spec))["metrics"]
    assert set(metrics) >= {"first_you_s", "reactions_per_1k",
                            "invitations_per_1k"}
    for m in metrics.values():
        assert m["evidence_grade"] in {"rule", "hypothesis", "no_signal"}
        # legacy key must track the new grade, never outrank it
        assert m["discriminating"] == (m["evidence_grade"] == "rule")


def _paired_rows(n: int, diff: float, noise: float = 0.05,
                 channels: tuple[str, ...] = ("@a", "@b", "@c")):
    """n matched pairs per channel, winner = control + diff."""
    rows = []
    for ch in channels:
        for i in range(n):
            base = 10.0 + (i % 5) * 3.0           # between-pair variance
            ctl_id = f"{ch}_c{i}"
            rows.append(VideoCraft(video_id=ctl_id, channel=ch, role="control",
                                   invitations_per_1k=base, words=1000))
            rows.append(VideoCraft(video_id=f"{ch}_w{i}", channel=ch,
                                   role="winner", matched_control=ctl_id,
                                   invitations_per_1k=base + diff + noise * (i % 2),
                                   words=1000))
    return rows


def test_paired_test_finds_a_consistent_within_pair_shift():
    """Between-video spread hides a real effect from an unpaired median test;
    differencing inside the matched pair recovers it."""
    out = compare_cohort(_paired_rows(6, diff=2.0))["metrics"]["invitations_per_1k"]
    paired = out["paired"]
    assert paired["n_pairs"] == 18
    lo, hi = paired["ci95"]
    assert lo > 0 and hi > 0                     # CI excludes zero
    assert paired["winners_higher"] == 1.0
    assert out["evidence_grade"] == "rule"       # paired CI + effect + 3 channels


def test_paired_noise_does_not_reach_rule():
    out = compare_cohort(_paired_rows(6, diff=0.0, noise=1.0))["metrics"]["invitations_per_1k"]
    assert out["evidence_grade"] != "rule"


def test_too_few_pairs_cannot_carry_a_rule():
    out = compare_cohort(_paired_rows(2, diff=3.0))["metrics"]["invitations_per_1k"]
    assert out["paired"]["n_pairs"] == 6
    assert out["evidence_grade"] != "rule"       # needs >= 8 complete pairs
