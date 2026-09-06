"""Remove the visible SynthID sparkle (✦) that Google Flow / Nano Banana burns
into the bottom-right of every generated image.

History (06/09/2026):
* v1 cropped 4.5% off every edge and rescaled. Measured on real output the
  star centre sits 97px from the right and 97px from the bottom of a
  1376x768 frame, so the crop never touched it and three "final" renders
  shipped with the mark on every still.
* v2 template-matched the star and blurred a disc — the template was lifted
  off-centre, the disc missed the left tip, and a free-running small-scale
  search produced false matches on gravel/grain.

v3 (this): the mark is at a FIXED offset from the corner, so the primary
fix is deterministic — a clone-stamp patch over the known spot, no
detection needed. A second, tightly localised check catches the older
smaller star closer to the corner. Removal is verified by normalised
cross-correlation against a template lifted from a real render. No
framing change, idempotent, no OpenCV.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

_TEMPLATE = Path(__file__).resolve().parents[3] / "assets" / "qc" / "flow_sparkle_template.npy"
_MIN_SCORE = 0.60          # measured: sparkles 0.72–0.91, clean frames ≤0.49 at scale 1.0
_REF_W, _REF_H = 1376, 768  # frame the offsets below were measured on
# (offset from right, offset from bottom, patch radius) in _REF pixels
_PRIMARY = (97, 97, 40)     # current Flow output star (~56px wide)
_SECONDARY = (39, 70, 32)   # older files: smaller star nearer the corner
_SEC_MIN = 0.60             # localised NCC threshold for the secondary spot


def _anomaly(im: Image.Image) -> np.ndarray:
    g = im.convert("L")
    a = np.asarray(g, dtype=float)
    b = np.asarray(g.filter(ImageFilter.GaussianBlur(10)), dtype=float)
    return a - b


def _load_template() -> np.ndarray | None:
    try:
        return np.load(_TEMPLATE)
    except Exception:
        return None


def _scaled_template(T: np.ndarray, f: float) -> np.ndarray:
    if abs(f - 1.0) < 1e-6:
        return T
    n = max(8, int(round(T.shape[0] * f)))
    im = Image.fromarray(((T - T.min()) / (T.max() - T.min() + 1e-6) * 255).astype(np.uint8))
    a = np.asarray(im.resize((n, n), Image.BILINEAR), dtype=float)
    return (a - a.mean()) / (a.std() + 1e-6)


def _ncc_at(A: np.ndarray, T: np.ndarray, cx: int, cy: int, win: int) -> float:
    """Best normalised cross-correlation of T within ±win px of (cx, cy)."""
    from numpy.lib.stride_tricks import sliding_window_view as swv
    th, tw = T.shape
    h, w = A.shape
    y1, y2 = max(0, cy - win - th // 2), min(h, cy + win + th // 2 + 1)
    x1, x2 = max(0, cx - win - tw // 2), min(w, cx + win + tw // 2 + 1)
    R = A[y1:y2, x1:x2]
    if R.shape[0] <= th or R.shape[1] <= tw:
        return 0.0
    Tn = (T - T.mean()) / (T.std() + 1e-6)
    W = swv(R, T.shape)
    m = W.mean(axis=(-1, -2), keepdims=True)
    s = W.std(axis=(-1, -2), keepdims=True) + 1e-6
    C = ((W - m) / s * Tn).mean(axis=(-1, -2))
    return float(C.max())


def _spot(im_size: tuple[int, int], spec: tuple[int, int, int]) -> tuple[int, int, int]:
    """Scale a (from_right, from_bottom, radius) spec to this image's size."""
    w, h = im_size
    sx, sy = w / _REF_W, h / _REF_H
    return (int(round(w - spec[0] * sx)), int(round(h - spec[1] * sy)),
            int(round(spec[2] * (sx + sy) / 2)))


