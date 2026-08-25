"""Round trips, not scenes, are what the translation stage pays for."""

from omnicast.reup.translate.contextual_pipeline import CONTEXTUAL_STAGE_BATCH_SIZE
from omnicast.reup.translate.contextual_runtime import NARRATION_FAST_BATCH_SIZE
from omnicast.reup.translate.scene_chunker import (
    DEFAULT_SCENE_GAP_MS,
    DEFAULT_SCENE_MAX_SEGMENTS,
    chunk_segments_into_scenes,
)


def _rows(count, *, gap_ms):
    """Short lines separated by a fixed gap — short-burst drama dialogue."""
    rows, t = [], 0
    for i in range(count):
        rows.append({
            "segment_id": f"s{i}", "segment_index": i,
            "start_ms": t, "end_ms": t + 800, "source_text": "你好啊",
        })
        t += 800 + gap_ms
    return rows


def test_a_breath_between_lines_is_not_a_scene_change():
    # At the old 1500ms threshold every 2s pause split a scene, turning 369
    # lines into 48 scenes — 48 LLM round trips at ~13s of claude-cli startup
    # each, which was 13 of the 15 minutes.
    # 20 lines x 2.8s stays inside the 75s duration cap, so this isolates the
    # gap rule from the other two limiters.
    scenes = chunk_segments_into_scenes(_rows(20, gap_ms=2000))
    assert len(scenes) == 1, "a 2s pause mid-conversation must not split"


def test_a_real_pause_still_splits():
    scenes = chunk_segments_into_scenes(_rows(6, gap_ms=DEFAULT_SCENE_GAP_MS + 500))
    assert len(scenes) == 6


def test_the_batch_can_hold_a_whole_scene():
    # Raising the scene size achieves nothing if the batch re-splits it: the
    # call count is what costs, and it is driven by batches, not scenes.
    assert NARRATION_FAST_BATCH_SIZE >= DEFAULT_SCENE_MAX_SEGMENTS


def test_a_long_scene_is_still_capped():
    # Unbounded scenes would hand the model an entire video in one prompt.
    scenes = chunk_segments_into_scenes(_rows(100, gap_ms=100))
    assert all(len(s.segments) <= DEFAULT_SCENE_MAX_SEGMENTS for s in scenes)


def test_batch_sizes_are_worth_a_round_trip():
    # pyvideotrans sends 50 lines per AI request; batching in single digits was
    # our own invention and cost a full process spawn per handful of lines.
    assert CONTEXTUAL_STAGE_BATCH_SIZE >= 16
    assert NARRATION_FAST_BATCH_SIZE >= 32


def test_a_sparse_scene_is_capped_by_wall_clock_too():
    """The third limiter, and the one that surprised me while writing these.

    Gap and line count are not enough: sparse dialogue reaches 75s of runtime
    long before it reaches 40 lines, and a scene that spans minutes stops being
    one scene.
    """
    from omnicast.reup.translate.scene_chunker import DEFAULT_SCENE_MAX_DURATION_MS

    scenes = chunk_segments_into_scenes(_rows(40, gap_ms=2000))
    assert len(scenes) > 1
    for scene in scenes:
        assert scene.end_ms - scene.start_ms <= DEFAULT_SCENE_MAX_DURATION_MS + 3000
