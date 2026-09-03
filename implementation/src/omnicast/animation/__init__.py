"""Animation subsystem (strategic review §7.1, P2 in §15).

THE REVIEW'S POINT, WHICH THIS PACKAGE TAKES LITERALLY:

    "Sinh nhiều ảnh AI rồi crossfade không thể thay thế việc này."

Generating a pile of AI images and crossfading them is not animation. Hand-drawn
storytelling channels have a character rig, a pose library, facial expressions,
lip sync, squash-and-stretch, anticipation, comic timing, prop interaction,
camera choreography, and keyframes with deliberate easing. §7.1 says plainly
that serving those channels needs a subsystem, not a better image prompt.

WHAT THIS IS, HONESTLY

This is the SPECIFICATION AND PLANNING layer of that subsystem, plus the parts
that are pure computation and therefore finishable today:

  bible     the character bible — identity, pose and expression inventory, and
            the continuity rules a renderer must obey
  timing    keyframes, easing, anticipation and squash-and-stretch as real
            curves; comic timing as measurable beats
  lipsync   phoneme -> viseme timing from the transcript cues we already have

It is NOT a renderer. Nothing here draws a frame, and `readiness()` says so in
the same measured/missing vocabulary the rest of the system uses, so this
package can never be mistaken for a finished animation pipeline the way
`video_intel` was once mistaken for a working analyzer.

The production router already refuses to route a scene to ANIMATION unless the
channel declares `character_animation`, and falls back with a recorded reason.
That refusal stays exactly as it is until a renderer exists to honour it.
"""

from omnicast.animation.bible import (
    CharacterBible,
    ContinuityIssue,
    Expression,
    Pose,
    check_continuity,
    load_bible,
    readiness,
)
from omnicast.animation.lipsync import (
    VISEMES,
    VisemeCue,
    text_to_visemes,
    visemes_for_transcript,
)
from omnicast.animation.timing import (
    EASINGS,
    Keyframe,
    anticipation_beats,
    comic_timing_report,
    ease,
    interpolate,
    squash_and_stretch,
)

__all__ = [
    "CharacterBible", "ContinuityIssue", "Expression", "Pose", "check_continuity",
    "load_bible", "readiness", "VISEMES", "VisemeCue", "text_to_visemes",
    "visemes_for_transcript", "EASINGS", "Keyframe", "anticipation_beats",
    "comic_timing_report", "ease", "interpolate", "squash_and_stretch",
]
