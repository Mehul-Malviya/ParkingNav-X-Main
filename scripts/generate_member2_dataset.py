#!/usr/bin/env python3
"""
Generate synthetic timestep CSVs for Member 2's ML pipeline.

Runs E1_normal_day and E2_event_placement across seeds 0-9.
Output: data/member2_synthetic/{scenario_id}/lots.csv

Format: 5-minute resolution, one row per (scenario_id, seed, window_start, lot_id).
source="simulated" distinguishes this from real observation data (Phase 3).

Full column spec (frozen Member-2 contract):
  scenario_id, seed, timestamp, sim_time_min, lot_id,
  capacity, occupied_spaces, occupancy_pct,
  arrivals_5m, departures_5m,
  day_type, event_type, event_intensity,
  source
"""

import csv
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digital_twin.config_loader import load_campus_config  # noqa: E402
from digital_twin.db import apply_migrations, get_connection  # noqa: E402
from digital_twin.simulation.engine import SimulationEngine  # noqa: E402
from digital_twin.simulation.scenario import ScenarioLoader  # noqa: E402
from digital_twin.simulation.strategy import FirstAvailableStrategy  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CAMPUS_CONFIG = REPO_ROOT / "configs/campus/vitap.yaml"

# Scenarios: path + metadata
SCENARIOS = {
    "E1_normal_day": {
        "path": REPO_ROOT / "configs/scenarios/vitap/E1_normal_day.yaml",
        "day_type": "normal",
        "event_type": None,
        "event_intensity": None,
    },
    "E2_event_placement": {
        "path": REPO_ROOT / "configs/scenarios/vitap/E2_event_placement.yaml",
        "day_type": "event",
        "event_type": "placement",
        "event_intensity": "high",
    },
}

SEEDS = list(range(10))
OUT_DIR = REPO_ROOT / "data" / "member2_synthetic"
WINDOW = 5        # aggregate to 5-minute windows
BASE_DATE = "2025-11-04"   # reference wall-clock date (normal day)
IST = timezone(timedelta(hours=5, minutes=30))

COLS = [
    "scenario_id", "seed", "timestamp", "sim_time_min",
    "lot_id", "capacity", "occupied_spaces", "occupancy_pct",
    "arrivals_5m", "departures_5m",
    "day_type", "event_type", "event_intensity",
    "source",
]

GATE_COLS = ["scenario_id", "seed", "tick", "sim_time_min", "gate_id", "queue_length", "source"]


def load_lot_capacities() -> dict:
    """Return {lot_id: usable_capacity} from vitap.yaml."""
    with open(CAMPUS_CONFIG) as f:
        campus = yaml.safe_load(f)
    return {lot["parking_lot_id"]: lot["usable_capacity"] for lot in campus["parking_lots"]}


def tick_to_timestamp(tick_min: int, start_min: int = 480) -> str:
    """Convert simulation tick (minutes since midnight) to ISO 8601 wall-clock string."""
    base = datetime.strptime(BASE_DATE, "%Y-%m-%d").replace(tzinfo=IST)
    wall = base + timedelta(minutes=start_min + tick_min)
    return wall.isoformat()


