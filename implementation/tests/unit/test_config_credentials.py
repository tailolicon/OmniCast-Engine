"""A key is a key wherever the operator put it."""

import pytest

from omnicast.config import credentials as creds


def test_environment_wins(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    monkeypatch.setattr(creds, "_from_vault", lambda p: "from-vault")
    assert creds.resolve_api_key("groq") == "from-env"


def test_an_explicit_override_beats_everything(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    assert creds.resolve_api_key("groq", override="explicit") == "explicit"


def test_the_vault_is_used_when_nothing_else_has_it(monkeypatch):
    # This is the case that silently failed: saved on the Providers screen,
    # invisible to every consumer, job dies at the translate stage.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(creds, "_from_vault", lambda p: "from-vault")

    class _Settings:
        groq_api_key = ""

    monkeypatch.setattr("omnicast.config.settings.get_settings", lambda: _Settings())
    assert creds.resolve_api_key("groq") == "from-vault"
    assert creds.has_api_key("groq")


def test_blank_everywhere_is_an_empty_string_not_a_crash(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(creds, "_from_vault", lambda p: "")

    class _Settings:
        groq_api_key = "   "

    monkeypatch.setattr("omnicast.config.settings.get_settings", lambda: _Settings())
    assert creds.resolve_api_key("groq") == ""
    assert not creds.has_api_key("groq")


def test_an_unlisted_provider_falls_back_to_conventional_names(monkeypatch):
    monkeypatch.setenv("SOMETHING_API_KEY", "k")
    assert creds.resolve_api_key("something") == "k"


def test_a_broken_vault_does_not_take_the_lookup_down(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    def _explode(provider):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(creds, "_from_vault", _explode)

    class _Settings:
        groq_api_key = "from-settings"

    monkeypatch.setattr("omnicast.config.settings.get_settings", lambda: _Settings())
    assert creds.resolve_api_key("groq") == "from-settings"
