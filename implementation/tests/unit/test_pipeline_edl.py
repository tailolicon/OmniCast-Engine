"""plan.json — every test pins a way a plan could waste money or lie.

The two lies that matter: a plan that bills more generations than the operator
signed for, and an assembled video that breaks the channel's motion promise
while every individual segment looks fine.
"""

from __future__ import annotations

from omnicast.pipeline.edl import (
    CaptionLine,
    DeliveryPromise,
    NarrationLine,
    PromiseType,
    Segment,
    SegmentLayer,
    SegmentRole,
    SegmentSource,
    Tracks,
    VideoPlan,
    assess_delivery,
    load_plan,
    save_plan,
    validate_plan,
)


def _seg(sid: str, order: int, *, source=SegmentSource.GENERATE,
         layer=SegmentLayer.PRIMARY, sec=6.0, spec=None, produced="",
         **kw) -> Segment:
    base_spec = {SegmentSource.GENERATE: {"prompt": "p"},
                 SegmentSource.EDIT: {"input_id": "a", "in_sec": 0, "out_sec": 2},
                 SegmentSource.COMPOSE: {"kind": "title-card"},
                 SegmentSource.PROVIDED: {"asset_id": "x"}}[source]
    return Segment(segment_id=sid, order=order, source=source, layer=layer,
                   target_sec=sec, spec=spec if spec is not None else base_spec,
                   produced_path=produced, **kw)


def _plan(segments, *, billable=None, promise=None, tracks=None,
          total=None) -> VideoPlan:
    if billable is None:
        billable = sum(1 for s in segments
                       if s.source is SegmentSource.GENERATE)
    if total is None:
        total = sum(s.target_sec for s in segments
                    if s.layer is SegmentLayer.PRIMARY) or 30.0
    return VideoPlan(plan_id="pl1", total_target_sec=total,
                     segments=segments, billable_generations=billable,
                     delivery_promise=promise or DeliveryPromise(),
                     tracks=tracks or Tracks())


# -- validation -------------------------------------------------------------

def test_valid_plan_has_no_issues():
    plan = _plan([_seg("s1", 0), _seg("s2", 1)])
    assert validate_plan(plan) == []


def test_duplicate_orders_flagged():
    plan = _plan([_seg("s1", 0), _seg("s2", 0)])
    assert any("orders are not unique" in i for i in validate_plan(plan))


def test_missing_spec_key_flagged():
    plan = _plan([_seg("s1", 0, spec={})])
    assert any("requires spec['prompt']" in i for i in validate_plan(plan))


def test_billable_count_must_match_signed_count():
    plan = _plan([_seg("s1", 0), _seg("s2", 1)], billable=1)
    assert any("signed cost and the real cost disagree" in i
               for i in validate_plan(plan))


def test_overlay_must_name_its_primary():
    over = _seg("o1", 1, source=SegmentSource.COMPOSE,
                layer=SegmentLayer.OVERLAY)
    plan = _plan([_seg("s1", 0), over])
    assert any("must name the primary segment" in i for i in validate_plan(plan))


def test_double_voice_is_flagged():
    seg = _seg("s1", 0, spec={"prompt": "p", "narration": "hello"})
    tracks = Tracks(narration=[NarrationLine(line_id="n1", text="hi")])
    plan = _plan([seg], tracks=tracks)
    assert any("mixed twice" in i for i in validate_plan(plan))


def test_promised_source_footage_must_exist():
    plan = _plan([_seg("s1", 0)],
                 promise=DeliveryPromise(type=PromiseType.SOURCE_LED,
                                         source_required=True))
    assert any("no edit/provided segment" in i for i in validate_plan(plan))


# -- promise arithmetic -----------------------------------------------------

def test_slideshow_fails_motion_floor(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    segs = [
        _seg("m1", 0, sec=6.0, produced=str(clip)),
        _seg("c1", 1, source=SegmentSource.COMPOSE, sec=18.0,
             produced=str(clip)),
    ]
    report = assess_delivery(_plan(segs))
    assert report["motion_ratio"] == 0.25
    assert report["ok"] is False        # motion_led floor is 0.7


def test_motion_led_passes_when_motion_carries(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    segs = [_seg("m1", 0, sec=24.0, produced=str(clip)),
            _seg("c1", 1, source=SegmentSource.COMPOSE, sec=6.0,
                 produced=str(clip))]
    assert assess_delivery(_plan(segs))["ok"] is True


def test_unproduced_segments_do_not_count(tmp_path):
    segs = [_seg("m1", 0, sec=24.0)]     # nothing on disk yet
    report = assess_delivery(_plan(segs))
    assert report["produced_seconds"] == 0


def test_three_identical_segments_warn(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    segs = [_seg(f"m{i}", i, produced=str(clip)) for i in range(3)]
    report = assess_delivery(_plan(segs))
    assert any("reads as a loop" in w for w in report["warnings"])


# -- write-back and resume --------------------------------------------------

def test_with_produced_updates_one_segment_only(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    plan = _plan([_seg("s1", 0), _seg("s2", 1)])
    updated = plan.with_produced("s1", str(clip))
    assert updated.segment("s1").produced
    assert not updated.segment("s2").produced
    assert [s.segment_id for s in updated.pending()] == ["s2"]


def test_plan_round_trips_through_disk(tmp_path):
    plan = _plan([_seg("s1", 0)],
                 tracks=Tracks(captions=[CaptionLine(
                     caption_id="c1", text="hi", start_sec=0.0, end_sec=1.5)]))
    save_plan(plan, tmp_path)
    loaded = load_plan(tmp_path)
    assert loaded is not None
    assert loaded.segment("s1").spec == {"prompt": "p"}
    assert loaded.tracks.captions[0].text == "hi"


def test_load_missing_plan_returns_none(tmp_path):
    assert load_plan(tmp_path) is None


def test_chapter_role_exists_for_long_video_reassembly():
    # The long-video composer tags 16:9 chapter cards with this role; losing
    # it silently would break the Shorts→long re-assembly path.
    seg = _seg("ch1", 0, source=SegmentSource.COMPOSE)
    assert seg.model_copy(update={"role": SegmentRole.CHAPTER}).role \
        is SegmentRole.CHAPTER
