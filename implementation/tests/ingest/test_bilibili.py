"""Bilibili ingest — URL parsing, WBI signing, stream choice, series listing.

All pure functions; no network. The download path itself needs a live CDN and
is exercised on the operator's machine.
"""
import pytest

from omnicast.ingest.bilibili.client import (
    BilibiliIngestError,
    entries_from_view,
    parse_space_collection,
    parse_video_ref,
    pick_streams,
)
from omnicast.ingest.bilibili.wbi import mixin_key, sign_params
from omnicast.ingest.detect import detect_source_platform


# ── platform detection ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
    ("https://b23.tv/abc123", "bilibili"),
    ("https://m.bilibili.com/video/BV1xx411c7mD", "bilibili"),
    ("BV1xx411c7mD", "bilibili"),
    ("av170001", "bilibili"),
    ("https://v.douyin.com/xYz/", "douyin"),
    ("https://www.douyin.com/video/7671126668437720356", "douyin"),
    ("https://example.com/whatever", "douyin"),   # historical default
])
def test_detect_source_platform(url, expected):
    assert detect_source_platform(url) == expected


# ── video ref parsing ───────────────────────────────────────────────────────

def test_parse_video_ref_bv_with_part():
    ref = parse_video_ref("https://www.bilibili.com/video/BV1xx411c7mD?p=3&t=12")
    assert ref == {"bvid": "BV1xx411c7mD", "page": 3}


def test_parse_video_ref_bare_ids():
    assert parse_video_ref("BV1xx411c7mD") == {"bvid": "BV1xx411c7mD", "page": 1}
    assert parse_video_ref("av170001") == {"aid": 170001, "page": 1}


def test_parse_video_ref_av_url():
    assert parse_video_ref("https://www.bilibili.com/video/av170001")["aid"] == 170001


@pytest.mark.parametrize("url,fragment", [
    ("https://www.bilibili.com/bangumi/play/ep123456", "bangumi"),
    ("https://www.bilibili.tv/en/video/2049823651", "bilibili.tv"),
    ("https://www.bilibili.com/read/cv123", "BV/av"),
])
def test_parse_video_ref_refuses_what_it_cannot_dub(url, fragment):
    with pytest.raises(BilibiliIngestError) as err:
        parse_video_ref(url)
    assert fragment in str(err.value)


def test_parse_space_collection():
    assert parse_space_collection(
        "https://space.bilibili.com/123456/channel/collectiondetail?sid=789"
    ) == {"mid": 123456, "season_id": 789}
    assert parse_space_collection(
        "https://space.bilibili.com/123456/lists/789?type=season"
    ) == {"mid": 123456, "season_id": 789}
    assert parse_space_collection("https://space.bilibili.com/123456") is None
    assert parse_space_collection("https://www.bilibili.com/video/BV1xx411c7mD") is None


# ── WBI signing ─────────────────────────────────────────────────────────────

_IMG = "7cd084941338484aae1ad9425b84077c"
_SUB = "4932caff0ff746eab6f01bf08b70ac45"


def test_mixin_key_matches_documented_vector():
    # Canonical example from the community API documentation.
    assert mixin_key(_IMG, _SUB) == "ea1db124af3c7062474693fa704f4ff8"


def test_sign_params_is_the_reference_recipe():
    signed = sign_params({"foo": "114", "bar": "514", "zab": 1919810},
                         _IMG, _SUB, wts=1702204169)
    # md5("bar=514&foo=114&wts=1702204169&zab=1919810" + mixin) — pinned so a
    # refactor that changes sorting/encoding/filtering fails loudly here.
    assert signed["w_rid"] == "8f6f2b5b3d485fe1886cec6a0be8c5d4"
    assert signed["wts"] == "1702204169"


def test_sign_params_filters_special_chars_and_is_deterministic():
    a = sign_params({"q": "ab!c(d)*e'"}, _IMG, _SUB, wts=1000)
    assert a["q"] == "abcde"          # signature covers the value actually sent
    b = sign_params({"q": "ab!c(d)*e'"}, _IMG, _SUB, wts=1000)
    assert a["w_rid"] == b["w_rid"]
    c = sign_params({"q": "abcdef"}, _IMG, _SUB, wts=1000)
    assert c["w_rid"] != a["w_rid"]


