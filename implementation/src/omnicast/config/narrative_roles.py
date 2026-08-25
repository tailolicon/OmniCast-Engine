"""The standard model-role configuration for the narrative pipeline.

This table has now been lost twice, the same way both times: it lived in one
launcher, somebody entered the pipeline through a different door, and the run
silently used a different model tier than the one the A/B chose.

  * 2026-07-19, batch 1456 — the overrides lived only in the launching shell's
    environment. A relaunch without them reverted an entire batch to Opus
    roles; nobody noticed until the audit log was read. Fix: `run_seq_batch.py`
    pinned them itself.
  * 2026-08-03 — a single run launched through `run_phase2_unit_first.py`,
    which never got that fix, ran planner and writer on Opus at max effort and
    exhausted the session quota 37 minutes in, scoring 0/100.

So the table lives in the package, and every launcher applies it. A launcher
that forgets is the bug this module exists to make impossible.
"""

from __future__ import annotations

# A/B-proven 2026-07-19: Sonnet planner + writer, -36% cost and the best
# campaign score. Opus stays on the challenger, where cross-lineage adversarial
# judgement is the whole point.
STANDARD_ROLE_ENV: dict[str, str] = {
    "OMNICAST_NARRATIVE_PLANNER_MODEL": "claude-sonnet-5",
    "OMNICAST_NARRATIVE_PLANNER_EFFORT": "high",
    "OMNICAST_NARRATIVE_WRITER_MODEL": "claude-sonnet-5",
    "OMNICAST_NARRATIVE_WRITER_EFFORT": "high",
    # 2026-07-25 Phase 2 (operator-funded): judging is DeepSeek-first again.
    # `OMNICAST_NARRATIVE_CLAUDE_ONLY=1` forces every judge back onto the
    # Anthropic quota and roughly doubles the burn per run — it is a debugging
    # switch, not a mode to launch in. Do NOT pin CHALLENGER_PROVIDER=deepseek
    # here either: a DeepSeek challenger over DeepSeek judges is
    # not_independent by identity and can never approve a release.
    "OMNICAST_NARRATIVE_CLAUDE_ONLY": "0",
}


def apply_standard_roles(environ) -> None:
    """Pin the standard role config; an explicit operator export still wins."""
    for key, value in STANDARD_ROLE_ENV.items():
        environ.setdefault(key, value)


__all__ = ["STANDARD_ROLE_ENV", "apply_standard_roles"]
