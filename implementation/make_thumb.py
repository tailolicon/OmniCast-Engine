"""LEGACY/EMERGENCY ONLY — regenerate a stock-frame thumbnail for one product.

OPERATOR POLICY 2026-07-09: production thumbnails are FLOW-ONLY (render fails
without Flow; see STRICT mode in render_real_video). This script remains solely
as a manual emergency tool and must not be wired into the pipeline.
Flow login: run scripts/flow_login.py once to establish the browser profile.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROD = ROOT / "output/products/beat_glp1_nausea/20260709_0234_shot_day_dinner_what_you_eat_tonight_decides_tomor"
ASSETS = PROD / "_assets"
CACHE = ROOT / "output" / "_img_cache"

import clickbait  # noqa: E402

FACE_RE = re.compile(
    r"woman|face|person|presenter|looking|clutching|holding|nauseous|smiling|"
    r"frustrated|tired|expression|couch|midsection", re.I)

# newest storyboard cache = this product's board (119 cells with queries)
board = None
for cp in sorted(CACHE.glob("storyboard_*.json"),
                 key=lambda p: p.stat().st_mtime, reverse=True):
    try:
        data = json.loads(cp.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) >= 100:
            board = data
            print(f"[board] {cp.name} ({len(data)} cells)")
            break
    except Exception:
        continue

cands: list[tuple[int, int, Path]] = []
for i in range(119):
    sp = ASSETS / f"scene_{i:02d}_stock.mp4"
    if not sp.exists() or sp.stat().st_size == 0:
        continue
    q = ""
    if board and i < len(board) and isinstance(board[i], dict):
        q = f"{board[i].get('stock_query', '')} {board[i].get('search_query', '')}"
    score = 2 if FACE_RE.search(q or "") else 0
    cands.append((score, i, sp))
cands.sort(key=lambda t: (-t[0], t[1]))
if not cands:
    raise SystemExit("no stock clips found")
score, idx, pick = cands[0]
print(f"[pick] scene {idx} (score {score}): "
      f"{(board[idx].get('stock_query') if board and idx < len(board) else '?')}")

bg = ASSETS / "_thumb_bg.png"
subprocess.run(["ffmpeg", "-y", "-ss", "1.0", "-i", str(pick),
                "-frames:v", "1", "-q:v", "2", str(bg)], check=True,
               capture_output=True)

script_text = (PROD / "script.txt").read_text(encoding="utf-8")
channel_meta = json.loads((ROOT / "channels/beat_glp1_nausea.json").read_text(encoding="utf-8"))
cb = clickbait.generate_clickbait(script_text, channel_meta) or {}
thumb_text = cb.get("thumb_text") or "WRONG DINNER?"
print(f"[text] {thumb_text!r} | title: {cb.get('title', '(giu title cu)')!r}")

accent = channel_meta.get("brand_color_hex", "#10B981").lstrip("#")
accent_rgb = tuple(int(accent[j:j + 2], 16) for j in (0, 2, 4))
out = PROD / "video_thumb.png"
clickbait.compose_thumbnail(bg, thumb_text, out, accent=accent_rgb)
print(f"[done] {out}")
