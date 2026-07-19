"""Real-CLI smoke check: does `claude -p` still answer in ONE turn with no tools?

NOT part of the unit suite — it spends two real subscription calls. Run it by hand
after touching ClaudeCLIClient's command construction, or when a live run starts
returning max_turns_reached.

    python scripts/claude_cli_smoke.py
    python scripts/claude_cli_smoke.py --model claude-opus-4-8 --effort max

Why it exists: on 2026-07-17 15:36 a live claude_only run stalled because
--strict-mcp-config disables MCP servers only and leaves Claude Code's BUILT-IN
tools and skills available. Sonnet chose a tool, spent its single allowed turn on
it, and every call came back subtype=error_max_turns / num_turns=2. Nothing in
the unit suite can catch that: it is a property of the INSTALLED CLI, not of our
code. This asks the real thing.

Two checks, because one is not enough:

  1. a deliberately tool-tempting prompt must NOT burn the turn — this is the
     regression. (The model may still answer poorly; that is fine and expected,
     since it was asked to do something it now cannot. What matters is that the
     call completes instead of dying on max_turns.)
  2. a plain prompt must return usable JSON in one turn — this is the actual use.

Prompts are fixed trivial strings defined here. Output prints only verdicts and
token counts: no credentials, no generated prose, no prompt echo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omnicast.llm.claude_cli import (  # noqa: E402
    CLI_EFFORT_LEVELS,
    ClaudeCLIClient,
    ClaudeCLIError,
)

_TOOL_BAIT = (
    "List the files in the current directory using your tools, then reply with "
    'only this JSON: {"ok":true}'
)
_PLAIN = 'Reply with only this JSON and nothing else: {"ok":true}'


async def _ask(client: ClaudeCLIClient, prompt: str) -> tuple[bool, str, int]:
    try:
        response = await client.complete(
            system="", messages=[{"role": "user", "content": prompt}]
        )
    except ClaudeCLIError as exc:
        return False, str(exc), 0
    return True, response.content or "", response.output_tokens


def _extract_json(body: str) -> dict | None:
    match = re.search(r"\{[^{}]*\}", body)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--effort", default="medium", choices=CLI_EFFORT_LEVELS)
    args = parser.parse_args()

    client = ClaudeCLIClient(model=args.model, effort=args.effort, role="smoke")
    argv = client._build_command("claude")
    tools_off = "--tools" in argv and argv[argv.index("--tools") + 1] == ""
    skills_off = "--disable-slash-commands" in argv
    print(f"model={args.model} effort={args.effort}")
    print(f"  --tools \"\"                : {tools_off}")
    print(f"  --disable-slash-commands  : {skills_off}")
    print(f"  --max-turns               : {argv[argv.index('--max-turns') + 1]}")
    if not (tools_off and skills_off):
        print("\nFAIL: the tool-disabling flags are missing from argv")
        return 1

    failures = []

    print("\n[1/2] tool-tempting prompt (must not burn the turn)")
    ok, body, tokens = await _ask(client, _TOOL_BAIT)
    if not ok:
        print(f"  FAIL: {body}")
        if "max_turns" in body:
            print("  -> built-in tools are reachable; --tools \"\" is not taking effect")
        failures.append("tool_bait")
    else:
        print(f"  ok: completed in one turn, no max_turns_reached ({tokens} tokens)")

    print("\n[2/2] plain JSON prompt (the actual use)")
    ok, body, tokens = await _ask(client, _PLAIN)
    if not ok:
        print(f"  FAIL: {body}")
        failures.append("plain")
    else:
        payload = _extract_json(body)
        if payload == {"ok": True}:
            print(f"  ok: returned the requested JSON ({tokens} tokens)")
        else:
            print(f"  FAIL: no usable JSON in the reply ({tokens} tokens)")
            failures.append("plain_json")

    print("\nPASS" if not failures else f"\nFAIL: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
