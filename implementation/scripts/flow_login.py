"""Flow (labs.google/fx) — one-time login + DOM inspector.

Google Flow has no public API, so the pipeline drives its web UI with
Playwright + a *persistent* browser profile. Run this ONCE to log in with your
Google account (the session is saved into the profile dir) and to dump the
live DOM so we can lock down stable selectors for the FlowProvider.

Usage:
    python -X utf8 scripts/flow_login.py
    python -X utf8 scripts/flow_login.py --profile .flow_profile --url https://labs.google/fx/vi/tools/flow/

Steps it performs:
    1. Launch a real, visible Chrome window using a persistent profile dir.
    2. Open Flow. You log in manually (Google blocks headless/bot logins).
    3. Press ENTER in this terminal when you are on the Flow project page.
    4. It captures: screenshot, page title/url, and candidate input/button
       elements (with roles, text, placeholders, test-ids) into
       <profile>/flow_inspect.json — used to calibrate selectors.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# JS that harvests candidate interactive elements for selector calibration.
_HARVEST_JS = r"""
() => {
  const pick = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || '',
    role: el.getAttribute('role') || '',
    placeholder: el.getAttribute('placeholder') || '',
    ariaLabel: el.getAttribute('aria-label') || '',
    testId: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '',
    name: el.getAttribute('name') || '',
    id: el.id || '',
    text: (el.innerText || el.value || '').trim().slice(0, 80),
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  });
  const sel = 'textarea, input, button, [role=button], [role=textbox], [contenteditable=true]';
  return [...document.querySelectorAll(sel)]
    .map(pick)
    .filter(e => e.visible);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Flow login + DOM inspector")
    ap.add_argument("--profile", default=str(ROOT / ".flow_profile"))
    ap.add_argument("--url", default="https://labs.google/fx/vi/tools/flow/")
    ap.add_argument("--channel", default="chrome",
                    help="browser channel: 'chrome' (less bot-detected) or '' for bundled chromium")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    profile_dir = Path(args.profile)
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1500, "height": 950},
        )
        if args.channel:
            launch_kwargs["channel"] = args.channel
        try:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            print(f"[warn] channel '{args.channel}' failed ({exc}); using bundled chromium")
            launch_kwargs.pop("channel", None)
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"[1/3] Opening Flow: {args.url}", flush=True)
        page.goto(args.url, wait_until="domcontentloaded", timeout=120_000)

        print("\n[2/3] Log in with your Google account in the browser window.", flush=True)
        print("      Go to your Flow PROJECT page (where you type a prompt).", flush=True)
        print("      Auto-detecting the prompt box (up to 8 min)...", flush=True)

        # Auto-detect: poll for a visible prompt input on the project page.
        # No stdin needed — capture as soon as the editor appears, else timeout.
        prompt_sel = "textarea, [role=textbox], [contenteditable=true]"
        detected = False
        deadline_polls = 160  # 160 * 3s = 8 min
        for i in range(deadline_polls):
            try:
                loc = page.locator(prompt_sel)
                n = loc.count()
                for j in range(n):
                    try:
                        if loc.nth(j).is_visible():
                            detected = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            if detected:
                print(f"      [ok] prompt box detected after ~{i*3}s on {page.url}", flush=True)
                break
            # Grace capture: after ~30s, snapshot whatever is on screen so we get
            # selectors even if the prompt element is a non-standard widget.
            if i == 40:
                print(f"      [grace] 120s elapsed, capturing current page: {page.url}", flush=True)
                break
            page.wait_for_timeout(3000)

        page.wait_for_timeout(1500)

        shot = profile_dir / "flow_after_login.png"
        page.screenshot(path=str(shot), full_page=False)

        try:
            candidates = page.evaluate(_HARVEST_JS)
        except Exception as exc:
            candidates = [{"error": str(exc)}]

        info = {
            "url": page.url,
            "title": page.title(),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
        out = profile_dir / "flow_inspect.json"
        out.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\n[3/3] Saved:", flush=True)
        print(f"      screenshot : {shot}", flush=True)
        print(f"      DOM dump   : {out}  ({len(candidates)} elements)", flush=True)
        print(f"      profile    : {profile_dir}  (session persisted; reused by FlowProvider)", flush=True)
        # Keep the window open briefly so a just-completed login fully persists.
        page.wait_for_timeout(4000)
        ctx.close()


if __name__ == "__main__":
    main()
