"""
Stage 3: Moderator-Side Review Queue Prioritizer, Precedent Retrieval & Feedback Loop.
"""

import math
from typing import List, Dict, Any, Optional
from recommendation.src.models import (
    PrioritizedQueueItem,
    PrecedentCase,
    RecommendationDetailResponse,
    FeedbackEvent,
    AudienceRating
)
from recommendation.src.config import HIGH_RISK_ESCALATION_CATEGORIES
from recommendation.src.personalization import TFIDFSimilarityProvider


class ReviewQueuePrioritizer:
    """
    Calculates review queue priority scores and sorts moderation queues.
    Formula: expected_harm * (1 - agent_consensus) * exposure
    """

    @staticmethod
    def calculate_priority(
        content_id: str,
        content_text: str,
        category: str,
        toxicity_score: float,
        agent_confidence_scores: Dict[str, float],
        agent_disagreement: float,
        exposure_count: int = 100,
        status: str = "pending_review",
        audience_rating: AudienceRating = AudienceRating.ADULT
    ) -> PrioritizedQueueItem:
        """
        Calculate priority score for a queued item.
        """
        category_clean = category.lower() if category else "other"
        
        # High risk category base harm
        is_high_risk = category_clean in HIGH_RISK_ESCALATION_CATEGORIES
        base_harm = 0.95 if is_high_risk else max(0.1, toxicity_score)

        # Agent consensus factor: (1 - agent_consensus) = agent_disagreement
        disagreement_factor = max(0.1, agent_disagreement)

        # Exposure score: logarithmic scaling of views/impressions
        exposure_score = max(1.0, math.log10(max(1, exposure_count) + 1.0))

        # Priority calculation
        priority_score = base_harm * disagreement_factor * exposure_score

        # Escalation trigger
        is_escalated = is_high_risk or (toxicity_score > 0.85 and disagreement_factor > 0.4)
        requires_senior = is_escalated or (audience_rating == AudienceRating.BLOCKED)

        if is_escalated:
            # Boost priority to top of queue
            priority_score += 1000.0

        return PrioritizedQueueItem(
            content_id=content_id,
            content_text=content_text,
            category=category,
            priority_score=round(priority_score, 4),
            expected_harm=round(base_harm, 4),
            agent_disagreement=round(disagreement_factor, 4),
            exposure_score=round(exposure_score, 4),
            audience_rating=audience_rating,
            status=status,
            is_escalated=is_escalated,
            requires_senior_moderator=requires_senior,
            created_at=""
        )

    @classmethod
    def prioritize_queue(
        cls,
        raw_items: List[Dict[str, Any]]
    ) -> List[PrioritizedQueueItem]:
        """
        Process a list of raw queued items and sort by priority score descending.
        """
        prioritized = []
        for item in raw_items:
            q_item = cls.calculate_priority(
                content_id=item.get("content_id", ""),
                content_text=item.get("content_text", ""),
                category=item.get("content_category", "general"),
                toxicity_score=item.get("toxicity_score", 0.0),
                agent_confidence_scores=item.get("agent_confidence_scores", {}),
                agent_disagreement=item.get("agent_disagreement", 0.2),
                exposure_count=item.get("exposure_count", 100),
                status=item.get("status", "pending_review"),
                audience_rating=AudienceRating(item.get("audience_rating", "adult"))
            )
            prioritized.append(q_item)

        # Sort descending by priority score
        prioritized.sort(key=lambda x: x.priority_score, reverse=True)
        return prioritized


class PrecedentRetriever:
    """
    Retrieves top k resolved moderation cases similar to a candidate item for explainability.
    """

    def __init__(self, precedent_cases: List[PrecedentCase]):
        self.cases = precedent_cases
        self.similarity_engine = TFIDFSimilarityProvider()

    def get_similar_precedents(
        self,
        content_text: str,
        category: str,
        k: int = 3
    ) -> List[PrecedentCase]:
        """
        Retrieve top k precedent cases sorted by textual & category similarity.
        """
        if not self.cases:
            return []

        query = f"{category} {content_text}"
        scored = []
        for case in self.cases:
            case_text = f"{case.category} {case.moderator_notes}"
            sim = self.similarity_engine.compute_similarity(query, case_text)
            if case.category.lower() == category.lower():
                sim += 0.3  # Category match bonus

            # Copy case with computed similarity
            c_copy = PrecedentCase(
                case_id=case.case_id,
                content_id=case.content_id,
                category=case.category,
                similarity_score=round(min(1.0, sim), 3),
                agent_verdict=case.agent_verdict,
                final_human_action=case.final_human_action,
                moderator_notes=case.moderator_notes,
                override_occurred=case.override_occurred
            )
            scored.append((c_copy.similarity_score, c_copy))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]]
