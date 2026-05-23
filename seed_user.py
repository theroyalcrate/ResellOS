"""
ResellOS - Seed Phase 1 User
Creates the single hardcoded user record for Phase 1 (DECISION 012).
Safe to run multiple times - will skip if user already exists.
"""

from db_client import get_client, PHASE_1_USER_ID


PHASE_1_USER = {
    "user_id": PHASE_1_USER_ID,
    "email": "josh@resellos.local",
    "state": "WA",
    "costing_method": "fifo",
    "tax_treatment": "conservative",
    "subscription_tier": "full",
    "account_status": "active",
}


def seed_user():
    client = get_client()

    existing = client.table("users").select("user_id").eq("user_id", PHASE_1_USER_ID).execute()

    if existing.data:
        print(f"User already exists: {PHASE_1_USER_ID}")
        print("Nothing to do.")
        return

    result = client.table("users").insert(PHASE_1_USER).execute()

    if result.data:
        print(f"User created successfully:")
        print(f"  user_id: {result.data[0]['user_id']}")
        print(f"  email:   {result.data[0]['email']}")
        print(f"  state:   {result.data[0]['state']}")
        print(f"  tier:    {result.data[0]['subscription_tier']}")
    else:
        print("ERROR: Insert returned no data.")


if __name__ == "__main__":
    seed_user()