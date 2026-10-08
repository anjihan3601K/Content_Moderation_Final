"""
Stage 3: Feedback loop.

Two kinds of signal:
- engagement events from viewers, which update the profile's learned interests and the
  feed bandit, inside the tier rules;
- moderator overrides of agent verdicts, which are the reward for the queue bandit and
  are appended to the precedent memory.

Neither can change what the safety gate allows.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.config import ENGAGEMENT_REWARDS
from recommendation.src.models import (
    AudienceRating,
    EventType,
    FeedbackEvent,
    FeedbackResponse,
    ModeratorAction,
    PrecedentCase,
    RecommendationItemModel,
    _now_iso,
)
from recommendation.src.moderator_queue import is_escalated, item_category, queue_arm_key, rule_based_suggestion
from recommendation.src.personalization import TierTopicGuard, primary_topic
from recommendation.src.safety_gate import SafetyGate
from recommendation.src.store import RecommendationRepository
from recommendation.src.telemetry import RecommendationTelemetry, get_telemetry

logger = logging.getLogger(__name__)

OVERRIDE_REWARD = 1.0
AGREEMENT_REWARD = -0.5

# Status an item takes after a moderator's final action.
STATUS_AFTER_ACTION = {
    ModeratorAction.APPROVE: "approved",
    ModeratorAction.WARN: "warned",
    ModeratorAction.REMOVE: "removed",
    ModeratorAction.ESCALATE: "escalated",
}


class ItemNotFoundError(LookupError):
    """The feedback refers to an item the recommender does not know."""


class FeedbackService:
    """Applies engagement events and moderator overrides."""

    def __init__(
        self,
        repository: RecommendationRepository,
        feed_bandit: ThompsonSamplingBandit,
        queue_bandit: ThompsonSamplingBandit,
        telemetry: Optional[RecommendationTelemetry] = None,
    ):
        self.repository = repository
        self.feed_bandit = feed_bandit
        self.queue_bandit = queue_bandit
        self.telemetry = telemetry or get_telemetry()

    def _item(self, item_id: str) -> RecommendationItemModel:
        item = self.repository.get_item(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        return item

    def handle_engagement(self, event: FeedbackEvent, profile_id: str) -> FeedbackResponse:
        """
        Record an engagement event and learn from it.

        Learning happens only when the item is one the gate would serve to this profile.
        Engagement with anything else (for example a child interacting with an item that
        reached them outside the feed) is recorded but teaches the recommender nothing.
        """
        item = self._item(event.item_id)
        profile = self.repository.get_profile(profile_id)
        reward = ENGAGEMENT_REWARDS[event.event_type.value]
        servable = SafetyGate.evaluate_item(profile, item).passed

        self.repository.record_event(str(uuid.uuid4()), {
            "event_type": event.event_type.value, "item_id": item.item_id, "profile_id": str(profile_id),
            "learned_from": servable, "timestamp": _now_iso(),
        })
        if not servable:
            logger.info(f"engagement_ignored profile_id={profile_id} item_id={item.item_id} reason=not_servable")
            return FeedbackResponse(
                accepted=True, event_type=event.event_type, item_id=item.item_id,
                detail="Recorded. Not used for learning: the item is not servable to this profile.",
            )

        topic = primary_topic(item)
        if reward != 0.0:
            updated = TierTopicGuard.update_learned_interests(profile, topic, reward)
            if updated != profile.learned_interests:
                profile.learned_interests = updated
                self.repository.save_profile(profile)
            if TierTopicGuard.is_topic_allowed(profile, topic):
                self.feed_bandit.update(f"{profile.age_tier.value}:{topic}", reward)
        return FeedbackResponse(
            accepted=True, event_type=event.event_type, item_id=item.item_id, detail="Recorded.",
        )

    def handle_override(self, event: FeedbackEvent, moderator_id: str) -> FeedbackResponse:
        """
        Record a moderator's final action on an item.

        Compares it with the agent verdict (supplied, or derived from the agents' signals),
        updates the queue bandit, appends a precedent, updates the item's status and
        records time-to-review.
        """
        if event.final_action is None:
            raise ValueError("final_action is required for a moderator_override event")
        item = self._item(event.item_id)
        agent_verdict = (event.original_verdict or rule_based_suggestion(item)[0]).strip().lower()
        final_action = event.final_action
        overridden = agent_verdict != final_action.value
        escalated = is_escalated(item)

        self.queue_bandit.update(
            queue_arm_key(item_category(item)), OVERRIDE_REWARD if overridden else AGREEMENT_REWARD
        )
        self.repository.add_precedent(PrecedentCase(
            case_id=f"case-{uuid.uuid4().hex[:12]}",
            content_id=item.item_id,
            category=item_category(item),
            topics=list(item.content_topics),
            agent_verdict=agent_verdict,
            final_human_action=final_action.value,
            moderator_notes=event.notes,
            override_occurred=overridden,
        ))

        seconds_in_queue = self._seconds_since(item.created_at)
        item.status = STATUS_AFTER_ACTION[final_action]
        if final_action == ModeratorAction.REMOVE:
            item.audience_rating = AudienceRating.BLOCKED
        elif final_action == ModeratorAction.APPROVE and item.audience_rating == AudienceRating.BLOCKED:
            # A human approval lifts a block, but never below adult: the agents' signals
            # that produced the block are still on the item.
            item.audience_rating = AudienceRating.ADULT
        self.repository.upsert_item(item)

        self.repository.record_event(str(uuid.uuid4()), {
            "event_type": EventType.MODERATOR_OVERRIDE.value, "item_id": item.item_id,
            "moderator_id": str(moderator_id), "agent_verdict": agent_verdict,
            "final_action": final_action.value, "override_occurred": overridden, "timestamp": _now_iso(),
        })
        self.telemetry.record_moderation_decision(overridden)
        if seconds_in_queue is not None:
            self.telemetry.record_time_to_review(seconds_in_queue, escalated)
        logger.info(
            f"moderator_decision item_id={item.item_id} agent={agent_verdict} final={final_action.value} "
            f"overridden={overridden} escalated={escalated}"
        )
        return FeedbackResponse(
            accepted=True, event_type=event.event_type, item_id=item.item_id,
            detail="Override recorded." if overridden else "Decision recorded; it matches the agent verdict.",
            override_occurred=overridden,
        )

    @staticmethod
    def _seconds_since(created_at: str) -> Optional[float]:
        try:
            created = datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds()
