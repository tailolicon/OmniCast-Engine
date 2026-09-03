"""NotebookLM — one-time login + DOM inspector (mirrors flow_login.py design).

NotebookLM has no consumer API, so the research runner drives its web UI with
Playwright + a persistent browser profile. Run this ONCE to log in with your
Google account; the session persists into the profile dir and is reused by
`notebook_research.browser_provider`.

DELIBERATELY SEPARATE from .flow_profile: two browser workers must never lock
one profile, and a dead Flow session must not take NotebookLM down (or vice
versa).

Usage:
    python -X utf8 scripts/notebooklm_login.py
    python -X utf8 scripts/notebooklm_login.py --profile output/notebooklm_profile
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
  const sel = 'textarea, input, button, [role=button], [role=textbox], ' +
              '[contenteditable=true], a[href], [role=tab], [role=listitem]';
  return [...document.querySelectorAll(sel)].map(pick).filter(e => e.visible);
}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="NotebookLM login + DOM inspector")
    ap.add_argument("--profile", default=str(ROOT / "output" / "notebooklm_profile"))
    ap.add_argument("--url", default="https://notebooklm.google.com/?hl=en")
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    profile_dir = Path(args.profile)
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--lang=en-US"],
            locale="en-US",   # fewer selector variants; VI aliases stay as fallback
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
        print(f"[1/3] Opening NotebookLM: {args.url}", flush=True)
        page.goto(args.url, wait_until="domcontentloaded", timeout=120_000)

        print("\n[2/3] Log in with your Google account in the browser window.", flush=True)
        print("      Waiting until the notebook list UI appears (up to 8 min)...", flush=True)

        # Signed-in NotebookLM shows a create-notebook affordance. Poll for it.
        import re as _re
        detected = False
        for i in range(160):  # 160 * 3s = 8 min
            try:
                for probe in (
                    page.get_by_role("button", name=_re.compile(r"create|new notebook|tạo", _re.I)),
                    page.locator("text=/create new|new notebook|tạo/i"),
                ):
                    try:
                        if probe.count() and probe.first.is_visible():
                            detected = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            if detected:
                print(f"      [ok] notebook UI detected after ~{i * 3}s on {page.url}", flush=True)
                break
            page.wait_for_timeout(3000)
        if not detected:
            print(f"      [grace] timeout — capturing current page anyway: {page.url}", flush=True)

        page.wait_for_timeout(1500)
        shot = profile_dir / "notebooklm_after_login.png"
        page.screenshot(path=str(shot), full_page=False)
        try:
            candidates = page.evaluate(_HARVEST_JS)
        except Exception as exc:
            candidates = [{"error": str(exc)}]
        out = profile_dir / "notebooklm_inspect.json"
        out.write_text(json.dumps({
            "url": page.url, "title": page.title(),
            "signed_in_detected": detected,
            "candidate_count": len(candidates), "candidates": candidates,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        print("\n[3/3] Saved:", flush=True)
        print(f"      screenshot : {shot}", flush=True)
        print(f"      DOM dump   : {out}  ({len(candidates)} elements)", flush=True)
        print(f"      profile    : {profile_dir}  (session persisted; reused by the runner)", flush=True)
        page.wait_for_timeout(4000)
        ctx.close()


if __name__ == "__main__":
    main()
