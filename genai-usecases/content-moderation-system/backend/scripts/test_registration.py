"""
Test registration and Firebase sync verification
"""

import sys
import logging
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.database.firebase_db import FirebaseDatabaseManager
from src.database.auth_db import AuthDatabase

def test_firebase_registration():
    db_mgr = FirebaseDatabaseManager(project_id="finalyearproject-ae788")
    auth_db = AuthDatabase("databases/moderation_auth.db")

    test_username = f"test_user_fb_sync"
    test_user_data = {
        "username": test_username,
        "password": "Password123!",
        "full_name": "Firebase Sync Test User",
        "role": "user",
        "email": "test_fb_sync@example.com",
        "phone": "+1234567890"
    }

    # 1. Register in SQLite Auth DB
    auth_db.create_user(
        username=test_user_data["username"],
        password=test_user_data["password"],
        full_name=test_user_data["full_name"],
        role=test_user_data["role"],
        email=test_user_data["email"],
        phone=test_user_data["phone"]
    )

    # 2. Sync to Firebase
    db_mgr.create_or_update_auth_user(test_user_data)

    # 3. Verify in Firestore
    if db_mgr.db:
        user_doc = db_mgr.db.collection("users").document(test_username).get()
        assert user_doc.exists, f"User {test_username} not found in Firestore 'users' collection!"
        print(f"✅ Verified Firestore user document: {user_doc.to_dict()}")

        profile_doc = db_mgr.db.collection("user_profiles").document(test_username).get()
        assert profile_doc.exists, f"User profile {test_username} not found in Firestore 'user_profiles' collection!"
        print(f"✅ Verified Firestore profile document: {profile_doc.to_dict()}")

        print("\n🎉 ALL TESTS PASSED! User registration successfully synced to Firebase.")

if __name__ == "__main__":
    test_firebase_registration()
