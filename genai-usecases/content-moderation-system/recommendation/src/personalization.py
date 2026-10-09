"""
Stage 2: Profile-Based Personalization, Embeddings, Contextual Bandit & Drift Guard.

Everything here runs on items that already passed the safety gate. The ranker can reorder
its input and leave items out; it has no code path that creates or admits an item, and
its output is gated again by the feed service before it is returned.
"""

import logging
import math
from typing import Dict, List, Optional, Sequence, Set

import numpy as np

from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.config import (
    ADULT_DIVERSITY_MIN,
    BANDIT_WEIGHT,
    BORDERLINE_SHARE_CAP,
    BORDERLINE_TOXICITY_THRESHOLD,
    CHILD_SAFE_TOPICS,
    EXPLICIT_BLEND_WEIGHT,
    FEED_HISTORY_WINDOW,
    LEARNED_DRIFT_LIMIT,
    RANKING_SEED,
    RELEVANCE_WEIGHT,
    RISK_TREND_MIN_SLOPE,
    RISK_TREND_PENALTY,
    SENSITIVE_TEEN_TOPICS,
    TEEN_ALLOWED_TOPICS,
)
from recommendation.src.embeddings import EmbeddingProvider, TfidfEmbeddingProvider, cosine_scores
from recommendation.src.models import (
    AgeTier,
    RecommendationItemModel,
    ViewerProfileModel,
    label_matches,
    normalize_label,
)
from recommendation.src.rating import find_escalation_categories

logger = logging.getLogger(__name__)

MAX_EXPLICIT_INTERESTS = 20
LEARNING_RATE = 0.1


class InterestNotAllowedError(ValueError):
    """Raised when a profile asks for explicit interests its tier may not select."""

    def __init__(self, rejected: List[str]):
        super().__init__(f"Interests not allowed for this profile: {rejected}")
        self.rejected = rejected


def item_topics(item: RecommendationItemModel) -> List[str]:
    """Normalised category and topic labels of an item, category first, without duplicates."""
    labels = [item.content_category] if item.content_category else []
    labels += list(item.content_topics)
    return list(dict.fromkeys(normalize_label(label) for label in labels if label))


def primary_topic(item: RecommendationItemModel) -> str:
    """The topic used as the item's bandit arm."""
    topics = item_topics(item)
    return topics[0] if topics else "unknown"


def is_borderline_risk(item: RecommendationItemModel) -> bool:
    """Borderline-risk content: flagged borderline, or toxicity at or above the borderline level."""
    return item.is_borderline or (
        item.toxicity_score is not None and item.toxicity_score >= BORDERLINE_TOXICITY_THRESHOLD
    )


