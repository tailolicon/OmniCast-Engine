"""The preview must show a subtitle, at the size the editor is asking for."""

import pysubs2
import pytest

from omnicast.api.reup_routes import _preview_subtitle
from omnicast.reup.media.overlay import OverlayConfig, SubtitleStyle


def _track(root, cues):
    d = root / "cache" / "subs" / "hash1"
    d.mkdir(parents=True)
    subs = pysubs2.SSAFile()
    style = pysubs2.SSAStyle()
    style.fontsize = 12          # the stale size the project was last saved with
    subs.styles["Default"] = style
    for start, end, text in cues:
        subs.append(pysubs2.SSAEvent(start=start, end=end, text=text))
    subs.save(str(d / "track.ass"))
    return d / "track.ass"


def test_the_editors_font_size_wins_over_the_saved_track(tmp_path):
    # Dragging the slider used to change nothing on screen: the preview burned
    # the project's own .ass, whose style comes from the last save.
    _track(tmp_path, [(0, 2000, "xin chào")])
    out = _preview_subtitle(tmp_path, OverlayConfig(subtitle=SubtitleStyle(font_size=40)), 1.0)
    assert pysubs2.load(str(out)).styles["Default"].fontsize == 40


def test_a_frame_with_no_speech_still_shows_a_line(tmp_path):
    # Most previewed frames fall between cues; with the real track they showed
    # no subtitle at all, so there was nothing to size against.
    _track(tmp_path, [(0, 2000, "câu đầu"), (60_000, 62_000, "câu sau")])
    out = _preview_subtitle(tmp_path, OverlayConfig(), 30.0)
    events = pysubs2.load(str(out)).events
    assert len(events) == 1
    assert events[0].start == 0 and events[0].end > 30_000


def test_it_picks_the_nearest_real_line(tmp_path):
    _track(tmp_path, [(0, 2000, "câu đầu"), (60_000, 62_000, "câu sau")])
    assert pysubs2.load(str(_preview_subtitle(tmp_path, OverlayConfig(), 59.0))).events[0].text == "câu sau"
    assert pysubs2.load(str(_preview_subtitle(tmp_path, OverlayConfig(), 1.0))).events[0].text == "câu đầu"


def test_position_follows_the_editor_too(tmp_path):
    _track(tmp_path, [(0, 2000, "x")])
    style = SubtitleStyle(alignment=7, margin_l=69, margin_v=43)
    out = _preview_subtitle(tmp_path, OverlayConfig(subtitle=style), 1.0)
    saved = pysubs2.load(str(out)).styles["Default"]
    assert int(saved.alignment) == 7 and saved.marginl == 69 and saved.marginv == 43


def test_no_track_at_all_is_not_an_error(tmp_path):
    # A job previewed before its subtitles exist should still render the frame,
    # just without a caption.
    (tmp_path / "cache" / "subs").mkdir(parents=True)
    assert _preview_subtitle(tmp_path, OverlayConfig(), 5.0) is None
