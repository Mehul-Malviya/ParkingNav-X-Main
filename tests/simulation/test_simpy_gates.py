"""Optional SimPy gate servers (gate_model: simpy)."""

import tempfile
from pathlib import Path

import pytest
import yaml

pytest.importorskip("simpy")

from digital_twin.config_loader import load_campus_config  # noqa: E402
from digital_twin.db import apply_migrations, get_connection  # noqa: E402
from digital_twin.simulation.engine import SimulationEngine  # noqa: E402
from digital_twin.simulation.gate_simpy import SimpyGates, lanes_for_capacity  # noqa: E402
from digital_twin.simulation.scenario import ScenarioLoader, ScenarioValidator  # noqa: E402
from digital_twin.simulation.strategy import NearestAvailableStrategy  # noqa: E402


def _run(scenario_name, gate_model, seed=0):
    raw = yaml.safe_load(open(f"configs/scenarios/vitap/{scenario_name}.yaml"))
    raw["random_seed"] = seed
    raw["gate_model"] = gate_model
    c = get_connection(":memory:")
    apply_migrations(c)
    load_campus_config(Path("configs/campus/vitap.yaml"), c)
    return SimulationEngine(runs_dir=tempfile.mkdtemp()).run(ScenarioLoader.from_dict(raw), NearestAvailableStrategy(), c)


def test_lanes_derived_from_documented_rate():
    assert lanes_for_capacity(6) == 2 and lanes_for_capacity(3) == 1 and lanes_for_capacity(1) == 1


def test_two_lane_gate_serves_two_per_twenty_seconds_fifo():
    g = SimpyGates({"g": 6})
    for v in "abcd":
        g.join("g", v)
    assert g.queue_length("g") == 4
    assert g.advance(19) == []
    assert g.advance(20) == ["a", "b"]
    assert g.queue_length("g") == 2
    assert g.advance(40) == ["c", "d"]


def test_closing_a_gate_requeues_waiting_vehicles_in_order():
    g = SimpyGates({"x": 3, "y": 3})
    for v in "abc":
        g.join("x", v)
    assert g.close_gate("x", "y") == ["a", "b", "c"]
    assert g.queue_length("x") == 0 and g.queue_length("y") == 3
    assert g.advance(20) == ["a"] and g.advance(40) == ["b"]


def test_invalid_gate_model_rejected():
    raw = yaml.safe_load(open("configs/scenarios/vitap/E1_normal_day.yaml"))
    raw["gate_model"] = "magic"
    c = get_connection(":memory:")
    apply_migrations(c)
    load_campus_config(Path("configs/campus/vitap.yaml"), c)
    assert any("gate_model" in e for e in ScenarioValidator.validate(ScenarioLoader.from_dict(raw), c))


def test_simpy_run_is_deterministic_and_conserves():
    a, b = _run("E1_normal_day", "simpy", 3), _run("E1_normal_day", "simpy", 3)
    assert [v["waiting_time_seconds"] for v in a.vehicles] == [v["waiting_time_seconds"] for v in b.vehicles]
    assert a.secondary_metrics["conservation_check"] is True


def test_low_load_wait_is_about_one_service_time():
    wait_min = _run("E1_normal_day", "simpy").metrics["avg_wait_time_min"]
    assert 0.2 < wait_min < 0.6, wait_min   # 20 s service + small queueing; tick model gives ~0


def test_overload_wait_matches_tick_model():
    tick = _run("parking_full", "tick").metrics["avg_wait_time_min"]
    simpy_ = _run("parking_full", "simpy")
    assert simpy_.secondary_metrics["conservation_check"] is True
    assert abs(simpy_.metrics["avg_wait_time_min"] - tick) / tick < 0.15
