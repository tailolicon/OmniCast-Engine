"""Tests for binary eval functions."""

import pytest

from omnicast.agents.evals import (
    eval_hook_under_15_words,
    eval_no_ai_cliches,
    eval_has_pattern_interrupt,
    eval_intro_under_30s,
    eval_segment_under_90s,
    eval_has_outro,
    eval_word_count_reasonable,
    run_binary_evals,
    WRITER_EVALS,
    AI_CLICHE_LIST,
)
from omnicast.models.script import ScriptDraft, ScriptSegment


@pytest.fixture
def good_draft() -> ScriptDraft:
    """Draft that passes all evals."""
    return ScriptDraft(
        variant_id="A",
        brief_title="Test",
        hook="90% of traders lose money.",  # 6 words
        segments=[
            ScriptSegment(
                index=0, heading="Intro", content="Welcome to this video.",
                estimated_duration_seconds=25, has_pattern_interrupt=True,
            ),
            ScriptSegment(
                index=1, heading="Point 1", content="First mistake is overtrading.",
                estimated_duration_seconds=80, has_pattern_interrupt=True,
            ),
            ScriptSegment(
                index=2, heading="Point 2", content="Second mistake is no stop loss.",
                estimated_duration_seconds=70, has_pattern_interrupt=False,
            ),
        ],
        outro="Thanks for watching. Subscribe!",
        word_count=1500,
        estimated_duration_seconds=600,
    )


@pytest.fixture
def bad_draft() -> ScriptDraft:
    """Draft that fails multiple evals."""
    return ScriptDraft(
        variant_id="B",
        brief_title="Test",
        hook="In today's fast-paced world of investing there are many things you need to know about making money",
        segments=[
            ScriptSegment(
                index=0, heading="Intro",
                content="Let's delve into the tapestry of investing.",
                estimated_duration_seconds=45,  # > 30s
                has_pattern_interrupt=False,
            ),
            ScriptSegment(
                index=1, heading="Main",
                content="This is a very long segment with lots of content.",
                estimated_duration_seconds=120,  # > 90s
                has_pattern_interrupt=False,
            ),
        ],
        outro="",  # empty outro
        word_count=5000,  # > 3000
        estimated_duration_seconds=1200,
    )


class TestHookLength:
    def test_short_hook_passes(self, good_draft):
        assert eval_hook_under_15_words(good_draft) is True

    def test_long_hook_fails(self, bad_draft):
        assert eval_hook_under_15_words(bad_draft) is False


class TestAICliches:
    def test_clean_text_passes(self, good_draft):
        assert eval_no_ai_cliches(good_draft) is True

    def test_cliche_text_fails(self, bad_draft):
        assert eval_no_ai_cliches(bad_draft) is False

    def test_cliche_list_not_empty(self):
        assert len(AI_CLICHE_LIST) > 10


class TestPatternInterrupt:
    def test_enough_interrupts(self, good_draft):
        assert eval_has_pattern_interrupt(good_draft) is True

    def test_no_interrupts(self, bad_draft):
        assert eval_has_pattern_interrupt(bad_draft) is False


class TestIntroDuration:
    def test_short_intro(self, good_draft):
        assert eval_intro_under_30s(good_draft) is True

    def test_long_intro(self, bad_draft):
        assert eval_intro_under_30s(bad_draft) is False

    def test_no_segments(self):
        draft = ScriptDraft(variant_id="X", brief_title="T", hook="H")
        assert eval_intro_under_30s(draft) is False


class TestSegmentDuration:
    def test_all_under_90(self, good_draft):
        assert eval_segment_under_90s(good_draft) is True

    def test_segment_over_90(self, bad_draft):
        assert eval_segment_under_90s(bad_draft) is False


class TestOutro:
    def test_has_outro(self, good_draft):
        assert eval_has_outro(good_draft) is True

    def test_empty_outro(self, bad_draft):
        assert eval_has_outro(bad_draft) is False


class TestWordCount:
    def test_reasonable_count(self, good_draft):
        assert eval_word_count_reasonable(good_draft) is True

    def test_too_many_words(self, bad_draft):
        assert eval_word_count_reasonable(bad_draft) is False

    def test_too_few_words(self):
        draft = ScriptDraft(variant_id="X", brief_title="T", hook="H", word_count=100)
        assert eval_word_count_reasonable(draft) is False


class TestRunBinaryEvals:
    def test_all_pass(self, good_draft):
        results = run_binary_evals(good_draft)
        assert all(results.values()), f"Failed evals: {[k for k, v in results.items() if not v]}"

    def test_mixed_results(self, bad_draft):
        results = run_binary_evals(bad_draft)
        assert not all(results.values())  # some should fail
        assert isinstance(results, dict)
        assert set(results.keys()) == set(WRITER_EVALS.keys())

    def test_custom_evals(self, good_draft):
        custom = {"hook_check": eval_hook_under_15_words}
        results = run_binary_evals(good_draft, evals=custom)
        assert "hook_check" in results
        assert len(results) == 1
