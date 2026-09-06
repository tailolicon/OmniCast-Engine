"""The Flow sparkle stripper must remove the mark where Flow puts it, verify
the removal, stay idempotent, and never touch pixels away from the corner."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from omnicast.media import flow_sparkle as fs


def _paste_star(im: Image.Image, cx: int, cy: int, scale: float = 1.0) -> Image.Image:
    """Stamp the real sparkle pattern (from the template) as a semi-transparent
    white overlay, like SynthID does."""
    T = np.load(fs._TEMPLATE)
    star = np.clip(T, 0, None)
    star = star / star.max()
    if scale != 1.0:
        n = int(round(star.shape[0] * scale))
        star = np.asarray(Image.fromarray((star * 255).astype(np.uint8)).resize((n, n)), dtype=float) / 255
    arr = np.asarray(im.convert("RGB")).astype(float)
    n = star.shape[0]
    y0, x0 = cy - n // 2, cx - n // 2
    a = star[..., None] * 0.55
    arr[y0:y0 + n, x0:x0 + n] = arr[y0:y0 + n, x0:x0 + n] * (1 - a) + 255 * a
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


@pytest.fixture()
def dark_scene(tmp_path: Path) -> Path:
    rng = np.random.default_rng(7)
    base = rng.normal(40, 12, (768, 1376, 3)).clip(0, 255).astype(np.uint8)
    p = tmp_path / "scene.png"
    Image.fromarray(base).save(p)
    return p


def test_template_asset_exists():
    assert fs._TEMPLATE.exists(), "assets/qc/flow_sparkle_template.npy missing"


def test_primary_star_removed_and_verified(dark_scene: Path):
    px, py, _ = fs._spot((1376, 768), fs._PRIMARY)
    _paste_star(Image.open(dark_scene), px, py).save(dark_scene)
    s0 = fs.find_sparkle(Image.open(dark_scene))[0]
    assert s0 >= fs._MIN_SCORE, f"stamped star not detected (score {s0:.2f})"
    r = fs.strip_sparkle(dark_scene)
    assert r["removed"] and r["found"]
    assert r["residual"] < fs._MIN_SCORE
    assert fs.find_sparkle(Image.open(dark_scene))[0] < fs._MIN_SCORE


def test_secondary_small_star_removed(dark_scene: Path):
    sx, sy, _ = fs._spot((1376, 768), fs._SECONDARY)
    _paste_star(Image.open(dark_scene), sx, sy, scale=0.7).save(dark_scene)
    r = fs.strip_sparkle(dark_scene)
    assert r["removed"]
    assert fs.find_sparkle(Image.open(dark_scene))[0] < fs._MIN_SCORE


def test_clean_image_untouched(dark_scene: Path):
    """No star → no patch (Nano Banana 2 stills carry no mark)."""
    before = np.asarray(Image.open(dark_scene).convert("RGB")).copy()
    r = fs.strip_sparkle(dark_scene)
    assert r["removed"] is False
    assert np.array_equal(before, np.asarray(Image.open(dark_scene).convert("RGB")))


def test_patch_confined_to_corner(dark_scene: Path):
    px, py, _ = fs._spot((1376, 768), fs._PRIMARY)
    _paste_star(Image.open(dark_scene), px, py).save(dark_scene)
    before = np.asarray(Image.open(dark_scene).convert("RGB")).copy()
    fs.strip_sparkle(dark_scene)
    after = np.asarray(Image.open(dark_scene).convert("RGB"))
    diff = np.abs(before.astype(int) - after.astype(int)).sum(axis=2) > 0
    ys, xs = np.nonzero(diff)
    assert diff.any()
    assert xs.min() > 1376 * 0.85 and ys.min() > 768 * 0.75


def test_clean_corner_secondary_untouched(dark_scene: Path):
    """No small star → the secondary spot must not be patched."""
    before = np.asarray(Image.open(dark_scene).convert("RGB")).copy()
    fs.strip_sparkle(dark_scene)
    after = np.asarray(Image.open(dark_scene).convert("RGB"))
    sx, sy, sr = fs._spot((1376, 768), fs._SECONDARY)
    # pixels right at the corner (outside the primary patch) are unchanged
    assert np.array_equal(before[sy + sr - 4:, sx + sr - 4:], after[sy + sr - 4:, sx + sr - 4:])
