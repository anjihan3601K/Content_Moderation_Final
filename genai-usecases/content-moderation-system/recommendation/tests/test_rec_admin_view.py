"""What the admin review page relies on: item details for display, and manual reviews reaching the recommender."""

import pytest

from conftest import make_item, make_profile
from recommendation.src import integration
from recommendation.src.api import RecommendationContainer
from recommendation.src.models import AgeTier, AudienceRating
from test_rec_final_review import Client

from gate_harness import base_state  # noqa: E402


@pytest.fixture
def linked(sqlite_repository, monkeypatch):
    """A client whose container is also registered as the integration's container provider."""
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    client = Client(sqlite_repository)
    integration.set_container_provider(lambda: client.container)
    yield client
    integration.set_container_provider(None)


def detail(client, item_id, role="admin"):
    return client.call("get", f"/api/items/{item_id}/recommendation", "staff", role)


# ─── details shown on the review page ───────────────────────────────────────────

def test_item_details_include_tags_rating_and_who_it_is_suggested_for(linked):
    integration.on_moderation_complete(base_state("clean"))
    body = detail(linked, "clean").json()
    assert body["audience_rating"] == "all_ages"
    assert body["category"] == "science" and body["content_topics"] == ["science"]
    assert body["status"] == "approved" and body["toxicity_score"] == 0.02
    assert body["agent_disagreement"] == 0.0 and body["overall_confidence"] == 0.85
    assert body["human_reviewed"] is False
    assert body["suitable_for"] == [
        {"age_tier": "child", "served": True, "reason": None},
        {"age_tier": "teen", "served": True, "reason": None},
        {"age_tier": "adult", "served": True, "reason": None},
    ]


@pytest.mark.parametrize("overrides, expected", [
    ({"content_category": "coding", "content_topics": ["coding"]}, ["above_tier", None, None]),
    ({"content_category": "news", "content_topics": ["news"]}, ["above_tier", "above_tier", None]),
    ({"status": "under_review"}, ["pending_review", "pending_review", "not_servable_status"]),
    ({"status": "removed", "content_removed": True}, ["blocked", "blocked", "blocked"]),
])
def test_suggested_for_gives_the_reason_each_age_group_is_excluded(linked, overrides, expected):
    state = base_state("item")
    state.update(overrides)
    integration.on_moderation_complete(state)
    reasons = [entry["reason"] for entry in detail(linked, "item").json()["suitable_for"]]
    assert reasons == expected


def test_item_stuck_because_the_language_model_failed_shows_no_tags(linked):
    """What the pipeline leaves behind when the first agent's model call fails."""
    state = base_state("stuck")
    state.update(status="under_review", content_category=None, content_topics=[], moderation_action=None,
                 violation_severity=None, agent_decisions=[
                     {"agent_name": "Content Analysis Agent", "decision": "needs_review", "confidence": 0.0}])
    integration.on_moderation_complete(state)
    body = detail(linked, "stuck").json()
    assert body["audience_rating"] == "adult" and body["content_topics"] == []
    assert not any(entry["served"] for entry in body["suitable_for"])


# ─── the hook stores items without waiting for an endpoint call ─────────────────

def test_workflow_hook_stores_items_through_the_container_provider(linked):
    integration.set_repository(None)
    integration.on_moderation_complete(base_state("early"))
    assert linked.repository.get_item("early") is not None


def test_hook_survives_a_container_that_cannot_be_built(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")

    def broken():
        raise OSError("cannot open database")

    integration.set_container_provider(broken)
    try:
        state = base_state("x")
        integration.on_moderation_complete(state)
        assert state["audience_rating"] == "all_ages"
        assert integration.on_manual_review({"content_id": "x"}, "approve") is False
    finally:
        integration.set_container_provider(None)


# ─── manual review in the admin view reaches the recommender ────────────────────

def content_row(content_id, status="under_review"):
    return {"content_id": content_id, "content_text": "Placeholder text.", "current_status": status, "toxicity_score": 0.0}


def test_manual_approval_makes_a_stuck_item_servable_to_adults_only(linked):
    state = base_state("stuck")
    state.update(status="under_review")
    integration.on_moderation_complete(state)
    for name, tier in (("kid", AgeTier.CHILD), ("teen", AgeTier.TEEN), ("grown", AgeTier.ADULT)):
        linked.repository.save_profile(make_profile(tier, profile_id=name, tier_declared=True))
    assert linked.feed("grown") == []

    assert integration.on_manual_review(content_row("stuck"), "approve", "Content Reviewer") is True

    stored = linked.repository.get_item("stuck")
    assert stored.status == "approved" and stored.human_reviewed
    assert stored.audience_rating == AudienceRating.ADULT
    assert linked.feed("grown") == ["stuck"]
    assert linked.feed("kid") == [] and linked.feed("teen") == []
    assert len(linked.repository.list_precedents()) == 1


def test_manual_review_of_an_item_the_recommender_never_saw_creates_it(linked):
    assert integration.on_manual_review(content_row("unseen", "flagged"), "approve") is True
    stored = linked.repository.get_item("unseen")
    assert stored.status == "approved" and stored.audience_rating == AudienceRating.ADULT
    assert stored.content_topics == [] and stored.human_reviewed


def test_manual_removal_blocks_the_item_everywhere(linked):
    integration.on_moderation_complete(base_state("ok"))
    linked.repository.save_profile(make_profile(AgeTier.ADULT, profile_id="grown", tier_declared=True))
    assert linked.feed("grown") == ["ok"]
    assert integration.on_manual_review(content_row("ok", "approved"), "remove") is True
    assert linked.repository.get_item("ok").audience_rating == AudienceRating.BLOCKED
    assert linked.feed("grown") == []


@pytest.mark.parametrize("content, decision", [
    (content_row("a"), "delete"), (content_row("a"), ""), (content_row("a"), None),
    ({"content_text": "no id"}, "approve"), (None, "approve"), ({"content_id": ""}, "approve"),
])
def test_unusable_manual_reviews_are_ignored(linked, content, decision):
    assert integration.on_manual_review(content, decision) is False
    assert linked.repository.list_items() == []


def test_manual_review_does_nothing_when_the_feature_is_off(linked, monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "false")
    assert integration.on_manual_review(content_row("a"), "approve") is False
    assert linked.repository.list_items() == []
