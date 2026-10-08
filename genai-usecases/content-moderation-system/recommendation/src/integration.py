"""
Hook between the host moderation workflow and the recommendation feature.

``backend/src/agents/workflow.py`` calls ``on_moderation_complete`` once the graph has
finished. It attaches the audience rating to the state and, when a repository has been
registered, stores the rated item so the feed and the moderator queue can see it.
"""

import logging
from typing import Any, Dict, Optional

from recommendation.src import rating
from recommendation.src.config import BLOCKED_STATUSES
from recommendation.src.models import AudienceRating, normalize_enum_value
from recommendation.src.store import RecommendationRepository

logger = logging.getLogger(__name__)

_repository: Optional[RecommendationRepository] = None


def set_repository(repository: Optional[RecommendationRepository]) -> None:
    """Register the repository that moderated items are stored in (None to clear)."""
    global _repository
    _repository = repository


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
    if result is None or _repository is None:
        return
    content_id = state.get("content_id")
    if not isinstance(content_id, str) or not content_id.strip():
        logger.error("Rated item has no content_id; not stored")
        return
    try:
        item = rating.build_item_from_state(state)
        existing = _repository.get_item(content_id)
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
        _repository.upsert_item(item)
    except Exception as error:
        logger.error(f"Could not store rated item {content_id}: {error}")
