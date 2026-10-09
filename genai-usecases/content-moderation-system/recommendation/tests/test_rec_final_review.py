"""
Regression tests for the final independent review (Stage 4).

Each test reproduces a finding from the reviewer's report. L = leak, W = weakness.
"""

import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from conftest import make_item, make_profile
from fakes import FakeFirestoreClient
from recommendation.src import integration
from recommendation.src.api import RecommendationContainer, create_recommendation_router
from recommendation.src.models import (
    AgeTier,
    AgeTrustLevel,
    AudienceRating,
    FeedbackEvent,
    GateReason,
    ParentalControls,
    PrecedentCase,
)
from recommendation.src.moderator_queue import ReviewQueuePrioritizer, is_escalated, needs_review
from recommendation.src.rating import derive_audience_rating, find_escalation_categories
from recommendation.src.safety_gate import SafetyGate
from recommendation.src.service import FeedService
from recommendation.src.store import (
    DualDocumentStore,
    FirestoreDocumentStore,
    RecommendationRepository,
    SQLiteDocumentStore,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
from gate_harness import base_state  # noqa: E402

MODERATOR_ROLES = {"moderator", "senior_moderator", "content_analyst", "policy_specialist", "admin"}


class Client:
    """The router with header-driven stand-in auth: X-User and X-Role."""

    def __init__(self, repository):
        from fastapi import Header

        def current_user(x_user: str = Header(...), x_role: str = Header("user")):
            return {"user_id": x_user, "role": x_role}

        def moderator(user: dict = Depends(current_user)):
            # Same shape as the host's get_moderator: depends on the current user.
            if user["role"] not in MODERATOR_ROLES:
                raise HTTPException(status_code=403, detail="Moderator access required")
            return user

        self.repository = repository
        self.container = RecommendationContainer(repository)
        app = FastAPI()
        app.include_router(create_recommendation_router(current_user, moderator, lambda: self.container))
        self.http = TestClient(app)

    def call(self, method, path, user, role="user", **kwargs):
        return self.http.request(method, path, headers={"X-User": user, "X-Role": role}, **kwargs)

    def feed(self, user):
        return [item["item_id"] for item in self.call("get", "/api/recommendations/feed", user, params={"limit": 50}).json()["items"]]


@pytest.fixture
def client(sqlite_repository):
    return Client(sqlite_repository)


def seed(repository):
    repository.upsert_item(make_item(item_id="sci"))
    repository.upsert_item(make_item(item_id="sports", content_category="sports", content_topics=["sports"]))
    repository.upsert_item(make_item(item_id="adult", audience_rating="adult", content_category="news", content_topics=["news"]))


# ─── L1: damaged profile record ─────────────────────────────────────────────────

def damage(repository, profile_id, **changes):
    data = repository.store.get("rec_profiles", profile_id)
    data.update(changes)
    repository.store.put("rec_profiles", profile_id, data)


def test_L1_damaged_profile_keeps_parental_blocks_and_cannot_self_raise(client):
    seed(client.repository)
    body = {"age_tier": "child", "age_trust_level": "verified",
            "parental_controls": {"blocked_categories": ["sports"], "strictness_level": "strict"}}
    assert client.call("put", "/api/profiles/kid/preferences", "admin", "admin", json=body).status_code == 200
    assert client.feed("kid") == ["sci"]

    damage(client.repository, "kid", parental_controls={"blocked_categories": ["sports"], "strictness_level": "very_strict"})

    assert client.feed("kid") == ["sci"]                       # the parental block survived
    stored = client.repository.store.get("rec_profiles", "kid")
    assert stored["parental_controls"]["blocked_categories"] == ["sports"]  # the feed did not overwrite the record
    for tier in ("teen", "adult"):
        assert client.call("put", "/api/profiles/kid/preferences", "kid", json={"age_tier": tier}).status_code == 409
    assert client.call("put", "/api/profiles/kid/preferences", "kid", json={"explicit_interests": []}).status_code == 409
    assert client.feed("kid") == ["sci"]


def test_L1_damaged_profile_is_the_most_restrictive_profile(sqlite_repository):
    sqlite_repository.save_profile(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED, profile_id="p"))
    damage(sqlite_repository, "p", age_tier="toddler")
    profile = sqlite_repository.get_profile("p")
    assert profile.record_damaged and profile.tier_declared
    assert profile.age_tier == AgeTier.CHILD
    assert profile.parental_controls.max_rating == AudienceRating.ALL_AGES
    assert profile.parental_controls.strictness_level.value == "strict"
    sqlite_repository.save_profile(profile)
    assert sqlite_repository.store.get("rec_profiles", "p")["age_tier"] == "toddler"  # not written back


