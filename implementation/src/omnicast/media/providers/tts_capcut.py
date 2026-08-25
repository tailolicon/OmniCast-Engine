"""CapCut TTS provider — real CapCut common_task API + legal fallbacks.

Spec form: ``capcut:<voice_type>`` (e.g. ``capcut:BV074_streaming``,
``capcut:en_us_002``).

Resolution order for synthesis
------------------------------
1. **CapCut editor API** (vendored K07VN/capcut-tts-api) when enabled — this is
   the actual CapCut/TikTok SAMI voice the catalog names.
2. **Volcengine seed-tts-2.0** when the operator has app keys and we have a
   nearest ByteDance-family speaker mapping.
3. **Edge neural** when the catalog declares an ``edge_fallback``.

Previously this provider only did (2)/(3). The unofficial API path is opt-out
via ``CAPCUT_TTS_ENABLED=0`` (default on). Device identity can be overridden
with ``CAPCUT_TTS_DEVICE_JSON`` (path to a device.json from CapCut PC).

Risk note: CapCut's editor API is not a public product contract. Use only with
an account/session you control; rate-limit bulk dubbing; prefer Volcengine for
production volume when you have keys.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from omnicast.media.capcut_voices import catalog, get_voice
from omnicast.media.providers.interfaces import ModelOption

_VENDOR_VOICE_JSON = (
    Path(__file__).resolve().parent / "_vendor" / "capcut_tts_api" / "data" / "Voice.json"
)

_FAIL_STATUSES = frozenset({"failed", "fail", "error"})


def api_enabled() -> bool:
    """CapCut API is on by default; set CAPCUT_TTS_ENABLED=0 to force fallbacks only."""
    raw = (os.environ.get("CAPCUT_TTS_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disabled")


def strict_mode() -> bool:
    """``CAPCUT_TTS_STRICT=1`` turns the silent Edge/Volcengine fallback into a failure.

    A dub job asks for a CapCut voice on purpose. Degrading a few hundred lines
    to ``edge:vi-VN-HoaiMyNeural`` one warning at a time produced a finished
    video in the wrong voice with nothing in the artifacts saying so — cheaper
    to fail on line 1 than to re-render an eight-minute retime afterwards.
    """
    raw = (os.environ.get("CAPCUT_TTS_STRICT") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on", "strict")


def _device_json_path() -> Path | None:
    raw = (os.environ.get("CAPCUT_TTS_DEVICE_JSON") or "").strip()
    if not raw:
        try:
            from omnicast.config.settings import get_settings

            raw = str(getattr(get_settings(), "capcut_tts_device_json", "") or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _poll_timeout() -> float:
    try:
        return max(15.0, float(os.environ.get("CAPCUT_TTS_TIMEOUT") or 90))
    except ValueError:
        return 90.0


def _poll_interval() -> float:
    try:
        return max(0.4, float(os.environ.get("CAPCUT_TTS_POLL_INTERVAL") or 1.0))
    except ValueError:
        return 1.0


def _retries() -> int:
    """Transient-error retries per line (``CAPCUT_TTS_RETRIES``, default 4).

    Dubbing a video is hundreds of sequential calls, and CapCut drops a
    connection every so often (WinError 10054). One reset used to end the whole
    job, so a bounded retry is the difference between finishing and restarting.
    """
    try:
        return max(0, int(os.environ.get("CAPCUT_TTS_RETRIES") or 4))
    except ValueError:
        return 4


def _is_permanent(exc: BaseException) -> bool:
    """A bad speaker id or rejected text will fail identically on every retry."""
    text = str(exc)
    return any(
        marker in text for marker in ("InvalidSpeaker", "InvalidText", "40402004")
    )


@lru_cache(maxsize=1)
def load_sdk_catalog() -> list[dict[str, Any]]:
    """Full CapCut Voice.json (129 entries when vendored file present)."""
    if not _VENDOR_VOICE_JSON.exists():
        return []
    try:
        raw = json.loads(_VENDOR_VOICE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        voice_type = str(item.get("voice_type") or "").strip()
        if not voice_type:
            continue
        lang = str(item.get("lang") or item.get("lan") or "").strip() or "und"
        label = str(item.get("display_name") or voice_type).strip()
        resource_id = str(item.get("resource_id") or "").strip()
        out.append(
            {
                "spec": f"capcut:{voice_type}",
                "speaker_id": voice_type,
                "voice_type": voice_type,
                "label": label,
                "gender": "unknown",
                "lang": lang,
                "provider": "capcut",
                "source": "capcut_sdk_voice_json",
                "desc": f"CapCut API · {label}",
                "resource_id": resource_id,
                "engine": "capcut_common_task",
            }
        )
    return out


def resolve_resource_id(voice_type: str) -> str | None:
    sid = (voice_type or "").strip()
    if sid.startswith("capcut:"):
        sid = sid.split(":", 1)[1]
    for row in load_sdk_catalog():
        if row["voice_type"] == sid or row["label"].lower() == sid.lower():
            rid = row.get("resource_id")
            return str(rid) if rid else None
    return None


def _make_client():
    from omnicast.media.providers._vendor.capcut_tts_api import CapCutClient, DeviceConfig

    device_path = _device_json_path()
    if device_path is not None:
        return CapCutClient(device=DeviceConfig.from_json_file(device_path))
    return CapCutClient()


def _parse_payload(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("payload")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def extract_speech_urls(query_response: dict[str, Any]) -> list[str]:
    """Pull CDN ``speech_url`` values from a CapCut TTS query response."""
    tasks = (query_response.get("data") or {}).get("tasks") or []
    urls: list[str] = []
    for task in tasks:
        payload = _parse_payload(task if isinstance(task, dict) else {})
        for block in payload.get("audio_subtitles") or []:
            if not isinstance(block, dict):
                continue
            url = block.get("speech_url") or block.get("url") or block.get("audio_url")
            if isinstance(url, str) and url.startswith("http"):
                urls.append(url)
        # Defensive: some builds may hoist the URL onto the task itself.
        for key in ("speech_url", "audio_url", "url"):
            val = task.get(key) if isinstance(task, dict) else None
            if isinstance(val, str) and val.startswith("http"):
                urls.append(val)
    # Dedup preserve order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _download_url(url: str, dest: Path, *, timeout: float = 60.0) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    fh.write(chunk)
        tmp.replace(dest)


def _maybe_convert_to_wav(mp3_path: Path, out: Path) -> None:
    if out.suffix.lower() == ".mp3":
        if mp3_path != out:
            out.write_bytes(mp3_path.read_bytes())
            if mp3_path != out:
                mp3_path.unlink(missing_ok=True)
        return
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "24000", str(out)],
        capture_output=True,
        text=True,
    )
    if mp3_path != out:
        mp3_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mp3→{out.suffix} failed: {(proc.stderr or '')[-400:]}")


def _rate_to_capcut(rate: object | None, speed: object | None) -> str:
    """Normalize Edge-style ``+8%`` / numeric speed into CapCut prosody rate."""
    if rate is not None:
        s = str(rate).strip()
        m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*%", s)
        if m:
            pct = float(m.group(1))
            return f"{max(0.5, min(2.0, 1.0 + pct / 100.0)):.2f}"
        try:
            return f"{max(0.5, min(2.0, float(s))):.2f}"
        except ValueError:
            pass
    if speed is not None:
        try:
            return f"{max(0.5, min(2.0, float(speed))):.2f}"
        except (TypeError, ValueError):
            pass
    return "1.0"


def synthesize_via_capcut_api(
    text: str,
    *,
    voice: str,
    output_path: str,
    rate: str = "1.0",
    timeout: float | None = None,
) -> str:
    """Blocking CapCut TTS → audio file, retrying transient failures."""
    import time

    attempts = _retries() + 1
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return _synthesize_once(
                text, voice=voice, output_path=output_path, rate=rate, timeout=timeout
            )
        except Exception as exc:
            last = exc
            if _is_permanent(exc) or attempt == attempts - 1:
                raise
            time.sleep(min(20.0, 2.0 * (2**attempt)))
    raise last if last else RuntimeError("CapCut TTS failed with no error recorded")


def _synthesize_once(
    text: str,
    *,
    voice: str,
    output_path: str,
    rate: str = "1.0",
    timeout: float | None = None,
) -> str:
    """One CapCut TTS round-trip. Raises on empty audio / API failure."""
    from omnicast.media.providers._vendor.capcut_tts_api.exceptions import CapCutError

    client = _make_client()
    voice_type = voice
    if voice_type.startswith("capcut:"):
        voice_type = voice_type.split(":", 1)[1]
    resource_id = resolve_resource_id(voice_type)

    try:
        query_res = client.generate_speech(
            texts=text,
            voice=voice_type,
            resource_id=resource_id,
            rate=rate,
            wait=True,
            poll_interval=_poll_interval(),
            timeout=timeout if timeout is not None else _poll_timeout(),
        )
    except CapCutError:
        raise
    except Exception as exc:
        raise RuntimeError(f"CapCut TTS request failed: {exc}") from exc

    tasks = (query_res.get("data") or {}).get("tasks") or []
    if tasks:
        status = str(tasks[0].get("status") or "").lower()
        if status in _FAIL_STATUSES:
            raise RuntimeError(f"CapCut TTS task failed: {tasks[0]!r}")

    urls = extract_speech_urls(query_res)
    if not urls:
        raise RuntimeError(
            "CapCut TTS returned no speech_url — "
            f"task keys={list(tasks[0].keys()) if tasks else []}"
        )

    out = Path(output_path)
    mp3_path = out if out.suffix.lower() == ".mp3" else out.with_suffix(".mp3.tmp")
    _download_url(urls[0], mp3_path)
    if not mp3_path.exists() or mp3_path.stat().st_size < 64:
        raise RuntimeError("CapCut TTS download produced empty audio")
    _maybe_convert_to_wav(mp3_path, out)
    if not out.exists() or out.stat().st_size < 64:
        raise RuntimeError(f"CapCut TTS wrote empty file: {out}")
    return str(out)


class CapCutTTSProvider:
    """CapCut/TikTok voices via CapCut API, with Volcengine/Edge fallbacks."""

    id = "capcut"
    name = "CapCut TTS (API + Edge/Volcengine fallback)"
    cost_per_unit = 0.0
    rate_limit: dict = {"rpm": 30}
    capability = "tts"

    # CapCut consumer speaker ids ≠ Volcengine seed-tts ids (zero exact
    # overlap). These are nearest ByteDance-family equivalents so `capcut:` still
    # synthesizes through the official engine when keys exist and CapCut API is
    # disabled/failing.
    _VOLCENGINE_EQUIVALENT: dict[str, str] = {
        "BV074_streaming": "zh_female_vv_uranus_bigtts",
        "BV075_streaming": "zh_male_m191_uranus_bigtts",
        "BV421_vivn_streaming": "zh_female_vv_uranus_bigtts",
        "en_us_001": "en_female_dacey_uranus_bigtts",
        "en_us_002": "en_female_dacey_uranus_bigtts",
        "en_female_samc": "en_female_stokie_uranus_bigtts",
        "en_female_makeup": "en_female_dacey_uranus_bigtts",
        "en_female_richgirl": "en_female_stokie_uranus_bigtts",
        "en_female_shenna": "en_female_dacey_uranus_bigtts",
        "en_female_pansino": "en_female_stokie_uranus_bigtts",
        "en_female_betty": "en_female_dacey_uranus_bigtts",
        "en_female_emotional": "en_female_stokie_uranus_bigtts",
        "en_us_006": "en_male_tim_uranus_bigtts",
        "en_us_007": "en_male_tim_uranus_bigtts",
        "en_us_009": "en_male_tim_uranus_bigtts",
        "en_us_010": "en_male_tim_uranus_bigtts",
        "en_male_cody": "en_male_tim_uranus_bigtts",
        "en_male_narration": "en_male_tim_uranus_bigtts",
        "en_uk_001": "en_male_tim_uranus_bigtts",
        "en_uk_003": "en_male_tim_uranus_bigtts",
        "de_001": "zh_female_vv_uranus_bigtts",
        "de_002": "zh_male_m191_uranus_bigtts",
        "fr_001": "zh_male_m191_uranus_bigtts",
        "fr_002": "zh_male_m191_uranus_bigtts",
        "es_002": "zh_male_m191_uranus_bigtts",
        "es_mx_002": "zh_male_m191_uranus_bigtts",
        "br_001": "zh_female_vv_uranus_bigtts",
        "br_003": "zh_female_sophie_uranus_bigtts",
        "br_004": "zh_female_tianmeitaozi_uranus_bigtts",
        "br_005": "zh_male_m191_uranus_bigtts",
        "id_001": "zh_female_vv_uranus_bigtts",
        "jp_001": "zh_female_vv_uranus_bigtts",
        "jp_003": "zh_female_sophie_uranus_bigtts",
        "jp_005": "zh_female_qingxinnvsheng_uranus_bigtts",
        "jp_006": "zh_male_m191_uranus_bigtts",
        "kr_002": "zh_male_m191_uranus_bigtts",
        "kr_003": "zh_female_vv_uranus_bigtts",
        "kr_004": "zh_male_m191_uranus_bigtts",
    }

    @property
    def models(self) -> list[ModelOption]:
        # Prefer full SDK catalog; fall back to curated rows that have a legal
        # stand-in so the UI always has something synthesizable offline.
        sdk = load_sdk_catalog()
        if sdk:
            return [
                ModelOption(id=v["voice_type"], name=v["label"], description=v["desc"])
                for v in sdk
            ]
        return [
            ModelOption(
                id=v["speaker_id"],
                name=f"{v['label']} ({v['lang']})",
                description=v["desc"],
            )
            for v in catalog()
            if v.get("edge_fallback") or v["speaker_id"] in self._VOLCENGINE_EQUIVALENT
        ]

    async def health_check(self) -> dict:
        enabled = api_enabled()
        detail = "api disabled (fallback only)" if not enabled else "ready"
        if enabled:
            try:
                client = _make_client()
                # Cheap local check — catalog load + client construct.
                n = len(client.list_voices(catalog_path=_VENDOR_VOICE_JSON))
                detail = f"api enabled · {n} voices in Voice.json"
            except Exception as exc:
                return {
                    "provider": self.id,
                    "healthy": False,
                    "detail": f"sdk unavailable: {exc}",
                    "api_enabled": enabled,
                }
        return {
            "provider": self.id,
            "healthy": True,
            "detail": detail,
            "api_enabled": enabled,
            "voices": len(self.models),
            "device_json": str(_device_json_path()) if _device_json_path() else None,
        }

    @staticmethod
    def resolve_fallback(speaker_id: str) -> str:
        """Legal/official stand-in when CapCut API is off or fails."""
        sid = (speaker_id or "").strip()
        if sid.startswith("capcut:"):
            sid = sid.split(":", 1)[1]

        voice = get_voice(sid)
        # Unknown to curated catalog is OK if it exists in Voice.json — caller
        # should have tried the API first.
        from omnicast.media.providers.tts_volcengine import load_credentials

        appid, token = load_credentials()
        equivalent = CapCutTTSProvider._VOLCENGINE_EQUIVALENT.get(sid)
        if appid and token and equivalent:
            return f"volcengine:{equivalent}"

        fallback = (voice or {}).get("edge_fallback") if voice else None
        if not fallback:
            # Try display-name match against SDK catalog → common Edge VN voices.
            for row in load_sdk_catalog():
                if row["voice_type"] == sid:
                    lang = (row.get("lang") or "").lower()
                    if lang.startswith("vi"):
                        return "edge:vi-VN-HoaiMyNeural"
                    if lang.startswith("en"):
                        return "edge:en-US-JennyNeural"
                    break
            raise RuntimeError(
                f"CapCut voice {sid!r} has no Volcengine/Edge fallback — "
                f"enable CAPCUT_TTS_ENABLED=1 for the real CapCut API, or pick "
                f"a catalog voice with edge_fallback."
            )
        return str(fallback)

    # Back-compat alias used by preview endpoint + older tests.
    resolve = resolve_fallback

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        voice_clone_path: str | None = None,
        output_path: str,
        rate: str | None = None,
        speed: float | None = None,
        **prosody: object,
    ) -> str:
        from omnicast.media.providers.registry import get_tts_provider
        from omnicast.media.voice_router import VoiceSpec, _supported_prosody

        if not model:
            raise RuntimeError(
                "capcut provider needs a speaker id, e.g. capcut:BV074_streaming"
            )

        sid = model.strip()
        if sid.startswith("capcut:"):
            sid = sid.split(":", 1)[1]

        # 1) Real CapCut API (default).
        if api_enabled():
            capcut_rate = _rate_to_capcut(
                rate if rate is not None else prosody.get("rate"),
                speed if speed is not None else prosody.get("speed"),
            )
            try:
                return await asyncio.to_thread(
                    synthesize_via_capcut_api,
                    text,
                    voice=sid,
                    output_path=output_path,
                    rate=capcut_rate,
                )
            except Exception as exc:
                if strict_mode():
                    raise RuntimeError(
                        f"CapCut API failed for {sid!r} and CAPCUT_TTS_STRICT is on "
                        f"(no Edge/Volcengine substitution): {exc}"
                    ) from exc
                # Fall through to legal stand-ins — router already treats this
                # provider as one chain entry; internal fallback keeps brand voice
                # family when possible without failing the whole job.
                try:
                    import structlog

                    structlog.get_logger().warning(
                        "capcut_api_failed_using_fallback",
                        voice=sid,
                        error=str(exc)[:240],
                    )
                except Exception:
                    pass

        # 2) Volcengine / Edge stand-in.
        fallback_spec = self.resolve_fallback(sid)
        spec = VoiceSpec.parse(fallback_spec)
        delegate = get_tts_provider(spec.provider)
        fwd: dict[str, object] = dict(prosody)
        if rate is not None:
            fwd["rate"] = rate
        if speed is not None:
            fwd["speed"] = speed
        return await delegate.generate(
            text,
            model=spec.voice,
            voice_clone_path=voice_clone_path,
            output_path=output_path,
            **_supported_prosody(delegate, fwd),
        )
