"""Gemini Image Provider implementation.

Uses Google GenAI SDK to generate images via Gemini 2.5 Flash Image.
"""

import base64
from pathlib import Path

from google import genai
from google.genai import types

from omnicast.config.settings import get_settings
from omnicast.media.providers.interfaces import IImageProvider, ModelOption


class MediaError(Exception):
    """Base exception for media generation errors."""
    pass


class GeminiImageProvider:
    """Image generation provider using Google Gemini Image API."""
    
    id = "gemini"
    name = "Google Gemini Image"
    models = [
        ModelOption(
            id="gemini-2.5-flash-image",
            name="Gemini 2.5 Flash Image",
            description="Fast image generation"
        ),
        ModelOption(
            id="gemini-3-pro-image",
            name="Gemini 3 Pro Image",
            description="Higher quality, professional"
        ),
    ]
    
    def __init__(self):
        """Initialize the provider. API key validation is deferred to generate()
        so the registry / list_providers can return metadata without a configured key.
        """
        self.settings = get_settings()
        # Note: api_key may be empty here. generate() will validate before use.
    
    async def generate(
        self,
        prompt: str,
        *,
        negative: str = "",
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        """Generate an image from a text prompt.
        
        Args:
            prompt: The text prompt describing the desired image.
            negative: Negative prompt (not used by Gemini, kept for interface compatibility).
            model: Optional model ID. Defaults to gemini-2.5-flash-image-preview.
            resolution: Optional (width, height) tuple. Not used by Gemini currently.
            output_path: Absolute path where the generated image should be saved.
        
        Returns:
            Absolute path to the generated image file.
        
        Raises:
            MediaError: If image generation fails.
        """
        if not self.settings.google_api_key:
            raise MediaError("GOOGLE_API_KEY not configured in settings")

        model_id = model or "gemini-2.5-flash-image"
        if not model_id.startswith("gemini"):
            # Callers (render_real_video --image-model) default to foreign ids
            # like "sd-turbo"; those 404 against the Gemini API.
            model_id = "gemini-2.5-flash-image"
        elif model_id.endswith("-image-preview"):
            # Retired preview aliases 404 — map to the stable id.
            model_id = model_id.removesuffix("-preview")

        try:
            # Create client with explicit api_key (don't rely on env-globals)
            client = genai.Client(api_key=self.settings.google_api_key)

            # Aspect ratio from requested resolution — without it Gemini picks
            # its own framing and 16:9 thumbnails come back square/vertical,
            # then downstream crops cut faces and baked text.
            cfg_kwargs: dict = {"response_modalities": ["IMAGE", "TEXT"]}
            if resolution:
                w, h = resolution
                aspect = "16:9" if w > h else ("9:16" if h > w else "1:1")
                try:
                    cfg_kwargs["image_config"] = types.ImageConfig(aspect_ratio=aspect)
                except Exception:
                    pass  # older SDK without ImageConfig — let the model decide

            # Generate content with image response
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(**cfg_kwargs)
            )
            
            # Extract image data from response
            if not response.candidates or not response.candidates[0].content:
                raise MediaError("Gemini returned no content in response")
            
            content = response.candidates[0].content
            image_data = None
            mime_type = "image/png"
            
            for part in content.parts:
                if part.inline_data:
                    image_data = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break
            
            if not image_data:
                raise MediaError("Gemini returned no image data in response")
            
            # SDK returns raw bytes (already decoded); only b64-decode strings.
            image_bytes = base64.b64decode(image_data) if isinstance(image_data, str) else image_data
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, "wb") as f:
                f.write(image_bytes)
            
            return str(output_file.absolute())
            
        except Exception as e:
            raise MediaError(f"Failed to generate image with Gemini: {e}") from e
