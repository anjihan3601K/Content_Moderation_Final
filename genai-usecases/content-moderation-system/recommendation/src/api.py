"""
Stage 3: HTTP endpoints for the recommendation feature.

Follows the host API's conventions: ``/api/<area>/...`` paths without a version segment,
``HTTPException`` for errors, and the host's own authentication dependencies, which are
passed in by ``backend/main.py``. Nothing here authenticates anyone by itself.

    GET  /api/recommendations/feed
    GET  /api/profiles/{profile_id}/preferences
    PUT  /api/profiles/{profile_id}/preferences
    GET  /api/moderation/queue/next
    GET  /api/items/{item_id}/recommendation
    POST /api/recommendations/feedback
"""

import logging
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query

from recommendation.src.bandit import ThompsonSamplingBandit
from recommendation.src.config import ADMIN_ROLE, RANKING_SEED, SENIOR_MODERATOR_ROLES, recommendation_db_path
from recommendation.src.feedback import FeedbackService, ItemNotFoundError
from recommendation.src.integration import set_repository
from recommendation.src.models import (
    AgeTier,
    EventType,
    FeedbackEvent,
    FeedbackResponse,
    FeedResponse,
    PreferencesResponse,
    PreferencesUpdateRequest,
    QueueResponse,
    RecommendationDetailResponse,
    ViewerProfileModel,
)
from recommendation.src.moderator_queue import (
    PrecedentRetriever,
    ReviewQueuePrioritizer,
    is_escalated,
    item_category,
)
from recommendation.src.personalization import InterestNotAllowedError, ProfileRanker, TierTopicGuard
from recommendation.src.safety_gate import TIER_RANK
from recommendation.src.service import FeedService
from recommendation.src.store import (
    DualDocumentStore,
    FirestoreDocumentStore,
    RecommendationRepository,
    SQLiteDocumentStore,
)

logger = logging.getLogger(__name__)

AuthDependency = Callable[..., Dict[str, Any]]


class RecommendationContainer:
    """The feature's services, built once around one repository."""

    def __init__(self, repository: RecommendationRepository, seed: int = RANKING_SEED):
        self.repository = repository
        arms = repository.load_bandit_arms()
        self.feed_bandit = ThompsonSamplingBandit(seed=seed, arms=arms, on_update=repository.save_bandit_arm)
        self.queue_bandit = ThompsonSamplingBandit(seed=seed, arms=arms, on_update=repository.save_bandit_arm)
        self.feed_service = FeedService(repository, ProfileRanker(bandit=self.feed_bandit))
        self.feedback_service = FeedbackService(repository, self.feed_bandit, self.queue_bandit)
        self.prioritizer = ReviewQueuePrioritizer(self.queue_bandit)
        self.precedents = PrecedentRetriever()


def build_container(firestore_client: Optional[Any] = None, db_path: Optional[str] = None) -> RecommendationContainer:
    """Build the services on SQLite, mirrored to Firestore when a client is supplied."""
    sqlite_store = SQLiteDocumentStore(db_path or recommendation_db_path())
    firestore_store = FirestoreDocumentStore(firestore_client) if firestore_client is not None else None
    return RecommendationContainer(RecommendationRepository(DualDocumentStore(sqlite_store, firestore_store)))


def _preferences(profile: ViewerProfileModel) -> PreferencesResponse:
    allowed = TierTopicGuard.allowed_topics(profile)
    return PreferencesResponse(
        profile_id=profile.profile_id,
        age_tier=profile.age_tier,
        age_trust_level=profile.age_trust_level,
        tier_declared=profile.tier_declared,
        explicit_interests=profile.explicit_interests,
        learned_interests=profile.learned_interests,
        parental_controls=profile.parental_controls,
        allowed_topics=sorted(allowed) if allowed is not None else None,
    )


