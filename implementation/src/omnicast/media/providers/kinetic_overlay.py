"""Kinetic Statistic Overlay Service for OmniCast Engine.

Uses Playwright to render high-resolution statistic callout cards (frosted glassmorphism,
gradient text, modern typography) as transparent overlays, overlayed by FFmpeg over videos.
"""

from __future__ import annotations

import os
import sys
import html as _html
from pathlib import Path
import structlog

# Ensure implementation/ is in path to import html_overlay
_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import html_overlay

logger = structlog.get_logger()

# Shared CSS — PLAIN emphasis (Vfacts style): just a big bold WHITE number with a
# soft shadow. No box, no gradient, no glowing accent bar, no colour — restrained,
# only enough to draw the eye. Clutter/decoration ("màu mè") reads as cheap.
_KINETIC_CSS = """
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:100%; height:100%; background:transparent;
    font-family:'Segoe UI','Arial','Helvetica Neue',sans-serif;
    -webkit-font-smoothing:antialiased; }

  .container {
    position: absolute;
    left: 7%;
    bottom: 15%;
    width: auto;
    max-width: 80%;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
  }

  .number {
    font-size: 16vh;
    font-weight: 800;
    line-height: 0.98;
    letter-spacing: -0.4vh;
    color: #ffffff;
    /* thin dark outline + soft shadow ONLY for legibility on any background */
    -webkit-text-stroke: 0.16vh rgba(0, 0, 0, 0.45);
    paint-order: stroke fill;
    text-shadow: 0 0.3vh 1.6vh rgba(0,0,0,0.55), 0 0 0.5vh rgba(0,0,0,0.7);
    font-feature-settings: "tnum" 1;
  }

  .label {
    font-size: 3.1vh;
    font-weight: 600;
    line-height: 1.2;
    color: #ffffff;
    opacity: 0.9;
    letter-spacing: 0.1vh;
    margin-top: 1vh;
    text-transform: uppercase;
    text-shadow: 0 0.2vh 1vh rgba(0,0,0,0.6);
  }

  @media (max-aspect-ratio: 1/1) {
    .container { left: 7%; bottom: 17%; max-width: 88%; }
    .number { font-size: 11vh; }
    .label { font-size: 2.6vh; }
  }

  /* HERO variant — a full-screen "shock number" moment: giant centered figure
     over a dim scrim so the staggering total lands hard (reference: 415 TWh /
     9.3 trillion L cards). Used only for the biggest scale stats, not inline. */
  body.hero { background: radial-gradient(ellipse at center,
      rgba(0,0,0,0.45) 0%, rgba(0,0,0,0.72) 100%); }
  body.hero .container {
    left: 0; right: 0; bottom: auto; top: 50%; transform: translateY(-50%);
    width: 92%; max-width: 92%; margin: 0 auto; align-items: center; text-align: center;
  }
  body.hero .number {
    font-size: 19vh; letter-spacing: -0.5vh; line-height: 1.0;
    max-width: 100%; white-space: normal; word-break: keep-all;
  }
  body.hero .label { font-size: 3.8vh; margin-top: 2.2vh; opacity: 0.95; }
  @media (max-aspect-ratio: 1/1) {
    body.hero .number { font-size: 14vh; }
    body.hero .label { font-size: 3.2vh; }
  }
"""


def render_kinetic_stat(
    number: str, label: str, out_png: Path, w: int = 1920, h: int = 1080,
    hero: bool = False,
) -> bool:
    """Render a statistical number + label into a transparent PNG overlay at wxh.

    hero=True → giant centered "shock number" over a dim scrim (full-screen moment
    for the biggest scale stats); default → restrained bottom-left inline callout.
    """
    if not html_overlay.available():
        logger.error("kinetic_overlay.playwright_unavailable")
        return False

    escaped_number = _html.escape(number.strip())
    escaped_label = _html.escape(label.strip())
    body_class = "hero" if hero else ""

    doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{_KINETIC_CSS}
</style>
</head>
<body class="{body_class}">
  <div class="container">
    <div class="number">{escaped_number}</div>
    <div class="label">{escaped_label}</div>
  </div>
</body>
</html>"""

    try:
        browser = html_overlay._get_browser()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.set_content(doc, wait_until="load")

        dest = Path(out_png)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
            
        page.screenshot(path=str(dest), type="png", omit_background=True)
        page.close()
        
        logger.info("kinetic_overlay.render_success", path=str(dest))
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        logger.error("kinetic_overlay.render_failed", number=number, label=label, error=str(e))
        return False


if __name__ == "__main__":
    import sys
    num = sys.argv[1] if len(sys.argv) > 1 else "40 Billion Tons"
    lab = sys.argv[2] if len(sys.argv) > 2 else "Annual Ice Sheet Melted"
    out = Path("output/test_kinetic_overlay.png")
    print(f"Rendering statistic: '{num}' | '{lab}'...")
    if render_kinetic_stat(num, lab, out):
        print(f"Success! Statistic overlay saved to {out}")
    else:
        print("Failed to render statistic overlay.")