def aggregate_to_5min(timesteps: list, lot_capacities: dict) -> list:
    """
    Group per-tick timestep dicts into 5-minute windows.
    Returns list of per-window, per-lot dicts.

    arrivals_5m  = sum of positive occupancy deltas in window (net inflow)
    departures_5m = sum of negative occupancy deltas in window (net outflow)
    """
    lot_ids = list(lot_capacities.keys())

    # Build per-lot tick series: {lot_id: [(tick, occ), ...]}
    series: dict[str, list] = {lid: [] for lid in lot_ids}
    for ts in timesteps:
        tick = ts.get("tick", 0)
        for lid in lot_ids:
            occ = ts.get(f"parking_occupancy_{lid}", 0)
            series[lid].append((tick, int(occ)))

    if not timesteps:
        return []

    max_tick = max(ts.get("tick", 0) for ts in timesteps)
    windows = range(0, max_tick + 1, WINDOW)

    rows = []
    for w_start in windows:
        w_end = w_start + WINDOW
        for lid in lot_ids:
            cap = lot_capacities[lid]
            # Ticks that fall in [w_start, w_end)
            window_ticks = [(t, o) for t, o in series[lid] if w_start <= t < w_end]
            if not window_ticks:
                continue

            occ_end = window_ticks[-1][1]

            # arrivals and departures from tick-to-tick deltas within window
            arrivals = 0
            departures = 0
            prev_occ = window_ticks[0][1]
            for _, occ in window_ticks[1:]:
                delta = occ - prev_occ
                if delta > 0:
                    arrivals += delta
                elif delta < 0:
                    departures += abs(delta)
                prev_occ = occ

            occupancy_pct = round(occ_end / cap * 100, 2) if cap > 0 else 0.0

            rows.append({
                "w_start": w_start,
                "lot_id": lid,
                "capacity": cap,
                "occupied_spaces": occ_end,
                "occupancy_pct": occupancy_pct,
                "arrivals_5m": arrivals,
                "departures_5m": departures,
            })

    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lot_capacities = load_lot_capacities()
    print(f"Lots: {list(lot_capacities.keys())}")
    print(f"Columns: {COLS}\n")

    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(CAMPUS_CONFIG, conn)

    engine = SimulationEngine(runs_dir=tempfile.mkdtemp())   # keep the shared runs/ folder untouched
    strategy = FirstAvailableStrategy()

    for scenario_id, meta in SCENARIOS.items():
        scen_dir = OUT_DIR / scenario_id
        scen_dir.mkdir(parents=True, exist_ok=True)

        all_rows = []
        gate_rows = []

        for seed in SEEDS:
            print(f"  {scenario_id} seed={seed} ...", flush=True)
            scenario = ScenarioLoader.load(str(meta["path"]))
            start_min = getattr(scenario, "start_time_min", 480)
            scenario.random_seed = seed

            result = engine.run(scenario, strategy, conn)

            # Per-minute gate queue depth (tick = minute), one row per (seed, minute, gate)
            for ts in result.timesteps:
                for key, qlen in ts.items():
                    if key.startswith("gate_queue_"):
                        gate_rows.append({
                            "scenario_id": scenario_id, "seed": seed, "tick": ts["tick"],
                            "sim_time_min": start_min + ts["tick"], "gate_id": key[len("gate_queue_"):],
                            "queue_length": qlen, "source": "simulated",
                        })

            window_rows = aggregate_to_5min(result.timesteps, lot_capacities)

            for r in window_rows:
                all_rows.append({
                    "scenario_id": scenario_id,
                    "seed": seed,
                    "timestamp": tick_to_timestamp(r["w_start"], start_min),
                    "sim_time_min": start_min + r["w_start"],
                    "lot_id": r["lot_id"],
                    "capacity": r["capacity"],
                    "occupied_spaces": r["occupied_spaces"],
                    "occupancy_pct": r["occupancy_pct"],
                    "arrivals_5m": r["arrivals_5m"],
                    "departures_5m": r["departures_5m"],
                    "day_type": meta["day_type"],
                    "event_type": meta["event_type"] if meta["event_type"] else "",
                    "event_intensity": meta["event_intensity"] if meta["event_intensity"] else "",
                    "source": "simulated",
                })

        out_path = scen_dir / "lots.csv"
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(all_rows)

        gates_path = scen_dir / "gates.csv"
        with open(gates_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=GATE_COLS)
            w.writeheader()
            w.writerows(gate_rows)
        print(f"  -> {gates_path} ({len(gate_rows)} rows | columns: {GATE_COLS})")

        print(f"  -> {out_path}")
        print(f"     {len(all_rows)} rows | columns: {COLS}\n")

    print("Done. Hand data/member2_synthetic/ to Member 2.")
    print("NOTE: source='simulated' — this is NOT the real calibration dataset.")
    print("      Real data comes from field observations (docs/member1/observation_plan.md).")


if __name__ == "__main__":
    main()
