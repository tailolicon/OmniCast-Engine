"""Script Farm bridge for NARRATIVE channels — the release gate stays local.

The plain farm flow (scriptfarm/WORKER_START.md sections 1-8) short-circuits
into CriticAgent scoring, which is fine for explainer channels but bypasses
the unit_first release gate (per-story compliance, narrative judges, repair
waves, final editor, release challenger). Narrative channels need the cloud
worker to be the WRITER ONLY, with every judge still running locally.

This bridge splits one unit_first run around the writer call:

  export  plan locally (plan_only.py: one planner call + audit), render the
          EXACT _story_prompt the pipeline would send, commit it as a
          type="narrative" queue item, push. The cloud worker answers the
          prompt verbatim — no channel templates, no FORMAT.md.
  import  pull the worker's story, parse it with the same _parse_story_output
          the live writer path uses, then run the full pipeline with
          OMNICAST_NARRATIVE_PLAN_FILE (approved plan takes planner attempt 1)
          and OMNICAST_NARRATIVE_DRAFT_FILE (draft on disk is judged, not
          rewritten). ACCEPTED/REJECTED comes from the same gate as a live run.

Single-story only (--stories 1): OMNICAST_NARRATIVE_DRAFT_FILE feeds exactly
story_1 of a one-story plan, and the corpus reads singles ahead of
compilations anyway (see run() in narrative_pipeline.py).

Usage:
  python scripts/farm_narrative.py export --channel true_dread_files_us \
      --topic "overnight hotel front desk off the highway" [--tries 3] [--no-push]
  python scripts/farm_narrative.py import [--item ID] [--no-pull] [--no-push]
  python scripts/farm_narrative.py status
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1]
REPO = IMPL.parent
FARM = REPO / "scriptfarm"
NARRATIVE_DIR = FARM / "narrative"
QUEUE = FARM / "queue.json"

sys.path.insert(0, str(IMPL / "src"))

WORKER_HEADER = """\
<!-- Script Farm NARRATIVE item — worker instructions.
     Answer the prompt below EXACTLY as written; it defines its own output
     format. Commit your raw answer (nothing else, no commentary, no code
     fences) to the response path named in queue.json for this item.
     Do NOT use the channel SYSTEM/TASK templates or FORMAT.md for this item. -->
