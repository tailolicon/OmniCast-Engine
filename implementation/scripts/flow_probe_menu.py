"""Flow probe — open the model chip menu to learn how to switch to Veo.

No generation (no credit cost). Reuses the logged-in profile, opens the
project, clicks the model chip ("Nano Banana ..."), and harvests the popup
menu items so we can wire model switching (image Nano Banana <-> video Veo).

Usage:
    python -X utf8 scripts/flow_probe_menu.py --project <FLOW_PROJECT_URL>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARVEST_MENU_JS = r"""
() => {
  const vis = (el) => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  const sel = '[role=menuitem], [role=option], [role=menuitemradio], li, button';
  return [...document.querySelectorAll(sel)]
    .filter(vis)
    .map(e => ({
      tag: e.tagName.toLowerCase(),
      role: e.getAttribute('role')||'',
      text: (e.innerText||'').trim().slice(0,80),
      testId: e.getAttribute('data-testid')||'',
      id: e.id||'',
    }))
    .filter(e => e.text);
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
        print(f"[1/4] Open project: {args.project}", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(7000)

        # Dump all visible buttons first so we can see the current model chip text.
        buttons_before = page.evaluate(_HARVEST_MENU_JS)
        (profile_dir / "flow_buttons_before.json").write_text(
            json.dumps(buttons_before, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[2/4] {len(buttons_before)} buttons before; saved flow_buttons_before.json", flush=True)

        print("[3/4] Try click model chip", flush=True)
        clicked = False
        # The model chip renders an emoji + model name + aspect glyph; match loosely.
        for pat in ("Banana", "Veo", "crop_", "🍌"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.last.click(timeout=8000)
                    clicked = True
                    print(f"      clicked chip via '{pat}'", flush=True)
                    break
                except Exception as exc:
                    print(f"      '{pat}' click failed: {str(exc)[:80]}", flush=True)
        if not clicked:
            print("      [warn] no chip clicked; dumping current state anyway", flush=True)
        page.wait_for_timeout(1800)

        menu = page.evaluate(_HARVEST_MENU_JS)
        page.screenshot(path=str(profile_dir / "flow_menu.png"), full_page=False)
        out = profile_dir / "flow_menu.json"
        out.write_text(json.dumps(menu, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[4/4] Saved {out}  items={len(menu)}", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
