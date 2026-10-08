"""
Stage 1: Deterministic Safety Gate with Uncertainty-Aware Safety Margins & Escalation Logic.

The gate is a fixed sequence of rule checks. It reads only the viewer profile's tier,
trust level and parental controls, and the item's moderation metadata. It never reads
interests, learned weights or bandit state, so none of them can influence it.

Fail-closed: an item passes only when every check positively establishes that it may be
served. Unknown ratings, statuses, categories or confidence signals are rejections, and
so is any item or profile that does not re-validate or that makes a check raise.

For child and teen viewers the gate does not rely on the rating alone: it independently
requires approved status, allow-listed topics, no disallowed policy violations, no
escalation label and a toxicity score below the tier's limit.
"""

import logging
from collections import Counter
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from recommendation.src.config import (
    ADULT_SERVABLE_STATUSES,
    APPROVED_STATUS,
    BLOCKED_STATUSES,
    CHILD_SAFE_TOPICS,
    HIGH_UNCERTAINTY_THRESHOLD,
    NO_VIOLATION_LABELS,
    SENSITIVE_TEEN_TOPICS,
    TEEN_ALLOWED_TOPICS,
    TEEN_TOLERATED_VIOLATIONS,
    TOXICITY_ADULT_THRESHOLD,
    TOXICITY_TEEN_THRESHOLD,
)
from recommendation.src.models import (
    AgeTier,
    AgeTrustLevel,
    AudienceRating,
    GateDecision,
    GateReason,
    RecommendationItemModel,
    Strictness,
    ViewerProfileModel,
    label_stems,
    normalize_enum_value,
    normalize_label,
)
from recommendation.src.rating import RATING_RANK, find_escalation_categories

logger = logging.getLogger(__name__)

TIER_RANK: Dict[AgeTier, int] = {
    AgeTier.CHILD: 1,
    AgeTier.TEEN: 2,
    AgeTier.ADULT: 3,
}

# Lower trust in the claimed age narrows the tolerated uncertainty.
TRUST_MULTIPLIER: Dict[AgeTrustLevel, float] = {
    AgeTrustLevel.VERIFIED: 1.0,
    AgeTrustLevel.PARENT_LINKED: 0.85,
    AgeTrustLevel.SELF_DECLARED: 0.7,
}

# LOW is the default and the baseline; the other levels can only tighten.
STRICTNESS_MULTIPLIER: Dict[Strictness, float] = {
    Strictness.LOW: 1.0,
    Strictness.MEDIUM: 0.8,
    Strictness.STRICT: 0.6,
}

# Trust levels that exempt an adult from the uncertainty margin.
MARGIN_EXEMPT_TRUST: FrozenSet[AgeTrustLevel] = frozenset(
    {AgeTrustLevel.PARENT_LINKED, AgeTrustLevel.VERIFIED}
)

TOPIC_ALLOW_LIST: Dict[AgeTier, FrozenSet[str]] = {
    AgeTier.CHILD: frozenset(CHILD_SAFE_TOPICS),
    AgeTier.TEEN: frozenset(TEEN_ALLOWED_TOPICS) | frozenset(SENSITIVE_TEEN_TOPICS),
}
VIOLATION_ALLOW_LIST: Dict[AgeTier, FrozenSet[str]] = {
    AgeTier.CHILD: NO_VIOLATION_LABELS,
    AgeTier.TEEN: TEEN_TOLERATED_VIOLATIONS | NO_VIOLATION_LABELS,
}
# A minor is only served an item whose toxicity score is known and below this value.
TOXICITY_LIMIT: Dict[AgeTier, float] = {
    AgeTier.CHILD: TOXICITY_TEEN_THRESHOLD,
    AgeTier.TEEN: TOXICITY_ADULT_THRESHOLD,
}


def _reject(item_id: str, reason: GateReason, margin: bool = False) -> GateDecision:
    return GateDecision(
        item_id=item_id, passed=False, rejection_reason=reason, safety_margin_applied=margin
    )


def _label_matches(blocked: str, label: str) -> bool:
    """
    True when every word of the blocked label appears in the label, compared by stem and
    in any order, so "games" blocks "gaming_family" and "kids music" blocks "music_kids".
    """
    blocked_stems = label_stems(blocked)
    return bool(blocked_stems) and blocked_stems <= label_stems(label)


