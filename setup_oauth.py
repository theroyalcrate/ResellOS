"""
ResellOS OAuth setup — generates two separate token files.

  credentials/token_business.json   gmail.modify + drive
                                     Authorize as your BUSINESS Gmail account
                                     (the one that receives LEGO invoices via forwarding).

  credentials/token_personal.json   gmail.modify + gmail.settings.basic
                                     Authorize as your PERSONAL Gmail account
                                     (the one where old LEGO invoices lived before forwarding).

Usage:
  python setup_oauth.py              # set up BOTH accounts (two browser windows)
  python setup_oauth.py --business   # business account only
  python setup_oauth.py --personal   # personal account only

If a valid token already exists it is refreshed silently (no browser).
The first time you run this, a browser window opens for each account — the
console will tell you which account to sign in with at each prompt.

Scope note: gmail.settings.basic is required for the personal account so the
safety-net filter (Agent 01B Mode 5) can call settings.filters.create. If the
authorization fails or those scopes are missing, go to:
  Google Cloud Console → APIs & Services → OAuth consent screen → Data Access
and add: gmail.modify, gmail.settings.basic, drive.file
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

_CREDS_DIR   = os.path.join(os.path.dirname(__file__), "credentials")
_CREDS_FILE  = os.path.join(_CREDS_DIR, "credentials.json")
_BIZ_TOKEN   = os.path.join(_CREDS_DIR, "token_business.json")
_PERS_TOKEN  = os.path.join(_CREDS_DIR, "token_personal.json")
_LEGACY_TOKEN = os.path.join(_CREDS_DIR, "token.json")  # pre-S10 name

BUSINESS_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

PERSONAL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


def _migrate_legacy_token() -> None:
    """Rename token.json → token_business.json when upgrading from pre-S10 setup."""
    if os.path.exists(_LEGACY_TOKEN) and not os.path.exists(_BIZ_TOKEN):
        os.rename(_LEGACY_TOKEN, _BIZ_TOKEN)
        print(f"  Migrated token.json → token_business.json")


def _setup_account(token_path: str, scopes: list, label: str) -> None:
    """Run OAuth flow for one account, saving the result to token_path."""
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if creds and creds.valid:
        print(f"  {label} token is valid — no re-authorization needed.")
        return

    if creds and creds.expired and creds.refresh_token:
        print(f"  Refreshing {label} token...")
        creds.refresh(Request())
    else:
        print(f"\n  A browser window will open.")
        print(f"  Sign in with your {label} Gmail account.")
        print("  (If the browser doesn't open, copy the URL from the terminal.)")
        input("  Press Enter to open the browser now...")
        flow = InstalledAppFlow.from_client_secrets_file(_CREDS_FILE, scopes)
        creds = flow.run_local_server(port=0)

    with open(token_path, "w") as f:
        f.write(creds.to_json())
    print(f"  Saved: {token_path}")


def main() -> None:
    if not os.path.exists(_CREDS_FILE):
        print(f"ERROR: credentials.json not found at {_CREDS_FILE}")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        sys.exit(1)

    # Migrate legacy token.json before determining what needs setup
    _migrate_legacy_token()

    args = set(sys.argv[1:])
    do_business = "--business" in args or not args
    do_personal  = "--personal"  in args or not args

    if do_business:
        print("=" * 60)
        print("  BUSINESS GMAIL + DRIVE")
        print("  Sign in as: your BUSINESS Gmail account")
        print("  (the one receiving LEGO invoices via Gmail forwarding)")
        print("=" * 60)
        _setup_account(_BIZ_TOKEN, BUSINESS_SCOPES, "BUSINESS")

    if do_personal:
        print()
        print("=" * 60)
        print("  PERSONAL GMAIL")
        print("  Sign in as: your PERSONAL Gmail account")
        print("  (the one where historical LEGO invoices live)")
        print("=" * 60)
        _setup_account(_PERS_TOKEN, PERSONAL_SCOPES, "PERSONAL")

    print("\nSetup complete!")
    if do_business:
        print(f"  Business token : {_BIZ_TOKEN}")
    if do_personal:
        print(f"  Personal token : {_PERS_TOKEN}")
    print("\nYou can now run: python agents/agent_01b_invoice_filing.py")


if __name__ == "__main__":
    main()