class TierTopicGuard:
    """
    Validates explicit interest selections and learned interest updates per age tier.
    """

    @staticmethod
    def allowed_topics(profile: ViewerProfileModel) -> Optional[Set[str]]:
        """
        Topics this profile may hold as interests. None means free choice (adult), still
        subject to ``is_topic_allowed``.
        """
        if profile.age_tier == AgeTier.CHILD:
            return set(CHILD_SAFE_TOPICS)
        if profile.age_tier == AgeTier.TEEN:
            allowance = {normalize_label(t) for t in profile.parental_controls.allowed_sensitive_topics}
            return set(TEEN_ALLOWED_TOPICS) | (set(SENSITIVE_TEEN_TOPICS) & allowance)
        return None

    @classmethod
    def is_topic_allowed(cls, profile: ViewerProfileModel, topic: str) -> bool:
        """Whether one topic may be an interest: tier list, platform rules, parental blocks."""
        normalized = normalize_label(topic)
        if not normalized or find_escalation_categories([normalized]):
            return False
        if any(label_matches(blocked, normalized) for blocked in profile.parental_controls.blocked_categories):
            return False
        allowed = cls.allowed_topics(profile)
        return allowed is None or normalized in allowed

    @classmethod
    def validate_explicit_interests(cls, profile: ViewerProfileModel, interests: Sequence[str]) -> List[str]:
        """
        Normalise and validate a requested explicit-interest list for this profile.

        Raises ``InterestNotAllowedError`` naming every rejected topic; nothing is
        silently dropped, so the caller knows the request was not applied.
        """
        normalized = list(dict.fromkeys(normalize_label(topic) for topic in interests))
        if len(normalized) > MAX_EXPLICIT_INTERESTS:
            raise InterestNotAllowedError(normalized[MAX_EXPLICIT_INTERESTS:])
        rejected = [topic for topic in normalized if not cls.is_topic_allowed(profile, topic)]
        if rejected:
            raise InterestNotAllowedError(rejected)
        return normalized

    @classmethod
    def update_learned_interests(
        cls,
        profile: ViewerProfileModel,
        topic: str,
        engagement_reward: float
    ) -> Dict[str, float]:
        """
        Update learned interests according to age tier constraints.
        - Child: engagement can only re-weight topics already in the explicit set. It
          can never add a topic, and a weight never exceeds the explicit baseline of 1.0.
        - Teen/Adult: engagement may add a limited number of allowed topics outside the
          explicit set (the drift limit); beyond that only existing topics are re-weighted.
        """
        learned = dict(profile.learned_interests)
        normalized = normalize_label(topic)
        if not cls.is_topic_allowed(profile, normalized):
            return learned

        explicit = {normalize_label(t) for t in profile.explicit_interests}
        if profile.age_tier == AgeTier.CHILD:
            if normalized not in explicit:
                return learned
            current = learned.get(normalized, 1.0)
        else:
            drift_limit = LEARNED_DRIFT_LIMIT[profile.age_tier.value]
            learned_only = [t for t in learned if t not in explicit]
            if normalized not in explicit and normalized not in learned and len(learned_only) >= drift_limit:
                return learned
            current = learned.get(normalized, 0.3)

        learned[normalized] = round(max(0.0, min(1.0, current + LEARNING_RATE * engagement_reward)), 4)
        return learned

    @classmethod
    def interest_weights(cls, profile: ViewerProfileModel) -> Dict[str, float]:
        """
        The profile's interest vector as topic -> weight.

        Child: explicit topics only; learned engagement re-weights them between 0.1 and 1.0.
        Teen and adult: a blend of the explicit set and learned weights. Topics that are no
        longer allowed (for example after a parental block) are left out for every tier.
        """
        explicit = [normalize_label(t) for t in profile.explicit_interests]
        learned = {normalize_label(t): w for t, w in profile.learned_interests.items()}
        weights: Dict[str, float] = {}

        if profile.age_tier == AgeTier.CHILD:
            for topic in explicit:
                weights[topic] = max(0.1, min(1.0, learned.get(topic, 1.0)))
        else:
            blend = EXPLICIT_BLEND_WEIGHT[profile.age_tier.value]
            for topic in dict.fromkeys(explicit + list(learned)):
                weight = blend * (1.0 if topic in explicit else 0.0) + (1.0 - blend) * learned.get(topic, 0.0)
                if weight > 0.0:
                    weights[topic] = weight

        return {topic: weight for topic, weight in weights.items() if cls.is_topic_allowed(profile, topic)}


def risk_trend_slope(history: Sequence[Dict]) -> float:
    """Least-squares slope of the risk score over the recent feed history (0 if too short)."""
    risks = [float(entry.get("risk") or 0.0) for entry in history]
    count = len(risks)
    if count < 5:
        return 0.0
    mean_x = (count - 1) / 2.0
    mean_y = sum(risks) / count
    denominator = sum((x - mean_x) ** 2 for x in range(count))
    return sum((x - mean_x) * (y - mean_y) for x, y in enumerate(risks)) / denominator


