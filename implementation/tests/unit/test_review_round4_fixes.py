"""Round-four review findings, pinned.

Every one is the same shape as the rounds before it: a module that is correct in
isolation and wired so its answer changes nothing — or, worse, wired so it
changes something for the worse.

  1. `av_forensics` measured OUR renders and never a competitor's, while the
     competitor pipeline's own docstring said "no frames are fetched" — so §5,
     the review's largest gap, was closed on the half that does not matter for
     learning.
  2. The production router named modes it cannot produce, and a 0.75-confidence
     keyword match could rewrite a considered storyboard cell into "AI picture
     of a chart" — which the image providers themselves warn is unreadable.
  3. `clickbait.py` read the competitor playbook by bare niche, with no scope
     chain, no gate, and `except Exception: pass` — §4.2's failure still live on
     the packaging path after the writer had been fixed.
  4. `depicts_real_events` was never passed, so the AI-disclosure branch was
     dead code.
"""

from __future__ import annotations

import json

import pytest

from omnicast.media.production_router import (
    APPROXIMATED_MODES,
    INFOGRAPHIC,
    RENDERED_MODES,
    STOCK,
    route_scene,
    route_storyboard,
    summarise,
)

CAPS = {"screen_capture"}


# ── 2. modes that are only approximated must say so, and must not override ──

def test_a_mode_with_no_renderer_is_marked_as_approximated():
    route = route_scene(0, "Retirement costs rose 42% in a decade",
                        capabilities=CAPS)
    assert route.mode == INFOGRAPHIC
    assert route.is_rendered_as_itself is False
    assert route.approximation_gap
    assert any("approximated" in n for n in route.notes)


def test_a_mode_that_really_is_produced_that_way_is_not_flagged():
    route = route_scene(0, "A city street at dusk, people walking",
                        capabilities=CAPS)
    assert route.mode == STOCK
    assert route.is_rendered_as_itself is True
    assert route.approximation_gap == ""


def test_every_approximated_mode_explains_what_is_missing():
    for mode, reason in APPROXIMATED_MODES.items():
        assert mode not in RENDERED_MODES
        assert reason and len(reason) > 20


def test_the_summary_counts_approximations_separately_from_substitutions():
    """A substitution changed the mode; an approximation kept the mode and
    changed how it gets made. Collapsing them hides the second one."""
    report = summarise(route_storyboard([
        {"narration": "Retirement costs rose 42% in a decade"},
        {"narration": "A city street at dusk, people walking"},
    ], capabilities=CAPS))
    assert report["approximated_count"] == 1
    assert report["substituted_count"] == 0
    assert "not a production-mode system" in report["approximation_note"]


def test_the_render_caller_only_overrides_modes_it_can_actually_render():
    """The dangerous case: a scene with a number is classified INFOGRAPHIC at
    0.75 confidence, and the old caller rewrote the storyboard cell to
    `generated_image` — an AI picture of a chart, which is worse than whatever
    the storyboard had chosen."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "render_real_video.py"
              ).read_text(encoding="utf-8")
    assert "_route.is_rendered_as_itself" in source
    assert "depicts_real_events=_real" in source


# ── 4. the disclosure branch must be reachable ──────────────────────────────

def test_disclosure_is_produced_when_the_caller_says_the_events_are_real():
    routes = route_storyboard([{"narration": "In 1348 the ships reached the harbour"}],
                              capabilities=CAPS, depicts_real_events=True)
    assert routes[0].requires_disclosure is True
    assert summarise(routes)["requires_disclosure"] is True


def test_the_default_is_still_no_claim():
    routes = route_storyboard([{"narration": "In 1348 the ships reached the harbour"}],
                              capabilities=CAPS)
    assert routes[0].requires_disclosure is False


# ── 3. packaging must use the same scope chain and gate as the writer ───────

def test_packaging_walks_the_scope_chain_instead_of_reading_the_niche_row():
    """A retirement channel for 65-year-olds could dress its thumbnails from a
    25-year-old audience's playbook, and nothing said so."""
    import clickbait
    from omnicast.analytics.intel_scope import resolve_scoped_playbook

    tried: list[str] = []

    def _load(scope, **kwargs):
        tried.append(scope)
        return None

    class _Channel:
        channel_id = "fin_retirement_us"
        niche = "finance"
        market = "us"
        intel_archetype = ""
        audience_segment = "55plus"
        content_format = "longform"

    resolve_scoped_playbook(_Channel(), "thumbnail_playbook", load=_load)
    assert tried[0].startswith("finance|fin_retirement_us|55plus|longform")
    assert tried[-1] == "finance"
    assert clickbait._scoped_playbook is not None


