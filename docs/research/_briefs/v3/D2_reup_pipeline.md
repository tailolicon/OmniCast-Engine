# BRIEF D2 — Tool_Reup_Douyin (Reup Video): full zh->vi translate/dub pipeline extraction

Read `docs/research/_briefs/v3/COMMON_V3.md` first and obey its output rules.

**Working root:** `E:\Project\OmniCast Engine\_refs\Tool_Reup_Douyin`
**Write report to:** `E:\Project\OmniCast Engine\docs\research\V3_D2_ReupPipeline.md`

**License:** no LICENSE file, but the project owner confirmed this is a community repo and
cleared direct reuse. So the port plan is a **lift-and-shift plan, not a reimplementation
plan**: for each capability say `copy as-is` / `copy + adapt` / `drop`, and name the exact
files and functions. We still need every prompt and every numeric constant verbatim, because
we must know what we are carrying over and what the numbers mean.

This repo is the most advanced zh->vi dubbing pipeline we have found. It has ~10.7k lines
across `src/app/{translate,tts,asr,audio,subtitle}`. We want ALL of its tuning knowledge.

## 1. Pipeline topology (exact)

Trace and draw the real call graph for BOTH translation lanes:
- **Contextual V2** (dialogue lane): `contextual_pipeline.py` + `contextual_runtime.py`
- **narration_fast_v2** (low-cost narration lane): `narration_fast_v2.py`

For each lane give an ordered stage list. Per stage: function name, file:line, input type,
output type, which model is called, whether it is deterministic or LLM.
Explicitly answer: what decides which lane a scene goes down? Paste the routing predicate
verbatim with its thresholds.

## 2. PROMPTS — the crown jewels

Find EVERY prompt/system-instruction string in the repo (start with `translate/presets.py`,
`openai_engine.py`, `contextual_runtime.py`, `narration_fast_v2.py`, and any `presets/` or
prompt template files on disk, including JSON files).

For each prompt:
- Paste the FULL text verbatim in a fenced block. Do not truncate. Do not paraphrase.
- Give `file:line`.
- Name the stage that uses it.
- List the interpolated variables and where their values come from.
- Note the output JSON schema attached to it (Structured Outputs) — paste the schema/pydantic
  model verbatim from `translate/models.py`.

Then answer:
- What is the exact prompt section ORDER used for prompt-cache reuse? Paste the assembly code.
- How is `prompt_cache_key` built? Paste verbatim.
- Exact model names/IDs used, per stage. Exact `temperature`, `top_p`, `max_output_tokens`,
  `reasoning` effort, and any `service_tier`. Paste the request-building code verbatim.

## 3. Scene chunking & context windows

From `scene_chunker.py` and `contextual_runtime.py`:
- Exact chunk size rules: max segments per scene, max chars, gap-in-seconds threshold that
  starts a new scene, overlap. Paste every constant with file:line.
