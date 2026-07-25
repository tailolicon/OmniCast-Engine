"""How many competitor videos already cover a topic — measured, not assumed.

WHY THIS EXISTS (P0.1 group 3, strategic review §3.3):

`TopicScorer._calc_gap_score` reads `raw_metrics["similar_competitor_videos"]`
and moves the score by up to 14 points on it. No scanner ever wrote that key.
The dimension therefore existed, was documented, was tested with hand-built
dicts — and was dead on every real run. This module is the measurement.

Two properties matter more than cleverness here:

* DETERMINISTIC AND CHEAP. It runs over titles already fetched for the scan, so
  it costs no extra quota and no LLM call, and it returns the same answer twice.
* IT REFUSES TO ANSWER ON A THIN CORPUS. Scoring an "empty space" bonus after
  looking at eleven videos is how an unresearched topic comes to look like a
  discovery — the exact conflation `_calc_gap_score` warns about in its own
  docstring. Below `MIN_CORPUS_FOR_COVERAGE` the caller is told "unknown", and
  the scorer's missing-signal path (neutral) applies.
"""

from __future__ import annotations

import re

# Below this many competitor videos in the scanned corpus, "no similar video
# found" carries no information about the market — only about our sample.
MIN_CORPUS_FOR_COVERAGE = 30

# Share of the SHORTER title's content words that must also appear in the other
# one (the overlap coefficient, |A∩B| / min(|A|,|B|)).
#
# Not Jaccard. Jaccard divides by the union, so "Retirement mistakes that cost
# you money" vs "The retirement mistakes nobody warns you about" — the same
# topic by any reading — scores 0.29 purely because both titles carry different
# filler. Penalising a title for being wordy is not a measure of coverage. The
# overlap coefficient asks the question we actually mean: is the shorter title's
# subject contained in the longer one's?
SIMILARITY_THRESHOLD = 0.5
# ...and an absolute floor, because a single shared word gives an overlap of
# 1.0 on a one-word title and means nothing.
MIN_SHARED_TOKENS = 2

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Deliberately small: a topic-word blocklist that grows into a domain lexicon
# starts making editorial decisions nobody reviewed.
_STOPWORDS = frozenset("""
a about after again all also an and any are as at be because been before being
both but by can could did do does during each few for from get got had has have
her here him his how however i if in into is it its just like make made may
might more most much my never new no nobody none nor not now of off on once one
only or other others our out over own per said same she should since so some
such than that the their them then there these they this those though through
thus to too under until up upon us use used using very via was way we were what
when where whether which while who whom whose why will with within without
would yet you your yours
""".split())


def content_tokens(title: str) -> frozenset[str]:
    """Lowercase content words of a title, stopwords and 1-2 char tokens removed."""
    return frozenset(
        tok for tok in _TOKEN_RE.findall((title or "").lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    )


def titles_are_similar(a: str, b: str, *, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """Whether two titles plausibly cover the same topic."""
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    if len(shared) < MIN_SHARED_TOKENS:
        return False
    return len(shared) / min(len(ta), len(tb)) >= threshold


def count_similar(
    title: str,
    corpus_titles: list[str],
    *,
    exclude_index: int | None = None,
    threshold: float = SIMILARITY_THRESHOLD,
) -> int:
    """How many OTHER titles in the corpus cover the same topic."""
    total = 0
    for idx, other in enumerate(corpus_titles):
        if idx == exclude_index:
            continue
        if titles_are_similar(title, other, threshold=threshold):
            total += 1
    return total


def coverage_of(
    title: str,
    corpus_titles: list[str],
    *,
    exclude_index: int | None = None,
    min_corpus: int = MIN_CORPUS_FOR_COVERAGE,
) -> int | None:
    """Coverage count, or None when the corpus is too thin to support a claim.

    None is the honest answer, and the scorer already treats a missing signal as
    neutral. Returning 0 here instead would hand out the full "nobody has
    covered this" bonus on the strength of a small sample."""
    if len(corpus_titles) < min_corpus:
        return None
    return count_similar(title, corpus_titles, exclude_index=exclude_index)
