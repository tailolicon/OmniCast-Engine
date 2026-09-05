"""Flow (labs.google/fx) image/video provider via browser automation.

Google Flow has NO public API. This provider drives the Flow web UI with
Playwright using a *persistent* logged-in profile (seeded once by
scripts/flow_login.py). It is the "use my paid Flow plan to save cost" path:
generations consume the account's Flow credits instead of metered API billing.

Backed model in Flow's UI:
    - Image: "Nano Banana" (Imagen-class), ~1376x768 (16:9). Default chip.
    - Video: "Veo" (switch the model chip).

Caveats (honest): UI-coupled and fragile — if Google changes the Flow DOM the
selectors break; ToS gray area; runs a real visible Chrome (headless is
bot-detected); slow (image ~40s, Veo video minutes).

All Playwright sync calls run on a single dedicated worker thread (Playwright's
sync API is not asyncio-safe), and the logged-in browser context is reused
across generations for speed.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from omnicast.media.providers.image_gemini import MediaError
from omnicast.media.providers.interfaces import ModelOption

# Confirmed selectors (calibrated from a live logged-in Flow project, 2026-05).
_PROMPT_SEL = '[contenteditable="true"]'  # the agent-chat composer ("Bạn muốn tạo gì?")
_GENERATE_SEL = 'button:has-text("arrow_forward")'
# Result tiles: match by src host (locale-proof — the 09/2026 UI serves
# results from flow-content.google and the alt text changed again), with
# the old alt texts kept as fallbacks for stragglers.
_RESULT_IMG_SEL = ('img[src*="flow-content.google/image"], '
                   'img[alt="Tile displaying a user\'s image"], '
                   'img[alt*="enerated" i], img[alt="Hình ảnh được tạo"]')
_MODEL_CHIP_RE = r"Nano Banana|Veo"
# ENGLISH ONLY: every selector/mode-check in this file targets Flow's English
# UI. The old value pinned the Vietnamese locale path (/fx/vi/) and the account
# preference is Vietnamese too, so the composer said "Video · 8 giây" where the
# mode check expects "Video · 8s" — image mode never engaged (live 2026-09-04).
# ?hl=en overrides the account language per-request; browser --lang does not.
_FLOW_HOME = "https://labs.google/fx/tools/flow?hl=en"


def _with_hl_en(url: str) -> str:
    """Append hl=en to a Flow/labs URL (project URLs captured from page.url
    come back without it)."""
    if not url or "hl=en" in url:
        return url
    return url + ("&hl=en" if "?" in url else "?hl=en")
# UI is pinned to English via ?hl=en, but keep the Vietnamese texts as
# fallbacks in case a page slips through with the account locale.
_NEW_PROJECT_SEL = ('button:has-text("New project"), '
                    'button:has-text("Start Creating"), '
                    'a:has-text("New project"), '
                    'button:has-text("Dự án mới")')


class FlowBlocked(MediaError):
    """Flow tripped its anti-abuse / quota guard. The run MUST stop and wait it
    out — retrying or pushing more prompts only deepens the block. Kept distinct
    from a plain shortfall MediaError so callers can tell 'wait it out' apart from
    'a few flaky shots, keep going and fill them per scene'."""


class FlowModelQuota(FlowBlocked):
    """MODEL-SPECIFIC quota: 'Bạn đã dùng hết hạn mức... Nano Banana Pro. Hãy thử
    dùng một mô hình khác.' Unlike an account block, switching to Nano Banana 2
    fixes it immediately — the provider's fallback catches this and retries."""


