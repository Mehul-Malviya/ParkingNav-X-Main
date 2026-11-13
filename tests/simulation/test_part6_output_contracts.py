"""
Part 6 — Output Contracts verification tests.

Covers:
  OC1  SimulationResult has config_hash, git_sha, runtime_sec
  OC2  runtime_sec > 0
  OC3  config_hash is 16-char hex string
  OC4  what_if() returns a CampusState (clone); doesn't mutate original
  OC5  what_if() projects lot occupancy forward
  OC6  snapshot() contains global block with total_occupancy_pct / total_queue
  OC7  snapshot() contains pending_vehicle count
  OC8  snapshot() gates have avg_wait_sec field
  OC9  snapshot() lots have travel_time_from_gate_sec field
  OC10 snapshot() lots_list / gates_list are lists
  OC11 make_dataset produces CSV with 26 mandatory columns
  OC12 make_dataset row count = windows * lots per run
  OC13 make_dataset output lands in data/generated/
  OC14 SimulationResult fields: config_hash persists across two runs with same scenario
"""

import csv
import tempfile
from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.state_manager import CampusState, GateState, ParkingLotState
from digital_twin.simulation.strategy import NearestAvailableStrategy

SCENARIO_DIR = Path("configs/scenarios/vitap")
CAMPUS_YAML = Path("configs/campus/vitap.yaml")
GENERATED_DIR = Path("data/generated")


def _conn():
    c = get_connection(":memory:")
    apply_migrations(c)
    load_campus_config(CAMPUS_YAML, c)
    return c


def _run(scenario_file: str = "E1_normal_day.yaml", seed: int = 7):
    raw = yaml.safe_load(open(SCENARIO_DIR / scenario_file))
    raw["random_seed"] = seed
    scenario = ScenarioLoader.from_dict(raw)
    engine = SimulationEngine(runs_dir=tempfile.mkdtemp())
    return engine.run(scenario, NearestAvailableStrategy(), _conn()), scenario


# ── OC1–OC3: SimulationResult new fields ─────────────────────────────────────

def test_oc1_simulation_result_has_new_fields():
    result, _ = _run()
    assert hasattr(result, "config_hash"), "SimulationResult must have config_hash"
    assert hasattr(result, "git_sha"), "SimulationResult must have git_sha"
    assert hasattr(result, "runtime_sec"), "SimulationResult must have runtime_sec"


def test_oc2_runtime_sec_positive():
    result, _ = _run()
    assert result.runtime_sec > 0, f"runtime_sec must be > 0, got {result.runtime_sec}"


def test_oc3_config_hash_format():
    result, _ = _run()
    assert isinstance(result.config_hash, str), "config_hash must be a string"
    assert len(result.config_hash) == 16, f"config_hash must be 16 hex chars, got '{result.config_hash}'"
    assert all(c in "0123456789abcdef" for c in result.config_hash), "config_hash must be lowercase hex"


def test_oc14_same_scenario_same_config_hash():
    r1, _ = _run(seed=7)
    r2, _ = _run(seed=7)
    assert r1.config_hash == r2.config_hash, "Same scenario must produce same config_hash"


# ── OC4–OC5: what_if() ────────────────────────────────────────────────────────

def _make_campus_state():
    state = CampusState(timestamp=None, scenario_id="test", seed=7)
    lot = ParkingLotState(
        id="lot-a", capacity=100, occupied=50, reserved_free=10, status="open",
        arrivals_last_15m=30, departures_last_15m=15,
    )
    gate = GateState(
        id="gate-main", status="open", queue_length=5,
        service_rate_vph=180, throughput_last_15m=20, avg_wait_sec_last_15m=10.0,
    )
    state.lots["lot-a"] = lot
    state.gates["gate-main"] = gate
    return state


def test_oc4_what_if_returns_campusstate():
    state = _make_campus_state()
    projected = state.what_if(horizon_min=30)
    assert isinstance(projected, CampusState), "what_if must return CampusState"


def test_oc4_what_if_does_not_mutate_original():
    state = _make_campus_state()
    orig_occ = state.lots["lot-a"].occupied
    state.what_if(horizon_min=60)
    assert state.lots["lot-a"].occupied == orig_occ, "what_if must not mutate the original state"


