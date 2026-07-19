"""Set up SadTalker locally for the avatar (talking-head) pipeline.

Clones the SadTalker repo and downloads its model checkpoints, then prints the
SADTALKER_HOME you should export so SadTalkerProvider can find it.

    python -X utf8 setup_avatar.py                 # clone + download into ./SadTalker
    python -X utf8 setup_avatar.py --dir D:/models/SadTalker

WARNING: SadTalker is a 2023 codebase with old pinned deps (numpy<1.24,
basicsr, facexlib, gfpgan). On Python 3.13 these may not install cleanly — a
dedicated Python 3.10 venv is the reliable path. Checkpoints are ~5GB.
On CPU-only torch inference is slow (minutes per scene).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/OpenTalker/SadTalker"


def run(cmd: list[str], cwd: str | None = None) -> int:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd).returncode


def main() -> None:
    ap = argparse.ArgumentParser(description="Clone + download SadTalker for OmniCast avatars")
    ap.add_argument("--dir", default="SadTalker", help="target directory")
    args = ap.parse_args()

    home = Path(args.dir).resolve()
    print(f"[1/3] Clone SadTalker -> {home}")
    if not home.exists():
        if run(["git", "clone", REPO, str(home)]) != 0:
            print("[ERROR] git clone failed. Is git installed?")
            sys.exit(1)
    else:
        print("      already present, skipping clone")

    print("[2/3] Download checkpoints (~5GB)")
    dl_sh = home / "scripts" / "download_models.sh"
    if dl_sh.exists():
        # bash on Windows ships with Git; fall back to manual note otherwise.
        rc = run(["bash", str(dl_sh)], cwd=str(home))
        if rc != 0:
            print("      [warn] download_models.sh failed; download manually per the SadTalker README "
                  "(checkpoints/ + gfpgan/weights/).")
    else:
        print("      [warn] download_models.sh not found; follow the SadTalker README to fetch checkpoints.")

    print("[3/3] Done.")
    print(f"\n  Set this so OmniCast can find it:\n    set SADTALKER_HOME={home}\n")
    print("  Then render with an avatar:")
    print(f"    python -X utf8 render_real_video.py --avatar sadtalker --portrait <character.png>")


if __name__ == "__main__":
    main()
