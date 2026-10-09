"""Stage 3: review-queue priority, precedent retrieval, feedback loop and telemetry."""

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from conftest import make_item, make_profile
from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.feedback import FeedbackService, ItemNotFoundError
from recommendation.src.models import AgeTier, AgeTrustLevel, AudienceRating, FeedbackEvent, PrecedentCase
from recommendation.src.moderator_queue import (
    PrecedentRetriever,
    ReviewQueuePrioritizer,
    is_escalated,
    needs_review,
    queue_arm_key,
    rule_based_suggestion,
)
from recommendation.src.service import FeedService
from recommendation.src.telemetry import RecommendationTelemetry


def queued(item_id, **overrides):
    fields = dict(item_id=item_id, status="flagged", audience_rating="adult", toxicity_score=0.5,
                  agent_disagreement=0.3, overall_confidence=0.8, exposure_count=100,
                  created_at="2026-01-01T00:00:00+00:00")
    fields.update(overrides)
    return make_item(**fields)


def case(case_id, category, action, **overrides):
    fields = dict(case_id=case_id, content_id=f"other-{case_id}", category=category, agent_verdict="approve",
                  final_human_action=action, override_occurred=action != "approve")
    fields.update(overrides)
    return PrecedentCase(**fields)


@pytest.fixture
def telemetry():
    reader = InMemoryMetricReader()
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    instance = RecommendationTelemetry(tracer_provider, MeterProvider(metric_readers=[reader]))
    instance.reader, instance.exporter = reader, exporter
    return instance


def metric_points(telemetry, name):
    data = telemetry.reader.get_metrics_data()
    points = []
    for resource_metrics in (data.resource_metrics if data else []):
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)
    return points


# ─── queue membership and priority ──────────────────────────────────────────────

@pytest.mark.parametrize("status, expected", [
    ("flagged", True), ("under_review", True), ("pending_human_review", True), ("escalated", True),
    ("approved", False), ("removed", False), ("warned", False), ("submitted", False), (None, False),
])
def test_only_items_awaiting_review_are_queued(status, expected):
    assert needs_review(queued("a", status=status)) is expected


def test_priority_is_harm_times_uncertainty_times_exposure():
    entry = ReviewQueuePrioritizer(use_learned_priority=False).calculate_priority(
        queued("a", toxicity_score=0.5, agent_disagreement=0.4, overall_confidence=0.9, exposure_count=99)
    )
    assert entry.expected_harm == 0.5
    assert entry.agent_disagreement == 0.4
    assert entry.exposure_score == 3.0
    assert entry.priority_score == pytest.approx(0.5 * 0.4 * 3.0)


def test_high_harm_high_disagreement_ranks_above_easy_items():
    items = [
        queued("easy", toxicity_score=0.1, agent_disagreement=0.0, overall_confidence=0.95),
        queued("hard", toxicity_score=0.8, agent_disagreement=0.6, overall_confidence=0.6),
        queued("harm-only", toxicity_score=0.8, agent_disagreement=0.0, overall_confidence=0.95),
        queued("split-only", toxicity_score=0.1, agent_disagreement=0.6, overall_confidence=0.6),
    ]
    order = [q.content_id for q in ReviewQueuePrioritizer().prioritize_queue(items)]
    assert order[0] == "hard" and order[-1] == "easy"


def test_exposure_raises_priority():
    items = [queued("seen", exposure_count=100000), queued("unseen", exposure_count=0)]
    assert [q.content_id for q in ReviewQueuePrioritizer().prioritize_queue(items)] == ["seen", "unseen"]


def test_unknown_signals_count_as_maximum_uncertainty_and_medium_harm():
    entry = ReviewQueuePrioritizer().calculate_priority(
        queued("a", toxicity_score=None, agent_disagreement=None, overall_confidence=None, exposure_count=0)
    )
    assert entry.expected_harm == 0.5 and entry.agent_disagreement == 1.0


def test_low_confidence_counts_as_uncertainty_even_when_agents_agree():
    assert ReviewQueuePrioritizer.uncertainty(queued("a", agent_disagreement=0.0, overall_confidence=0.2)) == 0.8


