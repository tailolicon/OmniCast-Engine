"""Provider registry for dynamic provider selection.

This module maintains a registry of available image and video providers
and provides functions to retrieve them by ID.

Providers are instantiated lazily to avoid requiring API keys at import time.
"""

import importlib
import json
import os
from pathlib import Path
from typing import Callable

from omnicast.media.providers.interfaces import IImageProvider, IVideoProvider, ITTSProvider
from omnicast.media.providers.image_gemini import GeminiImageProvider
from omnicast.media.providers.video_gemini import GeminiVideoProvider
from omnicast.media.providers.avatar import ITalkingHeadProvider

# Provider factories (lazy initialization)
def _get_local_sd():
    from omnicast.media.providers.image_local import LocalDiffusionProvider
    return LocalDiffusionProvider()


def _get_flow_image():
    from omnicast.media.providers.flow_browser import FlowProvider
    return FlowProvider()


_IMAGE_PROVIDER_FACTORIES: dict[str, Callable[[], IImageProvider]] = {
    "gemini": lambda: GeminiImageProvider(),
    "local-sd": _get_local_sd,
    "flow": _get_flow_image,
}

def _get_flow_video():
    from omnicast.media.providers.flow_browser import FlowProvider
    return FlowProvider()


_VIDEO_PROVIDER_FACTORIES: dict[str, Callable[[], IVideoProvider]] = {
    "gemini": lambda: GeminiVideoProvider(),
    "flow": _get_flow_video,
}

def _get_kokoro():
    from omnicast.media.providers.tts_local import KokoroTTSProvider
    return KokoroTTSProvider()

def _get_xttsv2():
    from omnicast.media.providers.tts_local import XTTSv2Provider
    return XTTSv2Provider()

def _get_edge():
    from omnicast.media.providers.tts_edge import EdgeTTSProvider
    return EdgeTTSProvider()

def _get_f5tts():
    from omnicast.media.providers.tts_local import F5TTSProvider
    return F5TTSProvider()

def _get_piper():
    from omnicast.media.providers.tts_local import PiperTTSProvider
    return PiperTTSProvider()

def _get_chatterbox():
    from omnicast.media.providers.tts_chatterbox import ChatterboxTTSProvider
    return ChatterboxTTSProvider()

# NOTE: pyttsx3/SAPI removed 2026-06-12 — neural-only policy. "piper" re-added
# 2026-06-20 via sherpa-onnx (neural VITS, self-contained k2-fsa model tarballs).
# "chatterbox" added 2026-07-13 (Resemble AI, MIT) — expressive emotion dial for
# horror narration; runs in an isolated venv via a persistent subprocess worker.
_TTS_PROVIDER_FACTORIES: dict[str, Callable[[], ITTSProvider]] = {
    "kokoro": _get_kokoro,
    "edge": _get_edge,
    "xttsv2": _get_xttsv2,
    "f5tts": _get_f5tts,
    "piper": _get_piper,
    "chatterbox": _get_chatterbox,
}


def _get_sadtalker():
    from omnicast.media.providers.avatar import SadTalkerProvider
    return SadTalkerProvider()


def _get_comfyui_hunyuan():
    from omnicast.media.providers.avatar import ComfyUIHunyuanProvider
    return ComfyUIHunyuanProvider()


def _get_procedural():
    from omnicast.media.providers.avatar import ProceduralTalkingHeadProvider
    return ProceduralTalkingHeadProvider()


_AVATAR_PROVIDER_FACTORIES: dict[str, Callable[[], ITalkingHeadProvider]] = {
    "procedural": _get_procedural,
    "sadtalker": _get_sadtalker,
    "comfyui-hunyuan": _get_comfyui_hunyuan,
}

# Cached instances
_IMAGE_PROVIDERS: dict[str, IImageProvider] = {}
_VIDEO_PROVIDERS: dict[str, IVideoProvider] = {}
_TTS_PROVIDERS: dict[str, ITTSProvider] = {}
_AVATAR_PROVIDERS: dict[str, ITalkingHeadProvider] = {}
_MANIFEST_LOADED = False
_MANIFEST_ENTRIES: dict[tuple[str, str], dict] = {}


