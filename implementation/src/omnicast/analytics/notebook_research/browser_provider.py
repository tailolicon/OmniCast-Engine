"""Playwright worker driving NotebookLM through the run state machine.

Happy path only, by design: semantic selectors (selectors.py), idempotent
manifest (manifest.py), condition-based waits with hard deadlines (never a
bare sleep), and artifacts (screenshot + accessibility snapshot + trace) on
every failure. UI drift beyond the selector table is NOT handled here — that
is the supervisor's job (an agent choosing one action from
SUPERVISOR_ALLOWLIST), and auth loss surfaces as AUTH_REQUIRED so the caller
falls back to the Native Learner instead of dying.

LIVE-RUN STATUS: this module is code-complete but UNVERIFIED against the real
NotebookLM UI until `scripts/notebooklm_login.py` has been run once and a
supervised first run calibrates the selector table (the login script dumps a
DOM inspection JSON for exactly that). Do not mark the NotebookLM provider
"done" until that first run passes — module ≠ capability.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

from omnicast.analytics.notebook_research.manifest import RunManifest
from omnicast.analytics.notebook_research.selectors import SELECTORS
from omnicast.analytics.notebook_research.state_machine import RunState

logger = structlog.get_logger()

NOTEBOOKLM_URL = "https://notebooklm.google.com/?hl=en"

# Deadlines (seconds). Condition-based polls run every POLL_S until deadline;
# a deadline hit is a FAILURE with artifacts, never a silent success.
POLL_S = 2.0
DEADLINE_AUTH = 60
DEADLINE_NOTEBOOK = 90
DEADLINE_UPLOAD_PER_SOURCE = 90
DEADLINE_INDEX_PER_SOURCE = 120
DEADLINE_RESPONSE = 420
RESPONSE_STABLE_CHECKS = 3


class AuthRequired(RuntimeError):
    pass


class UiDeadline(RuntimeError):
    pass


class NotebookLMWorker:
    def __init__(self, *, profile_dir: Path, work_dir: Path,
                 headless: bool = True) -> None:
        self.profile_dir = Path(profile_dir)
        self.work_dir = Path(work_dir)
        self.artifacts = self.work_dir / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self._pw = None
        self._ctx = None
        self.page = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def __enter__(self) -> "NotebookLMWorker":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        kwargs = dict(
            user_data_dir=str(self.profile_dir), headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--lang=en-US"],
            locale="en-US", viewport={"width": 1500, "height": 950},
        )
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                channel="chrome", **kwargs)
        except Exception:
            self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        try:
            self._ctx.tracing.start(screenshots=True, snapshots=True)
        except Exception:
            pass
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc is not None:
                self.save_failure_artifacts(reason=str(exc)[:120])
            if self._ctx is not None:
                try:
                    self._ctx.tracing.stop(
                        path=str(self.artifacts / "trace_last.zip"))
                except Exception:
                    pass
                self._ctx.close()
        finally:
            if self._pw is not None:
                self._pw.stop()

    # ── element resolution (semantic first) ──────────────────────────────────

    def find(self, key: str, *, timeout_s: float = 10.0,
             require_visible: bool = True):
        """Resolve a semantic selector to the first match, or None.

        require_visible=False exists for file inputs: real uploaders keep
        `input[type=file]` at display:none behind a styled button, and
        Playwright can set files on a hidden input just fine — requiring
        visibility was exactly why the first live run failed."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for strategy, value in SELECTORS[key]:
                try:
                    if strategy.startswith("role:"):
                        loc = self.page.get_by_role(
                            strategy.split(":", 1)[1],
                            name=re.compile(value, re.I))
                    elif strategy == "text":
                        loc = self.page.locator(f"text=/{value}/i")
                    else:
                        loc = self.page.locator(value)
                    if loc.count() and (not require_visible or loc.first.is_visible()):
                        return loc.first
                except Exception:
                    continue
            time.sleep(0.5)
        return None

    def save_failure_artifacts(self, reason: str = "") -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            self.page.screenshot(
                path=str(self.artifacts / f"fail_{stamp}.png"))
        except Exception:
            pass
        try:
            snap = self.page.accessibility.snapshot()
            (self.artifacts / f"fail_{stamp}.a11y.json").write_text(
                json.dumps({"reason": reason, "url": self.page.url,
                            "snapshot": snap}, ensure_ascii=False)[:2_000_000],
                encoding="utf-8")
        except Exception:
            pass

    # ── stages ───────────────────────────────────────────────────────────────

    def auth_check(self) -> None:
        self.page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded",
                       timeout=DEADLINE_AUTH * 1000)
        deadline = time.monotonic() + DEADLINE_AUTH
        while time.monotonic() < deadline:
            if self.find("signed_out_marker", timeout_s=1):
                raise AuthRequired(
                    "NotebookLM session signed out — run scripts/notebooklm_login.py")
            if self.find("create_notebook", timeout_s=1):
                return
            time.sleep(POLL_S)
        raise UiDeadline("auth_check: neither sign-in page nor notebook UI appeared")

    def resolve_notebook(self, notebook_key: str,
                         notebook_url: str = "") -> str:
        """Open the run's notebook and return its URL (the stable identity —
        titles are cosmetic and renames can fail silently).

        Priority: stored URL → title match on the home list → create new
        (then best-effort rename via the 'Untitled notebook' header)."""
        if notebook_url:
            # Force English UI: the ACCOUNT language (Vietnamese) overrides the
            # browser locale, and a bare notebook URL rendered VI — which is
            # why EN-only probes missed "Hộp truy vấn". Selectors stay
            # bilingual anyway; hl=en just narrows the variance.
            if "hl=" not in notebook_url:
                notebook_url += ("&" if "?" in notebook_url else "?") + "hl=en"
            self.page.goto(notebook_url, wait_until="domcontentloaded",
                           timeout=DEADLINE_NOTEBOOK * 1000)
            if self._wait_notebook_open():
                return self.page.url
            raise UiDeadline("resolve_notebook: stored notebook URL did not open")

        existing = self.page.locator(f"text={notebook_key}")
        try:
            if existing.count() and existing.first.is_visible():
                existing.first.click()
                if self._wait_notebook_open():
                    return self.page.url
        except Exception:
            pass

        btn = self.find("create_notebook", timeout_s=15)
        if btn is None:
            raise UiDeadline("resolve_notebook: create button not found")
        btn.click()
        if not self._wait_notebook_open():
            raise UiDeadline("resolve_notebook: notebook page did not open")
        # Best-effort rename: click the 'Untitled notebook' header, type key.
        try:
            header = self.find("notebook_title_header", timeout_s=8)
            if header is not None:
                header.click()
                self.page.keyboard.press("Control+a")
                self.page.keyboard.type(notebook_key)
                self.page.keyboard.press("Enter")
        except Exception:
            logger.warning("notebook rename failed — URL remains the identity")
        return self.page.url

    def _wait_notebook_open(self) -> bool:
        deadline = time.monotonic() + DEADLINE_NOTEBOOK
        while time.monotonic() < deadline:
            if self.find("add_source", timeout_s=1) or self.find("chat_input", timeout_s=1):
                return True
            time.sleep(POLL_S)
        return False

    def _open_sources_dialog(self) -> None:
        """The add-sources dialog AUTO-OPENS on a fresh notebook (live
        screenshot 2026-07-26); only click 'Add sources' when it isn't up."""
        if self.find("sources_dialog_marker", timeout_s=3) is not None:
            return
        add = self.find("add_source", timeout_s=20)
        if add is None:
            raise UiDeadline("sources dialog: Add sources button not found")
        add.click()
        if self.find("sources_dialog_marker", timeout_s=15) is None:
            raise UiDeadline("sources dialog did not open")

    def upload_sources(self, manifest: RunManifest, base_dir: Path) -> None:
        """Multi-select upload of all pending PACKET sources in one shot.

        Two mechanisms, in order: expect_file_chooser around the 'Upload
        files' button (the real UI opens a native chooser), then a hidden
        `input[type=file]` (visibility NOT required — that requirement was the
        first live-run failure)."""
        pending = [s for s in manifest.pending_uploads()
                   if s.source_kind == "packet"]
        if not pending:
            return
        self._open_sources_dialog()
        paths = [s.packet_path for s in pending]

        done = False
        opt = self.find("upload_file_option", timeout_s=10)
        if opt is not None:
            try:
                with self.page.expect_file_chooser(timeout=15000) as fc:
                    opt.click()
                fc.value.set_files(paths)
                done = True
            except Exception:
                pass
        if not done:
            file_input = self.find("file_input", timeout_s=15,
                                   require_visible=False)
            if file_input is None:
                raise UiDeadline("upload_sources: no file chooser and no file input")
            file_input.set_input_files(paths)

        for s in pending:
            s.upload_status = "uploaded"
            s.attempts += 1
        manifest.save(base_dir)

    def add_url_sources(self, manifest: RunManifest, base_dir: Path,
                        batch_limit: int = 40) -> None:
        """URL-first ingestion: add pending youtube_url sources one by one via
        the Websites option (NotebookLM pulls the transcript itself). Failures
        are recorded per-source for the caption/ASR packet fallback — one bad
        URL never stops the batch."""
        pending = [s for s in manifest.pending_uploads()
                   if s.source_kind == "youtube_url"][:batch_limit]
        for s in pending:
            try:
                self._open_sources_dialog()
                opt = self.find("website_source_option", timeout_s=10)
                if opt is None:
                    raise UiDeadline("url source: Websites option not found")
                opt.click()
                box = self.find("url_input", timeout_s=15)
                if box is None:
                    raise UiDeadline("url source: URL input not found")
                box.fill(s.url)
                confirm = self.find("url_submit", timeout_s=10)
                if confirm is not None:
                    confirm.click()
                else:
                    self.page.keyboard.press("Enter")
                s.upload_status = "uploaded"
            except Exception as exc:  # noqa: BLE001 — recorded, fallback later
                s.upload_status = "failed"
                s.last_error = str(exc)[:200]
                self.save_failure_artifacts(reason=f"url source {s.video_id}")
            s.attempts += 1
            manifest.save(base_dir)

    def _source_count_on_page(self) -> int:
        """Indexed-source count, strongest signal first (calibrated from the
        live UI 2026-07-26): the app itself prints "N sources" in the chat
        footer and overview header — that number IS the indexed count. The
        first live run sat on `[role=listitem]` (which matches nothing in the
        real sources panel) until deadline."""
        try:
            texts = self.page.locator(r"text=/\d+\s+(sources?|nguồn)/i")
            best = 0
            for i in range(min(texts.count(), 6)):
                m = re.search(r"(\d+)\s+(?:sources?|nguồn)",
                              texts.nth(i).inner_text(), re.I)
                if m:
                    best = max(best, int(m.group(1)))
            if best:
                return best
        except Exception:
            pass
        for probe in (r"text=/\.md/", SELECTORS["source_list_item"][0][1]):
            try:
                n = self.page.locator(probe).count()
                if n:
                    return n
            except Exception:
                continue
        return 0

    def wait_for_indexing(self, manifest: RunManifest, base_dir: Path) -> None:
        """Condition wait: source count reaches expectation AND no processing
        indicator remains. Deadline scales with source count."""
        expected = len(manifest.sources)
        deadline = time.monotonic() + DEADLINE_INDEX_PER_SOURCE * max(1, expected)
        stable = 0
        while time.monotonic() < deadline:
            count = self._source_count_on_page()
            processing = self.find("processing_indicator", timeout_s=1) is not None
            if count >= expected and not processing:
                stable += 1
                if stable >= 2:
                    for s in manifest.sources:
                        if s.upload_status == "uploaded":
                            s.upload_status = "indexed"
                    manifest.save(base_dir)
                    return
            else:
                stable = 0
            time.sleep(POLL_S)
        raise UiDeadline(
            f"wait_for_indexing: {expected} sources not ready within deadline "
            f"(last count {self._source_count_on_page()})")

    def run_prompt(self, prompt_text: str) -> str:
        """Send one prompt; return the final response text once it stops
        changing across RESPONSE_STABLE_CHECKS consecutive polls."""
        box = self.find("chat_input", timeout_s=30)
        if box is None:
            raise UiDeadline("run_prompt: chat input not found")
        box.click()
        box.fill(prompt_text)
        # WRONG-BOX GUARD: run 5 filled the sources-panel discovery textarea
        # and nothing noticed. The value must land in the box we filled.
        try:
            got = box.input_value()
        except Exception:
            got = ""
        if prompt_text[:60] not in (got or ""):
            raise UiDeadline("run_prompt: prompt text did not land in the chat box "
                             "(wrong element matched?)")
        # Angular Material enables Submit only on REAL input events — a
        # programmatic fill leaves it disabled (run 6 timed out clicking a
        # disabled button). Nudge with a no-op keystroke pair, then click;
        # Enter in the box is the fallback either way.
        box.press("End")
        self.page.keyboard.type(" ")
        self.page.keyboard.press("Backspace")
        # Enter in the chat box is the PROVEN send path (probe 2026-07-26).
        # The only button matching aria "Submit" belongs to the sources-panel
        # discovery form and sits disabled — clicking it burns the timeout.
        clicked = False
        send = self.find("send_button", timeout_s=2)
        if send is not None:
            try:
                if send.is_enabled():
                    send.click(timeout=5000)
                    clicked = True
            except Exception:
                pass
        if not clicked:
            box.press("Enter")

        deadline = time.monotonic() + DEADLINE_RESPONSE
        last, stable = "", 0
        while time.monotonic() < deadline:
            time.sleep(POLL_S)
            text = self._latest_response_text()
            if text and text == last:
                stable += 1
                if stable >= RESPONSE_STABLE_CHECKS:
                    return text
            else:
                stable = 0
                last = text
        raise UiDeadline("run_prompt: response did not stabilise before deadline")

    def _latest_response_text(self) -> str:
        for _, css in SELECTORS["response_container"]:
            try:
                loc = self.page.locator(css)
                if loc.count():
                    return loc.last.inner_text().strip()
            except Exception:
                continue
        return ""

    def capture_citations(self, max_chips: int = 40) -> list[dict]:
        """Best-effort citation harvest: click each chip, record the panel
        text, close. Failures are recorded per-chip, never fatal."""
        out: list[dict] = []
        for _, css in SELECTORS["citation_chip"]:
            try:
                chips = self.page.locator(css)
                n = min(chips.count(), max_chips)
            except Exception:
                continue
            if not n:
                continue
            for i in range(n):
                rec: dict = {"citation_no": i + 1}
                try:
                    chips.nth(i).click()
                    time.sleep(1.0)
                    panel = self.page.locator("[role=dialog], [role=complementary]")
                    if panel.count():
                        text = panel.last.inner_text()[:2000]
                        rec["quoted_text"] = text
                        m = re.search(r"\b(WIN|CTL)_([A-Za-z0-9_-]{6,})_", text)
                        if m:
                            rec["source_video_id"] = m.group(2)
                        ts = re.search(r"\[(\d{2}:\d{2})\]", text)
                        if ts:
                            rec["timestamp"] = ts.group(1)
                    self.page.keyboard.press("Escape")
                except Exception as exc:
                    rec["error"] = str(exc)[:120]
                out.append(rec)
            break  # first working strategy wins
        return out


