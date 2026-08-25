"""Episode/title parsing — the heuristics backfill grouping stands on."""
import pytest

from omnicast.library.titles import (
    base_title,
    group_key,
    normalize_key,
    parse_episode,
    series_slug,
)


@pytest.mark.parametrize("title,expected_ep", [
    ("《红魔猩猩》第3集 #科幻 #电影", 3),
    ("第十二集 修仙归来", 12),
    ("第二十三集", 23),
    ("修仙 第５集", 5),                      # fullwidth digit
    ("Khỉ Đột Đỏ - Tập 5", 5),
    ("Phim hay EP.12", 12),
    ("Anh hùng P3", 3),
    ("剑来（7）", 7),
    ("Tổng tài Phần 2", 2),
    ("龙王归来 08", 8),                      # bare trailing number
])
def test_parse_episode_finds_the_number(title, expected_ep):
    _, ep = parse_episode(title)
    assert ep == expected_ep


@pytest.mark.parametrize("title", [
    "Tiêu đề 1080",       # resolution, not an episode
    "Phim hay 2024",      # year
    "无题",                # nothing
    "",                    # empty
    "Đại chiến P720",     # P + resolution
])
def test_parse_episode_rejects_suspicious_numbers(title):
    _, ep = parse_episode(title)
    assert ep is None


def test_base_title_prefers_cjk_brackets():
    assert base_title("《红魔猩猩》第3集 #科幻") == "红魔猩猩"
    assert base_title("看这个", "【Khỉ Đột Đỏ】tập 9") == "Khỉ Đột Đỏ"


def test_base_title_strips_episode_and_hashtags():
    assert base_title("Khỉ Đột Đỏ - Tập 5 #phimhay") == "Khỉ Đột Đỏ"


def test_group_key_is_stable_across_episodes():
    k1 = group_key("作者A", "《红魔猩猩》第3集 #科幻")
    k2 = group_key("作者A", "《红魔猩猩》第14集")
    k3 = group_key("作者B", "《红魔猩猩》第3集")
    assert k1 == k2
    assert k1 != k3          # different author → different series bucket


def test_normalize_key_keeps_vietnamese_diacritics():
    assert normalize_key("Khỉ Đột Đỏ!") == "khỉđộtđỏ"


def test_series_slug_ascii_and_cjk():
    assert series_slug("Khi Dot Do") == "khi_dot_do"
    slug = series_slug("红魔猩猩")
    assert slug.startswith("series_") and slug.isascii()
    # deterministic — the same title always maps to the same id
    assert slug == series_slug("红魔猩猩")