"""

# Mirrors write_one() in narrative_pipeline.py — the worker adopts the same
# persona the live writer call gets as its system prompt.
WRITER_SYSTEM = (
    "You write restrained, plausible first-person horror recollections and "
    "obey the locked plan."
)


def slugify(text: str, max_len: int = 60) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def load_queue() -> dict:
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def save_queue(queue: dict) -> None:
    QUEUE.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_queue_item(item_id: str, channel_id: str, topic: str,
                     prompt_paths: list[str], response_paths: list[str],
                     added_by: str = "farm_narrative.py") -> dict:
    """Queue entry for a narrative item. Keeps the fields the CI queue
    validator asserts on (item_id/channel_id/title/status) plus the narrative
    extension fields workers act on."""
    return {
        "item_id": item_id,
        "channel_id": channel_id,
        "title": topic,
        "type": "narrative",
        "status": "queued",
        "prompt_paths": prompt_paths,
        "response_paths": response_paths,
        "added_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "added_by": added_by,
    }


def normalize_draft(worker_text: str, plan_item) -> str:
    """Worker answer -> the draft-file format load_draft_file() reads.

    The worker may answer in any shape _parse_story_output accepts (JSON,
    paragraph array, TITLE/NARRATION markers, plain prose). Parsing here with
    the same adapter the live writer path uses means import never depends on
    the worker guessing our file format.
    """
    from omnicast.agents.narrative_pipeline import _parse_story_output

    output = _parse_story_output(worker_text, plan_item)
    title = (output.title or plan_item.title).strip().replace("\n", " ")
    return f"[{title}]\n\n{output.narration.strip()}\n"


def select_drafted_item(queue: dict, item_id: str = "", channel_id: str = "") -> dict | None:
    """Oldest drafted narrative item, optionally pinned by id/channel."""
    candidates = [
        item for item in queue.get("items", [])
        if item.get("type") == "narrative"
        and (not item_id or item.get("item_id") == item_id)
        and (not channel_id or item.get("channel_id") == channel_id)
        and (item.get("status") == "drafted" or (item_id and item.get("status") in {"drafted", "queued"}))
    ]
    candidates.sort(key=lambda item: item.get("added_at", ""))
    return candidates[0] if candidates else None


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=check)


def git_commit_push(paths: list[str], message: str, push: bool) -> None:
    _git("add", "--", *paths)
    staged = _git("diff", "--cached", "--name-only").stdout.strip()
    if not staged:
        print("[git] nothing to commit")
        return
    _git("commit", "-m", message)
    if not push:
        print("[git] committed (push skipped)")
        return
    for attempt in range(3):
        result = _git("push", "origin", "main", check=False)
        if result.returncode == 0:
            print("[git] pushed")
            return
        # Workers push to main too — rebase our queue/prompt commit on top.
        _git("pull", "--rebase", "origin", "main", check=False)
    raise RuntimeError(f"git push failed after retries: {result.stderr.strip()}")


async def _load_strategy(channel_id: str):
    from omnicast.agents.narrative_pipeline import NamedChannelStrategy
    from omnicast.config.channel import ChannelProfileLoader
    from omnicast.config.narrative_quality import resolve_script_profile

    channel = await ChannelProfileLoader(IMPL / "channels").load(channel_id)
    profile_id = (getattr(channel, "script_profile", "") or "").strip()
    if not profile_id:
        raise SystemExit(f"{channel_id}: no script_profile — not a unit_first "
                         "narrative channel; use the plain farm flow instead")
    return NamedChannelStrategy.from_quality_profile(
        resolve_script_profile(profile_id))


def cmd_export(args: argparse.Namespace) -> int:
    from omnicast.agents.narrative_pipeline import (
        _story_prompt, load_approved_plan,
    )

    plan_file_tmp = IMPL / "output" / "_runlogs" / (
        f"farm_plan_{slugify(args.topic, 40)}.json")
    plan_file_tmp.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, args.tries + 1):
        print(f"[plan] attempt {attempt}/{args.tries}")
        proc = subprocess.run(
            [sys.executable, str(IMPL / "scripts" / "plan_only.py"),
             "--channel", args.channel, "--topic", args.topic,
             "--stories", "1", "--save", str(plan_file_tmp)],
            cwd=IMPL, text=True)
        if proc.returncode == 0 and plan_file_tmp.exists():
            try:
                plan = load_approved_plan(plan_file_tmp, 0)
                break
            except Exception as exc:
                print(f"[plan] saved file unusable: {exc}")
        plan_file_tmp.unlink(missing_ok=True)
    else:
        print("EXPORT_FAILED: no plan accepted")
        return 1

    if len(plan.stories) != 1:
        print(f"EXPORT_FAILED: expected 1 story, plan has {len(plan.stories)}")
        return 1

    strategy = asyncio.run(_load_strategy(args.channel))
    item = plan.stories[0]
    per_story = max(1, plan.target_word_count // len(plan.stories))
    prompt = _story_prompt(item, per_story, plan.cold_open, strategy,
                           topic=plan.topic)

    stamp = _dt.datetime.now().strftime("%Y%m%d")
    item_id = f"{stamp}_{slugify(args.topic)}-nu"
    out_dir = NARRATIVE_DIR / item_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(
        plan_file_tmp.read_text(encoding="utf-8"), encoding="utf-8")
    prompt_rel = f"scriptfarm/narrative/{item_id}/story_1.prompt.md"
    response_rel = f"scriptfarm/narrative/{item_id}/story_1.md"
    (out_dir / "story_1.prompt.md").write_text(
        WORKER_HEADER + "\nSYSTEM (adopt as your persona):\n"
        + WRITER_SYSTEM + "\n\n=== PROMPT ===\n\n" + prompt + "\n",
        encoding="utf-8")

    queue = load_queue()
    if any(entry.get("item_id") == item_id for entry in queue["items"]):
        print(f"EXPORT_FAILED: item_id {item_id} already queued")
        return 1
    queue["items"].append(build_queue_item(
        item_id, args.channel, args.topic, [prompt_rel], [response_rel]))
    save_queue(queue)

    git_commit_push(
        ["scriptfarm/queue.json", f"scriptfarm/narrative/{item_id}/"],
        f"farm(narrative): enqueue {item_id} — writer prompt for cloud worker",
        push=not args.no_push)
    print(f"EXPORTED item_id={item_id}")
    print("Spawn a worker with:\n  Run tailolicon/OmniCast-Engine/scriptfarm/"
          "WORKER_START.md from main.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from omnicast.agents.narrative_pipeline import load_approved_plan

    if not args.no_pull:
        _git("pull", "--rebase", "origin", "main", check=False)

    queue = load_queue()
    entry = select_drafted_item(queue, args.item, args.channel)
    if entry is None:
        print("IMPORT_NOTHING: no drafted narrative item in the queue")
        return 1
    item_id = entry["item_id"]
    response_path = REPO / entry["response_paths"][0]
    if not response_path.exists():
        print(f"IMPORT_FAILED: {item_id} marked {entry['status']} but "
              f"{entry['response_paths'][0]} does not exist")
        return 1

    plan_path = NARRATIVE_DIR / item_id / "plan.json"
    plan = load_approved_plan(plan_path, 0)
    draft_text = normalize_draft(
        response_path.read_text(encoding="utf-8"), plan.stories[0])
    draft_path = IMPL / "output" / "_runlogs" / f"farm_{item_id}_draft.txt"
    draft_path.write_text(draft_text, encoding="utf-8")
    words = len(draft_text.split())
    print(f"[import] {item_id}: draft normalized ({words} words) — "
          "running the FULL release gate locally")

    env = dict(os.environ)
    env.pop("OMNICAST_SCRIPT_WRITER_PROVIDER", None)  # recovery/repair stay local
    env["OMNICAST_NARRATIVE_PLAN_FILE"] = str(plan_path)
    env["OMNICAST_NARRATIVE_DRAFT_FILE"] = str(draft_path)
    env["OMNICAST_NARRATIVE_STORY_COUNT"] = "1"
    log_path = IMPL / "output" / "_runlogs" / f"farm_{item_id}_gate.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            [sys.executable, str(IMPL / "scripts" / "run_phase2_unit_first.py"),
             "--channel", entry["channel_id"], "--topic", entry["title"],
             "--stories", "1"],
            cwd=IMPL, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)

    tail = log_path.read_text(encoding="utf-8").strip().splitlines()
    verdict = tail[-1] if tail else "(empty log)"
    accepted = proc.returncode == 0 and any(
        line.startswith("ACCEPTED") for line in tail[-5:])
    print(f"[gate] {verdict}")

    queue = load_queue()  # release-gate runs are long; refetch before writing
    for candidate in queue["items"]:
        if candidate.get("item_id") == item_id:
            candidate["status"] = "approved" if accepted else "rejected"
            candidate["gate_verdict"] = verdict[:300]
            candidate["gated_at"] = _dt.datetime.now(
                _dt.timezone.utc).isoformat(timespec="seconds")
    save_queue(queue)
    git_commit_push(
        ["scriptfarm/queue.json"],
        f"farm(narrative): {item_id} release gate -> "
        f"{'approved' if accepted else 'rejected'}",
        push=not args.no_push)
    print(f"IMPORT_{'ACCEPTED' if accepted else 'REJECTED'} item={item_id} "
          f"log={log_path}")
    return 0 if accepted else 2


def cmd_status(_args: argparse.Namespace) -> int:
    queue = load_queue()
    rows = [item for item in queue.get("items", [])
            if item.get("type") == "narrative"]
    if not rows:
        print("no narrative items in the queue")
        return 0
    for item in rows:
        print(f"{item['item_id']:<50} {item['status']:<9} "
              f"{item.get('channel_id', '')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="plan locally, enqueue writer prompt")
    p_export.add_argument("--channel", default="true_dread_files_us")
    p_export.add_argument("--topic", required=True)
    p_export.add_argument("--tries", type=int, default=3,
                          help="planner attempts before giving up")
    p_export.add_argument("--no-push", action="store_true")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="judge a drafted story via the full release gate")
    p_import.add_argument("--item", default="")
    p_import.add_argument("--channel", default="")
    p_import.add_argument("--no-pull", action="store_true")
    p_import.add_argument("--no-push", action="store_true")
    p_import.set_defaults(func=cmd_import)

    p_status = sub.add_parser("status", help="list narrative queue items")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