# ── stage driver (used by scripts/competitor_research.py) ────────────────────


def run_notebook_stage(manifest: RunManifest, base_dir: Path,
                       worker: NotebookLMWorker,
                       prompt_texts: dict[str, str]) -> RunManifest:
    """Advance the manifest through the state machine with `worker`.

    Raises AuthRequired for the caller to fall back to the Native Learner.
    Any UiDeadline marks FAILED with artifacts and re-raises."""
    state = manifest.resume_state()
    if manifest.state == RunState.START:
        manifest.transition(RunState.AUTH_CHECK, base_dir)
    elif manifest.state in (RunState.FAILED, RunState.AUTH_REQUIRED):
        # Terminal states have no legal transitions — a resumed attempt resets
        # to AUTH_CHECK explicitly, with the reset on the record. Source/prompt
        # progress survives in the manifest, so nothing is redone.
        manifest.state = RunState.AUTH_CHECK
        manifest.history.append(
            f"{datetime.now(timezone.utc).isoformat()} -> AUTH_CHECK (resume after "
            "failure)")
        manifest.save(base_dir)
        state = RunState.AUTH_CHECK
    try:
        # NAVIGATION CONTEXT IS NEVER RESUMABLE: a fresh browser starts at
        # about:blank no matter what the manifest remembers, so auth + opening
        # the notebook run on EVERY invocation (cheap, idempotent). Live runs
        # 3-4 hung exactly here — resume jumped to WAIT_FOR_INDEXING and polled
        # a blank page until deadline.
        worker.auth_check()
        if state == RunState.AUTH_CHECK:
            manifest.transition(RunState.RESOLVE_NOTEBOOK, base_dir)
            state = RunState.RESOLVE_NOTEBOOK
        manifest.notebook_url = worker.resolve_notebook(
            manifest.notebook_key, manifest.notebook_url)
        manifest.save(base_dir)
        if state == RunState.RESOLVE_NOTEBOOK:
            manifest.transition(RunState.UPLOAD_SOURCES, base_dir)
            state = RunState.UPLOAD_SOURCES
        if state == RunState.UPLOAD_SOURCES:
            worker.upload_sources(manifest, base_dir)
            worker.add_url_sources(manifest, base_dir)
            manifest.transition(RunState.WAIT_FOR_INDEXING, base_dir)
            state = RunState.WAIT_FOR_INDEXING
        if state == RunState.WAIT_FOR_INDEXING:
            worker.wait_for_indexing(manifest, base_dir)
            manifest.transition(RunState.SOURCE_AUDIT, base_dir)
            state = RunState.SOURCE_AUDIT
        if state == RunState.SOURCE_AUDIT:
            audit = prompt_texts.get("source_audit", "")
            if audit:
                text = worker.run_prompt(audit)
                (Path(base_dir) / "responses").mkdir(parents=True, exist_ok=True)
                (Path(base_dir) / "responses" / "source_audit.md").write_text(
                    text, encoding="utf-8")
            manifest.transition(RunState.RUN_RESEARCH_PROMPTS, base_dir)
            state = RunState.RUN_RESEARCH_PROMPTS
        if state == RunState.RUN_RESEARCH_PROMPTS:
            resp_dir = Path(base_dir) / "responses"
            resp_dir.mkdir(parents=True, exist_ok=True)
            for job in manifest.pending_prompts():
                text = prompt_texts.get(job.prompt_id, "")
                if not text:
                    continue
                try:
                    answer = worker.run_prompt(text)
                    citations = worker.capture_citations()
                    rp = resp_dir / f"{job.prompt_id}.md"
                    cp = resp_dir / f"{job.prompt_id}.citations.json"
                    rp.write_text(answer, encoding="utf-8")
                    cp.write_text(json.dumps(citations, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
                    job.status = "complete"
                    job.response_path = str(rp)
                    job.citation_path = str(cp)
                except Exception as exc:
                    job.status = "failed"
                    job.attempts += 1
                    job.last_error = str(exc)[:200]
                    worker.save_failure_artifacts(reason=f"prompt {job.prompt_id}")
                manifest.save(base_dir)
            # Only advance when the recorded state is actually behind — a
            # VALIDATE-state manifest re-entering this stage for prompt
            # retries must not attempt an illegal VALIDATE→CAPTURE move.
            if manifest.state == RunState.RUN_RESEARCH_PROMPTS:
                manifest.transition(RunState.CAPTURE_RESPONSES, base_dir)
                manifest.transition(RunState.VALIDATE, base_dir)
        return manifest
    except AuthRequired:
        # Not a failure of the run — a failure of the session. Record and let
        # the caller fall back to the Native Learner.
        if RunState.AUTH_REQUIRED in {RunState.AUTH_REQUIRED}:
            try:
                manifest.state = RunState.AUTH_REQUIRED
                manifest.history.append(
                    f"{datetime.now(timezone.utc).isoformat()} -> AUTH_REQUIRED")
                manifest.save(base_dir)
            except Exception:
                pass
        raise
    except Exception as exc:
        worker.save_failure_artifacts(reason=str(exc)[:120])
        manifest.state = RunState.FAILED
        manifest.history.append(
            f"{datetime.now(timezone.utc).isoformat()} -> FAILED: {str(exc)[:120]}")
        manifest.save(base_dir)
        raise
