"""Ask the notebook ONE question and print the answer. Nothing else.

Corpus research happens once per channel. Building a resumable state machine
around a one-time job was the wrong trade: four consecutive runs each burned
minutes to surface one more automation bug, and none of them were bugs about
retirement videos.

So this is a hand tool. It opens the notebook that the run manifest already
points at, sends the text you give it, waits for the answer, and prints it.
No manifest writes, no source verification, no state transitions, no retries.
The operator (me) reads the answer and decides what to ask next.

Operator allowlist, unchanged: never deletes a notebook or a source, never
shares, never switches account, never accepts terms.

Usage:
  python scripts/notebooklm_ask.py "your question"
  python scripts/notebooklm_ask.py @path/to/question.txt [--out answer.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from omnicast.analytics.notebook_research.browser_provider import (  # noqa: E402
    NotebookLMWorker,
)
from omnicast.analytics.notebook_research.manifest import RunManifest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", help='text, or "@file" to read it from disk')
    ap.add_argument("--channel", default="senior_wealth_us")
    ap.add_argument("--notebook-key", default="SFR_280_URL_FIRST")
    ap.add_argument("--out", default="", help="also write the answer here")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    text = (Path(args.question[1:]).read_text(encoding="utf-8")
            if args.question.startswith("@") else args.question)
    text = text.strip()
    if not text:
        print("REJECTED: empty question")
        return 1

    base = ROOT / "output" / "research" / args.channel / "notebooklm" / "runs"
    manifest = RunManifest.load_or_create(base, args.channel, args.notebook_key)
    if not manifest.notebook_url:
        print("REJECTED: no notebook_url in the manifest — nothing to open")
        return 1

    profile = ROOT / "output" / "notebooklm_profile"
    with NotebookLMWorker(profile_dir=profile, work_dir=base,
                          headless=args.headless) as worker:
        worker.auth_check()
        worker.resolve_notebook(manifest.notebook_key, manifest.notebook_url)
        answer = worker.run_prompt(text)

    # WRITE FIRST, PRINT SECOND. The first live use got its answer and then
    # died printing it to a cp1252 console — the answer had a curly quote in
    # it. Saving after displaying means a display problem destroys the result.
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(answer, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 70)
    print(answer)
    print("=" * 70)
    if args.out:
        print(f"[written] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
