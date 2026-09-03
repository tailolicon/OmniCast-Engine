"""Obtain anonymous Douyin cookies with a real browser.

Douyin answers unsigned/uncookied detail requests with an empty HTTP 200 — a
success status carrying no body, which is its anti-bot reply rather than an
error (observed on `/aweme/v1/web/aweme/detail/`, 3 attempts exhausted). The
vendored downloader can sign requests but cannot mint the cookies the signature
is checked against: it only ever *reads* cookies from a file.

Loading `douyin.com` once in a browser is enough. The site plants `ttwid`,
`odin_tt`, `passport_csrf_token` and a real `msToken` on first visit, and those
are sufficient for public video detail — no login, no account.

Cookies are cached on disk because the handshake costs a browser launch.
`ttwid` is long-lived; `msToken` rotates, but the vendored `MsTokenManager`
regenerates that one per request anyway.
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DOUYIN_HOME = "https://www.douyin.com/"

# The set that makes a detail call work. `ttwid` is the one that actually
# matters; the others come along with it and are checked by the vendored
# CookieManager's own validation.
REQUIRED_COOKIES = ("ttwid",)
USEFUL_COOKIES = ("ttwid", "odin_tt", "passport_csrf_token", "msToken", "s_v_web_id")

# ttwid is issued with a multi-month expiry, but refetching weekly keeps the
# bundle from going stale alongside whatever else Douyin rotates.
CACHE_TTL_SECONDS = 7 * 24 * 3600

BROWSER_TIMEOUT_MS = 45_000


class CookieBootstrapError(RuntimeError):
    """Raised when a browser cannot produce usable Douyin cookies."""


def _read_cache(cache_path: Path) -> dict[str, str] | None:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(payload.get("fetched_at", 0)) > CACHE_TTL_SECONDS:
        return None
    cookies = payload.get("cookies") or {}
    if not all(cookies.get(name) for name in REQUIRED_COOKIES):
        return None
    return dict(cookies)


def _write_cache(cache_path: Path, cookies: dict[str, str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"fetched_at": time.time(), "cookies": cookies}, indent=2),
        encoding="utf-8",
    )


def _harvest(headless: bool) -> dict[str, str]:
    """Run the browser handshake, from sync or async callers alike.

    `fetch_video` is a coroutine, and Playwright's sync API refuses to run
    inside a live event loop. Hopping to a worker thread — which has no loop of
    its own — keeps a single entry point instead of forcing every caller to
    know which world it is in.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _harvest_blocking(headless)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="douyin-cookies") as pool:
        return pool.submit(_harvest_blocking, headless).result()


def _harvest_blocking(headless: bool) -> dict[str, str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise CookieBootstrapError(
            "playwright not installed — run `pip install playwright` and "
            "`playwright install chromium`, or pass cookies explicitly"
        ) from exc

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.goto(DOUYIN_HOME, timeout=BROWSER_TIMEOUT_MS, wait_until="domcontentloaded")
            # The cookie plant happens on the first XHR wave, not at DOM ready.
            page.wait_for_timeout(4000)
            jar = {c["name"]: c["value"] for c in context.cookies()}
        finally:
            browser.close()

    return {name: jar[name] for name in USEFUL_COOKIES if jar.get(name)}


def ensure_cookies(
    cache_path: Path,
    *,
    force: bool = False,
    headless: bool = True,
) -> dict[str, str]:
    """Return usable Douyin cookies, fetching them with a browser if needed.

    Falls back to a visible browser when headless comes back empty — Douyin
    fingerprints headless Chrome, and a visible window is the same trick the
    Flow provider already relies on.
    """
    if not force:
        cached = _read_cache(cache_path)
        if cached:
            return cached

    cookies = _harvest(headless=headless)
    if not all(cookies.get(name) for name in REQUIRED_COOKIES):
        if headless:
            cookies = _harvest(headless=False)
        if not all(cookies.get(name) for name in REQUIRED_COOKIES):
            raise CookieBootstrapError(
                f"Browser visit to {DOUYIN_HOME} produced no ttwid "
                f"(got: {sorted(cookies)}). Supply cookies manually instead."
            )

    _write_cache(cache_path, cookies)
    return cookies
