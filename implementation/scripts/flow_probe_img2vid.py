"""Flow probe — test attaching an image as the first frame for img2vid (Veo).

Sets a local image on Flow's hidden input[type=file] (accept=image/*) and
observes whether it attaches as a video first-frame + what controls appear.
No generation (no credit). Usage:
    python -X utf8 scripts/flow_probe_img2vid.py --project <URL> --image <png>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARVEST_JS = r"""
() => {
  const vis = (el) => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  return [...document.querySelectorAll('[role=menuitem],button,[role=tab]')]
    .filter(vis)
    .map(e => ({text:(e.innerText||'').trim().slice(0,50), role:e.getAttribute('role')||'',
                aria:e.getAttribute('aria-label')||''}))
    .filter(e => e.text || e.aria);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    ap.add_argument("--project", required=True)
    ap.add_argument("--image", required=True)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    profile_dir = Path(args.profile)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir), headless=False, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1500, "height": 950},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("[1/4] Open project", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(6000)

        print("[2/4] Open add-media menu, click 'Tải ... lên', set file", flush=True)
        # Open the add menu, then the upload menuitem (which wires the file input).
        try:
            page.locator('button:has-text("Thêm nội dung")').first.click(timeout=6000)
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"      add-media click warn: {str(e)[:60]}", flush=True)

        # Set the file directly on the hidden image input (works even if hidden).
        finp = page.locator('input[type=file]').first
        try:
            finp.set_input_files(str(Path(args.image).resolve()), timeout=8000)
            print("      set_input_files OK", flush=True)
        except Exception as e:
            print(f"      set_input_files FAILED: {str(e)[:120]}", flush=True)
        page.wait_for_timeout(2500)

        # One-time consent modal: "Tôi đồng ý" (I agree).
        for pat in ("Tôi đồng ý", "đồng ý", "Agree", "I agree"):
            c = page.locator(f'button:has-text("{pat}")')
            if c.count():
                try:
                    c.first.click(timeout=4000)
                    print(f"      consent clicked '{pat}'", flush=True)
                    break
                except Exception:
                    pass
        page.wait_for_timeout(7000)

        print("[3/4] Harvest + screenshot", flush=True)
        items = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_img2vid.png"), full_page=False)
        (profile_dir / "flow_img2vid.json").write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[4/4] items={len(items)}; saved flow_img2vid.json/png", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
