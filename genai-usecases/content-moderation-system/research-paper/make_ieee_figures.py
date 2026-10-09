"""
Figures for the IEEE paper (``paper.tex``), drawn from the files in ``data/``.

    backend/.venv/Scripts/python.exe research-paper/make_ieee_figures.py

Writes ``figures/ieee/fig_*.pdf`` (for LaTeX) and a PNG of each (for a Word template).
Sized for IEEE columns: 3.5 in for one column, 7.16 in across two. Titles are left to the
captions. Series keep the colours of the charts in ``recommendation/results/`` and add a
hatch, so they stay distinguishable in a greyscale print.
"""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "figures" / "ieee"

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK_SECONDARY, GRID = "#0b0b0b", "#52514e", "#d9d8d4"
HATCHES = ("", "///", "...", "xx")
ONE_COLUMN, TWO_COLUMNS = 3.5, 7.16

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "legend.fontsize": 7, "legend.frameon": False, "axes.edgecolor": INK_SECONDARY,
    "axes.linewidth": 0.6, "text.color": INK, "axes.labelcolor": INK, "hatch.linewidth": 0.5,
    "pdf.fonttype": 42, "figure.facecolor": "white", "axes.facecolor": "white",
})


def style(axis) -> None:
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    axis.yaxis.grid(True, color=GRID, linewidth=0.5)
    axis.set_axisbelow(True)
    axis.tick_params(length=2, width=0.5)


def grouped_bars(axis, groups, series, colors, fmt="{:.2f}", label_size=6.5) -> None:
    """``series`` maps a legend label to one value per group."""
    width = 0.8 / len(series)
    for index, (name, values) in enumerate(series.items()):
        xs = [g + (index - (len(series) - 1) / 2) * width for g in range(len(groups))]
        bars = axis.bar(xs, values, width * 0.88, color=colors[index], hatch=HATCHES[index],
                        edgecolor="white", linewidth=0.6, label=name)
        for bar, value in zip(bars, values):
            axis.annotate(fmt.format(value), (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                          xytext=(0, 1.5), textcoords="offset points", ha="center",
                          fontsize=label_size, color=INK_SECONDARY)
    axis.set_xticks(range(len(groups)), groups)
    style(axis)


def save(figure, name: str) -> None:
    figure.savefig(OUT / f"{name}.pdf", bbox_inches="tight", pad_inches=0.02)
    figure.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)


def read_csv(name: str):
    with open(DATA / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def architecture() -> None:
    figure, axis = plt.subplots(figsize=(TWO_COLUMNS, 2.55))
    axis.set_xlim(-1, 100)
    axis.set_ylim(-1, 37)
    axis.axis("off")

    def box(x, y, w, h, name, body=(), gate=False):
        axis.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8",
            facecolor="#dbe8f8" if gate else "white",
            edgecolor=BLUE if gate else INK_SECONDARY, linewidth=1.3 if gate else 0.8))
        lines = len(body)
        axis.text(x + w / 2, y + h / 2 + 1.25 * lines, name, ha="center", va="center",
                  fontsize=8, fontweight="bold")
        for index, line in enumerate(body):
            axis.text(x + w / 2, y + h / 2 + 1.25 * lines - 2.6 * (index + 1), line,
                      ha="center", va="center", fontsize=7, color=INK_SECONDARY)

    def arrow(points, dashed=False):
        for start, end in zip(points[:-2], points[1:-1]):
            axis.plot([start[0], end[0]], [start[1], end[1]], color=INK_SECONDARY, linewidth=0.8,
                      linestyle="--" if dashed else "-", solid_capstyle="butt")
        axis.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>", mutation_scale=7,
                                       color=INK_SECONDARY, linewidth=0.8, shrinkA=0, shrinkB=0,
                                       linestyle="--" if dashed else "-"))

    # Row 1: moderation before anything is served.
    box(0, 28, 14, 8, "Submission", ("text, image, URL",))
    box(18, 28, 26, 8, "Agentic moderation pipeline", ("6 agents + tools + human review",))
    box(48, 28, 22, 8, "Audience rating", ("rules can only raise it",))
    box(74, 28, 20, 8, "Rated items", ("rating + agent signals",))
    arrow([(14, 32), (18, 32)])
    arrow([(44, 32), (48, 32)])
    arrow([(70, 32), (74, 32)])

    # Row 2: the feed path.
    box(0, 13.5, 18, 9, "Safety gate", ("candidate pool", "10 ordered checks"), gate=True)
    box(25, 13.5, 22, 9, "Ranking", ("relevance + bandit", "drift, diversity guards"))
    box(54, 13.5, 18, 9, "Safety gate", ("ranked list", "same checks again"), gate=True)
    box(79, 13.5, 15, 9, "Feed", ("only approved,", "age-fit items"))
    arrow([(84, 28), (84, 25.2), (9, 25.2), (9, 22.5)])
    arrow([(18, 18), (25, 18)])
    arrow([(47, 18), (54, 18)])
    arrow([(72, 18), (79, 18)])
    axis.text(46, 25.9, "candidates", ha="center", fontsize=7, color=INK_SECONDARY)

    # Row 3: inputs and the moderator side.
    box(0, 0, 18, 9, "Viewer profile", ("age tier, trust,", "parental controls"))
    box(68, 0, 26, 9, "Moderator queue", ("harm x uncertainty x exposure",))
    arrow([(9, 9), (9, 13.5)])
    arrow([(18, 4.5), (63, 4.5), (63, 13.5)])
    arrow([(94, 32), (98, 32), (98, 4.5), (94, 4.5)])
    arrow([(86.5, 13.5), (86.5, 11.2), (36, 11.2), (36, 13.5)], dashed=True)
    axis.text(49, 7.4, "engagement feedback", ha="center", fontsize=7, color=INK_SECONDARY)
    save(figure, "fig_architecture")