def _manifest_path() -> Path:
    override = os.getenv("OMNICAST_PROVIDER_MANIFEST")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "providers.manifest.yaml"


def _factory_from_class(adapter_class: str):
    module_name, class_name = adapter_class.rsplit(".", 1)

    def _factory():
        module = importlib.import_module(module_name)
        return getattr(module, class_name)()

    return _factory


def _load_manifest_once() -> None:
    global _MANIFEST_LOADED
    if _MANIFEST_LOADED:
        return
    _MANIFEST_LOADED = True
    path = _manifest_path()
    if not path.exists():
        return
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("providers", raw if isinstance(raw, list) else [])
    for entry in entries:
        provider_id = str(entry.get("id") or "").strip()
        capability = str(entry.get("capability") or entry.get("category") or "").strip()
        adapter_class = str(entry.get("adapter_class") or "").strip()
        if not provider_id or not capability:
            continue
        _MANIFEST_ENTRIES[(capability, provider_id)] = dict(entry)
        if not adapter_class:
            continue
        factory = _factory_from_class(adapter_class)
        if capability == "image":
            _IMAGE_PROVIDER_FACTORIES[provider_id] = factory
        elif capability == "video":
            _VIDEO_PROVIDER_FACTORIES[provider_id] = factory
        elif capability == "tts":
            _TTS_PROVIDER_FACTORIES[provider_id] = factory


async def _default_health(provider_id: str, capability: str) -> dict:
    return {"ok": True, "provider_id": provider_id, "capability": capability}


def _decorate_provider(provider, capability: str, provider_id: str):
    meta = _MANIFEST_ENTRIES.get((capability, provider_id), {})
    if not hasattr(provider, "capability"):
        setattr(provider, "capability", capability)
    if not hasattr(provider, "cost_per_unit"):
        setattr(provider, "cost_per_unit", float(meta.get("cost_per_unit") or meta.get("cost") or 0.0))
    if not hasattr(provider, "rate_limit"):
        setattr(provider, "rate_limit", dict(meta.get("rate_limit") or {}))
    if not hasattr(provider, "health_check"):
        async def _health_check():
            return await _default_health(provider_id, capability)
        setattr(provider, "health_check", _health_check)
    return provider


def _provider_info(provider_id: str, capability: str, factory: Callable):
    meta = _MANIFEST_ENTRIES.get((capability, provider_id), {})
    try:
        provider = _decorate_provider(factory(), capability, provider_id)
        return {
            "id": provider.id,
            "name": provider.name,
            "category": capability,
            "capability": getattr(provider, "capability", capability),
            "cost_per_unit": float(getattr(provider, "cost_per_unit", 0.0) or 0.0),
            "rate_limit": getattr(provider, "rate_limit", {}) or {},
            "runtime": meta.get("runtime", "remote"),
            "min_vram_mb": int(meta.get("min_vram_mb") or 0),
            "requires_credential": bool(meta.get("requires_credential", False)),
            "config_schema": meta.get("config_schema", {}),
            "models": [{"id": m.id, "name": m.name, "description": m.description} for m in provider.models],
        }
    except Exception:
        return {
            "id": provider_id,
            "name": meta.get("name", f"{provider_id} (unavailable)"),
            "category": capability,
            "capability": capability,
            "cost_per_unit": float(meta.get("cost_per_unit") or meta.get("cost") or 0.0),
            "rate_limit": dict(meta.get("rate_limit") or {}),
            "runtime": meta.get("runtime", "remote"),
            "min_vram_mb": int(meta.get("min_vram_mb") or 0),
            "requires_credential": bool(meta.get("requires_credential", False)),
            "config_schema": meta.get("config_schema", {}),
            "models": [],
            "error": "Provider unavailable (check dependencies or API key)",
        }


