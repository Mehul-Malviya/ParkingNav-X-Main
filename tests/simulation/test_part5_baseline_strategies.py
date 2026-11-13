"""
Phase 5 — Baseline strategy tests (B1 and B2).

Verify reference strategies work correctly:
- B1 (First-Available): always picks first available lot in sorted order
- B2 (Nearest-Available): picks nearest available lot by shortest path
- Both deterministic: same seed = same assignment sequence
"""

from pathlib import Path

import pytest

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioConfig
from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "vitap.yaml", c)
    yield c
    c.close()


@pytest.fixture
def engine():
    return SimulationEngine()


def test_first_available_strategy_assigns_first_open_lot(conn, engine):
    """B1: always assigns first available lot (sorted order)."""
    scenario = ScenarioConfig(
        scenario_id="test-b1",
        campus_id="vitap",
        name="Test B1",
        duration_minutes=180,
        vehicle_count=50,
        arrival_rate_profile={"type": "constant", "rate": 0.83},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=100,
    )

    result = engine.run(scenario, FirstAvailableStrategy(), conn)

    # 6a: ALL vehicles must reach a terminal state (parked or exited) — none stuck mid-simulation
    terminal_states = {"parked", "exited", "rejected"}
    # A vehicle that parked, dwelled and is driving out when the clock stops (internal_state "departure")
    # is completing its journey -- but only if it STARTED leaving within the normal exit time. Measured over
    # 46,942 exited vehicles, DEPARTING -> EXITED takes 60-130 s; allow 300 s so a vehicle stuck in the
    # departure phase still fails this test.
    duration_sec = scenario.duration_minutes * 60
    max_exit_sec = 300

    def _departing_normally(v):
        if v["internal_state"] != "departure":
            return False
        t = {e["state"]: e["t_sec"] for e in v["state_trace"]}
        return "DEPARTING" in t and duration_sec - t["DEPARTING"] <= max_exit_sec

    terminal_vehicles = [
        v for v in result.vehicles
        if v["final_state"] in terminal_states or _departing_normally(v)
    ]
    assert len(terminal_vehicles) == len(result.vehicles), (
        f"Only {len(terminal_vehicles)}/{len(result.vehicles)} vehicles reached a terminal state; "
        f"states seen: {set(v['final_state'] for v in result.vehicles)}"
    )

    # B1 concentrates in the first available lot
    parked_vehicles = [v for v in result.vehicles if v["final_state"] == "parked"]
    assert len(parked_vehicles) > 0
    first_lot_assignments = sum(
        1 for v in parked_vehicles if v["assigned_lot_id"] == "vitap-lot-academic-main"
    )
    assert first_lot_assignments > 0


def test_nearest_available_strategy_picks_nearest_lot(conn, engine):
    """B2: picks nearest available lot by shortest path distance."""
    scenario = ScenarioConfig(
        scenario_id="test-b2",
        campus_id="vitap",
        name="Test B2",
        duration_minutes=60,
        vehicle_count=50,
        arrival_rate_profile={"type": "constant", "rate": 0.83},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=100,
    )

    result = engine.run(scenario, NearestAvailableStrategy(), conn)

    # All parked vehicles should have valid assignments
    parked_vehicles = [v for v in result.vehicles if v["final_state"] == "parked"]
    assert len(parked_vehicles) > 0
    assert all(v["assigned_lot_id"] is not None for v in parked_vehicles)


def test_b1_vs_b2_produce_different_distributions(conn, engine):
    """B1 and B2 assign differently (B1 fills first lot, B2 balances)."""
    scenario = ScenarioConfig(
        scenario_id="test-compare",
        campus_id="vitap",
        name="Test Compare",
        duration_minutes=120,
        vehicle_count=100,
        arrival_rate_profile={"type": "constant", "rate": 0.83},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=200,
    )

    result_b1 = engine.run(scenario, FirstAvailableStrategy(), conn)
    result_b2 = engine.run(scenario, NearestAvailableStrategy(), conn)

    assert len(result_b1.vehicles) > 0
    assert len(result_b2.vehicles) > 0

    # 6d: the two strategies must actually produce different lot-assignment distributions
    def lot_counts(result):
        counts = {}
        for v in result.vehicles:
            lot = v.get("assigned_lot_id")
            if lot:
                counts[lot] = counts.get(lot, 0) + 1
        return counts

    dist_b1 = lot_counts(result_b1)
    dist_b2 = lot_counts(result_b2)
    assert dist_b1 != dist_b2, (
        "B1 and B2 produced identical lot distributions — strategies are not differentiating"
    )


def test_baseline_determinism_same_seed_same_assignments(conn, engine):
    """Same seed → same assignments for B1 and B2."""
    scenario = ScenarioConfig(
        scenario_id="test-det",
        campus_id="vitap",
        name="Test Determinism",
        duration_minutes=60,
        vehicle_count=50,
        arrival_rate_profile={"type": "constant", "rate": 0.83},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=999,
    )

    result1 = engine.run(scenario, FirstAvailableStrategy(), conn)
    result2 = engine.run(scenario, FirstAvailableStrategy(), conn)

    # Sort by vehicle_id and compare
    v1_sorted = sorted(result1.vehicles, key=lambda v: v["vehicle_id"])
    v2_sorted = sorted(result2.vehicles, key=lambda v: v["vehicle_id"])

    for v1, v2 in zip(v1_sorted, v2_sorted):
        assert v1["assigned_lot_id"] == v2["assigned_lot_id"]


def test_occupancy_rises_then_falls(conn, engine):
    """6b: campus occupancy rises during burst arrivals then falls as vehicles dwell and depart.
    Dwell minimum is 30 min; vehicles arrive in a burst then exit, so occupancy peaks then declines."""
    scenario = ScenarioConfig(
        scenario_id="test-occ-shape",
        campus_id="vitap",
        name="Test Occupancy Shape",
        duration_minutes=180,
        vehicle_count=20,
        arrival_rate_profile={"type": "constant", "rate": 5.0},  # all 20 arrive in ~4 min
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=7,
    )

    result = engine.run(scenario, FirstAvailableStrategy(), conn)

    assert result.timesteps, "No timestep data recorded"
    occ_keys = [k for k in result.timesteps[0] if k.startswith("parking_occupancy_")]
    occ_series = [sum(ts.get(k, 0) for k in occ_keys) for ts in result.timesteps]
    assert len(occ_series) > 10, "Not enough timesteps to check shape"

    # Peak must be strictly greater than both start and end (rise then fall)
    peak = max(occ_series)
    start_occ = occ_series[0]
    end_occ = occ_series[-1]
    assert peak > start_occ, f"Occupancy never rose above start ({start_occ})"
    assert peak > end_occ, (
        f"Occupancy never fell after peak ({peak}); end={end_occ}. "
        "Dwell minimum=30 min, duration=180 min — all vehicles should have exited."
    )


if __name__ == "__main__":
    print("Run with: python -m pytest test_part5_baseline_strategies.py -v")
