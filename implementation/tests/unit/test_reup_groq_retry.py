"""Groq's free tier rate-limits mid-video; the job must ride it out."""

import pytest

from omnicast.reup.translate import llm_backends as lb


class _Err(Exception):
    def __init__(self, status_code, message="boom"):
        super().__init__(message)
        self.status_code = status_code


def test_the_servers_own_hint_is_honoured():
    msg = ("Rate limit reached for model `x` ... on tokens per minute (TPM): "
           "Limit 12000, Used 8409, Requested 4260. Please try again in 3.345s.")
    assert lb.groq_retry_delay(msg, 0) == pytest.approx(3.845)


def test_without_a_hint_it_backs_off():
    delays = [lb.groq_retry_delay("no hint", i) for i in range(4)]
    assert delays == [2.0, 4.0, 8.0, 16.0]


def test_a_hostile_hint_cannot_stall_the_job_forever():
    assert lb.groq_retry_delay("try again in 99999s", 0) == 60.0


def test_a_rate_limited_call_is_retried(monkeypatch):
    monkeypatch.setattr(lb.time, "sleep", lambda s: None)
    calls = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls.append(1)
                    if len(calls) < 3:
                        raise _Err(429, "Please try again in 0.1s")
                    return "ok"

    assert lb._groq_call(_Client(), model="m") == "ok"
    assert len(calls) == 3


def test_a_bad_request_is_not_retried(monkeypatch):
    monkeypatch.setattr(lb.time, "sleep", lambda s: None)
    calls = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls.append(1)
                    raise _Err(400, "json_validate_failed")

    with pytest.raises(_Err):
        lb._groq_call(_Client(), model="m")
    assert len(calls) == 1, "a malformed request will fail again identically"


def test_it_gives_up_rather_than_retrying_forever(monkeypatch):
    monkeypatch.setattr(lb.time, "sleep", lambda s: None)
    calls = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls.append(1)
                    raise _Err(429)

    with pytest.raises(_Err):
        lb._groq_call(_Client(), model="m")
    assert len(calls) == lb._GROQ_MAX_ATTEMPTS


def test_the_default_model_is_one_groq_actually_serves():
    # kimi-k2-instruct 404s on a current account and killed the job after the
    # download and ASR were already paid for.
    assert lb.DEFAULT_GROQ_MODEL != "moonshotai/kimi-k2-instruct"
