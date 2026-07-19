"""Flow probe — run one real image generation to learn the result DOM.

Reuses the persistent profile from flow_login.py (already logged in). Opens the
Flow project, types a prompt, clicks generate, waits for the result, then dumps
every media element (img/video src) + likely download controls so we can build
the FlowProvider's download step against real selectors.

Costs ~1 image credit. Usage:
    python -X utf8 scripts/flow_probe.py --project <FLOW_PROJECT_URL>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HARVEST_MEDIA_JS = r"""
() => {
  const abs = (u) => { try { return new URL(u, location.href).href; } catch { return u; } };
  const imgs = [...document.querySelectorAll('img')]
    .filter(e => (e.offsetWidth||e.offsetHeight))
    .map(e => ({src: abs(e.src), w: e.naturalWidth, h: e.naturalHeight, alt: e.alt||''}))
    .filter(e => e.src && !e.src.startsWith('data:image/svg'));
  const vids = [...document.querySelectorAll('video')]
    .map(e => ({src: abs(e.src||''), poster: abs(e.poster||''),
                srcChild: [...e.querySelectorAll('source')].map(s=>abs(s.src))}));
  const dlBtns = [...document.querySelectorAll('button,[role=button],a')]
    .filter(e => (e.offsetWidth||e.offsetHeight))
    .map(e => ({tag:e.tagName.toLowerCase(),
                text:(e.innerText||'').trim().slice(0,60),
                aria:e.getAttribute('aria-label')||'',
                href:e.getAttribute('href')||'',
                testId:e.getAttribute('data-testid')||''}))
    .filter(e => /download|tải|tai|save|lưu|export/i.test(e.text+e.aria+e.testId));
  return {imgs, vids, dlBtns};
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    ap.add_argument("--project", required=True, help="Flow project URL")
    ap.add_argument("--prompt", default="cinematic illustration of a glowing bitcoin "
                    "vault being drained, dramatic teal and orange lighting, highly detailed, 16:9")
    ap.add_argument("--wait", type=int, default=180, help="max seconds to wait for result")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    profile_dir = Path(args.profile)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1500, "height": 950},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"[1/5] Open project: {args.project}", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(4000)

        print("[2/5] Count media before generation", flush=True)
        before = page.evaluate("() => document.querySelectorAll('img,video').length")

        print("[3/5] Type prompt + click generate", flush=True)
        box = page.locator('[role="textbox"]').first
        box.click()
        box.fill(args.prompt) if box.evaluate("e=>e.tagName.toLowerCase()") == "textarea" else page.keyboard.type(args.prompt)
        page.wait_for_timeout(800)
        # Generate button = the one rendering the 'arrow_forward' material glyph.
        gen = page.locator('button:has-text("arrow_forward")').last
        if not gen.count():
            gen = page.get_by_role("button", name="Tạo").last
        gen.click()

        print(f"[4/5] Wait up to {args.wait}s for new media...", flush=True)
        result = None
        for i in range(args.wait // 3):
            page.wait_for_timeout(3000)
            now = page.evaluate("() => document.querySelectorAll('img,video').length")
            if now > before:
                page.wait_for_timeout(4000)  # let it settle/finish
                result = page.evaluate(_HARVEST_MEDIA_JS)
                print(f"      [ok] media grew {before}->{now} after ~{i*3}s", flush=True)
                break
        if result is None:
            print("      [warn] no new media detected; harvesting anyway", flush=True)
            result = page.evaluate(_HARVEST_MEDIA_JS)

        page.screenshot(path=str(profile_dir / "flow_probe.png"), full_page=False)
        out = profile_dir / "flow_probe.json"
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[5/5] Saved {out}  imgs={len(result.get('imgs',[]))} "
              f"vids={len(result.get('vids',[]))} dlBtns={len(result.get('dlBtns',[]))}", flush=True)
        page.wait_for_timeout(3000)
        ctx.close()


if __name__ == "__main__":
    main()
