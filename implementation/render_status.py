"""Thread-safe render-status writer for the HTML monitoring dashboard.

The renderer emits a single JSON file describing live progress: pipeline stages,
per-shot state + thumbnail paths, credits, timings, log tail, and the final
video path. dashboard.html polls this file to show the whole process.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

STAGES = ["script", "storyboard", "images", "compose", "concat", "done"]


class StatusWriter:
    """Writes status.json atomically; safe to call from parallel worker threads."""

    def __init__(self, status_path: Path, *, channel: str = "", title: str = "") -> None:
        self.path = Path(status_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._t0 = time.time()
        self._state = {
            "run_id": time.strftime("%Y%m%d-%H%M%S"),
            "channel": channel,
            "title": title,
            "started": self._t0,
            "elapsed": 0.0,
            "stage": "script",
            "stages": {s: "pending" for s in STAGES},
            "shots": [],          # [{idx, heading, illu, state}]
            "credits": None,      # {balance, cost_per_clip, needed}
            "video": None,        # final mp4 (relative)
            "log": [],
        }

    def _flush(self) -> None:
        self._state["elapsed"] = round(time.time() - self._t0, 1)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def stage(self, name: str, state: str = "active") -> None:
        with self._lock:
            self._state["stage"] = name
            self._state["stages"][name] = state
            if state == "active":  # mark earlier stages done
                for s in STAGES:
                    if s == name:
                        break
                    if self._state["stages"][s] != "error":
                        self._state["stages"][s] = "done"
            self._flush()

    def init_shots(self, shots: list[tuple[int, str]]) -> None:
        with self._lock:
            self._state["shots"] = [
                {"idx": i, "heading": h, "illu": None, "state": "pending"}
                for i, h in shots
            ]
            self._flush()

    def shot(self, idx: int, *, state: str | None = None, illu: str | None = None) -> None:
        with self._lock:
            for s in self._state["shots"]:
                if s["idx"] == idx:
                    if state is not None:
                        s["state"] = state
                    if illu is not None:
                        s["illu"] = illu
                    break
            self._flush()

    def credits(self, info: dict) -> None:
        with self._lock:
            self._state["credits"] = info
            self._flush()

    def video(self, rel_path: str) -> None:
        with self._lock:
            self._state["video"] = rel_path
            self._state["stages"]["done"] = "done"
            self._state["stage"] = "done"
            self._flush()

    def set_title(self, title: str) -> None:
        with self._lock:
            self._state["title"] = title
            self._flush()

    def qa(self, report: dict) -> None:
        with self._lock:
            self._state["qa"] = report
            self._flush()

    def log(self, line: str) -> None:
        with self._lock:
            self._state["log"].append(f"[{round(time.time() - self._t0,1)}s] {line}")
            self._state["log"] = self._state["log"][-200:]
            self._flush()

    def error(self, msg: str) -> None:
        with self._lock:
            self._state["stages"][self._state["stage"]] = "error"
            self._state["log"].append(f"[ERROR] {msg}")
            self._flush()
