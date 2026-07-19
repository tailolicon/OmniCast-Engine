"""Flow probe — locate the credit balance + per-generation cost in the UI.

Needed to build a credit-aware preflight: estimate total credits for a video
(shots x cost/clip) and abort BEFORE generating if the balance is insufficient.

No generation. Usage:
    python -X utf8 scripts/flow_probe_credits.py --project <URL>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Harvest any text node mentioning credits / numbers near the model + generate UI.
_HARVEST_JS = r"""
() => {
  const vis = (el) => !!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
  const kw = /credit|tín dụng|tin dung|lượt|luot|số dư|so du|available|còn lại|con lai|⚡|token|point/i;
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (!vis(el)) continue;
    if (el.children && el.children.length > 3) continue; // leaf-ish only
    const t = (el.innerText||'').trim();
    if (!t || t.length > 60) continue;
    const aria = el.getAttribute('aria-label')||'';
    const title = el.getAttribute('title')||'';
    if (kw.test(t+aria+title) || /\b\d{1,5}\b/.test(t)) {
      out.push({tag:el.tagName.toLowerCase(), text:t, aria, title});
    }
  }
  // de-dup
  const seen = new Set(); const uniq = [];
  for (const o of out) { const k=o.text+'|'+o.aria; if(!seen.has(k)){seen.add(k);uniq.push(o);} }
  return uniq;
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

        base = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_credits_base.png"))

        # Try hovering / clicking the PRO / account chip top-right to reveal balance.
        print("[2/4] Probe PRO/account area", flush=True)
        for pat in ("PRO", "Ultra", "Nâng cấp", "Upgrade"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.first.click(timeout=4000)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    pass
        after_pro = page.evaluate(_HARVEST_JS)
        page.screenshot(path=str(profile_dir / "flow_credits_pro.png"))

        out = profile_dir / "flow_credits.json"
        out.write_text(json.dumps({"base": base, "after_pro": after_pro},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[3/4] base nodes={len(base)} after_pro={len(after_pro)}", flush=True)
        print(f"[4/4] saved {out} + screenshots", flush=True)
        page.wait_for_timeout(2000)
        ctx.close()


if __name__ == "__main__":
    main()