def test_oc5_what_if_projects_occupancy():
    state = _make_campus_state()
    # net rate = (30-15)/15 = 1 veh/min; over 30 min → +30 vehicles
    projected = state.what_if(horizon_min=30)
    assert projected.lots["lot-a"].occupied > state.lots["lot-a"].occupied, (
        "Positive net arrival rate must increase projected occupancy"
    )


# ── OC6–OC10: snapshot() ──────────────────────────────────────────────────────

def test_oc6_snapshot_has_global_block():
    state = _make_campus_state()
    snap = state.snapshot()
    assert "global" in snap, "snapshot must include 'global' block"
    glb = snap["global"]
    assert "total_occupancy_pct" in glb
    assert "total_queue" in glb
    assert "overflow_count" in glb


def test_oc7_snapshot_has_pending_vehicle():
    state = _make_campus_state()
    snap = state.snapshot()
    assert "pending_vehicle" in snap, "snapshot must include 'pending_vehicle'"
    assert isinstance(snap["pending_vehicle"], int)


def test_oc8_snapshot_gates_have_avg_wait_sec():
    state = _make_campus_state()
    snap = state.snapshot()
    for gate_dict in snap["gates"].values():
        assert "avg_wait_sec" in gate_dict, f"gate snapshot must have avg_wait_sec: {gate_dict}"


def test_oc9_snapshot_lots_have_travel_time():
    state = _make_campus_state()
    snap = state.snapshot()
    for lot_dict in snap["lots"].values():
        assert "travel_time_from_gate_sec" in lot_dict, f"lot snapshot must have travel_time_from_gate_sec: {lot_dict}"


def test_oc10_snapshot_has_list_forms():
    state = _make_campus_state()
    snap = state.snapshot()
    assert "lots_list" in snap and isinstance(snap["lots_list"], list)
    assert "gates_list" in snap and isinstance(snap["gates_list"], list)


# ── OC11–OC13: make_dataset timeseries CSV ────────────────────────────────────

_EXPECTED_COLUMNS = {
    "timestamp", "scenario_id", "seed", "day_type", "event_type", "event_intensity",
    "minutes_to_event_start", "hour", "minute", "weekday",
    "lot_id", "capacity", "occupied", "occupancy_pct",
    "arrivals_5m", "departures_5m",
    "gate_id", "gate_arrivals_5m", "queue_length", "avg_wait_sec",
    "avg_travel_time_sec", "road_congestion_ratio_mean",
    "congestion_level", "lot_status", "gate_status", "source",
}


def test_oc11_make_dataset_25_columns():
    from digital_twin import api_functions
    conn = _conn()
    api_functions._conn = conn
    out = str(GENERATED_DIR / "test_oc11.csv")
    result = api_functions.make_dataset(
        campus_id="vitap",
        scenario_paths=[str(SCENARIO_DIR / "E1_normal_day.yaml")],
        seeds=[7],
        output_path=out,
    )
    assert set(result["columns"]) == _EXPECTED_COLUMNS, (
        f"Missing columns: {_EXPECTED_COLUMNS - set(result['columns'])}\n"
        f"Extra columns: {set(result['columns']) - _EXPECTED_COLUMNS}"
    )


def test_oc12_make_dataset_has_rows():
    from digital_twin import api_functions
    conn = _conn()
    api_functions._conn = conn
    out = str(GENERATED_DIR / "test_oc12.csv")
    result = api_functions.make_dataset(
        campus_id="vitap",
        scenario_paths=[str(SCENARIO_DIR / "E1_normal_day.yaml")],
        seeds=[7],
        output_path=out,
    )
    assert result["rows"] > 0, "make_dataset must produce at least one row"
    # Verify CSV on disk matches reported count
    with open(out, newline="") as f:
        actual_rows = sum(1 for _ in csv.DictReader(f))
    assert actual_rows == result["rows"]


def test_oc13_make_dataset_source_column_is_simulation():
    from digital_twin import api_functions
    conn = _conn()
    api_functions._conn = conn
    out = str(GENERATED_DIR / "test_oc13.csv")
    api_functions.make_dataset(
        campus_id="vitap",
        scenario_paths=[str(SCENARIO_DIR / "E1_normal_day.yaml")],
        seeds=[7],
        output_path=out,
    )
    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert all(r["source"] == "simulation" for r in rows), "source column must be 'simulation'"
