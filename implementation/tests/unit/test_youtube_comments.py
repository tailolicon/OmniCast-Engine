"""YouTubePlatform.fetch_comments — real commentThreads read (P0 item 2).

The bug: `fetch_comments` was `return []`. An audience-feedback consumer could
not distinguish "this video has no comments" from "this was never implemented",
so a stub read as a finding. These tests pin real paging, reply flattening, and
— most importantly — that an empty result now carries its reason."""

from __future__ import annotations

import pytest

from omnicast.platforms.models import PlatformId
from omnicast.platforms.youtube import YouTubePlatform


class FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class FakeThreads:
    """Stands in for service.commentThreads(); records the params it was given."""

    def __init__(self, pages, error=None):
        self.pages = pages
        self.error = error
        self.calls: list[dict] = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeRequest(self.pages[len(self.calls) - 1])


class FakeService:
    def __init__(self, threads):
        self._threads = threads

    def commentThreads(self):
        return self._threads


def _thread(cid, text, replies=0, reply_texts=()):
    item = {
        "id": f"thread_{cid}",
        "snippet": {
            "videoId": "vid1",
            "totalReplyCount": replies,
            "topLevelComment": {
                "id": cid,
                "snippet": {
                    "authorDisplayName": f"user_{cid}",
                    "authorChannelId": {"value": f"UC_{cid}"},
                    "textOriginal": text,
                    "likeCount": 7,
                    "publishedAt": "2026-07-01T00:00:00Z",
                    "updatedAt": "2026-07-01T00:00:00Z",
                },
            },
        },
    }
    if reply_texts:
        item["replies"] = {"comments": [
            {"id": f"{cid}_r{i}", "snippet": {
                "videoId": "vid1", "authorDisplayName": "replier",
                "authorChannelId": {"value": "UC_r"}, "textOriginal": t,
                "likeCount": 1, "publishedAt": "2026-07-02T00:00:00Z",
                "parentId": cid}}
            for i, t in enumerate(reply_texts)
        ]}
    return item


def _settings(monkeypatch, dry_run=False, api_key="k"):
    class _Settings:
        is_dry_run = dry_run
        youtube_api_key = api_key

    import omnicast.config.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: _Settings())


def _platform(monkeypatch, service=None, error=None, pages=None, dry_run=False):
    plat = YouTubePlatform(uploader=object())
    threads = FakeThreads(pages or [], error=error)
    fake = service or FakeService(threads)

    monkeypatch.setattr(YouTubePlatform, "_build_api_key_service",
                        lambda self: fake)
    _settings(monkeypatch, dry_run=dry_run)
    return plat, threads


async def test_returns_real_comments_with_replies_flattened(monkeypatch):
    pages = [{"items": [_thread("c1", "great video", replies=1, reply_texts=["thanks"])]}]
    plat, threads = _platform(monkeypatch, pages=pages)
    out = await plat.fetch_comments("vid1", "acct")
    assert [c["text"] for c in out] == ["great video", "thanks"]
    top, reply = out
    assert top["is_reply"] is False and top["reply_count"] == 1
    assert reply["is_reply"] is True and reply["parent_id"] == "c1"
    assert top["author_channel_id"] == "UC_c1"
    assert top["like_count"] == 7
    assert out.status == "ok"


async def test_pages_until_the_cap_then_stops(monkeypatch):
    pages = [
        {"items": [_thread(f"a{i}", f"t{i}") for i in range(2)], "nextPageToken": "p2"},
        {"items": [_thread(f"b{i}", f"u{i}") for i in range(2)]},
    ]
    plat, threads = _platform(monkeypatch, pages=pages)
    out = await plat.fetch_comments("vid1", "acct", max_comments=4)
    assert len(out) == 4
    assert len(threads.calls) == 2
    assert threads.calls[1]["pageToken"] == "p2"


async def test_cap_is_respected_even_mid_page(monkeypatch):
    pages = [{"items": [_thread(f"a{i}", f"t{i}") for i in range(5)]}]
    plat, _ = _platform(monkeypatch, pages=pages)
    out = await plat.fetch_comments("vid1", "acct", max_comments=3)
    assert len(out) == 3


async def test_disabled_comments_report_a_reason_not_a_bare_empty_list(monkeypatch):
    """The whole point of the fix: emptiness must be explainable."""

    class ApiError(Exception):
        pass

    plat, _ = _platform(monkeypatch, pages=[], error=ApiError("commentsDisabled for video"))
    out = await plat.fetch_comments("vid1", "acct")
    assert out == []
    assert out.status == "comments_disabled"


async def test_quota_exhaustion_is_distinguishable_from_disabled(monkeypatch):
    class ApiError(Exception):
        pass

    plat, _ = _platform(monkeypatch, pages=[], error=ApiError("quotaExceeded"))
    out = await plat.fetch_comments("vid1", "acct")
    assert out == []
    assert out.status == "quota_exceeded"


