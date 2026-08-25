"""Storyboard — cast registry, shot list, and reference-conditioned frames.

The gap this fills: before it, a scene was a free-text `image_prompt` plus a
channel-wide anchor set, which cannot say WHO is in a shot, WHICH image speaks
for them, or WHAT that image is allowed to control. See `models.py` for the
vocabulary, `binding.py` for the token↔image contract that makes reference
conditioning actually bind, and `continuity.py` for the fail-closed gate.
"""

from omnicast.storyboard.models import (  # noqa: F401
    Angle,
    BoardStatus,
    CameraShot,
    Entity,
    EntityImage,
    EntityKind,
    Frame,
    FrameType,
    ImageSource,
    Movement,
    RefMapping,
    RefRole,
    Shot,
    ShotEntityRef,
    Storyboard,
    normalize_name,
)

__all__ = [
    "Angle", "BoardStatus", "CameraShot", "Entity", "EntityImage", "EntityKind",
    "Frame", "FrameType", "ImageSource", "Movement", "RefMapping", "RefRole",
    "Shot", "ShotEntityRef", "Storyboard", "normalize_name",
]
