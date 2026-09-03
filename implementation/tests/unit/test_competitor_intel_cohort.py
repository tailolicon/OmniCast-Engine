"""competitor_intel now learns from a winner/control cohort (review §4.1, §4.8).

The verified bug: `_top_competitor_videos` did `vids.sort(key=views)[:N]`, so
playbooks described "what high-view videos look like" — big channels, old
videos, and every trait the channel repeats in its flops too. These tests pin
the replacement: per-channel outliers, a matched control group, contrast
prompts, and an explicit UNCONTROLLED stamp when no control could be paired."""

from __future__ import annotations

import pytest

from omnicast.analytics import competitor_intel as ci
from omnicast.analytics.cohort import select_cohort
from omnicast.analytics.transcript import Segment, Transcript


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """Records every prompt so the tests can assert on what the model was told."""

    def __init__(self, reply="PLAYBOOK"):
        self.reply = reply
        self.calls: list[dict] = []

    async def complete(self, system, messages, **kw):
        self.calls.append({"system": system, "user": messages[0]["content"]})
        return FakeResponse(self.reply)


def _v(vid, views, *, day="2026-07-01", minutes=15.0, title=None):
    return {
        "video_id": vid,
        "title": title or f"title {vid}",
        "views": views,
        "duration_minutes": minutes,
        "published_at": f"{day}T00:00:00Z",
        "engagement_rate": 0.03,
        "thumbnail_url": f"https://img/{vid}.jpg",
    }


def _cohort_with_controls():
    return select_cohort({
        "chan": [
            _v("win", 50_000, title="The winner title"),
            _v("ctl", 10_000, day="2026-07-04", title="An ordinary title"),
            _v("filler", 9_500, day="2026-06-01"),
        ]
    })


def _cohort_without_controls():
    return select_cohort({
        "chan": [
            _v("win", 90_000, day="2026-07-01"),
            _v("old_a", 10_000, day="2019-01-01"),
            _v("old_b", 10_000, day="2019-02-01"),
        ]
    })


def _by_id(cohort):
    ids = [r.video_id for r in cohort.winners + cohort.controls]
    return {i: _v(i, 1) for i in ids}


# ── Cohort assembly ──────────────────────────────────────────────────────────

async def test_videos_stay_grouped_by_channel_so_a_median_can_be_computed(monkeypatch):
    """The original flattened everything into one list; a per-channel median is
    impossible after that."""

    class FakeScanner:
        def __init__(self, config=None, api_key=None, http_client=None):
            # http_client is now injected and closed by the caller, so the
            # scanner's own un-closed AsyncClient is never created.
            self.http = http_client

        async def _resolve_handle(self, handle):
            return f"id_{handle}"

        async def _get_channel_uploads_playlist_id(self, cid):
            return f"pl_{cid}"

        async def _get_recent_video_ids(self, pl, max_results=30):
            return ["a", "b", "c"]

        async def _get_video_stats(self, ids):
            return [_v(f"{i}", 100) for i in ids]

    import omnicast.discovery.youtube_scanner as ys

    monkeypatch.setattr(ys, "YouTubeScanner", FakeScanner)

    class Chan:
        competitor_channel_ids = ["c1", "c2"]
        competitor_handles = []

    grouped = await ci._fetch_competitor_videos(Chan(), "key")
    assert set(grouped) == {"c1", "c2"}
    assert len(grouped["c1"]) == 3


# ── Title playbook ───────────────────────────────────────────────────────────

async def test_title_prompt_shows_both_groups_labelled():
    llm = FakeLLM()
    cohort = _cohort_with_controls()
    await ci._learn_titles(llm, cohort)
    user = llm.calls[0]["user"]
    assert "WINNER" in user and "CONTROL" in user
    assert "The winner title" in user
    assert "An ordinary title" in user
    # P0.1 group 2: labelling the two groups is no longer enough — the pairing
    # itself has to survive into the prompt, together with the channel, or the
    # model contrasts group means across channels.
    assert "PAIR 1" in user
    assert "chan" in user
    # The system prompt must forbid reporting traits shared by both groups.
    assert "house style" in llm.calls[0]["system"]


async def test_winner_only_playbook_is_stamped_uncontrolled():
    """Survivorship bias is allowed to reach the reader only when it is
    labelled as such."""
    llm = FakeLLM()
    cohort = _cohort_without_controls()
    assert cohort.is_comparable is False
    out = await ci._learn_titles(llm, cohort)
    assert out.startswith("[UNCONTROLLED")


async def test_comparable_playbook_is_not_stamped():
    llm = FakeLLM()
    out = await ci._learn_titles(llm, _cohort_with_controls())
    assert not out.startswith("[UNCONTROLLED")
    assert out == "PLAYBOOK"


