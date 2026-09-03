"""P0.1 group 3 — make the capability dimensions actually run.

Three things were scored, documented, unit-tested against hand-built dicts, and
DEAD on every real run:

  * `StackProfile` was never built from a channel, so `TopicScorer()` fell back
    to the neutral 7.5 for every topic — 15 points that could not move;
  * `similar_competitor_videos` was read by `_calc_gap_score` and written by
    nobody;
  * `production_requirements` gated a HARD ZERO and was written by nobody.

Every test below fails if its wiring is removed, and the end-to-end one goes
ChannelProfile -> DiscoveryOrchestrator -> ScoredTopic so that a future refactor
cannot quietly drop the profile again while the scorer's own unit tests stay
green — which is exactly how this got lost the first time.
"""

from __future__ import annotations

import pytest

from omnicast.config.channel import (
    DURATION_BAND_FACTOR,
    PIPELINE_UNSUPPORTED_PRODUCTION,
    ChannelProfile,
)
from omnicast.discovery import shadow_log
from omnicast.discovery.base import BaseScanner
from omnicast.discovery.models import DiscoveryConfig, TopicRawData
from omnicast.discovery.orchestrator import DiscoveryOrchestrator
from omnicast.discovery.scorer import STACK_FIT_NEUTRAL, TopicScorer
from omnicast.discovery.youtube_scanner import YouTubeScanner
from omnicast.models.enums import Market, Niche, TopicSource
from omnicast.shared.production_signals import infer_production_requirements
from omnicast.shared.topic_coverage import MIN_CORPUS_FOR_COVERAGE, coverage_of


def _channel(**overrides) -> ChannelProfile:
    data = dict(
        channel_id="fin_retirement_us",
        name="Smart Retirement",
        niche=Niche.FINANCE,
        market=Market.US,
        target_duration_min=10,
        brand_voice="authoritative",
    )
    data.update(overrides)
    return ChannelProfile(**data)


def _topic(title="The 5 retirement mistakes", *, niche=Niche.FINANCE,
           market=Market.US, description="", **metrics) -> TopicRawData:
    return TopicRawData(
        title=title,
        description=description,
        source=TopicSource.YOUTUBE_COMPETITOR,
        niche=niche,
        market=market,
        raw_metrics=metrics,
    )


# ── StackProfile is derived from configuration that already exists ───────────

def test_an_untouched_channel_file_still_yields_a_real_profile():
    """If a profile only materialised for channels someone hand-annotated, the
    dimension would stay neutral in practice and we would have moved the dead
    code rather than revived it."""
    profile = _channel().to_stack_profile()
    assert profile.is_configured is True
    assert profile.niches == {Niche.FINANCE}
    assert profile.markets == {Market.US}
    low, high = profile.duration_minutes
    assert (low, high) == (10 * DURATION_BAND_FACTOR[0], 10 * DURATION_BAND_FACTOR[1])
    assert "face_cam" in profile.unsupported_requirements


def test_the_engine_wide_limits_apply_without_per_channel_configuration():
    """OmniCast has no camera and no presenter on ANY channel. Requiring each
    channel file to restate that would guarantee some file forgets."""
    profile = _channel().to_stack_profile()
    assert PIPELINE_UNSUPPORTED_PRODUCTION <= profile.unsupported_requirements


def test_a_channel_may_declare_a_capability_it_actually_has():
    profile = _channel(supported_production=["interview"]).to_stack_profile()
    assert "interview" not in profile.unsupported_requirements
    assert "face_cam" in profile.unsupported_requirements


def test_an_explicit_band_wins_over_the_derived_one():
    profile = _channel(production_duration_band_min=(8.0, 12.0)).to_stack_profile()
    assert profile.duration_minutes == (8.0, 12.0)


def test_forbidden_words_do_not_become_topic_vetoes():
    """`forbidden_words` is about wording inside a script. Promoting it to a
    hard topic veto would zero unrelated topics and teach operators to empty
    the list."""
    profile = _channel(forbidden_words=["crazy", "guys"],
                       blocked_topic_keywords=["crypto"]).to_stack_profile()
    assert profile.blocked_keywords == {"crypto"}


