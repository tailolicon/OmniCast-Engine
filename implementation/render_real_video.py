"""
OmniCast Engine — Real Video Renderer (no-API-key, offline)
===========================================================
Renders a REAL, playable .mp4 from a generated script, using only local
tooling — no cloud API keys required:

    script .txt  ─┐
                  ├─► per-scene PNG card (Pillow)
                  ├─► per-scene voiceover .wav (pyttsx3 / Windows SAPI)
                  └─► ffmpeg subprocess  ─► scene_*.mp4  ─► concat ─► final.mp4

This exists because the in-package media stubs (TTS providers, Gemini image
provider, FFmpegModule._run_ffmpeg) either need an API key (GOOGLE_API_KEY,
empty here) or are placeholders that don't execute. This driver produces the
real artifact end-to-end with what's available on the box.

Usage:
    python -X utf8 render_real_video.py
    python -X utf8 render_real_video.py --script output/scripts/.../variant.txt
    python -X utf8 render_real_video.py --out output/real/final.mp4
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import html_overlay  # HTML/CSS Playwright overlay renderer (modern alt to Pillow)

ROOT = Path(__file__).parent

# STRICT quality mode (default ON): any step that would DEGRADE output quality
# (voice falling back to a flatter TTS, text cards instead of footage, missing
# BGM/SFX, junk thumbnail sources) FAILS the render loudly instead of shipping
# a worse video. Retries/JSON-repair are kept — they restore the intended
# content, they don't downgrade it. Set OMNICAST_STRICT=0 to allow degraded
# best-effort renders (debug only).
STRICT = os.environ.get("OMNICAST_STRICT", "1") != "0"
sys.path.insert(0, str(ROOT / "src"))


def _aiorun(coro):
    """Run a coroutine, even if a sync-Playwright event loop is already alive on
    this thread (html_overlay/web_shot/kinetic keep a persistent loop, which makes
    a plain _aiorun() raise 'cannot be called from a running event loop').
    Falls back to a dedicated worker thread+loop in that case."""
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # no running loop — normal path
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
        return _ex.submit(lambda: asyncio.run(coro)).result()
from omnicast.media.providers.web_assets import download_best_web_image
from omnicast.media.providers.stock_video import download_best_stock_video
from omnicast.media.providers.web_shot import capture_web_page
from omnicast.media.providers.kinetic_overlay import render_kinetic_stat

FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
FONT_REG = "C:/Windows/Fonts/arial.ttf"
W, H = 1920, 1080


# ─── Script parsing ───────────────────────────────────────────────────────────

@dataclass
class Scene:
    heading: str
    narration: str
    # Prosody from the script JSON (vfact pacing — docs/vfact_benchmark.json).
    # pace: "slow"|"normal"|"fast"|"" ("" = no script direction → heuristics apply)
    pace: str = ""
    pause_after_ms: int = 0      # deliberate silence AFTER this scene
    emphasis: tuple = ()          # words to stress (pitch lift on the scene)
    segment: str = ""             # story/segment title ("Level B2") — story cards


def find_best_script() -> Path | None:
    """Pick the highest-score script under output/scripts/**/variant_*scoreNN.txt."""
    candidates = glob.glob(str(ROOT / "output" / "scripts" / "**" / "*.txt"), recursive=True)
    best: tuple[int, Path] | None = None
    for c in candidates:
        m = re.search(r"score(\d+)", os.path.basename(c))
        score = int(m.group(1)) if m else 0
        if best is None or score > best[0]:
            best = (score, Path(c))
    return best[1] if best else None


def split_into_shots(scenes: list["Scene"], max_words: int) -> list["Scene"]:
    """Split each scene's narration into shorter 'shots' (~max_words each) so the
    illustration changes every few seconds and the on-screen caption matches the
    spoken line — tight script↔image sync. Each shot reuses its scene heading.
    """
    if max_words <= 0:
        return scenes
    # Two-speed editing: ENUMERATION lines (a comma series — "email, images, code,
    # video, homework…") get a faster cut rhythm (split on the commas into short
    # burst shots) so each listed item flashes its own image, like high-retention
    # montage moments. Normal explanation lines keep the calmer ~max_words chunking.
    _enum_re = re.compile(r"(\s*\w[^,]{0,40},){3,}")  # >=3 short comma items in a row
    shots: list[Scene] = []
    for sc in scenes:
        first_shot = len(shots)
        if _enum_re.search(sc.narration):
            items = [p.strip() for p in re.split(r",|\band\b", sc.narration) if p.strip()]
            # pair items up so shots aren't absurdly tiny (~2 items/shot)
            for k in range(0, len(items), 2):
                shots.append(Scene(heading=sc.heading,
                                   narration=", ".join(items[k:k + 2]),
                                   pace=sc.pace or "fast",  # enumeration = montage burst
                                   emphasis=sc.emphasis, segment=sc.segment))
        else:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", sc.narration) if s.strip()]
            chunk: list[str] = []
            count = 0
            for sent in sentences:
                w = len(sent.split())
                if chunk and count + w > max_words:
                    shots.append(Scene(heading=sc.heading, narration=" ".join(chunk),
                                       pace=sc.pace, emphasis=sc.emphasis, segment=sc.segment))
                    chunk, count = [], 0
                chunk.append(sent)
                count += w
            if chunk:
                shots.append(Scene(heading=sc.heading, narration=" ".join(chunk),
                                   pace=sc.pace, emphasis=sc.emphasis, segment=sc.segment))
        # the scene's dramatic pause lands AFTER its LAST shot only
        if len(shots) > first_shot and sc.pause_after_ms:
            shots[-1].pause_after_ms = sc.pause_after_ms
    return shots or scenes


def _split_blocks(text: str) -> list[str]:
    """Split script into scene blocks.

    Prefer explicit '---' separators. If absent, split on '[Heading]' marker
    lines (each heading starts a new scene; any text before the first heading
    is the hook block).
    """
    if "---" in text:
        return [b.strip() for b in text.split("---") if b.strip()]

    if re.search(r"^\s*\[.+?\]", text, re.MULTILINE):
        parts = re.split(r"(?m)^(?=\s*\[.+?\]\s*$)", text)
        return [p.strip() for p in parts if p.strip()]

    return [text.strip()] if text.strip() else []


def _parse_json_script(text: str) -> list[Scene]:
    """If the script is the LLM JSON storyboard (array of {vo, visual, sfx}),
    parse it into scenes. Returns [] when the text isn't that format."""
    import json as _json
    # The writer emits MULTIPLE JSON arrays (HOOK: [...], SEGMENT 1: [...], OUTRO:
    # [...]). Scan the whole text and decode EVERY array (raw_decode per '['), not
    # just the first — otherwise only the hook's few scenes survive.
    cleaned = re.sub(r"```(?:json)?", "", text)
    dec = _json.JSONDecoder()
    scenes: list[Scene] = []
    i = 0
    n = len(cleaned)
    while i < n:
        b = cleaned.find("[", i)
        if b == -1:
            break
        try:
            data, end = dec.raw_decode(cleaned[b:])
        except Exception:
            i = b + 1
            continue
        i = b + end
        if not isinstance(data, list):
            continue
        for obj in data:
            if not isinstance(obj, dict):
                continue
            vo = (obj.get("vo") or obj.get("narration") or obj.get("voiceover") or "").strip()
            if not vo:
                continue
            visual = (obj.get("visual") or obj.get("visual_prompt") or obj.get("image") or "").strip()
            heading = textwrap.shorten(visual or vo, width=48, placeholder="…")
            pace = str(obj.get("pace") or "").strip().lower()
            if pace not in ("slow", "normal", "fast"):
                pace = ""
            try:
                pause_ms = max(0, min(int(obj.get("pause_after_ms") or 0), 2000))
            except (TypeError, ValueError):
                pause_ms = 0
            emph_raw = obj.get("emphasis") or []
            if isinstance(emph_raw, str):
                emph_raw = [emph_raw]
            emph = tuple(str(e).strip() for e in emph_raw if str(e).strip()) \
                if isinstance(emph_raw, list) else ()
            seg = str(obj.get("segment") or "").strip()
            scenes.append(Scene(heading=heading, narration=vo, pace=pace,
                                pause_after_ms=pause_ms, emphasis=emph,
                                segment=seg))
    return scenes


def parse_script(text: str) -> list[Scene]:
    """Split a script into scenes by '---' or '[Heading]' boundaries.

    First block (no [heading]) = hook. Blocks with '[Heading]' use it as title.
    Final block = outro.

    Also accepts the LLM JSON storyboard format (a ```json fenced array of
    {"vo","visual","sfx"} objects) — phase-2 sometimes saves the raw JSON. In
    that case narration = vo, heading = a short label from visual.
    """
    js = _parse_json_script(text)
    if js:
        return js

    blocks = _split_blocks(text)
    scenes: list[Scene] = []
    for i, block in enumerate(blocks):
        hm = re.match(r"\[(.+?)\]\s*(.*)", block, re.DOTALL)
        if hm:
            heading = hm.group(1).strip()
            narration = hm.group(2).strip()
        elif i == 0:
            # Hook: derive a short title from the first sentence.
            first = re.split(r"(?<=[.!?])\s+", block.strip())[0]
            heading = textwrap.shorten(first, width=48, placeholder="…")
            narration = block
        else:
            heading = "Your Action Step"
            narration = block
        scenes.append(Scene(heading=heading, narration=narration))
    return scenes


# ─── Visual: PIL text card per scene ───────────────────────────────────────────

def render_card(
    scene: Scene, idx: int, total: int, out_png: Path, bg_image: Path | None = None
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    if bg_image and bg_image.exists():
        # Use a generated illustration as the background, cover-fit to frame,
        # then darken left side for legible text (presenter-slide look).
        base = Image.open(bg_image).convert("RGB")
        scale = max(W / base.width, H / base.height)
        base = base.resize((int(base.width * scale), int(base.height * scale)))
        left = (base.width - W) // 2
        top = (base.height - H) // 2
        img = base.crop((left, top, left + W, top + H))
        draw = ImageDraw.Draw(img)
        # left-to-right dark scrim so the title/caption column stays readable
        scrim = Image.new("L", (W, H), 0)
        sdraw = ImageDraw.Draw(scrim)
        for x in range(W):
            sdraw.line([(x, 0), (x, H)], fill=max(0, int(200 - (x / W) * 230)))
        black = Image.new("RGB", (W, H), (6, 8, 12))
        img = Image.composite(black, img, scrim)
        draw = ImageDraw.Draw(img)
    else:
        img = Image.new("RGB", (W, H), (12, 15, 22))
        draw = ImageDraw.Draw(img)
        # subtle vertical gradient band
        for y in range(H):
            shade = int(12 + (y / H) * 18)
            draw.line([(0, y), (W, y)], fill=(shade, shade + 3, shade + 8))

    # accent bar
    draw.rectangle([120, 300, 132, 820], fill=(70, 160, 255))

    f_kicker = ImageFont.truetype(FONT_REG, 34)
    f_title = ImageFont.truetype(FONT_BOLD, 88)
    f_body = ImageFont.truetype(FONT_REG, 44)

    draw.text((170, 250), f"SCENE {idx + 1} / {total}", font=f_kicker, fill=(120, 170, 240))

    # wrapped heading
    title_lines = textwrap.wrap(scene.heading, width=26)
    y = 320
    for line in title_lines[:3]:
        draw.text((170, y), line, font=f_title, fill=(245, 247, 252))
        y += 100

    # first ~2 sentences as on-screen caption
    sentences = re.split(r"(?<=[.!?])\s+", scene.narration)
    caption = " ".join(sentences[:2])[:280]
    y = max(y + 40, 700)
    for line in textwrap.wrap(caption, width=64)[:5]:
        draw.text((170, y), line, font=f_body, fill=(180, 190, 205))
        y += 60

    img.save(out_png)


def render_subtitle_overlay(scene: Scene, idx: int, total: int, out_png: Path) -> None:
    """Transparent RGBA layer with a centered bottom subtitle (the spoken line).

    Clean caption style for narration-only (history/storybook) videos — no big
    title or presenter, just synced subtitles over the moving illustration.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    f_sub = ImageFont.truetype(FONT_BOLD, 52)

    text = re.sub(r"\s+", " ", scene.narration).strip()
    # Caption hygiene: short lines (~38 CPL), max 2 lines. Long narration is the
    # word-synced (whisper/ASS) path's job; this static fallback stays terse.
    lines = textwrap.wrap(text, width=38)[:2]
    line_h = 66
    block_h = line_h * len(lines)
    y0 = H - 90 - block_h

    # Text only — NO background band. Heavy black outline + soft shadow keep it
    # legible over any moving illustration.
    y = y0
    for line in lines:
        w = draw.textlength(line, font=f_sub)
        x = (W - w) // 2
        # thick outline (3px ring) for contrast without a band
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx * dx + dy * dy >= 4:
                    draw.text((x + dx, y + dy), line, font=f_sub, fill=(0, 0, 0, 235))
        draw.text((x, y), line, font=f_sub, fill=(255, 255, 255, 255))
        y += line_h
    img.save(out_png)


def render_blank_overlay(scene: Scene, idx: int, total: int, out_png: Path) -> None:
    """Fully transparent overlay — used when word-synced captions are burned on
    the final video, so per-shot clips carry no static text."""
    from PIL import Image
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(out_png)


def render_text_overlay(scene: Scene, idx: int, total: int, out_png: Path) -> None:
    """Transparent RGBA text layer (scrim + kicker + title + caption).

    Rendered separately from the illustration so the text stays still while the
    background image gets Ken Burns motion behind it.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Left-to-right dark scrim (alpha fades out) for legible text column.
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(scrim)
    for x in range(W):
        a = max(0, int(210 - (x / W) * 250))
        sdraw.line([(x, 0), (x, H)], fill=(6, 8, 12, a))
    img = Image.alpha_composite(img, scrim)
    draw = ImageDraw.Draw(img)

    draw.rectangle([120, 300, 132, 820], fill=(70, 160, 255, 255))

    f_kicker = ImageFont.truetype(FONT_REG, 34)
    f_title = ImageFont.truetype(FONT_BOLD, 88)
    f_body = ImageFont.truetype(FONT_REG, 44)

    draw.text((170, 250), f"SCENE {idx + 1} / {total}", font=f_kicker, fill=(120, 170, 240, 255))
    y = 320
    for line in textwrap.wrap(scene.heading, width=26)[:3]:
        draw.text((170, y), line, font=f_title, fill=(245, 247, 252, 255))
        y += 100
    sentences = re.split(r"(?<=[.!?])\s+", scene.narration)
    caption = " ".join(sentences[:2])[:280]
    y = max(y + 40, 700)
    for line in textwrap.wrap(caption, width=64)[:5]:
        draw.text((170, y), line, font=f_body, fill=(180, 190, 205, 255))
        y += 60

    img.save(out_png)


def _apply_kinetic_stat(stat_png: Path | None, overlay_png: Path) -> None:
    """Alpha-composite a PRE-RENDERED kinetic stat PNG onto the transparent text
    overlay, in place. The stat PNG must be rendered earlier on the main thread —
    Playwright (sync) is thread-affine and cannot run inside the parallel compose
    workers ("Cannot switch to a different thread"). No-op / never raises."""
    try:
        if not stat_png or not stat_png.exists():
            return
        from PIL import Image
        base = Image.open(overlay_png).convert("RGBA")
        top = Image.open(stat_png).convert("RGBA")
        if top.size != base.size:
            top = top.resize(base.size)
        Image.alpha_composite(base, top).save(overlay_png)
    except Exception as e:
        print(f"[kinetic] [warn] {e}")


# Spelled-out forms of common stat numbers — TTS says "fifty percent", not "50%",
# so the digit string never matches the transcript. Map the digits we care about.
_NUM_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
    "20": "twenty", "30": "thirty", "40": "forty", "44": "forty", "50": "fifty",
    "60": "sixty", "63": "sixty", "70": "seventy", "80": "eighty", "90": "ninety",
    "100": "hundred", "300": "hundred", "1000": "thousand",
}
_STAT_STOP = {"of", "the", "a", "an", "in", "to", "and", "per", "with", "your", "you"}


def _stat_trigger_local(words_json: Path, number: str, label: str, clip_dur: float) -> float:
    """When (seconds into the scene) the stat is actually SPOKEN — so the kinetic
    callout can pop on that word (Vfacts style) instead of for the whole scene.
    Matches the transcript against tokens from stat_number + stat_label (the LABEL
    words are spoken verbatim, so they anchor reliably). Falls back to ~35% in."""
    import re as _re
    toks: set[str] = set()
    for src in (number or "", label or ""):
        for w in _re.findall(r"[a-z]+|\d+", src.lower()):
            if w in _STAT_STOP:
                continue
            if w.isdigit():
                toks.add(w)
                if w in _NUM_WORDS:
                    toks.add(_NUM_WORDS[w])
            elif len(w) >= 3:
                toks.add(w)
    try:
        words = json.loads(words_json.read_text(encoding="utf-8")) if words_json.exists() else []
    except Exception:
        words = []
    for wd in words:
        wt = _re.sub(r"[^a-z0-9]", "", str(wd.get("text", "")).lower())
        if not wt:
            continue
        for tk in toks:
            if tk == wt or (tk.isalpha() and len(tk) >= 4 and tk in wt):
                return max(0.0, float(wd.get("start", 0.0)) - 0.15)
    return max(0.0, clip_dur * 0.35)


FONT_HORROR = "C:/Windows/Fonts/CHILLER.TTF"


def _detect_story_segments(clips: list, scenes) -> list[tuple[float, str, int]]:
    """Return [(start_time, title, ordinal), …] for each story segment boundary.
    Shared by the overlay and the beat-insertion card renderers."""
    def _is_title(h: str) -> bool:
        h = (h or "").strip()
        return bool(h) and len(h.split()) <= 6 and h.upper() not in ("HOOK", "OUTRO")

    _MIN_GAP_S = 60.0
    starts: list[tuple[float, str, int]] = []
    t_acc, prev, ordn, last_card_t = 0.0, None, 0, -1e9
    for i, c in enumerate(clips):
        cd = probe_duration(c) if c and Path(c).exists() else 0.0
        sc = scenes[i] if i < len(scenes) else None
        h = ((getattr(sc, "segment", "") or "").strip()) if sc else ""
        if not h:
            prev = None; t_acc += cd; continue
        if (_is_title(h) and h != prev and (t_acc - last_card_t) >= _MIN_GAP_S):
            ordn += 1
            starts.append((t_acc, h, ordn))
            last_card_t = t_acc
        prev = h
        t_acc += cd
    return starts


_ORD_WORDS = {1: "STORY ONE", 2: "STORY TWO", 3: "STORY THREE",
              4: "STORY FOUR", 5: "STORY FIVE"}


