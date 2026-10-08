"""Safety gate unit tests: rating-vs-tier matrix, margins, parental controls, escalation."""

import itertools
import logging

import pytest

from conftest import make_item, make_profile
from recommendation.src.models import (
    AgeTier,
    AgeTrustLevel,
    AudienceRating,
    GateReason,
    RecommendationItemModel,
)
from recommendation.src.safety_gate import SafetyGate, summarize_rejections

MINOR_TIERS = [AgeTier.CHILD, AgeTier.TEEN]
ALL_TIERS = list(AgeTier)
ALL_TRUST = list(AgeTrustLevel)

RATING_RANK = {AudienceRating.ALL_AGES: 1, AudienceRating.TEEN: 2, AudienceRating.ADULT: 3, AudienceRating.BLOCKED: 4}
TIER_RANK = {AgeTier.CHILD: 1, AgeTier.TEEN: 2, AgeTier.ADULT: 3}

# Every ContentStatus value the backend defines, except "approved".
NON_APPROVED_BACKEND_STATUSES = [
    "submitted", "analyzing", "toxicity_check", "policy_check", "react_synthesis",
    "reputation_scoring", "appeal_review", "action_enforcement", "removed", "warned",
    "flagged", "under_review", "pending_human_review", "human_review_completed", "escalated",
]


def decide(profile, item):
    return SafetyGate.evaluate_item(profile, item)


# ─── rating versus tier ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "rating, tier, trust", list(itertools.product(AudienceRating, ALL_TIERS, ALL_TRUST))
)
def test_rating_tier_matrix(rating, tier, trust):
    decision = decide(make_profile(tier, trust), make_item(audience_rating=rating))
    expected = RATING_RANK[rating] <= TIER_RANK[tier]
    assert decision.passed is expected
    if rating == AudienceRating.BLOCKED:
        assert decision.rejection_reason == GateReason.BLOCKED
    elif not expected:
        assert decision.rejection_reason == GateReason.ABOVE_TIER


@pytest.mark.parametrize("tier, trust", list(itertools.product(ALL_TIERS, ALL_TRUST)))
@pytest.mark.parametrize(
    "item_overrides",
    [
        {"audience_rating": AudienceRating.BLOCKED},
        {"audience_rating": "blocked"},
        {"status": "removed"},
        {"status": "user_banned"},
        {"status": "User-Suspended"},
        {"status": "banned"},
    ],
)
def test_blocked_is_never_served(tier, trust, item_overrides):
    decision = decide(make_profile(tier, trust), make_item(**item_overrides))
    assert not decision.passed
    assert decision.rejection_reason == GateReason.BLOCKED


# ─── unrated legacy items ───────────────────────────────────────────────────────

@pytest.mark.parametrize("tier, trust", list(itertools.product(MINOR_TIERS, ALL_TRUST)))
@pytest.mark.parametrize("rating", [None, "", "unknown_rating", "PG-13"])
def test_unrated_is_withheld_from_minors(tier, trust, rating):
    decision = decide(make_profile(tier, trust), make_item(audience_rating=rating))
    assert not decision.passed
    assert decision.rejection_reason == GateReason.UNRATED


def test_unrated_is_withheld_from_self_declared_adult():
    decision = decide(
        make_profile(AgeTier.ADULT, AgeTrustLevel.SELF_DECLARED), make_item(audience_rating=None)
    )
    assert decision.rejection_reason == GateReason.UNRATED


@pytest.mark.parametrize("trust", [AgeTrustLevel.PARENT_LINKED, AgeTrustLevel.VERIFIED])
def test_unrated_is_treated_as_adult_for_trusted_adult(trust):
    assert decide(make_profile(AgeTier.ADULT, trust), make_item(audience_rating=None)).passed


def test_unrated_respects_parental_rating_cap():
    profile = make_profile(
        AgeTier.ADULT, AgeTrustLevel.VERIFIED, parental_controls={"max_rating": "teen"}
    )
    decision = decide(profile, make_item(audience_rating=None))
    assert decision.rejection_reason == GateReason.PARENTAL_BLOCK


# ─── status ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier, trust", list(itertools.product(MINOR_TIERS, ALL_TRUST)))
@pytest.mark.parametrize("status", NON_APPROVED_BACKEND_STATUSES + ["pending_review", "made_up", "", None])
def test_only_approved_status_reaches_minors(tier, trust, status):
    assert not decide(make_profile(tier, trust), make_item(status=status)).passed


