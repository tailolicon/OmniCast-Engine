"""Flow probe — img2vid via the image detail view (animate a library image).

Hypothesis: clicking a generated library image opens a detail view with its own
generate bar + model chip; switching that chip to Video (Veo) makes the image
the first frame -> type motion prompt -> Tạo = image-to-video. This probe opens
the first generated image, switches to Video, and dumps the resulting UI.
No generation. Usage:
    python -X utf8 scripts/flow_probe_detail_video.py --project <URL>
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
  for (const el of document.querySelectorAll('button,[role=tab],[role=textbox],img,input')) {
    if (!vis(el)) continue;
    out.push({tag:el.tagName.toLowerCase(), role:el.getAttribute('role')||'',
              text:(el.innerText||'').trim().slice(0,46),
              aria:el.getAttribute('aria-label')||'',
              alt:el.getAttribute('alt')||'', type:el.getAttribute('type')||''});
  }
  return out.filter(e=>e.text||e.aria||e.alt||e.type==='file');
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

        print("[2/5] Open first generated image (detail view)", flush=True)
        tile = page.locator('img[alt="Hình ảnh được tạo"]').first
        tile.click(timeout=8000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(profile_dir / "flow_detail.png"))
        detail = page.evaluate(_HARVEST_JS)

        print("[3/5] Open model chip in detail, switch to Video", flush=True)
        switched = False
        for pat in ("crop_", "Nano Banana", "Imagen", "Veo"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.last.click(timeout=6000); page.wait_for_timeout(900); break
                except Exception:
                    pass
        vid = page.locator('button[role="tab"][id$="-trigger-VIDEO"]')
        if not vid.count():
            vid = page.get_by_role("tab", name="Video")
        if vid.count():
            try:
                vid.first.click(); switched = True; page.wait_for_timeout(800)
            except Exception:
                pass
        page.keyboard.press("Escape")
        page.wait_for_timeout(1500)

        print("[4/5] Harvest post-switch UI", flush=True)
        after = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_detail_video.png"))
        (profile_dir / "flow_detail.json").write_text(
            json.dumps({"switched_video": switched, "detail": detail, "after": after},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[5/5] detail={len(detail)} after={len(after)} switched={switched}", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
