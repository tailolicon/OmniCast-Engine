# -*- coding: utf-8 -*-
"""Synthesize a license-clean horror SFX pack (procedural, no downloads).

Covers the atmospheric events that carry most horror moments and synthesize
convincingly: thunder, wind gust, heartbeat, low dread stinger, rain, radio
static, a cold sub-drone, and a best-effort tire screech. Output → assets/sfx/
horror/*.wav @ 48kHz mono. The event-SFX layer in render_real_video maps story
keywords to these files; drop higher-fidelity real foley in with the same name
to override any of them.
"""
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from pathlib import Path

SR = 48000
OUT = Path(__file__).resolve().parent.parent / "assets" / "sfx" / "horror"
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)


def _norm(x, peak=0.9):
    m = np.max(np.abs(x)) or 1.0
    return (x / m) * peak


def _fade(x, a=0.01, r=0.05):
    n = len(x)
    ai, ri = int(a * SR), int(r * SR)
    env = np.ones(n)
    if ai: env[:ai] = np.linspace(0, 1, ai)
    if ri: env[-ri:] = np.linspace(1, 0, ri)
    return x * env


def _lowpass(x, cut):
    # vectorized 2nd-order Butterworth lowpass (scipy, C-speed)
    cut = min(max(cut, 20.0), SR / 2 - 100)
    sos = butter(2, cut / (SR / 2), btype="low", output="sos")
    return sosfilt(sos, x)


def _brown(n):
    w = rng.standard_normal(n)
    b = np.cumsum(w)
    return b / (np.max(np.abs(b)) or 1.0)


def thunder(dur=4.0):
    n = int(dur * SR)
    b = _brown(n)
    low = _lowpass(b, 220)
    # sharp crack transient in the first 120ms
    crack = np.zeros(n)
    ci = int(0.12 * SR)
    crack[:ci] = rng.standard_normal(ci) * np.linspace(1, 0, ci) ** 2
    crack = _lowpass(crack, 900)
    env = np.exp(-np.linspace(0, 6, n))          # long decay rumble
    body = low * env
    # a second delayed rumble roll
    roll = np.zeros(n)
    d = int(0.5 * SR)
    roll[d:] = (low * np.exp(-np.linspace(0, 4, n)))[:n - d]
    x = _norm(body + 0.6 * roll + 0.8 * crack)
    return _fade(x, 0.001, 0.4)


def wind(dur=5.0):
    n = int(dur * SR)
    w = rng.standard_normal(n)
    band = _lowpass(w, 1200) - _lowpass(w, 300)   # bandpass-ish
    swell = (np.sin(np.linspace(0, np.pi, n)) ** 1.5)   # single gust swell
    gust = 0.6 + 0.4 * np.sin(np.linspace(0, 8, n))
    x = _norm(band * swell * gust)
    return _fade(x, 0.3, 0.6)


def heartbeat(dur=4.0, bpm=66):
    n = int(dur * SR)
    x = np.zeros(n)
    beat = int(SR * 60 / bpm)
    t = np.arange(beat) / SR
    for start in range(0, n - beat, beat):
        # lub-dub: two low thumps
        for off, amp, f in ((0.0, 1.0, 58), (0.16, 0.7, 52)):
            s = start + int(off * SR)
            if s + beat < n:
                thump = np.sin(2 * np.pi * f * t) * np.exp(-t * 22) * amp
                x[s:s + beat] += thump
    return _fade(_norm(x), 0.005, 0.1)


def stinger(dur=2.5):
    # cold dread hit: sub sine + detuned layer + noise swell up
    n = int(dur * SR)
    t = np.arange(n) / SR
    sub = np.sin(2 * np.pi * 46 * t) + 0.5 * np.sin(2 * np.pi * 47.5 * t)
    swell = np.linspace(0, 1, n) ** 2
    noise = _lowpass(rng.standard_normal(n), 600) * swell * 0.5
    x = _norm(sub * swell + noise)
    return _fade(x, 0.005, 0.4)


def drone(dur=6.0):
    # sustained unease bed, very low, slowly beating
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * 42 * t) + 0.6 * np.sin(2 * np.pi * 42.7 * t) \
        + 0.3 * np.sin(2 * np.pi * 84 * t)
    x *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * t)
    return _fade(_norm(x, 0.7), 0.5, 0.8)


def rain(dur=5.0):
    n = int(dur * SR)
    w = rng.standard_normal(n)
    hp = w - _lowpass(w, 2000)
    mod = 0.8 + 0.2 * rng.standard_normal(n)
    x = _norm(hp * mod * 0.6)
    return _fade(x, 0.3, 0.5)


def static(dur=3.0):
    n = int(dur * SR)
    w = rng.standard_normal(n)
    band = _lowpass(w, 3500) - _lowpass(w, 800)
    crackle = (rng.random(n) > 0.995).astype(float) * rng.standard_normal(n)
    x = _norm(band * 0.5 + crackle * 0.8)
    return _fade(x, 0.02, 0.1)


def screech(dur=1.4):
    # tire skid: bandpassed noise with a falling pitch resonance + harmonics
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = np.linspace(1400, 700, n)                 # falling squeal
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)
    noise = (_lowpass(rng.standard_normal(n), 2500) - _lowpass(rng.standard_normal(n), 900))
    env = np.concatenate([np.linspace(0, 1, int(0.05 * SR)),
                          np.ones(n - int(0.05 * SR))])[:n]
    env *= np.exp(-np.linspace(0, 2.5, n))
    x = _norm((tone * 0.6 + noise * 0.6) * env)
    return _fade(x, 0.005, 0.15)


def knock(dur=1.6, hits=(0.0, 0.28, 0.56)):
    # knuckles on a hollow door: three low thumps with woody resonance
    n = int(dur * SR)
    x = np.zeros(n)
    for h in hits:
        i0 = int(h * SR)
        hn = int(0.22 * SR)
        t = np.arange(hn) / SR
        body = np.sin(2 * np.pi * 95 * t) * np.exp(-t * 28)
        crack = _lowpass(rng.standard_normal(hn), 1800) * np.exp(-t * 60) * 0.5
        seg = body + crack
        x[i0:i0 + hn] += seg[:max(0, min(hn, n - i0))]
    return _fade(_norm(x), 0.003, 0.2)


def rattle(dur=1.8):
    # a metal door handle / crash bar shaken: bright metallic jitter bursts
    n = int(dur * SR)
    t = np.arange(n) / SR
    jitter = (rng.random(n) < 0.004).astype(float)   # sparse impulses
    ring = np.sin(2 * np.pi * 2600 * t) * 0.5 + np.sin(2 * np.pi * 3900 * t) * 0.3
    x = np.convolve(jitter, np.exp(-np.linspace(0, 10, int(0.05 * SR))), mode="same")
    x = x * ring + _lowpass(rng.standard_normal(n), 500) * 0.15 * x
    env = np.exp(-np.linspace(0, 1.6, n))
    return _fade(_norm(x * env), 0.005, 0.25)


PACK = {
    "thunder": thunder, "wind": wind, "heartbeat": heartbeat,
    "stinger": stinger, "drone": drone, "rain": rain,
    "static": static, "screech": screech,
    "knock": knock, "rattle": rattle,
}

for name, fn in PACK.items():
    x = fn().astype(np.float32)
    sf.write(str(OUT / f"{name}.wav"), x, SR)
    print(f"[sfx] {name:10s} {len(x)/SR:.1f}s -> {name}.wav")
print(f"[sfx] pack written to {OUT}")
