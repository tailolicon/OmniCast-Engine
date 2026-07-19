"""Flow probe — how to switch a NEW project from 'Tác nhân' (Agent) to image gen.

New projects open in Agent mode (chat/thinking), not the image generator. This
creates a fresh project, dumps the bottom-bar controls, clicks the 'Tác nhân'
toggle, and re-dumps to find how the image model chip (Nano Banana + aspect)
appears. No generation. Usage:
    python -X utf8 scripts/flow_probe_agent.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = "https://labs.google/fx/vi/tools/flow"

_JS = r"""
() => {
  const vis=(el)=>!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  return [...document.querySelectorAll('button,[role=button],[role=tab],[role=switch],[aria-pressed]')]
    .filter(vis)
    .map(e=>({tag:e.tagName.toLowerCase(), text:(e.innerText||'').trim().slice(0,40),
              aria:e.getAttribute('aria-label')||'', pressed:e.getAttribute('aria-pressed')||'',
              id:e.id||''}))
    .filter(e=>e.text||e.aria);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    pd = Path(args.profile)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(pd), headless=False, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1500, "height": 950})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("[1/5] create new project", flush=True)
        page.goto(HOME, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(5000)
        page.locator('button:has-text("Dự án mới")').first.click(timeout=8000)
        for _ in range(20):
            page.wait_for_timeout(1000)
            if "/project/" in page.url:
                break
        page.wait_for_timeout(4000)
        print("   url", page.url, flush=True)

        before = page.evaluate(_JS)
        page.screenshot(path=str(pd / "agent_before.png"))

        print("[2/5] click 'Tác nhân' toggle", flush=True)
        for sel in ('button:has-text("Tác nhân")', '[role=switch]:has-text("Tác nhân")'):
            loc = page.locator(sel)
            if loc.count():
                try:
                    loc.first.click(timeout=5000); print("   clicked", sel, flush=True); break
                except Exception as e:
                    print("   fail", str(e)[:50], flush=True)
        page.wait_for_timeout(2500)
        after = page.evaluate(_JS)
        page.screenshot(path=str(pd / "agent_after.png"))

        (pd / "agent_probe.json").write_text(
            json.dumps({"url": page.url, "before": before, "after": after},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[3/5] before={len(before)} after={len(after)} saved agent_probe.json", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
