"""Content pillars must survive the WHOLE pipeline, not just the scorer.

Found in review: the scorer classified a pillar in order to score
repeatability, then dropped it. No brief carried it, the learner wrote with
`scope_key(channel)` and no pillar, so the pillar dimension of every scope key
was `*` — end to end, on every path. §4.2's finest scope level existed in the
key format and nowhere in the data.

These tests follow one pillar from the scorer to the vault key and back to the
writer, and pin the property the brief actually asks for: two pillars on one
channel do not share a playbook.
"""

from __future__ import annotations

import pytest

from omnicast.agents import writer as writer_mod
from omnicast.analytics.intel_scope import fallback_chain, scope_key
from omnicast.config.channel import ChannelProfile
from omnicast.discovery.brief_generator import BriefGenerator
from omnicast.discovery.models import TopicRawData
from omnicast.discovery.scorer import TopicScorer
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.models.script import TopicBrief

PILLAR_CONFIG = [
    {"id": "annuities", "name": "Annuities", "keywords": ["annuity", "annuities"]},
    {"id": "social_security", "name": "Social Security",
     "keywords": ["social security", "medicare"]},
]


def _channel(**overrides) -> ChannelProfile:
    data = dict(
        channel_id="fin_retirement_us", name="Smart Retirement",
        niche=Niche.FINANCE, market=Market.US,
        audience_segment="55plus_preretiree", content_format="longform_narration",
        content_pillars=PILLAR_CONFIG,
    )
    data.update(overrides)
    return ChannelProfile(**data)


def _topic(title: str) -> TopicRawData:
    return TopicRawData(title=title, source=TopicSource.YOUTUBE_COMPETITOR,
                        niche=Niche.FINANCE, market=Market.US,
                        raw_metrics={"outlier_ratio": 4.0})


# ── 1. the scorer's answer leaves the scorer ────────────────────────────────

@pytest.mark.asyncio
async def test_the_scorer_reports_the_pillar_it_classified():
    from omnicast.analytics.pillars import load_pillars

    scorer = TopicScorer(pillars=load_pillars(PILLAR_CONFIG))
    scored = await scorer.score(_topic("How annuities really work"))
    assert scored.pillar_id == "annuities"


@pytest.mark.asyncio
async def test_an_unclassified_topic_carries_no_pillar_rather_than_a_state_name():
    """`unclassified` and `unconfigured` are states, not pillars. Either one in
    a scope key would invent a bucket nobody declared."""
    from omnicast.analytics.pillars import load_pillars

    scorer = TopicScorer(pillars=load_pillars(PILLAR_CONFIG))
    scored = await scorer.score(_topic("The best gaming laptop"))
    assert scored.pillar_id == ""

    unconfigured = await TopicScorer().score(_topic("How annuities really work"))
    assert unconfigured.pillar_id == ""


# ── 2. the brief carries it ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_brief_generator_carries_the_scorers_pillar_into_the_brief():
    from omnicast.analytics.pillars import load_pillars

    channel = _channel()
    scorer = TopicScorer(pillars=load_pillars(PILLAR_CONFIG))
    scored = await scorer.score(_topic("How annuities really work"))
    brief = BriefGenerator.generate(scored, channel.brand_voice, channel)
    assert brief.pillar_id == "annuities"


def test_a_builder_without_a_scored_topic_classifies_from_the_title():
    """`ChannelArchitect` and the API path build briefs with no ScoredTopic in
    hand. They must still land on the same pillar, via the same deterministic
    function, or two paths disagree about which playbook a channel reads."""
    channel = _channel()
    fields = TopicBrief.scope_fields_from_channel(
        channel, title="What Medicare will not cover")
    assert fields["pillar_id"] == "social_security"


def test_the_scorers_answer_wins_over_re_classification():
    channel = _channel()
    fields = TopicBrief.scope_fields_from_channel(
        channel, title="How annuities really work", pillar_id="social_security")
    assert fields["pillar_id"] == "social_security"


# ── 3. the key actually differs, and the writer reaches it ──────────────────

def test_two_pillars_on_one_channel_do_not_share_a_key():
    channel = _channel()
    annuities = scope_key(channel, pillar_id="annuities")
    social = scope_key(channel, pillar_id="social_security")
    channel_wide = scope_key(channel)
    assert len({annuities, social, channel_wide}) == 3


