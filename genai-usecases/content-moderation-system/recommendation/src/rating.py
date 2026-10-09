"""
Stage 1: Deterministic audience rating derived from the moderation pipeline's output.

Every rule here is a fixed comparison on fields the existing agents already write to
``ContentState``. Nothing is learned. The item starts at ``all_ages`` and rules can only
raise the rating. A signal that is missing, malformed or not recognised raises the rating
to ``adult``; it never counts as "nothing found".
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from recommendation.src.config import (
    APPROVED_STATUS,
    BLOCKED_STATUSES,
    BORDERLINE_TOXICITY_THRESHOLD,
    CHILD_SAFE_TOPICS,
    HIGH_RISK_ESCALATION_STEMS,
    NO_VIOLATION_LABELS,
    SENSITIVE_TEEN_TOPICS,
    SEVERITY_ALL_AGES,
    SEVERITY_TEEN,
    TEEN_ALLOWED_TOPICS,
    TEEN_TOLERATED_VIOLATIONS,
    TOXICITY_ADULT_THRESHOLD,
    TOXICITY_BLOCK_THRESHOLD,
    TOXICITY_TEEN_THRESHOLD,
    is_recommendation_enabled,
)
from recommendation.src.models import (
    AudienceRating,
    RecommendationItemModel,
    normalize_enum_value,
    normalize_label,
)

logger = logging.getLogger(__name__)

RATING_RANK: Dict[AudienceRating, int] = {
    AudienceRating.ALL_AGES: 1,
    AudienceRating.TEEN: 2,
    AudienceRating.ADULT: 3,
    AudienceRating.BLOCKED: 4,
}

# Agents whose "approve" is bookkeeping ("action completed"), not a judgement of the
# content, reported with confidence 1.0. Their approvals are not counted, because that
# would hide real disagreement. Any other verdict from them is counted like any agent's.
BOOKKEEPING_AGENTS = frozenset({"action enforcement agent", "hitl checkpoint agent"})
HUMAN_REVIEW_AGENT = "hitl human review"
# The ReAct loop synthesises the other agents' verdicts. Its verdict is counted like any
# other, but the "confidence" it reports is a weighted score (weight x confidence x
# priority, about 0.1 to 0.2 for a unanimous approval), not a probability, so it is left
# out of the confidence floor. Seen in a live run of the pipeline, not in the mock data.
SYNTHESIS_AGENTS = frozenset({"react decision loop"})
ALLOW = "allow"

# Collapse DecisionType values into verdict groups before measuring agreement.
_VERDICT_GROUPS: Dict[str, str] = {
    "approve": ALLOW,
    "human_approved": ALLOW,
    "warn": "warn",
    "remove": "remove",
    "suspend_user": "remove",
    "ban_user": "remove",
    "flag": "review",
    "needs_review": "review",
    "await_human": "review",
    "human_escalated": "review",
}

_LOW_MEDIA_RISK = frozenset({"none", "low", "safe"})
_DETECTION_FLAGS = (
    "contains_sensitive_content",
    "explicit_content_detected",
    "hate_speech_detected",
    "harassment_detected",
)


@dataclass(frozen=True)
class AgentSignals:
    """Agreement and confidence of the agents that judged an item."""

    disagreement: Optional[float]
    confidence: Optional[float]
    all_allow: bool
    human_approved: bool = False


@dataclass(frozen=True)
class RatingResult:
    """Outcome of rating one moderated item."""

    rating: AudienceRating
    agent_disagreement: Optional[float]
    overall_confidence: Optional[float]
    escalation_categories: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def escalated(self) -> bool:
        """True when the item carries a high-risk escalation category."""
        return bool(self.escalation_categories)


def find_escalation_categories(labels: Iterable[Any]) -> Tuple[str, ...]:
    """Return the high-risk escalation categories present in a set of labels."""
    found = set()
    squashed_labels = [normalize_label(label).replace("_", "") for label in labels if label is not None]
    # The labels are also checked joined together, so a term split across two labels
    # (["self", "harm"]) is still found.
    for squashed in squashed_labels + ["".join(squashed_labels)]:
        for category, stems in HIGH_RISK_ESCALATION_STEMS.items():
            if any(stem in squashed for stem in stems):
                found.add(category)
    return tuple(sorted(found))


def _read(decision: Any, name: str) -> Any:
    """Read a field from an AgentDecision dataclass or its dict form."""
    if isinstance(decision, Mapping):
        return decision.get(name)
    return getattr(decision, name, None)


def _to_unit_float(value: Any) -> Optional[float]:
    """
    A number in [0, 1], or None for a missing signal. Only real numbers are accepted:
    text such as "0", " 0 " or "0_0" is malformed pipeline output, not a score.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if number != number or number < 0.0 or number > 1.0:
        return None
    return number


