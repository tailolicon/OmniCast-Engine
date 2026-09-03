"""The film path's prompt contract: frame roles present, slop caught before spend.

Both mechanisms existed in this repo already — `clips.build_clip_prompt` wrote
proper first/last-frame wording and `slop.py` linted prompts — and neither was
reachable from `film_runner`, the only pipeline that renders video and spends
credits. These tests pin the wiring so it cannot silently come loose again.
"""

from __future__ import annotations

import pytest
import yaml

from omnicast.storyboard.clips import (
    FLF_CONSTRAINTS,
    FLF_FRAME_ROLES,
    flf_clip_prompt,
)
from omnicast.storyboard.film_runner import FilmError, load_film_spec


class TestFlfClipPrompt:
    def test_states_both_frame_roles(self):
        prompt = flf_clip_prompt("she lifts the lantern")
        assert "first attached image is the first frame" in prompt
        assert "second attached image is the last frame" in prompt

    def test_keeps_the_motion_line(self):
        assert "she lifts the lantern" in flf_clip_prompt("she lifts the lantern.")

    def test_no_double_terminator_on_motion(self):
        assert "lantern.." not in flf_clip_prompt("she lifts the lantern.")

    def test_appends_style_clause(self):
        prompt = flf_clip_prompt("a move", "Keep the flat cel style.")
        assert prompt.endswith("Keep the flat cel style.")

    def test_constraints_not_repeated_when_style_clause_has_them(self):
        prompt = flf_clip_prompt("a move", "Flat cel style, no scene change.")
        assert prompt.count("no scene change") == 1

    def test_constraints_added_when_style_clause_lacks_them(self):
        assert FLF_CONSTRAINTS in flf_clip_prompt("a move", "Flat cel style.")

    def test_empty_motion_still_yields_a_usable_prompt(self):
        prompt = flf_clip_prompt("")
        assert FLF_FRAME_ROLES in prompt
        assert "Along the way" not in prompt


def _spec_dict(tmp_path, still_prompt="a fox on a workbench, warm lamp light",
               shot_prompt="the fox turns its head") -> dict:
    return {
        "name": "t", "product_dir": str(tmp_path), "anchor": "K1",
        "style_lock": "flat cel colors, crisp ink outlines",
        "style_match_clause": "match the attached art",
        "video_style_clause": "keep the cel style",
        "stills": {
            "K1": {"file": "K1.jpg", "prompt": still_prompt},
            "K2": {"file": "K2.jpg", "prompt": still_prompt},
        },
        "shots": [{"id": "F1", "seconds": 5, "start": "K1", "end": "K2",
                   "prompt": shot_prompt}],
    }


def _write(tmp_path, spec: dict):
    path = tmp_path / "film.yaml"
    path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    return path


class TestSpecSlopGate:
    def test_clean_spec_loads(self, tmp_path):
        spec = load_film_spec(_write(tmp_path, _spec_dict(tmp_path)))
        assert len(spec.shots) == 1

    def test_blocking_slop_in_a_shot_stops_the_load(self, tmp_path):
        # "Cinematic" in the opening clause is the canonical empty evaluator:
        # it names no camera, light or lens, and it costs the highest-attention
        # position in the prompt.
        bad = _spec_dict(tmp_path, shot_prompt=
                         "Cinematic masterpiece, breathtaking ultra detailed, "
                         "8k hyperrealistic epic beautiful stunning")
        with pytest.raises(FilmError, match="blocking slop"):
            load_film_spec(_write(tmp_path, bad))

    def test_blocking_slop_in_a_still_stops_the_load(self, tmp_path):
        bad = _spec_dict(tmp_path, still_prompt=
                         "Cinematic masterpiece, breathtaking ultra detailed, "
                         "8k hyperrealistic epic beautiful stunning")
        with pytest.raises(FilmError, match="blocking slop"):
            load_film_spec(_write(tmp_path, bad))

    def test_error_names_the_offending_key(self, tmp_path):
        bad = _spec_dict(tmp_path, shot_prompt=
                         "Cinematic masterpiece, breathtaking ultra detailed, "
                         "8k hyperrealistic epic beautiful stunning")
        with pytest.raises(FilmError, match="F1"):
            load_film_spec(_write(tmp_path, bad))

    def test_gate_runs_before_any_file_check(self, tmp_path):
        """No image exists on disk here — the slop gate must still fire, which
        proves it runs at load time rather than after a generation attempt."""
        bad = _spec_dict(tmp_path, shot_prompt=
                         "Cinematic masterpiece, breathtaking ultra detailed, "
                         "8k hyperrealistic epic beautiful stunning")
        assert not (tmp_path / "K1.jpg").exists()
        with pytest.raises(FilmError):
            load_film_spec(_write(tmp_path, bad))