class ProfileRanker:
    """
    Ranks surviving candidate items using relevance similarity, Thompson sampling,
    and anti-radicalization drift guards.
    """

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        bandit: Optional[ThompsonSamplingBandit] = None,
        use_bandit: bool = True,
    ):
        self.embedding_provider = embedding_provider or TfidfEmbeddingProvider()
        self.bandit = bandit or ThompsonSamplingBandit(seed=RANKING_SEED)
        self.use_bandit = use_bandit

    def relevance_scores(self, profile: ViewerProfileModel, candidates: Sequence[RecommendationItemModel]) -> np.ndarray:
        """Cosine similarity between the profile's interest vector and each candidate."""
        weights = TierTopicGuard.interest_weights(profile)
        if not weights or not candidates:
            return np.zeros(len(candidates))
        topics = list(weights)
        item_texts = [f"{' '.join(item_topics(item))} {item.content_text}" for item in candidates]
        self.embedding_provider.fit(item_texts + topics)
        topic_vectors = self.embedding_provider.embed(topics)
        interest_vector = np.array([weights[topic] for topic in topics]) @ topic_vectors
        return cosine_scores(interest_vector, self.embedding_provider.embed(item_texts))

    def _bandit_score(self, profile: ViewerProfileModel, item: RecommendationItemModel) -> float:
        """
        Exploration term. For a child, only topics already in the explicit set are
        sampled; any other topic gets no exploration boost.
        """
        if not self.use_bandit:
            return 0.0
        topic = primary_topic(item)
        if profile.age_tier == AgeTier.CHILD:
            explicit = {normalize_label(t) for t in profile.explicit_interests}
            if topic not in explicit:
                return 0.0
        return self.bandit.sample(f"{profile.age_tier.value}:{topic}")

    def rank_items(
        self,
        profile: ViewerProfileModel,
        candidates: Sequence[RecommendationItemModel],
        limit: int = 10
    ) -> List[RecommendationItemModel]:
        """
        Rank candidate items surviving the safety gate and select up to ``limit`` of them.
        """
        if not candidates or limit <= 0:
            return []

        relevance = self.relevance_scores(profile, candidates)
        window = profile.recent_feed_history[-FEED_HISTORY_WINDOW:]
        trend_rising = risk_trend_slope(window) > RISK_TREND_MIN_SLOPE
        recent_mean_risk = sum(float(e.get("risk") or 0.0) for e in window) / len(window) if window else 0.0

        scored = []
        for index, item in enumerate(candidates):
            score = RELEVANCE_WEIGHT * float(relevance[index]) + BANDIT_WEIGHT * self._bandit_score(profile, item)
            # Drift guard, part 1: when recent feeds trend toward riskier content,
            # penalise items that would continue the trend.
            if trend_rising and (item.toxicity_score or 0.0) > recent_mean_risk:
                score *= RISK_TREND_PENALTY
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].item_id))

        return self._select(profile, scored, limit, window)

    def _select(self, profile, scored, limit, window) -> List[RecommendationItemModel]:
        """Greedy selection applying the borderline-share cap and the adult diversity guard."""
        cap = BORDERLINE_SHARE_CAP[profile.age_tier.value]
        borderline_in_window = sum(1 for entry in window if entry.get("borderline"))
        horizon = len(window) + limit
        interests = set(TierTopicGuard.interest_weights(profile))

        diversity_slots = 0
        if profile.age_tier == AgeTier.ADULT and interests:
            diversity_slots = math.ceil(limit * ADULT_DIVERSITY_MIN)
        familiar_limit = limit - diversity_slots

        selected: List[RecommendationItemModel] = []
        selected_ids: Set[str] = set()
        borderline_selected = 0
        familiar_selected = 0

        def try_add(item: RecommendationItemModel, enforce_diversity: bool) -> None:
            nonlocal borderline_selected, familiar_selected
            if len(selected) >= limit or item.item_id in selected_ids:
                return
            borderline = is_borderline_risk(item)
            # Drift guard, part 2: hard cap on the borderline share of recent feed + this feed.
            if borderline and (borderline_in_window + borderline_selected + 1) / horizon > cap:
                return
            familiar = bool(interests.intersection(item_topics(item)))
            if enforce_diversity and familiar and familiar_selected >= familiar_limit:
                return
            selected.append(item)
            selected_ids.add(item.item_id)
            borderline_selected += borderline
            familiar_selected += familiar

        for _, item in scored:
            try_add(item, enforce_diversity=True)
        # If there were not enough exploratory items to fill the reserved slots, fill up.
        for _, item in scored:
            try_add(item, enforce_diversity=False)
        return selected
