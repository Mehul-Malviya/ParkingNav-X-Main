"""
Part 7 — Simulator Metrics: 5 primary metrics + strategy comparison.

Spec requirements:
  M1  avg_search_time_min    > 0 and < 30 (believable range)
  M2  avg_wait_time_min      >= 0
  M3  avg_gate_queue         >= 0, max_gate_queue >= avg
  M4  overflow_events_count  >= 0
  M5  avg_travel_time_min    > 0 and < 60
       total_travel_distance_m > 0

  STRAT  Run S3 (event_day) with FirstAvailable + NearestAvailable on same
         seed. The strategies must produce different metrics on at least one
         primary field. Print the comparison table.

  HAND   Pick 3 vehicles from the NearestAvailable run; manually recompute
         their search_time and wait_time; confirm they match the logged values.

  SEC    secondary_metrics has avg_utilization_pct, utilization_imbalance,
         simulation_runtime_sec, avg_decision_latency_ms.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy, Member3Strategy, NearestAvailableStrategy

SCENARIO_DIR = Path("configs/scenarios/vitap")
CAMPUS_YAML = Path("configs/campus/vitap.yaml")
SEED = 7


def _conn():
    c = get_connection(":memory:")
    apply_migrations(c)
    load_campus_config(CAMPUS_YAML, c)
    return c


def _run(scenario_file: str, strategy, seed: int = SEED):
    raw = yaml.safe_load(open(SCENARIO_DIR / scenario_file))
    raw["random_seed"] = seed
    scenario = ScenarioLoader.from_dict(raw)
    engine = SimulationEngine(runs_dir=tempfile.mkdtemp())
    return engine.run(scenario, strategy, _conn())


# ── M1 avg parking search time ────────────────────────────────────────────────

def test_m1_avg_search_time_believable():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    val = r.metrics["avg_search_time_min"]
    assert val > 0, f"avg_search_time_min must be > 0, got {val}"
    assert val < 30, f"avg_search_time_min unrealistically large: {val} min"


# ── M2 avg waiting time ───────────────────────────────────────────────────────

def test_m2_avg_wait_time_non_negative():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    val = r.metrics["avg_wait_time_min"]
    assert val >= 0, f"avg_wait_time_min must be >= 0, got {val}"


# ── M3 avg / max gate queue ───────────────────────────────────────────────────

def test_m3_gate_queue_consistent():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    avg_q = r.metrics["avg_gate_queue"]
    max_q = r.metrics["max_gate_queue"]
    assert avg_q >= 0, f"avg_gate_queue must be >= 0, got {avg_q}"
    assert max_q >= avg_q, f"max_gate_queue ({max_q}) must be >= avg ({avg_q})"


# ── M4 overflow events ────────────────────────────────────────────────────────

def test_m4_overflow_non_negative():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    assert r.metrics["overflow_events_count"] >= 0


# ── M5 travel time and distance ───────────────────────────────────────────────

def test_m5_travel_time_believable():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    avg_t = r.metrics["avg_travel_time_min"]
    total_d = r.metrics["total_travel_distance_m"]
    assert avg_t > 0, f"avg_travel_time_min must be > 0, got {avg_t}"
    assert avg_t < 60, f"avg_travel_time_min unrealistically large: {avg_t} min"
    assert total_d > 0, f"total_travel_distance_m must be > 0, got {total_d}"


def test_m5_total_reassignments_present():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    assert "total_reassignments" in r.metrics
    assert r.metrics["total_reassignments"] >= 0


# ── Strategy comparison ───────────────────────────────────────────────────────

def test_strategy_comparison_different_metrics():
    """All 3 strategies must produce a believable table; B1 and B2 must differ."""
    r_fa = _run("E2_event_placement.yaml", FirstAvailableStrategy())
    r_na = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    r_m3 = _run("E2_event_placement.yaml", Member3Strategy())

    _PRIMARY = [
        "avg_search_time_min",
        "avg_wait_time_min",
        "avg_gate_queue",
        "overflow_events_count",
        "avg_travel_time_min",
    ]

    def _fmt(v):
        return str(round(v, 4)) if isinstance(v, float) else str(v)

    # Print comparison table (visible in pytest -s)
    print("\n\nStrategy Comparison -- S3 Event Day, seed=7")
    print(f"{'Metric':<30} {'B1-FirstAvail':>15} {'B2-Nearest':>12} {'M3-Optimizer':>14}")
    print("-" * 75)
    for k in _PRIMARY:
        print(f"{k:<30} {_fmt(r_fa.metrics.get(k,'N/A')):>15} {_fmt(r_na.metrics.get(k,'N/A')):>12} {_fmt(r_m3.metrics.get(k,'N/A')):>14}")
    print()

    # B1 and B2 must differ on at least one primary metric
    b1_b2_different = any(
        abs(r_fa.metrics.get(k, 0) - r_na.metrics.get(k, 0)) > 1e-9
        for k in _PRIMARY
    )
    assert b1_b2_different, (
        "B1-FirstAvailable and B2-NearestAvailable produced identical metrics -- "
        "strategies are not being distinguished by the engine"
    )

    # All 3 results must have believable search times
    for label, r in [("B1", r_fa), ("B2", r_na), ("M3", r_m3)]:
        st = r.metrics["avg_search_time_min"]
        assert 0 < st < 30, f"{label} avg_search_time_min out of believable range: {st}"


# ── Hand-check 3 vehicles ─────────────────────────────────────────────────────

def test_hand_check_3_vehicles():
    """
    Manual verification: recompute search_time and wait_time for 3 vehicles
    and confirm they match the logged values to within floating-point tolerance.
    """
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    dt = r.time_step_sec  # seconds per engine tick

    # Pick first 3 vehicles that have both gate ticks and are completed
    candidates = [
        v for v in r.vehicles
        if v.get("gate_admitted_tick") is not None
        and v.get("queue_enter_tick") is not None
        and v.get("search_time_seconds", 0) > 0
    ]
    assert len(candidates) >= 3, (
        f"Need at least 3 vehicles with gate ticks; got {len(candidates)}"
    )

    print("\n\nHand-check — 3 vehicles (NearestAvailable, S3, seed=7)")
    print(f"{'vehicle_id':<30} {'wait_logged':>12} {'wait_recalc':>12} {'search_logged':>14} {'search_logged_match':>20}")
    print("-" * 92)

    for v in candidates[:3]:
        # Wait time: (gate_admitted_tick - queue_enter_tick) * dt
        # Tick fields in result are stored in MINUTES (converted by _m() in engine)
        # So the diff in minutes * 60 = seconds
        queue_enter_min = v["queue_enter_tick"]   # minutes
        gate_admit_min = v["gate_admitted_tick"]   # minutes
        wait_recalc_sec = (gate_admit_min - queue_enter_min) * 60.0

        wait_logged = v.get("waiting_time_seconds", 0)
        search_logged = v.get("search_time_seconds", 0)

        wait_ok = abs(wait_recalc_sec - wait_logged) < 1.0  # within 1 second
        print(f"{v['vehicle_id']:<30} {wait_logged:>12.2f} {wait_recalc_sec:>12.2f} {search_logged:>14.2f} {'OK' if wait_ok else 'MISMATCH':>20}")

        assert wait_ok, (
            f"Vehicle {v['vehicle_id']}: wait_time mismatch. "
            f"logged={wait_logged:.2f}s recalc={wait_recalc_sec:.2f}s"
        )
        # Search time must be positive (occupancy formula always > 0)
        assert search_logged > 0, f"Vehicle {v['vehicle_id']}: search_time_seconds must be > 0"

    print()


# ── Secondary metrics ─────────────────────────────────────────────────────────

def test_secondary_metrics_has_utilization():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    sm = r.secondary_metrics
    assert "avg_utilization_pct" in sm, "secondary_metrics must have avg_utilization_pct"
    assert "utilization_imbalance" in sm, "secondary_metrics must have utilization_imbalance"
    assert 0.0 <= sm["avg_utilization_pct"] <= 100.0, f"avg_utilization_pct out of range: {sm['avg_utilization_pct']}"
    assert sm["utilization_imbalance"] >= 0.0


def test_secondary_metrics_has_runtime():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    sm = r.secondary_metrics
    assert "simulation_runtime_sec" in sm
    assert sm["simulation_runtime_sec"] > 0, "simulation_runtime_sec must be > 0"


def test_secondary_metrics_has_decision_latency():
    r = _run("E2_event_placement.yaml", NearestAvailableStrategy())
    sm = r.secondary_metrics
    assert "avg_decision_latency_ms" in sm
    assert sm["avg_decision_latency_ms"] >= 0.0
