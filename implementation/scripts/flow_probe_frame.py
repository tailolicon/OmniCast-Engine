"""Flow probe — find the Veo first-frame slot in Video mode.

Switches the generator to Video (Veo) then dumps the prompt-bar controls +
screenshot, so we can see how to attach an image as the first frame (img2vid).
No generation. Usage:
    python -X utf8 scripts/flow_probe_frame.py --project <URL>
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
  for (const el of document.querySelectorAll('button,[role=button],[role=menuitem],input,label,[role=tab]')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    out.push({tag:el.tagName.toLowerCase(), role:el.getAttribute('role')||'',
              text:(el.innerText||'').trim().slice(0,50),
              aria:el.getAttribute('aria-label')||'',
              type:el.getAttribute('type')||'', accept:el.getAttribute('accept')||'',
              y:Math.round(r.top)});
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

        # Switch to Video (Veo) mode.
        print("[2/4] Switch to Video mode", flush=True)
        for pat in ("crop_", "Imagen", "Nano Banana", "Veo"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.last.click(timeout=6000); page.wait_for_timeout(800); break
                except Exception:
                    pass
        vid = page.locator('button[role="tab"][id$="-trigger-VIDEO"]')
        if not vid.count():
            vid = page.get_by_role("tab", name="Video")
        if vid.count():
            vid.first.click(); page.wait_for_timeout(600)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1500)

        print("[3/4] Harvest prompt-bar controls (Video mode)", flush=True)
        items = page.evaluate(_HARVEST_JS)
        # Keep bottom-area controls (prompt bar) — the frame slot lives there.
        bottom = [e for e in items if e["y"] > 760]
        page.screenshot(path=str(profile_dir / "flow_frame.png"))
        (profile_dir / "flow_frame.json").write_text(
            json.dumps({"bottom": bottom, "all_count": len(items)}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        print(f"[4/4] bottom controls={len(bottom)}; saved flow_frame.json/png", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
