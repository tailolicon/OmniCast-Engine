"""Stock queries that ask for a human shape are re-routed to LANE 2.

Live: the storyboard emitted 'dark porch silhouette figure' as a stock_query
on the horror channel — stock returned an actual visible person as the threat
(codex audit R8/R15, frames v8_240/360/480). On strict-gate channels such
cells become generated_image money-shots where the figure is controllable.
"""
from omnicast.config.channel_styles import enforce_policy, get_style_policy


def _cell(q):
    return {"scene_index": 0, "visual_type": "stock_video", "stock_query": q,
            "search_query": "", "image_prompt": "", "video_prompt": "",
            "negative_prompt": "", "stat_number": "", "stat_label": ""}


def test_silhouette_query_coerced_to_generated_image():
    policy = get_style_policy("horror_real")
    board = [_cell("dark porch silhouette figure")]
    enforce_policy(board, ["porch"], policy)
    assert board[0]["visual_type"] == "generated_image"
    assert board[0]["stock_query"] == ""
    assert "grainy" in board[0]["image_prompt"]


def test_plain_place_query_untouched():
    policy = get_style_policy("horror_real")
    board = [_cell("dark farmhouse porch night")]
    enforce_policy(board, ["porch"], policy)
    assert board[0]["visual_type"] == "stock_video"
    assert board[0]["stock_query"] == "dark farmhouse porch night"


def test_footage_channel_not_affected():
    policy = get_style_policy("footage")
    board = [_cell("man walking on street")]
    enforce_policy(board, ["street"], policy)
    assert board[0]["visual_type"] == "stock_video"
