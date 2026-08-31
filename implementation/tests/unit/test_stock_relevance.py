"""The stock providers must not ship a wrong-subject clip.

Live failure: Pexels ranked a soil-tiller video first for the query
'flower bed dirt footprint night' and the renderer took videos[0] blindly —
the video's final beat showed farm machinery under a line about a footprint
under a window. Candidates are now ranked by query-word overlap with the
content descriptor (Pexels page-URL slug / Pixabay tags), and a page with
zero overlap anywhere counts as no result so the next provider gets a turn.
"""
from omnicast.media.providers.stock_video import _content_tokens, _match_score


def test_content_tokens_drop_grammar_keep_content():
    assert _content_tokens("a footprint in the flower bed at night") == {
        "footprint", "flower", "bed", "night"}


def test_zero_overlap_for_wrong_subject_slug():
    q = "flower bed dirt footprint night"
    slug = "https://www.pexels.com/video/a-machine-tilling-the-soil-854321/"
    assert _match_score(q, slug) == 0


def test_right_subject_slug_outranks_wrong_one():
    q = "flower bed dirt footprint night"
    good = "https://www.pexels.com/video/footprints-in-a-garden-flower-bed-11/"
    bad = "https://www.pexels.com/video/a-machine-tilling-the-soil-854321/"
    assert _match_score(q, good) > _match_score(q, bad)


def test_prefix_match_bridges_morphology():
    # footprint vs footprints, till vs tilling
    assert _match_score("footprint night", "footprints-at-night") == 2


def test_generic_slug_words_earn_no_credit():
    # 'footage' prefix-matched 'footprints' and let a burned-wood clip stand
    # in for footprints (live, v5 300s). Format words never count.
    q = "footprints in dirt around house"
    slug = "close-up-footage-of-a-burned-wood-on-a-muddy-ground-8066028"
    assert _match_score(q, slug) == 0


def test_pixabay_tags_score():
    q = "porch light burning night farmhouse"
    tags = "farmhouse, porch, night, rural"
    assert _match_score(q, tags) >= 3
