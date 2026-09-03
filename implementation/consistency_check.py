"""Character consistency QA — verify generated scene stills against the channel
mascot's DNA BEFORE they enter the video.

Pattern ported from Orkas-VideoStudio's stage-consistency skill (MIT): catch
identity drift at the STILL — re-rolling a cheap image (Flow image gen is free)
is far cheaper than discovering the drift after composing/animating. Rules kept
from the source skill:

  - verify against the DNA identity axes (face/hair/build/outfit), not vibes;
  - re-roll the image, bounded, never the downstream work;
  - NEVER hard-fail the render — keep the best candidate and note the
    shortcoming (a drifted mascot beats no video in a 24/7 pipeline);
  - cache verdicts by content hash so a resumed run re-verifies nothing.

Uses the same Gemini vision access as character_dna.py; silently no-ops when
GOOGLE_API_KEY is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
_VERIFY_CACHE = ROOT / "output" / "_characters" / "_verify"

# Bounds: verification is an LLM-vision call per image; re-rolls spend provider
# quota. Caps keep a long video from turning QA into its own cost center.
# Env overrides (WS1): OMNICAST_CONSISTENCY_MAX_CHECKS (0 = unlimited).
MAX_CHECKS_DEFAULT = 16
MAX_REROLLS_DEFAULT = 4

# Cache-key salt: v2 verdicts carry a quantitative score — old binary verdicts
# must not be served to scored runs.
_VERDICT_VERSION = "v2"

# Gate thresholds (env-tunable). drift_ratio = drifted / checked.
GATE_MAX_DRIFT_DEFAULT = 0.34


class ConsistencyGateError(SystemExit):
    """Raised (gate=block) when identity drift exceeds the threshold.

    Deliberately subclasses SystemExit: the render wraps the consistency call in
    a blanket `except Exception` (QA must never crash a render by accident), so
    an opt-in HARD gate has to ride an exception class that `except Exception`
    does not catch. Default gate mode is "warn" — nothing changes unless the
    operator sets OMNICAST_CONSISTENCY_GATE=block.
    """

    def __init__(self, message: str) -> None:
        super().__init__(3)  # exit code 3 = consistency gate
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.message


def _norm_verdict(data: dict) -> dict:
    """Normalize a raw/cached verdict to {match, score, axes, reason}.

    Old cached v1 verdicts have no score — derive 10/0 from match so
    aggregates stay meaningful without re-spending vision calls.
    """
    match = bool(data.get("match"))
    score = data.get("score")
    try:
        score = max(0.0, min(10.0, float(score)))
    except (TypeError, ValueError):
        score = 10.0 if match else 0.0
    axes = data.get("axes") if isinstance(data.get("axes"), dict) else {}
    return {"match": match, "score": score, "axes": axes,
            "reason": str(data.get("reason", ""))[:200]}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_path(image_path: Path, dna_block: str) -> Path | None:
    try:
        key = _sha(image_path.read_bytes() + dna_block.encode("utf-8")
                   + _VERDICT_VERSION.encode("utf-8"))
        return _VERIFY_CACHE / f"{key[:40]}.json"
    except Exception:
        return None


def verify_image(image_path: Path, dna_block: str) -> dict | None:
    """Vision-check one still against the DNA block.

    Returns {"match": bool, "reason": str} or None when unverifiable (no API
    key / API error) — the caller treats None as "unverified", never as a fail.
    Verdicts are cached by (image bytes + DNA) hash.
    """
    cp = _cache_path(image_path, dna_block)
    if cp and cp.exists():
        try:
            return _norm_verdict(json.loads(cp.read_text(encoding="utf-8")))
        except Exception:
            pass
    import sys
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from omnicast.config.settings import get_settings
        s = get_settings()
        if not s.google_api_key:
            return None
        from google import genai
        from google.genai import types

        img = image_path.read_bytes()
        client = genai.Client(api_key=s.google_api_key)
        prompt = (
            "You are a character-identity QA checker for AI video. The video's "
            f"recurring character is defined as: \"{dna_block}\".\n"
            "Check the image against the IDENTITY axes only (gender, age range, "
            "facial features, hair style+color, body shape, signature outfit). "
            "Ignore pose, expression, lighting, background, art-style rendering "
            "differences. If the image shows NO humanoid character at all, that "
            "is a match (nothing contradicts the identity).\n"
            "Score identity fidelity 0-10 (10 = unmistakably the same character, "
            "0 = clearly a different person). Also score each axis 0-10.\n"
            "Output ONLY JSON: {\"match\": true|false, \"score\": <0-10>, "
            "\"axes\": {\"face\": <0-10>, \"hair\": <0-10>, \"build\": <0-10>, "
            "\"outfit\": <0-10>}, \"reason\": \"<short>\"}"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_bytes(data=img, mime_type="image/png"), prompt],
        )
        txt = resp.candidates[0].content.parts[0].text
        m = re.search(r"\{[\s\S]*\}", txt)
        data = json.loads(m.group(0) if m else txt)
        verdict = _norm_verdict(data)
        if cp:
            _VERIFY_CACHE.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
        return verdict
    except Exception as exc:
        print(f"      [warn] consistency verify failed for "
              f"{image_path.name}: {str(exc)[:80]}")
        return None


def _resolve_max_checks(max_checks: int | None) -> int:
    """Explicit arg wins; else env OMNICAST_CONSISTENCY_MAX_CHECKS (0 =
    unlimited); else the historical default of 16."""
    if max_checks is not None:
        return max_checks if max_checks > 0 else 10**9
    try:
        env = int(os.environ.get("OMNICAST_CONSISTENCY_MAX_CHECKS", ""))
        return env if env > 0 else 10**9
    except ValueError:
        return MAX_CHECKS_DEFAULT


def _gate_mode(gate: str | None) -> str:
    mode = (gate or os.environ.get("OMNICAST_CONSISTENCY_GATE", "warn")).lower()
    return mode if mode in ("off", "warn", "block") else "warn"


def apply_gate(report: dict, gate: str | None = None,
               max_drift: float | None = None) -> None:
    """Image gate before render (WS1): judge the aggregate drift of a verified
    scene set. gate=off → no-op; warn (default) → print; block → raise
    ConsistencyGateError when drift_ratio exceeds the threshold
    (OMNICAST_CONSISTENCY_GATE_MAX_DRIFT, default 0.34)."""
    mode = _gate_mode(gate)
    if mode == "off" or not report.get("checked"):
        return
    if max_drift is None:
        try:
            max_drift = float(os.environ.get(
                "OMNICAST_CONSISTENCY_GATE_MAX_DRIFT", GATE_MAX_DRIFT_DEFAULT))
        except ValueError:
            max_drift = GATE_MAX_DRIFT_DEFAULT
    ratio = report.get("drift_ratio", 0.0)
    if ratio <= max_drift:
        return
    msg = (f"consistency gate: drift_ratio {ratio:.2f} > {max_drift:.2f} "
           f"({len(report.get('drifted', []))}/{report['checked']} drifted, "
           f"mean_score {report.get('mean_score', 0):.1f}/10)")
    if mode == "warn":
        print(f"      [consistency] WARN {msg}")
        return
    raise ConsistencyGateError(
        f"{msg} — render blocked (OMNICAST_CONSISTENCY_GATE=block). "
        "Fix the character anchor/ingredients or relax the threshold.")


def _write_report(report: dict, report_path: Path) -> None:
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # report is telemetry, never fatal
        print(f"      [consistency] report write failed: {str(exc)[:80]}")


def verify_scenes(
    scene_images: dict[int, Path],
    dna_block: str,
    *,
    regen: Callable[[int, Path], bool] | None = None,
    max_checks: int | None = None,
    max_rerolls: int = MAX_REROLLS_DEFAULT,
    report_path: Path | str | None = None,
    gate: str | None = None,
) -> dict:
    """Verify generated scene stills against the mascot DNA; re-roll drifted ones.

    scene_images: scene index -> generated PNG path (only GENERATED shots — web
    photos/stock frames are not the mascot and must not be checked).
    regen(i, path) -> bool: caller-supplied re-generator (same prompt, fresh
    roll, must also refresh the caller's prompt-cache). None = verify-only.
    max_checks: explicit cap; None → env OMNICAST_CONSISTENCY_MAX_CHECKS
    (0 = unlimited) → default 16.
    report_path: when set, the full report (per-scene verdicts + aggregates)
    is written there as JSON (`_consistency_report.json` in the product dir).
    gate: "off"|"warn"|"block" (None → env OMNICAST_CONSISTENCY_GATE, default
    warn). block raises ConsistencyGateError when drift_ratio exceeds
    OMNICAST_CONSISTENCY_GATE_MAX_DRIFT — the ONLY path that stops a render.

    Returns {"checked", "passed", "rerolled": [i], "drifted": [i],
    "unverified": [i], "scores": {i: 0-10}, "drift_ratio", "mean_score"} —
    with the default gate (warn), "drifted" shots stay in the video (never
    hard-fail), they are surfaced for the operator/status instead.
    """
    out: dict = {"checked": 0, "passed": 0, "rerolled": [], "drifted": [],
                 "unverified": [], "scores": {}, "verdicts": {},
                 "drift_ratio": 0.0, "mean_score": 0.0}
    if not dna_block or not scene_images:
        return out
    limit = _resolve_max_checks(max_checks)
    rerolls_left = max_rerolls
    consecutive_errors = 0
    for i in sorted(scene_images)[:limit]:
        img = scene_images[i]
        if not img.exists():
            continue
        v = verify_image(img, dna_block)
        if v is None:
            out["unverified"].append(i)
            consecutive_errors += 1
            if consecutive_errors >= 2:
                # Vision API down/keyless — stop burning calls; rest unverified.
                out["unverified"] += [j for j in sorted(scene_images)[:limit]
                                      if j > i]
                break
            continue
        v = _norm_verdict(v)
        consecutive_errors = 0
        out["checked"] += 1
        out["scores"][i] = v["score"]
        out["verdicts"][i] = v
        if v["match"]:
            out["passed"] += 1
            continue
        print(f"      [consistency] scene {i}: identity drift — {v['reason']}")
        if regen is None or rerolls_left <= 0:
            out["drifted"].append(i)
            continue
        rerolls_left -= 1
        ok = False
        try:
            ok = bool(regen(i, img))
        except Exception as exc:
            print(f"      [consistency] re-roll error scene {i}: {str(exc)[:80]}")
        v2 = _norm_verdict(verify_image(img, dna_block) or {}) if ok else None
        if v2 and v2["match"]:
            out["rerolled"].append(i)
            out["passed"] += 1
            out["scores"][i] = v2["score"]
            out["verdicts"][i] = v2
            print(f"      [consistency] scene {i}: re-roll fixed the drift")
        else:
            # Keep the best we have and note the shortcoming (never hard-fail).
            out["drifted"].append(i)
            if v2:
                out["scores"][i] = v2["score"]
                out["verdicts"][i] = v2
                print(f"      [consistency] scene {i}: still drifted after "
                      f"re-roll — {v2['reason']} (keeping)")
    # Quantitative aggregates (WS1): measurable drift instead of log lines only.
    if out["checked"]:
        out["drift_ratio"] = round(len(out["drifted"]) / out["checked"], 4)
        out["mean_score"] = round(
            sum(out["scores"].values()) / len(out["scores"]), 2)
    if report_path:
        _write_report(out, Path(report_path))
    apply_gate(out, gate)
    return out
