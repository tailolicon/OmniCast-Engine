"""StyleGuide model for visual direction.

Defines the visual style parameters for media generation.
"""

from pydantic import BaseModel, Field


class StyleGuide(BaseModel):
    """Visual style guide for media generation.
    
    tone: "energetic" | "professional" | "calm" | "playful"
    color_palette: hex codes ["#FF0000", "#00FF00"]
    tempo: "fast" | "medium" | "slow"
    camera_style: "static documentary" | "dynamic handheld" | etc
    brand_voice: free text
    must_include: list of required elements
    must_avoid: list of elements to avoid
    """
    tone: str = ""
    color_palette: list[str] = Field(default_factory=list)
    tempo: str = ""
    camera_style: str = ""
    brand_voice: str = ""
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
