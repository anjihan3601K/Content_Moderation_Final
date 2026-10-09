"""
API tests for every new endpoint, using the host application's real authentication.

The router is mounted on a fresh FastAPI app with ``get_current_user`` and
``get_moderator`` taken from ``backend/main.py``, backed by a real ``AuthDatabase`` in a
temporary file. No part of the host's auth is reimplemented or mocked.
"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

main = pytest.importorskip("main")

from conftest import make_item, make_profile, make_store  # noqa: E402
from recommendation.src.api import (  # noqa: E402
    RecommendationContainer,
    create_recommendation_router,
    register_recommendation_routes,
)
from recommendation.src.config import SENIOR_MODERATOR_ROLES, is_recommendation_enabled  # noqa: E402
from recommendation.src.models import AgeTier, PrecedentCase  # noqa: E402
from recommendation.src.store import RecommendationRepository  # noqa: E402
from src.database.auth_db import AuthDatabase  # noqa: E402

ROLES = ["user", "moderator", "senior_moderator", "content_analyst", "policy_specialist", "admin"]
NEW_PATHS = {
    "/api/recommendations/feed", "/api/profiles/{profile_id}/preferences", "/api/moderation/queue/next",
    "/api/items/{item_id}/recommendation", "/api/items/{item_id}/tags", "/api/recommendations/feedback",
}


class Session:
    """A logged-in user: the id and the Authorization header."""

    def __init__(self, user_id, token):
        self.user_id = str(user_id)
        self.headers = {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def auth(tmp_path_factory):
    """One real AuthDatabase with a logged-in account per role, shared by the module."""
    auth_db = AuthDatabase(str(tmp_path_factory.mktemp("auth") / "auth.db"))
    sessions = {}
    for name in ROLES + ["child", "teen"]:
        role = name if name in ROLES else "user"
        assert auth_db.create_user(f"{name}_account", "password123", f"{name} account", role)
        user = auth_db.authenticate_user(f"{name}_account", "password123")
        sessions[name] = Session(user["user_id"], auth_db.create_session(user["user_id"]))
    return auth_db, sessions


@pytest.fixture
def api(tmp_path, monkeypatch, auth):
    """
    Test client, sessions per role and the repository behind the router. Storage is the
    dual store (SQLite plus the Firestore fake), so every request exercises both backends.
    """
    auth_db, sessions = auth
    monkeypatch.setattr(main, "auth_db", auth_db)
    repository = RecommendationRepository(make_store("dual", tmp_path))

    repository.save_profile(make_profile(AgeTier.CHILD, profile_id=sessions["child"].user_id,
                                         explicit_interests=["science"], tier_declared=True))
    repository.save_profile(make_profile(AgeTier.TEEN, profile_id=sessions["teen"].user_id, tier_declared=True))
    repository.upsert_item(make_item(item_id="kids"))
    repository.upsert_item(make_item(item_id="teen", audience_rating="teen", content_category="coding", content_topics=["coding"]))
    repository.upsert_item(make_item(item_id="adult", audience_rating="adult", content_category="news", content_topics=["news"]))
    repository.upsert_item(make_item(item_id="gone", audience_rating="blocked", status="removed"))
    repository.upsert_item(make_item(item_id="queued", audience_rating="adult", status="flagged", toxicity_score=0.6,
                                     agent_disagreement=0.5, overall_confidence=0.6, content_category="news", content_topics=["news"]))
    repository.upsert_item(make_item(item_id="escalated", audience_rating="blocked", status="flagged", toxicity_score=0.4,
                                     content_category="grooming", content_topics=["grooming"], escalated=True))
    repository.add_precedent(PrecedentCase(case_id="case-1", content_id="old", category="news", topics=["news"],
                                           agent_verdict="approve", final_human_action="remove", override_occurred=True))

    container = RecommendationContainer(repository)
    app = FastAPI()
    app.include_router(create_recommendation_router(main.get_current_user, main.get_moderator, lambda: container))

    class Api:
        pass

    handle = Api()
    handle.client = TestClient(app)
    handle.sessions = sessions
    handle.repository = repository
    handle.container = container
    return handle


def ids(response):
    return {item["item_id"] for item in response.json()["items"]}


# ─── authentication on every endpoint ───────────────────────────────────────────

ENDPOINTS = [
    ("get", "/api/recommendations/feed", None),
    ("get", "/api/profiles/1/preferences", None),
    ("put", "/api/profiles/1/preferences", {"explicit_interests": []}),
    ("get", "/api/moderation/queue/next", None),
    ("get", "/api/items/kids/recommendation", None),
    ("post", "/api/recommendations/feedback", {"event_type": "click", "item_id": "kids"}),
]


@pytest.mark.parametrize("method, path, body", ENDPOINTS)
def test_every_endpoint_rejects_a_missing_token(api, method, path, body):
    response = api.client.request(method, path, json=body)
    assert response.status_code in (401, 403)
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.parametrize("method, path, body", ENDPOINTS)
def test_every_endpoint_rejects_an_invalid_token(api, method, path, body):
    response = api.client.request(method, path, json=body, headers={"Authorization": "Bearer not-a-session"})
    assert response.status_code == 401


# ─── GET /api/recommendations/feed ──────────────────────────────────────────────

def test_feed_is_age_aware(api):
    child = api.client.get("/api/recommendations/feed", headers=api.sessions["child"].headers)
    teen = api.client.get("/api/recommendations/feed", headers=api.sessions["teen"].headers)
    adult = api.client.get("/api/recommendations/feed", headers=api.sessions["user"].headers)
    assert child.status_code == teen.status_code == adult.status_code == 200
    assert ids(child) == {"kids"}
    assert ids(teen) == {"kids", "teen"}
    assert ids(adult) == {"kids", "teen", "adult"}
    body = child.json()
    assert body["age_tier"] == "child" and body["profile_id"] == api.sessions["child"].user_id
    assert body["total_candidate_count"] == 6 and body["rejected_count"] == 5
    assert body["rejection_summary"]["blocked"] == 2


def test_feed_is_always_for_the_callers_own_profile(api):
    response = api.client.get(
        "/api/recommendations/feed", params={"profile_id": api.sessions["user"].user_id},
        headers=api.sessions["child"].headers,
    )
    assert response.json()["age_tier"] == "child" and ids(response) == {"kids"}


@pytest.mark.parametrize("limit", [0, 51, -1, "many"])
def test_feed_limit_is_validated(api, limit):
    response = api.client.get("/api/recommendations/feed", params={"limit": limit}, headers=api.sessions["user"].headers)
    assert response.status_code == 422


def test_feed_limit_is_applied(api):
    response = api.client.get("/api/recommendations/feed", params={"limit": 1}, headers=api.sessions["user"].headers)
    assert len(response.json()["items"]) == 1


# ─── GET / PUT /api/profiles/{id}/preferences ───────────────────────────────────

def prefs_url(api, name):
    return f"/api/profiles/{api.sessions[name].user_id}/preferences"


def test_owner_reads_own_preferences_with_the_tier_topic_list(api):
    response = api.client.get(prefs_url(api, "child"), headers=api.sessions["child"].headers)
    assert response.status_code == 200
    body = response.json()
    assert body["age_tier"] == "child" and body["explicit_interests"] == ["science"]
    assert "science" in body["allowed_topics"] and "technology" not in body["allowed_topics"]
    adult = api.client.get(prefs_url(api, "user"), headers=api.sessions["user"].headers).json()
    assert adult["age_tier"] == "adult" and adult["age_trust_level"] == "self_declared"
    assert adult["allowed_topics"] is None and adult["tier_declared"] is False


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("caller", ["user", "moderator", "senior_moderator"])
def test_other_users_cannot_read_or_change_a_profile(api, method, caller):
    response = api.client.request(method, prefs_url(api, "child"), json={"explicit_interests": []},
                                  headers=api.sessions[caller].headers)
    assert response.status_code == 403


def test_admin_can_read_and_change_any_profile(api):
    assert api.client.get(prefs_url(api, "child"), headers=api.sessions["admin"].headers).status_code == 200
    response = api.client.put(
        prefs_url(api, "child"), headers=api.sessions["admin"].headers,
        json={"age_trust_level": "parent_linked", "parental_controls": {"blocked_categories": ["science"], "strictness_level": "strict"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["age_trust_level"] == "parent_linked"
    assert body["explicit_interests"] == []  # "science" is now parentally blocked
    feed = api.client.get("/api/recommendations/feed", headers=api.sessions["child"].headers)
    assert ids(feed) == set()  # parental controls override everything


def test_child_selecting_disallowed_interests_is_rejected_with_the_list(api):
    response = api.client.put(
        prefs_url(api, "child"), headers=api.sessions["child"].headers,
        json={"explicit_interests": ["animals", "technology", "violent_extremism", "dating"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["rejected"] == ["technology", "violent_extremism", "dating"]
    stored = api.repository.get_profile(api.sessions["child"].user_id)
    assert stored.explicit_interests == ["science"]  # nothing was applied


def test_valid_interests_are_saved(api):
    response = api.client.put(prefs_url(api, "child"), headers=api.sessions["child"].headers,
                              json={"explicit_interests": ["Animals", "puzzles"]})
    assert response.status_code == 200
    assert response.json()["explicit_interests"] == ["animals", "puzzles"]
    assert api.repository.get_profile(api.sessions["child"].user_id).explicit_interests == ["animals", "puzzles"]


def test_teen_sensitive_interest_and_adult_escalation_interest_are_rejected(api):
    teen = api.client.put(prefs_url(api, "teen"), headers=api.sessions["teen"].headers,
                          json={"explicit_interests": ["mental_health"]})
    adult = api.client.put(prefs_url(api, "user"), headers=api.sessions["user"].headers,
                           json={"explicit_interests": ["finance", "grooming"]})
    assert teen.status_code == 422 and adult.status_code == 422
    assert adult.json()["detail"]["rejected"] == ["grooming"]


def test_owner_cannot_change_trust_level_or_parental_controls(api):
    for body in ({"age_trust_level": "verified"}, {"parental_controls": {"strictness_level": "low"}}):
        response = api.client.put(prefs_url(api, "child"), headers=api.sessions["child"].headers, json=body)
        assert response.status_code == 403
    assert api.repository.get_profile(api.sessions["child"].user_id).age_trust_level.value == "verified"


def test_declared_tier_can_be_lowered_but_only_an_admin_can_raise_it(api):
    url, headers = prefs_url(api, "child"), api.sessions["child"].headers
    for tier in ("teen", "adult"):
        assert api.client.put(url, headers=headers, json={"age_tier": tier}).status_code == 403
    assert api.repository.get_profile(api.sessions["child"].user_id).age_tier == AgeTier.CHILD
    assert api.client.put(url, headers=api.sessions["admin"].headers, json={"age_tier": "teen"}).status_code == 200
    assert api.client.put(url, headers=headers, json={"age_tier": "child"}).status_code == 200
    assert api.client.put(url, headers=headers, json={"age_tier": "teen"}).status_code == 403


def test_first_declaration_is_allowed_and_revalidates_existing_interests(api):
    url, headers = prefs_url(api, "user"), api.sessions["user"].headers
    assert api.client.put(url, headers=headers, json={"explicit_interests": ["finance", "science"]}).status_code == 200
    response = api.client.put(url, headers=headers, json={"age_tier": "child"})
    assert response.status_code == 200
    body = response.json()
    assert body["age_tier"] == "child" and body["tier_declared"] is True
    assert body["explicit_interests"] == ["science"]  # "finance" is not a child topic
    assert api.client.put(url, headers=headers, json={"age_tier": "adult"}).status_code == 403


@pytest.mark.parametrize("body", [
    {"age_tier": "toddler"}, {"explicit_interests": "science"}, {"explicit_interests": ["x"] * 21},
    {"parental_controls": {"strictness_level": "extreme"}}, {"parental_controls": {"blocked_categories": ["animаls"]}},
])
def test_malformed_preference_bodies_are_rejected(api, body):
    response = api.client.put(prefs_url(api, "admin"), headers=api.sessions["admin"].headers, json=body)
    assert response.status_code == 422


# ─── GET /api/moderation/queue/next ─────────────────────────────────────────────

@pytest.mark.parametrize("caller", ["user", "child"])
def test_queue_is_blocked_for_non_moderators(api, caller):
    response = api.client.get("/api/moderation/queue/next", headers=api.sessions[caller].headers)
    assert response.status_code == 403


@pytest.mark.parametrize("caller", ["moderator", "content_analyst"])
def test_moderators_see_the_queue_without_escalated_items(api, caller):
    response = api.client.get("/api/moderation/queue/next", headers=api.sessions[caller].headers)
    assert response.status_code == 200
    body = response.json()
    assert [entry["content_id"] for entry in body["items"]] == ["queued"]
    assert body["escalated_withheld"] == 1 and body["queue_length"] == 1


@pytest.mark.parametrize("caller", sorted(SENIOR_MODERATOR_ROLES))
def test_senior_roles_see_escalated_items_first(api, caller):
    response = api.client.get("/api/moderation/queue/next", headers=api.sessions[caller].headers)
    body = response.json()
    assert [entry["content_id"] for entry in body["items"]] == ["escalated", "queued"]
    assert body["items"][0]["is_escalated"] and body["escalated_withheld"] == 0


def test_queue_limit(api):
    headers = api.sessions["admin"].headers
    assert len(api.client.get("/api/moderation/queue/next", params={"limit": 1}, headers=headers).json()["items"]) == 1
    assert api.client.get("/api/moderation/queue/next", params={"limit": 0}, headers=headers).status_code == 422


# ─── GET /api/items/{id}/recommendation ─────────────────────────────────────────

def test_item_recommendation_with_precedents(api):
    response = api.client.get("/api/items/queued/recommendation", headers=api.sessions["moderator"].headers)
    assert response.status_code == 200
    body = response.json()
    assert body["suggested_action"] == "remove" and body["suggestion_source"] == "precedents"
    assert body["precedents"][0]["case_id"] == "case-1" and body["precedents"][0]["final_human_action"] == "remove"
    assert body["precedents"][0]["similarity_score"] > 0


def test_item_recommendation_access_rules(api):
    assert api.client.get("/api/items/queued/recommendation", headers=api.sessions["user"].headers).status_code == 403
    assert api.client.get("/api/items/missing/recommendation", headers=api.sessions["moderator"].headers).status_code == 404
    assert api.client.get("/api/items/escalated/recommendation", headers=api.sessions["moderator"].headers).status_code == 403
    senior = api.client.get("/api/items/escalated/recommendation", headers=api.sessions["senior_moderator"].headers)
    assert senior.status_code == 200
    assert senior.json()["suggested_action"] == "escalate" and senior.json()["is_escalated"] is True
    assert api.client.get("/api/items/queued/recommendation", params={"k": 0}, headers=api.sessions["admin"].headers).status_code == 422


# ─── POST /api/recommendations/feedback ─────────────────────────────────────────

FEEDBACK = "/api/recommendations/feedback"


def test_engagement_event_is_recorded_for_the_caller(api):
    response = api.client.post(FEEDBACK, headers=api.sessions["user"].headers, json={"event_type": "view_long", "item_id": "adult"})
    assert response.status_code == 200 and response.json()["accepted"] is True
    assert api.repository.get_profile(api.sessions["user"].user_id).learned_interests == {"news": 0.4}
    assert api.container.feed_bandit.arms["adult:news"]["alpha"] == 2.0


def test_child_engagement_with_an_adult_item_teaches_nothing(api):
    response = api.client.post(FEEDBACK, headers=api.sessions["child"].headers, json={"event_type": "view_long", "item_id": "adult"})
    assert response.status_code == 200 and "Not used for learning" in response.json()["detail"]
    assert api.repository.get_profile(api.sessions["child"].user_id).learned_interests == {}


@pytest.mark.parametrize("caller", ["user", "child"])
def test_override_is_blocked_for_non_moderators(api, caller):
    response = api.client.post(FEEDBACK, headers=api.sessions[caller].headers,
                               json={"event_type": "moderator_override", "item_id": "queued", "final_action": "approve"})
    assert response.status_code == 403
    assert api.repository.get_item("queued").status == "flagged"
    assert len(api.repository.list_precedents()) == 1


def test_moderator_override_updates_queue_precedents_and_item(api):
    response = api.client.post(
        FEEDBACK, headers=api.sessions["moderator"].headers,
        json={"event_type": "moderator_override", "item_id": "queued", "final_action": "remove", "original_verdict": "approve"},
    )
    assert response.status_code == 200 and response.json()["override_occurred"] is True
    assert api.repository.get_item("queued").status == "removed"
    assert len(api.repository.list_precedents()) == 2
    assert api.container.queue_bandit.mean("queue:news") > 0.5
    queue = api.client.get("/api/moderation/queue/next", headers=api.sessions["admin"].headers).json()
    assert [entry["content_id"] for entry in queue["items"]] == ["escalated"]


def test_escalated_item_can_only_be_resolved_by_a_senior_role(api):
    body = {"event_type": "moderator_override", "item_id": "escalated", "final_action": "remove"}
    assert api.client.post(FEEDBACK, headers=api.sessions["moderator"].headers, json=body).status_code == 403
    assert api.client.post(FEEDBACK, headers=api.sessions["policy_specialist"].headers, json=body).status_code == 200


@pytest.mark.parametrize("body, status", [
    ({"event_type": "moderator_override", "item_id": "queued"}, 422),
    ({"event_type": "moderator_override", "item_id": "queued", "final_action": "delete_everything"}, 422),
    ({"event_type": "moderator_override", "item_id": "ghost", "final_action": "remove"}, 404),
    ({"event_type": "click", "item_id": "ghost"}, 404),
    ({"event_type": "teleport", "item_id": "kids"}, 422),
    ({"event_type": "click"}, 422),
    ({"event_type": "click", "item_id": ""}, 422),
])
def test_feedback_validation(api, body, status):
    assert api.client.post(FEEDBACK, headers=api.sessions["admin"].headers, json=body).status_code == status


# ─── registration and the feature flag ──────────────────────────────────────────

def paths(app):
    return {route.path for route in app.routes}


def test_register_adds_exactly_the_new_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_DB_PATH", str(tmp_path / "rec.db"))
    app = FastAPI()
    before = paths(app)
    register_recommendation_routes(app, main.get_current_user, main.get_moderator)
    assert paths(app) - before == NEW_PATHS


def test_host_app_exposes_the_routes_only_when_the_flag_is_on():
    host_paths = paths(main.app)
    if is_recommendation_enabled():
        assert NEW_PATHS <= host_paths
    else:
        assert not NEW_PATHS & host_paths


def test_new_routes_do_not_collide_with_existing_ones():
    existing = {route.path for route in main.app.routes} - NEW_PATHS
    prefixes = ("/api/recommendations", "/api/profiles", "/api/moderation", "/api/items")
    assert not [path for path in existing if path.startswith(prefixes)]


def test_senior_role_list_matches_the_host_dependency():
    from fastapi import HTTPException

    for role in ROLES:
        try:
            main.get_senior_moderator({"role": role})
            host_allows = True
        except HTTPException:
            host_allows = False
        assert host_allows == (role in SENIOR_MODERATOR_ROLES), role
