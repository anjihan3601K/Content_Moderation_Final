"""
Stage 1: Deterministic Safety Gate with Uncertainty-Aware Safety Margins & Escalation Logic.
"""

from typing import List, Tuple, Dict, Any, Optional
from recommendation.src.models import (
    AgeTier,
    AgeTrustLevel,
    AudienceRating,
    ViewerProfileModel,
    RecommendationItemModel,
    GateDecision
)
from recommendation.src.config import (
    DEFAULT_UNRATED_RATING,
    HIGH_UNCERTAINTY_THRESHOLD,
    HIGH_RISK_ESCALATION_CATEGORIES
)


# Numerical rank for deterministic comparison: all_ages < teen < adult < blocked
RATING_RANK = {
    AudienceRating.ALL_AGES: 1,
    AudienceRating.TEEN: 2,
    AudienceRating.ADULT: 3,
    AudienceRating.BLOCKED: 4
}

TIER_RANK = {
    AgeTier.CHILD: 1,
    AgeTier.TEEN: 2,
    AgeTier.ADULT: 3
}


def derive_audience_rating(
    status: str,
    toxicity_score: float,
    policy_violations: List[str],
    content_category: Optional[str] = None
) -> AudienceRating:
    """
    Deterministically derive an audience rating for an item based on agent decisions,
    toxicity scores, and policy violation categories.
    """
    status_lower = status.lower() if status else "approved"
    
    # Blocked items
    if status_lower in ["removed", "banned"]:
        return AudienceRating.BLOCKED
    
    if toxicity_score >= 0.75:
        return AudienceRating.BLOCKED
        
    for v in policy_violations:
        v_clean = v.lower()
        if v_clean in ["hate_speech", "harassment", "violence", "self_harm", "illegal_activity", "violent_extremism", "grooming"]:
            return AudienceRating.BLOCKED

    # Adult items
    if toxicity_score >= 0.35:
        return AudienceRating.ADULT

    for v in policy_violations:
        v_clean = v.lower()
        if v_clean in ["sexual_content", "bullying", "misinformation", "privacy_violation"]:
            return AudienceRating.ADULT
            
    if content_category in ["dating_advice", "politics_intro", "crime_documentary"]:
        return AudienceRating.ADULT

    # Teen items
    if toxicity_score >= 0.10:
        return AudienceRating.TEEN
        
    for v in policy_violations:
        if v.lower() in ["spam", "copyright"]:
            return AudienceRating.TEEN

    if content_category in TEEN_SENSITIVE_CATEGORIES:
        return AudienceRating.TEEN

    return AudienceRating.ALL_AGES


TEEN_SENSITIVE_CATEGORIES = {"gaming_general", "pop_culture", "fashion", "movies", "technology"}


class SafetyGate:
    """
    Deterministic safety gate enforcing age-rating constraints, uncertainty safety margins,
    parental control overrides, and high-risk category escalations.
    """

    @staticmethod
    def evaluate_item(
        profile: ViewerProfileModel,
        item: RecommendationItemModel
    ) -> GateDecision:
        """
        Evaluate a single content item against a viewer profile.
        Returns GateDecision indicating pass/fail and rejection reason.
        """
        # Safe default for legacy/unrated items
        rating = item.audience_rating or AudienceRating(DEFAULT_UNRATED_RATING)

        # 1. Rule: BLOCKED is never served to anyone
        if rating == AudienceRating.BLOCKED or item.status in ["removed", "banned"]:
            return GateDecision(
                item_id=item.item_id,
                passed=False,
                rejection_reason="blocked",
                safety_margin_applied=False
            )

        # 2. Parental Controls Override (overrides everything else)
        item_categories = [item.content_category] + (item.content_topics or [])
        for cat in profile.parental_controls.blocked_categories:
            if any(cat.lower() == c.lower() for c in item_categories):
                return GateDecision(
                    item_id=item.item_id,
                    passed=False,
                    rejection_reason="parental_block",
                    safety_margin_applied=True
                )

        # 3. Escalation Check: High-risk categories hidden from child and teen feeds immediately
        if profile.age_tier in [AgeTier.CHILD, AgeTier.TEEN]:
            if any(c.lower() in HIGH_RISK_ESCALATION_CATEGORIES for c in item_categories):
                return GateDecision(
                    item_id=item.item_id,
                    passed=False,
                    rejection_reason="escalation",
                    safety_margin_applied=True
                )

        # 4. Strict Rating vs Tier Check: item_rating > viewer_tier => REMOVE
        item_rank = RATING_RANK.get(rating, 3)
        tier_rank = TIER_RANK.get(profile.age_tier, 3)

        if item_rank > tier_rank:
            return GateDecision(
                item_id=item.item_id,
                passed=False,
                rejection_reason="above_tier",
                safety_margin_applied=False
            )

        # 5. Safety Margins for Child and Teen profiles
        if profile.age_tier in [AgeTier.CHILD, AgeTier.TEEN]:
            # Status check: Pending review or flagged content excluded for non-adults
            if item.status in ["pending_review", "flagged", "under_review", "pending_human_review"]:
                return GateDecision(
                    item_id=item.item_id,
                    passed=False,
                    rejection_reason="pending_review",
                    safety_margin_applied=True
                )

            # Trust-level adjusted uncertainty threshold
            # Lower age trust level (e.g. self_declared) makes safety margin stricter
            trust_multiplier = 1.0
            if profile.age_trust_level == AgeTrustLevel.SELF_DECLARED:
                trust_multiplier = 0.7  # 30% stricter uncertainty tolerance
            elif profile.age_trust_level == AgeTrustLevel.PARENT_LINKED:
                trust_multiplier = 0.85

            effective_uncertainty_threshold = HIGH_UNCERTAINTY_THRESHOLD * trust_multiplier

            # Agent disagreement / uncertainty check
            if item.agent_disagreement >= effective_uncertainty_threshold or item.overall_confidence < (1.0 - effective_uncertainty_threshold):
                return GateDecision(
                    item_id=item.item_id,
                    passed=False,
                    rejection_reason="high_uncertainty",
                    safety_margin_applied=True
                )

        # Passed all gate checks
        return GateDecision(
            item_id=item.item_id,
            passed=True,
            rejection_reason=None,
            safety_margin_applied=False
        )

    @classmethod
    def filter_candidate_pool(
        cls,
        profile: ViewerProfileModel,
        candidates: List[RecommendationItemModel]
    ) -> Tuple[List[RecommendationItemModel], List[GateDecision]]:
        """
        Filter candidate pool through the deterministic safety gate.
        Returns surviving items and audit log of decisions.
        """
        surviving_items = []
        decisions = []

        for item in candidates:
            decision = cls.evaluate_item(profile, item)
            decisions.append(decision)
            if decision.passed:
                surviving_items.append(item)

        return surviving_items, decisions