def leak_rate(metrics) -> None:
    rows = {(r["system"], r["tier"]): r["leak_rate_percent"] for r in metrics["leak_rate"]}
    figure, axis = plt.subplots(figsize=(ONE_COLUMN, 2.1))
    grouped_bars(axis, ["Child feeds", "Teen feeds"], {
        "Gate on": [rows[("gate_on", t)] for t in ("child", "teen")],
        "Gate off (ablation)": [rows[("gate_off", t)] for t in ("child", "teen")],
    }, [BLUE, ORANGE], "{:.1f}%", 7)
    axis.set_ylabel("Feeds with a forbidden item (%)")
    axis.set_ylim(0, 118)
    axis.legend(loc="upper center", ncols=2, bbox_to_anchor=(0.5, 1.16))
    save(figure, "fig_leak_rate")


SCENARIOS = {
    "clean_child": "Clean, child topic", "clean_teen": "Clean, teen topic",
    "sensitive_teen": "Sensitive teen topic", "borderline": "Borderline toxicity",
    "adult_general": "Adult topic", "adult_violation": "Violation / moderate toxicity",
    "high_disagreement": "An agent dissented", "escalation_approved": "High-risk, human-approved",
    "malformed": "Malformed pipeline output", "legacy_unrated": "Legacy, unrated",
    "pending_review": "Pending review", "escalation_pending": "High-risk, awaiting review",
    "removed": "Removed",
}


def sweep() -> None:
    rows = {r["scenario"]: r for r in read_csv("stage1_sweep_matrix.csv")}
    tiers = ("child", "teen", "adult")
    shares = []
    for key in SCENARIOS:
        row = []
        for tier in tiers:
            served, evaluated = rows[key][f"{tier}_served/{tier}_evaluated"].split("/")
            row.append(100.0 * int(served) / int(evaluated))
        shares.append(row)
    figure, axis = plt.subplots(figsize=(ONE_COLUMN, 3.3))
    ramp = LinearSegmentedColormap.from_list("served", ["#f4f8fd", "#9cc3ee", BLUE, "#174a8c"])
    image = axis.imshow(shares, cmap=ramp, vmin=0, vmax=100, aspect="auto")
    for y, row in enumerate(shares):
        for x, value in enumerate(row):
            axis.text(x, y, f"{value:.1f}", ha="center", va="center", fontsize=7,
                      color="white" if value > 55 else INK)
    axis.set_xticks(range(3), ["Child", "Teen", "Adult"])
    axis.set_yticks(range(len(SCENARIOS)), list(SCENARIOS.values()))
    axis.xaxis.tick_top()
    axis.tick_params(length=0)
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.set_xticks([x - 0.5 for x in range(1, 3)], minor=True)
    axis.set_yticks([y - 0.5 for y in range(1, len(SCENARIOS))], minor=True)
    axis.grid(which="minor", color="white", linewidth=1.2)
    axis.tick_params(which="minor", length=0)
    bar = figure.colorbar(image, ax=axis, fraction=0.05, pad=0.03)
    bar.set_label("Decisions served (%)")
    bar.outline.set_visible(False)
    bar.ax.tick_params(length=2, width=0.5)
    save(figure, "fig_sweep")


