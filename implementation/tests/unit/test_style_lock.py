"""style_lock: the gate must separate cel line-art from painterly wash and
stay blind to pure lighting changes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from omnicast.storyboard.style_lock import (
    BOUNDARY_GATE,
    STILL_GATE,
    check_boundary,
    check_still,
    film_span_report,
    lineart_distance,
    style_vector,
)


def _cel_image(path, *, brightness: float = 1.0, seed: int = 0):
    """Flat fills + hard dark outlines — the cel signature.

    `seed` only moves the shapes around; their sizes, colors and count stay
    fixed, the way two real frames of the same renderer share ink density
    even when the composition differs.
    """
    pos = np.random.default_rng(seed)
    ink = np.random.default_rng(42)
    img = Image.new("RGB", (256, 256),
                    tuple(int(c * brightness) for c in (235, 210, 170)))
    d = ImageDraw.Draw(img)
    # 8x8 grid with per-seed jitter: ink coverage is invariant, layout isn't —
    # like two frames from the same renderer.
    for gy in range(8):
        for gx in range(8):
            jx, jy = pos.integers(-5, 6, 2)
            x0, y0 = gx * 32 + 6 + int(jx), gy * 32 + 6 + int(jy)
            fill = tuple(int(c * brightness) for c in ink.integers(60, 220, 3))
            d.rectangle([x0, y0, x0 + 20, y0 + 20],
                        fill=fill, outline=(20, 15, 10), width=2)
    img.save(path, quality=95)
    return path


def _wash_image(path, *, seed: int = 0):
    """Same composition language but blurred soft — the watercolor signature."""
    _cel_image(path, seed=seed)
    img = Image.open(path).filter(ImageFilter.GaussianBlur(radius=4))
    img.save(path, quality=95)
    return path


@pytest.fixture()
def cel_anchor(tmp_path):
    return _cel_image(tmp_path / "anchor.jpg", seed=1)


def test_same_style_passes(tmp_path, cel_anchor):
    other = _cel_image(tmp_path / "other.jpg", seed=7)
    verdict = check_still(other, style_vector(cel_anchor))
    assert verdict.passed
    assert verdict.distance <= STILL_GATE


def test_painterly_wash_fails(tmp_path, cel_anchor):
    wash = _wash_image(tmp_path / "wash.jpg", seed=1)
    verdict = check_still(wash, style_vector(cel_anchor))
    assert not verdict.passed
    assert verdict.distance > STILL_GATE


def test_lighting_change_alone_does_not_trip_gate(tmp_path, cel_anchor):
    """The lantern lighting up must not read as a style break."""
    dim = _cel_image(tmp_path / "dim.jpg", brightness=0.62, seed=1)
    verdict = check_still(dim, style_vector(cel_anchor))
    assert verdict.passed, verdict.as_dict()


def test_boundary_same_frames_pass(tmp_path):
    a = _cel_image(tmp_path / "a.jpg", seed=3)
    b = _cel_image(tmp_path / "b.jpg", seed=3)
    assert check_boundary(a, b).passed


def test_boundary_style_break_fails(tmp_path):
    a = _cel_image(tmp_path / "a.jpg", seed=3)
    b = _wash_image(tmp_path / "b.jpg", seed=3)
    verdict = check_boundary(a, b)
    assert not verdict.passed
    assert verdict.distance > BOUNDARY_GATE


def test_film_span_reports_not_gates(tmp_path):
    head = _cel_image(tmp_path / "head.jpg", seed=2)
    tails = [_cel_image(tmp_path / "t1.jpg", seed=4),
             _wash_image(tmp_path / "t2.jpg", seed=5)]
    rows = film_span_report(head, tails)
    assert len(rows) == 2
    assert rows[1]["distance"] > rows[0]["distance"]


def test_distance_symmetric_zero_on_self(cel_anchor):
    v = style_vector(cel_anchor)
    dist, parts = lineart_distance(v, v)
    assert dist == 0.0
    assert set(parts) == {"grad", "strong", "sat_std", "col"}


_DEMO = (Path(__file__).resolve().parents[2] / "output" / "products"
         / "anim_demo" / "miko_lantern_ep1" / "stills_v4_backup")


@pytest.mark.skipif(not _DEMO.exists(), reason="v4 demo stills not on this machine")
def test_calibration_holds_on_real_demo_data():
    """The gate must keep separating the exact stills that motivated it: the
    approved anime-cel keyframes pass, the watercolor-drifted endpoints that
    caused the v4 style break fail. If a metric change breaks this, the
    thresholds must be recalibrated before shipping it."""
    anchor = style_vector(_DEMO / "K1.jpg")
    for good in ("K2b.jpg", "K3.jpg", "K4.jpg"):
        assert check_still(_DEMO / good, anchor).passed, good
    for bad in ("k5end.jpg", "k6end.jpg", "k7end.jpg"):
        assert not check_still(_DEMO / bad, anchor).passed, bad
