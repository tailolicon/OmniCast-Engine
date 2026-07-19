"""Genre-specific critic rubrics.

The explainer rubric (number-hook, CTA retention, SFX-required, insider data) and
the first-person-horror rubric are fundamentally different value systems; sharing
one prompt made them contradict each other (a horror script was told both "no CTA
needed" and "retention needs a mid-video CTA"). Each genre gets its own dimension
set + scoring bands here; CriticAgent selects by `content_format`.

Contract every rubric module exposes:
    VO_DIMS:  dict[name -> max]   (sums to 70)
    PROD_DIMS:dict[name -> max]   (sums to 30)
    VO_PASS, PROD_PASS: int       (75% gates)
    dimension_rubric() -> str     (the per-dimension scoring bands for the prompt)
    slop_cap_dims: dict[flag_key -> dimension_name]  (which dim a machine flag caps)
"""

from omnicast.agents.rubrics import narrative_horror
