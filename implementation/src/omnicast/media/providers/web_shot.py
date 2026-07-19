"""Web Screenshot Service for OmniCast Engine.

Uses Playwright to capture screenshots of live web pages and places them inside
a beautiful browser mockup frame against a premium dark gradient background.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path
import structlog

# Ensure implementation/ is in path to import html_overlay
_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import html_overlay

logger = structlog.get_logger()

_SCREENSHOT_CACHE_DIR = _ROOT / "output" / "_screenshot_cache"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _is_mostly_blank(png_path: Path, white_thresh: float = 0.86) -> bool:
    """True if the screenshot is mostly empty near-white (a blank shell / failed
    or sparse page — e.g. a site homepage). The browser mockup shows the TOP of
    the page (object-fit:cover, object-position:top), so measure that visible band
    plus the whole image; either being near-empty white => reject."""
    try:
        from PIL import Image, ImageStat

        def _frac_var(region):
            stat = ImageStat.Stat(region)
            variance = sum(stat.var) / 3.0
            px = list(region.getdata())
            nw = sum(1 for r, g, b in px if r > 236 and g > 236 and b > 236)
            return nw / len(px), variance

        with Image.open(png_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            full = im.resize((96, 60))
            # Visible band = top ~58% (what object-fit:cover/top reveals in the frame)
            top = im.crop((0, 0, w, int(h * 0.58))).resize((96, 36))
            fw_full, var_full = _frac_var(full)
            fw_top, var_top = _frac_var(top)
        # Reject if either the whole shot or the visible top band is mostly white
        # with little colour variance (text/figures would add variance).
        blank_full = fw_full >= white_thresh and var_full < 220.0
        blank_top = fw_top >= white_thresh and var_top < 220.0
        return blank_full or blank_top
    except Exception:
        return False  # can't tell → don't reject


def _extract_domain(url: str) -> str:
    """Extract domain name from URL for display in the mock address bar."""
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return "webpage"


def capture_web_page(url_or_query: str, dest_png: Path, target_w: int = 1920, target_h: int = 1080) -> bool:
    """Navigate to a URL or search DDG for query, screenshot it, and wrap in browser mockup."""
    if not html_overlay.available():
        logger.error("web_shot.playwright_unavailable")
        return False

    browser = html_overlay._get_browser()
    page = browser.new_page(viewport={"width": 1280, "height": 800}, user_agent=_UA)
    
    url = url_or_query.strip()
    is_direct_url = url.startswith("http://") or url.startswith("https://")
    
    try:
        # Step 1: Resolve Target URL
        if not is_direct_url:
            logger.info("web_shot.searching_duckduckgo", query=url)
            search_url = f"https://duckduckgo.com/?q={urllib.parse.quote(url)}"
            page.goto(search_url, timeout=20000, wait_until="load")
            page.wait_for_timeout(3000)
            
            # Find first organic search result link
            link_locator = page.locator('a[data-testid="result-title-a"], a.result__a, .links_main a')
            if link_locator.count() > 0:
                resolved_url = link_locator.first.get_attribute("href")
                if resolved_url:
                    if resolved_url.startswith("//"):
                        resolved_url = "https:" + resolved_url
                    elif resolved_url.startswith("/"):
                        resolved_url = "https://duckduckgo.com" + resolved_url
                    url = resolved_url
                    logger.info("web_shot.resolved_search_url", resolved_url=url)
                else:
                    logger.warn("web_shot.search_link_attribute_missing")
                    url = search_url  # fallback to search page itself
            else:
                logger.warn("web_shot.no_search_results_found")
                url = search_url  # fallback to search page itself

        # Step 2: Navigate and capture raw screenshot
        logger.info("web_shot.navigating_to_target", url=url[:80])
        page.goto(url, timeout=30000, wait_until="load")

        # Wait for network to settle (lazy content/images) — many sites paint a
        # blank shell on 'load' and fill in afterwards. Best-effort; ignore timeout.
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        # Nudge lazy-loaders by scrolling a little, then settle.
        try:
            page.evaluate("window.scrollTo(0, 240)")
        except Exception:
            pass
        page.wait_for_timeout(1200)

        # Save raw screenshot to a UNIQUE temp file — scenes composite in parallel,
        # so a shared filename would race and clobber other scenes' screenshots.
        import uuid
        _SCREENSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp_raw = _SCREENSHOT_CACHE_DIR / f"raw_{uuid.uuid4().hex[:12]}.png"

        page.screenshot(path=str(temp_raw), type="png")
        page.close()
        page = None

        if not temp_raw.exists() or temp_raw.stat().st_size == 0:
            logger.error("web_shot.raw_screenshot_empty")
            return False

        # BLANK GUARD: a near-empty white page (slow/blocked/sparse site) renders a
        # broken-looking blank browser frame — worse than B-roll. Reject it so the
        # caller falls back to stock_video.
        if _is_mostly_blank(temp_raw):
            logger.warn("web_shot.blank_page_rejected", url=url[:80])
            try:
                temp_raw.unlink()
            except Exception:
                pass
            return False

        # Step 3: Render Browser Mockup Frame
        domain = _extract_domain(url)
        # Convert absolute path to a URL that can be loaded in Playwright
        raw_img_url = temp_raw.resolve().as_uri()

        # HTML Mockup Template
        # Using HSL dark backgrounds, nice typography, glowing accent borders
        mockup_html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: 100%;
    height: 100%;
    background: linear-gradient(135deg, #090d16 0%, #111827 50%, #06090f 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .browser-window {{
    width: 86%;
    height: 82%;
    border-radius: 16px;
    background: #0f172a;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.65), 0 0 2px rgba(255, 255, 255, 0.15);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  .browser-header {{
    height: 48px;
    background: #1e293b;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    display: flex;
    align-items: center;
    padding: 0 16px;
    position: relative;
  }}
  .controls {{
    display: flex;
    gap: 8px;
  }}
  .control-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }}
  .dot-red {{ background: #ef4444; }}
  .dot-yellow {{ background: #f59e0b; }}
  .dot-green {{ background: #10b981; }}
  
  .address-bar {{
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    width: 50%;
    height: 28px;
    border-radius: 6px;
    background: #0f172a;
    border: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #94a3b8;
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.3px;
  }}
  .address-bar svg {{
    margin-right: 6px;
    color: #64748b;
  }}
  
  .browser-body {{
    flex: 1;
    background: #fff;
    overflow: hidden;
    position: relative;
  }}
  .screenshot-img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: top center;
  }}
</style>
</head>
<body>
  <div class="browser-window">
    <div class="browser-header">
      <div class="controls">
        <div class="control-dot dot-red"></div>
        <div class="control-dot dot-yellow"></div>
        <div class="control-dot dot-green"></div>
      </div>
      <div class="address-bar">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
        </svg>
        {domain}
      </div>
    </div>
    <div class="browser-body">
      <img class="screenshot-img" src="{raw_img_url}" alt="Webpage screenshot" />
    </div>
  </div>
</body>
</html>
"""
        
        # Shoot the mockup HTML
        mock_page = browser.new_page(viewport={"width": target_w, "height": target_h}, device_scale_factor=1)
        mock_page.set_content(mockup_html, wait_until="load")
        dest_png.parent.mkdir(parents=True, exist_ok=True)

        if dest_png.exists():
            dest_png.unlink()

        mock_page.screenshot(path=str(dest_png), type="png")
        try:
            mock_page.close()
        except Exception:
            pass
        
        # Cleanup temporary raw screenshot
        if temp_raw.exists():
            try:
                temp_raw.unlink()
            except Exception:
                pass
                
        logger.info("web_shot.mockup_created_success", path=str(dest_png))
        return dest_png.exists() and dest_png.stat().st_size > 0

    except Exception as e:
        logger.error("web_shot.capture_failed", url=url_or_query[:60], error=str(e))
        for _p in (locals().get("page"), locals().get("mock_page")):
            try:
                if _p:
                    _p.close()
            except Exception:
                pass
        return False


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Global_warming"
    out = Path("output/test_web_shot.png")
    print(f"Capturing screenshot for: '{q}'...")
    if capture_web_page(q, out):
        print(f"Success! Mockup saved to {out}")
    else:
        print("Failed to capture webpage screenshot mockup.")
