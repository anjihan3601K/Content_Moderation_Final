"""
Pydantic schemas and models for the Age-Gated Recommendation & Queue Prioritizer system.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class AgeTier(str, Enum):
    CHILD = "child"
    TEEN = "teen"
    ADULT = "adult"


class AgeTrustLevel(str, Enum):
    SELF_DECLARED = "self_declared"
    PARENT_LINKED = "parent_linked"
    VERIFIED = "verified"


class AudienceRating(str, Enum):
    ALL_AGES = "all_ages"
    TEEN = "teen"
    ADULT = "adult"
    BLOCKED = "blocked"


class ParentalControls(BaseModel):
    blocked_categories: List[str] = Field(default_factory=list)
    strictness_level: str = Field("medium", description="low, medium, strict")
    require_parent_approval_for_sensitive: bool = True


class ViewerProfileModel(BaseModel):
    profile_id: str = Field(..., description="Unique viewer profile ID")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    age_tier: AgeTier = Field(AgeTier.ADULT, description="child, teen, adult")
    age_trust_level: AgeTrustLevel = Field(AgeTrustLevel.SELF_DECLARED)
    explicit_interests: List[str] = Field(default_factory=list)
    learned_interests: Dict[str, float] = Field(default_factory=dict)  # topic -> weight (0.0 to 1.0)
    parental_controls: ParentalControls = Field(default_factory=ParentalControls)
    recent_feed_history: List[Dict[str, Any]] = Field(default_factory=list)  # history of served items for drift guard
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PreferencesUpdateRequest(BaseModel):
    explicit_interests: Optional[List[str]] = None
    parental_controls: Optional[ParentalControls] = None


class RecommendationItemModel(BaseModel):
    item_id: str
    content_text: str
    content_category: str
    content_topics: List[str] = Field(default_factory=list)
    audience_rating: AudienceRating = Field(AudienceRating.ADULT)
    toxicity_score: float = 0.0
    overall_confidence: float = 1.0
    agent_disagreement: float = 0.0  # 1 - agent_consensus
    agent_confidence_scores: Dict[str, float] = Field(default_factory=dict)
    status: str = "approved"  # approved, pending_review, flagged, removed
    is_borderline: bool = False
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class GateDecision(BaseModel):
    item_id: str
    passed: bool
    rejection_reason: Optional[str] = None  # above_tier, blocked, high_uncertainty, pending_review, parental_block, escalation
    safety_margin_applied: bool = False


class FeedRequest(BaseModel):
    limit: int = Field(10, ge=1, le=50)


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
    agent_disagreement: float
    exposure_score: float
    audience_rating: AudienceRating
    status: str
    is_escalated: bool
    requires_senior_moderator: bool
    created_at: str


class PrecedentCase(BaseModel):
    case_id: str
    content_id: str
    category: str
    similarity_score: float
    agent_verdict: str
    final_human_action: str  # approve, remove, warn, escalate
    moderator_notes: str
    override_occurred: bool


class RecommendationDetailResponse(BaseModel):
    item_id: str
    content_text: str
    category: str
    suggested_action: str
    confidence: float
    audience_rating: AudienceRating
    precedents: List[PrecedentCase]


class FeedbackEvent(BaseModel):
    event_type: str = Field(..., description="impression, click, view_long, skip, moderator_override")
    item_id: str
    profile_id: Optional[str] = None
    moderator_id: Optional[str] = None
    topic: Optional[str] = None
    reward_value: float = Field(0.0, description="Reward signal (-1.0 to 1.0)")
    original_verdict: Optional[str] = None
    final_action: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
