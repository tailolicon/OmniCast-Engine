"""Gemini CLI backend — bills the operator's GOOGLE subscription, not Claude.

Runs `gemini -p` headless as an INDEPENDENT judge account. In claude_only mode
every judge shares one Anthropic account, so a provider hiccup takes out the
primary and there is nothing to escalate to ("no independent fallback
configured" aborted live runs on 2026-07-18). A Gemini fallback is a different
company, different quota window, different failure domain — a real fallback.

Requirements: `gemini` on PATH (npm i -g @google/gemini-cli) and a one-time
interactive login (`gemini` → Login with Google). An unauthenticated CLI fails
fast with an auth message; this client surfaces it verbatim.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys

import structlog

logger = structlog.get_logger()

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class GeminiCLIClient:
    """Duck-type of the pipeline's delegate contract (complete/complete_structured)."""

    def __init__(self, model: str = "gemini-2.5-pro", role: str = "gemini_judge") -> None:
        self._model = model
        self._role = role
        # The pipeline's health bookkeeping reads `_provider`/`_model` to decide
        # whether a fallback is genuinely a different account domain.
        self._provider = "google"

    async def complete(self, *, system: str, messages: list[dict],
                       max_tokens: int | None = None,
                       temperature: float = 0.3):
        from omnicast.llm.client import LLMResponse

        exe = shutil.which("gemini")
        if not exe:
            raise RuntimeError("`gemini` CLI not on PATH (npm i -g @google/gemini-cli)")
        user = "\n\n".join(m.get("content", "") for m in messages
                           if m.get("role") == "user") or " "
        # Long prompts go through STDIN (the -p text is appended after stdin by
        # the CLI); command-line length limits on Windows killed the same
        # pattern for claude -p until prompts moved to a file.
        stdin_payload = (f"{system}\n\n{user}" if system else user)
        cmd = [exe, "-m", self._model, "-p",
               "Follow the instructions above exactly. Output only what they ask for."]

        def _run() -> str:
            proc = subprocess.run(
                cmd, input=stdin_payload, capture_output=True, text=True,
                encoding="utf-8", timeout=600, creationflags=_NO_WINDOW,
                env={k: v for k, v in os.environ.items()},
            )
            out = (proc.stdout or "").strip()
            if proc.returncode != 0 or not out:
                err = (proc.stderr or proc.stdout or "").strip()[:400]
                raise RuntimeError(f"gemini -p failed (rc={proc.returncode}): {err!r}")
            return out

        last = ""
        for attempt in range(2):
            try:
                content = await asyncio.to_thread(_run)
                break
            except Exception as exc:  # noqa: BLE001 - retried once, then surfaced
                last = str(exc)
                if "auth" in last.lower() or "GEMINI_API_KEY" in last:
                    raise  # login problems never fix themselves mid-run
                await asyncio.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError(last or "gemini -p failed after retries")

        logger.info("gemini-cli call completed", model=self._model,
                    role=self._role, output_chars=len(content))
        return LLMResponse(
            content=content, model=self._model,
            input_tokens=0, output_tokens=0, cost_usd=0.0, stop_reason="end_turn",
        )

    async def complete_structured(self, *, system: str, messages: list[dict],
                                  output_schema: type,
                                  max_tokens: int | None = None,
                                  temperature: float = 0.2):
        from omnicast.llm.json_utils import parse_json_payload

        response = await self.complete(
            system=system, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        parsed = output_schema.model_validate(parse_json_payload(response.content))
        return response, parsed
