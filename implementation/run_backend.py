"""Launch the OmniCast dashboard backend (real data API on :8767).

The dashboard (the standalone .html built in your external AI builder) fetches
its data from this API. Run this, then open / point the dashboard at
http://127.0.0.1:8767 — it shows REAL channels, pipeline status, niches, vault,
credits and render output instead of mock data.

    python -X utf8 run_backend.py            # port 8767 (what the dashboard expects)
    python -X utf8 run_backend.py --port 9000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    import uvicorn

    print(f"[backend] OmniCast API → http://{args.host}:{args.port}")
    print(f"[backend] OpenAPI contract: http://{args.host}:{args.port}/openapi.json")
    print(f"[backend] Interactive docs: http://{args.host}:{args.port}/docs")
    print("[backend] Point your dashboard at this URL. Ctrl+C to stop.")
    uvicorn.run("omnicast.api.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