class _FlowSession:
    """Single-thread owner of the persistent Playwright Chrome session."""

    # Map config ids → the model label shown in Flow's settings popover.
    # Labels as they appear in Flow's model dropdown (role=menuitem). Calibrated
    # 2026-05-31: options are "🍌 Nano Banana Pro", "🍌 Nano Banana 2", "Imagen 4"
    # (default = Imagen 4).
    _MODEL_LABELS = {
        "imagen4": "Imagen 4", "imagen-4": "Imagen 4", "imagen": "Imagen 4",
        "nano-banana": "Nano Banana 2", "nano_banana": "Nano Banana 2",
        "nano-banana-2": "Nano Banana 2", "nano-banana2": "Nano Banana 2",
        "nano banana 2": "Nano Banana 2", "nano banana": "Nano Banana 2",
        "nano-banana-pro": "Nano Banana Pro", "nano_banana_pro": "Nano Banana Pro",
        "nano banana pro": "Nano Banana Pro",
        "pro": "Nano Banana Pro",
    }

    def __init__(self, profile_dir: str, project_url: str, create_new: bool = False,
                 image_model: str = "", ref_images: list[str] | None = None) -> None:
        self._profile = profile_dir
        self._project = project_url
        self._create_new = create_new
        # Desired Flow image model (label). Empty = keep Flow's current default.
        # Unknown-but-nonempty names pass through verbatim: silently mapping
        # them to "" made every guard downstream think NO model was chosen
        # ('Nano Banana 2' with spaces fell through the slug table and the
        # quota guard treated the session as Pro).
        _key = (image_model or "").lower().strip()
        self._image_model = self._MODEL_LABELS.get(
            _key, (image_model or "").strip())
        # Ingredients (WS1 character consistency): reference images attached to
        # the composer so Nano Banana conditions every generation on the SAME
        # character — the root fix for per-frame face drift that the text-DNA
        # anchor alone cannot hold. Only existing files are kept.
        self._ref_images: list[str] = self._existing_refs(ref_images)
        self._ingredients_attached = False
        self._pw = None
        self._ctx = None
        self._page = None
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow")
        self._lock = threading.Lock()
        self._xlock_dir: Path | None = None  # cross-process Flow mutex (see below)

    # Flow caps ingredients per prompt; keep a safe margin (calibrated cap in
    # Flow's UI is small — 3 reference chips per prompt as of 2026-07).
    MAX_INGREDIENTS = 3

    @staticmethod
    def _existing_refs(ref_images: list[str] | None) -> list[str]:
        """Filter to existing, non-empty files, bounded by MAX_INGREDIENTS."""
        out: list[str] = []
        for r in ref_images or []:
            try:
                p = Path(r)
                if p.exists() and p.stat().st_size > 0:
                    out.append(str(p.resolve()))
            except Exception:
                continue
        return out[:_FlowSession.MAX_INGREDIENTS]

    def set_ref_images(self, ref_images: list[str] | None) -> None:
        """Swap the ingredient set (e.g. per-video anchor). Resets the attached
        flag so the next generation re-attaches the new chips."""
        refs = self._existing_refs(ref_images)
        if refs != self._ref_images:
            self._ref_images = refs
            self._ingredients_attached = False

    def submit(self, fn, *a):
        fut: Future = self._exec.submit(fn, *a)
        return fut.result()

    def _acquire_flow_xlock(self) -> None:
        """Cross-PROCESS Flow mutex — only one render may drive the single Chrome
        profile at a time (Chrome is single-instance per profile; two renders
        opening it collide). Concurrent renders WAIT here instead of crashing,
        so a batch can pipeline: while render A holds Flow (network-bound image
        gen), render B blocks here but render B's earlier CPU work already ran,
        and once A releases, B does images while A does TTS/compose. Atomic
        mkdir = the lock; a stale lock (dead owner PID) is reclaimed.
        Bypass with OMNICAST_FLOW_XLOCK=0."""
        import os as _os
        import time as _time
        if _os.environ.get("OMNICAST_FLOW_XLOCK", "1") == "0":
            return
        d = Path(self._profile).parent / ".flow_xlock"
        pidf = d / "owner.pid"
        waited = 0
        while True:
            try:
                d.mkdir(exist_ok=False)
                pidf.write_text(str(_os.getpid()), encoding="utf-8")
                self._xlock_dir = d
                return
            except FileExistsError:
                # stale? owner process gone → reclaim.
                try:
                    owner = int(pidf.read_text(encoding="utf-8").strip())
                    import ctypes
                    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, owner) \
                        if _os.name == "nt" else None
                    alive = bool(h) if _os.name == "nt" else True
                    if _os.name == "nt" and h:
                        ctypes.windll.kernel32.CloseHandle(h)
                    if not alive:
                        pidf.unlink(missing_ok=True); d.rmdir()
                        continue
                except Exception:
                    if waited > 900:  # 15 min: assume broken lock, force-reclaim
                        try:
                            pidf.unlink(missing_ok=True); d.rmdir()
                        except Exception:
                            pass
                        continue
                if waited == 0 or waited % 30 == 0:
                    print(f"      [flow] waiting for Flow lock ({waited}s)…", flush=True)
                _time.sleep(3); waited += 3

    def _release_flow_xlock(self) -> None:
        if self._xlock_dir is not None:
            try:
                (self._xlock_dir / "owner.pid").unlink(missing_ok=True)
                self._xlock_dir.rmdir()
            except Exception:
                pass
            self._xlock_dir = None

    # --- runs on the worker thread only ---
    def _ensure_page(self):
        if self._page is not None:
            return self._page
        self._acquire_flow_xlock()
        from playwright.sync_api import sync_playwright

        # STALE-LOCK CLEANUP: a hard-killed render leaves the Chrome profile's
        # Singleton* lock files behind, so the next launch dies with "Opening in
        # existing browser session … profile is already in use". No live browser
        # holds them now (this process is the only Flow driver), so remove them.
        try:
            _pf = Path(self._profile)
            for _lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                (_pf / _lock).unlink(missing_ok=True)
        except Exception:
            pass

        self._pw = sync_playwright().start()
        # LOCALE IS PINNED TO ENGLISH. Every selector and mode-check in this
        # file is written against Flow's English UI; a Vietnamese-locale
        # account rendered "Video · 8 giây" where the mode check expects
        # "Video · 8s", so the composer never left VIDEO mode and every image
        # batch died on "composer chip not found" (live 2026-09-04, twice).
        # Forcing Accept-Language/--lang keeps the page English regardless of
        # the Google account's language preference.
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self._profile,
            headless=False,
            channel="chrome",
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled",
                  "--lang=en-US", "--accept-lang=en-US",
                  # Headed Chrome must not steal the operator's focus: force
                  # Xwayland so --class applies, and a Hyprland rule parks
                  # class flow-render on a hidden special workspace silently
                  # (rule lives in ~/.config/hypr/hyprland.lua).
                  "--ozone-platform=x11", "--class=flow-render",
                  # Live-debug affordance: lets an operator attach a second
                  # CDP client mid-run to see what the page actually shows.
                  "--remote-debugging-port=9226"],
            viewport={"width": 1500, "height": 950},
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._hide_own_window()
        if self._create_new or not self._project:
            self._new_project(self._page)
        else:
            self._page.goto(_with_hl_en(self._project), wait_until="domcontentloaded", timeout=120_000)
            self._page.wait_for_timeout(4000)
        # Editor can take a few seconds to mount the prompt box after the project
        # URL resolves; wait for it so the first _type_prompt doesn't race-fail.
        try:
            self._page.wait_for_selector(_PROMPT_SEL, timeout=30_000)
        except Exception:
            print("[flow] warn: prompt textbox not visible after 30s", flush=True)
        self._dismiss_welcome_popup(self._page)
        return self._page

    def _hide_own_window(self) -> None:
        """Park this automation Chrome on a hidden Hyprland workspace so it
        never steals the operator's focus (live complaint 2026-09-05). The
        window maps a beat after launch and Chrome may re-activate itself, so
        dispatch a few times over the first seconds. No-op off Hyprland."""
        import shutil as _sh, subprocess as _sp, threading as _th, time as _t
        if not _sh.which("hyprctl"):
            return

        def _park():
            for _ in range(6):
                _sp.run(["hyprctl", "dispatch", "movetoworkspacesilent",
                         "special:flowrender,class:^(flow-render)$"],
                        capture_output=True, timeout=5)
                _t.sleep(1.5)

        _th.Thread(target=_park, daemon=True).start()

    def _dismiss_welcome_popup(self, page) -> None:
        """Radix UI changelog/welcome popups occasionally block the UI. If detected,
        programmatically remove the modal dialog and backdrop overlays from the DOM
        to restore pointer events to the underlying editor interface."""
        try:
            # Detect EITHER the changelog iframe or a leftover Radix backdrop —
            # after a first pass removes the iframe, the separate backdrop div
            # still intercepts clicks and a second pass must not no-op (live).
            iframe_sel = ('iframe[src*="changelogs"], '
                          'div[data-state="open"][data-aria-hidden="true"]')
            if page.locator(iframe_sel).count() > 0:
                print("[flow] Welcome/changelog popup detected. Dismissing it...", flush=True)
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(400)
                except Exception:
                    pass
                page.evaluate("""() => {
                    const dialog = document.querySelector('[role="dialog"]');
                    if (dialog) dialog.remove();
                    const overlays = document.querySelectorAll('[class*="sc-74a44e9a-0"], [class*="jDwSWX"]');
                    overlays.forEach(overlay => overlay.remove());
                    // Class names rotate every Flow build — also walk up from the
                    // changelog iframe itself and remove its whole overlay subtree.
                    document.querySelectorAll('iframe[src*="changelogs"]').forEach(f => {
                        let el = f, top = f;
                        while (el && el !== document.body) {
                            const pos = getComputedStyle(el).position;
                            if (pos === 'fixed' || pos === 'absolute') top = el;
                            el = el.parentElement;
                        }
                        top.remove();
                    });
                    // Radix marks BOTH the backdrop and the app root with
                    // data-aria-hidden — deleting every match removed the whole
                    // UI including the new-project button (live). The backdrop
                    // is an EMPTY div; the app root has children. Remove only
                    // empty ones, strip the attribute from the rest.
                    document.querySelectorAll('[data-radix-focus-guard]').forEach(el => el.remove());
                    document.querySelectorAll('div[data-aria-hidden="true"]').forEach(el => {
                        if (el.childElementCount === 0) {
                            el.remove();
                        } else {
                            el.removeAttribute('data-aria-hidden');
                            el.removeAttribute('aria-hidden');
                            el.style.pointerEvents = 'auto';
                        }
                    });

                    document.body.style.pointerEvents = 'auto';
                    document.body.style.overflow = 'auto';
                    document.documentElement.style.pointerEvents = 'auto';
                    document.documentElement.style.overflow = 'auto';
                    
                    document.querySelectorAll('[aria-hidden="true"]').forEach(el => {
                        el.removeAttribute('aria-hidden');
                    });
                }""")
                page.wait_for_timeout(1000)
        except Exception as exc:
            print(f"[flow] warn: welcome popup dismissal failed ({exc})", flush=True)

    def _new_project(self, page) -> None:
        """Create a fresh Flow project (one per video) so old images don't pile
        up and confuse the newest-first result mapping. Sets self._project."""
        page.goto(_FLOW_HOME, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(5000)
        # The changelog popup also appears on the HOME page and its overlay
        # intercepts the new-project click (live: 08-26 changelog iframe).
        self._dismiss_welcome_popup(page)
        before = page.url
        # 08/2026 redesign: labs.google/fx/.../flow can land on a MARKETING page
        # whose only entry is "Create with Google Flow" (no "Dự án mới"). Click
        # through it first; if that lands on accounts.google.com the stored
        # session has expired — fail with a message that says exactly that
        # instead of a generic click timeout (operator must log in manually;
        # credentials are never entered by automation).
        if page.locator(_NEW_PROJECT_SEL).count() == 0:
            entry = page.locator(
                'button:has-text("Create with Google Flow"), '
                'a:has-text("Create with Google Flow")')
            if entry.count() > 0:
                entry.first.click(timeout=8000)
                page.wait_for_timeout(6000)
                if "accounts.google.com" in page.url:
                    raise FlowBlocked(
                        "Flow session expired: entry button led to Google "
                        "sign-in. Run scripts/flow_login.py and log in, then "
                        "re-render.")
                self._dismiss_welcome_popup(page)
        try:
            page.locator(_NEW_PROJECT_SEL).first.click(timeout=8000)
        except Exception as exc:
            # One more dismissal + retry: the popup can mount late, after the
            # first dismissal pass already ran.
            self._dismiss_welcome_popup(page)
            try:
                page.locator(_NEW_PROJECT_SEL).first.click(timeout=8000)
            except Exception:
                raise MediaError(f"Flow: could not click the new-project button: {exc}")
        for _ in range(20):  # wait for navigation into /project/<id>
            page.wait_for_timeout(1000)
            if "/project/" in page.url and page.url != before:
                break
        if "/project/" not in page.url:
            raise MediaError("Flow: new project did not open a /project/ URL")
        page.wait_for_timeout(3000)
        self._project = page.url
        print(f"[flow] new project: {self._project}", flush=True)

    def _type_prompt(self, page, prompt: str, *, clear: bool = True) -> None:
        """clear=False appends after existing composer content — required when
        @-mention chips were just attached (Ctrl+A would wipe them)."""
        self._dismiss_welcome_popup(page)
        box = page.locator(_PROMPT_SEL).first
        # Explicit timeout so a covered/disabled prompt box (e.g. while Flow is
        # busy) fails fast instead of blocking on Playwright's 30s default.
        box.click(timeout=10_000)
        if clear:
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
        else:
            page.keyboard.press("End")
        page.keyboard.type(prompt, delay=2)
        page.wait_for_timeout(400)

    def _click_generate(self, page) -> None:
        """Click the send arrow that belongs to the COMPOSER. A page-wide
        `.last` match also hits the retry (↻) buttons on old error cards in
        the feed — which re-ran a dead Pro workflow instead of our prompt
        (the source of every 'phantom Pro generation' since the feed filled
        with error cards)."""
        target = page.evaluate(
            """(promptSel) => {
                const box = document.querySelector(promptSel);
                if (!box) return null;
                const pb = box.getBoundingClientRect();
                let best = null, bestD = 1e9;
                for (const b of document.querySelectorAll('button')) {
                    if (!(b.textContent || '').includes('arrow_forward'))
                        continue;
                    const r = b.getBoundingClientRect();
                    if (r.width === 0) continue;
                    const d = Math.abs((r.y + r.height / 2)
                        - (pb.y + pb.height / 2))
                        + Math.abs(r.x - pb.right) * 0.2;
                    if (d < bestD) { bestD = d; best = r; }
                }
                if (!best || bestD > 400) return null;
                return {x: best.x + best.width / 2,
                        y: best.y + best.height / 2};
            }""", _PROMPT_SEL)
        if target:
            page.mouse.click(target["x"], target["y"])
            return
        gen = page.locator(_GENERATE_SEL).last
        if not gen.count():
            gen = page.get_by_role("button", name="Create").last
        if not gen.count():
            gen = page.get_by_role("button", name="Tạo").last
        gen.click(timeout=10_000)

    def _newest_result_srcs(self, page) -> list[str]:
        return page.eval_on_selector_all(
            _RESULT_IMG_SEL, "els => els.map(e => e.src)"
        )

    def _all_media_srcs(self, page) -> list[str]:
        """Every generated-media URL on the page (images AND videos), DOM order."""
        return page.evaluate(
            """() => {
                const out = [];
                for (const e of document.querySelectorAll('img, video, source')) {
                    const u = e.currentSrc || e.src || '';
                    if (u && u.includes('getMediaUrlRedirect')) out.push(u);
                }
                return out;
            }"""
        )

    def _read_credits(self, page) -> int | None:
        """Read the Flow credit balance ("NNN Tín dụng Flow") from the account
        popover. Returns int credits, or None if not found. Image gen is free;
        only Veo video consumes credits — used for the img2vid preflight."""
        def _scan() -> int | None:
            txt = page.evaluate(
                "() => { for (const e of document.querySelectorAll('*')) {"
                "const t=(e.innerText||'').trim();"
                "if (/Tín dụng|credit/i.test(t) && /\\d/.test(t) && t.length<40) return t;"
                "} return ''; }"
            )
            m = re.search(r"([\d.,]+)\s*(?:Tín dụng|credit)", txt or "", re.I)
            return int(re.sub(r"[.,]", "", m.group(1))) if m else None

        got = _scan()
        if got is not None:
            return got
        # Open the account / PRO popover, then re-scan.
        for pat in ("PRO", "account_circle", "Ultra"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.first.click(timeout=4000)
                    page.wait_for_timeout(1200)
                    got = _scan()
                    page.keyboard.press("Escape")
                    if got is not None:
                        return got
                except Exception:
                    continue
        return None

    def read_credits(self) -> int | None:
        page = self._ensure_page()
        return self._read_credits(page)

    def _exit_agent_mode(self, page) -> None:
        """New Flow projects open in 'Tác nhân' (Agent) mode — a chat/thinking
        surface with no image model chip. Toggle it OFF so the generator switches
        to direct image generation (chip 'Imagen 4 / crop_16_9 / 1x' appears)."""
        try:
            agent = page.locator('button:has-text("Agent"), button:has-text("Tác nhân")').first
            if agent.count() and (agent.get_attribute("aria-pressed") == "true"):
                agent.click(timeout=5000)
                page.wait_for_timeout(1200)
        except Exception:
            pass

    def _open_settings_panel(self, page) -> None:
        """Open the model/format popover (chip shows model + aspect + count).

        Pattern order matters: the MODEL name ("Banana"/🍌) uniquely matches
        the composer chip, while "crop_" also matches other icon-bearing
        buttons — clicking one of those silently fails to open the popover
        (live run 8 burned all three retries that way)."""
        # The composer chip uniquely carries model name + output count in ONE
        # button ("🍌 Nano Banana Pro / crop_16_9 / x1"); workflow info cards
        # in the feed also mention the model name alone, so a single-text
        # match can hit a card and open nothing (live run 9, count=2).
        candidates = (
            'button:has-text("Banana"):has-text("x1")',
            'button:has-text("Veo"):has-text("x1")',
            'button:has-text("crop_"):has-text("x1")',
            'button:has-text("Banana")',
            'button:has-text("🍌")',
            'button:has-text("Imagen")',
            'button:has-text("Veo")',
            'button:has-text("crop_")',
        )
        for sel in candidates:
            loc = page.locator(sel)
            if loc.count():
                try:
                    loc.last.click(timeout=6000)
                    print(f"      [flow] settings opener matched {sel!r} "
                          f"(count={loc.count()})", flush=True)
                    return
                except Exception:
                    continue
        raise MediaError("Flow: could not open the model/format settings panel")

    def _close_agent_panel(self, page) -> None:
        """New Flow opens an AGENT chat panel on project load — slow (reasons step by
        step, ~2 min/image). Closing it (the panel's X) reverts to the CLASSIC direct
        prompt bar (composer with the 'Tác nhân' toggle OFF, Nano Banana + 1x chips),
        which generates straight away (~30 s/image) exactly like the old UI. So we
        just close the panel and keep using the fast direct flow. Best-effort +
        idempotent: if the direct composer ('Tác nhân' toggle) is already visible,
        we're done."""
        try:
            for _ in range(3):
                if page.locator('button:has-text("Agent"), button:has-text("Tác nhân")').count():
                    return  # already in direct mode
                x = page.locator('button:has-text("close")').last
                if not x.count():
                    return
                x.click(timeout=4000)
                page.wait_for_timeout(800)
        except Exception as e:
            print(f"      [flow] close agent panel skipped ({e})", flush=True)

    def _settings_popover(self, page):
        """The VISIBLE settings popover, or None. Radix keeps hidden mirror
        copies of the popover content in the DOM, so text-based waits with
        .last kept latching onto an invisible node and timing out (live runs
        8-10). Scope every interaction to the visible wrapper instead."""
        pops = page.locator("[data-radix-popper-content-wrapper]")
        fallback = None
        for i in range(pops.count() - 1, -1, -1):
            p = pops.nth(i)
            try:
                if not (p.locator(':text-is("9:16")').count()
                        and p.is_visible()):
                    continue
                # Prefer the FULL panel (aspect chips AND the model row) —
                # radix nests a smaller aspect-only wrapper inside it, and
                # matching that one made the model switch silently skip.
                if p.get_by_text("Banana", exact=False).count() \
                        or p.get_by_text("Veo", exact=False).count():
                    return p
                if fallback is None:
                    fallback = p
            except Exception:
                continue
        return fallback

    #: The composer persists its ENTIRE configuration in ONE localStorage key
    #: (calibrated live in the operator's Chrome via the extension). Model
    #: families: narwhal_display = Nano Banana 2 (free tier), abra = Omni
    #: Flash video. Writing this key and reloading replaces the whole fragile
    #: popover dance (eleven runs of selector archaeology died on that UI).
    _PROMPT_BOX_KEY = "FLOW_MAIN_PROMPT_BOX_STATE"

    def _apply_prompt_box_state(self, page, **updates) -> None:
        import json as _json

        cur = page.evaluate(
            f"() => localStorage.getItem('{self._PROMPT_BOX_KEY}')")
        try:
            state = _json.loads(cur) if cur else {}
        except Exception:
            state = {}
        if all(state.get(k) == v for k, v in updates.items()):
            return                       # already configured — no reload
        state.update(updates)
        page.evaluate(
            f"(s) => localStorage.setItem('{self._PROMPT_BOX_KEY}', s)",
            _json.dumps(state, separators=(",", ":")))
        # The composer reads the key on mount only.
        self._reload_project(page)
        print(f"      [flow] prompt-box state applied: {updates}", flush=True)

    #: Model label → localStorage family (calibrated live via the extension).
    #: Nano Banana PRO is the QUALITY model: it is the only tier that follows
    #: attached reference images faithfully — Nano Banana 2 drifted to
    #: training-prior archetypes (fairy forests, school girls, cyberpunk) on
    #: the exact prompts and chips that Pro rendered correctly. Keyframes
    #: therefore run on Pro; the 2-tier is only the quota fallback.
    _IMAGE_MODEL_FAMILIES = {
        "Nano Banana Pro": "nano_banana_pro",
        "Nano Banana 2": "narwhal_display",
    }

    def _set_image_mode(self, page, resolution: tuple[int, int] | None = None) -> None:
        """Configure the composer for image generation via localStorage state
        (portrait + selected model family + 1 output), then verify."""
        self._close_agent_panel(page)
        page.wait_for_timeout(300)
        portrait = bool(resolution and resolution[1] > resolution[0])
        model = self._image_model or "Nano Banana Pro"
        family = self._IMAGE_MODEL_FAMILIES.get(model, "nano_banana_pro")
        self._apply_prompt_box_state(
            page,
            imageOrVideoMode="IMAGE",
            aspectRatio="PORTRAIT" if portrait else "LANDSCAPE",
            selectedImageModelFamily=family,
            outputsPerPrompt=1,
        )
        # The composer mounts late and sometimes not at all on a stale page —
        # poll for the chip, and give the page ONE hard reload before giving
        # up (runs 37/40 died on two variants of this race).
        chip = page.locator('button:has-text("Banana"):has-text("x1")')
        for round_ in range(2):
            waited = 0
            while not chip.count() and waited < 30_000:
                # A changelog/credit popup that appears MID-SESSION (after a run
                # of generations) covers the composer, so the chip poll times
                # out even though the page finished loading. Dismiss it on every
                # poll tick — the start-of-session dismiss cannot catch a popup
                # Flow raises on generation 30+. Live 2026-09-04: renders died
                # at ~shot 34 on exactly this, twice.
                self._dismiss_welcome_popup(page)
                # 09/2026 redesign: the composer stopped reading the legacy
                # FLOW_MAIN_PROMPT_BOX_STATE key (its replacement has minified
                # field names that churn per build), so the localStorage write
                # above no longer flips the mode. Switch the way a user does:
                # open the mode chip ("Video · 720p · 8s") and click the Image
                # tab. English-only UI is pinned via ?hl=en, so these texts are
                # stable.
                video_chip = page.locator('button', has_text=re.compile(r"Video · "))
                if video_chip.count():
                    try:
                        video_chip.first.click(timeout=4000)
                        page.wait_for_timeout(1200)
                        img_tab = page.get_by_text("Image", exact=True)
                        if img_tab.count():
                            img_tab.first.click(timeout=4000)
                            page.wait_for_timeout(2000)
                            print("      [flow] mode switched to IMAGE via chip UI", flush=True)
                        else:
                            print("      [flow] chip menu opened but no Image tab found", flush=True)
                            page.keyboard.press("Escape")
                    except Exception as exc:
                        print(f"      [flow] chip UI switch failed: {str(exc)[:140]}", flush=True)
                page.wait_for_timeout(1500)
                waited += 1500
            if chip.count():
                break
            if round_ == 0:
                self._reload_project(page)
        if page.get_by_text(re.compile(r"Video · \d+s")).count():
            raise MediaError(
                "Flow composer still in VIDEO mode after applying the "
                "prompt-box state — needs a live DOM calibration.")
        if not chip.count():
            raise MediaError(
                "Flow composer chip not found after applying the prompt-box "
                "state — the page may not have finished loading.")
        return

    def _set_image_mode_LEGACY_POPOVER(self, page, resolution: tuple[int, int] | None = None) -> None:
        """Old UI-driven path, kept for reference during calibration."""
        self._close_agent_panel(page)
        page.wait_for_timeout(300)
        # The composer mode is remembered SERVER-SIDE per project: a manual
        # session that left it on Video makes an unguarded prompt generate a
        # billed VIDEO instead of a free image (happened live — one 4s clip
        # burned before the corrupt "still" crashed the gate). Force the
        # Hình ảnh tab; portrait is REQUIRED when asked for (a silent 16:9
        # fallback produced landscape "stills" for a full reroll cycle).
        pop = None
        for attempt in range(3):
            self._open_settings_panel(page)
            page.wait_for_timeout(1000)
            pop = self._settings_popover(page)
            if pop is not None:
                break
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        if pop is None:
            raise MediaError(
                "Flow: settings popover never opened (3 attempts)")
        img_tab = pop.locator(':text-is("Hình ảnh")')
        if img_tab.count():
            img_tab.first.click()
            page.wait_for_timeout(500)
        if resolution and resolution[1] > resolution[0]:
            pop.locator(':text-is("9:16")').first.click(timeout=5000)
            page.wait_for_timeout(300)
        # Proactively pick Nano Banana 2 for stills: Pro is the project
        # default and quota-limited — waiting for the quota ERROR text to
        # trigger the fallback wastes reroll attempts when Pro degrades
        # silently instead of erroring (operator-reported).
        # Stills NEVER run on Pro: it is quota-capped and the project default.
        # Whatever the configured value (settings stores the slug, some paths
        # normalize it to the label — 'Nano Banana Pro' reached here verbatim
        # and made the != check skip the switch for eleven runs), a Pro-ish
        # target is coerced to the free tier.
        raw_model = self._image_model or ""
        target_model = (raw_model if raw_model
                        and "pro" not in raw_model.lower()
                        else "Nano Banana 2")
        print(f"      [flow] image model target={target_model!r} "
              f"(configured={raw_model!r})", flush=True)
        try:
            # Playwright locators kept missing the model row through three
            # selector variants (emoji node, composite label, nested radix
            # wrappers) — leaf-node JS click is the calibration-proof form.
            def _js_click_text(txt: str, menu_only: bool = False) -> str:
                # Smallest visible element CONTAINING the text: leaf-only
                # filtering missed the label (the 🍌 emoji span makes its
                # parent non-leaf), containment-sort survives any nesting.
                # menu_only scopes to the OPEN dropdown — a page-wide match
                # for "Nano Banana" hit the composer chip itself and reported
                # 'clicked' while changing nothing (live run 24).
                return page.evaluate(
                    """([txt, menuOnly]) => {
                        const root = menuOnly
                            ? document.querySelector(
                                '[data-radix-menu-content][data-state="open"]')
                            : document;
                        if (!root) return 'no-menu';
                        const cands = [...root.querySelectorAll('*')]
                          .filter(e => e.offsetParent !== null
                              && (e.textContent || '').includes(txt));
                        if (!cands.length) return 'miss';
                        cands.sort((a, b) =>
                            a.textContent.length - b.textContent.length);
                        cands[0].click();
                        return 'clicked';
                    }""", [txt, menu_only])

            if target_model != "Nano Banana Pro":
                # Open the model dropdown via ITS OWN arrow inside the popover
                # (element-scoped): page-wide text clicks kept hitting the
                # model name inside feed cards, and the "open menu" that got
                # inspected was the settings popover itself.
                # Synthetic JS events never opened the Radix Select (isTrusted
                # checks) — use REAL CDP mouse clicks at measured coordinates.
                box = pop.evaluate(
                    """(el) => {
                        const leaf = [...el.querySelectorAll('*')]
                          .filter(e => e.offsetParent !== null
                              && e.childElementCount === 0);
                        const dd = leaf.find(e =>
                            (e.textContent || '').trim()
                                === 'arrow_drop_down');
                        if (!dd) return null;
                        const r = (dd.closest('button') || dd)
                            .getBoundingClientRect();
                        return {x: r.x + r.width / 2,
                                y: r.y + r.height / 2};
                    }""")
                r1 = "no-dd" if not box else "clicked"
                r2, hit = "skipped", ""
                if box:
                    page.mouse.click(box["x"], box["y"])
                    page.wait_for_timeout(800)
                    opt = page.evaluate(
                        """() => {
                            const opts = [...document.querySelectorAll(
                                '[role="option"]')]
                              .filter(e => e.offsetParent !== null);
                            const texts = opts.map(
                                e => (e.textContent || '').trim())
                              .filter(t => t).slice(0, 12);
                            let pick = opts.find(e => {
                                const t = e.textContent || '';
                                return t.includes('Banana')
                                    && !t.includes('Pro');
                            }) || opts.find(e =>
                                !((e.textContent || '').includes('Pro')));
                            if (!pick) return {err: 'no-option', texts};
                            const r = pick.getBoundingClientRect();
                            return {picked:
                                    (pick.textContent || '').trim(),
                                    x: r.x + r.width / 2,
                                    y: r.y + r.height / 2, texts};
                        }""")
                    safe = str(opt).encode("ascii", "ignore").decode()
                    print(f"      [flow] menu pick: {safe[:200]}", flush=True)
                    if isinstance(opt, dict) and opt.get("picked"):
                        page.mouse.click(opt["x"], opt["y"])
                        r2, hit = "clicked", opt["picked"]
                    else:
                        r2 = "miss"
                    page.wait_for_timeout(600)
                chip_txt = page.evaluate(
                    """() => {
                        const b = [...document.querySelectorAll('button')]
                          .find(x => (x.textContent || '').includes('Banana')
                              && (x.textContent || '').includes('x1'));
                        return b ? b.textContent.trim().slice(0, 60) : '';
                    }""")
                # ascii-safe: the chip text carries the 🍌 emoji, which
                # crashes print on Windows' charmap console and the crash
                # swallowed this whole log line (live run 25).
                chip_ascii = chip_txt.encode("ascii", "ignore").decode()
                print(f"      [flow] image model switch: open={r1} "
                      f"pick({hit or target_model})={r2} chip={chip_ascii!r}",
                      flush=True)
                # The dropdown menu STAYS OPEN after a JS click and swallows
                # every later pointer event (the prompt box click timed out
                # against it live). Close it explicitly and verify.
                for _ in range(3):
                    if not page.locator(
                            '[data-radix-menu-content][data-state="open"]'
                    ).count():
                        break
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(400)
        except Exception as e:
            print(f"      [flow] model pick skipped ({str(e)[:80]})",
                  flush=True)
        try:
            one = pop.locator(':text-is("x1")')
            if one.count():
                one.first.click()
        except Exception:
            pass
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        if page.get_by_text(re.compile(r"Video · \d+s")).count():
            raise MediaError(
                "Flow composer is still in VIDEO mode after switching to "
                "Hình ảnh — refusing to generate (a prompt here would bill a "
                "video). Needs a live DOM calibration.")
        if (resolution and resolution[1] > resolution[0]
                and not page.locator('button:has-text("crop_9_16")').count()
                and page.locator('button:has-text("crop_16_9")').count()):
            raise MediaError(
                "Flow composer still shows a 16:9 aspect chip after selecting "
                "9:16 — refusing to generate landscape stills for a portrait "
                "film.")
        if self._image_model:
            try:
                self._select_model(page, self._image_model)
            except Exception as e:
                print(f"      [flow] model select skipped ({e})", flush=True)
        if self._ref_images and not self._ingredients_attached:
            self._attach_ingredients(page)

    # Candidate openers for the ingredient/reference-image picker. Flow's UI
    # (vi locale) exposes it from the composer; exact affordance shifts between
    # releases, so we try several and then look for a file input. Best-effort:
    # a failed attach logs and generation continues with the text-DNA anchor.
    _INGREDIENT_OPENERS = (
        'button:has-text("Ingredients")', 'button:has-text("Thành phần")',  # EN first, vi fallback
        'button:has-text("add_photo")',        # material icon in composer
        'button:has-text("add_photo_alternate")',
        'button:has-text("image")',            # material icon fallback
        'button[aria-label*="nh"]:has-text("add")',
    )

    def _attach_ingredients(self, page) -> bool:
        """Attach the reference images to Flow's composer as ingredients so the
        image model conditions on the SAME character in every shot (WS1
        character-consistency root fix; the text DNA block stays as layer 1).

        Strategy: Playwright `set_input_files` on the composer's file input —
        immune to drag-drop/chooser flakiness. If no input is present, click the
        known opener buttons first. Never raises: on failure we log and return
        False so generation proceeds exactly as before."""
        try:
            inp = page.locator('input[type="file"]')
            if not inp.count():
                for sel in self._INGREDIENT_OPENERS:
                    try:
                        btn = page.locator(sel)
                        if btn.count():
                            btn.first.click(timeout=3000)
                            page.wait_for_timeout(800)
                            inp = page.locator('input[type="file"]')
                            if inp.count():
                                break
                    except Exception:
                        continue
            if not inp.count():
                print("      [flow] ingredients: no file input found in the "
                      "composer — needs a live DOM calibration; continuing "
                      "with text-DNA anchor only", flush=True)
                return False
            inp.first.set_input_files(self._ref_images)
            page.wait_for_timeout(2500)  # let the chips upload/appear
            # Close any picker/popover the opener may have left on screen.
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            except Exception:
                pass
            self._ingredients_attached = True
            print(f"      [flow] ingredients attached: "
                  f"{len(self._ref_images)} reference image(s)", flush=True)
            return True
        except Exception as e:
            print(f"      [flow] ingredients attach failed ({str(e)[:120]}) — "
                  "continuing with text-DNA anchor only", flush=True)
            return False

    def _select_model(self, page, label: str) -> None:
        """Pick the image model. Flow UI (probed 2026-07-11): the composer
        SETTINGS CHIP shows '<model> | crop_16_9 | 1x'; clicking it opens a
        popover whose MODEL DROPDOWN is a '<model> arrow_drop_down' button;
        clicking THAT lists the models as plain SPANs (no role):
        '🍌 Nano Banana Pro' / '🍌 Nano Banana 2' / '🍌 Nano Banana 2 Lite'.
        Best-effort — caller swallows failures (keeps default)."""
        chip = page.locator('button:has-text("crop_16_9")')
        if not chip.count():
            chip = page.locator('button:has-text("arrow_drop_down")')  # older UI
        if not chip.count():
            print("[flow] warn: model chip not found; keeping default", flush=True)
            return
        try:
            if label in (chip.first.inner_text() or ""):
                return  # already on the wanted model
        except Exception:
            pass
        chip.first.click(timeout=4000)  # open settings popover
        page.wait_for_timeout(700)
        dd = page.locator('button:has-text("arrow_drop_down")')
        if dd.count():
            dd.first.click(timeout=4000)  # open the model list
            page.wait_for_timeout(700)
        # EXACT text match — 'Nano Banana 2' is a prefix of 'Nano Banana 2 Lite'.
        opt = page.locator(f'span:text-is("🍌 {label}")')
        if not opt.count():
            opt = page.locator(f'span:text-is("{label}")')
        if not opt.count():
            opt = page.locator(f'[role="menuitem"]:has-text("{label}")')  # older UI
        if opt.count():
            opt.first.click(timeout=4000)
            page.wait_for_timeout(500)
            print(f"[flow] image model -> {label}", flush=True)
        else:
            print(f"[flow] warn: model '{label}' not in menu; keeping default", flush=True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    def _set_output_count(self, page, n: int) -> None:
        """Select Flow's native outputs-per-prompt (the 1x/x2/x3/x4 tabs in the
        model/format popover — free, 0 credits). One submission then yields n
        images: 4x fewer submits than repeating the prompt, which is both
        faster and far gentler on Flow's anti-abuse limits."""
        n = max(1, min(int(n), 4))
        label = "1x" if n == 1 else f"x{n}"
        try:
            self._open_settings_panel(page)
            page.wait_for_timeout(600)
            tab = page.get_by_role("tab", name=label, exact=True)
            if tab.count():
                tab.first.click(timeout=4000)
                page.wait_for_timeout(400)
                print(f"[flow] outputs per prompt -> {label}", flush=True)
            else:
                print(f"[flow] warn: count tab '{label}' not found; keeping current", flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        except Exception as e:
            print(f"[flow] warn: set output count failed ({e})", flush=True)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    def gen_image_multi(self, prompt: str, out_paths: list[str], wait_s: int,
                        resolution: tuple[int, int] | None = None) -> list[str]:
        """ONE prompt → up to 4 images via Flow's native x2/x3/x4 output tabs.
        Downloads every fresh result into out_paths (order not meaningful —
        same prompt). Resets the count to 1x afterwards so ordinary gen_image
        callers aren't surprised. Returns the paths actually written."""
        n = max(1, min(len(out_paths), 4))
        page = self._ensure_page()
        self._set_image_mode(page, resolution)
        self._check_blocked(page)
        self._set_output_count(page, n)
        try:
            before = set(self._newest_result_srcs(page))
            self._type_prompt(page, prompt)
            self._click_generate(page)
            fresh: list[str] = []
            for _ in range(max(1, wait_s // 3)):
                page.wait_for_timeout(3000)
                cur = self._newest_result_srcs(page)
                fresh = [s for s in cur if s and s not in before]
                if len(fresh) >= n:
                    page.wait_for_timeout(3000)  # settle
                    cur = self._newest_result_srcs(page)
                    fresh = [s for s in cur if s and s not in before]
                    break
            if not fresh:
                raise MediaError(f"Flow produced no image within {wait_s}s (x{n} mode)")
            written: list[str] = []
            for src, dst in zip(fresh[:n], out_paths):
                self._download(src, dst)
                written.append(str(Path(dst).resolve()))
            return written
        finally:
            self._set_output_count(page, 1)

    def _set_video_mode(self, page) -> None:
        """Switch the generator to Veo video, 16:9, 1 output."""
        self._exit_agent_mode(page)
        self._open_settings_panel(page)
        page.wait_for_timeout(800)
        # Tab: Video
        vid = page.locator('button[role="tab"][id$="-trigger-VIDEO"]')
        if not vid.count():
            vid = page.get_by_role("tab", name="Video")
        vid.first.click()
        page.wait_for_timeout(500)
        # Count: 1x (avoid multi-output)
        try:
            one = page.get_by_role("tab", name="1x", exact=True)
            if one.count():
                one.click()
        except Exception:
            pass
        # Close the panel so the prompt box is interactable again.
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

    def _download(self, src: str, out_path: str) -> None:
        resp = self._ctx.request.get(src, timeout=120_000)
        if not resp.ok:
            raise MediaError(f"Flow media fetch failed: HTTP {resp.status} {src}")
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(resp.body())

    def set_characters(self, names: list[str] | None) -> None:
        """Project CHARACTERS to @-mention into every prompt. This is how the
        approved keyframes were conditioned — uploaded ingredient chips never
        reached the composer (three off-context generations proved it)."""
        names = list(names or [])
        if names != getattr(self, "_characters", []):
            self._characters = names

    def set_prompt_assets(self, names: list[str] | None) -> None:
        """Project image ASSETS (by displayed name, e.g. 'K1.jpg') to attach
        to every prompt as visual anchors via the same @-picker."""
        names = list(names or [])
        if names != getattr(self, "_prompt_assets", []):
            self._prompt_assets = names

    def _mention_picker(self, page):
        """The VISIBLE @-picker overlay (identified by its search box), or
        None. Same trap as the settings popover: page-level text lookups hit
        the SIDEBAR ('Nhân vật' exists there too) and navigated away — every
        interaction must stay inside this container."""
        pops = page.locator(
            '[data-radix-popper-content-wrapper], [role="dialog"]')
        for i in range(pops.count() - 1, -1, -1):
            p = pops.nth(i)
            try:
                if (p.get_by_placeholder("Tìm kiếm thành phần").count()
                        and p.is_visible()):
                    return p
            except Exception:
                continue
        return None

    def _mention_attach(self, page, tab_label: str, item_name: str) -> bool:
        """Typing '@' in the composer opens the universal asset picker
        (tabs Tất cả/Hình ảnh/Nhân vật/…, search 'Tìm kiếm thành phần',
        confirm 'Thêm vào câu lệnh'). Search-first, then row, then confirm —
        the discipline that ended the look-alike-row bug in the manual runs."""
        box = page.locator(_PROMPT_SEL).first
        box.click(timeout=8000)
        page.keyboard.type("@", delay=30)
        picker = None
        for _ in range(4):
            page.wait_for_timeout(800)
            picker = self._mention_picker(page)
            if picker is not None:
                break
        if picker is None:
            page.keyboard.press("Backspace")
            print("      [flow] @-picker did not open", flush=True)
            return False
        try:
            tab = picker.locator(f':text-is("{tab_label}")')
            if tab.count():
                tab.first.click(timeout=4000)
                page.wait_for_timeout(700)
            search = picker.get_by_placeholder("Tìm kiếm thành phần")
            if search.count():
                search.first.fill(item_name)
                page.wait_for_timeout(1200)
            row = picker.get_by_text(item_name, exact=False)
            if not row.count():
                page.keyboard.press("Escape")
                page.keyboard.press("Backspace")   # drop the dangling '@'
                return False
            row.last.click(timeout=4000)
            page.wait_for_timeout(700)
            add = picker.locator('button:has-text("Add to prompt"), button:has-text("Thêm vào câu lệnh")')
            if add.count() and add.first.is_enabled():
                add.first.click(timeout=4000)
                page.wait_for_timeout(700)
                return True
            page.keyboard.press("Escape")
            page.keyboard.press("Backspace")
            return False
        except Exception as e:
            print(f"      [flow] mention {item_name!r} failed ({str(e)[:80]})",
                  flush=True)
            try:
                page.keyboard.press("Escape")
                page.keyboard.press("Backspace")
            except Exception:
                pass
            return False

    def set_prompt_files(self, paths: list[str] | None) -> None:
        """LOCAL image files to attach to every prompt via the @-picker's
        'Tệp tải lên' tab. The strongest conditioning channel this profile
        has: the project characters do not exist in its mention picker at all
        (tab shows 'Không tìm thấy kết quả nào'), while file-upload chips are
        first-class."""
        self._prompt_files = [str(Path(p).resolve()) for p in (paths or [])
                              if Path(p).exists()]

    def _mention_upload(self, page, path: str) -> bool:
        """'@' → 'Tệp tải lên' tab → file input → confirm. The uploaded item
        auto-selects (observed live on the FLF slot picker); confirm with
        'Thêm vào câu lệnh' when it does not auto-attach."""
        box = page.locator(_PROMPT_SEL).first
        box.click(timeout=8000)
        page.keyboard.type("@", delay=30)
        picker = None
        for _ in range(4):
            page.wait_for_timeout(800)
            picker = self._mention_picker(page)
            if picker is not None:
                break
        if picker is None:
            page.keyboard.press("Backspace")
            print("      [flow] @-picker did not open for upload", flush=True)
            return False
        try:
            tab = picker.locator(':text-is("Tệp tải lên")')
            if tab.count():
                tab.first.click(timeout=4000)
                page.wait_for_timeout(700)
            inputs = page.locator('input[type="file"]')
            if not inputs.count():
                page.keyboard.press("Escape")
                page.keyboard.press("Backspace")
                return False
            inputs.last.set_input_files(path)
            # Upload + auto-select; wait for the confirm button to enable.
            deadline_ms = 60_000
            waited = 0
            while waited < deadline_ms:
                page.wait_for_timeout(1500)
                waited += 1500
                if self._mention_picker(page) is None:
                    return True     # picker closed itself → chip attached
                add = picker.locator('button:has-text("Add to prompt"), button:has-text("Thêm vào câu lệnh")')
                try:
                    if add.count() and add.first.is_enabled():
                        add.first.click(timeout=4000)
                        page.wait_for_timeout(700)
                        return True
                except Exception:
                    pass
            page.keyboard.press("Escape")
            page.keyboard.press("Backspace")
            return False
        except Exception as e:
            print(f"      [flow] mention-upload {path!r} failed "
                  f"({str(e)[:80]})", flush=True)
            try:
                page.keyboard.press("Escape")
                page.keyboard.press("Backspace")
            except Exception:
                pass
            return False

    def _attach_prompt_refs(self, page) -> None:
        """Attach configured refs into the CURRENT prompt: local files first
        (strongest), then named assets, then characters (kept for profiles
        whose picker has them). Chips live inside the prompt text, so this
        runs per generation, after clearing the composer and before typing.
        Fail-closed when nothing attaches — a context-free still burns the
        reroll budget for nothing."""
        files = getattr(self, "_prompt_files", [])
        chars = getattr(self, "_characters", [])
        assets = getattr(self, "_prompt_assets", [])
        if not files and not chars and not assets:
            return
        # Clear leftover text first (chips are added fresh each time).
        box = page.locator(_PROMPT_SEL).first
        box.click(timeout=8000)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        attached = 0
        for path in files:
            ok = self._mention_upload(page, path)
            print(f"      [flow] file chip {Path(path).name!r}: "
                  f"{'ok' if ok else 'MISS'}", flush=True)
            attached += int(ok)
        for name in assets:
            ok = self._mention_attach(page, "Hình ảnh", name)
            print(f"      [flow] asset chip {name!r}: "
                  f"{'ok' if ok else 'MISS'}", flush=True)
            attached += int(ok)
        for name in chars:
            # Search from "Tất cả": this account's picker shows characters in
            # the all-assets list while its "Nhân vật" tab renders empty.
            ok = self._mention_attach(page, "Tất cả", name)
            print(f"      [flow] character chip {name!r}: "
                  f"{'ok' if ok else 'MISS'}", flush=True)
            attached += int(ok)
        if not attached:
            raise MediaError(
                "Flow: no reference chip could be attached via the @-picker "
                "— aborting instead of generating context-free stills")

    def _reload_project(self, page) -> None:
        """Hard-reset the composer UI. Chips and slot attachments do NOT
        survive a reload (observed live), so this is the reliable way to drop
        stale ingredient chips before attaching a new set — chip-remove
        buttons would need per-release DOM calibration."""
        page.goto(_with_hl_en(self._project), wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(4000)
        self._dismiss_welcome_popup(page)
        self._ingredients_attached = False
        self._characters_attached = False

    def gen_image(self, prompt: str, out_path: str, wait_s: int, resolution: tuple[int, int] | None = None) -> str:
        """One prompt → one image, identified through the WORKFLOW API.

        The old implementation diffed the DOM's <img src> set, but Flow signs
        those URLs per page-load: every poll saw "new" srcs for OLD images and
        happily downloaded a stale generation (three keyframes in a row came
        back as the same old picture before this was caught). Workflow ids and
        primaryMediaId are stable, so the project feed is the identity source;
        the DOM is only used to submit the prompt.
        """
        page = self._ensure_page()
        self._set_image_mode(page, resolution)
        # Early guard with a baseline: the feed is full of OLD Pro-quota error
        # cards, and an un-baselined check here killed the first NB2 run
        # before it could generate anything.
        self._check_blocked(page, self._quota_card_count(page))
        feed = self._workflows()
        before_ids = {w["media_id"] for w in feed if w["media_id"]}
        newest_ts = feed[0]["created"] if feed else ""
        has_chips = bool(getattr(self, "_characters", [])
                         or getattr(self, "_prompt_assets", [])
                         or getattr(self, "_prompt_files", []))
        self._attach_prompt_refs(page)
        self._type_prompt(page, prompt, clear=not has_chips)
        qbase = self._quota_card_count(page)
        self._click_generate(page)

        # Attached reference images create their own UPLOAD workflows named
        # after the file — newest in the feed, and exactly what got downloaded
        # as the "generation" three times in a row before this skip existed.
        # EVERY upload channel must be covered: legacy ingredients, named
        # assets, AND the @-picker file chips (missing the last one re-created
        # the stale-download bug live: workflow 'K4.jpg' returned as the gen).
        skip = {Path(r).name for r in (self._ref_images or [])}
        skip |= {Path(p).name for p in getattr(self, "_prompt_files", [])}
        skip |= set(getattr(self, "_prompt_assets", []))
        new_wf = self._await_new_workflow(page, before_ids, skip, wait_s,
                                          after_ts=newest_ts, qbase=qbase)
        print(f"      [flow] image workflow: {new_wf['name'][:60]!r} "
              f"media={new_wf['media_id'][:8]}", flush=True)
        data = self._await_media_bytes(page, new_wf["media_id"], wait_s,
                                       kind="image", qbase=qbase)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return str(out.resolve())

    WAVE = 3  # max prompts per wave — smaller bursts are gentler on Flow's abuse limits

    @staticmethod
    def _jitter(base_ms: int, spread: float = 0.35) -> int:
        """Randomise a wait so the cadence looks human, not bot-regular. A flagged
        Flow session relaxes faster when traffic is irregular + spaced out."""
        lo = int(base_ms * (1 - spread))
        hi = int(base_ms * (1 + spread))
        return random.randint(lo, hi)

    def _quota_card_count(self, page) -> int:
        """How many 'hết hạn mức … Nano Banana Pro' error cards are on the
        page. Failed generations leave their error cards in the project feed
        FOREVER, so presence alone is meaningless — only an INCREASE during
        the current generation means the quota actually fired now. (Without
        this, one old card made every later run raise FlowModelQuota even
        after the model was switched.)"""
        try:
            return page.evaluate(
                """() => {
                    let n = 0;
                    for (const e of document.querySelectorAll('*')) {
                        // Next.js embeds page data in <script> tags whose
                        // text ALSO contains the quota strings — and that
                        // blob changes on every poll, which broke the
                        // baseline. Count visible UI leaves only.
                        if (e.tagName === 'SCRIPT' || e.tagName === 'STYLE')
                            continue;
                        if (e.childElementCount === 0) {
                            const t = e.textContent || '';
                            if (t.includes('hết hạn mức')
                                || t.includes('hạn mức về số lượt')) n++;
                        }
                    }
                    return n;
                }""") or 0
        except Exception:
            return 0

    def _check_blocked(self, page, quota_baseline: int | None = None) -> None:
        """Detect Flow's 'unusual activity' / rate-limit block. If present, abort
        immediately (do NOT retry — hammering a flagged session makes it worse and
        is exactly what the block guards against). The operator must wait it out.

        quota_baseline: pass the pre-generation _quota_card_count so the model-
        quota check only fires on NEW error cards (old ones persist in the feed)."""
        try:
            txt = page.evaluate(
                "() => document.body ? document.body.innerText : ''") or ""
        except Exception:
            return
        low = txt.lower()
        # MODEL-specific quota ('...hết hạn mức... Nano Banana Pro. Hãy thử dùng
        # một mô hình khác.') → switching model fixes it; raise the fallback-able
        # subclass BEFORE the generic quota check.
        # When we are ALREADY generating on a non-Pro model, any Pro-quota text
        # can only be an OLD error card in the feed — the virtualized list
        # re-renders those the moment a new generation lands, which inflated
        # the baseline count and killed three healthy NB2 runs in a row.
        running_pro = "pro" in (self._image_model or "pro").lower()
        if "nano banana pro" in low and ("hết hạn mức" in low):
            print(f"      [flow] quota-guard eval: _image_model="
                  f"{(self._image_model or '').encode('ascii','ignore').decode()!r} "
                  f"running_pro={running_pro} baseline={quota_baseline}",
                  flush=True)
        if (running_pro and "nano banana pro" in low
                and ("hết hạn mức" in low or "hạn mức về số lượt" in low
                     or "reached your limit" in low or "try another model" in low
                     or "mô hình khác" in low)):
            if quota_baseline is None \
                    or self._quota_card_count(page) > quota_baseline:
                try:
                    cards = page.evaluate(
                        """() => {
                            const out = [];
                            for (const e of document.querySelectorAll('*')) {
                                if (e.childElementCount === 0) {
                                    const t = (e.textContent || '').trim();
                                    if (t.includes('hết hạn mức')
                                        || t.includes('Không thành công'))
                                        out.push(t.slice(0, 160));
                                }
                            }
                            return out.slice(-4);
                        }""")
                    safe = str(cards).encode("ascii", "ignore").decode()
                    print(f"      [flow] quota cards (newest last): "
                          f"{safe[:400]}", flush=True)
                except Exception:
                    pass
                raise FlowModelQuota(
                    "Nano Banana Pro hết lượt — chuyển Nano Banana 2 "
                    "(fallback tự động)."
                )
        # Hard image-generation QUOTA reached → abort, must wait ~1h (no bypass).
        if ("giới hạn tạo ảnh" in low or "hết hạn mức" in low
                or "reached your limit" in low
                or "generation limit" in low or "daily limit" in low
                or "quota" in low or "limit for today" in low):
            raise FlowBlocked(
                "Flow ĐÃ ĐẠT GIỚI HẠN tạo ảnh (quota). Dừng — đợi ~1 giờ rồi chạy lại."
            )
        # Anti-abuse / unusual-activity flag → abort (hammering makes it worse).
        if ("hoạt động bất thường" in low or "unusual activity" in low
                or "unusual traffic" in low):
            raise FlowBlocked(
                "Flow chặn do 'hoạt động bất thường' (rate-limit/anti-abuse của Google). "
                "Dừng để không làm nặng thêm — đợi vài giờ rồi thử lại, chạy thưa hơn."
            )

    def _gen_wave_once(self, page, prompts: list[str], wait_s: int) -> list[str]:
        """One attempt: submit prompts, return new result srcs in submission order
        (may be fewer than len(prompts) if Flow is slow/drops one)."""
        n = len(prompts)
        before = set(self._newest_result_srcs(page))
        for pr in prompts:
            self._type_prompt(page, pr)
            self._click_generate(page)
            page.wait_for_timeout(self._jitter(12000))  # gap between submits (jittered ~8-16s)

        new_ordered: list[str] = []
        for _ in range(max(1, wait_s // 3)):
            page.wait_for_timeout(3000)
            # Fail fast on quota/block error cards — without this the wave sat
            # out the FULL wait_s (~8 min) staring at 'hết hạn mức' errors before
            # the per-image path finally noticed and the fallback could fire.
            self._check_blocked(page)
            cur = self._newest_result_srcs(page)  # newest first
            new_ordered = [s for s in cur if s and s not in before]
            if len(new_ordered) >= n:
                page.wait_for_timeout(3000)
                cur = self._newest_result_srcs(page)
                new_ordered = [s for s in cur if s and s not in before]
                break
        return list(reversed(new_ordered))  # newest-first -> submission order

    def _gen_one(self, page, prompt: str, out_path: str, wait_s: int) -> bool:
        """Generate a SINGLE image with per-image retry and exact mapping. Submits
        one prompt, waits for exactly its result, downloads it. Retries up to
        FLOW_MAX_ATTEMPTS. Returns True on success, False if it never landed.
        Raises FlowBlocked if Flow's anti-abuse/quota guard trips."""
        _attempts = max(1, int(os.environ.get("FLOW_MAX_ATTEMPTS", "2")))
        for attempt in range(_attempts):
            self._check_blocked(page)  # raises FlowBlocked; nothing half-written
            srcs = self._gen_wave_once(page, [prompt], wait_s)
            if srcs:
                try:
                    self._download(srcs[0], out_path)
                    return True
                except Exception as e:
                    print(f"      [flow] download failed: {e}", flush=True)
            if attempt < _attempts - 1:
                page.wait_for_timeout(self._jitter(20000))  # short backoff (~13-27s)
        return False

    def _gen_wave(self, page, prompts: list[str], out_paths: list[str], wait_s: int) -> list[int]:
        """Generate a wave of prompts without ever losing or mis-assigning a good
        image. Returns the wave-local indices still missing after retries (empty =
        full success). Raises FlowBlocked if Flow's anti-abuse/quota guard trips —
        any image already downloaded stays on disk.

        Two-phase, because Flow does NOT tag a result image with the prompt that
        made it — the only mapping we have is submission order, and that is only
        trustworthy when *every* prompt in the wave landed:

          1) FAST PATH — fire the whole wave once. If all n images land, map them
             in submission order and download (the original, fast batch behaviour).
          2) SAFE FALLBACK — on any shortfall, do NOT positionally map the partial
             results (a dropped middle prompt would shift every later image onto
             the wrong scene). Instead regenerate each prompt individually via
             _gen_one: exact prompt→image mapping, per-image retry, and every image
             that succeeds is downloaded + kept (a flaky shot never costs a good
             one). Re-spending on a shot that happened to land in the failed batch
             attempt is cheap — Flow images are free.
        """
        n = len(prompts)
        self._check_blocked(page)  # abort before submitting to a flagged session
        srcs = self._gen_wave_once(page, prompts, wait_s)
        if len(srcs) >= n:
            for src, op in zip(srcs[:n], out_paths):
                self._download(src, op)
            return []
        print(f"      [flow] wave got {len(srcs)}/{n}; switching to per-image "
              f"gen for exact mapping", flush=True)
        missing: list[int] = []
        for i, (pr, op) in enumerate(zip(prompts, out_paths)):
            if not self._gen_one(page, pr, op, wait_s):
                missing.append(i)
        return missing

    @staticmethod
    def _on_disk(path: str) -> bool:
        """True if a non-empty file already exists at path (a successfully saved
        image we must never lose / regenerate)."""
        try:
            p = Path(path)
            return p.exists() and p.stat().st_size > 0
        except Exception:
            return False

    def gen_images(self, prompts: list[str], out_paths: list[str], wait_s: int, resolution: tuple[int, int] | None = None) -> list[str]:
        """Batch image gen in small waves (Flow's chat-style prompt box cannot
        absorb dozens of rapid submits — firing too many hangs the UI). Each wave
        fires up to WAVE prompts and downloads results as they land.

        Resilience contract (so a flaky shot never costs the whole batch):
          - every image that DOES generate is downloaded + kept immediately;
          - missing slots are retried per-image inside _gen_wave;
          - a wave that still falls short does NOT abort the batch — later waves
            keep running, and the missing indices are reported (logged + returned
            via the gaps left on disk) but NOT raised, so the caller fills them per
            scene (serial regen / stock / text card) and caches whatever landed for
            a quota-free resume;
          - the ONLY hard stop is FlowBlocked (anti-abuse/quota): re-raised so the
            run halts instead of hammering a flagged session — partials already on
            disk are preserved and cached by the caller.
        """
        page = self._ensure_page()
        self._set_image_mode(page, resolution)
        total_waves = (len(prompts) + self.WAVE - 1) // self.WAVE
        missing: list[int] = []
        blocked: FlowBlocked | None = None
        for wi, start in enumerate(range(0, len(prompts), self.WAVE)):
            end = min(start + self.WAVE, len(prompts))
            # RESUME: skip slots already saved — the quota-fallback retry re-runs
            # the whole batch, and regenerating landed images wastes quota.
            idxs = [k for k in range(start, end) if not self._on_disk(out_paths[k])]
            if not idxs:
                continue
            wp = [prompts[k] for k in idxs]
            wo = [out_paths[k] for k in idxs]
            try:
                miss = self._gen_wave(page, wp, wo, wait_s)
            except FlowBlocked as e:
                blocked = e
                # this wave onward is unmade except whatever already hit disk
                missing += [k for k in idxs if not self._on_disk(out_paths[k])]
                print(f"      [flow] blocked at wave {wi + 1}/{total_waves}: {e}", flush=True)
                break
            missing += [idxs[k] for k in miss]
            if wi < total_waves - 1:
                page.wait_for_timeout(self._jitter(25000))  # pace between waves (anti-flag)
        ok = len(prompts) - len(missing)
        if missing:
            print(f"      [flow] batch made {ok}/{len(prompts)} images; missing {missing}", flush=True)
        if blocked is not None:
            raise blocked  # stop the run; partials on disk are cached by the caller
        # Partial shortfall (not a block) is intentionally NOT raised — see contract:
        # the caller fills the gaps per scene and caches what landed for resume.
        return [str(Path(o).resolve()) for o in out_paths]

    def gen_video(self, prompt: str, out_path: str, wait_s: int) -> str:
        """Text-to-video via Flow's Veo. Switches to Video mode, generates, and
        downloads the resulting mp4. Veo renders slowly (minutes)."""
        page = self._ensure_page()
        self._set_video_mode(page)
        before = set(self._all_media_srcs(page))
        self._type_prompt(page, prompt)
        self._click_generate(page)

        new_src: str | None = None
        for _ in range(max(1, wait_s // 5)):
            page.wait_for_timeout(5000)
            cur = self._all_media_srcs(page)
            fresh = [s for s in cur if s and s not in before]
            if fresh:
                page.wait_for_timeout(5000)  # settle
                cur = self._all_media_srcs(page)
                fresh = [s for s in cur if s and s not in before] or fresh
                new_src = fresh[0]
                break
        if not new_src:
            raise MediaError(f"Flow Veo produced no video within {wait_s}s")
        self._download(new_src, out_path)
        return str(Path(out_path).resolve())

    # ------------------------------------------------------------------
    # First/last-frame (FLF) video — "Khung hình" mode with both slots.
    # This is the film path: video interpolates BETWEEN two APPROVED stills
    # (AIComicBuilder/Jellyfish architecture; see storyboard/style_lock.py for
    # why the endpoints must be image-model stills, never video tails).
    # ------------------------------------------------------------------

    def _trpc_get(self, proc: str, payload: dict) -> dict:
        """GET a Flow trpc endpoint through the logged-in browser context.

        Uses context.request (cookies ride along, no page JS) — immune to the
        page-extension fetch-wrapping that broke window.fetch pulls before.
        """
        import json as _json
        import urllib.parse as _up

        url = (f"https://labs.google/fx/api/trpc/{proc}"
               f"?input={_up.quote(_json.dumps({'json': payload}))}")
        resp = self._ctx.request.get(url, timeout=60_000)
        if not resp.ok:
            raise MediaError(f"Flow trpc {proc} failed: HTTP {resp.status}")
        return resp.json()

    def _project_id(self) -> str:
        m = re.search(r"/project/([0-9a-f-]{16,})", self._project or "")
        if not m:
            raise MediaError(f"Flow: no project id in url {self._project!r}")
        return m.group(1)

    def _workflows(self) -> list[dict]:
        """Project workflows newest-first: {name, created, media_id}."""
        r = self._trpc_get("flow.projectInitialData",
                           {"projectId": self._project_id()})
        raw = (r.get("result", {}).get("data", {}).get("json", {})
                .get("projectContents", {}).get("workflows", []))
        rows = []
        for it in raw:
            if not it:
                continue
            w = it.get("workflow", it) or {}
            md = w.get("metadata", {}) or {}
            rows.append({
                "name": md.get("displayName", "") or "",
                "created": md.get("createTime", "") or "",
                "media_id": md.get("primaryMediaId", "") or "",
            })
        rows.sort(key=lambda x: x["created"], reverse=True)
        return rows

    def _fetch_media_bytes(self, media_id: str) -> bytes | None:
        """Pull one finished video via media.fetchMedia (base64 in JSON).
        Returns None while the workflow is still rendering."""
        import base64

        try:
            r = self._trpc_get("media.fetchMedia", {"mediaKey": media_id})
        except MediaError:
            return None
        video = (r.get("result", {}).get("data", {}).get("json", {})
                  .get("result", {}).get("video", {}) or {})
        enc = video.get("encodedVideo")
        if not enc:
            return None
        return base64.b64decode(enc)

    def _fetch_image_bytes(self, media_id: str) -> bytes | None:
        """Pull one finished image via getMediaUrlRedirect (follows to the
        actual file). Returns None while still rendering / not yet routable.
        Raises when the media turns out to be a VIDEO — that means the
        composer generated the wrong kind and billed credits; silently saving
        it as a .jpg only crashes the pipeline further downstream."""
        url = ("https://labs.google/fx/api/trpc/media.getMediaUrlRedirect"
               f"?name={media_id}")
        try:
            resp = self._ctx.request.get(url, timeout=60_000)
        except Exception:
            return None
        if not resp.ok:
            return None
        body = resp.body()
        # A JSON/HTML body means the endpoint answered with an error or a
        # not-ready envelope instead of file bytes.
        if body[:1] in (b"{", b"[", b"<"):
            return None
        if body[:3] == b"\xff\xd8\xff" or body[:8] == b"\x89PNG\r\n\x1a\n" \
                or body[:4] == b"RIFF":
            return body
        if b"ftyp" in body[:16]:
            raise MediaError(
                "Flow returned a VIDEO for an image request — the composer "
                "was in the wrong mode and credits were billed. Aborting.")
        return body  # unknown-but-plausible image container: let PIL decide

    def _await_new_workflow(self, page, before_ids: set[str],
                            skip_names: set[str], wait_s: int,
                            after_ts: str = "",
                            qbase: int | None = None) -> dict:
        """Poll the project feed until a workflow with an UNSEEN media id
        appears. Identity by media_id, never by DOM src (signed URLs churn).
        `after_ts` (ISO from the feed itself) additionally rejects pre-existing
        workflows whose media id only became visible late — an old scene
        object surfacing its media mid-poll must not be mistaken for ours."""
        waited = 0
        while True:
            for w in self._workflows():
                if (w["media_id"] and w["media_id"] not in before_ids
                        and w["name"] not in skip_names
                        and (not after_ts or w["created"] > after_ts)):
                    return w
            if waited >= wait_s:
                raise MediaError(f"Flow: no new workflow within {wait_s}s")
            page.wait_for_timeout(5000)
            waited += 5
            self._check_blocked(page, qbase)

    def _await_media_bytes(self, page, media_id: str, wait_s: int,
                           *, kind: str, qbase: int | None = None) -> bytes:
        """Poll until the workflow's media is downloadable, then return it."""
        fetch = (self._fetch_image_bytes if kind == "image"
                 else self._fetch_media_bytes)
        waited = 0
        while True:
            data = fetch(media_id)
            if data:
                return data
            if waited >= wait_s:
                raise MediaError(
                    f"Flow: media {media_id} not downloadable within {wait_s}s")
            page.wait_for_timeout(5000)
            waited += 5
            self._check_blocked(page, qbase)

    def _set_flf_mode(self, page, seconds: int) -> None:
        """Configure the composer for first/last-frame video via localStorage
        (VIDEO mode + Omni Flash + portrait + duration), then verify the
        Bắt đầu slot rendered."""
        self._exit_agent_mode(page)
        self._apply_prompt_box_state(
            page,
            imageOrVideoMode="VIDEO",
            aspectRatio="PORTRAIT",
            selectedVideoModelFamily="abra",
            selectedVideoDuration=int(seconds),
            outputsPerPrompt=1,
        )
        if not page.get_by_text(re.compile(rf"Video · {seconds}s")).count():
            raise MediaError(
                f"Flow composer chip does not show 'Video · {seconds}s' "
                f"after applying the prompt-box state.")
        if self._slot_button(page, "Bắt đầu") is None \
                and self._slot_button(page, "Kết thúc") is None:
            raise MediaError(
                "Flow FLF: composer shows no frame slots after switching to "
                "VIDEO mode — frames/components submode may need its own "
                "state key (calibrate live).")

    def _slot_button(self, page, slot_label: str):
        """The empty-slot control, however Flow marks it up. The label text
        exists only while the slot is EMPTY (a thumbnail replaces it), so
        text presence == slot empty. None when no such text is on the page."""
        for loc in (page.get_by_role("button", name=slot_label),
                    page.locator(f'button:has-text("{slot_label}")'),
                    page.get_by_text(slot_label, exact=True)):
            if loc.count():
                return loc.first
        return None

    def _slot_attached(self, page, slot_label: str) -> bool:
        return self._slot_button(page, slot_label) is None

    def _attach_frame_slot(self, page, slot_label: str, image_path: str,
                           wait_s: int = 90) -> None:
        """Click the Bắt đầu/Kết thúc slot, upload the still into the picker,
        confirm it landed in the slot. Uploads are unique-named by the caller so
        the picker can never grab a lookalike (the K5-dup lesson)."""
        slot = self._slot_button(page, slot_label)
        if slot is None:
            return  # already filled (retry path)
        slot.click(timeout=10_000)
        page.wait_for_timeout(1500)
        inputs = page.locator('input[type="file"]')
        if not inputs.count():
            raise MediaError(f"Flow FLF: no file input after opening {slot_label!r} picker")
        inputs.last.set_input_files(image_path)
        # Upload → either auto-attaches to the open slot, or leaves the item
        # selected with an enabled "Thêm vào câu lệnh" button. Handle both.
        deadline = wait_s * 1000
        step = 1500
        waited = 0
        while waited < deadline:
            page.wait_for_timeout(step)
            waited += step
            if self._slot_attached(page, slot_label):
                page.keyboard.press("Escape")  # close picker if it lingered
                page.wait_for_timeout(300)
                if self._slot_attached(page, slot_label):
                    return
                continue  # Escape wiped it (observed once) — loop re-checks
            try:
                add = page.get_by_role("button", name=re.compile("Add to prompt|Thêm vào câu lệnh"))
                if add.count() and add.first.is_enabled():
                    add.first.click()
                    page.wait_for_timeout(800)
            except Exception:
                pass
        raise MediaError(
            f"Flow FLF: still not attached to {slot_label!r} after {wait_s}s "
            f"({image_path})")

    def gen_video_flf(self, prompt: str, start_path: str, end_path: str,
                      seconds: int, out_path: str, wait_s: int) -> dict:
        """One FLF clip: start still + end still + motion-delta prompt.

        Returns {"path", "workflow", "media_id"} for plan.json write-back
        (Orkas: produced artifacts must be re-renderable/diffable).
        """
        page = self._ensure_page()
        self._check_blocked(page, self._quota_card_count(page))
        self._set_flf_mode(page, seconds)
        feed = self._workflows()
        before_ids = {w["media_id"] for w in feed if w["media_id"]}
        newest_ts = feed[0]["created"] if feed else ""
        self._attach_frame_slot(page, "Bắt đầu", start_path)
        self._attach_frame_slot(page, "Kết thúc", end_path)
        self._type_prompt(page, prompt)
        qbase = self._quota_card_count(page)
        self._click_generate(page)
        page.wait_for_timeout(4000)

        # Identify the new workflow via the API, not the DOM: virtualized grids
        # lie, the project feed doesn't. Uploaded stills also create workflows
        # named after their file — skip those.
        upload_names = {Path(start_path).name, Path(end_path).name}
        new_wf = self._await_new_workflow(page, before_ids, upload_names,
                                          wait_s, after_ts=newest_ts,
                                          qbase=qbase)
        data = self._await_media_bytes(page, new_wf["media_id"], wait_s,
                                       kind="video", qbase=qbase)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return {"path": str(out.resolve()), "workflow": new_wf["name"],
                "media_id": new_wf["media_id"]}

    def close(self) -> None:
        def _c():
            try:
                if self._ctx:
                    self._ctx.close()
            finally:
                if self._pw:
                    self._pw.stop()
        try:
            self.submit(_c)
        except Exception:
            pass
        self._exec.shutdown(wait=False)
        self._release_flow_xlock()  # let a waiting render take Flow


class FlowProvider:
    """Image provider backed by Google Flow's web UI (browser automation)."""

    id = "flow"
    name = "Google Flow (browser)"
    models = [
        ModelOption(id="nano-banana", name="Nano Banana (Imagen)",
                    description="Flow image gen, ~1376x768 16:9, uses Flow plan credits"),
    ]

    def __init__(self, profile_dir: str | None = None, project_url: str | None = None) -> None:
        # Resolution order: explicit arg > env var > settings > repo default.
        s_image_model = ""
        try:
            from omnicast.config.settings import get_settings
            s = get_settings()
            s_profile, s_project = s.flow_profile_dir, s.flow_project_url
            s_image_model = getattr(s, "flow_image_model", "") or ""
        except Exception:
            s_profile, s_project = "", ""
        # Image model: env > settings (channel can set env FLOW_IMAGE_MODEL per render).
        self._image_model = os.environ.get("FLOW_IMAGE_MODEL") or s_image_model or ""
        default_profile = str(Path(__file__).resolve().parents[4] / ".flow_profile")
        self._profile = (
            profile_dir or os.environ.get("FLOW_PROFILE") or s_profile or default_profile
        )
        self._project = (
            project_url or os.environ.get("FLOW_PROJECT_URL") or s_project or ""
        )
        # One fresh Flow project per video (default) — avoids old images piling up
        # and confusing the newest-first result mapping. Set FLOW_NEW_PROJECT=0 to
        # reuse FLOW_PROJECT_URL instead. An EXPLICIT project_url argument flips
        # the default to reuse: a caller that names a project means that project
        # (the film pipeline's characters/settings live in it — a silent fresh
        # project generated off-style stills for a full bounded-reroll cycle
        # before this was caught).
        self._create_new = (os.environ.get("FLOW_NEW_PROJECT",
                                           "0" if project_url else "1") != "0")
        # Ingredients (WS1): reference images for character consistency.
        # env FLOW_INGREDIENTS = os.pathsep-separated image paths — lets the
        # render set them per-channel/per-video without new CLI plumbing.
        self._reference_images = self._refs_from_env()
        self._characters: list[str] = []
        self._prompt_assets: list[str] = []
        self._prompt_files: list[str] = []
        self._session: _FlowSession | None = None

    @staticmethod
    def _refs_from_env() -> list[str]:
        raw = os.environ.get("FLOW_INGREDIENTS", "").strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(os.pathsep) if p.strip()]

    def set_reference_images(self, ref_images: list[str] | None) -> None:
        """Set/replace the ingredient reference images (e.g. the per-character
        anchor set from omnicast.media.character_anchor). Applies to the live
        session immediately if one is open."""
        self._reference_images = list(ref_images or [])
        if self._session is not None:
            self._session.set_ref_images(self._reference_images)

    def set_characters(self, names: list[str] | None) -> None:
        """Attach the project's saved CHARACTERS to every generation (the way
        this project's approved keyframes were actually conditioned)."""
        self._characters = list(names or [])
        if self._session is not None:
            self._session.set_characters(self._characters)

    def set_prompt_assets(self, names: list[str] | None) -> None:
        """Attach project image assets (by display name, e.g. 'K1.jpg') to
        every generation as visual style anchors."""
        self._prompt_assets = list(names or [])
        if self._session is not None:
            self._session.set_prompt_assets(self._prompt_assets)

    def set_prompt_files(self, paths: list[str] | None) -> None:
        """Attach LOCAL image files to every generation via the @-picker
        upload tab (per-still anchor + previous keyframe)."""
        self._prompt_files = list(paths or [])
        if self._session is not None:
            self._session.set_prompt_files(self._prompt_files)

    def _sess(self) -> _FlowSession:
        if not self._create_new and not self._project:
            raise MediaError(
                "No Flow project: set FLOW_PROJECT_URL, or leave FLOW_NEW_PROJECT=1 "
                "to auto-create a fresh project per video."
            )
        if not Path(self._profile).exists():
            raise MediaError(
                f"Flow profile not found at {self._profile}. Run scripts/flow_login.py first."
            )
        if self._session is None:
            self._session = _FlowSession(self._profile, self._project,
                                         create_new=self._create_new,
                                         image_model=self._image_model,
                                         ref_images=self._reference_images)
            if self._characters:
                self._session.set_characters(self._characters)
            if self._prompt_assets:
                self._session.set_prompt_assets(self._prompt_assets)
            if self._prompt_files:
                self._session.set_prompt_files(self._prompt_files)
        return self._session

    async def _run_with_banana_fallback(self, call):
        """Run a session call; if Nano Banana Pro trips Flow's quota/limit guard,
        downgrade ONCE to Nano Banana 2 (fresh session, model re-applied) and
        retry. A second FlowBlocked is a real account-level anti-abuse block —
        re-raise and wait it out (never hammer a flagged session)."""
        try:
            return await call()
        except FlowModelQuota:
            # Model-specific 'out of uses for Nano Banana Pro' — fires even when
            # WE never picked Pro (Flow's UI default can be Pro). Always switch.
            if self._image_model == "Nano Banana 2":
                raise  # already on the fallback model — nothing left to switch to
            print("      [flow] Nano Banana Pro out of uses — "
                  "falling back to Nano Banana 2")
            try:
                if self._session is not None:
                    self._session.close()
            except Exception:
                pass
            self._session = None
            self._image_model = "Nano Banana 2"
            return await call()
        except FlowBlocked:
            if self._image_model != "Nano Banana Pro":
                raise
            print("      [flow] Nano Banana Pro blocked — "
                  "falling back to Nano Banana 2")
            try:
                if self._session is not None:
                    self._session.close()
            except Exception:
                pass
            self._session = None
            self._image_model = "Nano Banana 2"
            return await call()

    async def generate(
        self,
        prompt: str,
        *,
        negative: str = "",
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
        wait_s: int = 180,
    ) -> str:
        # All Playwright sync calls MUST run on the session's single worker thread
        # (sync API is thread-affine). sess.submit dispatches there; to_thread keeps
        # the blocking .result() off the event loop.
        async def _call():
            sess = self._sess()
            return await asyncio.to_thread(
                sess.submit, sess.gen_image, prompt, output_path, wait_s, resolution)
        return await self._run_with_banana_fallback(_call)

    async def generate_multi(
        self, prompt: str, output_paths: list[str], *,
        resolution: tuple[int, int] | None = None, wait_s: int = 300,
    ) -> list[str]:
        """ONE prompt → up to 4 images using Flow's native x2/x3/x4 output
        setting (0 credits, one submission). Preferred over generate_batch when
        you want VARIATIONS of the same prompt."""
        async def _call():
            sess = self._sess()
            return await asyncio.to_thread(
                sess.submit, sess.gen_image_multi, prompt, output_paths, wait_s, resolution)
        return await self._run_with_banana_fallback(_call)

    async def generate_batch(
        self, prompts: list[str], output_paths: list[str], *, resolution: tuple[int, int] | None = None, wait_s: int = 480,
    ) -> list[str]:
        """Generate many images via Flow in small waves with per-image retry.

        Partial-tolerant: each image that generates is downloaded immediately and
        only the failed slots are retried, so a flaky shot never discards good
        ones. A shortfall is NOT raised — the missing output paths are simply left
        absent on disk for the caller to fill per scene (and cache what landed for
        a quota-free resume). The only exception raised is FlowBlocked, when Flow's
        anti-abuse/quota guard trips and the run must stop and wait it out.
        """
        if len(prompts) != len(output_paths):
            raise MediaError("generate_batch: prompts and output_paths length mismatch")

        async def _call():
            sess = self._sess()
            return await asyncio.to_thread(
                sess.submit, sess.gen_images, prompts, output_paths, wait_s, resolution)
        return await self._run_with_banana_fallback(_call)

    async def convert(
        self,
        image_path: str,
        prompt: str,
        *,
        duration: int = 5,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
        wait_s: int = 600,
    ) -> str:
        """IVideoProvider: Veo text-to-video via Flow.

        v1 is text-driven (image_path is currently ignored; Flow's image->video
        first-frame wiring is a future calibration step). Veo is slow (minutes).
        """
        sess = self._sess()
        return await asyncio.to_thread(
            sess.submit, sess.gen_video, prompt, output_path, wait_s
        )

    #: FLF ("Khung hình" both slots) is implemented — film_runner keys on this.
    supports_last_frame = True

    async def convert_flf(self, start_path: str, end_path: str, prompt: str,
                          *, seconds: int, output_path: str,
                          wait_s: int = 480) -> dict:
        """First/last-frame clip between two APPROVED stills (the film path).
        Returns {"path", "workflow", "media_id"}."""
        sess = self._sess()
        return await asyncio.to_thread(
            sess.submit, sess.gen_video_flf, prompt, start_path, end_path,
            seconds, output_path, wait_s)

    async def credits(self) -> int | None:
        """Current Flow credit balance (None if unreadable). Image gen is free;
        Veo video costs credits."""
        sess = self._sess()
        return await asyncio.to_thread(sess.submit, sess.read_credits)

    async def preflight_video(self, n_clips: int, cost_per_clip: int | None = None) -> dict:
        """Estimate credits for an n-clip Veo render and check the balance.

        cost_per_clip: known credits/clip; if None, falls back to env
        FLOW_VEO_COST (default 20 — measured ~7/clip for a 4s Veo Fast clip on
        2026-05; the accurate path is to measure the balance delta on the first
        generated clip at runtime, then project the remainder).

        Returns {balance, cost_per_clip, needed, ok}. Raises MediaError if the
        balance is readable AND insufficient, so the run aborts before starting.
        """
        cpc = cost_per_clip or int(os.environ.get("FLOW_VEO_COST", "20"))
        balance = await self.credits()
        needed = n_clips * cpc
        info = {"balance": balance, "cost_per_clip": cpc, "needed": needed,
                "ok": balance is None or balance >= needed}
        if balance is not None and balance < needed:
            raise MediaError(
                f"Insufficient Flow credits: need ~{needed} ({n_clips}x{cpc}) "
                f"but balance is {balance}. Reduce shots or top up before rendering."
            )
        return info

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
