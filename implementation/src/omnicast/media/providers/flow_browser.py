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
_RESULT_IMG_SEL = 'img[alt="Hình ảnh được tạo"]'  # "Generated image" (vi locale)
_MODEL_CHIP_RE = r"Nano Banana|Veo"
_FLOW_HOME = "https://labs.google/fx/vi/tools/flow"
_NEW_PROJECT_SEL = 'button:has-text("Dự án mới")'  # "New project"


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
        "nano-banana-pro": "Nano Banana Pro", "nano_banana_pro": "Nano Banana Pro",
        "pro": "Nano Banana Pro",
    }

    def __init__(self, profile_dir: str, project_url: str, create_new: bool = False,
                 image_model: str = "") -> None:
        self._profile = profile_dir
        self._project = project_url
        self._create_new = create_new
        # Desired Flow image model (label). Empty = keep Flow's current default.
        self._image_model = self._MODEL_LABELS.get((image_model or "").lower().strip(), "")
        self._pw = None
        self._ctx = None
        self._page = None
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow")
        self._lock = threading.Lock()
        self._xlock_dir: Path | None = None  # cross-process Flow mutex (see below)

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
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self._profile,
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1500, "height": 950},
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        if self._create_new or not self._project:
            self._new_project(self._page)
        else:
            self._page.goto(self._project, wait_until="domcontentloaded", timeout=120_000)
            self._page.wait_for_timeout(4000)
        # Editor can take a few seconds to mount the prompt box after the project
        # URL resolves; wait for it so the first _type_prompt doesn't race-fail.
        try:
            self._page.wait_for_selector(_PROMPT_SEL, timeout=30_000)
        except Exception:
            print("[flow] warn: prompt textbox not visible after 30s", flush=True)
        self._dismiss_welcome_popup(self._page)
        return self._page

    def _dismiss_welcome_popup(self, page) -> None:
        """Radix UI changelog/welcome popups occasionally block the UI. If detected,
        programmatically remove the modal dialog and backdrop overlays from the DOM
        to restore pointer events to the underlying editor interface."""
        try:
            iframe_sel = 'iframe[src*="changelogs"]'
            if page.locator(iframe_sel).count() > 0:
                print("[flow] Welcome/changelog popup detected. Dismissing it...", flush=True)
                page.evaluate("""() => {
                    const dialog = document.querySelector('[role="dialog"]');
                    if (dialog) dialog.remove();
                    const overlays = document.querySelectorAll('[class*="sc-74a44e9a-0"], [class*="jDwSWX"]');
                    overlays.forEach(overlay => overlay.remove());
                    
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
        before = page.url
        try:
            page.locator(_NEW_PROJECT_SEL).first.click(timeout=8000)
        except Exception as exc:
            raise MediaError(f"Flow: could not click 'Dự án mới' (new project): {exc}")
        for _ in range(20):  # wait for navigation into /project/<id>
            page.wait_for_timeout(1000)
            if "/project/" in page.url and page.url != before:
                break
        if "/project/" not in page.url:
            raise MediaError("Flow: new project did not open a /project/ URL")
        page.wait_for_timeout(3000)
        self._project = page.url
        print(f"[flow] new project: {self._project}", flush=True)

    def _type_prompt(self, page, prompt: str) -> None:
        self._dismiss_welcome_popup(page)
        box = page.locator(_PROMPT_SEL).first
        # Explicit timeout so a covered/disabled prompt box (e.g. while Flow is
        # busy) fails fast instead of blocking on Playwright's 30s default.
        box.click(timeout=10_000)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.type(prompt, delay=2)
        page.wait_for_timeout(400)

    def _click_generate(self, page) -> None:
        gen = page.locator(_GENERATE_SEL).last
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
            agent = page.locator('button:has-text("Tác nhân")').first
            if agent.count() and (agent.get_attribute("aria-pressed") == "true"):
                agent.click(timeout=5000)
                page.wait_for_timeout(1200)
        except Exception:
            pass

    def _open_settings_panel(self, page) -> None:
        """Open the model/format popover (chip shows model + aspect + count)."""
        for pat in ("crop_", "Imagen", "Veo", "Banana", "🍌"):
            loc = page.locator(f'button:has-text("{pat}")')
            if loc.count():
                try:
                    loc.last.click(timeout=6000)
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
                if page.locator('button:has-text("Tác nhân")').count():
                    return  # already in direct mode
                x = page.locator('button:has-text("close")').last
                if not x.count():
                    return
                x.click(timeout=4000)
                page.wait_for_timeout(800)
        except Exception as e:
            print(f"      [flow] close agent panel skipped ({e})", flush=True)

    def _set_image_mode(self, page, resolution: tuple[int, int] | None = None) -> None:
        """Put the project in the CLASSIC direct image composer: close the agent
        chat panel (→ fast direct gen), then apply the requested image model.
        The account's composer default can be Nano Banana PRO (quota-limited) —
        `_select_model` was previously defined but never wired, so the configured
        model AND the Pro→2 quota fallback both silently did nothing."""
        self._close_agent_panel(page)
        page.wait_for_timeout(300)
        if self._image_model:
            try:
                self._select_model(page, self._image_model)
            except Exception as e:
                print(f"      [flow] model select skipped ({e})", flush=True)

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

    def gen_image(self, prompt: str, out_path: str, wait_s: int, resolution: tuple[int, int] | None = None) -> str:
        page = self._ensure_page()
        self._set_image_mode(page, resolution)
        self._check_blocked(page)  # raises FlowBlocked early instead of waiting out wait_s
        # Track by src set, not count: Flow virtualizes the media grid, so the
        # element count can stay flat while new results appear/old ones unmount.
        before = set(self._newest_result_srcs(page))
        self._type_prompt(page, prompt)
        self._click_generate(page)

        new_src: str | None = None
        for _ in range(max(1, wait_s // 3)):
            page.wait_for_timeout(3000)
            cur = self._newest_result_srcs(page)
            fresh = [s for s in cur if s and s not in before]
            if fresh:
                page.wait_for_timeout(3000)  # settle (image finishes loading)
                cur = self._newest_result_srcs(page)
                fresh = [s for s in cur if s and s not in before] or fresh
                new_src = fresh[0]
                break
        if not new_src:
            raise MediaError(f"Flow produced no image within {wait_s}s")

        self._download(new_src, out_path)
        return str(Path(out_path).resolve())

    WAVE = 3  # max prompts per wave — smaller bursts are gentler on Flow's abuse limits

    @staticmethod
    def _jitter(base_ms: int, spread: float = 0.35) -> int:
        """Randomise a wait so the cadence looks human, not bot-regular. A flagged
        Flow session relaxes faster when traffic is irregular + spaced out."""
        lo = int(base_ms * (1 - spread))
        hi = int(base_ms * (1 + spread))
        return random.randint(lo, hi)

    def _check_blocked(self, page) -> None:
        """Detect Flow's 'unusual activity' / rate-limit block. If present, abort
        immediately (do NOT retry — hammering a flagged session makes it worse and
        is exactly what the block guards against). The operator must wait it out."""
        try:
            txt = page.evaluate(
                "() => document.body ? document.body.innerText : ''") or ""
        except Exception:
            return
        low = txt.lower()
        # MODEL-specific quota ('...hết hạn mức... Nano Banana Pro. Hãy thử dùng
        # một mô hình khác.') → switching model fixes it; raise the fallback-able
        # subclass BEFORE the generic quota check.
        if ("nano banana pro" in low
                and ("hết hạn mức" in low or "hạn mức về số lượt" in low
                     or "reached your limit" in low or "try another model" in low
                     or "mô hình khác" in low)):
            raise FlowModelQuota(
                "Nano Banana Pro hết lượt — chuyển Nano Banana 2 (fallback tự động)."
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
        # reuse FLOW_PROJECT_URL instead.
        self._create_new = os.environ.get("FLOW_NEW_PROJECT", "1") != "0"
        self._session: _FlowSession | None = None

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
                                         image_model=self._image_model)
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
