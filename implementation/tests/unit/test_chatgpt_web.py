"""ChatGPT Web relay backend — prompt composition, config resolution, errors."""

import pytest
from pydantic import BaseModel

from omnicast.llm.chatgpt_web import (
    ChatGPTWebClient,
    ChatGPTWebDeterministic,
    _parse_env_file,
)


class _Verdict(BaseModel):
    ok: bool


def test_parse_env_file(tmp_path):
    env = tmp_path / "chatgpt-relay.env"
    env.write_text(
        "# comment\nHOST=127.0.0.1\nPORT=23158\nAPI_TOKEN='secret-token'\n\n",
        encoding="utf-8",
    )
    cfg = _parse_env_file(env)
    assert cfg == {"HOST": "127.0.0.1", "PORT": "23158", "API_TOKEN": "secret-token"}


def test_resolve_from_relay_env(tmp_path):
    env = tmp_path / "chatgpt-relay.env"
    env.write_text("HOST=127.0.0.1\nPORT=9999\nAPI_TOKEN=tok\n", encoding="utf-8")
    client = ChatGPTWebClient(relay_env=str(env))
    base, token = client._resolve()
    assert base == "http://127.0.0.1:9999"
    assert token == "tok"


def test_resolve_missing_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.delenv("SHIRO_RELAY_ENV", raising=False)
    client = ChatGPTWebClient(relay_env=str(tmp_path / "nope.env"))
    # No explicit creds and no readable env file anywhere it was pointed at.
    monkeypatch.setattr(
        "omnicast.llm.chatgpt_web._DEFAULT_RELAY_ENV", tmp_path / "also-nope.env"
    )
    with pytest.raises(ChatGPTWebDeterministic):
        client._resolve()


def test_identity_attributes():
    client = ChatGPTWebClient(model="GPT-5.6 Thinking")
    assert client._provider == "chatgpt_web"
    assert client._model == "GPT-5.6 Thinking"
    assert ChatGPTWebClient()._model == "chatgpt-web"
    assert client.total_cost == 0.0


async def test_complete_composes_prompt(monkeypatch):
    client = ChatGPTWebClient()
    sent: list[str] = []

    async def fake_chat(message: str) -> str:
        sent.append(message)
        return "the answer"

    monkeypatch.setattr(client, "_chat_once", fake_chat)
    resp = await client.complete(
        system="SYSTEM RULES",
        messages=[
            {"role": "user", "content": "first ask"},
            {"role": "assistant", "content": "earlier draft"},
            {"role": "user", "content": "revise it"},
        ],
    )
    assert resp.content == "the answer"
    assert resp.cost_usd == 0.0
    prompt = sent[0]
    assert prompt.index("SYSTEM RULES") < prompt.index("first ask")
    assert "[Your previous reply]\nearlier draft" in prompt
    assert prompt.rstrip().endswith("revise it")


async def test_complete_structured_parses_fenced_json(monkeypatch):
    client = ChatGPTWebClient()

    async def fake_chat(message: str) -> str:
        return "Sure!\n```json\n{\"ok\": true}\n```"

    monkeypatch.setattr(client, "_chat_once", fake_chat)
    _, parsed = await client.complete_structured(
        system="", messages=[{"role": "user", "content": "judge"}],
        output_schema=_Verdict,
    )
    assert parsed.ok is True


async def test_deterministic_error_not_retried(monkeypatch):
    client = ChatGPTWebClient()
    calls = {"n": 0}

    async def fake_chat(message: str) -> str:
        calls["n"] += 1
        raise ChatGPTWebDeterministic("relay auth failed")

    monkeypatch.setattr(client, "_chat_once", fake_chat)
    with pytest.raises(ChatGPTWebDeterministic):
        await client.complete(system="", messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 1
