"""Channel intro/outro bumpers — brand-consistent, render-ONCE, reused on every video.

A channel declares its bumpers in channels/<id>.json:

    "intro_clip": { "template": "remotion:IntroCard",
                    "props": { "title": "MONEY DECODED", "subtitle": "...", "accent": "#38bdf8" } },
    "outro_clip": { "template": "remotion:OutroCTA", "props": { "headline": "SUBSCRIBE" } },
    "subscribe_cta": "If this helped, hit subscribe so you never miss the next one."

Each bumper is rendered once and cached at output/channel_assets/<id>/<kind>_<hash>.mp4.
The cache key includes the spec + voice chain + cta text, so editing any of them
re-renders; otherwise the exact same clip is reused (byte-for-byte consistency, ~0 cost).
The outro's subscribe line is spoken in the CHANNEL voice (same chain as the body).

Source per bumper: {"file": "path.mp4"} (use an existing clip) OR
{"template": "remotion:Comp", "props": {...}} (render via remotion_render.py).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ASSETS = ROOT / "output" / "channel_assets"
W, H, FPS = 1920, 1080, 30


def _run(cmd: list[str]) -> bool:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write((p.stderr or "")[-1200:])
        return False
    return True


def _probe_dur(mp4: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(mp4)],
            capture_output=True, text=True, timeout=60)
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _key(spec: dict, voice_chain, cta: str, kind: str) -> str:
    blob = json.dumps({"spec": spec, "v": voice_chain, "cta": cta, "k": kind,
                       "wh": [W, H, FPS]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _normalize(src: Path, dst: Path, audio: Path | None) -> bool:
    """Re-encode a clip to the canonical concat format (W×H, FPS, h264/yuv420p,
    aac 44.1k stereo). If `audio` given, use it; else attach a silent track so the
    concat downstream always has matching stream layout."""
    vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p"
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if audio is not None:
        cmd += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(dst)]
    return _run(cmd) and dst.exists() and dst.stat().st_size > 0


def _make_source(spec: dict, work: Path, dur_s: float) -> Path | None:
    """Produce the raw (silent) bumper video from a file or a remotion template."""
    if spec.get("file"):
        f = Path(spec["file"])
        if not f.is_absolute():
            f = ROOT / f
        return f if f.exists() else None
    tmpl = (spec.get("template") or "")
    if tmpl.startswith("remotion:"):
        try:
            import remotion_render
            if not remotion_render.available():
                return None
            comp = tmpl.split(":", 1)[1]
            out = work / f"_bumper_src_{comp}.mp4"
            if remotion_render.render_scene(comp, dict(spec.get("props") or {}), out, dur_s, W, H):
                return out
        except Exception as e:
            print(f"[bumper] [warn] remotion source failed: {e}")
    return None


def _build_one(channel_id: str, kind: str, spec: dict, voice_chain,
               cta: str = "", voice_rate: str = "+10%", voice_pitch: str = "+12Hz") -> Path | None:
    """Render+cache one bumper (intro or outro). Returns the cached clip path."""
    if not spec:
        return None
    cdir = ASSETS / channel_id
    cdir.mkdir(parents=True, exist_ok=True)
    out = cdir / f"{kind}_{_key(spec, voice_chain, cta, kind)}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out

    # Outro: synth the subscribe CTA in the channel voice first → drives duration.
    audio = None
    dur_s = float(spec.get("duration_s", 4.0))
    if kind == "outro" and cta:
        try:
            from render_real_video import render_voice
            audio = cdir / "_outro_cta.mp3"
            d = render_voice(cta, audio, voice_chain, rate=voice_rate, pitch=voice_pitch)
            if d and d > 0:
                dur_s = d + 0.6  # small tail so the CTA finishes before cut
            else:
                audio = None
        except Exception as e:
            print(f"[bumper] [warn] outro CTA voice failed: {e}")
            audio = None

    src = _make_source(spec, cdir, dur_s)
    if not src or not Path(src).exists():
        print(f"[bumper] [warn] no source for {channel_id}/{kind}")
        return None
    if not _normalize(Path(src), out, audio):
        print(f"[bumper] [warn] normalize failed {channel_id}/{kind}")
        return None
    print(f"[bumper] {channel_id}/{kind} ready ({_probe_dur(out):.1f}s) -> {out.name}")
    return out


def resolve_bumpers(channel_meta: dict, voice_chain=None,
                    voice_rate: str = "+10%", voice_pitch: str = "+12Hz") -> dict:
    """Return {'intro': Path|None, 'outro': Path|None} for a channel, building+caching
    on first use. No-op (None) when the channel declares no bumpers."""
    cid = channel_meta.get("channel_id") or channel_meta.get("id") or "default"
    vc = voice_chain or [f"edge:{channel_meta.get('voice', 'en-US-AriaNeural')}"]
    res = {"intro": None, "outro": None}
    intro_spec = channel_meta.get("intro_clip")
    outro_spec = channel_meta.get("outro_clip")
    cta = (channel_meta.get("subscribe_cta") or "").strip()
    if intro_spec:
        res["intro"] = _build_one(cid, "intro", intro_spec, vc,
                                  voice_rate=voice_rate, voice_pitch=voice_pitch)
    if outro_spec:
        res["outro"] = _build_one(cid, "outro", outro_spec, vc, cta=cta,
                                  voice_rate=voice_rate, voice_pitch=voice_pitch)
    return res


def concat_with_bumpers(body: Path, intro: Path | None, outro: Path | None,
                        work: Path) -> bool:
    """Prepend intro + append outro to `body` (in place). Body is assumed already in
    a standard format; bumpers were normalized to match. Uses the concat filter so
    minor param drift can't break it. No-op if no bumpers."""
    parts: list[Path] = []
    if intro and intro.exists():
        parts.append(intro)
    parts.append(body)
    if outro and outro.exists():
        parts.append(outro)
    if len(parts) == 1:
        return True  # nothing to add

    inputs: list[str] = []
    for p in parts:
        inputs += ["-i", str(p)]
    n = len(parts)
    # Filter-concat: each input is scaled/padded/fps-normalized inline, so minor
    # codec/param drift between bumpers and body can't break the join.
    tmp = work / "_with_bumpers.mp4"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex",
        "".join(
            f"[{i}:v:0]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p,setsar=1[v{i}];"
            for i in range(n)
        ) + "".join(f"[v{i}][{i}:a:0]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        str(tmp),
    ]
    if not _run(cmd) or not tmp.exists() or tmp.stat().st_size == 0:
        print("[bumper] [warn] concat failed; leaving body unchanged")
        return False
    import os as _os
    _os.replace(tmp, body)
    return True