@pytest.mark.parametrize("overrides", [
    {"content_category": "violent_extremism"}, {"content_topics": ["grooming"]},
    {"policy_violations": ["self_harm_promotion"]}, {"escalated": True},
])
def test_escalation_categories_jump_the_queue_regardless_of_learned_priority(overrides):
    bandit = ThompsonSamplingBandit()
    for _ in range(200):
        bandit.update(queue_arm_key("news"), 1.0)       # learned: news is overridden constantly
        bandit.update(queue_arm_key("violent_extremism"), -1.0)
        bandit.update(queue_arm_key("science"), -1.0)
    items = [
        queued("worst-ordinary", content_category="news", content_topics=["news"], toxicity_score=0.99,
               agent_disagreement=0.9, overall_confidence=0.1, exposure_count=10**6),
        queued("escalated", toxicity_score=0.05, agent_disagreement=0.0, overall_confidence=0.99,
               exposure_count=0, **overrides),
    ]
    queue = ReviewQueuePrioritizer(bandit).prioritize_queue(items)
    assert [q.content_id for q in queue] == ["escalated", "worst-ordinary"]
    assert queue[0].is_escalated and queue[0].requires_senior_moderator
    assert queue[0].priority_score < queue[1].priority_score  # first because escalated, not because of score
    assert not queue[1].requires_senior_moderator


def test_learned_multiplier_reorders_ordinary_items_only_within_bounds():
    bandit = ThompsonSamplingBandit()
    for _ in range(50):
        bandit.update(queue_arm_key("news"), 1.0)
        bandit.update(queue_arm_key("science"), -1.0)
    prioritizer = ReviewQueuePrioritizer(bandit)
    news = prioritizer.calculate_priority(queued("n", content_category="news", content_topics=["news"]))
    science = prioritizer.calculate_priority(queued("s"))
    assert 1.4 < news.learned_multiplier <= 1.5 and 0.5 <= science.learned_multiplier < 0.6
    assert news.priority_score > science.priority_score
    off = ReviewQueuePrioritizer(bandit, use_learned_priority=False)
    assert off.calculate_priority(queued("n", content_category="news")).learned_multiplier == 1.0


def test_queue_order_is_deterministic_for_ties():
    items = [queued("b", created_at="2026-01-02T00:00:00+00:00"), queued("a", created_at="2026-01-02T00:00:00+00:00"),
             queued("older", created_at="2026-01-01T00:00:00+00:00")]
    assert [q.content_id for q in ReviewQueuePrioritizer().prioritize_queue(items)] == ["older", "a", "b"]


# ─── precedents ─────────────────────────────────────────────────────────────────

def test_precedents_are_the_k_most_similar_cases_with_their_final_actions():
    cases = [case("c1", "science", "remove"), case("c2", "news", "approve"), case("c3", "science", "remove", topics=["science"]),
             case("c4", "sports", "warn"), case("c5", "science", "approve")]
    found = PrecedentRetriever().get_similar_precedents(queued("item"), cases, k=3)
    assert len(found) == 3
    assert {c.category for c in found} == {"science"}
    assert found[0].similarity_score >= found[1].similarity_score >= found[2].similarity_score > 0
    assert all(c.final_human_action in {"remove", "approve"} for c in found)


def test_precedents_exclude_the_item_itself_and_unrelated_cases():
    cases = [case("self", "science", "remove", content_id="item"), case("far", "finance", "approve")]
    assert PrecedentRetriever().get_similar_precedents(queued("item"), cases, k=3) == []
    assert PrecedentRetriever().get_similar_precedents(queued("item"), [], k=3) == []


def test_suggestion_follows_weighted_precedents():
    retriever = PrecedentRetriever()
    item = queued("item")
    cases = [case("c1", "science", "remove"), case("c2", "science", "remove"), case("c3", "science", "approve")]
    precedents = retriever.get_similar_precedents(item, cases, k=3)
    action, confidence, source = retriever.suggest_action(item, precedents)
    assert (action, source) == ("remove", "precedents")
    assert confidence == pytest.approx(2 / 3, abs=0.01)


@pytest.mark.parametrize("toxicity, expected", [(0.9, "remove"), (0.5, "warn"), (0.1, "approve"), (None, "escalate")])
def test_rule_based_suggestion_without_precedents(toxicity, expected):
    item = queued("item", toxicity_score=toxicity)
    assert rule_based_suggestion(item)[0] == expected
    assert PrecedentRetriever().suggest_action(item, [])[::2] == (expected, "rules")


def test_escalated_item_is_always_suggested_for_escalation():
    item = queued("item", content_category="grooming", content_topics=["grooming"], toxicity_score=0.0)
    precedents = [case("c1", "grooming", "approve", similarity_score=1.0)]
    assert is_escalated(item)
    assert PrecedentRetriever().suggest_action(item, precedents)[0] == "escalate"


