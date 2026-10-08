"""
Hook between the host moderation workflow and the recommendation feature.

``backend/src/agents/workflow.py`` calls ``on_moderation_complete`` once the graph has
finished. It attaches the audience rating to the state and, when a repository has been
registered, stores the rated item so the feed and the moderator queue can see it.
"""

import logging
from typing import Any, Dict, Optional

from recommendation.src import rating
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

    Does nothing when the feature flag is off. Storage failures are logged and swallowed:
    an item that could not be stored is simply absent from feeds, which is the safe side.
    """
    result = rating.apply_audience_rating(state)
    if result is None or _repository is None:
        return
    try:
        _repository.upsert_item(rating.build_item_from_state(state))
    except Exception as error:
        logger.error(f"Could not store rated item {state.get('content_id')}: {error}")
