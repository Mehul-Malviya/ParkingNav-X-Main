"""
Run all ParkingNav-X experiments: E1–E6 × strategies × N seeds.

Usage:
    python scripts/run_all_experiments.py [--seeds 30] [--workers 2]
    python scripts/run_all_experiments.py --scenarios E1_normal_day --seeds 5

Outputs:
    experiments/results/all_results.json   (appended; existing valid results preserved)
    experiments/results/summary_table.md
    experiments/results/results_summary.json
"""

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(ROOT))

from digital_twin.db import get_connection, apply_migrations
from digital_twin.config_loader import load_campus_config
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy
from digital_twin.simulation.demo_strategies import PredictionOnlyStrategy, ParkingNavXFullStrategy

CAMPUS_YAML = ROOT / "configs" / "campus" / "vitap.yaml"
SCENARIO_DIR = ROOT / "configs" / "scenarios" / "vitap"
RESULTS_DIR  = ROOT / "experiments" / "results"
RUNS_DIR     = ROOT / "experiments" / "runs"

# Strategy factories with short labels that become directory names
def _make_strategy(code):
    LABELS = {
        "B1": ("B1", FirstAvailableStrategy),
        "B2": ("B2", NearestAvailableStrategy),
        "B3": ("B3", PredictionOnlyStrategy),
        "P":  ("P",  ParkingNavXFullStrategy),
    }
    label, cls = LABELS[code]
    s = cls()
    s.label = label  # engine uses getattr(strategy, "label", class_name)
    return s

# Experiment matrix
# E5 and E6 variants run P strategy only (ablation/noise are P-specific)
EXPERIMENTS = [
    # (yaml_stem, [strategies])
    ("E1_normal_day",       ["B1", "B2", "B3", "P"]),
    ("E2_event_placement",  ["B1", "B2", "B3", "P"]),
    ("E3_lot_closure",      ["B1", "B2", "B3", "P"]),
    ("E4_gate_closure",     ["B1", "B2", "B3", "P"]),
    ("E5_noise_0",          ["P"]),
    ("E5_noise_10",         ["P"]),
    ("E5_noise_20",         ["P"]),
    ("E6_ablation",         ["P"]),   # variant A
    ("E6_ablation_B",       ["P"]),
    ("E6_ablation_C",       ["P"]),
    ("E6_ablation_D",       ["P"]),
]


def get_conn():
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(CAMPUS_YAML, conn)
    return conn


def _existing_run_ids(results_path: Path) -> set:
    """Return run_ids of valid (no-error) existing results."""
    if not results_path.exists():
        return set()
    try:
        data = json.loads(results_path.read_text(encoding="utf-8", errors="replace"))
        return {r["run_id"] for r in data if "error" not in r and "run_id" in r}
    except Exception:
        return set()


def run_one(scenario_yaml: str, strategy_code: str, seed: int) -> dict:
    """Run a single (scenario, strategy, seed) cell."""
    scenario_file = SCENARIO_DIR / f"{scenario_yaml}.yaml"
    if not scenario_file.exists():
        run_id = f"{scenario_yaml}-{strategy_code}-s{seed}"
        return {"run_id": run_id, "scenario": scenario_yaml, "strategy": strategy_code,
                "seed": seed, "error": "scenario file not found"}

    conn = get_conn()
    strategy = _make_strategy(strategy_code)
    sc = ScenarioLoader.load(scenario_file)

    # Override seed so different iterations produce different demand patterns
    sc.random_seed = seed

    run_id = f"{scenario_yaml}-{strategy_code}-s{seed}"
    t0 = time.time()
    try:
        engine = SimulationEngine()
        result = engine.run(sc, strategy, conn, run_id=run_id)
        m = result.metrics
        elapsed = round(time.time() - t0, 2)
        conn.close()
        # Capture predictor model version (name of active model)
        try:
            from digital_twin.prediction.engine import get_predictor
            predictor = get_predictor()
            model_version = predictor._xgb.name if predictor._fitted else "MovingAverage"
        except Exception:
            model_version = "unknown"

        return {
            "run_id": run_id,
            "scenario": scenario_yaml,
            "strategy": strategy_code,
            "seed": seed,
            "elapsed_s": elapsed,
            "model_version": model_version,
            "git_sha": getattr(result, "git_sha", None),
            "total_vehicles": m.get("total_vehicles"),
            "total_ever_parked": m.get("total_ever_parked"),
            "successful_park_rate": m.get("successful_park_rate"),
            "overflow_events": m.get("overflow_events_count"),
            "avg_search_time_min": m.get("avg_search_time_min"),
            "avg_wait_time_min": m.get("avg_wait_time_min"),
            "avg_gate_queue": m.get("avg_gate_queue"),
            "max_gate_queue": m.get("max_gate_queue"),
            "status": "ok",
        }
    except Exception as e:
        conn.close()
        return {"run_id": run_id, "scenario": scenario_yaml, "strategy": strategy_code,
                "seed": seed, "error": str(e), "status": "error"}


