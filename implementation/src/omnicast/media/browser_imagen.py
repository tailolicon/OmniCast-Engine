"""Google Flow image generation via CloakBrowser.

Uses the user's existing Google Pro subscription to generate images via
Google Flow (labs.google/fx/tools/flow) — free with Pro plan.

Flow per scene:
  1. Navigate to Flow project URL
  2. Type visual_prompt into "Bạn muốn tạo gì?" input
  3. Click "→" generate button
  4. Wait for image to appear in media library
  5. Download PNG → save to output dir

Output: output/scripts/{channel_id}/{topic_slug}/images/scene_NNN.png

Setup (one time):
    python -c "
    import asyncio
    from omnicast.media.browser_imagen import setup_profile
    asyncio.run(setup_profile())
    "
    → Browser opens → log into Google Pro → press Enter

Usage:
    results = asyncio.run(generate_images_for_script_browser(
        script_json_path="path/to/script.json",
        flow_project_url="https://labs.google/fx/vi/tools/flow/project/YOUR_ID",
    ))
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import TypedDict

import structlog

logger = structlog.get_logger()

_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # implementation/
PROFILE_DIR = _ROOT / "output" / "browser_profile"

# Default project URL — override per-call or via env
DEFAULT_FLOW_PROJECT_URL = (
    "https://labs.google/fx/vi/tools/flow/project/50aa9955-5742-47c2-8571-13083c4c1557"
)

# Delay between scenes — Flow rate limit buffer
SCENE_DELAY_S = 6.0

# Generation timeout per image (Flow can be slow)
GENERATION_TIMEOUT_S = 120.0


class SceneImage(TypedDict):
    scene_index: int
    segment: str
    voiceover: str
    visual_prompt: str
    image_path: str
    status: str   # done | failed | skipped


# ─── Profile Setup ────────────────────────────────────────────────────────────

SETUP_WAIT_S = 120  # seconds to wait for user login during setup


def setup_profile(wait_s: int = SETUP_WAIT_S) -> None:
    """Open browser so user can log into Google Pro once.

    Run:
        python -c "from omnicast.media.browser_imagen import setup_profile; setup_profile()"

    Browser opens visible — log into Google, then wait for countdown to finish.
    """
    from cloakbrowser import launch_persistent_context  # type: ignore[import-untyped]

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("browser_imagen.setup_start", profile=str(PROFILE_DIR))

    ctx = launch_persistent_context(
        str(PROFILE_DIR),
        headless=False,
        humanize=True,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(DEFAULT_FLOW_PROJECT_URL)

    print("\n" + "=" * 60, flush=True)
    print("Browser opened at Google Flow.", flush=True)
    print(f"Log in with your Google Pro account if prompted.", flush=True)
    print(f"Waiting {wait_s}s then saving profile automatically...", flush=True)
    print("=" * 60, flush=True)

    for remaining in range(wait_s, 0, -5):
        print(f"  {remaining}s remaining...", flush=True)
        time.sleep(5)

    ctx.close()
    logger.info("browser_imagen.setup_done", profile=str(PROFILE_DIR))
    print("Profile saved. Future runs won't need login.", flush=True)


# ─── DOM helpers (run inside asyncio.to_thread) ───────────────────────────────
# Selectors derived from live DOM inspection of labs.google/fx/tools/flow
# Input:   INPUT aria-label="Văn bản có thể chỉnh sửa"  OR  DIV[contenteditable] class sc-a8ba1f43-0
# Generate: button whose innerText contains both "arrow_forward" AND "Tạo"
#            (distinguishes from sidebar "add_2\nTạo" button)

def _find_prompt_input(page: object) -> object | None:
    """Find the Flow prompt input: aria-label 'Văn bản có thể chỉnh sửa' or contenteditable div."""
    selectors = [
        # Primary: aria-label from live inspection
        'input[aria-label="Văn bản có thể chỉnh sửa"]',
        # Secondary: contenteditable DIV in same styled-component as generate button
        'div[contenteditable="true"][class*="sc-a8ba1f43"]',
        'div[contenteditable="true"][class*="djaQmW"]',
        # Fallback
        'div[contenteditable="true"]',
        '[role="textbox"]',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=5_000)
            return el
        except Exception:
            continue
    return None


def _find_generate_button(page: object) -> object | None:
    """Find the 'arrow_forward / Tạo' submit button (not the 'add_2 / Tạo' sidebar button)."""
    # Use JS to distinguish — button text contains "arrow_forward" AND "Tạo"
    try:
        clicked = page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button'));
                const btn = btns.find(b =>
                    b.innerText.includes('arrow_forward') && b.innerText.includes('T')
                );
                return btn ? btn.outerHTML.substring(0, 100) : null;
            }
        """)
        if clicked:
            # Return a locator that matches it
            return page.locator('button').filter(has_text="arrow_forward").last
    except Exception:
        pass

    # Fallback: last button on page (generate is rightmost in input bar)
    try:
        el = page.locator("button").last
        el.wait_for(state="visible", timeout=3_000)
        return el
    except Exception:
        pass

    return None


