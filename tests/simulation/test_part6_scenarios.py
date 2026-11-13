from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.models import ConfigError
from digital_twin.simulation.scenario import ScenarioLoader, ScenarioValidator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"
SCENARIOS = PROJECT_ROOT / "configs" / "scenarios" / "sample"


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "sample.yaml", c)
    load_campus_config(CONFIGS / "vitap.yaml", c)
    yield c
    c.close()


@pytest.mark.parametrize("filename", [
    "normal_day.yaml", "high_demand_event.yaml", "parking_closure.yaml", "gate_closure.yaml",
])
def test_starter_scenario_validates_successfully(conn, filename):
    scenario = ScenarioLoader.load(SCENARIOS / filename)
    errors = ScenarioValidator.validate(scenario, conn)
    assert errors == []


def test_scenario_referencing_nonexistent_lot_fails_validation(conn):
    raw = yaml.safe_load(open(SCENARIOS / "parking_closure.yaml"))
    raw["availability_overrides"]["closed_parking_lots"] = ["does-not-exist"]
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("unknown parking lot" in e for e in errors)


def test_scenario_missing_random_seed_fails_validation():
    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    del raw["random_seed"]
    with pytest.raises(ConfigError, match="random_seed"):
        ScenarioLoader.from_dict(raw)


def test_scenario_referencing_lot_from_other_campus_fails_validation(conn):
    raw = yaml.safe_load(open(SCENARIOS / "parking_closure.yaml"))
    raw["availability_overrides"]["closed_parking_lots"] = ["vitap-lot-placeholder"]  # exists, but for campus 'vitap'
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("unknown parking lot 'vitap-lot-placeholder'" in e for e in errors)


def test_ad_hoc_event_without_demand_multiplier_fails_validation(conn):
    raw = yaml.safe_load(open(SCENARIOS / "normal_day.yaml"))
    raw["event_conditions"] = {"ad_hoc": True}
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("demand_multiplier" in e for e in errors)


def test_event_conditions_referencing_real_event_id_validates(conn):
    scenario = ScenarioLoader.load(SCENARIOS / "high_demand_event.yaml")
    errors = ScenarioValidator.validate(scenario, conn)
    assert errors == []


def test_vitap_e3_bad_lot_id_caught_by_validator(conn):
    """Regression: E3 originally closed 'vitap-lot-1' (non-existent).
    The validator must reject this — the engine silently ignored it, causing
    E3 and E4 to produce identical results as if no closure applied."""
    raw = {
        "scenario_id": "vitap-lot-closure", "campus_id": "vitap",
        "name": "LOT_CLOSURE", "duration_minutes": 600, "vehicle_count": 400,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 43,
        "availability_overrides": {
            "closed_gates": [], "closed_parking_lots": ["vitap-lot-1"], "closed_roads": []
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("vitap-lot-1" in e for e in errors), (
        f"Validator should reject unknown lot 'vitap-lot-1'. Got errors: {errors}"
    )


def test_vitap_e4_bad_gate_id_caught_by_validator(conn):
    """Regression: E4 originally closed 'vitap-gate-1' (non-existent).
    Validator must reject it."""
    raw = {
        "scenario_id": "vitap-gate-closure", "campus_id": "vitap",
        "name": "GATE_CLOSURE", "duration_minutes": 600, "vehicle_count": 400,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 44,
        "availability_overrides": {
            "closed_gates": ["vitap-gate-1"], "closed_parking_lots": [], "closed_roads": []
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("vitap-gate-1" in e for e in errors), (
        f"Validator should reject unknown gate 'vitap-gate-1'. Got errors: {errors}"
    )


def test_vitap_e3_fixed_lot_id_validates(conn):
    """After fix: closing vitap-lot-academic-main (real ID) must pass validation."""
    raw = {
        "scenario_id": "vitap-lot-closure", "campus_id": "vitap",
        "name": "LOT_CLOSURE", "duration_minutes": 600, "vehicle_count": 400,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 43,
        "availability_overrides": {
            "closed_gates": [], "closed_parking_lots": ["vitap-lot-academic-main"], "closed_roads": []
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert errors == [], f"Fixed lot ID should validate cleanly. Got: {errors}"


def test_vitap_e4_fixed_gate_id_validates(conn):
    """After fix: closing vitap-gate-main (real ID) must pass validation."""
    raw = {
        "scenario_id": "vitap-gate-closure", "campus_id": "vitap",
        "name": "GATE_CLOSURE", "duration_minutes": 600, "vehicle_count": 400,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 44,
        "availability_overrides": {
            "closed_gates": ["vitap-gate-main"], "closed_parking_lots": [], "closed_roads": []
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert errors == [], f"Fixed gate ID should validate cleanly. Got: {errors}"


def test_timed_closure_bad_lot_id_caught(conn):
    """timed_closures referencing a non-existent lot must be rejected by validator."""
    raw = {
        "scenario_id": "vitap-lot-closure", "campus_id": "vitap",
        "name": "LOT_CLOSURE", "duration_minutes": 600, "vehicle_count": 400,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 43,
        "availability_overrides": {
            "closed_gates": [], "closed_parking_lots": [], "closed_roads": [],
            "timed_closures": [{"entity_type": "parking_lot", "entity_id": "vitap-lot-1", "start_tick": 60, "end_tick": 180}],
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("vitap-lot-1" in e for e in errors), f"Expected error for unknown lot. Got: {errors}"


def test_timed_closure_bad_gate_id_caught(conn):
    """timed_closures referencing a non-existent gate must be rejected by validator."""
    raw = {
        "scenario_id": "vitap-gate-closure", "campus_id": "vitap",
        "name": "GATE_CLOSURE", "duration_minutes": 600, "vehicle_count": 400,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 44,
        "availability_overrides": {
            "closed_gates": [], "closed_parking_lots": [], "closed_roads": [],
            "timed_closures": [{"entity_type": "gate", "entity_id": "vitap-gate-1", "start_tick": 45, "end_tick": 105}],
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    errors = ScenarioValidator.validate(scenario, conn)
    assert any("vitap-gate-1" in e for e in errors), f"Expected error for unknown gate. Got: {errors}"


def test_bad_entity_id_raises_error_in_engine(conn):
    """Engine must raise ValueError (not just return an error list) when a bad entity ID is in overrides."""
    from digital_twin.simulation.engine import SimulationEngine
    from digital_twin.simulation.strategy import FirstAvailableStrategy
    raw = {
        "scenario_id": "vitap-lot-closure", "campus_id": "vitap",
        "name": "LOT_CLOSURE", "duration_minutes": 10, "vehicle_count": 5,
        "arrival_rate_profile": {"type": "constant", "rate": 0.5},
        "event_conditions": None, "random_seed": 99,
        "availability_overrides": {
            "closed_gates": [], "closed_parking_lots": ["vitap-lot-does-not-exist"], "closed_roads": [],
        },
    }
    scenario = ScenarioLoader.from_dict(raw)
    eng = SimulationEngine()
    with pytest.raises(ValueError, match="validation failed"):
        eng.run(scenario, FirstAvailableStrategy(), conn)


if __name__ == "__main__":
    print("Run with pytest: python -m pytest test_part6_scenarios.py -v")
