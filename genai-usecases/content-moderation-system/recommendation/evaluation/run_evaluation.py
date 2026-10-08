"""
Stage 4: offline evaluation by replay on the mock data.

    backend/.venv/Scripts/python.exe recommendation/evaluation/run_evaluation.py

Deterministic: fixed seeds, no clock, no network. Two runs write byte-identical
``evaluation_metrics.json``. Outputs go to ``recommendation/results/``:

    evaluation_metrics.json        every number below
    evaluation_<section>.csv       one table per section
    chart_<section>.png            one chart per section

Sections
    A  leak rate            feeds for child/teen profiles, gate on versus gate off (ablation)
    B  relevance            ranker versus interest-only and random baselines; bandit off (ablation)
    C  bandit learning      simulated click feedback over rounds; bandit off and no-learning (ablations)
    D  diversity and drift  topic spread, out-of-interest share, borderline share
    E  queue                time-to-review of high-harm items versus FIFO and a plain risk sort
    F  precedents           suggested-action accuracy with and without precedent retrieval (ablation)

The "gate off" numbers exist only to show what the gate prevents. Gate-off feeds are built
by calling the ranker directly on mock data; the feed service has no way to disable the gate.
"""

import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_harness import RESULTS_DIR, leak_reason, load_dataset, load_mock_data  # noqa: E402
from recommendation.src.bandit import ThompsonSamplingBandit  # noqa: E402
from recommendation.src.feedback import FeedbackService  # noqa: E402
from recommendation.src.models import FeedbackEvent, RecommendationItemModel, ViewerProfileModel  # noqa: E402
from recommendation.src.moderator_queue import (  # noqa: E402
    PrecedentRetriever,
    ReviewQueuePrioritizer,
    is_escalated,
    needs_review,
    rule_based_suggestion,
)
from recommendation.src.personalization import ProfileRanker, is_borderline_risk, item_topics, primary_topic  # noqa: E402
from recommendation.src.safety_gate import SafetyGate  # noqa: E402
from recommendation.src.service import FeedService  # noqa: E402
from recommendation.src.store import RecommendationRepository  # noqa: E402

SEED = 20261008
FEED_SIZE = 10
LEAK_ROUNDS = 5
SIMULATION_ROUNDS = 10
SIMULATION_PROFILES_PER_TIER = 12
LATER_FLAGGED_RATE = 0.03
HIGH_HARM_TOXICITY = 0.5
PRECEDENT_K = 5
TIERS = ("child", "teen", "adult")

CLICK_PROBABILITY = {"hidden": 0.8, "explicit": 0.5, "other": 0.05}

# Chart colours: the validated default categorical palette, assigned to the same entity
# in every chart. Values are also printed on the marks and saved as CSV tables.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SURFACE, INK, INK_SECONDARY, INK_MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e6e5e1"