def test_L1_admin_can_repair_a_damaged_profile(client):
    client.repository.save_profile(make_profile(AgeTier.CHILD, profile_id="kid", tier_declared=True))
    damage(client.repository, "kid", age_trust_level="nonsense")
    response = client.call("put", "/api/profiles/kid/preferences", "admin", "admin",
                           json={"age_tier": "teen", "age_trust_level": "parent_linked"})
    assert response.status_code == 200
    repaired = client.repository.get_profile("kid")
    assert not repaired.record_damaged and repaired.age_tier == AgeTier.TEEN


@pytest.mark.parametrize("stored", [
    {"age_tier": "child", "tier_declared": False}, {"age_tier": "teen", "tier_declared": False}, {"age_tier": "teen"},
])
def test_L1_a_stored_minor_profile_cannot_raise_itself_even_if_never_marked_declared(client, stored):
    profile = make_profile(AgeTier(stored["age_tier"]), profile_id="kid")
    client.repository.save_profile(profile)
    if "tier_declared" not in stored:
        data = client.repository.store.get("rec_profiles", "kid")
        del data["tier_declared"]
        client.repository.store.put("rec_profiles", "kid", data)
    assert client.call("put", "/api/profiles/kid/preferences", "kid", json={"age_tier": "adult"}).status_code == 403
    assert client.repository.get_profile("kid").age_tier.value == stored["age_tier"]


# ─── L2: stale Firestore copy ───────────────────────────────────────────────────

class FlakyFirestore(FakeFirestoreClient):
    pass


@pytest.fixture
def dual(tmp_path):
    firestore = FlakyFirestore()
    store = DualDocumentStore(SQLiteDocumentStore(str(tmp_path / "rec.db")), FirestoreDocumentStore(firestore))
    return Client(RecommendationRepository(store)), firestore


def test_L2_a_removal_takes_effect_even_if_the_firestore_write_fails(dual):
    client, firestore = dual
    client.repository.upsert_item(make_item(item_id="bad"))
    client.repository.upsert_item(make_item(item_id="ok"))
    client.repository.save_profile(make_profile(AgeTier.CHILD, profile_id="kid", tier_declared=True))
    assert client.feed("kid") == ["bad", "ok"]

    firestore.available = False
    body = {"event_type": "moderator_override", "item_id": "bad", "final_action": "remove"}
    assert client.call("post", "/api/recommendations/feedback", "mod", "moderator", json=body).status_code == 200
    firestore.available = True

    assert firestore.data["rec_items"]["bad"]["status"] == "approved"   # Firestore really is stale
    assert client.feed("kid") == ["ok"]
    assert client.repository.get_item("bad").status == "removed"


def test_L2_a_tier_change_takes_effect_even_if_the_firestore_write_fails(dual):
    client, firestore = dual
    seed(client.repository)
    client.repository.save_profile(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED, profile_id="kid", tier_declared=True))
    assert "adult" in client.feed("kid")

    firestore.available = False
    body = {"age_tier": "child", "parental_controls": {"max_rating": "all_ages"}}
    assert client.call("put", "/api/profiles/kid/preferences", "admin", "admin", json=body).status_code == 200
    firestore.available = True

    assert client.feed("kid") == ["sci", "sports"]
    assert client.feed("kid") == ["sci", "sports"]               # and the feed did not write the stale tier back
    assert client.repository.get_profile("kid").age_tier == AgeTier.CHILD


def test_L2_pending_documents_resync_on_the_next_successful_write(dual):
    client, firestore = dual
    firestore.available = False
    client.repository.upsert_item(make_item(item_id="a", status="flagged"))
    firestore.available = True
    sqlite_store = client.repository.store.sqlite_store
    assert sqlite_store.pending_sync_ids("rec_items") == {"a"}
    client.repository.upsert_item(make_item(item_id="a", status="approved"))
    assert sqlite_store.pending_sync_ids("rec_items") == set()
    assert firestore.data["rec_items"]["a"]["status"] == "approved"


# ─── L3: machine re-rating versus a moderator's decision ────────────────────────

