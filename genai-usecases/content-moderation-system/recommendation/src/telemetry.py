"""
OpenTelemetry spans and metrics for the recommendation feature.

Uses ``opentelemetry-api`` directly (already a pinned dependency of the host project).
The host application does not configure a tracer or meter provider today, so against the
default global providers these calls are no-ops; they start exporting as soon as a
provider is configured, with no change here. Providers can be injected for tests.

Metrics
- ``recommendation.feed.latency``            histogram, ms, by tier
- ``recommendation.gate.rejections``         counter, by reason and tier
- ``recommendation.moderation.decisions``    counter, outcome = accepted | overridden
- ``recommendation.queue.time_to_review``    histogram, seconds, by escalated
"""

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from opentelemetry import metrics, trace

INSTRUMENTATION_NAME = "recommendation"


class RecommendationTelemetry:
    """Tracer and metric instruments for the feature."""

    def __init__(self, tracer_provider: Optional[Any] = None, meter_provider: Optional[Any] = None):
        self.tracer = trace.get_tracer(INSTRUMENTATION_NAME, tracer_provider=tracer_provider)
        meter = metrics.get_meter(INSTRUMENTATION_NAME, meter_provider=meter_provider)
        self.feed_latency = meter.create_histogram(
            "recommendation.feed.latency", unit="ms", description="Time to build a feed"
        )
        self.gate_rejections = meter.create_counter(
            "recommendation.gate.rejections", description="Items rejected by the safety gate"
        )
        self.moderation_decisions = meter.create_counter(
            "recommendation.moderation.decisions", description="Moderator decisions versus agent verdict"
        )
        self.time_to_review = meter.create_histogram(
            "recommendation.queue.time_to_review", unit="s", description="Queue entry to moderator decision"
        )

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Any]:
        """Start a span with the given attributes."""
        with self.tracer.start_as_current_span(name) as current:
            for key, value in attributes.items():
                current.set_attribute(key, value)
            yield current

    def record_feed_latency(self, milliseconds: float, tier: str) -> None:
        self.feed_latency.record(milliseconds, {"tier": tier})

    def record_gate_rejections(self, reason: str, tier: str, count: int = 1) -> None:
        self.gate_rejections.add(count, {"reason": reason, "tier": tier})

    def record_moderation_decision(self, overridden: bool) -> None:
        self.moderation_decisions.add(1, {"outcome": "overridden" if overridden else "accepted"})

    def record_time_to_review(self, seconds: float, escalated: bool) -> None:
        self.time_to_review.record(max(0.0, seconds), {"escalated": escalated})


_default: Optional[RecommendationTelemetry] = None


def get_telemetry() -> RecommendationTelemetry:
    """The process-wide instance bound to the global OpenTelemetry providers."""
    global _default
    if _default is None:
        _default = RecommendationTelemetry()
    return _default
