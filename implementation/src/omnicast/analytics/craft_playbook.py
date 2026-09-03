"""Compile craft forensics into a playbook a writer can actually USE.

The v1 playbook was 436 words of received wisdom. This one carries only what
a model cannot invent about THIS niche:

  1. MEASURED TARGETS — winner medians on metrics where winners and controls
     genuinely differ (a shared genre convention teaches nothing);
  2. A BEAT MAP in seconds — when the first number lands, when money lands,
     when "you" first appears, the cadence between numbers afterwards;
  3. AN EXEMPLAR BANK — real winner openings and transitions, attributed, for
     RHYTHM ONLY. Copying wording is blocked upstream (competitor_evidence's
     8-gram check) and restated here as a hard rule, because a style reference
     that gets paraphrased into the script is plagiarism with extra steps.
  4. A CONTRAST TABLE — the same slot as written by controls, so the model can
     see what losing looks like rather than guessing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_SENT = re.compile(r"(?<=[.!?])\s+")


def _first_sentences(text: str, n: int = 2, cap: int = 190) -> str:
    parts = [p.strip() for p in _SENT.split(text or "") if p.strip()]
    return " ".join(parts[:n])[:cap]


def _fmt(v, unit: str = "s") -> str:
    return "—" if v is None else f"{v}{unit}"


def compile_craft_playbook(forensics: dict, *, max_exemplars: int = 6) -> str:
    """Render the injectable playbook from a craft_forensics.json dict.

    EVIDENCE GRADE DECIDES VOICE (operator audit 27/07). The first version
    printed every median gap as a beat-map fact ("winners get to the money a
    minute and a half earlier"), and those gaps did not survive a bootstrap CI,
    an effect-size check or a cross-channel consistency check. A writer told a
    hypothesis in the voice of a rule will follow it like a rule.
    """
    videos = forensics.get("videos", [])
    cohort = forensics.get("cohort", {})
    metrics = cohort.get("metrics", {})
    win = [v for v in videos if v.get("role") == "winner"]
    ctl = [v for v in videos if v.get("role") == "control"]

    def m(key: str, field: str = "winner_median"):
        return (metrics.get(key) or {}).get(field)

    def grade(key: str) -> str:
        return (metrics.get(key) or {}).get("evidence_grade", "no_signal")

    rules = {k: v for k, v in metrics.items()
             if v.get("evidence_grade") == "rule"}
    hypotheses = {k: v for k, v in metrics.items()
                  if v.get("evidence_grade") == "hypothesis"}

    # TWO DIFFERENT CHANNEL COUNTS, AND THE HEADER USED TO SHOW ONLY THE
    # FLATTERING ONE. `cohort["channels"]` is every channel the corpus was
    # scraped from; a channel only reaches the statistics if it contributed
    # BOTH a winner and a control with usable captions. Printing six while
    # three were compared reads as six channels' worth of evidence.
    corpus_channels = list(cohort.get("channels", []))
    compared = max((v.get("channels_compared") or 0)
                   for v in metrics.values()) if metrics else 0

    lines: list[str] = []
    lines.append(
        f"MEASURED FROM {len(win)} WINNER + {len(ctl)} CONTROL VIDEOS IN THIS "
        f"NICHE (their own timed captions).")
    lines.append(
        f"  corpus scraped from {len(corpus_channels)} channels "
        f"({', '.join(corpus_channels) or 'n/a'}); "
        f"{compared} of them contributed both a winner and a control and so "
        f"carry the comparison. Every claim below rests on those "
        f"{compared}.")
    lines.append("")
    if rules:
        lines.append("── RULES (CI excludes zero, real effect size, same "
                     "direction in 3+ channels) ──")
        for k, v in rules.items():
            lines.append(f"  • {k}: winner {v.get('winner_median')} vs control "
                         f"{v.get('control_median')} "
                         f"(CI {v.get('ci95_of_median_diff')}, "
                         f"δ={v.get('cliffs_delta')}, "
                         f"{v.get('channels_same_direction')}/"
                         f"{v.get('channels_compared')} channels agree)")
    else:
        lines.append("── RULES ──")
        lines.append("  • NONE. No measured difference in this cohort survived "
                     "all three checks (bootstrap CI excluding zero, "
                     "non-negligible effect size, agreement across 3+ "
                     "channels). Write from the qualitative shapes below and "
                     "from the channel's own steering — do NOT treat any number "
                     "in this file as a target.")
    if hypotheses:
        lines.append("")
        lines.append("── HYPOTHESES (suggestive only — never optimise against "
                     "these; they may be channel-mix artefacts) ──")
        for k, v in hypotheses.items():
            lines.append(f"  • {k}: winner {v.get('winner_median')} vs control "
                         f"{v.get('control_median')} "
                         f"({v.get('channels_same_direction')}/"
                         f"{v.get('channels_compared')} channels agree)")
    lines.append("")
    lines.append("── HOW WINNERS OPEN (first sentences, verbatim, ATTRIBUTED) ──")
    lines.append("  STYLE REFERENCE ONLY. Never reuse these words, phrases, examples "
                 "or names. Copy the SHAPE: what kind of thing is said first.")
    for v in win[:max_exemplars]:
        lines.append(f"  • [{v.get('video_id')}] {_first_sentences(v.get('opening_30s', ''))}")
    lines.append("")
    # "LOSERS" is a verdict the data never delivered. These are matched
    # CONTROLS: same channel, same format, similar length and date, ordinary
    # views/day. Several are good videos. The word primed the writer to read
    # every control opening as a mistake to avoid.
    lines.append("── HOW MATCHED CONTROLS OPEN (same slot, ordinary views/day) ──")
    for v in ctl[:max_exemplars]:
        lines.append(f"  • [{v.get('video_id')}] {_first_sentences(v.get('opening_30s', ''))}")
    lines.append("")
    lines.append(
        "  OBSERVATION (qualitative, NOT a measured rule): reading these two "
        "lists side by side, winner openings lean toward something that "
        "HAPPENED or something the narrator will DO for the viewer — a named "
        "report, a new proposal, one person's story, an explicit promise of a "
        "calculation — while control openings lean toward an abstract "
        "condition that might apply (\"premiums could double\"). Counter-"
        "examples exist in both lists; nobody has tested this shape "
        "statistically. Treat it as a lens for reading the exemplars, not as "
        "an instruction. The script's own steering file decides how to open.")

    trans = [t for v in win for t in (v.get("transitions") or [])][:8]
    if trans:
        lines.append("")
        lines.append("── HOW WINNERS ANNOUNCE A TURN (rhythm reference) ──")
        for t in trans:
            lines.append(f"  • {t.strip()[:140]}")

    # RELIABILITY FILTER: a per-1k metric whose medians are near zero is
    # detector noise, not a finding — reporting "winners react less (0.2 vs
    # 2.3)" as a target would teach the writer to strip the very warmth this
    # channel is short of. Only densities with real mass are shown.
    register = {
        k: v for k, v in hypotheses.items()
        if not k.startswith("first_") and k != "number_gap_median_s"
        and max(v.get("winner_median") or 0, v.get("control_median") or 0) >= 5
    }
    if register:
        lines.append("")
        lines.append("── REGISTER (hypothesis-grade, winner vs control) ──")
        for k, v in register.items():
            lines.append(f"  • {k}: winner {v.get('winner_median')} vs control "
                         f"{v.get('control_median')}")
        lines.append(
            "  HOW TO READ THIS: these gaps are hypothesis-grade — none of them "
            "survived the evidence checks, and nothing here explains WHY the "
            "numbers differ. (An earlier version of this file asserted the "
            "cohort is less chatty *because* a credentialed human is on camera. "
            "That was a story about the data, not a finding from it.) "
            "The one thing that follows directly: a lower conversational "
            "density is NOT a demonstrated success factor, so do not chase it. "
            "This channel is faceless with a synthetic voice, so its own "
            "spoken-presence mechanics stay governed by the rubric, not by "
            "these medians.")

    non_disc = [k for k, v in metrics.items()
                if v.get("evidence_grade") == "no_signal"]
    if non_disc:
        lines.append("")
        lines.append("── NOT A DIFFERENTIATOR (genre convention — do not over-optimise) ──")
        lines.append("  " + ", ".join(non_disc))

    lines.append("")
    lines.append(
        "COMPLIANCE CONSTRAINT (this one IS a hard rule, and it comes from "
        "policy, not from the cohort): several of these channels build "
        "authority on first-person advisor credentials (\"as a financial "
        "advisor…\"). THIS CHANNEL IS BANNED from that — YMYL plus a synthetic "
        "voice. Source authority from the documents instead. Note what this "
        "rule does NOT say: it prescribes no opening shape and no timing. "
        "\"Money early\" in particular was removed — first_money_s is "
        f"{grade('first_money_s')} in this cohort.")
    return "\n".join(lines)


def compile_writer_playbook(forensics: dict) -> str:
    """Compile only evidence that is eligible to steer production.

    ``compile_craft_playbook`` is a research report: it intentionally contains
    hypotheses, contrast examples and qualitative interpretation so an analyst
    can inspect the cohort. Feeding that prose to a language model turns every
    caveated observation into a potential instruction. This artifact therefore
    carries RULE-grade differences only. If the cohort found none, it says none
    and contributes no craft instruction.
    """
    cohort = forensics.get("cohort", {})
    videos = forensics.get("videos", [])
    metrics = cohort.get("metrics", {})
    rules = {
        key: value for key, value in metrics.items()
        if value.get("evidence_grade") == "rule"
    }
    winners = sum(1 for v in videos if v.get("role") == "winner")
    controls = sum(1 for v in videos if v.get("role") == "control")
    compared = max(
        (int(v.get("channels_compared") or 0) for v in metrics.values()),
        default=0,
    )

    lines = [
        "PRODUCTION-ELIGIBLE COMPETITOR CRAFT RULES",
        f"Measured from {winners} winner + {controls} control transcripts; "
        f"{compared} channels contributed comparable pairs.",
        "",
    ]
    if not rules:
        lines += [
            "RULES: NONE.",
            "This cohort produced no script-craft instruction strong enough to "
            "steer the Writer. Use the channel editorial contract and policy; "
            "do not infer a target from medians, examples, or hypotheses.",
        ]
    else:
        lines.append(
            "RULES (bootstrap CI excludes zero, non-negligible effect, and "
            "same direction across at least three channels):")
        for key, value in rules.items():
            lines.append(
                f"- {key}: winner median {value.get('winner_median')} vs "
                f"control median {value.get('control_median')}; "
                f"CI {value.get('ci95_of_median_diff')}; "
                f"effect {value.get('cliffs_delta')}; "
                f"{value.get('channels_same_direction')}/"
                f"{value.get('channels_compared')} channels agree.")

    lines += [
        "",
        "POLICY (not a cohort finding): never claim advisor/CPA credentials, "
        "clients, or first-hand professional experience for a synthetic host. "
        "Authority comes from traceable primary documents.",
    ]
    return "\n".join(lines)


def load_and_compile(path: Path, **kw) -> str:
    return compile_craft_playbook(
        json.loads(Path(path).read_text(encoding="utf-8")), **kw)
