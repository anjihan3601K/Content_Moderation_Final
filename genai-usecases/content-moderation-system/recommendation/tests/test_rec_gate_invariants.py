"""
Invariant tests for the gate over random profile/item combinations.

The oracle below restates the safety rules independently of the gate's code and is applied
to every item the gate lets through. Seeded, so a failure is reproducible.
"""

import random
from typing import Any, List, Optional

from recommendation.src.models import (
    AgeTier,
    AgeTrustLevel,
    AudienceRating,
    ParentalControls,
    RecommendationItemModel,
    ViewerProfileModel,
)
from recommendation.src.safety_gate import SafetyGate

SEED = 20261008
PROFILE_COUNT = 300
ITEMS_PER_PROFILE = 40  # 12,000 profile/item combinations

RANK = {"all_ages": 1, "teen": 2, "adult": 3, "blocked": 4}
TIER = {"child": 1, "teen": 2, "adult": 3}
ESCALATION_TERMS = ("violent_extremism", "terrorism", "grooming", "child_safety", "child_exploitation", "self_harm")

RATINGS: List[Any] = ["all_ages", "teen", "adult", "blocked", None, "", "garbage", "ALL_AGES", " teen "]
STATUSES: List[Any] = [
    "approved", "approved", "approved", "Approved", "removed", "warned", "flagged", "under_review",
    "pending_human_review", "pending_review", "submitted", "analyzing", "escalated",
    "human_review_completed", "user_banned", "user_suspended", "banned", "", None, "garbage",
]
LABELS = [
    "science", "nature", "cartoons", "gaming_family", "technology", "pop_culture", "coding",
    "mental_health", "dating_advice", "politics_intro", "general", "crime_documentary",
    "violent_extremism", "grooming", "self_harm", "Self-Harm Promotion", "child safety",
    "hate_speech", "spam", "sexual_content", "unknown label",
]
NUMBERS: List[Any] = [0.0, 0.05, 0.2, 0.3, 0.32, 0.4, 0.44, 0.45, 0.5, 0.7, 0.9, 1.0, None, float("nan"), "bad"]


