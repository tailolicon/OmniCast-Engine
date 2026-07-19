"""Visual style presets for Media pipeline."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class StylePreset:
    """Visual editing style. Applied per-channel, consistent across all videos."""
    visual_density: int = 8  # cues per segment target
    zoom_style: str = "ken-burns slow"
    transition_primary: str = "glitch"
    transition_secondary: str = "whip-pan"
    text_animation: str = "zoom-slam"
    music_tempo: str = "slow-build"
    color_grade: str = "dark-cinematic"
    caption_style: str = "bold-word-highlight"


STYLE_PRESETS: dict[str, StylePreset] = {
    "dark_cinematic": StylePreset(
        visual_density=8,
        zoom_style="ken-burns slow",
        transition_primary="glitch",
        transition_secondary="whip-pan",
        text_animation="zoom-slam",
        music_tempo="slow-build",
        color_grade="dark-cinematic",
    ),
    "clean_educational": StylePreset(
        visual_density=6,
        zoom_style="static + slow-zoom",
        transition_primary="fade",
        transition_secondary="cut",
        text_animation="typewriter",
        music_tempo="neutral-upbeat",
        color_grade="bright-clean",
    ),
    "high_energy": StylePreset(
        visual_density=10,
        zoom_style="slam + whip-pan",
        transition_primary="whip-pan",
        transition_secondary="glitch",
        text_animation="bounce",
        music_tempo="high-bpm",
        color_grade="neon-dark",
    ),
    "documentary": StylePreset(
        visual_density=5,
        zoom_style="ken-burns slow",
        transition_primary="fade",
        transition_secondary="dissolve",
        text_animation="fade",
        music_tempo="ambient",
        color_grade="sepia-warm",
    ),
}
