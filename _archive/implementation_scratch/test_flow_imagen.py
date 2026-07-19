"""Live test: Generate one image via Google Flow and save locally.

Run:
    .venv\Scripts\python test_flow_imagen.py

Step 1: Browser opens (visible). Log into Google if prompted (~60s).
Step 2: Script auto-generates a test image and saves to output/test_flow_image.png
"""

import sys
import time
from pathlib import Path

# Force UTF-8 output so Vietnamese strings don't crash on cp1252 consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

PROFILE_DIR = ROOT / "output" / "browser_profile"
FLOW_URL = "https://labs.google/fx/vi/tools/flow/project/50aa9955-5742-47c2-8571-13083c4c1557"
OUT_IMAGE = ROOT / "output" / "test_flow_image.png"
DEBUG_SHOT = ROOT / "output" / "debug_screenshot.png"
LOGIN_WAIT_S = 60   # seconds for user to log in if needed
SPA_EXTRA_WAIT_S = 10  # extra wait after networkidle for SPA hydration

TEST_PROMPT = (
    "Photorealistic 16:9 cinematic shot: elderly couple sitting on a porch "
    "watching a golden sunset, warm light, shallow depth of field"
)


def _safe_print(*args, **kwargs):
    """Print with unicode errors replaced — safe on cp1252 consoles."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        print(text.encode("ascii", errors="replace").decode("ascii"), **kwargs)


def _get_generated_imgs(page):
    """Get generated image URLs — exclude profile pic, SVGs, and placeholders.

    Captures:
    - blob: URLs (in-browser generated images)
    - googleusercontent / ggpht / googleapis CDN images
    - Any img with naturalWidth > 100 (real image, not icon/placeholder)
    """
    try:
        return set(page.evaluate("""
            () => {
                const imgs = Array.from(document.querySelectorAll('img'));
                return imgs
                    .map(i => ({src: i.src || i.currentSrc || '', w: i.naturalWidth, h: i.naturalHeight}))
                    .filter(i =>
                        i.src.length > 10 &&
                        !i.src.includes('.svg') &&
                        !i.src.includes('/a/ACg') &&
                        !i.src.includes('placeholder') &&
                        !i.src.includes('favicon') &&
                        (
                            i.src.startsWith('blob:') ||
                            i.w > 100 ||   // any real-size image
                            i.src.includes('googleusercontent') ||
                            i.src.includes('ggpht') ||
                            i.src.includes('googleapis') ||
                            i.src.includes('labs.google/') ||
                            i.src.includes('gstatic')
                        )
                    )
                    .map(i => i.src);
            }
        """) or [])
    except Exception:
        return set()


def _get_all_imgs(page):
    """Get ALL visible img srcs for debugging."""
    try:
        return page.evaluate("""
            () => Array.from(document.querySelectorAll('img'))
                .map(i => ({src: i.src.substring(0, 100), w: i.naturalWidth, h: i.naturalHeight}))
                .filter(i => i.src.length > 5)
        """) or []
    except Exception:
        return []


def run_test():
    from cloakbrowser import launch_persistent_context  # type: ignore

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}", flush=True)
    print("Opening Google Flow in browser...", flush=True)
    print(f"If not logged in -> log into Google within {LOGIN_WAIT_S}s", flush=True)
    print(f"{'='*60}\n", flush=True)

    ctx = launch_persistent_context(
        str(PROFILE_DIR),
        headless=False,
        humanize=True,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    try:
        # Navigate to Flow project
        print(f"Navigating to: {FLOW_URL}", flush=True)
        page.goto(FLOW_URL)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass

        # Wait for login if needed (only relevant on first run)
        print(f"Waiting {LOGIN_WAIT_S}s for login / page load...", flush=True)
        for i in range(LOGIN_WAIT_S, 0, -5):
            print(f"  {i}s remaining...", flush=True)
            time.sleep(5)

        # Poll until SPA renders the Flow project editor (up to 90s extra)
        print("Waiting for Flow project editor to render...", flush=True)
        editor_ready = False
        for attempt in range(45):  # 45 x 2s = 90s max
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass
            # Check if any interactive input is in the DOM
            has_input = page.evaluate("""
                () => {
                    const ce = document.querySelector('[contenteditable="true"]');
                    const tb = document.querySelector('[role="textbox"]');
                    const inp = document.querySelector('input[aria-label]');
                    return !!(ce || tb || inp);
                }
            """)
            if has_input:
                print(f"  Editor ready after {attempt*2}s extra wait", flush=True)
                editor_ready = True
                break
            # Also check if still showing loading spinner
            loading = page.evaluate("""
                () => {
                    const text = document.body ? document.body.innerText : '';
                    return text.includes('oad') && text.length < 200;
                }
            """)
            if attempt % 5 == 0:
                title = page.title()
                print(f"  {attempt*2}s: title={title}, has_input={has_input}, loading={loading}", flush=True)
            time.sleep(2)

        if not editor_ready:
            print("  WARNING: editor may not be ready, trying anyway...", flush=True)
        print("Page loaded.\n", flush=True)

        # Debug info
        print(f"  Page title: {page.title()}", flush=True)
        print(f"  Page URL:   {page.url}", flush=True)

        # Snapshot existing images
        before = _get_generated_imgs(page)
        print(f"Images in project before: {len(before)}", flush=True)

        # Dump all inputs/textboxes for debugging
        try:
            all_inputs = page.evaluate("""
                () => {
                    const inputs = Array.from(document.querySelectorAll(
                        'input, textarea, [contenteditable="true"], [role="textbox"]'
                    ));
                    return inputs.map(el => ({
                        tag: el.tagName,
                        type: el.type || '',
                        role: el.getAttribute('role') || '',
                        aria: el.getAttribute('aria-label') || '',
                        ce: el.getAttribute('contenteditable') || '',
                        cls: el.className.substring(0, 60),
                        visible: el.offsetParent !== null
                    }));
                }
            """)
            print(f"  Found {len(all_inputs)} input elements:", flush=True)
            for inp in all_inputs[:10]:
                _safe_print(f"    {inp}", flush=True)
        except Exception as e:
            print(f"  Could not dump inputs: {e}", flush=True)

        # Find prompt input
        _safe_print(f"Prompt: {TEST_PROMPT[:70]}...", flush=True)

        # Find the generation prompt input (bottom bar "Bạn muốn tạo gì?")
        # NOTE: input[aria-label="Văn bản có thể chỉnh sửa"] = PROJECT TITLE field — DO NOT USE
        # Actual prompt = div[role="textbox"] or div[contenteditable] with class djaQmW/sc-a8ba1f43
        input_el = None

        # JS: find the prompt div by role=textbox (visible, not the title input)
        js_sel = page.evaluate("""
            () => {
                // Prefer role=textbox (the bottom prompt bar)
                const tb = document.querySelector('[role="textbox"]');
                if (tb && tb.offsetParent !== null) return '[role="textbox"]';
                // Contenteditable div (not input tag — input tag is the title field)
                const ce = Array.from(document.querySelectorAll('div[contenteditable="true"]'))
                    .find(el => el.offsetParent !== null);
                if (ce) return 'div[contenteditable="true"]';
                return null;
            }
        """)
        if js_sel:
            try:
                el = page.locator(js_sel).first
                el.wait_for(state="visible", timeout=5_000)
                input_el = el
                print(f"  Found prompt via JS: {js_sel}", flush=True)
            except Exception:
                input_el = None

        # CSS fallback — ordered by specificity, never input[aria-label] (that's title field)
        if not input_el:
            selectors = [
                '[role="textbox"]',
                'div[contenteditable="true"][class*="djaQmW"]',
                'div[contenteditable="true"][class*="sc-a8ba1f43"]',
                'div[contenteditable="true"]',
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=5_000)
                    input_el = el
                    print(f"  Found prompt via: {sel}", flush=True)
                    break
                except Exception:
                    print(f"  Not found: {sel}", flush=True)
                    continue

        if not input_el:
            # Take screenshot for debugging
            try:
                page.screenshot(path=str(DEBUG_SHOT))
                print(f"  Debug screenshot saved: {DEBUG_SHOT}", flush=True)
            except Exception as e:
                print(f"  Screenshot failed: {e}", flush=True)
            # Dump page text
            try:
                body = page.evaluate("() => document.body.innerText.substring(0, 800)")
                body_safe = body.encode("ascii", errors="replace").decode("ascii")
                print(f"  Page text:\n{body_safe}", flush=True)
            except Exception as e:
                print(f"  Could not get body text: {e}", flush=True)
            print("FAILED: Could not find prompt input", flush=True)
            return

        # Fill prompt via clipboard paste (avoids keystroke timing analysis)
        import subprocess
        # Write prompt to clipboard via PowerShell
        try:
            ps_cmd = f'Set-Clipboard -Value "{TEST_PROMPT}"'
            subprocess.run(["powershell", "-Command", ps_cmd], check=True, capture_output=True)
            clipboard_ok = True
        except Exception as e:
            clipboard_ok = False
            print(f"  Clipboard failed: {e}", flush=True)

        input_el.click()
        time.sleep(1.0)
        # Clear existing
        input_el.press("Control+a")
        time.sleep(0.2)
        input_el.press("Delete")
        time.sleep(0.3)

        if clipboard_ok:
            # Paste from clipboard — looks like normal human paste action
            input_el.press("Control+v")
            print("  Filled via clipboard paste", flush=True)
        else:
            # Fallback: type slowly
            input_el.type(TEST_PROMPT, delay=80)
            print("  Filled via slow typing", flush=True)

        time.sleep(2.0)  # human pause before submitting

        # Verify
        try:
            entered = page.evaluate(
                "() => { const el = document.querySelector('[role=\"textbox\"]'); return el ? el.innerText.trim() : ''; }"
            )
            print(f"  Text entered ({len(str(entered))} chars): {str(entered)[:50]}", flush=True)
        except Exception:
            pass

        # Submit via Enter (confirmed to trigger generation)
        input_el.press("Enter")
        time.sleep(1.0)
        print("  Submitted via Enter", flush=True)

        # Wait for new image
        WAIT_S = 300
        print(f"Waiting for image generation (up to {WAIT_S}s)...", flush=True)
        deadline = time.time() + WAIT_S
        new_src = None
        screenshot_taken = False
        while time.time() < deadline:
            current = _get_generated_imgs(page)
            new = current - before
            if new:
                new_src = next(iter(new))
                print(f"  New image detected: {new_src[:80]}", flush=True)
                break
            elapsed = int(time.time() - (deadline - WAIT_S))
            print(f"  {elapsed}s / {WAIT_S}s -- waiting...", flush=True)
            # Take mid-generation screenshot at 30s to see if anything is happening
            if elapsed >= 30 and not screenshot_taken:
                try:
                    mid_shot = ROOT / "output" / "debug_mid_generation.png"
                    page.screenshot(path=str(mid_shot))
                    print(f"  Mid screenshot: {mid_shot}", flush=True)
                    screenshot_taken = True
                except Exception:
                    pass
            time.sleep(3)

        if not new_src:
            # Debug: screenshot + dump all images
            try:
                page.screenshot(path=str(DEBUG_SHOT))
                print(f"  Debug screenshot: {DEBUG_SHOT}", flush=True)
            except Exception:
                pass
            all_imgs = _get_all_imgs(page)
            print(f"  All imgs in DOM ({len(all_imgs)}):", flush=True)
            for img in all_imgs[:15]:
                print(f"    {img}", flush=True)
            print("FAILED: No image appeared after 120s", flush=True)
            return

        # Download image
        print("Downloading image...", flush=True)
        import base64
        try:
            b64 = page.evaluate(
                """async (url) => {
                    const r = await fetch(url, {credentials: 'include'});
                    if (!r.ok) return null;
                    const buf = await r.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let bin = '';
                    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                    return btoa(bin);
                }""",
                new_src,
            )
            img_bytes = base64.b64decode(b64) if b64 else None
        except Exception as e:
            print(f"  fetch failed: {e}", flush=True)
            img_bytes = None

        if img_bytes:
            OUT_IMAGE.parent.mkdir(parents=True, exist_ok=True)
            OUT_IMAGE.write_bytes(img_bytes)
            print(f"\n{'='*60}", flush=True)
            print(f"SUCCESS! Image saved: {OUT_IMAGE}", flush=True)
            print(f"Size: {len(img_bytes):,} bytes ({len(img_bytes)//1024} KB)", flush=True)
            print(f"{'='*60}\n", flush=True)
        else:
            print("FAILED: Could not download image bytes", flush=True)

    finally:
        ctx.close()
        print("Browser closed. Profile saved for future runs.", flush=True)


if __name__ == "__main__":
    run_test()
