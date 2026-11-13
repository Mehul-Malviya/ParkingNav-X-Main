"""Event-level dwell override: only vehicles arriving inside the event window get the new lognormal."""

import math
import random

import yaml

from digital_twin.simulation.engine import DWELL_LOGNORMAL_MU, DWELL_LOGNORMAL_SIGMA, SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader


def _arrivals(event_overrides):
    raw = yaml.safe_load(open("configs/scenarios/vitap/E2_event_placement.yaml"))
    raw["event_conditions"].update(event_overrides)
    sc = ScenarioLoader.from_dict(raw)
    vs = SimulationEngine._generate_arrivals(sc, random.Random(1), ["vitap-gate-main"], ["d1"])
    return sc, vs


def test_default_dwell_unchanged_without_override():
    _, vs = _arrivals({})
    assert all(v.dwell_mu == DWELL_LOGNORMAL_MU and v.dwell_sigma == DWELL_LOGNORMAL_SIGMA for v in vs)


def test_event_window_vehicles_get_override():
    sc, vs = _arrivals({"dwell_median_minutes": 300, "dwell_sigma": 0.3})
    start = sc.event_conditions["start_tick"]
    end = start + sc.event_conditions["duration_ticks"]
    inside = [v for v in vs if start <= v.vehicle.arrival_tick < end]
    outside = [v for v in vs if not start <= v.vehicle.arrival_tick < end]
    assert inside and outside
    assert all(abs(v.dwell_mu - math.log(300)) < 1e-9 and v.dwell_sigma == 0.3 for v in inside)
    assert all(v.dwell_mu == DWELL_LOGNORMAL_MU for v in outside)
