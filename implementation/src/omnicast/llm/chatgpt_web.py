"""ChatGPT Web backend — routes prompts through the Shiro chatgpt-bridge relay.

Bills the operator's ChatGPT subscription, not an API balance. The relay
(github.com/DrA1ex/chatgpt-bridge, MIT — running as part of the Shiro stack)
drives a real logged-in chatgpt.com tab over a browser extension and exposes a
loopback HTTP API. One `POST /chat` = one prompt in, one full assistant reply
out; the relay serializes requests behind a global mutex, so this backend is
inherently one-call-at-a-time.

Requirements: the Shiro relay running on loopback (default 127.0.0.1:23158)
with at least one idle, logged-in ChatGPT tab connected. Credentials are read
from `.ShiroRuntime/state/chatgpt-relay.env` (key `API_TOKEN`) unless given
explicitly. A logged-out tab or a challenge page cannot be recovered
programmatically — those errors are surfaced verbatim and never retried.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Shiro's relay allows 30 minutes per answer (ANSWER_TIMEOUT_MS=1800000),
# but real answers land in 5-10 minutes; every observed 30-minute wait was a
# wedged tab, never a long Thinking turn. Cut off at 15 minutes so a wedge
# costs one recovery cycle instead of the relay's full ceiling. Aborting the
# HTTP request presses ChatGPT's stop button, which is acceptable here:
# _recover() reselects/restarts the tab before the retry anyway.
_READ_TIMEOUT_S = 900.0
_CONNECT_TIMEOUT_S = 30.0

_DEFAULT_RELAY_ENV = Path.home() / "Projects" / ".ShiroRuntime" / "state" / "chatgpt-relay.env"


class ChatGPTWebDeterministic(RuntimeError):
    """Errors that never fix themselves mid-run: bad token, no logged-in tab."""


class ChatGPTWebTransient(RuntimeError):
    """Errors worth one more attempt: 5xx, transport hiccups, transient turn errors."""


def _parse_env_file(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("\"'")
    return cfg


class ChatGPTWebClient:
    """Duck-type of the pipeline's delegate contract (complete/complete_structured)."""

    def __init__(self, *, base_url: str = "", api_token: str = "",
                 model: str = "", effort: str = "",
                 relay_env: str = "", max_tokens: int = 4096,
                 role: str = "chatgpt_web") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._effort = effort.strip()
        self._relay_env = relay_env
        self._role = role
        # The pipeline's health bookkeeping reads `_provider`/`_model` to decide
        # whether a fallback is genuinely a different account domain. The model
        # string is a ChatGPT UI picker label (e.g. "GPT-5.6 Thinking"); empty
        # means "whatever the tab is set to", reported as chatgpt-web.
        self._provider = "chatgpt_web"
        self._ui_model = model.strip()
        self._model = self._ui_model or "chatgpt-web"

    # --- config resolution -------------------------------------------------

    def _resolve(self) -> tuple[str, str]:
        if self._base_url and self._api_token:
            return self._base_url, self._api_token
        candidates = [p for p in (self._relay_env,
                                  os.environ.get("SHIRO_RELAY_ENV", ""))
                      if p] + [str(_DEFAULT_RELAY_ENV)]
        for candidate in candidates:
            path = Path(candidate).expanduser()
            if not path.is_file():
                continue
            cfg = _parse_env_file(path)
            if not self._api_token:
                self._api_token = cfg.get("API_TOKEN", "")
            if not self._base_url:
                host = cfg.get("HOST", "127.0.0.1") or "127.0.0.1"
                port = cfg.get("PORT", "23158") or "23158"
                self._base_url = f"http://{host}:{port}"
            break
        if not (self._base_url and self._api_token):
            raise ChatGPTWebDeterministic(
                "chatgpt_web: relay credentials not found — set "
                "chatgpt_web_base_url/chatgpt_web_api_token or point "
                "chatgpt_web_relay_env at .ShiroRuntime/state/chatgpt-relay.env"
            )
        return self._base_url, self._api_token

    # --- relay calls -------------------------------------------------------

    async def _pick_client(self, http, base: str) -> str:
        """A ready, idle, non-quarantined tab; prefer a blank chat so a human's
        open conversation is never hijacked."""
        r = await http.get(f"{base}/browser/clients")
        if r.status_code in (401, 403):
            raise ChatGPTWebDeterministic(f"chatgpt_web: relay auth failed ({r.status_code})")
        r.raise_for_status()
        clients = r.json().get("clients", [])
        usable = [c for c in clients
                  if c.get("ready") and not c.get("quarantined")
                  and not c.get("activeRequest")]
        blank = [c for c in usable if "/c/" not in (c.get("url") or "")]
        pool = blank or usable
        if not pool:
            raise ChatGPTWebDeterministic(
                "chatgpt_web: no idle ChatGPT tab connected to the relay — "
                "open/log into chatgpt.com in the Shiro browser profile"
            )
        return pool[0]["id"]

    async def _recover(self) -> None:
        """Self-heal the relay's browser side between retries.

        Live failure mode (2026-09-03): every /chat opened or left conversation
        tabs behind until the relay hit needsSelection, the one blank tab sat
        quarantined, and three 30-minute reads timed out in a row. Selection is
        an API call; a wedged tab set is only fixed by bouncing the dedicated
        chromium profile (proven manually). Both are safe to automate on this
        operator-local stack. Failures here are swallowed — the retry that
        follows will surface the real state."""
        import subprocess
        import httpx

        base, token = self._resolve()
        headers = {"Authorization": f"Bearer {token}"}
        timeout = httpx.Timeout(20.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as http:
                r = await http.get(f"{base}/browser/clients")
                clients = r.json().get("clients", []) if r.status_code == 200 else []
                usable = [c for c in clients
                          if c.get("ready") and not c.get("quarantined")
                          and not c.get("activeRequest")]
                blank = [c for c in usable if "/c/" not in (c.get("url") or "")]
                if blank:
                    await http.post(f"{base}/browser/select",
                                    json={"clientId": blank[0]["id"]})
                    logger.info("chatgpt_web recovered via select",
                                client=blank[0]["id"][:40])
                    return
        except Exception as exc:  # noqa: BLE001 - recovery is best-effort
            logger.warning("chatgpt_web recover probe failed", error=str(exc)[:120])
        if os.environ.get("OMNICAST_CHATGPT_WEB_AUTORESTART", "1") == "0":
            return
        profile = str(Path.home() / "Projects" / ".ShiroRuntime" / "chrome-profile")
        ext = str(Path.home() / "Projects" / ".ShiroRuntime" / "chatgpt-extension")
        logger.warning("chatgpt_web restarting dedicated chromium", profile=profile)
        try:
            subprocess.run(["pkill", "-f", f"--user-data-dir={profile}"],
                           capture_output=True, timeout=20)
            await asyncio.sleep(4)
            subprocess.Popen(
                ["chromium", f"--user-data-dir={profile}", f"--load-extension={ext}",
                 "--no-first-run", "--no-default-browser-check",
                 "--disable-background-timer-throttling", "--ozone-platform-hint=auto",
                 "--start-minimized", "https://chatgpt.com/"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True)
            # wait for exactly one fresh client to register
            import httpx as _hx
            async with _hx.AsyncClient(timeout=timeout, headers=headers) as http:
                for _ in range(24):
                    await asyncio.sleep(5)
                    try:
                        h = await http.get(f"{base}/health")
                        hd = h.json()
                        if hd.get("ok") and int(hd.get("clients") or 0) >= 1:
                            logger.info("chatgpt_web chromium back", clients=hd.get("clients"))
                            return
                    except Exception:  # noqa: BLE001
                        continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("chatgpt_web chromium restart failed", error=str(exc)[:120])

    async def _chat_once(self, message: str) -> str:
        import httpx

        base, token = self._resolve()
        timeout = httpx.Timeout(_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as http:
            health = await http.get(f"{base}/health")
            if health.status_code in (401, 403):
                raise ChatGPTWebDeterministic(
                    f"chatgpt_web: relay auth failed ({health.status_code})")
            hd = health.json() if health.status_code == 200 else {}
            needs_selection = bool(hd.get("needsSelection")) or (
                "select" in str(hd.get("error") or "").lower())
            # needsSelection is not a human problem — this client always names
            # its tab via sourceClientId, so only a truly empty/broken relay
            # (no tab, logged out, extension gone) is fatal here.
            if not hd.get("clients") or (not hd.get("ok") and not needs_selection):
                raise ChatGPTWebDeterministic(
                    f"chatgpt_web: relay unhealthy ({hd.get('error') or health.status_code}) "
                    "— the browser needs human attention (login/extension)")

            body: dict = {
                "message": message,
                # Every pipeline call already carries its full context, so each
                # request is a fresh conversation; no thread state to corrupt.
                "newSession": True,
                # Shiro runs the relay with AUTO_OPEN_TAB=1 — without an explicit
                # tab an ambiguous /chat silently opens NEW chatgpt.com tabs.
                "sourceClientId": await self._pick_client(http, base),
                "autoOpenTab": False,
            }
            if self._ui_model:
                body["model"] = self._ui_model
            if self._effort:
                body["effort"] = self._effort

            r = await http.post(f"{base}/chat", json=body)
            if r.status_code in (401, 403):
                raise ChatGPTWebDeterministic(f"chatgpt_web: relay auth failed ({r.status_code})")
            if r.status_code >= 500:
                raise ChatGPTWebTransient(
                    f"chatgpt_web: relay HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code >= 400:
                detail = ""
                try:
                    detail = r.json().get("detail", "")
                except Exception:  # noqa: BLE001 - body may not be JSON
                    detail = r.text[:300]
                raise ChatGPTWebDeterministic(f"chatgpt_web: relay HTTP {r.status_code}: {detail}")
            data = r.json()
            text = (data.get("response") or data.get("answer") or "").strip()
            finish = str(data.get("finishReason") or "")
            if not text:
                # A turn that died mid-flight (transient ChatGPT error, source
                # lost) is worth one more attempt on a fresh conversation.
                raise ChatGPTWebTransient(
                    f"chatgpt_web: empty answer (finishReason={finish or 'unknown'})")
            return text

    # --- delegate contract -------------------------------------------------

    async def complete(self, *, system: str, messages: list[dict],
                       max_tokens: int | None = None,
                       temperature: float = 0.7):
        from omnicast.llm.client import LLMResponse

        # The web UI has no system slot or sampling params: fold the system
        # prompt and prior turns into one plain-text prompt per request.
        parts: list[str] = []
        if system:
            parts.append(system.strip())
        for m in messages:
            content = str(m.get("content", "")).strip()
            if not content:
                continue
            if m.get("role") == "assistant":
                parts.append(f"[Your previous reply]\n{content}")
            else:
                parts.append(content)
        prompt = "\n\n".join(parts) or " "

        last = ""
        for attempt in range(3):
            try:
                content = await self._chat_once(prompt)
                break
            except ChatGPTWebDeterministic:
                raise
            except Exception as exc:  # noqa: BLE001 - transient path, retried then surfaced
                last = str(exc)
                logger.warning("chatgpt_web transient failure",
                               attempt=attempt, error=last[:200])
                await self._recover()
                await asyncio.sleep(5 * (attempt + 1))
        else:
            raise ChatGPTWebTransient(last or "chatgpt_web: failed after retries")

        logger.info("chatgpt_web call completed", model=self._model,
                    role=self._role, output_chars=len(content))
        # The relay reports no token usage; estimate for the session ledgers.
        return LLMResponse(
            content=content, model=self._model,
            input_tokens=len(prompt) // 4, output_tokens=len(content) // 4,
            cost_usd=0.0, stop_reason="end_turn", role=self._role,
        )

    async def complete_structured(self, *, system: str, messages: list[dict],
                                  output_schema: type,
                                  max_tokens: int | None = None,
                                  temperature: float = 0.3):
        from omnicast.llm.json_utils import parse_json_payload

        response = await self.complete(
            system=system, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        parsed = output_schema.model_validate(parse_json_payload(response.content))
        return response, parsed

    @property
    def total_cost(self) -> float:
        return 0.0
