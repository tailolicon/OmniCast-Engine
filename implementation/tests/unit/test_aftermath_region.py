"""_aftermath_region — word-budgeted tail window (live falsz-positive 04/09).

The hotel-front-desk draft (89/100) reported to the deputies in a full
aftermath scene, but nosleep-style one-line paragraphing plus the mandatory
what-stays coda pushed that scene out of the old last-3-paragraphs window.
The window is now a word budget (>=150 words / >=15% of the story, min 3
paragraphs) — a strict superset of the old window.
"""

from omnicast.agents.narrative_pipeline import _AUTHORITY_RE, _aftermath_region


def _story(paragraphs):
    return "\n\n".join(paragraphs)


class TestAftermathRegion:
    def test_superset_of_old_three_paragraph_window(self):
        paras = [f"Paragraph number {i} with a good many words in it." for i in range(10)]
        region = _aftermath_region(_story(paras))
        for p in paras[-3:]:
            assert p in region

    def test_short_paragraph_style_reaches_report_scene(self):
        # A realistic-length story told in short paragraphs; the report sits 8
        # from the end under a what-stays coda — exactly the live rejection shape.
        paras = [
            f"Something happened in beat {i} of the night, and I remember the "
            "way the sound carried across the empty lot while I stood at the "
            "desk telling myself it was nothing, counting the drawer again, "
            "watching the monitor out of the corner of my eye the whole time."
            for i in range(32)
        ]
        paras.append("I reported the whole thing to the deputies once I was out.")
        paras += [
            "They did not confirm any part of it for me.",
            "I finished the shift because nobody else could take the desk.",
            "Later I realized where he had been standing all along.",
            "That changed the part of the night I replay most.",
            "I still throw the deadbolt first, before anything else.",
            "The name on his card never matched anything on record.",
            "No car of his was ever seen in the lot at all.",
        ]
        region = _aftermath_region(_story(paras))
        assert _AUTHORITY_RE.search(region), "report scene must fall inside the window"

    def test_early_escape_call_stays_outside(self):
        # A 911 call in the first act of a long story must not discharge the
        # aftermath obligation.
        paras = ["I dialed 911 early on and hung up when nothing came of it."]
        paras += [
            f"Long middle paragraph {i} where the night keeps getting worse "
            "and worse with many words per line to build the word count out."
            for i in range(30)
        ]
        paras += ["I drove home.", "I never went back.", "The key is still in my drawer."]
        region = _aftermath_region(_story(paras))
        assert not _AUTHORITY_RE.search(region)

    def test_minimum_three_paragraphs_even_when_budget_met_sooner(self):
        paras = ["short.", "short.", "x " * 400, "tail one.", "tail two."]
        region = _aftermath_region(_story(paras))
        assert "tail one." in region and "tail two." in region
        assert region.count("\n\n") >= 2
