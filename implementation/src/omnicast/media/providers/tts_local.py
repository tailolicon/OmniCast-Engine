"""Local TTS providers (Kokoro, XTTSv2, F5).

All providers here synthesize REAL audio — no stubs. Heavy deps are
lazy-imported so the module loads without them; a clear RuntimeError fires
only when a provider is actually invoked without its dependency installed.

NOTE: pyttsx3/SAPI was deliberately removed project-wide (2026-06-12).
Robotic voices are worse than a failed job — quality gate, not a bug.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path

from omnicast.media.providers.interfaces import ITTSProvider, ModelOption

# Where downloaded Piper/sherpa-onnx models are cached (implementation/output/_models/piper)
_MODELS_DIR = Path(__file__).resolve().parents[4] / "output" / "_models" / "piper"
# k2-fsa pre-packages each Piper voice (onnx + tokens.txt + espeak-ng-data) as a
# self-contained tarball — no system espeak install needed.
_PIPER_RELEASE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                  "tts-models/vits-piper-{key}.tar.bz2")
# Memory caps: keep at most N piper model dirs ON DISK (LRU by mtime) and at most
# M loaded OfflineTts engines IN RAM. Stops the cache ballooning when many of the
# 163 voices get auditioned. Tunable via env.
_PIPER_MAX_MODELS = int(os.environ.get("OMNICAST_PIPER_MAX_MODELS", "12"))
_PIPER_MAX_ENGINES = int(os.environ.get("OMNICAST_PIPER_MAX_ENGINES", "2"))

# Kokoro voice id prefix → KPipeline lang_code (first letter encodes language)
#   a=American English, b=British English, e=Spanish, f=French, h=Hindi,
#   i=Italian, j=Japanese, p=Brazilian Portuguese, z=Mandarin
_KOKORO_LANGS = set("abefhijpz")

_KOKORO_DEFAULT_VOICE = "af_heart"

# Curated subset surfaced in the UI (full list: 54 voices in the model card)
_KOKORO_FEATURED = [
    ("af_heart", "Heart (US female)", "Warm, professional — default"),
    ("af_nova", "Nova (US female)", "Bright product/explainer voice"),
    ("af_sky", "Sky (US female)", "Energetic — Shorts/promo"),
    ("am_michael", "Michael (US male)", "Authoritative — finance/docu"),
    ("am_adam", "Adam (US male)", "Neutral tutorial voice"),
    ("bf_emma", "Emma (UK female)", "Clear British — documentation"),
    ("bm_george", "George (UK male)", "Formal British — documentary"),
    ("jf_alpha", "Alpha (JP female)", "Japanese narration"),
    ("zf_xiaoxiao", "Xiaoxiao (ZH female)", "Mandarin narration"),
    ("ef_dora", "Dora (ES female)", "Spanish narration"),
    ("ff_siwis", "Siwis (FR female)", "French narration"),
    ("hf_alpha", "Alpha (HI female)", "Hindi narration"),
]


class KokoroTTSProvider:
    """Kokoro-82M — local neural TTS, 54 voices / 9 languages, no API key.

    Voice ids follow the upstream scheme (``af_heart``, ``bm_george``,
    ``jf_alpha``...). The first letter selects the language pipeline.
    Pipelines are cached per lang_code (model load is expensive).
    """

    id = "kokoro"
    name = "Kokoro-82M (Local)"
    models = [ModelOption(id=v, name=n, description=d) for v, n, d in _KOKORO_FEATURED]

    _SAMPLE_RATE = 24_000

    def __init__(self) -> None:
        self._pipelines: dict[str, object] = {}

    @staticmethod
    def _ensure_espeak() -> None:
        """Point misaki/phonemizer at the bundled espeak-ng lib + data (no system
        install needed). MUST run BEFORE `import kokoro` because misaki binds the
        espeak library at import time. Without this, OOV words (e.g. 'Ozempic')
        get None phonemes → kokoro crashes and the chain falls back to edge."""
        try:
            import os
            import espeakng_loader
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
            data = espeakng_loader.get_data_path()
            os.environ.setdefault("ESPEAK_DATA_PATH", os.path.dirname(data))
            os.environ.setdefault("PHONEMIZER_ESPEAK_LIBRARY", espeakng_loader.get_library_path())
            EspeakWrapper.set_library(espeakng_loader.get_library_path())
        except Exception:
            pass  # best-effort; if missing, kokoro raises and the voice chain falls back

    def _pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            self._ensure_espeak()
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise RuntimeError(
                    "kokoro not installed. Run: pip install kokoro soundfile"
                ) from exc
            self._pipelines[lang_code] = KPipeline(lang_code=lang_code)
        return self._pipelines[lang_code]

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,  # unused — Kokoro has fixed voices
        output_path: str,
        speed: float = 1.0,   # per-scene prosody pace (0.85 slow … 1.12 fast)
    ) -> str:
        voice = (model or _KOKORO_DEFAULT_VOICE).strip()
        # Legacy profile ids ("kokoro_en_us_v1") → default US voice
        if not re.match(r"^[abefhijpz][fm]_", voice):
            voice = _KOKORO_DEFAULT_VOICE
        lang = voice[0] if voice[0] in _KOKORO_LANGS else "a"
        speed = max(0.5, min(float(speed or 1.0), 1.5))

        def _infer() -> str:
            import numpy as np
            import soundfile as sf

            pipe = self._pipeline(lang)
            chunks: list = []
            # KPipeline yields (graphemes, phonemes, audio) per text segment
            for _, _, audio in pipe(text, voice=voice, speed=speed):
                if audio is not None:
                    chunks.append(audio)
            if not chunks:
                raise RuntimeError(f"Kokoro produced no audio (voice={voice})")
            wav = np.concatenate(chunks)
            sf.write(output_path, wav, self._SAMPLE_RATE)
            return output_path

        return await asyncio.to_thread(_infer)


class PiperTTSProvider:
    """Piper (VITS) — local neural TTS via sherpa-onnx. 160+ models / 40+ langs.

    Re-added 2026-06-20 (the old direct-piper integration was dropped 2026-06-12).
    This routes through sherpa-onnx with k2-fsa's self-contained model tarballs,
    so it is neural VITS (policy-compliant) and needs no system espeak install.

    Voice id = a piper model key, e.g. ``en_US-amy-low``, ``en_GB-alan-medium``.
    Multi-speaker models accept a speaker id suffix: ``en_US-libritts_r-medium#42``.
    Models download + cache to ``output/_models/piper/`` on first use (~30-110 MB).
    """

    id = "piper"
    name = "Piper / sherpa-onnx (Local)"
    models = [
        ModelOption(id="en_US-amy-low", name="Amy (US female)", description="Fast, clear — default"),
        ModelOption(id="en_US-ryan-high", name="Ryan (US male)", description="High-quality US male"),
        ModelOption(id="en_GB-alan-medium", name="Alan (UK male)", description="UK male narrator"),
        ModelOption(id="en_US-libritts_r-medium", name="LibriTTS-R (904 speakers)", description="Multi-speaker — use #<sid>"),
    ]

    _DEFAULT = "en_US-amy-low"

    def __init__(self) -> None:
        self._engines: dict[str, object] = {}

    @classmethod
    def _ensure_model(cls, key: str) -> Path:
        """Download + extract the piper model tarball for `key` if missing.
        Returns the extracted model directory."""
        import tarfile
        import urllib.request

        d = _MODELS_DIR / f"vits-piper-{key}"
        if d.is_dir() and list(d.glob("*.onnx")):
            os.utime(d, None)  # mark recently used for LRU
            return d
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        tb = _MODELS_DIR / f"vits-piper-{key}.tar.bz2"
        if not tb.exists():
            url = _PIPER_RELEASE.format(key=key)
            try:
                urllib.request.urlretrieve(url, tb)
            except Exception as exc:
                raise RuntimeError(f"Piper model '{key}' download failed: {exc}") from exc
        with tarfile.open(tb, "r:bz2") as t:
            t.extractall(_MODELS_DIR)
        try:
            tb.unlink()  # free ~30-110 MB once extracted
        except OSError:
            pass
        if not (d.is_dir() and list(d.glob("*.onnx"))):
            raise RuntimeError(f"Piper model '{key}' extracted but no .onnx found")
        os.utime(d, None)  # bump mtime so LRU treats it as recently used
        cls._trim_disk(keep=d)
        return d

    @classmethod
    def _trim_disk(cls, keep: Path | None = None) -> None:
        """Keep at most _PIPER_MAX_MODELS extracted model dirs (LRU by mtime).
        Never deletes `keep` (the dir just downloaded/used)."""
        dirs = [p for p in _MODELS_DIR.glob("vits-piper-*") if p.is_dir()]
        if len(dirs) <= _PIPER_MAX_MODELS:
            return
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)  # newest first
        for old in dirs[_PIPER_MAX_MODELS:]:
            if keep and old == keep:
                continue
            shutil.rmtree(old, ignore_errors=True)

    def _engine(self, key: str):
        if key in self._engines:
            return self._engines[key]
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx not installed. Run: pip install sherpa-onnx"
            ) from exc
        d = self._ensure_model(key)
        onnx = str(next(d.glob("*.onnx")))
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=onnx,
                    tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"),
                ),
                num_threads=2, provider="cpu"),
            max_num_sentences=2)
        # RAM LRU: drop the oldest loaded engine before adding a new one (each
        # OfflineTts pins its model in memory; auditioning many voices would pile up).
        while len(self._engines) >= _PIPER_MAX_ENGINES:
            self._engines.pop(next(iter(self._engines)))
        self._engines[key] = sherpa_onnx.OfflineTts(cfg)
        return self._engines[key]

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,  # unused — Piper has fixed voices
        output_path: str,
        speed: float = 1.0,   # per-scene prosody pace (0.85 slow … 1.12 fast)
    ) -> str:
        spec = (model or self._DEFAULT).strip()
        key, _, sid_s = spec.partition("#")
        key = key or self._DEFAULT
        try:
            sid = int(sid_s) if sid_s else 0
        except ValueError:
            sid = 0
        _speed = max(0.5, min(float(speed or 1.0), 1.5))

        def _infer() -> str:
            import soundfile as sf
            eng = self._engine(key)
            audio = eng.generate(text, sid=sid, speed=_speed)
            if not len(audio.samples):
                raise RuntimeError(f"Piper produced no audio (model={key})")
            sf.write(output_path, audio.samples, audio.sample_rate)
            return output_path

        return await asyncio.to_thread(_infer)


class XTTSv2Provider:
    """XTTSv2 — voice cloning via Coqui TTS. Requires ``pip install TTS``.

    Slow on CPU; intended for per-channel brand voices generated in batch.
    """

    id = "xttsv2"
    name = "XTTSv2 (Local Cloning)"
    models = [
        ModelOption(id="tts_models/multilingual/multi-dataset/xtts_v2",
                    name="XTTS v2", description="Multilingual zero-shot clone")
    ]

    _tts = None  # cached model — load once

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,
        output_path: str,
        language: str = "en",
    ) -> str:
        if not voice_clone_path:
            raise ValueError("XTTSv2 requires voice_clone_path (reference audio)")

        def _infer() -> str:
            try:
                from TTS.api import TTS  # Coqui
            except ImportError as exc:
                raise RuntimeError(
                    "Coqui TTS not installed. Run: pip install TTS"
                ) from exc
            cls = XTTSv2Provider
            if cls._tts is None:
                cls._tts = TTS(model or self.models[0].id)
            cls._tts.tts_to_file(
                text=text,
                speaker_wav=voice_clone_path,
                language=language,
                file_path=output_path,
            )
            return output_path

        return await asyncio.to_thread(_infer)


class F5TTSProvider:
    """F5-TTS zero-shot voice cloning (local), ported from the voice-pro stack.

    Higher-fidelity clone than XTTSv2. Requires the optional ``f5-tts`` package
    (pulls torch). Lazy-imports so the module loads without the dependency;
    raises a clear error only when actually invoked without it installed.
    Inference runs in a thread — the f5_tts API is synchronous and blocking.
    """

    id = "f5tts"
    name = "F5-TTS (Local Cloning)"
    models = [
        ModelOption(id="F5TTS_v1_Base", name="F5-TTS v1 Base", description="Default zero-shot clone model"),
    ]

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,
        output_path: str,
    ) -> str:
        """Synthesize ``text`` in the reference speaker's voice.

        Args:
            text: Text to speak.
            model: F5-TTS model id (defaults to F5TTS_v1_Base).
            voice_clone_path: Reference audio (required — F5 is clone-only).
            output_path: Target .wav path.

        Returns:
            Path to the generated audio.
        """
        if not voice_clone_path:
            raise ValueError("F5-TTS requires voice_clone_path (reference audio for cloning)")

        def _infer() -> str:
            try:
                from f5_tts.api import F5TTS
            except ImportError as exc:
                raise RuntimeError(
                    "f5-tts not installed. Run: pip install f5-tts"
                ) from exc
            tts = F5TTS(model=model or self.models[0].id)
            tts.infer(
                ref_file=voice_clone_path,
                ref_text="",          # empty -> F5 auto-transcribes the reference
                gen_text=text,
                file_wave=output_path,
            )
            return output_path

        return await asyncio.to_thread(_infer)