def _get_media_images_before(page: object) -> set[str]:
    """Return generated image URLs in the project — excludes profile pic and SVG placeholders.

    From live inspection:
    - Profile pic: lh3.googleusercontent.com/a/ACg8oc...  (path starts with /a/)
    - Placeholder:  labs.google/fx/pinhole/flower-placeholder.svg
    - Generated:    lh3.googleusercontent.com/... (without /a/ prefix) or other CDN
    """
    try:
        srcs = page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('img');
                return Array.from(imgs)
                    .map(i => i.src)
                    .filter(s =>
                        s.length > 10 &&
                        !s.includes('.svg') &&
                        !s.includes('/a/ACg') &&   // profile picture pattern
                        !s.includes('placeholder') &&
                        (s.includes('googleusercontent') || s.includes('ggpht') ||
                         s.includes('googleapis') || s.includes('labs.google'))
                    );
            }
        """)
        return set(srcs or [])
    except Exception:
        return set()


def _wait_for_new_image(
    page: object,
    before: set[str],
    timeout_s: float = GENERATION_TIMEOUT_S,
) -> str | None:
    """Poll until a new image URL appears that wasn't in `before`. Return src."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            current = _get_media_images_before(page)
            new = current - before
            if new:
                return next(iter(new))
        except Exception:
            pass
        time.sleep(2.0)
    return None


def _download_image(page: object, src: str) -> bytes | None:
    """Download image bytes using the page's authenticated session."""
    # Method 1: fetch with credentials
    try:
        b64 = page.evaluate(
            """async (url) => {
                try {
                    const r = await fetch(url, {credentials: 'include'});
                    if (!r.ok) return null;
                    const buf = await r.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let bin = '';
                    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                    return btoa(bin);
                } catch(e) { return null; }
            }""",
            src,
        )
        if b64:
            return base64.b64decode(b64)
    except Exception:
        pass

    # Method 2: canvas extraction
    try:
        b64 = page.evaluate(
            """(url) => new Promise(resolve => {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                img.onload = () => {
                    const c = document.createElement('canvas');
                    c.width = img.naturalWidth; c.height = img.naturalHeight;
                    c.getContext('2d').drawImage(img, 0, 0);
                    resolve(c.toDataURL('image/png').split(',')[1]);
                };
                img.onerror = () => resolve(null);
                img.src = url;
            })""",
            src,
        )
        if b64:
            return base64.b64decode(b64)
    except Exception:
        pass

    return None


def _submit_via_keyboard(page: object) -> None:
    """Fallback: submit by pressing Enter in the input."""
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass


