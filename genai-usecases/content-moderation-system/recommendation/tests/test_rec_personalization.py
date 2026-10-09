"""Stage 2: tier topic rules, embeddings, bandit, ranking, drift guard, diversity guard."""

import math
import random

import numpy as np
import pytest

from conftest import make_item, make_profile
from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.config import (
    ADULT_DIVERSITY_MIN,
    BORDERLINE_SHARE_CAP,
    CHILD_SAFE_TOPICS,
    LEARNED_DRIFT_LIMIT,
    TEEN_ALLOWED_TOPICS,
)
from recommendation.src.embeddings import TfidfEmbeddingProvider, cosine_scores, tokenize
from recommendation.src.models import AgeTier, AgeTrustLevel
from recommendation.src.personalization import (
    InterestNotAllowedError,
    ProfileRanker,
    TierTopicGuard,
    is_borderline_risk,
    item_topics,
    risk_trend_slope,
)
from recommendation.src.safety_gate import SafetyGate

ADULT = dict(tier=AgeTier.ADULT, trust=AgeTrustLevel.VERIFIED)


def topic_item(item_id, topic, **overrides):
    fields = dict(item_id=item_id, content_category=topic, content_topics=[topic],
                  content_text=f"Placeholder item {item_id} about {topic}.", audience_rating="adult")
    fields.update(overrides)
    return make_item(**fields)


# ─── explicit interests ─────────────────────────────────────────────────────────

def test_child_can_select_only_child_topics():
    child = make_profile(AgeTier.CHILD)
    assert TierTopicGuard.validate_explicit_interests(child, ["Science", "animals"]) == ["science", "animals"]
    with pytest.raises(InterestNotAllowedError) as error:
        TierTopicGuard.validate_explicit_interests(child, ["science", "technology", "violent_extremism", "dating"])
    assert error.value.rejected == ["technology", "violent_extremism", "dating"]


def test_teen_topic_list_is_wider_and_sensitive_topics_need_a_parent():
    teen = make_profile(AgeTier.TEEN)
    assert TierTopicGuard.validate_explicit_interests(teen, ["coding", "science"]) == ["coding", "science"]
    with pytest.raises(InterestNotAllowedError):
        TierTopicGuard.validate_explicit_interests(teen, ["mental_health"])
    with pytest.raises(InterestNotAllowedError):
        TierTopicGuard.validate_explicit_interests(teen, ["nightlife"])
    allowed = make_profile(AgeTier.TEEN, parental_controls={"allowed_sensitive_topics": ["mental_health"]})
    assert TierTopicGuard.validate_explicit_interests(allowed, ["mental_health"]) == ["mental_health"]


def test_parental_allowance_does_not_widen_a_childs_topic_list():
    child = make_profile(AgeTier.CHILD, parental_controls={"allowed_sensitive_topics": ["mental_health"]})
    assert TierTopicGuard.allowed_topics(child) == set(CHILD_SAFE_TOPICS)


def test_adult_has_free_choice_within_platform_rules():
    adult = make_profile(**ADULT)
    assert TierTopicGuard.validate_explicit_interests(adult, ["nightlife", "Finance"]) == ["nightlife", "finance"]
    for topic in ["violent_extremism", "grooming", "self-harm promotion", ""]:
        with pytest.raises(InterestNotAllowedError):
            TierTopicGuard.validate_explicit_interests(adult, [topic])


@pytest.mark.parametrize("tier", list(AgeTier))
def test_parentally_blocked_topic_cannot_be_an_interest(tier):
    profile = make_profile(tier, parental_controls={"blocked_categories": ["gaming"]})
    with pytest.raises(InterestNotAllowedError):
        TierTopicGuard.validate_explicit_interests(profile, ["gaming_family"])


def test_interests_are_deduplicated_and_capped():
    adult = make_profile(**ADULT)
    assert TierTopicGuard.validate_explicit_interests(adult, ["News", "news", " news "]) == ["news"]
    with pytest.raises(InterestNotAllowedError):
        TierTopicGuard.validate_explicit_interests(adult, [f"topic{i}" for i in range(21)])


# ─── learned interests ──────────────────────────────────────────────────────────

def test_child_engagement_can_never_add_a_topic():
    child = make_profile(AgeTier.CHILD, explicit_interests=["science"])
    for topic in ["animals", "technology", "violent_extremism", "nightlife"]:
        for _ in range(50):
            child.learned_interests = TierTopicGuard.update_learned_interests(child, topic, 1.0)
    assert child.learned_interests == {}
    assert set(TierTopicGuard.interest_weights(child)) == {"science"}


