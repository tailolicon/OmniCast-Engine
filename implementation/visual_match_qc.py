"""Per-shot VO<->visual semantic match QC (vision LLM).

The storyboard builds prompts FROM the narration, but nothing verified the
ACQUIRED visual (loose Pexels matches, AI-image drift) against what the voice
is saying at that moment. This tool samples one frame per shot from the final
video, pairs it with that shot's spoken words (_assets/scene_XX.words.json),
and has a vision model score the semantic match 0-10.

Usage:
  python visual_match_qc.py <product_dir> [--threshold 5] [--limit N]

Writes <product_dir>/_visual_match_qc.json and prints worst offenders.
Exit code 1 if average < 6 or >15% of shots below threshold.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_PROMPT = (
    "You are a video QC reviewer. The narrator is saying:\n\"{text}\"\n\n"
    "Score 0-10 how well this frame VISUALLY SUPPORTS that line for a viewer "
    "(10 = depicts the subject directly; 6-7 = related mood/context that fits; "
    "3-5 = generic filler, weak link; 0-2 = wrong/contradicting/confusing). "
    "Frames with only large text/captions score by whether the text matches "
    "the line. Reply as JSON only: {{\"score\": <int>, \"reason\": \"<8 words max>\"}}"
)


def _shot_timeline(product: Path) -> list[dict]:
    """[{idx, start, mid, text}] from per-shot word timing sidecars."""
    files = sorted((product / "_assets").glob("scene_*.words.json"),
                   key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    shots, t = [], 0.0
    for f in files:
        words = json.loads(f.read_text(encoding="utf-8"))
        if not words:
            continue
        dur = max(w["end"] for w in words)
        text = " ".join(w["text"] for w in words)
        shots.append({"idx": len(shots), "start": t, "mid": t + dur / 2.0,
                      "dur": dur, "text": text})
        t += dur
    return shots


def _extract_frame(video: Path, ts: float, out_jpg: Path) -> bool:
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "4", "-vf", "scale=640:-1", str(out_jpg)],
        capture_output=True, creationflags=_NO_WINDOW, timeout=60)
    return out_jpg.exists() and out_jpg.stat().st_size > 0


async def _score_shot(client, model: str, shot: dict, jpg: Path,
                      sem: asyncio.Semaphore) -> dict:
    from google.genai import types
    async with sem:
        for attempt in (1, 2):
            try:
                def _call():
                    return client.models.generate_content(
                        model=model,
                        contents=[
                            types.Part.from_bytes(data=jpg.read_bytes(),
                                                  mime_type="image/jpeg"),
                            _PROMPT.format(text=shot["text"][:300]),
                        ])
                resp = await asyncio.to_thread(_call)
                m = re.search(r"\{[\s\S]*\}", resp.text or "")
                d = json.loads(m.group(0))
                return {**shot, "score": max(0, min(10, int(d.get("score", 0)))),
                        "reason": str(d.get("reason", ""))[:120], "frame": str(jpg)}
            except Exception as e:
                if attempt == 2:
                    return {**shot, "score": -1, "reason": f"qc_error: {e}"[:120],
                            "frame": str(jpg)}
                await asyncio.sleep(3)


async def run_qc(product: Path, threshold: int, limit: int | None) -> dict:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from google import genai
    from omnicast.config.settings import get_settings

    video = product / "video.mp4"
    if not video.exists():
        raise SystemExit(f"video.mp4 not found in {product}")
    shots = _shot_timeline(product)
    if limit:
        step = max(1, len(shots) // limit)
        shots = shots[::step][:limit]
    if not shots:
        raise SystemExit("no word-timing sidecars — render with word subs first")

    # Sanity: timeline drift vs real duration (crossfades overlap slightly)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, creationflags=_NO_WINDOW)
    real_dur = float(probe.stdout.strip() or 0)
    est_dur = shots[-1]["start"] + shots[-1]["dur"]
    scale = real_dur / est_dur if est_dur and real_dur else 1.0

    fdir = product / "_qc_frames"
    fdir.mkdir(exist_ok=True)
    ok_shots = []
    for s in shots:
        jpg = fdir / f"shot_{s['idx']:03d}.jpg"
        if _extract_frame(video, s["mid"] * scale, jpg):
            s["_jpg"] = jpg
            ok_shots.append(s)

    client = genai.Client(api_key=get_settings().google_api_key)
    sem = asyncio.Semaphore(8)
    results = await asyncio.gather(*[
        _score_shot(client, "gemini-2.5-flash", s, s.pop("_jpg"), sem)
        for s in ok_shots])

    scored = [r for r in results if r["score"] >= 0]
    avg = sum(r["score"] for r in scored) / max(1, len(scored))
    low = sorted([r for r in scored if r["score"] < threshold],
                 key=lambda r: r["score"])
    report = {
        "video": str(video), "shots_scored": len(scored),
        "avg_score": round(avg, 2),
        "below_threshold": len(low), "threshold": threshold,
        "timeline_scale": round(scale, 4),
        "worst": [{k: r[k] for k in ("idx", "score", "reason", "text", "frame")}
                  for r in low[:20]],
        "errors": len(results) - len(scored),
    }
    (product / "_visual_match_qc.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("product", help="product dir containing video.mp4 + _assets/")
    ap.add_argument("--threshold", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None,
                    help="sample only N shots evenly (cost/speed cap)")
    args = ap.parse_args()
    rep = asyncio.run(run_qc(Path(args.product), args.threshold, args.limit))
    print(f"[visual-qc] {rep['shots_scored']} shots | avg {rep['avg_score']}/10 "
          f"| {rep['below_threshold']} below {rep['threshold']}")
    for w in rep["worst"]:
        print(f"  shot {w['idx']:3d}  {w['score']}/10  {w['reason']}  "
              f"VO: {w['text'][:70]!r}")
    bad_ratio = rep["below_threshold"] / max(1, rep["shots_scored"])
    return 1 if (rep["avg_score"] < 6 or bad_ratio > 0.15) else 0


if __name__ == "__main__":
    raise SystemExit(main())
