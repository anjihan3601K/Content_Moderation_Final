"""
Pydantic schemas and models for the Age-Gated Recommendation & Queue Prioritizer system.
"""

import re
import unicodedata
from functools import lru_cache
from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def normalize_label(value: Any) -> str:
    """
    Normalise a category, topic, status or violation label for comparison.

    Unicode compatibility forms are folded, case is folded, invisible format characters
    are dropped and every run of separators or punctuation becomes one underscore, so
    "Self-Harm", "self  harm" and "self/harm" all compare equal to "self_harm".
    """
    return _normalize_text(str(value))


@lru_cache(maxsize=8192)
def _normalize_text(text: str) -> str:
    """Cached worker for ``normalize_label``; labels repeat heavily across items."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return re.sub(r"[\W_]+", "_", text).strip("_")


def normalize_enum_value(value: Any) -> str:
    """
    Normalise a value that must be one of a fixed set (status, severity, verdict, rating).

    Only case, surrounding whitespace and the space/hyphen/underscore choice are forgiven.
    Punctuation is kept, so "!none" or "safe?" do not read as "none" or "safe".
    """
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


_STOP_WORDS = frozenset({"for", "and", "the", "of", "a", "an", "to", "in", "on", "with"})


def label_stems(value: Any) -> frozenset:
    """
    Word stems of a label, for matching a parent's wording against topic names.

    "games", "gaming" and "game" share a stem, as do "sport" and "sports"; filler words
    are dropped, so "music for kids" has the same stems as "music_kids".
    """
    stems = set()
    for token in normalize_label(value).split("_"):
        if not token or token in _STOP_WORDS:
            continue
        for suffix in ("ing", "es", "s", "e"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                token = token[: -len(suffix)]
                break
        stems.add(token)
    return frozenset(stems)


def label_matches(blocked: Any, label: Any) -> bool:
    """
    True when every word of the blocked label appears in the label, compared by stem and
    in any order, so "games" blocks "gaming_family" and "kids music" blocks "music_kids".
    """
    blocked_stems = label_stems(blocked)
    return bool(blocked_stems) and blocked_stems <= label_stems(label)


class AgeTier(str, Enum):
    CHILD = "child"
    TEEN = "teen"
    ADULT = "adult"


class AgeTrustLevel(str, Enum):
    SELF_DECLARED = "self_declared"
    PARENT_LINKED = "parent_linked"
    VERIFIED = "verified"


class AudienceRating(str, Enum):
    """Mirrors ``AudienceRating`` in backend/src/core/models.py (same string values)."""

    ALL_AGES = "all_ages"
    TEEN = "teen"
    ADULT = "adult"
    BLOCKED = "blocked"


class Strictness(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    STRICT = "strict"


class GateReason(str, Enum):
    """Why the safety gate rejected an item."""

    BLOCKED = "blocked"
    NOT_SERVABLE_STATUS = "not_servable_status"
    UNRATED = "unrated"
    PARENTAL_BLOCK = "parental_block"
    ESCALATION = "escalation"
    ABOVE_TIER = "above_tier"
    TOXICITY = "toxicity"
    UNLISTED_TOPIC = "unlisted_topic"
    POLICY_VIOLATION = "policy_violation"
    INVALID = "invalid"
    PENDING_REVIEW = "pending_review"
    HIGH_UNCERTAINTY = "high_uncertainty"
    MISSING_SIGNALS = "missing_signals"
    SENSITIVE_TOPIC = "sensitive_topic"
    BORDERLINE = "borderline"


class ParentalControls(BaseModel):
    """
    Restrictions set by a parent or admin.

    Every field narrows what the gate allows, with one deliberate exception:
    ``allowed_sensitive_topics`` lets a teen see teen-rated sensitive topics. It has no
    effect for a child and can never lift an item above the viewer's tier.
    """

    model_config = ConfigDict(validate_assignment=True)

    blocked_categories: List[str] = Field(default_factory=list, description="Categories, topics or violation labels to hide")
    strictness_level: Strictness = Field(Strictness.LOW, description="low (no extra restriction), medium, strict")
    max_rating: Optional[AudienceRating] = Field(None, description="Highest rating the viewer may see")
    allowed_sensitive_topics: List[str] = Field(default_factory=list, description="Sensitive teen topics a parent has allowed")
    require_parent_approval_for_sensitive: bool = True

    @field_validator("blocked_categories", "allowed_sensitive_topics")
    @classmethod
    def _labels_must_be_plain_text(cls, values: List[str]) -> List[str]:
        """Reject look-alike characters that would make a block silently match nothing."""
        for value in values:
            if not normalize_label(value) or not normalize_label(value).isascii():
                raise ValueError(f"label must be non-empty plain ASCII text: {value!r}")
            if not label_stems(value):
                raise ValueError(f"label has no meaningful word and would match nothing: {value!r}")
        return values


class ViewerProfileModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = Field(..., description="Unique viewer profile ID")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    age_tier: AgeTier = Field(AgeTier.ADULT, description="child, teen, adult")
    age_trust_level: AgeTrustLevel = Field(AgeTrustLevel.SELF_DECLARED)
    explicit_interests: List[str] = Field(default_factory=list)
    learned_interests: Dict[str, float] = Field(default_factory=dict)  # topic -> weight (0.0 to 1.0)
    parental_controls: ParentalControls = Field(default_factory=ParentalControls)
    recent_feed_history: List[Dict[str, Any]] = Field(default_factory=list)  # history of served items for drift guard
    tier_declared: bool = Field(False, description="True once an age tier has been explicitly set")
    record_damaged: bool = Field(
        False, description="Set when the stored record could not be read; only an admin can repair it"
    )
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("learned_interests")
    @classmethod
    def _weights_in_unit_range(cls, weights: Dict[str, float]) -> Dict[str, float]:
        for topic, weight in weights.items():
            if not (0.0 <= weight <= 1.0):
                raise ValueError(f"learned interest weight out of range for {topic!r}")
        return weights


class PreferencesUpdateRequest(BaseModel):
    """Body of PUT /api/profiles/{id}/preferences. Omitted fields are left unchanged."""

    explicit_interests: Optional[List[str]] = Field(None, max_length=20, description="Validated against the tier's topic list")
    age_tier: Optional[AgeTier] = Field(None, description="Self-declared tier; raising it later needs an admin")
    age_trust_level: Optional[AgeTrustLevel] = Field(None, description="Admin only")
    parental_controls: Optional[ParentalControls] = Field(None, description="Admin only")


class PreferencesResponse(BaseModel):
    profile_id: str
    age_tier: AgeTier
    age_trust_level: AgeTrustLevel
    tier_declared: bool
    explicit_interests: List[str]
    learned_interests: Dict[str, float]
    parental_controls: ParentalControls
    allowed_topics: Optional[List[str]] = Field(None, description="Topics this tier may select; None means free choice")


class RecommendationItemModel(BaseModel):
    """
    A candidate item as the recommender sees it.

    Safety-relevant fields default to "unknown" (None), never to a safe-looking value:
    the gate withholds items with unknown rating, status or confidence signals from
    child and teen viewers. ``escalated`` and ``is_borderline`` can only add restrictions;
    the gate also checks the item's labels itself and does not rely on them.
    """

    model_config = ConfigDict(validate_assignment=True)

    item_id: str
    content_text: str = ""
    content_category: Optional[str] = None
    content_topics: List[str] = Field(default_factory=list)
    policy_violations: List[str] = Field(default_factory=list)
    audience_rating: Optional[AudienceRating] = Field(None, description="None means unrated (legacy)")
    toxicity_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    overall_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    agent_disagreement: Optional[float] = Field(None, ge=0.0, le=1.0, description="1 - agent consensus")
    agent_confidence_scores: Dict[str, float] = Field(default_factory=dict)
    status: Optional[str] = Field(None, description="ContentStatus value; None means unknown")
    is_borderline: bool = False
    escalated: bool = False
    human_reviewed: bool = Field(False, description="A moderator has decided on this item")
    tags_source: str = Field("pipeline", description="Who set category and topics: pipeline or moderator")
    audience_tags: List[str] = Field(default_factory=list, description="Moderator's audience tags (child, teen, 18_plus); they only raise the rating")
    exposure_count: int = Field(0, ge=0)
    created_at: str = Field(default_factory=_now_iso)

    @field_validator("audience_rating", mode="before")
    @classmethod
    def _unknown_rating_is_unrated(cls, value: Any) -> Any:
        """A rating string this module does not recognise is treated as unrated."""
        if value is None or isinstance(value, AudienceRating):
            return value
        try:
            return AudienceRating(normalize_enum_value(value))
        except ValueError:
            return None

    @field_validator("toxicity_score", "overall_confidence", "agent_disagreement", mode="before")
    @classmethod
    def _unusable_number_is_unknown(cls, value: Any) -> Any:
        """NaN and anything that is not already a number are treated as a missing signal."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
        except OverflowError:
            return None
        return None if number != number else number