def test_packaging_refuses_an_ungated_row(monkeypatch):
    """The row must pass `intel_gate`: uncontrolled, stale or legacy artifacts
    are refused for packaging exactly as they are for the writer."""
    from omnicast.analytics.intel_scope import resolve_scoped_playbook

    class _Channel:
        channel_id = "ch"
        niche = "finance"
        market = "us"
        intel_archetype = ""
        audience_segment = ""
        content_format = ""

    class _LegacyRow:
        title_playbook = thumbnail_playbook = script_playbook = "OLD PLAYBOOK"
        cohort_meta = "{}"          # no research_run_id -> legacy

    text, decision = resolve_scoped_playbook(
        _Channel(), "thumbnail_playbook", load=lambda scope, **kw: _LegacyRow())
    assert text == ""
    assert decision.status != "ok"


def test_packaging_reports_the_level_that_answered(monkeypatch):
    from omnicast.analytics.intel_scope import resolve_scoped_playbook

    class _Channel:
        channel_id = "ch"
        niche = "finance"
        market = "us"
        intel_archetype = ""
        audience_segment = "55plus"
        content_format = "longform"

    class _Row:
        title_playbook = thumbnail_playbook = script_playbook = "NICHE WIDE"
        cohort_meta = json.dumps({"research_run_id": "r1", "is_comparable": True,
                                  "generated_at": "2099-01-01T00:00:00+00:00"})

    _, decision = resolve_scoped_playbook(
        _Channel(), "thumbnail_playbook",
        load=lambda scope, **kw: _Row() if scope == "finance" else None)
    assert decision.scope_level == "niche"


def test_clickbait_no_longer_swallows_every_exception():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "clickbait.py"
              ).read_text(encoding="utf-8")
    # The CALL is gone (only the comment explaining why it went remains).
    assert "_vdb.get_competitor_intel(" not in source
    assert "except Exception:\n            pass" not in source
    assert "resolve_scoped_playbook" in source


# ── 1. competitor forensics must have a production caller ───────────────────

def _set_forensics(monkeypatch, enabled: bool) -> None:
    """Flip the flag through SETTINGS, which is how production reads it.

    Round five: the flag was read straight from `os.environ`, but this project
    configures through pydantic `.env` + `Settings` and the field was not
    declared — so a `.env` line was ignored while looking exactly like it
    worked. It is a declared setting now, and `get_settings` is `lru_cache`d,
    so a test must clear the cache rather than just setting an env var."""
    from omnicast.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("OMNICAST_COMPETITOR_FORENSICS", "1" if enabled else "0")
    settings_module.get_settings.cache_clear()


def test_the_flag_is_a_declared_setting_not_a_loose_env_var():
    from omnicast.config.settings import Settings

    assert "omnicast_competitor_forensics" in Settings.model_fields
    assert Settings.model_fields["omnicast_competitor_forensics"].default is False


def test_competitor_forensics_is_off_by_default_and_says_so(monkeypatch):
    from omnicast.analytics import av_fetch

    _set_forensics(monkeypatch, False)
    assert av_fetch.forensics_enabled() is False
    assert av_fetch.measure_competitor_video("abc") is None


def test_the_flag_turns_it_on(monkeypatch):
    from omnicast.analytics import av_fetch

    _set_forensics(monkeypatch, True)
    assert av_fetch.forensics_enabled() is True


