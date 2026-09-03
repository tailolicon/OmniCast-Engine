"""film_runner: gates fire in order, regen is bounded, plan.json is written
back after every produced clip, and reuse skips paid work."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from omnicast.pipeline.edl import load_plan
from omnicast.storyboard import film_runner
from omnicast.storyboard.film_runner import (
    FilmError,
    FilmShot,
    FilmSpec,
    FilmStill,
    build_plan,
    gate_clips,
    gate_stills,
    load_film_spec,
    run_film,
)


def _cel(path: Path, seed: int = 0, brightness: float = 1.0) -> Path:
    """Seed moves shapes only; ink density stays fixed (same-renderer feel)."""
    pos = np.random.default_rng(seed)
    ink = np.random.default_rng(42)
    img = Image.new("RGB", (256, 256),
                    tuple(int(c * brightness) for c in (235, 210, 170)))
    d = ImageDraw.Draw(img)
    for gy in range(8):
        for gx in range(8):
            jx, jy = pos.integers(-5, 6, 2)
            x0, y0 = gx * 32 + 6 + int(jx), gy * 32 + 6 + int(jy)
            fill = tuple(int(c * brightness) for c in ink.integers(60, 220, 3))
            d.rectangle([x0, y0, x0 + 20, y0 + 20],
                        fill=fill, outline=(20, 15, 10), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=95)
    return path


def _wash(path: Path, seed: int = 0) -> Path:
    _cel(path, seed=seed)
    Image.open(path).filter(ImageFilter.GaussianBlur(4)).save(path, quality=95)
    return path


def _spec(tmp_path: Path, n_shots: int = 2) -> FilmSpec:
    stills = {}
    keys = ["K1", "K2", "K3"][: n_shots + 1]
    for i, k in enumerate(keys):
        p = tmp_path / "stills" / f"{k}.jpg"
        _cel(p, seed=i + 1)
        stills[k] = FilmStill(key=k, path=p, prompt=f"regen {k}")
    shots = [
        FilmShot(shot_id=f"S{i+1}", order=i, seconds=4,
                 start=keys[i], end=keys[i + 1], prompt=f"motion {i}")
        for i in range(n_shots)
    ]
    return FilmSpec(
        name="t", product_dir=tmp_path, anchor="K1",
        style_lock="cel", style_match_clause="match style",
        video_style_clause="keep style",
        stills=stills, shots=shots,
    )


class FakeProvider:
    """Counts calls; regen produces a clean cel still; clips are tiny mp4s."""

    def __init__(self, tmp_path: Path, regen_fixes: bool = True):
        self.tmp = tmp_path
        self.regen_fixes = regen_fixes
        self.refs = None
        self.generate_calls: list[str] = []
        self.flf_calls: list[dict] = []

    def set_reference_images(self, refs):
        self.refs = refs

    def set_characters(self, names):
        self.characters = list(names or [])

    async def generate(self, prompt, *, output_path, resolution=None,
                       wait_s=0, **kw):
        self.generate_calls.append(output_path)
        if self.regen_fixes:
            # Unique layout per call: the all-pairs content gate rejects a
            # regen that duplicates ANY existing keyframe.
            _cel(Path(output_path), seed=40 + len(self.generate_calls))
        else:
            _wash(Path(output_path), seed=9)
        return output_path

    async def convert_flf(self, start, end, prompt, *, seconds, output_path,
                          wait_s=0):
        self.flf_calls.append({"start": start, "end": end,
                               "prompt": prompt, "seconds": seconds})
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        return {"path": str(out), "workflow": f"wf-{out.stem}",
                "media_id": f"mid-{out.stem}"}


def test_gate_stills_passes_clean_spec(tmp_path):
    spec = _spec(tmp_path)
    provider = FakeProvider(tmp_path)
    verdicts = asyncio.run(gate_stills(spec, provider))
    assert not provider.generate_calls          # nothing regenerated
    assert all(v.passed for v in verdicts.values())


def test_gate_stills_regenerates_drifted_still(tmp_path):
    spec = _spec(tmp_path)
    spec.characters = ["Miko"]
    _wash(spec.stills["K2"].path, seed=2)       # drifted endpoint
    provider = FakeProvider(tmp_path)
    verdicts = asyncio.run(gate_stills(spec, provider))
    assert provider.generate_calls == [str(spec.stills["K2"].path)]
    assert provider.characters == ["Miko"]      # conditioning channel set
    assert verdicts["K2"].passed


def test_gate_stills_bounded_rerolls_fail_closed(tmp_path):
    spec = _spec(tmp_path)
    _wash(spec.stills["K2"].path, seed=2)
    provider = FakeProvider(tmp_path, regen_fixes=False)   # regen stays bad
    with pytest.raises(FilmError, match="failed its gate"):
        asyncio.run(gate_stills(spec, provider))
    assert len(provider.generate_calls) == film_runner.MAX_STILL_REROLLS


def test_gate_stills_no_prompt_refuses_regen(tmp_path):
    spec = _spec(tmp_path)
    _wash(spec.stills["K2"].path, seed=2)
    spec.stills["K2"].prompt = ""
    with pytest.raises(FilmError, match="no regen prompt"):
        asyncio.run(gate_stills(spec, FakeProvider(tmp_path)))


def test_gate_stills_rejects_copy_of_previous_keyframe(tmp_path):
    """A byte-copy of the previous keyframe passes the style gate perfectly —
    only the content gate can catch that the story beat did not happen (this
    is the stale-download failure from the first live run)."""
    import shutil

    spec = _spec(tmp_path)
    spec.stills["K2"].extra_refs = ["stills/K1.jpg"]
    shutil.copy(spec.stills["K1"].path, spec.stills["K2"].path)

    class CopyThenFixProvider(FakeProvider):
        async def generate(self, prompt, *, output_path, **kw):
            self.generate_calls.append(output_path)
            _cel(Path(output_path), seed=7)      # a genuinely new layout
            return output_path

    provider = CopyThenFixProvider(tmp_path)
    verdicts = asyncio.run(gate_stills(spec, provider))
    assert provider.generate_calls          # the copy was rejected and regenerated
    assert verdicts["K2"].passed


def test_gate_stills_rerolls_unreadable_file(tmp_path):
    """A non-image on disk (live bug: an mp4 saved as .jpg) must count as a
    failed candidate and be regenerated — never crash the stage."""
    spec = _spec(tmp_path)
    spec.stills["K2"].path.write_bytes(b"\x00\x00\x00 ftypisom-not-an-image")
    provider = FakeProvider(tmp_path)
    verdicts = asyncio.run(gate_stills(spec, provider))
    assert provider.generate_calls == [str(spec.stills["K2"].path)]
    assert verdicts["K2"].passed


def test_regen_prompt_content_first_and_frame_free(tmp_path):
    """Live lesson: the word "frame" got painted literally (an empty picture
    frame); the regen prompt must never contain it."""
    spec = _spec(tmp_path)
    from omnicast.storyboard.film_runner import _still_regen_prompt
    text = _still_regen_prompt(spec, spec.stills["K2"])
    assert spec.stills["K2"].prompt in text
    assert spec.style_lock in text
    assert "frame" not in text.lower().replace("keyframe", "")


def test_build_plan_valid_and_billable(tmp_path):
    spec = _spec(tmp_path, n_shots=2)
    plan = build_plan(spec)
    assert plan.billable_generations == 2
    assert [s.segment_id for s in plan.ordered()] == ["S1", "S2"]
    assert plan.segments[0].spec["mode"] == "flf"


def test_gate_clips_produces_and_writes_plan(tmp_path):
    spec = _spec(tmp_path)
    provider = FakeProvider(tmp_path)
    plan = build_plan(spec)
    plan = asyncio.run(gate_clips(spec, plan, provider))
    assert len(provider.flf_calls) == 2
    # style clause pinned onto every clip prompt
    assert all("keep style" in c["prompt"] for c in provider.flf_calls)
    # write-back happened: plan.json on disk knows the produced paths
    saved = load_plan(spec.product_dir)
    assert saved is not None
    assert all(s.produced for s in saved.segments)


def test_gate_clips_reuses_existing(tmp_path):
    spec = _spec(tmp_path)
    provider = FakeProvider(tmp_path)
    plan = build_plan(spec)
    plan = asyncio.run(gate_clips(spec, plan, provider))
    again = FakeProvider(tmp_path)
    asyncio.run(gate_clips(spec, plan, again))
    assert not again.flf_calls                  # nothing re-billed


def test_load_film_spec_roundtrip(tmp_path):
    product = tmp_path / "prod"
    (product / "stills").mkdir(parents=True)
    yaml_text = f"""
name: t
product_dir: "{product.as_posix()}"
anchor: K1
style_lock: cel
style_match_clause: match
video_style_clause: keep
stills:
  K1: {{file: stills/K1.jpg}}
  K2: {{file: stills/K2.jpg, prompt: p2, extra_refs: [stills/K1.jpg]}}
shots:
  - {{id: S1, seconds: 4, start: K1, end: K2, prompt: move}}
bgm: {{path: "", gain: 0.3}}
"""
    p = tmp_path / "film.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    spec = load_film_spec(p)
    assert spec.anchor == "K1"
    assert spec.shots[0].end == "K2"
    assert spec.stills["K2"].extra_refs == ["stills/K1.jpg"]
    assert spec.bgm_gain == 0.3


def test_load_film_spec_unknown_key_fails(tmp_path):
    p = tmp_path / "film.yaml"
    p.write_text("""
name: t
product_dir: "x"
anchor: K1
style_lock: a
style_match_clause: b
video_style_clause: c
stills:
  K1: {file: k1.jpg}
shots:
  - {id: S1, seconds: 4, start: K1, end: MISSING, prompt: m}
""", encoding="utf-8")
    with pytest.raises(FilmError, match="unknown still key"):
        load_film_spec(p)
