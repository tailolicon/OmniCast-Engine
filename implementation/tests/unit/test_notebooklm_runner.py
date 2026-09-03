"""Pins for the NotebookLM runner's deterministic core (no browser needed):
state machine legality + resume points, manifest idempotency (dedupe, stale
hash re-upload, prompt-hash re-run), and the supervisor allowlist contract.
"""

from __future__ import annotations

import pytest

from omnicast.analytics.notebook_research.manifest import RunManifest, short_hash
from omnicast.analytics.notebook_research.selectors import (
    SELECTORS,
    SUPERVISOR_ALLOWLIST,
)
from omnicast.analytics.notebook_research.state_machine import (
    TRANSITIONS,
    IllegalTransition,
    RunState,
    advance,
    resume_point,
)


class TestStateMachine:
    def test_happy_path_is_legal(self):
        path = [RunState.START, RunState.AUTH_CHECK, RunState.RESOLVE_NOTEBOOK,
                RunState.UPLOAD_SOURCES, RunState.WAIT_FOR_INDEXING,
                RunState.SOURCE_AUDIT, RunState.RUN_RESEARCH_PROMPTS,
                RunState.CAPTURE_RESPONSES, RunState.VALIDATE,
                RunState.INGEST, RunState.COMPLETE]
        cur = path[0]
        for nxt in path[1:]:
            cur = advance(cur, nxt)
        assert cur is RunState.COMPLETE

    def test_illegal_jump_raises(self):
        with pytest.raises(IllegalTransition):
            advance(RunState.AUTH_CHECK, RunState.RUN_RESEARCH_PROMPTS)

    def test_killed_at_indexing_resumes_without_reupload(self):
        assert resume_point(RunState.WAIT_FOR_INDEXING) is RunState.WAIT_FOR_INDEXING

    def test_auth_required_resumes_at_auth_check(self):
        assert resume_point(RunState.AUTH_REQUIRED) is RunState.AUTH_CHECK

    def test_every_state_has_a_transition_entry(self):
        assert set(TRANSITIONS) == set(RunState)


class TestManifest:
    def _packets(self, tmp_path, content_a="alpha transcript", content_b="beta"):
        a = tmp_path / "WIN_vidA.md"
        b = tmp_path / "CTL_vidB.md"
        a.write_text(content_a, encoding="utf-8")
        b.write_text(content_b, encoding="utf-8")
        return [("vidA", "winner", a), ("vidB", "control", b)]

    def test_register_is_idempotent(self, tmp_path):
        m = RunManifest.load_or_create(tmp_path, "ch", "NB")
        pk = self._packets(tmp_path)
        m.register_sources(pk)
        m.register_sources(pk)
        assert len(m.sources) == 2
        assert len(m.pending_uploads()) == 2

    def test_changed_hash_marks_stale_pending(self, tmp_path):
        m = RunManifest.load_or_create(tmp_path, "ch", "NB")
        pk = self._packets(tmp_path)
        m.register_sources(pk)
        for s in m.sources:
            s.upload_status = "indexed"
        pk[0][2].write_text("alpha transcript CHANGED", encoding="utf-8")
        m.register_sources(pk)
        pend = m.pending_uploads()
        assert [s.video_id for s in pend] == ["vidA"]
        assert pend[0].source_hash == short_hash("alpha transcript CHANGED")

    def test_remote_title_carries_role_and_hash(self, tmp_path):
        m = RunManifest.load_or_create(tmp_path, "ch", "NB")
        m.register_sources(self._packets(tmp_path))
        titles = {s.video_id: s.remote_title for s in m.sources}
        assert titles["vidA"].startswith("WIN_vidA_")
        assert titles["vidB"].startswith("CTL_vidB_")

    def test_persist_and_resume_roundtrip(self, tmp_path):
        m = RunManifest.load_or_create(tmp_path, "ch", "NB")
        m.register_sources(self._packets(tmp_path))
        m.transition(RunState.AUTH_CHECK, tmp_path)
        m.transition(RunState.RESOLVE_NOTEBOOK, tmp_path)
        m2 = RunManifest.load_or_create(tmp_path, "ch", "NB")
        assert m2.state is RunState.RESOLVE_NOTEBOOK
        assert len(m2.sources) == 2
        assert len(m2.history) == 2

    def test_prompt_hash_change_forces_rerun(self, tmp_path):
        m = RunManifest.load_or_create(tmp_path, "ch", "NB")
        j = m.register_prompt("pair_comparison", "old prompt")
        j.status = "complete"
        j2 = m.register_prompt("pair_comparison", "new prompt")
        assert j2.status == "pending"
        j3 = m.register_prompt("pair_comparison", "new prompt")
        assert j3.status == "pending" and len(m.prompts) == 1
        assert j3 is j2

    def test_completed_prompt_same_hash_not_rerun(self, tmp_path):
        m = RunManifest.load_or_create(tmp_path, "ch", "NB")
        j = m.register_prompt("cohort_synthesis", "the prompt")
        j.status = "complete"
        m.register_prompt("cohort_synthesis", "the prompt")
        assert m.pending_prompts() == []


class TestSupervisorContract:
    def test_allowlist_has_no_destructive_actions(self):
        banned = {"delete", "share", "remove", "account", "subscription", "terms"}
        for action in SUPERVISOR_ALLOWLIST:
            assert not any(b in action for b in banned), action

    def test_selectors_avoid_obfuscated_primary(self):
        # First strategy of every semantic key must be meaning-based (role/text)
        # or a structural css like input[type=file] — never .sc-xxx classes.
        for key, strategies in SELECTORS.items():
            first_strategy, first_value = strategies[0]
            assert not first_value.startswith(".sc-"), key
            assert "mdc" not in first_value, key