def test_the_download_has_a_real_wall_clock_timeout():
    """`socket_timeout` bounds ONE network read. A server dripping a byte at a
    time never trips it, and the docstring claimed a hard timeout — only a
    subprocess can be killed."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2]
              / "src/omnicast/analytics/av_fetch.py").read_text(encoding="utf-8")
    assert "subprocess.run" in source
    assert "timeout=DOWNLOAD_TIMEOUT_SECONDS" in source
    assert "TimeoutExpired" in source


def test_a_video_that_is_too_long_is_skipped_rather_than_downloaded(monkeypatch):
    from omnicast.analytics import av_fetch

    _set_forensics(monkeypatch, True)
    called: list[str] = []
    monkeypatch.setattr(av_fetch, "download_video",
                        lambda vid, workdir: called.append(vid) or "")
    assert av_fetch.measure_competitor_video(
        "abc", duration_minutes=av_fetch.MAX_DURATION_MINUTES + 1) is None
    assert called == []


@pytest.mark.asyncio
async def test_the_blueprint_stage_says_when_forensics_is_off(monkeypatch):
    from omnicast.analytics import av_fetch
    from omnicast.analytics import competitor_intel as ci
    from omnicast.analytics.transcript import Segment, Transcript

    _set_forensics(monkeypatch, False)
    rows = [{"video_id": "w1", "title": "5 retirement mistakes",
             "duration_minutes": 11.0,
             "transcript": Transcript(video_id="w1", text="hello there",
                                      source="test",
                                      segments=(Segment(0.0, "hello there", 2.0),))}]
    payload, notes = await ci._measure_production("finance", rows)
    assert payload is not None
    assert any("forensics is OFF" in n for n in notes)
    assert payload["art_style"] == "unknown"


@pytest.mark.asyncio
async def test_measured_frames_reach_the_competitor_blueprint(monkeypatch):
    """The whole point: with the flag on, a competitor blueprint carries real
    shot rhythm and colour instead of `unknown`."""
    from omnicast.analytics import av_fetch
    from omnicast.analytics import competitor_intel as ci
    from omnicast.analytics.transcript import Segment, Transcript

    _set_forensics(monkeypatch, True)
    monkeypatch.setattr(av_fetch, "measure_competitor_video",
                        lambda video_id, **kw: {
                            "field_status": {"shots": "measured"},
                            "colour_mood": "cold",
                            "shot_count": 12,
                            "median_shot_seconds": 3.5,
                            "cuts_per_minute": 17.0,
                            "motion_mix": {"static": 0.6, "drift": 0.4},
                            "transition_mix": {"cut": 10, "dissolve": 1},
                            "notes": [],
                        })
    rows = [{"video_id": "w1", "title": "5 retirement mistakes",
             "duration_minutes": 11.0,
             "transcript": Transcript(video_id="w1", text="hello there",
                                      source="test",
                                      segments=(Segment(0.0, "hello there", 2.0),))}]
    payload, _notes = await ci._measure_production("finance", rows)
    assert payload["color_mood"] == "cold"
    low, high = payload["pacing_scene_duration"]
    assert low < 3.5 < high
    # ...and it is still honest about the fields frames alone cannot support.
    assert payload["art_style"] == "unknown"
    assert {"art_style", "b_roll_ratio", "text_overlay_freq"} <= set(
        payload["assumed_fields"])


@pytest.mark.asyncio
async def test_a_failed_download_costs_that_video_and_is_recorded(monkeypatch):
    from omnicast.analytics import av_fetch
    from omnicast.analytics import competitor_intel as ci
    from omnicast.analytics.transcript import Segment, Transcript

    _set_forensics(monkeypatch, True)
    monkeypatch.setattr(av_fetch, "measure_competitor_video",
                        lambda video_id, **kw: None)
    rows = [{"video_id": "w1", "title": "5 retirement mistakes",
             "duration_minutes": 11.0,
             "transcript": Transcript(video_id="w1", text="hello there",
                                      source="test",
                                      segments=(Segment(0.0, "hello there", 2.0),))}]
    payload, notes = await ci._measure_production("finance", rows)
    assert payload is not None
    assert any("no frames measured" in n for n in notes)


# ── round five: fail-open, missing pillar scope, phantom capability ─────────

def _legacy_row():
    class _Row:
        title_playbook = thumbnail_playbook = script_playbook = "OLD PLAYBOOK"
        cohort_meta = "{}"          # no research_run_id -> legacy -> refused
    return _Row()


def test_a_required_channel_stops_instead_of_packaging_without_intel(monkeypatch):
    """THE FAIL-OPEN. `_scoped_playbook` caught `CompetitorIntelRequired` along
    with everything else and returned `('', None)`, so a channel that declared
    it would rather stop than ship unverified packaging kept rendering — the
    single thing the declaration exists to prevent."""
    import clickbait
    from omnicast.agents import writer as writer_mod
    from omnicast.analytics.intel_gate import CompetitorIntelRequired

    monkeypatch.setattr(writer_mod, "_load_competitor_intel",
                        lambda scope, **kw: _legacy_row())
    meta = {"channel_id": "ch", "niche": "finance", "market": "us",
            "competitor_intel_required": True}
    with pytest.raises(CompetitorIntelRequired):
        clickbait._scoped_playbook(meta, "thumbnail_playbook")


def test_the_failure_survives_the_outer_handler_in_generate_clickbait(monkeypatch):
    """The regression the reviewer asked for: through the real entry point.

    An `except Exception: return None` one frame out would turn the raise back
    into a no-op, so this asserts the exception escapes `generate_clickbait`
    itself."""
    import clickbait
    from omnicast.agents import writer as writer_mod
    from omnicast.analytics.intel_gate import CompetitorIntelRequired

    monkeypatch.setattr(writer_mod, "_load_competitor_intel",
                        lambda scope, **kw: _legacy_row())
    meta = {"channel_id": "ch", "niche": "finance", "market": "us",
            "competitor_intel_required": True}
    with pytest.raises(CompetitorIntelRequired):
        clickbait.generate_clickbait("A script about annuities.", meta)


def test_a_channel_that_did_not_ask_to_fail_closed_still_degrades(monkeypatch):
    """Fail-closed is opt-in. Everything else keeps packaging without the
    playbook rather than stopping."""
    import clickbait
    from omnicast.agents import writer as writer_mod

    monkeypatch.setattr(writer_mod, "_load_competitor_intel",
                        lambda scope, **kw: _legacy_row())
    text, decision = clickbait._scoped_playbook(
        {"channel_id": "ch", "niche": "finance"}, "thumbnail_playbook")
    assert text == ""
    assert decision is not None and decision.status != "ok"


def test_packaging_is_scoped_by_content_pillar(monkeypatch):
    """Annuities and social security shared one channel-wide playbook: the
    packaging path scoped four dimensions and left the fifth blank."""
    import clickbait
    from omnicast.agents import writer as writer_mod

    tried: list[str] = []
    monkeypatch.setattr(writer_mod, "_load_competitor_intel",
                        lambda scope, **kw: tried.append(scope) or None)

    meta = {
        "channel_id": "fin_retirement_us", "niche": "finance", "market": "us",
        "audience_segment": "55plus", "content_format": "longform",
        "content_pillars": [
            {"id": "annuities", "keywords": ["annuity", "annuities"]},
            {"id": "social_security", "keywords": ["medicare", "social security"]},
        ],
    }
    clickbait._scoped_playbook(
        meta, "thumbnail_playbook",
        clickbait._packaging_pillar(meta, "How annuities really work"))
    annuity_key = tried[0]

    tried.clear()
    clickbait._scoped_playbook(
        meta, "thumbnail_playbook",
        clickbait._packaging_pillar(meta, "What Medicare will not cover"))
    social_key = tried[0]

    assert annuity_key.endswith("annuities")
    assert social_key.endswith("social_security")
    assert annuity_key != social_key


def test_an_unclassifiable_script_widens_the_key_rather_than_inventing_a_pillar():
    import clickbait

    meta = {"channel_id": "ch", "niche": "finance",
            "content_pillars": [{"id": "annuities", "keywords": ["annuity"]}]}
    assert clickbait._packaging_pillar(meta, "The best gaming laptop") == ""
    assert clickbait._packaging_pillar({}, "anything") == ""


def test_a_phantom_capability_does_not_reach_the_router():
    from omnicast.media.production_router import capabilities_from_channel

    channel = type("C", (), {"supported_production": ["screen_capture"]})()
    assert "screen_capture" not in capabilities_from_channel(channel)


@pytest.mark.asyncio
async def test_the_topic_scorer_vetoes_a_topic_that_needs_screen_capture():
    """ROUND SIX. The previous version of this test was named "does not reach
    the topic scorer" and never ran the scorer — it asserted on the router,
    which the scorer does not call. The scorer reads
    `ChannelProfile.to_stack_profile()`, and `screen_capture` was missing from
    `PIPELINE_UNSUPPORTED_PRODUCTION`, so the veto set came out EMPTY and a
    software tutorial scored as fully producible at the moment the system
    decides what to make."""
    from omnicast.config.channel import (
        PIPELINE_UNSUPPORTED_PRODUCTION,
        ChannelProfile,
    )
    from omnicast.discovery.models import TopicRawData
    from omnicast.discovery.scorer import TopicScorer
    from omnicast.models.enums import Market, Niche, TopicSource

    assert "screen_capture" in PIPELINE_UNSUPPORTED_PRODUCTION

    channel = ChannelProfile(channel_id="ch", name="C", niche=Niche.TECH,
                             market=Market.US)
    profile = channel.to_stack_profile()
    assert "screen_capture" in profile.unsupported_requirements

    topic = TopicRawData(
        title="Step-by-step in the dashboard", source=TopicSource.YOUTUBE_COMPETITOR,
        niche=Niche.TECH, market=Market.US,
        raw_metrics={"production_requirements": ["screen_capture"],
                     "duration_minutes": 10.0})
    scored = await TopicScorer(stack_profile=profile, scoring_mode="v2").score(topic)
    assert scored.stack_fit == 0.0
    assert any("screen_capture" in note for note in scored.score_notes)


@pytest.mark.asyncio
async def test_a_channel_that_really_has_a_capture_step_can_declare_it():
    """The veto is engine-wide, not a law: a channel with a capture rig says so
    and gets its capability back."""
    from omnicast.config.channel import ChannelProfile
    from omnicast.models.enums import Market, Niche

    channel = ChannelProfile(channel_id="ch", name="C", niche=Niche.TECH,
                             market=Market.US,
                             supported_production=["screen_capture"])
    assert "screen_capture" not in channel.to_stack_profile().unsupported_requirements


# ── round six: the renderer must not swallow the fail-closed error ──────────

def test_the_renderer_re_raises_the_required_intel_failure():
    """`generate_clickbait` re-raised it and `render_real_video` caught it again
    with `except Exception`, logged a warning and printed DONE — the
    declaration went back to sleep one frame further out."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "render_real_video.py"
              ).read_text(encoding="utf-8")
    assert "except CompetitorIntelRequired as exc:" in source
    blocked = source.index("except CompetitorIntelRequired as exc:")

    # Order matters more than presence: a narrow clause placed AFTER
    # `except Exception` never runs. Python would not even accept it, but the
    # broad clause guarding the same `try` is the one that has to come second.
    broad = source.index("except Exception as exc:", blocked)
    handler = source[blocked:broad]
    assert "raise" in handler, "the clause catches it and lets the render continue"
    assert "BLOCKED" in handler
    assert "publishable=False" in handler
    assert "packaging_blocked" in handler

    # And nothing between the two prints a success line for this path.
    assert 'print(f"[5/5] DONE' not in handler


