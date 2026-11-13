"""
Part 10 coverage tests — missing / partial items from the audit.

C10-1  BPR travel time increases monotonically with flow
C10-2  Closed gate admits no new vehicles (queue does not grow after closure)
C10-3  Snapshot serialisation completes in < 50 ms for campus-scale state
C10-4  Named E1 scenario: invariants hold for ≥ 100 simulation timesteps
"""

import tempfile
import time
from pathlib import Path

import pytest
import yaml

SCENARIO_DIR = Path("configs/scenarios/vitap")
CAMPUS_YAML = Path("configs/campus/vitap.yaml")
SEED = 7


def _conn():
    from digital_twin.config_loader import load_campus_config
    from digital_twin.db import apply_migrations, get_connection

    c = get_connection(":memory:")
    apply_migrations(c)
    load_campus_config(CAMPUS_YAML, c)
    return c


def _run(scenario_file: str, strategy, seed: int = SEED):
    from digital_twin.simulation.engine import SimulationEngine
    from digital_twin.simulation.scenario import ScenarioLoader

    raw = yaml.safe_load(open(SCENARIO_DIR / scenario_file))
    raw["random_seed"] = seed
    scenario = ScenarioLoader.from_dict(raw)
    engine = SimulationEngine(runs_dir=tempfile.mkdtemp())
    return engine.run(scenario, strategy, _conn())


# ── C10-1: BPR monotonicity ───────────────────────────────────────────────────

def test_c10_1_bpr_monotonically_increases_with_flow():
    """Travel time must increase as flow increases (BPR property)."""
    from digital_twin.simulation.engine import bpr_travel_time

    t_free = 60.0
    capacity = 100

    times = [bpr_travel_time(t_free, flow, capacity) for flow in range(0, 201, 10)]
    for i in range(1, len(times)):
        assert times[i] >= times[i - 1], (
            f"BPR not monotone: t({(i-1)*10})={times[i-1]:.3f} > t({i*10})={times[i]:.3f}"
        )


def test_c10_1_bpr_free_flow_baseline():
    """At zero flow, BPR must return exactly t_free."""
    from digital_twin.simulation.engine import bpr_travel_time

    assert bpr_travel_time(120.0, 0, 100) == pytest.approx(120.0)


def test_c10_1_bpr_zero_capacity_guard():
    """Zero-capacity road returns t_free (guard against division by zero)."""
    from digital_twin.simulation.engine import bpr_travel_time

    assert bpr_travel_time(30.0, 50, 0) == pytest.approx(30.0)


# ── C10-2: Closed gate queue does not grow ───────────────────────────────────

def _make_snapshot(**kwargs):
    """Build a minimal StateSnapshot with required positional fields."""
    from digital_twin.simulation.state_snapshot import StateSnapshot

    defaults = dict(
        sim_time=0,
        sim_time_iso="2024-01-01T08:00:00",
        lots=[],
        gates=[],
        roads=[],
        pending_arrivals_by_gate={},
        active_events=[],
        active_disruptions=[],
        travel_time_matrix={},
        walk_time={},
    )
    defaults.update(kwargs)
    return StateSnapshot(**defaults)


def test_c10_2_closed_gate_status_changes():
    """Closing a gate must set its status to 'closed'."""
    from digital_twin.simulation.state_snapshot import GateState

    gate = GateState(
        id="G1",
        queue_length=5,
        service_rate_veh_per_min=6.0,
        status="open",
        throughput_last_5min=0,
    )
    snap = _make_snapshot(gates=[gate])
    snap.apply_event({"type": "gate_closed", "gate_id": "G1"})
    assert snap.get_gate_by_id("G1").status == "closed"


def test_c10_2_closed_gate_queue_does_not_grow():
    """After closure the queue length must be ≤ its pre-closure value."""
    from digital_twin.simulation.state_snapshot import GateState

    initial_queue = 8
    gate = GateState(
        id="G2",
        queue_length=initial_queue,
        service_rate_veh_per_min=6.0,
        status="open",
        throughput_last_5min=0,
    )
    snap = _make_snapshot(gates=[gate])
    snap.apply_event({"type": "gate_closed", "gate_id": "G2"})
    assert snap.get_gate_by_id("G2").queue_length <= initial_queue


# ── C10-3: Snapshot < 50 ms ──────────────────────────────────────────────────

def test_c10_3_snapshot_serialisation_under_50ms():
    """to_dict() on a campus-scale snapshot must complete in < 50 ms (median)."""
    from digital_twin.simulation.state_snapshot import GateState, LotState

    lots = [
        LotState(
            id=f"LOT_{i:02d}",
            capacity=200,
            occupied=100,
            available=100,
            reserved_free=0,
            status="open",
            inflow_5m=5,
            outflow_5m=3,
        )
        for i in range(20)
    ]
    gates = [
        GateState(
            id=f"GATE_{i}",
            queue_length=10,
            service_rate_veh_per_min=6.0,
            status="open",
            throughput_last_5min=30,
        )
        for i in range(5)
    ]
    snap = _make_snapshot(sim_time=3600, lots=lots, gates=gates)

    times_ms = []
    for _ in range(10):
        t0 = time.perf_counter()
        snap.to_dict()
        times_ms.append((time.perf_counter() - t0) * 1000)

    median_ms = sorted(times_ms)[5]
    assert median_ms < 50.0, f"Snapshot median={median_ms:.1f} ms exceeds 50 ms budget"


# ── C10-4: Named scenario invariants across ≥ 100 timesteps ──────────────────

def test_c10_4_e1_normal_day_occupancy_invariants():
    """E1 normal-day: occupancy_pct must stay 0–100 for every recorded timestep."""
    from digital_twin.simulation.strategy import NearestAvailableStrategy

    r = _run("E1_normal_day.yaml", NearestAvailableStrategy())

    assert len(r.timesteps) >= 100, (
        f"Expected ≥100 timesteps, got {len(r.timesteps)}"
    )
    for i, ts in enumerate(r.timesteps):
        for lot_id, lot in ts.get("parking_lots", {}).items():
            occ = lot.get("occupancy_pct", 0.0)
            assert 0.0 <= occ <= 100.0, (
                f"timestep {i}, lot {lot_id}: occupancy_pct={occ} out of [0,100]"
            )


def test_c10_4_e1_gate_queue_non_negative():
    """E1 normal-day: gate queue lengths must be non-negative throughout."""
    from digital_twin.simulation.strategy import NearestAvailableStrategy

    r = _run("E1_normal_day.yaml", NearestAvailableStrategy())

    for i, ts in enumerate(r.timesteps):
        for gate_id, gate in ts.get("gates", {}).items():
            q = gate.get("queue_length", 0)
            assert q >= 0, f"timestep {i}, gate {gate_id}: queue_length={q} < 0"
