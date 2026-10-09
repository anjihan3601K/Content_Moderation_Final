"""
Feed service: the one place where a recommendation feed is assembled.

Order of operations, which is the safety argument for the whole feature:

1. load the profile and every candidate item;
2. safety gate on the candidate pool;
3. ranking and guards, on gate survivors only;
4. safety gate again on the ranked list, immediately before returning.

There is no parameter, flag or profile field that skips step 2 or step 4.
"""

import logging
import time
from typing import Optional

from recommendation.src.models import FeedResponse, ViewerProfileModel
from recommendation.src.personalization import ProfileRanker, is_borderline_risk
from recommendation.src.safety_gate import SafetyGate, summarize_rejections
from recommendation.src.store import RecommendationRepository
from recommendation.src.telemetry import RecommendationTelemetry, get_telemetry

logger = logging.getLogger(__name__)

MAX_FEED_SIZE = 50


class FeedService:
    """Builds the age-aware personalized feed for one viewer profile."""

    def __init__(
        self,
        repository: RecommendationRepository,
        ranker: Optional[ProfileRanker] = None,
        telemetry: Optional[RecommendationTelemetry] = None,
    ):
        self.repository = repository
        self.ranker = ranker or ProfileRanker()
        self.telemetry = telemetry or get_telemetry()

    def get_feed(self, profile_id: str, limit: int = 10, record_history: bool = True) -> FeedResponse:
        """Return up to ``limit`` items for the profile, gated before and after ranking."""
        limit = max(1, min(MAX_FEED_SIZE, int(limit)))
        started = time.perf_counter()
        with self.telemetry.span("recommendation.feed", profile_id=str(profile_id), limit=limit):
            profile = self.repository.get_profile(profile_id)
            candidates = self.repository.list_items()

            survivors, decisions = SafetyGate.filter_candidate_pool(profile, candidates)
            ranked = self.ranker.rank_items(profile, survivors, limit)
            final_items = SafetyGate.enforce_final_output(profile, ranked)[:limit]

            if record_history:
                self._record_history(profile, final_items)

        rejection_summary = summarize_rejections(decisions)
        tier = profile.age_tier.value
        for reason, count in rejection_summary.items():
            self.telemetry.record_gate_rejections(reason, tier, count)
        self.telemetry.record_feed_latency((time.perf_counter() - started) * 1000.0, tier)
        logger.info(
            f"feed_served profile_id={profile_id} tier={tier} candidates={len(candidates)} "
            f"passed_gate={len(survivors)} served={len(final_items)}"
        )
        return FeedResponse(
            profile_id=profile.profile_id,
            age_tier=profile.age_tier,
            items=final_items,
            total_candidate_count=len(candidates),
            passed_gate_count=len(survivors),
            rejected_count=len(candidates) - len(survivors),
            rejection_summary=rejection_summary,
        )

    def _record_history(self, profile: ViewerProfileModel, items) -> None:
        """Append what was served to the profile's feed history, which feeds the drift guard."""
        if not items:
            return
        profile.recent_feed_history = profile.recent_feed_history + [
            {"item_id": item.item_id, "borderline": is_borderline_risk(item), "risk": item.toxicity_score or 0.0}
            for item in items
        ]
        self.repository.save_profile(profile)