def get_image_provider(provider_id: str) -> IImageProvider:
    """Get an image provider by ID (lazy initialization).
    
    Args:
        provider_id: The provider ID (e.g., 'gemini').
    
    Returns:
        The image provider instance.
    
    Raises:
        ValueError: If the provider ID is not found.
    """
    _load_manifest_once()
    # Check cache first
    if provider_id in _IMAGE_PROVIDERS:
        return _IMAGE_PROVIDERS[provider_id]
    
    # Instantiate from factory
    factory = _IMAGE_PROVIDER_FACTORIES.get(provider_id)
    if not factory:
        available = ", ".join(_IMAGE_PROVIDER_FACTORIES.keys())
        raise ValueError(f"Unknown image provider: {provider_id}. Available: {available}")
    
    provider = _decorate_provider(factory(), "image", provider_id)
    _IMAGE_PROVIDERS[provider_id] = provider
    return provider


def get_video_provider(provider_id: str) -> IVideoProvider:
    """Get a video provider by ID (lazy initialization).
    
    Args:
        provider_id: The provider ID (e.g., 'gemini').
    
    Returns:
        The video provider instance.
    
    Raises:
        ValueError: If the provider ID is not found.
    """
    _load_manifest_once()
    # Check cache first
    if provider_id in _VIDEO_PROVIDERS:
        return _VIDEO_PROVIDERS[provider_id]
    
    # Instantiate from factory
    factory = _VIDEO_PROVIDER_FACTORIES.get(provider_id)
    if not factory:
        available = ", ".join(_VIDEO_PROVIDER_FACTORIES.keys())
        raise ValueError(f"Unknown video provider: {provider_id}. Available: {available}")
    
    provider = _decorate_provider(factory(), "video", provider_id)
    _VIDEO_PROVIDERS[provider_id] = provider
    return provider


def get_tts_provider(provider_id: str) -> ITTSProvider:
    """Get a TTS provider by ID (lazy initialization)."""
    _load_manifest_once()
    if provider_id in _TTS_PROVIDERS:
        return _TTS_PROVIDERS[provider_id]
    
    factory = _TTS_PROVIDER_FACTORIES.get(provider_id)
    if not factory:
        available = ", ".join(_TTS_PROVIDER_FACTORIES.keys())
        raise ValueError(f"Unknown TTS provider: {provider_id}. Available: {available}")
    
    provider = _decorate_provider(factory(), "tts", provider_id)
    _TTS_PROVIDERS[provider_id] = provider
    return provider


def get_avatar_provider(provider_id: str) -> ITalkingHeadProvider:
    """Get a talking-head (avatar) provider by ID (lazy initialization)."""
    if provider_id in _AVATAR_PROVIDERS:
        return _AVATAR_PROVIDERS[provider_id]

    factory = _AVATAR_PROVIDER_FACTORIES.get(provider_id)
    if not factory:
        available = ", ".join(_AVATAR_PROVIDER_FACTORIES.keys())
        raise ValueError(f"Unknown avatar provider: {provider_id}. Available: {available}")

    provider = factory()
    _AVATAR_PROVIDERS[provider_id] = provider
    return provider


def list_providers() -> list[dict]:
    """List all available providers with their metadata.
    
    Returns:
        A list of dictionaries containing provider information.
    """
    _load_manifest_once()
    providers = []
    
    for provider_id, factory in _IMAGE_PROVIDER_FACTORIES.items():
        providers.append(_provider_info(provider_id, "image", factory))
    
    for provider_id, factory in _VIDEO_PROVIDER_FACTORIES.items():
        providers.append(_provider_info(provider_id, "video", factory))
    
    for provider_id, factory in _TTS_PROVIDER_FACTORIES.items():
        providers.append(_provider_info(provider_id, "tts", factory))
    
    return providers


def register_image_provider(provider_id: str, provider: IImageProvider) -> None:
    """Register a custom image provider.
    
    Args:
        provider_id: The provider ID to register.
        provider: The provider instance.
    """
    _IMAGE_PROVIDERS[provider_id] = provider


def register_video_provider(provider_id: str, provider: IVideoProvider) -> None:
    """Register a custom video provider.
    
    Args:
        provider_id: The provider ID to register.
        provider: The provider instance.
    """
    _VIDEO_PROVIDERS[provider_id] = provider


def register_tts_provider(provider_id: str, provider: ITTSProvider) -> None:
    """Register a custom TTS provider."""
    _TTS_PROVIDERS[provider_id] = provider
    _load_manifest_once()
    _load_manifest_once()
