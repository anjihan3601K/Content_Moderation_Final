"""
Stage 2: Profile-Based Personalization, Embeddings, Contextual Bandit & Drift Guard.
"""

import math
import random
from typing import List, Dict, Any, Optional
from recommendation.src.models import (
    AgeTier,
    ViewerProfileModel,
    RecommendationItemModel
)
from recommendation.src.config import (
    CHILD_SAFE_TOPICS,
    TEEN_ALLOWED_TOPICS,
    SENSITIVE_TEEN_TOPICS,
    BORDERLINE_DRIFT_CAP,
    ADULT_DIVERSITY_MIN
)


class BaseEmbeddingProvider:
    """Interface for lightweight interest embedding calculations."""

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        raise NotImplementedError


class TFIDFSimilarityProvider(BaseEmbeddingProvider):
    """
    Lightweight TF-IDF and bag-of-words similarity provider.
    Zero external network dependencies, deterministic and lightweight.
    """

    def _tokenize(self, text: str) -> List[str]:
        return [w.lower() for w in text.replace("-", " ").replace("_", " ").split() if len(w) > 2]

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        tokens_a = set(self._tokenize(text_a))
        tokens_b = set(self._tokenize(text_b))
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a.intersection(tokens_b)
        union = tokens_a.union(tokens_b)
        return float(len(intersection)) / float(len(union))


class ThompsonSamplingBandit:
    """
    Contextual bandit using Beta distribution sampling for interest explore/exploit.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        # Store alpha (successes + 1) and beta (failures + 1) per topic
        self.arms: Dict[str, Dict[str, float]] = {}

    def get_arm_sample(self, topic: str) -> float:
        arm = self.arms.get(topic, {"alpha": 1.0, "beta": 1.0})
        # Beta distribution sampling
        return self.rng.betavariate(arm["alpha"], arm["beta"])

    def update(self, topic: str, reward: float):
        """
        Update bandit weights: positive reward increases alpha, negative increases beta.
        """
        if topic not in self.arms:
            self.arms[topic] = {"alpha": 1.0, "beta": 1.0}
        
        if reward > 0:
            self.arms[topic]["alpha"] += reward
        else:
            self.arms[topic]["beta"] += abs(reward)


class TierTopicGuard:
    """
    Validates explicit interest selections and learned interest updates per age tier.
    """

    @staticmethod
    def validate_explicit_interests(age_tier: AgeTier, interests: List[str]) -> List[str]:
        """
        Filter explicit interest requests against allowed topic list for tier.
        """
        if age_tier == AgeTier.CHILD:
            return [i for i in interests if i.lower() in CHILD_SAFE_TOPICS]
        elif age_tier == AgeTier.TEEN:
            allowed = set(TEEN_ALLOWED_TOPICS + SENSITIVE_TEEN_TOPICS)
            return [i for i in interests if i.lower() in allowed]
        else:
            # Adult: free choice
            return interests

    @staticmethod
    def update_learned_interests(
        profile: ViewerProfileModel,
        topic: str,
        engagement_reward: float
    ) -> Dict[str, float]:
        """
        Update learned interests according to age tier constraints.
        - Child: Learned engagement can only reorder or down-weight topics already in the child's explicit set.
                 It can NEVER add new topic categories or widen the pool.
        - Teen/Adult: Blended updates.
        """
        current_learned = dict(profile.learned_interests)

        if profile.age_tier == AgeTier.CHILD:
            # Child rule: topic MUST already exist in child's explicit_interests
            if topic not in profile.explicit_interests:
                # Engagement cannot add new topic for children!
                return current_learned

            # Can reorder or down-weight, weight range [0.0, 1.0]
            curr_weight = current_learned.get(topic, 0.5)
            new_weight = max(0.0, min(1.0, curr_weight + (engagement_reward * 0.1)))
            current_learned[topic] = new_weight
            return current_learned

        elif profile.age_tier == AgeTier.TEEN:
            # Teen: Allowed topics only
            allowed = set(TEEN_ALLOWED_TOPICS + SENSITIVE_TEEN_TOPICS)
            if topic in allowed:
                curr_weight = current_learned.get(topic, 0.3)
                new_weight = max(0.0, min(1.0, curr_weight + (engagement_reward * 0.1)))
                current_learned[topic] = new_weight
            return current_learned

        else:
            # Adult: Full update
            curr_weight = current_learned.get(topic, 0.3)
            new_weight = max(0.0, min(1.0, curr_weight + (engagement_reward * 0.1)))
            current_learned[topic] = new_weight
            return current_learned


class ProfileRanker:
    """
    Ranks surviving candidate items using relevance similarity, Thompson sampling,
    and anti-radicalization drift guards.
    """

    def __init__(self, embedding_provider: Optional[BaseEmbeddingProvider] = None, seed: int = 42):
        self.embedding_provider = embedding_provider or TFIDFSimilarityProvider()
        self.bandit = ThompsonSamplingBandit(seed=seed)

    def rank_items(
        self,
        profile: ViewerProfileModel,
        candidates: List[RecommendationItemModel]
    ) -> List[RecommendationItemModel]:
        """
        Rank candidate items surviving the safety gate.
        """
        if not candidates:
            return []

        # 1. Build profile text vector representation from explicit and learned interests
        interest_text = " ".join(profile.explicit_interests)
        for t, weight in profile.learned_interests.items():
            if weight > 0.3:
                interest_text += f" {t}"

        # Calculate recent borderline share in profile's history
        recent_history = profile.recent_feed_history[-20:] if profile.recent_feed_history else []
        borderline_count = sum(1 for h in recent_history if h.get("is_borderline", False))
        recent_borderline_share = float(borderline_count) / float(len(recent_history)) if recent_history else 0.0

        scored_items = []
        for item in candidates:
            item_text = f"{item.content_text} {item.content_category} {' '.join(item.content_topics)}"
            relevance = self.embedding_provider.compute_similarity(interest_text, item_text)

            # Bandit sample for item category/topic
            bandit_sample = self.bandit.get_arm_sample(item.content_category)

            # Combined score: 60% relevance + 40% bandit exploration
            final_score = (0.6 * relevance) + (0.4 * bandit_sample)

            # 2. Drift Guard Penalty against radicalization funnels
            if item.is_borderline:
                if recent_borderline_share >= BORDERLINE_DRIFT_CAP or profile.age_tier != AgeTier.ADULT:
                    # Penalize score heavily if drift cap reached or non-adult
                    final_score *= 0.1

            scored_items.append((final_score, item))

        # Sort descending by score
        scored_items.sort(key=lambda x: x[0], reverse=True)
        ranked = [item for _, item in scored_items]

        # 3. Adult Diversity Guard
        if profile.age_tier == AgeTier.ADULT and len(ranked) >= 5:
            # Ensure at least ADULT_DIVERSITY_MIN share comes from non-primary explicit topics
            primary_topics = set(profile.explicit_interests)
            exploratory = [i for i in ranked if i.content_category not in primary_topics]
            if exploratory:
                # Interleave exploratory item if top items are all primary
                if ranked[0].content_category in primary_topics and len(exploratory) > 0:
                    ranked.insert(2, exploratory[0])
                    # Remove duplicate
                    seen = set()
                    deduped = []
                    for it in ranked:
                        if it.item_id not in seen:
                            seen.add(it.item_id)
                            deduped.append(it)
                    ranked = deduped

        return ranked
