"""Sound cues must mark structure, not accompany every cut.

The first Retirement Desk render put a whoosh at nearly every scene change.
The rule was "fire when the scene heading changes" — reasonable for a
storyboard with four sections, a tic for one that names every scene. The
operator's first sentence about the finished video was about this noise, and no
quality gate had anything to say, because correctness gates cannot hear.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import render_real_video as rrv


@dataclass
class _Scene:
    heading: str = ""
    narration: str = ""
    pause_after_ms: int = 0
    emphasis: tuple = field(default_factory=tuple)


def _starts(n: int, step: float) -> list[float]:
    return [i * step for i in range(n)]


def test_a_heading_on_every_scene_earns_no_cues_at_all():
    """Headings that never repeat carry no section information. Spacing alone
    would still let one through every 45s of pure noise."""
    scenes = [_Scene(heading=f"Point {i}") for i in range(40)]
    cues = rrv._section_cue_times(_starts(40, 20.0), scenes, 800.0)
    assert cues == []


def test_real_sections_do_get_their_cue():
    # 40 scenes, 4 sections — headings repeat, so they behave like sections.
    scenes = [_Scene(heading=f"Section {i // 10}") for i in range(40)]
    cues = rrv._section_cue_times(_starts(40, 20.0), scenes, 800.0)
    assert len(cues) == 3                      # three changes after the first
    assert cues[0] == 10 * 20.0 - 0.08


def test_cues_are_never_closer_together_than_a_section_can_be():
    # sections change every 2 scenes = every 10s: structurally impossible
    scenes = [_Scene(heading=f"S{i // 2}") for i in range(20)]
    cues = rrv._section_cue_times(_starts(20, 5.0), scenes, 100.0)
    assert all(b - a >= rrv.MIN_CUE_GAP_S for a, b in zip(cues, cues[1:]))


def test_cue_budget_scales_with_the_video_not_the_storyboard():
    """A 3-minute video gets at most two cues however many headings it has."""
    scenes = [_Scene(heading=f"S{i // 4}") for i in range(40)]
    cues = rrv._section_cue_times(_starts(40, 5.0), scenes, 180.0)
    assert len(cues) <= int(180.0 // rrv.CUE_SECONDS_PER_CUE)


def test_unheaded_storyboard_is_silent_rather_than_guessed_at():
    scenes = [_Scene() for _ in range(20)]
    assert rrv._section_cue_times(_starts(20, 30.0), scenes, 600.0) == []


def test_short_video_gets_no_transition_cue():
    scenes = [_Scene(heading=f"S{i // 3}") for i in range(9)]
    assert rrv._section_cue_times(_starts(9, 8.0), scenes, 72.0) == []


def test_punch_in_is_reserved_for_the_strongest_beats():
    """Every scene in a finance script mentions a figure, so the old boolean
    ("has a number → punch in") made the emphatic move the default one."""
    scenes = [_Scene(heading="S") for _ in range(24)]
    for i, sc in enumerate(scenes):
        sc.narration = f"Roughly {i} percent of retirees do this every year."
    scenes[7].narration = "That is $1,240,000 sitting in the wrong account."
    scenes[15].narration = "Three million households will cross that line."
    board = [{} for _ in scenes]
    board[7] = {"stat_number": "$1.24M"}

    punch = rrv._punch_in_scenes(scenes, board)
    assert 7 in punch                                   # the storyboard's own stat
    assert len(punch) <= max(1, int(len(scenes) * rrv.PUNCH_SHARE))
    ordered = sorted(punch)
    assert all(b - a >= rrv.MIN_PUNCH_SPACING for a, b in zip(ordered, ordered[1:]))


def test_punch_in_never_lands_on_the_hook():
    scenes = [_Scene(narration="A huge $980,000 gap opens right here.")
              for _ in range(12)]
    assert not ({0, 1} & rrv._punch_in_scenes(scenes, [{} for _ in scenes]))


def test_every_scene_qualifying_still_yields_a_minority_of_punches():
    scenes = [_Scene(narration="$500,000 matters here.", pause_after_ms=600,
                     emphasis=("$500,000",)) for _ in range(30)]
    board = [{"stat_number": "$500k"} for _ in scenes]
    punch = rrv._punch_in_scenes(scenes, board)
    assert 0 < len(punch) <= max(1, int(30 * rrv.PUNCH_SHARE))


def test_cut_rhythm_follows_the_writers_pace_marker():
    """Greedy packing to one global word budget cut every shot to the same
    length, which is a metronome, not editing. The writer's own pace marker is
    the one rhythm signal we can honour without inventing a cohort claim."""
    para = " ".join(f"Sentence number {i} carries about eight ordinary words here."
                    for i in range(6))
    counts = {}
    for pace in ("slow", "normal", "fast"):
        shots = rrv.split_into_shots(
            [rrv.Scene(heading="H", narration=para, pace=pace)], 24)
        counts[pace] = len(shots)
    assert counts["slow"] < counts["normal"] < counts["fast"]


def test_pace_marker_never_produces_a_degenerate_one_word_shot():
    para = " ".join(f"Short line {i}." for i in range(20))
    shots = rrv.split_into_shots(
        [rrv.Scene(heading="H", narration=para, pace="fast")], 4)
    assert all(len(s.narration.split()) >= 3 for s in shots)


def test_reveal_chime_is_rate_limited_and_the_cap_is_time_ordered():
    """Two separate defects lived in the tail of _mix_sfx: every hero number
    got a chime (~2.4/min in this cohort), and the 24-event cap truncated by
    INSERTION order — whooshes first — so a long video lost its late reveals
    while keeping every transition."""
    source = rrv.__file__ and open(rrv.__file__, encoding="utf-8").read()
    assert "MIN_TING_GAP_S" in source
    assert "events.sort(key=lambda e: e[0])" in source
    i_sort = source.index("events.sort(key=lambda e: e[0])")
    i_cap = source.index("events[:24]")
    assert i_sort < i_cap, "the cap must run on a time-ordered list"


def test_senior_finance_restrained_sfx_marks_reveals_not_transitions():
    """Older finance viewers need quiet structural emphasis, not creator-style
    whooshes. A 15-minute video may earn only a few soft reveal cues."""
    policy = rrv._sfx_event_policy("restrained", 15 * 60)
    assert policy["transition_cues"] is False
    assert policy["reveal_min_gap_s"] >= 120
    assert policy["max_events"] <= 3

    full = rrv._sfx_event_policy("full", 15 * 60)
    assert full["transition_cues"] is True
    assert full["reveal_min_gap_s"] < policy["reveal_min_gap_s"]
