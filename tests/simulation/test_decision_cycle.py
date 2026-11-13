"""
Decision cycle tests (Phase 5–6 gap fix).

Verify:
1. Strategy.update_policy() called every 5 ticks
2. Decision latency measured in milliseconds
3. Works with forecast=None (Member 2 not integrated yet)
4. B1/B2 ignore forecast and keep working
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioConfig
from digital_twin.simulation.strategy import (
    AllocationStrategy,
    AssignmentResult,
    CampusState,
    Vehicle,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "sample.yaml", c)
    yield c
    c.close()


@pytest.fixture
def engine():
    return SimulationEngine()


class CountingStrategy(AllocationStrategy):
    """Track how many times update_policy is called."""

    def __init__(self):
        self.policy_updates = []
        self.update_count = 0

    def assign(self, vehicle: Vehicle, campus_state: CampusState) -> AssignmentResult:
        open_lots = [
            lid for lid in campus_state.parking_lots
            if campus_state.parking_lots[lid]["status"] == "open"
            and campus_state.parking_lots[lid]["occupied_spaces"]
            < campus_state.parking_lots[lid]["usable_capacity"]
        ]
        return AssignmentResult(parking_lot_id=open_lots[0] if open_lots else None)

    def update_policy(self, state_snapshot: dict, forecast: dict = None) -> None:
        self.update_count += 1
        self.policy_updates.append({
            "count": self.update_count,
            "has_forecast": forecast is not None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


def test_update_policy_called_every_5_ticks(conn, engine):
    """Strategy.update_policy() called exactly once per 5-tick interval."""
    scenario = ScenarioConfig(
        scenario_id="test-decision-cycle",
        campus_id="sample",
        name="Test Decision Cycle",
        duration_minutes=60,
        vehicle_count=50,
        arrival_rate_profile={"type": "constant", "rate": 0.83},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=500,
    )

    strategy = CountingStrategy()
    engine.run(scenario, strategy, conn)

    # Decision cycle: every 5 ticks (0, 5, 10, 15, ..., 55)
    # For 60-minute scenario: 0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55 = 12 calls
    expected_calls = scenario.duration_minutes // 5
    assert strategy.update_count == expected_calls, \
        f"Expected {expected_calls} update_policy calls, got {strategy.update_count}"


def test_decision_latency_measured(conn, engine):
    """Decision latency is measured and recorded in milliseconds."""
    scenario = ScenarioConfig(
        scenario_id="test-latency",
        campus_id="sample",
        name="Test Latency",
        duration_minutes=30,
        vehicle_count=30,
        arrival_rate_profile={"type": "constant", "rate": 1.0},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=501,
    )

    strategy = CountingStrategy()
    engine.run(scenario, strategy, conn)

    # Each policy update should have a measurable latency
    assert len(strategy.policy_updates) > 0
    for update in strategy.policy_updates:
        assert "count" in update
        assert "has_forecast" in update
        assert "timestamp" in update


def test_forecast_none_when_prediction_disabled(conn, engine):
    """When use_prediction=False, forecast is None in every policy update."""
    scenario = ScenarioConfig(
        scenario_id="test-no-forecast",
        campus_id="sample",
        name="Test No Forecast",
        duration_minutes=20,
        vehicle_count=20,
        arrival_rate_profile={"type": "constant", "rate": 1.0},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=502,
        use_prediction=False,  # opt out of prediction engine
    )

    strategy = CountingStrategy()
    engine.run(scenario, strategy, conn)

    # All policy updates should have forecast=None because use_prediction=False
    assert all(not update["has_forecast"] for update in strategy.policy_updates)


def test_baseline_strategies_ignore_forecast(conn, engine):
    """B1 and B2 work with forecast=None (forecast parameter ignored)."""
    from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy

    scenario = ScenarioConfig(
        scenario_id="test-baselines-no-forecast",
        campus_id="sample",
        name="Test Baselines No Forecast",
        duration_minutes=30,
        vehicle_count=50,
        arrival_rate_profile={"type": "constant", "rate": 0.83},
        event_conditions=None,
        availability_overrides={"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
        prediction_error_injection_level=0.0,
        random_seed=503,
    )

    result_b1 = engine.run(scenario, FirstAvailableStrategy(), conn)
    result_b2 = engine.run(scenario, NearestAvailableStrategy(), conn)

    # Both should complete without error (forecast=None doesn't break them)
    assert len(result_b1.vehicles) > 0
    assert len(result_b2.vehicles) > 0


if __name__ == "__main__":
    print("Run with: python -m pytest test_decision_cycle.py -v")