class GateDecision(BaseModel):
    item_id: str
    passed: bool
    rejection_reason: Optional[GateReason] = None
    safety_margin_applied: bool = False


class FeedResponse(BaseModel):
    profile_id: str
    age_tier: AgeTier
    items: List[RecommendationItemModel]
    total_candidate_count: int
    passed_gate_count: int
    rejected_count: int
    rejection_summary: Dict[str, int]


class PrioritizedQueueItem(BaseModel):
    content_id: str
    content_text: str
    category: str
    priority_score: float
    expected_harm: float
    agent_disagreement: float = Field(..., description="Uncertainty used in the score: max(disagreement, 1 - confidence)")
    exposure_score: float
    learned_multiplier: float = Field(1.0, description="Adjustment learned from moderator overrides")
    audience_rating: Optional[AudienceRating] = None
    status: str
    is_escalated: bool
    requires_senior_moderator: bool
    created_at: str


class QueueResponse(BaseModel):
    items: List[PrioritizedQueueItem]
    queue_length: int
    escalated_withheld: int = Field(0, description="Escalated items hidden because the caller is not a senior role")


class PrecedentCase(BaseModel):
    case_id: str
    content_id: str
    category: str
    topics: List[str] = Field(default_factory=list)
    is_escalated: bool = Field(False, description="The case concerned a high-risk escalation category")
    similarity_score: float = 0.0
    agent_verdict: str
    final_human_action: str  # approve, remove, warn, escalate
    moderator_notes: str = ""
    override_occurred: bool
    resolved_at: str = Field(default_factory=_now_iso)


