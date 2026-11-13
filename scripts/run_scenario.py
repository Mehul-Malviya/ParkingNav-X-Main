"""
Run a VIT-AP scenario across all strategies and compare results side by side.

Usage:
    python scripts/run_scenario.py peak_hour
    python scripts/run_scenario.py E1_normal_day
    python scripts/run_scenario.py parking_full
    python scripts/run_scenario.py road_closure
    python scripts/run_scenario.py E4_gate_closure
    python scripts/run_scenario.py E2_event_placement

Results saved to runs/vitap-<scenario>/<strategy>/seed_0/metrics.json
"""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from digital_twin.config_loader import load_campus_config  # noqa: E402
from digital_twin.db import apply_migrations, get_connection  # noqa: E402
from digital_twin.simulation.demo_strategies import (  # noqa: E402
    ParkingNavXFullStrategy,
    PredictionOnlyStrategy,
)
from digital_twin.simulation.engine import SimulationEngine  # noqa: E402
from digital_twin.simulation.scenario import ScenarioLoader  # noqa: E402
from digital_twin.simulation.strategy import (  # noqa: E402
    FirstAvailableStrategy,
    NearestAvailableStrategy,
)

SCENARIO_DIR = ROOT / "configs" / "scenarios" / "vitap"
CAMPUS_YAML  = ROOT / "configs" / "campus" / "vitap.yaml"

STRATEGIES = [
    ("B1", "First Available",           FirstAvailableStrategy()),
    ("B2", "Nearest Available",         NearestAvailableStrategy()),
    ("B3", "Prediction only",           PredictionOnlyStrategy()),
    ("P",  "ParkingNav-X (full)",       ParkingNavXFullStrategy()),
]

W = 28  # column width


def fmt(val, suffix=""):
    if val is None or val == "":
        return "-"
    if isinstance(val, float):
        return f"{val:.2f}{suffix}"
    return f"{val}{suffix}"


def run_strategy(scenario, strategy, conn, label):
    engine = SimulationEngine()
    run_id = f"vitap-demo-{uuid.uuid4().hex[:8]}"
    result = engine.run(scenario, strategy, conn, run_id=run_id)
    return result.metrics


def main():
    scenario_name = sys.argv[1] if len(sys.argv) > 1 else "peak_hour"
    scenario_file = SCENARIO_DIR / f"{scenario_name}.yaml"
    if not scenario_file.exists():
        available = [f.stem for f in SCENARIO_DIR.glob("*.yaml")]
        print(f"\nScenario '{scenario_name}' not found.")
        print(f"Available: {', '.join(sorted(available))}\n")
        sys.exit(1)

    db_path = ROOT / "digital_twin.db"
    conn = get_connection(db_path)
    apply_migrations(conn)
    load_campus_config(CAMPUS_YAML, conn)
    scenario = ScenarioLoader.load(scenario_file)

    print(f"\n{'='*100}")
    print("  ParkingNav-X  |  VIT-AP University Smart Parking Digital Twin")
    print(f"  Scenario  : {scenario_name}")
    print("  Campus    : VIT-AP, Amaravati, Andhra Pradesh")
    print(f"  Duration  : {scenario.duration_minutes} min  |  Vehicles : {scenario.vehicle_count}")
    print(f"{'='*100}")
    print("  Running all 4 strategies (B1 -> B2 -> B3 -> P) ...\n")

    results = []
    for code, name, strategy in STRATEGIES:
        print(f"  [{code}] {name} ...")
        m = run_strategy(scenario, strategy, conn, code)
        results.append((code, name, m))
        out_dir = ROOT / "runs" / f"vitap-{scenario_name}" / code / "seed_0"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text(json.dumps(m, indent=2))

    conn.close()

    # -- Comparison table -------------------------------------------------------
    col = 18
    headers = [f"{r[0]}-{r[1].split()[0]}" for r in results]
    metrics_list = [r[2] for r in results]

    def row(metric_label, key):
        vals = [fmt(m.get(key)) for m in metrics_list]
        print(f"  {metric_label:<28}" + "".join(f"{v:>{col}}" for v in vals))

    print(f"\n{'─'*100}")
    print(f"  {'Metric':<28}" + "".join(f"{h:>{col}}" for h in headers))
    print(f"{'─'*100}")
    row("Vehicles simulated",    "total_vehicles")
    row("Vehicles parked",       "parked_vehicles")
    row("Completed trips",       "completed_vehicles")
    row("Overflow events",       "overflow_events_count")
    row("Avg search time (min)", "avg_search_time_min")
    row("Avg wait time (min)",   "avg_wait_time_min")
    row("Avg gate queue",        "avg_gate_queue")
    row("Peak gate queue",       "max_gate_queue")
    print(f"{'─'*100}")

    # -- Winner ----------------------------------------------------------------
    search_times = [m.get("avg_search_time_min") or 999 for m in metrics_list]
    best_idx = search_times.index(min(search_times))
    best = results[best_idx]
    print(f"\n  Best strategy : [{best[0]}] {best[1]}  (lowest avg search time)")
    print("\n  What each strategy does:")
    print("   B1  First Available     - naive, no optimisation")
    print("   B2  Nearest Available   - picks closest open lot")
    print("   B3  Prediction only     - avoids nearly-full lots using fill-rate forecast")
    print("   P   ParkingNav-X (full) - prediction + gate load balancing + zone routing")
    print(f"\n  Results saved to: runs/vitap-{scenario_name}/")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
