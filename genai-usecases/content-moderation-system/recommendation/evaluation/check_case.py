"""
Try one case by hand: describe what the moderation pipeline reported about an item and who
is viewing, and see the rating, the gate's decision and the reason.

    backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --tier child --category grooming
    backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --tier adult --category grooming --human-approved
    backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --tier teen --status flagged
    backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --tier teen --trust self_declared --dissent flag
    backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --tier child --block gaming --category gaming_family

Everything not given on the command line is the clean default: an approved "science" item
with toxicity 0.02 that every agent approved, shown to a verified viewer.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_harness import base_state, profile_from_record  # noqa: E402
from recommendation.src.rating import build_item_from_state, derive_audience_rating  # noqa: E402
from recommendation.src.safety_gate import SafetyGate  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rate one item and gate it for one viewer.")
    viewer = parser.add_argument_group("viewer")
    viewer.add_argument("--tier", choices=["child", "teen", "adult"], default="child")
    viewer.add_argument("--trust", choices=["self_declared", "parent_linked", "verified"], default="verified")
    viewer.add_argument("--block", action="append", default=[], help="parental blocked category (repeatable)")
    viewer.add_argument("--strictness", choices=["low", "medium", "strict"], default="low")
    viewer.add_argument("--max-rating", choices=["all_ages", "teen", "adult"])
    viewer.add_argument("--allow-sensitive", action="append", default=[], help="parent-allowed sensitive topic")

    item = parser.add_argument_group("what the pipeline reported about the item")
    item.add_argument("--status", default="approved")
    item.add_argument("--action", default=None, help="moderation_action; defaults to the status")
    item.add_argument("--category", default="science")
    item.add_argument("--topic", action="append", default=None, help="content topic (repeatable)")
    item.add_argument("--toxicity", type=float, default=0.02)
    item.add_argument("--violation", action="append", default=[], help="policy violation label (repeatable)")
    item.add_argument("--flag", action="append", default=[], help="policy flag (repeatable)")
    item.add_argument("--severity", default="none")
    item.add_argument("--dissent", action="append", default=[], help="verdict of an agent that did not approve")
    item.add_argument("--human-approved", action="store_true", help="a human moderator reviewed and approved it")
    item.add_argument("--legacy", action="store_true", help="treat as an unrated legacy item")
    item.add_argument("--drop", action="append", default=[], help="remove a field from the pipeline output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = base_state("manual-check", args.dissent)
    state.update(
        status=args.status,
        moderation_action=args.action or args.status,
        content_removed=args.status == "removed",
        content_category=args.category,
        content_topics=args.topic if args.topic is not None else [args.category],
        toxicity_score=args.toxicity,
        policy_violations=args.violation,
        policy_flags=args.flag,
        violation_severity=args.severity,
    )
    for key in args.drop:
        state.pop(key, None)
    if args.human_approved:
        state["agent_decisions"].append({"agent_name": "HITL Human Review", "decision": "human_approved", "confidence": 1.0})

    controls = {"blocked_categories": args.block, "strictness_level": args.strictness,
                "allowed_sensitive_topics": args.allow_sensitive}
    if args.max_rating:
        controls["max_rating"] = args.max_rating
    profile = profile_from_record(
        {"age_tier": args.tier, "age_trust_level": args.trust, "parental_controls": controls}
    )

    item = build_item_from_state(state, rated=not args.legacy)
    decision = SafetyGate.evaluate_item(profile, item)

    print(f"Viewer        : {args.tier} / {args.trust}")
    if args.legacy:
        print("Rating        : unrated (legacy item)")
    else:
        result = derive_audience_rating(state)
        print(f"Rating        : {result.rating.value}")
        print(f"Why           : {', '.join(result.reasons) or 'no rule raised the rating'}")
        print(f"Disagreement  : {result.agent_disagreement}   Confidence: {result.overall_confidence}")
        print(f"Escalation    : {', '.join(result.escalation_categories) or 'none'}")
    if decision.passed:
        print("Gate decision : SERVED")
    else:
        print(f"Gate decision : REJECTED ({decision.rejection_reason.value})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
