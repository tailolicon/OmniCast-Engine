"""Binary eval functions — code-based, no LLM needed.

Each eval is a pure function: ScriptDraft -> bool
True = pass, False = fail

Based on PROJECT_CONTEXT.md Section 12B.
"""

from __future__ import annotations

from omnicast.models.script import ScriptDraft

# Common AI cliches to detect
AI_CLICHE_LIST = [
    "delve", "tapestry", "realm", "landscape", "paradigm",
    "synergy", "holistic", "leverage", "robust", "seamless",
    "cutting-edge", "game-changer", "unlock", "empower",
    "in today's fast-paced world", "let's dive in",
    "without further ado", "buckle up",
]


def eval_hook_under_15_words(draft: ScriptDraft) -> bool:
    """Hook should be concise — under 15 words."""
    return len(draft.hook.split()) <= 15


def eval_no_ai_cliches(draft: ScriptDraft) -> bool:
    """No AI cliche phrases in the full text."""
    full_text = draft.hook + " " + " ".join(s.content for s in draft.segments)
    text_lower = full_text.lower()
    return not any(cliche.lower() in text_lower for cliche in AI_CLICHE_LIST)


def eval_has_pattern_interrupt(draft: ScriptDraft) -> bool:
    """At least 2 segments have pattern_interrupt = True."""
    count = sum(1 for s in draft.segments if s.has_pattern_interrupt)
    return count >= 2


def eval_intro_under_30s(draft: ScriptDraft) -> bool:
    """First segment (intro) should be ≤ 30 seconds."""
    if not draft.segments:
        return False
    return draft.segments[0].estimated_duration_seconds <= 30


def eval_segment_under_90s(draft: ScriptDraft) -> bool:
    """All segments should be ≤ 90 seconds."""
    return all(s.estimated_duration_seconds <= 90 for s in draft.segments)


def eval_under_target_duration(draft: ScriptDraft, max_seconds: int = 900) -> bool:
    """Total duration within target."""
    return draft.estimated_duration_seconds <= max_seconds


def eval_has_outro(draft: ScriptDraft) -> bool:
    """Script should have an outro."""
    return len(draft.outro.strip()) > 0


def eval_word_count_reasonable(draft: ScriptDraft) -> bool:
    """Word count between 800 and 3000 (5-20 min video)."""
    return 800 <= draft.word_count <= 3000


# Registry of all evals
WRITER_EVALS: dict[str, callable] = {
    "hook_under_15_words": eval_hook_under_15_words,
    "no_ai_cliches": eval_no_ai_cliches,
    "has_pattern_interrupt": eval_has_pattern_interrupt,
    "intro_under_30s": eval_intro_under_30s,
    "segment_under_90s": eval_segment_under_90s,
    "has_outro": eval_has_outro,
    "word_count_reasonable": eval_word_count_reasonable,
}


def run_binary_evals(
    draft: ScriptDraft,
    evals: dict[str, callable] | None = None,
) -> dict[str, bool]:
    """Run all binary evals on a draft. Returns {eval_name: pass/fail}."""
    if evals is None:
        evals = WRITER_EVALS
    results: dict[str, bool] = {}
    for name, fn in evals.items():
        try:
            results[name] = fn(draft)
        except Exception:
            results[name] = False
    return results
