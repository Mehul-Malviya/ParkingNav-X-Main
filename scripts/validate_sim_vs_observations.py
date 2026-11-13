"""
M13 Validation: compare simulation output against observed lot occupancy.

Runs the simulation over the same time window as vitap_observations.csv and
computes residuals (RMSE, MAE, MAPE) per lot and overall.

Usage:
    python scripts/validate_sim_vs_observations.py [--scenario E1_normal_day] [--seed 0]

Outputs a table of per-lot residuals and an overall score to stdout.
All data is synthetic — labeled in the CSV and in simulation output.
"""

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OBS_CSV = ROOT / "data" / "observations" / "vitap_observations.csv"
CAMPUS_YAML = ROOT / "configs" / "campus" / "vitap.yaml"
SCENARIO_DIR = ROOT / "configs" / "scenarios" / "vitap"


def load_observations(csv_path: Path) -> dict:
    """Return {lot_id: [(sim_time_min, fill_rate), ...]} from the observation CSV."""
    import csv
    from datetime import datetime, timezone

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                lot_id = r["parking_lot_id"].strip()
                occ = int(r["occupied_spaces"])
                cap = int(r["capacity"])
                rows.append((ts, lot_id, occ, cap))
            except (KeyError, ValueError):
                continue

    if not rows:
        return {}

    # Normalise to sim-time in minutes from earliest timestamp
    t0 = min(r[0] for r in rows)
    obs: dict = {}
    for ts, lot_id, occ, cap in rows:
        if cap <= 0:
            continue
        sim_min = (ts - t0).total_seconds() / 60.0
        obs.setdefault(lot_id, []).append((sim_min, occ / cap))
    return obs


def run_simulation_for_scenario(scenario_stem: str, seed: int) -> dict:
    """
    Run one simulation and return per-lot fill rate timeseries.
    Returns {lot_id: [(sim_time_min, fill_rate), ...]}
    """
    from digital_twin.db import get_connection, apply_migrations
    from digital_twin.config_loader import load_campus_config
    from digital_twin.simulation.engine import SimulationEngine
    from digital_twin.simulation.scenario import ScenarioLoader
    from digital_twin.simulation.strategy import NearestAvailableStrategy

    scenario_file = SCENARIO_DIR / f"{scenario_stem}.yaml"
    if not scenario_file.exists():
        raise FileNotFoundError(f"Scenario not found: {scenario_file}")

    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(CAMPUS_YAML, conn)

    sc = ScenarioLoader.load(scenario_file)
    sc.random_seed = seed
    strategy = NearestAvailableStrategy()

    engine = SimulationEngine()
    result = engine.run(sc, strategy, conn, run_id=f"validate-{scenario_stem}-s{seed}")

    # Convert timeline to per-lot fill rate series
    lot_series: dict = {}
    for ts_entry in result.timesteps:
        sim_min = ts_entry.get("sim_time_min", ts_entry.get("tick", 0))
        for key, val in ts_entry.items():
            if key.startswith("occupancy_") and isinstance(val, (int, float)):
                lot_id = key[len("occupancy_"):]
                lot_series.setdefault(lot_id, []).append((sim_min, val))
    return lot_series


def _rmse(pairs: list) -> float:
    if not pairs:
        return float("nan")
    return math.sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs))


def _mae(pairs: list) -> float:
    if not pairs:
        return float("nan")
    return sum(abs(a - b) for a, b in pairs) / len(pairs)


def _mape(pairs: list) -> float:
    valid = [(a, b) for a, b in pairs if abs(a) > 1e-6]
    if not valid:
        return float("nan")
    return 100.0 * sum(abs(a - b) / abs(a) for a, b in valid) / len(valid)


def align_series(obs_series: list, sim_series: list, tolerance_min: float = 5.0) -> list:
    """
    Match observation timestamps to nearest simulation timestamps within tolerance.
    Returns [(obs_fill, sim_fill), ...] aligned pairs.
    """
    pairs = []
    sim_lookup = {round(t, 1): v for t, v in sim_series}
    for obs_t, obs_v in obs_series:
        # Find closest sim tick within tolerance
        best_t, best_d = None, float("inf")
        for sim_t in sim_lookup:
            d = abs(sim_t - obs_t)
            if d < best_d and d <= tolerance_min:
                best_d, best_t = d, sim_t
        if best_t is not None:
            pairs.append((obs_v, sim_lookup[best_t]))
    return pairs


def main():
    parser = argparse.ArgumentParser(description="Sim-vs-observations validation (M13)")
    parser.add_argument("--scenario", default="E1_normal_day",
                        help="Scenario YAML stem to run (default: E1_normal_day)")
    parser.add_argument("--seed", type=int, default=0, help="Random seed (default: 0)")
    parser.add_argument("--tolerance", type=float, default=5.0,
                        help="Max time gap (minutes) to align obs to sim tick (default: 5)")
    args = parser.parse_args()

    print(f"Loading observations from {OBS_CSV} ...")
    if not OBS_CSV.exists():
        print(f"ERROR: {OBS_CSV} not found")
        sys.exit(1)
    obs = load_observations(OBS_CSV)
    print(f"  Loaded observations for {len(obs)} lots: {sorted(obs.keys())}")

    print(f"\nRunning simulation: scenario={args.scenario} seed={args.seed} ...")
    try:
        sim = run_simulation_for_scenario(args.scenario, args.seed)
    except Exception as e:
        print(f"ERROR running simulation: {e}")
        sys.exit(1)
    print(f"  Simulation produced timeseries for {len(sim)} lots: {sorted(sim.keys())}")

    # Report
    print(f"\n{'Lot':<40} {'n_pairs':>7} {'RMSE':>8} {'MAE':>8} {'MAPE%':>8}")
    print("-" * 75)

    all_pairs = []
    for lot_id in sorted(obs.keys()):
        if lot_id not in sim:
            print(f"  {lot_id:<38} {'—':>7}  (no simulation data for this lot)")
            continue
        pairs = align_series(obs[lot_id], sim[lot_id], tolerance_min=args.tolerance)
        all_pairs.extend(pairs)
        rmse = _rmse(pairs)
        mae = _mae(pairs)
        mape = _mape(pairs)
        print(f"  {lot_id:<38} {len(pairs):>7} {rmse:>8.4f} {mae:>8.4f} {mape:>8.2f}")

    print("-" * 75)
    print(f"  {'OVERALL':<38} {len(all_pairs):>7} {_rmse(all_pairs):>8.4f} "
          f"{_mae(all_pairs):>8.4f} {_mape(all_pairs):>8.2f}")
    print("\nNote: All data is synthetic (source=simulated in observations CSV).")
    print("RMSE/MAE in fill-rate units [0,1]; MAPE in percent.")


if __name__ == "__main__":
    main()
