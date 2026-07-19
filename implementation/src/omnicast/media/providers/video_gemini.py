"""Gemini Video Provider implementation (Veo 3).

Uses Google GenAI SDK to generate videos via Veo 3 API.
Polls operation status until completion.
"""

import asyncio
import base64
import httpx
from pathlib import Path

from google import genai
from google.genai import types

from omnicast.config.settings import get_settings
from omnicast.media.providers.interfaces import IVideoProvider, ModelOption
from omnicast.media.providers.image_gemini import MediaError


class GeminiVideoProvider:
    """Video generation provider using Google Veo 3 API."""
    
    id = "gemini"
    name = "Google Veo"
    models = [
        ModelOption(
            id="veo-3.0-generate-001",
            name="Veo 3.0",
            description="Video generation via Gemini API (paid tier)"
        ),
        ModelOption(
            id="veo-3.1-generate-preview",
            name="Veo 3.1 (preview)",
            description="Latest Veo via Gemini API (paid tier)"
        ),
    ]
    
    def __init__(self):
        """Initialize the provider. API key validation is deferred to convert()
        so the registry / list_providers can return metadata without a configured key.
        """
        self.settings = get_settings()
        # Note: api_key may be empty here. convert() will validate before use.
    
    async def convert(
        self,
        image_path: str,
        prompt: str,
        *,
        duration: int = 5,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        """Convert an image into a video clip.
        
        Args:
            image_path: Absolute path to the source image.
            prompt: Text prompt describing the desired video motion/style.
            duration: Duration of the video in seconds (will be clamped to 4, 6, or 8).
            model: Optional model ID. Defaults to veo-3.0-generate-001.
            resolution: Optional (width, height) tuple for aspect ratio.
            output_path: Absolute path where the generated video should be saved.
        
        Returns:
            Absolute path to the generated video file.
        
        Raises:
            MediaError: If video generation fails.
        """
        if not self.settings.google_api_key:
            raise MediaError("GOOGLE_API_KEY not configured in settings")

        model_id = model or "veo-3.0-generate-001"

        try:
            # Load and encode image
            image_bytes, mime_type = await self._load_image(image_path)
            
            # Build full prompt
            full_prompt = prompt if prompt else "Generate a video based on this image."
            
            # Clamp duration to supported values
            duration_seconds = self._clamp_duration(duration)
            
            # Determine aspect ratio from resolution
            aspect_ratio = self._determine_aspect_ratio(resolution)
            
            print(f"[veo] Starting video generation with model={model_id} duration={duration_seconds}s{aspect_ratio if aspect_ratio else ''}")
            
            # Initialize client with explicit api_key
            client = genai.Client(api_key=self.settings.google_api_key)
            
            # Generate video
            operation = client.models.generate_videos(
                model=model_id,
                prompt=full_prompt,
                image=types.Image(data=image_bytes, mime_type=mime_type),
                config=types.GenerateVideosConfig(
                    number_of_videos=1,
                    duration_seconds=duration_seconds,
                    **({"aspect_ratio": aspect_ratio} if aspect_ratio else {})
                )
            )
            
            # Poll until done
            for i in range(120):  # Max 10 minutes (120 * 5s)
                if operation.done:
                    break
                await asyncio.sleep(5)
                print(f"[veo] Polling... attempt {i + 1}")
                operation = client.operations.get_videos_operation(operation=operation)
            
            if not operation.done:
                raise MediaError("Veo video generation timed out after 10 minutes")
            
            # Check for errors
            if hasattr(operation, 'error') and operation.error:
                raise MediaError(f"Veo generation failed: {operation.error}")
            
            # Extract video data from response
            video_data = await self._extract_video_data(operation)
            
            # Save to file
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, "wb") as f:
                f.write(video_data)
            
            return str(output_file.absolute())
            
        except Exception as e:
            raise MediaError(f"Failed to generate video with Veo: {e}") from e
    
    async def _load_image(self, image_path: str) -> tuple[bytes, str]:
        """Load image from path and return (bytes, mime_type)."""
        path = Path(image_path)
        
        # Determine mime type from extension
        ext_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
        }
        mime_type = ext_map.get(path.suffix.lower(), 'image/png')
        
        # Read and encode image
        with open(path, 'rb') as f:
            image_bytes = f.read()
        
        return image_bytes, mime_type
    
    def _clamp_duration(self, duration: int) -> int:
        """Clamp duration to nearest supported value (4, 6, or 8 seconds)."""
        supported = [4, 6, 8]
        return min(supported, key=lambda x: abs(x - duration))
    
    def _determine_aspect_ratio(self, resolution: tuple[int, int] | None) -> str | None:
        """Determine aspect ratio from resolution."""
        if not resolution:
            return None
        
        width, height = resolution
        if height > width:
            return "9:16"
        elif width > height:
            return "16:9"
        else:
            return "1:1"
    
    async def _extract_video_data(self, operation) -> bytes:
        """Extract video bytes from operation response.
        
        Handles multiple possible response field names and formats.
        """
        # Get response/result from operation
        resp = getattr(operation, 'response', None) or getattr(operation, 'result', None)
        
        if not resp:
            raise MediaError("Veo returned no response/result")
        
        print(f"[veo] response keys: {list(resp.keys()) if hasattr(resp, 'keys') else 'N/A'}")
        
        # Try different field names for generated videos list
        videos_list = (
            getattr(resp, 'generatedVideos', None) or
            getattr(resp, 'generated_videos', None) or
            (getattr(resp, 'videos', None) if isinstance(getattr(resp, 'videos', None), list) else None)
        )
        
        if not videos_list or not isinstance(videos_list, list) or len(videos_list) == 0:
            raise MediaError("Veo returned no generated videos list")
        
        first_video = videos_list[0]
        print(f"[veo] first video keys: {list(first_video.keys()) if hasattr(first_video, 'keys') else 'N/A'}")
        
        # Try to get video object
        video_obj = (
            getattr(first_video, 'video', None) or
            first_video
        )
        
        if not video_obj:
            raise MediaError("Veo returned no video object")
        
        # Prefer inline video bytes
        video_bytes = getattr(video_obj, 'videoBytes', None) or getattr(video_obj, 'video_bytes', None)
        
        if video_bytes:
            # Decode base64
            return base64.b64decode(video_bytes)
        
        # Otherwise fetch from URI
        uri = getattr(video_obj, 'uri', None)
        if uri:
            return await self._fetch_video_from_uri(uri)
        
        raise MediaError("Veo returned video with no uri or videoBytes")
    
    async def _fetch_video_from_uri(self, uri: str) -> bytes:
        """Fetch video from URI with API key authentication."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                uri,
                headers={
                    "x-goog-api-key": self.settings.google_api_key,
                    "Accept": "*/*"
                },
                follow_redirects=True
            )
            
            if not response.is_success:
                raise MediaError(f"Failed to download Veo video: {response.status_code} {response.text}")
            
            return response.content
