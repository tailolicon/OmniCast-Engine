"""Flow probe — find the 'animate this image' (img2vid) action on a library tile.

Hovers then clicks the most-recent library image and harvests the action
buttons that appear (looking for 'Tạo video' / animate / first-frame). No
generation. Usage:
    python -X utf8 scripts/flow_probe_tile.py --project <URL>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARVEST_JS = r"""
() => {
  const vis = (el) => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  return [...document.querySelectorAll('button,[role=menuitem],[role=button],a')]
    .filter(vis)
    .map(e => ({text:(e.innerText||'').trim().slice(0,50),
                aria:e.getAttribute('aria-label')||'',
                title:e.getAttribute('title')||''}))
    .filter(e => e.text||e.aria||e.title);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    ap.add_argument("--project", required=True)
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
        print("[1/5] Open project", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(6000)

        tile = page.locator('img[alt="Hình ảnh được tạo"]').first
        if not tile.count():
            tile = page.locator('img').nth(1)
        box = tile.bounding_box()
        print(f"[2/5] Hover first tile @ {box}", flush=True)
        tile.hover()
        page.wait_for_timeout(1500)
        hover_items = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_tile_hover.png"))

        print("[3/5] Click tile", flush=True)
        try:
            tile.click(timeout=5000)
        except Exception as e:
            print(f"      click warn: {str(e)[:60]}", flush=True)
        page.wait_for_timeout(2500)
        click_items = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_tile_click.png"))

        out = profile_dir / "flow_tile.json"
        out.write_text(json.dumps({"hover": hover_items, "click": click_items},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[4/5] hover items={len(hover_items)} click items={len(click_items)}", flush=True)
        print(f"[5/5] saved {out} + flow_tile_hover.png / flow_tile_click.png", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
