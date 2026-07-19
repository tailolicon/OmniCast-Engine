"""Media provider abstraction layer for OmniCast.

This module provides a unified interface for image and video generation
across different providers (Gemini, ComfyUI, etc.).
"""

from omnicast.media.providers.interfaces import (
    IImageProvider,
    IVideoProvider,
    ModelOption,
)

__all__ = ["IImageProvider", "IVideoProvider", "ModelOption"]
