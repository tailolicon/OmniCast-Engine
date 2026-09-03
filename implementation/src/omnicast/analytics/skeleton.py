"""Structural measurement of a spoken script — the "skeleton".

Content is not what separates a watched video from an abandoned one in this
niche; everyone explains the same rules. The skeleton is: where the first
figure lands, how often one idea is handed to the next, how much the sentence
length varies, how present the narrator is.

Lives in the package, not in a script, because two callers need the identical
measurement: the research tool that profiles 133 competitor captions, and the
generation gate that measures our own draft against them. A gate computing
"roughly the same thing" as the profiler would compare two different rulers.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

# Open loops: a promise now, paid later. These are the phrasings that plant one.
LOOP = re.compile(
    r"\b(stay with me|stick around|by the end of this|i'?ll (explain|show|get to|come back)"
    r"|more on that|in (a|just a) (minute|moment|second)|later in this video"
    r"|but first|before (we|i) (get to|do)|hold that thought|keep that in mind"
    r"|here'?s the part|the (one|thing) nobody|wait (until|till) you (see|hear))\b",
    re.I)
# Bridges: how one idea is handed to the next.
BRIDGE = re.compile(
    r"^(but|so|now|here'?s|and (yet|here)|which (is why|means)|the (question|problem) "
    r"(is|then)|that'?s (why|when|where)|except|the catch|meanwhile|okay|alright)\b",
    re.I)
RHETORICAL = re.compile(r"\?\s*$")
# DIGITS AND WORDS BOTH COUNT, because the two sides of every comparison write
# them differently. Competitor captions come from ASR, which renders "twenty
# one" as "21"; our scripts are prose written to be SPOKEN, so they spell
# numbers out — and must, since a TTS splitter once read "$7,760" aloud as "$7"
# and "760". Counting only digits reported a 4,435-word draft holding 31
# numeric anchors as containing no number at all.
NUMBER = re.compile(
    r"\b\d[\d,]*(\.\d+)?\b|\$\s?\d"
    r"|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|billion|percent)\b", re.I)
# Softeners: the story/metaphor beat that follows a run of figures.
FIGURATIVE = re.compile(
    r"\b(like|as if|imagine|picture|think of it|it'?s the same as|sort of like"
    r"|the way (a|an|you)|feels like)\b", re.I)
CTA = re.compile(
    r"\b(subscribe|hit the (bell|like)|comment below|let me know|link (in|below)"
    r"|check the description|share this)\b", re.I)
SECOND_PERSON = re.compile(r"\b(you|your|you'?re|you'?ll|you'?ve)\b", re.I)
FIRST_PERSON = re.compile(r"\b(i|i'?m|i'?ve|i'?ll|my|me)\b", re.I)

STACCATO_MAX_WORDS = 9      # a "short" sentence
STACCATO_RUN = 3            # this many in a row is a deliberate burst


@dataclass
class Skeleton:
    video_id: str
    title: str
    role: str
    words: int = 0
    sentences: int = 0
    # F5 pacing — positions as % of the script
    first_question_pct: float | None = None
    first_number_pct: float | None = None
    first_dollar_pct: float | None = None
    first_promise_pct: float | None = None
    last_new_figure_pct: float | None = None
    first_cta_pct: float | None = None
    # F6 open loops
    loops: list[float] = field(default_factory=list)          # % positions
    # F7 bridging
    bridge_rate_per_100_sent: float = 0.0
    rhetorical_per_100_sent: float = 0.0
    bridge_openers: list[str] = field(default_factory=list)   # actual words used
    # F8 rhythm
    median_sentence_words: float = 0.0
    sentence_len_spread: float = 0.0
    staccato_runs: list[float] = field(default_factory=list)  # % positions
    # F9 density
    numbers_per_100w: float = 0.0
    max_density_window: float = 0.0        # figures in the densest 100 words
    figurative_per_100w: float = 0.0
    # voice
    you_per_100w: float = 0.0
    i_per_100w: float = 0.0
    # Did the source carry real punctuation? Rhythm numbers measured off the
    # 14-word fallback chunker are not sentence lengths at all — they are the
    # chunk size — and averaging them together with punctuated scripts drags
    # any median toward 14 and any spread toward zero. 15 of 147 horror
    # captions land here, so this has to be visible, not assumed.
    punctuated: bool = True


def read_caption(path: Path) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if (not line or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:"))
                or "-->" in line or line.isdigit()):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line in seen:      # auto-captions repeat each line
            continue
        seen.add(line)
        out.append(line)
    return " ".join(out)


def is_punctuated(text: str) -> bool:
    """Does this text split into real sentences, or only into breath-chunks?"""
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return bool(parts) and len(parts) > 5 and statistics.median(
        len(p.split()) for p in parts) < 60


def sentences_of(text: str) -> list[str]:
    """Auto-captions carry no punctuation reliably, so fall back to chunks."""
    if is_punctuated(text):
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    words = text.split()                  # unpunctuated: approximate by breath
    return [" ".join(words[i:i + 14]) for i in range(0, len(words), 14)]


def pct_of_first(words: list[str], rx: re.Pattern) -> float | None:
    for i, w in enumerate(words):
        if rx.search(w):
            return round(100 * i / max(1, len(words)), 1)
    return None


def analyse(video_id: str, title: str, role: str, text: str) -> Skeleton:
    words = text.split()
    sents = sentences_of(text)
    sk = Skeleton(video_id=video_id, title=title, role=role,
                  words=len(words), sentences=len(sents),
                  punctuated=is_punctuated(text))
    if not words:
        return sk

    sk.first_number_pct = pct_of_first(words, NUMBER)
    sk.first_dollar_pct = pct_of_first(words, re.compile(r"\$\s?\d"))
    sk.first_cta_pct = pct_of_first(words, CTA)

    # Phrase-level positions need the running text, not single tokens.
    def phrase_pct(rx: re.Pattern) -> float | None:
        m = rx.search(text)
        if not m:
            return None
        return round(100 * len(text[:m.start()].split()) / max(1, len(words)), 1)

    sk.first_promise_pct = phrase_pct(LOOP)
    sk.loops = []
    for m in LOOP.finditer(text):
        sk.loops.append(round(100 * len(text[:m.start()].split())
                              / max(1, len(words)), 1))

    q = [i for i, s in enumerate(sents) if RHETORICAL.search(s)]
    if q:
        sk.first_question_pct = round(100 * q[0] / max(1, len(sents)), 1)
    sk.rhetorical_per_100_sent = round(100 * len(q) / max(1, len(sents)), 1)

    openers = [s.split()[0].strip(",.").lower() for s in sents
               if s.split() and BRIDGE.match(s)]
    sk.bridge_rate_per_100_sent = round(100 * len(openers) / max(1, len(sents)), 1)
    sk.bridge_openers = [w for w, _ in
                         sorted({o: openers.count(o) for o in set(openers)}.items(),
                                key=lambda kv: -kv[1])[:6]]

    lens = [len(s.split()) for s in sents]
    sk.median_sentence_words = round(statistics.median(lens), 1)
    sk.sentence_len_spread = round(
        statistics.pstdev(lens) if len(lens) > 1 else 0.0, 1)
    run = 0
    for i, n in enumerate(lens):
        run = run + 1 if n <= STACCATO_MAX_WORDS else 0
        if run == STACCATO_RUN:
            sk.staccato_runs.append(round(100 * i / max(1, len(sents)), 1))

    nums = [i for i, w in enumerate(words) if NUMBER.search(w)]
    sk.numbers_per_100w = round(100 * len(nums) / len(words), 1)
    if nums:
        sk.last_new_figure_pct = round(100 * nums[-1] / len(words), 1)
        dens = 0
        for start in range(0, len(words), 25):
            dens = max(dens, sum(1 for n in nums if start <= n < start + 100))
        sk.max_density_window = dens
    sk.figurative_per_100w = round(
        100 * len(FIGURATIVE.findall(text)) / len(words), 1)
    sk.you_per_100w = round(100 * len(SECOND_PERSON.findall(text)) / len(words), 1)
    sk.i_per_100w = round(100 * len(FIRST_PERSON.findall(text)) / len(words), 1)
    return sk


# ── the gate ────────────────────────────────────────────────────────────────
#
# THREE FLOORS, NOT SIXTEEN. The profiler measures sixteen things about the
# cohort; forcing a draft to hit sixteen medians would produce a forgery of the
# average video in this niche, which is worth less than an honest outlier. The
# operator's instruction was explicit: do not cost the writer its creativity.
#
# These three are floors because they are what made a rejected build read as a
# bulletin rather than a video, and each was measured, not guessed:
#   * self_per_100w   — the missing "I". Ours 0.3-0.5 against a cohort 2.4.
#   * you_per_100w    — who the script is speaking to. Ours 2.3 against 4.7.
#   * sentence_spread — rhythm. Ours 5.9-6.1 against 10.3. A flat spread IS
#                       the metronome an operator heard and called flat editing.
#
# Everything else the profiler reports stays advisory. A gate that cannot be
# argued with had better be one that cannot be wrong.
# SET FROM THE DISTRIBUTION, NOT FROM A RATIO. The first version used "half
# the median", "two thirds of the median" — numbers with no meaning behind
# them. These are the 10th percentile of 133 competitor scripts, so a breach
# says something concrete: this draft is less personal, less direct or flatter
# than nine competitors in ten. Recalibrating made the rhythm floor STRICTER
# (7.5 → 8.1) and the first-person floor looser (1.2 → 0.9), and the draft
# under review failed both before and after — the point was to have a reason,
# not to let anything through.
#
# On the first-person floor specifically: the cohort median of 2.4 is NOT the
# target and must not become one. Splitting it shows judgment ("I dislike
# calling that lost") runs 0.25 and biography or credential 0.02; the rest is
# ordinary spoken first person ("I'll walk you through", "let me"). A faceless
# YMYL channel may write all of that except the biography — but matching 2.4
# would mean padding, and padding is the opposite of presence.
# PER CHANNEL, because two niches measured on the same ruler want OPPOSITE
# things. Retirement explainers address the viewer constantly (`you` 4.7 per
# 100 words) and reference themselves sparingly (`I` 2.4). First-person horror
# is the mirror image: `you` 0.4, `I` 6.8. One global floor would have ordered
# every horror narrator to start lecturing the audience.
#
# AND BOUNDS, not floors. The finance failure was ABSENCE — too little self,
# too little address, too little variation — so those are minimums. The horror
# failure is EXCESS: sentences at 24 words against a genre whose entire
# distribution runs 10 to 15, and the first concrete detail arriving at 60%
# where the genre anchors in its opening line. Those need maximums.
#
# `None` on a side means unbounded. An unlisted channel is NOT gated at all:
# borrowing another niche's numbers is the mistake this table exists to stop.
SKELETON_BOUNDS: dict[str, dict[str, tuple[float | None, float | None]]] = {
    # 133 competitor scripts; minimums at p10.
    "senior_wealth_us": {
        "i_per_100w": (0.9, None),           # p5 0.50 · p25 1.50 · median 2.40
        "you_per_100w": (2.8, None),         # p5 2.40 · p25 3.60 · median 4.70
        "sentence_len_spread": (8.1, None),  # p5 7.30 · p25 9.10 · median 10.3
    },
    # 147 competitor scripts (@mrnightmare, @DarkSomnium, @Unit522);
    # maximums at p90, because this genre's failure mode is literary prose.
    "true_dread_files_us": {
        "median_sentence_words": (None, 15.0),  # p10 10 · median 13 · p90 15
        "staccato_run_count": (3, None),        # p10 3 · median 9 · p90 79
        # Recomputed after the number rule was corrected to count spelled-out
        # numerals as well as digits. Under digits only this read p90 7.9;
        # measured properly the genre anchors almost immediately — median 0.3%
        # — and the honest ceiling is 2.4. Tightening it fails the draft that
        # prompted the recount, which is the point: the ruler is not adjusted
        # to the thing being measured.
        "first_number_pct": (None, 2.4),        # p10 0.0 · median 0.3 · p90 2.4
    },
}

COHORT_MEDIANS: dict[str, dict[str, float]] = {
    "senior_wealth_us": {
        "i_per_100w": 2.4, "you_per_100w": 4.7, "sentence_len_spread": 10.3,
        "first_dollar_pct": 18.9, "first_question_pct": 5.0,
        "first_promise_pct": 7.2, "bridge_rate_per_100_sent": 19.7,
        "rhetorical_per_100_sent": 9.8, "last_new_figure_pct": 96.3,
    },
    "true_dread_files_us": {
        "median_sentence_words": 13.0, "staccato_run_count": 9.0,
        "first_number_pct": 0.3, "i_per_100w": 6.8, "you_per_100w": 0.4,
        "sentence_len_spread": 7.7, "bridge_rate_per_100_sent": 3.9,
        "figurative_per_100w": 0.5,
    },
}

_LABELS = {
    "i_per_100w": ("first-person presence", "'I' per 100 words"),
    "you_per_100w": ("direct address", "'you' per 100 words"),
    "sentence_len_spread": ("sentence-length variety",
                            "standard deviation of sentence length"),
    "median_sentence_words": ("sentence length", "median words per sentence"),
    "staccato_run_count": ("short-sentence bursts",
                           "runs of 3+ sentences under 10 words"),
    "first_number_pct": ("first concrete detail",
                         "position of the first number, % into the script"),
}

# What to tell the writer, keyed by metric AND by which side was breached.
_ADVICE = {
    ("i_per_100w", "min"):
        "The narrator is absent. Say what YOU make of the material and speak "
        "the way a person speaks. Never a credential, a client or an invented "
        "experience; judgment about the material is what belongs here.",
    ("you_per_100w", "min"):
        "Write to one viewer, not to a readership. Second person, their "
        "situation, their money.",
    ("sentence_len_spread", "min"):
        "Every sentence is the same length, which is why it reads like a "
        "metronome. Break a dense passage with three short ones; let an "
        "explanation run long when it earns the room.",
    ("median_sentence_words", "max"):
        "These are written sentences, not spoken ones. The genre runs 10-15 "
        "words a sentence; this is prose a narrator has to fight. Cut the "
        "subordinate clauses and let the plain statements stand alone.",
    ("staccato_run_count", "min"):
        "Nothing ever speeds up. Three short sentences in a row is how this "
        "genre raises tension — 'The nights were different. The nights "
        "dragged.' Use it where the story turns, not everywhere.",
    ("first_number_pct", "max"):
        "No specific detail anchors the opening. An account that sounds true "
        "carries measurable specifics early — an age, a year, a time of night "
        "— because that is what someone recounting a real event remembers. "
        "Atmosphere first reads as fiction.",
}


def _metric(sk: "Skeleton", key: str):
    """Read one gated metric, including the ones that are counts of a list."""
    if key == "staccato_run_count":
        return len(sk.staccato_runs)
    return getattr(sk, key, None)


def skeleton_problems(text: str, channel_id: str = "") -> list[str]:
    """Bounds this draft is outside, phrased as something a writer can act on.

    Returns fixes, not scores. Each names the measured value, the cohort's, and
    the bound, so the writer is told what is wrong rather than ordered to hit a
    target. A channel with no measured corpus is not gated — see
    SKELETON_BOUNDS.
    """
    bounds = SKELETON_BOUNDS.get(channel_id or "")
    if not bounds:
        return []
    sk = analyse("draft", "draft", "ours", re.sub(r"^\[.*?\]\s*$", " ",
                                                  text or "", flags=re.M))
    out: list[str] = []
    if sk.words < 200:                 # a fragment has no measurable rhythm
        return out
    medians = COHORT_MEDIANS.get(channel_id, {})
    for key, (low, high) in bounds.items():
        got = _metric(sk, key)
        if got is None:
            # ABSENT IS NOT "NOTHING TO JUDGE". A position metric reads None
            # when the thing never happens at all, and against a CEILING that
            # is the worst possible case, not an exemption: the draft measured
            # here contained no number anywhere, which is further from the
            # genre than arriving late. Skipping it let a script with zero
            # concrete anchors pass a bound written to require early ones.
            if high is not None:
                what, unit = _LABELS[key]
                out.append(
                    f"{what.upper()} never appears at all ({unit}); competitors "
                    f"in this niche run {medians.get(key, '?')} and the ceiling "
                    f"for this channel is {high}. "
                    + _ADVICE.get((key, "max"), ""))
            continue
        # Rhythm read off the 14-word fallback chunker is not a sentence
        # length; refuse to judge it rather than judge it wrongly.
        if key in ("median_sentence_words", "sentence_len_spread") \
                and not sk.punctuated:
            continue
        if low is not None and got < low:
            side, bound = "min", low
        elif high is not None and got > high:
            side, bound = "max", high
        else:
            continue
        what, unit = _LABELS[key]
        limit = ("the floor for this channel is" if side == "min"
                 else "the ceiling for this channel is")
        out.append(
            f"{what.upper()} is {got} ({unit}); competitors in this niche run "
            f"{medians.get(key, '?')} and {limit} {bound}. "
            + _ADVICE.get((key, side), ""))
    return out


def skeleton_report(text: str, channel_id: str = "") -> dict:
    """Full measurement of one draft beside its own cohort. Advisory."""
    sk = analyse("draft", "draft", "ours",
                 re.sub(r"^\[.*?\]\s*$", " ", text or "", flags=re.M))
    return {"measured": sk.__dict__,
            "channel_id": channel_id,
            "cohort_median": dict(COHORT_MEDIANS.get(channel_id, {})),
            "bounds": {k: list(v) for k, v in
                       SKELETON_BOUNDS.get(channel_id, {}).items()},
            "out_of_bounds": skeleton_problems(text, channel_id)}