def test_two_pillars_on_one_channel_do_not_share_a_playbook(monkeypatch):
    """The property §4.2 asks for, end to end: the writer for an annuities
    topic must not receive the social-security playbook, and vice versa."""
    channel = _channel()
    vault = {}

    class _Row:
        cohort_meta = "{}"

        def __init__(self, text):
            self.title_playbook = self.thumbnail_playbook = self.script_playbook = text

    for pillar in ("annuities", "social_security"):
        vault[scope_key(channel, pillar_id=pillar)] = _Row(f"PLAYBOOK::{pillar}")
    vault["finance"] = _Row("PLAYBOOK::niche_wide")

    served: list[str] = []

    def _load(scope, **kw):
        row = vault.get(scope)
        if row is not None:
            served.append(row.script_playbook)
        return row

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _load)

    for title, expected in [("How annuities really work", "annuities"),
                            ("What Medicare will not cover", "social_security")]:
        brief = TopicBrief(
            title=title, niche=Niche.FINANCE, market=Market.US,
            channel_id=channel.channel_id,
            **TopicBrief.scope_fields_from_channel(channel, title=title))
        served.clear()
        writer_mod.resolve_competitor_playbook(brief)
        assert served == [f"PLAYBOOK::{expected}"]


def test_a_topic_in_an_unlearned_pillar_falls_back_to_the_channel_wide_row(monkeypatch):
    """Falling back is correct — a pillar with no run of its own should not lose
    the channel's playbook. Doing it SILENTLY is what §4.2 objects to, and the
    level is logged."""
    channel = _channel()
    channel_wide_key = scope_key(channel)

    class _Row:
        cohort_meta = "{}"
        title_playbook = thumbnail_playbook = script_playbook = "CHANNEL WIDE"

    tried: list[str] = []

    def _load(scope, **kw):
        tried.append(scope)
        return _Row() if scope == channel_wide_key else None

    monkeypatch.setattr(writer_mod, "_load_competitor_intel", _load)
    brief = TopicBrief(
        title="How annuities really work", niche=Niche.FINANCE, market=Market.US,
        channel_id=channel.channel_id,
        **TopicBrief.scope_fields_from_channel(
            channel, title="How annuities really work"))
    writer_mod.resolve_competitor_playbook(brief)

    assert tried[0] == scope_key(channel, pillar_id="annuities")
    assert channel_wide_key in tried
    levels = [level for level, key in fallback_chain(brief)]
    assert levels[0] == "exact" and "no_pillar" in levels


# ── 4. the learner writes under the pillar key ──────────────────────────────

@pytest.mark.asyncio
async def test_the_learner_filters_the_corpus_and_writes_the_pillar_key(monkeypatch):
    """Filtering happens BEFORE cohort selection: a median computed over every
    video and then filtered would judge annuity videos against the channel's
    all-topic baseline, which answers a different question."""
    from omnicast.analytics import competitor_intel as ci

    channel = _channel()
    seen_keys: list[str] = []

    videos = {
        "UC1": [
            {"video_id": "a1", "title": "Annuity payouts explained", "views": 90_000,
             "duration_minutes": 12.0, "published_at": "2026-05-01T00:00:00Z"},
            {"video_id": "a2", "title": "Annuity fees to avoid", "views": 9_000,
             "duration_minutes": 12.0, "published_at": "2026-05-03T00:00:00Z"},
            {"video_id": "a3", "title": "Annuity basics", "views": 8_000,
             "duration_minutes": 12.0, "published_at": "2026-05-05T00:00:00Z"},
            {"video_id": "s1", "title": "Medicare traps", "views": 500_000,
             "duration_minutes": 12.0, "published_at": "2026-05-02T00:00:00Z"},
            {"video_id": "s2", "title": "Medicare basics", "views": 8_000,
             "duration_minutes": 12.0, "published_at": "2026-05-04T00:00:00Z"},
            {"video_id": "s3", "title": "Medicare and social security", "views": 7_000,
             "duration_minutes": 12.0, "published_at": "2026-05-06T00:00:00Z"},
        ]
    }

    async def _fake_fetch(channel, api_key, per_channel=30):
        return {cid: [dict(v) for v in group] for cid, group in videos.items()}

    monkeypatch.setattr(ci, "_fetch_competitor_videos", _fake_fetch)

    cohort, _by_id = await ci.build_competitor_cohort(
        channel, "key", video_filter=lambda v: "annuity" in v["title"].lower())
    assert cohort.winners
    assert all("annuity" in w.title.lower() for w in cohort.winners)
    # The huge Medicare video is the channel's real outlier; it must not be in
    # an annuities cohort at all.
    assert "s1" not in [w.video_id for w in cohort.winners]

    seen_keys.append(scope_key(channel, pillar_id="annuities"))
    assert seen_keys[0].endswith("annuities")


def test_a_pillar_that_is_not_declared_is_refused_not_invented():
    """Writing under a pillar nobody declared would create a row the writer can
    never ask for."""
    channel = _channel()
    declared = {p["id"] for p in PILLAR_CONFIG}
    assert "crypto" not in declared
    assert scope_key(channel, pillar_id="annuities") != scope_key(channel)
