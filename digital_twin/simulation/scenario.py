"""
Part 6: Scenario Generation -- the configuration layer Part 4's engine
executes. Scenarios are YAML files under configs/scenarios/{campus_id}/.
Every scenario is SYNTHETIC by construction; none is presented as real
campus behavior.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from digital_twin.models import ConfigError


@dataclass
class ScenarioConfig:
    scenario_id: str
    campus_id: str
    name: str
    duration_minutes: int
    vehicle_count: int
    arrival_rate_profile: dict          # {"type": "constant", "rate": n} or {"type": "profile", "points": [{time, rate}, ...]}
    event_conditions: Optional[dict]    # {"event_id": ...} or {"ad_hoc": true, "demand_multiplier": n}
    availability_overrides: dict        # {"closed_gates": [], "closed_parking_lots": [], "closed_roads": []}
    prediction_error_injection_level: float
    random_seed: int
    start_time_min: int = 480           # Wall-clock start (minutes since midnight); 480 = 08:00
    # Ablation flags (Phase 7, E6): control which components are active
    use_prediction: bool = True         # Enable Member 2's occupancy forecasts
    use_optimization: bool = True       # Enable Member 3's optimizer (vs. baseline)
    use_uncertainty: bool = True        # Include uncertainty intervals in decisions
    proactive: bool = True              # Use proactive routing (vs. reactive)
    # Warm-down: no new arrivals in the last N minutes so vehicles can exit before recording ends
    warmdown_minutes: int = 0
    # Simulation tick length in seconds (spec default 10 s). Scenario times stay in minutes; the engine
    # converts. Must divide 60 evenly. Output ticks (vehicle logs, timesteps) are still reported in minutes.
    time_step_sec: int = 10
    # Gate server model: "tick" (default, capacity x dt credit) or "simpy" (optional multi-lane SimPy servers).
    gate_model: str = "tick"
    # Optional vehicle mix with per-type dwell: {type: {share, dwell_median_minutes, dwell_sigma}}.
    # None -> one global lognormal dwell for every vehicle (default behaviour).
    vehicle_types: Optional[dict] = None


class ScenarioLoader:
    @staticmethod
    def load(path) -> ScenarioConfig:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return ScenarioLoader.from_dict(raw)

    @staticmethod
    def from_dict(raw: dict) -> ScenarioConfig:
        if "random_seed" not in raw:
            raise ConfigError(
                f"Scenario '{raw.get('scenario_id', '?')}' is missing random_seed. "
                "No scenario runs without an explicit seed."
            )
        return ScenarioConfig(
            scenario_id=raw["scenario_id"],
            campus_id=raw["campus_id"],
            name=raw["name"],
            duration_minutes=raw["duration_minutes"],
            vehicle_count=raw["vehicle_count"],
            arrival_rate_profile=raw["arrival_rate_profile"],
            event_conditions=raw.get("event_conditions"),
            availability_overrides=raw.get(
                "availability_overrides",
                {"closed_gates": [], "closed_parking_lots": [], "closed_roads": []},
            ),
            prediction_error_injection_level=raw.get("prediction_error_injection_level", 0.0),
            random_seed=raw["random_seed"],
            start_time_min=raw.get("start_time_min", 480),
            use_prediction=raw.get("use_prediction", True),
            use_optimization=raw.get("use_optimization", True),
            use_uncertainty=raw.get("use_uncertainty", True),
            proactive=raw.get("proactive", True),
            warmdown_minutes=raw.get("warmdown_minutes", 0),
            time_step_sec=raw.get("time_step_sec", 10),
            gate_model=raw.get("gate_model", "tick"),
            vehicle_types=raw.get("vehicle_types"),
        )


class ScenarioValidator:
    @staticmethod
    def validate(scenario: ScenarioConfig, conn) -> list:
        errors = []

        campus_row = conn.execute(
            "SELECT campus_id FROM campuses WHERE campus_id=?", (scenario.campus_id,)
        ).fetchone()
        if not campus_row:
            errors.append(f"Scenario references unknown campus_id '{scenario.campus_id}'.")
            return errors  # nothing else can be checked meaningfully

        if scenario.vehicle_count < 0:
            errors.append("vehicle_count must be non-negative.")
        if scenario.gate_model not in ("tick", "simpy"):
            errors.append(f"gate_model must be 'tick' or 'simpy'; got '{scenario.gate_model}'.")
        if scenario.vehicle_types is not None:
            if not isinstance(scenario.vehicle_types, dict) or not scenario.vehicle_types:
                errors.append("vehicle_types must be a non-empty mapping of type -> {share, dwell_median_minutes, dwell_sigma}.")
            else:
                for tname, spec in scenario.vehicle_types.items():
                    if not isinstance(spec, dict) or spec.get("share", 0) <= 0:
                        errors.append(f"vehicle_types['{tname}'].share must be > 0.")
                    elif spec.get("dwell_median_minutes", 0) <= 0:
                        errors.append(f"vehicle_types['{tname}'].dwell_median_minutes must be > 0.")
                    elif spec.get("dwell_sigma", 0.6) <= 0:
                        errors.append(f"vehicle_types['{tname}'].dwell_sigma must be > 0.")
        if not (1 <= scenario.time_step_sec <= 60) or 60 % scenario.time_step_sec != 0:
            errors.append(f"time_step_sec must be between 1 and 60 and divide 60 evenly; got {scenario.time_step_sec}.")

        overrides = scenario.availability_overrides or {}

        def _exists(table, id_column, entity_id):
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE campus_id=? AND {id_column}=?",
                (scenario.campus_id, entity_id),
            ).fetchone()
            return row is not None

        for gate_id in overrides.get("closed_gates", []):
            if not _exists("gates", "gate_id", gate_id):
                errors.append(f"availability_overrides.closed_gates references unknown gate '{gate_id}' for campus '{scenario.campus_id}'.")

        for lot_id in overrides.get("closed_parking_lots", []):
            if not _exists("parking_lots", "parking_lot_id", lot_id):
                errors.append(f"availability_overrides.closed_parking_lots references unknown parking lot '{lot_id}' for campus '{scenario.campus_id}'.")

        for road_id in overrides.get("closed_roads", []):
            if not _exists("roads", "road_id", road_id):
                errors.append(f"availability_overrides.closed_roads references unknown road '{road_id}' for campus '{scenario.campus_id}'.")

        for tc in overrides.get("timed_closures", []):
            etype = tc.get("entity_type")
            eid = tc.get("entity_id")
            if etype == "parking_lot":
                if not _exists("parking_lots", "parking_lot_id", eid):
                    errors.append(f"availability_overrides.timed_closures references unknown parking lot '{eid}' for campus '{scenario.campus_id}'.")
            elif etype == "gate":
                if not _exists("gates", "gate_id", eid):
                    errors.append(f"availability_overrides.timed_closures references unknown gate '{eid}' for campus '{scenario.campus_id}'.")
            elif etype == "road":
                if not _exists("roads", "road_id", eid):
                    errors.append(f"availability_overrides.timed_closures references unknown road '{eid}' for campus '{scenario.campus_id}'.")

        if scenario.event_conditions:
            ec = scenario.event_conditions
            if ec.get("ad_hoc"):
                if "demand_multiplier" not in ec:
                    errors.append("event_conditions.ad_hoc requires an explicit demand_multiplier.")
            else:
                event_id = ec.get("event_id")
                if not event_id or not _exists("events", "event_id", event_id):
                    errors.append(
                        f"event_conditions references unknown event_id '{event_id}' for campus "
                        f"'{scenario.campus_id}' and is not marked ad_hoc."
                    )

        return errors


CAMPUS_SCENARIOS_ROOT = Path(__file__).resolve().parent.parent.parent / "configs" / "scenarios"
