"""
Generate result charts from experiments/results/all_results.json.

Produces PNG figures in experiments/results/charts/:
  - strategy_comparison_E1.png  (bar chart: search time / wait / overflow per strategy)
  - strategy_comparison_E2.png
  - strategy_comparison_E3.png
  - strategy_comparison_E4.png
  - prediction_metrics.png       (grouped bar: MAE / WAPE per lot per model)
  - j_cost_comparison.png        (J cost across strategies)

Usage:
    python scripts/generate_charts.py
"""

import json
import math
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE  = ROOT / "experiments" / "results" / "all_results.json"
SUMMARY_FILE  = ROOT / "experiments" / "results" / "results_summary.json"
PRED_FILE     = ROOT / "experiments" / "results" / "prediction_metrics.json"
CHARTS_DIR    = ROOT / "experiments" / "results" / "charts"

STRATEGY_COLORS = {
    "B1": "#e74c3c",
    "B2": "#e67e22",
    "B3": "#3498db",
    "P":  "#2ecc71",
}
STRATEGY_ORDER = ["B1", "B2", "B3", "P"]
STRATEGY_LABELS = {
    "B1": "B1 First-Avail",
    "B2": "B2 Nearest",
    "B3": "B3 Pred-Only",
    "P":  "P ParkingNavX",
}


def _ci95(values):
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    if n < 2:
        return 0.0
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    t = 2.0 if n < 30 else 1.96
    return t * std / math.sqrt(n)


def load_results():
    if not RESULTS_FILE.exists():
        print(f"ERROR: {RESULTS_FILE} not found")
        sys.exit(1)
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def group_by_scenario_strategy(results):
    groups = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            groups[(r["scenario"], r["strategy"])].append(r)
    return groups


def draw_bar_chart(ax, scenarios, strategies, metric_key, groups, title, ylabel, fallback_label="n/a"):
    """Draw grouped bar chart for one metric across strategies."""
    import matplotlib.patches as mpatches
    n_strategies = len(strategies)
    bar_w = 0.7 / n_strategies
    xs = list(range(len(scenarios)))

    for i, st in enumerate(strategies):
        means, errs, labels_x = [], [], []
        for sc in scenarios:
            runs = groups.get((sc, st), [])
            vals = [r[metric_key] for r in runs if r.get(metric_key) is not None]
            means.append(sum(vals) / len(vals) if vals else 0.0)
            errs.append(_ci95(vals) if vals else 0.0)
        offset = (i - n_strategies / 2 + 0.5) * bar_w
        bars = ax.bar(
            [x + offset for x in xs], means,
            width=bar_w * 0.9,
            color=STRATEGY_COLORS.get(st, "#95a5a6"),
            label=STRATEGY_LABELS.get(st, st),
            capsize=3,
        )
        ax.errorbar(
            [x + offset for x in xs], means,
            yerr=errs, fmt="none", ecolor="black", capsize=3, linewidth=1,
        )

    ax.set_xticks(xs)
    ax.set_xticklabels([sc.replace("_", "\n") for sc in scenarios], fontsize=8)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_ylim(bottom=0)


