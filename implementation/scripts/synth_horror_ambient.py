# -*- coding: utf-8 -*-
"""Synthesize sparse Mr.Nightmare-style dread BEDS (long, evolving, no melody).

The existing horror tracks are melodic dark-ambient; Mr. Nightmare uses a nearly
subliminal deep drone — low sustained tone, slow detuned beating, distant sub
rumble, occasional swells, NO rhythm or tune. License-clean (generated). Output
→ assets/music/horror/*.mp3 so music_lib picks them like any other track.
"""
import numpy as np
import soundfile as sf
import subprocess
from pathlib import Path
from scipy.signal import butter, sosfilt

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "music" / "horror"
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(13)


def _lp(x, cut):
    sos = butter(2, min(max(cut, 20), SR/2-100)/(SR/2), btype="low", output="sos")
    return sosfilt(sos, x)


def _swell(n, period_s, depth=0.5, base=0.5):
    t = np.arange(n)/SR
    return base + depth*0.5*(1+np.sin(2*np.pi*t/period_s - np.pi/2))


def bed(name, dur_s, root_hz, detune, sub=True, shimmer_hz=None):
    n = int(dur_s*SR)
    t = np.arange(n)/SR
    # core drone: root + a few detuned partials → slow beating unease
    x = np.sin(2*np.pi*root_hz*t)
    x += 0.6*np.sin(2*np.pi*(root_hz+detune)*t)
    x += 0.4*np.sin(2*np.pi*(root_hz*2+detune*1.5)*t)
    x += 0.25*np.sin(2*np.pi*(root_hz*3)*t)
    x *= _swell(n, period_s=38, depth=0.5, base=0.5)   # very slow breathing
    # distant sub rumble (filtered brown noise, slow swells)
    if sub:
        w = rng.standard_normal(n); b = np.cumsum(w); b /= np.max(np.abs(b)) or 1
        rum = _lp(b, 80) * _swell(n, 55, 0.7, 0.3)
        x += 0.5*rum
    # sparse high dissonant shimmer fading in/out (dread, not melody)
    if shimmer_hz:
        sh = np.sin(2*np.pi*shimmer_hz*t) * (0.10*np.clip(np.sin(2*np.pi*t/70), 0, 1))
        x += sh
    x = _lp(x, 2200)                     # keep it dark, no highs
    x /= (np.max(np.abs(x)) or 1); x *= 0.82
    # long fades so it loops/enters unnoticed
    fi = int(4*SR); fo = int(6*SR)
    x[:fi] *= np.linspace(0,1,fi); x[-fo:] *= np.linspace(1,0,fo)
    stereo = np.stack([x, np.roll(x, 400)], axis=1)   # tiny width
    wav = OUT/f"{name}.wav"; mp3 = OUT/f"{name}.mp3"
    sf.write(str(wav), stereo.astype(np.float32), SR)
    subprocess.run(["ffmpeg","-y","-i",str(wav),"-c:a","libmp3lame","-b:a","160k",
                    str(mp3)], capture_output=True)
    wav.unlink(missing_ok=True)
    print(f"[ambient] {name}: {dur_s}s root={root_hz}Hz -> {mp3.name}")


# name, seconds, root freq, detune, sub, shimmer
bed("Dread Drone I",  270, 46.0, 0.6, True,  188.0)
bed("Dread Drone II", 300, 41.0, 0.9, True,  None)
bed("Hollow Air",     255, 55.0, 0.4, True,  233.0)
print("[ambient] done — 3 beds in assets/music/horror/")
