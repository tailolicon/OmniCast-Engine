# Script output contract

The draft in `script.md` is parsed by the pipeline's existing parser
(`WriterAgent._parse_draft`). Anything outside this structure is silently lost, so the
structure is a hard gate. `scriptfarm/tools/validate_script.py` enforces the checklist below
in CI.

## Structure

```
HOOK:
SCENES:
[{"vo": "...", "visual": "...", "sfx": "alarm", "pace": "fast", "pause_after_ms": 0, "emphasis": ["$855,800"]}, ...]

SEGMENT 1: <heading>
SCENES:
[...]

SEGMENT 2: <heading>
SCENES:
[...]

... more segments ...

OUTRO:
SCENES:
[...]
```

- Block keywords `HOOK:`, `SEGMENT <n>: <heading>`, `OUTRO:` start at column 0.
- Segments are numbered 1..N without gaps or duplicates.
- Each block contains `SCENES:` followed by ONE JSON array. A ```json fence around the
  array is tolerated but not required.

## Scene object fields

| field | required | rules |
| --- | --- | --- |
| `vo` | yes | Spoken narration. Target ≤ 25 words per scene (hard fail > 45). Natural speech, zero scripting jargon, no stage directions. |
| `visual` | yes | Concrete visual description / stock-footage query for that 3–5 s cut. |
| `sfx` | no | Sound cue name or omit/null. |
| `pace` | no | `slow` \| `normal` \| `fast`. |
| `pause_after_ms` | no | 0–2000. Dramatic beat after the scene. |
| `emphasis` | no | Up to 4 exact substrings of `vo` to stress. Only where there is a real number/stat — everything stressed = nothing stressed. |

## Checklist (what CI validates)

1. `HOOK:` block present, `OUTRO:` block present, ≥ 3 `SEGMENT n:` blocks.
2. Every block's `SCENES:` JSON array parses; every scene has non-empty `vo` and `visual`.
3. No scene `vo` over 45 words.
4. Total spoken words (all `vo` joined) ≥ `target_duration_min × 110`
   (from `scriptfarm/channels/<channel_id>/meta.json`).
5. No `{{` placeholder residue anywhere.
6. `result.json` exists beside `script.md` and its `item_id`/`channel_id` match the path.

Everything in the channel's SYSTEM.md (persona bans, no fabricated statistics, niche
compliance, hook rules) binds on top of this structural contract — CI cannot check honesty,
so the downstream critic on the operator's machine re-scores every imported draft.