@pytest.mark.parametrize("status", ["flagged", "under_review", "pending_human_review", "pending_review"])
@pytest.mark.parametrize("tier", MINOR_TIERS)
def test_pending_and_flagged_reason_for_minors(tier, status):
    assert decide(make_profile(tier), make_item(status=status)).rejection_reason == GateReason.PENDING_REVIEW


@pytest.mark.parametrize("status", ["submitted", "analyzing", "flagged", "escalated", "made_up", "", None])
@pytest.mark.parametrize("trust", ALL_TRUST)
def test_unmoderated_or_unknown_status_is_not_served_to_adults(status, trust):
    decision = decide(make_profile(AgeTier.ADULT, trust), make_item(status=status))
    assert decision.rejection_reason == GateReason.NOT_SERVABLE_STATUS


def test_warned_item_only_for_trusted_adults():
    item = make_item(status="warned", audience_rating=AudienceRating.ADULT)
    assert decide(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED), item).passed
    self_declared = decide(make_profile(AgeTier.ADULT, AgeTrustLevel.SELF_DECLARED), item)
    assert self_declared.rejection_reason == GateReason.PENDING_REVIEW


# ─── uncertainty margin ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier, trust", list(itertools.product(MINOR_TIERS, ALL_TRUST)))
@pytest.mark.parametrize(
    "signals",
    [{"agent_disagreement": 0.45}, {"agent_disagreement": 0.9}, {"overall_confidence": 0.3}],
)
def test_high_uncertainty_is_excluded_for_minors(tier, trust, signals):
    decision = decide(make_profile(tier, trust), make_item(**signals))
    assert decision.rejection_reason == GateReason.HIGH_UNCERTAINTY
    assert decision.safety_margin_applied


@pytest.mark.parametrize("tier", MINOR_TIERS)
@pytest.mark.parametrize(
    "signals",
    [
        {"agent_disagreement": None},
        {"overall_confidence": None},
        {"agent_disagreement": float("nan")},
        {"overall_confidence": float("nan")},
        {"agent_disagreement": "n/a"},
    ],
)
def test_missing_signals_are_excluded_for_minors(tier, signals):
    assert decide(make_profile(tier), make_item(**signals)).rejection_reason == GateReason.MISSING_SIGNALS


def test_trusted_adult_is_not_subject_to_the_margin():
    item = make_item(audience_rating=AudienceRating.ADULT, agent_disagreement=0.9, overall_confidence=None)
    decision = decide(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED), item)
    assert decision.passed
    assert not decision.safety_margin_applied


def test_self_declared_adult_is_subject_to_the_margin():
    item = make_item(audience_rating=AudienceRating.ADULT, agent_disagreement=0.9)
    decision = decide(make_profile(AgeTier.ADULT, AgeTrustLevel.SELF_DECLARED), item)
    assert decision.rejection_reason == GateReason.HIGH_UNCERTAINTY


def test_lower_trust_makes_the_gate_stricter():
    item = make_item(agent_disagreement=0.33)
    assert decide(make_profile(AgeTier.TEEN, AgeTrustLevel.VERIFIED), item).passed
    assert decide(make_profile(AgeTier.TEEN, AgeTrustLevel.PARENT_LINKED), item).passed
    assert not decide(make_profile(AgeTier.TEEN, AgeTrustLevel.SELF_DECLARED), item).passed
    thresholds = [
        SafetyGate.uncertainty_threshold(make_profile(AgeTier.TEEN, trust))
        for trust in (AgeTrustLevel.SELF_DECLARED, AgeTrustLevel.PARENT_LINKED, AgeTrustLevel.VERIFIED)
    ]
    assert thresholds == sorted(thresholds) and len(set(thresholds)) == 3


def test_strict_parental_setting_makes_the_gate_stricter():
    item = make_item(agent_disagreement=0.3)
    assert decide(make_profile(AgeTier.TEEN, parental_controls={"strictness_level": "low"}), item).passed
    strict = decide(make_profile(AgeTier.TEEN, parental_controls={"strictness_level": "strict"}), item)
    assert strict.rejection_reason == GateReason.HIGH_UNCERTAINTY


def test_threshold_never_exceeds_the_ceiling():
    from recommendation.src.config import HIGH_UNCERTAINTY_CEILING

    for tier, trust, strictness in itertools.product(ALL_TIERS, ALL_TRUST, ["low", "medium", "strict"]):
        profile = make_profile(tier, trust, parental_controls={"strictness_level": strictness})
        assert SafetyGate.uncertainty_threshold(profile) <= HIGH_UNCERTAINTY_CEILING


