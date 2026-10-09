"""
Shared helpers for replaying mock data through the rating derivation and the safety gate.

Used by the tests, by ``run_gate_report.py`` and by ``check_case.py`` so that all three
exercise the same path: pipeline state -> audience rating -> item -> gate decision.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recommendation.src.models import (  # noqa: E402
    GateDecision,
    ParentalControls,
    RecommendationItemModel,
    ViewerProfileModel,
)
from recommendation.src.rating import build_item_from_state, derive_audience_rating  # noqa: E402
from recommendation.src.safety_gate import SafetyGate  # noqa: E402

MOCK_DATA_DIR = PROJECT_ROOT / "recommendation" / "mock_data"
RESULTS_DIR = PROJECT_ROOT / "recommendation" / "results"

RATING_RANK = {"all_ages": 1, "teen": 2, "adult": 3, "blocked": 4}
TIER_RANK = {"child": 1, "teen": 2, "adult": 3}

_JUDGING_AGENTS = ("Content Analysis Agent", "Toxicity Detection Agent", "Policy Violation Agent")


def load_dataset(name: str) -> List[Dict[str, Any]]:
    """Load one generated mock dataset by name (for example ``items``)."""
    path = MOCK_DATA_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run recommendation/mock_data/generate_mock_data.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def base_state(content_id: str = "case-item", dissent: Sequence[str] = ()) -> Dict[str, Any]:
    """The clean, approved, all-ages "science" state every catalogue case starts from."""
    decisions = [{"agent_name": name, "decision": "approve", "confidence": 0.85} for name in _JUDGING_AGENTS]
    for offset, verdict in enumerate(dissent):
        decisions[-1 - offset]["decision"] = verdict
    decisions.append({"agent_name": "Action Enforcement Agent", "decision": "approve", "confidence": 1.0})
    return {
        "content_id": content_id,
        "content_text": "Placeholder item about science.",
        "status": "approved",
        "moderation_action": "approved",
        "content_removed": False,
        "toxicity_score": 0.02,
        "policy_violations": [],
        "policy_flags": [],
        "violation_severity": "none",
        "contains_sensitive_content": False,
        "explicit_content_detected": False,
        "hate_speech_detected": False,
        "harassment_detected": False,
        "media_risk_level": "none",
        "content_category": "science",
        "content_topics": ["science"],
        "agent_decisions": decisions,
    }


def profile_from_record(record: Dict[str, Any]) -> ViewerProfileModel:
    """Build a viewer profile from a mock-data or catalogue record."""
    return ViewerProfileModel(
        profile_id=record.get("profile_id", "case-viewer"),
        user_id=record.get("user_id"),
        age_tier=record["age_tier"],
        age_trust_level=record["age_trust_level"],
        explicit_interests=record.get("explicit_interests", []),
        learned_interests=record.get("learned_interests", {}),
        parental_controls=ParentalControls(**record.get("parental_controls", {})),
    )


def item_from_record(record: Dict[str, Any]) -> RecommendationItemModel:
    """Build the recommender's item from a mock ``items.json`` record."""
    return build_item_from_state(
        record["pipeline_state"],
        exposure_count=record.get("exposure_count", 0),
        rated=not record.get("legacy", False),
    )


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """
    Replay one catalogue case and compare the outcome with what the case expects.

    Returns the case identifiers together with the actual rating, whether the item was
    served, the gate's reason code, and ``ok`` (rating, served and reason all as expected).
    """
    state = base_state(case["case_id"], case.get("dissent", ()))
    state.update(case.get("state_overrides", {}))
    for key in case.get("state_drop", []):
        state.pop(key, None)
    if case.get("human_approved"):
        state["agent_decisions"] = state["agent_decisions"] + [
            {"agent_name": "HITL Human Review", "decision": "human_approved", "confidence": 1.0}
        ]

    legacy = case.get("legacy", False)
    actual_rating: Optional[str] = None if legacy else derive_audience_rating(state).rating.value
    item = build_item_from_state(state, rated=not legacy)
    if case.get("item_overrides"):
        # model_copy skips validation on purpose: this models a value changed behind the
        # gate's back, which the gate must catch by re-validating.
        item = item.model_copy(update=case["item_overrides"])

    decision: GateDecision = SafetyGate.evaluate_item(profile_from_record(case["viewer"]), item)
    actual_reason = decision.rejection_reason.value if decision.rejection_reason else None
    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "rule": case["rule"],
        "viewer_tier": case["viewer"]["age_tier"],
        "viewer_trust": case["viewer"]["age_trust_level"],
        "expected_rating": case["expected_rating"],
        "actual_rating": actual_rating,
        "expected_served": case["expected_served"],
        "actual_served": decision.passed,
        "expected_reason": case["expected_reason"],
        "actual_reason": actual_reason,
        "ok": (
            actual_rating == case["expected_rating"]
            and decision.passed == case["expected_served"]
            and actual_reason == case["expected_reason"]
        ),
    }


def leak_reason(profile: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    """
    Ground-truth check for the bulk sweep: why serving this mock item to this mock
    profile would be a leak, or None. Uses only the scenario labels the generator
    assigned, never the gate's or the rating module's own output.
    """
    tier = profile["age_tier"]
    expected = item["expected_rating"]
    minor = tier != "adult"
    if expected == "blocked":
        return "blocked item served"
    if item["scenario"] in ("pending_review", "escalation_pending"):
        return "item awaiting review served"
    if expected is None:
        if minor or profile["age_trust_level"] == "self_declared":
            return "unrated item served to a minor or low-trust viewer"
        return None
    if RATING_RANK[expected] > TIER_RANK[tier]:
        return "item above viewer tier served"
    if minor and item["scenario"] in ("high_disagreement", "malformed", "escalation_approved", "adult_general", "adult_violation"):
        return "uncertain, malformed or adult item served to a minor"
    if tier == "child" and item["scenario"] == "borderline":
        return "borderline item served to a child"
    return None


def load_mock_data(repository: Any) -> Dict[str, int]:
    """
    Load the mock items, profiles and resolved cases into a repository. Mock profiles are
    stored as explicitly declared; their interests are stored as generated, without
    tier validation, so the tests can check the system copes with whatever is stored.
    """
    from recommendation.src.models import PrecedentCase

    items = load_dataset("items")
    for record in items:
        item = item_from_record(record)
        item.created_at = record["created_at"]
        repository.upsert_item(item)
    profiles = load_dataset("profiles")
    for record in profiles:
        profile = profile_from_record(record)
        profile.tier_declared = True
        repository.save_profile(profile)
    topics_by_item = {r["item_id"]: r["pipeline_state"].get("content_topics") or [] for r in items}
    cases = load_dataset("resolved_cases")
    for record in cases:
        topics = topics_by_item.get(record["content_id"], [])
        repository.add_precedent(PrecedentCase(
            **{key: record[key] for key in (
                "case_id", "content_id", "category", "agent_verdict", "final_human_action",
                "override_occurred", "moderator_notes", "resolved_at",
            )},
            topics=topics if isinstance(topics, list) else [],
        ))
    return {"items": len(items), "profiles": len(profiles), "precedents": len(cases)}
