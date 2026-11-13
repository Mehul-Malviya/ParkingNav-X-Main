"""Vehicle-type dwell: default unchanged, mix honoured, validation, and dwell really differs by type."""

import math
import random
import tempfile
from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import DWELL_LOGNORMAL_MU, SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader, ScenarioValidator
from digital_twin.simulation.strategy import FirstAvailableStrategy

E8 = "configs/scenarios/vitap/E8_vehicle_types.yaml"


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    apply_migrations(c)
    load_campus_config(Path("configs/campus/vitap.yaml"), c)
    return c


def _arrivals(path, **overrides):
    raw = yaml.safe_load(open(path))
    raw.update(overrides)
    sc = ScenarioLoader.from_dict(raw)
    return sc, SimulationEngine._generate_arrivals(sc, random.Random(3), ["vitap-gate-main"], ["d"])


def test_no_vehicle_types_means_global_dwell_for_everyone():
    _, vs = _arrivals("configs/scenarios/vitap/E1_normal_day.yaml")
    assert all(v.vehicle.vehicle_type == "general" and v.dwell_mu == DWELL_LOGNORMAL_MU for v in vs)


def test_mix_follows_shares_and_sets_dwell_parameters():
    sc, vs = _arrivals(E8)
    counts = {t: sum(1 for v in vs if v.vehicle.vehicle_type == t) for t in sc.vehicle_types}
    n = len(vs)
    for t, spec in sc.vehicle_types.items():
        assert abs(counts[t] / n - spec["share"]) < 0.08, (t, counts)
    for v in vs:
        assert abs(v.dwell_mu - math.log(sc.vehicle_types[v.vehicle.vehicle_type]["dwell_median_minutes"])) < 1e-9


def test_event_override_beats_vehicle_type():
    raw = yaml.safe_load(open("configs/scenarios/vitap/E2_event_placement.yaml"))
    raw["vehicle_types"] = {"a": {"share": 1, "dwell_median_minutes": 60}}
    raw["event_conditions"]["dwell_median_minutes"] = 300
    sc = ScenarioLoader.from_dict(raw)
    vs = SimulationEngine._generate_arrivals(sc, random.Random(1), ["vitap-gate-main"], ["d"])
    s0 = sc.event_conditions["start_tick"]
    e0 = s0 + sc.event_conditions["duration_ticks"]
    inside = [v for v in vs if s0 <= v.vehicle.arrival_tick < e0]
    outside = [v for v in vs if not s0 <= v.vehicle.arrival_tick < e0]
    assert inside and outside
    assert all(abs(v.dwell_mu - math.log(300)) < 1e-9 for v in inside)
    assert all(abs(v.dwell_mu - math.log(60)) < 1e-9 for v in outside)


@pytest.mark.parametrize("bad", [
    {"student": {"share": 0, "dwell_median_minutes": 60}},
    {"student": {"share": 1, "dwell_median_minutes": 0}},
    {"student": {"share": 1, "dwell_median_minutes": 60, "dwell_sigma": -1}},
    {},
])
def test_invalid_vehicle_types_rejected_with_clear_message(conn, bad):
    raw = yaml.safe_load(open("configs/scenarios/vitap/E1_normal_day.yaml"))
    raw["vehicle_types"] = bad
    errors = ScenarioValidator.validate(ScenarioLoader.from_dict(raw), conn)
    assert any("vehicle_types" in e for e in errors), errors


def test_dwell_actually_differs_by_type_in_a_run(conn):
    sc = ScenarioLoader.load(E8)
    sc.random_seed = 5
    r = SimulationEngine(runs_dir=tempfile.mkdtemp()).run(sc, FirstAvailableStrategy(), conn)
    stay = {}
    for v in r.vehicles:
        t = {e["state"]: e["t_sec"] for e in v["state_trace"]}
        if "PARKED" in t and "DEPARTING" in t:
            stay.setdefault(v["vehicle_type"], []).append((t["DEPARTING"] - t["PARKED"]) / 60)
    mean = {k: sum(x) / len(x) for k, x in stay.items()}
    assert set(mean) == {"student", "staff", "visitor"}
    assert mean["visitor"] < mean["student"] < mean["staff"], mean
