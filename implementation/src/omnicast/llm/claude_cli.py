"""Claude Code CLI backend — bills the operator's SUBSCRIPTION, not API credits.

Runs `claude -p` headless (official Agent-SDK pattern) for pure-text writer
calls. Marginal cost per script ≈ $0 (plan usage limits apply instead of
per-token billing). Enable with OMNICAST_CLAUDE_BACKEND=cli.

Requirements: `claude /login` completed once on this machine with the
subscription account (an unauthenticated CLI returns API 401).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys

import structlog

logger = structlog.get_logger()


def extract_json(content: str) -> str:
    """Pull the JSON document out of a model reply that may not be only JSON.

    The old parser handled exactly two shapes: a bare document, or one inside a
    ```json fence. Anything else — a one-line preamble, a closing remark — went
    straight to `orjson.loads` and raised, and the caller labelled the result
    "schema or provider error", which reads as though the model returned the
    wrong FIELDS rather than the right ones wrapped in a sentence.

    That mislabelling hid a standing cost. The narrative planner has been
    logging planner=4 / planner_schema_retry=4 for weeks: every first attempt
    failing, planner quota spent twice per plan. Three explanations were
    measured and eliminated first — the prompt names all 16 required fields;
    345 real continuity_ledger entries top out at 21 words against a 24-word
    limit; real plans run 2,100-2,350 tokens against a 3,200 cap. What is left
    is the wrapper, and the retry succeeds because its contract text is
    forceful enough to suppress the preamble.

    Falls back to the outermost braces so a preamble, a trailing note, or both
    parse. Raises nothing itself; a reply with no object at all still fails at
    the caller, where it should.
    """
    text = (content or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        return text[start:end + 1]
    return text


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# This process runs INSIDE a Claude Code session — the child `claude` must not
# inherit session/host auth vars or it 401s instead of using the login store.
_STRIP_PREFIXES = ("CLAUDE", "ANTHROPIC")

# ISOLATED CONFIG DIR — the operator's real ~/.claude carries hooks/rules that
# rewrite Claude's writing style (measured: a 'caveman mode' hook stripped the
# articles out of generated horror prose). The child runs with its own
# CLAUDE_CONFIG_DIR holding ONLY a copy of the login credentials: no hooks, no
# CLAUDE.md, no rules — clean model behaviour + far less prompt overhead.
import atexit
import shutil
from pathlib import Path

# Per-PROCESS isolated dir so multiple concurrent script generations (parallel
# `claude -p` calls) never race on the same credentials/session files. Cleaned up
# on interpreter exit. (Single-process runs still get one clean dir.)
_ISO_DIR = Path.home() / f".claude-omnicast-cli-{os.getpid()}"
_ISO_DIR.mkdir(parents=True, exist_ok=True)   # must exist before any temp-file write


@atexit.register
def _cleanup_iso_dir() -> None:
    try:
        _sync_credentials_back()  # a refreshed token must never die with the dir
        shutil.rmtree(_ISO_DIR, ignore_errors=True)
    except Exception:
        pass


def _sync_credentials(force: bool = False) -> None:
    src = Path.home() / ".claude" / ".credentials.json"
    dst = _ISO_DIR / ".credentials.json"
    _ISO_DIR.mkdir(exist_ok=True)
    if not src.exists():
        return
    if force or not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
        dst.write_bytes(src.read_bytes())


def _sync_credentials_back() -> None:
    """Copy a token the CLI refreshed inside the isolated dir back to ~/.claude.

    OAuth refresh ROTATES the refresh token. The CLI writes the new pair to
    CLAUDE_CONFIG_DIR (= the per-PID dir), so without this sync the only valid
    refresh token is deleted at interpreter exit and the stale one left in
    ~/.claude can never refresh again — the whole machine loses auth until a
    manual `claude /login` (observed 2026-07-16: 19:42 expiry, 20:54 run
    refreshed in-dir and exited, 23:20 run dead).
    """
    src = _ISO_DIR / ".credentials.json"
    dst = Path.home() / ".claude" / ".credentials.json"
    try:
        if not src.exists():
            return
        if dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
            return
        tmp = dst.with_name(".credentials.json.omnicast-tmp")
        tmp.write_bytes(src.read_bytes())
        os.replace(tmp, dst)
    except Exception:
        pass


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(_STRIP_PREFIXES)}
    _sync_credentials()
    env["CLAUDE_CONFIG_DIR"] = str(_ISO_DIR)
    return env


# `claude --help`: "Effort level for the current session (low, medium, high,
# xhigh, max)". The CLI answers an unknown value with a warning on stdout and
# silently falls back to its default, so a typo would cost minutes per call and
# report nothing. Validate here instead.
CLI_EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


class ClaudeCLIError(RuntimeError):
    """Base for `claude -p` failures."""


class ClaudeCLITransient(ClaudeCLIError):
    """Worth retrying: a throttle, an auth refresh, an empty stdout blip."""


class ClaudeCLIDeterministic(ClaudeCLIError):
    """Will fail identically next time. Retrying only burns quota and minutes."""


# Result shapes that a retry cannot change. Live 2026-07-17 15:36: every
# plan-repair call returned subtype=error_max_turns and the client retried it
# four times with 20/40/60s sleeps between — ~6 minutes and four subscription
# calls spent re-asking a question that was already settled.
_DETERMINISTIC_SUBTYPES = frozenset({"error_max_turns"})
# Transient is an ALLOWLIST, not a fallback. An unrecognised is_error now fails
# fast and carries its message, so it can be classified deliberately rather than
# absorbed into a retry loop. Empty stdout stays here: a subscription throttle
# was measured returning exactly that, and losing a 15-minute run to one blip is
# worse than one wasted retry.
_TRANSIENT_RESULT_RE = re.compile(
    r"rate[ _-]?limit|usage[ _-]?limit|too many requests|\b429\b|\b50[023]\b|"
    r"overloaded|temporarily unavailable|timed? ?out|try again",
    re.I,
)
# stderr that means "you invoked me wrong" — never worth a retry.
# Bounded: four tries, three waits. The waits only ever follow a failure that
# another try could plausibly fix.
_MAX_ATTEMPTS = 4
_ARG_ERROR_RE = re.compile(
    r"unknown option|unrecognized|invalid (?:model|argument|option|value)|"
    r"^usage:|error: missing|not allowed|permission denied|is not recognized",
    re.I | re.MULTILINE,
)


def _classify_result(subtype: str, text: str) -> str:
    """'deterministic' | 'transient' | 'auth' for an is_error result object."""
    if "401" in text or "unauthor" in text.lower():
        return "auth"
    if subtype in _DETERMINISTIC_SUBTYPES:
        return "deterministic"
    if _TRANSIENT_RESULT_RE.search(text):
        return "transient"
    return "deterministic"


class ClaudeCLIClient:
    """Duck-type of LLMClient's delegate contract (complete/complete_structured).

    ``effort`` and ``role`` are per-client and immutable. Effort belongs to the
    role, not the model: on 2026-07-17 14:32 a Sonnet planner call ran 7 minutes
    and 11,924 output tokens because every stage inherited the CLI's default
    reasoning depth. They are constructor options rather than per-call env vars so
    two channels in one process cannot race each other's settings.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        effort: str | None = None,
        role: str = "",
    ) -> None:
        if effort is not None and effort not in CLI_EFFORT_LEVELS:
            raise ValueError(
                f"unsupported claude CLI effort {effort!r}; this CLI accepts "
                f"{', '.join(CLI_EFFORT_LEVELS)}"
            )
        self._model = model
        self._effort = effort
        self._role = role

    def _build_command(self, exe: str) -> list[str]:
        """The argv for one call, without the system-prompt file (caller adds it).

        This is an LLM-as-text-client, not an agent. It must answer in one turn
        with no tools — so tools are disabled EXPLICITLY.

        Live 2026-07-17 15:36 is why: --strict-mcp-config disables MCP servers
        only, and leaves Claude Code's BUILT-IN tools and skills available.
        Sonnet, handed a plan-repair prompt, chose a tool, spent the single
        allowed turn on it, and every call returned subtype=error_max_turns with
        num_turns=2. Reproduced and fixed here: without these flags the probe
        returns error_max_turns/num_turns=2; with them, success/num_turns=1.

        --max-turns 1 stays. Now that tools are genuinely unavailable, one turn is
        all a text completion needs — raising it would only buy room for the agent
        behaviour this call must not have.
        """
        cmd = [exe, "-p", "--model", self._model,
               "--output-format", "json", "--max-turns", "1",
               # "" = disable every built-in tool (per `claude --help`). Passed as
               # its own argv element, so Windows list2cmdline renders it as the
               # empty quoted string the CLI expects rather than dropping it.
               "--tools", "",
               "--disable-slash-commands",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
        if self._effort:
            cmd += ["--effort", self._effort]
        return cmd

    async def complete(self, *, system: str, messages: list[dict],
                       max_tokens: int | None = None,
                       temperature: float = 0.7):
        from omnicast.llm.client import LLMResponse

        import shutil
        import tempfile
        exe = shutil.which("claude")  # Windows: the launcher is claude.CMD —
        if not exe:                   # bare "claude" fails CreateProcess
            raise RuntimeError("`claude` CLI not on PATH")
        prompt = "\n\n".join(m.get("content", "") for m in messages
                             if m.get("role") == "user") or " "
        cmd = self._build_command(exe)
        sys_file = None
        if system:
            # Writer system prompts run 10k+ chars — as an ARG they blow the
            # Windows command-line limit and claude exits with empty stdout.
            sys_file = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".txt",
                dir=str(_ISO_DIR), delete=False)
            sys_file.write(system)
            sys_file.close()
            cmd += ["--system-prompt-file", sys_file.name]

        def _run() -> dict:
            p = subprocess.run(cmd, input=prompt, capture_output=True,
                               text=True, encoding="utf-8", timeout=1800,
                               cwd=str(_ISO_DIR),  # empty dir → no project CLAUDE.md
                               env=_clean_env(), creationflags=_NO_WINDOW)
            out = p.stdout
            err = p.stderr or ""
            if not out.strip():
                # A bad flag prints usage to stderr and nothing to stdout; a
                # throttle prints nothing to either. Same symptom, opposite
                # treatment, so read stderr before deciding to wait 20 seconds.
                if _ARG_ERROR_RE.search(err):
                    raise ClaudeCLIDeterministic(
                        f"claude -p rejected its arguments (rc={p.returncode}); "
                        f"stderr: {err[:300]!r}")
                raise ClaudeCLITransient(
                    f"claude -p: empty stdout (rc={p.returncode}); "
                    f"stderr: {err[:300]!r}")
            # --output-format json emits a bare result OBJECT on a clean config,
            # but an ARRAY of events when hooks/plugins add stream entries.
            start = min((i for i in (out.find("{"), out.find("[")) if i >= 0),
                        default=-1)
            if start < 0:
                # It answered with something, just not JSON. That is a config or
                # invocation problem and will reproduce exactly.
                raise ClaudeCLIDeterministic(
                    f"claude -p: no JSON in output: {out[:200]!r}")
            data, _ = json.JSONDecoder().raw_decode(out[start:])
            if isinstance(data, list):
                return next(x for x in data if x.get("type") == "result")
            return data

        # Retry ONLY what a retry can fix. Concurrent script generations can hit a
        # transient subscription throttle that returns empty stdout — a retry
        # almost always succeeds, so a parallel batch shouldn't lose a whole
        # script, and the waits are minutes-scale because a rate-limit window is
        # too (3×(4-8s) was observed live losing a 15-minute run to one throttle).
        #
        # Everything else fails immediately. Live 2026-07-17 15:36 spent ~6 minutes
        # and four subscription calls re-asking a settled question, because any
        # is_error was treated as a throttle. A deterministic failure retried is
        # just the same failure, later and more expensively.
        r = None
        _last = ""
        try:
            for _attempt in range(_MAX_ATTEMPTS):
                final = _attempt == _MAX_ATTEMPTS - 1
                try:
                    r = await asyncio.to_thread(_run)
                except ClaudeCLIDeterministic:
                    raise
                except ClaudeCLITransient as _ex:
                    _last = str(_ex)
                    r = None
                    if final:
                        break          # nothing left to wait for
                    await asyncio.sleep(20 * (_attempt + 1))
                    continue
                if not r.get("is_error"):
                    break                          # success
                _subtype = str(r.get("subtype") or "")
                _text = str(r.get("result") or "")
                _kind = _classify_result(_subtype, _text)
                if _kind == "auth":
                    _sync_credentials(force=True)  # stale copied token → resync + retry
                    _last = f"claude -p auth error: {_text[:200]}"
                    r = None
                    if final:
                        break
                    await asyncio.sleep(2)
                    continue
                if _kind == "transient":
                    _last = f"claude -p transient ({_subtype or 'is_error'}): {_text[:200]}"
                    r = None
                    if final:
                        break
                    await asyncio.sleep(20 * (_attempt + 1))
                    continue
                if _subtype == "error_max_turns":
                    # Actionable rather than mysterious: this only happens when the
                    # model spends its single turn on a tool call, which means the
                    # tool-disabling flags are not reaching the CLI.
                    raise ClaudeCLIDeterministic(
                        "claude -p hit max_turns: the model spent its one allowed "
                        "turn on a tool call. This client disables built-in tools "
                        '(--tools "" --disable-slash-commands); if you see this, '
                        f"those flags are not reaching the CLI. model={self._model}"
                    )
                if "session limit" in (_text or "").lower():
                    # Surface the quota hit on STDOUT: the detached batch loop
                    # greps run logs for "session limit ... resets" to decide
                    # whether to sleep until the window resets. A limit that
                    # only reaches the audit JSON (observed live: a compliance-
                    # stage hit) left the loop blind and the retry unspent.
                    logger.warning("claude-cli session limit", detail=_text[:160])
                raise ClaudeCLIDeterministic(
                    f"claude -p failed deterministically "
                    f"(subtype={_subtype or 'is_error'}): {_text[:300] or '(no message)'}"
                )
        finally:
            _sync_credentials_back()  # persist a token the CLI just rotated
            if sys_file is not None:
                try:
                    os.unlink(sys_file.name)
                except Exception:
                    pass
        if r is None or r.get("is_error"):
            raise ClaudeCLITransient(
                _last or "claude -p failed after retries")
        usage = r.get("usage") or {}
        # total_cost_usd from the CLI is NOTIONAL — subscription auth is not
        # billed per token. Ledger cost stays 0 so budgets/ROI aren't polluted;
        # the notional figure is logged for usage-limit awareness only.
        notional = round(float(r.get("total_cost_usd") or 0.0), 4)
        resp = LLMResponse(
            content=str(r.get("result") or ""),
            model=self._model,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=0.0,
            stop_reason="end_turn",
            notional_cost_usd=notional,
            role=self._role,
            effort=self._effort or "",
        )
        # role/effort in the line: the 14:32 log could only be read by inferring
        # the stage from timestamps.
        logger.info("claude-cli call completed", model=self._model,
                    role=self._role or "unlabelled", effort=self._effort or "default",
                    output_tokens=resp.output_tokens,
                    notional_cost_usd=notional)
        return resp

    async def complete_structured(self, *, system: str, messages: list[dict],
                                  output_schema: type,
                                  max_tokens: int | None = None,
                                  temperature: float = 0.3):
        import re

        import orjson
        resp = await self.complete(system=system, messages=messages,
                                   max_tokens=max_tokens, temperature=temperature)
        parsed = output_schema.model_validate(
            orjson.loads(extract_json(resp.content)))
        return resp, parsed