class MemoryStore:
    """In-memory document store for the replay (nothing is written to a database)."""

    def __init__(self) -> None:
        self.data: Dict[str, Dict[str, str]] = defaultdict(dict)

    def put(self, collection: str, doc_id: str, data: Dict[str, Any]) -> None:
        self.data[collection][str(doc_id)] = json.dumps(data)

    def get(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        raw = self.data[collection].get(str(doc_id))
        return json.loads(raw) if raw is not None else None

    def list(self, collection: str, limit: int = 1000) -> List[Dict[str, Any]]:
        documents = self.data[collection]
        return [json.loads(documents[key]) for key in sorted(documents)[:limit]]


class EvalRepository(RecommendationRepository):
    """Repository that keeps the parsed item list between feeds; items are static in a replay."""

    def __init__(self) -> None:
        super().__init__(MemoryStore())
        self._items: Optional[List[RecommendationItemModel]] = None

    def upsert_item(self, item: RecommendationItemModel) -> None:
        super().upsert_item(item)
        self._items = None

    def list_items(self, limit: int = 5000) -> List[RecommendationItemModel]:
        if self._items is None:
            self._items = super().list_items(limit)
        return self._items


def fresh_repository() -> EvalRepository:
    repository = EvalRepository()
    load_mock_data(repository)
    return repository


def mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


# ─── A. leak rate ───────────────────────────────────────────────────────────────

def later_flagged_items(item_records: Dict[str, Dict[str, Any]]) -> set:
    """
    Items that look clean now but that, in this simulation, a later review flags: a
    seeded 3 % of the approved child- and teen-rated items. The gate cannot know about
    them, so this measures the residual risk the gate does not remove.
    """
    rng = random.Random(SEED + 1)
    eligible = sorted(
        item_id for item_id, record in item_records.items()
        if record["scenario"] in ("clean_child", "clean_teen", "sensitive_teen", "borderline")
    )
    return {item_id for item_id in eligible if rng.random() < LATER_FLAGGED_RATE}


def evaluate_leaks(profile_records, item_records) -> List[Dict[str, Any]]:
    later_flagged = later_flagged_items(item_records)
    rows = []
    for system in ("gate_on", "gate_off"):
        repository = fresh_repository()
        ranker = ProfileRanker(bandit=ThompsonSamplingBandit(seed=SEED))
        service = FeedService(repository, ranker)
        counts = {tier: Counter() for tier in ("child", "teen")}
        for record in profile_records:
            tier = record["age_tier"]
            if tier == "adult":
                continue
            for _ in range(LEAK_ROUNDS):
                if system == "gate_on":
                    feed = service.get_feed(record["profile_id"], FEED_SIZE).items
                else:
                    profile = repository.get_profile(record["profile_id"])
                    feed = ranker.rank_items(profile, repository.list_items(), FEED_SIZE)
                leaked = [item for item in feed if leak_reason(record, item_records[item.item_id])]
                counts[tier]["feeds"] += 1
                counts[tier]["items"] += len(feed)
                counts[tier]["feeds_with_leak"] += bool(leaked)
                counts[tier]["leaked_items"] += len(leaked)
                counts[tier]["feeds_with_later_flagged"] += any(item.item_id in later_flagged for item in feed)
        for tier, c in counts.items():
            rows.append({
                "system": system, "tier": tier, "feeds": c["feeds"], "items_served": c["items"],
                "feeds_with_above_tier_item": c["feeds_with_leak"],
                "leak_rate_percent": percent(c["feeds_with_leak"], c["feeds"]),
                "above_tier_items_served": c["leaked_items"],
                "feeds_with_later_flagged_item": c["feeds_with_later_flagged"],
                "later_flagged_rate_percent": percent(c["feeds_with_later_flagged"], c["feeds"]),
            })
    return rows


# ─── B and D. relevance, diversity, drift ───────────────────────────────────────

def true_gain(record: Dict[str, Any], item: RecommendationItemModel) -> float:
    """
    Graded relevance from the mock profile: an item on an explicit interest is relevant,
    graded by that interest's stored weight; anything else is not relevant.
    """
    explicit = set(record["explicit_interests"])
    weights = record.get("learned_interests", {})
    return max((weights.get(topic, 1.0) for topic in item_topics(item) if topic in explicit), default=0.0)


def ndcg(gains: Sequence[float], ideal: Sequence[float]) -> float:
    def dcg(values: Sequence[float]) -> float:
        return sum(value / math.log2(index + 2) for index, value in enumerate(values))
    ideal_dcg = dcg(sorted(ideal, reverse=True)[:len(gains) or FEED_SIZE])
    return dcg(gains) / ideal_dcg if ideal_dcg > 0 else 0.0


def interest_only_ranking(record, survivors) -> List[RecommendationItemModel]:
    """Baseline: order by the number of explicit interests an item matches, ties by id."""
    explicit = set(record["explicit_interests"])
    return sorted(survivors, key=lambda item: (-len(explicit.intersection(item_topics(item))), item.item_id))[:FEED_SIZE]


def evaluate_relevance(profile_records) -> Dict[str, List[Dict[str, Any]]]:
    repository = fresh_repository()
    items = repository.list_items()
    rng = random.Random(SEED + 2)
    systems: Dict[str, Callable] = {
        "full_system": lambda record, profile, survivors: ProfileRanker(
            bandit=ThompsonSamplingBandit(seed=SEED)).rank_items(profile, survivors, FEED_SIZE),
        "bandit_off": lambda record, profile, survivors: ProfileRanker(use_bandit=False).rank_items(profile, survivors, FEED_SIZE),
        "interest_only": lambda record, profile, survivors: interest_only_ranking(record, survivors),
        "random": lambda record, profile, survivors: rng.sample(survivors, min(FEED_SIZE, len(survivors))),
    }
    relevance = {name: defaultdict(list) for name in systems}
    spread = {name: {tier: defaultdict(list) for tier in TIERS} for name in systems}
    evaluated = 0
    for record in profile_records:
        profile = repository.get_profile(record["profile_id"])
        survivors, _ = SafetyGate.filter_candidate_pool(profile, items)
        if len(survivors) < 2 * FEED_SIZE:
            continue
        evaluated += 1
        ideal = [true_gain(record, item) for item in survivors]
        explicit = set(record["explicit_interests"])
        for name, build in systems.items():
            feed = build(record, profile, survivors)
            gains = [true_gain(record, item) for item in feed]
            relevance[name]["precision_at_10"].append(sum(1 for g in gains if g > 0) / FEED_SIZE)
            relevance[name]["ndcg_at_10"].append(ndcg(gains, ideal))
            relevance[name]["hit_rate_at_10"].append(1.0 if any(g > 0 for g in gains) else 0.0)
            tier_spread = spread[name][record["age_tier"]]
            tier_spread["distinct_topics"].append(len({primary_topic(item) for item in feed}))
            tier_spread["outside_interest_share"].append(
                sum(1 for item in feed if not explicit.intersection(item_topics(item))) / len(feed))
            tier_spread["borderline_share"].append(sum(1 for item in feed if is_borderline_risk(item)) / len(feed))

    relevance_rows = [
        {"system": name, "profiles": evaluated, **{metric: mean(values) for metric, values in metrics.items()}}
        for name, metrics in relevance.items()
    ]
    spread_rows = [
        {"system": name, "tier": tier, "profiles": len(metrics["distinct_topics"]),
         **{metric: mean(values) for metric, values in metrics.items()}}
        for name, tiers in spread.items() for tier, metrics in tiers.items()
    ]
    return {"relevance": relevance_rows, "diversity_drift": spread_rows}


# ─── C. bandit learning under simulated feedback ────────────────────────────────

def simulated_click(profile_id: str, round_index: int, item: RecommendationItemModel, explicit: set, hidden: set) -> bool:
    """A seeded click decision that is the same in every variant for the same exposure."""
    topics = set(item_topics(item))
    kind = "hidden" if topics & hidden else "explicit" if topics & explicit else "other"
    draw = random.Random(f"{SEED}:{profile_id}:{round_index}:{item.item_id}").random()
    return draw < CLICK_PROBABILITY[kind]


def evaluate_bandit(profile_records) -> Dict[str, Any]:
    """
    Each simulated viewer likes their explicit interests and, more strongly, two topics
    they never declared. A variant can only find those by exploring and learning.
    """
    chosen = []
    for tier in TIERS:
        chosen += [r for r in profile_records if r["age_tier"] == tier][:SIMULATION_PROFILES_PER_TIER]

    base = fresh_repository()
    items = base.list_items()
    hidden_topics: Dict[str, set] = {}
    taste_rng = random.Random(SEED + 3)
    for record in chosen:
        survivors, _ = SafetyGate.filter_candidate_pool(base.get_profile(record["profile_id"]), items)
        available = sorted({t for item in survivors for t in item_topics(item)} - set(record["explicit_interests"]))
        hidden_topics[record["profile_id"]] = set(taste_rng.sample(available, min(2, len(available))))

    variants = {
        "full_system": {"use_bandit": True, "learn": True, "random": False},
        "bandit_off": {"use_bandit": False, "learn": True, "random": False},
        "no_learning": {"use_bandit": False, "learn": False, "random": False},
        "random": {"use_bandit": False, "learn": False, "random": True},
    }
    clicks = {name: {tier: [[0, 0] for _ in range(SIMULATION_ROUNDS)] for tier in TIERS} for name in variants}
    for name, options in variants.items():
        repository = fresh_repository()
        bandit = ThompsonSamplingBandit(seed=SEED)
        service = FeedService(repository, ProfileRanker(bandit=bandit, use_bandit=options["use_bandit"]))
        feedback = FeedbackService(repository, bandit, ThompsonSamplingBandit(seed=SEED))
        pick_rng = random.Random(SEED + 4)
        for round_index in range(SIMULATION_ROUNDS):
            for record in chosen:
                profile_id, tier = record["profile_id"], record["age_tier"]
                if options["random"]:
                    survivors, _ = SafetyGate.filter_candidate_pool(repository.get_profile(profile_id), repository.list_items())
                    feed = pick_rng.sample(survivors, min(FEED_SIZE, len(survivors)))
                else:
                    feed = service.get_feed(profile_id, FEED_SIZE).items
                for item in feed:
                    clicked = simulated_click(profile_id, round_index, item, set(record["explicit_interests"]), hidden_topics[profile_id])
                    clicks[name][tier][round_index][0] += clicked
                    clicks[name][tier][round_index][1] += 1
                    if options["learn"]:
                        feedback.handle_engagement(
                            FeedbackEvent(event_type="view_long" if clicked else "skip", item_id=item.item_id), profile_id)

    by_round, summary = [], []
    for name in variants:
        for tier in TIERS:
            rounds = clicks[name][tier]
            for round_index, (hits, shown) in enumerate(rounds):
                by_round.append({"variant": name, "tier": tier, "round": round_index + 1,
                                 "click_rate": round(hits / shown, 4) if shown else 0.0})
            first, last = rounds[:3], rounds[-3:]
            summary.append({
                "variant": name, "tier": tier,
                "click_rate_overall": round(sum(h for h, _ in rounds) / max(1, sum(s for _, s in rounds)), 4),
                "click_rate_rounds_1_3": round(sum(h for h, _ in first) / max(1, sum(s for _, s in first)), 4),
                "click_rate_rounds_8_10": round(sum(h for h, _ in last) / max(1, sum(s for _, s in last)), 4),
            })
    return {"bandit_by_round": by_round, "bandit_summary": summary}


# ─── E. moderator queue ─────────────────────────────────────────────────────────

def evaluate_queue(item_records) -> List[Dict[str, Any]]:
    """One item is reviewed per time step; time-to-review is an item's position in the order."""
    repository = fresh_repository()
    queue_items = [item for item in repository.list_items() if needs_review(item)]

    def high_harm(item: RecommendationItemModel) -> bool:
        record = item_records[item.item_id]
        return record["scenario"] == "escalation_pending" or (item.toxicity_score or 0.0) >= HIGH_HARM_TOXICITY

    prioritized = [entry.content_id for entry in ReviewQueuePrioritizer().prioritize_queue(queue_items)]
    orders = {
        "prioritizer": prioritized,
        "risk_score_sort": [i.item_id for i in sorted(queue_items, key=lambda i: (-(i.toxicity_score or 0.0), i.item_id))],
        "fifo": [i.item_id for i in sorted(queue_items, key=lambda i: (i.created_at, i.item_id))],
    }
    by_id = {item.item_id: item for item in queue_items}
    harmful = {item.item_id for item in queue_items if high_harm(item)}
    escalated = {item.item_id for item in queue_items if is_escalated(item)}
    rows = []
    for name, order in orders.items():
        position = {item_id: index + 1 for index, item_id in enumerate(order)}
        top = set(order[:len(harmful)])
        rows.append({
            "policy": name, "queue_length": len(order), "high_harm_items": len(harmful),
            "mean_time_to_review_high_harm": mean([position[i] for i in harmful]),
            "mean_time_to_review_escalated": mean([position[i] for i in escalated]),
            "mean_time_to_review_all": mean(list(position.values())),
            "high_harm_in_first_n_percent": percent(len(top & harmful), len(harmful)),
            "exposure_weighted_wait": round(sum(
                position[i] * (by_id[i].toxicity_score or 0.0) * math.log10(1 + by_id[i].exposure_count) for i in order), 1),
        })
    return rows


# ─── F. precedent retrieval ─────────────────────────────────────────────────────

def evaluate_precedents() -> List[Dict[str, Any]]:
    """
    Leave-one-out: for each resolved case, suggest an action for its item using the other
    cases (the retriever never returns a case about the same item), and compare with what
    the moderator actually did.
    """
    repository = fresh_repository()
    cases = repository.list_precedents()
    retriever = PrecedentRetriever()
    outcomes = {"with_precedents": Counter(), "rules_only": Counter()}
    for case in cases:
        item = repository.get_item(case.content_id)
        precedents = retriever.get_similar_precedents(item, [c for c in cases if c.case_id != case.case_id], PRECEDENT_K)
        with_precedents = retriever.suggest_action(item, precedents)[0]
        rules_only = rule_based_suggestion(item)[0]
        group = "override" if case.override_occurred else "agreement"
        for name, suggestion in (("with_precedents", with_precedents), ("rules_only", rules_only)):
            outcomes[name]["cases"] += 1
            outcomes[name]["correct"] += suggestion == case.final_human_action
            outcomes[name][f"{group}_cases"] += 1
            outcomes[name][f"{group}_correct"] += suggestion == case.final_human_action
    return [{
        "system": name, "cases": c["cases"], "accuracy_percent": percent(c["correct"], c["cases"]),
        "override_cases": c["override_cases"],
        "accuracy_on_override_cases_percent": percent(c["override_correct"], c["override_cases"]),
        "agreement_cases": c["agreement_cases"],
        "accuracy_on_agreement_cases_percent": percent(c["agreement_correct"], c["agreement_cases"]),
    } for name, c in outcomes.items()]


# ─── output ─────────────────────────────────────────────────────────────────────

def write_csv(name: str, rows: List[Dict[str, Any]]) -> None:
    with (RESULTS_DIR / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def print_table(title: str, rows: List[Dict[str, Any]]) -> None:
    header = list(rows[0])
    widths = [max(len(str(h)), *(len(str(row[h])) for row in rows)) for h in header]
    print(f"\n{title}")
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(row[h]).ljust(w) for h, w in zip(header, widths)))


