"""
Stage 3: Moderator-Side Review Queue Prioritizer & Precedent Retrieval.

Priority is ``expected_harm x (1 - agent_consensus) x exposure``, scaled by a multiplier
learned from moderator overrides. Escalated items (high-risk categories) are a separate,
leading sort key: they come first whatever the learned multiplier says, and are shown
only to senior moderator roles.
"""

import logging
import math
from typing import Dict, List, Optional, Sequence, Tuple

from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.config import (
    BLOCKED_STATUSES,
    NO_VIOLATION_LABELS,
    REVIEW_QUEUE_STATUSES,
    TEEN_TOLERATED_VIOLATIONS,
    TOXICITY_ADULT_THRESHOLD,
    TOXICITY_BLOCK_THRESHOLD,
)
from recommendation.src.embeddings import EmbeddingProvider, TfidfEmbeddingProvider, cosine_scores
from recommendation.src.models import (
    PrecedentCase,
    PrioritizedQueueItem,
    RecommendationItemModel,
    normalize_enum_value,
    normalize_label,
)
from recommendation.src.rating import find_escalation_categories

logger = logging.getLogger(__name__)

UNKNOWN_HARM = 0.5
ESCALATION_HARM = 0.95
VIOLATION_HARM_FLOOR = 0.5
MIN_UNCERTAINTY = 0.05
CATEGORY_MATCH_BONUS = 0.3


def queue_arm_key(category: str) -> str:
    """Bandit arm that learns how often agents are overridden in a category."""
    return f"queue:{normalize_label(category) or 'unknown'}"


def item_category(item: RecommendationItemModel) -> str:
    """The category used for queue learning and precedent matching."""
    if item.content_category:
        return normalize_label(item.content_category)
    return normalize_label(item.content_topics[0]) if item.content_topics else "unknown"


def is_escalated(item: RecommendationItemModel) -> bool:
    """
    High-risk escalation: the stored flag, an escalation label on the item, or a
    moderator having escalated it (status ``escalated``).
    """
    labels = [item.content_category, *item.content_topics, *item.policy_violations]
    status = normalize_enum_value(item.status) if item.status else ""
    return item.escalated or status == "escalated" or bool(find_escalation_categories(labels))


def needs_review(item: RecommendationItemModel) -> bool:
    """
    Whether an item belongs in the moderator queue: it is awaiting review, or it is in a
    high-risk category and no human has decided on it yet, whatever its status says.
    """
    status = normalize_enum_value(item.status) if item.status else ""
    if status in BLOCKED_STATUSES:
        return False
    return status in REVIEW_QUEUE_STATUSES or (is_escalated(item) and not item.human_reviewed)


class ReviewQueuePrioritizer:
    """
    Calculates review queue priority scores and sorts moderation queues.
    Formula: expected_harm * (1 - agent_consensus) * exposure
    """

    def __init__(self, bandit: Optional[ThompsonSamplingBandit] = None, use_learned_priority: bool = True):
        self.bandit = bandit or ThompsonSamplingBandit()
        self.use_learned_priority = use_learned_priority

    @staticmethod
    def expected_harm(item: RecommendationItemModel) -> float:
        """Harm estimate in [0, 1] from the agents' signals; unknown toxicity counts as 0.5."""
        harm = item.toxicity_score if item.toxicity_score is not None else UNKNOWN_HARM
        violations = {normalize_label(v) for v in item.policy_violations} - NO_VIOLATION_LABELS
        if violations - TEEN_TOLERATED_VIOLATIONS:
            harm = max(harm, VIOLATION_HARM_FLOOR)
        if is_escalated(item):
            harm = max(harm, ESCALATION_HARM)
        return harm

    @staticmethod
    def uncertainty(item: RecommendationItemModel) -> float:
        """1 - agent consensus: the larger of disagreement and lack of confidence; unknown counts as 1."""
        if item.agent_disagreement is None or item.overall_confidence is None:
            return 1.0
        return max(MIN_UNCERTAINTY, item.agent_disagreement, 1.0 - item.overall_confidence)

    @staticmethod
    def exposure_score(item: RecommendationItemModel) -> float:
        """Logarithmic exposure: 1.0 for an unseen item, +1 per tenfold increase in views."""
        return 1.0 + math.log10(1 + item.exposure_count)

    def learned_multiplier(self, item: RecommendationItemModel) -> float:
        """Between 0.5 and 1.5: higher for categories where moderators often override the agents."""
        if not self.use_learned_priority:
            return 1.0
        return 0.5 + self.bandit.mean(queue_arm_key(item_category(item)))

    def calculate_priority(self, item: RecommendationItemModel) -> PrioritizedQueueItem:
        """
        Calculate priority score for a queued item.
        """
        harm = self.expected_harm(item)
        uncertainty = self.uncertainty(item)
        exposure = self.exposure_score(item)
        multiplier = self.learned_multiplier(item)
        escalated = is_escalated(item)
        return PrioritizedQueueItem(
            content_id=item.item_id,
            content_text=item.content_text,
            category=item_category(item),
            priority_score=round(harm * uncertainty * exposure * multiplier, 4),
            expected_harm=round(harm, 4),
            agent_disagreement=round(uncertainty, 4),
            exposure_score=round(exposure, 4),
            learned_multiplier=round(multiplier, 4),
            audience_rating=item.audience_rating,
            status=item.status or "unknown",
            is_escalated=escalated,
            requires_senior_moderator=escalated,
            created_at=item.created_at,
        )

    def prioritize_queue(self, items: Sequence[RecommendationItemModel]) -> List[PrioritizedQueueItem]:
        """
        Score every item that needs review and sort: escalated first, then by priority
        (highest first), then oldest first.
        """
        prioritized = [self.calculate_priority(item) for item in items if needs_review(item)]
        prioritized.sort(key=lambda q: (not q.is_escalated, -q.priority_score, q.created_at, q.content_id))
        return prioritized


