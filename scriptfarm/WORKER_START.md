# Script Farm — universal stateless worker entrypoint

> **Vietnamese summary / Tóm tắt:** Đây là điểm vào duy nhất cho worker AI sinh script trên cloud.
> Một câu lệnh cho ChatGPT (hoặc bất kỳ assistant nào có quyền đọc/ghi GitHub) là đủ:
> `Run tailolicon/OmniCast-Engine/scriptfarm/WORKER_START.md from main.`
> Không cần laptop, không cần API key: **chính model đang chat là writer**, kết quả commit thẳng vào repo.

This is the only human prompt required for a fresh worker:

> Run `tailolicon/OmniCast-Engine/scriptfarm/WORKER_START.md` from `main`.

Repository state is authoritative; chat history is not. A fresh worker MUST NOT rely on chat
memory, copied handoffs, or stale SHA assumptions.

## 0. Ground rules

- **You (the assistant model) are the scriptwriter.** No external LLM API, local shell,
  container, or harness is required. Your own generation IS the compute.
- Use connected GitHub read/write operations for every durable step. Before reporting that
  GitHub is read-only, actually attempt the write with a fresh blob/ref SHA. One rejected
  write is capability-local — retry through another supported GitHub operation or move to the
  next eligible unit; it is never a session-end signal.
- Farm workers only touch `scriptfarm/**`. Never modify `implementation/**`, workflows, or
  any other path.
- Work on `main` directly. All writes use optimistic concurrency: refetch the file SHA
  immediately before each update; on conflict, refetch and reapply.

## 1. Read the router (minimum reads, in order)

1. `scriptfarm/queue.json` — the work list.
2. `scriptfarm/FORMAT.md` — the output contract (validation gate).
3. This file's remaining sections.

Do not bulk-read channel templates before selecting a unit.

## 2. Select and claim exactly one unit

1. Eligible unit = the oldest `queue.json` item with `"status": "queued"` that has **no**
   claim file, or one whose claim is expired (see below).
2. Claim by **creating** `scriptfarm/claims/<item_id>.json` (a create fails if the file
   already exists — that atomicity is the lock):

```json
{
  "item_id": "<item_id>",
  "worker": "<platform/model, e.g. chatgpt-web>",
  "claimed_at": "<ISO-8601 UTC>",
  "note": "drafting"
}
```

3. If the create fails (already claimed), immediately try the next eligible item. Do not wait.
4. **Claim expiry:** a claim older than 2 hours whose item is still `queued` is
   takeover-eligible — overwrite it with your own claim (add `"takeover_from"`).

## 3. Load the channel context

For the item's `channel_id`, read:

- `scriptfarm/channels/<channel_id>/SYSTEM.md` — your persona and hard rules for this draft.
- `scriptfarm/channels/<channel_id>/TASK.md` — the generation instruction.
- `scriptfarm/channels/<channel_id>/meta.json` — `content_format`, `target_duration_min`.

Substitute every `{{PLACEHOLDER}}` in TASK.md with the queue item's fields
(`title`, `key_points`, `target_audience`, `pain_point`, `content_angle`, `topics_done`,
`next_topic`). A missing field substitutes to an empty string, except `{{TITLE}}` which is
mandatory. **No `{{` may survive into your draft** — the validator rejects it.

## 4. Write the draft

Adopt SYSTEM.md as your operating persona, execute TASK.md, and emit **only** the script in
the exact structure defined by `scriptfarm/FORMAT.md` (HOOK / SEGMENT n / OUTRO blocks, each
with a `SCENES:` JSON array). Self-check against the FORMAT.md checklist before committing —
a failed GitHub Actions check on your commit means you fix the same file in place.

## 5. Commit the result

Create:

- `scriptfarm/scripts/<channel_id>/<item_id>/script.md` — the draft, nothing else in the file.
- `scriptfarm/scripts/<channel_id>/<item_id>/result.json`:

```json
{
  "item_id": "<item_id>",
  "channel_id": "<channel_id>",
  "title": "<queue item title>",
  "word_count": <spoken words, all vo fields>,
  "worker": "<platform/model>",
  "drafted_at": "<ISO-8601 UTC>",
  "notes": "<anything the operator should know, or empty>"
}
```

## 6. Update the queue and release

1. Refetch `scriptfarm/queue.json` (fresh SHA), set the item's `"status": "drafted"` and add
   `"draft_path"` + `"drafted_at"`. On write conflict: refetch, reapply, retry.
2. Delete your `scriptfarm/claims/<item_id>.json`.
3. **Completing one unit is a continuation trigger**: if another eligible queued item exists
   and the runtime still allows work, claim it and continue. Do not idle; do not self-time
   the session. Only a real platform cutoff starts the handoff (persist the newest valid
   draft first, then release your claim).

## 7. Enqueue protocol (the one-command flow)

When the operator says something like **“Sinh script cho <channel_id>: <topic>”** (or asks
for a new script in any wording):

1. Append a new item to `queue.json`:

```json
{
  "item_id": "<YYYYMMDD>_<ascii-slug-of-title>",
  "channel_id": "<one of scriptfarm/channels/*>",
  "title": "<topic>",
  "key_points": [],
  "target_audience": "",
  "pain_point": "",
  "content_angle": "",
  "topics_done": [],
  "next_topic": "",
  "status": "queued",
  "added_at": "<ISO-8601 UTC>",
  "added_by": "<who asked>"
}
```

Fill any brief fields the operator gave; research-quality `key_points` you can supply
yourself are welcome (cite mainstream facts only, no fabricated statistics — SYSTEM.md
rules bind here too).

2. Then immediately continue as a worker: claim the item you just enqueued and draft it
   (sections 2–6). One human sentence in, one committed validated script out.

## 8. Status semantics

| status | meaning | who sets it |
| --- | --- | --- |
| `queued` | waiting for a worker | enqueuer |
| `drafted` | script.md committed, CI validation pending/green | worker |
| `approved` | operator accepted; laptop render may consume it | operator |
| `rejected` | operator declined; item is dead unless re-queued | operator |

Workers never set `approved`/`rejected`. The render pipeline on the operator's machine
imports `drafted`/`approved` scripts through `OMNICAST_SCRIPT_FARM=1` and re-scores them
with its own critic — quality gates downstream stay authoritative.

## 9. Narrative items (`"type": "narrative"`) — different contract

Queue items carrying `"type": "narrative"` are **writer-only** units for the
operator's unit_first release gate (exported by
`implementation/scripts/farm_narrative.py`). For these items, sections 3-5
above do NOT apply:

1. Claim exactly as in section 2 (same claim file, same expiry rules).
2. **Ignore the channel SYSTEM/TASK templates and FORMAT.md entirely.** For
   each path in the item's `prompt_paths`, read the file: it contains a
   SYSTEM line (adopt it as your persona) and a complete, self-contained
   prompt that defines its own output format.
3. Answer each prompt exactly as it instructs, and commit your **raw answer**
   — no commentary, no markdown fences around it, nothing added — to the
   matching path in the item's `response_paths`.
4. Flip the item's status to `drafted` and release your claim (section 6
   rules). Do not touch any other field.

There is no CI validation for narrative responses: the operator's machine
parses your answer with the same adapter the live writer path uses, then runs
the full narrative release gate (compliance, judges, repair waves, final
editor, release challenger) locally. The gate — not you, not CI — decides
`approved`/`rejected` for these items.