class SafetyGate:
    """
    Deterministic safety gate enforcing age-rating constraints, uncertainty safety margins,
    parental control overrides, and high-risk category escalations.
    """

    @staticmethod
    def uncertainty_threshold(profile: ViewerProfileModel) -> float:
        """Disagreement level at or above which an item is too uncertain for this viewer."""
        trust = TRUST_MULTIPLIER.get(profile.age_trust_level, min(TRUST_MULTIPLIER.values()))
        strictness = STRICTNESS_MULTIPLIER.get(
            profile.parental_controls.strictness_level, min(STRICTNESS_MULTIPLIER.values())
        )
        return HIGH_UNCERTAINTY_THRESHOLD * trust * strictness

    @staticmethod
    def margin_applies(profile: ViewerProfileModel) -> bool:
        """
        Whether the uncertainty safety margin applies to this viewer.

        Always, except for an adult whose age is parent-linked or verified. A
        self-declared adult age may be false, so the margin stays on.
        """
        return not (
            profile.age_tier == AgeTier.ADULT and profile.age_trust_level in MARGIN_EXEMPT_TRUST
        )

    @classmethod
    def evaluate_item(
        cls,
        profile: ViewerProfileModel,
        item: RecommendationItemModel
    ) -> GateDecision:
        """
        Evaluate a single content item against a viewer profile.
        Returns GateDecision indicating pass/fail and rejection reason.

        Both inputs are re-validated first, so a model changed through ``model_copy`` or
        ``model_construct`` cannot carry an unchecked value into the rules.
        """
        item_id = str(getattr(item, "item_id", "unknown"))
        try:
            checked_profile = ViewerProfileModel.model_validate(profile.model_dump(warnings=False))
            checked_item = RecommendationItemModel.model_validate(item.model_dump(warnings=False))
            return cls._apply_rules(checked_profile, checked_item)
        except Exception as error:
            logger.error(f"gate_invalid_input item_id={item_id} error={type(error).__name__}")
            return _reject(item_id, GateReason.INVALID, margin=True)

    @classmethod
    def _apply_rules(
        cls,
        profile: ViewerProfileModel,
        item: RecommendationItemModel
    ) -> GateDecision:
        """The ordered rule checks, on validated inputs. First failing check wins."""
        item_id = item.item_id
        tier_rank = TIER_RANK.get(profile.age_tier, TIER_RANK[AgeTier.CHILD])
        is_minor = tier_rank < TIER_RANK[AgeTier.ADULT]
        margin = cls.margin_applies(profile)
        controls = profile.parental_controls
        status = normalize_label(item.status) if item.status else ""
        exact_status = normalize_enum_value(item.status) if item.status else ""
        exactly_approved = exact_status == APPROVED_STATUS
        # Empty labels are kept: for a minor they fail the allow-lists below.
        topic_labels = [normalize_label(label) for label in item.content_topics]
        if item.content_category is not None:
            topic_labels.insert(0, normalize_label(item.content_category))
        violation_labels = [normalize_label(label) for label in item.policy_violations]
        labels = topic_labels + violation_labels
        rating = item.audience_rating

        # 1. BLOCKED is never served to anyone.
        if rating == AudienceRating.BLOCKED or status in BLOCKED_STATUSES:
            return _reject(item_id, GateReason.BLOCKED)

        # 2. Status must be one that is known to be servable.
        if exact_status not in ADULT_SERVABLE_STATUSES:
            if is_minor:
                return _reject(item_id, GateReason.PENDING_REVIEW, margin=True)
            return _reject(item_id, GateReason.NOT_SERVABLE_STATUS)

        # 3. Unrated (legacy) items: withheld wherever the margin applies, adult otherwise.
        if rating is None:
            if margin:
                return _reject(item_id, GateReason.UNRATED, margin=True)
            rating = AudienceRating.ADULT
        item_rank = RATING_RANK.get(rating, RATING_RANK[AudienceRating.BLOCKED])

        # 4. Parental controls override everything that follows.
        blocked_labels = [normalize_label(c) for c in controls.blocked_categories if c]
        if any(_label_matches(blocked, label) for blocked in blocked_labels for label in labels):
            return _reject(item_id, GateReason.PARENTAL_BLOCK, margin=True)
        if controls.max_rating is not None:
            cap_rank = RATING_RANK.get(controls.max_rating, RATING_RANK[AudienceRating.ALL_AGES])
            if item_rank > cap_rank:
                return _reject(item_id, GateReason.PARENTAL_BLOCK, margin=True)

        # 5. Escalation categories are hidden from child and teen feeds immediately.
        if is_minor and (item.escalated or find_escalation_categories(labels)):
            return _reject(item_id, GateReason.ESCALATION, margin=True)

        # 6. Rating versus tier: item rating above the viewer's tier is removed.
        if item_rank > tier_rank:
            return _reject(item_id, GateReason.ABOVE_TIER)

        if is_minor:
            # 7. Independent of the rating: every topic must be on the tier's allow-list,
            #    no policy violation outside the tier's tolerated set may be present, and
            #    the toxicity score must be known and under the tier's limit.
            allowed_topics = TOPIC_ALLOW_LIST[profile.age_tier]
            if not topic_labels or not all(label in allowed_topics for label in topic_labels):
                return _reject(item_id, GateReason.UNLISTED_TOPIC, margin=True)
            tolerated = VIOLATION_ALLOW_LIST[profile.age_tier]
            if not all(label in tolerated for label in violation_labels):
                return _reject(item_id, GateReason.POLICY_VIOLATION, margin=True)

            toxicity = item.toxicity_score
            if toxicity is None or not (0.0 <= toxicity < TOXICITY_LIMIT[profile.age_tier]):
                return _reject(item_id, GateReason.TOXICITY, margin=True)

            # 8. Sensitive teen topics need an explicit parental allowance.
            allowance = {normalize_label(t) for t in controls.allowed_sensitive_topics if t}
            sensitive = [label for label in topic_labels if label in SENSITIVE_TEEN_TOPICS]
            if any(label not in allowance for label in sensitive):
                return _reject(item_id, GateReason.SENSITIVE_TOPIC, margin=True)

            # 9. Borderline items never reach a child, nor a teen under strict controls.
            if item.is_borderline and (
                profile.age_tier == AgeTier.CHILD or controls.strictness_level == Strictness.STRICT
            ):
                return _reject(item_id, GateReason.BORDERLINE, margin=True)

        # 10. Safety margin: only approved items with known, low uncertainty.
        if margin:
            if not exactly_approved:
                return _reject(item_id, GateReason.PENDING_REVIEW, margin=True)
            disagreement: Optional[float] = item.agent_disagreement
            confidence: Optional[float] = item.overall_confidence
            if disagreement is None or confidence is None:
                return _reject(item_id, GateReason.MISSING_SIGNALS, margin=True)
            threshold = cls.uncertainty_threshold(profile)
            # Written as "not (inside the safe range)" so a NaN can never pass.
            if not (0.0 <= disagreement < threshold and 1.0 - threshold <= confidence <= 1.0):
                return _reject(item_id, GateReason.HIGH_UNCERTAINTY, margin=True)

        return GateDecision(item_id=item_id, passed=True, safety_margin_applied=margin)

    @classmethod
    def filter_candidate_pool(
        cls,
        profile: ViewerProfileModel,
        candidates: Sequence[RecommendationItemModel]
    ) -> Tuple[List[RecommendationItemModel], List[GateDecision]]:
        """
        Filter candidate pool through the deterministic safety gate.
        Returns surviving items and audit log of decisions.
        """
        surviving_items: List[RecommendationItemModel] = []
        decisions: List[GateDecision] = []

        for item in candidates:
            decision = cls.evaluate_item(profile, item)
            decisions.append(decision)
            if decision.passed:
                surviving_items.append(item)

        return surviving_items, decisions

    @classmethod
    def enforce_final_output(
        cls,
        profile: ViewerProfileModel,
        ranked_items: Sequence[RecommendationItemModel]
    ) -> List[RecommendationItemModel]:
        """
        Re-run the gate on the final ranked list immediately before it is returned.

        The ranker only ever receives gate survivors, so this should drop nothing. If it
        does, an upstream stage introduced or altered an item; the item is dropped and the
        event is logged as an error.
        """
        surviving, decisions = cls.filter_candidate_pool(profile, ranked_items)
        dropped = [d for d in decisions if not d.passed]
        if dropped:
            reasons = Counter(d.rejection_reason.value for d in dropped if d.rejection_reason)
            logger.error(
                f"gate_final_check_dropped profile_id={profile.profile_id} "
                f"tier={profile.age_tier.value} count={len(dropped)} reasons={dict(reasons)}"
            )
        return surviving


def summarize_rejections(decisions: Sequence[GateDecision]) -> Dict[str, int]:
    """Count gate rejections by reason."""
    counts = Counter(
        d.rejection_reason.value for d in decisions if not d.passed and d.rejection_reason
    )
    return dict(counts)
