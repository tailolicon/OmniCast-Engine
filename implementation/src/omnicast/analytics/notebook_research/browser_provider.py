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
# Sources asked about per verification question. One question per source is a
# ~100s round-trip, so a 280-source corpus would take about eight hours to
# check — which is not a check, it is a second project.
VERIFY_BATCH = 10
# Marker a caller puts where a long question may be cut into consecutive turns.
PROMPT_SPLIT = "<<<SPLIT>>>"


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
                    # UI_INDEXED, not "indexed": all we learned is that the
                    # app's own source counter reached the expected number.
                    # Whether each URL actually yielded a transcript is a
                    # different question, answered by verify_sources().
                    for s in manifest.sources:
                        if s.upload_status == "uploaded":
                            s.upload_status = "ui_indexed"
                    manifest.save(base_dir)
                    return
            else:
                stable = 0
            time.sleep(POLL_S)
        raise UiDeadline(
            f"wait_for_indexing: {expected} sources not ready within deadline "
            f"(last count {self._source_count_on_page()})")

    def run_prompt(self, prompt_text: str) -> str:
        """Send one prompt; return the final response.

        Completion detection (run 8 post-mortem): text stability alone fires
        early — Gemini pauses mid-generation (the "Thoughts" phase), the text
        holds still for a few polls, and the next prompt then finds the chat
        box DISABLED because the real answer is still streaming. The box's
        editability IS the ground-truth generation signal, so the flow is:
        wait box editable (previous turn may still run) → send → confirm
        generation started → wait until box editable again AND text stable."""
        # A PROMPT TOO LONG TO SEND IS SENT IN PIECES. The 26-pair cohort
        # questions (~4.6k chars) landed in the box intact — the truncation
        # check passed — and no send path submitted them, while a ~700-char
        # probe went out fine. Rather than binary-search a live UI for the
        # exact submit cap, the caller marks where the question can be cut and
        # the parts go as consecutive turns; the chat keeps its own context.
        if PROMPT_SPLIT in prompt_text:
            answer = ""
            for part in [p.strip() for p in prompt_text.split(PROMPT_SPLIT)]:
                if part:
                    answer = self.run_prompt(part)
            return answer

        box = self.find("chat_input", timeout_s=30)
        if box is None:
            raise UiDeadline("run_prompt: chat input not found")

        deadline = time.monotonic() + DEADLINE_RESPONSE
        _polls = 0
        while time.monotonic() < deadline:
            try:
                if box.is_editable():
                    break
            except Exception:
                pass
            # A lingering citation panel/dialog disables the chat box (run 9:
            # two prompts click-timed-out right after citation capture) —
            # nudge it closed while waiting.
            _polls += 1
            if _polls % 3 == 0:
                try:
                    self.page.keyboard.press("Escape")
                except Exception:
                    pass
            time.sleep(POLL_S)
        else:
            raise UiDeadline("run_prompt: chat box never became editable "
                             "(previous generation still running?)")
        baseline = self._latest_response_text()
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
        # TRUNCATION IS A DIFFERENT FAILURE FROM A DEAD SEND BUTTON, and they
        # look identical from outside: the text is visibly in the box and
        # nothing submits. The wrong-box guard above only compares the first 60
        # characters, so a box that accepted a prefix and dropped the rest
        # passed it. Report the two lengths and let the caller shorten.
        if len(got or "") + 8 < len(prompt_text):
            raise UiDeadline(
                f"run_prompt: chat box accepted only {len(got or '')} of "
                f"{len(prompt_text)} characters — the prompt is over the "
                f"input limit, not un-sendable")
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
        # SEND IS NOT ONE ACTION, IT IS A LADDER. The 26-pair cohort prompts
        # (~4.9k chars over 86 lines) all failed with "generation never started"
        # while the text sat visibly in the box: the short prompts that worked
        # before had gone out on the first rung, so nothing had ever exercised
        # the fallbacks. Ctrl+Enter is the multi-line submit, and a second pass
        # matters because the first Enter on a freshly filled long textarea can
        # land while the app is still reflowing it.
        def _attempt_send() -> None:
            sent = False
            snd = self.find("send_button", timeout_s=2)
            if snd is not None:
                try:
                    if snd.is_enabled():
                        snd.click(timeout=5000)
                        sent = True
                except Exception:
                    pass
            if not sent:
                try:
                    box.press("Control+Enter")
                except Exception:
                    pass
                try:
                    box.press("Enter")
                except Exception:
                    pass

        def _started(window_s: float) -> bool:
            end = time.monotonic() + window_s
            while time.monotonic() < end:
                try:
                    if not box.is_editable():
                        return True
                except Exception:
                    pass
                if self._latest_response_text() != baseline:
                    return True
                time.sleep(1.0)
            return False

        # Confirm generation actually STARTED (box disables or a new message
        # pair appears) — otherwise "stable" would trivially pass on the old
        # answer and the send failure would go unnoticed.
        _attempt_send()
        started = _started(45)
        if not started:
            try:
                box.click()
                box.press("End")
            except Exception:
                pass
            _attempt_send()
            started = _started(30)
        if not started:
            raise UiDeadline(
                f"run_prompt: generation never started after send "
                f"(prompt {len(prompt_text)} chars, "
                f"{len(prompt_text.splitlines())} lines)")

        last, stable = "", 0
        while time.monotonic() < deadline:
            time.sleep(POLL_S)
            text = self._latest_response_text()
            try:
                editable = box.is_editable()
            except Exception:
                editable = False
            if editable and text and text == last:
                stable += 1
                if stable >= RESPONSE_STABLE_CHECKS:
                    # The captured turn can include the question and the
                    # reasoning trace. Every caller then parses OUR words, or
                    # Gemini's thinking, as the answer — see the two strippers
                    # for what that cost.
                    return self._strip_thoughts(
                        self._strip_prompt_echo(text, prompt_text))
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

    @staticmethod
    def _strip_thoughts(text: str) -> str:
        """Drop Gemini's reasoning trace from the head of an answer.

        The trace sits INSIDE the answer node. Collapsed it is two lines
        ("Thoughts" / "expand_more"); while it is still streaming it is the
        whole chain of thought, complete with the UI's icon words. A run that
        captured mid-stream stored a page of "Analyzing Transcript Passages"
        and no answer at all, and nothing downstream could tell that apart from
        a model that had answered badly.
        """
        lines = (text or "").splitlines()
        widget = {"thoughts", "expand_more", "expand_less", "neurology",
                  "travel_explore", "edit_document", "auto_awesome"}
        i = 0
        if not lines or lines[0].strip().lower() != "thoughts":
            return (text or "").strip()
        i = 1
        last_widget = 0
        while i < len(lines):
            if lines[i].strip().lower() in widget:
                last_widget = i
            i += 1
        # Everything up to the final widget marker is trace; a collapsed
        # trace makes that marker line 1 and costs nothing.
        return "\n".join(lines[last_widget + 1:]).strip()

    @staticmethod
    def _strip_prompt_echo(text: str, prompt: str) -> str:
        """Drop the question from the captured turn, if it came along.

        THE PROMPT'S OWN VOCABULARY WAS BEING READ AS THE ANSWER. The response
        container can hold the whole turn, question included, and the source
        probe asks the model to reply "NO_TRANSCRIPT if that source has none".
        Searching the captured text for NO_TRANSCRIPT therefore matched the
        question every single time: ten live probes were recorded as "no
        verbatim quote" while the screenshot showed a quote sitting right
        there. Any parser that looks for a token it also SENDS has this bug.
        """
        body = (text or "").strip()
        head = " ".join((prompt or "").split())[:80]
        if not head:
            return body
        flat = " ".join(body.split())
        idx = flat.find(head)
        if idx < 0:
            return body
        # Cut on the ORIGINAL text using the tail of the echoed prompt, so the
        # answer keeps its own line breaks (the batch parser needs them).
        tail = " ".join((prompt or "").split())[-60:]
        pos = flat.find(tail, idx)
        if pos < 0:
            return body
        marker = tail.split()[-4:] if len(tail.split()) >= 4 else tail.split()
        needle = " ".join(marker)
        cut = body.find(needle)
        return body[cut + len(needle):].strip() if cut >= 0 else body

    @staticmethod
    def _quote_matches_transcript(video_id: str, quote: str, timestamp: str,
                                  vtt_dir: Path) -> tuple[bool, str]:
        """Is this quote actually IN that video's transcript, near that time?

        Checking the SHAPE of the answer (a QUOTE line, a mm:ss) proves the
        model can follow a format, not that it read anything: a fabricated
        quote with a fabricated timestamp passes a format check perfectly.
        We hold 234 local VTTs — the claim is checkable, so it must be checked.
        """
        hits = list(Path(vtt_dir).glob(f"{video_id}*.vtt")) if vtt_dir else []
        if not hits:
            return False, "no local transcript to check against"
        try:
            from omnicast.analytics.craft_forensics import parse_vtt

            lines = parse_vtt(hits[0])
        except Exception as exc:
            return False, f"transcript unreadable: {str(exc)[:80]}"
        if not lines:
            return False, "local transcript empty"

        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9 ]", " ", s.lower())

        norm_quote = " ".join(_norm(quote).split())
        if len(norm_quote.split()) < 4:
            return False, "quote too short to verify"
        joined = " ".join(" ".join(_norm(ln.text).split()) for ln in lines)
        # Auto-captions punctuate and line-break differently, so require a
        # contiguous 5-word run from the quote rather than the whole string.
        words = norm_quote.split()
        window = 5
        found_at: float | None = None
        for i in range(len(words) - window + 1):
            frag = " ".join(words[i:i + window])
            if frag in joined:
                for ln in lines:
                    if frag in " ".join(_norm(ln.text).split()):
                        found_at = ln.t
                        break
                break
        if found_at is None:
            return False, "quote not present in the local transcript"
        if timestamp:
            parts = [int(p) for p in timestamp.split(":")]
            claimed = (parts[0] * 60 + parts[1] if len(parts) == 2
                       else parts[0] * 3600 + parts[1] * 60 + parts[2])
            if abs(claimed - found_at) > 90:
                return False, (f"timestamp {timestamp} is {abs(claimed - found_at):.0f}s "
                               f"from where the quote actually appears")
        return True, f"quote found at {found_at:.0f}s in the local transcript"

    @staticmethod
    def _parse_batch_probe(answer: str) -> dict[int, tuple[str, str, str]]:
        """Pull (quote, timestamp, status) per slot number out of one reply.

        Tolerant on shape, strict on content: a model asked for `n| QUOTE: … |
        AT: … | STATUS: …` will sometimes number with `1.`, wrap lines in bold,
        or drop a slot entirely. A missing slot must read as MISSING — silently
        skipping it would leave the source at its previous status and let an
        unanswered question look like a passed one.
        """
        out: dict[int, tuple[str, str, str]] = {}
        for raw in (answer or "").splitlines():
            line = raw.strip().lstrip("*-• ").replace("**", "")
            m = re.match(r"^(\d{1,3})\s*[|.)\]:]\s*(.+)$", line)
            if not m:
                continue
            slot, rest = int(m.group(1)), m.group(2)
            if "QUOTE" not in rest.upper() and "STATUS" not in rest.upper():
                continue
            q = re.search(r"QUOTE:\s*(.*?)(?=\s*\|\s*AT:|\s*\|\s*STATUS:|$)",
                          rest, re.I)
            t = re.search(r"AT:\s*(\d{1,2}:\d{2}(?::\d{2})?)", rest, re.I)
            st = re.search(r"STATUS:\s*([A-Z_]+)", rest, re.I)
            quote = (q.group(1).strip().strip('"“”') if q else "")
            status = (st.group(1).upper() if st else "OK")
            if "NO_TRANSCRIPT" in rest.upper():
                status = "NO_TRANSCRIPT"
            out[slot] = (quote, t.group(1) if t else "", status)
        return out

    def verify_sources(self, manifest: RunManifest, base_dir: Path,
                       sample: int = 0, vtt_dir: Path | None = None,
                       titles: dict[str, str] | None = None,
                       batch: int = VERIFY_BATCH) -> dict:
        """Promote ui_indexed → evidence_usable by ASKING about the sources.

        A source count proves the row exists; it does not prove a transcript
        was pulled.

        ASKED IN BATCHES, because one question per source does not finish. A
        probe round-trip is ~100s of UI wait, so 280 sources one at a time is
        an eight-hour job for a step that is supposed to be a check, and the
        operator's first reaction to watching it was the correct one. Ten
        sources per question turns the same corpus into ~28 questions.

        Batching is safe here precisely because the answer is not trusted: each
        quote is cross-checked against THAT video's local caption file, so a
        model that answers slot 7 with source 3's line fails slot 7. Isolation
        was never what made the probe sound; the transcript check is.
        """
        targets = [s for s in manifest.sources
                   if s.upload_status in ("ui_indexed", "indexed")]
        if sample and sample < len(targets):
            step = max(1, len(targets) // sample)
            targets = targets[::step][:sample]
        checked = verified = empty = 0
        batch = max(1, int(batch))

        for start in range(0, len(targets), batch):
            chunk = targets[start:start + batch]
            # ADDRESS THE SOURCE THE WAY THE APP DOES. The first live probes
            # asked for "the source whose URL ends with <id>" and all ten came
            # back without a quote: the source list shows TITLES, and the model
            # has no URL index to match a suffix against.
            lines = []
            for n, s_ in enumerate(chunk, start=1):
                title = (titles or {}).get(s_.video_id) or s_.remote_title
                lines.append(f"{n}. " + (f'"{title}"' if title
                                         else f"(source with URL ending {s_.video_id})"))
            probe = (
                "For EACH numbered source below, copy one verbatim line from "
                "the middle of THAT source's own transcript.\n\n"
                + "\n".join(lines) +
                "\n\nAnswer with exactly one line per number, nothing else:\n"
                "<n>| QUOTE: <8-14 words copied verbatim> | AT: <mm:ss> | "
                "STATUS: OK\n"
                "Use STATUS: NO_TRANSCRIPT for any source you cannot read. Do "
                "NOT paraphrase, do NOT summarise, and never answer one number "
                "using another source's text.")
            try:
                answer = self.run_prompt(probe)
            except Exception as exc:
                for s_ in chunk:
                    s_.verify_note = f"probe failed: {str(exc)[:120]}"
                    checked += 1
                manifest.save(base_dir)
                continue

            # KEEP THE WHOLE REPLY. The per-source note truncates at 200 chars,
            # and the first batch answered slot 1 and nothing else — a fact
            # that took a screenshot to establish because the reply itself was
            # never written down anywhere.
            try:
                dump = Path(base_dir) / "verify_replies"
                dump.mkdir(parents=True, exist_ok=True)
                (dump / f"batch_{start // batch:03d}.txt").write_text(
                    (probe + "\n\n=== REPLY ===\n" + (answer or "")),
                    encoding="utf-8")
            except OSError:
                pass
            parsed = self._parse_batch_probe(answer or "")
            # UNDER-ANSWERING IS THE MODEL'S PROBLEM, NOT THE SOURCES'. The
            # first live batch replied about slot 1 and stopped; marking the
            # other nine "failed" would have written our unanswered question
            # into the record as nine dead videos. Ask once more, naming what
            # is missing, before believing anything.
            missing = [n for n in range(1, len(chunk) + 1)
                       if not parsed.get(n, ("", "", ""))[0]
                       and parsed.get(n, ("", "", ""))[2] != "NO_TRANSCRIPT"]
            if missing and len(missing) < len(chunk) + 1:
                nudge = ("You answered only some of them. Give me the SAME "
                         "format for exactly these numbers, one line each, "
                         "nothing else: " + ", ".join(str(n) for n in missing))
                try:
                    more = self._parse_batch_probe(self.run_prompt(nudge))
                    for n, val in more.items():
                        if n in missing:
                            parsed[n] = val
                except Exception as exc:
                    logger.warning("batch re-ask failed", error=str(exc)[:120])

            for n, s_ in enumerate(chunk, start=1):
                checked += 1
                quote, ts, status = parsed.get(n, ("", "", "MISSING"))
                # EVIDENCE, NOT ANSWER LENGTH (operator audit): the old check
                # said "8+ words in the reply" — which a summary, a
                # refusal-with-context or a hallucination all satisfy.
                if status == "NO_TRANSCRIPT" or not quote:
                    s_.upload_status = "failed"
                    # KEEP WHAT IT ACTUALLY SAID, so a refusal, a rate-limit
                    # banner and a drifted reply format stay distinguishable.
                    s_.verify_note = (
                        f"no verbatim quote for slot {n} ({status}) | reply: "
                        + " ".join((answer or "").split())[:200])
                    empty += 1
                elif not ts:
                    s_.upload_status = "ui_indexed"
                    s_.verify_note = f"quote without timestamp: {quote[:60]}"
                    empty += 1
                else:
                    ok, why = self._quote_matches_transcript(
                        s_.video_id, quote, ts, vtt_dir or Path())
                    s_.verified_words = len(quote.split())
                    s_.verify_quote = quote[:200]
                    s_.verify_timestamp = ts
                    s_.verify_note = why
                    if ok:
                        s_.upload_status = "evidence_usable"
                        verified += 1
                    else:
                        # Well-formed but uncorroborated: the model may have
                        # invented both the quote and the time, or answered
                        # this slot from a different source. Not evidence.
                        s_.upload_status = "ui_indexed"
                        empty += 1
            manifest.save(base_dir)

        summary = {"checked": checked, "verified": verified, "empty": empty,
                   "batch": batch,
                   "questions_asked": (len(targets) + batch - 1) // batch,
                   "sampled": bool(sample and sample < len(manifest.sources)),
                   "population": len(manifest.sources)}
        (Path(base_dir) / "source_verification.json").write_text(
            json.dumps(summary, indent=1), encoding="utf-8")
        return summary

    def capture_citations(self, max_chips: int = 40) -> list[dict]:
        """Citations OF THE LAST ANSWER — click each chip, record the panel
        text, close. Failures are recorded per-chip, never fatal.

        SCOPED TO THE LATEST RESPONSE (operator audit 27/07): harvesting chips
        page-wide collected every citation in the whole chat history, so three
        different questions came back with 36/40 identical citation positions
        and a first citation pointing at a video that was never asked about.
        A citation set that does not belong to its answer is worse than none —
        it looks like evidence."""
        out: list[dict] = []
        scope = self.page
        for _, css in SELECTORS["response_container"]:
            try:
                blocks = self.page.locator(css)
                if blocks.count():
                    scope = blocks.last          # the answer just generated
                    break
            except Exception:
                continue
        for _, css in SELECTORS["citation_chip"]:
            try:
                chips = scope.locator(css)
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
        # Leave the UI clean: a citation panel left open disables the chat box
        # and starves every later prompt (run 9).
        for _ in range(3):
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                break
            time.sleep(0.5)
        return out


# ── stage driver (used by scripts/competitor_research.py) ────────────────────


def run_notebook_stage(manifest: RunManifest, base_dir: Path,
                       worker: NotebookLMWorker,
                       prompt_texts: dict[str, str],
                       url_batch_limit: int = 40,
                       verify_sample: int = 0,
                       vtt_dir: Path | None = None,
                       titles: dict[str, str] | None = None) -> RunManifest:
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
            # Cohort-scale runs add hundreds of URL sources; the batch limit is
            # a resume checkpoint, not a cap on the corpus.
            worker.add_url_sources(manifest, base_dir,
                                   batch_limit=url_batch_limit)
            manifest.transition(RunState.WAIT_FOR_INDEXING, base_dir)
            state = RunState.WAIT_FOR_INDEXING
        if state == RunState.WAIT_FOR_INDEXING:
            worker.wait_for_indexing(manifest, base_dir)
            manifest.transition(RunState.SOURCE_AUDIT, base_dir)
            state = RunState.SOURCE_AUDIT
        # ARTIFACTS ARE PER NOTEBOOK (operator audit 27/07). Every run wrote to
        # a shared `responses/`, so a 19-source pilot and a 280-source corpus
        # left their answers side by side under identical names — an audit
        # reading `source_audit.md` next to the 280 run was reading the pilot.
        resp_dir = Path(base_dir) / manifest.notebook_key / "responses"
        resp_dir.mkdir(parents=True, exist_ok=True)
        # PROVE the sources carry transcripts before any finding rests on them.
        # Runs on EVERY invocation when asked, not only when the state machine
        # happens to pass through SOURCE_AUDIT: a corpus that finished ingestion
        # sits in VALIDATE forever, and verification would never fire again.
        # Sampled at cohort scale, and the summary always says what was checked.
        if verify_sample:
            summary = worker.verify_sources(manifest, base_dir,
                                            sample=verify_sample,
                                            vtt_dir=vtt_dir, titles=titles)
            (resp_dir / "source_verification.json").write_text(
                json.dumps(summary, indent=1), encoding="utf-8")
            logger.info("notebook source verification", **summary)
        if state == RunState.SOURCE_AUDIT:
            audit = prompt_texts.get("source_audit", "")
            if audit:
                text = worker.run_prompt(audit)
                (resp_dir / "source_audit.md").write_text(text, encoding="utf-8")
            manifest.transition(RunState.RUN_RESEARCH_PROMPTS, base_dir)
            state = RunState.RUN_RESEARCH_PROMPTS
        if state == RunState.RUN_RESEARCH_PROMPTS:
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
