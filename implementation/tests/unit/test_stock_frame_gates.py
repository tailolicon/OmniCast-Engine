"""Frame-level and synonym-level vetoes added after the v5/v6 audits.

Live failures these pin down:
- a hooded FIGURE walked in as the threat under a 'people, faces' negative
  (slugs say 'person/man/hooded', never 'people');
- a Bell Aliant payphone survived a 2-sample OCR when both samples hit glare;
- yt-dlp had no negative filtering at all (the figure came from there).
"""
from omnicast.media.providers.stock_video import _hits_negative, _reject_junk


def test_people_negative_matches_person_slug():
    slug = "a-person-in-a-hoodie-walking-at-night-1234"
    assert _hits_negative(slug, ["people"]) == "people"


def test_people_negative_matches_figure_and_silhouette():
    assert _hits_negative("dark-figure-on-a-road", ["people"]) == "people"
    assert _hits_negative("silhouette-of-a-man", ["people"]) == "people"


def test_urban_negative_matches_city_slug():
    assert _hits_negative("city-street-at-night", ["urban"]) == "urban"


def test_clean_slug_survives_expansion():
    assert _hits_negative("empty-porch-light-at-night", ["people", "urban"]) is None


def test_ytdlp_title_negative_veto():
    info = {"title": "Hooded man walking alone at night", "duration": 30}
    assert _reject_junk(info, negative_terms=["people"]) is not None


def test_ytdlp_clean_title_passes():
    info = {"title": "Rural farmhouse at dusk b-roll", "duration": 30}
    assert _reject_junk(info, negative_terms=["people"]) is None
