"""The fear gate was rejecting the planner's best ladders.

Run 14, three plans, all three rejected by the fear gate at 2-3/7 present.
Read by hand, the ladders had a hand pushing through a gap, a man stepping
inside and crossing the kitchen toward her, a slider giving an inch, a hand
flat against the wall beside her shoulder — all classified 'other' by a
keyword list — while a mailbox flag 'standing up again the next afternoon'
was 'present' because of 'standing'. These rungs are the ground truth.
"""

from __future__ import annotations

import pytest

import omnicast.agents.narrative_pipeline as np

PRESENT = [
    "The interior garage door — chained by Nolan weeks ago — creaks open until a hand pushes through the gap.",
    "The slider lock gives and the door slides an inch, letting in cold air, before she can decide what to grab.",
    "He steps inside and crosses the kitchen toward her, still talking, and does not stop when she tells him to leave.",
    "He gets a hand flat against the hallway wall beside her shoulder, blocking the way toward the bedrooms.",
    "The back door eases open on its own weight one night and Emmett is standing in it, saying her aunt's hospital room number.",
    "A car idles at the curb after dark, headlights off, then pulls away the moment she looks out the front window.",
    "The driveway motion light snaps on and a shape she can't place moves off toward the garage instead of vanishing outright.",
    "At night the garage door opener motor hums and stops on its own, keypad glowing like someone just tried a code.",
    "When she tells him no delivery was mentioned, he says her aunt's first name and hospital room number, then steps toward the mudroom.",
    "A shape crosses the kitchen window blinds outside, gravel crunching closer along the side path.",
    "The kitchen doorknob turns slowly from outside while Pepper goes rigid and growls low near Nolan's feet.",
    "Someone taps twice on the back slider glass and says her uncle's first name like they expect him to answer.",
    "That night the back door handle is wrenched hard against the deadbolt while he stands ten feet away in the kitchen.",
    "Still on the line, he hears the laundry-room window sash being forced up in the room he just left.",
    "Another tap came, this time closer to the center of the glass.",
    # run 14 re-audit: state words inside an event are not a trace
    "The garage side door, its hook-and-eye unlatched, swings inward, and Roy's voice calls out for Elsie.",
    "The propped chair scrapes and the mudroom door gives; he's inside, and the dogs are barking at the bottom of the stairs.",
    "The sunroom's sliding door begins rattling as something metal works into the track and the safety bar lifts.",
    "A knuckle-knock raps twice against the sunroom glass, and when she checks, the broom handle wedged in the slider's track has been moved.",
    "A calm voice through the back door recites Rosalind's name and exact hospital room number, insisting he must drop off a rail.",
    'A man arrives at the front door in daylight claiming to deliver a shower chair, and his eyes linger past her shoulder.',
    'A man in a plain company polo, no badge, knocks at the front door in daylight and states the exact insulin dosage aloud.',
    'Headlights swing into the gravel drive and idle far down by the mailbox before reversing back out onto the road.',
    "Daylight knock: Roy asks about the well pump and mentions Elsie's surgery date like it's nothing.",
    "The slider lurches open several inches, cold air pushing the curtain sideways, and a hand closes over the door's edge.",
    "He's standing at the foot of the staircase calling her aunt's name in a singsong voice, moving toward the first step.",
    'The kitchen doorknob turns back and forth in its lock, and the door frame takes a soft, testing shove.',
    # 'finds' inside an event is not a discovery frame
    "The window frame cracks and a hand tears through the screen, reaching for the inside catch; she is already moving down the hallway before it finds the lock.",
    "He finds the bulkhead unlocked from her firewood run earlier, lifts the slanted doors, and climbs down into the cellar.",
]
TRACE = [
    "The mailbox flag she lowered the evening before is standing up again the next afternoon.",
    "Garage side door found unlatched one morning despite Nolan checking it the night before.",
    "Recycling bin already at the curb a day early, though he never moved it.",
    "The porch bulb Wallace always kept lit is unscrewed a quarter turn when she arrives the first night.",
    "She finds the back door only latched, not deadbolted, though she remembers turning it herself the night before.",
    "The recliner in the living room sits a few inches off its usual mark, cushion flattened like someone sat there.",
    "A business card for an oxygen-supply company is wedged in the mudroom door when she comes back from feeding the barn cats.",
    "Returning from the hospital, the mailbox flag is up though he never touched it.",
    "Woodpile behind the garage restacked differently.",
    "A note listing the exact minute he fed the cat each night.",
    "Mail flap she'd already cleared that morning swings faintly when she gets home, envelopes shifted.",
    'The mail on the counter is out of order, rubber band off, the kind of thing a carrier could explain.',
    "The signed delivery slip listing her aunt's insulin dose goes missing from the kitchen counter sometime that same week.",
    'Porch light she always leaves off is glowing when she gets back from walking the dogs the first evening.',
]


NOT_PRESENT = [
    # an absence noticed is not the threat acting; trace or other both keep it out of the count
    "The porch motion light doesn't trip when she carries in the mail the second evening, though the bulb still looks fine.",
]


@pytest.mark.parametrize("rung", NOT_PRESENT)
def test_an_absence_noticed_is_not_present(rung):
    assert np.rung_kind(rung) != "present", rung


@pytest.mark.parametrize("rung", PRESENT)
def test_the_threat_acting_now_is_present(rung):
    assert np.rung_kind(rung) == "present", rung


@pytest.mark.parametrize("rung", TRACE)
def test_evidence_found_afterwards_is_trace(rung):
    assert np.rung_kind(rung) == "trace", rung


def test_run_14s_best_ladders_now_pass_the_gate():
    class _S:
        story_id = "story_1"
        escalation_ladder = [TRACE[2], TRACE[1], PRESENT[7], PRESENT[9], PRESENT[10], PRESENT[0]]

    class _P:
        stories = [_S()]

    assert np.ladder_fear_problems(_P()) == []
