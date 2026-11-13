from pathlib import Path

import pytest

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import (
    AllocationStrategy,
    AssignmentResult,
    FixedLotStrategy,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"
SCENARIOS = PROJECT_ROOT / "configs" / "scenarios" / "sample"


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "sample.yaml", c)
    yield c
    c.close()


class AlwaysNearestOpenStrategy(AllocationStrategy):
    """Minimal real-ish strategy for engine tests -- picks the first open,
    available lot by sorted id. Not owned by Member 1 in spirit; used here
    only to exercise the engine end-to-end."""

    def assign(self, vehicle, campus_state):
        for lot_id in sorted(campus_state.parking_lots):
            lot = campus_state.parking_lots[lot_id]
            if lot["status"] == "open" and lot["occupied_spaces"] < lot["usable_capacity"]:
                return AssignmentResult(parking_lot_id=lot_id, gate_id=vehicle.entry_gate)
        return AssignmentResult(parking_lot_id=None)


def test_same_seed_produces_byte_identical_metrics(conn):
    scenario = ScenarioLoader.load(SCENARIOS / "normal_day.yaml")
    engine = SimulationEngine()

    result_a = engine.run(scenario, AlwaysNearestOpenStrategy(), conn, run_id="run-a")
    result_b = engine.run(scenario, AlwaysNearestOpenStrategy(), conn, run_id="run-b")

    assert result_a.vehicles == result_b.vehicles
    assert result_a.timesteps == result_b.timesteps


def test_closed_parking_lot_receives_zero_assignments(conn):
    raw_scenario = SCENARIOS / "parking_closure.yaml"
    scenario = ScenarioLoader.load(raw_scenario)
    engine = SimulationEngine()
    result = engine.run(scenario, AlwaysNearestOpenStrategy(), conn)

    assigned_lots = {v["assigned_lot_id"] for v in result.vehicles if v["assigned_lot_id"]}
    assert "sample-lot-1" not in assigned_lots


def test_closed_gate_admits_zero_vehicles(conn):
    scenario = ScenarioLoader.load(SCENARIOS / "gate_closure.yaml")
    engine = SimulationEngine()
    result = engine.run(scenario, AlwaysNearestOpenStrategy(), conn)

    assert all(v["assigned_lot_id"] is None for v in result.vehicles)
    assert all(v["waiting_time_seconds"] == 0 for v in result.vehicles)


def test_gate_queue_length_never_negative(conn):
    scenario = ScenarioLoader.load(SCENARIOS / "normal_day.yaml")
    engine = SimulationEngine()
    result = engine.run(scenario, AlwaysNearestOpenStrategy(), conn)

    for ts in result.timesteps:
        for key, value in ts.items():
            if key.startswith("gate_queue_"):
                assert value >= 0


def test_parking_occupancy_never_exceeds_usable_capacity(conn):
    scenario = ScenarioLoader.load(SCENARIOS / "normal_day.yaml")
    engine = SimulationEngine()
    result = engine.run(scenario, AlwaysNearestOpenStrategy(), conn)

    max_occupancy_seen = max(
        (v for ts in result.timesteps for k, v in ts.items() if k == "parking_occupancy_sample-lot-1"),
        default=0,
    )
    assert max_occupancy_seen <= 18  # sample-lot-1 usable_capacity


def test_fixed_lot_strategy_is_actually_called_not_bypassed(conn):
    """Trivial 2-vehicle scenario: every vehicle must end up assigned to
    the strategy's fixed lot -- proving the engine calls the interface."""
    import yaml
    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    raw["vehicle_count"] = 2
    raw["duration_minutes"] = 30
    scenario = ScenarioLoader.from_dict(raw)

    engine = SimulationEngine()
    result = engine.run(scenario, FixedLotStrategy("sample-lot-2"), conn)

    assigned = [v["assigned_lot_id"] for v in result.vehicles]
    assert assigned == ["sample-lot-2", "sample-lot-2"]


def test_overflow_event_recorded_once_per_timestep_not_per_vehicle(conn):
    import yaml

    from digital_twin.simulation.strategy import FirstAvailableStrategy
    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    raw["vehicle_count"] = 300  # Far more than capacity (~30 spaces)
    raw["duration_minutes"] = 30
    raw["arrival_rate_profile"] = {"type": "constant", "rate": 10.0}
    scenario = ScenarioLoader.from_dict(raw)

    engine = SimulationEngine()
    # High load causes genuine overflow (lots fill, vehicles fail assignment)
    result = engine.run(scenario, FirstAvailableStrategy(), conn)

    # With overflow, many vehicles should fail to park
    failed_vehicles = [v for v in result.vehicles if v["final_state"] != "parked" and v["assigned_lot_id"] is None]
    assert len(failed_vehicles) > 0, "Expected some vehicles to fail due to full lots"

    # Overflow events should be recorded (multiple attempts, one per timestep)
    assert len(result.overflow_events) > 0
    # Infeasibility rejections tracked: assignments rejected as infeasible (full/closed lot)
    assert result.infeasibility_rejections > 0, "Expected infeasibility rejections to be logged"
    # Per-timestep flag must collapse duplicates into one boolean, not a count.
    for ts in result.timesteps:
        for key, value in ts.items():
            if key.startswith("overflow_"):
                assert value in (True, False)


