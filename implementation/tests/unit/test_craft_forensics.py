"""Craft forensics — measuring how the competition actually writes.

The compiled playbook used to be 436 words of received wisdom ("plant an open
loop", "be conversational"), which a writer model already knows and therefore
learns nothing from. These tests pin the measurement layer that replaced it.
"""

from __future__ import annotations

from pathlib import Path

from omnicast.analytics.craft_forensics import analyse_vtt, compare_cohort, parse_vtt
from omnicast.analytics.craft_playbook import (
    compile_craft_playbook,
    compile_writer_playbook,
)

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
So you might<00:00:00.500><c> be</c> wondering

00:00:02.000 --> 00:00:06.000 align:start position:0%
The IRS just released a press release about refunds.

00:00:30.000 --> 00:00:34.000 align:start position:0%
That is 40 percent of retirees.

00:01:30.000 --> 00:01:34.000 align:start position:0%
It costs $2,040 a month. Now the second thing to know is the limit.
"""


def _write(tmp_path: Path, name: str = "vid.en.vtt") -> Path:
    p = tmp_path / name
    p.write_text(VTT, encoding="utf-8")
    return p


def test_parse_vtt_strips_inline_timing_tags(tmp_path):
    lines = parse_vtt(_write(tmp_path))
    assert lines and "<" not in " ".join(ln.text for ln in lines)
    assert lines[0].t == 0.0


def test_beat_map_locates_first_you_number_and_money(tmp_path):
    c = analyse_vtt(_write(tmp_path), video_id="vid", role="winner")
    assert c.first_you_s == 0.0            # "you" in the opening line
    assert c.first_number_s == 30.0        # "40 percent"
    assert c.first_money_s == 90.0         # "$2,040"
    assert c.duration_s >= 90.0


def test_transitions_are_whole_sentences_not_caption_fragments(tmp_path):
    """Caption lines cut mid-clause; a fragment teaches rhythm nothing."""
    c = analyse_vtt(_write(tmp_path), video_id="vid", role="winner")
    assert c.transitions
    for t in c.transitions:
        assert len(t.split()) >= 4
        assert "Now the second thing to know" in t or t.endswith((".", "!", "?"))


def test_compare_cohort_marks_shared_conventions_as_non_discriminating():
    from omnicast.analytics.craft_forensics import VideoCraft

    same = [VideoCraft(video_id=f"w{i}", role="winner", first_money_s=80.0,
                       numbers_per_min=2.0) for i in range(3)]
    same += [VideoCraft(video_id=f"c{i}", role="control", first_money_s=80.0,
                        numbers_per_min=2.0) for i in range(3)]
    cmp = compare_cohort(same)
    assert cmp["metrics"]["numbers_per_min"]["discriminating"] is False
    assert cmp["metrics"]["first_money_s"]["discriminating"] is False


def test_playbook_carries_evidence_not_platitudes():
    forensics = {
        "videos": [
            {"video_id": "w1", "role": "winner", "first_money_s": 80.0,
             "opening_30s": "The IRS just released a press release. It matters.",
             "transitions": ["Now the second thing to know is the limit."]},
            {"video_id": "c1", "role": "control", "first_money_s": 165.0,
             "opening_30s": "Premiums could double over the next decade.",
             "transitions": []},
        ],
        "cohort": {"winner_count": 1, "control_count": 1,
                   "channels": ["@a", "@b", "@c"], "metrics": {
            # rule-grade: survives CI + effect size + 3-channel agreement
            "first_money_s": {"winner_median": 80.0, "control_median": 165.0,
                              "delta": -85.0, "evidence_grade": "rule",
                              "ci95_of_median_diff": (-120.0, -30.0),
                              "cliffs_delta": -0.5,
                              "channels_same_direction": 3,
                              "channels_compared": 3, "discriminating": True},
            # hypothesis-grade: must be voiced as suggestive, never as target
            "first_you_s": {"winner_median": 2.2, "control_median": 6.4,
                            "delta": -4.2, "evidence_grade": "hypothesis",
                            "ci95_of_median_diff": (-9.0, 0.4),
                            "cliffs_delta": -0.3,
                            "channels_same_direction": 2,
                            "channels_compared": 3, "discriminating": False},
            "contractions_per_1k": {"winner_median": 47.6,
                                    "control_median": 57.3, "delta": -9.7,
                                    "evidence_grade": "hypothesis",
                                    "ci95_of_median_diff": (-14.0, -1.0),
                                    "cliffs_delta": -0.25,
                                    "channels_same_direction": 2,
                                    "channels_compared": 3,
                                    "discriminating": False},
        }},
    }
    pb = compile_craft_playbook(forensics)
    # concrete evidence, attributed
    assert "The IRS just released" in pb and "[w1]" in pb
    assert "Premiums could double" in pb          # the losing shape is shown too
    # rule vs hypothesis must be visibly separated
    assert "── RULES" in pb and "first_money_s" in pb
    assert "HYPOTHESES" in pb and "never optimise against" in pb
    assert "first_you_s" in pb
    # the persona the cohort uses is the one this channel is banned from
    assert "BANNED" in pb
    # copying wording is forbidden even though exemplars are shown
    assert "Never reuse these words" in pb


def test_playbook_never_issues_a_rule_it_did_not_measure():
    """The prose used to give orders the tables contradicted: "write the first
    line as an event or a promise, never as a maybe" and "money early" while
    `first_money_s` was no_signal and the rules table said NONE."""
    forensics = {
        "videos": [
            {"video_id": "w1", "role": "winner",
             "opening_30s": "The IRS just released a report.", "transitions": []},
            {"video_id": "c1", "role": "control",
             "opening_30s": "Premiums could double.", "transitions": []},
        ],
        "cohort": {"winner_count": 1, "control_count": 1, "channels": ["@a"],
                   "metrics": {
                       "first_money_s": {"winner_median": 80.0,
                                         "control_median": 165.0,
                                         "evidence_grade": "no_signal",
                                         "ci95_of_median_diff": None,
                                         "cliffs_delta": 0.02,
                                         "channels_same_direction": 1,
                                         "channels_compared": 1,
                                         "discriminating": False}}},
    }
    pb = compile_craft_playbook(forensics)
    assert "RULES" in pb and "NONE" in pb
    # no imperative dressed as a finding
    for order in ("never as a maybe", "money early",
                  "Write the first line as an event"):
        assert order not in pb
    # the qualitative read is offered as an observation, explicitly untested
    assert "OBSERVATION" in pb and "NOT a measured rule" in pb
    # the only hard rule left is the compliance one, and it says so
    assert "comes from policy, not from the cohort" in pb


def test_writer_playbook_excludes_hypotheses_and_style_exemplars():
    """Research prose is useful to an analyst and unsafe as executable prompt
    steering. A model may follow text even after being told it is untested."""
    forensics = {
        "videos": [
            {"video_id": "w1", "role": "winner",
             "opening_30s": "The IRS just released a report.", "transitions": []},
            {"video_id": "c1", "role": "control",
             "opening_30s": "Premiums could double.", "transitions": []},
        ],
        "cohort": {"winner_count": 1, "control_count": 1,
                   "channels": ["@a", "@b", "@c"], "metrics": {
            "first_question_s": {
                "winner_median": 20.0, "control_median": 40.0,
                "evidence_grade": "hypothesis",
                "channels_same_direction": 2, "channels_compared": 3,
            },
        }},
    }
    writer_pb = compile_writer_playbook(forensics)
    assert "PRODUCTION-ELIGIBLE" in writer_pb
    assert "HYPOTHESES" not in writer_pb
    assert "HOW WINNERS OPEN" not in writer_pb
    assert "STYLE REFERENCE" not in writer_pb
    assert "qualitative" not in writer_pb.lower()