def _label_list(value: Any) -> Optional[List[str]]:
    """
    Normalise a list-of-labels field. Returns None when the field is missing or malformed
    (not a list of non-empty strings), which callers must treat as an unknown signal.
    """
    if not isinstance(value, (list, tuple, set, frozenset)):
        return None
    labels: List[str] = []
    for entry in value:
        if not isinstance(entry, str):
            return None
        normalized = normalize_label(entry)
        if not normalized:
            return None
        labels.append(normalized)
    return labels


def compute_agent_signals(agent_decisions: Any) -> AgentSignals:
    """
    Compute agreement and confidence from the pipeline's agent decisions.

    Disagreement is 1 minus the share of judging agents in the largest verdict group.
    Confidence is the lowest confidence any judging agent reported. ``all_allow`` is true
    only when every judging agent allowed the content, or when the last judging decision
    is a human review that allowed it (a human approval settles earlier disagreement).
    With nothing usable the signals are None, which the gate treats as uncertain.
    """
    if not isinstance(agent_decisions, (list, tuple)):
        return AgentSignals(None, None, False)

    verdicts: List[str] = []
    confidences: List[float] = []
    last_is_human_allow = False
    human_confidence: Optional[float] = None

    for decision in agent_decisions:
        raw_name = _read(decision, "agent_name")
        agent_name = " ".join(raw_name.lower().split()) if isinstance(raw_name, str) else ""
        raw_verdict = _read(decision, "decision")
        raw_verdict = getattr(raw_verdict, "value", raw_verdict)
        verdict = _VERDICT_GROUPS.get(normalize_enum_value(raw_verdict)) if isinstance(raw_verdict, str) else None
        confidence = _to_unit_float(_read(decision, "confidence"))
        if agent_name in BOOKKEEPING_AGENTS and verdict == ALLOW:
            continue
        if not agent_name or verdict is None or confidence is None:
            # A decision that cannot be read counts as a dissenting, zero-confidence vote.
            verdict, confidence = "unreadable", 0.0
        verdicts.append(verdict)
        if agent_name not in SYNTHESIS_AGENTS or verdict == "unreadable":
            confidences.append(confidence)
        last_is_human_allow = agent_name == HUMAN_REVIEW_AGENT and verdict == ALLOW
        human_confidence = confidence if last_is_human_allow else None

    if not verdicts:
        return AgentSignals(None, None, False)
    if last_is_human_allow:
        return AgentSignals(0.0, human_confidence, True, human_approved=True)

    largest_group = max(verdicts.count(v) for v in set(verdicts))
    disagreement = round(1.0 - (largest_group / len(verdicts)), 4)
    lowest_confidence = min(confidences) if confidences else None
    return AgentSignals(disagreement, lowest_confidence, all(v == ALLOW for v in verdicts))