def test_the_packaging_pillar_comes_from_the_brief_not_from_the_script(monkeypatch):
    """ROUND SIX. Packaging re-derived the pillar by classifying the first 2000
    characters of the script, so a video the SCORER had already filed under
    `annuities` could take the `social_security` thumbnail playbook — the two
    halves of one system disagreeing about what the video is.

    This runs `generate_clickbait` itself. The LLM call afterwards fails with no
    key and returns None; what is under test is which scope key the playbook
    lookup asked for, which happens before that."""
    import clickbait

    meta = {"channel_id": "ch", "niche": "finance", "market": "us",
            "content_pillars": [
                {"id": "annuities", "keywords": ["annuity", "annuities"]},
                {"id": "social_security",
                 "keywords": ["medicare", "social security"]},
            ]}
    script = "Medicare and social security explained. Medicare again."

    # Left to itself the classifier reads the script and answers social_security.
    assert clickbait._packaging_pillar(meta, script) == "social_security"

    asked: list[str] = []
    monkeypatch.setattr(clickbait, "_scoped_playbook",
                        lambda m, a, p="": asked.append(p) or ("", None))
    clickbait.generate_clickbait(script, meta, pillar_id="annuities")

    assert asked, "generate_clickbait never looked a playbook up"
    assert set(asked) == {"annuities"}, (
        f"packaging used {set(asked)} while the brief said annuities")


