# -*- coding: utf-8 -*-
"""Generate a batch of horror scripts with the varied writer, collect them into
output/_script_eval/ for external (literary-AI) evaluation.

Each topic is a 3-story compilation; the point of the batch is to show the writer
now VARIES structure/endings across stories and across videos (not one fixed arc).
Also copies the pre-variety-fix 'motel' script as a baseline for comparison.
"""
import json
import re
import asyncio
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CH = "true_dread_files_us"
EVAL = ROOT / "output" / "_script_eval"
EVAL.mkdir(parents=True, exist_ok=True)

# v3 set — post critic scoring-integrity fix + rubric split. Run CONCURRENTLY
# (script gen is LLM/I-O bound, near-zero local cost → free speedup vs sequential).
# v4 — continuity self-check pass (#8) + threat-mix + blacklist + fingerprint feed-forward.
# Human-threat-friendly settings so the "≥2 of 3 stories are human threats" law fits.
TOPICS = [
    "3 True Encounters Closing a Store Alone at Night",
    "3 True Things That Happened on the Night Bus",
    "3 True Encounters at a Trailhead Parking Lot After Dark",
]
PREFIX = "v4_"
IDX_START = 1


def _newest_product(topic: str) -> Path | None:
    base = ROOT / "output" / "products" / CH
    if not base.exists():
        return None
    key = [w for w in re.sub(r"[^a-z0-9 ]", "", topic.lower()).split()][:4]
    best = None
    for d in base.iterdir():
        s = d.name.lower()
        if all(k in s for k in key) and (d / "script.txt").exists():
            if best is None or d.stat().st_mtime > best.stat().st_mtime:
                best = d
    return best


def _collect(product: Path, idx: int, note: str = "") -> str:
    script = (product / "script.txt").read_text(encoding="utf-8")
    title, score = "", ""
    tf = product / "video_title.txt"
    if tf.exists():
        title = tf.read_text(encoding="utf-8").strip()
    mf = product / "meta.json"
    if mf.exists():
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            score = str(m.get("script_score") or m.get("score") or "")
            if not title:
                title = m.get("title", "")
        except Exception:
            pass
    words = len(script.split())
    slug = re.sub(r"[^a-z0-9]+", "_", product.name.lower())[:50]
    out = EVAL / f"{PREFIX}{idx:02d}_{slug}.txt"
    header = (f"CHANNEL: True Dread Files (first-person true-horror compilation)\n"
              f"TITLE: {title}\n"
              f"INTERNAL CRITIC SCORE: {score or 'n/a'}/100\n"
              f"WORDS: {words}  (~{words/150:.1f} min narrated)\n")
    if note:
        header += f"NOTE: {note}\n"
    header += ("\nEVALUATE: is this genuinely frightening and immersive? Do the 3\n"
               "stories in THIS video use DIFFERENT structures/endings (not the\n"
               "same shape repeated)? Voice authentic first-person? Any AI-slop\n"
               "tells, clichés, or predictability?\n" + "=" * 70 + "\n\n")
    out.write_text(header + script, encoding="utf-8")
    print(f"[collect] -> {out.name} ({words} words, score {score or 'n/a'})", flush=True)
    return out.name


async def _gen_one(idx: int, topic: str) -> None:
    t0 = time.time()
    print(f"[eval] === start ({idx}) {topic} ===", flush=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-X", "utf8", "content_flow.py",
        "--channel", CH, "--topic", topic, "--phase", "2",
        cwd=str(ROOT), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    pd = _newest_product(topic)
    if pd:
        _collect(pd, idx)
    else:
        print(f"[eval] !! no product for '{topic}' (rc={proc.returncode})", flush=True)
        print((out or b"").decode("utf-8", "ignore")[-800:], flush=True)
    print(f"[eval] done ({idx}) in {(time.time()-t0)/60:.1f} min", flush=True)


def main() -> int:
    print(f"[eval] generating {len(TOPICS)} scripts CONCURRENTLY (LLM-bound → free parallelism)…",
          flush=True)

    async def _run():
        await asyncio.gather(*[_gen_one(IDX_START + n, t) for n, t in enumerate(TOPICS)])

    asyncio.run(_run())

    # (baseline motel + v1 set already collected in a previous run — kept for contrast)

    # README for the evaluators
    readme = EVAL / "README.md"
    readme.write_text(
        "# True Dread Files — script evaluation set\n\n"
        "First-person 'allegedly true' horror compilations (Mr. Nightmare / Lets "
        "Read register). Each file is one video = 3 back-to-back stories.\n\n"
        "## What to judge\n"
        "1. **Fear + immersion** — does it actually unsettle? Slow-burn dread, not gore.\n"
        "2. **Structural variety** — within each video the 3 stories should use "
        "DIFFERENT shapes/endings (twist / ambiguous / slow-burn / false-ending / "
        "unreliable-narrator / not-about-you / recurrence). Flag sameness.\n"
        "3. **Authentic first-person voice** — real person telling you, quoted "
        "dialogue, named bystanders, mundane specifics. No host framing, no "
        "'this is a true story', no stats.\n"
        "4. **AI-slop tells** — clichés, repetition, padding, predictability.\n\n"
        "`00_*` is a BASELINE from before the variety fix (all twist endings) — "
        "compare the newer ones against it.\n",
        encoding="utf-8")
    print(f"[eval] DONE — files in {EVAL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
