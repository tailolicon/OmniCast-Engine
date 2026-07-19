"""Deterministic idempotency keys for pipeline-step checkpointing (M0).

GOTCHA (see SPEC_M0_NenMong.md §6.4): the idempotency key MUST be computed from
*deterministic* inputs only. Runtime-varying fields — timestamps, uuids, run/
execution/job ids, anything ending in `_at`, temp absolute paths — would change
the hash every run and silently disable checkpointing. `canonical_inputs()`
strips them before hashing; callers may pass extra keys via `ignore`.

This module is pure (stdlib only) and has no side effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

# Field names that are inherently non-deterministic across runs/retries.
_NONDETERMINISTIC_KEYS: frozenset[str] = frozenset({
    "timestamp", "ts", "time", "now", "datetime", "date",
    "uuid", "guid", "nonce", "random", "seed_random",
    "run_id", "execution_id", "job_id", "trace_id", "request_id", "correlation_id",
    "attempt", "retry", "retries",
})

# A value that *looks* like a temp/abs path is treated as non-deterministic only
# when its KEY suggests a scratch path (e.g. tmp_path, work_dir, output_path).
_PATHY_KEY_RE = re.compile(r"(^|_)(tmp|temp|work|scratch|output|out|cache)_?(dir|path|file)?$", re.I)
_ENDS_AT_RE = re.compile(r"_at$", re.I)


def _is_ignored_key(key: str, ignore: frozenset[str]) -> bool:
    k = key.lower()
    if k in ignore:
        return True
    if _ENDS_AT_RE.search(k):          # created_at, started_at, finished_at, ...
        return True
    if _PATHY_KEY_RE.search(k):        # tmp_path, work_dir, output_path, ...
        return True
    return False


def _clean(obj: Any, ignore: frozenset[str]) -> Any:
    if isinstance(obj, dict):
        return {
            k: _clean(v, ignore)
            for k, v in obj.items()
            if not _is_ignored_key(str(k), ignore)
        }
    if isinstance(obj, (list, tuple)):
        return [_clean(v, ignore) for v in obj]
    return obj


def canonical_inputs(inputs: dict[str, Any], *, ignore: Iterable[str] | None = None) -> str:
    """Return a stable canonical JSON string of `inputs` with non-deterministic
    fields removed and keys sorted. Same logical inputs → same string."""
    ig = _NONDETERMINISTIC_KEYS | frozenset(k.lower() for k in (ignore or ()))
    cleaned = _clean(inputs or {}, ig)
    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def idempotency_key(step_id: str, inputs: dict[str, Any], *, ignore: Iterable[str] | None = None) -> str:
    """sha256 over (step_id + canonical deterministic inputs)."""
    basis = f"{step_id}|{canonical_inputs(inputs, ignore=ignore)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
