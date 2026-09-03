"""Reup output lands in the per-channel product layout, not the scratch dir."""

import json

import pytest

from omnicast.reup import publish as pub


@pytest.fixture(autouse=True)
def products_root(tmp_path, monkeypatch):
    root = tmp_path / "products"
    monkeypatch.setattr("omnicast.storage.products.PRODUCTS_DIR", root)
    return root


def _video(tmp_path, name="export.mp4", data=b"video-bytes"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_published_video_lands_under_its_channel(tmp_path, products_root):
    pd = pub.publish_reup_product(
        channel="true_dread_files_us", aweme_id="7671126668437720356",
        exported_video=_video(tmp_path), title="Hồng Ma Tinh Tinh",
    )
    assert pd.parent == products_root / "true_dread_files_us"
    assert (pd / "video.mp4").read_bytes() == b"video-bytes"


def test_a_job_with_no_channel_still_lands_somewhere_findable(tmp_path, products_root):
    pd = pub.publish_reup_product(
        channel=None, aweme_id="123", exported_video=_video(tmp_path), title="x",
    )
    assert pd.parent == products_root / pub.UNASSIGNED_CHANNEL


def test_re_exporting_updates_the_same_folder(tmp_path, products_root):
    first = pub.publish_reup_product(
        channel="c", aweme_id="777", exported_video=_video(tmp_path), title="Tựa cũ",
    )
    # Title changes between runs; looking the folder up by title would scatter
    # a second copy next to the first.
    second = pub.publish_reup_product(
        channel="c", aweme_id="777",
        exported_video=_video(tmp_path, "v2.mp4", b"newer"), title="Tựa đã sửa",
    )
    assert first == second
    assert len(list((products_root / "c").iterdir())) == 1
    assert (second / "video.mp4").read_bytes() == b"newer"


def test_a_different_source_gets_its_own_folder(tmp_path, products_root):
    a = pub.publish_reup_product(channel="c", aweme_id="1", exported_video=_video(tmp_path), title="a")
    b = pub.publish_reup_product(channel="c", aweme_id="2", exported_video=_video(tmp_path, "b.mp4"), title="b")
    assert a != b


def test_meta_records_where_the_video_came_from(tmp_path, products_root):
    pd = pub.publish_reup_product(
        channel="c", aweme_id="99", exported_video=_video(tmp_path), title="Tựa Việt",
        source_url="https://www.douyin.com/video/99", segment_count=362, review_pending=81,
    )
    meta = json.loads((pd / "meta.json").read_text(encoding="utf-8"))
    assert meta["kind"] == "reup"
    assert meta["source_aweme_id"] == "99"
    assert meta["source_url"].endswith("/99")
    assert (meta["source_language"], meta["target_language"]) == ("zh", "vi")
    assert meta["segment_count"] == 362 and meta["review_pending"] == 81


def test_subtitles_and_script_travel_with_the_video(tmp_path, products_root):
    srt = tmp_path / "track.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nxin chào\n", encoding="utf-8")
    pd = pub.publish_reup_product(
        channel="c", aweme_id="5", exported_video=_video(tmp_path), title="t",
        subtitle_paths=[srt], script_lines=["câu một", "câu hai"],
    )
    assert (pd / "subtitles.srt").exists()
    assert (pd / "script.txt").read_text(encoding="utf-8").splitlines() == ["câu một", "câu hai"]


def test_publishing_does_not_move_the_export(tmp_path, products_root):
    # The export cache checks its output still exists; moving it would force a
    # full re-encode on the next export.
    video = _video(tmp_path)
    pub.publish_reup_product(channel="c", aweme_id="8", exported_video=video, title="t")
    assert video.exists()


def test_the_product_is_a_copy_not_a_link_to_the_export(tmp_path, products_root):
    # A hard link means the next render rewrites the delivered video in place,
    # and an interrupted render leaves the published product corrupt.
    video = _video(tmp_path)
    pd = pub.publish_reup_product(channel="c", aweme_id="10", exported_video=video, title="t")
    published = pd / "video.mp4"
    assert published.stat().st_ino != video.stat().st_ino or published.stat().st_nlink == 1
    video.write_bytes(b"a later render overwrote the export")
    assert published.read_bytes() == b"video-bytes", "the published copy must not follow"


def test_no_staging_file_is_left_behind(tmp_path, products_root):
    pd = pub.publish_reup_product(
        channel="c", aweme_id="11", exported_video=_video(tmp_path), title="t")
    assert not list(pd.glob("*.incoming"))


def test_a_missing_export_does_not_crash_the_publish(tmp_path, products_root):
    pd = pub.publish_reup_product(
        channel="c", aweme_id="9", exported_video=tmp_path / "gone.mp4", title="t",
    )
    assert (pd / "meta.json").exists()
    assert not (pd / "video.mp4").exists()


def test_the_source_cover_is_published_as_the_thumb(tmp_path, products_root):
    cover = tmp_path / "clip_cover.jpg"
    cover.write_bytes(b"jpeg")
    pd = pub.publish_reup_product(
        channel="c", aweme_id="20", exported_video=_video(tmp_path), title="t",
        cover_path=cover,
    )
    assert (pd / "thumb.jpg").read_bytes() == b"jpeg"


def test_a_missing_cover_is_simply_absent(tmp_path, products_root):
    # No thumbnail must never fail a dub that is otherwise fine.
    pd = pub.publish_reup_product(
        channel="c", aweme_id="21", exported_video=_video(tmp_path), title="t",
        cover_path=tmp_path / "gone.jpg",
    )
    assert (pd / "video.mp4").exists()
    assert not list(pd.glob("thumb.*"))
