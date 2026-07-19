"""Behavior tests for channel_style sourcing policies (config/channel_styles.py)."""

from omnicast.config.channel_styles import (
    STYLE_POLICIES,
    enforce_policy,
    get_style_policy,
)


class TestGetStylePolicy:
    def test_known_styles_resolve(self):
        for sid in ("footage", "storytelling", "horror_real"):
            p = get_style_policy(sid)
            assert p is not None and p.style_id == sid

    def test_auto_none_unknown_return_none(self):
        assert get_style_policy(None) is None
        assert get_style_policy("") is None
        assert get_style_policy("auto") is None
        assert get_style_policy("does_not_exist") is None

    def test_case_and_whitespace_tolerant(self):
        assert get_style_policy("  Horror_Real ").style_id == "horror_real"


class TestHorrorRealPolicy:
    def test_photoreal_generated_money_shot_allowed(self):
        """Since the 2026-07-11 policy change, horror allows photoreal FOUND-PHOTO
        style generated stills for scare money-shots (stock has no silhouettes)."""
        policy = STYLE_POLICIES["horror_real"]
        board = [
            {"visual_type": "generated_image",
             "image_prompt": "grainy amateur night photograph, distant silhouette in warehouse aisle"},
            {"visual_type": "stock_video", "stock_query": "fog forest night"},
        ]
        out = enforce_policy(board, ["Aisle Nine", "The Forest"], policy)
        assert out[0]["visual_type"] == "generated_image"
        assert out[1]["visual_type"] == "stock_video"
        assert out[1]["stock_query"] == "fog forest night"

    def test_web_search_image_allowed(self):
        policy = STYLE_POLICIES["horror_real"]
        board = [{"visual_type": "web_search_image", "search_query": "1987 newspaper headline"}]
        out = enforce_policy(board, ["News"], policy)
        assert out[0]["visual_type"] == "web_search_image"


class TestStorytellingPolicy:
    def test_web_types_banned_and_coerced_to_generated(self):
        policy = STYLE_POLICIES["storytelling"]
        board = [
            {"visual_type": "web_search_image", "search_query": "ancient roman coin", "image_prompt": ""},
            {"visual_type": "web_screenshot", "search_query": "https://example.com", "image_prompt": ""},
            {"visual_type": "generated_image", "image_prompt": "a king in a torchlit hall"},
        ]
        out = enforce_policy(board, ["The Coin", "The Site", "The King"], policy)
        assert out[0]["visual_type"] == "generated_image"
        assert out[0]["image_prompt"] == "ancient roman coin"  # derived from search_query
        assert out[1]["visual_type"] == "generated_image"
        assert out[1]["image_prompt"]  # derived (falls back to heading/search)
        assert out[2]["visual_type"] == "generated_image"

    def test_requires_image_provider(self):
        policy = STYLE_POLICIES["storytelling"]
        assert policy.requires_image_provider is True
        assert policy.default_image_provider == "flow"

    def test_stock_atmosphere_still_allowed(self):
        policy = STYLE_POLICIES["storytelling"]
        board = [{"visual_type": "stock_video", "stock_query": "storm clouds timelapse"}]
        out = enforce_policy(board, ["Storm"], policy)
        assert out[0]["visual_type"] == "stock_video"


class TestFootagePolicy:
    def test_all_types_with_content_pass_through(self):
        policy = STYLE_POLICIES["footage"]
        board = [
            {"visual_type": "stock_video", "stock_query": "city traffic"},
            {"visual_type": "generated_image", "image_prompt": "a symbolic maze of doors"},
            {"visual_type": "web_search_image", "search_query": "SPIVA report chart"},
            {"visual_type": "web_screenshot", "search_query": "https://www.sec.gov"},
        ]
        out = enforce_policy(board, ["a", "b", "c", "d"], policy)
        assert [c["visual_type"] for c in out] == [
            "stock_video", "generated_image", "web_search_image", "web_screenshot"]

    def test_empty_stub_cells_coerced_to_stock(self):
        """Storyboard salvage losses arrive as bare cells — those must become
        stock B-roll (with a derived query), not doomed blank image gens."""
        policy = STYLE_POLICIES["footage"]
        out = enforce_policy(
            [{"visual_type": "generated_image"}, {}],
            ["Compound Interest Math", "Bank Fees Explained"], policy)
        for cell, kw in zip(out, ("compound", "bank")):
            assert cell["visual_type"] == "stock_video"
            assert kw in cell["stock_query"]


class TestEnforcePolicyRobustness:
    def test_missing_visual_type_defaults_generated_and_gets_coerced(self):
        policy = STYLE_POLICIES["horror_real"]
        out = enforce_policy([{}], ["Empty Streets At Night"], policy)
        assert out[0]["visual_type"] == "stock_video"
        assert "night" in out[0]["stock_query"]

    def test_non_dict_cells_survive(self):
        policy = STYLE_POLICIES["horror_real"]
        out = enforce_policy([None, {"visual_type": "generated_image"}], ["x", "y"], policy)
        assert out[0] is None
        assert out[1]["visual_type"] == "stock_video"

    def test_headings_shorter_than_board(self):
        # storytelling bans web images — coercion must survive missing headings
        policy = STYLE_POLICIES["storytelling"]
        out = enforce_policy(
            [{"visual_type": "web_search_image", "search_query": "an old dusty attic"}], [], policy)
        assert out[0]["visual_type"] == "generated_image"
        assert out[0]["image_prompt"]