@pytest.fixture
def hooked(sqlite_repository, monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    integration.set_repository(sqlite_repository)
    yield Client(sqlite_repository)
    integration.set_repository(None)


def test_L3_a_pipeline_rerun_does_not_undo_a_moderators_removal(hooked):
    hooked.repository.save_profile(make_profile(AgeTier.CHILD, profile_id="kid", tier_declared=True))
    integration.on_moderation_complete(base_state("p1"))
    assert hooked.feed("kid") == ["p1"]

    body = {"event_type": "moderator_override", "item_id": "p1", "final_action": "remove"}
    assert hooked.call("post", "/api/recommendations/feedback", "mod", "moderator", json=body).status_code == 200
    assert hooked.feed("kid") == []

    integration.on_moderation_complete(base_state("p1"))
    assert hooked.feed("kid") == []
    assert hooked.repository.get_item("p1").status == "removed"


def test_L3_a_rerun_can_tighten_but_not_loosen_a_human_reviewed_item(hooked):
    integration.on_moderation_complete(base_state("p1"))
    body = {"event_type": "moderator_override", "item_id": "p1", "final_action": "approve"}
    hooked.call("post", "/api/recommendations/feedback", "mod", "moderator", json=body)
    assert hooked.repository.get_item("p1").audience_rating == AudienceRating.ADULT

    integration.on_moderation_complete(base_state("p1"))                      # machine says all_ages again
    assert hooked.repository.get_item("p1").audience_rating == AudienceRating.ADULT

    removed = base_state("p1")
    removed.update(status="removed", moderation_action="removed", content_removed=True)
    integration.on_moderation_complete(removed)                               # stricter: accepted
    assert hooked.repository.get_item("p1").audience_rating == AudienceRating.BLOCKED


@pytest.mark.parametrize("content_id", [None, "", "  ", 7])
def test_L3_items_without_a_usable_id_are_not_stored(hooked, content_id):
    state = base_state("x")
    state["content_id"] = content_id
    integration.on_moderation_complete(state)
    assert hooked.repository.list_items() == []


# ─── L4 and W1, W2: escalation and the moderator side ───────────────────────────

def escalated_item(item_id="esc", **overrides):
    fields = dict(item_id=item_id, status="flagged", audience_rating="blocked", content_category="grooming",
                  content_topics=["grooming", "gaming_general"], toxicity_score=0.4, escalated=True)
    fields.update(overrides)
    return make_item(**fields)


def test_L4_resolved_escalated_cases_are_not_shown_to_ordinary_moderators(client):
    client.repository.upsert_item(escalated_item())
    client.repository.upsert_item(make_item(item_id="plain", status="flagged", audience_rating="adult",
                                            content_category="gaming_general", content_topics=["gaming_general"]))
    body = {"event_type": "moderator_override", "item_id": "esc", "final_action": "remove", "notes": "senior-only note"}
    assert client.call("post", "/api/recommendations/feedback", "boss", "senior_moderator", json=body).status_code == 200

    ordinary = client.call("get", "/api/items/plain/recommendation", "mod", "moderator", params={"k": 10}).json()
    assert ordinary["precedents"] == []
    senior = client.call("get", "/api/items/plain/recommendation", "boss", "senior_moderator", params={"k": 10}).json()
    assert [case["content_id"] for case in senior["precedents"]] == ["esc"]


def test_L4_escalated_precedents_stored_without_the_flag_are_still_filtered(client):
    client.repository.upsert_item(make_item(item_id="plain", status="flagged", audience_rating="adult",
                                            content_category="gaming_general", content_topics=["gaming_general"]))
    client.repository.add_precedent(PrecedentCase(
        case_id="old", content_id="x", category="self_harm", topics=["gaming_general"],
        agent_verdict="approve", final_human_action="remove", override_occurred=True))
    ordinary = client.call("get", "/api/items/plain/recommendation", "mod", "moderator").json()
    assert ordinary["precedents"] == []


def test_W1_an_item_escalated_by_a_moderator_becomes_senior_only_and_goes_first(client):
    client.repository.upsert_item(make_item(item_id="f1", status="flagged", audience_rating="adult", toxicity_score=0.1))
    client.repository.upsert_item(make_item(item_id="f2", status="flagged", audience_rating="adult", toxicity_score=0.9,
                                            agent_disagreement=0.9, overall_confidence=0.2, exposure_count=10**6))
    body = {"event_type": "moderator_override", "item_id": "f1", "final_action": "escalate"}
    assert client.call("post", "/api/recommendations/feedback", "mod", "moderator", json=body).status_code == 200

    stored = client.repository.get_item("f1")
    assert stored.escalated and stored.status == "escalated" and is_escalated(stored)
    ordinary = client.call("get", "/api/moderation/queue/next", "mod", "moderator").json()
    assert [entry["content_id"] for entry in ordinary["items"]] == ["f2"] and ordinary["escalated_withheld"] == 1
    senior = client.call("get", "/api/moderation/queue/next", "boss", "senior_moderator").json()
    assert [entry["content_id"] for entry in senior["items"]] == ["f1", "f2"]
    assert client.call("get", "/api/items/f1/recommendation", "mod", "moderator").status_code == 403
    approve = {"event_type": "moderator_override", "item_id": "f1", "final_action": "approve"}
    assert client.call("post", "/api/recommendations/feedback", "mod2", "moderator", json=approve).status_code == 403


def test_W1_status_escalated_alone_counts_as_escalated():
    assert is_escalated(make_item(status="escalated"))


@pytest.mark.parametrize("status", ["approved", "pending", None, "needs_review", "flagged", "warned"])
def test_W2_unreviewed_high_risk_items_are_queued_whatever_their_status(status):
    item = escalated_item(status=status)
    assert needs_review(item)
    queue = ReviewQueuePrioritizer().prioritize_queue([item, make_item(item_id="plain", status="flagged")])
    assert queue[0].content_id == "esc"


def test_W2_reviewed_or_removed_high_risk_items_leave_the_queue():
    assert not needs_review(escalated_item(status="approved", human_reviewed=True))
    assert not needs_review(escalated_item(status="removed"))


def test_W2_agent_approval_alone_never_makes_a_high_risk_item_servable():
    state = base_state("x")
    state.update(content_category="grooming", content_topics=["grooming"])
    assert derive_audience_rating(state).rating == AudienceRating.BLOCKED
    for tier, trust in [(AgeTier.ADULT, AgeTrustLevel.VERIFIED), (AgeTier.TEEN, AgeTrustLevel.VERIFIED)]:
        from recommendation.src.rating import build_item_from_state
        assert not SafetyGate.evaluate_item(make_profile(tier, trust), build_item_from_state(state)).passed


def test_W3_escalation_term_split_across_labels_is_found():
    assert find_escalation_categories(["self", "harm"]) == ("self_harm",)
    assert find_escalation_categories(["science", "nature"]) == ()


# ─── W5 to W8 and notes ─────────────────────────────────────────────────────────

def test_W5_borderline_is_derived_by_the_gate_when_the_stored_flag_is_missing():
    strict_teen = make_profile(AgeTier.TEEN, parental_controls={"strictness_level": "strict"})
    item = make_item(audience_rating="teen", content_category="coding", content_topics=["coding"], toxicity_score=0.3)
    assert item.is_borderline is False
    assert SafetyGate.evaluate_item(strict_teen, item).rejection_reason == GateReason.BORDERLINE


def test_W6_an_async_moderator_dependency_is_refused():
    async def async_moderator(user):
        return user

    with pytest.raises(TypeError):
        create_recommendation_router(lambda: {}, async_moderator, lambda: None)


@pytest.mark.parametrize("value", ["0", " 0 ", "0_0", b"0", "٠", "0.01", True])
def test_W7_text_is_never_parsed_as_a_score(value):
    state = base_state("x")
    state["toxicity_score"] = value
    assert derive_audience_rating(state).rating == AudienceRating.ADULT
    assert make_item(toxicity_score=value).toxicity_score is None
    assert make_item(agent_disagreement=value).agent_disagreement is None


@pytest.mark.parametrize("label", ["the", "of the", "a", "and"])
def test_W8_parental_blocks_made_only_of_filler_words_are_rejected(label):
    with pytest.raises(ValueError):
        ParentalControls(blocked_categories=[label])


@pytest.mark.parametrize("action", ["approve", "warn"])
@pytest.mark.parametrize("rating", ["all_ages", "teen", None, "blocked"])
def test_note_a_moderator_decision_never_leaves_an_item_rated_for_minors(sqlite_repository, action, rating):
    client = Client(sqlite_repository)
    sqlite_repository.upsert_item(make_item(item_id="f", status="flagged", audience_rating=rating))
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="kid", tier_declared=True))
    sqlite_repository.save_profile(make_profile(AgeTier.TEEN, profile_id="teen", tier_declared=True))
    body = {"event_type": "moderator_override", "item_id": "f", "final_action": action}
    assert client.call("post", "/api/recommendations/feedback", "mod", "moderator", json=body).status_code == 200
    assert sqlite_repository.get_item("f").audience_rating == AudienceRating.ADULT
    assert client.feed("kid") == [] and client.feed("teen") == []
