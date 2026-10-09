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


# ─── moderator tags ─────────────────────────────────────────────────────────────

def stuck_state(content_id="stuck"):
    """A post whose language-model call failed: under review, no category, no topics."""
    state = base_state(content_id)
    state.update(status="under_review", content_category=None, content_topics=[], moderation_action=None,
                 violation_severity=None, agent_decisions=[
                     {"agent_name": "Content Analysis Agent", "decision": "needs_review", "confidence": 0.0}])
    return state


def set_tags(client, item_id, topics, role="moderator"):
    return client.call("put", f"/api/items/{item_id}/tags", "staff", role, json={"topics": topics})


def served_tiers(body):
    return [entry["age_tier"] for entry in body["suitable_for"] if entry["served"]]


def test_tags_alone_do_not_make_an_unapproved_item_servable(linked):
    integration.on_moderation_complete(stuck_state())
    response = set_tags(linked, "stuck", ["Science", "animals"])
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "science" and body["content_topics"] == ["science", "animals"]
    assert body["tags_source"] == "moderator"
    assert body["audience_rating"] == "adult" and served_tiers(body) == []
    assert "science" in body["known_topics"] and "mental_health" in body["known_topics"]


@pytest.mark.parametrize("topics, rating, tiers", [
    (["science", "animals"], "all_ages", ["child", "teen", "adult"]),
    (["coding"], "teen", ["teen", "adult"]),
    (["science", "coding"], "teen", ["teen", "adult"]),
    (["news"], "adult", ["adult"]),
    (["science", "my_own_tag"], "adult", ["adult"]),
])
def test_approved_and_tagged_by_a_moderator_is_rated_from_the_tags(linked, topics, rating, tiers):
    integration.on_moderation_complete(stuck_state())
    assert integration.on_manual_review(content_row("stuck"), "approve") is True
    body = set_tags(linked, "stuck", topics).json()
    assert body["audience_rating"] == rating
    assert served_tiers(body) == tiers
    assert body["human_reviewed"] is True


def test_order_does_not_matter_tag_first_then_approve(linked):
    integration.on_moderation_complete(stuck_state())
    set_tags(linked, "stuck", ["science"])
    assert integration.on_manual_review(content_row("stuck"), "approve") is True
    body = detail(linked, "stuck").json()
    assert body["audience_rating"] == "all_ages" and served_tiers(body) == ["child", "teen", "adult"]


def test_pipeline_tags_plus_approval_stay_adult_until_a_moderator_confirms_the_tags(linked):
    state = base_state("item")
    state.update(status="under_review")
    integration.on_moderation_complete(state)
    integration.on_manual_review(content_row("item"), "approve")
    assert detail(linked, "item").json()["audience_rating"] == "adult"
    assert set_tags(linked, "item", ["science"]).json()["audience_rating"] == "all_ages"


@pytest.mark.parametrize("overrides, expected", [
    ({"toxicity_score": 0.2}, "teen"), ({"toxicity_score": 0.5}, "adult"), ({"toxicity_score": None}, "adult"),
    ({"policy_violations": ["spam"]}, "teen"), ({"policy_violations": ["hate_speech"]}, "adult"),
])
def test_machine_signals_still_cap_the_rating_of_a_tagged_item(linked, overrides, expected):
    linked.repository.upsert_item(make_item(item_id="i", status="under_review", audience_rating="adult", **overrides))
    integration.on_manual_review(content_row("i"), "approve")
    assert set_tags(linked, "i", ["science"]).json()["audience_rating"] == expected


def test_tagging_a_removed_item_does_not_unblock_it(linked):
    integration.on_moderation_complete(stuck_state())
    integration.on_manual_review(content_row("stuck"), "remove")
    body = set_tags(linked, "stuck", ["science"]).json()
    assert body["audience_rating"] == "blocked" and served_tiers(body) == []


def test_a_high_risk_tag_escalates_the_item(linked):
    integration.on_moderation_complete(stuck_state())
    integration.on_manual_review(content_row("stuck"), "approve")
    body = set_tags(linked, "stuck", ["science", "self harm"]).json()
    assert body["is_escalated"] is True and body["audience_rating"] == "adult"
    assert served_tiers(body) == ["adult"]
    assert set_tags(linked, "stuck", ["science"]).status_code == 403            # now senior-only
    assert set_tags(linked, "stuck", ["science"], role="senior_moderator").status_code == 200
    assert linked.repository.get_item("stuck").escalated is True                  # escalation is not undone by retagging


def test_moderator_tags_survive_a_pipeline_rerun(linked):
    integration.on_moderation_complete(stuck_state())
    integration.on_manual_review(content_row("stuck"), "approve")
    set_tags(linked, "stuck", ["coding"])
    rerun = base_state("stuck")                                                   # the pipeline now says "science"
    integration.on_moderation_complete(rerun)
    stored = linked.repository.get_item("stuck")
    assert stored.content_topics == ["coding"] and stored.tags_source == "moderator"
    assert stored.audience_rating.value == "teen"


def test_tag_endpoint_access_and_validation(linked):
    integration.on_moderation_complete(stuck_state())
    assert set_tags(linked, "stuck", ["science"], role="user").status_code == 403
    assert set_tags(linked, "missing", ["science"]).status_code == 404
    for bad in ([], [""], ["x" * 41], ["animаls"], ["t"] * 11 + ["u" + str(n) for n in range(11)], "science"):
        assert set_tags(linked, "stuck", bad).status_code == 422, bad
    assert set_tags(linked, "stuck", ["Science", "science", " SCIENCE "]).json()["content_topics"] == ["science"]


def test_approval_settles_agent_disagreement(linked):
    linked.repository.upsert_item(make_item(item_id="i", status="pending_human_review", audience_rating="adult",
                                            agent_disagreement=0.5, overall_confidence=0.3))
    integration.on_manual_review(content_row("i"), "approve")
    stored = linked.repository.get_item("i")
    assert (stored.agent_disagreement, stored.overall_confidence) == (0.0, 1.0)
