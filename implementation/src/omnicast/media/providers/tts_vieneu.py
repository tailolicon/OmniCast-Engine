"""VieNeu — local neural Vietnamese TTS (14 preset voices + reference cloning).

Added 2026-08-08 for the Douyin reup workstream, but registered as a normal
provider so any Vietnamese channel can use it: `vieneu:Minh Đức`.

Runs fully local through ONNX Runtime. Unlike the 2.x line it needs no eSpeak NG
install — 3.x phonemises with the bundled `sea_g2p` wheel. Models (~165 MB
backbone + ~90 MB audio tokenizer) download to the HF cache on first use.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from omnicast.media.providers.interfaces import ITTSProvider, ModelOption

# The catalogue ships in the model repo's voices_v3_turbo.json; mirroring the
# useful ones here keeps voice pickers working without loading the model. The
# authoritative list is always `provider.list_voices()`.
_VIENEU_VOICES: tuple[tuple[str, str], ...] = (
    ("Minh Đức", "Nam · Bắc · tin tức"),
    ("Mai Anh", "Nữ · Bắc · tin tức"),
    ("Phạm Tuyên", "Nam · Bắc · tự nhiên"),
    ("Trúc Ly", "Nữ · Bắc · tự nhiên"),
    ("Đoan Trang", "Nữ · Bắc · tự nhiên"),
    ("Thanh Bình", "Nam · Bắc · kể chuyện"),
    ("Ngọc Linh", "Nữ · Bắc · kể chuyện"),
    ("Minh Triết", "Nam · Nam · tin tức"),
    ("Thùy Dung", "Nữ · Nam · tin tức"),
    ("Xuân Vĩnh", "Nam · Nam · tự nhiên"),
    ("Thái Sơn", "Nam · Nam · kể chuyện"),
    ("Thục Đoan", "Nữ · Nam · kể chuyện"),
    ("Quang Sơn", "Nam · Trung · tự nhiên"),
    ("Ngọc Trân", "Nữ · Trung · tự nhiên"),
)

_DEFAULT_VOICE = "Ngọc Linh"

# `infer` exposes no rate control, so pace is an ffmpeg pass afterwards. atempo
# only accepts 0.5–2.0 per filter instance, which is well outside anything a
# channel should be asking for anyway.
_MIN_SPEED = 0.5
_MAX_SPEED = 2.0


class VieneuTTSProvider:
    """VieNeu v3 Turbo — Vietnamese neural TTS, local ONNX."""

    id = "vieneu"
    name = "VieNeu v3 Turbo (Local, Vietnamese)"
    models = [
        ModelOption(id=voice, name=voice, description=description)
        for voice, description in _VIENEU_VOICES
    ]
    cost_per_unit = 0.0
    rate_limit: dict = {}
    capability = "tts"

    _SAMPLE_RATE = 48_000

    def __init__(self) -> None:
        self._client: object | None = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import vieneu
        except ImportError as exc:
            raise RuntimeError(
                "vieneu not installed. Run: pip install 'vieneu>=3.2,<4'"
            ) from exc
        # Model load is slow (ONNX sessions + ~250 MB of weights); one per process.
        self._client = vieneu.Vieneu()
        return self._client

    async def health_check(self) -> dict:
        import importlib.util

        installed = importlib.util.find_spec("vieneu") is not None
        return {
            "provider": self.id,
            "healthy": installed,
            "detail": "ok" if installed else "package `vieneu` not installed",
            "voices": len(self.models),
            "loaded": self._client is not None,
        }

    def list_voices(self) -> list[tuple[str, str]]:
        """Live catalogue from the loaded model: list of (description, voice_id)."""
        return list(self._get_client().list_preset_voices())

    @staticmethod
    def _apply_speed(wav_path: Path, speed: float) -> None:
        """Re-time in place with ffmpeg atempo (pitch-preserving)."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not on PATH — needed to apply VieNeu speed")
        with tempfile.TemporaryDirectory() as tmp:
            retimed = Path(tmp) / "retimed.wav"
            result = subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error",
                 "-i", str(wav_path), "-filter:a", f"atempo={speed:.3f}",
                 str(retimed)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not retimed.is_file():
                raise RuntimeError(f"atempo pass failed: {result.stderr.strip()[:300]}")
            shutil.copyfile(retimed, wav_path)

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,
        output_path: str,
        speed: float = 1.0,
        style: str | None = None,
    ) -> str:
        voice_id = (model or _DEFAULT_VOICE).strip()
        speed = max(_MIN_SPEED, min(float(speed or 1.0), _MAX_SPEED))

        def _infer() -> str:
            client = self._get_client()
            kwargs: dict[str, object] = {"text": text}

            if voice_clone_path:
                reference = Path(voice_clone_path)
                if not reference.is_file():
                    raise RuntimeError(f"VieNeu reference audio not found: {reference}")
                kwargs["ref_audio"] = str(reference)
                # VieNeu clones best with a transcript of the reference; the
                # convention (shared with the reup batch importer) is a sidecar
                # .txt of the same name.
                sidecar = reference.with_suffix(".txt")
                if sidecar.is_file():
                    kwargs["ref_text"] = sidecar.read_text(encoding="utf-8").strip()
            else:
                kwargs["voice"] = client.get_preset_voice(voice_id)

            if style:
                kwargs["style"] = style

            audio = client.infer(**kwargs)
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            client.save(audio, str(out))
            if not out.is_file() or out.stat().st_size <= 44:
                raise RuntimeError(f"VieNeu produced no audio (voice={voice_id})")
            if abs(speed - 1.0) > 0.01:
                self._apply_speed(out, speed)
            return str(out)

        return await asyncio.to_thread(_infer)