def test_child_engagement_only_reweights_within_the_explicit_set():
    child = make_profile(AgeTier.CHILD, explicit_interests=["science", "animals"])
    for _ in range(30):
        child.learned_interests = TierTopicGuard.update_learned_interests(child, "science", -1.0)
    for _ in range(30):
        child.learned_interests = TierTopicGuard.update_learned_interests(child, "animals", 1.0)
    weights = TierTopicGuard.interest_weights(child)
    assert set(weights) == {"science", "animals"}
    assert weights["science"] == 0.1 and weights["animals"] == 1.0  # down-weighted, never above baseline


def test_hostile_stored_learned_interests_do_not_enter_a_childs_vector():
    child = make_profile(
        AgeTier.CHILD, explicit_interests=["science"],
        learned_interests={"violent_extremism": 1.0, "nightlife": 1.0, "technology": 1.0},
    )
    assert TierTopicGuard.interest_weights(child) == {"science": 1.0}


@pytest.mark.parametrize("tier, pool", [(AgeTier.TEEN, TEEN_ALLOWED_TOPICS), (AgeTier.ADULT, [f"topic{i}" for i in range(30)])])
def test_learned_drift_from_the_explicit_set_is_capped(tier, pool):
    profile = make_profile(tier, AgeTrustLevel.VERIFIED, explicit_interests=[pool[0]])
    for topic in pool:
        profile.learned_interests = TierTopicGuard.update_learned_interests(profile, topic, 1.0)
    learned_only = [t for t in profile.learned_interests if t != pool[0]]
    assert len(learned_only) == LEARNED_DRIFT_LIMIT[tier.value]


def test_teen_engagement_with_a_disallowed_topic_is_ignored():
    teen = make_profile(AgeTier.TEEN, explicit_interests=["coding"])
    for topic in ["nightlife", "mental_health", "grooming"]:
        teen.learned_interests = TierTopicGuard.update_learned_interests(teen, topic, 1.0)
    assert teen.learned_interests == {}


def test_teen_and_adult_blend_explicit_and_learned():
    teen = make_profile(AgeTier.TEEN, explicit_interests=["coding"], learned_interests={"coding": 1.0, "art": 0.5})
    weights = TierTopicGuard.interest_weights(teen)
    assert weights["coding"] == pytest.approx(1.0) and weights["art"] == pytest.approx(0.2)
    adult = make_profile(**ADULT, explicit_interests=["news"], learned_interests={"finance": 0.6})
    weights = TierTopicGuard.interest_weights(adult)
    assert weights["news"] == pytest.approx(0.5) and weights["finance"] == pytest.approx(0.3)


def test_weights_stay_in_range():
    adult = make_profile(**ADULT, explicit_interests=["news"])
    for _ in range(100):
        adult.learned_interests = TierTopicGuard.update_learned_interests(adult, "news", 1.0)
    assert adult.learned_interests["news"] == 1.0
    for _ in range(100):
        adult.learned_interests = TierTopicGuard.update_learned_interests(adult, "news", -1.0)
    assert adult.learned_interests["news"] == 0.0


# ─── embeddings ─────────────────────────────────────────────────────────────────

def test_tokenize_splits_labels():
    assert tokenize("Gaming_Family & Pop-Culture 101") == ["gaming", "family", "pop", "culture", "101"]


def test_tfidf_ranks_matching_text_first_and_is_deterministic():
    texts = ["science nature experiments", "sports football league", "science chemistry lab"]
    provider = TfidfEmbeddingProvider()
    provider.fit(texts + ["science"])
    matrix = provider.embed(texts)
    scores = cosine_scores(provider.embed(["science"])[0], matrix)
    assert scores[0] > scores[1] and scores[2] > scores[1] and scores[1] == 0.0
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)
    again = TfidfEmbeddingProvider()
    again.fit(texts + ["science"])
    assert np.array_equal(again.embed(texts), matrix)


def test_unknown_or_empty_text_has_zero_similarity():
    provider = TfidfEmbeddingProvider()
    provider.fit(["science nature"])
    assert cosine_scores(provider.embed(["zzz"])[0], provider.embed(["science nature"])).tolist() == [0.0]
    assert cosine_scores(np.zeros(2), np.zeros((0, 2))).tolist() == []


# ─── bandit ─────────────────────────────────────────────────────────────────────

def test_bandit_learns_from_rewards():
    bandit = ThompsonSamplingBandit(seed=1)
    assert bandit.mean("a") == 0.5
    for _ in range(20):
        bandit.update("a", 1.0)
        bandit.update("b", -1.0)
    assert bandit.mean("a") > 0.9 and bandit.mean("b") < 0.1
    samples_a = [bandit.sample("a") for _ in range(200)]
    samples_b = [bandit.sample("b") for _ in range(200)]
    assert sum(samples_a) / 200 > sum(samples_b) / 200 + 0.5


