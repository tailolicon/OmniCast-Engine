"""Voice Router — multi-source TTS with per-channel voice identity.

Voice spec format: ``provider:voice_id``
    kokoro:af_heart          → Kokoro-82M local, voice af_heart
    edge:ko-KR-SunHiNeural   → Edge-TTS cloud, Korean female
    xttsv2:/path/to/ref.wav  → XTTSv2 clone (voice_id = reference audio path)

Routing rules:
  1. Channel config (`channels/{id}.json`) carries `voice_profile` (primary)
     and optional `voice_fallback` (ordered list of specs).
  2. The router tries each spec in order. A provider error → next spec.
  3. If ALL specs fail → MediaError. There is deliberately NO low-quality
     last resort (pyttsx3/SAPI removed 2026-06-12): a failed job is better
     than a robotic voice reaching a channel.

Scaling note: every new channel just declares its voice in JSON — no code
change. New TTS engines plug in via the provider registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

from omnicast.shared.errors import MediaError

logger = structlog.get_logger()

# ── Voice spec ────────────────────────────────────────────────────────────────

_SPEC_RE = re.compile(r"^(?P<provider>[a-z0-9_-]+):(?P<voice>.+)$")

# Legacy profile ids (pre-2026-06) → new specs. Old channel JSONs keep working.
_LEGACY_MAP = {
    "kokoro_en_us_v1": "kokoro:af_heart",
    "kokoro_en_gb_v1": "kokoro:bf_emma",
    "kokoro_en_au_v1": "edge:en-AU-NatashaNeural",   # Kokoro has no AU accent
    "kokoro_en_ca_v1": "edge:en-CA-ClaraNeural",
    "kokoro_en_in_v1": "edge:en-IN-NeerjaNeural",
    "kokoro_en_ph_v1": "edge:en-PH-RosaNeural",
    "kokoro_de_v1": "edge:de-DE-KatjaNeural",        # Kokoro has no German
    "kokoro_fr_v1": "kokoro:ff_siwis",
    "kokoro_id_v1": "edge:id-ID-GadisNeural",        # Kokoro has no Indonesian
    "kokoro_vi_v1": "edge:vi-VN-HoaiMyNeural",       # Kokoro has no Vietnamese
}

# Market → (primary, fallback) — used when a channel has no explicit voice.
# Diversity across channels comes from MARKET_VOICE_POOL rotation below.
MARKET_VOICE_DEFAULTS: dict[str, tuple[str, str]] = {
    "US": ("kokoro:af_heart", "edge:en-US-AriaNeural"),
    "UK": ("kokoro:bf_emma", "edge:en-GB-SoniaNeural"),
    "AU": ("edge:en-AU-NatashaNeural", "kokoro:af_heart"),
    "CA": ("edge:en-CA-ClaraNeural", "kokoro:af_heart"),
    "IN": ("edge:en-IN-NeerjaNeural", "kokoro:hf_alpha"),
    "JP": ("kokoro:jf_alpha", "edge:ja-JP-NanamiNeural"),
    "KR": ("edge:ko-KR-SunHiNeural", "edge:ko-KR-InJoonNeural"),
    "CN": ("kokoro:zf_xiaoxiao", "edge:zh-CN-XiaoxiaoNeural"),
    "DE": ("edge:de-DE-KatjaNeural", "edge:de-DE-ConradNeural"),
    "FR": ("kokoro:ff_siwis", "edge:fr-FR-DeniseNeural"),
    "ES": ("kokoro:ef_dora", "edge:es-ES-ElviraNeural"),
    "VN": ("edge:vi-VN-HoaiMyNeural", "edge:vi-VN-NamMinhNeural"),
    "ID": ("edge:id-ID-GadisNeural", "edge:id-ID-ArdiNeural"),
    "PH": ("edge:en-PH-RosaNeural", "kokoro:af_heart"),
}
_DEFAULT_MARKET = "US"

# Per-market voice pools — ChannelBuilder rotates through these so that
# channels in the same market DON'T share one voice (anti mass-produced signal).
MARKET_VOICE_POOL: dict[str, list[str]] = {
    "US": ["kokoro:af_heart", "kokoro:af_nova", "kokoro:am_michael",
           "kokoro:am_adam", "kokoro:af_sky",
           # Edge/Azure US neural voices — broad pool so channels stay distinct
           # even without local providers installed (deterministic hash pick).
           "edge:en-US-AriaNeural", "edge:en-US-GuyNeural", "edge:en-US-JennyNeural",
           "edge:en-US-DavisNeural", "edge:en-US-AmberNeural", "edge:en-US-AndrewNeural",
           "edge:en-US-EmmaNeural", "edge:en-US-BrianNeural", "edge:en-US-JasonNeural",
           "edge:en-US-SaraNeural", "edge:en-US-TonyNeural", "edge:en-US-NancyNeural",
           "edge:en-US-RogerNeural", "edge:en-US-SteffanNeural"],
    "UK": ["kokoro:bf_emma", "kokoro:bm_george", "kokoro:bf_isabella",
           "kokoro:bm_lewis", "edge:en-GB-SoniaNeural", "edge:en-GB-RyanNeural"],
    "JP": ["kokoro:jf_alpha", "kokoro:jf_gongitsune", "kokoro:jm_kumo",
           "edge:ja-JP-NanamiNeural", "edge:ja-JP-KeitaNeural"],
    "KR": ["edge:ko-KR-SunHiNeural", "edge:ko-KR-InJoonNeural",
           "edge:ko-KR-HyunsuMultilingualNeural"],
    "CN": ["kokoro:zf_xiaoxiao", "kokoro:zm_yunxi", "edge:zh-CN-XiaoxiaoNeural"],
}


@dataclass(frozen=True)
class VoiceSpec:
    provider: str
    voice: str

    @classmethod
    def parse(cls, spec: str) -> "VoiceSpec":
        spec = (spec or "").strip()
        spec = _LEGACY_MAP.get(spec, spec)
        m = _SPEC_RE.match(spec)
        if not m:
            raise ValueError(
                f"Invalid voice spec '{spec}'. Expected 'provider:voice_id' "
                f"(e.g. 'kokoro:af_heart', 'edge:ko-KR-SunHiNeural')."
            )
        return cls(provider=m.group("provider"), voice=m.group("voice"))

    def __str__(self) -> str:  # round-trips back to spec form
        return f"{self.provider}:{self.voice}"


def resolve_channel_voice(channel_cfg: dict) -> list[VoiceSpec]:
    """Build the ordered voice chain for a channel config dict.

    Priority: explicit voice_profile → explicit voice_fallback list
              → market defaults. Always at least 2 entries when possible.
    """
    chain: list[str] = []
    profile = channel_cfg.get("voice_profile")
    if profile:
        chain.append(profile)
    chain.extend(channel_cfg.get("voice_fallback", []) or [])

    market = (channel_cfg.get("market") or _DEFAULT_MARKET).upper()
    primary, fallback = MARKET_VOICE_DEFAULTS.get(
        market, MARKET_VOICE_DEFAULTS[_DEFAULT_MARKET])

    # DISTINCTNESS GUARANTEE: a channel-deterministic EDGE voice from the market
    # pool. Edge always works (no local deps), so even when preferred local
    # providers (kokoro/xtts) aren't installed, each channel resolves to a
    # DIFFERENT real voice instead of every channel collapsing onto the single
    # market-default fallback. Deterministic (hash of channel_id) → same channel
    # → same voice every render (brand consistency).
    cid = str(channel_cfg.get("channel_id") or channel_cfg.get("id") or "")
    det_edge = None
    pool = [v for v in MARKET_VOICE_POOL.get(market, []) if v.startswith("edge:")]
    if cid and pool:
        import hashlib as _hl
        det_edge = pool[int(_hl.sha256(cid.encode()).hexdigest(), 16) % len(pool)]

    if not chain:
        # No explicit channel voice: lead with the deterministic edge so distinct
        # channels sound distinct out of the box.
        chain = [det_edge or primary]
    elif len(chain) == 1:
        # Lone entry is the channel's preferred (often a local kokoro voice). Make
        # the FIRST working fallback the channel-distinct edge — tried before the
        # generic market default, so kokoro-missing channels stay distinct.
        if det_edge and det_edge != chain[0]:
            chain.append(det_edge)
    # Always end with a guaranteed cross-provider last resort.
    if fallback not in chain:
        chain.append(fallback)

    specs: list[VoiceSpec] = []
    seen: set[str] = set()
    for raw in chain:
        try:
            s = VoiceSpec.parse(raw)
        except ValueError:
            logger.warning("Skipping invalid voice spec", spec=raw,
                           channel=channel_cfg.get("channel_id"))
            continue
        if str(s) not in seen:
            seen.add(str(s))
            specs.append(s)
    if not specs:
        specs = [VoiceSpec.parse(primary), VoiceSpec.parse(fallback)]
    return specs


def pick_voice_for_new_channel(market: str, taken: set[str] | None = None) -> str:
    """Least-used voice from the market pool — keeps sibling channels distinct."""
    pool = MARKET_VOICE_POOL.get(market.upper())
    if not pool:
        return MARKET_VOICE_DEFAULTS.get(
            market.upper(), MARKET_VOICE_DEFAULTS[_DEFAULT_MARKET])[0]
    taken = taken or set()
    for v in pool:
        if v not in taken:
            return v
    return pool[len(taken) % len(pool)]  # all taken → round-robin


# ── Router ────────────────────────────────────────────────────────────────────

@dataclass
class SynthesisResult:
    audio_path: str
    spec: VoiceSpec
    attempts: list[str] = field(default_factory=list)  # failed specs, in order


class VoiceRouter:
    """Tries voice specs in order until one synthesizes successfully."""

    async def synthesize(
        self,
        text: str,
        specs: list[VoiceSpec] | list[str],
        output_path: str,
        *,
        voice_clone_path: str | None = None,
    ) -> SynthesisResult:
        from omnicast.media.providers.registry import get_tts_provider

        parsed = [s if isinstance(s, VoiceSpec) else VoiceSpec.parse(s)
                  for s in specs]
        if not parsed:
            raise MediaError("VoiceRouter: empty voice spec chain")

        failures: list[str] = []
        errors: list[str] = []
        for spec in parsed:
            try:
                provider = get_tts_provider(spec.provider)
            except ValueError as exc:
                failures.append(str(spec))
                errors.append(str(exc))
                continue
            # Clone providers take the reference audio as the "voice"
            clone = voice_clone_path
            if spec.provider in ("xttsv2", "f5tts") and not clone:
                clone = spec.voice
            try:
                path = await provider.generate(
                    text,
                    model=spec.voice,
                    voice_clone_path=clone,
                    output_path=output_path,
                )
                if failures:
                    logger.warning("TTS fell back", used=str(spec),
                                   failed=failures)
                return SynthesisResult(audio_path=path, spec=spec,
                                       attempts=failures)
            except Exception as exc:  # provider-level failure → next spec
                failures.append(str(spec))
                errors.append(f"{spec}: {exc}")
                logger.warning("TTS spec failed, trying next",
                               spec=str(spec), error=str(exc))

        raise MediaError(
            "All TTS sources failed (no low-quality fallback by design). "
            f"Chain: {[str(s) for s in parsed]}. Errors: {errors}"
        )