def generate_strategy_comparison_charts(groups):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("WARNING: matplotlib not installed — skipping charts")
        return

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    scenarios_all = sorted({sc for sc, _ in groups.keys()})

    metrics = [
        ("avg_search_time_min",   "Avg Search Time (min)",    "Search Time Comparison"),
        ("avg_wait_time_min",     "Avg Wait Time (min)",      "Wait Time Comparison"),
        ("overflow_events",       "Overflow Events",          "Overflow Events Comparison"),
        ("avg_gate_queue",        "Avg Gate Queue (vehicles)","Gate Queue Comparison"),
    ]

    # One chart per scenario with all metrics side by side
    for sc in scenarios_all:
        sc_groups = {(s, st): v for (s, st), v in groups.items() if s == sc}
        fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4))
        if len(metrics) == 1:
            axes = [axes]
        for ax, (mkey, ylabel, mtitle) in zip(axes, metrics):
            means, errs = [], []
            for st in STRATEGY_ORDER:
                runs = groups.get((sc, st), [])
                vals = [r[mkey] for r in runs if r.get(mkey) is not None]
                means.append(sum(vals) / len(vals) if vals else 0.0)
                errs.append(_ci95(vals))
            xs = range(len(STRATEGY_ORDER))
            colors = [STRATEGY_COLORS.get(st, "#95a5a6") for st in STRATEGY_ORDER]
            ax.bar(xs, means, color=colors, capsize=4)
            ax.errorbar(xs, means, yerr=errs, fmt="none", ecolor="black", capsize=4, linewidth=1.2)
            ax.set_xticks(list(xs))
            ax.set_xticklabels([STRATEGY_LABELS[st].replace(" ", "\n") for st in STRATEGY_ORDER], fontsize=8)
            ax.set_title(mtitle, fontsize=9, fontweight="bold")
            ax.set_ylabel(ylabel, fontsize=8)
            ax.grid(axis="y", linestyle="--", alpha=0.4)
            ax.set_ylim(bottom=0)
        fig.suptitle(f"Strategy Comparison — {sc}", fontsize=12, fontweight="bold")
        fig.tight_layout()
        out = CHARTS_DIR / f"strategy_comparison_{sc}.png"
        fig.savefig(out, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved: {out.name}")

    # All scenarios overview — search time only
    fig, ax = plt.subplots(figsize=(max(8, len(scenarios_all) * 2.5), 4))
    draw_bar_chart(ax, scenarios_all, STRATEGY_ORDER, "avg_search_time_min", groups,
                   "Avg Search Time by Scenario & Strategy", "Avg Search Time (min)")
    fig.tight_layout()
    out = CHARTS_DIR / "all_scenarios_search_time.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out.name}")

    # J cost comparison
    fig, ax = plt.subplots(figsize=(max(8, len(scenarios_all) * 2.5), 4))
    draw_bar_chart(ax, scenarios_all, STRATEGY_ORDER, "cost_J", groups,
                   "J-Cost by Scenario & Strategy", "J Cost (lower = better)")
    fig.tight_layout()
    out = CHARTS_DIR / "j_cost_comparison.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def generate_prediction_chart():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    if not PRED_FILE.exists():
        print("  prediction_metrics.json not found — skipping prediction chart")
        return

    data = json.loads(PRED_FILE.read_text(encoding="utf-8"))
    lots = data.get("lots", [])
    if not lots:
        return

    models = ["historical_average", "moving_average", "xgboost"]
    model_labels = {"historical_average": "Hist-Avg", "moving_average": "Mov-Avg", "xgboost": "XGBoost"}
    model_colors = {"historical_average": "#3498db", "moving_average": "#e67e22", "xgboost": "#2ecc71"}
    lot_ids = [lot["lot_id"].replace("vitap-lot-", "") for lot in lots]

    fig, (ax_mae, ax_r2) = plt.subplots(1, 2, figsize=(12, 4))
    bar_w = 0.25
    xs = list(range(len(lot_ids)))

    for i, model in enumerate(models):
        mae_vals, r2_vals = [], []
        for lot in lots:
            m = lot.get(model, {})
            mae_vals.append(m.get("mae", 0.0) or 0.0)
            r2_vals.append(m.get("r2", 0.0) or 0.0)
        offset = (i - 1) * bar_w
        ax_mae.bar([x + offset for x in xs], mae_vals, width=bar_w * 0.9,
                   color=model_colors[model], label=model_labels[model])
        ax_r2.bar([x + offset for x in xs], r2_vals, width=bar_w * 0.9,
                  color=model_colors[model], label=model_labels[model])

    for ax, title, ylabel in [
        (ax_mae, "MAE by Lot and Model", "MAE (fill-rate units)"),
        (ax_r2, "R² by Lot and Model", "R²"),
    ]:
        ax.set_xticks(xs)
        ax.set_xticklabels(lot_ids, fontsize=8, rotation=15)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=9)
        ax.legend(fontsize=8)
        ax.grid(axis="y", linestyle="--", alpha=0.4)

    ax_r2.set_ylim(-0.2, 1.0)
    ax_mae.set_ylim(bottom=0)
    horizon = data.get("horizon_minutes", 15)
    fig.suptitle(f"Prediction Model Comparison — {horizon}-min Horizon", fontsize=11, fontweight="bold")
    fig.tight_layout()
    out = CHARTS_DIR / "prediction_metrics.png"
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120, bbox_inches="tight")
    import matplotlib.pyplot as _plt
    _plt.close(fig)
    print(f"  Saved: {out.name}")


def main():
    print("Generating charts from experiment results...")
    results = load_results()
    print(f"  Loaded {len(results)} result records")
    groups = group_by_scenario_strategy(results)
    print(f"  {len(groups)} (scenario, strategy) cells")

    generate_strategy_comparison_charts(groups)
    generate_prediction_chart()

    print(f"\nCharts saved to: {CHARTS_DIR}")


if __name__ == "__main__":
    main()
