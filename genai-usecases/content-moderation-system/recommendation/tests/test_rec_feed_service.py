"""The feed path end to end: gate, ranker, bandit and guards together never leak."""

import random

import pytest

from conftest import make_item, make_profile
from gate_harness import leak_reason, load_dataset
from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.models import AgeTier, AgeTrustLevel, AudienceRating
from recommendation.src.personalization import ProfileRanker
from recommendation.src.safety_gate import SafetyGate
from recommendation.src.service import MAX_FEED_SIZE, FeedService

SEED = 20261008
RISKY_TOPICS = ["violent_extremism", "grooming", "self_harm", "nightlife", "true_crime", "news", "dating"]


def seed_items(repository):
    repository.upsert_item(make_item(item_id="kids-1"))
    repository.upsert_item(make_item(item_id="kids-2", content_category="animals", content_topics=["animals"]))
    repository.upsert_item(make_item(item_id="teen-1", audience_rating="teen", content_category="coding", content_topics=["coding"]))
    repository.upsert_item(make_item(item_id="adult-1", audience_rating="adult", content_category="news", content_topics=["news"]))
    repository.upsert_item(make_item(item_id="blocked-1", audience_rating="blocked", status="removed"))
    repository.upsert_item(make_item(item_id="pending-1", status="flagged", audience_rating="adult"))
    repository.upsert_item(make_item(item_id="legacy-1", audience_rating=None))


def test_feed_respects_the_tier_on_every_backend(repository):
    seed_items(repository)
    for tier, expected in [
        (AgeTier.CHILD, {"kids-1", "kids-2"}),
        (AgeTier.TEEN, {"kids-1", "kids-2", "teen-1"}),
        (AgeTier.ADULT, {"kids-1", "kids-2", "teen-1", "adult-1", "legacy-1"}),
    ]:
        repository.save_profile(make_profile(tier, AgeTrustLevel.VERIFIED, profile_id=tier.value))
        feed = FeedService(repository).get_feed(tier.value, limit=20)
        assert {item.item_id for item in feed.items} == expected
        assert feed.total_candidate_count == 7
        assert feed.passed_gate_count == len(expected)
        assert feed.rejected_count == 7 - len(expected)
        assert sum(feed.rejection_summary.values()) == feed.rejected_count


def test_unknown_account_gets_the_default_adult_profile_with_the_margin(sqlite_repository):
    seed_items(sqlite_repository)
    feed = FeedService(sqlite_repository).get_feed("never-seen", limit=20)
    assert feed.age_tier == AgeTier.ADULT
    assert "legacy-1" not in {item.item_id for item in feed.items}  # self-declared: unrated withheld
    assert "adult-1" in {item.item_id for item in feed.items}


def test_limit_is_clamped_and_history_recorded(sqlite_repository):
    for n in range(80):
        sqlite_repository.upsert_item(make_item(item_id=f"i{n:02d}"))
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="c"))
    service = FeedService(sqlite_repository)
    assert len(service.get_feed("c", limit=5).items) == 5
    assert len(service.get_feed("c", limit=10_000).items) == MAX_FEED_SIZE
    assert len(service.get_feed("c", limit=-3).items) == 1
    history = sqlite_repository.get_profile("c").recent_feed_history
    assert len(history) == 50 and set(history[0]) == {"item_id", "borderline", "risk"}
    before = len(history)
    service.get_feed("c", limit=5, record_history=False)
    assert len(sqlite_repository.get_profile("c").recent_feed_history) == before


class InjectingRanker(ProfileRanker):
    """A faulty or compromised ranker that tries to add items the gate rejected."""

    def __init__(self, smuggled):
        super().__init__()
        self.smuggled = smuggled

    def rank_items(self, profile, candidates, limit=10):
        return list(self.smuggled) + list(candidates)


def test_final_gate_removes_anything_a_ranker_adds(sqlite_repository):
    seed_items(sqlite_repository)
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="c"))
    smuggled = [sqlite_repository.get_item(name) for name in ("adult-1", "blocked-1", "pending-1", "legacy-1", "teen-1")]
    smuggled.append(make_item(item_id="invented", audience_rating="adult"))
    feed = FeedService(sqlite_repository, ranker=InjectingRanker(smuggled)).get_feed("c", limit=20)
    assert {item.item_id for item in feed.items} == {"kids-1", "kids-2"}


