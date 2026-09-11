"""
Firebase Demo Users Seeding Script
Initializes demo accounts in Firebase Authentication and Firestore document store,
synced with local SQLite backup data.
"""

import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.database.firebase_db import FirebaseDatabaseManager
from src.database.auth_db import AuthDatabase

DEMO_USERS = [
    {
        "username": "admin",
        "email": "admin@contentmod.com",
        "password": "admin123",
        "full_name": "Sanjay Kapoor - System Administrator",
        "role": "admin",
        "user_id": "usr-admin-001"
    },
    {
        "username": "moderator1",
        "email": "mod1@contentmod.com",
        "password": "mod123",
        "full_name": "Rohan Sharma - Content Moderator",
        "role": "moderator",
        "user_id": "usr-mod-001"
    },
    {
        "username": "senior_mod",
        "email": "seniormod@contentmod.com",
        "password": "mod123",
        "full_name": "Ananya Roy - Senior Moderator",
        "role": "senior_moderator",
        "user_id": "usr-mod-002"
    },
    {
        "username": "analyst",
        "email": "analyst@contentmod.com",
        "password": "mod123",
        "full_name": "Kavita Verma - Content Analyst",
        "role": "content_analyst",
        "user_id": "usr-analyst-001"
    },
    {
        "username": "policy_expert",
        "email": "policy@contentmod.com",
        "password": "mod123",
        "full_name": "Vikram Seth - Policy Specialist",
        "role": "policy_specialist",
        "user_id": "usr-policy-001"
    },
    {
        "username": "priya",
        "email": "priya@example.com",
        "password": "user123",
        "full_name": "Priya Sharma",
        "role": "user",
        "user_id": "usr-user-001"
    },
    {
        "username": "raj",
        "email": "raj@example.com",
        "password": "user123",
        "full_name": "Raj Kumar",
        "role": "user",
        "user_id": "usr-user-002"
    },
    {
        "username": "amit",
        "email": "amit@example.com",
        "password": "user123",
        "full_name": "Amit Patel",
        "role": "user",
        "user_id": "usr-user-003"
    }
]


def seed_firebase():
    print("🚀 Initializing Firebase & SQLite Data Seeding...")
    db_mgr = FirebaseDatabaseManager(project_id="finalyearproject-ae788")
    auth_db = AuthDatabase("databases/moderation_auth.db")

    for u in DEMO_USERS:
        # Seed SQLite auth
        auth_db.create_user(
            username=u["username"],
            password=u["password"],
            full_name=u["full_name"],
            role=u["role"],
            email=u["email"]
        )

        # Seed Firestore user profile
        db_mgr.create_or_update_user({
            "user_id": u["user_id"],
            "username": u["username"],
            "email": u["email"],
            "full_name": u["full_name"],
            "role": u["role"],
            "account_age_days": 120,
            "total_posts": 5,
            "total_violations": 0,
            "previous_warnings": 0,
            "previous_suspensions": 0,
            "reputation_score": 0.95 if u["role"] != "user" else 0.85,
            "reputation_tier": "trusted" if u["role"] != "user" else "regular",
            "verified": True,
            "follower_count": 42
        })
        print(f"  ✅ Account initialized: {u['username']} ({u['role']})")

    print("\n🎉 Seeding Completed Successfully! All demo accounts are active.")


if __name__ == "__main__":
    seed_firebase()
