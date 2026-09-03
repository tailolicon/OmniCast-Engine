"""Alternative LLM backends for the reup translation engine.

The ported engine funnels every model call through one method,
`OpenAITranslationEngine._call_structured_output`, which does:

    client.responses.parse(model=..., instructions=..., input=...,
                           text_format=<pydantic model>, temperature=...,
                           prompt_cache_key=...)
    -> response.output_parsed, response.usage

That is the OpenAI Responses API, which nothing else implements. Rather than
rewrite the engine, this module supplies drop-in clients exposing the same
`.responses.parse(...)` shape, so swapping backends is a one-line change:

    engine = ClaudeCLITranslationEngine(settings)   # no API cost
    engine = GroqTranslationEngine(settings)        # cheap + very fast
    engine = OpenAITranslationEngine(settings)      # upstream default

Backends differ in how they are billed, which matters here because a single
video fans out to dozens of scene calls:

* claude-cli — runs `claude -p` against the operator's existing Claude
  subscription. No per-token charge. Slowest per call (process spawn).
* groq       — per-token but very cheap and very fast; open-weight models are
  weaker at zh→vi register and honorifics, so expect more review flags.
* openai     — upstream's tuned path; prompt caching works, costs the most.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from omnicast.reup.core.settings import AppSettings
from omnicast.reup.translate.openai_engine import OpenAITranslationEngine

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# `moonshotai/kimi-k2-instruct` 404s on a current Groq account — the job died
# at the translate stage with model_not_found after the download and ASR were
# already done. Checked against the live model list: gpt-oss-120b is the
# strongest general model there and handled a zh→vi test line cleanly in 1.5s.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"


@dataclass(slots=True)
class _Usage:
    """Mirrors the fields `_usage_value` probes on an OpenAI usage object."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(slots=True)
class _ParsedResponse:
    output_parsed: Any
    usage: _Usage


