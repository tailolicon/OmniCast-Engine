"""HTML/CSS overlay renderer (Playwright) — modern replacement for the Pillow
text overlays in render_real_video.py.

Why: Pillow draws fixed-coordinate text (hard wraps, no gradients, no rounded
frosted cards, manual outlines). Rendering the overlay as HTML/CSS and screen-
shotting it with a transparent background gives gradient text, auto-wrapping,
letter-spacing, soft shadows and rounded translucent "glass" cards — far nicer
typography for the same per-shot transparent PNG the ffmpeg compositor expects.

Architecture note (important): OmniCast overlays are TRANSPARENT layers composited
by ffmpeg OVER the moving Ken Burns / Veo background. A separate transparent layer
has nothing behind it in the page, so real CSS `backdrop-filter: blur()` would blur
nothing. We therefore use a *frosted translucent card* look (rgba fill + border +
shadow) rather than true backdrop blur — visually close, and it keeps the
background free to animate underneath.

Drop-in: render_text_overlay / render_subtitle_overlay mirror the Pillow function
signatures (scene, idx, total, out_png, w, h). A shared headless Chromium is kept
alive (singleton) so rendering 20-40 shots costs one browser launch, not N.
"""

from __future__ import annotations

import html as _html
import re
from importlib.util import find_spec
from pathlib import Path

# ── Shared singleton Chromium (sync API; render_real_video.py is a sync script) ──
_pw = None
_browser = None


def available() -> bool:
    """True if Playwright is importable. Browser-binary problems surface later and
    fall back to Pillow at the call site, so this stays a cheap import check."""
    return find_spec("playwright") is not None


def _get_browser():
    global _pw, _browser
    if _browser is not None:
        try:
            if _browser.is_connected():
                return _browser
        except Exception:
            pass
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(args=[
        "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-gpu", "--disable-extensions",
    ])
    return _browser


def close() -> None:
    """Shut the shared browser down — call once at the end of a render run."""
    global _pw, _browser
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    finally:
        _browser = None
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    finally:
        _pw = None


def _shoot(html: str, out_png: Path, w: int, h: int) -> None:
    """Render an HTML string to a transparent PNG at exactly w×h."""
    browser = _get_browser()
    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
    try:
        page.set_content(html, wait_until="load")
        page.screenshot(path=str(out_png), type="png", omit_background=True)
    finally:
        try:
            page.close()
        except Exception:
            pass


# ── Shared CSS shell ─────────────────────────────────────────────────────────
# Units are vh/vw/% so a single template adapts to both 1920×1080 and 1080×1920
# without per-orientation files. Transparent html/body → omit_background works.
_BASE_CSS = """
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:100%; height:100%; background:transparent;
    font-family:'Segoe UI','Arial','Helvetica Neue',sans-serif;
    -webkit-font-smoothing:antialiased; }
"""


def render_text_overlay(scene, idx: int, total: int, out_png: Path, w: int, h: int) -> None:
    """Editorial overlay: left gradient scrim, accent bar, kicker, gradient title,
    frosted caption card. Transparent everywhere else."""
    heading = _html.escape((scene.heading or "").strip())
    sentences = re.split(r"(?<=[.!?])\s+", scene.narration or "")
    caption = _html.escape(" ".join(sentences[:2])[:280].strip())
    kicker = f"SCENE {idx + 1} / {total}"

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .scrim {{ position:absolute; inset:0; width:64%;
    background:linear-gradient(90deg, rgba(6,8,12,.88) 0%, rgba(6,8,12,.72) 38%, rgba(6,8,12,0) 100%); }}
  .wrap {{ position:absolute; left:8.8%; top:22%; width:52%; }}
  .bar {{ width:.55vh; height:0; display:inline-block; }}
  .kicker {{ font-size:3.0vh; font-weight:600; letter-spacing:.32vh;
    color:#79aaf0; text-transform:uppercase; margin-bottom:2.4vh;
    display:flex; align-items:center; gap:1.4vh; }}
  .kicker::before {{ content:''; width:1.0vh; height:5.4vh; border-radius:1vh;
    background:linear-gradient(180deg,#4aa0ff,#2f6bff); box-shadow:0 0 1.6vh rgba(70,160,255,.6); }}
  .title {{ font-size:8.0vh; font-weight:800; line-height:1.06; letter-spacing:-.05vh;
    background:linear-gradient(180deg,#ffffff 0%,#cfd8e6 100%);
    -webkit-background-clip:text; background-clip:text; color:transparent;
    text-shadow:0 .4vh 2.4vh rgba(0,0,0,.45); margin-bottom:3.2vh; }}
  .cap {{ font-size:3.9vh; line-height:1.34; color:#e6ebf3; font-weight:400;
    padding:2.4vh 2.8vh; border-radius:2.0vh;
    background:rgba(18,22,32,.46); border:1px solid rgba(255,255,255,.10);
    box-shadow:0 1.2vh 4vh rgba(0,0,0,.35); backdrop-filter:blur(2px); }}
</style></head><body>
  <div class="scrim"></div>
  <div class="wrap">
    <div class="kicker">{_html.escape(kicker)}</div>
    <div class="title">{heading}</div>
    {f'<div class="cap">{caption}</div>' if caption else ''}
  </div>
</body></html>"""
    _shoot(doc, out_png, w, h)


def render_subtitle_overlay(scene, idx: int, total: int, out_png: Path, w: int, h: int) -> None:
    """Clean bottom subtitle: centered spoken line in a soft frosted pill with a
    crisp shadow — readable over any moving illustration."""
    text = _html.escape(re.sub(r"\s+", " ", scene.narration or "").strip())

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .sub {{ position:absolute; left:50%; bottom:7.5%; transform:translateX(-50%);
    max-width:82%; text-align:center;
    font-size:4.7vh; font-weight:700; line-height:1.28; color:#ffffff;
    padding:1.6vh 3.2vh; border-radius:1.8vh;
    background:rgba(8,10,16,.50); border:1px solid rgba(255,255,255,.12);
    box-shadow:0 1vh 3.2vh rgba(0,0,0,.45);
    text-shadow:0 .25vh 1.2vh rgba(0,0,0,.85), 0 0 .3vh rgba(0,0,0,.9);
    backdrop-filter:blur(2px); }}
</style></head><body>
  {f'<div class="sub">{text}</div>' if text else ''}
</body></html>"""
    _shoot(doc, out_png, w, h)