def make_charts(metrics: Dict[str, Any]) -> None:
    """Draw one PNG per section. Imported here so the metrics can be computed without matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "text.color": INK, "axes.labelcolor": INK_SECONDARY, "axes.edgecolor": GRID,
        "xtick.color": INK_MUTED, "ytick.color": INK_MUTED, "xtick.labelcolor": INK_SECONDARY,
        "ytick.labelcolor": INK_SECONDARY, "axes.titleweight": "bold", "axes.titlesize": 11,
        "axes.titlelocation": "left", "legend.frameon": False, "svg.hashsalt": str(SEED),
    })

    def style(axis) -> None:
        for side in ("top", "right", "left"):
            axis.spines[side].set_visible(False)
        axis.yaxis.grid(True, color=GRID, linewidth=0.8)
        axis.set_axisbelow(True)
        axis.tick_params(length=0)

    def grouped_bars(axis, groups, series, values, colors, fmt="{:.2f}") -> None:
        width = 0.8 / len(series)
        for s_index, name in enumerate(series):
            xs = [g + (s_index - (len(series) - 1) / 2) * width for g in range(len(groups))]
            bars = axis.bar(xs, values[name], width * 0.9, color=colors[s_index], label=name, edgecolor=SURFACE, linewidth=2)
            for bar, value in zip(bars, values[name]):
                axis.annotate(fmt.format(value), (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                              xytext=(0, 3), textcoords="offset points", ha="center", color=INK_SECONDARY, fontsize=9)
        axis.set_xticks(range(len(groups)), groups)
        style(axis)

    def save(figure, name: str) -> None:
        figure.tight_layout()
        figure.savefig(RESULTS_DIR / name, dpi=150, metadata={"Software": None})
        plt.close(figure)

    # A. leak rate
    leaks = {(r["system"], r["tier"]): r["leak_rate_percent"] for r in metrics["leak_rate"]}
    figure, axis = plt.subplots(figsize=(6.2, 3.8))
    grouped_bars(axis, ["Child feeds", "Teen feeds"], ["Gate on", "Gate off (ablation)"],
                 {"Gate on": [leaks[("gate_on", t)] for t in ("child", "teen")],
                  "Gate off (ablation)": [leaks[("gate_off", t)] for t in ("child", "teen")]},
                 [BLUE, ORANGE], "{:.1f}%")
    axis.set_title("Feeds containing an item the viewer must not see")
    axis.set_ylabel("% of feeds")
    axis.set_ylim(0, 115)
    axis.legend(loc="upper left", ncols=2)
    save(figure, "chart_leak_rate.png")

    # B. relevance
    relevance = {r["system"]: r for r in metrics["relevance"]}
    labels = {"full_system": "Full system", "bandit_off": "Bandit off", "interest_only": "Interest-only", "random": "Random"}
    figure, axis = plt.subplots(figsize=(7.6, 3.8))
    grouped_bars(axis, ["Precision@10", "NDCG@10", "Hit rate@10"], list(labels.values()),
                 {labels[k]: [relevance[k]["precision_at_10"], relevance[k]["ndcg_at_10"], relevance[k]["hit_rate_at_10"]] for k in labels},
                 [BLUE, ORANGE, AQUA, YELLOW])
    axis.set_title("Relevance of one feed against the profile's stated interests")
    axis.set_ylim(0, 1.25)
    axis.legend(loc="upper left", ncols=4)
    save(figure, "chart_relevance.png")

    # C. bandit learning (small multiples, one shared y-axis)
    variants = {"full_system": ("Full system", BLUE), "bandit_off": ("Bandit off", ORANGE),
                "no_learning": ("No learning", AQUA), "random": ("Random", YELLOW)}
    figure, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), sharey=True)
    for axis, tier in zip(axes, TIERS):
        for key, (label, color) in variants.items():
            points = [r["click_rate"] for r in metrics["bandit_by_round"] if r["variant"] == key and r["tier"] == tier]
            axis.plot(range(1, len(points) + 1), points, color=color, linewidth=2, marker="o", markersize=4, label=label)
        axis.set_title(f"{tier.capitalize()} profiles")
        axis.set_xlabel("Feedback round")
        axis.set_xticks(range(1, SIMULATION_ROUNDS + 1))
        axis.set_ylim(0, 1)
        style(axis)
    axes[0].set_ylabel("Simulated click rate")
    axes[2].legend(loc="upper left", fontsize=9)
    figure.suptitle("Click rate as feedback accumulates (simulated viewers with undeclared tastes)",
                    x=0.01, ha="left", fontweight="bold", fontsize=11)
    save(figure, "chart_bandit_learning.png")

    # D. drift and diversity
    spread = {(r["system"], r["tier"]): r for r in metrics["diversity_drift"]}
    figure, axes = plt.subplots(1, 2, figsize=(9.5, 3.8))
    for axis, metric, title in ((axes[0], "outside_interest_share", "Share of feed outside stated interests"),
                                (axes[1], "borderline_share", "Share of feed that is borderline-risk")):
        grouped_bars(axis, ["Teen", "Adult"], ["Full system", "Interest-only"],
                     {"Full system": [spread[("full_system", t)][metric] for t in ("teen", "adult")],
                      "Interest-only": [spread[("interest_only", t)][metric] for t in ("teen", "adult")]},
                     [BLUE, AQUA])
        axis.set_title(title)
        axis.set_ylim(0, max(0.5, axis.get_ylim()[1] * 1.25))
    axes[0].legend(loc="upper left", ncols=2)
    save(figure, "chart_diversity_drift.png")

    # E. queue
    queue = {r["policy"]: r for r in metrics["queue"]}
    policies = {"prioritizer": ("Prioritizer", BLUE), "risk_score_sort": ("Risk-score sort", ORANGE), "fifo": ("FIFO", AQUA)}
    figure, axis = plt.subplots(figsize=(6.6, 3.8))
    grouped_bars(axis, ["High-harm items", "Escalated items", "All items"], [v[0] for v in policies.values()],
                 {label: [queue[k]["mean_time_to_review_high_harm"], queue[k]["mean_time_to_review_escalated"],
                          queue[k]["mean_time_to_review_all"]] for k, (label, _) in policies.items()},
                 [v[1] for v in policies.values()], "{:.1f}")
    axis.set_title("Mean time-to-review (queue position; lower is sooner)")
    axis.set_ylabel("Position in review order")
    axis.set_ylim(0, axis.get_ylim()[1] * 1.2)
    axis.legend(loc="upper left", ncols=3)
    save(figure, "chart_queue.png")

    # F. precedents
    precedents = {r["system"]: r for r in metrics["precedents"]}
    figure, axis = plt.subplots(figsize=(6.6, 3.8))
    grouped_bars(axis, ["All cases", "Override cases", "Agreement cases"], ["With precedents", "Rules only (ablation)"],
                 {"With precedents": [precedents["with_precedents"][k] for k in
                                      ("accuracy_percent", "accuracy_on_override_cases_percent", "accuracy_on_agreement_cases_percent")],
                  "Rules only (ablation)": [precedents["rules_only"][k] for k in
                                            ("accuracy_percent", "accuracy_on_override_cases_percent", "accuracy_on_agreement_cases_percent")]},
                 [BLUE, ORANGE], "{:.1f}%")
    axis.set_title("Suggested action matches the moderator's final action")
    axis.set_ylabel("% of resolved cases")
    axis.set_ylim(0, 125)
    axis.legend(loc="upper left", ncols=2)
    save(figure, "chart_precedents.png")


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    profile_records = load_dataset("profiles")
    item_records = {record["item_id"]: record for record in load_dataset("items")}

    metrics: Dict[str, Any] = {"seed": SEED, "feed_size": FEED_SIZE}
    metrics["leak_rate"] = evaluate_leaks(profile_records, item_records)
    metrics.update(evaluate_relevance(profile_records))
    metrics.update(evaluate_bandit(profile_records))
    metrics["queue"] = evaluate_queue(item_records)
    metrics["precedents"] = evaluate_precedents()

    titles = {
        "leak_rate": "A. Leak rate in child and teen feeds",
        "relevance": "B. Relevance of a single feed",
        "bandit_summary": "C. Simulated click rate with feedback",
        "diversity_drift": "D. Diversity and drift",
        "queue": "E. Review queue",
        "precedents": "F. Precedent retrieval",
    }
    for key, title in titles.items():
        print_table(title, metrics[key])
        write_csv(f"evaluation_{key}.csv", metrics[key])
    write_csv("evaluation_bandit_by_round.csv", metrics["bandit_by_round"])
    (RESULTS_DIR / "evaluation_metrics.json").write_text(
        json.dumps(metrics, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    make_charts(metrics)
    print(f"\nWrote evaluation_metrics.json, 7 CSV tables and 6 charts to {RESULTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
