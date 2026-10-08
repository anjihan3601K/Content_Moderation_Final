"""
Stage 1 replay: run the rejection-case catalogue and the full mock-data sweep through the
rating derivation and the safety gate, print the tables and save them.

    backend/.venv/Scripts/python.exe recommendation/evaluation/run_gate_report.py

Outputs (recommendation/results/):
    stage1_case_results.csv     one row per catalogue case, expected versus actual
    stage1_rating_accuracy.csv  derived rating versus the scenario's expected rating
    stage1_sweep_matrix.csv     served / evaluated per item scenario and viewer tier
    stage1_rejection_reasons.csv  gate rejections by reason and viewer tier
    stage1_gate_report.json     everything above plus the headline numbers

Deterministic: no randomness, no clock, no network. Exit code 1 if any case fails, any
rating is wrong or any leak is found.
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_harness import (  # noqa: E402
    RESULTS_DIR,
    item_from_record,
    leak_reason,
    load_dataset,
    profile_from_record,
    run_case,
)
from recommendation.src.safety_gate import SafetyGate  # noqa: E402

TIERS = ("child", "teen", "adult")


def _write_csv(name: str, header: List[str], rows: List[List[Any]]) -> None:
    with (RESULTS_DIR / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _print_table(title: str, header: List[str], rows: List[List[Any]]) -> None:
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows)]
    print(f"\n{title}")
    print("  ".join(str(cell).ljust(width) for cell, width in zip(header, widths)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))


def run_catalogue() -> List[Dict[str, Any]]:
    """Replay every named case."""
    return [run_case(case) for case in load_dataset("rejection_cases")]


def run_sweep() -> Dict[str, Any]:
    """Evaluate every mock profile against every mock item."""
    item_records = load_dataset("items")
    profile_records = load_dataset("profiles")
    items = [item_from_record(record) for record in item_records]

    rating_table: Dict[str, Counter] = defaultdict(Counter)
    for record, item in zip(item_records, items):
        actual = item.audience_rating.value if item.audience_rating else "unrated"
        rating_table[record["scenario"]][actual] += 1
    rating_mismatches = sum(
        1 for record, item in zip(item_records, items)
        if (item.audience_rating.value if item.audience_rating else None) != record["expected_rating"]
    )

    evaluated: Counter = Counter()
    served: Counter = Counter()
    reasons: Counter = Counter()
    leaks: List[Dict[str, str]] = []
    for profile_record in profile_records:
        profile = profile_from_record(profile_record)
        tier = profile_record["age_tier"]
        for record, item in zip(item_records, items):
            decision = SafetyGate.evaluate_item(profile, item)
            evaluated[(record["scenario"], tier)] += 1
            if decision.passed:
                served[(record["scenario"], tier)] += 1
                problem = leak_reason(profile_record, record)
                if problem:
                    leaks.append({"profile_id": profile_record["profile_id"], "item_id": record["item_id"], "problem": problem})
            else:
                reasons[(decision.rejection_reason.value, tier)] += 1

    scenarios = list(dict.fromkeys(record["scenario"] for record in item_records))
    return {
        "scenarios": scenarios,
        "item_count": len(item_records),
        "profile_count": len(profile_records),
        "profiles_by_tier": dict(Counter(p["age_tier"] for p in profile_records)),
        "rating_table": {scenario: dict(counts) for scenario, counts in rating_table.items()},
        "expected_rating": {record["scenario"]: record["expected_rating"] or "unrated" for record in item_records},
        "scenario_counts": dict(Counter(record["scenario"] for record in item_records)),
        "rating_mismatches": rating_mismatches,
        "evaluated": evaluated,
        "served": served,
        "reasons": reasons,
        "leaks": leaks,
    }


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Catalogue of named cases
    cases = run_catalogue()
    case_header = ["case", "title", "viewer", "expected_rating", "actual_rating",
                   "expected_outcome", "actual_outcome", "result"]
    case_rows = []
    for c in cases:
        expected = "served" if c["expected_served"] else f"rejected: {c['expected_reason']}"
        actual = "served" if c["actual_served"] else f"rejected: {c['actual_reason']}"
        case_rows.append([
            c["case_id"], c["title"], f"{c['viewer_tier']}/{c['viewer_trust']}",
            c["expected_rating"] or "unrated", c["actual_rating"] or "unrated",
            expected, actual, "PASS" if c["ok"] else "FAIL",
        ])
    _print_table("1. Rejection-case catalogue", case_header, case_rows)
    _write_csv("stage1_case_results.csv", case_header, case_rows)
    failed_cases = [c["case_id"] for c in cases if not c["ok"]]

    # 2. Rating accuracy on the bulk items
    sweep = run_sweep()
    rating_header = ["scenario", "items", "expected_rating", "all_ages", "teen", "adult", "blocked", "unrated", "correct"]
    rating_rows = []
    for scenario in sweep["scenarios"]:
        counts = sweep["rating_table"][scenario]
        expected = sweep["expected_rating"][scenario]
        rating_rows.append([
            scenario, sweep["scenario_counts"][scenario], expected,
            *[counts.get(r, 0) for r in ("all_ages", "teen", "adult", "blocked", "unrated")],
            counts.get(expected, 0),
        ])
    _print_table("2. Derived audience rating by item scenario", rating_header, rating_rows)
    _write_csv("stage1_rating_accuracy.csv", rating_header, rating_rows)

    # 3. Served / evaluated per scenario and tier
    matrix_header = ["scenario", "expected_rating"] + [f"{t}_served/{t}_evaluated" for t in TIERS]
    matrix_rows = []
    for scenario in sweep["scenarios"]:
        matrix_rows.append([
            scenario, sweep["expected_rating"][scenario],
            *[f"{sweep['served'][(scenario, t)]}/{sweep['evaluated'][(scenario, t)]}" for t in TIERS],
        ])
    _print_table("3. Items served per scenario and viewer tier (served/evaluated)", matrix_header, matrix_rows)
    _write_csv("stage1_sweep_matrix.csv", matrix_header, matrix_rows)

    # 4. Rejection reasons
    reason_names = sorted({reason for reason, _ in sweep["reasons"]})
    reason_header = ["reason"] + list(TIERS) + ["total"]
    reason_rows = []
    for reason in reason_names:
        per_tier = [sweep["reasons"][(reason, t)] for t in TIERS]
        reason_rows.append([reason, *per_tier, sum(per_tier)])
    _print_table("4. Gate rejections by reason and viewer tier", reason_header, reason_rows)
    _write_csv("stage1_rejection_reasons.csv", reason_header, reason_rows)

    # 5. Headline numbers
    total_evaluated = sum(sweep["evaluated"].values())
    total_served = sum(sweep["served"].values())
    minor_evaluated = sum(v for (_, t), v in sweep["evaluated"].items() if t != "adult")
    minor_served = sum(v for (_, t), v in sweep["served"].items() if t != "adult")
    summary = {
        "catalogue_cases": len(cases),
        "catalogue_passed": len(cases) - len(failed_cases),
        "catalogue_failed": failed_cases,
        "items": sweep["item_count"],
        "profiles": sweep["profile_count"],
        "profiles_by_tier": sweep["profiles_by_tier"],
        "rating_mismatches": sweep["rating_mismatches"],
        "combinations_evaluated": total_evaluated,
        "combinations_served": total_served,
        "minor_combinations_evaluated": minor_evaluated,
        "minor_combinations_served": minor_served,
        "leaks": len(sweep["leaks"]),
        "leak_rate_percent": round(100.0 * len(sweep["leaks"]) / total_evaluated, 4),
    }
    _print_table("5. Summary", ["metric", "value"], [[k, v] for k, v in summary.items()])

    report = {
        "summary": summary,
        "cases": cases,
        "rating_accuracy": [dict(zip(rating_header, row)) for row in rating_rows],
        "sweep_matrix": [dict(zip(matrix_header, row)) for row in matrix_rows],
        "rejection_reasons": [dict(zip(reason_header, row)) for row in reason_rows],
        "leak_examples": sweep["leaks"][:50],
    }
    (RESULTS_DIR / "stage1_gate_report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    failed = bool(failed_cases or sweep["rating_mismatches"] or sweep["leaks"])
    print("\nRESULT:", "FAILED" if failed else "all cases as expected, no rating mismatch, no leak")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