def find_sparkle(im: Image.Image, template: np.ndarray | None = None) -> tuple[float, tuple[int, int], float]:
    """Return (ncc_score, (cx, cy), scale) for the star at either known spot.
    Kept as the verification oracle; removal does not depend on it."""
    T0 = template if template is not None else _load_template()
    if T0 is None:
        return 0.0, (0, 0), 1.0
    A = _anomaly(im)
    px, py, _ = _spot(im.size, _PRIMARY)
    sx, sy, _ = _spot(im.size, _SECONDARY)
    best = (0.0, (0, 0), 1.0)
    for (cx, cy, scales, win) in ((px, py, (0.9, 1.0, 1.1), 24), (sx, sy, (0.6, 0.7, 0.8), 14)):
        for f in scales:
            s = _ncc_at(A, _scaled_template(T0, f), cx, cy, win)
            if s > best[0]:
                best = (s, (cx, cy), f)
    return best


def _refine_centre(A: np.ndarray, pos: tuple[int, int], win: int = 30) -> tuple[int, int]:
    """Centre the patch on the star's brightness-anomaly centroid (the nominal
    spot can be a few px off per image)."""
    h, w = A.shape
    x, y = pos
    x1, x2 = max(0, x - win), min(w, x + win)
    y1, y2 = max(0, y - win), min(h, y + win)
    sub = np.clip(A[y1:y2, x1:x2], 0, None)
    m = sub >= sub.max() * 0.35
    if m.sum() < 4:
        return pos
    ys, xs = np.nonzero(m)
    wts = sub[m]
    rx = int(round(x1 + (xs * wts).sum() / wts.sum()))
    ry = int(round(y1 + (ys * wts).sum() / wts.sum()))
    return (rx, ry) if abs(rx - x) <= 12 and abs(ry - y) <= 12 else pos


def _clone_patch(im: Image.Image, cx: int, cy: int, r: int) -> Image.Image:
    """Cover a disc with the texture immediately to its LEFT (clone stamp),
    feathered. Keeps grain and gradients that a blur would turn into a smudge."""
    im = im.convert("RGB")
    w, h = im.size
    shift = int(r * 2.4)
    if cx - r - shift < 0:            # no room on the left → take from above
        src = im.transform(im.size, Image.AFFINE, (1, 0, 0, 0, 1, -shift))
    else:
        src = im.transform(im.size, Image.AFFINE, (1, 0, -shift, 0, 1, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(5))
    return Image.composite(src, im, mask)


def strip_sparkle(path: Path, min_score: float = _MIN_SCORE, verify: bool = True,
                  force: bool = False) -> dict:
    """Remove the Flow sparkle in place when a localised match finds it at
    one of the two known spots (calibration 06/09: Nano Banana 2 stills
    carry NO mark, so an unconditional patch would only damage clean
    corners). `force` patches the primary spot regardless (re-processing
    files whose star was half-removed by an earlier pass).
    Returns {found, score, pos, removed, residual}; never raises."""
    path = Path(path)
    info = {"found": False, "score": 0.0, "pos": (0, 0), "removed": False, "residual": 0.0}
    try:
        T = _load_template()
        with Image.open(path) as im0:
            im = im0.convert("RGB")
        score, pos, scale = find_sparkle(im, T)
        info.update(score=round(score, 3), pos=pos, scale=scale)
        px, py, pr = _spot(im.size, _PRIMARY)
        sx, sy, sr = _spot(im.size, _SECONDARY)
        A = _anomaly(im) if T is not None else None
        do_primary = force or (T is not None and _ncc_at(A, T, px, py, 24) >= min_score)
        do_secondary = T is not None and max(
            _ncc_at(A, _scaled_template(T, f), sx, sy, 14) for f in (0.6, 0.7, 0.8)) >= _SEC_MIN
        if not (do_primary or do_secondary):
            return info
        info["found"] = bool(score >= min_score or do_secondary)
        out = im
        if do_primary:
            if A is not None:
                px, py = _refine_centre(A, (px, py))
            out = _clone_patch(out, px, py, pr)
        if do_secondary:
            out = _clone_patch(out, sx, sy, sr)
        if verify and T is not None:
            s2 = find_sparkle(out, T)[0]
            info["residual"] = round(s2, 3)
            if s2 >= min_score:  # widen once
                out = _clone_patch(out, px, py, int(pr * 1.4))
                info["residual"] = round(find_sparkle(out, T)[0], 3)
        out.save(path)
        info["removed"] = True
    except Exception as exc:  # a marked image beats a dead render
        info["error"] = str(exc)
    return info
