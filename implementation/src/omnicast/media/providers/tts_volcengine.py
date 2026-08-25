"""Volcengine / Doubao seed-tts-2.0 — ByteDance's own speech API.

This is the engine family behind CapCut's built-in voices, reached through
ByteDance's documented endpoint instead of the app or a reverse-engineered
private route. Ported from `_refs/pyvideotrans/videotrans/tts/_doubao2.py`.

Two things make it usable for Vietnamese even though the speaker catalog is
Chinese/English: the request declares `explicit_language=crosslingual` and turns
on the language detector, so a `zh_female_*` speaker reads Vietnamese text in
that speaker's voice. That is the same trick CapCut uses to offer one voice set
across languages.

Full speaker catalog (102 ids) lives in
``omnicast/media/data/doubao2_voices.json`` (copied from pyvideotrans).

Credentials are the operator's own Volcengine app (`X-Api-App-Id` +
`X-Api-Access-Key`). Set them in `.env`:

    VOLCENGINE_TTS_APPID=...
    VOLCENGINE_TTS_ACCESS_TOKEN=...
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any

from omnicast.media.providers.interfaces import ITTSProvider, ModelOption

API_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RESOURCE_ID = "seed-tts-2.0"
MODEL = "seed-tts-2.0-standard"

SAMPLE_RATE = 48_000

# Terminal status the stream sends when synthesis finished cleanly.
_DONE_CODE = 20_000_000

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "doubao2_voices.json"

# Featured subset kept for UI defaults / docs; full list comes from the JSON.
_FEATURED_FEMALE: tuple[tuple[str, str], ...] = (
    ("zh_female_vv_uranus_bigtts", "Vivi — mặc định, trong trẻo"),
    ("zh_female_sophie_uranus_bigtts", "Sophie — quyến rũ"),
    ("zh_female_qingxinnvsheng_uranus_bigtts", "Thanh tân — nhẹ, sáng"),
    ("zh_female_cancan_uranus_bigtts", "Càn Càn — tri thức"),
    ("zh_female_tianmeixiaoyuan_uranus_bigtts", "Tiểu Nguyên — ngọt"),
    ("zh_female_tianmeitaozi_uranus_bigtts", "Đào Tử — ngọt, trẻ"),
    ("zh_female_shuangkuaisisi_uranus_bigtts", "Tư Tư — dứt khoát"),
    ("zh_female_linjianvhai_uranus_bigtts", "Cô gái hàng xóm"),
    ("zh_female_xiaohe_uranus_bigtts", "Tiểu Hà"),
    ("zh_female_kefunvsheng_uranus_bigtts", "Nắng ấm — ấm, dịu"),
    ("en_female_dacey_uranus_bigtts", "Dacey — English female"),
    ("en_female_stokie_uranus_bigtts", "Stokie — English female"),
    ("en_male_tim_uranus_bigtts", "Tim — English male"),
)

DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"


class VolcengineCredentialsMissing(RuntimeError):
    """Raised when the Volcengine app id / access token are not configured."""


def load_credentials() -> tuple[str, str]:
    """Return (appid, access_token) from OmniCast settings or the environment."""
    appid = os.environ.get("VOLCENGINE_TTS_APPID", "")
    token = os.environ.get("VOLCENGINE_TTS_ACCESS_TOKEN", "")
    if not (appid and token):
        try:
            from omnicast.config.settings import get_settings

            settings = get_settings()
            appid = appid or getattr(settings, "volcengine_tts_appid", "")
            token = token or getattr(settings, "volcengine_tts_access_token", "")
        except Exception:
            pass
    return appid, token


@lru_cache(maxsize=1)
def load_speaker_catalog() -> dict[str, str]:
    """Map display name → speaker id (102 seed-tts-2.0 voices).

    The JSON has ``zh`` / ``en`` locale keys with the same speaker set (crosslingual).
    We keep a single deduped map keyed by display name.
    """
    if not _CATALOG_PATH.exists():
        return {name: sid for sid, name in _FEATURED_FEMALE}
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8-sig"))
    out: dict[str, str] = {}
    for locale_map in raw.values():
        if isinstance(locale_map, dict):
            for name, speaker_id in locale_map.items():
                if isinstance(name, str) and isinstance(speaker_id, str):
                    out[name] = speaker_id
    # Featured labels win if JSON uses different display text for same id.
    for speaker_id, label in _FEATURED_FEMALE:
        if label not in out:
            out[label] = speaker_id
    return out


@lru_cache(maxsize=1)
def list_speakers() -> list[dict[str, Any]]:
    """Full catalog as list of {speaker_id, label, gender, lang, spec}."""
    name_to_id = load_speaker_catalog()
    # Reverse: one entry per speaker id (prefer first display name seen).
    by_id: dict[str, str] = {}
    for name, sid in name_to_id.items():
        by_id.setdefault(sid, name)

    entries: list[dict[str, Any]] = []
    for speaker_id, label in sorted(by_id.items(), key=lambda x: x[1].lower()):
        gender = "unknown"
        lang = "zh"
        low = speaker_id.lower()
        if "female" in low or "nv" in low:
            gender = "female"
        elif "male" in low:
            gender = "male"
        if low.startswith("en_"):
            lang = "en"
        elif low.startswith("zh_") or low.startswith("saturn_zh_"):
            lang = "zh"
        entries.append(
            {
                "spec": f"volcengine:{speaker_id}",
                "speaker_id": speaker_id,
                "label": label,
                "gender": gender,
                "lang": lang,
                "provider": "volcengine",
                "source": "bytedance_seed_tts_2",
                "desc": f"Doubao seed-tts-2.0 · {label}",
                "engine": "seed-tts-2.0",
            }
        )
    return entries


def resolve_speaker(name_or_id: str) -> str:
    """Accept speaker id or display name; return canonical speaker id."""
    raw = (name_or_id or "").strip()
    if raw.startswith("volcengine:"):
        raw = raw.split(":", 1)[1]
    if not raw:
        return DEFAULT_SPEAKER
    catalog = load_speaker_catalog()
    if raw in catalog.values():
        return raw
    if raw in catalog:
        return catalog[raw]
    # Case-insensitive display-name match.
    low = raw.lower()
    for name, sid in catalog.items():
        if name.lower() == low:
            return sid
    return raw  # pass through — account may have speakers not in our JSON


def _write_pcm_as_wav(pcm: bytes, output_path: Path, *, channels: int = 1) -> None:
    """The API streams raw PCM; the rest of the pipeline expects a WAV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)  # pcm_s16
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)


