"""Flow probe/action — create a NEW Flow project and capture its URL.

Each video should live in its own fresh project (avoids hundreds of stale images
piling up in one project and confusing the newest-first result mapping). This
opens the Flow tools home, clicks 'new project', and prints the resulting URL.

    python -X utf8 scripts/flow_new_project.py            # probe + create
    python -X utf8 scripts/flow_new_project.py --probe     # dump buttons only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = "https://labs.google/fx/vi/tools/flow"

_HARVEST_JS = r"""
() => {
  const vis = (el)=>!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  return [...document.querySelectorAll('button,a,[role=button]')]
    .filter(vis)
    .map(e=>({tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,50),
              aria:e.getAttribute('aria-label')||'', href:e.getAttribute('href')||''}))
    .filter(e=>e.text||e.aria);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    ap.add_argument("--probe", action="store_true", help="dump buttons only, do not click")
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
        print(f"[1/4] Open Flow home: {HOME}", flush=True)
        page.goto(HOME, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(6000)

        items = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_home.png"))
        (profile_dir / "flow_home.json").write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[2/4] {len(items)} buttons; saved flow_home.json/png", flush=True)

        if args.probe:
            page.wait_for_timeout(1500); ctx.close(); return

        print("[3/4] Click 'new project'", flush=True)
        before_url = page.url
        clicked = False
        for pat in ("Dự án mới", "New project", "Tạo dự án", "Dự án", "New", "Tạo mới"):
            loc = page.locator(f'button:has-text("{pat}"), a:has-text("{pat}")')
            if loc.count():
                try:
                    loc.first.click(timeout=6000)
                    clicked = True
                    print(f"      clicked '{pat}'", flush=True)
                    break
                except Exception as e:
                    print(f"      '{pat}' failed: {str(e)[:50]}", flush=True)
        page.wait_for_timeout(6000)

        new_url = page.url
        page.screenshot(path=str(profile_dir / "flow_newproj.png"))
        print(f"[4/4] clicked={clicked} before={before_url}", flush=True)
        print(f"      NEW PROJECT URL: {new_url}", flush=True)
        if "/project/" in new_url and new_url != before_url:
            (profile_dir / "last_project_url.txt").write_text(new_url, encoding="utf-8")
            print("      saved last_project_url.txt", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
