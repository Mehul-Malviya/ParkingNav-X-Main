"""
Frozen output contracts (docs/member1/contracts.md), checked from the producer side.

These tests stand in for the teammates' code: Member 2 (dataset CSVs), Member 3 (StateSnapshot, fork,
pluggable strategy) and Member 4 (API functions, run artifacts) all consume exactly what is asserted here.
If a column, key or shape below changes, a consumer breaks -- so the change must be deliberate.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from digital_twin import api_functions as api
from digital_twin.simulation.strategy import AssignmentResult, NearestAvailableStrategy

ROOT = Path(__file__).resolve().parent.parent

MEMBER2_DATASET_COLUMNS = [
    "timestamp", "scenario_id", "seed", "day_type", "event_type", "event_intensity",
    "minutes_to_event_start", "hour", "minute", "weekday", "lot_id", "capacity",
    "occupied", "occupancy_pct", "arrivals_5m", "departures_5m", "gate_id",
    "gate_arrivals_5m", "queue_length", "avg_wait_sec", "avg_travel_time_sec",
    "road_congestion_ratio_mean", "congestion_level", "lot_status", "gate_status", "source",
]
MEMBER2_LOTS_COLUMNS = [
    "scenario_id", "seed", "timestamp", "sim_time_min", "lot_id", "capacity", "occupied_spaces",
    "occupancy_pct", "arrivals_5m", "departures_5m", "day_type", "event_type", "event_intensity", "source",
]
MEMBER2_GATES_COLUMNS = ["scenario_id", "seed", "tick", "sim_time_min", "gate_id", "queue_length", "source"]

RUN_ARTIFACTS = {"vehicles.parquet", "intervals.parquet", "metrics.json", "manifest.json",
                 "decisions.jsonl", "overflow_events.json"}
PRIMARY_METRIC_KEYS = {"avg_search_time_min", "avg_waiting_time_min", "avg_gate_queue_vehicles",
                       "max_gate_queue_vehicles", "overflow_events_count", "avg_travel_time_min",
                       "avg_travel_distance_m", "lot_peak_occupied_spaces"}
MANIFEST_KEYS = {"scenario_id", "strategy_name", "random_seed", "config_hash", "git_commit",
                 "recorded_at", "vehicle_count", "timestep_count"}
SNAPSHOT_KEYS = {"sim_time", "sim_time_iso", "scenario_id", "seed", "lots", "gates", "roads",
                 "pending_arrivals_by_gate", "active_events", "active_disruptions",
                 "travel_time_matrix", "walk_time", "forecast", "vehicles", "event_log"}
VEHICLE_KEYS = {"vehicle_id", "entry_gate", "destination_id", "arrival_tick", "arrival_time",
                "search_time_seconds", "waiting_time_seconds", "travel_time_seconds",
                "travel_distance_meters", "assigned_lot_id", "final_state", "internal_state",
                "complied", "vehicle_type", "reassigned_count", "state_trace"}


def _small_scenario(**over):
    raw = yaml.safe_load(open(ROOT / "configs/scenarios/vitap/E1_normal_day.yaml"))
    raw.update({"vehicle_count": 80, "duration_minutes": 240, "warmdown_minutes": 30})
    raw.update(over)
    return raw


@pytest.fixture
def run_id():
    api.init()
    api.load_campus("vitap")
    return api.run_simulation(_small_scenario(), "NearestAvailable", 7)


# ---------------- Member 2 ----------------

def test_member2_make_dataset_columns(tmp_path):
    api.init()
    api.load_campus("vitap")
    out = tmp_path / "ml.csv"
    res = api.make_dataset("vitap", [str(ROOT / "configs/scenarios/vitap/E1_normal_day.yaml")], [0], str(out))
    assert res["columns"] == MEMBER2_DATASET_COLUMNS


def test_member2_timestep_csv_columns_match_generator():
    spec = importlib.util.spec_from_file_location("gen_m2", ROOT / "scripts/generate_member2_dataset.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.COLS == MEMBER2_LOTS_COLUMNS
    assert gen.GATE_COLS == MEMBER2_GATES_COLUMNS


# ---------------- Member 4: run artifacts + API ----------------

def test_run_artifacts_and_manifest(tmp_path):
    from digital_twin.config_loader import load_campus_config
    from digital_twin.db import apply_migrations, get_connection
    from digital_twin.simulation.engine import SimulationEngine
    from digital_twin.simulation.scenario import ScenarioLoader

    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(ROOT / "configs/campus/vitap.yaml", conn)
    runs = tmp_path / "runs"
    SimulationEngine(runs_dir=str(runs)).run(ScenarioLoader.from_dict(_small_scenario()), NearestAvailableStrategy(), conn)
    run_dir = next(runs.glob("*/*/seed_*"))
    assert {p.name for p in run_dir.iterdir()} >= RUN_ARTIFACTS
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert PRIMARY_METRIC_KEYS <= set(metrics["primary_metrics"])
    assert "secondary_metrics" in metrics
    assert MANIFEST_KEYS <= set(json.loads((run_dir / "manifest.json").read_text()))
    decisions = [json.loads(line) for line in (run_dir / "decisions.jsonl").read_text().splitlines()]
    assert decisions and set(decisions[0]) == {"tick", "latency_ms"}


def test_api_functions_exist_and_get_metrics_works(run_id):
    for name in ("load_campus", "get_state", "run_simulation", "run_batch", "get_metrics", "get_timeline",
                 "export_geojson", "get_vehicles", "register_strategy"):
        assert callable(getattr(api, name)), name
    m = api.get_metrics(run_id)
    assert "primary_metrics" in m and "secondary_metrics" in m


def test_get_vehicles_is_real_data_not_a_stub(run_id):
    vehicles = api.get_vehicles(run_id)
    assert len(vehicles) == 80
    assert VEHICLE_KEYS <= set(vehicles[0])
    json.dumps(vehicles)   # JSON-serializable for FastAPI


def test_get_timeline_is_real_data_and_respects_capacity(run_id):
    tl = api.get_timeline(run_id)
    assert len(tl) == 240 and [t["tick"] for t in tl[:3]] == [0, 1, 2]
    assert {"occupancy_by_lot", "queue_by_gate", "road_load_by_road", "overflow_by_lot"} <= set(tl[0])
    state = api.get_state(run_id, 0)
    cap = {lot["id"]: lot["capacity"] for lot in state["lots"]}
    for t in tl:
        for lot_id, occ in t["occupancy_by_lot"].items():
            assert 0 <= occ <= cap[lot_id], (t["tick"], lot_id, occ)
    assert max(sum(t["occupancy_by_lot"].values()) for t in tl) > 0


def test_invalid_run_id_is_a_clear_error():
    api.init()
    for fn in (api.get_vehicles, api.get_timeline, api.get_metrics):
        with pytest.raises(KeyError):
            fn("no-such-run")


# ---------------- Member 3: snapshot, fork, pluggable strategy ----------------

def test_state_snapshot_contract_and_internal_consistency(run_id):
    tick = 90
    state = api.get_state(run_id, tick)
    assert SNAPSHOT_KEYS <= set(state)
    json.dumps(state, default=str)
    assert state["sim_time"] == tick and state["scenario_id"] == "vitap-normal-day"
    for lot in state["lots"]:
        assert lot["occupied"] + lot["available"] == lot["capacity"] or lot["occupied"] >= lot["capacity"]
        assert 0 <= lot["occupied"] <= lot["capacity"]
    assert state["travel_time_matrix"] and all(
        isinstance(x, float) for row in state["travel_time_matrix"].values() for x in row.values())
    # Cross-check two independently built views: a lot's occupancy must equal the number of vehicles
    # that currently hold a space there (SEARCHING or PARKED) according to their own state traces.
    holding = {}
    for v in state["vehicles"]:
        if v["state"] in ("SEARCHING", "PARKED") and v["assigned_lot"]:
            holding[v["assigned_lot"]] = holding.get(v["assigned_lot"], 0) + 1
    for lot in state["lots"]:
        assert holding.get(lot["id"], 0) == lot["occupied"], (lot["id"], holding, lot["occupied"])


def test_state_snapshot_fork_is_independent(run_id):
    snap = api._build_snapshot(run_id, 90)
    before = snap.to_dict()
    fork = snap.fork()
    fork.lots[0].occupied += 5
    fork.gates[0].queue_length += 9
    assert snap.to_dict() == before


def test_state_tick_out_of_range_is_rejected(run_id):
    with pytest.raises(ValueError):
        api.get_state(run_id, 10_000)


def test_pluggable_strategy_registration_runs_and_is_called(run_id):
    calls = {"assign": 0, "update_policy": 0}

    class Probe(NearestAvailableStrategy):
        label = "Probe"

        def assign(self, vehicle, state):
            calls["assign"] += 1
            result = super().assign(vehicle, state)
            assert isinstance(result, AssignmentResult)
            return result

        def update_policy(self, state, forecast):
            calls["update_policy"] += 1
            # forecast may be None (prediction unavailable) or a dict (prediction active)

    api.register_strategy("Probe", Probe)
    rid = api.run_simulation(_small_scenario(), "Probe", 3)
    assert calls["assign"] >= 80 and calls["update_policy"] >= 10
    assert api.get_metrics(rid)["secondary_metrics"]["conservation_check"] is True


def test_unknown_strategy_lists_the_available_ones():
    api.init()
    api.load_campus("vitap")
    with pytest.raises(ValueError, match="Available"):
        api.run_simulation(_small_scenario(), "Nope", 0)


# ---------------- spec entry point ----------------

def test_spec_entry_point_python_m_simulation():
    proc = subprocess.run(
        [sys.executable, "-m", "simulation", "run", "--scenario", "S1", "--strategy", "nearest", "--seed", "7"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "Conservation: total=400" in proc.stdout and "[OK]" in proc.stdout
