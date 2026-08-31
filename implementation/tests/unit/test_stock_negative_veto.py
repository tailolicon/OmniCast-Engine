"""The storyboard's negative_prompt vetoes wrong-world stock candidates.

Live failure (codex audit v4_300): the query matched winter footage — snowbound
cabins and a snowman under a summer perimeter-check line. The cell's
negative_prompt named 'snow, winter'; the provider now rejects candidates whose
descriptor (Pexels slug / Pixabay tags) matches any negative term.
"""
from omnicast.media.providers.stock_video import _hits_negative


def test_snow_candidate_vetoed_in_summer_story():
    slug = "https://www.pexels.com/video/cabins-covered-in-snow-855321/"
    assert _hits_negative(slug, ["snow", "winter"]) == "snow"


def test_on_world_candidate_survives():
    slug = "https://www.pexels.com/video/footprints-in-a-garden-flower-bed-11/"
    assert _hits_negative(slug, ["snow", "winter", "daylight"]) is None


def test_prefix_bridges_morphology():
    # 'snowman', 'snowy' all hit the 'snow' veto via the 4-char prefix rule
    assert _hits_negative("a-snowman-in-a-field", ["snow"]) == "snow"


def test_actor_veto_for_first_person_beats():
    tags = "woman, mirror, phone, talking"
    # Which negative term reports the hit is unimportant (synonym expansion
    # means 'actor' can claim it first) — the veto firing is the contract.
    assert _hits_negative(tags, ["actor", "face", "woman"]) is not None


def test_no_negatives_means_no_veto():
    assert _hits_negative("anything-at-all", None) is None
    assert _hits_negative("anything-at-all", []) is None