# ── stream selection ────────────────────────────────────────────────────────

def _dash(*videos, audio=None):
    return {"dash": {"video": list(videos), "audio": audio or []}}


def test_pick_streams_prefers_avc_under_the_cap():
    data = _dash(
        {"id": 80, "codecid": 12, "base_url": "hevc1080", "bandwidth": 900},
        {"id": 80, "codecid": 7, "base_url": "avc1080", "bandwidth": 1000},
        {"id": 116, "codecid": 7, "base_url": "avc1080p60", "bandwidth": 2000},
        {"id": 64, "codecid": 7, "base_url": "avc720", "bandwidth": 500},
        audio=[{"base_url": "a1", "bandwidth": 100}, {"base_url": "a2", "bandwidth": 200}],
    )
    chosen = pick_streams(data, quality_max=80)
    assert chosen["mode"] == "dash"
    assert chosen["video"]["base_url"] == "avc1080"     # not p60 (over cap), not hevc
    assert chosen["audio"]["base_url"] == "a2"          # highest bandwidth
    assert chosen["qn"] == 80


def test_pick_streams_falls_back_to_hevc_when_no_avc():
    data = _dash({"id": 64, "codecid": 12, "base_url": "hevc720", "bandwidth": 1})
    assert pick_streams(data)["video"]["base_url"] == "hevc720"


def test_pick_streams_over_cap_only_still_returns_something():
    # Anonymous sessions sometimes only get one rung; a cap must not zero it out.
    data = _dash({"id": 116, "codecid": 7, "base_url": "only", "bandwidth": 1})
    assert pick_streams(data, quality_max=80)["video"]["base_url"] == "only"


def test_pick_streams_durl_fallback_and_empty_raises():
    durl = {"quality": 32, "durl": [{"url": "main.flv", "backup_url": ["bk.flv"]}]}
    chosen = pick_streams(durl)
    assert chosen["mode"] == "durl" and chosen["url"] == "main.flv"
    assert chosen["backups"] == ["bk.flv"]
    with pytest.raises(BilibiliIngestError):
        pick_streams({"durl": [], "dash": None})


# ── series listing from view data ───────────────────────────────────────────

def test_entries_from_view_multi_part():
    info = {
        "bvid": "BV1xx411c7mD",
        "title": "《修仙》全集",
        "owner": {"name": "作者A"},
        "pages": [
            {"page": 1, "cid": 11, "part": "第1集"},
            {"page": 2, "cid": 12, "part": "第2集"},
            {"page": 3, "cid": 13, "part": ""},
        ],
    }
    listing = entries_from_view(info)
    assert listing["author"] == "作者A"
    sids = [e["sid"] for e in listing["entries"]]
    assert sids == ["BV1xx411c7mD_p1", "BV1xx411c7mD_p2", "BV1xx411c7mD_p3"]
    assert listing["entries"][0]["title"] == "第1集"
    assert listing["entries"][2]["title"] == "P3"          # empty part gets a name
    assert listing["entries"][1]["url"].endswith("?p=2")


def test_entries_from_view_ugc_season_wins_over_pages():
    info = {
        "bvid": "BV1aa411c7aa",
        "title": "tập lẻ",
        "owner": {"name": "作者B"},
        "pages": [{"page": 1, "cid": 1, "part": ""}],
        "ugc_season": {
            "title": "《斗罗》合集",
            "sections": [{"episodes": [
                {"bvid": "BV1aa411c7aa", "title": "第1集"},
                {"bvid": "BV1bb411c7bb", "title": "第2集"},
            ]}],
        },
    }
    listing = entries_from_view(info)
    assert listing["title"] == "《斗罗》合集"
    assert [e["sid"] for e in listing["entries"]] == ["BV1aa411c7aa", "BV1bb411c7bb"]
    assert [e["position"] for e in listing["entries"]] == [1, 2]


def test_entries_from_view_single_video():
    info = {"bvid": "BV1cc411c7cc", "title": "one-shot", "owner": {"name": "x"},
            "pages": [{"page": 1, "cid": 9, "part": ""}]}
    listing = entries_from_view(info)
    assert len(listing["entries"]) == 1
    assert listing["entries"][0]["sid"] == "BV1cc411c7cc"
