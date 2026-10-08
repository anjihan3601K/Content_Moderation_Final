"""Storage: the same behaviour on SQLite, on Firestore (in-memory fake) and on both together."""

import sqlite3

import pytest

from conftest import make_item, make_profile
from fakes import FakeFirestoreClient
from recommendation.src.config import recommendation_db_path
from recommendation.src.models import AgeTier, AgeTrustLevel, AudienceRating, PrecedentCase
from recommendation.src.store import (
    COLLECTIONS,
    FEED_HISTORY_LIMIT,
    DualDocumentStore,
    FirestoreDocumentStore,
    RecommendationRepository,
    SQLiteDocumentStore,
)


def precedent(case_id="case-1", **overrides):
    fields = dict(case_id=case_id, content_id="item-1", category="science", agent_verdict="approve",
                  final_human_action="remove", override_occurred=True)
    fields.update(overrides)
    return PrecedentCase(**fields)


# ─── every backend (the ``repository`` fixture runs each test three times) ──────

def test_item_round_trip(repository):
    item = make_item(item_id="a", audience_rating="teen", policy_violations=["spam"], exposure_count=7)
    repository.upsert_item(item)
    assert repository.get_item("a") == item
    assert repository.get_item("missing") is None


def test_item_upsert_replaces(repository):
    repository.upsert_item(make_item(item_id="a", status="flagged"))
    repository.upsert_item(make_item(item_id="a", status="approved"))
    assert [i.status for i in repository.list_items()] == ["approved"]


def test_list_items_is_ordered_and_complete(repository):
    for name in ["c", "a", "b"]:
        repository.upsert_item(make_item(item_id=name))
    assert [i.item_id for i in repository.list_items()] == ["a", "b", "c"]


def test_stored_item_with_unknown_rating_loads_as_unrated(repository):
    data = make_item(item_id="a").model_dump(mode="json")
    data["audience_rating"] = "PG-13"
    repository.store.put("rec_items", "a", data)
    assert repository.get_item("a").audience_rating is None


def test_unreadable_item_record_is_skipped_not_served(repository):
    repository.upsert_item(make_item(item_id="good"))
    repository.store.put("rec_items", "bad", {"item_id": "bad", "content_topics": "not-a-list"})
    assert [i.item_id for i in repository.list_items()] == ["good"]
    assert repository.get_item("bad") is None


def test_missing_profile_is_the_default_adult_self_declared(repository):
    profile = repository.get_profile("42")
    assert (profile.age_tier, profile.age_trust_level) == (AgeTier.ADULT, AgeTrustLevel.SELF_DECLARED)
    assert not profile.tier_declared
    assert not repository.profile_exists("42")


def test_profile_round_trip(repository):
    profile = make_profile(
        AgeTier.TEEN, AgeTrustLevel.PARENT_LINKED, profile_id="7", explicit_interests=["coding"],
        learned_interests={"coding": 0.8}, parental_controls={"blocked_categories": ["gaming"], "max_rating": "teen"},
        tier_declared=True,
    )
    repository.save_profile(profile)
    loaded = repository.get_profile("7")
    assert loaded.age_tier == AgeTier.TEEN
    assert loaded.parental_controls.max_rating == AudienceRating.TEEN
    assert loaded.model_dump(exclude={"updated_at"}) == profile.model_dump(exclude={"updated_at"})
    assert repository.profile_exists("7")


@pytest.mark.parametrize(
    "damage",
    [{"age_tier": None}, {"age_tier": ""}, {"age_tier": "toddler"}, {"age_trust_level": "nonsense"},
     {"parental_controls": "broken"}, {"learned_interests": {"x": 9}}],
)
def test_damaged_profile_record_is_treated_as_child(repository, damage):
    profile = make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED, profile_id="7")
    repository.save_profile(profile)
    data = repository.store.get("rec_profiles", "7")
    data.update(damage)
    repository.store.put("rec_profiles", "7", data)
    assert repository.get_profile("7").age_tier == AgeTier.CHILD


def test_profile_missing_its_tier_key_is_treated_as_child(repository):
    repository.save_profile(make_profile(AgeTier.ADULT, profile_id="7"))
    data = repository.store.get("rec_profiles", "7")
    del data["age_tier"]
    repository.store.put("rec_profiles", "7", data)
    assert repository.get_profile("7").age_tier == AgeTier.CHILD


