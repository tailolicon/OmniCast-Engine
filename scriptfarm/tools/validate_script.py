"""Script Farm CI validator — stdlib only (runs on bare GitHub Actions python).

Validates every scriptfarm/scripts/<channel>/<item>/script.md against the
structural contract in scriptfarm/FORMAT.md. Exit 1 on any failure.

Usage: python scriptfarm/tools/validate_script.py [script.md ...]
       (no args = validate all farm scripts)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FARM = Path(__file__).resolve().parents[1]

MAX_VO_WORDS = 45
FLOOR_WORDS_PER_MIN = 110


def _extract_scenes(block: str) -> list[dict] | None:
    """Parse the SCENES: JSON array in a block. None = missing/unparseable."""
    block = re.sub(r"```(?:json)?", "", block)
    m = re.search(r"SCENES\s*:\s*\[", block, re.IGNORECASE)
    if not m:
        return None
    raw = block[m.end() - 1:]
    dec = json.JSONDecoder()
    try:
        items, _ = dec.raw_decode(raw)
    except json.JSONDecodeError:
        try:
            items, _ = dec.raw_decode(re.sub(r",\s*([\]}])", r"\1", raw))
        except json.JSONDecodeError:
            return None
    return [i for i in items if isinstance(i, dict)]


def validate(script_path: Path) -> list[str]:
    errors: list[str] = []
    item_dir = script_path.parent
    channel_id = item_dir.parent.name
    item_id = item_dir.name
    text = script_path.read_text(encoding="utf-8")
    clean = re.sub(r"\*+", "", text)

    if "{{" in text:
        errors.append("placeholder residue '{{' found — TASK.md was not fully substituted")

    hook = re.search(r"HOOK\s*:\s*\n?(.*?)(?=\nSEGMENT\s*1\b|\Z)", clean,
                     re.DOTALL | re.IGNORECASE)
    outro = re.search(r"OUTRO\s*:\s*\n?(.*?)$", clean, re.DOTALL | re.IGNORECASE)
    segs = re.findall(r"SEGMENT\s*(\d+)\s*:\s*([^\n]*)\n(.*?)(?=\nSEGMENT\s*\d+|\nMID-ROLL|\nOUTRO|\Z)",
                      clean, re.DOTALL | re.IGNORECASE)

    if not hook:
        errors.append("missing HOOK: block")
    if not outro:
        errors.append("missing OUTRO: block")
    if len(segs) < 3:
        errors.append(f"only {len(segs)} SEGMENT blocks (need >= 3)")
    indices = [int(i) for i, _, _ in segs]
    if indices != list(range(1, len(indices) + 1)):
        errors.append(f"segment numbering not 1..N without gaps: {indices}")

    total_words = 0
    blocks = []
    if hook:
        blocks.append(("HOOK", hook.group(1)))
    blocks += [(f"SEGMENT {i}", body) for i, _, body in segs]
    if outro:
        blocks.append(("OUTRO", outro.group(1)))
    for name, body in blocks:
        scenes = _extract_scenes(body)
        if scenes is None:
            errors.append(f"{name}: SCENES JSON array missing or unparseable")
            continue
        if not scenes:
            errors.append(f"{name}: SCENES array is empty")
        for n, sc in enumerate(scenes, 1):
            vo = str(sc.get("vo", sc.get("voiceover", ""))).strip()
            visual = str(sc.get("visual", sc.get("visual_prompt", ""))).strip()
            if not vo:
                errors.append(f"{name} scene {n}: empty vo")
                continue
            if not visual:
                errors.append(f"{name} scene {n}: empty visual")
            words = len(vo.split())
            total_words += words
            if words > MAX_VO_WORDS:
                errors.append(f"{name} scene {n}: vo has {words} words (max {MAX_VO_WORDS})")

    meta_path = FARM / "channels" / channel_id / "meta.json"
    if meta_path.is_file():
        duration = int(json.loads(meta_path.read_text(encoding="utf-8"))
                       .get("target_duration_min", 10) or 10)
        floor = duration * FLOOR_WORDS_PER_MIN
        if total_words < floor:
            errors.append(f"total spoken words {total_words} < floor {floor} "
                          f"({duration} min x {FLOOR_WORDS_PER_MIN})")
    else:
        errors.append(f"unknown channel '{channel_id}' (no scriptfarm/channels/{channel_id}/meta.json)")

    result_path = item_dir / "result.json"
    if not result_path.is_file():
        errors.append("result.json missing beside script.md")
    else:
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("item_id") != item_id:
                errors.append(f"result.json item_id {result.get('item_id')!r} != path {item_id!r}")
            if result.get("channel_id") != channel_id:
                errors.append(f"result.json channel_id {result.get('channel_id')!r} != path {channel_id!r}")
        except json.JSONDecodeError as exc:
            errors.append(f"result.json invalid JSON: {exc}")

    return errors


def main(argv: list[str]) -> int:
    targets = ([Path(a) for a in argv]
               if argv else sorted((FARM / "scripts").glob("*/*/script.md")))
    if not targets:
        print("no farm scripts to validate")
        return 0
    failed = 0
    for path in targets:
        errs = validate(path)
        try:
            rel = path.relative_to(FARM.parent)
        except ValueError:
            rel = path
        if errs:
            failed += 1
            print(f"FAIL {rel}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"OK   {rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
