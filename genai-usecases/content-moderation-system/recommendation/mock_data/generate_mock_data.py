"""
Seeded mock-data generator for the recommendation feature.

Run from the project root:

    backend/.venv/Scripts/python.exe recommendation/mock_data/generate_mock_data.py

Writes items.json, profiles.json, engagement.json, resolved_cases.json and
rejection_cases.json next to this file. The seed is fixed, so two runs produce
byte-identical files.

Content safety: every item body is neutral placeholder text. Harmful material is
represented only by labels (for example ``category: violent_extremism``) and by the
numeric signals the moderation agents would have produced. No harmful text is generated.
"""

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recommendation.src.config import (  # noqa: E402
    CHILD_SAFE_TOPICS,
    SENSITIVE_TEEN_TOPICS,
    TEEN_ALLOWED_TOPICS,
)

SEED = 20261008
OUTPUT_DIR = Path(__file__).resolve().parent
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)

TEEN_ONLY_TOPICS = tuple(t for t in TEEN_ALLOWED_TOPICS if t not in CHILD_SAFE_TOPICS)
ADULT_TOPICS = ("general", "news", "finance", "politics", "crime_documentary", "dating", "nightlife", "true_crime")
ADULT_VIOLATIONS = ("misinformation", "harassment", "hate_speech", "sexual_content", "violence")
ESCALATION_LABELS = ("violent_extremism", "grooming", "self_harm_promotion")
PENDING_STATUSES = ("flagged", "under_review", "pending_human_review")

# scenario -> (count, expected audience rating; None means unrated legacy)
ITEM_SCENARIOS = {
    "clean_child": (220, "all_ages"),
    "clean_teen": (140, "teen"),
    "sensitive_teen": (30, "teen"),
    "adult_general": (120, "adult"),
    "adult_violation": (50, "adult"),
    "borderline": (40, "teen"),
    "high_disagreement": (50, "adult"),
    "pending_review": (40, "adult"),
    "removed": (40, "blocked"),
    "escalation_pending": (24, "blocked"),
    "escalation_approved": (6, "adult"),
    "legacy_unrated": (30, None),
    "malformed": (10, "adult"),
}


def _timestamp(minutes: int) -> str:
    return (BASE_TIME + timedelta(minutes=minutes)).isoformat()


