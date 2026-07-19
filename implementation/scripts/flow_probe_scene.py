"""Flow probe — the 'Tạo cảnh' (create scene) video builder, Flow's img2vid home.

Flow organizes video around Scenes. The add-media menu has 'Tạo cảnh'. This
probe opens it and dumps the resulting UI (frame slots / first-frame upload /
Veo prompt) to see where an image becomes a video's first frame. No generation.
    python -X utf8 scripts/flow_probe_scene.py --project <URL>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARVEST_JS = r"""
() => {
  const vis = (el) => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  const out = [];
  for (const el of document.querySelectorAll('button,[role=tab],[role=menuitem],[role=textbox],input,label,h1,h2,h3')) {
    if (!vis(el)) continue;
    out.push({tag:el.tagName.toLowerCase(), role:el.getAttribute('role')||'',
              text:(el.innerText||'').trim().slice(0,50),
              aria:el.getAttribute('aria-label')||'', type:el.getAttribute('type')||'',
              accept:el.getAttribute('accept')||''});
  }
  return out.filter(e=>e.text||e.aria||e.type==='file');
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
        print("[1/4] Open project", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(6000)

        print("[2/4] Open add menu -> 'Tạo cảnh'", flush=True)
        try:
            page.locator('button:has-text("Thêm nội dung")').first.click(timeout=6000)
            page.wait_for_timeout(1000)
        except Exception as e:
            print("  add-menu warn:", str(e)[:50], flush=True)
        for pat in ("Tạo cảnh", "Tạo nhân vật", "cảnh"):
            loc = page.locator(f'[role=menuitem]:has-text("{pat}")')
            if not loc.count():
                loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.first.click(timeout=5000)
                    print(f"  clicked '{pat}'", flush=True)
                    break
                except Exception:
                    pass
        page.wait_for_timeout(3000)

        print("[3/4] Harvest scene builder UI", flush=True)
        items = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_scene.png"))
        (profile_dir / "flow_scene.json").write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[4/4] items={len(items)}; saved flow_scene.json/png", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