def test_without_a_brief_pillar_the_classifier_still_covers_old_callers(monkeypatch):
    import clickbait

    meta = {"channel_id": "ch", "niche": "finance", "market": "us",
            "content_pillars": [
                {"id": "annuities", "keywords": ["annuity", "annuities"]},
                {"id": "social_security",
                 "keywords": ["medicare", "social security"]},
            ]}
    asked: list[str] = []
    monkeypatch.setattr(clickbait, "_scoped_playbook",
                        lambda m, a, p="": asked.append(p) or ("", None))
    clickbait.generate_clickbait(
        "Medicare and social security explained. Medicare again.", meta)
    assert set(asked) == {"social_security"}


def test_the_renderer_passes_the_brief_pillar_down():
    """The call site is the whole point: a `pillar_id` parameter nothing fills
    is the same bug with a wider signature."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "render_real_video.py"
              ).read_text(encoding="utf-8")
    assert "pillar_id=_pillar_ssot" in source
    assert '"pillar_id"' in source


def test_the_script_classifier_is_only_a_labelled_fallback(monkeypatch):
    import clickbait
    from omnicast.agents import writer as writer_mod

    tried: list[str] = []
    monkeypatch.setattr(writer_mod, "_load_competitor_intel",
                        lambda scope, **kw: tried.append(scope) or None)
    meta = {"channel_id": "ch", "niche": "finance", "market": "us",
            "content_pillars": [{"id": "annuities", "keywords": ["annuity"]},
                                {"id": "social_security", "keywords": ["medicare"]}]}
    clickbait._scoped_playbook(meta, "thumbnail_playbook", "annuities")
    assert tried[0].endswith("annuities")
