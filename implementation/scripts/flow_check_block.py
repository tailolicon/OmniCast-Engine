"""Quick Flow block probe — open the logged-in Flow profile, read the page text,
and report whether Google's 'unusual activity' / quota block is currently shown.
No generation. Usage: python -X utf8 scripts/flow_check_block.py"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FLOW_HOME = "https://labs.google/fx/vi/tools/flow"

BLOCK_KW = [
    "hoạt động bất thường", "unusual activity", "unusual traffic",
    "giới hạn tạo ảnh", "reached your limit", "generation limit",
    "daily limit", "quota", "limit for today",
]


def main() -> None:
    profile = str(ROOT / ".flow_profile")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile, headless=False, args=["--start-maximized"],
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(_FLOW_HOME, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)  # let SPA + any block banner render
        try:
            txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except Exception as e:
            txt = ""
            print("[err] read body failed:", e)
        low = txt.lower()
        hits = [k for k in BLOCK_KW if k in low]
        print("URL:", page.url)
        print("BODY_LEN:", len(txt))
        if hits:
            print("BLOCKED=YES  matched:", hits)
        else:
            print("BLOCKED=NO  (no block/quota keywords on page)")
        # show a small slice for eyeballing
        print("--- first 600 chars ---")
        print(txt[:600])
        ctx.close()


if __name__ == "__main__":
    main()
