"""Audience rating derivation from pipeline state: deterministic and fail-closed."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

import pytest

from recommendation.src.models import AudienceRating
from recommendation.src.rating import (
    RATING_RANK,
    AgentSignals,
    apply_audience_rating,
    compute_agent_signals,
    derive_audience_rating,
    find_escalation_categories,
)


class _Decision(Enum):
    APPROVE = "approve"
    REMOVE = "remove"
    FLAG = "flag"


@dataclass
class _AgentDecision:
    """Stand-in with the same attributes as backend AgentDecision."""

    agent_name: str
    decision: Any
    confidence: float


def clean_state(**overrides: Any) -> Dict[str, Any]:
    state = dict(
        content_id="c1",
        status="approved",
        moderation_action="approved",
        toxicity_score=0.02,
        content_removed=False,
        policy_violations=[],
        policy_flags=[],
        violation_severity="none",
        contains_sensitive_content=False,
        explicit_content_detected=False,
        hate_speech_detected=False,
        harassment_detected=False,
        media_risk_level="none",
        content_category="science",
        content_topics=["nature"],
        agent_decisions=[
            _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.85),
            _AgentDecision("Toxicity Detection Agent", _Decision.APPROVE, 0.9),
            _AgentDecision("Policy Violation Agent", _Decision.APPROVE, 0.85),
        ],
    )
    state.update(overrides)
    return state


def rating_of(**overrides: Any) -> AudienceRating:
    return derive_audience_rating(clean_state(**overrides)).rating


def test_clean_approved_child_topic_is_all_ages():
    assert rating_of() == AudienceRating.ALL_AGES


def test_teen_topic_is_teen():
    assert rating_of(content_category="technology", content_topics=["coding"]) == AudienceRating.TEEN


def test_sensitive_teen_topic_is_teen():
    assert rating_of(content_category="mental_health", content_topics=[]) == AudienceRating.TEEN


@pytest.mark.parametrize("category", ["general", "crime_documentary", "something new", ""])
def test_unknown_or_missing_topic_is_adult(category):
    assert rating_of(content_category=category, content_topics=[]) == AudienceRating.ADULT


def test_one_unknown_topic_among_safe_ones_is_adult():
    assert rating_of(content_topics=["nature", "unlisted_topic"]) == AudienceRating.ADULT


@pytest.mark.parametrize(
    "status",
    ["submitted", "analyzing", "toxicity_check", "policy_check", "react_synthesis",
     "reputation_scoring", "appeal_review", "action_enforcement", "warned", "flagged",
     "under_review", "pending_human_review", "human_review_completed", "escalated",
     "made_up_status", "", None],
)
def test_any_status_other_than_approved_is_at_least_adult(status):
    assert RATING_RANK[rating_of(status=status)] >= RATING_RANK[AudienceRating.ADULT]


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "removed"},
        {"moderation_action": "user_banned"},
        {"moderation_action": "user_suspended"},
        {"content_removed": True},
        {"toxicity_score": 0.75},
    ],
)
def test_removed_or_sanctioned_is_blocked(overrides):
    assert rating_of(**overrides) == AudienceRating.BLOCKED


@pytest.mark.parametrize(
    "toxicity, expected",
    [(0.0, AudienceRating.ALL_AGES), (0.0999, AudienceRating.ALL_AGES),
     (0.10, AudienceRating.TEEN), (0.3499, AudienceRating.TEEN),
     (0.35, AudienceRating.ADULT), (0.7499, AudienceRating.ADULT),
     (0.75, AudienceRating.BLOCKED), (1.0, AudienceRating.BLOCKED)],
)
def test_toxicity_thresholds(toxicity, expected):
    assert rating_of(toxicity_score=toxicity) == expected


@pytest.mark.parametrize("toxicity", [None, "high", float("nan"), -0.1, 1.5])
def test_missing_or_invalid_toxicity_is_adult(toxicity):
    assert rating_of(toxicity_score=toxicity) == AudienceRating.ADULT


@pytest.mark.parametrize("violation", ["spam", "copyright"])
def test_tolerated_violation_is_teen(violation):
    assert rating_of(policy_violations=[violation]) == AudienceRating.TEEN


@pytest.mark.parametrize(
    "violation",
    ["hate_speech", "harassment", "bullying", "violence", "sexual_content", "misinformation",
     "illegal_activity", "impersonation", "privacy_violation", "never_seen_before"],
)
def test_other_or_unknown_violation_is_adult(violation):
    assert rating_of(policy_violations=[violation]) == AudienceRating.ADULT


def test_none_violation_label_is_ignored():
    assert rating_of(policy_violations=["none"]) == AudienceRating.ALL_AGES


@pytest.mark.parametrize(
    "severity, expected",
    [("low", AudienceRating.TEEN), ("medium", AudienceRating.ADULT),
     ("high", AudienceRating.ADULT), ("critical", AudienceRating.ADULT),
     ("unknown", AudienceRating.ADULT)],
)
def test_severity(severity, expected):
    assert rating_of(violation_severity=severity) == expected


@pytest.mark.parametrize(
    "flag",
    ["contains_sensitive_content", "explicit_content_detected", "hate_speech_detected", "harassment_detected"],
)
def test_sensitive_flags_are_adult(flag):
    assert rating_of(**{flag: True}) == AudienceRating.ADULT


def test_media_risk_is_adult():
    assert rating_of(media_risk_level="high") == AudienceRating.ADULT


@pytest.mark.parametrize(
    "label", ["violent_extremism", "grooming", "self_harm", "self-harm promotion", "Child Safety"]
)
def test_escalation_category_blocked_until_approved(label):
    pending = derive_audience_rating(clean_state(status="flagged", policy_violations=[label]))
    assert pending.rating == AudienceRating.BLOCKED
    assert pending.escalated

    approved = derive_audience_rating(clean_state(policy_violations=[label]))
    assert approved.rating == AudienceRating.ADULT
    assert approved.escalated


def test_escalation_found_in_category_and_topics():
    assert find_escalation_categories(["science", "Violent-Extremism news"]) == ("violent_extremism",)
    assert find_escalation_categories(["science", None]) == ()


def test_rating_is_deterministic():
    state = clean_state(policy_violations=["spam"], toxicity_score=0.2)
    assert derive_audience_rating(state) == derive_audience_rating(dict(state))


# ─── agent signals ──────────────────────────────────────────────────────────────

def test_unanimous_agents_have_zero_disagreement_and_min_confidence():
    assert compute_agent_signals(clean_state()["agent_decisions"]) == AgentSignals(0.0, 0.85, True)


def test_split_agents_disagree():
    decisions = [
        _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.85),
        _AgentDecision("Toxicity Detection Agent", _Decision.REMOVE, 0.9),
        _AgentDecision("Policy Violation Agent", _Decision.FLAG, 0.6),
    ]
    signals = compute_agent_signals(decisions)
    assert signals.disagreement == pytest.approx(0.6667, abs=1e-4)
    assert signals.confidence == 0.6
    assert not signals.all_allow


def test_bookkeeping_agents_do_not_hide_disagreement():
    decisions = [
        _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.85),
        _AgentDecision("Toxicity Detection Agent", _Decision.REMOVE, 0.9),
        _AgentDecision("Action Enforcement Agent", _Decision.APPROVE, 1.0),
        _AgentDecision("HITL Checkpoint Agent", _Decision.APPROVE, 1.0),
    ]
    assert compute_agent_signals(decisions) == AgentSignals(0.5, 0.85, False)


def test_dict_decisions_and_string_verdicts_are_read():
    decisions = [
        {"agent_name": "Content Analysis Agent", "decision": "approve", "confidence": 0.8},
        {"agent_name": "Policy Violation Agent", "decision": "warn", "confidence": 0.7},
    ]
    assert compute_agent_signals(decisions) == AgentSignals(0.5, 0.7, False)


def test_human_review_replaces_agent_verdicts():
    decisions = [
        _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.85),
        _AgentDecision("Toxicity Detection Agent", _Decision.REMOVE, 0.9),
        {"agent_name": "HITL Human Review", "decision": "human_approved", "confidence": 1.0},
    ]
    assert compute_agent_signals(decisions) == AgentSignals(0.0, 1.0, True)


def test_human_review_only_settles_things_when_it_is_last_and_allows():
    approve = _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.85)
    remove = _AgentDecision("Toxicity Detection Agent", _Decision.REMOVE, 0.99)
    human_allow = {"agent_name": "HITL Human Review", "decision": "human_approved", "confidence": 1.0}
    human_remove = {"agent_name": "HITL Human Review", "decision": "remove", "confidence": 1.0}

    overridden = compute_agent_signals([approve, human_allow, remove, remove])
    assert not overridden.all_allow and overridden.disagreement > 0.0
    assert not compute_agent_signals([approve, human_remove]).all_allow


@pytest.mark.parametrize("dissent", [_Decision.REMOVE, _Decision.FLAG, "warn", "ban_user"])
def test_any_dissenting_agent_keeps_an_approved_item_adult(dissent):
    decisions = clean_state()["agent_decisions"] + [_AgentDecision("Extra Agent", dissent, 0.99)]
    assert rating_of(agent_decisions=decisions) == AudienceRating.ADULT


def test_unanimous_remove_is_not_mistaken_for_agreement_to_serve():
    decisions = [_AgentDecision(f"Agent {i}", _Decision.REMOVE, 1.0) for i in range(3)]
    assert rating_of(agent_decisions=decisions) == AudienceRating.ADULT


def test_nameless_decision_is_unreadable():
    signals = compute_agent_signals([{"decision": "approve", "confidence": 1.0}])
    assert signals == AgentSignals(0.0, 0.0, False)


def test_unreadable_decision_counts_against_confidence():
    decisions = [
        _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.85),
        {"agent_name": "Toxicity Detection Agent", "decision": "???", "confidence": 0.9},
    ]
    assert compute_agent_signals(decisions) == AgentSignals(0.5, 0.0, False)


@pytest.mark.parametrize(
    "decisions",
    [None, [], "approve", {"a": 1}, 5, [_AgentDecision("Action Enforcement Agent", _Decision.APPROVE, 1.0)]],
)
def test_no_judging_decisions_means_unknown(decisions):
    assert compute_agent_signals(decisions) == AgentSignals(None, None, False)
    assert rating_of(agent_decisions=decisions) == AudienceRating.ADULT


# ─── missing or malformed signals never lower the rating (review 1) ─────────────

REQUIRED_FIELDS = [
    "moderation_action", "content_removed", "policy_violations", "policy_flags",
    "violation_severity", "contains_sensitive_content", "explicit_content_detected",
    "hate_speech_detected", "harassment_detected", "media_risk_level", "toxicity_score",
    "agent_decisions", "status",
]


@pytest.mark.parametrize("field_name", REQUIRED_FIELDS)
def test_deleting_any_signal_never_rates_below_adult(field_name):
    state = clean_state()
    del state[field_name]
    assert RATING_RANK[derive_audience_rating(state).rating] >= RATING_RANK[AudienceRating.ADULT]


@pytest.mark.parametrize("field_name", REQUIRED_FIELDS)
@pytest.mark.parametrize("bad_value", [None, "", 0, [None], {"type": "x"}, "garbage", 10**400])
def test_malformed_signal_never_rates_below_adult(field_name, bad_value):
    if field_name == "toxicity_score" and bad_value == 0:
        pytest.skip("0 is a valid toxicity score")
    state = clean_state(**{field_name: bad_value})
    assert RATING_RANK[derive_audience_rating(state).rating] >= RATING_RANK[AudienceRating.ADULT]


@pytest.mark.parametrize(
    "flags",
    [["sexual_content"], ["anything"], "self_harm", {"type": "self_harm"}, ["suicide"], [""]],
)
def test_any_policy_flag_keeps_the_item_from_minors(flags):
    assert RATING_RANK[rating_of(policy_flags=flags)] >= RATING_RANK[AudienceRating.ADULT]


@pytest.mark.parametrize("action", ["remove", "ban_user", "flagged", "warned", "Removed.", "approved."])
def test_moderation_action_must_be_exactly_approved(action):
    assert RATING_RANK[rating_of(moderation_action=action)] >= RATING_RANK[AudienceRating.ADULT]


@pytest.mark.parametrize(
    "label",
    ["selfharm", "self  harm", "self\tharm", "self\u2011harm", "self\u00a0harm", "self/harm",
     "suicide", "extremism", "violent extremist", "terrorist", "groomer", "csam",
     "child sexual abuse", "g r o o m i n g", "radicalization", "Self-Harm Promotion"],
)
def test_escalation_spelling_variants_are_caught(label):
    assert find_escalation_categories([label])
    assert derive_audience_rating(clean_state(status="flagged", policy_flags=[label])).rating == AudienceRating.BLOCKED


# ─── pipeline hook ──────────────────────────────────────────────────────────────

def test_apply_is_a_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("RECOMMENDATION_ENABLED", raising=False)
    state = clean_state()
    assert apply_audience_rating(state) is None
    assert "audience_rating" not in state
    assert "agent_disagreement" not in state


def test_apply_writes_rating_when_flag_on(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    state = clean_state(content_topics=["coding"])
    result = apply_audience_rating(state)
    assert result is not None
    assert state["audience_rating"] == "teen"
    assert state["agent_disagreement"] == 0.0


# ─── review 2 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "category", [None, "", 0, False, [], {}, 5, True, ["violence"], {"name": "violence"}, b"violence"]
)
def test_missing_or_malformed_category_never_rates_below_adult(category):
    assert RATING_RANK[rating_of(content_category=category, content_topics=["education"])] >= 3
    state = clean_state(content_topics=["education"])
    del state["content_category"]
    assert RATING_RANK[derive_audience_rating(state).rating] >= 3


@pytest.mark.parametrize(
    "name, verdict",
    [("Action Enforcement Agent", "remove"), ("Action Enforcement Agent", "needs_review"),
     ("HITL Checkpoint Agent", "await_human"), ("(hitl) checkpoint: agent", "remove")],
)
def test_bookkeeping_agents_are_counted_when_they_do_not_approve(name, verdict):
    decisions = [
        _AgentDecision("Content Analysis Agent", _Decision.APPROVE, 0.9),
        {"agent_name": name, "decision": verdict, "confidence": 1.0},
    ]
    signals = compute_agent_signals(decisions)
    assert not signals.all_allow and signals.disagreement == 0.5
    assert rating_of(agent_decisions=decisions) == AudienceRating.ADULT


@pytest.mark.parametrize(
    "overrides",
    [{"violation_severity": "!none"}, {"violation_severity": "none?"}, {"media_risk_level": "!safe"},
     {"media_risk_level": "safe?"}, {"status": "!approved"}, {"moderation_action": "(approved)"}],
)
def test_punctuated_enum_values_are_not_read_as_the_safe_value(overrides):
    assert RATING_RANK[rating_of(**overrides)] >= 3


@pytest.mark.parametrize("verdict", ["!approve", "approve?", "not approve"])
def test_punctuated_verdict_is_not_an_approval(verdict):
    decisions = [{"agent_name": "Content Analysis Agent", "decision": verdict, "confidence": 1.0}]
    assert not compute_agent_signals(decisions).all_allow