def derive_audience_rating(state: Mapping[str, Any]) -> RatingResult:
    """
    Deterministically derive an audience rating from a final ``ContentState``.

    An item reaches ``all_ages`` or ``teen`` only if it was explicitly approved, every
    judging agent allowed it, and every signal needed to justify the rating is present
    and well-formed.
    """
    reasons: List[str] = []
    rank = RATING_RANK[AudienceRating.ALL_AGES]

    def raise_to(rating: AudienceRating, reason: str) -> None:
        nonlocal rank
        if RATING_RANK[rating] > rank:
            rank = RATING_RANK[rating]
        reasons.append(reason)

    raw_status = state.get("status")
    raw_action = state.get("moderation_action")
    status = normalize_label(raw_status) if isinstance(raw_status, str) else ""
    action = normalize_label(raw_action) if isinstance(raw_action, str) else ""
    # "approved" must match exactly; only blocked values are matched loosely.
    approved = isinstance(raw_status, str) and normalize_enum_value(raw_status) == APPROVED_STATUS

    # Taken down, or the author was sanctioned for it.
    if status in BLOCKED_STATUSES or action in BLOCKED_STATUSES or state.get("content_removed") not in (False, None):
        raise_to(AudienceRating.BLOCKED, "removed_or_sanctioned")
    if not approved:
        raise_to(AudienceRating.ADULT, f"status_not_approved:{status or 'missing'}")
    # The pipeline only writes moderation_action when the enforcement agent runs, and it
    # does not run for content approved on the normal path. So an absent action is fine;
    # an action that is present must say "approved".
    if raw_action is not None and not (
        isinstance(raw_action, str) and normalize_enum_value(raw_action) == APPROVED_STATUS
    ):
        raise_to(AudienceRating.ADULT, f"action_not_approved:{action or 'malformed'}")
    if state.get("content_removed") is not False:
        raise_to(AudienceRating.ADULT, "content_removed_unknown")

    # Label fields. A missing or malformed field is unknown, hence adult.
    violations = _label_list(state.get("policy_violations"))
    policy_flags = _label_list(state.get("policy_flags"))
    topics = _label_list(state.get("content_topics"))
    raw_category = state.get("content_category")
    category = normalize_label(raw_category) if isinstance(raw_category, str) else ""
    if not category:
        raise_to(AudienceRating.ADULT, "signal_missing_or_malformed:content_category")

    escalation_inputs: List[Any] = [category, repr(raw_category)]
    for name, labels in (("policy_violations", violations), ("policy_flags", policy_flags), ("content_topics", topics)):
        if labels is None:
            raise_to(AudienceRating.ADULT, f"signal_missing_or_malformed:{name}")
            escalation_inputs.append(repr(state.get(name)))
        else:
            escalation_inputs.extend(labels)
    signals = compute_agent_signals(state.get("agent_decisions"))
    escalation = find_escalation_categories(escalation_inputs)
    if escalation:
        # Withheld from everyone until a human moderator has approved it. Approval by
        # the agents alone is not enough for a high-risk category.
        raise_to(
            AudienceRating.ADULT if approved and signals.human_approved else AudienceRating.BLOCKED,
            "escalation_category:" + ",".join(escalation),
        )

    for violation in violations or []:
        if violation in NO_VIOLATION_LABELS:
            continue
        if violation in TEEN_TOLERATED_VIOLATIONS:
            raise_to(AudienceRating.TEEN, f"violation:{violation}")
        else:
            raise_to(AudienceRating.ADULT, f"violation:{violation}")

    # Anything the policy agent flagged keeps the item away from minors.
    if policy_flags:
        raise_to(AudienceRating.ADULT, "policy_flags_present")

    toxicity = _to_unit_float(state.get("toxicity_score"))
    if toxicity is None:
        raise_to(AudienceRating.ADULT, "toxicity_missing")
    elif toxicity >= TOXICITY_BLOCK_THRESHOLD:
        raise_to(AudienceRating.BLOCKED, "toxicity_block")
    elif toxicity >= TOXICITY_ADULT_THRESHOLD:
        raise_to(AudienceRating.ADULT, "toxicity_adult")
    elif toxicity >= TOXICITY_TEEN_THRESHOLD:
        raise_to(AudienceRating.TEEN, "toxicity_teen")

    raw_severity = state.get("violation_severity")
    severity = normalize_enum_value(raw_severity) if isinstance(raw_severity, str) else ""
    if severity not in SEVERITY_TEEN:
        raise_to(AudienceRating.ADULT, f"severity:{severity or 'missing'}")
    elif severity not in SEVERITY_ALL_AGES:
        raise_to(AudienceRating.TEEN, f"severity:{severity}")

    for flag_name in _DETECTION_FLAGS:
        if state.get(flag_name) is not False:
            raise_to(AudienceRating.ADULT, f"{flag_name}:{state.get(flag_name)!r}")

    raw_media_risk = state.get("media_risk_level")
    media_risk = normalize_enum_value(raw_media_risk) if isinstance(raw_media_risk, str) else ""
    if media_risk not in _LOW_MEDIA_RISK:
        raise_to(AudienceRating.ADULT, f"media_risk:{media_risk or 'missing'}")

    if not signals.all_allow:
        raise_to(AudienceRating.ADULT, "not_every_agent_allowed")

    # Topic allow-lists: an unknown or missing topic can never rate below adult.
    topic_labels = ([category] if category else []) + (topics or [])
    if not topic_labels:
        raise_to(AudienceRating.ADULT, "topic_missing")
    elif not all(label in TEEN_ALLOWED_TOPICS or label in SENSITIVE_TEEN_TOPICS for label in topic_labels):
        raise_to(AudienceRating.ADULT, "topic_not_on_teen_list")
    elif not all(label in CHILD_SAFE_TOPICS for label in topic_labels):
        raise_to(AudienceRating.TEEN, "topic_not_on_child_list")

    rating = next(r for r, value in RATING_RANK.items() if value == rank)
    return RatingResult(
        rating=rating,
        agent_disagreement=signals.disagreement,
        overall_confidence=signals.confidence,
        escalation_categories=escalation,
        reasons=tuple(reasons),
    )