def build_summary(results: list) -> tuple[str, dict]:
    """Return (markdown_str, summary_dict) from results."""
    from collections import defaultdict
    import math

    groups = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            groups[(r["scenario"], r["strategy"])].append(r)

    def _stats(vals):
        if not vals:
            return None
        n = len(vals)
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if n > 1 else 0.0
        # t-critical ~ 1.96 for n>=30, use scipy if available else 2.0
        try:
            from scipy.stats import t as t_dist
            tc = float(t_dist.ppf(0.975, df=max(n - 1, 1)))
        except ImportError:
            tc = 2.0 if n < 30 else 1.96
        ci95 = tc * std / math.sqrt(n)
        return {"mean": round(mean, 4), "std": round(std, 4), "ci95": round(ci95, 4), "n": n}

    summary_dict = {}
    md_lines = [
        "# ParkingNav-X Experiment Results\n",
        "| Scenario | Strategy | n | Avg Search (min) | ±95%CI | Avg Wait (min) | ±95%CI | Avg Queue | Overflow |",
        "|----------|----------|---|------------------|--------|----------------|--------|-----------|----------|",
    ]

    for (sc, st), runs in sorted(groups.items()):
        key = f"{sc}|{st}"
        metrics = {}
        for metric in ["avg_search_time_min", "avg_wait_time_min", "avg_gate_queue", "overflow_events"]:
            vals = [r[metric] for r in runs if r.get(metric) is not None]
            metrics[metric] = _stats(vals)
        summary_dict[key] = {"scenario": sc, "strategy": st, "n": len(runs), "metrics": metrics}

        def _fmt(s):
            return f"{s['mean']:.3f}" if s else "—"
        def _ci(s):
            return f"{s['ci95']:.3f}" if s else "—"

        md_lines.append(
            f"| {sc} | {st} | {len(runs)} "
            f"| {_fmt(metrics.get('avg_search_time_min'))} | ±{_ci(metrics.get('avg_search_time_min'))} "
            f"| {_fmt(metrics.get('avg_wait_time_min'))} | ±{_ci(metrics.get('avg_wait_time_min'))} "
            f"| {_fmt(metrics.get('avg_gate_queue'))} "
            f"| {_fmt(metrics.get('overflow_events'))} |"
        )

    return "\n".join(md_lines), summary_dict


def main():
    parser = argparse.ArgumentParser(description="Run ParkingNav-X experiment matrix")
    parser.add_argument("--seeds", type=int, default=30, help="Seeds per cell (default 30, spec requires 30 for valid 95% CI)")
    parser.add_argument("--workers", type=int, default=2, help="Parallel workers")
    parser.add_argument("--scenarios", nargs="+", default=None,
                        help="Specific scenario yaml stems to run (e.g. E1_normal_day)")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip run_ids already in all_results.json (default True)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    results_path = RESULTS_DIR / "all_results.json"
    existing_ids = _existing_run_ids(results_path) if args.skip_existing else set()
    if existing_ids:
        print(f"Skipping {len(existing_ids)} already-completed run_ids")

    # Filter matrix
    matrix = EXPERIMENTS
    if args.scenarios:
        matrix = [(sc, sts) for sc, sts in matrix if sc in args.scenarios]

    # Build task list, skip existing
    tasks = []
    for scenario_yaml, strategies in matrix:
        if not (SCENARIO_DIR / f"{scenario_yaml}.yaml").exists():
            print(f"  ! Skipping {scenario_yaml} — YAML not found")
            continue
        for strategy_code in strategies:
            for seed in range(args.seeds):
                run_id = f"{scenario_yaml}-{strategy_code}-s{seed}"
                if run_id not in existing_ids:
                    tasks.append((scenario_yaml, strategy_code, seed))

    if not tasks:
        print("All tasks already completed. Nothing to run.")
        return

    print(f"Running {len(tasks)} tasks ({args.workers} workers) …\n")

    new_results = []
    completed = 0

    # Load existing results once for incremental flush
    existing_all = []
    if results_path.exists():
        try:
            existing_all = json.loads(results_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            existing_all = []
    existing_by_id = {r["run_id"]: r for r in existing_all}

    def _flush():
        merged_now = list(existing_by_id.values())
        results_path.write_text(json.dumps(merged_now, indent=2), encoding="utf-8")

    FLUSH_EVERY = 10
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_one, sc, st, sd): (sc, st, sd)
                   for sc, st, sd in tasks}
        for future in as_completed(futures):
            r = future.result()
            new_results.append(r)
            existing_by_id[r["run_id"]] = r
            completed += 1
            if r.get("status") == "ok":
                print(f"  OK [{completed}/{len(tasks)}] {r['run_id']} "
                      f"search={r.get('avg_search_time_min','?')} min "
                      f"overflow={r.get('overflow_events','?')}")
            else:
                print(f"  ERR [{completed}/{len(tasks)}] {r['run_id']}: {r.get('error','?')}")
            if completed % FLUSH_EVERY == 0:
                _flush()

    merged = list(existing_by_id.values())
    results_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"\nDone: {len(merged)} total results saved -> {results_path}")

    # Summary
    md, summary_dict = build_summary(merged)
    (RESULTS_DIR / "summary_table.md").write_text(md)
    (RESULTS_DIR / "results_summary.json").write_text(json.dumps(summary_dict, indent=2))
    print(f"Summary -> experiments/results/summary_table.md + results_summary.json")
    print("\n" + md)


if __name__ == "__main__":
    main()
