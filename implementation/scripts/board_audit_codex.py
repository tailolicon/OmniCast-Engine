"""Storyboard audit/repair via Codex CLI — a standing render pre-pass.

The storyboard LLM still ships phase/observer/ledger mistakes that per-cell
gates cannot see (a subdivision aerial while the narrator watches from the
kitchen; a moon insert at the driveway beat; a kennel for a house dog). This
utility hands the SCRIPT + BOARD to Codex with the channel's visual rules and
lets it repair the board file in place. Deterministic gates still run after.

Usage:
    python -X utf8 scripts/board_audit_codex.py --script <script.txt> [--board <board.json>]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROMPT = """\
You are the visual editor for a first-person creepy-story YouTube channel.
Repair the storyboard file {board} (a JSON array; cell i covers scene i of the
script below) so every cell obeys these rules, derived from the genre's top
channels (see output/research/true_dread_files_us/codex_visual_grammar.md if
present):

1. STORY-WORLD LEDGER: fix the story's season/region/property from the script;
   define 4-8 recurring anchor looks and build every stock_query from one of
   them plus season tokens. New locations only when the narration names them.
2. PHASE + OBSERVER POSITION: the camera is where the narrator's body is.
   Never the threat's POV, never a location the narrator is not in.
3. THREAT OFF-SCREEN in stock: no person/figure/silhouette stock queries —
   the door, handle, window, darkness carry him. If a visible distant shape is
   truly required by the narration, set visual_type "generated_image" with a
   grainy found-photo image_prompt instead.
4. PROPS LITERAL: show the actual named prop in its stated state (an unlit
   porch bulb, a wall landline, one blue heeler at the house door - not a
   candle, payphone, or kennel).
5. NO READABLE TEXT/NUMBERS in any expected frame; negative_prompt lists this
   story's world-breakers as plain comma-separated words.
6. Named institutions get modest real architecture (no signage text).

Edit ONLY these fields per cell: visual_type, stock_query, search_query,
image_prompt, video_prompt, negative_prompt. Keep scene_index and cell count
exactly as they are. Keep queries 2-5 concrete everyday words a stock site
could match. After editing, verify the file is valid JSON with the same number
of cells, then print exactly: BOARD_OK changes=<number of cells you changed>

SCRIPT:
{script}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--board", default="")
    args = ap.parse_args()

    board_path = args.board
    if not board_path:
        cands = sorted(glob.glob(str(ROOT / "output/_img_cache/storyboard_*.json")),
                       key=os.path.getmtime)
        if not cands:
            print("no storyboard cache found"); return 2
        board_path = cands[-1]
    board_path = Path(board_path)
    before = json.loads(board_path.read_text(encoding="utf-8"))
    script_text = Path(args.script).read_text(encoding="utf-8")

    cx = shutil.which("codex")
    if not cx:
        print("codex CLI not found"); return 2
    prompt = PROMPT.format(board=board_path.as_posix(), script=script_text)
    p = subprocess.run(
        [cx, "exec", "--cd", str(ROOT), "--sandbox", "workspace-write", "-"],
        input=prompt, capture_output=True, text=True, timeout=3600)
    tail = (p.stdout or "")[-2000:]
    print(tail)
    if "BOARD_OK" not in tail:
        print("[board-audit] codex did not confirm — board left as-is")
        return 1
    after = json.loads(board_path.read_text(encoding="utf-8"))
    if len(after) != len(before):
        board_path.write_text(json.dumps(before, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        print("[board-audit] cell count changed — reverted")
        return 1
    changed = sum(1 for a, b in zip(after, before) if a != b)
    print(f"[board-audit] accepted: {changed} cells changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
