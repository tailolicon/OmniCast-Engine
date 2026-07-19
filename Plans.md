# OmniCast Engine Plans.md

Created: 2026-07-15

Spec delta:
- path: `implementation/specs/NARRATIVE_HORROR_GENERATION.md`
- change: channel-scoped quality strategy, forensic quote contract, atomic candidate patches, blind selection, final compilation gate, tiered claims, benchmark contract
- why: scalar scoring plus a single rewrite cannot reliably produce or prove top-channel horror quality

Team validation mode: `subagent` (Architecture, QA, Skeptic/Product)

---

## Phase 1: Maximum-quality creepy script pipeline

Purpose: Raise creepy-script authenticity without reintroducing noisy debate or permitting regressions in clean narration.

| Task | Content | DoD | Depends | Status |
|------|---------|-----|---------|--------|
| 1.1 | Update the narrative spec and named channel quality strategy contract `[tdd:required]` | Spec defines strategy isolation, forensic issues, objective vs editorial gates, bounded calls, release tiers, and benchmark claim | - | cc:完了 |
| 1.2 | Add named channel strategy validation and anti-AI specificity diagnostics `[tdd:required]` | Invalid strategy fails before LLM spend; channel A cannot leak into B; digit and number-word anchors are observed while style heuristics remain editorial flags | 1.1 | cc:完了 |
| 1.3 | Enforce forensic critic and atomic exact-patch contracts `[tdd:required]` | Major/critical issues require a unique quote/anchor; hallucinated quotes cannot edit; a bad/overlapping/oversized edit rejects the entire candidate | 1.1 | cc:完了 |
| 1.4 | Generate two independent patch candidates and select by blind comparison `[tdd:required]` | Original and two candidates are compared anonymously; tie/invalid/low-confidence or any final regression keeps the original; clean stories stay byte-identical | 1.2, 1.3 | cc:完了 |
| 1.5 | Add plan preflight, final compilation authenticity gate, audit stages, and tiered release metadata `[tdd:required]` | Bad plans stop before story spend; annotation starts only after final editorial approval; metadata never equates critic score with competitive validation | 1.4 | cc:完了 |
| 1.6 | Run full regression, independent review, and a paid end-to-end creepy script test `[tdd:required]` | Unit suite and VO hash checks pass; paid artifact reports all-attempt cost/latency and no critical/major review finding remains | 1.5 | **cc:REOPENED** (see note) |

**Task 1.6 reopened (2026-07-17).** It was marked complete while *both* clauses of its
own DoD were false, and the 07:33 artifact is what made that visible:

- *"paid artifact reports all-attempt cost/latency"* — it did not. `narrative_audit.json`
  recorded `attempt: 2` with `call_counts.planner: 1`: the per-run counters reset each
  attempt, so attempt 1's spend was billed to nobody. All-attempt accounting
  (`attempts_executed`, `attempt_summaries`, `aggregate_call_counts`,
  `aggregate_cost_usd`, `aggregate_latency_s`) exists now, including for runs where
  every attempt aborts (`NarrativeRunExhausted.evidence`, persisted by `_step_script`
  as `narrative_failure_audit.json`).
- *"no critical/major review finding remains"* — an independent manual audit of that
  artifact found several majors (impossible fence-gap traversal, shared beat sheet,
  topic mismatch, missing child-safety response, forbidden ending, unspoken locked age).

The accounting half is now implemented and unit-tested. The review half cannot be closed
by code: it needs a **new** paid end-to-end run whose artifact is independently reviewed
with no critical/major finding. 1.6 stays REOPENED until that run exists, and 2.1
depends on it, so 2.1 cannot close first.

**Second live run (2026-07-17 13:34) — no script, and 1.6 stays REOPENED.**
`output/products/true_dread_files_us/20260717_1334_3_true_encounters_while_servicing_vending_machines/narrative_failure_audit.json`

| | |
|---|---|
| Wall clock | **575.1s** (9.6 min) |
| Calls | `planner=6`, `plan_audit=10`, `plan_audit_escalation=5`, **`story_writer=0`**, everything after = 0 |
| Marginal cost | `0.0` — Claude CLI bills a subscription and reports zero; every DeepSeek primary audit failed before returning a billable response |
| Result | **No script.** Two outer attempts, both `plan_blocked`; five rejected plans persisted |