def create_recommendation_router(
    get_current_user: AuthDependency,
    get_moderator: AuthDependency,
    get_container: Callable[[], RecommendationContainer],
) -> APIRouter:
    """Create the router. The two auth dependencies are the host application's own."""
    router = APIRouter(tags=["recommendations"])

    def own_profile_or_admin(profile_id: str, user: Dict[str, Any]) -> None:
        if str(user["user_id"]) != str(profile_id) and user["role"] != ADMIN_ROLE:
            raise HTTPException(status_code=403, detail="You can only access your own profile")

    @router.get("/api/recommendations/feed", response_model=FeedResponse)
    async def get_feed(
        limit: int = Query(10, ge=1, le=50, description="Number of items"),
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """Age-aware personalized feed for the authenticated user's profile."""
        try:
            return get_container().feed_service.get_feed(str(user["user_id"]), limit)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error building feed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/profiles/{profile_id}/preferences", response_model=PreferencesResponse)
    async def get_preferences(profile_id: str, user: Dict[str, Any] = Depends(get_current_user)):
        """Explicit interests and parental controls of a profile (owner or admin)."""
        own_profile_or_admin(profile_id, user)
        try:
            return _preferences(get_container().repository.get_profile(profile_id))
        except Exception as e:
            logger.error(f"Error reading preferences: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.put("/api/profiles/{profile_id}/preferences", response_model=PreferencesResponse)
    async def update_preferences(
        profile_id: str,
        request: PreferencesUpdateRequest,
        user: Dict[str, Any] = Depends(get_current_user),
    ):
        """
        Update a profile's preferences, validated against its age tier.

        The owner may set explicit interests, and may declare an age tier once or lower
        it later. Raising a declared tier, changing the trust level and changing parental
        controls are admin-only.
        """
        own_profile_or_admin(profile_id, user)
        is_admin = user["role"] == ADMIN_ROLE
        try:
            repository = get_container().repository
            profile = repository.get_profile(profile_id)

            if (request.age_trust_level is not None or request.parental_controls is not None) and not is_admin:
                raise HTTPException(status_code=403, detail="Only an admin can change trust level or parental controls")
            if request.age_tier is not None and request.age_tier != profile.age_tier:
                raising = TIER_RANK[request.age_tier] > TIER_RANK[profile.age_tier]
                if raising and profile.tier_declared and not is_admin:
                    raise HTTPException(status_code=403, detail="Only an admin can raise a declared age tier")
            if request.age_tier is not None:
                profile.age_tier = request.age_tier
                profile.tier_declared = True
            if request.age_trust_level is not None:
                profile.age_trust_level = request.age_trust_level
            if request.parental_controls is not None:
                profile.parental_controls = request.parental_controls

            # Interests are validated against the tier and controls as they are after this
            # update, so lowering a tier or adding a block also re-checks the existing list.
            interests = request.explicit_interests if request.explicit_interests is not None else profile.explicit_interests
            try:
                profile.explicit_interests = TierTopicGuard.validate_explicit_interests(profile, interests)
            except InterestNotAllowedError as error:
                if request.explicit_interests is not None:
                    raise HTTPException(
                        status_code=422,
                        detail={"message": "Interests not allowed for this age tier", "rejected": error.rejected},
                    )
                profile.explicit_interests = [t for t in interests if TierTopicGuard.is_topic_allowed(profile, t)]
            profile.learned_interests = {
                topic: weight for topic, weight in profile.learned_interests.items()
                if TierTopicGuard.is_topic_allowed(profile, topic)
                and (profile.age_tier != AgeTier.CHILD or topic in profile.explicit_interests)
            }
            repository.save_profile(profile)
            return _preferences(profile)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating preferences: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/moderation/queue/next", response_model=QueueResponse)
    async def get_next_in_queue(
        limit: int = Query(10, ge=1, le=100, description="Number of items"),
        user: Dict[str, Any] = Depends(get_moderator),
    ):
        """Prioritized review queue. Escalated items are returned only to senior roles."""
        try:
            container = get_container()
            queue = container.prioritizer.prioritize_queue(container.repository.list_items())
            withheld = 0
            if user["role"] not in SENIOR_MODERATOR_ROLES:
                withheld = sum(1 for entry in queue if entry.requires_senior_moderator)
                queue = [entry for entry in queue if not entry.requires_senior_moderator]
            return QueueResponse(items=queue[:limit], queue_length=len(queue), escalated_withheld=withheld)
        except Exception as e:
            logger.error(f"Error building review queue: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/items/{item_id}/recommendation", response_model=RecommendationDetailResponse)
    async def get_item_recommendation(
        item_id: str,
        k: int = Query(3, ge=1, le=10, description="Number of precedent cases"),
        user: Dict[str, Any] = Depends(get_moderator),
    ):
        """Suggested moderator action for an item, with the most similar resolved cases."""
        try:
            container = get_container()
            item = container.repository.get_item(item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Item not found")
            escalated = is_escalated(item)
            if escalated and user["role"] not in SENIOR_MODERATOR_ROLES:
                raise HTTPException(status_code=403, detail="Senior moderator access required")
            precedents = container.precedents.get_similar_precedents(item, container.repository.list_precedents(), k)
            action, confidence, source = container.precedents.suggest_action(item, precedents)
            return RecommendationDetailResponse(
                item_id=item.item_id,
                content_text=item.content_text,
                category=item_category(item),
                suggested_action=action,
                confidence=confidence,
                suggestion_source=source,
                audience_rating=item.audience_rating,
                is_escalated=escalated,
                precedents=precedents,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error building item recommendation: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/recommendations/feedback", response_model=FeedbackResponse)
    async def post_feedback(event: FeedbackEvent, user: Dict[str, Any] = Depends(get_current_user)):
        """
        Engagement events from viewers and moderator overrides of agent verdicts.

        A ``moderator_override`` requires a moderator role (the same check as
        ``get_moderator``), and a senior role when the item is escalated.
        """
        try:
            container = get_container()
            if event.event_type == EventType.MODERATOR_OVERRIDE:
                get_moderator(user)
                if event.final_action is None:
                    raise HTTPException(status_code=422, detail="final_action is required for moderator_override")
                item = container.repository.get_item(event.item_id)
                if item is not None and is_escalated(item) and user["role"] not in SENIOR_MODERATOR_ROLES:
                    raise HTTPException(status_code=403, detail="Senior moderator access required")
                return container.feedback_service.handle_override(event, str(user["user_id"]))
            return container.feedback_service.handle_engagement(event, str(user["user_id"]))
        except HTTPException:
            raise
        except ItemNotFoundError:
            raise HTTPException(status_code=404, detail="Item not found")
        except Exception as e:
            logger.error(f"Error recording feedback: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router


def register_recommendation_routes(
    app: FastAPI,
    get_current_user: AuthDependency,
    get_moderator: AuthDependency,
    firestore_client_provider: Optional[Callable[[], Any]] = None,
) -> None:
    """
    Add the recommendation endpoints to the host application.

    Called by ``backend/main.py`` only when ``RECOMMENDATION_ENABLED`` is true. Storage is
    opened on first use, because the host creates its database connections at startup,
    after routes are registered.
    """
    state: Dict[str, RecommendationContainer] = {}

    def get_container() -> RecommendationContainer:
        if "container" not in state:
            client = firestore_client_provider() if firestore_client_provider else None
            state["container"] = build_container(firestore_client=client)
            set_repository(state["container"].repository)
        return state["container"]

    app.include_router(create_recommendation_router(get_current_user, get_moderator, get_container))
    logger.info("Recommendation endpoints registered")
