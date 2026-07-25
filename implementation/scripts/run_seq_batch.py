"""Detached sequential batch runner for unit_first generation.

One Claude subscription cannot serve two pipelines at once (observed live:
parallel runs throttle each other until the health gate aborts), and session-
bound background shells are killed at ~10 minutes — twice this lost the tail
of a sequential batch. This runner is meant to be launched DETACHED
(Start-Process / nohup) so it survives the agent session:

    .venv/Scripts/python.exe scripts/run_seq_batch.py \
        "3 True Encounters ..." "3 True Encounters ..." [...]

Results land in output/_seq_batch/<stamp>/: one log per topic plus a
summary.txt with the terminal line of each run. Kill any prior batch's
python processes before starting a new one — two batches ARE a parallel run.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
RUNNER = ROOT / "scripts" / "run_phase2_unit_first.py"

# The A/B-proven standard role config (2026-07-19): Sonnet planner + writer
# (-36% cost, best campaign score). These overrides once lived only in the
# launching shell's environment — one relaunch without them silently reverted
# an entire batch to Opus roles (batch 20260719_1456) and nobody noticed until
# the audit log was read. The runner owns operational policy, so it pins the
# standard itself.
_STANDARD_ROLE_ENV = {
    "OMNICAST_NARRATIVE_PLANNER_MODEL": "claude-sonnet-5",
    "OMNICAST_NARRATIVE_PLANNER_EFFORT": "high",
    "OMNICAST_NARRATIVE_WRITER_MODEL": "claude-sonnet-5",
    "OMNICAST_NARRATIVE_WRITER_EFFORT": "high",
    # 2026-07-25, operator-funded and operator-approved: the release
    # challenger runs on DeepSeek — a genuinely different PROVIDER lineage
    # than the Sonnet judges and Opus escalation (both external reviews named
    # the all-Anthropic judging stack a shared-blind-spot risk). Balance was
    # probed live before this was pinned; with a dead balance the challenger
    # is unreachable and releases fail closed, which is the correct failure.
    "OMNICAST_NARRATIVE_CHALLENGER_PROVIDER": "deepseek",
}


def apply_standard_roles(environ) -> None:
    """Pin the standard role config; an explicit operator export still wins."""
    for key, value in _STANDARD_ROLE_ENV.items():
        environ.setdefault(key, value)


def should_retry(returncode: int, terminal: str, wait: float | None, attempt: int) -> bool:
    """A run killed BY the quota window deserves a retry; a completed content
    verdict does not, even when a limit marker appears elsewhere in its log
    (2026-07-19: a finished 83/100 release-gate rejection was re-run because a
    stray session-limit line in its log matched — the retry burned a fresh
    quota window on a question the run had already answered)."""
    if returncode == 0 or wait is None or attempt >= 3:
        return False
    if not terminal or terminal.startswith("(log unreadable"):
        return True
    if "session limit" in terminal.lower():
        return True
    # A zero-score "verdict" with a limit marker in the log is a quota-poisoned
    # run — the judges died mid-run and fail-closed zeroed the build (live
    # 2026-07-20 0848: compliance calls hit the session limit, the run still
    # printed a release-gate 0/100 line, and the topic lost its retry).
    return "(0/100)" in terminal

# "You've hit your session limit · resets 5:40am (Asia/Saigon)" — the dot can
# arrive mojibake'd through Windows console encodings, so anchor on "resets".
_LIMIT_RE = re.compile(r"session limit.{0,40}?resets\s+(\d{1,2}):(\d{2})\s*(am|pm)", re.I | re.S)


def seconds_until_reset(log_text: str, now: datetime.datetime) -> float | None:
    """Seconds to sleep (with a 5-minute cushion) if the log shows a quota hit.

    Quota windows are the throughput bottleneck (~2-3 runs per ~5h window); a
    batch that dies on the window boundary wastes every window nobody is awake
    for. Returns None when no session-limit marker is present."""
    match = _LIMIT_RE.search(log_text)
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds() + 300.0


def main(topics: list[str]) -> int:
    apply_standard_roles(os.environ)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = ROOT / "output" / "_seq_batch" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = out_dir / "summary.txt"

    def note(line: str) -> None:
        with summary.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    note(f"batch start {datetime.datetime.now():%H:%M:%S} | {len(topics)} topics")
    for index, topic in enumerate(topics, 1):
        slug = "".join(c if c.isalnum() else "_" for c in topic.lower())[:40]
        # A topic gets one quota-driven retry per window boundary, max 3 tries:
        # a run killed BY the window is not a verdict on the topic.
        for attempt in range(1, 4):
            log = out_dir / f"{index:02d}_{slug}{'' if attempt == 1 else f'_r{attempt}'}.log"
            note(f"[{index}] START {datetime.datetime.now():%H:%M:%S} try {attempt} {topic}")
            with log.open("w", encoding="utf-8") as fh:
                proc = subprocess.run(
                    [str(PYTHON), str(RUNNER), "--topic", topic],
                    stdout=fh, stderr=subprocess.STDOUT, cwd=str(ROOT),
                )
            terminal = ""
            text = ""
            try:
                text = log.read_text(encoding="utf-8", errors="replace")
                for line in text.splitlines():
                    if ("REJECTED" in line or "ACCEPTED" in line
                            or "production_ready" in line):
                        terminal = line.strip()
            except Exception as exc:  # noqa: BLE001 - a summary must never crash the batch
                terminal = f"(log unreadable: {exc})"
            note(f"[{index}] DONE rc={proc.returncode} try {attempt} {terminal[:160]}")
            wait = seconds_until_reset(text, datetime.datetime.now())
            if not should_retry(proc.returncode, terminal, wait, attempt):
                break
            note(f"[{index}] quota window hit; sleeping {wait/60:.0f} min until reset")
            time.sleep(wait)
    note(f"batch end {datetime.datetime.now():%H:%M:%S}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