def agent_decisions(rng: random.Random, dissent: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """
    Agent decisions in the shape the pipeline writes. ``dissent`` lists the verdicts of
    judging agents that did not approve, applied from the last judging agent backwards.
    """
    judging = [
        ["Content Analysis Agent", "approve", 0.85],
        ["Toxicity Detection Agent", "approve", round(rng.uniform(0.80, 0.95), 2)],
        ["Policy Violation Agent", "approve", 0.85],
    ]
    for offset, verdict in enumerate(dissent):
        judging[-1 - offset][1] = verdict
        judging[-1 - offset][2] = round(rng.uniform(0.60, 0.90), 2)
    decisions = [{"agent_name": n, "decision": d, "confidence": c} for n, d, c in judging]
    decisions.append({"agent_name": "Action Enforcement Agent", "decision": "approve", "confidence": 1.0})
    return decisions


def clean_state(rng: random.Random, content_id: str, category: str, topics: List[str]) -> Dict[str, Any]:
    """A fully populated final pipeline state for approved, unremarkable content."""
    return {
        "content_id": content_id,
        "content_text": f"Placeholder item {content_id} about {category.replace('_', ' ')}.",
        "status": "approved",
        "moderation_action": "approved",
        "content_removed": False,
        "toxicity_score": round(rng.uniform(0.0, 0.09), 3),
        "policy_violations": [],
        "policy_flags": [],
        "violation_severity": "none",
        "contains_sensitive_content": False,
        "explicit_content_detected": False,
        "hate_speech_detected": False,
        "harassment_detected": False,
        "media_risk_level": "none",
        "content_category": category,
        "content_topics": topics,
        "agent_decisions": agent_decisions(rng),
    }


def _child_topics(rng: random.Random) -> List[str]:
    return rng.sample(CHILD_SAFE_TOPICS, rng.randint(1, 2))


def build_state(rng: random.Random, scenario: str, content_id: str) -> Dict[str, Any]:
    """Build the pipeline state for one item of a scenario."""
    state = clean_state(rng, content_id, rng.choice(CHILD_SAFE_TOPICS), _child_topics(rng))

    if scenario in ("clean_child", "legacy_unrated"):
        pass
    elif scenario == "clean_teen":
        state["content_category"] = rng.choice(TEEN_ONLY_TOPICS)
        state["content_topics"] = rng.sample(TEEN_ALLOWED_TOPICS, rng.randint(1, 2))
        state["toxicity_score"] = round(rng.uniform(0.0, 0.24), 3)
    elif scenario == "sensitive_teen":
        state["content_category"] = rng.choice(SENSITIVE_TEEN_TOPICS)
        state["content_topics"] = []
    elif scenario == "adult_general":
        state["content_category"] = rng.choice(ADULT_TOPICS)
        state["content_topics"] = rng.sample(ADULT_TOPICS, rng.randint(0, 2))
        state["toxicity_score"] = round(rng.uniform(0.0, 0.30), 3)
    elif scenario == "adult_violation":
        if rng.random() < 0.5:
            violation = rng.choice(ADULT_VIOLATIONS)
            state.update(
                policy_violations=[violation], policy_flags=[violation], violation_severity="medium",
                status="warned", moderation_action="warned",
            )
        else:
            state["toxicity_score"] = round(rng.uniform(0.35, 0.74), 3)
    elif scenario == "borderline":
        state["content_category"] = rng.choice(TEEN_ONLY_TOPICS)
        state["content_topics"] = rng.sample(TEEN_ALLOWED_TOPICS, 1)
        state["toxicity_score"] = round(rng.uniform(0.25, 0.34), 3)
        state["violation_severity"] = rng.choice(["none", "low"])
    elif scenario == "high_disagreement":
        dissent = rng.choice([["flag"], ["remove"], ["warn"], ["flag", "remove"]])
        state["agent_decisions"] = agent_decisions(rng, dissent)
    elif scenario == "pending_review":
        state["status"] = rng.choice(PENDING_STATUSES)
        state["moderation_action"] = "flagged"
        state["toxicity_score"] = round(rng.uniform(0.20, 0.60), 3)
        state["agent_decisions"] = agent_decisions(rng, ["flag"])
    elif scenario == "removed":
        violation = rng.choice(ADULT_VIOLATIONS)
        state.update(
            status="removed", moderation_action=rng.choice(["removed", "user_banned", "user_suspended"]),
            content_removed=True, toxicity_score=round(rng.uniform(0.60, 0.99), 3),
            policy_violations=[violation], policy_flags=[violation], violation_severity="critical",
            agent_decisions=agent_decisions(rng, ["remove", "remove"]),
        )
    elif scenario in ("escalation_pending", "escalation_approved"):
        label = rng.choice(ESCALATION_LABELS)
        state["content_category"] = label
        state["content_topics"] = [label]
        state["content_text"] = f"Placeholder item {content_id} labelled {label}."
        state["policy_violations"] = [label]
        if scenario == "escalation_pending":
            state.update(
                status=rng.choice(PENDING_STATUSES), moderation_action="flagged",
                policy_flags=[label], violation_severity="critical",
                toxicity_score=round(rng.uniform(0.30, 0.70), 3),
                agent_decisions=agent_decisions(rng, ["flag", "remove"]),
            )
        else:
            # A senior moderator reviewed it and approved it for adults (e.g. news reporting).
            state["agent_decisions"] = agent_decisions(rng, ["flag"]) + [
                {"agent_name": "HITL Human Review", "decision": "human_approved", "confidence": 1.0}
            ]
    elif scenario == "malformed":
        defect = rng.choice(
            ["no_severity", "no_flags", "flags_string", "category_none", "toxicity_text", "no_decisions"]
        )
        if defect == "no_severity":
            del state["violation_severity"]
        elif defect == "no_flags":
            # (A missing moderation_action is not a defect: the real pipeline does not
            # write it for content approved on the normal path.)
            del state["policy_flags"]
        elif defect == "flags_string":
            state["policy_flags"] = "self_harm"
        elif defect == "category_none":
            state["content_category"] = None
        elif defect == "toxicity_text":
            state["toxicity_score"] = "low"
        else:
            state["agent_decisions"] = []
        state["defect"] = defect
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    return state


def generate_items(rng: random.Random) -> List[Dict[str, Any]]:
    """800 items across the scenarios, each with the pipeline state that produced it."""
    items: List[Dict[str, Any]] = []
    index = 0
    for scenario, (count, expected_rating) in ITEM_SCENARIOS.items():
        for _ in range(count):
            index += 1
            content_id = f"item-{index:04d}"
            items.append({
                "item_id": content_id,
                "scenario": scenario,
                "expected_rating": expected_rating,
                "legacy": scenario == "legacy_unrated",
                "exposure_count": rng.choice([0, 5, 20, 100, 500, 2500, 10000]),
                "created_at": _timestamp(index * 7),
                "pipeline_state": build_state(rng, scenario, content_id),
            })
    return items


def generate_profiles(rng: random.Random) -> List[Dict[str, Any]]:
    """80 viewer profiles across tiers, trust levels and parental-control settings."""
    profiles: List[Dict[str, Any]] = []
    plan = [("child", 26, CHILD_SAFE_TOPICS), ("teen", 28, TEEN_ALLOWED_TOPICS), ("adult", 26, TEEN_ALLOWED_TOPICS + ADULT_TOPICS)]
    trust_levels = ["self_declared", "parent_linked", "verified"]
    index = 0
    for tier, count, topic_pool in plan:
        for position in range(count):
            index += 1
            scenario = "normal"
            controls: Dict[str, Any] = {}
            requested: List[str] = []
            interests = rng.sample(topic_pool, rng.randint(2, 4))
            learned = {topic: round(rng.uniform(0.2, 0.9), 2) for topic in interests}

            if tier != "adult" and position % 5 == 0:
                scenario = "parental_block"
                controls = {"blocked_categories": [rng.choice(["gaming", "sports", "music", "cartoons"])]}
            elif tier != "adult" and position % 5 == 1:
                scenario = "strict_controls"
                controls = {"strictness_level": "strict", "max_rating": "all_ages" if tier == "child" else "teen"}
            elif tier == "teen" and position % 5 == 2:
                scenario = "sensitive_allowed"
                controls = {"allowed_sensitive_topics": ["mental_health"]}
            elif tier == "child" and position % 5 == 2:
                scenario = "risky_engagement"
                learned.update({"violent_extremism": 0.95, "nightlife": 0.9, "true_crime": 0.85})
            elif tier != "adult" and position % 5 == 3:
                scenario = "disallowed_interest_request"
                requested = interests + ["violent_extremism", "dating", "nightlife"]

            profiles.append({
                "profile_id": f"profile-{index:03d}",
                "user_id": str(1000 + index),
                "age_tier": tier,
                "age_trust_level": trust_levels[position % 3],
                "explicit_interests": interests,
                "requested_explicit_interests": requested or interests,
                "learned_interests": learned,
                "parental_controls": controls,
                "scenario": scenario,
            })
    return profiles


def generate_engagement(rng: random.Random, items: List[Dict[str, Any]], profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Simulated engagement. Risky-engagement child profiles keep interacting with risky items."""
    risky_items = [i["item_id"] for i in items if i["expected_rating"] in ("adult", "blocked")]
    all_items = [i["item_id"] for i in items]
    events: List[Dict[str, Any]] = []
    minute = 0
    for profile in profiles:
        for _ in range(rng.randint(20, 50)):
            minute += 3
            pool = risky_items if profile["scenario"] == "risky_engagement" and rng.random() < 0.7 else all_items
            events.append({
                "profile_id": profile["profile_id"],
                "item_id": rng.choice(pool),
                "event_type": rng.choice(["impression", "click", "view_long", "skip"]),
                "timestamp": _timestamp(minute),
            })
    return events


NORM_ACTIONS = ("approve", "warn", "remove")
NORM_CONSISTENCY = 0.8


def category_norm(category: str) -> str:
    """
    The action moderators usually take in a category, in this mock world.

    Escalation categories are escalated. Every other category is given one of three
    "house norms" by its position in the alphabet. This is a deliberate construction: it
    gives the precedent memory something category-specific to recover that fixed rules on
    toxicity cannot know. See the note on circularity in results/RESULTS.md.
    """
    if category in ESCALATION_LABELS:
        return "escalate"
    known = sorted(set(TEEN_ALLOWED_TOPICS) | set(SENSITIVE_TEEN_TOPICS) | set(ADULT_TOPICS))
    return NORM_ACTIONS[known.index(category) % 3] if category in known else "warn"


def agent_verdict_for(state: Dict[str, Any]) -> str:
    """The verdict the agents' signals alone would give (mirrors the rule-based suggestion)."""
    if state.get("content_category") in ESCALATION_LABELS:
        return "escalate"
    toxicity = state.get("toxicity_score")
    if not isinstance(toxicity, (int, float)):
        return "escalate"
    if toxicity >= 0.75:
        return "remove"
    return "warn" if toxicity >= 0.35 else "approve"


def generate_resolved_cases(rng: random.Random, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    200 resolved moderation cases with the final human action.

    The human follows the category's norm 80 % of the time and otherwise picks another
    action at random. A case is an override whenever that differs from the agent verdict.
    """
    reviewable = [i for i in items if i["scenario"] in (
        "pending_review", "removed", "escalation_pending", "escalation_approved",
        "high_disagreement", "adult_violation", "borderline",
    )]
    actions = ["approve", "warn", "remove", "escalate"]
    cases: List[Dict[str, Any]] = []
    for index in range(1, 201):
        item = rng.choice(reviewable)
        state = item["pipeline_state"]
        category = state.get("content_category") or "unknown"
        agent_verdict = agent_verdict_for(state)
        norm = category_norm(category)
        final_action = norm if rng.random() < NORM_CONSISTENCY else rng.choice([a for a in actions if a != norm])
        cases.append({
            "case_id": f"case-{index:03d}",
            "content_id": item["item_id"],
            "category": category,
            "agent_verdict": agent_verdict,
            "final_human_action": final_action,
            "override_occurred": final_action != agent_verdict,
            "moderator_notes": f"Placeholder note for case {index:03d}.",
            "resolved_at": _timestamp(100000 + index * 11),
        })
    return cases


def _case(case_id: str, title: str, rule: str, viewer: Dict[str, Any], expected_reason: Optional[str],
          expected_rating: Optional[str] = "all_ages", state: Optional[Dict[str, Any]] = None,
          drop: Sequence[str] = (), item: Optional[Dict[str, Any]] = None, legacy: bool = False,
          dissent: Sequence[str] = (), human_approved: bool = False) -> Dict[str, Any]:
    return {
        "case_id": case_id, "title": title, "rule": rule, "viewer": viewer, "human_approved": human_approved,
        "state_overrides": state or {}, "state_drop": list(drop), "dissent": list(dissent),
        "item_overrides": item or {}, "legacy": legacy,
        "expected_rating": expected_rating, "expected_served": expected_reason is None,
        "expected_reason": expected_reason,
    }


def generate_rejection_cases() -> List[Dict[str, Any]]:
    """
    Hand-written catalogue: one named case per rule the gate enforces, plus control cases
    that must be served. Each case starts from a clean, approved, all-ages "science" item
    and changes only what the case is about.

    ``state_overrides`` change what the moderation pipeline reported. ``item_overrides``
    change the item after rating, to model a wrong or stale rating reaching the gate.
    """
    child = {"age_tier": "child", "age_trust_level": "verified"}
    teen = {"age_tier": "teen", "age_trust_level": "verified"}
    adult = {"age_tier": "adult", "age_trust_level": "verified"}
    adult_self = {"age_tier": "adult", "age_trust_level": "self_declared"}
    teen_self = {"age_tier": "teen", "age_trust_level": "self_declared"}

    def controls(viewer: Dict[str, Any], **settings: Any) -> Dict[str, Any]:
        return {**viewer, "parental_controls": settings}

    tech = {"content_category": "technology", "content_topics": ["coding"]}
    return [
        # Blocked content is served to nobody
        _case("R01", "Removed content, adult viewer", "blocked never served", adult, "blocked", "blocked",
              state={"status": "removed", "moderation_action": "removed", "content_removed": True}),
        _case("R02", "Author banned for the content", "blocked never served", adult, "blocked", "blocked",
              state={"moderation_action": "user_banned"}),
        _case("R03", "Approved but toxicity 0.90", "blocked never served", adult, "blocked", "blocked",
              state={"toxicity_score": 0.90}),
        # Rating above tier
        _case("R04", "Adult-rated item, child viewer", "rating > tier", child, "above_tier", "adult",
              state={"content_category": "news", "content_topics": ["news"]}),
        _case("R05", "Adult-rated item, teen viewer", "rating > tier", teen, "above_tier", "adult",
              state={"content_category": "news", "content_topics": ["news"]}),
        _case("R06", "Teen-rated item, child viewer", "rating > tier", child, "above_tier", "teen", state=tech),
        # Unrated legacy items
        _case("R07", "Legacy unrated item, child viewer", "unrated withheld", child, "unrated", None, legacy=True),
        _case("R08", "Legacy unrated item, teen viewer", "unrated withheld", teen, "unrated", None, legacy=True),
        _case("R09", "Legacy unrated item, self-declared adult", "unrated withheld", adult_self, "unrated", None, legacy=True),
        # Pending review and flagged
        _case("R10", "Flagged item, child viewer", "pending/flagged withheld", child, "pending_review", "adult",
              state={"status": "flagged", "moderation_action": "flagged"}),
        _case("R11", "Awaiting human review, teen viewer", "pending/flagged withheld", teen, "pending_review", "adult",
              state={"status": "pending_human_review", "moderation_action": "flagged"}),
        _case("R12", "Under review, teen viewer", "pending/flagged withheld", teen, "pending_review", "adult",
              state={"status": "under_review", "moderation_action": "flagged"}),
        _case("R13", "Flagged item, verified adult", "only moderated content is served", adult, "not_servable_status", "adult",
              state={"status": "flagged", "moderation_action": "flagged"}),
        _case("R14", "Not yet moderated (submitted), verified adult", "only moderated content is served", adult,
              "not_servable_status", "adult", state={"status": "submitted", "moderation_action": None}),
        # Escalation categories
        _case("R15", "violent_extremism label awaiting review, adult viewer", "escalation", adult, "blocked", "blocked",
              state={"content_category": "violent_extremism", "status": "flagged", "moderation_action": "flagged"}),
        _case("R16", "grooming label, moderator-approved, child viewer", "escalation", child, "escalation", "adult",
              state={"content_category": "grooming", "content_topics": ["grooming"]}, human_approved=True),
        _case("R17", "self_harm_promotion label, moderator-approved, teen viewer", "escalation", teen, "escalation", "adult",
              state={"policy_violations": ["self_harm_promotion"]}, human_approved=True),
        _case("R18", "Escalation label misspelled as 'selfharm', teen viewer", "escalation", teen, "escalation", "adult",
              state={"content_topics": ["science", "selfharm"]}, human_approved=True),
        _case("R19", "Wrong all_ages rating on a grooming-labelled item, child viewer", "escalation (gate does not trust the rating)",
              child, "escalation", "adult", state={"content_topics": ["grooming"]}, item={"audience_rating": "all_ages"},
              human_approved=True),
        # Uncertainty margin
        _case("R20", "One agent flagged the item, child viewer", "agent disagreement", child, "above_tier", "adult", dissent=["flag"]),
        _case("R21", "All agents voted remove but status says approved, child viewer", "agent disagreement", child,
              "above_tier", "adult", dissent=["remove", "remove", "remove"]),
        _case("R22", "Disagreement 0.50 on an all_ages item, child viewer", "high uncertainty", child, "high_uncertainty",
              item={"agent_disagreement": 0.5}),
        _case("R23", "Confidence 0.30 on an all_ages item, teen viewer", "high uncertainty", teen, "high_uncertainty",
              item={"overall_confidence": 0.3}),
        _case("R24", "Confidence signals missing, child viewer", "missing signal is not certainty", child, "missing_signals",
              item={"agent_disagreement": None}),
        _case("R25", "Disagreement 0.33, self-declared teen", "lower trust is stricter", teen_self, "high_uncertainty",
              item={"agent_disagreement": 0.33}),
        _case("R26", "Disagreement 0.30, teen under strict parental setting", "parental strictness", controls(teen, strictness_level="strict"),
              "high_uncertainty", item={"agent_disagreement": 0.30}),
        # Parental controls
        _case("R27", "Parent blocked 'gaming'; item is gaming_family, child viewer", "parental controls", controls(child, blocked_categories=["gaming"]),
              "parental_block", state={"content_category": "gaming_family", "content_topics": ["gaming_family"]}),
        _case("R28", "Parent capped rating at all_ages; teen item, teen viewer", "parental controls", controls(teen, max_rating="all_ages"),
              "parental_block", "teen", state=tech),
        _case("R29", "Blocked category applies to an adult profile too", "parental controls", controls(adult, blocked_categories=["news"]),
              "parental_block", "adult", state={"content_category": "news", "content_topics": ["news"]}),
        # Sensitive topics and borderline
        _case("R30", "mental_health topic, teen without parental allowance", "sensitive teen topics", teen, "sensitive_topic", "teen",
              state={"content_category": "mental_health", "content_topics": []}),
        _case("R31", "Borderline item (toxicity 0.30), teen under strict setting", "borderline content", controls(teen, strictness_level="strict"),
              "borderline", "teen", state={**tech, "toxicity_score": 0.30}),
        # Checks the gate makes independently of the rating
        _case("R32", "Wrong all_ages rating on a 'general' topic, child viewer", "topic allow-list", child, "unlisted_topic", "adult",
              state={"content_category": "general", "content_topics": []}, item={"audience_rating": "all_ages"}),
        _case("R33", "Wrong all_ages rating with a hate_speech violation, teen viewer", "violation allow-list", teen, "policy_violation", "adult",
              state={"policy_violations": ["hate_speech"]}, item={"audience_rating": "all_ages"}),
        _case("R34", "Wrong all_ages rating with toxicity 0.60, child viewer", "toxicity limit", child, "toxicity", "adult",
              state={"toxicity_score": 0.60}, item={"audience_rating": "all_ages"}),
        # Missing or malformed pipeline output
        _case("R35", "Pipeline omitted violation_severity, child viewer", "missing signal never lowers a rating", child, "above_tier", "adult",
              drop=["violation_severity"]),
        _case("R36", "Policy agent raised a flag, teen viewer", "missing signal never lowers a rating", teen, "above_tier", "adult",
              state={"policy_flags": ["needs_attention"]}),
        _case("R37", "content_category missing, child viewer", "missing signal never lowers a rating", child, "above_tier", "adult",
              state={"content_category": None}),
        _case("R38", "Action is 'warned' although status is approved, teen viewer", "status and action must agree", teen, "above_tier", "adult",
              state={"moderation_action": "warned"}),
        _case("R39", "Warned item, self-declared adult", "lower trust is stricter", adult_self, "pending_review", "adult",
              state={"status": "warned", "moderation_action": "warned"}),
        _case("R40", "Status 'approved' with a hidden zero-width character, child viewer", "exact status match", child, "pending_review", "adult",
              state={"status": "approved​"}),
        # Attempts to get around the gate
        _case("R41", "Item altered after rating (disagreement set to 7), child viewer", "invalid input is rejected", child, "invalid",
              item={"agent_disagreement": 7}),
        _case("R42", "Child whose interests and learned signals point at adult topics", "personalization cannot bypass the gate",
              {**child, "explicit_interests": ["violent_extremism", "nightlife"], "learned_interests": {"news": 1.0, "nightlife": 1.0}},
              "above_tier", "adult", state={"content_category": "news", "content_topics": ["news"]}),
        # Controls: these must be served, to show the gate does not simply reject everything
        _case("C01", "Clean all_ages item, child viewer", "control", child, None),
        _case("C02", "Clean teen item, teen viewer", "control", teen, None, "teen", state=tech),
        _case("C03", "Adult-rated item, verified adult", "control", adult, None, "adult",
              state={"content_category": "news", "content_topics": ["news"]}),
        _case("C04", "Disagreement 0.33, verified teen (same item as R25)", "control", teen, None, item={"agent_disagreement": 0.33}),
        _case("C05", "mental_health topic, teen with parental allowance (same item as R30)", "control",
              controls(teen, allowed_sensitive_topics=["mental_health"]), None, "teen",
              state={"content_category": "mental_health", "content_topics": []}),
        _case("C06", "Moderator-approved escalation item, verified adult (same item as R16)", "control", adult, None, "adult",
              state={"content_category": "grooming", "content_topics": ["grooming"]}, human_approved=True),
    ]


def generate(seed: int = SEED) -> Dict[str, List[Dict[str, Any]]]:
    """Generate every dataset from one seed."""
    rng = random.Random(seed)
    items = generate_items(rng)
    profiles = generate_profiles(rng)
    return {
        "items": items,
        "profiles": profiles,
        "engagement": generate_engagement(rng, items, profiles),
        "resolved_cases": generate_resolved_cases(rng, items),
        "rejection_cases": generate_rejection_cases(),
    }


def write(output_dir: Path = OUTPUT_DIR, seed: int = SEED) -> Dict[str, int]:
    """Write each dataset to ``<name>.json`` and return the record counts."""
    datasets = generate(seed)
    for name, records in datasets.items():
        text = json.dumps(records, indent=1, sort_keys=True, ensure_ascii=True)
        (output_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8", newline="\n")
    return {name: len(records) for name, records in datasets.items()}


if __name__ == "__main__":
    for dataset, count in write().items():
        print(f"{dataset}: {count}")
