"""Provider interface definitions for media generation.

This module defines Protocol-based interfaces for image and video providers,
following the structural typing pattern from AutoVio.
"""

from typing import Protocol, NamedTuple


class ModelOption(NamedTuple):
    """Represents a model option available from a provider."""
    id: str
    name: str
    description: str = ""


class IImageProvider(Protocol):
    """Protocol for image generation providers.
    
    Any class implementing this protocol must provide the required attributes
    and methods. Python's structural typing will check for compatibility at
    runtime without explicit inheritance.
    """
    
    id: str
    """Unique identifier for the provider (e.g., 'gemini', 'comfyui')."""
    capability: str
    """Capability kind exposed to CapabilityBus, usually 'image'."""
    cost_per_unit: float
    """Estimated cost per generated image for budget planning."""
    rate_limit: dict
    """Provider-specific rate limit metadata for UI/budget guardrails."""
    
    name: str
    """Human-readable name of the provider."""

    models: list[ModelOption]
    """List of available models for this provider."""

    supports_reference_images: bool
    """Whether `generate()` honours per-call ordered reference images.

    Declared rather than assumed. A provider that accepts the argument and
    ignores it yields character drift that reads as a prompt-writing bug, so
    callers must check this before relying on reference conditioning and record
    a degradation when it is False. Providers predating this flag simply lack
    the attribute; use `getattr(provider, "supports_reference_images", False)`.
    """

    max_reference_images: int
    """Upper bound on references per call. Callers decide what to drop."""

    async def health_check(self) -> dict:
        """Return provider health metadata without generating media."""
        ...

    async def generate(
        self,
        prompt: str,
        *,
        negative: str = "",
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
        reference_images: list[str] | None = None,
        reference_labels: list[str] | None = None,
    ) -> str:
        """Generate an image from a text prompt.

        Args:
            prompt: The text prompt describing the desired image.
            negative: Negative prompt to avoid certain elements.
            model: Optional model ID to use. If None, uses provider default.
            resolution: Optional (width, height) tuple. If None, uses provider default.
            output_path: Absolute path where the generated image should be saved.
            reference_images: Ordered reference paths. Position is meaningful:
                the Nth entry is what the prompt's Nth label names. Only
                honoured when `supports_reference_images` is True.
            reference_labels: Labels parallel to `reference_images`.

        Returns:
            Absolute path to the generated image file.

        Raises:
            MediaError: If image generation fails.
        """
        ...


class IVideoProvider(Protocol):
    """Protocol for video generation providers.
    
    Video providers convert an image into a short video clip based on a prompt.
    """
    
    id: str
    """Unique identifier for the provider (e.g., 'gemini', 'runway')."""
    capability: str
    """Capability kind exposed to CapabilityBus, usually 'video'."""
    cost_per_unit: float
    """Estimated cost per generated clip for budget planning."""
    rate_limit: dict
    """Provider-specific rate limit metadata for UI/budget guardrails."""
    
    name: str
    """Human-readable name of the provider."""
    
    models: list[ModelOption]
    """List of available models for this provider."""
    
    async def health_check(self) -> dict:
        """Return provider health metadata without generating media."""
        ...
    
    async def convert(
        self,
        image_path: str,
        prompt: str,
        *,
        duration: int = 5,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
        last_image_path: str | None = None,
    ) -> str:
        """Convert an image into a video clip.

        Args:
            image_path: Absolute path to the source image.
            prompt: Text prompt describing the desired video motion/style.
            duration: Duration of the video in seconds.
            model: Optional model ID to use. If None, uses provider default.
            resolution: Optional (width, height) tuple. If None, uses provider default.
            output_path: Absolute path where the generated video should be saved.
            last_image_path: Optional still the clip must END on (first/last-
                frame interpolation). Callers MUST check the provider's
                `supports_last_frame` attribute (absent == False) before
                passing this — providers without the capability do not accept
                the keyword at all, so the plan can fall back to plain i2v
                instead of dying mid-render.

        Returns:
            Absolute path to the generated video file.

        Raises:
            MediaError: If video generation fails.
        """
        ...


class ITTSProvider(Protocol):
    """Protocol for Text-to-Speech (TTS) providers."""
    
    id: str
    capability: str
    name: str
    models: list[ModelOption]
    cost_per_unit: float
    rate_limit: dict
    
    async def health_check(self) -> dict:
        """Return provider health metadata without synthesizing audio."""
        ...
    
    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,
        output_path: str,
    ) -> str:
        """Generate audio from text.
        
        Args:
            text: Text to synthesize.
            model: Optional model/voice ID to use.
            voice_clone_path: Optional path to an audio file for cloning.
            output_path: Absolute path where the audio should be saved.
            
        Returns:
            Absolute path to the generated audio file.
        """
        ...