def norm(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


SAFE_LABELS = ["science", "nature", "cartoons", "gaming_family", "technology", "pop_culture", "coding"]


def random_item(rng: random.Random, index: int) -> RecommendationItemModel:
    """Half the items are plausible moderated content, half are hostile or malformed."""
    if rng.random() < 0.5:
        return RecommendationItemModel(
            item_id=f"item-{index}",
            content_category=rng.choice(SAFE_LABELS),
            content_topics=rng.sample(SAFE_LABELS, rng.randint(0, 2)),
            audience_rating=rng.choice(["all_ages", "all_ages", "teen", "adult"]),
            toxicity_score=rng.choice([0.0, 0.05, 0.2]),
            overall_confidence=rng.choice([0.6, 0.75, 0.85, 0.9, 1.0]),
            agent_disagreement=rng.choice([0.0, 0.0, 0.2, 0.25, 0.33, 0.4, 0.5]),
            status=rng.choice(["approved", "approved", "approved", "flagged", "warned"]),
            is_borderline=rng.random() < 0.15,
        )
    return RecommendationItemModel(
        item_id=f"item-{index}",
        content_category=rng.choice(LABELS + [None]),
        content_topics=rng.sample(LABELS, rng.randint(0, 3)),
        policy_violations=rng.sample(LABELS, rng.randint(0, 2)) if rng.random() < 0.3 else [],
        audience_rating=rng.choice(RATINGS),
        toxicity_score=rng.choice([0.0, 0.2, 0.9, None]),
        overall_confidence=rng.choice(NUMBERS),
        agent_disagreement=rng.choice(NUMBERS),
        status=rng.choice(STATUSES),
        is_borderline=rng.random() < 0.2,
        escalated=rng.random() < 0.05,
    )


def random_profile(rng: random.Random, index: int) -> ViewerProfileModel:
    """Random profile, including interests and learned weights that point at risky topics."""
    return ViewerProfileModel(
        profile_id=f"profile-{index}",
        age_tier=rng.choice(list(AgeTier)),
        age_trust_level=rng.choice(list(AgeTrustLevel)),
        explicit_interests=rng.sample(LABELS, rng.randint(0, 5)),
        learned_interests={label: rng.random() for label in rng.sample(LABELS, rng.randint(0, 6))},
        recent_feed_history=[{"item_id": f"h{i}", "is_borderline": True} for i in range(rng.randint(0, 5))],
        parental_controls=ParentalControls(
            blocked_categories=rng.sample(LABELS, rng.randint(0, 2)) if rng.random() < 0.3 else [],
            strictness_level=rng.choice(["low", "medium", "strict"]),
            max_rating=rng.choice([None, None, "all_ages", "teen", "adult"]),
            allowed_sensitive_topics=rng.sample(["mental_health", "dating_advice", "politics_intro"], rng.randint(0, 2)),
        ),
    )


def violation(profile: ViewerProfileModel, item: RecommendationItemModel) -> Optional[str]:
    """Return why serving this item to this profile breaks a safety rule, or None."""
    tier = TIER[profile.age_tier.value]
    minor = tier < 3
    rating = item.audience_rating.value if item.audience_rating else None
    status = norm(item.status) if item.status else ""
    labels = [norm(x) for x in [item.content_category, *item.content_topics, *item.policy_violations] if x]

    if rating == "blocked" or status in {"removed", "banned", "user_banned", "user_suspended", "blocked"}:
        return "blocked item served"
    if rating is not None and RANK[rating] > tier:
        return "item above viewer tier served"
    if status not in {"approved", "warned"}:
        return "item with unservable status served"
    if {norm(c) for c in profile.parental_controls.blocked_categories} & set(labels):
        return "parentally blocked category served"
    cap = profile.parental_controls.max_rating
    if cap is not None and RANK[rating or "adult"] > RANK[cap.value]:
        return "item above parental rating cap served"
    if minor:
        if rating is None:
            return "unrated item served to a minor"
        if status != "approved":
            return "non-approved item served to a minor"
        if item.escalated or any(term in label for term in ESCALATION_TERMS for label in labels):
            return "escalation category served to a minor"
        if item.agent_disagreement is None or item.overall_confidence is None:
            return "item with missing confidence signals served to a minor"
        if not item.agent_disagreement < 0.45 or not item.overall_confidence >= 0.55:
            return "high-uncertainty item served to a minor"
        if profile.age_tier == AgeTier.CHILD and item.is_borderline:
            return "borderline item served to a child"
    return None


def test_no_unsafe_item_passes_the_gate_over_random_combinations():
    rng = random.Random(SEED)
    checked = passed = minor_passed = 0
    for p in range(PROFILE_COUNT):
        profile = random_profile(rng, p)
        pool = [random_item(rng, p * ITEMS_PER_PROFILE + i) for i in range(ITEMS_PER_PROFILE)]
        survivors, decisions = SafetyGate.filter_candidate_pool(profile, pool)
        assert len(decisions) == len(pool)
        for item in survivors:
            problem = violation(profile, item)
            assert problem is None, f"{problem}: profile={profile.model_dump()} item={item.model_dump()}"
            passed += 1
            minor_passed += profile.age_tier != AgeTier.ADULT
        checked += len(pool)

    assert checked >= 1000
    # Guard against a vacuous run in which nothing ever passes.
    assert passed > 100
    assert minor_passed > 20
    print(f"\ninvariant run: combinations={checked} passed={passed} passed_to_minors={minor_passed}")


def test_gate_decision_is_independent_of_personalization_inputs():
    rng = random.Random(SEED + 1)
    for index in range(1500):
        profile = random_profile(rng, index)
        item = random_item(rng, index)
        stripped = profile.model_copy(
            update={"explicit_interests": [], "learned_interests": {}, "recent_feed_history": []}
        )
        assert SafetyGate.evaluate_item(profile, item) == SafetyGate.evaluate_item(stripped, item)


def test_final_output_check_is_idempotent_and_never_adds_items():
    rng = random.Random(SEED + 2)
    for index in range(200):
        profile = random_profile(rng, index)
        pool = [random_item(rng, index * 20 + i) for i in range(20)]
        survivors, _ = SafetyGate.filter_candidate_pool(profile, pool)
        shuffled = list(pool)
        rng.shuffle(shuffled)
        final = SafetyGate.enforce_final_output(profile, shuffled)
        assert {i.item_id for i in final} == {i.item_id for i in survivors}
        assert SafetyGate.enforce_final_output(profile, final) == final


def test_blocked_and_adult_rated_items_never_reach_a_child_regardless_of_everything_else():
    rng = random.Random(SEED + 3)
    for index in range(2000):
        profile = random_profile(rng, index).model_copy(update={"age_tier": AgeTier.CHILD})
        item = random_item(rng, index).model_copy(
            update={"audience_rating": rng.choice([AudienceRating.TEEN, AudienceRating.ADULT, AudienceRating.BLOCKED])}
        )
        assert not SafetyGate.evaluate_item(profile, item).passed
