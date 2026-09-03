"""Mine real competitor premises so the planner can see what fresh looks like.

`premise_freshness_gate` and `avoid_tropes` can only forbid. Across 48 saved
plans the auditor issued 108 trope rejections — more than every other category
combined — while the plans themselves carried 132 distinct threat sentences.
The planner is not lazy; it varies wording and props freely. What it reuses is
SHAPE: "a man recites her plate number", "a man recites her patient's name",
"a man names a patient from her folder" are one premise wearing three coats.

Nothing had ever shown it the alternative. We hold 147 competitor captions and
had mined them for rhythm, opening moves and length — never for what actually
HAPPENS in them.

This extracts the opening situation of each competitor video: who the narrator
was, where they were, and what first went wrong. The bank is a reference of
shapes, never of wording — reusing a competitor's sentence would be theft and
would also fail the same freshness gate.

Usage:
  python scripts/build_premise_bank.py --channel true_dread_files_us
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from omnicast.analytics.skeleton import read_caption  # noqa: E402

# The first wrong thing, in the words a real account uses for it.
#
# MATCHED PER SENTENCE, not across the whole transcript. The first version put
# `[^.!?]*` on both sides of the trigger and ran finditer over 5,000-word
# captions; it backtracked for hours and produced nothing. Splitting first
# bounds every match to one sentence and makes the scan linear.
TURN = re.compile(
    r"\b(that'?s when|then i (saw|heard|noticed|realised|realized)|"
    r"the first (thing|time)|what (i|we) didn'?t|until i saw|"
    r"i noticed|it was only when|the problem was)\b", re.I)

_SENT = re.compile(r"(?<=[.!?])\s+")


def first_turns(text: str, limit: int = 3) -> list[str]:
    """The sentences where an ordinary evening stops being ordinary."""
    out: list[str] = []
    for sentence in _SENT.split(text):
        if len(out) >= limit:
            break
        sentence = " ".join(sentence.split())
        if 6 <= len(sentence.split()) <= 45 and TURN.search(sentence):
            out.append(sentence)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="true_dread_files_us")
    ap.add_argument("--open-words", type=int, default=90)
    args = ap.parse_args()

    res = ROOT / "output" / "research" / args.channel
    raw = json.loads((res / "raw_videos.json").read_text(encoding="utf-8"))
    meta = {v["video_id"]: (v.get("title", ""), int(v.get("views") or 0))
            for items in raw.values() for v in items}

    by: dict[str, Path] = {}
    for f in sorted((res / "_vtt_corpus").glob("*.vtt")):
        by.setdefault(f.name.split(".")[0], f)

    bank = []
    for vid, f in by.items():
        if vid not in meta:
            continue
        text = read_caption(f)
        if len(text.split()) < 800:
            continue
        title, views = meta[vid]
        opening = " ".join(text.split()[: args.open_words])
        turns = first_turns(text)
        bank.append({
            "video_id": vid, "title": title, "views": views,
            "opening": opening,
            "first_turns": turns,
        })

    bank.sort(key=lambda r: -r["views"])
    out = res / "premise_bank.json"
    out.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"{len(bank)} competitor premises -> {out}\n")
    print("Ten highest-viewed openings, as SHAPES to learn from:")
    for row in bank[:10]:
        print(f"\n· {row['views']:,} — {row['title'][:56]}")
        print(f"  {row['opening'][:200]}")
        if row["first_turns"]:
            print(f"  TURN: {row['first_turns'][0][:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
