"""Local resource probe used by the runtime router."""

from __future__ import annotations

import os
import subprocess
import sys

# On Windows, spawning nvidia-smi pops a console window each time. CREATE_NO_WINDOW
# suppresses it (mirrors the pattern in media/output_audit.py).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ResourceProbe:
    """Best-effort CPU/GPU probe with env override for tests and operators."""

    def gpu_free_mb(self) -> int:
        env = os.getenv("OMNICAST_GPU_FREE_MB")
        if env:
            try:
                return int(env)
            except ValueError:
                return 0
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                creationflags=_NO_WINDOW,
            )
            values = [
                int(line.strip())
                for line in result.stdout.splitlines()
                if line.strip().isdigit()
            ]
            return max(values) if values else 0
        except Exception:
            return 0

    def can_run(self, model_manifest) -> bool:
        min_vram = int(getattr(model_manifest, "min_vram_mb", 0) or 0)
        runtime = str(getattr(model_manifest, "runtime", "remote") or "remote")
        if runtime != "local" or min_vram <= 0:
            return True
        return self.gpu_free_mb() >= min_vram
