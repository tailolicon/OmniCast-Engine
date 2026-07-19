"""Dry-run test for imagen4 module."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from omnicast.media.imagen4 import generate_images_for_script

SAMPLE = {
    "channel_id": "test_channel",
    "topic": "Test Topic",
    "variant_id": "A",
    "score": 85,
    "approved": True,
    "hook": "Hook text",
    "outro": "Outro text",
    "scenes": [
        {
            "segment": "Intro",
            "voiceover": "Hello world",
            "visual_prompt": "A bright sunny day with blue sky, 16:9",
            "sfx": None,
            "duration_s": 4.0,
        },
        {
            "segment": "Body",
            "voiceover": "Here is the content",
            "visual_prompt": "Person looking at retirement charts on laptop, modern office",
            "sfx": "whoosh",
            "duration_s": 5.0,
        },
        {
            "segment": "Outro",
            "voiceover": "Thanks for watching",
            "visual_prompt": "",   # empty → should be skipped
            "sfx": None,
            "duration_s": 3.0,
        },
    ],
}

TMP_DIR = Path(__file__).parent / "output" / "scripts" / "_test_dry_run"
TMP_JSON = TMP_DIR / "variant_A_score85.json"


async def main():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    TMP_JSON.write_text(json.dumps(SAMPLE, indent=2), encoding="utf-8")

    results = await generate_images_for_script(
        script_json_path=str(TMP_JSON),
        google_api_key="fake_key_dry_run",
        dry_run=True,
    )

    for r in results:
        print(f"  scene {r['scene_index']:02d} [{r['status']:7s}] {r['image_path'] or '(no path)'}")

    done    = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"\nTotal: {len(results)}  done={done}  skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
