"""Road closing mid-run: unreachable lots -> rejection with overflow log, no crash, recovery after reopening."""

from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import NearestAvailableStrategy

MAIN_GATE_ROADS = [
    "vitap-road-main-gate-to-academic-lot",
    "vitap-road-main-gate-to-hostel-lot",
    "vitap-road-main-gate-to-admin-lot",
    "vitap-road-main-gate-to-sports-lot",
    "vitap-road-main-gate-to-overflow",
]
START, END = 120, 180


@pytest.fixture
def result():
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(Path("configs/campus/vitap.yaml"), conn)
    raw = yaml.safe_load(open("configs/scenarios/vitap/E1_normal_day.yaml"))
    raw["random_seed"] = 7
    raw["availability_overrides"] = {
        "closed_gates": [], "closed_parking_lots": [], "closed_roads": [],
        "timed_closures": [
            {"entity_type": "road", "entity_id": r, "start_tick": START, "end_tick": END}
            for r in MAIN_GATE_ROADS
        ],
    }
    return SimulationEngine().run(ScenarioLoader.from_dict(raw), NearestAvailableStrategy(), conn)


def test_closure_window_rejects_only_unreachable_arrivals(result):
    rejected = [v for v in result.vehicles if v["final_state"] == "rejected"]
    assert rejected, "main-gate vehicles routed during the closure should be rejected"
    for v in rejected:
        assert v["entry_gate"] == "vitap-gate-main"
        assert START <= v["gate_admitted_tick"] < END or START <= (v["search_start_tick"] or START) < END


def test_overflow_events_equal_rejections_and_reason_logged(result):
    rejected = sum(1 for v in result.vehicles if v["final_state"] == "rejected")
    assert len(result.overflow_events) == rejected
    assert all(e["reason"].startswith(("infeasible", "unreachable", "no_feasible")) for e in result.overflow_events)


def test_recovers_after_reopen_and_conserves(result):
    after = [v for v in result.vehicles if v["arrival_tick"] >= END + 30]
    assert after and all(v["final_state"] != "rejected" for v in after)
    sec = result.secondary_metrics
    assert sec["conservation_check"] is True