# ─── feedback: moderator overrides ──────────────────────────────────────────────

def feedback_service(repository, telemetry=None):
    feed_bandit = ThompsonSamplingBandit(seed=1, on_update=repository.save_bandit_arm)
    queue_bandit = ThompsonSamplingBandit(seed=1, on_update=repository.save_bandit_arm)
    return FeedbackService(repository, feed_bandit, queue_bandit, telemetry)


def override(item_id, action, verdict=None):
    return FeedbackEvent(event_type="moderator_override", item_id=item_id, final_action=action,
                         original_verdict=verdict, notes="Placeholder note.")


def test_override_updates_the_bandit_and_the_precedent_memory(repository, telemetry):
    repository.upsert_item(queued("item"))
    service = feedback_service(repository, telemetry)
    arm = queue_arm_key("science")
    assert service.queue_bandit.mean(arm) == 0.5

    response = service.handle_override(override("item", "remove", verdict="approve"), moderator_id="m1")

    assert response.override_occurred is True
    assert service.queue_bandit.mean(arm) > 0.5
    assert repository.load_bandit_arms()[arm] == {"alpha": 2.0, "beta": 1.0}
    precedents = repository.list_precedents()
    assert len(precedents) == 1
    assert (precedents[0].content_id, precedents[0].agent_verdict, precedents[0].final_human_action) == ("item", "approve", "remove")
    assert precedents[0].override_occurred
    stored = repository.get_item("item")
    assert stored.status == "removed" and stored.audience_rating == AudienceRating.BLOCKED
    assert not needs_review(stored)
    events = repository.list_events()
    assert events[0]["moderator_id"] == "m1" and events[0]["override_occurred"] is True
    assert metric_points(telemetry, "recommendation.moderation.decisions")[0].attributes["outcome"] == "overridden"
    review_times = metric_points(telemetry, "recommendation.queue.time_to_review")
    assert review_times[0].count == 1 and review_times[0].sum > 0


def test_agreeing_with_the_agent_lowers_learned_priority_and_is_still_a_precedent(sqlite_repository, telemetry):
    sqlite_repository.upsert_item(queued("item"))
    service = feedback_service(sqlite_repository, telemetry)
    response = service.handle_override(override("item", "warn", verdict="warn"), moderator_id="m1")
    assert response.override_occurred is False
    assert service.queue_bandit.mean(queue_arm_key("science")) < 0.5
    assert not sqlite_repository.list_precedents()[0].override_occurred
    assert metric_points(telemetry, "recommendation.moderation.decisions")[0].attributes["outcome"] == "accepted"


def test_agent_verdict_is_derived_when_not_supplied(sqlite_repository):
    sqlite_repository.upsert_item(queued("item", toxicity_score=0.9))
    response = feedback_service(sqlite_repository).handle_override(override("item", "approve"), "m1")
    assert sqlite_repository.list_precedents()[0].agent_verdict == "remove"
    assert response.override_occurred is True


def test_approving_a_blocked_item_never_rates_it_below_adult(sqlite_repository):
    sqlite_repository.upsert_item(queued("item", audience_rating="blocked", content_category="grooming", content_topics=["grooming"]))
    feedback_service(sqlite_repository).handle_override(override("item", "approve"), "m1")
    stored = sqlite_repository.get_item("item")
    assert stored.status == "approved" and stored.audience_rating == AudienceRating.ADULT
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="c"))
    sqlite_repository.save_profile(make_profile(AgeTier.TEEN, profile_id="t"))
    assert FeedService(sqlite_repository).get_feed("c").items == []
    assert FeedService(sqlite_repository).get_feed("t").items == []


def test_overrides_feed_back_into_queue_order_and_precedent_suggestions(sqlite_repository):
    for n in range(6):
        sqlite_repository.upsert_item(queued(f"news-{n}", content_category="news", content_topics=["news"]))
        sqlite_repository.upsert_item(queued(f"sci-{n}"))
    service = feedback_service(sqlite_repository)
    for n in range(5):
        service.handle_override(override(f"news-{n}", "remove", verdict="approve"), "m1")
        service.handle_override(override(f"sci-{n}", "approve", verdict="approve"), "m1")
    queue = ReviewQueuePrioritizer(service.queue_bandit).prioritize_queue(sqlite_repository.list_items())
    assert [q.content_id for q in queue] == ["news-5", "sci-5"]
    retriever = PrecedentRetriever()
    item = sqlite_repository.get_item("news-5")
    precedents = retriever.get_similar_precedents(item, sqlite_repository.list_precedents(), k=3)
    assert retriever.suggest_action(item, precedents)[0] == "remove"


