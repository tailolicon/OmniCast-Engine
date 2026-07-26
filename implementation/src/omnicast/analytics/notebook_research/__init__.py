"""NotebookLM browser research runner (challenger provider).

Architecture (GPT proposal 2026-07-26, user-approved):
    Playwright worker (happy path, state machine, idempotent manifest)
  + Claude browser supervisor (UI-drift recovery, allowlisted actions only)
  + Native Learner as failover — an AUTH/UI failure here must never stop it.

NotebookLM findings NEVER go straight to the vault: they pass
`analytics.competitor_evidence.validate_findings` (code-level evidence check),
then the reconciler compares them against Native Learner output, and only then
does `intel_gate` decide what the Writer may read.
"""
