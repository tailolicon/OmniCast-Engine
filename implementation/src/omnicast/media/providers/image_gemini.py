"""Gemini Image Provider implementation.

Uses Google GenAI SDK to generate images via Gemini 2.5 Flash Image.

REFERENCE CONDITIONING. `generate()` accepts an ORDERED list of reference
images. They are sent interleaved with their labels —

    "[IMAGE 1]:", <bytes>, "[IMAGE 2]:", <bytes>, …, <prompt>

— so each label sits immediately before the image it names in the token
stream. A prompt that then says "[IMAGE 1] stands in [IMAGE 2]" is bound to
specific files rather than to whatever the model inferred from an unlabelled
pile. `omnicast/storyboard/binding.py` produces both the labels and the paths;
this module stays ignorant of what an entity is.

ORDER IS THE BINDING, so a missing reference file is a hard error and never a
skip: dropping element 2 would slide element 3 into its place and silently
re-point every later token in the prompt.
"""

import base64
import mimetypes
from pathlib import Path

from google import genai
from google.genai import types

from omnicast.config.settings import get_settings
from omnicast.media.providers.interfaces import IImageProvider, ModelOption

#: Fallback label shape when the caller supplies images but no labels. Kept as
#: a literal rather than imported from `storyboard.binding` so that media
#: providers do not depend on the storyboard package.
_DEFAULT_LABEL = "[IMAGE {n}]"


class MediaError(Exception):
    """Base exception for media generation errors."""
    pass


def _image_part(path: str):
    """One inline image part, or a hard failure explaining which file broke."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise MediaError(
            f"reference image missing or empty: {path} — refusing to generate, "
            f"because dropping it would renumber every later [IMAGE n] token "
            f"and silently re-point the prompt")
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return types.Part.from_bytes(data=p.read_bytes(), mime_type=mime)


class GeminiImageProvider:
    """Image generation provider using Google Gemini Image API."""
    
    id = "gemini"
    name = "Google Gemini Image"
    #: Callers check this before handing over a reference set — a provider that
    #: silently ignores references produces drift that looks like a prompt bug.
    supports_reference_images = True
    max_reference_images = 8
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

    def _build_contents(
        self,
        prompt: str,
        reference_images: list[str] | None,
        reference_labels: list[str] | None,
    ):
        """Interleave `label, image, label, image, …, prompt`.

        Returns the bare prompt when there are no references, which is the
        pre-existing call shape — an unconditioned generation must keep
        behaving exactly as it did.
        """
        refs = list(reference_images or [])
        if not refs:
            return prompt

        labels = list(reference_labels or [])
        if labels and len(labels) != len(refs):
            raise MediaError(
                f"reference_labels has {len(labels)} entries for {len(refs)} "
                f"images — a mismatched pairing binds every token to the "
                f"wrong file")
        if not labels:
            labels = [_DEFAULT_LABEL.format(n=i + 1) for i in range(len(refs))]
        if len(refs) > self.max_reference_images:
            raise MediaError(
                f"{len(refs)} reference images exceeds the "
                f"{self.max_reference_images} this provider accepts; the "
                f"caller must decide what to drop, not this layer")

        contents: list = []
        for label, path in zip(labels, refs):
            contents.append(f"{label}:")
            contents.append(_image_part(path))
        contents.append(prompt)
        return contents


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
        """Generate an image from a text prompt, optionally conditioned on refs.

        Args:
            prompt: The text prompt describing the desired image.
            negative: Negative prompt (not used by Gemini, kept for interface compatibility).
            model: Optional model ID. Defaults to gemini-2.5-flash-image-preview.
            resolution: Optional (width, height) tuple. Not used by Gemini currently.
            output_path: Absolute path where the generated image should be saved.
            reference_images: Ordered reference file paths. Position N here is
                what the prompt's Nth label refers to — do not reorder.
            reference_labels: Labels parallel to `reference_images`. Defaults to
                "[IMAGE 1]", "[IMAGE 2]", … Must be the same length when given.

        Returns:
            Absolute path to the generated image file.

        Raises:
            MediaError: If image generation fails.
        """
        # Built before the API key check and outside the try: a mismatched or
        # missing reference is a caller bug, and it must surface as itself
        # rather than as "Failed to generate image with Gemini".
        contents = self._build_contents(prompt, reference_images, reference_labels)

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
                contents=contents,
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
