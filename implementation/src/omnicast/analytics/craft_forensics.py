"""Craft forensics — measure HOW winners actually write and pace, from their
own timed captions.

The first compiled playbook was 436 words of received wisdom ("plant an open
loop", "conversational but urgent"). A writer model already knows that; it
learns nothing. What it cannot invent is the MEASURED shape of a winning video
in this niche: the second the first hard number lands, how often numbers keep
landing, how the narrator reacts to their own figures, how sections are
announced out loud, how long they let a sentence run.

This module reads timed VTT captions (already on disk from the cohort fetch)
and produces:

  * a BEAT MAP in seconds (first number, first question, first "you", section
    signposts, CTA position, density curve per minute);
  * QUANTITATIVE TARGETS (numbers per minute, words per sentence, contraction
    rate, reaction/invitation density) as winner-vs-control deltas;
  * an EXEMPLAR BANK of short, attributed openings and transitions to imitate
    in RHYTHM — never in wording (an anti-copy n-gram check is enforced by
    compliance.competitor_evidence before anything reaches a script).

Everything here is descriptive measurement of files we already fetched; no
network, no model calls.
"""

from __future__ import annotations

import random
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

# Reuse the spoken-presence detectors so the numbers we demand of our own
# writer are measured the SAME way on the competition.
from omnicast.agents.rubrics.finance_explainer import (
    _COMPANION_RE,
    _CONTRACTION_RE,
    _INVITATION_RE,
    _REACTION_RE,
    _SIGNPOST_RE,
)

_TS = re.compile(r"^(\d\d):(\d\d):(\d\d\.\d\d\d) --> ")
_TAG = re.compile(r"<[^>]+>")
# DOLLARS only — "40 percent" is a different beat from "$2,040", and the
# playbook reports this as "first dollar figure". A regex that quietly widens
# its own label is how a measurement stops meaning what it says.
_MONEY = re.compile(
    r"\$\s?[\d,]+(?:\.\d+)?"
    r"|\b[\d,]+(?:\.\d+)?\s?(?:dollars|bucks)\b", re.IGNORECASE)
_ANYNUM = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_QUESTION = re.compile(r"\?")
_SECOND_PERSON = re.compile(r"\byou(?:r|'re|'ve|'ll)?\b", re.IGNORECASE)
_CTA = re.compile(
    r"\b(?:subscribe|hit (?:that )?like|tap like|comment below|let me know|"
    r"tell me in the comments|link (?:below|in the description))\b", re.IGNORECASE)


@dataclass
class TimedLine:
    t: float
    text: str


@dataclass
class VideoCraft:
    video_id: str
    role: str = ""
    channel: str = ""
    duration_s: float = 0.0
    words: int = 0
    # beat map (seconds; None = never happens)
    first_number_s: float | None = None
    first_money_s: float | None = None
    first_question_s: float | None = None
    first_you_s: float | None = None
    first_cta_s: float | None = None
    signpost_times: list[float] = field(default_factory=list)
    numbers_per_min: float = 0.0
    number_gap_median_s: float | None = None
    # register
    words_per_sentence: float = 0.0
    contractions_per_1k: float = 0.0
    reactions_per_1k: float = 0.0
    invitations_per_1k: float = 0.0
    companionship_per_1k: float = 0.0
    questions_per_1k: float = 0.0
    second_person_per_1k: float = 0.0
    matched_control: str = ""
    opening_30s: str = ""
    transitions: list[str] = field(default_factory=list)


def parse_vtt(path: Path) -> list[TimedLine]:
    """Timed caption lines, de-duplicated (YouTube VTT repeats rolling text)."""
    out: list[TimedLine] = []
    t: float | None = None
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _TS.match(raw)
        if m:
            h, mi, s = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + float(s)
            continue
        if t is None or not raw.strip() or raw.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        line = _TAG.sub("", raw).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(TimedLine(t, line))
    return out


def _first_time(lines: list[TimedLine], pattern: re.Pattern) -> float | None:
    for ln in lines:
        if pattern.search(ln.text):
            return ln.t
    return None


