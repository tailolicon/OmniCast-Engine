"""Repair budget — bounded, content-keyed retry ledger for expensive steps.

Pattern ported from Orkas-VideoStudio's draft-repair-state (MIT): a step that
keeps failing on the SAME inputs must not be re-run forever — every scheduler
tick would re-spend Flow quota / Veo credits / LLM tokens on a render that is
going to fail again. The ledger persists failures keyed by a *content
signature* (sha256 of the inputs that determine the output):

  - inputs unchanged  -> each failure burns one attempt; after ``max_failures``
    the step is BLOCKED until the inputs change or the state file is deleted.
  - inputs changed    -> the budget resets automatically (new content = new
    chances), so a fixed script re-renders immediately.
  - success           -> the ledger is cleared (history kept for audit).

Pure JSON-file state, no vault dependency: the state lives next to the product
it guards (e.g. ``<product_dir>/_repair_state.json``) so deleting the product
folder also deletes its ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAX_FAILURES_DEFAULT = 3   # block on the 3rd consecutive same-content failure
_HISTORY_KEEP = 12


def content_signature(*parts: str | bytes) -> str:
    """Deterministic sha256 over the inputs that define the step's output."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="replace") if isinstance(p, str) else p)
        h.update(b"\x00")
    return h.hexdigest()


@dataclass
class RepairBudget:
    """Load/inspect/update one step's repair ledger. See module docstring."""

    state_path: Path
    max_failures: int = MAX_FAILURES_DEFAULT
    state: dict = field(default_factory=dict)

    @classmethod
    def load(cls, state_path: Path | str,
             max_failures: int = MAX_FAILURES_DEFAULT) -> "RepairBudget":
        p = Path(state_path)
        state: dict = {}
        if p.exists():
            try:
                state = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    state = {}
            except Exception:
                state = {}  # corrupt state never blocks — start fresh
        return cls(state_path=p, max_failures=max_failures, state=state)

    # ── queries ──────────────────────────────────────────────────────────────
    @property
    def failed_attempts(self) -> int:
        try:
            return max(0, int(self.state.get("failed_attempts", 0)))
        except (TypeError, ValueError):
            return 0

    def _last_signature(self) -> str:
        last = self.state.get("last_error")
        return (last or {}).get("content_signature", "") if isinstance(last, dict) else ""

    def blocked(self, signature: str) -> bool:
        """True when this content already failed ``max_failures`` times.

        A different signature is never blocked (content changed -> fresh budget).
        """
        return (self.state.get("status") == "failed"
                and self.failed_attempts >= self.max_failures
                and self._last_signature() == signature)

    def remaining(self, signature: str) -> int:
        if self._last_signature() != signature:
            return self.max_failures
        return max(0, self.max_failures - self.failed_attempts)

    # ── updates ──────────────────────────────────────────────────────────────
    def record_failure(self, signature: str, code: str, message: str) -> None:
        """Count one failure for this content; reset the count if content changed."""
        prior = self.failed_attempts if self._last_signature() == signature else 0
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "code": code,
            "message": (message or "")[:300],
            "content_signature": signature,
        }
        history = self.state.get("history")
        history = history if isinstance(history, list) else []
        self.state = {
            "status": "failed",
            "failed_attempts": prior + 1,
            "max_failures": self.max_failures,
            "last_error": entry,
            "history": (history + [entry])[-_HISTORY_KEEP:],
        }
        self._write()

    def record_success(self, signature: str, detail: str = "") -> None:
        history = self.state.get("history")
        self.state = {
            "status": "ok",
            "failed_attempts": 0,
            "max_failures": self.max_failures,
            "last_error": None,
            "history": history if isinstance(history, list) else [],
            "last_success": {
                "ts": datetime.now(timezone.utc).isoformat(),
                "content_signature": signature,
                "detail": (detail or "")[:300],
            },
        }
        self._write()

    def _write(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass  # ledger write failure must never break the step itself
