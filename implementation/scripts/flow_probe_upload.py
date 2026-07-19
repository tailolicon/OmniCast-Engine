"""Flow probe — learn the image-upload (first-frame) flow for img2vid.

autovio-style video = scene image -> image-to-video clip. In Flow that means
attaching an image as the first frame, switching to Veo video, prompting motion.
This probe discovers: the add-media control, any <input type=file>, and the
menu/options shown, so we can wire FlowProvider.convert() as true img2vid.

No credit cost (no generation). Usage:
    python -X utf8 scripts/flow_probe_upload.py --project <FLOW_PROJECT_URL>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARVEST_JS = r"""
() => {
  const vis = (el) => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  const fileInputs = [...document.querySelectorAll('input[type=file]')].map(e => ({
    accept: e.getAttribute('accept')||'', name: e.getAttribute('name')||'',
    id: e.id||'', hidden: !vis(e),
  }));
  const items = [...document.querySelectorAll('[role=menuitem],[role=option],button,li,a')]
    .filter(vis)
    .map(e => ({tag:e.tagName.toLowerCase(), role:e.getAttribute('role')||'',
                text:(e.innerText||'').trim().slice(0,60), testId:e.getAttribute('data-testid')||''}))
    .filter(e => e.text);
  return {fileInputs, items};
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
        print(f"[1/4] Open project", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(6000)

        before = page.evaluate(_HARVEST_JS)
        print(f"[2/4] file inputs (initial): {len(before['fileInputs'])}", flush=True)

        # Try to open the add-media control (prompt-bar '+' / 'Thêm nội dung nghe nhìn').
        print("[3/4] Click add-media control", flush=True)
        clicked = False
        for pat in ("Thêm nội dung", "add\n", "Thêm", "add"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.first.click(timeout=6000)
                    clicked = True
                    print(f"      clicked via '{pat}'", flush=True)
                    break
                except Exception as e:
                    print(f"      '{pat}' failed: {str(e)[:60]}", flush=True)
        page.wait_for_timeout(2000)

        after = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_upload.png"), full_page=False)
        out = profile_dir / "flow_upload.json"
        out.write_text(json.dumps({"clicked": clicked, "before": before, "after": after},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[4/4] file inputs after: {len(after['fileInputs'])}; items: {len(after['items'])}", flush=True)
        print(f"      saved {out}", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