class AudienceSuitability(BaseModel):
    """Whether a verified viewer of one age tier, with no parental controls, would be served the item."""

    age_tier: AgeTier
    served: bool
    reason: Optional[GateReason] = Field(None, description="Why it is withheld, when it is")


class RecommendationDetailResponse(BaseModel):
    item_id: str
    content_text: str
    category: str
    content_topics: List[str] = Field(default_factory=list)
    policy_violations: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    toxicity_score: Optional[float] = None
    agent_disagreement: Optional[float] = None
    overall_confidence: Optional[float] = None
    human_reviewed: bool = False
    tags_source: str = "pipeline"
    audience_tags: List[str] = Field(default_factory=list, description="Audience tags set by a moderator")
    known_topics: List[str] = Field(default_factory=list, description="Topics that have an age-group list")
    audience_tag_options: List[str] = Field(default_factory=list, description="Audience tags a moderator can set")
    suitable_for: List[AudienceSuitability] = Field(default_factory=list)
    suggested_action: str
    confidence: float
    suggestion_source: str = Field(..., description="precedents or rules")
    audience_rating: Optional[AudienceRating] = None
    is_escalated: bool
    precedents: List[PrecedentCase]


class ItemTagsRequest(BaseModel):
    """Body of PUT /api/items/{id}/tags. The first tag becomes the item's category."""

    topics: List[str] = Field(..., min_length=1, max_length=10, description="Tags chosen by the moderator")

    @field_validator("topics")
    @classmethod
    def _tags_must_be_plain_text(cls, values: List[str]) -> List[str]:
        cleaned = []
        for value in values:
            label = normalize_label(value)
            if not label or not label.isascii() or len(label) > 40:
                raise ValueError(f"tag must be 1 to 40 plain ASCII characters: {value!r}")
            if label not in cleaned:
                cleaned.append(label)
        return cleaned


class ItemTagsEntry(BaseModel):
    """One row of the admin tags page."""

    item_id: str
    content_text: str
    category: str
    content_topics: List[str] = Field(default_factory=list)
    audience_tags: List[str] = Field(default_factory=list)
    tags_source: str = "pipeline"
    status: Optional[str] = None
    audience_rating: Optional[AudienceRating] = None
    human_reviewed: bool = False
    is_escalated: bool = False


class ItemTagsListResponse(BaseModel):
    """Response of GET /api/items/tags."""

    items: List[ItemTagsEntry] = Field(default_factory=list)
    known_topics: List[str] = Field(default_factory=list, description="Topics that have an age-group list")
    audience_tag_options: List[str] = Field(default_factory=list, description="Audience tags a moderator can set")
    escalated_withheld: int = Field(0, description="High-risk items hidden from a non-senior caller")


class EventType(str, Enum):
    IMPRESSION = "impression"
    CLICK = "click"
    VIEW_LONG = "view_long"
    SKIP = "skip"
    MODERATOR_OVERRIDE = "moderator_override"


class ModeratorAction(str, Enum):
    APPROVE = "approve"
    WARN = "warn"
    REMOVE = "remove"
    ESCALATE = "escalate"


class FeedbackEvent(BaseModel):
    """Body of POST /api/recommendations/feedback."""

    event_type: EventType = Field(..., description="impression, click, view_long, skip, moderator_override")
    item_id: str = Field(..., min_length=1)
    original_verdict: Optional[str] = Field(None, description="Agent verdict being reviewed (moderator_override)")
    final_action: Optional[ModeratorAction] = Field(None, description="Required for moderator_override")
    notes: str = Field("", max_length=2000)


class FeedbackResponse(BaseModel):
    accepted: bool
    event_type: EventType
    item_id: str
    detail: str
    override_occurred: Optional[bool] = None
