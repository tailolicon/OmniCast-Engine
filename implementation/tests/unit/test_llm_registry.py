"""Tests for the LLM provider registry — extensibility without editing LLMClient."""

import pytest

from omnicast.llm import LLMResponse
from omnicast.llm.client import LLMClient
from omnicast.llm.registry import (
    OpenAICompatClient,
    get_llm_backend,
    list_llm_providers,
    register_llm_backend,
)


@pytest.fixture
def staging_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x@localhost/db")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost/")
    monkeypatch.setenv("OMNICAST_MODE", "staging")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    from omnicast.config.settings import reset_settings
    reset_settings()


class TestRegistry:
    def test_builtins_registered(self):
        providers = list_llm_providers()
        for expected in ("deepseek", "ollama", "openai", "groq"):
            assert expected in providers

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_backend("does-not-exist")

    def test_register_custom_provider(self, staging_settings):
        """A new provider becomes usable via one register call — no LLMClient edit."""

        class FakeBackend:
            _model = "fake-1"

            async def complete(self, *, system, messages, max_tokens=None, temperature=0.7):
                return LLMResponse(
                    content="fake", model="fake-1",
                    input_tokens=1, output_tokens=1,
                    cost_usd=0.0, stop_reason="stop",
                )

            async def complete_structured(self, *, system, messages, output_schema,
                                          max_tokens=None, temperature=0.3):
                return (await self.complete(system=system, messages=messages)), output_schema()

            @property
            def total_cost(self) -> float:
                return 0.0

        register_llm_backend("fake", lambda **kw: FakeBackend())
        assert "fake" in list_llm_providers()
        backend = get_llm_backend("fake")
        assert isinstance(backend, FakeBackend)

    async def test_llmclient_uses_registered_provider(self, staging_settings):
        """LLMClient routes a registry provider through the delegate path."""

        class EchoBackend:
            _model = "echo-1"

            async def complete(self, *, system, messages, max_tokens=None, temperature=0.7):
                return LLMResponse(
                    content=messages[-1]["content"], model="echo-1",
                    input_tokens=0, output_tokens=0,
                    cost_usd=0.0, stop_reason="stop",
                )

            async def complete_structured(self, *, system, messages, output_schema,
                                          max_tokens=None, temperature=0.3):
                return (await self.complete(system=system, messages=messages)), output_schema()

            @property
            def total_cost(self) -> float:
                return 0.0

        register_llm_backend("echo", lambda **kw: EchoBackend())
        client = LLMClient(provider="echo")
        resp = await client.complete(system="s", messages=[{"role": "user", "content": "ping"}])
        assert resp.content == "ping"
        assert client.total_cost == 0.0


class TestOpenAICompatClient:
    def test_local_provider_defaults_key(self):
        """Ollama needs no real key; client tolerates empty."""
        c = OpenAICompatClient(api_key="", model="llama3.1:70b",
                               base_url="http://localhost:11434/v1", provider_id="ollama")
        assert c._api_key == "not-needed"
        assert c._model == "llama3.1:70b"
        assert c.total_cost == 0.0
