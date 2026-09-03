"""One worker, one job at a time, with retries and cleanup.

`POST /run` used to spawn a thread per call, so pasting five links started five
dubs at once: five ffmpeg encodes, five ASR models and five TTS streams fighting
over the same CPU, GPU and Douyin rate limit. Everything finished later than if
they had simply queued.

So: a single worker thread drains a queue. State lives in vault.db (`status`),
not in memory, so a queue survives a backend restart — the worker picks the
`queued` rows back up on the next start.

Retries use the resume path rather than starting over. Every stage is keyed by
a content hash, so a second attempt walks past the download, the ASR and the
translation already on disk and retries only what actually broke. A failure
that left a half-written workspace behind is cleaned up first, because the
runner refuses to build on partial project data.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from omnicast.reup import vault_link

# Two retries: enough to ride out a rate limit, a dead CDN node or a flaky
# provider, and few enough that a genuinely broken job stops wasting the queue.
DEFAULT_MAX_ATTEMPTS = 3
RETRY_BACKOFF_S = (15.0, 60.0)


@dataclass
class QueuedJob:
    job_id: str
    url: str
    options: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0


class ReupQueue:
    """Serial job runner. `start()` is idempotent."""

    def __init__(self, run_job: Callable[[QueuedJob], None], *, max_attempts: int = DEFAULT_MAX_ATTEMPTS):
        self._run_job = run_job
        self._max_attempts = max_attempts
        self._pending: list[QueuedJob] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._current: QueuedJob | None = None
        self._stopping = False

    # ── public surface ───────────────────────────────────────────────────────

    def submit(self, job: QueuedJob) -> None:
        with self._lock:
            self._pending.append(job)
        vault_link.update_job(job.job_id, status="queued")
        self._wake.set()
        self.start()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self._current.job_id if self._current else None,
                "attempt": self._current.attempts if self._current else 0,
                "pending": [{"job_id": j.job_id, "url": j.url} for j in self._pending],
            }

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stopping = False
        self._worker = threading.Thread(target=self._drain, name="reup-queue", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    # ── worker ───────────────────────────────────────────────────────────────

    def _next(self) -> QueuedJob | None:
        with self._lock:
            return self._pending.pop(0) if self._pending else None

    def _drain(self) -> None:
        while not self._stopping:
            job = self._next()
            if job is None:
                self._wake.wait(timeout=5.0)
                self._wake.clear()
                continue
            with self._lock:
                self._current = job
            try:
                self._run_with_retries(job)
            finally:
                with self._lock:
                    self._current = None

    def _run_with_retries(self, job: QueuedJob) -> None:
        while job.attempts < self._max_attempts and not self._stopping:
            job.attempts += 1
            try:
                self._run_job(job)
                return
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                clean_partial_workspace(job.job_id)
                if job.attempts >= self._max_attempts:
                    vault_link.update_job(
                        job.job_id, status="failed",
                        error=f"{last} (bỏ cuộc sau {job.attempts} lần thử)",
                    )
                    return
                vault_link.update_job(
                    job.job_id, status="queued",
                    error=f"{last} (thử lại lần {job.attempts + 1}/{self._max_attempts})",
                )
                delay = RETRY_BACKOFF_S[min(job.attempts - 1, len(RETRY_BACKOFF_S) - 1)]
                time.sleep(delay)


def clean_partial_workspace(job_id: str) -> Path | None:
    """Delete a workspace that failed before it became resumable.

    A folder with `project.json` + `project.db` is worth keeping: the caches in
    it make the retry cheap. Anything less is rubble the runner will refuse to
    build on, and leaving it there turns a transient failure into a permanent
    one for that video.
    """
    import shutil

    row = vault_link.get_job(job_id) or {}
    root_raw = str(row.get("project_root") or "")
    if not root_raw:
        return None
    root = Path(root_raw)
    if not root.is_dir():
        return None
    if (root / "project.json").is_file() and (root / "project.db").is_file():
        return None
    shutil.rmtree(root, ignore_errors=True)
    return root