def test_bandit_is_seeded_and_clips_rewards():
    first, second = ThompsonSamplingBandit(seed=7), ThompsonSamplingBandit(seed=7)
    assert [first.sample("x") for _ in range(5)] == [second.sample("x") for _ in range(5)]
    first.update("x", 50.0)
    assert first.arms["x"] == {"alpha": 2.0, "beta": 1.0}
    first.update("x", 0.0)
    assert first.arms["x"] == {"alpha": 2.0, "beta": 1.0}


def test_bandit_persists_through_the_callback_and_reloads(sqlite_repository):
    bandit = ThompsonSamplingBandit(seed=1, on_update=sqlite_repository.save_bandit_arm)
    bandit.update("teen:coding", 1.0)
    bandit.update("teen:coding", -0.5)
    reloaded = ThompsonSamplingBandit(seed=1, arms=sqlite_repository.load_bandit_arms())
    assert reloaded.arms == {"teen:coding": {"alpha": 2.0, "beta": 1.5}}


def test_child_gets_no_exploration_boost_outside_the_explicit_set():
    bandit = ThompsonSamplingBandit(seed=1)
    for _ in range(100):
        bandit.update("child:animals", 1.0)
    ranker = ProfileRanker(bandit=bandit)
    child = make_profile(AgeTier.CHILD, explicit_interests=["science"])
    assert ranker._bandit_score(child, topic_item("a", "animals", audience_rating="all_ages")) == 0.0
    assert ranker._bandit_score(child, topic_item("s", "science", audience_rating="all_ages")) > 0.0


# ─── ranking ────────────────────────────────────────────────────────────────────

def test_ranker_only_reorders_and_trims_its_input():
    rng = random.Random(3)
    profile = make_profile(**ADULT, explicit_interests=["news"])
    for _ in range(50):
        pool = [topic_item(f"i{n}", rng.choice(["news", "finance", "sports", "art"])) for n in range(rng.randint(0, 40))]
        limit = rng.randint(1, 15)
        ranked = ProfileRanker(bandit=ThompsonSamplingBandit(seed=rng.randint(0, 999))).rank_items(profile, pool, limit)
        ids = [item.item_id for item in ranked]
        assert len(ids) == len(set(ids)) == min(limit, len(pool))
        assert set(ids) <= {item.item_id for item in pool}


def test_ranker_handles_empty_input_and_no_interests():
    profile = make_profile(**ADULT)
    assert ProfileRanker().rank_items(profile, [], 10) == []
    assert len(ProfileRanker().rank_items(profile, [topic_item("a", "news")], 10)) == 1
    assert ProfileRanker().rank_items(profile, [topic_item("a", "news")], 0) == []


def test_relevant_items_rank_first_without_the_bandit():
    profile = make_profile(AgeTier.TEEN, explicit_interests=["coding"])
    pool = [topic_item(f"s{n}", "sports", audience_rating="teen") for n in range(5)]
    pool += [topic_item(f"c{n}", "coding", audience_rating="teen") for n in range(3)]
    ranked = ProfileRanker(use_bandit=False).rank_items(profile, pool, 8)
    assert {item.item_id for item in ranked[:3]} == {"c0", "c1", "c2"}


def precision_at_k(profile_record, feed, k=10):
    interests = set(profile_record.explicit_interests)
    return sum(1 for item in feed[:k] if interests & set(item_topics(item))) / k


def test_personalization_beats_a_random_baseline_on_mock_data(mock_repository):
    from gate_harness import load_dataset

    items = mock_repository.list_items()
    rng = random.Random(11)
    ranked_scores, random_scores = [], []
    for record in load_dataset("profiles"):
        profile = mock_repository.get_profile(record["profile_id"])
        survivors, _ = SafetyGate.filter_candidate_pool(profile, items)
        if len(survivors) < 20:
            continue
        feed = ProfileRanker(bandit=ThompsonSamplingBandit(seed=5)).rank_items(profile, survivors, 10)
        ranked_scores.append(precision_at_k(profile, feed))
        random_scores.append(precision_at_k(profile, rng.sample(survivors, 10)))
    assert len(ranked_scores) >= 60
    mean_ranked = sum(ranked_scores) / len(ranked_scores)
    mean_random = sum(random_scores) / len(random_scores)
    print(f"\nprecision@10 ranked={mean_ranked:.3f} random={mean_random:.3f} profiles={len(ranked_scores)}")
    assert mean_ranked > mean_random + 0.2


# ─── drift guard ────────────────────────────────────────────────────────────────

def borderline_item(item_id, topic="coding"):
    return topic_item(item_id, topic, audience_rating="teen", toxicity_score=0.3, is_borderline=True)


def test_borderline_risk_definition():
    assert is_borderline_risk(borderline_item("b"))
    assert is_borderline_risk(topic_item("t", "news", toxicity_score=0.25))
    assert not is_borderline_risk(topic_item("c", "news", toxicity_score=0.24))


