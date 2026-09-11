"""
Firebase Firestore Database Manager for Content Moderation Platform
Handles primary reads/writes to Google Cloud Firestore with automatic SQLite backup synchronization.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from pathlib import Path

# Import SQLite database classes for local backup sync
from .moderation_db import ModerationDatabase
from .auth_db import AuthDatabase

logger = logging.getLogger("firebase_db")

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, auth as firebase_auth
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("firebase_admin package not installed. Falling back to local SQLite.")


class FirebaseDatabaseManager:
    """
    Dual-Database Manager:
    Uses Cloud Firestore for primary cloud data persistence and syncs to local SQLite as backup.
    """
    def __init__(self, project_id: str = "finalyearproject-ae788", service_account_path: Optional[str] = None):
        self.project_id = project_id
        self.db = None
        self.sqlite_mod = ModerationDatabase()
        self.sqlite_auth = AuthDatabase()

        if FIREBASE_AVAILABLE:
            self._init_firebase(service_account_path)

    def _init_firebase(self, service_account_path: Optional[str] = None):
        """Initialize Firebase Admin SDK"""
        try:
            if not firebase_admin._apps:
                # Check for explicit service account file, ENV variable, or local JSON in backend dir
                key_path = service_account_path or os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")
                
                if not key_path:
                    backend_dir = Path(__file__).parent.parent.parent
                    possible_filenames = [
                        "ServiceKey.JSON", "serviceKey.json", "serviceAccountKey.json", 
                        "firebase-key.json", "service_account.json"
                    ]
                    for fname in possible_filenames:
                        candidate = backend_dir / fname
                        if candidate.exists():
                            key_path = str(candidate)
                            break
                    
                    if not key_path:
                        for p in backend_dir.glob("*.json"):
                            if "key" in p.name.lower() or "service" in p.name.lower() or "firebase" in p.name.lower():
                                key_path = str(p)
                                break

                if key_path and Path(key_path).exists():
                    cred = credentials.Certificate(key_path)
                    firebase_admin.initialize_app(cred, {"projectId": self.project_id})
                    logger.info(f"✅ Firebase Admin initialized with certificate from {key_path}")
                else:
                    logger.warning("⚠️ No serviceAccountKey.json found in backend directory. Firebase Admin writes require service account credentials.")
                    try:
                        cred = credentials.ApplicationDefault()
                        firebase_admin.initialize_app(cred, {"projectId": self.project_id})
                    except Exception:
                        firebase_admin.initialize_app(options={"projectId": self.project_id})
                    logger.info(f"✅ Firebase initialized in unauthenticated/default mode for project {self.project_id}")

            self.db = firestore.client()
            logger.info("✅ Firestore client initialized.")
        except Exception as e:
            logger.warning(f"⚠️ Firebase Admin initialization notice: {e}. SQLite backup will serve requests.")

    # ═══════════════════════════════════════════════════════════════════════════════
    # Content Submission Methods
    # ═══════════════════════════════════════════════════════════════════════════════

    def create_content_submission(self, content_data: Dict[str, Any]) -> str:
        """Create a content submission in Firestore & sync to SQLite backup."""
        content_id = content_data.get("content_id")
        
        # 1. SQLite Backup
        try:
            self.sqlite_mod.create_content_submission(content_data)
        except Exception as e:
            logger.error(f"SQLite backup write error (content_submission): {e}")

        # 2. Firestore Primary
        if self.db:
            try:
                doc_ref = self.db.collection("content_submissions").document(content_id)
                doc_ref.set({
                    "content_id": content_id,
                    "submission_id": content_data.get("submission_id"),
                    "user_id": content_data.get("user_id"),
                    "username": content_data.get("username"),
                    "content_text": content_data.get("content_text"),
                    "content_type": content_data.get("content_type"),
                    "platform": content_data.get("platform", "generic"),
                    "language": content_data.get("language", "en"),
                    "submission_timestamp": content_data.get("submission_timestamp"),
                    "current_status": content_data.get("status", "submitted"),
                    "toxicity_score": content_data.get("toxicity_score", 0.0),
                    "requires_human_review": bool(content_data.get("requires_human_review", False)),
                    "updated_at": firestore.SERVER_TIMESTAMP if hasattr(firestore, "SERVER_TIMESTAMP") else datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Firestore write error (content_submission): {e}")

        return content_id

    def update_content_status(
        self,
        content_id: str,
        status: str,
        moderation_action: Optional[str] = None,
        action_reason: Optional[str] = None,
        toxicity_score: Optional[float] = None
    ):
        """Update content status in Firestore & SQLite."""
        # 1. SQLite Backup
        try:
            self.sqlite_mod.update_content_status(
                content_id=content_id,
                status=status,
                moderation_action=moderation_action,
                action_reason=action_reason,
                toxicity_score=toxicity_score
            )
        except Exception as e:
            logger.error(f"SQLite status update error: {e}")

        # 2. Firestore Primary
        if self.db:
            try:
                doc_ref = self.db.collection("content_submissions").document(content_id)
                update_payload = {"current_status": status, "processed_at": datetime.now().isoformat()}
                if moderation_action: update_payload["moderation_action"] = moderation_action
                if action_reason: update_payload["action_reason"] = action_reason
                if toxicity_score is not None: update_payload["toxicity_score"] = toxicity_score
                
                doc_ref.set(update_payload, merge=True)
            except Exception as e:
                logger.error(f"Firestore status update error: {e}")

    def get_content_by_id(self, content_id: str) -> Optional[Dict[str, Any]]:
        """Get content submission by ID from Firestore (fallback to SQLite)."""
        if self.db:
            try:
                doc = self.db.collection("content_submissions").document(content_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["current_status"] = data.get("current_status") or data.get("status")
                    return data
            except Exception as e:
                logger.error(f"Firestore read error (content_id): {e}")

        return self.sqlite_mod.get_content_by_id(content_id)

    def get_all_content(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all content submissions."""
        if self.db:
            try:
                docs = self.db.collection("content_submissions").limit(limit).stream()
                results = []
                for doc in docs:
                    d = doc.to_dict()
                    d["current_status"] = d.get("current_status") or d.get("status")
                    results.append(d)
                if results:
                    return results
            except Exception as e:
                logger.error(f"Firestore read error (get_all_content): {e}")

        return self.sqlite_mod.get_all_content(limit=limit)

    def get_content_by_status(self, status: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get content submissions by status."""
        if self.db:
            try:
                docs = self.db.collection("content_submissions").where("current_status", "==", status).limit(limit).stream()
                results = [doc.to_dict() for doc in docs]
                if results:
                    return results
            except Exception as e:
                logger.error(f"Firestore query error (status): {e}")

        return self.sqlite_mod.get_content_by_status(status=status, limit=limit)

    # ═══════════════════════════════════════════════════════════════════════════════
    # Agent Execution & Policy Violation Methods
    # ═══════════════════════════════════════════════════════════════════════════════

    def save_agent_decision(self, content_id: str, agent_decision: Any):
        """Save agent execution decision in Firestore & SQLite."""
        self.sqlite_mod.save_agent_decision(content_id, agent_decision)

        if self.db:
            try:
                ref = self.db.collection("agent_executions").document()
                ref.set({
                    "content_id": content_id,
                    "agent_name": getattr(agent_decision, "agent_name", "unknown"),
                    "decision": getattr(getattr(agent_decision, "decision", "unknown"), "value", str(getattr(agent_decision, "decision", "unknown"))),
                    "confidence": getattr(agent_decision, "confidence", 0.0),
                    "reasoning": getattr(agent_decision, "reasoning", ""),
                    "flags": getattr(agent_decision, "flags", []),
                    "recommendations": getattr(agent_decision, "recommendations", []),
                    "extracted_data": getattr(agent_decision, "extracted_data", {}),
                    "requires_human_review": getattr(agent_decision, "requires_human_review", False),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Firestore write error (agent_decision): {e}")

    def get_agent_executions(self, content_id: str) -> List[Dict[str, Any]]:
        """Get agent executions for content."""
        if self.db:
            try:
                docs = self.db.collection("agent_executions").where("content_id", "==", content_id).stream()
                res = [d.to_dict() for d in docs]
                if res: return res
            except Exception as e:
                logger.error(f"Firestore read error (agent_executions): {e}")

        return self.sqlite_mod.get_agent_executions(content_id)

    def get_agent_decisions(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get all agent decisions for analytics from SQLite backup."""
        return self.sqlite_mod.get_agent_decisions(limit=limit)

    def get_all_appeals(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get all appeals for analytics from SQLite backup."""
        return self.sqlite_mod.get_all_appeals(limit=limit)

    def save_policy_violations(self, content_id: str, violations: List[str], severity: str, agent_name: str):
        """Save policy violations."""
        self.sqlite_mod.save_policy_violations(content_id, violations, severity, agent_name)

        if self.db:
            try:
                for v in violations:
                    self.db.collection("policy_violations").document().set({
                        "content_id": content_id,
                        "violation_type": v,
                        "severity": severity,
                        "detected_by_agent": agent_name,
                        "timestamp": datetime.now().isoformat()
                    })
            except Exception as e:
                logger.error(f"Firestore write error (policy_violations): {e}")

    def get_policy_violations(self, content_id: str) -> List[Dict[str, Any]]:
        """Get policy violations for content."""
        if self.db:
            try:
                docs = self.db.collection("policy_violations").where("content_id", "==", content_id).stream()
                res = [d.to_dict() for d in docs]
                if res: return res
            except Exception as e:
                logger.error(f"Firestore read error (policy_violations): {e}")

        return self.sqlite_mod.get_policy_violations(content_id)

    # ═══════════════════════════════════════════════════════════════════════════════
    # Stories & Story Comments Methods
    # ═══════════════════════════════════════════════════════════════════════════════

    def create_story(self, story_data: Dict[str, Any]) -> str:
        """Create a new story in Firestore & SQLite."""
        story_id = story_data.get("story_id")
        self.sqlite_mod.create_story(story_data)

        if self.db:
            try:
                self.db.collection("stories").document(story_id).set({
                    "story_id": story_id,
                    "user_id": story_data.get("user_id"),
                    "username": story_data.get("username"),
                    "title": story_data.get("title"),
                    "content_text": story_data.get("content_text"),
                    "content_id": story_data.get("content_id"),
                    "moderation_status": story_data.get("moderation_status", "pending"),
                    "is_approved": 1 if story_data.get("is_approved") else 0,
                    "is_visible": 1 if story_data.get("is_visible") else 0,
                    "toxicity_score": story_data.get("toxicity_score", 0.0),
                    "created_at": story_data.get("created_at", datetime.now().isoformat())
                })
            except Exception as e:
                logger.error(f"Firestore write error (story): {e}")

        return story_id

    def get_story_by_content_id(self, content_id: str) -> Optional[Dict[str, Any]]:
        """Get story by content_id."""
        if self.db:
            try:
                docs = self.db.collection("stories").where("content_id", "==", content_id).limit(1).stream()
                for doc in docs:
                    return doc.to_dict()
            except Exception as e:
                logger.error(f"Firestore read error (story content_id): {e}")

        return self.sqlite_mod.get_story_by_content_id(content_id)

    def get_all_stories(self, limit: int = 100, visible_only: bool = False) -> List[Dict[str, Any]]:
        """Get all stories from Firestore (fallback SQLite)."""
        if self.db:
            try:
                ref = self.db.collection("stories")
                if visible_only:
                    ref = ref.where("is_visible", "==", 1)
                docs = ref.limit(limit).stream()
                results = [d.to_dict() for d in docs]
                if results: return results
            except Exception as e:
                logger.error(f"Firestore read error (get_all_stories): {e}")

        return self.sqlite_mod.get_all_stories(limit=limit, visible_only=visible_only)

    def update_story_moderation(
        self,
        story_id: str,
        moderation_status: str,
        is_approved: bool,
        is_visible: bool,
        toxicity_score: Optional[float] = None
    ):
        """Update story moderation status in Firestore & SQLite."""
        self.sqlite_mod.update_story_moderation(
            story_id=story_id,
            moderation_status=moderation_status,
            is_approved=is_approved,
            is_visible=is_visible,
            toxicity_score=toxicity_score
        )

        if self.db:
            try:
                payload = {
                    "moderation_status": moderation_status,
                    "is_approved": 1 if is_approved else 0,
                    "is_visible": 1 if is_visible else 0,
                    "updated_at": datetime.now().isoformat()
                }
                if toxicity_score is not None: payload["toxicity_score"] = toxicity_score
                self.db.collection("stories").document(story_id).set(payload, merge=True)
            except Exception as e:
                logger.error(f"Firestore update error (story): {e}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # User Profile & Authentication Synchronization
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile from Firestore (fallback SQLite)."""
        if self.db:
            try:
                doc = self.db.collection("user_profiles").document(str(user_id)).get()
                if doc.exists: return doc.to_dict()
            except Exception as e:
                logger.error(f"Firestore read error (user_profile): {e}")

        return self.sqlite_mod.get_user_profile(user_id)

    def create_or_update_user(self, user_data: Dict[str, Any]):
        """Sync user profile to Firestore & SQLite."""
        user_id = str(user_data.get("user_id"))
        self.sqlite_mod.create_or_update_user(user_data)

        if self.db:
            try:
                self.db.collection("user_profiles").document(user_id).set(user_data, merge=True)
            except Exception as e:
                logger.error(f"Firestore write error (user_profile): {e}")

    def sync_firebase_role_claim(self, email: Optional[str], role: str = "user") -> None:
        """Mirror the application role into Firebase Auth custom claims."""
        if not FIREBASE_AVAILABLE or not email:
            return

        try:
            user_record = firebase_auth.get_user_by_email(email)
            if not user_record:
                return

            firebase_auth.set_custom_user_claims(user_record.uid, {"role": role})
            logger.info(f"✅ Synced Firebase custom claim role='{role}' for email '{email}'")
        except Exception as e:
            logger.debug(f"Firebase custom claim sync skipped for '{email}': {e}")

    def create_or_update_auth_user(self, user_data: Dict[str, Any]):
        """
        Sync user authentication details & account metadata to Firestore 'users' collection 
        and Firebase Authentication.
        """
        username = user_data.get("username")
        user_id = str(user_data.get("user_id") or username)
        role = user_data.get("role", "user")
        
        doc_payload = {
            "user_id": user_id,
            "username": username,
            "full_name": user_data.get("full_name"),
            "role": role,
            "email": user_data.get("email"),
            "phone": user_data.get("phone"),
            "is_active": user_data.get("is_active", 1),
            "created_at": user_data.get("created_at") or datetime.now().isoformat(),
            "last_login": user_data.get("last_login")
        }

        # 1. Store user in Firestore 'users' collection
        if self.db:
            try:
                self.db.collection("users").document(username).set(doc_payload, merge=True)
                logger.info(f"✅ Synced user '{username}' to Firestore 'users' collection.")
            except Exception as e:
                logger.error(f"Firestore write error (users collection for {username}): {e}")

        # 2. Attempt to register user in Firebase Auth if available
        if FIREBASE_AVAILABLE and user_data.get("email"):
            try:
                email = user_data.get("email")
                display_name = user_data.get("full_name") or username
                password = user_data.get("password") or "DefaultPass123!"
                
                try:
                    # Check if user exists in Firebase Auth
                    firebase_user = firebase_auth.get_user_by_email(email)
                    firebase_auth.set_custom_user_claims(firebase_user.uid, {"role": role})
                    logger.info(f"✅ Updated Firebase custom claim role='{role}' for '{email}'")
                except firebase_auth.UserNotFoundError:
                    # Create user in Firebase Auth
                    firebase_user = firebase_auth.create_user(
                        email=email,
                        password=password,
                        display_name=display_name,
                        uid=user_id if len(user_id) <= 128 else None
                    )
                    firebase_auth.set_custom_user_claims(firebase_user.uid, {"role": role})
                    logger.info(f"✅ Created Firebase Auth account and synced role='{role}' for email '{email}'")
            except Exception as e:
                logger.debug(f"Firebase Auth creation notice for {username}: {e}")

        # 3. Create default user profile in Firestore 'user_profiles' collection as well
        self.create_or_update_user({
            "user_id": user_id,
            "username": username,
            "full_name": user_data.get("full_name"),
            "email": user_data.get("email"),
            "role": role,
            "account_age_days": user_data.get("account_age_days", 1),
            "total_posts": user_data.get("total_posts", 0),
            "total_violations": user_data.get("total_violations", 0),
            "previous_warnings": user_data.get("previous_warnings", 0),
            "previous_suspensions": user_data.get("previous_suspensions", 0),
            "reputation_score": user_data.get("reputation_score", 0.85 if role == "user" else 0.95),
            "reputation_tier": user_data.get("reputation_tier", "regular" if role == "user" else "trusted"),
            "verified": user_data.get("verified", True),
            "follower_count": user_data.get("follower_count", 0),
            "created_at": user_data.get("created_at") or datetime.now().isoformat()
        })

    def get_statistics(self) -> Dict[str, Any]:
        """Get platform statistics."""
        return self.sqlite_mod.get_statistics()