def _run_sync(coro):
    """Run an async call from the engine's synchronous code path.

    Reup stages run either on the CLI's main thread or on a plain worker thread
    from the API route — neither has a running loop, so `asyncio.run` is safe.
    The explicit check keeps the failure legible if that ever changes.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "reup translation backends are synchronous; call them off the event loop"
    )


class _ClaudeCLIResponses:
    def __init__(self, model: str, effort: str | None) -> None:
        self._model = model
        self._effort = effort

    def parse(
        self,
        *,
        model: str | None = None,
        instructions: str,
        input: str,  # noqa: A002 - matches the OpenAI keyword
        text_format: type,
        temperature: float = 0.2,
        prompt_cache_key: str | None = None,  # noqa: ARG002 - CLI has no cache key
    ) -> _ParsedResponse:
        from pydantic import ValidationError

        from omnicast.llm.claude_cli import ClaudeCLIClient, extract_json

        # `model` here is the pipeline's own label, which it also feeds into the
        # translation stage hash — for a non-OpenAI backend that string is
        # "claude-cli:default", not a model id. Passing it through reached
        # `claude -p --model claude-cli:default` and died on an unknown model.
        # The backend owns which Claude model it runs; set it on the engine.
        del model
        client = ClaudeCLIClient(
            model=self._model,
            effort=self._effort,
            role="reup-translate",
        )

        # `complete_structured` asks for "some JSON" and validates afterwards,
        # which is not enough here: on a two-line zh→vi sample it produced
        # {"1": "...", "2": "..."} instead of the declared {"lines": [...]}.
        # The pipeline matches segments by id, so a reshaped payload fails the
        # batch. Spell the schema out, and feed validation errors back on retry.
        schema = json.dumps(text_format.model_json_schema(), ensure_ascii=False)
        system = (
            f"{instructions}\n\n"
            f"Return ONLY a JSON object valid against this JSON Schema. No prose, "
            f"no markdown fence, no extra keys, and never rename or drop keys:\n{schema}"
        )

        last_error: Exception | None = None
        for attempt in range(2):
            messages = [{"role": "user", "content": input}]
            if last_error is not None:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous reply did not validate: {last_error}\n"
                            f"Return the same content reshaped to the schema exactly."
                        ),
                    }
                )
            response = _run_sync(
                client.complete(
                    system=system,
                    messages=messages,
                    temperature=temperature,
                )
            )
            try:
                parsed = text_format.model_validate(
                    json.loads(extract_json(response.content))
                )
            except (ValidationError, ValueError, TypeError) as exc:
                last_error = exc
                continue
            return _ParsedResponse(
                output_parsed=parsed,
                usage=_Usage(
                    input_tokens=getattr(response, "input_tokens", None),
                    output_tokens=getattr(response, "output_tokens", None),
                ),
            )

        raise RuntimeError(
            f"claude-cli did not return {text_format.__name__}-shaped JSON "
            f"after 2 attempts: {last_error}"
        )


_GROQ_MAX_ATTEMPTS = 6
_GROQ_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)s", re.I)


def groq_retry_delay(message: str, attempt: int) -> float:
    """How long to wait after a 429.

    Groq's free tier caps tokens per minute and the error says exactly how long
    to wait ("Please try again in 3.345s"). Honour that; a whole video's worth
    of scenes will trip the cap repeatedly and the job used to die outright on
    the first one, throwing away the download, the ASR and every scene already
    translated.
    """
    found = _GROQ_RETRY_AFTER_RE.search(message or "")
    if found:
        return min(60.0, float(found.group(1)) + 0.5)
    return min(60.0, 2.0 * (2 ** attempt))


def _groq_call(client, **kwargs):
    last: Exception | None = None
    for attempt in range(_GROQ_MAX_ATTEMPTS):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            retriable = status == 429 or status in {500, 502, 503, 529}
            if not retriable or attempt == _GROQ_MAX_ATTEMPTS - 1:
                raise
            last = exc
            time.sleep(groq_retry_delay(str(exc), attempt))
    raise last  # pragma: no cover - loop always returns or raises above


class _GroqResponses:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def parse(
        self,
        *,
        model: str | None = None,
        instructions: str,
        input: str,  # noqa: A002
        text_format: type,
        temperature: float = 0.2,
        prompt_cache_key: str | None = None,  # noqa: ARG002 - Groq has no cache key
    ) -> _ParsedResponse:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=GROQ_BASE_URL)
        schema = text_format.model_json_schema()
        # Same reasoning as the Claude shim: the incoming `model` is the
        # pipeline's cache label ("groq:default"), not a Groq model id.
        del model
        selected = self._model

        try:
            completion = _groq_call(
                client,
                model=selected,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": input},
                ],
                temperature=temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": text_format.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except Exception:
            # Not every Groq model accepts json_schema. json_object is universally
            # supported, so restate the schema in the prompt and validate after.
            completion = _groq_call(
                client,
                model=selected,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{instructions}\n\nReply with JSON matching this schema "
                            f"exactly:\n{json.dumps(schema, ensure_ascii=False)}"
                        ),
                    },
                    {"role": "user", "content": input},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )

        content = completion.choices[0].message.content or ""
        from omnicast.llm.claude_cli import extract_json

        parsed = text_format.model_validate(json.loads(extract_json(content)))
        usage = getattr(completion, "usage", None)
        return _ParsedResponse(
            output_parsed=parsed,
            usage=_Usage(
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            ),
        )


class _ShimClient:
    def __init__(self, responses: object) -> None:
        self.responses = responses


class ClaudeCLITranslationEngine(OpenAITranslationEngine):
    """Translate through `claude -p` — billed to the subscription, not per token."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        model: str = DEFAULT_CLAUDE_MODEL,
        effort: str | None = None,
    ) -> None:
        super().__init__(settings)
        self._cli_model = model
        self._cli_effort = effort

    def _build_client(self):
        return _ShimClient(_ClaudeCLIResponses(self._cli_model, self._cli_effort))

    @staticmethod
    def estimate_metric_cost_usd(metric, *, model: str) -> float:  # noqa: ARG004
        # Subscription-billed: per-call cost is not meaningful here, and
        # inheriting OpenAI's price table would invent charges that never happen.
        return 0.0


class GroqTranslationEngine(OpenAITranslationEngine):
    """Translate through Groq's OpenAI-compatible chat completions."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        api_key: str,
        model: str = DEFAULT_GROQ_MODEL,
    ) -> None:
        super().__init__(settings)
        if not api_key:
            raise RuntimeError("Groq backend needs an API key (GROQ_API_KEY)")
        self._groq_api_key = api_key
        self._groq_model = model

    def _build_client(self):
        return _ShimClient(_GroqResponses(self._groq_api_key, self._groq_model))


def build_translation_engine(
    backend: str,
    settings: AppSettings,
    *,
    model: str | None = None,
    groq_api_key: str | None = None,
    claude_effort: str | None = None,
):
    """Pick a translation engine by name: `claude-cli`, `groq`, or `openai`."""
    backend = (backend or "openai").strip().lower()
    if backend in {"claude-cli", "claude", "sonnet"}:
        return ClaudeCLITranslationEngine(
            settings, model=model or DEFAULT_CLAUDE_MODEL, effort=claude_effort
        )
    if backend == "groq":
        # Resolver, not os.environ: a key entered on the Providers screen lands
        # in the vault, and reading only the environment made the job die at the
        # translate stage — fifteen minutes of download and ASR in.
        from omnicast.config.credentials import resolve_api_key

        return GroqTranslationEngine(
            settings,
            api_key=resolve_api_key("groq", override=groq_api_key),
            model=model or DEFAULT_GROQ_MODEL,
        )
    if backend == "openai":
        return OpenAITranslationEngine(settings)
    raise ValueError(f"Unknown translation backend {backend!r}")