def _click_generate_via_js(page: object) -> bool:
    """Click the 'arrow_forward / Tạo' generate button via JS.

    From live DOM inspection:
    - Generate button innerText = 'arrow_forward\\nTạo'
    - Sidebar add button innerText = 'add_2\\nTạo'  ← must NOT click this
    """
    try:
        clicked = page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button'));
                // Match: innerText has 'arrow_forward' (not 'add_2')
                const genBtn = btns.find(b => {
                    const t = b.innerText || '';
                    return t.includes('arrow_forward') && t.includes('T');
                });
                if (genBtn) { genBtn.click(); return true; }

                // Fallback: last button on the page (generate is rightmost)
                if (btns.length > 0) {
                    btns[btns.length - 1].click();
                    return true;
                }
                return false;
            }
        """)
        return bool(clicked)
    except Exception:
        return False


# ─── Core scene generator ─────────────────────────────────────────────────────

def _generate_one_flow(
    page: object,
    prompt: str,
    out_path: Path,
    scene_idx: int,
) -> tuple[bool, str]:
    """Generate one image via Google Flow. Runs synchronously (called via to_thread)."""
    try:
        # Snapshot existing images before generation
        before = _get_media_images_before(page)

        # Find prompt input
        input_el = _find_prompt_input(page)
        if not input_el:
            return False, "Prompt input not found — check profile login and project URL"

        # Clear and type prompt
        input_el.click()
        # Select all and replace
        input_el.fill("")
        time.sleep(0.3)
        input_el.type(prompt, delay=30)   # humanize: ~30ms per char
        time.sleep(0.5)

        # Try clicking the generate button
        gen_btn = _find_generate_button(page)
        submitted = False

        if gen_btn:
            try:
                gen_btn.click()
                submitted = True
            except Exception:
                pass

        if not submitted:
            submitted = _click_generate_via_js(page)

        if not submitted:
            # Final fallback: Enter key
            _submit_via_keyboard(page)

        # Wait for new image to appear
        new_src = _wait_for_new_image(page, before, timeout_s=GENERATION_TIMEOUT_S)
        if not new_src:
            return False, f"No new image appeared after {GENERATION_TIMEOUT_S}s"

        # Download
        img_bytes = _download_image(page, new_src)
        if not img_bytes:
            return False, f"Failed to download image from {new_src[:80]}"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        logger.info("browser_imagen.saved", scene=scene_idx, bytes=len(img_bytes), path=str(out_path))
        return True, ""

    except Exception as exc:
        return False, str(exc)[:300]


# ─── Batch entry point ────────────────────────────────────────────────────────

def _run_browser_session(
    scenes: list[dict],
    images_dir: Path,
    flow_project_url: str,
    headless: bool,
    channel_id: str,
    topic: str,
) -> list[SceneImage]:
    """Run entire browser session synchronously in one thread.

    Playwright sync API uses greenlets internally — ALL page calls MUST stay
    in the same OS thread.  Never split calls across asyncio.to_thread().
    """
    from cloakbrowser import launch_persistent_context  # type: ignore[import-untyped]

    ctx = launch_persistent_context(
        str(PROFILE_DIR),
        headless=headless,
        humanize=True,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    try:
        logger.info("browser_imagen.navigating", url=flow_project_url)
        page.goto(flow_project_url)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        time.sleep(2.0)  # let SPA hydrate

        results: list[SceneImage] = []
        t0 = time.time()

        for i, scene in enumerate(scenes):
            prompt = scene.get("visual_prompt", "").strip()
            out_path = images_dir / f"scene_{i:03d}.png"

            if not prompt:
                results.append(SceneImage(
                    scene_index=i, segment=scene.get("segment", ""),
                    voiceover=scene.get("voiceover", ""), visual_prompt="",
                    image_path="", status="skipped",
                ))
                continue

            logger.info(
                "browser_imagen.generating",
                scene=i, total=len(scenes),
                prompt=prompt[:70],
            )

            ok, err = _generate_one_flow(page, prompt, out_path, i)

            results.append(SceneImage(
                scene_index=i,
                segment=scene.get("segment", ""),
                voiceover=scene.get("voiceover", ""),
                visual_prompt=prompt,
                image_path=str(out_path) if ok else "",
                status="done" if ok else "failed",
            ))

            if not ok:
                logger.error("browser_imagen.scene_failed", scene=i, error=err)

            if i < len(scenes) - 1:
                time.sleep(SCENE_DELAY_S)

        elapsed = time.time() - t0
        done   = sum(1 for r in results if r["status"] == "done")
        failed = sum(1 for r in results if r["status"] == "failed")
        logger.info(
            "browser_imagen.batch_done",
            channel_id=channel_id, topic=topic,
            done=done, failed=failed,
            elapsed_s=round(elapsed, 1),
            cost_usd=0.0,
        )
        return results

    finally:
        try:
            ctx.close()
        except Exception:
            pass


async def generate_images_for_script_browser(
    script_json_path: str | Path,
    *,
    flow_project_url: str = DEFAULT_FLOW_PROJECT_URL,
    headless: bool = True,
    max_scenes: int | None = None,
) -> list[SceneImage]:
    """Generate images for every scene in a script JSON using Google Flow.

    Args:
        script_json_path:  Path to script .json from Phase 2.
        flow_project_url:  Google Flow project URL (with Pro subscription).
        headless:          Run headless (default). Set False to debug.
        max_scenes:        Cap scenes (None = all).

    Returns:
        List of SceneImage results.
    """
    if not PROFILE_DIR.exists():
        raise RuntimeError(
            "Browser profile not found. Run setup:\n"
            "  python -c \"import asyncio; from omnicast.media.browser_imagen "
            "import setup_profile; asyncio.run(setup_profile())\""
        )

    script_path = Path(script_json_path)
    if not script_path.exists():
        raise FileNotFoundError(f"Script JSON not found: {script_path}")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    channel_id: str = data.get("channel_id", "unknown")
    topic: str = data.get("topic", "unknown")
    scenes: list[dict] = data.get("scenes", [])

    if not scenes:
        logger.warning("browser_imagen.no_scenes", path=str(script_path))
        return []

    if max_scenes:
        scenes = scenes[:max_scenes]

    images_dir = script_path.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Run entire browser session in one dedicated thread — greenlet safety
    return await asyncio.to_thread(
        _run_browser_session,
        scenes, images_dir, flow_project_url, headless, channel_id, topic,
    )
