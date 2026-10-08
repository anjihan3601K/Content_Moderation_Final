"""
Storage for the recommendation feature: SQLite and Firestore behind one interface.

The host project has no storage abstraction; ``FirebaseDatabaseManager`` writes SQLite
first and Firestore when it is available, and reads Firestore with a SQLite fallback.
This module follows the same pattern for the feature's own data:

- ``DocumentStore`` is the small interface both backends implement.
- ``SQLiteDocumentStore`` keeps each collection in its own table of a separate database
  file (``recommendation_data.db``), so no existing table is altered.
- ``FirestoreDocumentStore`` wraps a Firestore client (or a compatible fake).
- ``DualDocumentStore`` composes the two the way the host project does.
- ``RecommendationRepository`` is the typed layer the services use.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from recommendation.src.models import (
    AgeTier,
    PrecedentCase,
    RecommendationItemModel,
    ViewerProfileModel,
    _now_iso,
)

logger = logging.getLogger(__name__)

COLLECTIONS = ("rec_items", "rec_profiles", "rec_events", "rec_bandit_arms", "rec_precedents")
FEED_HISTORY_LIMIT = 50


class DocumentStore(Protocol):
    """Minimal document storage: named collections of JSON documents keyed by id."""

    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None: ...

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]: ...

    def list(self, collection: str, limit: int = 1000) -> List[Dict[str, Any]]: ...


def _check_collection(collection: str) -> None:
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown collection: {collection}")


class SQLiteDocumentStore:
    """SQLite backend. One table per collection, created with CREATE TABLE IF NOT EXISTS."""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self) -> None:
        conn = self.get_connection()
        try:
            for collection in COLLECTIONS:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {collection} ("
                    "doc_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
            conn.commit()
        finally:
            conn.close()

    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        _check_collection(collection)
        conn = self.get_connection()
        try:
            conn.execute(
                f"INSERT INTO {collection} (doc_id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(doc_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (str(doc_id), json.dumps(data), _now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        _check_collection(collection)
        conn = self.get_connection()
        try:
            row = conn.execute(
                f"SELECT data FROM {collection} WHERE doc_id = ?", (str(doc_id),)
            ).fetchone()
            return json.loads(row["data"]) if row else None
        finally:
            conn.close()

    def list(self, collection: str, limit: int = 1000) -> List[Dict[str, Any]]:
        _check_collection(collection)
        conn = self.get_connection()
        try:
            rows = conn.execute(
                f"SELECT data FROM {collection} ORDER BY doc_id LIMIT ?", (int(limit),)
            ).fetchall()
            return [json.loads(row["data"]) for row in rows]
        finally:
            conn.close()


class FirestoreDocumentStore:
    """Firestore backend. ``client`` is a ``google.cloud.firestore`` client or a compatible fake."""

    def __init__(self, client: Any):
        if client is None:
            raise ValueError("Firestore client is required")
        self.client = client

    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        _check_collection(collection)
        self.client.collection(collection).document(str(doc_id)).set(data)

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        _check_collection(collection)
        snapshot = self.client.collection(collection).document(str(doc_id)).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list(self, collection: str, limit: int = 1000) -> List[Dict[str, Any]]:
        _check_collection(collection)
        documents = [doc.to_dict() for doc in self.client.collection(collection).limit(int(limit)).stream()]
        return sorted(documents, key=lambda d: str(d.get("_doc_id", "")))


class DualDocumentStore:
    """
    SQLite plus optional Firestore, in the host project's pattern: write SQLite first and
    then Firestore; read Firestore first and fall back to SQLite. A Firestore failure is
    logged and never fails the request.
    """

    def __init__(self, sqlite_store: SQLiteDocumentStore, firestore_store: Optional[FirestoreDocumentStore] = None):
        self.sqlite_store = sqlite_store
        self.firestore_store = firestore_store

    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        self.sqlite_store.put(collection, doc_id, data)
        if self.firestore_store is not None:
            try:
                self.firestore_store.put(collection, doc_id, data)
            except Exception as error:
                logger.warning(f"Firestore write failed for {collection}/{doc_id}: {error}")

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        if self.firestore_store is not None:
            try:
                document = self.firestore_store.get(collection, doc_id)
                if document is not None:
                    return document
            except Exception as error:
                logger.warning(f"Firestore read failed for {collection}/{doc_id}: {error}")
        return self.sqlite_store.get(collection, doc_id)

    def list(self, collection: str, limit: int = 1000) -> List[Dict[str, Any]]:
        if self.firestore_store is not None:
            try:
                documents = self.firestore_store.list(collection, limit)
                if documents:
                    return documents
            except Exception as error:
                logger.warning(f"Firestore list failed for {collection}: {error}")
        return self.sqlite_store.list(collection, limit)


class RecommendationRepository:
    """Typed access to the feature's data on top of any ``DocumentStore``."""

    def __init__(self, store: DocumentStore):
        self.store = store

    # ─── items ──────────────────────────────────────────────────────────────────

    def upsert_item(self, item: RecommendationItemModel) -> None:
        data = item.model_dump(mode="json")
        data["_doc_id"] = item.item_id
        self.store.put("rec_items", item.item_id, data)

    def get_item(self, item_id: str) -> Optional[RecommendationItemModel]:
        data = self.store.get("rec_items", item_id)
        return self._to_item(data) if data else None

    def list_items(self, limit: int = 5000) -> List[RecommendationItemModel]:
        items = (self._to_item(data) for data in self.store.list("rec_items", limit))
        return [item for item in items if item is not None]

    @staticmethod
    def _to_item(data: Dict[str, Any]) -> Optional[RecommendationItemModel]:
        try:
            return RecommendationItemModel.model_validate({k: v for k, v in data.items() if k != "_doc_id"})
        except Exception as error:
            logger.error(f"Unreadable item record skipped: {data.get('item_id')} ({type(error).__name__})")
            return None

    # ─── profiles ───────────────────────────────────────────────────────────────

    def get_profile(self, profile_id: str) -> ViewerProfileModel:
        """
        Load a viewer profile.

        An account with no stored profile gets the default (adult, self-declared), by
        product decision. A stored profile that cannot be read, or that has lost its age
        tier, is returned as a child profile: when the record is damaged the safe
        assumption is the most restrictive one.
        """
        data = self.store.get("rec_profiles", profile_id)
        if data is None:
            return ViewerProfileModel(profile_id=str(profile_id), user_id=str(profile_id))
        try:
            if not data.get("age_tier"):
                raise ValueError("age_tier missing")
            return ViewerProfileModel.model_validate({k: v for k, v in data.items() if k != "_doc_id"})
        except Exception as error:
            logger.error(f"Profile {profile_id} unreadable ({type(error).__name__}); treating as child")
            return ViewerProfileModel(profile_id=str(profile_id), user_id=str(profile_id), age_tier=AgeTier.CHILD)

    def profile_exists(self, profile_id: str) -> bool:
        return self.store.get("rec_profiles", profile_id) is not None

    def save_profile(self, profile: ViewerProfileModel) -> None:
        profile.updated_at = _now_iso()
        profile.recent_feed_history = profile.recent_feed_history[-FEED_HISTORY_LIMIT:]
        data = profile.model_dump(mode="json")
        data["_doc_id"] = profile.profile_id
        self.store.put("rec_profiles", profile.profile_id, data)

    # ─── engagement and override events ─────────────────────────────────────────

    def record_event(self, event_id: str, event: Dict[str, Any]) -> None:
        self.store.put("rec_events", event_id, {**event, "_doc_id": event_id})

    def list_events(self, limit: int = 5000) -> List[Dict[str, Any]]:
        return self.store.list("rec_events", limit)

    # ─── bandit arms ────────────────────────────────────────────────────────────

    def load_bandit_arms(self) -> Dict[str, Dict[str, float]]:
        arms: Dict[str, Dict[str, float]] = {}
        for data in self.store.list("rec_bandit_arms", 10000):
            try:
                arms[str(data["key"])] = {"alpha": float(data["alpha"]), "beta": float(data["beta"])}
            except (KeyError, TypeError, ValueError):
                logger.error(f"Unreadable bandit arm skipped: {data.get('_doc_id')}")
        return arms

    def save_bandit_arm(self, key: str, alpha: float, beta: float) -> None:
        self.store.put("rec_bandit_arms", key, {"_doc_id": key, "key": key, "alpha": alpha, "beta": beta})

    # ─── precedent memory ───────────────────────────────────────────────────────

    def add_precedent(self, case: PrecedentCase) -> None:
        data = case.model_dump(mode="json")
        data["_doc_id"] = case.case_id
        self.store.put("rec_precedents", case.case_id, data)

    def list_precedents(self, limit: int = 5000) -> List[PrecedentCase]:
        cases: List[PrecedentCase] = []
        for data in self.store.list("rec_precedents", limit):
            try:
                cases.append(PrecedentCase.model_validate({k: v for k, v in data.items() if k != "_doc_id"}))
            except Exception as error:
                logger.error(f"Unreadable precedent skipped: {data.get('case_id')} ({type(error).__name__})")
        return cases