def analyse_vtt(path: Path, *, video_id: str = "", role: str = "",
                channel: str = "", matched_control: str = "") -> VideoCraft:
    lines = parse_vtt(path)
    if not lines:
        return VideoCraft(video_id=video_id or path.stem, role=role,
                          channel=channel, matched_control=matched_control)
    text = " ".join(ln.text for ln in lines)
    words = max(1, len(text.split()))
    duration = lines[-1].t or 1.0
    per_1k = 1000.0 / words

    num_times = [ln.t for ln in lines if _ANYNUM.search(ln.text)]
    gaps = [b - a for a, b in zip(num_times, num_times[1:]) if b > a]
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.split()]

    # opening: everything spoken in the first 30 seconds (rhythm reference)
    opening = " ".join(ln.text for ln in lines if ln.t <= 30.0)
    # transitions: the SENTENCE around each signpost, not the caption line —
    # caption boundaries cut mid-clause ("than $200. Next up, transportation.")
    # and a fragment teaches rhythm nothing.
    _sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    transitions = [s for s in _sents
                   if _SIGNPOST_RE.search(s) and 4 <= len(s.split()) <= 32][:12]

    return VideoCraft(
        video_id=video_id or path.stem,
        role=role,
        channel=channel,
        matched_control=matched_control,
        duration_s=round(duration, 1),
        words=words,
        first_number_s=_first_time(lines, _ANYNUM),
        first_money_s=_first_time(lines, _MONEY),
        first_question_s=_first_time(lines, _QUESTION),
        first_you_s=_first_time(lines, _SECOND_PERSON),
        first_cta_s=_first_time(lines, _CTA),
        signpost_times=[ln.t for ln in lines if _SIGNPOST_RE.search(ln.text)][:20],
        numbers_per_min=round(len(num_times) / max(1.0, duration / 60.0), 2),
        number_gap_median_s=(round(statistics.median(gaps), 1) if gaps else None),
        words_per_sentence=round(words / max(1, len(sentences)), 1),
        contractions_per_1k=round(len(_CONTRACTION_RE.findall(text)) * per_1k, 1),
        reactions_per_1k=round(len(_REACTION_RE.findall(text)) * per_1k, 1),
        invitations_per_1k=round(len(_INVITATION_RE.findall(text)) * per_1k, 1),
        companionship_per_1k=round(len(_COMPANION_RE.findall(text)) * per_1k, 1),
        questions_per_1k=round(len(_QUESTION.findall(text)) * per_1k, 1),
        second_person_per_1k=round(len(_SECOND_PERSON.findall(text)) * per_1k, 1),
        opening_30s=opening[:900],
        transitions=transitions,
    )