def test_unknown_secondary_niche_ids_are_skipped_not_guessed():
    profile = _channel(niches=[{"niche_id": "health"}, {"niche_id": "not_a_niche"}]
                       ).to_stack_profile()
    assert Niche.FINANCE in profile.niches
    assert len(profile.niches) == 2


# ── the wiring: ChannelProfile -> DiscoveryOrchestrator -> ScoredTopic ───────

class _FakeScanner(BaseScanner):
    source = TopicSource.YOUTUBE_COMPETITOR

    def __init__(self, topics):
        super().__init__(DiscoveryConfig(niche=Niche.FINANCE, markets=[Market.US]))
        self._topics = topics

    async def _scan(self):
        return self._topics


def _e2e_topics() -> list[TopicRawData]:
    common = dict(outlier_ratio=3.0, channel_median_views=40_000,
                  engagement_rate=0.05, channel_avg_engagement=0.04)
    return [
        _topic("5 retirement mistakes to avoid", duration_minutes=11.0,
               title_patterns=["number", "warning"], production_requirements=[],
               **common),
        _topic("My reaction to the pension crash", duration_minutes=11.0,
               title_patterns=["statement"],
               production_requirements=["face_cam"], **common),
    ]


@pytest.mark.asyncio
async def test_stack_fit_moves_end_to_end_from_a_channel_profile(monkeypatch):
    """The regression that matters: build the orchestrator the way production
    builds it, and prove the score is no longer a constant."""
    monkeypatch.setattr(shadow_log, "append_rows", lambda rows: None)

    channel = _channel(proven_title_patterns=["number", "how_to"])
    orch = DiscoveryOrchestrator.for_channel(channel)
    # for_channel must also carry the channel itself: BriefGenerator reads
    # per-channel policy from it, and the shadow corpus is keyed by it.
    assert orch.channel is channel
    assert orch.scorer._stack.is_configured is True

    orch.scanners = [_FakeScanner(_e2e_topics())]
    result = await orch.run()
    by_title = {s.raw.title: s for s in result.scored_topics}

    good = by_title["5 retirement mistakes to avoid"]
    blocked = by_title["My reaction to the pension crash"]

    # On-niche, on-market, in-band runtime, proven format -> full marks.
    assert good.stack_fit == 15.0
    # Needs a face on camera -> hard zero, with the reason attached.
    assert blocked.stack_fit == 0.0
    assert any("face_cam" in note for note in blocked.score_notes)
    # And neither is the neutral value the unwired scorer always produced.
    assert good.stack_fit != STACK_FIT_NEUTRAL
    assert blocked.stack_fit != STACK_FIT_NEUTRAL


@pytest.mark.asyncio
async def test_without_the_wiring_both_topics_score_identically():
    """The control for the test above: same topics, scorer built the way
    `for_channel` used to build it. If this ever stops being 7.5/7.5, the test
    above is passing for a reason other than the wiring."""
    scorer = TopicScorer()
    scored = await scorer.score_batch(_e2e_topics())
    assert {s.stack_fit for s in scored} == {STACK_FIT_NEUTRAL}


@pytest.mark.asyncio
async def test_stack_fit_only_reaches_the_deciding_score_under_v2():
    """Shadow mode is still the default, so stack fit shows up in
    `total_score_v2` and NOT in the number that decides. Anyone reading
    `total_score` to check their profile took effect would conclude it had
    not."""
    topics = _e2e_topics()
    profile = _channel(proven_title_patterns=["number"]).to_stack_profile()

    shadow = await TopicScorer(stack_profile=profile,
                               scoring_mode="shadow").score_batch(topics)
    live = await TopicScorer(stack_profile=profile,
                             scoring_mode="v2").score_batch(topics)

    shadow_blocked = next(s for s in shadow if s.stack_fit == 0.0)
    live_blocked = next(s for s in live if s.stack_fit == 0.0)
    assert shadow_blocked.scoring_version == "v1"
    assert shadow_blocked.total_score == shadow_blocked.total_score_v1
    assert live_blocked.scoring_version == "v2"
    assert live_blocked.total_score == live_blocked.total_score_v2


# ── the scanner now writes the two supply signals ────────────────────────────