def test_override_needs_a_final_action_and_a_known_item(sqlite_repository):
    service = feedback_service(sqlite_repository)
    with pytest.raises(ItemNotFoundError):
        service.handle_override(override("ghost", "remove"), "m1")
    sqlite_repository.upsert_item(queued("item"))
    with pytest.raises(ValueError):
        service.handle_override(FeedbackEvent(event_type="moderator_override", item_id="item"), "m1")


# ─── feedback: engagement ───────────────────────────────────────────────────────

def engage(item_id, kind="view_long"):
    return FeedbackEvent(event_type=kind, item_id=item_id)


def test_adult_engagement_updates_learned_interests_and_the_feed_bandit(repository):
    repository.upsert_item(make_item(item_id="n", audience_rating="adult", content_category="news", content_topics=["news"]))
    repository.save_profile(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED, profile_id="a"))
    service = feedback_service(repository)
    service.handle_engagement(engage("n"), "a")
    assert repository.get_profile("a").learned_interests == {"news": 0.4}
    assert service.feed_bandit.arms["adult:news"] == {"alpha": 2.0, "beta": 1.0}
    service.handle_engagement(engage("n", "skip"), "a")
    assert repository.get_profile("a").learned_interests == {"news": 0.35}
    service.handle_engagement(engage("n", "impression"), "a")
    assert repository.get_profile("a").learned_interests == {"news": 0.35}
    assert len(repository.list_events()) == 3


def test_child_engagement_cannot_add_topics_or_learn_from_unservable_items(sqlite_repository):
    sqlite_repository.upsert_item(make_item(item_id="animals", content_category="animals", content_topics=["animals"]))
    sqlite_repository.upsert_item(make_item(item_id="adult", audience_rating="adult", content_category="nightlife", content_topics=["nightlife"]))
    sqlite_repository.upsert_item(make_item(item_id="science"))
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="c", explicit_interests=["science"]))
    service = feedback_service(sqlite_repository)

    for _ in range(20):
        ignored = service.handle_engagement(engage("adult"), "c")       # not servable to a child
        service.handle_engagement(engage("animals"), "c")                # servable, but not an explicit interest
    assert "Not used for learning" in ignored.detail
    profile = sqlite_repository.get_profile("c")
    assert profile.learned_interests == {}
    assert "child:nightlife" not in service.feed_bandit.arms

    service.handle_engagement(engage("science", "skip"), "c")
    assert sqlite_repository.get_profile("c").learned_interests == {"science": 0.95}


def test_engagement_with_an_unknown_item_is_an_error(sqlite_repository):
    with pytest.raises(ItemNotFoundError):
        feedback_service(sqlite_repository).handle_engagement(engage("ghost"), "a")


# ─── telemetry ──────────────────────────────────────────────────────────────────

def test_feed_emits_a_span_latency_and_rejections_by_reason(sqlite_repository, telemetry):
    sqlite_repository.upsert_item(make_item(item_id="ok"))
    sqlite_repository.upsert_item(make_item(item_id="teen", audience_rating="teen"))
    sqlite_repository.upsert_item(make_item(item_id="gone", audience_rating="blocked"))
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="c"))
    FeedService(sqlite_repository, telemetry=telemetry).get_feed("c")

    spans = telemetry.exporter.get_finished_spans()
    assert [span.name for span in spans] == ["recommendation.feed"]
    assert spans[0].attributes["profile_id"] == "c"
    latency = metric_points(telemetry, "recommendation.feed.latency")
    assert latency[0].count == 1 and latency[0].attributes["tier"] == "child"
    rejections = {(p.attributes["reason"], p.attributes["tier"]): p.value for p in metric_points(telemetry, "recommendation.gate.rejections")}
    assert rejections == {("above_tier", "child"): 1, ("blocked", "child"): 1}


def test_default_telemetry_is_a_safe_noop_without_configured_providers():
    from recommendation.src.telemetry import get_telemetry

    instance = get_telemetry()
    assert instance is get_telemetry()
    with instance.span("recommendation.test", key="value"):
        instance.record_feed_latency(1.0, "adult")
        instance.record_gate_rejections("blocked", "adult")
        instance.record_moderation_decision(True)
        instance.record_time_to_review(-5.0, False)
