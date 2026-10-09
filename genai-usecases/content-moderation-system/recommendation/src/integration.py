"""
Hook between the host moderation workflow and the recommendation feature.

``backend/src/agents/workflow.py`` calls ``on_moderation_complete`` once the graph has
finished. It attaches the audience rating to the state and, when a repository has been
registered, stores the rated item so the feed and the moderator queue can see it.
"""

import logging
from typing import Any, Callable, Dict, Optional

from recommendation.src import rating
from recommendation.src.config import BLOCKED_STATUSES
from recommendation.src.models import AudienceRating, normalize_enum_value
from recommendation.src.store import RecommendationRepository

logger = logging.getLogger(__name__)

_repository: Optional[RecommendationRepository] = None
_container_provider: Optional[Callable[[], Any]] = None


def set_repository(repository: Optional[RecommendationRepository]) -> None:
    """Register the repository that moderated items are stored in (None to clear)."""
    global _repository
    _repository = repository


def set_container_provider(provider: Optional[Callable[[], Any]]) -> None:
    """
    Register a function returning the feature's service container (None to clear).

    The container opens its storage on first use, so registering the provider at startup
    lets the workflow hook store items even before any recommendation endpoint is called.
    """
    global _container_provider
    _container_provider = provider


def _current_repository() -> Optional[RecommendationRepository]:
    if _repository is not None:
        return _repository
    return _container_provider().repository if _container_provider is not None else None


def on_moderation_complete(state: Dict[str, Any]) -> None:
    """
    Rate a final pipeline state and store the item.

    A moderator's decision takes precedence over a later machine rating: if a human has
    already removed the item it is left as it is, and otherwise a re-run can make a
    human-reviewed item stricter but never more permissive.

    Does nothing when the feature flag is off. Storage failures are logged and swallowed
    so they cannot affect moderation. Two consequences to know: a new item that could
    not be stored is absent from feeds, but an item stored earlier keeps its earlier
    rating until a later run succeeds; and items moderated while the flag is off are not
    updated, so ``rec_items`` should be rebuilt after the flag has been off for a while.
    """
    result = rating.apply_audience_rating(state)
    if result is None:
        return
    try:
        repository = _current_repository()
    except Exception as error:
        logger.error(f"Recommendation storage unavailable: {error}")
        return
    if repository is None:
        return
    content_id = state.get("content_id")
    if not isinstance(content_id, str) or not content_id.strip():
        logger.error("Rated item has no content_id; not stored")
        return
    try:
        item = rating.build_item_from_state(state)
        existing = repository.get_item(content_id)
        if existing is not None and existing.human_reviewed:
            existing_status = normalize_enum_value(existing.status) if existing.status else ""
            if existing_status in BLOCKED_STATUSES or existing.audience_rating == AudienceRating.BLOCKED:
                logger.info(f"Item {content_id} was removed by a moderator; machine re-rating ignored")
                return
            item.human_reviewed = True
            item.escalated = item.escalated or existing.escalated
            if item.audience_rating is None or (
                existing.audience_rating is not None
                and rating.RATING_RANK[existing.audience_rating] > rating.RATING_RANK[item.audience_rating]
            ):
                item.audience_rating = existing.audience_rating
        repository.upsert_item(item)
    except Exception as error:
        logger.error(f"Could not store rated item {content_id}: {error}")


MANUAL_REVIEW_ACTIONS = ("approve", "warn", "remove", "escalate")


def on_manual_review(content: Dict[str, Any], decision: str, reviewer: str = "moderator") -> bool:
    """
    Tell the recommender about a decision made through the host's manual-review endpoints,
    which update only the moderation database.

    The decision is applied exactly like a moderator decision sent to the feedback
    endpoint: it marks the item human-reviewed, updates its status, records a precedent,
    and an approval makes the item servable to adults at most. Rating an item for teens or
    children takes a full pipeline run, because that needs the agents' topic and safety
    signals. An item the recommender has never seen is created from the content row,
    unrated, before the decision is applied.

    Returns True when the decision was applied. Never raises.
    """
    from recommendation.src.config import is_recommendation_enabled
    from recommendation.src.models import FeedbackEvent, RecommendationItemModel

    if not is_recommendation_enabled() or _container_provider is None:
        return False
    action = str(decision or "").strip().lower()
    content_id = content.get("content_id") if isinstance(content, dict) else None
    if action not in MANUAL_REVIEW_ACTIONS or not isinstance(content_id, str) or not content_id.strip():
        return False
    try:
        container = _container_provider()
        if container.repository.get_item(content_id) is None:
            container.repository.upsert_item(RecommendationItemModel(
                item_id=content_id,
                content_text=str(content.get("content_text") or ""),
                status=content.get("current_status") or content.get("status"),
                toxicity_score=content.get("toxicity_score"),
            ))
        container.feedback_service.handle_override(
            FeedbackEvent(event_type="moderator_override", item_id=content_id, final_action=action,
                          notes=f"Manual review by {reviewer}"[:2000]),
            moderator_id=str(reviewer),
        )
        return True
    except Exception as error:
        logger.error(f"Could not apply manual review of {content_id} to the recommender: {error}")
        return False