def rule_based_suggestion(item: RecommendationItemModel) -> Tuple[str, float]:
    """Suggested action from the agents' signals alone, used when no precedent applies."""
    if is_escalated(item):
        return "escalate", 0.9
    toxicity = item.toxicity_score
    if toxicity is None:
        return "escalate", 0.5
    if toxicity >= TOXICITY_BLOCK_THRESHOLD:
        return "remove", round(toxicity, 4)
    if toxicity >= TOXICITY_ADULT_THRESHOLD:
        return "warn", 0.6
    return "approve", round(1.0 - toxicity, 4)


class PrecedentRetriever:
    """
    Retrieves top k resolved moderation cases similar to a candidate item for explainability.
    """

    def __init__(self, embedding_provider: Optional[EmbeddingProvider] = None):
        self.embedding_provider = embedding_provider or TfidfEmbeddingProvider()

    @staticmethod
    def _case_text(case: PrecedentCase) -> str:
        return f"{case.category} {' '.join(case.topics)} {case.agent_verdict}"

    def get_similar_precedents(
        self,
        item: RecommendationItemModel,
        cases: Sequence[PrecedentCase],
        k: int = 3
    ) -> List[PrecedentCase]:
        """
        Retrieve the k most similar resolved cases, each returned with its similarity score.
        Cases about the item itself are excluded.
        """
        cases = [case for case in cases if case.content_id != item.item_id]
        if not cases or k <= 0:
            return []
        category = item_category(item)
        query = f"{category} {' '.join(normalize_label(t) for t in item.content_topics)}"
        case_texts = [self._case_text(case) for case in cases]
        self.embedding_provider.fit(case_texts + [query])
        scores = cosine_scores(
            self.embedding_provider.embed([query])[0], self.embedding_provider.embed(case_texts)
        )
        ranked = []
        for case, score in zip(cases, scores):
            similarity = float(score) + (CATEGORY_MATCH_BONUS if normalize_label(case.category) == category else 0.0)
            ranked.append((min(1.0, similarity), case))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].case_id))
        return [
            case.model_copy(update={"similarity_score": round(similarity, 4)})
            for similarity, case in ranked[:k] if similarity > 0.0
        ]

    def suggest_action(
        self,
        item: RecommendationItemModel,
        precedents: Sequence[PrecedentCase]
    ) -> Tuple[str, float, str]:
        """
        Suggested action, a confidence in [0, 1] and its source ("precedents" or "rules").

        With precedents: the final human action with the most similarity-weighted support.
        An escalated item is always suggested for escalation, whatever precedents say.
        """
        if is_escalated(item) or not precedents:
            action, confidence = rule_based_suggestion(item)
            return action, confidence, "rules"
        support: Dict[str, float] = {}
        for case in precedents:
            support[case.final_human_action] = support.get(case.final_human_action, 0.0) + case.similarity_score
        action = sorted(support, key=lambda name: (-support[name], name))[0]
        total = sum(support.values())
        return action, round(support[action] / total, 4) if total else 0.0, "precedents"
