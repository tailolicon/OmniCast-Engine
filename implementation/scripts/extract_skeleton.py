"""Measure the structural skeleton of competitor scripts from their captions.

The operator's framing: content is interchangeable — anyone can explain the
earnings test — but the SKELETON (how the information is sequenced, paced and
handed off) is what makes one video land and another bounce. Learn the
skeleton from competitors, then hang our own flesh (the argument, the angle)
on it.

WHY THIS IS LOCAL AND NOT ASKED OF A MODEL. Of twelve skeleton factors, five
are counting problems: what fraction of the words is hook, where the staccato
runs sit, how dense the figures get, where the open loops are planted. A
language model reading retrieved passages answered nine such questions for us
earlier and got one right (verify_notebook_claims.py). We hold the captions,
so we count them. The qualitative factors — insight, viral factor, emotional
arc, bridging syntax, kicker — stay with NotebookLM, which is good at those.

Nothing here is a rule. It is a description of what these videos do, printed
so a human can decide what is worth copying.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ONE RULER. The measurement lives in the package so the generation gate
# and this profiler compute the identical numbers; a private copy here
# would silently drift and compare our drafts against a different scale.
from omnicast.analytics.skeleton import (  # noqa: E402
    Skeleton,
    analyse,
    read_caption,
)


ROWS = [("words", "words"),
        ("first number at %", "first_number_pct"),
        ("first $ figure at %", "first_dollar_pct"),
        ("first open loop at %", "first_promise_pct"),
        ("first question at %", "first_question_pct"),
        ("last new figure at %", "last_new_figure_pct"),
        ("first CTA at %", "first_cta_pct"),
        ("median sentence words", "median_sentence_words"),
        ("sentence spread", "sentence_len_spread"),
        ("bridges /100 sent", "bridge_rate_per_100_sent"),
        ("rhetorical Q /100 sent", "rhetorical_per_100_sent"),
        ("numbers /100 words", "numbers_per_100w"),
        ("densest 100w window", "max_density_window"),
        ("figurative /100 words", "figurative_per_100w"),
        ("'you' /100 words", "you_per_100w"),
        ("'I' /100 words", "i_per_100w")]


# Rhythm is only a sentence measurement when the source has sentences. On a
# caption without punctuation these read the 14-word chunker instead, which
# pulls any median toward 14 and any spread toward zero.
RHYTHM_ATTRS = {"median_sentence_words", "sentence_len_spread"}


def _median(rows: list[Skeleton], attr: str):
    if attr in RHYTHM_ATTRS:
        rows = [r for r in rows if getattr(r, "punctuated", True)]
    vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return round(statistics.median(vals), 1) if vals else None


def compare(our_path: Path, cohort: list[Skeleton]) -> None:
    """Print our script's skeleton beside the cohort's.

    Deliberately a REPORT, not a gate. The cohort median is a description of
    what this genre does, and a script forced to hit sixteen medians is a
    forgery of the average video — which is the opposite of the point. The
    writer keeps its judgement; the numbers just stop us from being
    structurally foreign without noticing.
    """
    text = our_path.read_text(encoding="utf-8")
    text = re.sub(r"^\[.*?\]\s*$", " ", text, flags=re.M)      # scene headings
    ours = analyse("ours", our_path.name, "ours", text)
    print(f"\n=== OUR SCRIPT vs COHORT ({len(cohort)} competitor scripts) ===")
    print(f"{'metric':<26}{'ours':>10}{'cohort':>10}{'winners':>10}   note")
    wins = [s for s in cohort if s.role == "winner"]
    for label, attr in ROWS:
        o = getattr(ours, attr)
        c = _median(cohort, attr)
        w = _median(wins, attr)
        note = ""
        if o is None:
            note = "ABSENT from our script"
        elif c:
            ratio = o / c if c else 0
            if ratio > 1.6:
                note = f"{ratio:.1f}x the cohort"
            elif ratio < 0.6:
                note = f"{ratio:.1f}x the cohort"
        print(f"{label:<26}{str(o):>10}{str(c):>10}{str(w):>10}   {note}")
    print(f"\nopen loops in ours: {len(ours.loops)} at {ours.loops or '—'}")
    print(f"staccato runs in ours: {len(ours.staccato_runs)}")
    print(f"bridge openers in ours: {', '.join(ours.bridge_openers) or '—'}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    channel = sys.argv[1] if len(sys.argv) > 1 else "senior_wealth_us"
    compare_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    res = ROOT / "output" / "research" / channel
    raw = json.loads((res / "raw_videos.json").read_text(encoding="utf-8"))

    from omnicast.analytics.cohort_labels import label_corpus
    snap = res / "corpus_snapshot.json"
    from datetime import datetime
    now = (datetime.fromisoformat(
        json.loads(snap.read_text(encoding="utf-8"))["snapshot_at"])
        if snap.exists() else None)
    labelled = {v.video_id: v for v in label_corpus(raw, now=now)}

    # ONE SCRIPT PER VIDEO. yt_dlp saves a file per caption track, so a video
    # with `en` and `en-orig` lands twice and every percentile is computed on a
    # corpus that silently double-counts. The horror corpus reported n=294 for
    # 147 videos before this.
    vtt_dir = res / "_vtt_corpus"
    by_video: dict[str, Path] = {}
    for f in sorted(vtt_dir.glob("*.vtt")):
        by_video.setdefault(f.name.split(".")[0], f)

    skeletons: list[Skeleton] = []
    for vid, f in sorted(by_video.items()):
        lab = labelled.get(vid)
        if lab is None or lab.fmt != "long":
            continue
        text = read_caption(f)
        if len(text.split()) < 400:
            continue
        skeletons.append(analyse(vid, lab.title or vid, lab.role, text))

    out = res / "skeleton_measurements.json"
    out.write_text(json.dumps([s.__dict__ for s in skeletons],
                              ensure_ascii=False, indent=1), encoding="utf-8")

    med = _median
    print(f"measured {len(skeletons)} long-form scripts from local captions\n")
    groups = [("ALL", skeletons),
              ("winner", [s for s in skeletons if s.role == "winner"]),
              ("control", [s for s in skeletons if s.role == "control"])]
    print(f"{'metric':<26}" + "".join(f"{g:>12}" for g, _ in groups))
    for label, attr in ROWS:
        print(f"{label:<26}" + "".join(
            f"{str(med(rs, attr)):>12}" for _, rs in groups))

    loops = [len(s.loops) for s in skeletons]
    stac = [len(s.staccato_runs) for s in skeletons]
    print(f"\nopen loops per script  median {statistics.median(loops):.0f}, "
          f"max {max(loops) if loops else 0}")
    print(f"staccato runs per script median {statistics.median(stac):.0f}, "
          f"max {max(stac) if stac else 0}")
    allop: dict[str, int] = {}
    for s in skeletons:
        for o in s.bridge_openers:
            allop[o] = allop.get(o, 0) + 1
    print("most common bridge openers:",
          ", ".join(f"{w}({n})" for w, n in
                    sorted(allop.items(), key=lambda kv: -kv[1])[:10]))
    print(f"\n[written] {out}")
    if compare_path is not None:
        compare(compare_path, skeletons)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
