"""Apply an exact, auditable scene-level editorial patch to a Writer raw draft.

This is deliberately deterministic: every requested voiceover must match exactly
once unless ``allow_missing`` is set. It gives an operator or agent a safe way to
make surgical edits after model quota exhaustion without flattening the
storyboard or bypassing the normal release gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from omnicast.agents.writer import WriterAgent


def _all_scene_lists(draft):
    yield draft.hook_scenes
    for segment in draft.segments:
        yield segment.scenes
    yield draft.outro_scenes


def apply_patch(draft, patch: dict):
    delete = set(patch.get("delete_voiceovers") or [])
    replacements = {
        item["from"]: item for item in (patch.get("replace_scenes") or [])
    }
    insertions = {}
    for item in patch.get("insert_after") or []:
        insertions.setdefault(item["after"], []).extend(item["scenes"])
    deleted: set[str] = set()
    replaced: set[str] = set()
    inserted_after: set[str] = set()
    heading_replacements = patch.get("rename_segments") or {}

    hook_scenes = list(draft.hook_scenes)
    segments = list(draft.segments)
    outro_scenes = list(draft.outro_scenes)
    groups = [hook_scenes] + [list(segment.scenes) for segment in segments] + [
        outro_scenes
    ]

    for group_index, scenes in enumerate(groups):
        kept = []
        for scene in scenes:
            voiceover = scene.voiceover.strip()
            if voiceover in delete:
                deleted.add(voiceover)
                continue
            replacement = replacements.get(voiceover)
            if replacement is not None:
                updates = {"voiceover": replacement["to"]}
                for field in (
                    "visual_prompt",
                    "sfx",
                    "pace",
                    "pause_after_ms",
                    "emphasis",
                ):
                    if field in replacement:
                        updates[field] = replacement[field]
                scene = scene.model_copy(update=updates)
                replaced.add(voiceover)
            kept.append(scene)
            if voiceover in insertions:
                for addition in insertions[voiceover]:
                    kept.append(
                        scene.model_copy(
                            update={
                                "voiceover": addition["voiceover"],
                                "visual_prompt": addition["visual_prompt"],
                                "sfx": addition.get("sfx"),
                                "pace": addition.get("pace", "normal"),
                                "pause_after_ms": addition.get(
                                    "pause_after_ms", 0
                                ),
                                "emphasis": addition.get("emphasis", []),
                            }
                        )
                    )
                inserted_after.add(voiceover)
        groups[group_index] = kept

    missing_delete = delete - deleted
    missing_replace = set(replacements) - replaced
    missing_insert = set(insertions) - inserted_after
    if not patch.get("allow_missing") and (
        missing_delete or missing_replace or missing_insert
    ):
        raise ValueError(
            "Patch did not match every requested scene: "
            f"missing_delete={sorted(missing_delete)!r}, "
            f"missing_replace={sorted(missing_replace)!r}, "
            f"missing_insert={sorted(missing_insert)!r}"
        )

    updated_segments = []
    renamed: set[str] = set()
    for segment, scenes in zip(segments, groups[1:-1], strict=True):
        heading = segment.heading
        if heading in heading_replacements:
            renamed.add(heading)
            heading = heading_replacements[heading]
        updated_segments.append(
            segment.model_copy(
                update={
                    "heading": heading,
                    "scenes": scenes,
                    "content": " ".join(scene.voiceover for scene in scenes),
                    "estimated_duration_seconds": max(
                        1, round(sum(scene.duration_s for scene in scenes))
                    ),
                }
            )
        )
    missing_headings = set(heading_replacements) - renamed
    if not patch.get("allow_missing") and missing_headings:
        raise ValueError(
            "Patch did not match every requested segment heading: "
            f"{sorted(missing_headings)!r}"
        )
    return draft.model_copy(
        update={
            "hook_scenes": groups[0],
            "hook": " ".join(scene.voiceover for scene in groups[0]),
            "segments": updated_segments,
            "outro_scenes": groups[-1],
            "outro": " ".join(scene.voiceover for scene in groups[-1]),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--variant-id", default="manual")
    args = parser.parse_args()

    raw = args.input.read_text(encoding="utf-8")
    spec = json.loads(args.patch.read_text(encoding="utf-8"))
    writer = WriterAgent(llm=None)  # parsing/serialization make no LLM call
    draft = writer._parse_draft(raw, args.variant_id, args.topic, version=3)
    patched = apply_patch(draft, spec)
    output = writer._draft_to_script_text(patched)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "spoken_words": writer._word_count(patched),
                "scenes": sum(len(group) for group in _all_scene_lists(patched)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