async def test_empty_cohort_learns_nothing_and_calls_no_llm():
    llm = FakeLLM()
    empty = select_cohort({})
    assert await ci._learn_titles(llm, empty) == ""
    assert llm.calls == []


# ── Script playbook over FULL transcripts ────────────────────────────────────

def _long_transcript(video_id, word):
    segs = [Segment(start=float(i * 3), text=f"{word}{i}", duration=3.0) for i in range(3000)]
    return Transcript(
        video_id=video_id,
        text=" ".join(s.text for s in segs),
        source="captions",
        segments=tuple(segs),
    )


async def test_script_digest_sees_the_end_of_the_video(monkeypatch):
    """With the old 3,500-char cut, the payoff and CTA — the part that actually
    separates a breakout from its channel's baseline — never reached the model."""
    cohort = _cohort_with_controls()
    monkeypatch.setattr(ci, "_fetch_transcript",
                        lambda vid, duration_minutes=0.0: _long_transcript(vid, "w"))
    llm = FakeLLM()
    playbook, notes = await ci._learn_scripts(llm, cohort, _by_id(cohort))
    assert playbook == "PLAYBOOK"
    digest_prompts = [c["user"] for c in llm.calls if c["system"] == ci._DIGEST_SYS]
    assert digest_prompts, "no per-video digest was produced"
    assert any("w2999" in p for p in digest_prompts)  # the tail made it in
    assert notes == []


async def test_script_synthesis_receives_both_winner_and_control_digests(monkeypatch):
    cohort = _cohort_with_controls()
    monkeypatch.setattr(ci, "_fetch_transcript",
                        lambda vid, duration_minutes=0.0: Transcript(
                            video_id=vid, text=f"transcript of {vid}", source="captions"))
    llm = FakeLLM()
    await ci._learn_scripts(llm, cohort, _by_id(cohort))
    synthesis = [c["user"] for c in llm.calls if c["system"] == ci._SCRIPT_SYS][0]
    assert "### WINNER" in synthesis
    assert "### CONTROL" in synthesis


async def test_missing_transcripts_are_reported_not_silently_dropped(monkeypatch):
    """A three-video sample that quietly became a one-video sample used to look
    exactly like a strong signal."""
    cohort = _cohort_with_controls()

    def _fetch(vid, duration_minutes=0.0):
        if vid == "win":
            return Transcript(video_id=vid, text="winner words", source="captions")
        return Transcript(video_id=vid, note="captions unavailable: TranscriptsDisabled")

    monkeypatch.setattr(ci, "_fetch_transcript", _fetch)
    llm = FakeLLM()
    playbook, notes = await ci._learn_scripts(llm, cohort, _by_id(cohort))
    assert any("no transcript" in n for n in notes)
    assert any("winner-only" in n for n in notes)
    assert playbook.startswith("[UNCONTROLLED")


async def test_no_usable_winner_transcript_produces_no_playbook(monkeypatch):
    cohort = _cohort_with_controls()
    monkeypatch.setattr(ci, "_fetch_transcript",
                        lambda vid, duration_minutes=0.0: Transcript(video_id=vid, note="none"))
    llm = FakeLLM()
    playbook, notes = await ci._learn_scripts(llm, cohort, _by_id(cohort))
    assert playbook == ""
    assert any("no winner transcript" in n for n in notes)


async def test_over_long_transcript_declares_what_it_dropped(monkeypatch):
    """Bounded context is fine. Pretending the bound does not exist is not."""
    cohort = _cohort_with_controls()
    huge = Transcript(video_id="win", text="x" * (ci.TRANSCRIPT_CHUNK_CHARS * 10),
                      source="captions")
    llm = FakeLLM()
    digest = await ci._digest_video(llm, "WINNER", "t", huge)
    assert digest.startswith("### WINNER")
    assert "were not" in llm.calls[0]["user"]  # the dropped-parts note


# ── The view-sorted path still exists, but only where it is honest ───────────

def test_view_sorted_helper_is_documented_as_not_for_learning():
    doc = ci._all_competitor_videos.__doc__ or ""
    assert "NOT for learning" in doc


def test_old_biased_entry_point_is_gone():
    """`_top_competitor_videos` was the bug's front door. It must not come back
    by habit — any caller has to choose the cohort or the honest flat pool."""
    assert not hasattr(ci, "_top_competitor_videos")


@pytest.mark.parametrize("group", ["winners", "controls"])
def test_thumbnail_urls_are_resolved_per_group(group):
    cohort = _cohort_with_controls()
    by_id = {r.video_id: _v(r.video_id, 1) for r in cohort.winners + cohort.controls}
    winner_urls, control_urls = ci._thumb_urls(cohort, by_id)
    picked = winner_urls if group == "winners" else control_urls
    assert picked and all(u.startswith("https://img/") for u in picked)
