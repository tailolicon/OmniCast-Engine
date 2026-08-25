"""Clip chains — exclusions, staging, and the first/last-frame landing.

Every test pins a way a chain can ship motion that contradicts the board:
a beat replayed after it already happened, a future beat leaked early, a
final clip that drifts off the approved last still, or an FLF prompt sent to
a provider that cannot take a second image and goes hunting for it.
"""

from __future__ import annotations

from pathlib import Path

from omnicast.storyboard import clips
from omnicast.storyboard.clips import (
    ClipPlan,
    build_clip_prompt,
    plan_shot_chain,
    render_shot_chain,
)
from omnicast.storyboard.frames import FramePromptSet, build_frames_for_shot
from omnicast.storyboard.models import (
    CameraShot,
    Entity,
    EntityImage,
    EntityKind,
    Movement,
    RefRole,
    Shot,
    ShotEntityRef,
    Storyboard,
)


def _shot(**kw) -> Shot:
    base = dict(shot_id="s1", board_id="b", index=3,
                camera_shot=CameraShot.MS, movement=Movement.STATIC)
    base.update(kw)
    return Shot(**base)


# --------------------------------------------------------------------------
# Scope exclusions — the firewall must reach the MODEL, not only the gate
# --------------------------------------------------------------------------

def test_completed_beats_become_do_not_replay():
    shot = _shot(beats_completed=["Minh drops the keys.", "the door slams"])
    prompt = build_clip_prompt(shot, 0, 1)
    assert "Already happened before this clip: Minh drops the keys; " \
           "the door slams. Do not replay it." in prompt


def test_reserved_beats_become_do_not_yet():
    shot = _shot(beats_reserved=["she opens the letter"])
    prompt = build_clip_prompt(shot, 0, 1)
    assert "Do not yet show: she opens the letter. That belongs to a later " \
           "shot." in prompt


def test_no_beats_no_exclusion_lines():
    prompt = build_clip_prompt(_shot(), 0, 1)
    assert "Already happened" not in prompt
    assert "Do not yet show" not in prompt


def test_exclusions_capped_at_three_each():
    shot = _shot(beats_completed=[f"beat {i}" for i in range(6)])
    prompt = build_clip_prompt(shot, 0, 1)
    assert "beat 2" in prompt and "beat 3" not in prompt


# --------------------------------------------------------------------------
# First/last-frame prompt — say the path, never re-say the endpoints
# --------------------------------------------------------------------------

def test_flf_prompt_names_both_frames_and_the_path():
    prompt = build_clip_prompt(_shot(), 0, 1, "she reaches the door",
                               to_last_frame=True)
    assert "first attached image is the first frame" in prompt
    assert "second attached image is the last frame" in prompt
    assert "one continuous take" in prompt
    assert "Along the way: she reaches the door." in prompt


def test_flf_prompt_drops_the_settle_tail():
    # "End on a settled pose" belongs to open-ended i2v clips; an FLF clip's
    # ending IS the attached last frame, and asking for a settle on top of it
    # fights the interpolation target.
    prompt = build_clip_prompt(_shot(), 0, 3, to_last_frame=True)
    assert "settled, continuable pose" not in prompt


# --------------------------------------------------------------------------
# Planning — only the FINAL clip lands on the canonical last still
# --------------------------------------------------------------------------

def test_end_anchor_lands_only_on_final_clip():
    plans = plan_shot_chain(_shot(), 18.0, "/stills/first.png",
                            end_anchor="/stills/last.png", clip_seconds=6)
    assert len(plans) == 3
    assert [p.end_frame for p in plans] == ["", "", "/stills/last.png"]
    assert "last frame" in plans[-1].prompt
    assert "last frame" not in plans[0].prompt


def test_no_end_anchor_plans_plain_i2v():
    plans = plan_shot_chain(_shot(), 12.0, "/stills/first.png")
    assert all(p.end_frame == "" for p in plans)


def test_single_clip_shot_gets_both_anchors():
    plans = plan_shot_chain(_shot(), 5.0, "/a.png", end_anchor="/z.png")
    assert len(plans) == 1
    assert plans[0].start_frame == "/a.png"
    assert plans[0].end_frame == "/z.png"


# --------------------------------------------------------------------------
# Rendering — capability decides, and the decision is recorded
# --------------------------------------------------------------------------