def _median(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


FIELDS = ("first_number_s", "first_money_s", "first_question_s", "first_you_s",
          "first_cta_s", "numbers_per_min", "number_gap_median_s",
          "words_per_sentence", "contractions_per_1k", "reactions_per_1k",
          "invitations_per_1k", "companionship_per_1k", "questions_per_1k",
          "second_person_per_1k")


def _bootstrap_ci(win: list[float], ctl: list[float], *, iters: int = 2000,
                  seed: int = 12345) -> tuple[float, float] | None:
    """Percentile CI for the winner−control median difference.

    A 15%-of-median rule (the first version of this function) has no notion of
    spread: with 41 vs 32 noisy videos it labelled five metrics
    "discriminating" that a proper test could not separate from zero."""
    if len(win) < 5 or len(ctl) < 5:
        return None
    rnd = random.Random(seed)
    diffs = []
    for _ in range(iters):
        a = [win[rnd.randrange(len(win))] for _ in win]
        b = [ctl[rnd.randrange(len(ctl))] for _ in ctl]
        diffs.append(statistics.median(a) - statistics.median(b))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    return round(lo, 3), round(hi, 3)


def _cliffs_delta(win: list[float], ctl: list[float]) -> float | None:
    """Non-parametric effect size in [-1, 1]; |δ|<0.147 is negligible."""
    if not win or not ctl:
        return None
    gt = sum(1 for a in win for b in ctl if a > b)
    lt = sum(1 for a in win for b in ctl if a < b)
    return round((gt - lt) / (len(win) * len(ctl)), 3)


def _paired_stats(crafts: list[VideoCraft], field: str, *,
                  iters: int = 2000, seed: int = 4242) -> dict | None:
    """Within-pair difference stats for one metric.

    Each winner carries `matched_control`; the pair was built inside a channel,
    same format, nearest duration and publish date. Differencing inside the
    pair removes exactly the between-video variance that swamps an unpaired
    median test — which is why the cohort was matched in the first place.
    """
    by_id = {c.video_id: c for c in crafts}
    diffs: list[float] = []
    for c in crafts:
        if c.role != "winner" or not c.matched_control:
            continue
        ctl = by_id.get(c.matched_control)
        if ctl is None:
            continue
        a, b = getattr(c, field), getattr(ctl, field)
        if a is None or b is None:
            continue
        diffs.append(float(a) - float(b))
    if len(diffs) < 4:
        return {"n_pairs": len(diffs), "median_diff": None, "ci95": None,
                "winners_higher": None,
                "note": "too few complete pairs to test"}
    rnd = random.Random(seed)
    boots = []
    for _ in range(iters):
        s = [diffs[rnd.randrange(len(diffs))] for _ in diffs]
        boots.append(statistics.median(s))
    boots.sort()
    lo = round(boots[int(0.025 * len(boots))], 3)
    hi = round(boots[int(0.975 * len(boots)) - 1], 3)
    return {
        "n_pairs": len(diffs),
        "median_diff": round(statistics.median(diffs), 3),
        "ci95": (lo, hi),
        # sign test companion: how often the winner is simply higher
        "winners_higher": round(sum(1 for d in diffs if d > 0) / len(diffs), 3),
    }


def compare_cohort(crafts: list[VideoCraft], *, min_channels: int = 3) -> dict:
    """Winner-vs-control comparison with an honest evidence grade.

    Three hurdles, because pooled medians on an unbalanced cohort produce
    Simpson's-paradox artefacts (the operator audit found exactly one: pooled
    "winners react less" reversed inside the channel that dominates the pool):
      1. a bootstrap 95% CI for the median difference that excludes zero;
      2. a non-negligible Cliff's delta;
      3. the SAME DIRECTION in at least `min_channels` channels.
    Anything short of all three is a `hypothesis`, never a rule.
    """
    win = [c for c in crafts if c.role == "winner"]
    ctl = [c for c in crafts if c.role == "control"]
    by_channel: dict[str, list[VideoCraft]] = {}
    for c in crafts:
        by_channel.setdefault(c.channel or "", []).append(c)

    out: dict[str, dict] = {}
    for f in FIELDS:
        wv = [getattr(c, f) for c in win if getattr(c, f) is not None]
        cv = [getattr(c, f) for c in ctl if getattr(c, f) is not None]
        w, c_ = _median(wv), _median(cv)
        delta = (round(w - c_, 2) if (w is not None and c_ is not None) else None)
        ci = _bootstrap_ci(wv, cv)
        eff = _cliffs_delta(wv, cv)

        # per-channel direction — the Simpson's-paradox check
        dirs: dict[str, int] = {}
        for ch, rows in by_channel.items():
            if not ch:
                continue
            cw = [getattr(x, f) for x in rows
                  if x.role == "winner" and getattr(x, f) is not None]
            cc = [getattr(x, f) for x in rows
                  if x.role == "control" and getattr(x, f) is not None]
            if len(cw) >= 2 and len(cc) >= 2:
                d = statistics.median(cw) - statistics.median(cc)
                dirs[ch] = (1 if d > 0 else (-1 if d < 0 else 0))
        agree = 0
        if delta is not None and dirs:
            want = 1 if delta > 0 else -1
            agree = sum(1 for v in dirs.values() if v == want)

        # PAIRED ANALYSIS — the comparison the cohort was actually built for.
        # Unpaired medians carry every between-video difference (channel voice,
        # topic, length) as noise; a matched pair cancels it, so the same data
        # answers a sharper question: within a pair, does the winner differ?
        paired = _paired_stats(crafts, f)

        ci_excludes_zero = bool(ci and (ci[0] > 0 or ci[1] < 0))
        strong_effect = bool(eff is not None and abs(eff) >= 0.147)
        consistent = agree >= min_channels
        paired_significant = bool(
            paired and paired["n_pairs"] >= 8
            and paired["ci95"] and (paired["ci95"][0] > 0 or paired["ci95"][1] < 0))

        # A rule needs cross-channel agreement AND a difference that survives
        # either the unpaired CI or the (stronger) paired CI.
        grade = ("rule" if (consistent and strong_effect
                            and (ci_excludes_zero or paired_significant))
                 else "hypothesis" if (ci_excludes_zero or strong_effect
                                       or paired_significant)
                 else "no_signal")
        out[f] = {
            "winner_median": w, "control_median": c_, "delta": delta,
            "ci95_of_median_diff": ci, "cliffs_delta": eff,
            "paired": paired,
            "channels_same_direction": agree,
            "channels_compared": len(dirs),
            "evidence_grade": grade,
            # kept for readers of the old key; a rule is the only thing that
            # may become a writer/render directive.
            "discriminating": grade == "rule",
        }
    return {"winner_count": len(win), "control_count": len(ctl),
            "channels": sorted(k for k in by_channel if k),
            "metrics": out}