def apply_audience_rating(state: Dict[str, Any]) -> Optional[RatingResult]:
    """
    Write ``audience_rating`` and ``agent_disagreement`` onto a final pipeline state.

    Called by the moderation workflow after the graph finishes. Does nothing when the
    feature flag is off, so the pipeline output is unchanged for existing deployments;
    items moderated while the flag is off stay unrated and are withheld from minors.
    The returned result also carries the confidence and escalation categories for the
    caller that persists the item.
    """
    if not is_recommendation_enabled() or state is None:
        return None
    result = derive_audience_rating(state)
    state["audience_rating"] = result.rating.value
    state["agent_disagreement"] = result.agent_disagreement
    logger.info(
        f"audience_rating content_id={state.get('content_id')} rating={result.rating.value} "
        f"disagreement={result.agent_disagreement} escalated={result.escalated}"
    )
    return result


def build_item_from_state(
    state: Mapping[str, Any],
    exposure_count: int = 0,
    rated: bool = True,
) -> RecommendationItemModel:
    """
    Build the recommender's view of an item from a final pipeline state.

    With ``rated=False`` the item is built the way a legacy record looks: no rating and
    no agent signals. Malformed label fields become empty rather than failing, because the
    rating derivation has already raised the rating for them.
    """
    result = derive_audience_rating(state) if rated else None
    category = state.get("content_category")
    status = state.get("status")
    toxicity = _to_unit_float(state.get("toxicity_score"))
    severity = state.get("violation_severity")
    is_borderline = bool(
        result is not None
        and result.rating == AudienceRating.TEEN
        and (
            (toxicity is not None and toxicity >= BORDERLINE_TOXICITY_THRESHOLD)
            or (isinstance(severity, str) and normalize_enum_value(severity) == "low")
        )
    )
    return RecommendationItemModel(
        item_id=str(state.get("content_id")),
        content_text=str(state.get("content_text") or ""),
        content_category=category if isinstance(category, str) else None,
        content_topics=[t for t in (_raw_list(state.get("content_topics"))) if isinstance(t, str)],
        policy_violations=[v for v in (_raw_list(state.get("policy_violations"))) if isinstance(v, str)],
        audience_rating=result.rating if result else None,
        toxicity_score=toxicity,
        overall_confidence=result.overall_confidence if result else None,
        agent_disagreement=result.agent_disagreement if result else None,
        status=status if isinstance(status, str) else None,
        is_borderline=is_borderline,
        escalated=result.escalated if result else bool(find_escalation_categories([category])),
        human_reviewed=bool(rated and compute_agent_signals(state.get("agent_decisions")).human_approved),
        exposure_count=max(0, int(exposure_count)),
    )


def rating_for_human_reviewed_item(item: RecommendationItemModel) -> AudienceRating:
    """
    Rating for an item that a moderator has approved AND tagged by hand.

    The moderator's approval and tags stand in for the agents' judgement and topic
    extraction, which is what makes it possible to rate an item below ``adult`` when the
    language model was unavailable. Every machine signal that is on the item still
    counts and can only raise the rating: toxicity (unknown means adult), policy
    violations, escalation labels and the topic allow-lists.
    """
    labels = [normalize_label(label) for label in [item.content_category, *item.content_topics] if label]
    violations = {normalize_label(v) for v in item.policy_violations} - NO_VIOLATION_LABELS
    rank = RATING_RANK[AudienceRating.ALL_AGES]

    def at_least(rating: AudienceRating) -> None:
        nonlocal rank
        rank = max(rank, RATING_RANK[rating])

    if item.escalated or find_escalation_categories(labels + sorted(violations)):
        at_least(AudienceRating.ADULT)
    toxicity = item.toxicity_score
    if toxicity is None or toxicity >= TOXICITY_ADULT_THRESHOLD:
        at_least(AudienceRating.ADULT)
    elif toxicity >= TOXICITY_TEEN_THRESHOLD:
        at_least(AudienceRating.TEEN)
    if violations - TEEN_TOLERATED_VIOLATIONS:
        at_least(AudienceRating.ADULT)
    elif violations:
        at_least(AudienceRating.TEEN)
    if not labels or not all(l in TEEN_ALLOWED_TOPICS or l in SENSITIVE_TEEN_TOPICS for l in labels):
        at_least(AudienceRating.ADULT)
    elif not all(l in CHILD_SAFE_TOPICS for l in labels):
        at_least(AudienceRating.TEEN)
    return next(r for r, value in RATING_RANK.items() if value == rank)


def _raw_list(value: Any) -> List[Any]:
    """A list-like field as a list; anything else as empty."""
    return list(value) if isinstance(value, (list, tuple, set, frozenset)) else []
