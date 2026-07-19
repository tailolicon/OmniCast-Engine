"""One-time YouTube upload consent per channel.

Opens the Google consent screen in your browser, then stores the resulting
refresh token under the channel's id so the auto-uploader can publish without
prompting again.

Prereq (one-time, manual — the API cannot do this for you):
  1. Create the YouTube channel on youtube.com (channels are tied to a Google
     account; there is no API to create one).
  2. In Google Cloud Console: enable "YouTube Data API v3", create an OAuth
     client of type "Desktop app", download client_secret.json.
  3. Point settings at it: YOUTUBE_OAUTH_CLIENT_SECRET=/path/client_secret.json
     (or pass --client-secret). No OMNICAST_ prefix — config/settings.py has no env_prefix.

Usage:
  python scripts/youtube_authorize.py --channel <channel_id> [--client-secret path]

<channel_id> must match the channels/<channel_id>.json the pipeline renders for.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    from omnicast.config.settings import get_settings
    from omnicast.upload.oauth import ANALYTICS_SCOPES, OAuth2Manager, SCOPES

    ap = argparse.ArgumentParser(description="Authorize YouTube upload for a channel")
    ap.add_argument("--channel", required=True, help="channel id (matches channels/<id>.json)")
    ap.add_argument("--client-secret", default=None, help="path to client_secret.json")
    ap.add_argument("--port", type=int, default=0, help="local redirect port (0=auto)")
    ap.add_argument("--analytics", action="store_true",
                    help="also request YouTube Analytics read scopes (watch time, "
                         "retention, revenue) — needed by analytics/collector.py. "
                         "Enable 'YouTube Analytics API' in Cloud Console first.")
    args = ap.parse_args()

    s = get_settings()
    client_secret = args.client_secret or s.youtube_oauth_client_secret
    if not client_secret or not Path(client_secret).exists():
        print(f"[ERROR] client_secret.json not found: {client_secret!r}\n"
              "Set YOUTUBE_OAUTH_CLIENT_SECRET or pass --client-secret.")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = SCOPES + (ANALYTICS_SCOPES if args.analytics else [])
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, scopes)
    print(f"[1/2] Opening browser for Google consent ({len(scopes)} scope(s): "
          f"upload{' + analytics' if args.analytics else ''})...")
    creds = flow.run_local_server(port=args.port, prompt="consent")

    mgr = OAuth2Manager(token_dir=s.youtube_token_dir, encryption_key=s.youtube_token_key or None)
    import asyncio
    asyncio.run(mgr.store_token(args.channel, json.loads(creds.to_json())))
    print(f"[2/2] Token stored for channel '{args.channel}' at "
          f"{Path(s.youtube_token_dir) / (args.channel + '.json')}")
    print("Done. The auto-uploader can now publish to this channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