What went right: the run **failed safely**. Nothing was drafted against a premise that
had not passed its audit, and the failure audit persisted, which is the only reason any
of this is known. Most of the audit was also correct and valuable — cart/man geometry,
an exterior latch thrown from inside, an escape route running toward the threat, an
active brew cycle after the mains were cut, a trade tech skipping the obvious diagnostic.

What it exposed, now fixed (see the spec's "Release integrity" §3-§8):

1. **Provider health was masked by escalation.** All ten DeepSeek primary audits failed;
   Claude escalation answered all five audits; the audit reported clean. Had a plan
   passed, the run would have paid for three Opus drafts and only then found the
   DeepSeek scorer/compliance/final-editor unreachable. `primary_healthy`,
   `primary_provider_errors` and `verdict_source` now survive escalation, and a
   **provider health domain** (account, not model name — `v4-pro` and `v4-flash` are one
   balance) aborts before the writer when a mandatory post-writer judge has no healthy
   independent fallback.
2. **Rejection reasons were not aligned per plan.** Five plans, one trailing blocker
   list. Now one typed `PlanRejection` per plan, with stage, exact errors, fingerprint,
   digest, audit and call counts.
3. **One blocker was overclaimed** — "a staffed, lit valet booth at a hospital-adjacent
   garage at 1:25 a.m. is wrong trade knowledge" killed a concept. Some hospitals do
   staff overnight valet; absent a plan stating the hours that is site-specific
   uncertainty. `PlanIssue` now requires an exact plan quote, and a `site_specific`
   major is demoted to a recommendation. Legitimate geometry/hardware/electrical/trade
   contradictions still block.
4. **Six full replans for local defects.** Bounded targeted repair now fixes only the
   blocked stories, keeps approved story plans byte-identical, and re-runs every gate.
5. **One concept lost to a missing `story_2.voice_rules`.** Schema failures now earn one
   contract-only retry and are recorded in the rejection history.

**Third run (2026-07-17 14:02) — health-gate check, MANUALLY STOPPED, not a live
result.** `implementation/output/opus48_healthgate_20260717_140248.stdout.log`: ~9.5
minutes, 11 Claude Opus CLI calls, **zero writer calls**. It proved the writer gate held
— nothing was drafted against an unaudited or unjudgeable premise — but it had to be
killed by hand, and *why* it needed killing is the defect: the health gate ran **after**
the planner loop, so a plan that kept getting blocked kept being repaired and re-planned
against a provider the first audit had already proved dead. Two fixes:

1. **Abort/fall back at the first audit.** Health is knowable there and is acted on
   there — before plan-contract retry, targeted repair, a new planner attempt, or writer
   spend. The blocked plan is recorded as evidence first, so the abort still carries the
   premise and its reasons. A dead health domain is never dialled again: `_audit_plan`
   skips the primary, and each mandatory judge routes to its fallback under its own
   counter (`critic_score_escalation`, `final_editor_escalation`,
   `story_compliance_escalation`, `annotation_escalation`). That run should have been
   `planner=1`, two bounded primary retries, one escalated audit, then abort.
2. **A complete subscription-CLI fallback path**, so live generation can continue
   without DeepSeek balance. Cross-provider primary routing is unchanged and DeepSeek is
   still tried first while healthy; its 402 now switches *all later mandatory judging* to
   Sonnet instead of repeating dead calls. Roles are explicit and env-overridable
   (planner Sonnet, writer Opus under `OMNICAST_NARRATIVE_MAX_QUALITY=1`, judge/
   compliance/final/annotation fallback Sonnet, challenger Opus), resolved per run
   through `LLMClient`/`ClaudeCLIClient` with no global settings mutation. The compliance
   fallback is deliberately not `deepseek-v4-pro`: same account, same outage. The
   challenger stays Opus so it differs from the Sonnet judges that approve on the
   fallback path — independence is now measured against the judges that **actually ran**
   (`judge_identities`), not the ones the wiring nominated.

**Fourth run (2026-07-17 14:32) — first max-quality fallback attempt, MANUALLY STOPPED
after ~31 minutes with ZERO writer calls.**
`implementation/output/max_quality_live_20260717_143235.stdout.log`. The complete Sonnet
fallback path worked — and the run still never reached the writer. The plan stage alone
logged: planner 7m (11,924 output tokens), audit 2.4m, targeted repair 4.5m, re-audit 6m,
second repair 2.8m, then a multi-minute gap consistent with a dead-provider retry, then
another Sonnet call at 15:03. Operationally unusable. Three defects, all fixed:

1. **The health mark landed downstream of the audit.** Now marked inside `_audit_plan`
   the moment the primary fails — before escalating, before returning — so every later
   re-audit, repair audit, compliance, score, final and annotation call routes around it
   immediately. A dead account is dialled **exactly twice per run**, however many audits
   follow. Health also now outlives an attempt: `run_with_retry` owns the context and
   passes `inherit_health_context=True`, so attempt 2 no longer re-discovers a 402 at the
   price of another bounded round.
2. **The CLI was invoked with no `--effort`.** Every stage inherited the CLI's default
   reasoning depth, which is why a *structured planner call* burned 7 minutes and 11,924
   tokens. Effort is a property of the role, so `cli_effort` is now an immutable
   constructor option on `LLMClient`/`ClaudeCLIClient` (not a per-call env var — two
   channels in one process must not race each other's depth), validated eagerly against
   `low|medium|high|xhigh|max` because the CLI ignores an unknown value with a warning
   and silently uses its default. Planner/judges run `medium`; writer and challenger run
   `max` under max-quality. Omitting the option reproduces the old command line exactly,
   so non-unit flows are untouched.
3. **The plan stage had no strict budget.** `true_horror_strict_v1` now sets
   `maximum_plan_attempts=2` / `maximum_plan_repairs=1`: one plan, at most one targeted
   repair, one re-audit, then abandon — and the outer loop buys exactly one fresh
   concept. A compilation needing more than one repair is not close.

Also: audit contract retries are counted separately (`plan_audit_contract_retry`) so they
cannot burn a creative attempt silently, and CLI role/effort/model now appear in the
completion log and notional subscription cost in the attempt evidence — the 14:32 log
could only be read by inferring the stage from timestamps.

Verification is unit-level only: **123 focused passed** (release-integrity 74 + autonomy
23 + unit-pipeline 26), 194 across all seven `test_narrative_*.py` files, 19 in the new
`test_claude_cli_effort.py`, and **1233 passed / 6 skipped** for the full `tests/unit`
suite. No live success is claimed; both the 14:02 and 14:32 runs are recorded as stopped
diagnostics, not completed runs.
**External blocker resolved operationally, not fixed (2026-07-17).** The operator
confirmed the DeepSeek quota is exhausted, so `OMNICAST_NARRATIVE_CLAUDE_ONLY=1` now
routes **every** unit-first role to the Claude CLI and makes **zero** DeepSeek calls — no
health probe, no first primary attempt — by never handing the pipeline a DeepSeek client
at all. Unset restores DeepSeek-first with no code change, so this is reversible by
deleting one line.

The switch had to be wired through `Settings`, not `os.environ`: pydantic-settings reads
`implementation/.env` into the Settings model and does not populate `os.environ`, and only
the API-server path calls `load_dotenv` — so an env-only read would have made a `.env`
switch silently inert on a CLI run (verified: `os.environ` returns `None` while Settings
returns `"1"`). `implementation/.env` was appended to, never rewritten; no secret was
read, printed or modified. `.env.example` documents the non-secret switches.

Under `claude_only` the fallbacks are `None` on purpose: one Anthropic subscription is one
health domain, so a model swap is not a fallback and would only buy a pointless retry
against the same dead domain. If Claude dies the run aborts fail-closed. `judge_mode` and
per-role `model/effort` are recorded in the logs and both audits, but no gate reads them —
gates read resolved client identity, which a label cannot misdescribe. The independent
challenger (Opus over Sonnet judges) and the strict plan budget (2 attempts / 1 repair)
are unchanged.

**Fifth run (2026-07-17 15:36) — first claude_only attempt, MANUALLY STOPPED ~15:48.**
`implementation/output/claude_only_live_20260717_153651.stdout.log`. The routing worked:
`judge_mode=claude_only`, zero DeepSeek calls, planner and critic completed. Then every
targeted plan-repair call died — session JSONL ending `max_turns_reached`, `maxTurns=1`,
`turnCount=2` — and the client retried the identical failure. Two defects, both fixed:

1. **`--strict-mcp-config` disables MCP servers only; built-in tools and skills stayed
   available.** Sonnet chose a tool, spent its single allowed turn on it, and returned
   `error_max_turns`. `_build_command` now passes `--tools ""` (per `claude --help`:
   *"Use `""` to disable all tools"*) and `--disable-slash-commands`, with the empty
   string as its own argv element so Windows renders it rather than dropping it.
   Reproduced and verified against the installed CLI: without the flags,
   `error_max_turns`/`num_turns=2`; with them, `success`/`num_turns=1`. `--max-turns 1`
   stays — one turn is all a text completion needs once tools are truly gone.
2. **Every `is_error` was treated as a throttle.** ~6 minutes and four subscription calls
   went on re-asking a settled question. Transient is now an allowlist (empty stdout,
   rate/usage limit, 429/5xx, 401-resync); `max_turns_reached`, bad arguments, non-JSON
   output, permission/config and any *unrecognised* error fail immediately with their
   message. Empty stdout is the same symptom for a bad flag and a throttle, so stderr is
   read before waiting 20 seconds. No sleep ever follows the final attempt. Credential
   sync-back still runs on every exit path.

`scripts/claude_cli_smoke.py` (outside the unit suite, two real calls) checks this
against the installed CLI and **passes**: a tool-tempting prompt no longer burns the turn,
and a plain prompt returns usable JSON in one turn. No unit test can catch this — it is a
property of the CLI, not of our code.

**Sixth run (2026-07-17 16:03) — completed fail-closed, 504.1s, still no script.**
`output/products/true_dread_files_us/20260717_1612_3_true_encounters_while_rekeying_businesses_after_/narrative_failure_audit.json`:
`planner=4`, `plan_audit=3`, `plan_repair=3`, `story_writer=0`, $0 marginal / $0.7666
notional, zero DeepSeek calls. **The infrastructure is now fine.** Every earlier defect
stayed fixed: routing held, no `max_turns_reached`, the run ended by itself instead of
being killed. What failed is planner judgement and the repair envelope.

The auditor was *right* every time, and none of it is weakened:

- a locksmith trapped by the front door he had just rekeyed, ignoring code-required free
  interior egress;
- an apprentice watching a stalker close in over two nights, returning alone on the third
  with no report, partner or escort;
- a non-emergency call placed while a man was pressed to the glass;
- doors latching with no staged mechanism; generic self-closing-door horror with no trade
  logic;
- `safety_obligation="trusted_adult_or_witness"` against an aftermath of `told_no_one`.

Three fixes:

1. **Max-quality planner is now Opus at `high` effort** (plan auditor stays Sonnet/medium,
   so planner and judge remain different readers). One plan call decides whether three
   writer calls are worth making — it is the cheapest place in the run to buy judgement.
   `high` not `max`: nothing measures `max` as better here, and the 14:32 run measured what
   plan-stage depth costs (31 minutes, no prose).
2. **A profile-scoped pre-return self-audit in the existing plan call** — no new paid
   judge. Every rule is a defect the 16:03 auditor already caught after the plan was paid
   for: trade reality, egress, staged mechanism, proportionate adaptation to a repeated
   threat, emergency-vs-non-emergency immediacy, safety/escape/ending/aftermath agreement,
   trade logic over haunted-house mechanics, exact-subject `topic_promise`. Horror-only.
3. **`topic_promise` declared an internal gate string.** A whole plan died at preflight for
   naming "a laundromat" and "a furniture warehouse" without repeating the extracted
   subject word `business`. The gate is right and unchanged — the planner had simply never
   been told what the field was for.

Plus **repair envelope resilience**: all three 16:03 repairs died before re-audit (twice on
`continuity_ledger` >24 words, once on JSON truncated at line 61), so the proposed fixes
were never judged. One schema/JSON contract retry now exists, counted separately as
`plan_repair_schema_retry`, carrying only the validator's exact words and demanding the
same repaired stories rather than a redesign; the prompt names every required field, the
24-word cap, compact JSON and 6000 tokens of headroom. Two schema failures stop at two
repair calls. Every gate after a valid repair is unchanged.

Verification: **1292 passed / 6 skipped**. These are planner-quality and contract fixes.
They still prove nothing about the next artifact — no script has been produced. 1.6 still
needs a live run that produces one.

---

## Phase 2: Writer plan compliance and accepted artifact

Purpose: Eliminate the remaining writer bottleneck by proving that every story completes its locked physical action and ending before compilation release.

| Task | Content | DoD | Depends | Status |
|------|---------|-----|---------|--------|
| 2.1 | Make creepy writer output stable enough for accepted production artifacts `[tdd:required]` | Plan separates spoken setup from private continuity facts; only locally failed first drafts get one deterministic recovery; repair contract errors get at most one bounded retry; obvious unsafe/irrational behavior is rejected; clean stories remain byte-identical; annotations remain post-lock; targeted and full tests pass; one paid artifact reaches `production_ready` and manual review finds no critical/major defect | 1.6 | cc:WIP |

Validation note (2026-07-15): all release/audit paths were exercised with paid Claude
generation. The latest candidates were correctly retained as `needs_edit` (89, then 85)
for a real agency contradiction, a missing locked setup fact, and a hard length miss.
No artifact is yet accepted as top-channel ready, so task 2.1 intentionally remains WIP.

Validation note (2026-07-17): task 2.1 stays **WIP**, and the reason is now a measured
false positive rather than an absence of evidence. The paid artifact
`output/products/true_dread_files_us/20260717_0733_3_true_encounters_while_delivering_newspapers_befo`
reached `93/100 production_ready`; an independent manual audit scored it ~58-62 and
found an impossible fence-gap traversal, three stories sharing one semantic beat sheet,
a newspapers/packages topic mismatch, a sixteen-year-old abduction attempt with no
police or adult response, a forbidden `I never went back to find out who he was`
ending, and a locked narrator age never spoken on the page. The scoring critic filed
the impossible escape as `severity=minor / issue_kind=style`; the final editor wrote
"No human-safety failures" and "Ending mechanisms vary" about that compilation.

The release path was rebuilt so those defects are caught by gates rather than by the
judges that missed them (see `implementation/specs/NARRATIVE_HORROR_GENERATION.md`
§"Release integrity"). Replayed against that exact artifact, the current code blocks it
at three independent layers: 4 plan-time preflight errors before any paid writer call
(duplicate `threat_mechanism`/`escape_mechanism` on stories 1+3, story 2's topic drift,
story 1's minor-safety obligation), 4 story-time deterministic gate failures
(`plan_fact_age`, `forbidden_ending`, `plan_fact_topic_promise` ×2), and severity
promotion of the critic's own "physically unclear" minor to a blocking major.

2.1's DoD is unchanged and unmet: **no paid `production_ready` artifact has yet passed
an independent manual audit with zero critical/major defects.** The gates are proven
against the known failure, not against the next one. `competitive_validated` is not
claimed and remains gated on the separate 30-topic blind benchmark defined in the spec.

**2.1 after the 13:34 live run (2026-07-17): still WIP, and no closer to closing.** That
run produced **no script at all** — 575.1s, `planner=6`, `plan_audit=10`,
`plan_audit_escalation=5`, `story_writer=0`. A run that writes nothing cannot satisfy a
DoD about what the writer produces, so 2.1 has no new evidence either way. It also still
depends on 1.6, which is REOPENED. The five defects that run exposed are fixed and
unit-tested (123 focused, 1233 full suite), but every one of them is about *refusing to
write badly*, not about writing well: the writer path has not been exercised end-to-end
since. Neither stopped run is a live result: the 14:02 health check (~9.5 min, 11 Opus
calls) and the 14:32 max-quality attempt (~31 min, 5 logged Sonnet calls) both produced
zero prose. What they produced were defects — a delayed health abort, a missing
`--effort`, and an unbounded plan stage — all since fixed. Closing 2.1 needs a live run on a healthy quality path that
reaches `production_ready` and then survives an independent manual audit with no
critical/major finding. DeepSeek health remains the external blocker (every primary
plan-audit call 402'd); the complete Sonnet-CLI fallback path now exists so a live run
can proceed without DeepSeek balance, but it has not yet been exercised end-to-end.