class MutatingRanker(ProfileRanker):
    """A ranker that rewrites an item to make an unservable one look servable."""

    def rank_items(self, profile, candidates, limit=10):
        return [item.model_copy(update={"audience_rating": AudienceRating.ALL_AGES, "status": "flagged"}) for item in candidates]


def test_final_gate_rechecks_items_a_ranker_altered(sqlite_repository):
    seed_items(sqlite_repository)
    sqlite_repository.save_profile(make_profile(AgeTier.CHILD, profile_id="c"))
    assert FeedService(sqlite_repository, ranker=MutatingRanker()).get_feed("c", limit=20).items == []


def test_damaged_profile_record_gets_the_child_feed(sqlite_repository):
    seed_items(sqlite_repository)
    sqlite_repository.save_profile(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED, profile_id="p"))
    data = sqlite_repository.store.get("rec_profiles", "p")
    data["age_tier"] = None
    sqlite_repository.store.put("rec_profiles", "p", data)
    feed = FeedService(sqlite_repository).get_feed("p", limit=20)
    assert feed.age_tier == AgeTier.CHILD
    assert {item.item_id for item in feed.items} == {"kids-1", "kids-2"}


def test_no_leak_through_the_full_feed_path_whatever_the_personalization_state(mock_repository):
    """
    Invariant test for the whole pipeline: every mock profile, with randomised explicit
    interests, hostile learned signals, saturated feed history and random bandit state.
    """
    rng = random.Random(SEED)
    profile_records = {record["profile_id"]: record for record in load_dataset("profiles")}
    item_records = {record["item_id"]: record for record in load_dataset("items")}
    topics = sorted({
        topic for record in item_records.values()
        for topic in (record["pipeline_state"].get("content_topics") or []) if isinstance(topic, str)
    })

    class HostileRepository:
        """Serves the mock data but replaces each profile's personalization inputs."""

        def __init__(self, inner):
            self.inner = inner
            self.items = inner.list_items()

        def list_items(self):
            return self.items

        def get_profile(self, profile_id):
            profile = self.inner.get_profile(profile_id)
            return profile.model_copy(update={
                "explicit_interests": rng.sample(RISKY_TOPICS + topics, rng.randint(0, 6)),
                "learned_interests": {t: rng.random() for t in rng.sample(RISKY_TOPICS + topics, rng.randint(0, 8))},
                "recent_feed_history": [
                    {"item_id": "h", "borderline": rng.random() < 0.5, "risk": rng.random()}
                    for _ in range(rng.randint(0, 20))
                ],
            })

        def save_profile(self, profile):
            raise AssertionError("history must not be recorded in this test")

    hostile = HostileRepository(mock_repository)
    feeds = served = served_to_minors = 0
    for profile_id, profile_record in profile_records.items():
        checked_profile = mock_repository.get_profile(profile_id)
        for _ in range(13):
            bandit = ThompsonSamplingBandit(seed=rng.randint(0, 10**9))
            for topic in rng.sample(RISKY_TOPICS + topics, 10):
                for tier in ("child", "teen", "adult"):
                    for _ in range(rng.randint(1, 30)):
                        bandit.update(f"{tier}:{topic}", rng.choice([1.0, 1.0, -1.0]))
            service = FeedService(hostile, ranker=ProfileRanker(bandit=bandit))
            feed = service.get_feed(profile_id, limit=rng.choice([5, 10, 25, 50]), record_history=False)
            feeds += 1
            for item in feed.items:
                problem = leak_reason(profile_record, item_records[item.item_id])
                assert problem is None, (problem, profile_id, item.item_id)
                assert SafetyGate.evaluate_item(checked_profile, item).passed
                served += 1
                served_to_minors += profile_record["age_tier"] != "adult"

    print(f"\nfeed invariant: feeds={feeds} items_served={served} served_to_minors={served_to_minors}")
    assert feeds >= 1000
    assert served > 5000 and served_to_minors > 2000


@pytest.mark.parametrize("tier", ["child", "teen"])
def test_minor_feeds_on_mock_data_contain_only_tier_appropriate_ratings(mock_repository, tier):
    allowed = {"child": {"all_ages"}, "teen": {"all_ages", "teen"}}[tier]
    for record in load_dataset("profiles"):
        if record["age_tier"] != tier:
            continue
        feed = FeedService(mock_repository).get_feed(record["profile_id"], limit=50, record_history=False)
        assert {item.audience_rating.value for item in feed.items} <= allowed
        assert all(item.status == "approved" for item in feed.items)
