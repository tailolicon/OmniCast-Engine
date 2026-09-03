"""A file must not be findable only by a number that can change.

Variant text was written as `variant_{id}_score{score}.txt` and later looked
up by rebuilding that same name. It worked until a gate adjusted the score
between the write and the read: the skeleton gate lowered a draft after its
file was on disk, and the run died with

    No such file: variant_claude_revised_score70.txt

while holding a result that said 72. The draft existed. Nothing was corrupt.
The pipeline simply could not name it any more.
"""

from __future__ import annotations

import pytest

from omnicast.agents.orchestrator import DebateResult
from omnicast.pipeline.steps import _variant_text_path


def _result(vid: str = "claude_revised", score: int = 72) -> DebateResult:
    return DebateResult(variant_id=vid, final_draft=None, final_score=score,
                        approved=False, converged=True)


def test_the_recorded_path_wins_even_after_the_score_moves(tmp_path):
    written = tmp_path / "variant_claude_revised_score70.txt"
    written.write_text("the draft", encoding="utf-8")
    r = _result(score=72)                       # a gate moved it after writing
    r.variant_path = str(written)
    assert _variant_text_path(tmp_path, r) == written


def test_an_old_product_without_the_recorded_path_still_resolves(tmp_path):
    """Products written before `variant_path` existed must keep opening."""
    written = tmp_path / "variant_claude_revised_score70.txt"
    written.write_text("the draft", encoding="utf-8")
    assert _variant_text_path(tmp_path, _result(score=70)) == written


def test_a_moved_score_falls_back_to_the_variant_id(tmp_path):
    written = tmp_path / "variant_claude_revised_score70.txt"
    written.write_text("the draft", encoding="utf-8")
    # no recorded path, and the score no longer matches the name
    assert _variant_text_path(tmp_path, _result(score=72)) == written


def test_the_newest_file_wins_when_several_scores_exist(tmp_path):
    import os
    import time

    old = tmp_path / "variant_claude_revised_score60.txt"
    old.write_text("older", encoding="utf-8")
    time.sleep(0.01)
    new = tmp_path / "variant_claude_revised_score70.txt"
    new.write_text("newer", encoding="utf-8")
    os.utime(new, None)
    assert _variant_text_path(tmp_path, _result(score=99)) == new


def test_a_different_variant_is_not_silently_substituted(tmp_path):
    """Returning some other variant's text would be worse than failing: the
    run would continue and ship a draft nobody selected."""
    (tmp_path / "variant_claude_initial_score27.txt").write_text(
        "the fragment", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as exc:
        _variant_text_path(tmp_path, _result("claude_revised", 72))
    assert "claude_revised" in str(exc.value)


def test_the_error_says_what_it_looked_for(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        _variant_text_path(tmp_path, _result())
    message = str(exc.value)
    assert "recorded path" in message and "72" in message


def test_the_writer_records_the_path_it_wrote():
    from pathlib import Path

    import omnicast.pipeline.steps as steps

    src = Path(steps.__file__).read_text(encoding="utf-8")
    assert "r.variant_path = str(" in src
    # and no caller rebuilds the name for the best result any more
    assert 'vdir / f"variant_{best.variant_id}_score{best.final_score}.txt"' \
        not in src