def _render_card_png(path: Path, kicker: str, title: str, subtitle: str = "") -> None:
    """Near-black full-frame title card: red letterspaced kicker, bone-white
    horror-font title, optional subtitle. Used for intro + story beat cards."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (W, H), (2, 2, 4))
    d = ImageDraw.Draw(img)
    try:
        f_kick = ImageFont.truetype(FONT_REG, 40)
        f_title = ImageFont.truetype(FONT_HORROR, 172)
        f_sub = ImageFont.truetype(FONT_REG, 44)
    except Exception:
        f_kick = f_sub = ImageFont.truetype(FONT_REG, 40)
        f_title = ImageFont.truetype(FONT_BOLD, 120)
    if kicker:
        k = " ".join(kicker)  # letterspaced
        wk = d.textlength(k, font=f_kick)
        d.text(((W - wk) / 2, H / 2 - 165), k, font=f_kick, fill=(122, 12, 12))
    wt = d.textlength(title, font=f_title)
    d.text(((W - wt) / 2, H / 2 - 110), title, font=f_title, fill=(226, 222, 210))
    if subtitle:
        ws = d.textlength(subtitle, font=f_sub)
        d.text(((W - ws) / 2, H / 2 + 90), subtitle, font=f_sub, fill=(150, 40, 40))
    img.save(path)


def _make_card_clip(png: Path, out_clip: Path, dur: float, fps: float,
                    drone: Path | None) -> bool:
    """Build a card CLIP: the still card for `dur`s with a low drone that fades to
    SILENCE — the deliberate beat that lets the card land before narration resumes."""
    if drone and drone.exists():
        aud_in = ["-i", str(drone)]
        afilter = (f"[1:a]atrim=0:{dur},volume=0.30,afade=t=in:st=0:d=0.4,"
                   f"afade=t=out:st={max(0.0,dur-1.0):.2f}:d=1.0,"
                   f"aresample=48000,aformat=channel_layouts=stereo[a]")
    else:
        aud_in = ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo"]
        afilter = "[1:a]aformat=channel_layouts=stereo[a]"
    fc = (f"[0:v]scale={W}:{H},fps={fps},format=yuv420p,setsar=1[v];" + afilter)
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur}", "-i", str(png), *aud_in,
         "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-shortest",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out_clip)])
    return out_clip.exists() and out_clip.stat().st_size > 0


def _insert_story_beats(out_mp4: Path, work: Path, clips: list, scenes,
                        channel_meta: dict) -> None:
    """Splice a real BEAT at each story boundary: a channel INTRO card at 0:00 and
    a STORY title card before each account, each held ~2.8s over a low drone that
    fades to silence — so the card lands in a pause, THEN narration resumes. This
    replaces the old pure-visual overlay (which ran the voice straight through the
    card with no breath — operator: 'không dừng 1 nhịp sau khi ảnh đó xuất hiện')."""
    segs = _detect_story_segments(clips, scenes)
    if len(segs) > 6:
        print(f"[3s/5] Story beats skipped (segment signal noisy: {len(segs)})")
        return

    D = 2.8
    fps = _probe_fps(out_mp4) or 30.0
    drone = ROOT / "assets" / "sfx" / "horror" / "drone.wav"

    # 1) build card clips: intro (t=0) + one per story segment
    clip_specs: list[tuple[float, Path]] = []  # (insert_at_time, clip_path)
    intro_png = work / "card_intro.png"
    intro_title = str(channel_meta.get("card_intro_title")
                      or channel_meta.get("brand_name") or "TRUE DREAD FILES").upper()
    intro_sub = str(channel_meta.get("card_intro_subtitle") or "REAL ACCOUNTS · NOTHING EXPLAINED")
    _render_card_png(intro_png, "", intro_title, intro_sub)
    intro_clip = work / "cardclip_intro.mp4"
    if _make_card_clip(intro_png, intro_clip, D, fps, drone):
        clip_specs.append((0.0, intro_clip))

    for t0, title, o in segs:
        png = work / f"card_story_{o}.png"
        _render_card_png(png, _ORD_WORDS.get(o, f"STORY {o}"), title.upper())
        cc = work / f"cardclip_{o}.mp4"
        if _make_card_clip(png, cc, D, fps, drone):
            clip_specs.append((t0, cc))

    if not clip_specs:
        return

    # 2) splice: cut the main video at each story time, interleave the cards.
    # sequence = intro, part[0:t1], card1, part[t1:t2], card2, …
    cut_times = sorted({t for t, _ in clip_specs if t > 0.5})
    total = probe_duration(out_mp4)
    bounds = [0.0] + cut_times + [total]
    inputs = ["-i", str(out_mp4)]
    card_by_time = {t: c for t, c in clip_specs}
    intro = card_by_time.get(0.0)
    # map card input indices
    card_inputs: dict[float, int] = {}
    idx = 1
    if intro:
        inputs += ["-i", str(intro)]; intro_idx = idx; idx += 1
    else:
        intro_idx = None
    for t in cut_times:
        inputs += ["-i", str(card_by_time[t])]; card_inputs[t] = idx; idx += 1

    fc_parts: list[str] = []
    seq: list[str] = []
    # normalize each input to a common spec so concat accepts them
    def _norm_card(i: int, tag: str):
        fc_parts.append(f"[{i}:v]scale={W}:{H},fps={fps},format=yuv420p,setsar=1[{tag}v]")
        fc_parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[{tag}a]")
        seq.extend([f"[{tag}v]", f"[{tag}a]"])

    if intro_idx is not None:
        _norm_card(intro_idx, "ci")
    for p in range(len(bounds) - 1):
        s, e = bounds[p], bounds[p + 1]
        if e - s < 0.2:  # skip empty part (e.g. story 1 at t=0)
            continue
        fc_parts.append(f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS,"
                        f"scale={W}:{H},fps={fps},format=yuv420p,setsar=1[v{p}]")
        fc_parts.append(f"[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,"
                        f"aresample=48000,aformat=channel_layouts=stereo[a{p}]")
        seq.extend([f"[v{p}]", f"[a{p}]"])
        # after this part ends at boundary e, insert the card whose time == e
        if e in card_inputs:
            _norm_card(card_inputs[e], f"cs{p}")

    n_seg = len(seq) // 2
    if n_seg < 2:
        return
    fc = ";".join(fc_parts) + ";" + "".join(seq) + \
        f"concat=n={n_seg}:v=1:a=1[v][a]"
    tmp = out_mp4.with_name(out_mp4.stem + "_beats.mp4")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(tmp)])
    if tmp.exists() and tmp.stat().st_size > 0:
        _replace_retry(tmp, out_mp4, label="storybeats")
        print(f"[3s/5] Story beats spliced: intro + {len(segs)} cards (with pause)")


def _overlay_story_cards(out_mp4: Path, work: Path, clips: list, scenes) -> None:
    """Mr. Nightmare-style STORY TITLE CARDS: a near-black full-frame card for
    ~2.8s at the start of each story segment. Fixes multi-story comprehension —
    without them viewers can't tell where one account ends and the next begins,
    and the dread never lands (operator feedback 2026-07-11)."""
    from PIL import Image, ImageDraw, ImageFont

    # A story-segment heading is a SHORT title ("Level B2", "The Silver Sedan"),
    # never a full narration sentence. Depending on the parse path, scene.heading
    # can be the segment title (good) OR the first narration sentence (bad — then
    # it changes almost every shot). Only accept SHORT headings as boundaries, and
    # require a real gap between cards, so a broken heading signal can't spew 100+
    # black cards. If the count still looks wrong (>6), skip entirely (fail-safe).
    def _is_title(h: str) -> bool:
        h = (h or "").strip()
        return bool(h) and len(h.split()) <= 6 and h.upper() not in ("HOOK", "OUTRO")

    _MIN_GAP_S = 60.0  # stories are minutes apart; two cards <60s apart = noise
    starts: list[tuple[float, str, int]] = []
    t_acc, prev, ordn, last_card_t = 0.0, None, 0, -1e9
    for i, c in enumerate(clips):
        cd = probe_duration(c) if c and Path(c).exists() else 0.0
        # Use the SEGMENT title ("Level B2"), NOT heading (= visual query, 100+
        # unique values → 100+ cards). Fall back to heading only if segment empty.
        sc = scenes[i] if i < len(scenes) else None
        h = ((getattr(sc, "segment", "") or "").strip()) if sc else ""
        if not h:  # no segment field (legacy/prose parse) → skip, don't guess
            prev = None; t_acc += cd; continue
        if (_is_title(h) and h != prev and (t_acc - last_card_t) >= _MIN_GAP_S):
            ordn += 1
            starts.append((t_acc, h, ordn))
            last_card_t = t_acc
        prev = h
        t_acc += cd
    if not starts or len(starts) > 6:
        if len(starts) > 6:
            print(f"[3s/5] Story cards skipped (segment signal noisy: {len(starts)})")
        return

    ORD = {1: "STORY ONE", 2: "STORY TWO", 3: "STORY THREE",
           4: "STORY FOUR", 5: "STORY FIVE"}
    events: list[tuple[Path, float, float]] = []
    try:
        f_kick = ImageFont.truetype(FONT_REG, 38)
        f_title = ImageFont.truetype(FONT_HORROR, 190)
    except Exception:
        f_kick = ImageFont.truetype(FONT_REG, 38)
        f_title = ImageFont.truetype(FONT_BOLD, 130)
    for t0, h, o in starts:
        img = Image.new("RGBA", (W, H), (2, 2, 4, 242))
        d = ImageDraw.Draw(img)
        kick = " ".join(ORD.get(o, f"STORY {o}"))  # letterspaced
        w1 = d.textlength(kick, font=f_kick)
        d.text(((W - w1) / 2, H / 2 - 175), kick, font=f_kick,
               fill=(122, 12, 12, 255))
        title = h.upper()
        w2 = d.textlength(title, font=f_title)
        d.text(((W - w2) / 2, H / 2 - 120), title, font=f_title,
               fill=(226, 222, 210, 255))
        png = work / f"storycard_{o}.png"
        img.save(png)
        events.append((png, max(0.0, t0), t0 + 2.8))

    tmp = out_mp4.with_name(out_mp4.stem + "_cards.mp4")
    cmd = ["ffmpeg", "-y", "-i", str(out_mp4)]
    for png, _, _ in events:
        cmd += ["-i", str(png)]  # single-frame input (no -loop — overlay holds it;
        #                          -loop 1 makes an infinite input that breaks the graph)
    fc, last = [], "[0:v]"
    for idx, (png, t0, t1) in enumerate(events, start=1):
        fc.append(f"{last}[{idx}:v]overlay=0:0:enable=between(t\\,{t0:.2f}\\,{t1:.2f})[v{idx}]")
        last = f"[v{idx}]"
    cmd += ["-filter_complex", ";".join(fc), "-map", last, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", str(tmp)]
    run(cmd)
    if tmp.exists() and tmp.stat().st_size > 0:
        _replace_retry(tmp, out_mp4, label="storycards")
        print(f"[3s/5] Story title cards: {len(events)}")


def _overlay_timed_kinetics(out_mp4: Path, work: Path, kinetic_paths: dict,
                            clips: list, board: list) -> None:
    """Composite each pre-rendered kinetic stat PNG onto the FINAL video as a
    TIMED overlay — visible only ~1.8s starting when its number is spoken, not for
    the whole scene. One ffmpeg pass; no-op when there are no stats."""
    if not kinetic_paths:
        return
    events: list[tuple[Path, float, float]] = []
    t_acc = 0.0
    for i in range(len(clips)):
        ci = clips[i] if i < len(clips) else None
        cd = probe_duration(ci) if ci and Path(ci).exists() else 0.0
        png = kinetic_paths.get(i)
        if png and Path(png).exists() and cd > 0:
            cell = board[i] if (board and i < len(board)) else {}
            local = _stat_trigger_local(work / f"scene_{i:02d}.words.json",
                                        cell.get("stat_number", ""),
                                        cell.get("stat_label", ""), cd)
            t0 = t_acc + local
            t1 = min(t_acc + cd - 0.05, t0 + 1.8)
            if t1 > t0:
                events.append((Path(png), t0, t1))
        t_acc += cd
    if not events:
        return
    # Safety cap: emphasis is a rare accent (Vfacts leaves most of the film clean).
    # If the storyboard over-flagged stats, keep only the first few, evenly biased.
    _MAX_KINETICS = 4
    if len(events) > _MAX_KINETICS:
        step = len(events) / _MAX_KINETICS
        events = [events[int(k * step)] for k in range(_MAX_KINETICS)]
        print(f"[3+/5] Capped kinetic callouts to {_MAX_KINETICS} (Vfacts-style sparsity)")
    tmp = out_mp4.with_name(out_mp4.stem + "_kin.mp4")
    cmd = ["ffmpeg", "-y", "-i", str(out_mp4)]
    for png, _, _ in events:
        cmd += ["-i", str(png)]
    fc: list[str] = []
    last = "[0:v]"
    for idx, (png, t0, t1) in enumerate(events, start=1):
        lbl = f"[v{idx}]"
        fc.append(f"{last}[{idx}:v]overlay=0:0:enable=between(t\\,{t0:.2f}\\,{t1:.2f}){lbl}")
        last = lbl
    cmd += ["-filter_complex", ";".join(fc), "-map", last, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", str(tmp)]
    try:
        run(cmd)
        if tmp.exists() and tmp.stat().st_size > 0:
            _replace_retry(tmp, out_mp4, label="kinetic")
            print(f"[3+/5] Kinetic stats word-synced ({len(events)} timed callouts)")
    except Exception as e:
        if STRICT:
            raise RuntimeError(f"Kinetic overlay failed ({e}) — STRICT mode "
                               "refuses to ship without the stat callouts") from e
        print(f"[kinetic] [warn] timed overlay failed ({e}); leaving video as-is")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _mix_sfx(out_mp4: Path, work: Path, clips: list, board, scenes,
             sfx_style: str = "full") -> None:
    """Mix subtle SFX into the finished video: a soft whoosh at each section change
    (scene heading flips) and a ting when a hero/shock number reveals. No-op + safe
    if assets or ffmpeg fail — purely additive polish, never breaks the render.

    sfx_style (channels/<id>.json "sfx_style"): "full" (default explainer polish),
    "off" — no cue track at all. Horror/story channels use "off": a whoosh at
    every transition reads as EDITING, breaks dread; silence + room tone scare
    more (Mr. Nightmare-style minimal editing).
    """
    # "diegetic" = horror event-SFX only (handled by _mix_diegetic_sfx); the
    # whoosh/ting transition cues here read as EDITING and break dread, so skip.
    if (sfx_style or "full").lower().strip() in ("off", "none", "diegetic"):
        print("[3++/5] SFX: transition cues off (channel sfx_style)")
        return
    whoosh = ROOT / "assets" / "sfx" / "whoosh.wav"
    ting = ROOT / "assets" / "sfx" / "ting.wav"
    if not whoosh.exists() and not ting.exists():
        return
    import re as _re
    _hero_re = _re.compile(r"\b(million|billion|trillion)\b|\d[\d.,]{6,}|\d+\s?%", _re.I)
    # cumulative start time of each scene from real clip durations
    starts, t = [], 0.0
    for i in range(len(clips)):
        starts.append(t)
        cd = probe_duration(clips[i]) if (clips[i] and clips[i].exists()) else 0.0
        t += cd
    events: list[tuple[float, Path]] = []  # (time, sfx)
    prev_head = None
    for i in range(len(starts)):
        cell = board[i] if (board and i < len(board)) else {}
        sc = scenes[i] if i < len(scenes) else None
        head = (sc.heading if sc else "") or ""
        added_whoosh = False
        if whoosh.exists() and head and head != prev_head and i > 0:
            events.append((max(0.0, starts[i] - 0.08), whoosh))  # lead the cut slightly
            added_whoosh = True
        prev_head = head
        # Twist beat: the Writer marks a deliberate pause after this scene → whoosh
        # into the twist even without a section change (skip if a heading whoosh
        # already fired here so we don't double it).
        if (whoosh.exists() and not added_whoosh and i > 0 and sc is not None
                and (getattr(sc, "pause_after_ms", 0) or 0) >= 400):
            events.append((max(0.0, starts[i] - 0.08), whoosh))
        num = (cell.get("stat_number") or "") + " " + (cell.get("stat_label") or "")
        if ting.exists() and (cell.get("stat_number") or "").strip() and _hero_re.search(num):
            events.append((starts[i] + 0.15, ting))
        # Emphasized number/key word → ting even when the storyboard left
        # stat_number empty (the Writer's emphasis carries the reveal).
        elif (ting.exists() and sc is not None and getattr(sc, "emphasis", ())
                and _hero_re.search(" ".join(sc.emphasis))):
            events.append((starts[i] + 0.15, ting))
    if not events:
        return
    events = events[:24]  # safety cap
    tmp = out_mp4.with_name(out_mp4.stem + "_sfx.mp4")
    try:
        inputs = ["-i", str(out_mp4)]
        for _, sfx in events:
            inputs += ["-i", str(sfx)]
        parts, mixn = [], ["[0:a]"]
        for idx, (tm, _sfx) in enumerate(events, start=1):
            parts.append(f"[{idx}:a]adelay={int(tm*1000)}:all=1[s{idx}]")
            mixn.append(f"[s{idx}]")
        fc = ";".join(parts) + ";" + "".join(mixn) + \
            f"amix=inputs={len(events)+1}:duration=first:dropout_transition=0:normalize=0[a]"
        run(["ffmpeg", "-y", *inputs, "-filter_complex", fc,
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             str(tmp)])
        if tmp.exists() and tmp.stat().st_size > 0:
            _replace_retry(tmp, out_mp4, label="sfx")
            print(f"[3++/5] SFX mixed ({len(events)} cues: whoosh/ting)")
    except Exception as e:
        if STRICT:
            raise RuntimeError(f"SFX mix failed ({e}) — STRICT mode refuses "
                               "to ship without the cue track") from e
        print(f"[sfx] [warn] mix skipped ({e})")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


# Event → SFX for horror narration. (sfx_name, gain, keyword regex). Deliberately
# sparse and conservative: a well-placed sound lands; a wall of them reads cheap.
# Patterns require the EVENT context (e.g. "heart pounding", not bare "heart") so
# "my heart sank" or "no cell signal" never trigger a cue.
_DIEGETIC_SFX = [
    ("screech", 0.55, r"\b(?:slammed?|hit|stomp\w*)\s+(?:on\s+)?(?:the\s+)?brakes?\b"
                      r"|\bbrakes?\s+(?:screech|squeal|lock)\w*|\bskidd?\w*"
                      r"|\btires?\s+(?:screech|squeal|scream)\w*|\bscreech\w*\s+to\s+a\b"),
    ("thunder",  0.6,  r"\bthunder\w*|\blightning\b|\bthunderclap\b"),
    ("wind",     0.3,  r"\bwind\s+(?:pick\w*|howl\w*|gust\w*|whipp\w*)|\bgust\s+of\s+wind\b"
                      r"|\bhowling\s+wind\b|\bwind\s+rose\b"),
    ("rain",     0.32, r"\bdownpour\b|\bpouring\s+rain\b|\brain\s+(?:start\w*|came|hammer\w*)"
                      r"|\bdrizzl\w*"),
    ("heartbeat",0.4,  r"\bheart\s+(?:pound\w*|hammer\w*|rac\w*|thud\w*|slamm\w*)"
                      r"|\bheartbeat\b|\bpulse\s+(?:pound\w*|hammer\w*)"),
    ("static",   0.4,  r"\bradio\s+(?:static|crackl\w*|hiss\w*)|\bstatic\s+crackl\w*"
                      r"|\bsignal\s+(?:cut|died|dropped)\b"),
    ("stinger",  0.55, r"\bstanding\s+(?:at\s+my|there|exactly|right\s+(?:at|behind|beside))\b"
                      r"|\bfilled\s+the\s+\w*\s*window\b|\bright\s+(?:behind|beside|next\s+to)\s+me\b"
                      r"|\bhis\s+face\s+(?:filled|was\s+at)\b|\bwas\s+standing\s+at\s+my\b"),
]


def _mix_diegetic_sfx(out_mp4: Path, work: Path, clips: list, scenes,
                      sfx_style: str = "diegetic", cap: int = 8,
                      min_gap_s: float = 6.0) -> None:
    """Event-matched horror SFX: when the narration says something HAPPENS (hard
    braking, thunder, a heart pounding, the figure appearing), drop the matching
    sound at the exact word — using the scene's word timings — ducked under the
    voice. Sparse by design (operator: 'có SFX nhưng không lạm dụng'): one cue per
    category per scene, a minimum gap between cues, and a hard total cap.

    Files live in assets/sfx/horror/<name>.wav; drop real foley in with the same
    name to override the synthesized defaults."""
    if (sfx_style or "").lower().strip() != "diegetic":
        return
    sfx_dir = ROOT / "assets" / "sfx" / "horror"
    if not sfx_dir.is_dir():
        print("[sfx-ev] no horror sfx pack — skipped")
        return
    import re as _re
    compiled = [(name, gain, _re.compile(pat, _re.I)) for name, gain, pat in _DIEGETIC_SFX
                if (sfx_dir / f"{name}.wav").exists()]

    # cumulative scene start offsets from real clip durations
    starts, t = [], 0.0
    for i in range(len(clips)):
        starts.append(t)
        cd = probe_duration(clips[i]) if (clips[i] and clips[i].exists()) else 0.0
        t += cd

    def _time_at_char(narr: str, wjson: list, ch_idx: int) -> float | None:
        wcount = len(narr[:ch_idx].split())
        if 0 <= wcount < len(wjson):
            return float(wjson[wcount].get("start", 0.0) or 0.0)
        return None

    events: list[tuple[float, Path, float]] = []  # (abs_time, sfx_path, gain)
    for i, sc in enumerate(scenes):
        narr = (getattr(sc, "narration", "") or "")
        if not narr:
            continue
        wpath = work / f"scene_{i:02d}.words.json"
        wjson = []
        if wpath.exists():
            try:
                wjson = json.loads(wpath.read_text(encoding="utf-8"))
            except Exception:
                wjson = []
        fired = set()  # one cue per category per scene
        for name, gain, rx in compiled:
            if name in fired:
                continue
            m = rx.search(narr)
            if not m:
                continue
            local = _time_at_char(narr, wjson, m.start()) if wjson else 0.0
            if local is None:
                local = 0.0
            events.append((starts[i] + local, sfx_dir / f"{name}.wav", gain))
            fired.add(name)

    if not events:
        print("[sfx-ev] no story events matched")
        return
    # enforce min-gap + total cap (keep earliest, drop cues too close to a kept one)
    events.sort(key=lambda e: e[0])
    kept: list[tuple[float, Path, float]] = []
    for ev in events:
        if kept and ev[0] - kept[-1][0] < min_gap_s:
            continue
        kept.append(ev)
        if len(kept) >= cap:
            break

    tmp = out_mp4.with_name(out_mp4.stem + "_dsfx.mp4")
    try:
        inputs = ["-i", str(out_mp4)]
        for _, sfx, _g in kept:
            inputs += ["-i", str(sfx)]
        parts, mixn = [], ["[0:a]"]
        for idx, (tm, _sfx, gain) in enumerate(kept, start=1):
            parts.append(f"[{idx}:a]volume={gain:.2f},adelay={int(tm*1000)}:all=1[s{idx}]")
            mixn.append(f"[s{idx}]")
        fc = ";".join(parts) + ";" + "".join(mixn) + \
            f"amix=inputs={len(kept)+1}:duration=first:dropout_transition=0:normalize=0[a]"
        run(["ffmpeg", "-y", *inputs, "-filter_complex", fc,
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             str(tmp)])
        if tmp.exists() and tmp.stat().st_size > 0:
            _replace_retry(tmp, out_mp4, label="dsfx")
            names = ", ".join(sorted({p.stem for _, p, _ in kept}))
            print(f"[3++/5] Event SFX mixed ({len(kept)} cues: {names})")
    except Exception as e:
        if STRICT:
            raise RuntimeError(f"Event-SFX mix failed ({e})") from e
        print(f"[sfx-ev] [warn] skipped ({e})")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _zoompan_expr(motion_idx: int, frames: int) -> tuple[str, str, str]:
    """Return (z, x, y) zoompan expressions for a Ken Burns move.

    6 cycling moves: zoom-in, zoom-out, pan R/L/up/down. Background is pre-scaled
    so there is room to pan/zoom without showing edges.
    """
    n = max(1, frames)
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    m = motion_idx % 6
    if m == 0:  # zoom in (centered)
        return (f"min(1+0.0012*on,1.18)", cx, cy)
    if m == 1:  # zoom out (centered)
        return (f"max(1.18-0.0012*on,1.0)", cx, cy)
    z = "1.12"
    if m == 2:  # pan right
        return (z, f"(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)/2")
    if m == 3:  # pan left
        return (z, f"(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)/2")
    if m == 4:  # pan up
        return (z, "(iw-iw/zoom)/2", f"(ih-ih/zoom)*(1-on/{n})")
    return (z, "(iw-iw/zoom)/2", f"(ih-ih/zoom)*on/{n}")  # pan down


def ken_burns_scene(
    illu_png: Path, overlay_png: Path, audio: Path, dur: float,
    out_mp4: Path, motion_idx: int, avatar_mp4: Path | None = None,
    *, inset_frac: float = 0.42, margin: int = 80, fps: int = 30,
) -> None:
    """Compose a scene clip: Ken-Burns-animated illustration background + static
    text overlay (+ optional talking-head presenter inset). Audio = avatar's
    narration if present, else the scene voiceover."""
    frames = max(1, round(dur * fps))
    z, x, y = _zoompan_expr(motion_idx, frames)
    is_portrait = H > W
    sw, sh = (2700, 4800) if is_portrait else (4800, 2700)
    kb = (
        f"[0:v]scale={sw}:{sh}:flags=lanczos,setsar=1,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps}"
        f"{(',' + GRADE) if GRADE else ''}[bg];"
    )
    inputs = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(illu_png),
        "-i", str(audio),
        "-loop", "1", "-i", str(overlay_png),
    ]
    # Gentle in/out fade on the video only (audio untouched, clip duration
    # unchanged) so scene cuts feel smooth instead of hard — and the caption
    # offsets (computed from clip durations) stay exact.
    fd = 0.15
    fade = f"fade=t=in:st=0:d={fd},fade=t=out:st={max(0.0, dur - fd):.2f}:d={fd}"
    if avatar_mp4 is not None:
        inputs += ["-i", str(avatar_mp4)]
        av_h = int(H * inset_frac)
        filt = (
            kb
            + "[bg][2:v]overlay=0:0[bt];"
            + f"[3:v]scale=-2:{av_h},setsar=1[av];"
            + f"[bt][av]overlay=W-w-{margin}:H-h-{margin}:shortest=1,{fade}[v]"
        )
        amap = "3:a"
    else:
        filt = kb + f"[bg][2:v]overlay=0:0,{fade}[v]"
        amap = "1:a"

    run(inputs + [
        "-filter_complex", filt,
        "-map", "[v]", "-map", amap,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{dur:.2f}", "-shortest",
        str(out_mp4),
    ])


# ─── Audio: edge-tts neural voice (free, no API key) per scene ──────────────────

def _trim_silence(audio: Path, pad: float = 0.08) -> None:
    """Strip leading + trailing silence from a TTS clip, keeping a tiny pad. Per
    scene this stops the next image appearing during dead air at the clip edges —
    the visible symptom is the picture running a few seconds ahead of the voice.
    No-op if ffmpeg is missing or the filter fails (keeps the original audio)."""
    fm = shutil.which("ffmpeg")
    if not fm:
        return
    tmp = audio.with_name(audio.stem + "_trim" + audio.suffix)
    thr = "-45dB"
    af = (
        f"silenceremove=start_periods=1:start_silence={pad}:start_threshold={thr}:detection=peak,"
        "areverse,"
        f"silenceremove=start_periods=1:start_silence={pad}:start_threshold={thr}:detection=peak,"
        "areverse"
    )
    try:
        proc = subprocess.run(
            [fm, "-y", "-i", str(audio), "-af", af, str(tmp)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, audio)
        elif tmp.exists():
            tmp.unlink()
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _sentences_to_words(sentences: list[dict]) -> list[dict]:
    """Expand SentenceBoundary spans into per-word timings by distributing each
    sentence's [start,end] across its words proportional to word length. Used for
    multilingual edge-tts voices that don't emit WordBoundary. Approximate but the
    TEXT is exact and the sentence span is ground truth, so it beats whisper."""
    out: list[dict] = []
    for s in sentences:
        txt = (s.get("text") or "").strip()
        toks = txt.split()
        if not toks:
            continue
        s0, s1 = float(s["start"]), float(s["end"])
        span = max(0.01, s1 - s0)
        weights = [max(1, len(t)) for t in toks]
        total = sum(weights)
        t = s0
        for tok, wgt in zip(toks, weights):
            d = span * (wgt / total)
            out.append({"start": t, "end": t + d, "text": tok})
            t += d
    return out


def _trim_to_span(audio: Path, words: list[dict], pad: float = 0.08) -> None:
    """Cut the audio to its real speech span [first_word - pad, last_word + pad]
    and shift the word timings in-place to match the trimmed clip. More precise
    than silence detection because edge-tts tells us exactly when speech starts/
    ends. No-op (keeps original) if ffmpeg missing or the cut fails."""
    if not words:
        return
    fm = shutil.which("ffmpeg")
    if not fm:
        return
    t0 = max(0.0, words[0]["start"] - pad)
    t1 = words[-1]["end"] + pad
    if t1 <= t0:
        return
    tmp = audio.with_name(audio.stem + "_span" + audio.suffix)
    try:
        proc = subprocess.run(
            [fm, "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
             "-i", str(audio), "-c", "copy", str(tmp)],
            capture_output=True, text=True, timeout=120,
        )
        # -c copy can be imprecise on mp3 frame boundaries; re-encode if it failed
        if proc.returncode != 0 or not (tmp.exists() and tmp.stat().st_size > 0):
            proc = subprocess.run(
                [fm, "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                 "-i", str(audio), str(tmp)],
                capture_output=True, text=True, timeout=120,
            )
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, audio)
            for w in words:  # shift to the new zero
                w["start"] = max(0.0, w["start"] - t0)
                w["end"] = max(0.0, w["end"] - t0)
        elif tmp.exists():
            tmp.unlink()
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _render_voice_edge(text: str, out_audio: Path, voice: str,
                       rate: str, pitch: str) -> float:
    """Edge neural TTS path — emits EXACT WordBoundary timings (best sync). Writes
    mp3 + a .words.json sidecar. Raises on failure so the chain can fall back."""
    import edge_tts  # noqa: F401  (import error → caller falls back)

    audio_buf = bytearray()
    words: list[dict] = []
    sentences: list[dict] = []

    async def _go() -> None:
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        async for ch in comm.stream():
            t = ch.get("type")
            if t == "audio":
                audio_buf.extend(ch["data"])
            elif t == "WordBoundary":
                st = ch["offset"] / 1e7   # 100-ns ticks → seconds
                words.append({"start": st, "end": st + ch["duration"] / 1e7,
                              "text": ch.get("text", "")})
            elif t == "SentenceBoundary":
                st = ch["offset"] / 1e7
                sentences.append({"start": st, "end": st + ch["duration"] / 1e7,
                                  "text": ch.get("text", "")})

    _aiorun(_go())
    if not audio_buf:
        raise RuntimeError("edge-tts returned no audio")
    if not words and sentences:
        words = _sentences_to_words(sentences)
    out_audio.write_bytes(bytes(audio_buf))
    if words:
        _trim_to_span(out_audio, words, pad=0.08)
    else:
        _trim_silence(out_audio)
    try:
        out_audio.with_suffix(".words.json").write_text(
            json.dumps(words), encoding="utf-8")
    except Exception:
        pass
    return probe_duration(out_audio)


def _render_voice_provider(text: str, out_audio: Path, spec, rate: str, pitch: str,
                           clone_path: str | None = None) -> float:
    """Non-edge provider path (kokoro / xttsv2 / f5tts) via the TTS registry.

    These engines don't emit word boundaries, so word timings are approximated by
    distributing the KNOWN script text across the measured audio duration
    (proportional by length) — exact text, ground-truth duration, beats whisper.
    Writes mp3 + a .words.json sidecar so caption + kinetic word-sync still work.
    """
    from omnicast.media.providers.registry import get_tts_provider
    provider = get_tts_provider(spec.provider)
    clone = clone_path
    if spec.provider in ("xttsv2", "f5tts") and not clone:
        clone = spec.voice  # clone providers take the ref-audio path as the voice
    raw = out_audio.with_suffix(".tts.wav")
    # Per-scene prosody: kokoro's native `speed` param measurably does NOT land
    # (syllable-rate variance ~0.06 vs the 0.08 vfact gate — flat delivery is
    # the #1 reason narrated horror reads as boring). Realize the requested rate
    # deterministically with ffmpeg atempo AFTER synthesis instead, for every
    # non-edge provider. Pitch untouched; clamped so voices never chipmunk.
    _m = re.search(r"-?\d+", rate or "+0%")
    _speed = round(1.0 + (int(_m.group()) if _m else 0) / 100.0, 3)
    _speed = max(0.85, min(1.15, _speed))
    _aiorun(provider.generate(text, model=spec.voice,
                              voice_clone_path=clone, output_path=str(raw)))
    if not raw.exists() or raw.stat().st_size == 0:
        raise RuntimeError(f"{spec.provider} produced no audio")
    # Transcode to mp3 (pipeline expects mp3 at out_audio); trim leading/trailing silence.
    _af = ["-af", f"atempo={_speed}"] if abs(_speed - 1.0) >= 0.02 else []
    run(["ffmpeg", "-y", "-i", str(raw), *_af,
         "-c:a", "libmp3lame", "-b:a", "192k", str(out_audio)])
    try:
        raw.unlink()
    except Exception:
        pass
    _trim_silence(out_audio)
    dur = probe_duration(out_audio)
    words = _sentences_to_words([{"start": 0.0, "end": dur, "text": text}])
    for w in words:
        w["approx"] = True  # proportional estimate, NOT real word boundaries —
        # caption code must prefer whisper alignment over these (drift!).
    try:
        out_audio.with_suffix(".words.json").write_text(json.dumps(words), encoding="utf-8")
    except Exception:
        pass
    return dur


def render_voice(text: str, out_audio: Path, voice_chain="en-US-GuyNeural",
                 rate: str = "+10%", pitch: str = "+12Hz",
                 clone_path: str | None = None) -> float:
    """Synthesize narration through the channel's voice chain (provider:voice_id),
    trying each spec in order until one succeeds — real multi-source TTS.

    `voice_chain` may be a list of specs (['kokoro:af_heart', 'edge:en-US-AriaNeural'])
    or a bare string (treated as a single edge voice for back-compat). Edge specs
    get exact WordBoundary timings; other providers get proportional timings.
    Neural-only by policy — if the whole chain fails the job fails (no robotic SAPI).
    """
    from omnicast.media.voice_router import VoiceSpec

    if isinstance(voice_chain, str):
        # bare voice id → edge (back-compat with --voice and old callers)
        chain = [voice_chain if ":" in voice_chain else f"edge:{voice_chain}"]
    else:
        chain = list(voice_chain) or ["edge:en-US-AriaNeural"]

    # STRICT: the channel's PRIMARY voice or nothing. The fallback chain once
    # silently swapped kokoro for a flat edge voice — the whole video shipped
    # sounding lifeless. A failed render is cheaper than a bad published voice.
    if STRICT and len(chain) > 1:
        chain = chain[:1]

    errors: list[str] = []
    for raw in chain:
        try:
            spec = VoiceSpec.parse(raw)
        except Exception as e:
            errors.append(f"{raw}: {e}")
            continue
        try:
            if spec.provider == "edge":
                return _render_voice_edge(text, out_audio, spec.voice, rate, pitch)
            return _render_voice_provider(text, out_audio, spec, rate, pitch, clone_path)
        except Exception as exc:
            errors.append(f"{spec}: {exc}")
            print(f"      [warn] voice '{spec}' failed ({exc}); trying next in chain")

    raise RuntimeError(f"All TTS voices failed (neural-only, no robotic fallback). "
                       f"Chain={chain} Errors={errors}")


# ─── FFmpeg: real subprocess ────────────────────────────────────────────────────

def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-2000:])
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd[:6])} ...")


def scene_to_mp4(png: Path, wav: Path, dur: float, out_mp4: Path) -> None:
    """Still image + voiceover → timed scene clip (real ffmpeg)."""
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(png),
        "-i", str(wav),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H}",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{dur:.2f}", "-shortest",
        str(out_mp4),
    ])


def avatar_over_background(
    bg_png: Path,
    avatar_mp4: Path,
    out_mp4: Path,
    *,
    inset_frac: float = 0.42,
    margin: int = 80,
) -> None:
    """Composite a talking-head clip as a presenter inset over an illustration bg.

    bg_png    = still illustration (background image, no audio)
    avatar_mp4 = talking-head video WITH narration audio (drives duration + sound)

    The avatar is scaled to `inset_frac` of frame height and pinned bottom-right
    with a margin — an intentional "presenter + slide" composition. The output
    uses the avatar clip's audio and runs for the avatar's duration.
    """
    av_h = int(H * inset_frac)
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg_png),
        "-i", str(avatar_mp4),
        "-filter_complex",
        (
            f"[0:v]scale={W}:{H},setsar=1[bg];"
            f"[1:v]scale=-2:{av_h},setsar=1[av];"
            f"[bg][av]overlay=W-w-{margin}:H-h-{margin}:shortest=1[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_mp4),
    ])


def concat_scenes(clips: list[Path], out_mp4: Path, work: Path) -> None:
    listfile = work / "concat.txt"
    # concat demuxer resolves paths relative to the list file; use absolute.
    listfile.write_text(
        "\n".join(f"file '{c.resolve().as_posix()}'" for c in clips), encoding="utf-8"
    )
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(listfile),
        "-c", "copy",
        str(out_mp4),
    ])


def _load_image_provider(provider_id: str):
    """Resolve an image provider from the omnicast package (src/)."""
    src = ROOT / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from omnicast.media.providers.registry import get_image_provider

    return get_image_provider(provider_id)


# Shared art direction prepended to EVERY scene image prompt (autovio pattern:
# a consistent style prefix is what makes a scene set look like one coherent film
# instead of unrelated stock images).
STYLE_PREFIXES = {
    "editorial": (
        "ONE single full-frame cinematic illustration of a single scene, "
        "consistent art direction, semi-realistic digital painting, dramatic "
        "volumetric lighting, teal-and-amber cinematic color grade, "
        "cinematic composition, highly detailed, no text, no words, no letters"
    ),
    # Bible/history storybook look (matches the user's reference prompts).
    "watercolor": (
        "ONE single full-frame hand-painted watercolor illustration of a single "
        "scene, thin black ink outlines, soft watercolor wash, warm burnt orange "
        "and sepia and soft navy tones, white paper background with visible paper "
        "texture, modern storybook illustration, no text, no words"
    ),
    # Realistic documentary look (history/mythology explainers).
    "documentary": (
        "ONE single full-frame cinematic documentary illustration of a single "
        "scene, realistic detailed rendering, natural dramatic lighting, muted "
        "earthy palette, subtle film grain, cinematic composition, no text, no words"
    ),
    # Finance/news explainer look (matches the reference finance thumbnails).
    "dark_finance": (
        "ONE single full-frame sleek financial explainer illustration of a single "
        "scene, dark navy background, gold and red accents, glowing data "
        "visualisations and charts, dramatic rim lighting, modern, high detail, "
        "no text, no words, no letters"
    ),
    # Educational/medical channels look.
    "clean_educational": (
        "ONE single full-frame clean vector illustration of a single scene, minimalist design, "
        "flat colors, bright pastel color scheme, friendly corporate Memphis aesthetic, "
        "professional outline, modern digital art, clean background, no text, no words"
    ),
    # Vibrant 3D channels look.
    "vibrant_3d": (
        "ONE single full-frame modern 3d illustration of a single scene, vibrant clay render style, "
        "smooth plastic textures, isometric perspective, warm inviting studio lighting, "
        "colorful visual elements, cute friendly design, no text, no words"
    ),
    # Whiteboard channels look.
    "whiteboard_sketch": (
        "ONE single full-frame hand-drawn whiteboard sketch of a single scene, simple black ink "
        "line drawings, whiteboard background, minimalist marker illustration, conceptual "
        "diagrammatic drawing, no text, no words"
    ),
    # Horror "found footage" look. The scares must read as REAL amateur photos —
    # cinematic/designed AI frames (symmetry, rim light, movie-poster grade)
    # instantly kill the 'this happened' effect (operator feedback 2026-07-11).
    "found_photo": (
        "ONE single full-frame REAL PHOTOGRAPH of a single scene, amateur night "
        "photo taken on an old phone camera, harsh direct flash or a single dim "
        "sodium light, heavy high-ISO grain, slight motion blur, imperfect "
        "off-center framing, mundane realistic environment with ONE unsettling "
        "detail, no text, no words"
    ),
}
STYLE_PREFIX = STYLE_PREFIXES["editorial"]  # default; overridden by --style

# Base negative prompts applied globally to all generations (mostly layout & text bans).
NEGATIVE_COMMON = ("text, words, letters, watermark, logo, low quality, blurry, "
                   "extra limbs, deformed, grid, collage, split screen, multiple "
                   "panels, contact sheet, 2x2, four panels, montage, diptych, triptych")

# Style-specific negative prompts to prevent models from shifting media (e.g. 3D models outputting flat sketches).
STYLE_NEGATIVES = {
    "editorial": "photograph, photo, photorealistic, realistic photo, stock photo, 3d render, cgi, dslr, raw photo, hyperrealistic",
    "watercolor": "photograph, photo, photorealistic, realistic photo, stock photo, 3d render, cgi, dslr, raw photo, hyperrealistic, digital painting, vectors",
    "documentary": "3d render, cgi, sketch, watercolor, vector, flat design, illustration, cartoon",
    "dark_finance": "photograph, photo, photorealistic, realistic photo, stock photo, cgi, dslr, raw photo, hyperrealistic, hand-drawn sketch, watercolor",
    "clean_educational": "photograph, photo, realistic, 3d render, cgi, volumetric lighting, dark atmosphere, shadow gradients, sketch, detailed texture",
    "vibrant_3d": "photograph, photo, realistic, watercolor, sketch, hand-drawn, flat vector, ink lines",
    "whiteboard_sketch": "photograph, photo, realistic, 3d render, cgi, colorful painting, watercolor, complex background, shadow gradient",
    "found_photo": ("illustration, painting, digital art, concept art, 3d render, cgi, "
                    "cinematic lighting, dramatic rim light, volumetric light, symmetrical "
                    "composition, movie poster, film still, professional photography, "
                    "studio lighting, bokeh, color grading, posed, epic, stylized"),
}

# Keep NEGATIVE_DEFAULT for backwards compatibility / default fallback
NEGATIVE_DEFAULT = f"{NEGATIVE_COMMON}, {STYLE_NEGATIVES['editorial']}"

# Short, hard style lock appended to the END of every image prompt. Models weight
# trailing tokens heavily, so this re-asserts the medium after the LLM's scene
# description (which often drifts toward photoreal on photo-leaning models).
STYLE_LOCK = {
    "editorial": "in a consistent semi-realistic digital painting illustration style, not a photograph",
    "watercolor": "in a consistent hand-painted watercolor illustration style, not a photograph",
    "documentary": "in a consistent painted cinematic illustration style, not a photograph",
    "dark_finance": "in a consistent sleek digital illustration style, not a photograph",
    "clean_educational": "in a consistent clean minimalist vector illustration style, flat colors, not a photograph, not 3D",
    "vibrant_3d": "in a consistent vibrant 3d clay illustration style, smooth textures, not a photograph",
    "whiteboard_sketch": "in a consistent hand-drawn marker whiteboard sketch style, simple lines, not a photograph",
    "found_photo": ("as a real unedited amateur photograph, grainy and imperfect, "
                    "not an illustration, not cinematic, not posed, not symmetrical"),
}

# Per-channel LOOK applied to every shot background (channels/<id>.json
# "visual_grade"; auto "horror" when channel_style == horror_real). Raw stock
# reads as clean documentary footage — horror needs crushed blacks, cold
# desaturation, heavy vignette and live grain or it carries zero dread.
GRADE_PRESETS = {
    "horror": ("eq=brightness=-0.05:contrast=1.15:saturation=0.42,"
               "colorbalance=bs=0.10:bm=0.05:bh=0.03,"
               "vignette=angle=PI/4.3,noise=alls=6:allf=t+u"),
}
GRADE = ""  # set per-channel in main()


# Storyboard art-director system prompt — mirrors autovio's continuity constraint:
# all scenes form a continuous video with choice between generated images and web search images.
STORYBOARD_SYSTEM = (
    "You are a storyboard art director for a narrated explainer video. Given the "
    "full narration split into ordered scenes, produce a JSON array of per-scene "
    "visual prompts. For each scene, pick the BEST visual type to make the video "
    "feel like a real, dynamic documentary — not a static slideshow.\n\n"
    "CRITICAL #1 — VISUAL TYPE CRITERIA. Decide per scene with ONE question: 'CAN I FILM IT?'\n"
    "  DECISION TREE (pick exactly one):\n"
    "  1) Is it a real action/place/object/person you could film generically (eating, cooking, "
    "a tired person, a kitchen, nature)? -> 'stock_video' (DEFAULT, ~75-80% of scenes).\n"
    "  2) Is it a SPECIFIC real thing that must be shown EXACTLY and a generic clip won't do — a "
    "named product (e.g. an Ozempic pen), a real public figure/brand/logo, a study figure / chart "
    "/ data table, a map, a news headline? -> 'web_search_image' (fetches the real photo). Use this "
    "for AUTHORITY/DATA moments (the documentary 'show the real source' technique).\n"
    "  3) Is it a striking NUMBER? -> 'stock_video' background + stat_number/stat_label (kinetic).\n"
    "  4) Is it PURELY abstract/symbolic — unfilmable AND no real photo exists (a metaphysical "
    "concept, a stylized internal-body process)? -> 'generated_image' (LAST resort, ~5-10%; looks "
    "cartoonish, breaks realism — avoid unless truly nothing real fits).\n"
    "  Bias order: stock_video > web_search_image > kinetic > generated_image.\n"
    "- 'stock_video': PREFER THIS for any concrete real-world subject, action, place, "
    "object, nature, people, or activity (e.g. melting glacier, city traffic, person "
    "eating, ocean waves, factory, hands typing). Real moving B-roll footage is far more "
    "engaging than a still image. The 'stock_query' MUST be a CONCRETE, FILMABLE visual "
    "subject (2-5 plain nouns/scene words a stock site would have): e.g. 'tired woman "
    "kitchen table', 'salmon fillet plate', 'person declining wine glass'. NEVER an abstract "
    "phrase or idiom (NOT 'plan backfires', NOT 'backfires completely', NOT 'the real reason') "
    "— abstract queries pull random unrelated videos. If a line is abstract, translate it to a "
    "concrete scene that represents it.\n"
    "  >> STRICT STOCK QUERY RULES (a bad query pulls an absurd clip — cat sniffing coffee, "
    "clothing tags — that ruins the video):\n"
    "    (a) Lead with the CONCRETE physical subject + a visible action/shot: 'pouring olive oil "
    "close up', 'coconut oil spooned from jar', NOT a vague word like 'quality'/'material'/'problem' "
    "(those pull the wrong sense, e.g. 'quality' -> clothing-quality-check footage).\n"
    "    (b) NEVER query a brand / recipe / compound name a stock library won't have "
    "(NOT 'bulletproof coffee', NOT 'MCT oil') — translate to the GENERIC filmable form: "
    "'creamy coffee in a mug', 'person drinking coffee', 'clear oil poured into coffee'.\n"
    "    (c) NEVER append abstract suffixes to a food/object query — no 'animation', 'molecules', "
    "'diagram', '3d', 'stomach', 'slow', 'illustration' tacked on (e.g. NOT 'MCT fat molecules "
    "animation stomach slow' — just 'coconut oil pouring close up'). Those suffixes return zero hits "
    "then fall back to junk.\n"
    "    (d) Keep it 2-4 everyday nouns a Pexels/Pixabay clip would actually be tagged with.\n"
    "    (e) NEVER query 'reading/holding a label / package / box / nutrition facts' — stock libraries "
    "have no nutrition-label footage and return CLOTHING-tag / apparel videos instead. Show the actual "
    "FOOD or PRODUCT directly (e.g. vo 'quality of the fat, olive oil is healthy' -> 'olive oil bottle "
    "and almonds on table', NOT 'person reading nutrition label').\n"
    "  >> METAPHOR EXCEPTION: when the narration explains an ABSTRACT process (a physiological/"
    "mechanical mechanism) and the scene's intended visual gives a concrete visual metaphor for it, "
    "USE that metaphor as the stock_query AS LONG AS it is itself filmable B-roll. "
    "e.g. vo 'your stomach slows to a crawl' + metaphor 'clogged traffic alley' -> stock_query "
    "'traffic jam narrow street' (real footage exists). The metaphor must be a literal filmable scene, "
    "never the idiom itself ('stomach slows' stays banned; 'traffic jam' is fine).\n"
    "- 'generated_image': Use ONLY for abstract concepts/metaphors with no real footage "
    "(e.g. a symbolic visual metaphor). Keep a consistent style across these.\n"
    "- 'web_search_image': USE GENEROUSLY for any SPECIFIC real thing that must be exact — named "
    "product packaging, a real person/brand/logo, a data chart/graph/study figure, a map, a news "
    "headline/screenshot. This is the 'real evidence on screen' technique (like a documentary "
    "cutting to the actual NASA map). Real photos beat generic b-roll for these. Provide a precise "
    "'search_query' (e.g. 'Ozempic semaglutide injection pen', 'GLP-1 nausea incidence chart', "
    "'Wegovy box packaging'). Returns real, watermark-filtered images.\n"
    "- 'web_screenshot': Use ONLY when the narration references a website/report/dashboard/social post "
    "AND you can supply a REAL, well-known, currently-live URL (e.g. a homepage like 'https://www.cdc.gov', "
    "'https://www.fda.gov', 'https://pubmed.ncbi.nlm.nih.gov') in 'search_query'. "
    "Do NOT invent deep article URLs (e.g. fake '/article/12345' paths) — they 404 and screenshot a blank/error page. "
    "If you cannot name a real live URL, use 'web_search_image' (to find the report/headline image) or "
    "'stock_video' instead — never a guessed URL.\n"
    "  >> AUTHORITY/CITATION moments ('clinical trials', 'studies show', 'research found'): do NOT screenshot "
    "a site homepage — homepages render mostly blank/white in headless capture and look broken. "
    "For authority, use 'web_search_image' (search_query like 'GLP-1 nausea clinical study journal page') "
    "to fetch a real report/figure image, or a 'stock_video' of a lab/clinician. Reserve 'web_screenshot' "
    "only for a CONTENT-RICH page you are confident renders with visible text/figures.\n\n"
    "CRITICAL #1b — KINETIC STATS (USE VERY SPARINGLY): a stat callout is a RARE "
    "punctuation mark, not a habit. Across the WHOLE video set 'stat_number' on AT MOST "
    "3-4 scenes — ONLY the single most SHOCKING, memorable numbers (the headline stat of "
    "the video). For every other number — minor durations ('6 hours', '12 hours'), small "
    "amounts ('5g', '10g'), ordinary multipliers — LEAVE stat_number EMPTY and just let "
    "the narration + B-roll carry it. Over-using callouts looks cheap and noisy (the "
    "opposite of a premium documentary, which lets footage breathe with no text most of "
    "the time). When you DO use one: fill 'stat_number' (e.g. '50%', '44%') and 'stat_label' "
    "(a SHORT ALL-CAPS caption, e.g. 'OF USERS REPORT NAUSEA'); it renders as a plain bold "
    "white callout. You MUST then set visual_type 'stock_video' (a calm related real scene) "
    "for the background — NEVER 'generated_image', and NEVER a chart/graph/bar-graph. "
    "Default to EMPTY stat_number; only the rare headline number earns a callout.\n"
    "  >> CRITICAL: the background 'stock_query' MUST depict the SUBJECT of the stat_label, "
    "NOT a literal prop of the number. The number is already drawn by the callout. "
    "WRONG: stat '60+ min' / 'PROLONGED STOMACH EMPTYING' -> 'person checking watch clock' "
    "(a wristwatch has nothing to do with digestion — looks absurd). "
    "RIGHT: -> 'stomach digestion anatomy' or 'slow food digesting'. "
    "Never use clock/stopwatch/timer/calendar/number-prop footage for a time/quantity stat; "
    "film the THING the stat is about.\n\n"
    "CRITICAL #1c — NEVER A CHART: do NOT request charts, graphs, bar graphs, pie charts, "
    "diagrams of numbers, or 'statistics visual' for ANY visual_type — generated images render "
    "them as garbled nonsense. Show the IDEA with a real scene + a kinetic stat callout.\n"
    "  >> NO ABSTRACT SCIENCE STOCK: for a nutrition/diet/digestion topic, NEVER fall back to "
    "'DNA strand', 'molecule', 'cell', 'double helix', 'lab beaker' footage to mean a nutrient or "
    "deficiency — it is disconnected and screams stock-filler. Film the CONCRETE everyday subject: "
    "vitamin/nutrient -> the supplement bottle + capsules + the actual foods (e.g. 'vitamin B6 "
    "supplement pills and salmon spinach bananas'); 'deficiency' -> a tired person / those foods; "
    "'protein' -> eggs, chicken, a shaker. Always the food/pill/body, never the molecule.\n\n"
    "CRITICAL #1d — DOCUMENTARY CONSISTENCY: aim for 90%+ of scenes to be 'stock_video' "
    "(real footage) so the film looks coherent — mixing cartoon AI images with real footage "
    "looks broken. Use 'generated_image' ONLY for a pure abstract metaphor with NO filmable "
    "equivalent, and never for journals, studies, reports, notebooks, documents, app/UI, or "
    "anything with text (those render as garbled scribbles). For a journal/study/report/website "
    "reference use 'web_screenshot'. Everything else → 'stock_video' with a concrete query.\n\n"
    "CRITICAL #2 — GENERATED IMAGES LIMITATIONS:\n"
    "If visual_type is 'generated_image', the image model CANNOT render legible text, charts, "
    "graphs, website UIs, or numbers. NEVER ask for a chart/UI in a generated image. Instead, "
    "describe ONLY the concrete subject, setting, composition, lighting, and mood. Never name a "
    "medium or realism level (no 'photo', 'photorealistic').\n\n"
    "CRITICAL #3 — WEB SEARCH QUERIES:\n"
    "If visual_type is 'web_search_image', you must provide a 'search_query' containing precise, "
    "specific English keywords that will yield high-quality, relevant real-world images from "
    "a search engine. (e.g., 'Semaglutide Wegovy syringe packaging box', 'Shopify merchant analytics dashboard screenshot', "
    "'medical chart showing brain scan', 'Bloomberg news article headline on GLP-1'). Keep the query "
    "descriptive but concise. Also provide a fallback 'image_prompt' in case search fails.\n\n"
    "CRITICAL #4 — MATCH THE NARRATION: each scene's visual must directly match what the voiceover "
    "is saying. If the voiceover talks about a specific statistic or news headline, use 'web_search_image' "
    "with a query for that headline or report.\n\n"
    "Return ONLY a JSON array of objects with keys: "
    "['scene_index', 'visual_type', 'stock_query', 'search_query', 'image_prompt', "
    "'video_prompt', 'negative_prompt', 'stat_number', 'stat_label']"
)


def _web_cache_path(query: str, w: int, h: int) -> Path:
    key = hashlib.sha256(f"web_{query}_{w}_{h}".encode("utf-8")).hexdigest()[:32]
    return _IMG_CACHE_DIR / f"web_{key}.png"


class ChartAuditError(RuntimeError):
    """A chart value failed the fact-ledger audit — the render must stop."""


def _ledger_digit_cores(script_path: Path) -> set[str] | None:
    """Digit cores of every value in the product's fact ledger, or None when no
    ledger exists (non-YMYL channel or pre-ledger product)."""
    lf = script_path.parent / "fact_ledger.json"
    if not lf.exists():
        return None
    try:
        data = _json.loads(lf.read_text(encoding="utf-8"))
        entries = (data.get("ledger") or {}).get("entries") or []
        cores: set[str] = set()
        for e in entries:
            for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", f"{e.get('value', '')} {e.get('claim', '')}"):
                core = re.sub(r"\D", "", tok)
                if core:
                    cores.add(core)
        return cores
    except Exception as exc:
        print(f"[chart] [warn] fact ledger unreadable ({exc}) — treating as absent")
        return None


def _render_chart_cell(spec: dict, dest: Path, script_path: Path, w: int, h: int) -> bool:
    """Render a storyboard chart cell as a REAL data chart (chart_gen PNG).

    Fail-closed audit: when the product carries a fact ledger, every chart value
    must appear in it — a figure the ledger never sourced must not reach the
    screen (raises ChartAuditError, which aborts the render on purpose)."""
    labels = [str(x) for x in (spec.get("labels") or [])]
    values_raw = spec.get("values") or []
    if not labels or len(labels) != len(values_raw) or not (2 <= len(labels) <= 6):
        print(f"[chart] [warn] malformed chart_spec (labels={len(labels)}, "
              f"values={len(values_raw)}) — skipping chart")
        return False
    try:
        values = [float(v) for v in values_raw]
    except (TypeError, ValueError):
        print("[chart] [warn] non-numeric chart values — skipping chart")
        return False

    cores = _ledger_digit_cores(script_path)
    if cores is None:
        print("[chart] [warn] no fact ledger to audit against — chart skipped "
              "(unaudited numbers must not render)")
        return False
    bad = [v for v in values
           if re.sub(r"\D", "", f"{v:g}") and re.sub(r"\D", "", f"{v:g}") not in cores]
    if bad:
        raise ChartAuditError(
            f"chart values {bad} not present in fact_ledger.json — a figure "
            "without a sourced ledger entry must not be drawn (fix the ledger "
            "or the storyboard, then re-render)")

    from omnicast.media.providers import chart_gen
    if not chart_gen.available():
        print("[chart] [warn] matplotlib unavailable — chart skipped")
        return False
    return chart_gen.render_chart(
        list(zip(labels, values)), dest,
        title=str(spec.get("title") or ""),
        highlight_label=(str(spec.get("highlight")) if spec.get("highlight") else None),
        source=str(spec.get("source") or ""),
        w=w, h=h)


# Content-addressed image cache: identical (prompt, model, canvas size) always
# yields the same illustration, so we never re-spend Flow/Imagen quota on a shot
# we already rendered. Survives re-renders that only change compose/concat/BGM/
# captions. Key = sha256(model|WxH|prompt) — style + DNA already live in `prompt`.
_IMG_CACHE_DIR = ROOT / "output" / "_img_cache"


def _img_cache_path(prompt: str, model: str, w: int, h: int) -> Path:
    key = hashlib.sha256(f"{model}|{w}x{h}|{prompt}".encode("utf-8")).hexdigest()[:32]
    return _IMG_CACHE_DIR / f"{key}.png"


def _cache_hit(p: Path) -> bool:
    try:
        return p.exists() and p.stat().st_size > 0
    except Exception:
        return False


def build_illustration_prompt(scene: Scene, style_prefix: str) -> str:
    """Fallback per-scene prompt (used when the storyboard LLM is unavailable)."""
    topic = re.sub(r"[\[\]]", "", scene.heading).strip()
    return f"{style_prefix}, scene depicting {topic}"


def _replace_retry(src: Path, dst: Path, label: str = "", tries: int = 6,
                   delay_s: float = 5.0) -> None:
    """os.replace with retries — the render target is often LOCKED by a media
    player previewing it (WinError 5), which used to silently drop BGM/SFX/
    kinetic passes. Raises on final failure so callers log their warning."""
    for t in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if t == 0:
                print(f"      [{label or 'replace'}] {dst.name} locked "
                      "(player open?) — retrying...")
            time.sleep(delay_s)
    raise PermissionError(f"{dst} still locked after {tries} tries — "
                          "close the video player and re-run")


def _repair_json_quotes(s: str) -> str:
    """Escape unescaped double quotes INSIDE JSON string values (LLM tell).
    A quote only closes a string if the next non-space char is , : ] or }."""
    out: list[str] = []
    in_str = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if not in_str:
            if c == '"':
                in_str = True
            out.append(c)
        elif c == "\\" and i + 1 < n:
            out.append(s[i:i + 2])
            i += 2
            continue
        elif c == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",:]}":
                in_str = False
                out.append(c)
            else:
                out.append('\\"')
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _storyboard_cache_path(scenes: list[Scene], style: str, channel_meta: dict | None = None) -> Path:
    """Deterministic cache key for a storyboard: same script + style + channel -> same
    prompts -> same image cache hits. Without this, the LLM's temperature would
    produce fresh prompts every re-render and defeat the image cache."""
    meta_str = json.dumps(channel_meta or {}, sort_keys=True)
    # Schema version token: bump when the storyboard schema changes so old cached
    # boards (without new fields like stock_query/stat_number) are regenerated.
    blob = "sb_v16\n" + style + "\n" + meta_str + "\n" + "\n".join(f"{sc.heading}|{sc.narration}" for sc in scenes)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return _IMG_CACHE_DIR / f"storyboard_{key}.json"


def cached_storyboard(scenes: list[Scene], style: str, channel_meta: dict | None = None) -> list[dict] | None:
    """generate_storyboard with an on-disk cache keyed by script+style+channel. Lets a
    re-render (style tweak aside) reuse the exact prompts and hit the image cache."""
    import json as _json
    cp = _storyboard_cache_path(scenes, style, channel_meta)
    if _cache_hit(cp):
        try:
            data = _json.loads(cp.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) == len(scenes):
                print(f"[1a/5] Storyboard cache hit ({len(data)} prompts)")
                return data
        except Exception:
            pass
    board = generate_storyboard(scenes, channel_meta)
    if board:
        try:
            _IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(_json.dumps(board), encoding="utf-8")
        except Exception:
            pass
    return board


# Max scenes per storyboard LLM call. Fine-sync can expand a 10-min script to
# 130+ shots; one call would need ~350 output tokens/scene (~50k) and silently
# truncates at the 16k cap — the salvaged tail then loses its cells and renders
# as text cards / broken image gens. Chunking keeps every call under the cap.
_SB_CHUNK = 40


def generate_storyboard(scenes: list[Scene], channel_meta: dict | None = None) -> list[dict] | None:
    """Chunked LLM calls -> per-scene {image_prompt, video_prompt, negative_prompt}
    with cross-scene visual continuity. Returns None on any failure (caller
    falls back to per-scene heuristic prompts)."""
    try:
        src = ROOT / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))

        out: list[dict] = []
        for start in range(0, len(scenes), _SB_CHUNK):
            chunk = scenes[start:start + _SB_CHUNK]
            cells = _storyboard_chunk(chunk, start, len(scenes), channel_meta)
            if cells is None:
                # Partial board = the exact truncation bug this chunking fixes.
                # All-or-nothing: let the caller's retry/STRICT logic decide.
                return None
            out.extend(cells)
        return out
    except Exception as exc:
        print(f"      [warn] storyboard LLM failed ({exc}); per-scene fallback")
        return None


def _storyboard_chunk(scenes: list[Scene], offset: int, total: int,
                      channel_meta: dict | None = None) -> list[dict] | None:
    """One storyboard LLM call for scenes[offset:offset+len(scenes)] of `total`.
    Returns len(scenes) cells (missing indices become {}), or None on failure."""
    try:
        import asyncio

        import orjson

        from omnicast.config.settings import get_settings
        from omnicast.llm.client import LLMClient

        s = get_settings()
        scene_block = "\n".join(
            f"Scene {offset + i}: [{sc.heading}] {sc.narration[:400]}"
            for i, sc in enumerate(scenes)
        )
        chunk_note = ""
        if total > len(scenes):
            chunk_note = (
                f"(These are scenes {offset}-{offset + len(scenes) - 1} of a "
                f"{total}-scene video — keep the same continuous world/style as "
                f"the rest.) ")
        # The per-request preference must match the channel style — a hardcoded
        # 'PREFER stock_video' here overpowered the storytelling directive and
        # produced an all-stock board on an illustrated channel.
        prefer_line = ("PREFER 'stock_video' for real-world subjects/actions so "
                       "the video has real motion. ")
        try:
            from omnicast.config.channel_styles import get_style_policy
            _p = get_style_policy((channel_meta or {}).get("channel_style"))
            if _p and _p.preferred_type == "generated_image":
                prefer_line = ("PREFER 'generated_image' — this channel is an "
                               "ILLUSTRATED STORYTELLING channel (one continuous "
                               "painted world); use 'stock_video' only for rare "
                               "neutral atmosphere cutaways (sky, rain, fire). ")
        except Exception:
            pass
        # Real-chart mode: channels that declare (and can back) `chart_render`
        # may request a data-true chart cell. The chart is drawn by matplotlib
        # from the numbers given — NEVER by an image model — so CRITICAL #1c
        # (never a chart) is lifted only for this explicit visual_type.
        _chart_mode = "chart_render" in {
            str(x).strip().lower()
            for x in (channel_meta or {}).get("supported_production", []) or []}
        _chart_type = ' | "chart"' if _chart_mode else ""
        _chart_keys = (
            '  "chart_spec": {"title": "<short chart title>", '
            '"labels": ["<bar label>", "..."], "values": [<number>, ...], '
            '"highlight": "<label of the key bar, else empty>", '
            '"source": "<source name + year, e.g. SSA 2026>"},  // ONLY when visual_type is "chart"\n'
            if _chart_mode else "")
        _chart_note = (
            "CHART MODE ENABLED (overrides CRITICAL #1c for this channel): when the "
            "narration COMPARES 2-6 real numbers (claiming ages, tax tiers, costs), "
            "use visual_type 'chart' with a chart_spec. Use ONLY numbers spoken in "
            "the narration — the chart is rendered from your values by a real chart "
            "engine and every value is audited against the fact ledger; an invented "
            "value blocks the render. Single numbers still use the kinetic stat "
            "callout, not a chart. "
            if _chart_mode else "")
        user = (
            f"{chunk_note}{len(scenes)} scenes below. Pick the best visual_type per scene. "
            f"{prefer_line}{_chart_note}"
            f"Keep one continuous world + consistent style for any generated images.\n\n{scene_block}\n\n"
            "Return a JSON array, one object per scene IN ORDER:\n"
            '[{\n'
            '  "scene_index": 0,\n'
            f'  "visual_type": "stock_video" | "generated_image" | "web_search_image" | "web_screenshot"{_chart_type},\n'
            '  "stock_query": "<2-5 word B-roll keywords if stock_video, else empty>",\n'
            '  "search_query": "<search query or URL if web_search_image/web_screenshot, else empty>",\n'
            '  "image_prompt": "<detailed prompt for generation, or fallback if a fetch fails>",\n'
            '  "video_prompt": "<camera/motion for image-to-video>",\n'
            '  "negative_prompt": "<things to avoid>",\n'
            + _chart_keys +
            '  "stat_number": "<big number/stat if any, e.g. 52% — else empty>",\n'
            '  "stat_label": "<short ALL-CAPS caption for the stat, else empty>"\n'
            '}]'
        )

        system_prompt = STORYBOARD_SYSTEM
        if channel_meta:
            brand_voice = channel_meta.get("brand_voice", "")
            audience_meta = channel_meta.get("audience") or {}
            audience_pain = ""
            if isinstance(audience_meta, dict):
                pain_points = audience_meta.get("pain_points")
                if isinstance(pain_points, list):
                    audience_pain = ", ".join(pain_points)
                elif isinstance(pain_points, str):
                    audience_pain = pain_points
            
            context_blocks = []
            if brand_voice:
                context_blocks.append(f"Channel Brand Voice: {brand_voice}")
            if audience_pain:
                context_blocks.append(f"Target Audience Pain Points: {audience_pain}")
            
            if context_blocks:
                context_info = (
                    "\n\nCRITICAL #4 — RESPECT CHANNEL CONTEXT:\n"
                    "The video is for a channel with the brand voice and target audience described below. "
                    "The imagery, character demographics, tone, and metaphors should align with this brand voice "
                    "and directly address or visualize these audience pain points.\n\n"
                    "=== CHANNEL CONTEXT ===\n" + "\n".join(context_blocks) + "\n=======================\n"
                )
                system_prompt = STORYBOARD_SYSTEM + context_info

            # Channel-style sourcing directive (footage/storytelling/horror_real)
            # goes LAST so it outweighs the default footage-documentary bias.
            from omnicast.config.channel_styles import get_style_policy
            _policy = get_style_policy(channel_meta.get("channel_style"))
            if _policy:
                system_prompt = system_prompt + _policy.storyboard_directive

        llm = LLMClient(provider="deepseek", model=s.deepseek_flash_model)
        resp = _aiorun(llm.complete(
            system=system_prompt,
            messages=[{"role": "user", "content": user}],
            max_tokens=min(16000, 1500 + len(scenes) * 350), temperature=0.6,
        ))
        txt = resp.content
        m = re.search(r"\[[\s\S]*\]", txt)
        raw = m.group(0) if m else txt
        try:
            data = orjson.loads(raw)
        except Exception:
            # Same failure class as the Writer's scene JSON: unescaped inner
            # quotes / trailing commas. One bad char used to kill the WHOLE
            # board → every scene became a text card. Repair, then salvage
            # object-by-object so one broken cell can't sink 119 shots.
            cleaned = re.sub(r",\s*([\]}])", r"\1", raw)
            fixed = _repair_json_quotes(cleaned)
            try:
                data = orjson.loads(fixed)
            except Exception:
                dec = json.JSONDecoder()
                data = []
                i2 = 0
                while True:
                    b2 = fixed.find("{", i2)
                    if b2 < 0:
                        break
                    try:
                        obj, end2 = dec.raw_decode(fixed[b2:])
                        data.append(obj)
                        i2 = b2 + end2
                    except Exception:
                        i2 = b2 + 1
                if not data:
                    raise
                print(f"      [warn] storyboard JSON salvaged {len(data)} cells")
        board = {int(d.get("scene_index", offset + i)): d for i, d in enumerate(data)}
        return [board.get(offset + i, {}) for i in range(len(scenes))]
    except Exception as exc:
        print(f"      [warn] storyboard chunk @{offset} failed ({exc})")
        return None


def render_illustration(provider, model: str, out_png: Path, prompt: str, negative: str, resolution: tuple[int, int] | None = None) -> None:
    import asyncio

    res = resolution
    if res is None:
        res = (1024, 576) if model == "sdxl-turbo" else (512, 512)

    _aiorun(provider.generate(
        prompt,
        negative=negative,
        model=model,
        resolution=res,
        output_path=str(out_png.resolve()),
    ))


def _load_video_provider(provider_id: str):
    """Resolve a video provider (e.g. Flow/Veo) from the omnicast package."""
    src = ROOT / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from omnicast.media.providers.registry import get_video_provider

    return get_video_provider(provider_id)


def veo_motion_scene(
    veo_clip: Path, overlay_png: Path, audio: Path, dur: float,
    out_mp4: Path, avatar_mp4: Path | None = None,
    *, inset_frac: float = 0.42, margin: int = 80, fps: int = 30,
    in_offset: float = 0.0,
) -> None:
    """Compose a shot from a real Veo motion clip (looped/trimmed to the
    narration duration) + static text overlay (+ avatar inset). autovio-style:
    each shot is an actual moving video clip, not a panned still.

    in_offset: start the source clip N seconds in — adjacent shots that reuse
    one downloaded clip each start deeper so they don't play as a visible loop.
    """
    inputs = ["ffmpeg", "-y"]
    if in_offset > 0:
        inputs += ["-ss", f"{in_offset:.2f}"]
    inputs += [
        "-stream_loop", "-1", "-i", str(veo_clip),   # loop motion to fill dur
        "-i", str(audio),
        "-loop", "1", "-i", str(overlay_png),
    ]
    base = f"[0:v]scale={W}:{H},setsar=1,fps={fps}{(',' + GRADE) if GRADE else ''}[bg];"
    fd = 0.15
    fade = f"fade=t=in:st=0:d={fd},fade=t=out:st={max(0.0, dur - fd):.2f}:d={fd}"
    if avatar_mp4 is not None:
        inputs += ["-i", str(avatar_mp4)]
        av_h = int(H * inset_frac)
        filt = (
            base
            + "[bg][2:v]overlay=0:0[bt];"
            + f"[3:v]scale=-2:{av_h},setsar=1[av];"
            + f"[bt][av]overlay=W-w-{margin}:H-h-{margin},{fade}[v]"
        )
        amap = "3:a"
    else:
        filt = base + f"[bg][2:v]overlay=0:0,{fade}[v]"
        amap = "1:a"
    run(inputs + [
        "-filter_complex", filt,
        "-map", "[v]", "-map", amap,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{dur:.2f}", "-shortest",
        str(out_mp4),
    ])


def _load_avatar_provider(provider_id: str):
    """Resolve a talking-head provider from the omnicast package (src/)."""
    src = ROOT / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from omnicast.media.providers.registry import get_avatar_provider

    return get_avatar_provider(provider_id)


def probe_duration(mp4: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _probe_fps(mp4: Path) -> float:
    """Video frame rate (avg_frame_rate as float). 0.0 if unknown."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=avg_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
        capture_output=True, text=True,
    )
    try:
        num, _, den = out.stdout.strip().partition("/")
        den = den or "1"
        return round(float(num) / float(den), 3) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    global W, H
    ap = argparse.ArgumentParser(description="OmniCast — real offline video render")
    ap.add_argument("--shorts", action="store_true",
                    help="vertical 9:16 (1080x1920) output for Shorts/TikTok/Reels")
    ap.add_argument("--script", default=None, help="Path to script .txt (auto-picks best if omitted)")
    ap.add_argument("--out", default=str(ROOT / "output" / "real" / "final.mp4"))
    ap.add_argument("--max-scenes", type=int, default=None,
                    help="cap scene count (debug/preview only). Default: no cap — "
                         "the old default of 99 SILENTLY truncated long scripts "
                         "(a 135-scene 15-min video lost its third act + outro).")
    ap.add_argument("--voice", default="en-US-AndrewMultilingualNeural",
                    help="edge-tts voice — Multilingual neural voices are the most natural "
                         "(en-US-AndrewMultilingualNeural / AvaMultilingual / BrianMultilingual / EmmaMultilingual)")
    ap.add_argument("--voice-rate", default="+10%",
                    help="edge-tts speaking rate (energy): e.g. +10%% faster, default +10%%")
    ap.add_argument("--voice-pitch", default="+12Hz",
                    help="edge-tts pitch (liveliness): e.g. +12Hz higher, default +12Hz")
    ap.add_argument("--avatar", default=None,
                    help="talking-head provider id: 'sadtalker' (local) or 'comfyui-hunyuan' (remote)")
    ap.add_argument("--portrait", default=None,
                    help="portrait image of the speaking character (required if --avatar)")
    ap.add_argument("--images", default=None,
                    help="image provider id for illustration backgrounds: 'local-sd' or 'gemini'")
    ap.add_argument("--image-model", default="sd-turbo",
                    help="image model id (sd-turbo, sdxl-turbo, ...)")
    ap.add_argument("--beat-words", type=int, default=12,
                    help="split scenes into ~N-word shots (~4-5s each) for tight, "
                         "Vfacts-style footage↔line pacing — vfact benchmark is 3.66s/cut, "
                         "15+ shots/min; shorter = more cuts (0=off)")
    ap.add_argument("--motion", default="kenburns", choices=["kenburns", "veo"],
                    help="background motion: 'kenburns' (still+pan, free) or 'veo' (real Veo clips, costs credits)")
    ap.add_argument("--style", default="editorial", choices=list(STYLE_PREFIXES),
                    help="art style prepended to every image prompt (editorial | watercolor)")
    ap.add_argument("--subtitles", action="store_true",
                    help="bottom-centered subtitles (spoken line) instead of title card — for narration-only videos")
    ap.add_argument("--word-subs", dest="word_subs", action="store_true", default=None,
                    help="word-synced captions: transcribe the final audio with whisper and "
                         "time captions to the spoken word (auto-on when available + subtitles)")
    ap.add_argument("--no-word-subs", dest="word_subs", action="store_false",
                    help="force the old static per-shot caption instead of word-synced")
    ap.add_argument("--no-music", action="store_true",
                    help="disable background music (default: mix a mood-matched royalty-free track)")
    ap.add_argument("--music-mood", default="",
                    help="override BGM mood folder (cinematic|dramatic|ambient|corporate|uplifting|tense|calm|epic)")
    ap.add_argument("--music-volume", type=float, default=0.10,
                    help="BGM volume under narration (0.10 ≈ -20 dB, default)")
    ap.add_argument("--channel", default=None,
                    help="channel id (channels/<id>.json): applies that channel's style/voice/subtitle/pacing")
    ap.add_argument("--all-stock", dest="all_stock", action="store_true",
                    help="route EVERY scene through real stock video footage (yt-dlp/Pexels), "
                         "ignoring generated/web-image — for an all-footage documentary look")
    ap.add_argument("--overlay", default="html", choices=["html", "pillow"],
                    help="text/subtitle overlay renderer: 'html' (Playwright, gradient/frosted, default) "
                         "or 'pillow' (legacy flat). Auto-falls back to pillow if Playwright missing.")
    args = ap.parse_args()
    if args.shorts:
        W, H = 1080, 1920  # vertical canvas; all overlays/ken-burns use W,H

    # Per-channel style: a channel config supplies its own look. Explicit CLI
    # flags still override the channel defaults (argparse default sentinels).
    accent = [255, 209, 71]
    channel_meta: dict = {}
    voice_chain: list[str] = [f"edge:{args.voice}"]  # default; channel block refines
    if args.channel:
        import json as _json

        import channel_render
        cr = channel_render.resolve(args.channel)
        accent = cr.get("accent", accent)
        try:
            channel_meta = _json.loads(
                (ROOT / "channels" / f"{args.channel}.json").read_text(encoding="utf-8"))
        except Exception:
            channel_meta = {"name": cr.get("channel_name", args.channel)}
        print(f"[chan] {args.channel} -> style={cr['style']} voice={cr['voice']} "
              f"subtitle={cr['subtitle']} beat={cr['beat_words']} motion={cr['motion']}")
        if args.style == "editorial":
            args.style = cr["style"]
        _voice_was_default = (args.voice == "en-US-AndrewMultilingualNeural")
        if _voice_was_default:
            args.voice = cr["voice"]
        # Multi-source voice chain (provider:voice_id). Honors the channel's
        # voice_profile + voice_fallback (e.g. kokoro:af_heart → edge fallback);
        # an explicit --voice override pins a single edge voice. Always ends with
        # the channel_render edge mapping as a guaranteed last resort.
        try:
            from omnicast.media.voice_router import resolve_channel_voice
            if _voice_was_default:
                voice_chain = [str(s) for s in resolve_channel_voice(channel_meta)]
            else:
                # explicit --voice: accept a full 'provider:voice_id' spec
                # (e.g. 'kokoro:af_heart') or a bare edge voice id.
                voice_chain = [args.voice if ":" in args.voice else f"edge:{args.voice}"]
        except Exception as _vexc:
            print(f"[chan] voice chain resolve failed ({_vexc}); edge-only")
            voice_chain = [args.voice if ":" in args.voice else f"edge:{args.voice}"]
        _edge_fb = f"edge:{cr['voice']}"
        if _edge_fb not in voice_chain:
            voice_chain.append(_edge_fb)
        print(f"[chan] voice chain: {voice_chain}")
        # Per-channel voice energy override (channels/<id>.json: voice_rate/voice_pitch)
        if channel_meta.get("voice_rate"):
            args.voice_rate = str(channel_meta["voice_rate"])
        if channel_meta.get("voice_pitch"):
            args.voice_pitch = str(channel_meta["voice_pitch"])
        # Per-channel BGM level (horror channels run quieter beds — atmosphere
        # comes from room tone, not music). Explicit --music-volume still wins.
        if args.music_volume == 0.10 and channel_meta.get("music_volume"):
            args.music_volume = float(channel_meta["music_volume"])
        # Per-channel color grade on every shot (see GRADE_PRESETS).
        _vg = str(channel_meta.get("visual_grade")
                  or ("horror" if channel_meta.get("channel_style") == "horror_real" else "")
                  ).lower().strip()
        if _vg in GRADE_PRESETS:
            globals()["GRADE"] = GRADE_PRESETS[_vg]
            print(f"[chan] visual grade: {_vg}")
        if not args.subtitles:
            args.subtitles = cr["subtitle"]
        if args.beat_words == 12:  # still at default → channel preset wins
            args.beat_words = cr["beat_words"]
        if args.motion == "kenburns":
            args.motion = cr["motion"]

    style_prefix = STYLE_PREFIXES.get(args.style, STYLE_PREFIX)
    style_negative = f"{NEGATIVE_COMMON}, {STYLE_NEGATIVES.get(args.style, STYLE_NEGATIVES['editorial'])}"

    # PER-CHANNEL STYLE OVERRIDE — a channel that wants its OWN look (instead of
    # one of the shared preset wrappers) declares it in channels/<id>.json:
    #   "image_style_prompt":   "<prefix wrapped around every scene prompt>"
    #   "image_style_negative": "<optional negative terms>"
    #   "image_style_lock":     "<optional trailing style lock>"
    # Presets stay the default; overrides prevent multi-channel same-look drift.
    if channel_meta.get("image_style_prompt"):
        style_prefix = str(channel_meta["image_style_prompt"])
        if channel_meta.get("image_style_negative"):
            style_negative = f"{NEGATIVE_COMMON}, {channel_meta['image_style_negative']}"
        if channel_meta.get("image_style_lock"):
            STYLE_LOCK[args.style] = str(channel_meta["image_style_lock"])
        print(f"[chan] custom image style override active")

    # Word-synced captions: whisper transcribes the final audio and times captions
    # to the spoken word (vs. the old static per-shot line). Auto-on when whisper
    # is available and subtitles are requested; --no-word-subs forces static.
    import subtitle_sync
    word_subs = bool(args.subtitles) and subtitle_sync.available()
    if args.word_subs is False:
        word_subs = False
    elif args.word_subs is True and not subtitle_sync.available():
        print("[warn] --word-subs requested but whisper/ffmpeg unavailable; static captions.")
    # When word-subs are on we burn captions once on the final video, so skip the
    # static per-shot caption overlay (avoid double captions).
    if args.subtitles:
        overlay_fn = render_blank_overlay if word_subs else render_subtitle_overlay
    else:
        overlay_fn = render_text_overlay

    # HTML/CSS overlay (gradient title, frosted caption/subtitle card) — replaces
    # the flat Pillow text. Transparent PNG so Ken Burns/Veo still animate behind.
    # Falls back to the Pillow fn on any Playwright failure (missing browser etc),
    # so a render never breaks because of the cosmetic upgrade.
    use_html = args.overlay == "html" and html_overlay.available()
    if use_html and overlay_fn is not render_blank_overlay:
        import atexit
        atexit.register(html_overlay.close)
        _html_fn = (html_overlay.render_subtitle_overlay
                    if overlay_fn is render_subtitle_overlay
                    else html_overlay.render_text_overlay)
        _pillow_fn = overlay_fn
        _warned = {"v": False}

        def overlay_fn(sc, i, total, out_png):  # noqa: F811 (intentional drop-in swap)
            try:
                _html_fn(sc, i, total, out_png, W, H)
            except Exception as exc:
                if not _warned["v"]:
                    print(f"[warn] HTML overlay failed ({exc}); using Pillow.")
                    _warned["v"] = True
                _pillow_fn(sc, i, total, out_png)
    elif args.overlay == "html" and not html_overlay.available():
        print("[warn] --overlay html requested but Playwright not installed; using Pillow.")

    if args.avatar and not args.portrait:
        print("[ERROR] --avatar requires --portrait <character image>.")
        sys.exit(1)

    script_path = Path(args.script) if args.script else find_best_script()
    if not script_path or not script_path.exists():
        print("[ERROR] No script found. Run content_flow.py --phase 2 first.")
        sys.exit(1)

    print(f"[1/5] Script: {script_path}")
    # PROSODY SIDECAR: phase-2 writes script.json (full storyboard incl. per-scene
    # pace/pause_after_ms/emphasis) next to the prose script.txt. Prefer it —
    # prose loses all delivery direction (the "flat robot voice" gap).
    scenes: list[Scene] = []
    _sidecar = script_path.with_suffix(".json") if script_path.suffix != ".json" else script_path
    if _sidecar.exists():
        try:
            _sb = json.loads(_sidecar.read_text(encoding="utf-8"))
            _sc_list = _sb.get("scenes") if isinstance(_sb, dict) else _sb
            if isinstance(_sc_list, list) and _sc_list:
                scenes = _parse_json_script(json.dumps(_sc_list))
                if scenes:
                    print(f"      Storyboard sidecar: {_sidecar.name} "
                          f"({sum(1 for s in scenes if s.pace)} scenes with prosody)")
        except Exception as _se:
            print(f"      [warn] sidecar {_sidecar.name} unusable ({_se}); falling back to prose")
            scenes = []
    if not scenes:
        scenes = parse_script(script_path.read_text(encoding="utf-8"))
    if args.max_scenes:
        scenes = scenes[: args.max_scenes]
        print(f"      [warn] --max-scenes={args.max_scenes} TRUNCATES the script")
    print(f"      Parsed {len(scenes)} scenes")
    if args.beat_words > 0:
        scenes = split_into_shots(scenes, args.beat_words)
        print(f"      Fine sync: expanded to {len(scenes)} shots (~{args.beat_words} words each)")

    out = Path(args.out)
    work = out.parent / "_assets"
    work.mkdir(parents=True, exist_ok=True)

    # Live status for the HTML dashboard (output/real/_status/status.json).
    import render_status
    # Initial title = first scene heading (real content) instead of the script
    # filename; replaced by the generated clickbait title once it's ready.
    _init_title = (scenes[0].heading if scenes else script_path.stem) or script_path.stem
    status = render_status.StatusWriter(
        out.parent / "_status" / "status.json",
        channel=(args.channel or ""), title=_init_title,
    )
    status.init_shots([(i, sc.heading) for i, sc in enumerate(scenes)])
    status.stage("script", "done")
    status.log(f"{len(scenes)} shots, style={args.style}, motion={args.motion}")

    avatar_provider = _load_avatar_provider(args.avatar) if args.avatar else None
    veo_mode = args.motion == "veo"
    # In Veo mode the background is a generated video (no still images); the Flow
    # session is the VIDEO provider. Otherwise use the image provider.
    image_provider = None if veo_mode else (_load_image_provider(args.images) if args.images else None)

    # Channel-style: a storytelling channel is mostly generated illustrations, so
    # it needs an image provider even when --images was not passed. Explicit
    # --images / --all-stock / veo still win.
    if image_provider is None and not veo_mode and not args.all_stock:
        try:
            from omnicast.config.channel_styles import get_style_policy
            _sp = get_style_policy(channel_meta.get("channel_style"))
            if _sp and _sp.requires_image_provider:
                _pid = channel_meta.get("image_provider") or _sp.default_image_provider
                if _pid:
                    print(f"[chan] channel_style '{_sp.style_id}' needs images -> provider '{_pid}'")
                    image_provider = _load_image_provider(_pid)
        except Exception as e:
            print(f"[warn] channel_style image provider skipped: {e}")

    # Storyboard: one LLM pass builds continuity-aware, detailed per-scene prompts
    # (same world/style/characters). Falls back to the heuristic prompt per scene.
    img_prompts: list[str] = []
    img_negs: list[str] = []
    veo_prompts: list[str] = []
    # Character DNA: a channel mascot must stay face-consistent across every shot.
    # Resolve the channel's recurring character into a compact prompt block and
    # inject it into every image/video prompt (text anchor = layer-1 lock).
    dna_block = ""
    try:
        import character_dna
        character = character_dna.resolve_character(channel_meta)
        if character:
            dna_block = character_dna.build_dna_block(character)
            if dna_block:
                print(f"[1a/5] Character DNA locked: {character.get('name', '?')}")
    except Exception as e:
        print(f"[warn] character DNA skipped: {e}")

    bg_paths: dict[int, Path] = {}
    stock_paths: dict[int, Path] = {}  # scene_idx -> downloaded stock VIDEO clip
    # ANTI-DUP: fine-sync splits one scene into adjacent shots that share a
    # stock query — identical clips back-to-back read as a visible loop. Reuse
    # the downloaded file but start each repeat deeper into the clip.
    stock_offsets: dict[int, float] = {}   # scene_idx -> in-point seconds
    _stock_seen: dict[str, list] = {}      # query -> [Path, use_count]

    def _stock_reuse(i: int, q: str) -> bool:
        """Reuse an already-downloaded clip for a repeated query (offset in-point)."""
        ent = _stock_seen.get(q)
        if not ent or not ent[0].exists():
            return False
        stock_paths[i] = ent[0]
        stock_offsets[i] = ent[1] * 4.5
        ent[1] += 1
        print(f"[stock-video] scene {i}: reuse '{q}' (offset {stock_offsets[i]:.1f}s)")
        return True
    kinetic_paths: dict[int, Path] = {}  # scene_idx -> pre-rendered kinetic stat PNG

    board = None  # always defined; downstream guards on `if board`
    # Build the storyboard whenever the visual pipeline is board-driven: image gen,
    # veo motion, OR --all-stock (which still needs per-scene stock_query from it).
    if image_provider is not None or veo_mode or args.all_stock:
        print("[1a/5] Generating storyboard (continuity-aware prompts)...")
        status.stage("storyboard", "active"); status.log("storyboard LLM...")
        board = cached_storyboard(scenes, args.style, channel_meta)

        if not board:
            # One QUALITY-PRESERVING retry (fresh LLM call, temperature reroll)
            # before deciding anything — transient JSON breakage is common.
            print("      [retry] storyboard failed — one fresh attempt...")
            board = generate_storyboard(scenes, channel_meta)
        if not board:
            if STRICT:
                raise RuntimeError(
                    "Storyboard failed twice — STRICT mode refuses heading-derived "
                    "queries/text cards. Re-run, or set OMNICAST_STRICT=0 to allow "
                    "a degraded render.")
            if args.all_stock:
                print("      [warn] no storyboard — deriving stock queries from scene headings")
                board = [{} for _ in scenes]

        # Production mode router (strategic review §7): decide WHAT KIND of
        # visual each beat needs — chart, real evidence, reconstruction, screen
        # capture, hold — before the style policy decides where the picture
        # comes from. The two answer different questions and the order matters:
        # coercing a source first would hide the fact that a scene wanted a
        # chart at all.
        #
        # It only annotates and only overrides when it is confident, so a good
        # LLM storyboard is left alone; the value is the recorded decision and
        # the substitution log, not another coercion pass.
        if board:
            try:
                from omnicast.media.production_router import (
                    capabilities_from_channel,
                    route_storyboard,
                    summarise,
                )

                _scenes_for_router = [
                    {"narration": getattr(sc, "narration", "") or getattr(sc, "text", ""),
                     "visual": (board[i] or {}).get("image_prompt", ""),
                     "stock_query": (board[i] or {}).get("stock_query", "")}
                    for i, sc in enumerate(scenes) if i < len(board)
                ]
                _caps = capabilities_from_channel(
                    type("_C", (), {"supported_production":
                                    channel_meta.get("supported_production", [])})())
                # DEPICTS REAL EVENTS. Without this the disclosure branch was
                # dead code: the router defaulted to False and never marked a
                # single scene. A channel is non-fiction unless it says
                # otherwise — the safe default for a disclosure flag.
                _real = bool(channel_meta.get(
                    "depicts_real_events",
                    str(channel_meta.get("content_mode", "")).lower() != "fiction"))
                _routes = route_storyboard(_scenes_for_router, capabilities=_caps,
                                           depicts_real_events=_real)
                for _route in _routes:
                    _cell = board[_route.scene_index]
                    if not isinstance(_cell, dict):
                        continue
                    _cell["production_mode"] = _route.mode
                    _cell["production_mode_confidence"] = _route.confidence
                    if _route.approximation_gap:
                        _cell["production_mode_approximated"] = _route.approximation_gap
                    if _route.requires_disclosure:
                        _cell["requires_ai_disclosure"] = True
                    # OVERRIDE ONLY WHERE THE MODE IS REALLY PRODUCED THAT WAY.
                    # `INFOGRAPHIC -> generated_image` is an approximation, and
                    # the image providers warn they are poor at charts, numbers
                    # and text — so rewriting a considered storyboard cell into
                    # "AI picture of a chart" on a 0.75-confidence keyword match
                    # made the video worse while looking like a decision.
                    if (_route.confidence >= 0.75
                            and _route.is_rendered_as_itself
                            and _route.visual_type != "hold"):
                        _cell["visual_type"] = _route.visual_type
                _summary_extra = summarise(_routes)
                _summary = _summary_extra
                status.log(
                    f"production modes: {_summary['modes']} "
                    f"(substituted {_summary['substituted_count']}, "
                    f"approximated {_summary['approximated_count']}, "
                    f"defaulted {_summary['defaulted_count']})")
                for _appx in _summary["approximated"][:5]:
                    print(f"      [mode] scene {_appx['scene_index']}: "
                          f"{_appx['mode']} approximated — "
                          f"{_appx['approximation_gap']}")
                for _sub in _summary["substituted"][:5]:
                    print(f"      [mode] scene {_sub['scene_index']}: "
                          f"{_sub['fallback_reason']}")
            except Exception as e:
                print(f"[warn] production mode router skipped: {e}")

        # Channel-style policy: hard-coerce visual types the channel's style bans
        # (e.g. horror_real never shows AI art) BEFORE acquisition. The storyboard
        # directive already biased the LLM; this is the guarantee.
        if board:
            try:
                from omnicast.config.channel_styles import enforce_policy, get_style_policy
                _policy = get_style_policy(channel_meta.get("channel_style"))
                if _policy:
                    board = enforce_policy(board, [sc.heading for sc in scenes], _policy)
                    status.log(f"channel_style={_policy.style_id} policy enforced")
            except Exception as e:
                print(f"[warn] channel_style policy skipped: {e}")

        # Acquire per-scene visuals by type. Every branch falls back to a generated
        # image on failure so a fetch problem never breaks the render.
        if board:
            _IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            for i, cell in enumerate(board):
                visual_type = cell.get("visual_type", "generated_image")
                query = (cell.get("search_query") or "").strip()
                stock_query = (cell.get("stock_query") or "").strip()

                # Unfilmable kinetic-description text ('text popup: $70,000
                # filling screen, bold…') pulls random junk clips. It leaks in
                # from TWO directions: the LLM writes it as stock_query, AND the
                # writer's kinetic visual_prompt becomes the shot HEADING that
                # the fallback derivation below would otherwise pick up.
                _JUNK_Q = (r"text popup|filling screen|on screen|bold|kinetic|"
                           r"callout|animation|font|typography|graphic|overlay")

                def _filmable(*cands: str) -> str:
                    """First candidate that is non-empty and actually filmable."""
                    for c in cands:
                        c = (c or "").strip()
                        if c and not re.search(_JUNK_Q, c, re.I):
                            return c.lower()
                    return ""

                if stock_query and re.search(_JUNK_Q, stock_query, re.I):
                    _head = re.sub(r"[\[\]]", "", scenes[i].heading).strip()
                    _lbl = re.sub(r"[^a-zA-Z ]", " ",
                                  (cell.get("stat_label") or "")).strip()
                    stock_query = _filmable(_lbl, _head)
                    cell["stock_query"] = stock_query

                # ENFORCE: a stat scene MUST be real B-roll (stock_video) so the
                # plain white kinetic callout sits over footage — NOT a generated
                # cartoon that bakes the number into a chart/book (rule #1b). The
                # LLM sometimes ignores this, so force it here.
                if (cell.get("stat_number") or "").strip() and visual_type == "chart":
                    # A chart already draws its numbers — a kinetic callout on
                    # top would double-print them. The chart wins.
                    cell["stat_number"] = ""
                    cell["stat_label"] = ""
                elif (cell.get("stat_number") or "").strip() and visual_type != "stock_video":
                    visual_type = "stock_video"
                    cell["visual_type"] = "stock_video"
                    if not stock_query:
                        heading = re.sub(r"[\[\]]", "", scenes[i].heading).strip()
                        lbl = re.sub(r"\b(of|the|a|an|per|with|your|you|report|reports)\b", " ",
                                     re.sub(r"[^a-zA-Z ]", " ", (cell.get("stat_label") or "").lower())).strip()
                        # Label first (rule #1b: film the stat's SUBJECT), then a
                        # non-junk heading/search query; junk candidates skipped.
                        stock_query = _filmable(lbl, heading, query)
                        cell["stock_query"] = stock_query

                # --all-stock: force every scene to real footage. Derive a query
                # from stock_query > search_query > the scene heading keywords.
                if args.all_stock:
                    q = stock_query or query
                    if not q:
                        q = re.sub(r"[\[\]…]", "", scenes[i].heading).strip()
                    if _stock_reuse(i, q):
                        continue
                    vclip = work / f"scene_{i:02d}_stock.mp4"
                    print(f"[stock-video] (all-stock) scene {i}: '{q}' ...")
                    try:
                        ok = download_best_stock_video(q, vclip, W, H, max_seconds=15)
                    except Exception as e:
                        print(f"[stock-video] [warn] error scene {i}: {e}"); ok = False
                    if ok and vclip.exists() and vclip.stat().st_size > 0:
                        stock_paths[i] = vclip
                        _stock_seen[q] = [vclip, 1]
                    else:
                        print(f"[stock-video] [warn] failed scene {i}; will use text card.")
                    continue

                # --- Real data chart (chart_render channels; audited vs ledger) ---
                if visual_type == "chart":
                    _spec = cell.get("chart_spec") or {}
                    dest = work / f"scene_{i:02d}_chart.png"
                    _chart_ok = False
                    try:
                        _chart_ok = _render_chart_cell(_spec, dest, script_path, W, H)
                    except ChartAuditError as _ce:
                        # Fail-closed on purpose: a chart whose number the fact
                        # ledger never sourced must not ship in a YMYL video.
                        raise SystemExit(f"[chart] AUDIT BLOCK scene {i}: {_ce}")
                    except Exception as e:
                        print(f"[chart] [warn] error scene {i}: {e}")
                    if _chart_ok and dest.exists() and dest.stat().st_size > 0:
                        bg_paths[i] = dest
                        print(f"[chart] rendered scene {i}: "
                              f"'{str(_spec.get('title') or '')[:48]}'")
                        continue
                    # Never approximate a failed chart with an AI graph — fall
                    # back to real B-roll of the scene's subject instead.
                    _sq = _filmable(stock_query,
                                    re.sub(r"[\[\]]", "", scenes[i].heading))
                    if _sq:
                        vclip = work / f"scene_{i:02d}_stock.mp4"
                        print(f"[chart] [warn] chart failed scene {i}; stock fallback '{_sq}'")
                        try:
                            if download_best_stock_video(_sq, vclip, W, H, max_seconds=15) \
                                    and vclip.exists() and vclip.stat().st_size > 0:
                                stock_paths[i] = vclip
                                continue
                        except Exception as e:
                            print(f"[chart] [warn] stock fallback error scene {i}: {e}")
                    # Last resort is a generic illustration — scrub any chart
                    # wording so the image model is never asked to draw a graph.
                    if re.search(r"\b(chart|graph|diagram|infographic|bar|axis)\b",
                                 (cell.get("image_prompt") or ""), re.I):
                        cell["image_prompt"] = ""
                    cell["visual_type"] = "generated_image"
                    visual_type = "generated_image"

                # --- Real moving B-roll footage (preferred) ---
                if visual_type == "stock_video" and stock_query:
                    if _stock_reuse(i, stock_query):
                        continue
                    vclip = work / f"scene_{i:02d}_stock.mp4"
                    print(f"[stock-video] scene {i}: '{stock_query}' ...")
                    try:
                        ok = download_best_stock_video(stock_query, vclip, W, H, max_seconds=15)
                    except Exception as e:
                        print(f"[stock-video] [warn] error scene {i}: {e}")
                        ok = False
                    if ok and vclip.exists() and vclip.stat().st_size > 0:
                        stock_paths[i] = vclip
                        _stock_seen[stock_query] = [vclip, 1]
                        print(f"[stock-video] got clip scene {i}")
                        continue
                    print(f"[stock-video] [warn] failed scene {i}; falling back to generated image.")
                    cell["visual_type"] = "generated_image"

                # --- Live website / report / map screenshot (browser mockup) ---
                elif visual_type == "web_screenshot" and query:
                    dest = work / f"scene_{i:02d}_illu.png"
                    print(f"[web-shot] scene {i}: '{query[:50]}' ...")
                    try:
                        ok = capture_web_page(query, dest, W, H)
                    except Exception as e:
                        print(f"[web-shot] [warn] error scene {i}: {e}")
                        ok = False
                    if ok and dest.exists():
                        bg_paths[i] = dest
                        print(f"[web-shot] captured scene {i}")
                        continue
                    # Web screenshot failed/blank → prefer real B-roll over a
                    # garbled generated "study" image. Derive a stock query.
                    sq = (cell.get("stock_query") or "").strip()
                    if not sq:
                        sq = re.sub(r"[\[\]]", "", scenes[i].heading).strip() or "doctor research laboratory"
                    vclip = work / f"scene_{i:02d}_stock.mp4"
                    print(f"[web-shot] [warn] failed scene {i}; falling back to stock '{sq}'")
                    try:
                        if download_best_stock_video(sq, vclip, W, H, max_seconds=15) and vclip.exists() and vclip.stat().st_size > 0:
                            stock_paths[i] = vclip
                            continue
                    except Exception as e:
                        print(f"[web-shot] [warn] stock fallback error scene {i}: {e}")
                    cell["visual_type"] = "generated_image"

                # --- Real still image from web search ---
                elif visual_type == "web_search_image" and query:
                    dest = work / f"scene_{i:02d}_illu.png"
                    cp = _web_cache_path(query, W, H)
                    if _cache_hit(cp):
                        try:
                            print(f"[web-search] Cache hit for scene {i}: '{query}'")
                            shutil.copyfile(cp, dest)
                            bg_paths[i] = dest
                            continue
                        except Exception:
                            pass
                    print(f"[web-search] Searching web for scene {i}: '{query}'...")
                    if download_best_web_image(query, dest, W, H):
                        try:
                            shutil.copyfile(dest, cp)
                        except Exception:
                            pass
                        bg_paths[i] = dest
                        print(f"[web-search] Downloaded web image for scene {i}")
                    else:
                        print(f"[web-search] [warn] failed scene {i}; falling back to generated image.")
                        cell["visual_type"] = "generated_image"

        # STRICT: in all-stock mode every scene must have REAL footage — a text
        # card is a quality downgrade, not an acceptable output. Fail with the
        # exact scene list so the operator can fix queries/quota and re-run.
        if STRICT and args.all_stock:
            _missing = [i for i in range(len(scenes)) if i not in stock_paths]
            if _missing:
                _qs = []
                for _mi in _missing[:6]:
                    _c = board[_mi] if (board and _mi < len(board)) else {}
                    _qs.append(f"scene {_mi}: '{(_c.get('stock_query') or _c.get('search_query') or scenes[_mi].heading)[:60]}'")
                raise RuntimeError(
                    f"Stock footage missing for {len(_missing)}/{len(scenes)} scenes — "
                    "STRICT mode refuses text cards. Failing queries: " + "; ".join(_qs))

        # Build prompts for the remaining generated images
        for i, sc in enumerate(scenes):
            cell = board[i] if board else {}
            core = (cell.get("image_prompt") or "").strip()
            motion = (cell.get("video_prompt") or "").strip()
            img = f"{style_prefix}, {core}" if core else build_illustration_prompt(sc, style_prefix)
            if dna_block:
                img = f"{img}. {dna_block}"
            # Re-assert the medium at the END (trailing tokens dominate) so every
            # shot lands in the same style instead of drifting to photoreal.
            lock = STYLE_LOCK.get(args.style, STYLE_LOCK["editorial"])
            img = f"{img}. {lock}"
            img_prompts.append(img)
            # Union the LLM's per-scene negatives with the defaults — never let the
            # LLM drop the photoreal/grid bans that keep the set consistent.
            scene_neg = (cell.get("negative_prompt") or "").strip()
            img_negs.append(f"{scene_neg}, {style_negative}" if scene_neg else style_negative)
            base = core or re.sub(r"[\[\]]", "", sc.heading)
            vp = f"{base}. {motion}. cinematic" if motion else f"{base}. cinematic"
            if dna_block:
                vp = f"{vp}. {dna_block}"
            veo_prompts.append(vp)

    # Scenes whose visual came from the web/stock acquisition above — these are
    # NOT generated art, so the mascot-consistency check below must skip them.
    _web_bg = set(bg_paths)

    # Batch illustration pre-generation: providers that render concurrently
    # (e.g. Flow) implement generate_batch — fire all prompts at once instead of
    # waiting per scene. Falls back to per-scene render_illustration otherwise.
    if image_provider is not None and hasattr(image_provider, "generate_batch"):
        import asyncio
        _IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        outs = [work / f"scene_{i:02d}_illu.png" for i in range(len(scenes))]
        cpaths = [_img_cache_path(img_prompts[i], args.image_model, W, H)
                  for i in range(len(scenes))]
        miss = [i for i in range(len(scenes)) if i not in bg_paths and i not in stock_paths and not _cache_hit(cpaths[i])]
        hits = (len(scenes) - len(bg_paths) - len(stock_paths)) - len(miss)
        print(f"[1b/5] Image cache: {hits} hit / {len(miss)} to generate "
              f"(saved {hits} Flow generations, skipped {len(bg_paths)} web search images)")
        status.stage("images", "active")
        status.log(f"cache {hits} hit / {len(miss)} gen")
        # Restore cached shots without spending any quota.
        for i in range(len(scenes)):
            if i in bg_paths or i in stock_paths:
                continue
            if _cache_hit(cpaths[i]):
                try:
                    shutil.copyfile(cpaths[i], outs[i])
                    bg_paths[i] = outs[i]
                except Exception:
                    miss.append(i)  # cache copy failed -> regenerate
        # Generate only the misses, then persist them to the cache. Persist in a
        # `finally` so that if the provider aborts mid-batch (e.g. Flow anti-abuse
        # block), every wave that DID complete is still cached — the next run
        # resumes from there instead of re-spending quota on those shots.
        if miss:
            miss = sorted(set(miss))
            try:
                _aiorun(image_provider.generate_batch(
                    [img_prompts[i] for i in miss],
                    [str(outs[i].resolve()) for i in miss],
                    resolution=(W, H),
                ))
            finally:
                saved = 0
                for i in miss:
                    if _cache_hit(outs[i]) and not _cache_hit(cpaths[i]):
                        try:
                            shutil.copyfile(outs[i], cpaths[i])
                            saved += 1
                        except Exception:
                            pass
                if saved:
                    print(f"[1b/5] Cached {saved} completed shots (resume-safe)")
        for i in range(len(scenes)):
            if i not in bg_paths and i not in stock_paths and outs[i].exists():
                bg_paths[i] = outs[i]
        for i in range(len(scenes)):
            status.shot(i, illu=f"_assets/scene_{i:02d}_illu.png", state="active")
        status.stage("images", "done")

    total = len(scenes)
    total_words = sum(len(sc.narration.split()) for sc in scenes)

    # Veo motion phase (real moving clips). Serial — single Flow browser, each
    # Veo clip takes minutes. Credit preflight aborts BEFORE spending if the
    # balance can't cover the run; a live re-check after clip #1 measures the
    # true per-clip cost and bails early if the remainder won't fit.
    veo_paths: dict[int, Path] = {}
    if veo_mode:
        import asyncio
        vprov = _load_video_provider("flow")
        info = _aiorun(vprov.preflight_video(total))
        bal0 = info["balance"]
        status.credits(info); status.stage("images", "active")
        print(f"[1b/5] Credits balance={bal0} est_need={info['needed']} "
              f"({total}x{info['cost_per_clip']}); generating {total} Veo clips (serial)...")
        for i in range(total):
            vclip = work / f"scene_{i:02d}_veo.mp4"
            _aiorun(vprov.convert("", veo_prompts[i],
                                      output_path=str(vclip.resolve()), wait_s=600))
            veo_paths[i] = vclip
            status.shot(i, state="active"); status.log(f"Veo clip {i+1}/{total}")
            if i == 0 and bal0:
                bal1 = _aiorun(vprov.credits())
                if bal1 is not None:
                    real = max(1, bal0 - bal1)
                    need = (total - 1) * real
                    print(f"      measured cost/clip={real}; balance={bal1}; remaining_need={need}")
                    if bal1 < need:
                        vprov.close()
                        print(f"[ABORT] Insufficient credits for remaining {total-1} clips "
                              f"(need {need}, have {bal1}). Partial clips kept.")
                        sys.exit(2)
            print(f"[1b/5] Veo clip {i+1}/{total} done")
        vprov.close()

    # Ensure a background image exists per shot. Batch providers (Flow) already
    # filled bg_paths above; a non-batch provider (local-sd) is NOT thread-safe,
    # so generate those serially here before the parallel compose phase.
    if image_provider is not None:
        _IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for i in range(total):
            if i in bg_paths or i in stock_paths:
                continue
            bg = work / f"scene_{i:02d}_illu.png"
            cp = _img_cache_path(img_prompts[i], args.image_model, W, H)
            if _cache_hit(cp):
                try:
                    shutil.copyfile(cp, bg)
                    bg_paths[i] = bg
                    continue
                except Exception:
                    pass
            try:
                render_illustration(image_provider, args.image_model, bg, img_prompts[i], img_negs[i], resolution=(W, H))
            except Exception as _ie:
                # Image gen failure (broken model cache, OOM, etc) must NOT kill the
                # whole render — leave this scene without a bg; compose falls back
                # to a text card for it.
                print(f"[1b/5] [warn] image gen failed scene {i}: {str(_ie)[:80]}")
                continue
            if _cache_hit(bg):
                try:
                    shutil.copyfile(bg, cp)
                except Exception:
                    pass
            bg_paths[i] = bg

    # Character consistency QA (Orkas stage-consistency pattern): verify the
    # GENERATED stills against the mascot DNA and re-roll drifted shots —
    # catching identity drift at the still is far cheaper than after compose/
    # animate. Web/stock visuals are skipped (not the mascot). Drifted shots
    # that survive a re-roll are kept and surfaced, never a hard fail.
    # Kill-switch: OMNICAST_CONSISTENCY=0.
    if (dna_block and image_provider is not None
            and os.environ.get("OMNICAST_CONSISTENCY", "1") != "0"):
        try:
            import consistency_check
            _gen_imgs = {i: bg_paths[i] for i in bg_paths if i not in _web_bg}
            if _gen_imgs:
                def _regen(i: int, path: Path) -> bool:
                    render_illustration(image_provider, args.image_model, path,
                                        img_prompts[i], img_negs[i],
                                        resolution=(W, H))
                    if not _cache_hit(path):
                        return False
                    try:  # refresh the prompt-cache so resume keeps the fix
                        shutil.copyfile(path, _img_cache_path(
                            img_prompts[i], args.image_model, W, H))
                    except Exception:
                        pass
                    return True

                status.log("consistency check (mascot identity)...")
                _crep = consistency_check.verify_scenes(
                    _gen_imgs, dna_block, regen=_regen)
                if _crep["checked"] or _crep["unverified"]:
                    print(f"[1c/5] Consistency: {_crep['passed']}/{_crep['checked']} ok, "
                          f"re-rolled {len(_crep['rerolled'])}, "
                          f"drifted {len(_crep['drifted'])}, "
                          f"unverified {len(_crep['unverified'])}")
                    status.log(
                        f"consistency {_crep['passed']}/{_crep['checked']} ok"
                        + (f", drifted {len(_crep['drifted'])}"
                           if _crep["drifted"] else ""))
        except Exception as e:
            print(f"[warn] consistency check skipped: {e}")

    # IMAGE PHASE DONE → close the Flow browser + release its cross-process lock
    # NOW (before TTS/compose), so a concurrent render can grab Flow while this
    # one does CPU-bound TTS/compose. This is what makes a batch pipeline instead
    # of serialize. No-op for providers without a session.
    if image_provider is not None:
        try:
            _s = getattr(image_provider, "_session", None)
            if _s is not None and hasattr(_s, "close"):
                _s.close()
                image_provider._session = None  # thumb gen re-opens Flow later
                print("[1d/5] Flow released (image phase done) — CPU stages free to overlap")
        except Exception as _ce:
            print(f"[warn] flow release skipped: {_ce}")

    # Route the spoken outro/CTA scenes (comment → subscribe → next) onto the
    # OutroCTA end-card so the whole closing plays over one clean YouTube-end-screen
    # layout (Gemini "2-in-1") instead of random b-roll — single, no drift, hard end.
    if board:
        # Match CTA either by what's SPOKEN (narration) or by the intended VISUAL
        # (a "subscribe button" / "comment section" / "like button" b-roll graphic).
        # Keying on narration alone let a subscribe-button stock scene slip through
        # between OutroCTA cards → a second subscribe on screen. Catch both.
        _cta_re = re.compile(r"\b(subscribe|comment|drop (it|yours|your)|next up|next:|"
                             r"pinned in the comments|see you (there|next)|hit like|"
                             r"tell me below|tell me in the comments|let me know below|"
                             r"which (one )?surprised you)\b", re.I)
        _cta_vis_re = re.compile(r"subscribe|comment section|like button|notification bell|"
                                 r"end screen|end card|channel page", re.I)
        _acc = channel_meta.get("brand_color_hex") or "#38bdf8"
        # Scan the whole outro tail (CTA outros span several scenes once split by
        # beat_words). Only CTA scenes are converted, so body scenes are untouched.
        _tail = max(0, len(board) - 10)
        # The outro is one contiguous block at the very end. Find the FIRST CTA shot
        # in the tail (a comment/subscribe/next line, or a CTA-graphic visual), then
        # route THAT shot and EVERY shot after it onto the OutroCTA card — so split
        # continuation shots (e.g. the tail of the "Next: …" sentence with no CTA
        # keyword) don't fall back to b-roll between/after cards.
        _outro_start = None
        for _i in range(_tail, len(board)):
            cell_i = board[_i] if _i < len(board) else None
            if cell_i is None or (cell_i.get("stat_number") or "").strip():
                continue
            _nar = scenes[_i].narration if _i < len(scenes) else ""
            _vis = " ".join((cell_i.get(k) or "") for k in ("stock_query", "search_query", "image_prompt"))
            if _cta_re.search(_nar) or _cta_vis_re.search(_vis):
                _outro_start = _i
                break
        if _outro_start is not None:
            for _i in range(_outro_start, len(board)):
                cell_i = board[_i] if _i < len(board) else None
                if cell_i is None or (cell_i.get("stat_number") or "").strip():
                    continue
                cell_i["template"] = "remotion:OutroCTA"
                cell_i["remotion_props"] = {"sub": "", "accent": _acc, "bg": "#0a0f1a"}

    # Pre-render kinetic stat callouts on the MAIN thread (Playwright sync is
    # thread-affine — cannot run inside the parallel compose workers below).
    # A "shock-scale" number (millions/billions/trillions or % / many digits) is
    # rendered HERO: a giant centered figure over a dim scrim (full-screen moment),
    # vs the restrained bottom-left inline callout for ordinary stats.
    _hero_re = re.compile(r"\b(million|billion|trillion)\b|\d[\d.,]{6,}|\d+\s?%", re.I)
    if board:
        for i in range(total):
            cell = board[i] if i < len(board) else {}
            number = (cell.get("stat_number") or "").strip()
            if not number:
                continue
            label = (cell.get("stat_label") or "").strip()
            _hero = bool(_hero_re.search(number + " " + label))
            spng = work / f"scene_{i:02d}_stat.png"
            try:
                if render_kinetic_stat(number, label, spng, W, H, hero=_hero) and spng.exists():
                    kinetic_paths[i] = spng
            except Exception as e:
                print(f"[kinetic] [warn] pre-render scene {i}: {e}")

    # Variable speaking rate per section (learned from high-retention essays:
    # SLOW dramatic hook -> FAST info-dense body -> faster number climax -> SLOW
    # outro). Role priority: hook > outro > climax > body. climax = number-dense
    # scenes (a stat cell, or large numbers / scale words in the narration).
    _num_re = re.compile(r"\d{3,}|\d+([.,]\d+)?\s?%|\b\d+x\b|"
                         r"\b(billion|million|trillion|thousand|percent|times)\b", re.I)

    def _base_rate_pct() -> int:
        m = re.search(r"-?\d+", args.voice_rate or "+0%")
        return int(m.group()) if m else 0

    def _scene_rate(i: int) -> str:
        # 1) Script-directed prosody wins (Writer sets pace per scene role —
        #    vfact benchmark: hook/outro ≥25% slower than body, climax faster).
        _pace = getattr(scenes[i], "pace", "") if i < len(scenes) else ""
        if _pace == "slow":
            return f"{_base_rate_pct() - 15:+d}%"
        if _pace == "fast":
            return f"{_base_rate_pct() + 12:+d}%"
        if _pace == "normal":
            return args.voice_rate
        # 2) No script direction → legacy heuristics.
        if i <= 1:
            return "-12%"                       # greeting + hook: lean in, weighty
        cell = board[i] if (board and i < len(board)) else None
        if cell is not None and cell.get("template") == "remotion:OutroCTA":
            return "-8%"                        # outro/CTA: slow, deliberate close
        _nar = scenes[i].narration if i < len(scenes) else ""
        if (cell is not None and (cell.get("stat_number") or "").strip()) or _num_re.search(_nar):
            return "+8%"                        # climax: dense numbers, push energy
        return args.voice_rate                  # body: channel default

    # Companion pitch lift on number/climax scenes (edge-tts can't do per-word SSML
    # pitch, so we raise the whole line a few Hz to mimic the "spike on the big
    # number" energy of high-retention narration). Hook/outro keep the base pitch.
    def _base_pitch_hz() -> int:
        m = re.search(r"-?\d+", args.voice_pitch or "+0Hz")
        return int(m.group()) if m else 0

    def _scene_pitch(i: int) -> str:
        # Script-directed emphasis → pitch lift (vfact spikes pitch on key words;
        # edge-tts has no per-word SSML so the whole line gets the lift).
        # GUARD: models tend to put emphasis on EVERY scene (run 2026-07-08:
        # 65/65) — lifting everything kills contrast. Lift only when the scene
        # actually carries a number/stat (the vfact spike moments).
        if i < len(scenes) and getattr(scenes[i], "emphasis", ()):
            _n = scenes[i].narration
            if _num_re.search(_n) or any(any(ch.isdigit() for ch in e)
                                         for e in scenes[i].emphasis):
                return f"{_base_pitch_hz() + 8:+d}Hz"
        if i <= 1:
            return args.voice_pitch
        cell = board[i] if (board and i < len(board)) else None
        if cell is not None and cell.get("template") == "remotion:OutroCTA":
            return args.voice_pitch
        _nar = scenes[i].narration if i < len(scenes) else ""
        if (cell is not None and (cell.get("stat_number") or "").strip()) or _num_re.search(_nar):
            return f"{_base_pitch_hz() + 8:+d}Hz"
        return args.voice_pitch

    # Dramatic beat: hold ~1s of silence BEFORE a chapter/rhetorical question so it
    # lands (reference uses a ~2s pause before its big chapter question). We shift
    # the scene's word timings by the same lead so captions stay perfectly synced.
    def _lead_silence(i: int) -> float:
        if i <= 1:
            return 0.0
        cell = board[i] if (board and i < len(board)) else None
        if cell is not None and cell.get("template") == "remotion:OutroCTA":
            return 0.0
        nar = (scenes[i].narration if i < len(scenes) else "").strip()
        if nar.endswith("?") and 4 <= len(nar.split()) <= 16:
            return 1.0
        return 0.0

    def _scene_motion(i: int) -> int:
        # vfact zoom marker: punch a centered ZOOM-IN on the number/twist so the
        # motion emphasizes it (reference zooms hard on data/reveals); other shots
        # keep cycling the 6 ken-burns moves. Ties the zoom to the same stat/twist
        # markers the Writer emits: a stat cell, a hero number, an emphasis word,
        # or a deliberate dramatic pause.
        sc = scenes[i] if i < len(scenes) else None
        cell = board[i] if (board and i < len(board)) else {}
        has_stat = bool((cell.get("stat_number") or "").strip()) or bool(
            _num_re.search(sc.narration if sc else ""))
        has_emph = bool(getattr(sc, "emphasis", ())) if sc else False
        is_twist = ((getattr(sc, "pause_after_ms", 0) or 0) >= 400) if sc else False
        return 0 if (has_stat or has_emph or is_twist) else i

    def _compose(i: int) -> Path:
        sc = scenes[i]
        png = work / f"scene_{i:02d}.png"
        audio = work / f"scene_{i:02d}.mp3"
        clip = work / f"scene_{i:02d}.mp4"
        # Section-aware delivery via VOICE (see _scene_rate): slow weighty hook,
        # body at pace, faster on number climaxes, slow deliberate outro.
        _rate = _scene_rate(i)
        dur = render_voice(sc.narration, audio, voice_chain,
                           rate=_rate, pitch=_scene_pitch(i),
                           clone_path=channel_meta.get("voice_clone_ref"))

        _lead = _lead_silence(i)
        if _lead > 0:
            _padded = work / f"scene_{i:02d}_pad.mp3"
            run(["ffmpeg", "-y", "-i", str(audio), "-af",
                 f"adelay={int(_lead*1000)}:all=1", "-c:a", "libmp3lame", "-q:a", "2",
                 str(_padded)])
            if _padded.exists() and _padded.stat().st_size > 0:
                audio = _padded
                dur += _lead
                _wf = work / f"scene_{i:02d}.words.json"
                if _wf.exists():
                    try:
                        _ws = json.loads(_wf.read_text(encoding="utf-8"))
                        for _w in _ws:
                            _w["start"] += _lead
                            _w["end"] += _lead
                        _wf.write_text(json.dumps(_ws), encoding="utf-8")
                    except Exception:
                        pass

        # Script-directed dramatic pause AFTER this scene (vfact: breaths are cut,
        # every pause is intentional — 400-1500ms beats at twists/chapter turns).
        _tail_ms = int(getattr(sc, "pause_after_ms", 0) or 0)
        if _tail_ms > 0:
            _tailp = work / f"scene_{i:02d}_tail.mp3"
            run(["ffmpeg", "-y", "-i", str(audio), "-af",
                 f"apad=pad_dur={_tail_ms/1000:.3f}", "-c:a", "libmp3lame", "-q:a", "2",
                 str(_tailp)])
            if _tailp.exists() and _tailp.stat().st_size > 0:
                audio = _tailp
                dur += _tail_ms / 1000.0

        talk = None
        if avatar_provider is not None:
            import asyncio
            talk = work / f"scene_{i:02d}_avatar.mp4"
            _aiorun(avatar_provider.animate(
                str(Path(args.portrait).resolve()),
                str(audio.resolve()),
                output_path=str(talk.resolve()),
            ))

        clip_dur = probe_duration(talk) if talk else dur
        cell = board[i] if (board and i < len(board)) else {}

        # ── Remotion animated scene (additive template) ──────────────────────
        # A cell may opt into a React/Remotion composition (intro, count-up stat,
        # outro CTA) instead of the ffmpeg ken-burns/stock path. Falls back to the
        # normal pipeline if Remotion isn't installed or the render fails.
        _tmpl = (cell.get("template") or "").strip()
        if _tmpl.startswith("remotion:"):
            try:
                import remotion_render
                if remotion_render.available():
                    comp = _tmpl.split(":", 1)[1]
                    rprops = dict(cell.get("remotion_props") or {})
                    rvid = work / f"scene_{i:02d}_remotion.mp4"
                    if remotion_render.render_scene(comp, rprops, rvid, clip_dur, W, H):
                        run(["ffmpeg", "-y", "-i", str(rvid), "-i", str(audio),
                             "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                             "-shortest", str(clip)])
                        status.shot(i, state="done")
                        print(f"[2/5] Shot {i+1}/{total}  [remotion:{comp}]  {dur:5.1f}s")
                        return clip
                    print(f"[remotion] [warn] scene {i} render failed; ffmpeg fallback")
            except Exception as _rexc:
                print(f"[remotion] [warn] scene {i} fell back: {_rexc}")

        def _build_overlay() -> Path:
            ov = work / f"scene_{i:02d}_text.png"
            overlay_fn(sc, i, total, ov)
            # Kinetic stat is NOT baked here anymore — it is composited later as a
            # TIMED overlay (_overlay_timed_kinetics) so it pops only when the number
            # is actually spoken (Vfacts style), not for the whole scene.
            return ov

        sclip = stock_paths.get(i)
        vbg = veo_paths.get(i)
        bg = bg_paths.get(i)
        if sclip is not None and sclip.exists():
            # Real B-roll footage looped/trimmed to narration duration (reuses the
            # Veo compositor: stream_loop + overlay + narration audio).
            overlay = _build_overlay()
            veo_motion_scene(sclip, overlay, audio, clip_dur, clip, avatar_mp4=talk,
                             in_offset=stock_offsets.get(i, 0.0))
        elif vbg is not None and vbg.exists():
            overlay = _build_overlay()
            veo_motion_scene(vbg, overlay, audio, clip_dur, clip, avatar_mp4=talk)
        elif bg is not None and bg.exists():
            overlay = _build_overlay()
            ken_burns_scene(bg, overlay, audio, clip_dur, clip, _scene_motion(i), avatar_mp4=talk)
        else:
            # No visual for this scene — usually a generated image Google's safety
            # filter refused (dark/figure prompts trip it). A plain text card among
            # photoreal footage looks broken, so for a real-look channel try one
            # dark atmosphere STOCK clip first (on-brand, always available), and
            # only fall to a text card if even that fails.
            _rescued = False
            if GRADE and talk is None:  # GRADE set => real-look channel (horror grade)
                _rq = re.sub(r"[\[\]…]", "", (sc.heading or sc.narration or "")).strip()
                _rq = " ".join(_rq.split()[:4]).lower() or "dark empty hallway night"
                _rclip = work / f"scene_{i:02d}_rescue.mp4"
                try:
                    print(f"[rescue] scene {i}: policy/miss → dark stock '{_rq}'")
                    if download_best_stock_video(_rq, _rclip, W, H, max_seconds=15) \
                            and _rclip.exists() and _rclip.stat().st_size > 0:
                        overlay = _build_overlay()
                        veo_motion_scene(_rclip, overlay, audio, clip_dur, clip)
                        _rescued = True
                except Exception as _re2:
                    print(f"[rescue] [warn] scene {i} stock rescue failed: {_re2}")
            if not _rescued:
                render_card(sc, i, total, png, bg_image=None)
                if talk is not None:
                    avatar_over_background(png, talk, clip)
                else:
                    scene_to_mp4(png, audio, dur, clip)
        status.shot(i, state="done")
        print(f"[2/5] Shot {i+1}/{total}  '{sc.heading[:36]}'  {dur:5.1f}s")
        return clip

    # Parallel compose: tts + avatar + Ken Burns are independent per shot.
    # ffmpeg runs as a subprocess (true parallelism); cap workers to avoid
    # oversubscribing CPU since each ffmpeg is itself multi-threaded.
    import concurrent.futures
    workers = max(2, min(6, (os.cpu_count() or 4) // 2))
    print(f"[2/5] Composing {total} shots ({workers} parallel)...")
    status.stage("compose", "active"); status.log(f"composing {total} shots ({workers} parallel)")
    clips: list[Path] = [Path()] * total
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_compose, i): i for i in range(total)}
        for fut in concurrent.futures.as_completed(futs):
            clips[futs[fut]] = fut.result()

    print(f"[3/5] Concatenating {len(clips)} clips ...")
    status.stage("concat", "active"); status.log("concatenating clips")
    concat_scenes(clips, out, work)

    # Background music: pick a royalty-free track matched to the channel's niche/
    # mood and mix it well under the narration. Reusable library at assets/music/
    # <mood>/. No-op if disabled or no tracks present. Done before captions so the
    # subtitle re-encode (audio copy) preserves the music.
    if not args.no_music:
        try:
            import music_lib
            mood = args.music_mood or (channel_meta.get("music_mood", "") if channel_meta else "")
            niche = (channel_meta.get("niche", "") if channel_meta else "")
            used = music_lib.apply_to_video(
                out, niche=niche, style=args.style, mood=mood,
                channel_id=(args.channel or ""), volume=args.music_volume)
            if used:
                status.log(f"bgm: {used}")
                print(f"[3-/5] Background music mixed: {used}")
            elif STRICT:
                raise RuntimeError(
                    "BGM missing (no track / mix failed / target locked) — a "
                    "silent video is a quality downgrade. Close any player "
                    "holding video.mp4, check assets/music/, and re-run.")
            else:
                print("[3-/5] No background music (assets/music/ empty) — skipped.")
        except Exception as e:
            if STRICT:
                raise
            print(f"[warn] bgm mix skipped: {e}")

    # Word-synced captions. Prefer the EXACT edge-tts word timings (sidecar
    # scene_NN.words.json) offset by each scene's position — perfect text + sync,
    # no whisper guesswork. Fall back to whisper transcription if timings missing.
    if word_subs:
        status.stage("subtitle", "active")
        acc = tuple(accent[:3]) if accent else None
        ok_sub = False
        try:
            words_all: list[dict] = []
            t_acc = 0.0
            for i in range(total):
                wf = work / f"scene_{i:02d}.words.json"
                clip_i = clips[i] if i < len(clips) else None
                cd = probe_duration(clip_i) if clip_i and clip_i.exists() else 0.0
                if wf.exists():
                    try:
                        for w in json.loads(wf.read_text(encoding="utf-8")):
                            words_all.append({
                                "start": w["start"] + t_acc,
                                "end": w["end"] + t_acc,
                                "text": w.get("text", ""),
                            })
                    except Exception:
                        pass
                t_acc += cd
            # PROPORTIONAL timings (kokoro/piper have no word boundaries) DRIFT
            # inside every scene — captions lag/lead the voice ("thiếu chữ").
            # If most words are approx, skip them and force whisper alignment
            # on the REAL final audio.
            _n_approx = sum(1 for w in words_all if w.get("approx"))
            if words_all and _n_approx > len(words_all) // 2:
                if not subtitle_sync.available():
                    raise RuntimeError(
                        "Captions need whisper alignment (voice has no word "
                        "boundaries — proportional timings drift) but "
                        "faster-whisper is not installed in the venv. "
                        "pip install faster-whisper, then re-run.")
                print(f"[3a/5] {_n_approx}/{len(words_all)} word timings are "
                      "approximations — using whisper alignment instead.")
                words_all = []
            if words_all:
                status.log("word-synced captions (edge timings)...")
                print(f"[3a/5] Word-synced captions (edge timings, {len(words_all)} words)...")
                ok_sub = subtitle_sync.apply_words(
                    out, work, words_all, width=W, height=H, accent=acc, channel_meta=channel_meta)
        except Exception as e:
            if STRICT:
                raise
            print(f"[warn] edge-timing captions failed ({e}); trying whisper...")
        try:
            if not ok_sub:
                status.log("word-synced captions (whisper)...")
                print("[3a/5] Word-synced captions (whisper transcribe + burn)...")
                ok_sub = subtitle_sync.apply_to_video(out, work, width=W, height=H, accent=acc, channel_meta=channel_meta)
            if not ok_sub and STRICT and bool(args.subtitles):
                raise RuntimeError("Captions failed to burn — STRICT mode refuses "
                                   "to ship a captionless video when subtitles are on")
            status.log("captions burned" if ok_sub else "captions skipped (empty/transcribe)")
            status.stage("subtitle", "done")
        except Exception as e:
            if STRICT:
                raise
            print(f"[warn] word-sub burn skipped: {e}")
            status.stage("subtitle", "done")

    # Word-synced kinetic stat callouts — applied LAST (after bgm + captions) so no
    # later re-encode can drop them. Each stat pops only when its number is spoken
    # (~1.8s), Vfacts style. Uses the same scene word timings as the captions.
    try:
        _overlay_timed_kinetics(out, work, kinetic_paths, clips, board)
    except Exception as e:
        print(f"[kinetic] [warn] timed kinetics skipped: {e}")

    # SFX must be mixed BEFORE the story-beat splice: the splice inserts card time
    # into the timeline, so any cue placed afterward (by original clip timing) would
    # drift. Mixing SFX into the audio first means the splice carries each cue along
    # with its own video part, keeping it aligned.

    # Subtle SFX polish (whoosh at section changes, ting on hero numbers) — additive.
    _sfx_style = str(channel_meta.get("sfx_style") or "full")
    try:
        _mix_sfx(out, work, clips, board, scenes, sfx_style=_sfx_style)
    except Exception as e:
        print(f"[sfx] [warn] sfx skipped: {e}")

    # Event-matched diegetic SFX (horror): thunder/brake-screech/heartbeat/etc at
    # the exact spoken word, ducked under the voice. Sparse + capped.
    try:
        _mix_diegetic_sfx(out, work, clips, scenes, sfx_style=_sfx_style)
    except Exception as e:
        print(f"[sfx-ev] [warn] event sfx skipped: {e}")

    # Story beats (multi-story narration channels): channel INTRO card at 0:00 +
    # a story title card before each account, spliced in with a real pause (drone
    # fading to silence) so the card lands before narration resumes. Runs LAST of
    # the timeline edits (it changes durations). Falls back to the pure-visual
    # overlay if the splice fails.
    if channel_meta.get("story_cards", channel_meta.get("channel_style") == "horror_real"):
        try:
            _insert_story_beats(out, work, clips, scenes, channel_meta)
        except Exception as e:
            print(f"[storybeats] [warn] splice failed, trying overlay: {e}")
            try:
                _overlay_story_cards(out, work, clips, scenes)
            except Exception as e2:
                print(f"[storycards] [warn] skipped: {e2}")

    # FINAL AUDIO MASTER — publish spec: −14 LUFS, 48 kHz stereo AAC 192k.
    # Every upstream mix step (BGM/captions/kinetic/SFX) re-encodes with source
    # properties (kokoro TTS = mono low-rate), so master LAST or the output
    # audit rejects the file (audio_not_stereo / sample_rate / loudness).
    # Two-pass LINEAR loudnorm: single-pass is dynamic (per-frame gain) and
    # pumps up the deliberate dramatic pauses the pacing audit checks for.
    try:
        _tmp_m = out.with_name(out.stem + "_master.mp4")
        _ln = "loudnorm=I=-14:TP=-1.5:LRA=11"
        try:  # pass 1: measure
            _p1 = subprocess.run(
                ["ffmpeg", "-y", "-i", str(out), "-af", f"{_ln}:print_format=json",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=900,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
            # raw_decode: ffmpeg prints trailing lines after the stats JSON,
            # plain loads() raises Extra data and silently forced 1-pass mode.
            _mjson, _ = json.JSONDecoder().raw_decode(_p1.stderr[_p1.stderr.rfind("{"):])
            _ln = (f"{_ln}:measured_I={_mjson['input_i']}:measured_TP={_mjson['input_tp']}"
                   f":measured_LRA={_mjson['input_lra']}:measured_thresh={_mjson['input_thresh']}"
                   f":offset={_mjson['target_offset']}:linear=true")
        except Exception:
            pass  # fall back to single-pass dynamic loudnorm
        run(["ffmpeg", "-y", "-i", str(out), "-af", _ln,
             "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
             "-c:v", "copy", str(_tmp_m)])
        if _tmp_m.exists() and _tmp_m.stat().st_size > 0:
            _replace_retry(_tmp_m, out, label="master")
            print(f"[3z/5] Audio mastered: -14 LUFS 48 kHz stereo AAC 192k "
                  f"({'linear 2-pass' if 'linear=true' in _ln else 'dynamic 1-pass'})")
    except Exception as e:
        if STRICT:
            raise RuntimeError(f"Audio mastering failed ({e}) — STRICT refuses "
                               "non-publish-spec audio") from e
        print(f"[master] [warn] skipped ({e})")

    # Channel intro/outro bumpers — brand-consistent, render-once, reused every
    # video. Prepended/appended to the finished body. No-op if channel declares none.
    if channel_meta.get("intro_clip") or channel_meta.get("outro_clip"):
        try:
            import bumper
            b = bumper.resolve_bumpers(channel_meta, voice_chain=voice_chain,
                                       voice_rate=args.voice_rate, voice_pitch=args.voice_pitch)
            if b["intro"] or b["outro"]:
                if bumper.concat_with_bumpers(out, b["intro"], b["outro"], work):
                    print(f"[4-/5] Bumpers added: intro={'✓' if b['intro'] else '–'} outro={'✓' if b['outro'] else '–'}")
        except Exception as e:
            print(f"[bumper] [warn] skipped: {e}")

    dur = probe_duration(out)
    size_mb = out.stat().st_size / (1024 * 1024)

    # QA self-review: a render only ships if it has real video+audio streams,
    # audible (non-silent) audio and non-blank frames. Report -> status.json.
    try:
        import qa_check
        status.stage("qa", "active"); status.log("QA self-review...")
        # Motion ratio (Orkas delivery guard): real-motion scenes = stock B-roll
        # + Veo clips; generated stills with Ken-Burns are "slide grammar".
        _motion_sec = 0.0
        try:
            _motion_sec = sum(
                probe_duration(clips[i]) for i in range(len(clips))
                if (i in stock_paths or i in veo_paths)
                and clips[i] and clips[i].exists())
        except Exception:
            _motion_sec = 0.0
        qa_rep = qa_check.validate_video(
            str(out),
            motion_sec=_motion_sec,
            motion_min_ratio=float(channel_meta.get("motion_min_ratio") or 0.0),
            evidence_dir=str(out.parent))
        status.qa(qa_rep)
        status.log(f"QA: {qa_rep['summary']}")
        print(f"[3b/5] QA: {qa_rep['summary']}")
        if not qa_rep["ok"]:
            status.error(f"QA failed: {qa_rep['summary']}")
            print(f"[QA-FAIL] {qa_rep['summary']} — render kept for inspection.")
        status.stage("qa", "done")
    except Exception as e:
        print(f"[warn] QA self-review skipped: {e}")

    status.video(out.name); status.log(f"done {dur:.0f}s {size_mb:.1f}MB")
    print(f"[4/5] Rendered: {out}")

    # Imported here so the handler below can NAME the fail-closed error rather
    # than catching it with everything else.
    try:
        from omnicast.analytics.intel_gate import CompetitorIntelRequired
    except Exception:  # pragma: no cover - package unavailable in bare scripts
        class CompetitorIntelRequired(RuntimeError):
            """Fallback so the handler below stays well-formed."""

    # Clickbait title + thumbnail (all channels). Title -> <stem>_title.txt,
    # thumbnail 1280x720 -> <stem>_thumb.png. Thumbnail bg = the hook
    # illustration (or a frame pulled from the final video as fallback).
    try:
        import clickbait
        # The pillar comes from the BRIEF (recorded in product meta), not from
        # re-reading the script: `TopicBrief.pillar_id` already decided it, and
        # re-classifying 2,000 characters could hand an annuities video the
        # social-security playbook because it mentions Medicare a lot. The
        # classifier remains a fallback and says so.
        _pillar_ssot = ""
        try:
            from omnicast.storage import products as _products_meta
            _pillar_ssot = str((_products_meta.read_meta(out.parent) or {}).get(
                "pillar_id") or "")
        except Exception:
            _pillar_ssot = ""
        cb = clickbait.generate_clickbait(
            script_path.read_text(encoding="utf-8"), channel_meta,
            pillar_id=_pillar_ssot)
        if cb:
            (out.with_name(out.stem + "_title.txt")).write_text(
                cb["title"], encoding="utf-8")
            status.set_title(cb["title"])  # show real video title in dashboard
            # Thumbnail background generated by the SAME image provider (Flow
            # Nano Banana) from the clickbait thumb_prompt — a dramatic,
            # high-contrast shot with space for text. Fallbacks: hook
            # illustration, then a frame from the final video.
            thumb_bg = work / "_thumb_bg.png"
            generated = False
            if image_provider is not None and (cb.get("thumb_prompt")):
                try:
                    import asyncio
                    # Thumbnails want a PREMIUM photoreal look (Vox/Johnny-Harris
                    # authority), NOT the channel's flat 2D illustration style — a
                    # cartoon thumb reads as a cheap Freepik/Canva channel. Override
                    # the in-video illustration style_prefix with a cinematic one.
                    _is_horror = (channel_meta.get("channel_style") == "horror_real"
                                  or channel_meta.get("thumb_style") == "horror")
                    _ttext = (cb.get("thumb_text") or "").strip().upper()
                    if _is_horror:
                        # Horror thumbs: found-footage grade + scratched horror font,
                        # NOT the bright-yellow MrBeast look (which reads as clickbait
                        # comedy, kills the dread). Uncanny near-human subject.
                        THUMB_STYLE = (
                            "grainy amateur night photograph, found-footage look, harsh "
                            "single light source, deep crushed shadows, cold teal and "
                            "desaturated grade, heavy film grain, high contrast, ominous"
                        )
                        THUMB_NEG = (
                            "flat vector, cartoon, illustration, clipart, 2d, anime, "
                            "bright cheerful colors, yellow impact font, comedy, smiling, "
                            "gore, monster, fangs, claws, low detail, blurry, watermark, "
                            "gibberish text, misspelled text, garbled letters"
                        )
                        tp = (
                            f"{THUMB_STYLE}, {cb['thumb_prompt']}, a lone almost-human "
                            f"figure that is subtly wrong (too tall, too still). "
                            f"Large all-caps horror-movie headline text reading exactly "
                            f"\"{_ttext}\" — scratched distressed bone-white letters with "
                            f"a thin dried-blood-red edge, perfectly spelled, highly "
                            f"legible, cinematic horror typography, NOT yellow"
                        )
                    else:
                        THUMB_STYLE = (
                            "photorealistic cinematic photograph, dramatic exaggerated "
                            "facial expression, vivid rim lighting, teal and magenta studio "
                            "lighting, shallow depth of field, hyper-detailed, high contrast"
                        )
                        THUMB_NEG = (
                            "flat vector, cartoon, illustration, clipart, 2d, anime, drawing, "
                            "low detail, blurry, watermark, logo, "
                            "deformed hands, extra fingers, distorted face, "
                            "gibberish text, misspelled text, garbled letters"
                        )
                        tp = (
                            f"{THUMB_STYLE}, {cb['thumb_prompt']}, bold dramatic subject. "
                            f"Large bold all-caps YouTube thumbnail headline text reading "
                            f"exactly \"{_ttext}\" placed in a corner — thick sans-serif, "
                            f"heavy black outline, one word in bright yellow, perfectly spelled, "
                            f"highly legible, MrBeast-style impactful thumbnail typography"
                        )
                    _aiorun(image_provider.generate(
                        tp, negative=THUMB_NEG,
                        model=args.image_model, resolution=(1280, 720),
                        output_path=str(thumb_bg.resolve())))
                    generated = thumb_bg.exists()
                    print(f"[4b/5] Thumbnail (text baked by Flow): '{_ttext}'")
                except Exception as te:
                    print(f"      [warn] Flow thumbnail gen failed ({te}); fallback")
            thumb = out.with_name(out.stem + "_thumb.png")
            if generated:
                # Flow already rendered the headline text — use the image directly
                # (normalize to 1280x720). Adding Pillow text would double it.
                try:
                    from PIL import Image as _PImg
                    im = _PImg.open(thumb_bg).convert("RGB")
                    tw, th = 1280, 720
                    sc = max(tw / im.width, th / im.height)
                    im = im.resize((int(im.width * sc), int(im.height * sc)))
                    x0 = (im.width - tw) // 2; y0 = (im.height - th) // 2
                    im.crop((x0, y0, x0 + tw, y0 + th)).save(thumb)
                except Exception as _re:
                    print(f"      [warn] thumb finalize failed ({_re}); raw copy")
                    shutil.copyfile(thumb_bg, thumb)
            else:
                # OPERATOR POLICY (2026-07-09): thumbnails are FLOW-ONLY. A stock
                # frame reads as generic and tanks CTR ("lấy 1 frame quá xấu").
                # No Flow = no thumbnail = failed render — log into Flow and
                # re-run. (Non-strict debug builds keep the legacy paths below.)
                if STRICT:
                    raise RuntimeError(
                        "Flow unavailable/failed — thumbnails are FLOW-ONLY by "
                        "operator policy (no stock frames). Open Flow in the "
                        "browser profile, sign in, then re-run the render.")
                # Flow unavailable/expired (it often dies by the thumbnail stage).
                # Build a PHOTOREAL thumb without it, then Pillow text on top.
                got_bg = False
                # 1) A frame from OUR OWN licensed stock footage — prefer scenes
                #    with a human face/emotion (CTR driver). The old web-image
                #    search returned other channels' thumbnails and Etsy product
                #    shots (copyright risk + stray baked-in text) — removed.
                try:
                    _face_re = re.compile(
                        r"woman|face|person|presenter|looking|clutching|holding|"
                        r"nauseous|smiling|frustrated|tired|expression", re.I)
                    _cands: list[tuple[int, Path]] = []
                    for _i in range(len(scenes)):
                        _sp = work / f"scene_{_i:02d}_stock.mp4"
                        if not _sp.exists() or _sp.stat().st_size == 0:
                            continue
                        _cell_q = ""
                        if board and _i < len(board) and board[_i]:
                            _cell_q = (board[_i].get("stock_query")
                                       or board[_i].get("search_query") or "")
                        _txt = f"{_cell_q} {scenes[_i].heading}"
                        _score = 2 if _face_re.search(_txt) else 0
                        _cands.append((_score, _sp))
                    _cands.sort(key=lambda t: -t[0])
                    if _cands:
                        _pick = _cands[0][1]
                        run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(_pick),
                             "-frames:v", "1", "-q:v", "2", str(thumb_bg)])
                        if thumb_bg.exists() and thumb_bg.stat().st_size > 0:
                            got_bg = True
                            print(f"[4b/5] Thumbnail bg: own stock frame ({_pick.name})")
                except Exception as _se:
                    print(f"      [warn] stock thumb bg failed ({_se})")
                if not got_bg and STRICT:
                    raise RuntimeError(
                        "Thumbnail source failed (no face/emotion stock frame) — "
                        "STRICT mode refuses random-frame thumbnails. Log into "
                        "Flow for AI thumbs or fix the stock footage, then re-run.")
                # 2) Last resort (non-strict only): a CONTENT frame from a mid
                #    SCENE CLIP (pre-caption, pre-kinetics).
                if not got_bg:
                    _mid = None
                    if 'clips' in dir() and clips:
                        _c0 = len(clips) // 2
                        for _c in list(clips[_c0:]) + list(clips[:_c0]):
                            if _c and Path(_c).exists():
                                _mid = _c
                                break
                    if _mid:
                        run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(_mid),
                             "-frames:v", "1", str(thumb_bg)])
                    if not thumb_bg.exists():  # truly nothing else — frame from final
                        _dv = probe_duration(out) or 60.0
                        run(["ffmpeg", "-y", "-ss", f"{max(3.0, _dv * 0.45):.1f}",
                             "-i", str(out), "-frames:v", "1", str(thumb_bg)])
                clickbait.compose_thumbnail(Path(thumb_bg), cb["thumb_text"], thumb,
                                            accent=tuple(accent))
            status.log(f"title: {cb['title']}")
            print(f"[4b/5] Title : {cb['title']}")
            print(f"[4b/5] Thumb : {thumb}  ('{cb['thumb_text']}')")
            # A previous run may have persisted a fail-closed packaging state.
            # Clear it only after this run has produced the complete title and
            # thumbnail package; the exception handlers below must leave it set.
            from omnicast.storage import products as _products
            _products.mark_packaging_ready(out.parent)
    except CompetitorIntelRequired as exc:
        # FAIL CLOSED, ALL THE WAY OUT. `generate_clickbait` re-raises this, and
        # catching it here with everything else put the declaration back to
        # sleep one frame further out: the render printed a warning, printed
        # DONE, and shipped packaging built from patterns the channel had said
        # it would rather not ship at all.
        #
        # The MP4 stays on disk — it is already rendered and re-rendering costs
        # money — but the product is marked unpublishable and the process exits
        # non-zero, so no caller mistakes this for a completed render.
        status.error(f"competitor intel required but unusable: {exc}")
        print(f"[5/5] BLOCKED — {exc}")
        print("       The video was rendered but has NO approved packaging and "
              "must not be published. Re-run competitor intel for this channel, "
              "or clear `competitor_intel_required` if that is really intended.")
        try:
            from omnicast.storage import products as _products
            _products.write_meta(out.parent, packaging_blocked=str(exc),
                                 publishable=False)
        except Exception:
            pass
        raise
    except Exception as exc:
        print(f"      [warn] clickbait failed: {exc}")

    print(f"[5/5] DONE — duration={dur:.1f}s  size={size_mb:.1f}MB  words={total_words}")
    print(f"\n  Real playable MP4 at: {out}")

    # LLM spend for THIS render (storyboard + clickbait + expand). Printed + saved to
    # the product meta so per-video cost is visible, not buried in per-call logs.
    try:
        from omnicast.llm.client import get_session_cost
        _c = get_session_cost()
        _by = ", ".join(f"{m}=${v:.4f}" for m, v in sorted(_c["by_model"].items(), key=lambda x: -x[1]))
        print(f"[cost] render LLM: ${_c['total']:.4f} ({_c['calls']} calls) — {_by}")
        from omnicast.storage import products as _products
        _products.write_meta(out.parent, llm_cost_render_usd=_c["total"],
                             llm_cost_render_by_model=_c["by_model"])
    except Exception as _ce:
        print(f"      [cost] summary skipped ({_ce})")

    # Full QC manifest: consolidate variants/QA/timeline/bgm/voice/ffprobe into meta.json
    try:
        from omnicast.storage import products as _products
        _products.build_manifest(out.parent)
        print(f"[meta] QC manifest written → {out.parent / 'meta.json'}")
    except Exception as _me:
        print(f"      [meta] manifest skipped ({_me})")


if __name__ == "__main__":
    main()
