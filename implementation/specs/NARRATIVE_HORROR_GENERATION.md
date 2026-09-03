# SPEC: Narrative Horror Generation Quality

> **Status:** Active
> **Scope:** Unit-first planning, story generation, editorial review, repair,
> production annotation, and release gating
> **Primary channel:** `true_dread_files_us`

## Goal

Generate allegedly true first-person horror that keeps the strong fight-or-flight
behavior introduced in V4 while removing the patterns that make a script feel
machine-made: continuity breaks, stacked corroboration, interchangeable narrators,
formulaic endings, and arbitrary precision.

The system optimizes for credible spoken storytelling, not for a high self-reported
model score. A score routes repair work; it is not proof of competitiveness.

## Channel quality strategy

Narrative taste resolves from a validated strategy ID in
`channels/<channel_id>.json`, then a genre preset, then immutable system defaults.
The resolved object is run-local: editing one channel cannot mutate another channel or
a process-global default. A strategy may strengthen editorial thresholds and define
voice texture, threat/ending variety, trope and phrase avoid-lists, patch count, and
comparison confidence. It cannot weaken objective release gates.

Unknown strategy IDs fail before paid model calls. Objective facts (story count,
length, CTA/meta text, duplicates, forensic-contract integrity, annotation coverage)
are hard gates. Polished metaphor, fake precision, proof cosplay, shared-author cadence,
and over-explained endings are editorial signals; a style regex alone never rejects a
script.

## Release integrity

Added 2026-07-17 after a measured false positive: a compilation the system scored
`93/100 production_ready` was independently audited at ~58-62. Its critic filed a man
who fills a fence gap shoulder-to-shoulder, ridden "straight past his shoulder", as
`severity=minor / issue_kind=style`; its final editor certified "No human-safety
failures" for a sixteen-year-old's abduction attempt that nobody reports. The lesson is
not that the judges were bad. It is that **a judge's verdict was the only thing standing
between a broken premise and a shot video**, and two judges on one provider share one
blind spot. These layers exist so a release does not depend on a model noticing.