def test_feed_history_is_trimmed(repository):
    profile = make_profile(profile_id="7")
    profile.recent_feed_history = [{"item_id": str(i)} for i in range(FEED_HISTORY_LIMIT + 30)]
    repository.save_profile(profile)
    history = repository.get_profile("7").recent_feed_history
    assert len(history) == FEED_HISTORY_LIMIT
    assert history[-1]["item_id"] == str(FEED_HISTORY_LIMIT + 29)


def test_bandit_arms_round_trip(repository):
    repository.save_bandit_arm("teen:coding", 3.0, 1.5)
    repository.save_bandit_arm("queue:science", 1.0, 4.0)
    repository.save_bandit_arm("teen:coding", 4.0, 1.5)
    assert repository.load_bandit_arms() == {
        "teen:coding": {"alpha": 4.0, "beta": 1.5}, "queue:science": {"alpha": 1.0, "beta": 4.0},
    }


def test_precedents_round_trip(repository):
    repository.add_precedent(precedent("case-2", topics=["a", "b"]))
    repository.add_precedent(precedent("case-1"))
    cases = repository.list_precedents()
    assert [c.case_id for c in cases] == ["case-1", "case-2"]
    assert cases[1].topics == ["a", "b"]


def test_events_round_trip(repository):
    repository.record_event("e1", {"event_type": "click", "item_id": "a"})
    assert repository.list_events()[0]["event_type"] == "click"


def test_unknown_collection_is_rejected(repository):
    with pytest.raises(ValueError):
        repository.store.put("content_submissions", "x", {})
    with pytest.raises(ValueError):
        repository.store.list("users; DROP TABLE rec_items")


# ─── backend-specific behaviour ─────────────────────────────────────────────────

def test_sqlite_persists_across_connections(tmp_path):
    path = str(tmp_path / "rec.db")
    RecommendationRepository(SQLiteDocumentStore(path)).upsert_item(make_item(item_id="a"))
    assert RecommendationRepository(SQLiteDocumentStore(path)).get_item("a") is not None


def test_sqlite_creates_only_its_own_tables(tmp_path):
    path = str(tmp_path / "rec.db")
    SQLiteDocumentStore(path)
    conn = sqlite3.connect(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert tables == set(COLLECTIONS)


def test_default_database_file_is_separate_from_the_host_databases(monkeypatch):
    monkeypatch.delenv("RECOMMENDATION_DB_PATH", raising=False)
    path = recommendation_db_path().replace("\\", "/")
    assert path.endswith("backend/databases/recommendation_data.db")
    monkeypatch.setenv("RECOMMENDATION_DB_PATH", "/tmp/elsewhere.db")
    assert recommendation_db_path() == "/tmp/elsewhere.db"


def test_firestore_store_requires_a_client():
    with pytest.raises(ValueError):
        FirestoreDocumentStore(None)


def test_dual_store_writes_both_and_reads_firestore_first(tmp_path):
    sqlite_store = SQLiteDocumentStore(str(tmp_path / "rec.db"))
    client = FakeFirestoreClient()
    dual = DualDocumentStore(sqlite_store, FirestoreDocumentStore(client))
    dual.put("rec_items", "a", {"v": 1})
    assert sqlite_store.get("rec_items", "a") == {"v": 1}
    assert client.data["rec_items"]["a"] == {"v": 1}
    client.data["rec_items"]["a"] = {"v": 2}
    assert dual.get("rec_items", "a") == {"v": 2}


def test_dual_store_survives_a_firestore_outage(tmp_path):
    client = FakeFirestoreClient()
    repo = RecommendationRepository(
        DualDocumentStore(SQLiteDocumentStore(str(tmp_path / "rec.db")), FirestoreDocumentStore(client))
    )
    repo.upsert_item(make_item(item_id="a"))
    client.available = False
    repo.upsert_item(make_item(item_id="b"))
    assert {i.item_id for i in repo.list_items()} == {"a", "b"}
    assert repo.get_item("b") is not None


def test_dual_store_without_firestore_is_sqlite_only(tmp_path):
    repo = RecommendationRepository(DualDocumentStore(SQLiteDocumentStore(str(tmp_path / "rec.db"))))
    repo.upsert_item(make_item(item_id="a"))
    assert repo.get_item("a") is not None
