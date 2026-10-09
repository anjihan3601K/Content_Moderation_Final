"""
Wall-clock cost of the rating derivation, the safety gate and one feed request, on the
mock data. Writes ``research-paper/data/latency.json``.

    backend/.venv/Scripts/python.exe research-paper/measure_latency.py

Unlike the evaluation metrics, these numbers depend on the machine and vary between
runs; quote them together with the hardware in ``06_reproducibility.md``. Everything
runs in memory: no database, network or language-model call is timed.
"""

import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "recommendation" / "evaluation"))

from gate_harness import item_from_record, load_dataset, profile_from_record  # noqa: E402
from run_evaluation import FEED_SIZE, SEED, fresh_repository  # noqa: E402
from recommendation.src.bandit import ThompsonSamplingBandit  # noqa: E402
from recommendation.src.personalization import ProfileRanker  # noqa: E402
from recommendation.src.rating import derive_audience_rating  # noqa: E402
from recommendation.src.safety_gate import SafetyGate  # noqa: E402
from recommendation.src.service import FeedService  # noqa: E402

REPEATS = 5
OUTPUT = Path(__file__).resolve().parent / "data" / "latency.json"


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


def main() -> int:
    item_records = load_dataset("items")
    profile_records = load_dataset("profiles")
    profiles = [profile_from_record(record) for record in profile_records]
    items = [item_from_record(record) for record in item_records]

    rating_runs = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        for record in item_records:
            derive_audience_rating(record["pipeline_state"])
        rating_runs.append(time.perf_counter() - started)

    gate_runs = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        for profile in profiles:
            for item in items:
                SafetyGate.evaluate_item(profile, item)
        gate_runs.append(time.perf_counter() - started)
    decisions = len(profiles) * len(items)

    repository = fresh_repository()
    service = FeedService(repository, ProfileRanker(bandit=ThompsonSamplingBandit(seed=SEED)))
    service.get_feed(profile_records[0]["profile_id"], FEED_SIZE)  # warm-up, not timed
    feed_times = []
    for _ in range(REPEATS):
        for record in profile_records:
            started = time.perf_counter()
            service.get_feed(record["profile_id"], FEED_SIZE)
            feed_times.append(time.perf_counter() - started)

    gate_best = min(gate_runs)
    result = {
        "repeats": REPEATS,
        "rating": {
            "items": len(item_records),
            "microseconds_per_item_median": round(statistics.median(rating_runs) / len(item_records) * 1e6, 1),
        },
        "gate": {
            "decisions_per_run": decisions,
            "seconds_per_run_median": round(statistics.median(gate_runs), 3),
            "microseconds_per_decision_median": round(statistics.median(gate_runs) / decisions * 1e6, 1),
            "decisions_per_second_best_run": int(decisions / gate_best),
        },
        "feed": {
            "requests": len(feed_times),
            "candidate_pool": len(items),
            "feed_size": FEED_SIZE,
            "milliseconds_median": round(statistics.median(feed_times) * 1e3, 1),
            "milliseconds_p95": round(percentile(feed_times, 0.95) * 1e3, 1),
            "milliseconds_max": round(max(feed_times) * 1e3, 1),
        },
    }
    OUTPUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