1. **Typed semantic mechanisms.** Every story plan declares one value on each of four
   closed axes — `threat_mechanism`, `progression_mechanism`, `escape_mechanism`,
   `aftermath_mechanism`. No two stories in a compilation may share a value on any
   axis. Prose fields ("a silent man blocks her shortcut" / "a figure stands in her
   path") normalize to different strings while describing the same beat, so the
   previous literal-diversity check passed three stories a viewer experiences as one.
   Checked in `validate_plan_preflight`, before any paid writer call.
2. **Concept freshness is enforced, not requested.** `plan_concept_fingerprint` is the
   sorted multiset of mechanism signatures; an outer retry may not reuse a spent
   fingerprint, and a plan reusing a majority of a spent plan's story concepts is
   materially equivalent and rejected. Scope matters: a candidate rejected inside one
   run's planner loop does **not** burn its concept — a rejection must be repairable.
   A verbatim resend of a rejected plan is caught separately by material digest.
3. **The plan audit is a typed verdict**, not a boolean:
   `valid | blocked | infra_failed | contract_failed`. Every grounded critical or major
   blocks (previously a lone major was discarded and only two on one story blocked).
   The planner is replanned up to `maximum_plan_attempts`; an unresolved block at the
   bound **aborts before story writing** rather than proceeding with the objection
   demoted to a warning. A provider failure retries and escalates to a genuinely
   different provider where one is configured, and otherwise reports `infra_failed` and
   aborts — an unanswered audit is not a clean audit. An auditor that answers but cannot
   ground its own blocking objections gets one contract retry and then `contract_failed`,
   which is also an abort: a verdict nobody can act on is not a clean plan either.
   Provider identity is compared by resolved `(provider, model)`, not by variable name,
   because the CapabilityBus can resolve two differently-named preferences onto one
   provider.
4. **The plan audit is also the live probe of the critic path — and escalation must not
   launder it.** It is a real paid critic call that happens before the first writer call,
   so a dead or unfunded critic provider can abort the run before it buys three full
   drafts. That only works if the health signal survives the verdict: the live run of
   2026-07-17 13:34 failed all ten DeepSeek primary audits, answered all five audits from
   Claude escalation, and reported a clean verdict — had any plan passed, the run would
   have bought three Opus drafts and only then discovered that the scorer, compliance
   auditor and final editor were all unreachable. `PlanAuditResult` therefore carries
   `primary_healthy`, `primary_provider_errors` and `verdict_source` alongside the
   verdict, and escalation never sets `primary_healthy` back to true.

   `_assert_post_writer_path_healthy` then gates the writer on a **provider health
   domain**, which is deliberately coarser than model identity: providers die by
   *account*, not by model name. `deepseek-v4-pro` and `deepseek-v4-flash` are two
   identities and one balance, one key, one outage — calling that pair a fallback for
   each other is calling a system resilient because it can fail twice. If any mandatory
   post-writer judge (`critic_score`, `final_editor`, `story_compliance`) sits on the
   failed account with no configured fallback in a *different* health domain, the run
   raises `QualityPathUnhealthy` before the writer and reports the full bill. When a
   genuinely independent fallback is configured for every mandatory stage, `_route`
   sends those calls to it and the run proceeds. Configuration that cannot satisfy the
   channel's required quality path at all fails earlier still, in
   `_preflight_quality_path`, before the planner.

   **The domain is marked dead inside `_audit_plan`, at the first bounded failure.**
   Live 2026-07-17 14:02 was stopped by hand after ~9.5 minutes and 11 Opus calls with
   zero writer calls: the health check sat *after* the planner loop, so a plan that kept
   getting blocked kept being repaired and re-planned against a provider the very first
   audit had already proved dead. Marking now happens the moment the primary fails —
   before escalating, before returning — so every later re-audit, targeted-repair audit,
   compliance, score, final and annotation call in the same run routes around it
   immediately. The blocked plan is recorded as evidence first, so an abort still
   carries the premise and its reasons. **A dead account is dialled exactly twice per
   run** (one bounded failure set), however many audits follow.

   **Health outlives an attempt.** `run()` used to clear the context, so outer attempt 2
   re-discovered a dead provider at the price of another bounded round. `run_with_retry`
   now owns the context via `_begin_health_context()` and passes
   `inherit_health_context=True`; a 402 does not heal because we started a fresh concept.

   Every mandatory judge routes to its fallback under its own counter
   (`critic_score_escalation`, `final_editor_escalation`, `story_compliance_escalation`,
   `annotation_escalation`, `plan_audit_contract_retry`), so "how much did we spend on a
   corpse" is answerable from the ledger. The 14:02 run should have been one planner
   call, two bounded primary audit retries, one escalated audit, and an abort.
5. **Every rejected plan keeps its own reasons.** The 13:34 failure audit persisted five
   rejected plans against a single trailing blocker list, so four of them could not be
   matched to why they died, and a sixth planner output that failed schema validation
   (a missing `story_2.voice_rules`) left no trace at all. `PlanRejection` is now one
   typed record per rejected plan — `attempt`, `planner_attempt`, `stage`
   (`schema | preflight | freshness | audit | repair`), the exact `errors`, the candidate
   plan when one parsed, its fingerprint and material digest, the `PlanAuditResult` that
   rejected it, and the call counts / cost / latency at that moment. Schema failures are
   recorded too, with redacted validation text in `raw_evidence` and `plan=None`: there
   is no plan object to keep, and none is invented. These travel
   `PlanNotPlausible`/`PlannerUnavailable` → `AttemptSummary.plan_rejections` →
   `NarrativeRunEvidence` → `narrative_failure_audit.json`.
6. **A blocking plan objection must quote the plan.** `PlanIssue` carries an
   `evidence_quote` that every major/critical must copy verbatim, exactly and uniquely,
   from the challenged story's own plan text, plus a `knowledge_scope`
   (`universal | site_specific`) and a `confidence`. An objection that cannot point at
   the words it objects to is one the planner cannot act on. `knowledge_scope` calibrates
   what a reader of a premise can actually know: physics, hardware, geometry, established
   trade practice and contradictions inside the plan are `universal` and block; one site's
   staffing, hours or policy that the plan never states is `site_specific` and is demoted
   to a minor recommendation. The 13:34 audit vetoed a whole concept on "a staffed, lit
   valet booth at a hospital-adjacent garage at 1:25 a.m. is wrong trade knowledge" —
   some hospitals do staff overnight valet, and absent a plan that states the hours that
   is site-specific uncertainty, not an established constraint. Scope defaults to
   `universal`, so an issue that forgets to classify itself still blocks; demotion only
   fires when the auditor explicitly admits the claim is site-dependent. If the plan
   *itself* states the hours and the story contradicts them, that is an in-plan
   contradiction and blocks normally. The legitimate 13:34 blockers — cart/man geometry,
   an exterior latch thrown from inside, an escape route running toward the threat, an
   active brew cycle after the mains were cut, a trade tech skipping the obvious
   diagnostic — are all `universal` and all still block.
7. **A blocked story is repaired, not re-rolled.** The 13:34 run spent 575.1 seconds and
   never wrote a word, largely re-rolling whole compilations because one story's cart
   geometry was wrong while the other two were fine. A blocked audit now triggers a
   bounded targeted repair (`max_plan_repairs`, default 2): the auditor's own `plan_fix`
   is applied to the failed stories only, the approved stories are asserted
   **byte-identical**, and the repaired plan re-runs *every* gate — preflight, freshness,
   mechanism diversity and a full fresh audit. A repair cannot buy its way past a rule the
   planner had to satisfy, cannot return the wrong stories, and is rejected if it
   regresses the blocker count. A premise-wide objection (every story, or a
   compilation-level issue) is not repairable and abandons the concept. Planner effort is
   accounted separately as `planner`, `planner_schema_retry` and `plan_repair`.
8. **A schema slip is not a bad concept.** The live planner omitted one story's
   `voice_rules` and burned an entire concept for it. A schema/provider failure now earns
   one contract-only retry naming the exact missing fields and asking for the same plan
   completed — not a redesign, and never a fabricated creative default for a required
   field. A planner that never returns a parseable plan raises `PlannerUnavailable`
   (outcome `aborted`), which is deliberately distinct from `PlanNotPlausible`
   (`plan_blocked`): an infrastructure outage says nothing about the concept, and the two
   should not share a bucket.
9. **Severity calibration.** A `minor` whose own problem text asserts a physical or
   causal impossibility is promoted to a blocking `major` contradiction. This reads the
   judge's words about its own finding, not the prose. A judge may be wrong about
   whether an action is impossible; it may not be wrong about what "impossible" means
   for release. Grounding still applies: an unquoted claim stays minor, because there
   is nothing to repair.
10. **Adversarial release challenger.** Runs only for would-be releases, prompted to
   assume the existing approval is wrong. It returns typed verdicts on physical
   possibility, timeline consistency, semantic repetition, topic alignment, safety
   response, plan fidelity, and forbidden endings. A `fail` requires one exact unique
   narration quote and blocks; an ungrounded veto, a malformed contract, and an
   unreachable challenger all fail closed. A `pass` is only accepted when every axis was
   actually examined.
11. **A challenger that is not independent cannot approve.** The adversary exists to
   break *correlated* judge error — on 2026-07-17 the critic and the final editor were
   one provider agreeing with each other. Independence is measured against the judges
   that **actually ran**, not the ones the wiring nominated: on a fallback path the
   compilation is approved by the fallback, so `_routed_judge` records every resolved
   judge identity in `judge_identities` and a challenger matching any of them is not
   independent. A Sonnet challenger reviewing a Sonnet fallback judge is one reader
   twice, whatever the variables were called. A challenger whose resolved
   `(provider, model)` equals the critic's or any actual judge's returns
   `not_independent`, never `passed`;
   `ReleaseChallengeResult` enforces this as a model invariant, so no call site can
   forget to check it alongside the status. It may still **veto**: a grounded quote is
   evidence regardless of who found it, and evidence does not become less true for
   coming from a correlated reader — but "I found nothing" is only worth the
   independence of the reader who says it. When the channel requires a challenger and
   the identity is already knowable, `_preflight_quality_path` fails **before the
   writer**, because prose that is unreleasable by construction is not worth buying.
   Identity is re-checked at challenge time, since clients can be re-resolved.
12. **All-attempt accounting.** The artifact reported `attempt=2` with `planner=1`: the
   per-run counters reset each attempt, so the selected attempt was billed as if the
   one before it had been free. `run_with_retry` returns `attempts_executed`,
   `attempt_summaries` (including aborted attempts, their reason, and what they spent),
   `aggregate_call_counts`, `aggregate_cost_usd`, and `aggregate_latency_s`. When
   **every** attempt aborts there is no result to carry them, so the evidence rides on
   `NarrativeRunExhausted.evidence` instead — that is the run which spends most and
   delivers least, and it is the last place the bill should vanish. `_step_script`
   persists it as `narrative_failure_audit.json` before re-raising; that folder is not a
   product and no score or script is fabricated for it.

### `claude_only` — the temporary mode while the DeepSeek quota is exhausted

Operator-confirmed 2026-07-17: DeepSeek quota is gone. `OMNICAST_NARRATIVE_CLAUDE_ONLY=1`
makes the unit-first flow run **every** role on the Claude CLI and issue **zero** DeepSeek
calls — not a health probe, not a first primary attempt. It does this by never handing the
pipeline a DeepSeek client at all: a call that is unreachable cannot be made, which is a
stronger guarantee than a fallback that fires after the first 402. `_narrative_role_clients`
resolves the mode once per run; nothing global is mutated, and unset restores DeepSeek-first
routing with no code change, so DeepSeek can be turned back on by deleting a line.

**The switch lives on Settings, not only in `os.environ`.** pydantic-settings reads
`implementation/.env` into the Settings *model*; it does not populate `os.environ`, and
only the API-server path calls `load_dotenv`. An `os.environ`-only read would make a
`.env` switch silently inert on a CLI/step run — verified: `os.environ` returns `None`
while `Settings.omnicast_narrative_claude_only` returns `"1"`. `_runtime_flag` therefore
reads the environment first (so an operator can override one run) and then Settings, the
same precedence `LLMClient` already uses for `OMNICAST_CLAUDE_BACKEND`.

Under `claude_only` the fallbacks are deliberately `None`. Within one Anthropic
subscription a model swap is not a fallback: one quota, one key, **one health domain**.
Offering one would only buy a pointless retry against the same dead domain. If Claude
itself dies the run aborts fail-closed, which is correct — there is nothing left to judge
with. The plan-audit escalation is the one exception and is a different *model* (Opus over
a Sonnet critic), so the "escalation must not be the same client as the primary" rule still
has somewhere to escalate to; it is a different reader, not a different account, and the
health domain still knows that.

The mode is **descriptive**. `judge_mode` and `model_roles` are recorded on the result, in
`narrative_audit.json`, in `narrative_failure_audit.json` and in the logs, so an artifact
states which models judged it. No gate reads them: every gate reads resolved client
identity, which a label cannot misdescribe. The independent-challenger rule is unaffected —
Opus challenging Sonnet judges is a real second reader, and independence is still measured
against the judges that actually ran.

### The CLI is a text client, not an agent

Live 2026-07-17 15:36 (`claude_only_live_20260717_153651.stdout.log`, stopped by hand
~15:48). The routing was correct — `judge_mode=claude_only`, zero DeepSeek calls, planner
and critic completed. Then every targeted plan-repair call died: the isolated session
JSONL ended `attachment.type = "max_turns_reached"`, `maxTurns = 1`, `turnCount = 2`.

`--strict-mcp-config` disables MCP **servers** only. It leaves Claude Code's **built-in
tools and skills** available. Handed a plan-repair prompt, Sonnet chose a tool, spent the
single allowed turn on it, and returned `subtype=error_max_turns`. The client then
retried the identical deterministic failure four times with 20/40/60s waits between.

`_build_command` now disables them explicitly, per `claude --help` (*"Use `""` to disable
all tools"*):

    --tools ""                 # every built-in tool off
    --disable-slash-commands   # every skill off
    --strict-mcp-config --mcp-config {"mcpServers":{}}   # unchanged

The empty string is passed as its own argv element, so Windows `list2cmdline` renders it
as `--tools ""` rather than dropping it. Verified against the installed CLI: without the
flags the probe returns `error_max_turns` / `num_turns=2`; with them, `success` /
`num_turns=1`. `--max-turns 1` stays — now that tools are genuinely unavailable, one turn
is all a text completion needs, and raising it would only buy room for the agent
behaviour this call must not have.

`scripts/claude_cli_smoke.py` checks this against the real CLI (two subscription calls,
deliberately outside the unit suite): a tool-tempting prompt must not burn the turn, and
a plain prompt must return usable JSON in one turn. No unit test can catch it — it is a
property of the installed CLI, not of this code.

**Retry classification.** Transient is now an allowlist, not a fallback:

| Failure | Treatment |
|---|---|
| `error_max_turns`, invalid model/arguments, non-JSON output, permission/config, unrecognised `is_error` | **fail immediately**, one subprocess call, no sleep |
| empty stdout (measured throttle shape), rate/usage limit, 429/5xx, "temporarily unavailable" | retry, bounded at `_MAX_ATTEMPTS=4` |
| `401` / unauthorised | resync credentials, retry |

Empty stdout is the same symptom for a bad flag and a throttle, so stderr is read before
deciding to wait 20 seconds. **No sleep ever follows the final attempt** — four tries,
three waits. A deterministic failure retried is just the same failure, later and more
expensively; the 15:36 run spent ~6 minutes and four subscription calls re-asking a
settled question. Credential sync-back still runs on every exit path including a
deterministic raise, so a token the CLI just rotated survives a failed call.

### Model roles and effort

The unit-first flow resolves one client per role, explicitly, via
`_narrative_role_clients`. Roles are per-run values passed into the pipeline; no global
setting is mutated, so another channel or flow in the same process is unaffected. Every
role is env-overridable:

| Role | Model default | Effort default | Overrides |
|---|---|---|---|
| planner + plan repair | `claude-opus-4-8` when `OMNICAST_NARRATIVE_MAX_QUALITY=1`, else `claude-sonnet-5` | `high` in max-quality, else `medium` | `OMNICAST_NARRATIVE_PLANNER_MODEL` / `_PLANNER_EFFORT` |
| writer / repair | `claude-opus-4-8` when `OMNICAST_NARRATIVE_MAX_QUALITY=1`, else `settings.claude_model` | `max` in max-quality, else `high` | `OMNICAST_NARRATIVE_WRITER_MODEL` / `_WRITER_EFFORT` |
| judge / compliance / final / plan-audit fallback | `claude-sonnet-5` (CLI) | `medium` | `OMNICAST_NARRATIVE_JUDGE_FALLBACK_MODEL` / `_JUDGE_EFFORT` |
| release challenger | `claude-opus-4-8` (CLI) | `max` in max-quality, else `high` | `OMNICAST_NARRATIVE_CHALLENGER_MODEL` / `_CHALLENGER_EFFORT` |
| annotation fallback | `claude-sonnet-5` (CLI) | `medium` | `OMNICAST_NARRATIVE_ANNOTATION_MODEL` |
| critic / compliance / annotation primary | DeepSeek pro / flash / flash — **or `claude-sonnet-5` (CLI) at `medium` under `claude_only`** | `medium` when Claude | existing settings / `OMNICAST_NARRATIVE_CLAUDE_ONLY` |
| plan-audit escalation | `claude-sonnet-5` — **or `claude-opus-4-8` under `claude_only`**, so it differs from the Sonnet critic | `medium` | `OMNICAST_NARRATIVE_JUDGE_FALLBACK_MODEL` |

**Effort is a property of the role, not the model.** Live 2026-07-17 14:32: a Sonnet
*planner* call ran 7 minutes and 11,924 output tokens, and a Sonnet *re-audit* ran 6
minutes, because `ClaudeCLIClient` invoked the CLI with no `--effort` and every stage
inherited its default reasoning depth. Planning and judging are structured, bounded
jobs; prose is where depth pays. `cli_effort` is an immutable constructor option on
`LLMClient`/`ClaudeCLIClient` (never a per-call env var, so two channels in one process
cannot race each other's depth), validated eagerly against the levels this CLI accepts —
`low, medium, high, xhigh, max` — because the CLI answers an unknown `--effort` with a
warning on stdout and silently uses its default. Omitting the option reproduces the
previous command line exactly, so non-unit flows are untouched.

### The plan is where judgement is cheapest

Live 2026-07-17 16:03 completed fail-closed in 504.1s with zero DeepSeek calls and
`story_writer=0` — infrastructure fine, planner not. A Sonnet/medium planner produced
premises the auditor correctly killed on **trade reasoning**: a locksmith trapped by the
front door he had just rekeyed (ignoring code-required free interior egress), an
apprentice watching a stalker close in over two nights and returning alone on the third
with no report or partner, a non-emergency call placed while a man was pressed to the
glass, doors latching with no staged mechanism, and `safety_obligation` promising a told
adult against an aftermath of `told_no_one`. Every one of those is a judgement failure,
not a format failure.

Three responses, none of which weaken the auditor:

1. **Under max-quality the planner is Opus** (`high` effort). One plan call decides
   whether three writer calls are worth making, so it is the cheapest place in the run to
   buy judgement. `high` rather than `max`: the failures were reasoning quality, which the
   model change addresses, and nothing measures `max` as better here — while the 14:32 run
   measured exactly what plan-stage depth costs (31 minutes, no prose). Depth is priced in
   wall clock at the stage that has already starved this pipeline of prose four times.
   The **plan auditor stays Sonnet/medium**, so planner and judge remain different readers.
2. **A profile-scoped pre-return self-audit** (`plan_self_audit_rules`), inside the
   existing plan call — no new paid judge. Every rule is a defect the 16:03 auditor
   already caught after the plan was paid for: trade reality (does the narrator's own job
   dissolve this threat?), egress, staged mechanism for anything that moves, proportionate
   adaptation to a repeated human threat, emergency-vs-non-emergency immediacy,
   safety/escape/ending/aftermath agreement, trade logic over haunted-house mechanics, and
   exact-subject `topic_promise`. Generic channels inherit none of it.
3. **`topic_promise` is declared an internal gate string.** The 16:03 preflight threw away
   a whole plan because the promise named real sites ("a laundromat", "a furniture
   warehouse") without repeating the extracted subject word `business`. The gate is right
   and unchanged; the planner had simply never been told what the field is for. It must
   now repeat the exact subject wording *and* name the concrete site — the prompt shows
   the failing and passing forms.

### Targeted repair must survive its own envelope

All three of the 16:03 repairs died before re-audit — twice on `continuity_ledger` entries
over 24 words, once on JSON that ended mid-object at line 61. The proposed fixes were
never judged at all. A malformed envelope is not a rejected idea, and burning a concept
for one throws away work that may well have been right.

`_repair_plan` now gets **exactly one** schema/JSON contract retry, counted as
`plan_repair_schema_retry` and kept apart from the creative repair budget. The retry
carries only the validator's exact words and demands *the same repaired stories* — not a
redesign, not a rethink of the objection. The prompt names every required field, states
the ledger's 24-word cap as the single most common way a repair is discarded, demands
compact JSON, and gets 6000 tokens of headroom. After a valid repair every existing gate
runs exactly as before: approved stories byte-identical, preflight, freshness, mechanism
diversity, fresh audit. Two schema failures stop at two repair calls; a valid-but-still-
implausible repair gets nothing beyond the existing quality budget.

### Plan-stage budget

A profile field, not a magic number in the coordinator. `true_horror_strict_v1` sets
`maximum_plan_attempts=2` and `maximum_plan_repairs=1`: one initial plan, at most one
targeted repair, one re-audit, then abandon the concept — and the outer loop buys
exactly one fresh concept. The 14:32 run allowed two local repairs *and* a fresh planner
loop inside a single outer attempt, at 2-7 minutes per Sonnet call, and never reached the
writer in 31 minutes. A compilation needing more than one targeted repair is not close;
abandoning it is cheaper and better than sanding it. Fail-closed behaviour and
fresh-concept enforcement are unchanged.

DeepSeek stays the primary while healthy — it is far cheaper — and cross-provider
primary routing is unchanged. What changed is that its 402 now switches **all later
mandatory judging** to the Sonnet fallback instead of re-dialling a dead account at
every stage. The compliance fallback is deliberately *not* `deepseek-v4-pro`: that is
the same account as the primary, and a fallback that dies with its primary is not a
fallback. The challenger stays Opus so it differs from the Sonnet judges that approve
the release on the fallback path.

### Measured live runs

Three paid/subscription runs drove the layers above. **None produced a releasable
script**, and none is evidence that the next one will.

| Run | Outcome | Evidence |
|---|---|---|
| `20260717_0733_..._delivering_newspapers_befo` | `93/100 production_ready` — **false positive**, independently audited ~58-62 | `narrative_audit.json`; reported `attempt=2` with `planner=1` |
| `20260717_1334_..._servicing_vending_machines` | **575.1s, no script** — safe failure, no story ever written | `narrative_failure_audit.json`; `planner=6`, `plan_audit=10`, `plan_audit_escalation=5`, `story_writer=0` |
| `opus48_healthgate_20260717_140248` | **manually stopped after ~9.5 min** — not a completed run, and not a success | 11 Opus CLI calls, `story_writer=0`; exposed the delayed health abort fixed above |
| `max_quality_live_20260717_143235` | **manually stopped after ~31 min** — not a completed run, and not a success | 5 logged Sonnet CLI calls (planner 7m/11,924 tok; audit 2.4m; repair 4.5m; re-audit 6m; repair 2.8m), `story_writer=0`; exposed missing `--effort` and an unbounded plan stage |
| `claude_only_live_20260717_153651` | **manually stopped ~15:48** — not a completed run, and not a success | `judge_mode=claude_only` and zero DeepSeek calls both held; planner+critic completed; every plan-repair call returned `max_turns_reached` (`maxTurns=1`, `turnCount=2`) and was retried; exposed built-in tools left enabled and retry misclassification |
| `20260717_1612_..._rekeying_businesses_after_` | **completed fail-closed, 504.1s, no script** — infrastructure clean, planner not | `planner=4`, `plan_audit=3`, `plan_repair=3`, `story_writer=0`, $0 marginal / $0.7666 notional; audit blocked real trade defects; all 3 repairs died on schema before re-audit |

The 14:32 max-quality run is the same lesson at a larger scale. It had a complete
healthy fallback path and still never reached the writer in 31 minutes: the plan stage
alone spent one 7-minute planner call, a 2.4-minute audit, a 4.5-minute repair, a
6-minute re-audit and a 2.8-minute second repair, every one of them a Sonnet CLI call
running at the CLI's default reasoning depth, followed by a multi-minute gap consistent
with a dead-provider retry. Zero prose. Three defects, all fixed above: effort was never
passed per role; the plan stage had no strict budget; and the health mark landed
downstream of the audit rather than inside it. **It is recorded as a stopped diagnostic
run, not a live result.**

The 14:02 health-check run is worth stating precisely, because it is easy to read as a
win and is not one. It proved the writer gate held (zero drafts against an unaudited or
unjudgeable premise) — but it was **stopped by hand**, not by the pipeline, and the
reason it needed stopping is the defect: it spent ~9.5 minutes and 11 Opus calls
repairing and re-planning after the first audit had already established the provider was
dead. It is recorded as a stopped diagnostic run, not a live result.

The 13:34 run is the one the current layers were written from, and it is worth reading
precisely, because most of what it did was correct:

- **It failed safely.** Zero `story_writer` calls: nothing was drafted against a premise
  that had not passed its audit. The failure audit persisted, which is how any of this is
  known.
- **`aggregate_cost_usd` is 0.0, and that is accurate rather than reassuring.** The
  Claude CLI bills a subscription and reports zero marginal cost, and every DeepSeek
  primary audit failed *before* returning a billable response. Eleven Claude CLI calls
  (6 planner + 5 escalation) did the work. Zero marginal cost is not zero cost: it is
  9.6 minutes of wall clock and eleven Opus calls against a subscription quota.
- **Most of the audit was right and valuable.** The cart/man geometry contradiction, an
  exterior latch thrown from inside, an escape route running toward the threat, an active
  brew cycle after the mains were cut, and a trade tech skipping the obvious diagnostic
  are exactly the objections a pre-writer audit exists to raise.
- **The defects it exposed are the five fixed above**: primary provider health masked by
  escalation; rejection reasons not aligned to the plans they rejected; one overclaimed
  blocker (`site_specific` speculation about overnight valet hours) killing a concept;
  six full replans where targeted repair would do; and a whole concept lost to one
  missing `voice_rules`.

### Channel-scoped release gates

These read typed plan data and are **off by default**, so one channel's editorial policy
cannot leak into another. `true_horror_strict_v1` turns them on:

| Gate | Blocks when |
|---|---|
| `topic_alignment_gate` | a story's `topic_promise` does not deliver the topic's subject term |
| `plan_fact_fidelity_gate` | a locked minor's age, or the topic's subject, is never spoken in the narration |
| `safety_response_gate` | a minor survives a human threat and the plan declares neither `authorities_contacted` nor `trusted_adult_or_witness` nor a concrete (>=5 word) reason nobody is told; or a declared response never reaches the page |
| `forbidden_ending_gate` | the last paragraph closes on a self-referential disclaimer (`I never went back to find out who he was`) |
| `require_distinct_mechanisms` | two stories share a typed mechanism (on by default) |
| `release_challenger_required` | the adversarial challenger fails, is malformed, or is unreachable |
| `promote_impossibility_to_major` | a quoted minor asserts a physical/causal impossibility (on by default) |

The topic subject is the longest significant stem in the title after dropping
compilation scaffolding and temporal words ("3 True Encounters While Delivering
**Newspapers** Before Dawn"). This is an explicit heuristic. It errs only in the
direction that costs nothing: if it names a term the planner considers secondary, the
planner satisfies the gate by naming that term in `topic_promise`, which a
title-honest plan does anyway.

**Minor safety has three legal paths, not one.** `authorities_contacted`,
`trusted_adult_or_witness`, and `concrete_reason_omitted` (with a concrete >=5 word
reason) all satisfy the plan gate; only `not_applicable` — a plan that simply never
addresses what a child does after surviving a human threat — is rejected. Forcing
police onto every story would manufacture exactly the formulaic ending the channel
promise exists to avoid. The obligation is that the child tells *someone responsible*,
or the plan says concretely why not. Whichever path is declared, the narration must
deliver it, checked against the **aftermath** (the closing paragraphs) rather than the
whole story: "my mom always said the dark before dawn is the darkest" is a remembered
saying, not somebody being told, and the neighbour who opens a door mid-escape is not
the neighbour who was told afterwards. `trusted_adult_or_witness` requires someone with
standing over the narrator (parent, guardian, teacher, employer, named neighbour,
witness); a bare "adult"/"man"/"woman" does not discharge it.

**What is deterministic and what is not.** Plan-time mechanism diversity, topic
alignment, minor-safety obligation, spoken plan facts, and forbidden endings are
deterministic and cost nothing. Story-level *semantic* repetition and timeline
contradiction are not reduced to a regex — they are caught by typed plan diversity
before prose exists, and by the challenger's typed verdicts afterwards. That is a
weaker guarantee than a deterministic gate and is documented as such rather than
disguised by a brittle pattern list.

## Invariants

Every narrative draft must satisfy these rules before the critic sees it:

1. **Continuity ledger:** privately track the hook promise, timeline, people/object
   counts, locations, props, threat position, protagonist response, and escape for
   every story. The hook event must occur in the body and every action must be
   physically possible in the stated order.
2. **Fight-or-flight stays:** the protagonist makes a plausible decision under
   pressure. Quality repair must never solve a continuity issue by deleting the
   core chase, escape, defensive action, or emergency call.
3. **Evidence restraint:** at most one aftermath/corroboration beat per story, and
   at least one story in a compilation has none. Camera failure, police/ranger
   confirmation, records, tracks, witness confirmation, and later recurrence all
   count as corroboration. Never stack them to prove the story true.
4. **Distinct endings:** assign a different ending shape to every story. No two
   stories may end with later evidence proving the threat selected or followed the
   narrator. End within one or two beats of the strongest image/action.
5. **Specificity budget:** use exact numbers only when they affect a decision,
   spatial logic, or timing. Use no more than four exact numeric anchors per story
   and no more than one precise clock time. Never add arbitrary counts to simulate
   authenticity.
6. **Distinct voices:** privately assign each narrator a different age/life context,
   sentence rhythm, vocabulary, skepticism level, and dialogue habit. Do not reuse
   character names supplied in recent-channel history.
7. **No stock self-reassurance:** omit `I told myself`, `I figured it was`,
   `I convinced myself`, and equivalent repeated rationalization. Show uncertainty
   through a check, a hesitation, dialogue, or a wrong decision.

## Pipeline behavior

The production horror path is **unit-first**. A compilation is never drafted or
rewritten as one monolithic response:

1. Claude Sonnet creates a compact compilation plan with one continuity ledger,
   narrator voice, threat, escape action, evidence allowance, ending shape, and one
   concise `setup_requirement` per story. `setup_requirement` contains only the ordinary
   context that must be spoken before danger; private setting/ledger facts constrain
   continuity but are not exposition obligations. The planner must not introduce an
   exact unit, floor, exit, or prop unless it affects threat, choice, escape, or ending.
   The plan also carries the typed release data described under "Release integrity":
   four mechanism axes, a `topic_promise`, `narrator_age_band`/`narrator_age_years`, and
   a `safety_obligation` (with a concrete `safety_omission_reason` when nobody is told).
2. Each story is written independently and concurrently from its own locked plan.
   Story calls emit narration only; visual directions, CTAs, and channel framing are
   forbidden. Before emitting prose the writer privately checks five required beats:
   ordinary setup, confirmed threat, decision plus practical action, completed locked
   escape, and completed ending. These are semantic obligations, not visible headings
   or a fixed paragraph formula.
3. The plan is validated before story calls: exactly five unique concise ledger entries,
   valid evidence allowances, required threat mix, distinct narrator/threat/ending
   fields, distinct typed mechanisms, channel-scoped topic/safety gates, and concept
   freshness against previously spent concepts. A bad plan is rejected before paying for
   story generation, and a plan whose audit stays blocked at the attempt bound aborts
   the run rather than drafting against it.
   Each story prompt receives an integer 90%-110% word envelope and must silently check
   that envelope before returning. After the parallel first drafts, only a story with a
   deterministic local release failure may receive one full-story recovery call. The
   recovery is accepted only when it strictly reduces that story's attributable
   hard-gate failures (the compilation-total length check names a story for targeting
   but is not attributed to it), or ties at zero failures while moving strictly closer
   to the per-story target; clean story bytes remain
   unchanged. This happens before semantic audits so bad-length prose is not needlessly
   audited.
4. An independent DeepSeek Flash per-story compliance audit runs concurrently after
   deterministic drafting checks and before the global DeepSeek Pro score. It
   echoes a deterministic fingerprint of the assigned plan and supplies exact, unique,
   ordered narration quotes for the five required beats. It also judges preservation
   of locked geography/threat facts, completion (not merely intent) of the required
   response/escape and ending, evidence allowance, and absence of equivalent stock
   self-reassurance. Wrong-story fingerprints, missing/ambiguous/out-of-order quotes,
   ungrounded issues, contradictory booleans, or malformed output receive one Flash
   contract retry. A still-invalid story receives at most one bounded Pro compliance
   escalation and then fails closed under the identical local validators. JSON `null`
   is normalized only for the optional repair `anchor_quote`; required evidence remains
   a strict exact string. `unclear` evidence-budget status is unresolved, not an
   approval. An overall critic score cannot compensate for a failed
   story compliance audit.
5. Deterministic gates run before semantic scoring: requested story count, spoken
   length, banned self-reassurance, numeric-anchor budget, repeated paragraphs and
   cross-story phrases, CTA/meta language, evidence budget, and plan diversity. Digit
   and number-word anchors normalize to the same value.
6. A content-only critic scores continuity/believability (25), distinct/authentic
   voices (20), dread/escalation (20), plausible fight-or-flight (10), structural
   variety (10), originality (10), and ending discipline (5). Production metadata
   can never inflate this score. Every repairable major/critical issue contains a
   category, confidence, viewer impact, and exact unique quote (or unique insertion
   anchor) from the named story. A hallucinated, wrong-story, or ambiguous quote makes
   the critic contract invalid and cannot reach repair.
   When a major/critical continuity omission conflicts with an exact, approved story
   compliance audit, the critic receives one targeted reread. It must withdraw a finding
   whose own quote already proves the required action, or retain it only after naming the
   exact unmet verb or terminal state. This bounded disagreement check is not an open
   debate loop.
7. Grounded major/critical compliance defects join the critic's repair queue. There is
   one normal bounded repair wave. A second surgical salvage wave is allowed
   only when the first candidate is accepted monotonically, the fresh score already
   meets the channel floor, deterministic gates are clean, there are at most three
   grounded blockers, and no free-form critical issue remains. One writer call per
   failed story emits exactly two
   independent atomic patch candidates built from the same original. Every edit is
   validated against the original before any edit applies; overlapping, cascading,
   partial, oversized, or whole-story replacement rejects the whole candidate. A find
   region is capped at 120 words and the combined change remains capped at 20% of the
   story, so one defective paragraph can be replaced without authorizing broad rewrites.
   The repair prompt states current length, exact desired envelope, and exact edit budget.
   A schema-invalid or locally non-atomic candidate pair receives one contract-only retry
   containing the validator error; it does not receive a new creative brief. A second
   invalid pair fails closed to the baseline.
8. Valid candidates and the original receive anonymous labels. A comparative selector
   may choose a candidate only when it resolves the anchored blockers, preserves the
   locked plan, and introduces no voice, dread, response, or ending regression. Tie,
   invalid output, low confidence, or unknown ID keeps the original. A fresh absolute
   compilation audit remains mandatory and can always roll the candidate back.
9. After an accepted patch, only changed stories are compliance-audited again; prior
   reviews of byte-identical stories remain valid. A candidate cannot be monotonic or
   lockable unless every current story has a valid approved compliance review.
10. A final compilation editor is a read-only gate, not a prose rewriter. It checks the
   channel promise, shared-author voice, repeated threat/aftermath/ending mechanisms,
   dread curve, cold-open payoff, and completed endings. It returns anchored issues only.
   A malformed or forensically ungrounded final-editor response receives one contract
   retry before failing closed. When a grounded final-editor blocker commissions a
   bounded repair wave, that blocker joins the monotonic baseline: a candidate that
   resolves it without any dimension, blocker, or deterministic-gate regression is
   accepted even at an equal fresh total score, and the mandatory final-gate recheck
   still decides the lock. Content locks only when this gate approves and the
   channel threshold (default >=82),
   dimension floors, forensic contract, and deterministic gates all pass — and only
   when the plan audit is `valid` and the adversarial release challenger has either
   passed or is not required by the channel. A locked result carries both as evidence;
   the result invariant re-derives the lock and rejects one that does not.
11. After content lock, DeepSeek Flash adds visual/SFX/prosody annotations keyed by
   immutable beat IDs. It cannot emit or edit narration, and assembly verifies that
   normalized whitespace aside, the final storyboard preserves punctuation, case, and
   every spoken byte. The locked narration hash is recorded.
12. A failed compilation is stored as `needs_edit` without a canonical `script.txt`.
   Render endpoints reject products that are not `production_ready`, unless an
   operator explicitly uses the existing force override.
   Every automated production approval stores SHA-256 bindings for canonical
   `script.txt` and any `script.json`; later byte changes fail the render release gate,
   just as reviewed manual overrides already do.

- Normal happy path is one plan, parallel story calls, deterministic gates, parallel
  per-story compliance,
  one critic, one final compilation gate, and parallel annotation. A failed story adds
  one two-candidate patch batch, one
  selector, one fresh critic, and one final-gate recheck. A second batch is a bounded
  high-score salvage, never a default loop. Annotation runs
  in parallel only after the content lock. Debate, tournament, ThinkingAgent,
  Evolution, and whole-script polish are not part of this path.

- Human-response plausibility is a release property, not a style preference. A narrator
  who has reached safety must use readily available help appropriate to an active human
  threat; the story may omit authorities only when it supplies a concrete reason. A
  character may not refuse an obvious identity/safety check merely to preserve mystery,
  leave a known person trapped without urgent help, or re-enter danger without necessity.

- Initial generation performs the private ledger and audit before emitting JSON.
- Length expansion returns insertion-only scene patches and runs at most once per
  caller. It adds causal action, obstacles, decisions, dialogue, and sensory
  geography without re-emitting clean scenes. It must not add statistics, official
  records, extra witnesses, or supernatural proof.
- A high-scoring draft that fails only the length gate receives a scene fill, not a
  full revision.
- Revision is exactly one paid rewrite. It uses the narrative contract and preserves
  story count/shape unless the critic explicitly identifies structure as the defect;
  the caller decides separately whether length or another audit justifies more work.
- The existing post-generation continuity call is a broader narrative quality pass
  covering all invariants above. It edits minimally and returns the original draft
  if the repair output is suspiciously short or invalid.
- Debate never assumes another round is better: the highest-scoring approved round,
  or otherwise the highest-scoring round, is the result for that variant.
- Debate never pays for a revision after the final configured scoring round, because
  there is no subsequent round in which that rewrite could be evaluated.
- Thinking/self-critique calls are disabled until their output is wired into a
  measurable revision decision; decorative notes must not consume tokens.
- Evolution uses a narrative-only merge contract, preserves the requested story
  count, contains no explainer/CTA scaffolding, and is scored fresh by the Critic.
  It receives no synthetic score or approval bonus.
- Evolution is opt-in (`OMNICAST_DEBATE_EVOLUTION=1`) rather than part of the
  normal debate path; the measured horror merge was slower, short, and no better
  than its source variants.
- Per-variant cost counts each distinct LLM client once and stops new rounds at the
  configured variant budget.
- Final product selection prefers a draft that clears the deterministic spoken-word
  floor over a higher-scored but unusably short unapproved draft.

## Acceptance checks

Release-integrity checks (regression-tested against the 2026-07-17 artifact itself in
`tests/unit/test_narrative_release_integrity.py`, using the verbatim plan and narration
in `tests/fixtures/narrative/true_dread_20260717.json`):

- Two stories sharing a typed threat/escape mechanism are rejected before any writer
  call, while a compilation distinct on every axis passes.
- A story whose `topic_promise` does not deliver the topic subject is rejected at plan
  time; a legitimate synonym ("newspaper bundles") is accepted on the stem.
- A minor facing a human threat whose plan commits to no response at all is rejected at
  plan time; authorities, a trusted adult, and a concrete stated reason are each
  accepted; adults do not inherit the obligation.
- A declared safety response that never reaches the aftermath blocks release, for both
  the authorities and the trusted-adult path; an incidental family noun elsewhere in the
  story and a bare "adult" do not discharge it.
- A challenger sharing the critic's resolved provider/model returns `not_independent`
  and cannot content-lock on a pass, fails before the writer when required, and can
  still veto with a grounded quote; a genuinely independent pass does unlock.
- A run where every attempt aborts raises `NarrativeRunExhausted` carrying exact
  aggregate planner/audit call counts, cost, latency, and every rejected plan; the
  evidence survives a JSON round-trip and invents no score or script.
- A dead primary auditor whose verdict is rescued by escalation still reports
  `primary_healthy=False`, `verdict_source="escalation"`, and aborts with zero writer
  calls when the mandatory post-writer judges share the failed account; with a fallback
  in a different health domain configured for every mandatory stage, the same run drafts
  and locks.
- A health failure aborts at the FIRST audit: `planner=1`, two bounded primary retries,
  one escalation, `plan_repair=0`, `story_writer=0`, and the blocked plan is still on
  the rejection record. Missing a fallback for one mandatory stage names that stage and
  aborts before any repair or writer call.
- After a health domain is marked dead, `story_compliance`, `critic_score` and
  `final_editor` primary counts stay at zero and the `*_escalation` counters carry the
  exact call counts instead.
- A challenger matching the resolved identity of a judge that ACTUALLY approved the
  release — including a fallback judge — cannot approve; an Opus challenger over Sonnet
  judges can, and records `challenger_is_independent`. A veto blocks either way.
- Each rejected plan carries its own aligned reasons, stage, fingerprint, digest, audit
  and call counts, in planner order; a schema-invalid planner response is recorded with
  redacted `raw_evidence` and `plan=None`, earns one contract-only retry naming the
  missing field, and a retry that completes the plan saves the concept.
- Every major/critical plan objection quotes the exact plan text it challenges;
  ungrounded or fabricated quotes fail the audit contract closed rather than reading as
  clean; the live geometry/latch/route/brew/trade blockers still block; a
  `site_specific` claim is demoted to a minor recommendation and cannot veto a concept,
  unless the plan itself states the policy the story contradicts.
- A one-story block is repaired in place: approved story plans stay byte-identical, the
  repair re-runs preflight/freshness/mechanism diversity and a fresh audit, a repair that
  returns the wrong stories or collides mechanisms is rejected, and a premise-wide
  objection is never repaired locally.
- Narration that never speaks a locked minor's age, or never names the topic subject,
  blocks release.
- A last paragraph closing on "I never went back to find out who he was" blocks release;
  the same clause mid-story does not.
- A `minor`/`style` issue whose text says "physically unclear" is promoted to a blocking
  `major` contradiction; a genuine pacing note stays minor; an unquoted claim stays minor.
- One grounded major blocks the plan; an unresolved block at the attempt bound aborts
  before the writer; an audit provider failure aborts and never reports clean; an
  escalation to the same client is not counted as a second opinion.
- A repeated concept is rejected before story generation; a rejected plan can still be
  repaired and accepted, because a rejection must not burn its own concept.
- A challenger `fail` with an exact quote blocks; an ungrounded veto and an unreachable
  challenger fail closed; the challenger does not run for compilations that are not
  release candidates.
- `attempts_executed`, `attempt_summaries`, `aggregate_call_counts`, cost, and latency
  cover every attempt, including aborted ones — attempt 2 never reads as if attempt 1
  was free.

- Three story-generation calls overlap in time and receive different locked plans.
- A local hard-gate failure retries only that story once before audit; a clean story is
  byte-identical and no recovery call occurs on the normal happy path.
- Per-story compliance calls overlap in time, bind to the exact assigned plan, and
  require exact unique quotes in narrative order for all five required beats.
- Missing escape completion or ending completion blocks lock even when the global
  score exceeds the channel threshold; malformed compliance output blocks annotation.
- After repair, only changed stories are re-audited and unchanged story bytes and
  approved audits are preserved.
- A failed story alone is repaired; non-failing story narration is byte-identical.
- Repair runs once, produces two candidates from the same baseline, and a regressed
  candidate is rolled back. A malformed/non-atomic pair receives at most one bounded
  contract retry under the same forensic anchors and edit budgets.
- Content score excludes visuals, SFX, stock-footage suitability, and prosody.
- Annotation cannot change voiceover; a missing/duplicate/unknown beat ID fails the
  production-ready gate.
- Rejected output has `stage=needs_edit`, no canonical `script.txt`, and cannot be
  selected by the normal render path.
- Invalid/non-unique forensic quotes cannot reach patch generation; a failed critic
  integrity retry fails closed.
- Patch application is atomic and bounded; bytes outside accepted spans are unchanged.
- Original narration participates anonymously in comparison and wins ties, invalid
  selection, low confidence, and any final gate/dimension/score regression.
- Two channel strategies loaded sequentially or concurrently remain independent.
- Annotation output containing narration fields is rejected, and assembled voiceover
  preserves punctuation/case as well as words.

- Narrative prompts contain the ledger, evidence, ending, number, voice, and
  self-reassurance constraints.
- Narrative expansion contains no explainer requests such as data points,
  objections/rebuttals, or key statistics.
- Narrative expansion emits only JSON insertion patches and preserves every clean
  scene byte-for-byte.
- Narrative revision does not force five segments, CTAs, open loops, stock footage,
  or statistics.
- A regressed debate revision can never replace its better prior round.
- An evolved draft's stored score and approval are the Critic's fresh result.
- Explainer generation and revision behavior remains unchanged.

## Release claims and benchmark

- `content_valid`: objective structure and continuity checks pass.
- `editorially_ready`: the channel score/dimension floors and final compilation gate
  pass with no unresolved major/critical issue.
- `production_test_ready`: locked annotation is exact and any manual override is
  SHA-256-bound to the released script and storyboard.
- `competitive_validated`: never inferred from a model score. It requires a fixed
  30-topic blind benchmark against the strongest baseline, majority wins on at least
  21 topics, zero critical continuity defects, no more than 5% major defects, adequate
  rater agreement, and subsequent matched-video retention evidence.

Benchmark reporting includes automated acceptance rate, all-attempt cost per accepted
script, p50/p95 latency, rater agreement, and an inconclusive result when evidence is
weak. Until then the strongest permitted claim is `production_test_ready`.

`production_test_ready` is a statement about gates, not about quality. On 2026-07-17 an
artifact carried that tier and an independent manual audit scored it ~58-62; the tier
was accurate and the video was not shippable. The gates added since are proven against
that specific failure and are not evidence that the next artifact is good. The claim
this spec supports is: *the known defect classes are now blocked deterministically or
fail closed.* Anything stronger — including task 2.1's own DoD — requires a paid
artifact that reaches `production_ready` and then survives an independent manual audit
with zero critical/major defects. `competitive_validated` remains separate, unclaimed,
and gated on the 30-topic blind benchmark above.

**Current status (2026-07-17).** No live run has produced a releasable script. The 07:33
run produced one and it was a false positive; the 13:34 run produced none in 575.1
seconds and was correct to; the 14:02 health check was stopped by hand after ~9.5
minutes; the 14:32 max-quality run was stopped by hand after ~31 minutes with zero
writer calls; the 15:36 claude_only run was stopped by hand after every plan-repair
call hit max_turns_reached; the 16:03 run completed fail-closed in 504.1s and wrote
nothing. Verification is unit-level only:

- **136 focused passed** — `test_narrative_release_integrity.py` (87) +
  `test_narrative_autonomy.py` (23) + `test_narrative_unit_pipeline.py` (26).
- **207 passed** across all seven `test_narrative_*.py` files, plus **40 passed** in
  `test_claude_cli_effort.py` and **25 passed** in `test_narrative_claude_only.py`.
- **1292 passed, 6 skipped** for the full `tests/unit` suite.
- `scripts/claude_cli_smoke.py` PASSES against the installed CLI (one turn, no
  `max_turns_reached`, usable JSON) — the one check the unit suite structurally cannot
  make.

`claude_only` is a routing change, not a quality change. It buys the ability to run at
all while DeepSeek is dead; it does not make the next artifact good, and every release
gate is unchanged.

Task 1.6 is **REOPENED** and task 2.1 remains **WIP**; neither `production_ready` nor
`competitive_validated` is claimed. Unit tests prove the gates behave as specified
against a known failure; they are not evidence that a future artifact is good. The
external blocker is that DeepSeek appears unhealthy (every primary plan-audit call
402'd), which the pipeline now detects before the writer instead of after it.