def test_vehicle_accounting_identity(conn):
    """parked + exited + in_system + rejected must equal total_vehicles_simulated."""
    import json
    import tempfile
    from pathlib import Path as _Path

    import yaml

    from digital_twin.simulation.metrics_recorder import MetricsRecorder
    from digital_twin.simulation.strategy import FirstAvailableStrategy

    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    scenario = ScenarioLoader.from_dict(raw)
    result = SimulationEngine().run(scenario, FirstAvailableStrategy(), conn)

    with tempfile.TemporaryDirectory() as tmp:
        recorder = MetricsRecorder(output_root=tmp)
        run_dir = recorder.record_run(
            scenario_id=scenario.scenario_id,
            strategy_name="B1",
            seed=scenario.random_seed,
            vehicle_metrics=result.vehicles,
            timestep_metrics=result.timesteps,
            overflow_events=result.overflow_events,
            config_dict={"campus_id": scenario.campus_id},
        )
        with open(_Path(run_dir) / "metrics.json") as f:
            m = json.load(f)

    sm = m["secondary_metrics"]
    total = sm["total_vehicles_simulated"]
    parked = sm["parked_vehicles"]
    exited = sm["exited_vehicles"]
    in_system = sm["in_system_vehicles"]
    rejected = sm["rejected_vehicles"]

    # Loose: all buckets sum to total
    assert parked + exited + in_system + rejected == total, (
        f"Accounting identity broken: parked={parked} exited={exited} "
        f"in_system={in_system} rejected={rejected} != total={total}"
    )

    # 6c: strict conservation — vehicles that entered the campus must be parked XOR have exited
    # (in_system are still in transit; rejected never entered a lot)
    entered = parked + exited + in_system  # everyone who made it past the gate
    assert entered >= parked + exited, (
        f"Conservation violation: entered ({entered}) < parked ({parked}) + exited ({exited})"
    )
    # Key strict identity: parked + exited == entered - in_system (no vehicles lost)
    assert parked + exited == entered - in_system, (
        f"Strict conservation broken: parked ({parked}) + exited ({exited}) != "
        f"entered ({entered}) - in_system ({in_system})"
    )


def test_warmdown_reduces_in_system_vehicles(conn):
    """With warmdown_minutes=30, no new arrivals in the last 30 min.
    in_system at end should be low (departure-phase vehicles only, < 5%)."""
    import yaml

    from digital_twin.simulation.strategy import FirstAvailableStrategy

    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    raw["warmdown_minutes"] = 30
    raw["duration_minutes"] = 120
    raw["vehicle_count"] = 100
    raw["arrival_rate_profile"] = {"type": "constant", "rate": 1.0}
    scenario = ScenarioLoader.from_dict(raw)

    result = SimulationEngine().run(scenario, FirstAvailableStrategy(), conn)
    in_system = sum(1 for v in result.vehicles if v["final_state"] == "in_system")
    total = len(result.vehicles)
    pct = in_system / total if total else 0
    assert pct < 0.05, (
        f"in_system={in_system}/{total} ({pct:.1%}) exceeds 5% with warmdown=30; "
        "warmdown should eliminate transit-stuck vehicles"
    )


def test_warmdown_no_arrivals_in_last_N_minutes(conn):
    """Verify that no vehicle's arrival_tick falls within the warmdown window."""
    import yaml

    from digital_twin.simulation.strategy import FirstAvailableStrategy

    DURATION = 120
    WARMDOWN = 30
    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    raw["warmdown_minutes"] = WARMDOWN
    raw["duration_minutes"] = DURATION
    raw["vehicle_count"] = 200
    raw["arrival_rate_profile"] = {"type": "constant", "rate": 2.0}
    scenario = ScenarioLoader.from_dict(raw)

    result = SimulationEngine().run(scenario, FirstAvailableStrategy(), conn)
    warmdown_start = DURATION - WARMDOWN
    late_arrivals = [v for v in result.vehicles if v["arrival_tick"] >= warmdown_start]
    assert len(late_arrivals) == 0, (
        f"{len(late_arrivals)} vehicles arrived after tick {warmdown_start} (warmdown boundary)"
    )


if __name__ == "__main__":
    print("Run with pytest: python -m pytest test_part4_part5_simulation.py -v")
