"""Prompt builder for image and video generation.

Builds full prompts by combining style guide, default instructions,
and scene-specific prompts. Ported from AutoVio.
"""

from omnicast.media.style_guide import StyleGuide


# Default instructions (from AutoVio)
DEFAULT_IMAGE_INSTRUCTION = (
    "Generate a high-quality photorealistic image. Cinematic composition, "
    "natural lighting, sharp focus, professional photography quality."
)

DEFAULT_VIDEO_INSTRUCTION = (
    "Animate this image into a smooth 5-second video clip. Subtle natural "
    "motion, cinematic camera movement, no jarring cuts."
)


def build_image_style_prefix(guide: StyleGuide) -> str:
    """Build style prefix for image generation prompt.
    
    Ported from AutoVio image.ts:7-27
    Combines color palette, tone, and tempo into visual style description.
    """
    parts = []
    
    # Base: always lead with photorealistic default when we have any style guide
    parts.append("Professional photography, natural lighting, lifelike textures")
    
    if guide.color_palette:
        color_desc = _describe_color_palette(guide.color_palette)
        parts.append(color_desc)
    
    if guide.tone:
        style_keywords = _tone_to_visual_style(guide.tone)
        parts.append(style_keywords)
    
    if guide.tempo:
        composition_style = _tempo_to_composition(guide.tempo)
        parts.append(composition_style)
    
    return ", ".join(parts)


def build_video_style_prefix(guide: StyleGuide) -> str:
    """Build style prefix for video generation prompt.
    
    Ported from AutoVio video.ts:6-19
    Combines camera style, tempo, and tone into motion description.
    """
    parts = []
    
    if guide.camera_style:
        parts.append(guide.camera_style)
    
    if guide.tempo:
        parts.append(_tempo_to_motion(guide.tempo))
    
    if guide.tone:
        parts.append(_tone_to_cinematic(guide.tone))
    
    return ", ".join(parts) if parts else ""


def build_full_image_prompt(
    scene_image_prompt: str,
    guide: StyleGuide,
    extra_instruction: str = ""
) -> str:
    """Build full image generation prompt.
    
    Format: [style_prefix]\n\n[default_or_custom_instruction]\n\n[scene_prompt]
    
    Args:
        scene_image_prompt: The scene-specific image prompt
        guide: Style guide for visual direction
        extra_instruction: Optional custom instruction override
    
    Returns:
        Full formatted prompt for image generation
    """
    parts = []
    
    prefix = build_image_style_prefix(guide)
    if prefix:
        parts.append(prefix)
    
    parts.append(extra_instruction or DEFAULT_IMAGE_INSTRUCTION)
    parts.append(scene_image_prompt)
    
    return "\n\n".join(parts)


def build_full_video_prompt(
    scene_video_prompt: str,
    guide: StyleGuide,
    extra_instruction: str = ""
) -> str:
    """Build full video generation prompt.
    
    Format: [style_prefix]\n\n[default_or_custom_instruction]\n\n[scene_prompt]
    
    Args:
        scene_video_prompt: The scene-specific video prompt
        guide: Style guide for visual direction
        extra_instruction: Optional custom instruction override
    
    Returns:
        Full formatted prompt for video generation
    """
    parts = []
    
    prefix = build_video_style_prefix(guide)
    if prefix:
        parts.append(prefix)
    
    parts.append(extra_instruction or DEFAULT_VIDEO_INSTRUCTION)
    parts.append(scene_video_prompt)
    
    return "\n\n".join(parts)


def format_style_guide_for_prompt(guide: StyleGuide) -> str:
    """Format StyleGuide into markdown for LLM prompts.
    
    Ported from AutoVio scenario.ts:7-33
    """
    parts = ["## Project Style Guide"]
    
    if guide.tone:
        parts.append(f"**Tone:** {guide.tone}")
    if guide.color_palette:
        parts.append(f"**Color Palette:** {', '.join(guide.color_palette)}")
    if guide.tempo:
        parts.append(f"**Tempo:** {guide.tempo}-paced")
    if guide.camera_style:
        parts.append(f"**Camera Style:** {guide.camera_style}")
    if guide.brand_voice:
        parts.append(f"**Brand Voice:** {guide.brand_voice}")
    if guide.must_include:
        parts.append(f"**Must Include:** {', '.join(guide.must_include)}")
    if guide.must_avoid:
        parts.append(f"**Must Avoid:** {', '.join(guide.must_avoid)}")
    
    return "\n".join(parts)


# Helper functions (ported from AutoVio)

def _describe_color_palette(hex_codes: list[str]) -> str:
    """Describe color palette in natural language."""
    colors = " and ".join(_hex_to_color_name(hex_code) for hex_code in hex_codes)
    return f"rich {colors} color palette"


def _hex_to_color_name(hex_code: str) -> str:
    """Convert hex code to simple color name."""
    if not hex_code or not hex_code.startswith("#"):
        return "neutral"
    
    try:
        r = int(hex_code[1:3], 16)
        g = int(hex_code[3:5], 16)
        b = int(hex_code[5:7], 16)
        
        if r > g and r > b:
            return "red"
        elif g > r and g > b:
            return "green"
        elif b > r and b > g:
            return "blue"
        elif r > 200 and g > 200 and b > 200:
            return "bright"
        else:
            return "neutral"
    except (ValueError, IndexError):
        return "neutral"


def _tone_to_visual_style(tone: str) -> str:
    """Convert tone to visual style keywords."""
    lower = tone.lower()
    
    if "energetic" in lower or "dynamic" in lower:
        return "dynamic but realistic composition, high contrast, natural lighting"
    elif "professional" in lower or "corporate" in lower:
        return "clean composition, balanced lighting, professional quality"
    elif "calm" in lower or "peaceful" in lower:
        return "soft natural lighting, gentle composition, serene atmosphere"
    elif "playful" in lower or "fun" in lower:
        return "lifelike composition, natural lighting, playful but realistic mood"
    else:
        return "high-quality, realistic composition"


def _tempo_to_composition(tempo: str) -> str:
    """Convert tempo to composition style."""
    t = tempo.lower()
    
    if "fast" in t:
        return "dynamic framing, bold composition"
    elif "slow" in t:
        return "steady composition, balanced framing"
    else:
        return "balanced, natural composition"


def _tempo_to_motion(tempo: str) -> str:
    """Convert tempo to motion description."""
    t = tempo.lower()
    
    if "fast" in t:
        return "quick motion, dynamic camera movement"
    elif "slow" in t:
        return "slow motion, smooth camera movement"
    else:
        return "steady camera movement"


def _tone_to_cinematic(tone: str) -> str:
    """Convert tone to cinematic style."""
    lower = tone.lower()
    
    if "energetic" in lower:
        return "energetic pacing, dynamic cuts"
    elif "professional" in lower:
        return "smooth professional transitions"
    elif "calm" in lower:
        return "gentle pacing, soft transitions"
    else:
        return "cinematic quality"
