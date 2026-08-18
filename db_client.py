"""
ResellOS - Supabase Database Client
Single source of truth for database connections.
Every agent imports the client from here.

Phase 1: Uses secret key with hardcoded user UUID (DECISION 012).
Phase 2: Will switch to publishable key + Supabase Auth.
"""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client, Client


load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env file.")
    sys.exit(1)


def get_client() -> Client:
    """Return a Supabase client configured for backend operations."""
    client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    # Python 3.14 + Windows SSL interceptor: replace the postgrest HTTP session
    # with one that skips certificate verification. Safe for a local CLI tool.
    old = client.postgrest.session
    client.postgrest.session = httpx.Client(
        base_url=str(client.postgrest.base_url),
        headers=dict(old.headers),
        verify=False,
        follow_redirects=True,
        http2=True,
    )
    return client


# Phase 1: hardcoded single user UUID per DECISION 012.
# Re-pointed 2026-08-12 (migration 018) to Josh's real Supabase Auth user ID,
# created as the Chrome extension's auth prerequisite. All existing data (9
# orders, 216 gift cards, etc.) was migrated to this same ID that same session
# -- backend scripts still use the secret key (RLS bypass) and this constant,
# not a real login, but now they share one identity with the extension instead
# of two. Still "Phase 1" in the sense that there's no per-request auth context
# yet -- true Phase 2 (scripts authenticate as this real user) is unchanged/future.
PHASE_1_USER_ID = "9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4"


if __name__ == "__main__":
    client = get_client()
    result = client.table("users").select("user_id, email, state").execute()
    print(f"Connection successful. Users table has {len(result.data)} row(s).")
    if result.data:
        for row in result.data:
            print(f"  {row['email']} ({row['state']})")