@pytest.mark.parametrize("tier", [AgeTier.TEEN, AgeTier.ADULT])
def test_drift_guard_caps_the_borderline_share(tier):
    profile = make_profile(tier, AgeTrustLevel.VERIFIED, explicit_interests=["coding"])
    pool = [borderline_item(f"b{n}") for n in range(30)] + [
        topic_item(f"c{n}", "sports", audience_rating="teen") for n in range(30)
    ]
    feed = ProfileRanker(use_bandit=False).rank_items(profile, pool, 10)
    borderline = sum(1 for item in feed if is_borderline_risk(item))
    assert len(feed) == 10
    assert borderline == math.floor(10 * BORDERLINE_SHARE_CAP[tier.value])
    assert borderline >= 1  # the guard caps, it does not ban


def test_drift_guard_counts_the_recent_feed_history():
    saturated = [{"item_id": f"h{n}", "borderline": True, "risk": 0.3} for n in range(20)]
    profile = make_profile(AgeTier.TEEN, explicit_interests=["coding"], recent_feed_history=saturated)
    pool = [borderline_item(f"b{n}") for n in range(10)] + [
        topic_item(f"c{n}", "sports", audience_rating="teen") for n in range(10)
    ]
    feed = ProfileRanker(use_bandit=False).rank_items(profile, pool, 10)
    assert len(feed) == 10 and not any(is_borderline_risk(item) for item in feed)


def test_borderline_only_pool_yields_a_short_feed_rather_than_breaking_the_cap():
    profile = make_profile(AgeTier.TEEN, explicit_interests=["coding"])
    feed = ProfileRanker(use_bandit=False).rank_items(profile, [borderline_item(f"b{n}") for n in range(20)], 10)
    assert len(feed) == 1


def test_risk_trend_slope():
    assert risk_trend_slope([{"risk": 0.1}] * 3) == 0.0
    assert risk_trend_slope([{"risk": r / 10} for r in range(8)]) == pytest.approx(0.1)
    assert risk_trend_slope([{"risk": 0.2}] * 10) == 0.0
    assert risk_trend_slope([{"risk": r / 10} for r in range(8, 0, -1)]) < 0.0


def test_rising_risk_trend_penalises_riskier_items():
    pool = [topic_item("risky", "news", toxicity_score=0.2), topic_item("calm", "news", toxicity_score=0.0)]
    flat = make_profile(**ADULT, explicit_interests=["news"],
                        recent_feed_history=[{"item_id": str(n), "risk": 0.05} for n in range(10)])
    rising = make_profile(**ADULT, explicit_interests=["news"],
                          recent_feed_history=[{"item_id": str(n), "risk": n * 0.015} for n in range(10)])
    ranker = ProfileRanker(use_bandit=False)
    # Without a trend the two tie on relevance and the id breaks the tie.
    assert [i.item_id for i in ranker.rank_items(flat, pool, 2)] == ["calm", "risky"]
    pool_reversed = [topic_item("a_risky", "news", toxicity_score=0.2), topic_item("b_calm", "news", toxicity_score=0.0)]
    assert [i.item_id for i in ranker.rank_items(flat, pool_reversed, 2)] == ["a_risky", "b_calm"]
    assert [i.item_id for i in ranker.rank_items(rising, pool_reversed, 2)] == ["b_calm", "a_risky"]


# ─── adult diversity guard ──────────────────────────────────────────────────────

def test_adult_feed_reserves_room_for_topics_outside_the_interests():
    profile = make_profile(**ADULT, explicit_interests=["news"])
    pool = [topic_item(f"n{n}", "news") for n in range(40)] + [topic_item(f"o{n}", "gardening") for n in range(10)]
    feed = ProfileRanker(use_bandit=False).rank_items(profile, pool, 10)
    exploratory = sum(1 for item in feed if "news" not in item_topics(item))
    assert len(feed) == 10
    assert exploratory == math.ceil(10 * ADULT_DIVERSITY_MIN)


def test_without_the_guard_the_same_pool_is_an_echo_chamber():
    teen = make_profile(AgeTier.TEEN, explicit_interests=["coding"])
    pool = [topic_item(f"n{n}", "coding", audience_rating="teen") for n in range(40)]
    pool += [topic_item(f"o{n}", "sports", audience_rating="teen") for n in range(10)]
    feed = ProfileRanker(use_bandit=False).rank_items(teen, pool, 10)
    assert all("coding" in item_topics(item) for item in feed)


def test_diversity_guard_fills_the_feed_when_nothing_exploratory_exists():
    profile = make_profile(**ADULT, explicit_interests=["news"])
    feed = ProfileRanker(use_bandit=False).rank_items(profile, [topic_item(f"n{n}", "news") for n in range(40)], 10)
    assert len(feed) == 10