def _model_options() -> list[ModelOption]:
    """All speakers for registry / capability bus (full catalog when JSON present)."""
    speakers = list_speakers()
    if speakers:
        return [
            ModelOption(id=s["speaker_id"], name=s["label"], description=s["desc"])
            for s in speakers
        ]
    return [ModelOption(id=v, name=v, description=d) for v, d in _FEATURED_FEMALE]


class VolcengineTTSProvider:
    """ByteDance seed-tts-2.0 — full CapCut-family TTS via official API."""

    id = "volcengine"
    name = "Volcengine / Doubao seed-tts-2.0 (ByteDance)"
    models = _model_options()
    # Billed per character by Volcengine; the real figure depends on the
    # operator's plan, so it is not asserted here.
    cost_per_unit = 0.0
    rate_limit: dict = {}
    capability = "tts"

    async def health_check(self) -> dict:
        appid, token = load_credentials()
        configured = bool(appid and token)
        return {
            "provider": self.id,
            "healthy": configured,
            "detail": (
                "ready"
                if configured
                else "set VOLCENGINE_TTS_APPID + VOLCENGINE_TTS_ACCESS_TOKEN"
            ),
            "voices": len(self.models),
            "catalog_path": str(_CATALOG_PATH) if _CATALOG_PATH.exists() else None,
        }

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,  # unused — fixed speaker catalog
        output_path: str,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> str:
        appid, token = load_credentials()
        if not (appid and token):
            raise VolcengineCredentialsMissing(
                "Volcengine TTS needs VOLCENGINE_TTS_APPID and "
                "VOLCENGINE_TTS_ACCESS_TOKEN (see .env)"
            )

        speaker = resolve_speaker(model or DEFAULT_SPEAKER)
        # The API takes percentage deltas, not multipliers.
        speech_rate = int(min(max(100 * (float(speed) - 1.0), -50.0), 100.0))
        loudness_rate = int(min(max(100 * (float(volume) - 1.0), -50.0), 100.0))

        def _synthesize() -> str:
            import requests

            headers = {
                "X-Api-App-Id": appid,
                "X-Api-Access-Key": token,
                "X-Api-Resource-Id": RESOURCE_ID,
                "Content-Type": "application/json",
                "Connection": "keep-alive",
            }
            payload = {
                "user": {"uid": f"{time.time()}"},
                "req_params": {
                    "text": text,
                    "speaker": speaker,
                    "model": MODEL,
                    "audio_params": {
                        "format": "pcm",
                        "sample_rate": SAMPLE_RATE,
                        "enable_timestamp": True,
                        "speech_rate": speech_rate,
                        "loudness_rate": loudness_rate,
                    },
                    # Lets a zh/en speaker read Vietnamese in its own voice.
                    "additions": json.dumps(
                        {
                            "explicit_language": "crosslingual",
                            "enable_language_detector": "true",
                            "disable_markdown_filter": True,
                        }
                    ),
                },
            }

            response = requests.post(API_URL, headers=headers, json=payload,
                                     stream=True, timeout=180)
            if response.status_code in (400, 401, 402, 404):
                raise RuntimeError(
                    f"Volcengine rejected the request ({response.status_code}) — "
                    f"check app id / access token"
                )
            if response.status_code == 403:
                raise RuntimeError(
                    f"Speaker {speaker!r} is not enabled on this Volcengine account "
                    f"(403) — it may need to be purchased in the console"
                )
            response.raise_for_status()

            audio = bytearray()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                chunk = json.loads(line)
                code = chunk.get("code", 0)
                if code == _DONE_CODE:
                    break
                if code:
                    raise RuntimeError(f"Volcengine TTS error: {chunk}")
                if chunk.get("data"):
                    audio.extend(base64.b64decode(chunk["data"]))

            if not audio:
                raise RuntimeError(f"Volcengine returned no audio for speaker {speaker!r}")

            out = Path(output_path)
            _write_pcm_as_wav(bytes(audio), out)
            return str(out)

        return await asyncio.to_thread(_synthesize)
