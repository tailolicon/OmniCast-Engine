"""Media Pipeline Orchestrator. Runs all modules in correct order with parallel where possible."""

from __future__ import annotations
import asyncio
import re
import structlog
from omnicast.media.base import BaseMediaModule
from omnicast.media.models import (
    MediaPipelineState, MediaStatus, RenderJob, RenderLayer,
    TTSRequest, TTSResult, ImageGenRequest, ImageGenResult,
    VideoGenRequest, VideoGenResult, MusicRequest, MusicResult,
    SubtitleRequest, SubtitleResult, ThumbnailRequest, ThumbnailResult,
    RenderResult, ContentFingerprint,
)
from omnicast.media.tts import TTSModule
from omnicast.media.image_gen import ImageGenModule
from omnicast.media.video_gen import VideoGenModule
from omnicast.media.music import MusicModule
from omnicast.media.subtitle import SubtitleModule
from omnicast.media.thumbnail import ThumbnailModule
from omnicast.media.ffmpeg import FFmpegModule
from omnicast.media.fingerprint import FingerprintModule
from omnicast.media.providers.registry import get_image_provider, get_video_provider
from omnicast.media.style_guide import StyleGuide
from omnicast.media.prompt_builder import build_full_image_prompt, build_full_video_prompt
from omnicast.models.schemas import BrandConfig
from omnicast.models.script import MIDROLL_FLOOR_MIN, SPOKEN_WPM
from omnicast.config.styles import StylePreset
from omnicast.config.settings import get_settings
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()

# Hard platform floor only — the 8-min YouTube mid-roll minimum. This gate rejects
# ONLY genuinely-too-short scripts; longer videos (10, 12, 15+ min) pass freely.
# Per-video target length is enforced upstream (Writer floor / Critic), scaled to
# each brief's target_duration_min — not capped here.
MIN_SCRIPT_WORDS = MIDROLL_FLOOR_MIN * SPOKEN_WPM   # 8 min × 150 wpm = 1200
MIN_VOICEOVER_SECONDS = MIDROLL_FLOOR_MIN * 60.0     # 480s


def count_spoken_words(text: str) -> int:
    """Count spoken words for duration gates."""
    return len(re.findall(r"\b[\w']+\b", text or ""))


def _resolve_provider(kind: str, default_provider: str, default_model: str | None = None) -> tuple[str, str | None]:
    """Resolve media provider selection through CapabilityBus with registry fallback."""
    try:
        from omnicast.capabilities import CapabilityBus, ResolvePolicy
        from pathlib import Path as _Path

        db_path = _Path(__file__).resolve().parents[3] / "output" / "vault.db"
        cap = CapabilityBus(db_path=db_path).resolve(
            kind,
            policy=ResolvePolicy(prefer_provider_id=default_provider),
        )
        provider_id = cap.provider_id or default_provider
        model = default_model
        if provider_id != default_provider and cap.model_id and cap.model_id != provider_id:
            model = cap.model_id
        return provider_id, model
    except Exception:
        return default_provider, default_model


