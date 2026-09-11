"""
SQLite to Cloud Firebase Migration Script
Migrates all existing data from local SQLite databases (moderation_auth.db and moderation_data.db)
into Google Cloud Firestore and Firebase Authentication.
"""

import sys
import os
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration")

# Add backend directory to sys.path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.database.firebase_db import FirebaseDatabaseManager
from src.database.auth_db import AuthDatabase
from src.database.moderation_db import ModerationDatabase

try:
    from firebase_admin import auth as firebase_auth
except ImportError:
    firebase_auth = None


def get_sqlite_rows(db_path: Path, query: str):
    """Utility to query SQLite table and return list of dictionaries."""
    if not db_path.exists():
        logger.warning(f"Database file does not exist at {db_path}")
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def migrate_all_to_firebase():
    logger.info("🚀 Starting SQLite to Cloud Firebase Migration...")
    
    db_mgr = FirebaseDatabaseManager(project_id="finalyearproject-ae788")
    if not db_mgr.db:
        logger.error("❌ Firestore client not available. Aborting migration.")
        return

    firestore_db = db_mgr.db
    auth_db_path = backend_dir / "databases" / "moderation_auth.db"
    data_db_path = backend_dir / "databases" / "moderation_data.db"

    # Verify live authenticated access to Cloud Firestore
    try:
        test_ref = firestore_db.collection("_health_check").document("auth_test")
        test_ref.set({"timestamp": datetime.now().isoformat(), "status": "ok"})
        logger.info("✅ Live Cloud Firestore write test passed!")
    except Exception as auth_err:
        err_msg = str(auth_err)
        logger.error("\n❌ FIREBASE FIRESTORE INITIALIZATION REQUIRED!")
        logger.error(f"   Error: {err_msg}")
        
        if "does not exist" in err_msg.lower() or "notfound" in err_msg.lower() or "404" in err_msg:
            logger.error("\n👉 REASON: Google Cloud has not provisioned the default Firestore database for project 'finalyearproject-ae788' yet.")
            logger.error("👉 TO FIX THIS IN 10 SECONDS:")
            logger.error("   1. In your Firebase Console (where you are right now), click '+ Start collection'.")
            logger.error("   2. Collection ID: type 'users'")
            logger.error("   3. Document ID: type 'test'")
            logger.error("   4. Field: 'test', Value: 'test'")
            logger.error("   5. Click 'Save'.")
            logger.error("   6. Re-run this migration script: python scripts/migrate_sqlite_to_firebase.py")
        else:
            logger.error("👉 Please verify your ServiceKey.JSON file and Firebase Console settings.")
        return

    # =========================================================================
    # 1. Migrate Auth Users (moderation_auth.db -> users)
    # =========================================================================
    users_rows = get_sqlite_rows(auth_db_path, "SELECT * FROM users")
    logger.info(f"📦 Migrating {len(users_rows)} users from moderation_auth.db...")
    for user in users_rows:
        username = user["username"]
        user_id = str(user["user_id"])
        
        # Write to Firestore 'users' collection
        doc_ref = firestore_db.collection("users").document(username)
        doc_ref.set({
            "user_id": user_id,
            "username": username,
            "full_name": user["full_name"],
            "role": user["role"],
            "email": user["email"],
            "phone": user["phone"],
            "is_active": user["is_active"],
            "created_at": user["created_at"],
            "last_login": user["last_login"]
        }, merge=True)

        # Write to Firestore 'user_profiles' collection
        db_mgr.create_or_update_user({
            "user_id": user_id,
            "username": username,
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user["role"],
            "account_age_days": 120,
            "reputation_score": 0.95 if user["role"] != "user" else 0.85,
            "reputation_tier": "trusted" if user["role"] != "user" else "regular",
            "verified": True
        })

        # Try registering in Firebase Auth if email exists
        if firebase_auth and user.get("email"):
            try:
                try:
                    firebase_auth.get_user_by_email(user["email"])
                except firebase_auth.UserNotFoundError:
                    firebase_auth.create_user(
                        email=user["email"],
                        password="Password123!",
                        display_name=user["full_name"],
                        uid=f"usr-{user_id}"
                    )
            except Exception as e:
                logger.debug(f"Firebase Auth sync notice for {username}: {e}")

        logger.info(f"  ✅ User migrated: {username} ({user['role']})")

    # =========================================================================
    # 2. Migrate Moderator Stats (moderation_auth.db -> moderator_stats)
    # =========================================================================
    stats_rows = get_sqlite_rows(auth_db_path, "SELECT * FROM moderator_stats")
    logger.info(f"📦 Migrating {len(stats_rows)} moderator stats records...")
    for s in stats_rows:
        firestore_db.collection("moderator_stats").document(str(s["user_id"])).set(s, merge=True)

    # =========================================================================
    # 3. Migrate User Sessions (moderation_auth.db -> user_sessions)
    # =========================================================================
    sessions_rows = get_sqlite_rows(auth_db_path, "SELECT * FROM user_sessions")
    logger.info(f"📦 Migrating {len(sessions_rows)} user sessions...")
    for session in sessions_rows:
        firestore_db.collection("user_sessions").document(session["session_id"]).set(session, merge=True)

    # =========================================================================
    # 4. Migrate Audit Logs (moderation_auth.db -> audit_logs)
    # =========================================================================
    audit_rows = get_sqlite_rows(auth_db_path, "SELECT * FROM audit_log")
    logger.info(f"📦 Migrating {len(audit_rows)} audit logs...")
    for log in audit_rows:
        log_id = str(log["log_id"])
        firestore_db.collection("audit_logs").document(log_id).set(log, merge=True)

    # =========================================================================
    # 5. Migrate Content Submissions (moderation_data.db -> content_submissions)
    # =========================================================================
    content_rows = get_sqlite_rows(data_db_path, "SELECT * FROM content_submissions")
    logger.info(f"📦 Migrating {len(content_rows)} content submissions...")
    for content in content_rows:
        cid = content["content_id"]
        firestore_db.collection("content_submissions").document(cid).set(content, merge=True)
        logger.info(f"  ✅ Content submission migrated: {cid}")

    # =========================================================================
    # 6. Migrate User Profiles (moderation_data.db -> user_profiles)
    # =========================================================================
    profiles_rows = get_sqlite_rows(data_db_path, "SELECT * FROM user_profiles")
    logger.info(f"📦 Migrating {len(profiles_rows)} user profiles...")
    for profile in profiles_rows:
        uid = str(profile["user_id"])
        firestore_db.collection("user_profiles").document(uid).set(profile, merge=True)

    # =========================================================================
    # 7. Migrate Agent Executions (moderation_data.db -> agent_executions)
    # =========================================================================
    exec_rows = get_sqlite_rows(data_db_path, "SELECT * FROM agent_executions")
    logger.info(f"📦 Migrating {len(exec_rows)} agent executions...")
    for exec_rec in exec_rows:
        eid = str(exec_rec["id"])
        firestore_db.collection("agent_executions").document(eid).set(exec_rec, merge=True)

    # =========================================================================
    # 8. Migrate Policy Violations (moderation_data.db -> policy_violations)
    # =========================================================================
    violation_rows = get_sqlite_rows(data_db_path, "SELECT * FROM policy_violations")
    logger.info(f"📦 Migrating {len(violation_rows)} policy violations...")
    for v in violation_rows:
        vid = str(v["id"])
        firestore_db.collection("policy_violations").document(vid).set(v, merge=True)

    # =========================================================================
    # 9. Migrate Manual Reviews (moderation_data.db -> manual_reviews)
    # =========================================================================
    review_rows = get_sqlite_rows(data_db_path, "SELECT * FROM manual_reviews")
    logger.info(f"📦 Migrating {len(review_rows)} manual reviews...")
    for r in review_rows:
        rid = str(r["id"])
        firestore_db.collection("manual_reviews").document(rid).set(r, merge=True)

    # =========================================================================
    # 10. Migrate Stories & Story Comments (moderation_data.db -> stories / story_comments)
    # =========================================================================
    story_rows = get_sqlite_rows(data_db_path, "SELECT * FROM stories")
    logger.info(f"📦 Migrating {len(story_rows)} stories...")
    for story in story_rows:
        sid = story["story_id"]
        firestore_db.collection("stories").document(sid).set(story, merge=True)
        logger.info(f"  ✅ Story migrated: {sid}")

    comment_rows = get_sqlite_rows(data_db_path, "SELECT * FROM story_comments")
    logger.info(f"📦 Migrating {len(comment_rows)} story comments...")
    for comment in comment_rows:
        cmid = comment["comment_id"]
        firestore_db.collection("story_comments").document(cmid).set(comment, merge=True)

    logger.info("🎉 SQLite to Cloud Firebase Migration Completed Successfully!")


if __name__ == "__main__":
    migrate_all_to_firebase()
