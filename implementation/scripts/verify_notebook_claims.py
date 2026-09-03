"""Check NotebookLM's word-position claims against the captions we hold.

The answers came back with numbers that sound measured: "first number at word
6", "first dollar figure at word 130". They were produced by a model reading
retrieved passages, not by counting — and the model itself said it could only
see snippets, then went looking on the web for transcripts it lacked.

We have 234 caption files pulled straight from YouTube. So the claims are
checkable, and a claim that is checkable and unchecked is just a nicer-looking
guess. This counts the real positions and prints them next to what was
claimed; it decides nothing on its own.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# What NotebookLM stated, transcribed by hand from the three answer files.
# (title fragment, claimed first-number word, claimed first-dollar word)
CLAIMS: list[tuple[str, int | None, int | None]] = [
    ("I Read Vanguard", 6, None),
    ("I Keep Warning People", 7, 210),
    ("Once Your Portfolio Hits", 12, 130),
    ("5 Expenses Retirees Can Cut", 13, 103),
    ("Working While Collecting Social Security", 21, None),
    ("The One Social Security Rule I Actually Trust", 33, None),
    ("IRS Owes Millions", 33, None),
    ("Too Rich", 76, 157),
    ("4% Rule", 1, 38),
    ("3 Estate Planning Moves", 2, None),
    ("5 Money Habits", 4, 9),
    ("Medicare Premiums Could Double", 8, 33),
    ("How Roth Conversions", 14, 51),
    ("10 Brutal Criticisms", 25, 200),
    ("12 Rules That Keep Me", 59, None),
]

NUM = re.compile(
    r"\b(\d[\d,]*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion)\b", re.I)
DOLLAR = re.compile(r"\$\s?\d|\b\d[\d,]*(\.\d+)?\s*(dollars|million|thousand)\b",
                    re.I)


def words_of(vtt: Path) -> list[str]:
    """Spoken words in order, cues and timing stripped."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in vtt.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if (not line or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:"))
                or "-->" in line or line.isdigit()):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line in seen:      # YouTube auto-captions repeat lines
            continue
        seen.add(line)
        out.extend(line.split())
    return out


def first_hit(words: list[str], rx: re.Pattern) -> int | None:
    for i, w in enumerate(words, start=1):
        if rx.search(w):
            return i
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    res = ROOT / "output" / "research" / "senior_wealth_us"
    raw = json.loads((res / "raw_videos.json").read_text(encoding="utf-8"))
    by_title = {}
    for items in raw.values():
        for v in items:
            if v.get("title") and v.get("video_id"):
                by_title[v["title"]] = v["video_id"]

    vtt_dir = res / "_vtt_corpus"
    print(f"{'title fragment':<44} {'claim#':>7} {'real#':>7}  "
          f"{'claim$':>7} {'real$':>7}  verdict")
    print("-" * 92)
    checked = agree_n = agree_d = missing = 0
    for frag, c_num, c_dol in CLAIMS:
        match = next((t for t in by_title if frag.lower() in t.lower()), None)
        if match is None:
            print(f"{frag[:44]:<44} {'-':>7} {'-':>7}  {'-':>7} {'-':>7}  "
                  f"NO SUCH TITLE in the corpus")
            missing += 1
            continue
        vid = by_title[match]
        files = list(vtt_dir.glob(f"{vid}*.vtt"))
        if not files:
            print(f"{frag[:44]:<44} {'-':>7} {'-':>7}  {'-':>7} {'-':>7}  "
                  f"no local caption ({vid})")
            missing += 1
            continue
        w = words_of(files[0])
        r_num, r_dol = first_hit(w, NUM), first_hit(w, DOLLAR)
        checked += 1
        # "Close" is generous on purpose: the model counted a retrieved passage,
        # we count the whole caption, and auto-captions drop filler words.
        ok_n = c_num is not None and r_num is not None and abs(c_num - r_num) <= 10
        ok_d = c_dol is not None and r_dol is not None and abs(c_dol - r_dol) <= 30
        agree_n += ok_n
        agree_d += ok_d
        verdict = ("num OK" if ok_n else "num OFF") + (
            f" · dollar {'OK' if ok_d else 'OFF'}" if c_dol is not None else "")
        print(f"{frag[:44]:<44} {str(c_num):>7} {str(r_num):>7}  "
              f"{str(c_dol):>7} {str(r_dol):>7}  {verdict}")

    print("-" * 92)
    print(f"checked {checked}, unavailable {missing} | first-number within 10 "
          f"words: {agree_n}/{checked} | first-dollar within 30 words: "
          f"{agree_d}/{sum(1 for _, _, d in CLAIMS if d is not None)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