# ─── parental controls ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", ALL_TIERS)
@pytest.mark.parametrize(
    "item_overrides",
    [
        {"content_category": "gaming_family"},
        {"content_topics": ["science", "Gaming Family"]},
        {"policy_violations": ["gaming-family"]},
    ],
)
def test_parental_block_matches_category_topic_and_violation(tier, item_overrides):
    profile = make_profile(tier, parental_controls={"blocked_categories": ["Gaming_Family"]})
    assert decide(profile, make_item(**item_overrides)).rejection_reason == GateReason.PARENTAL_BLOCK


@pytest.mark.parametrize("label", ["gaming_family", "gaming-general", "video gaming", "Gaming"])
def test_parental_block_matches_whole_words_inside_labels(label):
    profile = make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED, parental_controls={"blocked_categories": ["gaming"]})
    item = make_item(content_topics=[label], audience_rating="adult")
    assert decide(profile, item).rejection_reason == GateReason.PARENTAL_BLOCK


@pytest.mark.parametrize("entry", ["SPORTS\u200b\u0430", "anim\u0430ls", "", "  "])
def test_parental_labels_reject_lookalike_or_empty_text(entry):
    with pytest.raises(ValueError):
        make_profile(AgeTier.CHILD, parental_controls={"blocked_categories": [entry]})


def test_no_parental_setting_is_looser_than_the_default():
    default = SafetyGate.uncertainty_threshold(make_profile(AgeTier.CHILD))
    for strictness in ["low", "medium", "strict"]:
        profile = make_profile(AgeTier.CHILD, parental_controls={"strictness_level": strictness})
        assert SafetyGate.uncertainty_threshold(profile) <= default


def test_parental_rating_cap():
    profile = make_profile(AgeTier.TEEN, parental_controls={"max_rating": "all_ages"})
    assert decide(profile, make_item(audience_rating="all_ages")).passed
    assert decide(profile, make_item(audience_rating="teen")).rejection_reason == GateReason.PARENTAL_BLOCK


def test_parental_cap_cannot_raise_the_tier():
    profile = make_profile(AgeTier.CHILD, parental_controls={"max_rating": "adult"})
    assert decide(profile, make_item(audience_rating="teen")).rejection_reason == GateReason.ABOVE_TIER
    assert decide(profile, make_item(audience_rating="adult")).rejection_reason == GateReason.ABOVE_TIER


# ─── escalation, sensitive topics, borderline ───────────────────────────────────

@pytest.mark.parametrize("tier, trust", list(itertools.product(MINOR_TIERS, ALL_TRUST)))
@pytest.mark.parametrize(
    "item_overrides",
    [
        {"content_category": "violent_extremism"},
        {"content_topics": ["science", "grooming"]},
        {"policy_violations": ["self_harm"]},
        {"policy_violations": ["Self-Harm Promotion"]},
        {"content_topics": ["child safety"]},
        {"escalated": True},
    ],
)
def test_escalation_hidden_from_minors_even_if_rated_all_ages(tier, trust, item_overrides):
    decision = decide(make_profile(tier, trust), make_item(**item_overrides))
    assert decision.rejection_reason == GateReason.ESCALATION


@pytest.mark.parametrize(
    "label",
    ["selfharm", "self  harm", "suicide", "extremism", "terrorist", "groomer", "csam",
     "g r o o m i n g", "GROOM\u0130NG", "gr\u043eoming", "eating disorder", "radicalization"],
)
@pytest.mark.parametrize("field", ["content_category", "content_topics", "policy_violations"])
@pytest.mark.parametrize("tier", MINOR_TIERS)
def test_escalation_spelling_variants_never_reach_minors(tier, field, label):
    value = label if field == "content_category" else [label]
    assert not decide(make_profile(tier), make_item(**{field: value})).passed


@pytest.mark.parametrize("tier", MINOR_TIERS)
@pytest.mark.parametrize("label", ["general", "crime_documentary", "unknown", "dating", "mental  health x"])
def test_minors_only_get_allow_listed_topics_whatever_the_rating(tier, label):
    decision = decide(make_profile(tier), make_item(content_topics=[label]))
    assert decision.rejection_reason == GateReason.UNLISTED_TOPIC


@pytest.mark.parametrize("tier", MINOR_TIERS)
def test_minors_need_at_least_one_topic(tier):
    item = make_item(content_category=None, content_topics=[])
    assert decide(make_profile(tier), item).rejection_reason == GateReason.UNLISTED_TOPIC


def test_child_gets_only_child_topics_even_if_rated_all_ages():
    item = make_item(content_category="technology", content_topics=[])
    assert decide(make_profile(AgeTier.CHILD), item).rejection_reason == GateReason.UNLISTED_TOPIC
    assert decide(make_profile(AgeTier.TEEN), item).passed