class _Provider:
    """Records every convert() call; optionally advertises FLF support."""

    id = "stub"

    def __init__(self, tmp: Path, *, flf: bool = False):
        self.tmp = tmp
        self.calls: list[dict] = []
        if flf:
            self.supports_last_frame = True

    async def convert(self, image_path, prompt, **kwargs):
        self.calls.append({"image_path": image_path, "prompt": prompt, **kwargs})
        out = Path(kwargs["output_path"])
        out.write_bytes(b"x" * 32)
        return str(out)


async def test_render_passes_last_frame_to_capable_provider(tmp_path,
                                                            monkeypatch):
    # The tail extraction shells out to ffmpeg; a chain of one clip never
    # needs it, but the code path still runs — stub it to stay hermetic.
    monkeypatch.setattr(clips, "extract_last_frame", lambda *_a, **_k: "")
    provider = _Provider(tmp_path, flf=True)
    result = await render_shot_chain(
        _shot(), 5.0, "/stills/first.png", provider, tmp_path,
        end_anchor="/stills/last.png")
    assert provider.calls[-1]["last_image_path"] == "/stills/last.png"
    assert not any("falls back" in n for n in result.notes)


async def test_render_falls_back_when_provider_cannot_land(tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(clips, "extract_last_frame", lambda *_a, **_k: "")
    provider = _Provider(tmp_path)  # no supports_last_frame at all
    result = await render_shot_chain(
        _shot(), 5.0, "/stills/first.png", provider, tmp_path,
        end_anchor="/stills/last.png")
    call = provider.calls[-1]
    assert "last_image_path" not in call
    # The prompt must NOT promise a second image the provider never attached.
    assert "last frame" not in call["prompt"]
    assert any("falls back" in n for n in result.notes)


# --------------------------------------------------------------------------
# Vertical staging — the clause exists only when the channel asks for it
# --------------------------------------------------------------------------

def _board_one_shot() -> Storyboard:
    entity = Entity(
        entity_id="e1", board_id="b", kind=EntityKind.CHARACTER, name="Minh",
        images=[EntityImage(image_id="i1", entity_id="e1", path="/r/m.png",
                            role=RefRole.IDENTITY, approved=True)])
    shot = Shot(shot_id="s1", board_id="b", index=0,
                cast=[ShotEntityRef(entity_id="e1", index=0)],
                movement=Movement.STATIC)
    return Storyboard(board_id="b", channel_id="ch", entities=[entity],
                      shots=[shot])


def test_static_camera_with_action_still_gets_first_and_last():
    # Locked camera, moving subject: the scene's end state differs from its
    # start, so a single KEY still would leave the chain nothing to land on.
    from omnicast.storyboard.frames import plan_frame_types
    from omnicast.storyboard.models import FrameType

    moving_subject = _shot(movement=Movement.STATIC,
                           action_beats=["the fold springs open"])
    assert plan_frame_types(moving_subject) == [FrameType.FIRST,
                                                FrameType.LAST]
    truly_still = _shot(movement=Movement.STATIC)
    assert plan_frame_types(truly_still) == [FrameType.KEY]


def test_vertical_safe_appends_staging_clause():
    board = _board_one_shot()
    prompts = FramePromptSet(key="Minh sets the keys on the table.")
    frames, _ = build_frames_for_shot(board.shots[0], board, prompts,
                                      vertical_safe=True)
    assert "Staging: keep the subject" in frames[0].base_prompt


def test_default_has_no_staging_clause():
    board = _board_one_shot()
    prompts = FramePromptSet(key="Minh sets the keys on the table.")
    frames, _ = build_frames_for_shot(board.shots[0], board, prompts)
    assert "Staging:" not in frames[0].base_prompt


# --------------------------------------------------------------------------
# Provider capability flag — SDK-gated, importable without credentials
# --------------------------------------------------------------------------

def test_gemini_provider_advertises_flf_from_sdk():
    from google.genai import types

    from omnicast.media.providers.video_gemini import GeminiVideoProvider

    expected = "last_frame" in types.GenerateVideosConfig.model_fields
    assert GeminiVideoProvider.supports_last_frame is expected


def test_clipplan_dict_round_trips_end_frame():
    plan = ClipPlan(shot_id="s", shot_index=1, ordinal=0, seconds=6,
                    start_frame="/a.png", reanchored=True, prompt="p",
                    end_frame="/z.png")
    assert plan.as_dict()["end_frame"] == "/z.png"
