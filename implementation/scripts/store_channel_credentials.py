"""Store a YouTube channel's account credentials ENCRYPTED in the vault.

Uses the existing CredentialVault (Fernet via OMNICAST_CREDENTIAL_FERNET_KEY).
Never writes plaintext files; never prints the secret back.

One-time key setup (do once, keep the key in your password manager / .env):
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  -> set OMNICAST_CREDENTIAL_FERNET_KEY=<that key> in implementation/.env

Usage (prompts for the password, never passes it on the command line):
  python scripts/store_channel_credentials.py --channel money_blueprint_us \
      --email you@gmail.com --youtube-channel-id UCxxxx --channel-name "The Money Blueprint"

Read back later:
  python scripts/store_channel_credentials.py --channel money_blueprint_us --show
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    from omnicast.config.settings import get_settings
    from omnicast.services.credential_vault import CredentialVault

    ap = argparse.ArgumentParser(description="Encrypt + store channel account credentials in vault.db")
    ap.add_argument("--channel", required=True, help="channel id (matches channels/<id>.json)")
    ap.add_argument("--email", default="", help="Google account email")
    ap.add_argument("--youtube-channel-id", default="", help="UC... channel id")
    ap.add_argument("--channel-name", default="", help="public channel name")
    ap.add_argument("--show", action="store_true", help="decrypt + print the stored record")
    args = ap.parse_args()

    s = get_settings()
    key = s.omnicast_credential_fernet_key or None
    if not key:
        print("[ERROR] OMNICAST_CREDENTIAL_FERNET_KEY not set — refusing to store "
              "account passwords unencrypted.\nGenerate one:\n  python -c "
              '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
              "\nthen add it to implementation/.env and re-run.")
        return 1

    vault = CredentialVault(db_path=ROOT / "output" / "vault.db", encryption_key=key)
    cred_id = None
    for c in vault.list_safe(provider="youtube_account"):
        if c["account_id"] == args.channel:
            cred_id = c["credential_id"]

    if args.show:
        if not cred_id:
            print(f"[ERROR] No stored credentials for '{args.channel}'.")
            return 1
        print(vault.get_secret(cred_id))
        return 0

    if not args.email:
        print("[ERROR] --email required when storing.")
        return 1
    password = getpass.getpass(f"Google account password for {args.email}: ")
    payload = json.dumps({
        "email": args.email,
        "password": password,
        "youtube_channel_id": args.youtube_channel_id,
        "channel_name": args.channel_name,
        "channel_id": args.channel,
    }, ensure_ascii=False)
    rec = vault.store_secret(
        provider="youtube_account", account_id=args.channel,
        secret=payload, label=f"YouTube account for {args.channel}")
    print(f"[OK] Stored encrypted credentials as {rec.credential_id} "
          f"(vault.db, Fernet). Retrieve with --show.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