def test_policy_violations_are_checked_independently_of_the_rating():
    hate = make_item(policy_violations=["hate_speech"])
    spam = make_item(policy_violations=["spam"])
    assert decide(make_profile(AgeTier.CHILD), hate).rejection_reason == GateReason.POLICY_VIOLATION
    assert decide(make_profile(AgeTier.TEEN), hate).rejection_reason == GateReason.POLICY_VIOLATION
    assert decide(make_profile(AgeTier.CHILD), spam).rejection_reason == GateReason.POLICY_VIOLATION
    assert decide(make_profile(AgeTier.TEEN), spam).passed


# ─── unvalidated changes to models (review 1) ───────────────────────────────────

@pytest.mark.parametrize(
    "update",
    [
        {"audience_rating": "all_ages"},
        {"content_topics": "self_harm"},
        {"agent_disagreement": -5},
        {"overall_confidence": float("inf")},
        {"policy_violations": None},
    ],
)
def test_model_copy_cannot_smuggle_an_unchecked_item_past_the_gate(update):
    base = make_item(audience_rating="adult", content_topics=["grooming"], agent_disagreement=0.9)
    assert not decide(make_profile(AgeTier.CHILD), base.model_copy(update=update)).passed


@pytest.mark.parametrize("trust", [None, "garbage", "SELF_DECLARED", ""])
def test_unknown_trust_level_never_loosens_the_gate(trust):
    profile = make_profile(AgeTier.ADULT, AgeTrustLevel.SELF_DECLARED).model_copy(update={"age_trust_level": trust})
    item = make_item(audience_rating=None, status="warned", overall_confidence=None)
    assert not decide(profile, item).passed


@pytest.mark.parametrize(
    "update",
    [{"parental_controls": None}, {"age_tier": "toddler"}, {"age_tier": None}],
)
def test_invalid_profile_is_served_nothing(update):
    profile = make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED).model_copy(update=update)
    assert decide(profile, make_item()).rejection_reason == GateReason.INVALID


def test_assignment_is_validated():
    item = make_item()
    with pytest.raises(ValueError):
        item.agent_disagreement = 7
    item.audience_rating = "not a rating"
    assert item.audience_rating is None


def test_sensitive_teen_topic_needs_parental_allowance():
    item = make_item(audience_rating="teen", content_category="mental_health", content_topics=[])
    assert decide(make_profile(AgeTier.TEEN), item).rejection_reason == GateReason.SENSITIVE_TOPIC
    allowed = make_profile(AgeTier.TEEN, parental_controls={"allowed_sensitive_topics": ["mental_health"]})
    assert decide(allowed, item).passed
    assert decide(make_profile(AgeTier.ADULT, AgeTrustLevel.VERIFIED), item).passed


def test_parental_allowance_cannot_lift_a_child_above_tier():
    item = make_item(audience_rating="teen", content_category="mental_health", content_topics=[])
    profile = make_profile(AgeTier.CHILD, parental_controls={"allowed_sensitive_topics": ["mental_health"]})
    assert decide(profile, item).rejection_reason == GateReason.ABOVE_TIER


def test_borderline_never_reaches_a_child():
    item = make_item(is_borderline=True)
    assert decide(make_profile(AgeTier.CHILD), item).rejection_reason == GateReason.BORDERLINE
    assert decide(make_profile(AgeTier.TEEN), item).passed
    strict_teen = make_profile(AgeTier.TEEN, parental_controls={"strictness_level": "strict"})
    assert decide(strict_teen, item).rejection_reason == GateReason.BORDERLINE


# ─── pool filtering and the final check ─────────────────────────────────────────

def test_filter_candidate_pool_returns_survivors_and_full_audit():
    profile = make_profile(AgeTier.CHILD)
    pool = [
        make_item(item_id="ok"),
        make_item(item_id="teen", audience_rating="teen"),
        make_item(item_id="blocked", audience_rating="blocked"),
        make_item(item_id="pending", status="flagged"),
    ]
    survivors, decisions = SafetyGate.filter_candidate_pool(profile, pool)
    assert [i.item_id for i in survivors] == ["ok"]
    assert len(decisions) == 4
    assert summarize_rejections(decisions) == {"above_tier": 1, "blocked": 1, "pending_review": 1}


def test_final_check_drops_an_item_injected_after_the_gate(caplog):
    profile = make_profile(AgeTier.TEEN)
    injected = make_item(item_id="injected", audience_rating="adult")
    with caplog.at_level(logging.ERROR):
        output = SafetyGate.enforce_final_output(profile, [make_item(item_id="ok"), injected])
    assert [i.item_id for i in output] == ["ok"]
    assert "gate_final_check_dropped" in caplog.text