REASONS = {
    "above_tier": "Rating above tier", "blocked": "Blocked", "parental_block": "Parental control",
    "pending_review": "Pending review", "unrated": "Unrated", "not_servable_status": "Not a servable status",
    "sensitive_topic": "Sensitive topic", "high_uncertainty": "High uncertainty",
    "escalation": "High-risk category", "borderline": "Borderline", "missing_signals": "Missing signals",
}


def rejection_reasons() -> None:
    rows = {r["reason"]: r for r in read_csv("stage1_rejection_reasons.csv")}
    order = sorted(REASONS, key=lambda key: int(rows[key]["total"]))
    figure, axis = plt.subplots(figsize=(ONE_COLUMN, 2.7))
    left = [0] * len(order)
    for index, (tier, color) in enumerate((("child", BLUE), ("teen", ORANGE), ("adult", AQUA))):
        values = [int(rows[key][tier]) for key in order]
        axis.barh(range(len(order)), values, 0.68, left=left, color=color, hatch=HATCHES[index],
                  edgecolor="white", linewidth=0.6, label=f"{tier.capitalize()} profiles")
        left = [a + b for a, b in zip(left, values)]
    for y, total in enumerate(left):
        axis.text(total + 150, y, f"{total:,}", va="center", fontsize=6.5, color=INK_SECONDARY)
    axis.set_yticks(range(len(order)), [REASONS[key] for key in order])
    axis.set_xlabel("Rejections (first failing check)")
    axis.set_xlim(0, 16500)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    axis.xaxis.grid(True, color=GRID, linewidth=0.5)
    axis.set_axisbelow(True)
    axis.tick_params(length=2, width=0.5)
    axis.legend(loc="lower right")
    save(figure, "fig_rejection_reasons")


def relevance(metrics) -> None:
    rows = {r["system"]: r for r in metrics["relevance"]}
    labels = {"full_system": "Full system", "bandit_off": "Bandit off",
              "interest_only": "Interest-only", "random": "Random"}
    figure, axis = plt.subplots(figsize=(ONE_COLUMN, 2.2))
    grouped_bars(axis, ["Precision@10", "NDCG@10", "Hit rate@10"], {
        label: [rows[key]["precision_at_10"], rows[key]["ndcg_at_10"], rows[key]["hit_rate_at_10"]]
        for key, label in labels.items()
    }, [BLUE, ORANGE, AQUA, YELLOW], "{:.2f}", 5.8)
    axis.set_ylabel("Score")
    axis.set_ylim(0, 1.32)
    axis.legend(loc="upper center", ncols=4, bbox_to_anchor=(0.5, 1.02), columnspacing=0.9, handlelength=1.4)
    save(figure, "fig_relevance")


def bandit(metrics) -> None:
    variants = {"full_system": ("Full system", BLUE, "o", "-"), "bandit_off": ("Bandit off", ORANGE, "s", "--"),
                "no_learning": ("No learning", AQUA, "^", "-."), "random": ("Random", YELLOW, "D", ":")}
    figure, axes = plt.subplots(1, 3, figsize=(TWO_COLUMNS, 2.1), sharey=True)
    for axis, tier in zip(axes, ("child", "teen", "adult")):
        for key, (label, color, marker, line) in variants.items():
            points = [r["click_rate"] for r in metrics["bandit_by_round"] if r["variant"] == key and r["tier"] == tier]
            axis.plot(range(1, len(points) + 1), points, color=color, linewidth=1.2, linestyle=line,
                      marker=marker, markersize=3, label=label)
        axis.set_title(f"{tier.capitalize()} profiles", fontsize=8)
        axis.set_xlabel("Feedback round")
        axis.set_xticks(range(1, 11))
        axis.set_ylim(0, 0.8)
        style(axis)
    axes[0].set_ylabel("Simulated click rate")
    axes[0].legend(loc="lower left", ncols=2)
    figure.tight_layout(w_pad=0.8)
    save(figure, "fig_bandit")


