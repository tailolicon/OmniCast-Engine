"""Web Asset Search and Downloader Service for OmniCast Engine.

Searches the web (DuckDuckGo Images) for real-world images/evidence and downloads
them, fallback-scaling to fit the target video aspect ratio.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
import time
from pathlib import Path
import structlog
from PIL import Image

# Ensure parent directory is in path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent.parent))

logger = structlog.get_logger()

_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # implementation/
SEARCH_PROFILE_DIR = _ROOT / "output" / "search_profile"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def resize_to_cover(img_path: Path, target_w: int, target_h: int) -> bool:
    """Resize and crop image to fill target_w x target_h (cover mode)."""
    try:
        with Image.open(img_path) as img:
            img_w, img_h = img.size
            
            # Calculate scale factor to cover target
            scale = max(target_w / img_w, target_h / img_h)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # Center crop
            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            right = left + target_w
            bottom = top + target_h
            
            cropped = resized.crop((left, top, right, bottom))
            
            if cropped.mode != 'RGB':
                cropped = cropped.convert('RGB')
            cropped.save(img_path, "PNG")
            return True
    except Exception as e:
        logger.error("web_assets.resize_failed", path=str(img_path), error=str(e))
        return False


def _download_url(url: str, dest: Path) -> bool:
    """Try to download URL to dest using urllib with desktop User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            dest.write_bytes(r.read())
        # Try to open to verify it's a valid image
        with Image.open(dest) as img:
            img.verify()
        return True
    except Exception as e:
        logger.warn("web_assets.download_failed", url=url[:60], error=str(e))
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        return False


def fetch_web_images(query: str, limit: int = 5) -> list[dict]:
    """Search DuckDuckGo Images using CloakBrowser and return list of results metadata."""
    # Lazy/optional import: cloakbrowser is an optional dep — importing it at module
    # top would crash every importer (incl. render_real_video) when it's not
    # installed. Degrade gracefully: no cloakbrowser → no web-image results.
    try:
        from cloakbrowser import launch_persistent_context  # type: ignore[import-untyped]
    except Exception as e:
        logger.warn("web_assets.cloakbrowser_unavailable", error=str(e))
        return []

    SEARCH_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("web_assets.search_start", query=query)

    ctx = launch_persistent_context(
        str(SEARCH_PROFILE_DIR),
        headless=True,
        humanize=True,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_viewport_size({"width": 1280, "height": 800})
    
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    try:
        page.goto(url)
        # Wait up to 8s for the search page to load
        page.wait_for_timeout(4000)
        
        # Traverse React Fiber to extract structured items
        items = page.evaluate("""() => {
            const figures = document.querySelectorAll('figure');
            if (figures.length === 0) return [];
            
            const first = figures[0];
            const keys = Object.keys(first);
            const reactKey = keys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactProps'));
            if (!reactKey) return [];
            
            const extracted = [];
            for (let fig of figures) {
                let node = fig[reactKey];
                let found_item = null;
                while (node) {
                    const props = node.memoizedProps;
                    if (props) {
                        for (let k of Object.keys(props)) {
                            const val = props[k];
                            if (val && typeof val === 'object' && !Array.isArray(val)) {
                                if ('image' in val && 'title' in val && 'height' in val && 'width' in val) {
                                    found_item = val;
                                    break;
                                }
                            }
                        }
                    }
                    if (found_item) break;
                    node = node.return;
                }
                if (found_item) {
                    extracted.push({
                        title: found_item.title,
                        image: found_item.image,
                        width: found_item.width,
                        height: found_item.height,
                        source: found_item.source,
                        url: found_item.url
                    });
                }
            }
            return extracted;
        }""")
        
        logger.info("web_assets.search_done", found=len(items))
        return items[:limit]
    except Exception as e:
        logger.error("web_assets.search_error", query=query, error=str(e))
        return []
    finally:
        try:
            ctx.close()
        except Exception:
            pass


# Stock-preview domains that tile a visible watermark over the image — unusable.
_WATERMARK_DOMAINS = (
    "dreamstime", "shutterstock", "alamy", "istockphoto", "istock", "123rf",
    "depositphotos", "gettyimages", "stock.adobe", "adobestock", "bigstock",
    "canstockphoto", "vectorstock", "watermark", "agefotostock", "stockphoto",
)


def _is_watermarked(item: dict) -> bool:
    hay = (str(item.get("image", "")) + " " + str(item.get("source", "")) + " "
           + str(item.get("url", ""))).lower()
    return any(d in hay for d in _WATERMARK_DOMAINS)


def download_best_web_image(query: str, out_path: Path, target_w: int = 1920, target_h: int = 1080) -> bool:
    """Search for query, download the first valid NON-watermarked image, scale/crop to target."""
    items = fetch_web_images(query, limit=30)
    if not items:
        logger.warn("web_assets.no_results_found", query=query)
        return False

    # Prefer clean sources; only fall back to watermarked previews if nothing else.
    clean = [it for it in items if not _is_watermarked(it)]
    ordered = clean + [it for it in items if _is_watermarked(it)]

    for idx, item in enumerate(ordered):
        img_url = item.get("image")
        if not img_url:
            continue
        if idx < len(clean) and _is_watermarked(item):
            continue  # safety
        logger.info("web_assets.attempting_download", index=idx, url=img_url[:60])

        logger.info("web_assets.attempting_download", index=idx, url=img_url[:60])
        
        # 1. Try direct URL download
        if _download_url(img_url, out_path):
            if resize_to_cover(out_path, target_w, target_h):
                logger.info("web_assets.download_success", url=img_url[:60])
                return True
                
        # 2. Try DuckDuckGo proxied thumbnail URL as fallback
        # The DDG proxied format: https://external-content.duckduckgo.com/iu/?u=URL-encoded-url
        proxy_url = f"https://external-content.duckduckgo.com/iu/?u={urllib.parse.quote(img_url)}&f=1"
        logger.info("web_assets.attempting_proxy_download", index=idx, url=proxy_url[:60])
        if _download_url(proxy_url, out_path):
            if resize_to_cover(out_path, target_w, target_h):
                logger.info("web_assets.proxy_download_success", url=proxy_url[:60])
                return True
                
    logger.error("web_assets.all_downloads_failed", query=query)
    return False
