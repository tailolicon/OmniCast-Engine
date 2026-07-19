"""Flow batch-order probe — learn result<->prompt ordering for parallel submit.

Fires TWO visually distinct prompts back-to-back (no waiting between), then once
results arrive downloads every NEW image in DOM order. Viewing the downloaded
files tells us how Flow orders results vs submission order, and whether each
prompt yields x1 or x2 images — needed to build a correct parallel batch mode.

No credit cost (Flow image gen is free on the plan). Usage:
    python -X utf8 scripts/flow_probe_batch.py --project <FLOW_PROJECT_URL>
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PROMPT_SEL = '[role="textbox"]'
_GENERATE_SEL = 'button:has-text("arrow_forward")'
_RESULT_IMG_SEL = 'img[alt="Hình ảnh được tạo"]'

PROMPTS = [
    "a single bright red apple on a plain white background, centered, studio photo",
    "a single glossy blue metallic cube on a plain black background, centered, studio render",
]


def _srcs(page):
    return page.eval_on_selector_all(_RESULT_IMG_SEL, "els => els.map(e => e.src)")


def _submit(page, prompt: str) -> None:
    box = page.locator(_PROMPT_SEL).first
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.type(prompt, delay=4)
    page.wait_for_timeout(500)
    gen = page.locator(_GENERATE_SEL).last
    gen.click()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    ap.add_argument("--project", required=True)
    ap.add_argument("--wait", type=int, default=240)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    profile_dir = Path(args.profile)
    out_dir = profile_dir / "batch_probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir), headless=False, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1500, "height": 950},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"[1/4] Open project", flush=True)
        page.goto(args.project, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(4000)

        before = set(_srcs(page))
        print(f"[2/4] Fire {len(PROMPTS)} prompts rapidly (submission order):", flush=True)
        for i, pr in enumerate(PROMPTS):
            _submit(page, pr)
            print(f"      submitted #{i}: {pr[:40]}", flush=True)
            page.wait_for_timeout(2500)  # brief gap, do NOT wait for completion

        print(f"[3/4] Wait up to {args.wait}s for results...", flush=True)
        new_ordered: list[str] = []
        for _ in range(args.wait // 3):
            page.wait_for_timeout(3000)
            cur = _srcs(page)  # DOM order
            new_ordered = [s for s in cur if s and s not in before]
            if len(new_ordered) >= len(PROMPTS):
                page.wait_for_timeout(4000)
                cur = _srcs(page)
                new_ordered = [s for s in cur if s and s not in before]
                break

        print(f"[4/4] {len(new_ordered)} new imgs (DOM order). Downloading...", flush=True)
        for idx, src in enumerate(new_ordered):
            r = ctx.request.get(src, timeout=120_000)
            (out_dir / f"dom_{idx}.png").write_bytes(r.body())
            print(f"      dom_{idx}.png  <- {src[-60:]}", flush=True)
        page.screenshot(path=str(out_dir / "batch_screen.png"))
        print(f"      saved to {out_dir}", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