class MediaPipelineOrchestrator:
    """Run full media pipeline for one video.

    Execution order:
    1. TTS (voiceover from script) — sequential, needed first
    2. Parallel group:
       - Image generation (scene images)
       - Music selection/generation
    3. Video gen (optional, needs images from step 2)
    4. Subtitle (needs TTS audio from step 1)
    5. Thumbnail (needs images from step 2)
    6. FFmpeg render (needs all above)
    7. Content fingerprint (needs rendered video)
    """

    def __init__(
        self,
        tts: TTSModule | None = None,
        image_gen: ImageGenModule | None = None,
        video_gen: VideoGenModule | None = None,
        music: MusicModule | None = None,
        subtitle: SubtitleModule | None = None,
        thumbnail: ThumbnailModule | None = None,
        ffmpeg: FFmpegModule | None = None,
        fingerprint: FingerprintModule | None = None,
    ) -> None:
        self.tts = tts or TTSModule()
        self.image_gen = image_gen or ImageGenModule()
        self.video_gen = video_gen or VideoGenModule()
        self.music = music or MusicModule()
        self.subtitle = subtitle or SubtitleModule()
        self.thumbnail = thumbnail or ThumbnailModule()
        self.ffmpeg = ffmpeg or FFmpegModule()
        self.fingerprint = fingerprint or FingerprintModule()

    async def run(
        self,
        video_id: str,
        channel_id: str,
        script_text: str,
        scene_prompts: list[str],
        brand: BrandConfig,
        output_dir: str,
        existing_fingerprints: list[ContentFingerprint] | None = None,
        style_preset: StylePreset | None = None,
        style_guide: StyleGuide | None = None,
    ) -> tuple[MediaPipelineState, RenderResult | None, ContentFingerprint | None]:
        """Execute full pipeline. Returns (state, render_result, fingerprint).

        Steps:
        0. Optional: VisualDirectorAgent.enrich() if scenes lack AI media gen fields
        1. Run TTS → get audio path + duration
        2. Parallel: image gen (all scenes) + music search
        3. Optional: video gen (if brand.use_video_gen)
        4. Subtitle from TTS audio
        5. Thumbnail from first scene image
        6. Build RenderJob layers → FFmpeg render (with style_preset for transitions/visuals)
        7. Fingerprint check → reject if duplicate
        """
        state = MediaPipelineState(video_id=video_id, channel_id=channel_id)

        # Step 0: Optional VisualDirectorAgent.enrich() if using provider system
        # This would be called by the caller before run() if needed
        # For now, we assume scene_prompts already contain AI media gen fields if using providers

        # Step 1: TTS
        script_words = count_spoken_words(script_text)
        if script_words < MIN_SCRIPT_WORDS:
            logger.error(
                "Media pipeline rejected short script",
                video_id=video_id,
                words=script_words,
                min_words=MIN_SCRIPT_WORDS,
            )
            state = state.model_copy(update={"tts": MediaStatus.FAILED})
            return state, None, None

        tts_result = await self._run_tts(script_text, brand, output_dir)
        state = state.model_copy(update={"tts": MediaStatus.DONE if tts_result else MediaStatus.FAILED})
        if not tts_result:
            return state, None, None
        if tts_result.duration_seconds < MIN_VOICEOVER_SECONDS:
            logger.error(
                "Media pipeline rejected short voiceover",
                video_id=video_id,
                duration_seconds=tts_result.duration_seconds,
                min_duration_seconds=MIN_VOICEOVER_SECONDS,
            )
            state = state.model_copy(update={"render": MediaStatus.FAILED})
            return state, None, None

        # Step 2: Parallel — images + music
        image_results, music_result = await self._run_parallel_media(
            scene_prompts, brand, output_dir, style_guide
        )
        images_ok = bool(image_results) and any(getattr(r, "image_path", "") for r in image_results)
        state = state.model_copy(update={
            "images": MediaStatus.DONE if images_ok else MediaStatus.FAILED,
            "music": MediaStatus.DONE if music_result else MediaStatus.FAILED,
        })

        # Step 3: Optional video gen
        video_results = None
        if brand.use_video_gen and images_ok:
            video_results = await self._run_video_gen(scene_prompts, image_results, brand, output_dir, style_guide)
            state = state.model_copy(update={
                "video_gen": MediaStatus.DONE if video_results else MediaStatus.FAILED
            })
        else:
            state = state.model_copy(update={"video_gen": MediaStatus.SKIPPED})

        # Step 4: Subtitle
        sub_result = await self._run_subtitle(tts_result, output_dir)
        state = state.model_copy(update={
            "subtitle": MediaStatus.DONE if sub_result else MediaStatus.FAILED
        })

        # Step 5: Thumbnail
        thumb_result = await self._run_thumbnail(
            video_id, image_results, brand, output_dir
        )
        state = state.model_copy(update={
            "thumbnail": MediaStatus.DONE if thumb_result else MediaStatus.FAILED
        })

        if state.has_failure:
            return state, None, None

        # Step 6: FFmpeg render
        render_result = await self._run_render(
            video_id, channel_id, tts_result, image_results, video_results,
            music_result, sub_result, brand, output_dir, style_preset
        )
        state = state.model_copy(update={
            "render": MediaStatus.DONE if render_result else MediaStatus.FAILED
        })

        if not render_result:
            return state, None, None

        # Step 7: Fingerprint
        fp = self._run_fingerprint(video_id, script_text, image_results, tts_result)
        if existing_fingerprints:
            dup = self.fingerprint.check_duplicate(fp, existing_fingerprints)
            if dup:
                logger.warning("Duplicate detected", video_id=video_id, duplicate_of=dup.video_id)
                state = state.model_copy(update={"fingerprint": MediaStatus.FAILED})
                return state, render_result, fp

        state = state.model_copy(update={"fingerprint": MediaStatus.DONE})
        return state, render_result, fp

    async def _run_tts(self, script_text: str, brand: BrandConfig, output_dir: str) -> TTSResult | None:
        """Build TTSRequest from brand config and run."""
        try:
            req = TTSRequest(
                text=script_text,
                voice_profile=brand.voice_profile,
                voice_clone=brand.voice_clone,
                output_path=f"{output_dir}/voiceover.wav",
            )
            return await self.tts.process(req)
        except Exception as exc:
            logger.error("TTS failed", error=str(exc))
            return None

    async def _run_parallel_media(
        self, scene_prompts: list[str], brand: BrandConfig, output_dir: str,
        style_guide: StyleGuide | None = None,
    ) -> tuple[list[ImageGenResult] | None, MusicResult | None]:
        """Run image gen + music in parallel."""
        image_task = self._run_images(scene_prompts, brand, output_dir, style_guide)
        music_task = self._run_music(brand, output_dir)
        images, music = await asyncio.gather(image_task, music_task, return_exceptions=True)
        img_result = images if isinstance(images, list) else None
        mus_result = music if isinstance(music, MusicResult) else None
        return img_result, mus_result

    async def _run_images(
        self, 
        prompts: list[str], 
        brand: BrandConfig, 
        output_dir: str,
        style_guide: StyleGuide | None = None,
    ) -> list[ImageGenResult]:
        """Generate all scene images using provider system."""
        settings = get_settings()
        provider_id = getattr(brand, 'image_provider', None) or settings.media_image_provider
        model = getattr(brand, 'image_model', None) or settings.media_image_model
        provider_id, model = _resolve_provider("image", provider_id, model)
        
        provider = get_image_provider(provider_id)
        results = []
        
        for i, prompt in enumerate(prompts):
            try:
                output_path = f"{output_dir}/scene_{i:03d}.png"
                
                # Build full prompt with style guide if available
                if style_guide:
                    full_prompt = build_full_image_prompt(prompt, style_guide)
                else:
                    full_prompt = prompt
                
                image_path = await provider.generate(
                    prompt=full_prompt,
                    negative=getattr(brand, 'negative_prompt', ''),
                    model=model,
                    resolution=getattr(brand, 'image_resolution', None),
                    output_path=output_path
                )
                results.append(ImageGenResult(image_path=image_path, prompt=prompt))
            except Exception as exc:
                logger.error("Image generation failed", scene=i, error=str(exc))
                # Add failed result to maintain list order
                results.append(ImageGenResult(image_path="", prompt=prompt))
        
        return results

    async def _run_music(self, brand: BrandConfig, output_dir: str) -> MusicResult:
        req = MusicRequest(
            bpm_range=brand.music_bpm_range,
            output_path=f"{output_dir}/music_bg.wav",
        )
        return await self.music.process(req)

    async def _run_video_gen(
        self, prompts: list[str], images: list[ImageGenResult],
        brand: BrandConfig, output_dir: str,
        style_guide: StyleGuide | None = None,
    ) -> list[VideoGenResult] | None:
        """Generate videos from images using provider system."""
        settings = get_settings()
        provider_id = getattr(brand, 'video_provider', None) or settings.media_video_provider
        model = getattr(brand, 'video_model', None) or settings.media_video_model
        duration = getattr(brand, 'video_duration', 5)
        provider_id, model = _resolve_provider("video", provider_id, model)
        
        provider = get_video_provider(provider_id)
        results = []
        
        try:
            for i, (prompt, img) in enumerate(zip(prompts, images)):
                if not img.image_path:
                    logger.warning("Skipping video gen for scene with no image", scene=i)
                    results.append(VideoGenResult(video_path="", prompt=prompt))
                    continue
                
                try:
                    output_path = f"{output_dir}/clip_{i:03d}.mp4"
                    
                    # Build full prompt with style guide if available
                    if style_guide:
                        full_prompt = build_full_video_prompt(prompt, style_guide)
                    else:
                        full_prompt = prompt
                    
                    video_path = await provider.convert(
                        image_path=img.image_path,
                        prompt=full_prompt,
                        duration=duration,
                        model=model,
                        resolution=getattr(brand, 'video_resolution', None),
                        output_path=output_path
                    )
                    results.append(VideoGenResult(video_path=video_path, prompt=prompt))
                except Exception as exc:
                    logger.error("Video generation failed", scene=i, error=str(exc))
                    results.append(VideoGenResult(video_path="", prompt=prompt))
            
            return results
        except Exception as exc:
            logger.error("Video gen failed", error=str(exc))
            return None

    async def _run_subtitle(self, tts_result: TTSResult, output_dir: str) -> SubtitleResult | None:
        try:
            req = SubtitleRequest(
                audio_path=tts_result.audio_path,
                output_path=f"{output_dir}/subtitle.srt",
            )
            return await self.subtitle.process(req)
        except Exception as exc:
            logger.error("Subtitle failed", error=str(exc))
            return None

    async def _run_thumbnail(
        self, video_id: str, images: list[ImageGenResult] | None,
        brand: BrandConfig, output_dir: str,
    ) -> ThumbnailResult | None:
        try:
            req = ThumbnailRequest(
                title=video_id,
                style=brand.thumbnail_style,
                source_image=images[0].image_path if images else None,
                color_palette=brand.color_palette,
                font=brand.font,
                output_dir=f"{output_dir}/thumbnails",
            )
            return await self.thumbnail.process(req)
        except Exception as exc:
            logger.error("Thumbnail failed", error=str(exc))
            return None

    async def _run_render(
        self, video_id: str, channel_id: str,
        tts_result: TTSResult, images: list[ImageGenResult] | None,
        videos: list[VideoGenResult] | None, music: MusicResult | None,
        subtitle: SubtitleResult | None, brand: BrandConfig, output_dir: str,
        style_preset: StylePreset | None = None,
    ) -> RenderResult | None:
        try:
            layers = []
            # Video/image layer
            if videos:
                for v in videos:
                    layers.append(RenderLayer(layer_type="video", file_path=v.video_path))
            elif images:
                for img in images:
                    layers.append(RenderLayer(layer_type="video", file_path=img.image_path))

            # Voiceover
            layers.append(RenderLayer(layer_type="voiceover", file_path=tts_result.audio_path))

            # Music
            if music:
                layers.append(RenderLayer(layer_type="music", file_path=music.audio_path, volume_db=-20.0))

            # Subtitle
            if subtitle:
                layers.append(RenderLayer(layer_type="subtitle", file_path=subtitle.srt_path))

            # Intro/outro
            if brand.intro_template:
                layers.append(RenderLayer(layer_type="intro_outro", file_path=brand.intro_template))
            if brand.outro_template:
                layers.append(RenderLayer(layer_type="intro_outro", file_path=brand.outro_template))

            # Apply style preset transitions if provided
            transition_primary = style_preset.transition_primary if style_preset else brand.transition_style
            transition_secondary = style_preset.transition_secondary if style_preset else brand.transition_style

            job = RenderJob(
                job_id=f"render_{video_id}",
                channel_id=channel_id,
                layers=layers,
                output_path=f"{output_dir}/final_video.mp4",
                transition_primary=transition_primary,
                transition_secondary=transition_secondary,
            )
            return await self.ffmpeg.process(job)
        except Exception as exc:
            logger.error("Render failed", error=str(exc))
            return None

    def _run_fingerprint(
        self, video_id: str, script_text: str,
        images: list[ImageGenResult] | None, tts_result: TTSResult,
    ) -> ContentFingerprint:
        image_paths = [img.image_path for img in images] if images else []
        return self.fingerprint.build_fingerprint(
            video_id=video_id,
            script_text=script_text,
            image_paths=image_paths,
            audio_path=tts_result.audio_path,
        )