- Batch sizes for each LLM stage, and the split-on-failure logic (the "split batches for
  mismatched ids AND retryable parse failures" behaviour). Paste it.
- Checkpointing: `contextual_checkpoint.py` — what is stored, key shape, resume logic. Paste.

## 4. Semantic QC rule set (`semantic_qc.py`) — extract EVERY rule

For each rule: rule id/name, what it checks, the exact threshold constant, the severity, the
review reason code it emits, and whether it hard-blocks downstream. Paste the rule bodies.
Cross-reference `docs/REVIEW_REASON_CODES.md` and `docs/ERROR_TAXONOMY.md` — paste those two
docs in full (they are short and are pure distilled experience).
Also paste `docs/SEMANTIC_QC_SPEC.md`, `docs/KNOWN_LIMITATIONS.md`, and
`docs/GOLDEN_SEMANTIC_DATASET.md` in full.
Explain the review gate: what state must a segment be in before TTS/export is allowed?
Paste the gating predicate verbatim.

## 5. The zh->vi specific intelligence (highest value — be exhaustive)

This is where a Vietnamese-market reup tool beats a generic translator. Extract:
- **Character profiles / relationship memory** (`relationship_memory.py`, `character_profiles`,
  `relationship_profiles`, `scene_memories` tables): the exact schema, how a character is
  identified across scenes, how relationships are inferred, how they are fed back into prompts.
  Paste the DDL from `project/database.py` for all of these tables.
- **Honorifics / xưng hô**: Vietnamese pronoun selection (anh/em/tôi/cậu/tớ/ông/bà/con/cháu...).
  Where is this decided? Paste every list/table/enum of pronoun options and the selection logic.
  This is THE hardest part of zh->vi and we want their entire approach.
- **Register model**: `register/tone/turn_function/relation_type/politeness/power_direction/
  emotional_tone` — paste the full enum value lists and where each is produced/consumed.
- **Term memory**: `narration_term_memory_defaults.json` — paste it in full. Explain how the
  term/entity mini-pass works and how the term sheet is injected back into prompts.
- **subtitle_text vs tts_text**: why two fields, what transformations differ between them
  (numbers, abbreviations, punctuation, reading of units/symbols). Paste the rules.
- Any Chinese-specific handling: 成语/idioms, measure words, names transliteration
  (Hán-Việt vs pinyin), numbers/dates, scientific notation repair. Paste the code.

## 6. Budget governor & cost control (`narration_fast_v2.py`)

- Paste the budget governor verbatim: what counts as budget, the caps, the escalation policy
  ("sparse escalation"), and what happens when the budget is exhausted.
- Any token estimation code. Paste it.

## 7. ASR config

From `asr/faster_whisper_engine.py`:
- Exact model size, device, compute_type, beam_size, VAD settings and every VAD parameter,
  language handling, `condition_on_previous_text`, temperature fallback list, word timestamps,
  `initial_prompt`. Paste the call verbatim.
- How are speakers assigned (is there diarization, or heuristics)? Paste.
- Segment persistence schema. Paste the DDL for `segments`.

## 8. TTS + audio (`tts/`, `audio/`)

- `tts/presets.py` + `presets/` on disk: paste every preset JSON/dict verbatim (name, engine,
  voice id, language, sample rate, speed, volume, pitch).
- Speaker->voice binding + voice policy precedence: paste the resolver verbatim.
- **Stage hashing / cache keys**: what exactly goes into a TTS clip cache key? Paste the
  hashing function. (We need this — it determines correct incremental rerun.)
- `audio/voiceover_track.py`: how are TTS clips fitted to subtitle slots? Paste the
  time-fitting logic: does it stretch (atempo), pad, trim, or shift? Exact tolerance values,
  atempo bounds, crossfade lengths, gap handling. Every constant with file:line.
- `audio/mixdown.py`: paste the exact ffmpeg filter graph strings and every level constant
  (voice gain, original background volume, BGM volume, ducking params, sidechaincompress
  settings, loudnorm/EBU R128 targets). We specifically need the "original_volume = 0.07"
  style numbers and where each comes from.

## 9. Subtitle rendering

- `subtitle/export.py` + `hardsub.py`: paste the full default ASS style block verbatim
  (font, size, colors, outline, shadow, margins, alignment) and any per-profile overrides.
- Exact ffmpeg subtitle burn-in command, including escaping of Windows paths (this is a
  classic breakage point) — paste verbatim.
- `subtitle/qc.py`: exact CPS, CPL, min/max duration, overlap tolerance constants. Paste all.
- The `Subtext gốc` (dual-line original subtitle) rendering. Paste.

## 10. Project profiles

Paste every file under `presets/project_profiles/*.json` verbatim (or wherever they live),
plus `docs/PROJECT_PROFILES.md` in full. Explain what each numeric default is compensating for.

## 11. Export presets & watermark

Paste every export preset (YouTube 16:9, Shorts 9:16) verbatim: resolution, fps, video codec,
CRF/bitrate, preset, pix_fmt, audio codec/bitrate, and the exact ffmpeg arg lists.
Paste the watermark filter strings and default profiles.

## 12. Ops / resilience worth stealing

- `ops/doctor.py`: the full preflight check list and which stage each check blocks. Paste the
  check table.
- `ops/project_safety.py`: when is a backup taken, what is backed up. Paste triggers.
- `ops/cache_ops.py`: cache layout on disk (exact directory tree + filename patterns) and the
  orphan-retention rule. Paste.
- `core/jobs.py`: the job/progress/cancel/retry model. Paste the state machine.
- `docs/AI_BUGFIX_WORKFLOW.md` and `docs/RELEASE_CHECKLIST.md` — paste in full.

## 13. PORT PLAN FOR OMNICAST (required final section)

Table: `capability | source file:line | numeric config to carry over | reimplement difficulty
(S/M/L) | does OmniCast already have an equivalent (media/tts.py, media/subtitle.py,
media/ffmpeg.py, media/voice_router.py) | verdict`.
Then a ranked TOP-20 list: the twenty single most valuable things to bring across, most
valuable first, each one sentence + the numbers.

## Reminders

- No web search. No subagents. Read files directly.
- Prompts and numeric constants must be VERBATIM with `file:line`. Truncating a prompt makes
  the report useless.
- Mark everything `NO-LICENSE / reimplement` in the port plan.