def test_final_check_catches_an_item_mutated_after_the_gate():
    profile = make_profile(AgeTier.CHILD)
    item = make_item()
    survivors, _ = SafetyGate.filter_candidate_pool(profile, [item])
    survivors[0].audience_rating = AudienceRating.ADULT
    assert SafetyGate.enforce_final_output(profile, survivors) == []


def test_gate_ignores_interests_learned_signals_and_history():
    item = make_item(audience_rating="teen")
    plain = make_profile(AgeTier.CHILD)
    loaded = make_profile(
        AgeTier.CHILD,
        explicit_interests=["violent_extremism", "adult"],
        learned_interests={"adult": 1.0, "teen": 1.0},
        recent_feed_history=[{"item_id": "x", "audience_rating": "adult"}] * 50,
    )
    assert decide(plain, item) == decide(loaded, item)
    assert not decide(loaded, item).passed


def test_item_defaults_are_unknown_not_safe():
    bare = RecommendationItemModel(item_id="bare")
    for tier, trust in itertools.product(ALL_TIERS, ALL_TRUST):
        assert not decide(make_profile(tier, trust), bare).passed


# ─── review 2 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "blocked, topic",
    [("sport", "sports"), ("animal", "animals"), ("cartoon", "cartoons"), ("puzzle", "puzzles"),
     ("craft", "crafts"), ("game", "gaming_family"), ("games", "gaming_family"),
     ("kids music", "music_kids"), ("music for kids", "music_kids"), ("family gaming", "gaming_family")],
)
def test_parental_block_matches_plural_and_reordered_wording(blocked, topic):
    profile = make_profile(AgeTier.CHILD, parental_controls={"blocked_categories": [blocked]})
    item = make_item(content_category=topic, content_topics=[topic])
    assert decide(profile, item).rejection_reason == GateReason.PARENTAL_BLOCK


def test_parental_block_does_not_match_unrelated_topics():
    profile = make_profile(AgeTier.CHILD, parental_controls={"blocked_categories": ["gaming", "kids music"]})
    assert decide(profile, make_item()).passed
    assert decide(profile, make_item(content_category="music_kids", content_topics=[])).rejection_reason == GateReason.PARENTAL_BLOCK


@pytest.mark.parametrize("tier, toxicity, passes", [
    (AgeTier.CHILD, 0.0999, True), (AgeTier.CHILD, 0.10, False), (AgeTier.CHILD, 0.99, False),
    (AgeTier.CHILD, None, False), (AgeTier.TEEN, 0.3499, True), (AgeTier.TEEN, 0.35, False),
    (AgeTier.TEEN, 0.99, False), (AgeTier.TEEN, None, False),
])
def test_gate_checks_toxicity_itself_for_minors(tier, toxicity, passes):
    decision = decide(make_profile(tier), make_item(toxicity_score=toxicity))
    assert decision.passed is passes
    if not passes:
        assert decision.rejection_reason == GateReason.TOXICITY


@pytest.mark.parametrize("tier", MINOR_TIERS)
@pytest.mark.parametrize("overrides, reason", [
    ({"content_topics": ["science", ""]}, GateReason.UNLISTED_TOPIC),
    ({"content_category": ""}, GateReason.UNLISTED_TOPIC),
    ({"policy_violations": [""]}, GateReason.POLICY_VIOLATION),
])
def test_empty_labels_are_malformed_for_minors(tier, overrides, reason):
    assert decide(make_profile(tier), make_item(**overrides)).rejection_reason == reason


@pytest.mark.parametrize("tier", MINOR_TIERS)
@pytest.mark.parametrize("violations", [["none"], ["None."], ["No violation"]])
def test_no_violation_markers_are_not_violations(tier, violations):
    assert decide(make_profile(tier), make_item(policy_violations=violations)).passed


@pytest.mark.parametrize("status", ["!approved", "approved!", "(approved)", "approved\u200b", "!warned"])
@pytest.mark.parametrize("tier, trust", list(itertools.product(ALL_TIERS, ALL_TRUST)))
def test_status_must_match_exactly_for_everyone(tier, trust, status):
    assert not decide(make_profile(tier, trust), make_item(status=status, audience_rating="adult")).passed


@pytest.mark.parametrize("rating", ["all ages!", "all_ages?", "!teen"])
def test_punctuated_rating_is_unrated(rating):
    assert make_item(audience_rating=rating).audience_rating is None