async def test_dry_run_says_dry_run(monkeypatch):
    plat, _ = _platform(monkeypatch, pages=[{"items": []}], dry_run=True)
    out = await plat.fetch_comments("vid1", "acct")
    assert out == []
    assert out.status == "dry_run"


async def test_missing_post_id_is_rejected_before_any_api_call(monkeypatch):
    plat, threads = _platform(monkeypatch, pages=[{"items": []}])
    out = await plat.fetch_comments("", "acct")
    assert out == []
    assert out.status == "no post_id"
    assert threads.calls == []


async def test_request_asks_for_replies_and_plain_text(monkeypatch):
    plat, threads = _platform(monkeypatch, pages=[{"items": []}])
    await plat.fetch_comments("vid1", "acct")
    params = threads.calls[0]
    assert "replies" in params["part"]
    assert params["textFormat"] == "plainText"
    assert params["videoId"] == "vid1"


def test_platform_id_unchanged():
    assert YouTubePlatform.id == PlatformId.YOUTUBE.value


@pytest.mark.parametrize("blob,expected", [
    ("commentsDisabled", "comments_disabled"),
    ("rateLimitExceeded", "quota_exceeded"),
    ("videoNotFound", "video_not_found"),
])
def test_error_reasons_are_mapped(blob, expected):
    from omnicast.platforms.youtube import _comment_error_reason

    assert _comment_error_reason(Exception(blob)) == expected


# ── Outcome travels with the result, not on the adapter ──────────────────────

async def test_status_rides_on_the_result_so_concurrent_fetches_cannot_race(monkeypatch):
    """Two fetches sharing one adapter used to overwrite each other's reason on
    `self`, so the loser read the winner's diagnosis of a different video."""
    import asyncio

    class Router:
        """Fails for 'bad', succeeds for 'good'."""

        def commentThreads(self):
            return self

        def list(self, **kw):
            if kw["videoId"] == "bad":
                raise Exception("commentsDisabled")
            return FakeRequest({"items": [_thread("c1", "hello")]})

    plat = YouTubePlatform(uploader=object())

    monkeypatch.setattr(YouTubePlatform, "_build_api_key_service",
                        lambda self: Router())
    _settings(monkeypatch)

    good, bad = await asyncio.gather(
        plat.fetch_comments("good", "acct"),
        plat.fetch_comments("bad", "acct"),
    )
    assert good.status == "ok" and good.ok is True and len(good) == 1
    assert bad.status == "comments_disabled" and bad.ok is False and len(bad) == 0


async def test_result_still_behaves_like_a_plain_list(monkeypatch):
    plat, _ = _platform(monkeypatch, pages=[{"items": [_thread("c1", "x")]}])
    out = await plat.fetch_comments("vid1", "acct")
    assert isinstance(out, list)
    assert len(out) == 1 and out[0]["text"] == "x"
    assert [c["text"] for c in out] == ["x"]


# ── OAuth degrades to the API key instead of giving up ───────────────────────

async def test_broken_oauth_falls_back_to_the_api_key(monkeypatch):
    """A revoked token must not be reported as 'this video has no comments' —
    public comment threads are readable with the key alone."""

    class DeadOAuth:
        async def get_credentials(self, account_id):
            raise RuntimeError("refresh token revoked")

    threads = FakeThreads([{"items": [_thread("c1", "still readable")]}])
    plat = YouTubePlatform(uploader=object(), oauth=DeadOAuth())
    monkeypatch.setattr(YouTubePlatform, "_build_api_key_service",
                        lambda self: FakeService(threads))
    _settings(monkeypatch)

    out = await plat.fetch_comments("vid1", "acct")
    assert out.status == "ok"
    assert out.credential == "api_key_after_oauth_failure"
    assert [c["text"] for c in out] == ["still readable"]


async def test_oauth_is_preferred_when_it_works(monkeypatch):
    class LiveOAuth:
        async def get_credentials(self, account_id):
            assert account_id == "acct"      # the account is passed, not stored
            return "creds"

    class Uploader:
        def _build_service(self, credentials):
            assert credentials == "creds"
            return FakeService(FakeThreads([{"items": [_thread("c1", "oauth path")]}]))

    plat = YouTubePlatform(uploader=Uploader(), oauth=LiveOAuth())
    _settings(monkeypatch)
    out = await plat.fetch_comments("vid1", "acct")
    assert out.credential == "oauth"
    assert out.status == "ok"


async def test_no_oauth_and_no_key_is_a_named_failure(monkeypatch):
    plat = YouTubePlatform(uploader=object())
    _settings(monkeypatch, api_key="")
    out = await plat.fetch_comments("vid1", "acct")
    assert out == []
    assert out.status == "no_credentials"