def guards(metrics) -> None:
    rows = {(r["system"], r["tier"]): r for r in metrics["diversity_drift"]}
    figure, axes = plt.subplots(1, 2, figsize=(ONE_COLUMN, 2.1))
    panels = (("borderline_share", "Borderline share (%)", {"teen": 15, "adult": 30}, "cap", 0.8),
              ("outside_interest_share", "Outside interests (%)", {"adult": 20}, "minimum", 3.6))
    for axis, (metric, label, limits, word, lift) in zip(axes, panels):
        grouped_bars(axis, ["Teen", "Adult"], {
            "Full system": [100 * rows[("full_system", t)][metric] for t in ("teen", "adult")],
            "Interest-only": [100 * rows[("interest_only", t)][metric] for t in ("teen", "adult")],
        }, [BLUE, AQUA], "{:.1f}", 6.2)
        for tier, limit in limits.items():
            x = ("teen", "adult").index(tier)
            axis.plot([x - 0.45, x + 0.45], [limit, limit], color=INK, linewidth=0.8, linestyle="--")
            axis.text(x, limit + lift, f"{word} {limit}%", ha="center", fontsize=6.2, color=INK)
        axis.set_ylabel(label)
        axis.set_ylim(0, 36)
    handles, names = axes[0].get_legend_handles_labels()
    figure.legend(handles, names, loc="upper center", ncols=2, bbox_to_anchor=(0.5, 1.07))
    figure.tight_layout(w_pad=1.0)
    save(figure, "fig_guards")


def queue(metrics) -> None:
    rows = {r["policy"]: r for r in metrics["queue"]}
    labels = {"prioritizer": "Prioritizer", "risk_score_sort": "Risk-score sort", "fifo": "FIFO"}
    figure, axis = plt.subplots(figsize=(ONE_COLUMN, 2.1))
    grouped_bars(axis, ["High-harm items", "High-risk items", "All items"], {
        label: [rows[key]["mean_time_to_review_high_harm"], rows[key]["mean_time_to_review_escalated"],
                rows[key]["mean_time_to_review_all"]] for key, label in labels.items()
    }, [BLUE, ORANGE, AQUA], "{:.1f}", 6.5)
    axis.set_ylabel("Mean queue position at review")
    axis.set_ylim(0, 66)
    axis.legend(loc="upper center", ncols=3, bbox_to_anchor=(0.5, 1.02), columnspacing=1.0)
    save(figure, "fig_queue")


def precedents(metrics) -> None:
    rows = {r["system"]: r for r in metrics["precedents"]}
    keys = ("accuracy_percent", "accuracy_on_override_cases_percent", "accuracy_on_agreement_cases_percent")
    figure, axis = plt.subplots(figsize=(ONE_COLUMN, 2.1))
    grouped_bars(axis, ["All (200)", "Override (120)", "Agreement (80)"], {
        "With precedents": [rows["with_precedents"][k] for k in keys],
        "Rules only (ablation)": [rows["rules_only"][k] for k in keys],
    }, [BLUE, ORANGE], "{:.1f}%", 6.5)
    axis.set_ylabel("Suggested action correct (%)")
    axis.set_ylim(0, 128)
    axis.legend(loc="upper center", ncols=2, bbox_to_anchor=(0.5, 1.02))
    save(figure, "fig_precedents")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    metrics = json.loads((DATA / "evaluation_metrics.json").read_text(encoding="utf-8"))
    architecture()
    leak_rate(metrics)
    sweep()
    rejection_reasons()
    relevance(metrics)
    bandit(metrics)
    guards(metrics)
    queue(metrics)
    precedents(metrics)
    print(f"wrote {len(list(OUT.glob('*.pdf')))} figures to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
