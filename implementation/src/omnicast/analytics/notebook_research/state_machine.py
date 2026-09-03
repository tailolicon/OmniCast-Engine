"""Run state machine for the NotebookLM browser worker.

Every transition is persisted to the manifest BEFORE the action that follows
it, so a killed process resumes exactly where it stopped (a machine dying in
WAIT_FOR_INDEXING must not re-upload sources). Pure code — no browser here.
"""

from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    START = "START"
    AUTH_CHECK = "AUTH_CHECK"
    AUTH_REQUIRED = "AUTH_REQUIRED"          # terminal for this provider → native fallback
    RESOLVE_NOTEBOOK = "RESOLVE_NOTEBOOK"
    UPLOAD_SOURCES = "UPLOAD_SOURCES"
    WAIT_FOR_INDEXING = "WAIT_FOR_INDEXING"
    SOURCE_AUDIT = "SOURCE_AUDIT"
    RUN_RESEARCH_PROMPTS = "RUN_RESEARCH_PROMPTS"
    CAPTURE_RESPONSES = "CAPTURE_RESPONSES"
    VALIDATE = "VALIDATE"
    INGEST = "INGEST"
    COMPLETE = "COMPLETE"                    # terminal
    FAILED = "FAILED"                        # terminal (trace + screenshot saved)


TERMINAL = {RunState.COMPLETE, RunState.FAILED, RunState.AUTH_REQUIRED}

# The only legal moves. Anything else is a bug, not a retry.
TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.START: {RunState.AUTH_CHECK},
    RunState.AUTH_CHECK: {RunState.AUTH_REQUIRED, RunState.RESOLVE_NOTEBOOK},
    RunState.AUTH_REQUIRED: set(),
    RunState.RESOLVE_NOTEBOOK: {RunState.UPLOAD_SOURCES, RunState.FAILED},
    RunState.UPLOAD_SOURCES: {RunState.WAIT_FOR_INDEXING, RunState.FAILED},
    RunState.WAIT_FOR_INDEXING: {RunState.SOURCE_AUDIT, RunState.FAILED},
    RunState.SOURCE_AUDIT: {RunState.RUN_RESEARCH_PROMPTS, RunState.FAILED},
    RunState.RUN_RESEARCH_PROMPTS: {RunState.CAPTURE_RESPONSES, RunState.FAILED},
    RunState.CAPTURE_RESPONSES: {RunState.VALIDATE, RunState.FAILED},
    RunState.VALIDATE: {RunState.INGEST, RunState.FAILED},
    RunState.INGEST: {RunState.COMPLETE, RunState.FAILED},
    RunState.COMPLETE: set(),
    RunState.FAILED: set(),
}

# Where a resumed run re-enters for each recorded state: idempotent stages
# re-run themselves; completed stages are skipped by their own manifests.
RESUME_AT: dict[RunState, RunState] = {
    RunState.START: RunState.AUTH_CHECK,
    RunState.AUTH_CHECK: RunState.AUTH_CHECK,
    RunState.AUTH_REQUIRED: RunState.AUTH_CHECK,   # user may have re-logged in
    RunState.RESOLVE_NOTEBOOK: RunState.RESOLVE_NOTEBOOK,
    RunState.UPLOAD_SOURCES: RunState.UPLOAD_SOURCES,       # dedupe via manifest
    RunState.WAIT_FOR_INDEXING: RunState.WAIT_FOR_INDEXING,  # never re-upload
    RunState.SOURCE_AUDIT: RunState.SOURCE_AUDIT,
    RunState.RUN_RESEARCH_PROMPTS: RunState.RUN_RESEARCH_PROMPTS,  # prompt-level dedupe
    RunState.CAPTURE_RESPONSES: RunState.RUN_RESEARCH_PROMPTS,
    # VALIDATE re-enters at the prompts stage: failed prompt jobs must get
    # their retry (completed ones are hash-deduped), THEN validation reruns.
    RunState.VALIDATE: RunState.RUN_RESEARCH_PROMPTS,
    RunState.INGEST: RunState.VALIDATE,   # validation is cheap; re-verify before ingest
    RunState.COMPLETE: RunState.COMPLETE,
    RunState.FAILED: RunState.AUTH_CHECK,  # a fresh attempt starts from auth
}


class IllegalTransition(RuntimeError):
    pass


def advance(current: RunState, nxt: RunState) -> RunState:
    if nxt not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current.value} -> {nxt.value} is not a legal move")
    return nxt


def resume_point(recorded: RunState) -> RunState:
    return RESUME_AT[recorded]