def _video(vid, title, views, *, description="", published="2026-05-01T00:00:00Z"):
    likes = max(1, views // 100)
    comments = max(0, views // 500)
    return {
        "video_id": vid,
        "title": title,
        "description": description,
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_rate": round((likes + comments) / views, 4),
        "duration_minutes": 10.0,
        "published_at": published,
        "tags": [],
    }


def test_scanner_writes_production_requirements_the_scorer_vetoes_on():
    outliers = [_topic("Interview with a retired teacher", video_id="v1")]
    YouTubeScanner._annotate_supply_signals(outliers, [_video("v1", "x", 1)])
    assert outliers[0].raw_metrics["production_requirements"] == ["interview"]


def test_coverage_is_withheld_on_a_corpus_too_thin_to_support_it():
    """"No similar video found" after eleven videos says nothing about the
    market. Reporting 0 would hand out the full uncovered-topic bonus."""
    corpus = [_video(f"v{i}", f"unrelated topic {i}", 1000) for i in range(11)]
    outliers = [_topic("The 5 retirement mistakes", video_id="v0")]
    YouTubeScanner._annotate_supply_signals(outliers, corpus)
    metrics = outliers[0].raw_metrics
    assert "similar_competitor_videos" not in metrics
    assert "corpus" in metrics["coverage_note"]
    assert metrics["coverage_corpus_size"] == 11


def test_coverage_is_counted_once_the_corpus_is_large_enough():
    corpus = [_video(f"v{i}", f"completely unrelated subject {i}", 1000)
              for i in range(MIN_CORPUS_FOR_COVERAGE)]
    corpus += [
        _video("dup1", "Retirement mistakes that cost you money", 1000),
        _video("dup2", "Avoid these retirement mistakes", 1000),
    ]
    outliers = [_topic("The retirement mistakes nobody warns you about",
                       video_id="self")]
    YouTubeScanner._annotate_supply_signals(outliers, corpus)
    assert outliers[0].raw_metrics["similar_competitor_videos"] == 2


def test_a_video_does_not_count_as_covering_itself():
    corpus = [_video(f"v{i}", f"unrelated subject number {i}", 1000)
              for i in range(MIN_CORPUS_FOR_COVERAGE)]
    corpus.append(_video("self", "The retirement mistakes nobody warns you about", 1000))
    outliers = [_topic("The retirement mistakes nobody warns you about",
                       video_id="self")]
    YouTubeScanner._annotate_supply_signals(outliers, corpus)
    assert outliers[0].raw_metrics["similar_competitor_videos"] == 0


def test_the_supply_signals_actually_move_the_gap_score():
    """Writing the keys is only half the job — they have to reach the score."""
    base = dict(outlier_ratio=3.0, channel_median_views=40_000,
                engagement_rate=0.04, channel_avg_engagement=0.04)
    scorer = TopicScorer()
    empty_space = scorer._calc_gap_score(_topic(similar_competitor_videos=0, **base))
    crowded = scorer._calc_gap_score(_topic(similar_competitor_videos=9, **base))
    unknown = scorer._calc_gap_score(_topic(**base))
    assert empty_space > unknown > crowded


# ── false positives are expensive, so they get their own tests ───────────────

@pytest.mark.parametrize("title", [
    "How to live on $2,000 a month in retirement",   # 'live'
    "The truth about interviews for a job at 60",    # 'interviews' as a subject
    "Why your reaction time slows after 70",         # 'reaction' as a subject
])
def test_ambiguous_words_do_not_trigger_a_hard_veto(title):
    """A hit here is a hard zero. An operator who watches good topics vetoed
    for a word in a sentence stops configuring the feature entirely."""
    assert infer_production_requirements(title) == set()


@pytest.mark.parametrize("title,tag", [
    ("Unboxing the new retirement planner", "in_person_demo"),
    ("My reaction to the 2026 pension reform", "face_cam"),
    ("Livestream: markets open", "live_footage"),
    ("We visited the biggest pension fund", "on_location"),
    ("Interview with a fund manager", "interview"),
])
def test_real_signals_are_still_detected(title, tag):
    assert tag in infer_production_requirements(title)


def test_coverage_helper_returns_none_not_zero_when_it_cannot_answer():
    assert coverage_of("anything", ["a", "b"]) is None
    assert coverage_of("anything at all", [""] * MIN_CORPUS_FOR_COVERAGE) == 0
