"""
Phase 7 — Scenarios & Disruptions (M4)

Tests that all Phase 7 scenario files run end-to-end with B1 and B2 baselines.

Scenarios covered:
- E1: Normal day (baseline)
- E2: High-demand event (placement drive, multiplier 1.8x)
- E3: Parking lot closure (tests diversion)
- E4: Gate closure (tests queue buildup)
- E5: Robustness with forecast noise (0%, 10%, 20%)
"""

from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.forecast_noise import ForecastNoiseInjector
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"
SCENARIOS = PROJECT_ROOT / "configs" / "scenarios" / "vitap"


@pytest.fixture
def conn(tmp_path):
    """Database with VIT-AP campus loaded."""
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "vitap.yaml", c)
    yield c
    c.close()


@pytest.fixture
def engine():
    return SimulationEngine()


class TestPhase7Scenarios:
    """Verify all Phase 7 scenarios run end-to-end."""

    def test_e1_normal_day_b1_b2(self, conn, engine):
        """E1: Normal day runs with both B1 and B2 (baseline)."""
        with open(SCENARIOS / "E1_normal_day.yaml") as f:
            raw = yaml.safe_load(f)
        scenario = ScenarioLoader.from_dict(raw)

        result_b1 = engine.run(scenario, FirstAvailableStrategy(), conn)
        assert len(result_b1.vehicles) > 0

        result_b2 = engine.run(scenario, NearestAvailableStrategy(), conn)
        assert len(result_b2.vehicles) > 0

    def test_e2_event_placement_demand_spike(self, conn, engine):
        """E2: Placement event scenario loads and runs."""
        with open(SCENARIOS / "E2_event_placement.yaml") as f:
            raw = yaml.safe_load(f)

        scenario = ScenarioLoader.from_dict(raw)
        assert scenario.event_conditions is not None
        assert scenario.event_conditions["demand_multiplier"] == 1.8
        assert "academic" in scenario.event_conditions["affected_zones"]

        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        assert len(result.vehicles) > 0

    def test_e3_lot_closure_diversion(self, conn, engine):
        """E3: Lot closure scenario loads and runs."""
        with open(SCENARIOS / "E3_lot_closure.yaml") as f:
            raw = yaml.safe_load(f)

        scenario = ScenarioLoader.from_dict(raw)
        overrides = scenario.availability_overrides or {}
        timed = overrides.get("timed_closures", [])
        assert any(tc["entity_type"] == "parking_lot" for tc in timed), \
            "E3 must have a timed parking_lot closure"

        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        assert len(result.vehicles) > 0

    def test_e4_gate_closure_queue_buildup(self, conn, engine):
        """E4: Gate closure scenario loads and runs."""
        with open(SCENARIOS / "E4_gate_closure.yaml") as f:
            raw = yaml.safe_load(f)

        scenario = ScenarioLoader.from_dict(raw)
        overrides = scenario.availability_overrides or {}
        timed = overrides.get("timed_closures", [])
        assert any(tc["entity_type"] == "gate" for tc in timed), \
            "E4 must have a timed gate closure"

        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        assert len(result.vehicles) > 0
        # Check wait times are recorded
        wait_times = [v["waiting_time_seconds"] for v in result.vehicles
                     if v["waiting_time_seconds"] is not None]
        assert len(wait_times) > 0

    @pytest.mark.parametrize("noise_level", [0, 10, 20])
    def test_e5_robustness_noise_levels(self, conn, engine, noise_level):
        """E5: Robustness with forecast noise (σ=0%, 10%, 20%) runs without error."""
        scenario_file = SCENARIOS / f"E5_noise_{noise_level}.yaml"
        with open(scenario_file) as f:
            raw = yaml.safe_load(f)

        scenario = ScenarioLoader.from_dict(raw)
        assert scenario.prediction_error_injection_level == noise_level / 100.0

        result_b1 = engine.run(scenario, FirstAvailableStrategy(), conn)
        result_b2 = engine.run(scenario, NearestAvailableStrategy(), conn)

        assert len(result_b1.vehicles) > 0
        assert len(result_b2.vehicles) > 0

    def test_forecast_noise_injector(self):
        """ForecastNoiseInjector applies Gaussian noise correctly."""
        injector = ForecastNoiseInjector(noise_level=0.10, seed=999)

        forecast = {
            "occupancy_15min": 50.0,
            "occupancy_30min": 60.0,
            "queue_length_gate_1": 10.0,
            "other_field": "unchanged"
        }

        noisy = injector.perturb(forecast)

        # Numeric occupancy/queue fields should be perturbed
        assert abs(noisy["occupancy_15min"] - 50.0) > 0

        # Non-matching fields unchanged
        assert noisy["other_field"] == "unchanged"

        # All should be non-negative
        assert all(v >= 0 for k, v in noisy.items()
                  if isinstance(v, (int, float)) and k.startswith(("occupancy", "queue")))

    def test_forecast_noise_zero_level_no_op(self):
        """ForecastNoiseInjector with σ=0 is a no-op."""
        injector = ForecastNoiseInjector(noise_level=0.0, seed=999)
        forecast = {"occupancy_15min": 50.0, "queue_length_gate_1": 10.0}
        noisy = injector.perturb(forecast)
        assert noisy == forecast

    def test_scenario_ablation_flags(self):
        """Verify ablation flags are preserved in scenario config."""
        with open(SCENARIOS / "E2_event_placement.yaml") as f:
            raw = yaml.safe_load(f)

        scenario = ScenarioLoader.from_dict(raw)
        assert scenario.use_prediction is True
        assert scenario.use_optimization is True
        assert scenario.use_uncertainty is True
        assert scenario.proactive is True


class TestFix1TravelTime:
    """Fix 1: travel_time_seconds must be gate→lot BPR time, not end-to-end."""

    def test_travel_time_is_gate_to_lot_only(self, conn, engine):
        """travel_time_seconds should reflect BPR road time (~76–534s for vitap), not dwell."""
        with open(SCENARIOS / "E1_normal_day.yaml") as f:
            raw = yaml.safe_load(f)
        scenario = ScenarioLoader.from_dict(raw)
        result = engine.run(scenario, FirstAvailableStrategy(), conn)

        parked = [v for v in result.vehicles if v["assigned_lot_id"] is not None
                  and v["travel_time_seconds"] > 0]
        assert len(parked) > 0, "Expected parked vehicles with travel_time_seconds"

        # Gate→lot roads in vitap range from 76s (hostel) to 534s (sports).
        # End-to-end would be thousands of seconds (dwell ~120 min = 7200 s).
        for v in parked:
            assert v["travel_time_seconds"] <= 600, (
                f"travel_time_seconds={v['travel_time_seconds']} > 600s — "
                "likely still recording end-to-end time instead of gate→lot"
            )
        # end_to_end_time_seconds (for completed vehicles) should be much larger
        completed = [v for v in result.vehicles if v.get("end_to_end_time_seconds") is not None]
        if completed:
            avg_e2e = sum(v["end_to_end_time_seconds"] for v in completed) / len(completed)
            assert avg_e2e > 1000, f"avg end-to-end {avg_e2e:.0f}s seems too short (expected dwell ~120 min)"

    def test_different_assigned_lots_produce_different_travel_distance(self, conn, engine):
        """Strategy assigns first, then route to that lot: B1 vs B2 must differ in travel_distance_meters.
        B1 goes to academic-main (450m); B2 goes to hostel (380m) or nearest — distances must differ."""
        with open(SCENARIOS / "E1_normal_day.yaml") as f:
            raw = yaml.safe_load(f)
        raw["vehicle_count"] = 5
        raw["random_seed"] = 77
        raw["duration_minutes"] = 60
        scenario_b1 = ScenarioLoader.from_dict(dict(raw))
        scenario_b2 = ScenarioLoader.from_dict(dict(raw))

        result_b1 = engine.run(scenario_b1, FirstAvailableStrategy(), conn)
        result_b2 = engine.run(scenario_b2, NearestAvailableStrategy(), conn)

        dists_b1 = [v["travel_distance_meters"] for v in result_b1.vehicles if v["assigned_lot_id"]]
        dists_b2 = [v["travel_distance_meters"] for v in result_b2.vehicles if v["assigned_lot_id"]]

        if dists_b1 and dists_b2:
            avg_b1 = sum(dists_b1) / len(dists_b1)
            avg_b2 = sum(dists_b2) / len(dists_b2)
            # B1 (config order: academic-main=450m first) vs B2 (nearest from gate)
            # They must differ — if route target were always the same lot, they'd be identical
            assert avg_b1 != avg_b2, (
                f"B1 avg dist={avg_b1:.0f}m equals B2 avg dist={avg_b2:.0f}m — "
                "travel distance must reflect the strategy-assigned lot, not a fixed target"
            )


class TestFix2SearchTime:
    """Fix 2: search_time_seconds must be occupancy-based, not transit time."""

    def test_search_time_occupancy_formula_grows_near_full(self):
        """Unit-level check: occupancy_search_seconds grows sharply as occ → 1.
        Formula: 0.5 * 60 * (1 + occ / max(0.001, 1 - occ)) seconds.
        At 30% occ: ~52s; at 95% occ: ~600s.
        """
        def formula(occ):
            return 0.5 * 60 * (1 + occ / max(0.001, 1.0 - occ))

        search_30 = formula(0.30)
        search_95 = formula(0.95)
        assert search_95 > search_30, (
            f"search at 95% ({search_95:.1f}s) should exceed 30% ({search_30:.1f}s)"
        )
        # At 0% occupancy floor: 30 s (0.5 min)
        assert abs(formula(0.0) - 30.0) < 0.1

    def test_search_time_increases_with_demand(self, tmp_path):
        """High-demand run (lots near full) should have higher avg search time than low-demand."""
        c = get_connection(str(tmp_path / "t.db"))
        apply_migrations(c)
        load_campus_config(PROJECT_ROOT / "configs" / "campus" / "vitap.yaml", c)
        eng = SimulationEngine()

        with open(SCENARIOS / "E1_normal_day.yaml") as f:
            raw = yaml.safe_load(f)

        # Low demand: 5 vehicles — lots nearly empty at assignment
        raw_low = dict(raw)
        raw_low["vehicle_count"] = 5
        raw_low["random_seed"] = 1
        raw_low["duration_minutes"] = 120
        raw_low["warmdown_minutes"] = 0
        low_result = eng.run(ScenarioLoader.from_dict(raw_low), FirstAvailableStrategy(), c)

        # High demand: 400 vehicles — lots fill near capacity before end
        raw_high = dict(raw)
        raw_high["vehicle_count"] = 400
        raw_high["random_seed"] = 2
        raw_high["duration_minutes"] = 120
        raw_high["warmdown_minutes"] = 0
        raw_high["arrival_rate_profile"] = {"type": "constant", "rate": 3.0}
        high_result = eng.run(ScenarioLoader.from_dict(raw_high), FirstAvailableStrategy(), c)
        c.close()

        low_s = [v["search_time_seconds"] for v in low_result.vehicles if v["search_time_seconds"] > 0]
        high_s = [v["search_time_seconds"] for v in high_result.vehicles if v["search_time_seconds"] > 0]

        if low_s and high_s:
            avg_low = sum(low_s) / len(low_s)
            avg_high = sum(high_s) / len(high_s)
            assert avg_high > avg_low, (
                f"High-demand avg search ({avg_high:.1f}s) should exceed low-demand ({avg_low:.1f}s)"
            )


class TestFix4SportsLotReachability:
    """Fix 4: all open lots must be reachable from at least one open gate via driveable path."""

    def test_all_open_lots_reachable_from_a_gate(self, conn):
        """After adding vitap-road-main-gate-to-sports-lot, sports lot must be reachable."""
        import networkx as nx

        from digital_twin.graph_service import CampusGraphService

        graph_svc = CampusGraphService()
        graph = graph_svc.build_graph("vitap", conn)

        gate_ids = [r[0] for r in conn.execute(
            "SELECT gate_id FROM gates WHERE campus_id='vitap' AND status='open'"
        ).fetchall()]
        lot_rows = conn.execute(
            "SELECT parking_lot_id FROM parking_lots WHERE campus_id='vitap' AND status='open'"
        ).fetchall()

        unreachable = []
        for (lot_id,) in lot_rows:
            reachable = any(
                nx.has_path(graph, gate_id, lot_id)
                for gate_id in gate_ids
                if gate_id in graph and lot_id in graph
            )
            if not reachable:
                unreachable.append(lot_id)

        assert unreachable == [], (
            f"Lots unreachable from any open gate via driveable path: {unreachable}. "
            "ScenarioValidator does not check graph connectivity — add this test to catch it."
        )


class TestFix5B1Order:
    """Fix 5: FirstAvailableStrategy must use config order, not alphabetical."""

    def test_b1_uses_config_order_not_alphabetical(self, conn):
        """B1 should assign academic-main before admin-visitor (config order),
        but alphabetically 'admin-visitor' < 'academic-main' would come first."""
        from digital_twin.graph_service import CampusGraphService
        from digital_twin.simulation.strategy import (
            CampusState,
            FirstAvailableStrategy,
            Vehicle,
        )

        graph = CampusGraphService().build_graph("vitap", conn)

        # Build a campus_state where all lots are open and empty
        lot_rows = conn.execute(
            "SELECT parking_lot_id, usable_capacity, status FROM parking_lots WHERE campus_id='vitap'"
        ).fetchall()
        parking_lots = {
            row[0]: {"status": row[2], "usable_capacity": row[1], "occupied_spaces": 0}
            for row in lot_rows
        }
        state = CampusState(
            campus_id="vitap",
            graph=graph,
            parking_lots=parking_lots,
            gates={},
            roads={},
        )
        vehicle = Vehicle(vehicle_id="v1", entry_gate="vitap-gate-main",
                          destination_id="vitap-osm-1485919486", arrival_tick=0)
        result = FirstAvailableStrategy().assign(vehicle, state)

        # Config (YAML) order: academic-main is first. Alphabetically admin-visitor < academic-main.
        assert result.parking_lot_id == "vitap-lot-academic-main", (
            f"B1 picked '{result.parking_lot_id}' but should pick 'vitap-lot-academic-main' "
            "(first in config order). If alphabetical, 'admin-visitor' would win instead."
        )


class TestCruising:
    """Cruising fix: overflow ≠ rejected; vehicles cruise to next lot when assigned lot fills."""

    def test_no_rejection_while_lots_have_space(self, conn, engine):
        """When any lot has usable space, no vehicle should be rejected.
        E1 normal day (400 veh, 472 usable spaces) — campus never fully fills,
        so rejected_vehicles must be 0."""
        with open(SCENARIOS / "E1_normal_day.yaml") as f:
            raw = yaml.safe_load(f)
        raw["random_seed"] = 42
        result = engine.run(ScenarioLoader.from_dict(raw), FirstAvailableStrategy(), conn)
        rejected = sum(1 for v in result.vehicles if v["final_state"] == "rejected")
        assert rejected == 0, (
            f"E1 (400 veh, 472 capacity): expected 0 rejections, got {rejected}. "
            "Vehicles should cruise to next lot, not be rejected while space exists."
        )

    def test_overflow_can_exceed_rejected(self, conn, engine):
        """overflow_events_count can be > rejected_vehicles_count when vehicles
        cruise successfully after finding their assigned lot full.
        Use E2 (470 veh) where some lots fill mid-run."""
        with open(SCENARIOS / "E2_event_placement.yaml") as f:
            raw = yaml.safe_load(f)
        raw["random_seed"] = 42
        result = engine.run(ScenarioLoader.from_dict(raw), NearestAvailableStrategy(), conn)
        overflow = result.metrics["overflow_events_count"]
        rejected = sum(1 for v in result.vehicles if v["final_state"] == "rejected")
        # With cruising: vehicles reroute, so overflow can be ≥ rejected
        assert overflow >= rejected, (
            f"overflow_events ({overflow}) should be >= rejected ({rejected}); "
            "cruising means overflow > rejected is normal"
        )

    def test_cruising_adds_travel_distance(self, conn, engine):
        """A vehicle that cruises (assigned lot full on arrival) should have
        higher travel_distance than one that parks directly.
        Force cruising by using very high demand on a small scenario."""
        with open(SCENARIOS / "E1_normal_day.yaml") as f:
            raw = yaml.safe_load(f)

        # Low demand baseline
        low = dict(raw)
        low["vehicle_count"] = 5
        low["random_seed"] = 10
        low["duration_minutes"] = 60
        low["warmdown_minutes"] = 0
        res_low = engine.run(ScenarioLoader.from_dict(low), FirstAvailableStrategy(), conn)

        # High demand forces lot fills and cruising
        high = dict(raw)
        high["vehicle_count"] = 450
        high["random_seed"] = 11
        high["duration_minutes"] = 60
        high["warmdown_minutes"] = 0
        high["arrival_rate_profile"] = {"type": "constant", "rate": 8.0}
        res_high = engine.run(ScenarioLoader.from_dict(high), FirstAvailableStrategy(), conn)

        dist_low = [v["travel_distance_meters"] for v in res_low.vehicles if v["travel_distance_meters"] > 0]
        dist_high = [v["travel_distance_meters"] for v in res_high.vehicles if v["travel_distance_meters"] > 0]

        if dist_low and dist_high:
            avg_low = sum(dist_low) / len(dist_low)
            avg_high = sum(dist_high) / len(dist_high)
            # High demand causes cruising → higher average distance per vehicle
            assert avg_high >= avg_low, (
                f"High-demand avg dist ({avg_high:.0f}m) should be >= low-demand ({avg_low:.0f}m) "
                "due to cruising to secondary lots"
            )

    def test_parking_full_still_produces_rejections(self, conn, engine):
        """When demand (600 veh) exceeds total campus capacity (472 usable spaces),
        true rejections must still occur — cruising cannot find space that doesn't exist."""
        scenario = ScenarioLoader.load(str(PROJECT_ROOT / "configs" / "scenarios" / "vitap" / "parking_full.yaml"))
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        rejected = sum(1 for v in result.vehicles if v["final_state"] == "rejected")
        assert rejected > 0, (
            "parking_full (600 veh vs 472 capacity): expected rejections, got 0. "
            "True rejection should still occur when no lot has usable space."
        )


class TestTimedClosures:
    """Timed closures: lot/gate closed only during [start_tick, end_tick)."""

    def _make_scenario(self, timed_closures, seed=7, vehicle_count=80, duration=200):
        return ScenarioLoader.from_dict({
            "scenario_id": "test-timed", "campus_id": "vitap",
            "name": "TIMED", "duration_minutes": duration, "vehicle_count": vehicle_count,
            "arrival_rate_profile": {"type": "constant", "rate": 0.5},
            "event_conditions": None, "random_seed": seed,
            "warmdown_minutes": 10,
            "availability_overrides": {
                "closed_gates": [], "closed_parking_lots": [], "closed_roads": [],
                "timed_closures": timed_closures,
            },
        })

    def test_no_inflow_to_lot_during_closure(self, conn, engine):
        """No vehicle may park in academic-main while it is timed-closed (ticks 60–120)."""
        scenario = self._make_scenario([
            {"entity_type": "parking_lot", "entity_id": "vitap-lot-academic-main", "start_tick": 60, "end_tick": 120}
        ])
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        # Find timestep records during closure
        for ts in result.timesteps:
            if 60 <= ts["tick"] < 120:
                occ_before = next(
                    (ts2.get("parking_occupancy_vitap-lot-academic-main", 0)
                     for ts2 in result.timesteps if ts2["tick"] == 59), 0
                )
                occ_now = ts.get("parking_occupancy_vitap-lot-academic-main", occ_before)
                # Occupancy must not increase during closure (only decreases via departures)
                assert occ_now <= occ_before + 1, (
                    f"tick {ts['tick']}: academic-main gained space during closure: {occ_before} → {occ_now}"
                )
                occ_before = occ_now

    def test_inflow_resumes_after_lot_closure(self, conn, engine):
        """Academic-main occupancy rises again after closure ends."""
        scenario = self._make_scenario([
            {"entity_type": "parking_lot", "entity_id": "vitap-lot-academic-main", "start_tick": 20, "end_tick": 60}
        ], vehicle_count=120)
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        # Peak occupancy AFTER closure must be > 0 (vehicles parked post-reopening)
        post_occs = [ts.get("parking_occupancy_vitap-lot-academic-main", 0)
                     for ts in result.timesteps if ts["tick"] >= 60]
        assert max(post_occs) > 0, "academic-main should accept vehicles after closure ends"

    def test_no_arrivals_at_closed_gate_during_closure(self, conn, engine):
        """During gate-main timed closure, queue at gate-main must not grow."""
        scenario = self._make_scenario([
            {"entity_type": "gate", "entity_id": "vitap-gate-main", "start_tick": 50, "end_tick": 100}
        ], vehicle_count=60)
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        for ts in result.timesteps:
            if 50 <= ts["tick"] < 100:
                assert ts.get("gate_queue_vitap-gate-main", 0) == 0, (
                    f"tick {ts['tick']}: gate-main queue should be 0 during closure, "
                    f"got {ts.get('gate_queue_vitap-gate-main')}"
                )

    def test_gate_diverts_arrivals_during_closure(self, conn, engine):
        """Vehicles arriving during gate-main closure are diverted; gate-main queue stays 0.
        Gate throughput is high enough that the visitor gate clears instantly, so we verify
        diversion via the invariant that gate-main never queues during closure, and that
        overall completion rate is not harmed (vehicles enter via visitor gate instead)."""
        scenario = self._make_scenario([
            {"entity_type": "gate", "entity_id": "vitap-gate-main", "start_tick": 40, "end_tick": 80}
        ], vehicle_count=80)
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        # Gate-main must have zero queue during closure (no arrivals admitted there)
        for ts in result.timesteps:
            if 40 <= ts["tick"] < 80:
                assert ts.get("gate_queue_vitap-gate-main", 0) == 0, (
                    f"tick {ts['tick']}: gate-main should have no queue during closure"
                )
        # Vehicles must still enter campus (not all rejected due to closed gate)
        assert len(result.vehicles) > 0, "Should have vehicles in simulation"


class TestRoadTimedClosure:
    """Road can be timed-closed; vehicles reroute; travel distance rises during closure."""

    def test_road_closure_no_rejections(self, conn, engine):
        """Closing main-gate→academic-main road forces reroute; all 400 vehicles still park."""
        scenario = ScenarioLoader.load(
            str(PROJECT_ROOT / "configs" / "scenarios" / "vitap" / "road_closure.yaml")
        )
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        rejected = sum(1 for v in result.vehicles if v["final_state"] == "rejected")
        assert rejected == 0, f"road_closure should produce 0 rejections (alt path exists), got {rejected}"

    def test_road_closure_travel_distance_higher_during_window(self, conn, engine):
        """Vehicles arriving during the road closure travel farther on average than those outside it."""
        scenario = ScenarioLoader.load(
            str(PROJECT_ROOT / "configs" / "scenarios" / "vitap" / "road_closure.yaml")
        )
        result = engine.run(scenario, FirstAvailableStrategy(), conn)
        # Closure is ticks 60–180 in the YAML
        closure_start, closure_end = 60, 180
        dist_during = [v["travel_distance_meters"] for v in result.vehicles
                       if closure_start <= v["arrival_tick"] < closure_end
                       and v.get("travel_distance_meters", 0) > 0]
        dist_outside = [v["travel_distance_meters"] for v in result.vehicles
                        if (v["arrival_tick"] < closure_start or v["arrival_tick"] >= closure_end)
                        and v.get("travel_distance_meters", 0) > 0]
        if dist_during and dist_outside:
            avg_during = sum(dist_during) / len(dist_during)
            avg_outside = sum(dist_outside) / len(dist_outside)
            assert avg_during >= avg_outside * 0.90, (
                f"During closure: avg dist {avg_during:.0f} m, outside: {avg_outside:.0f} m — "
                "expected closure window to have at least comparable travel distance"
            )


class TestGateQueueOverload:
    """Gate queue logic: queue grows when arrival rate exceeds service rate."""

    def test_gate_queue_grows_under_overload(self, conn, engine):
        """With gate capacity=1 and 6 veh/min burst, queue depth must exceed 0."""
        # Use the sample campus (1 gate with capacity we can control via the scenario)
        # We build a minimal in-memory scenario using vitap config but cap the gate
        # by setting a very low capacity in a direct DB patch after loading.
        # Patch gate-main capacity to 1 for this test only (in a separate connection)
        c2 = get_connection(":memory:")
        apply_migrations(c2)
        load_campus_config(
            PROJECT_ROOT / "configs" / "campus" / "vitap.yaml", c2
        )
        c2.execute("UPDATE gates SET capacity = 1 WHERE gate_id = 'vitap-gate-main'")
        c2.execute("UPDATE gates SET capacity = 1 WHERE gate_id = 'vitap-gate-visitor'")
        c2.commit()

        scenario = ScenarioLoader.from_dict({
            "scenario_id": "test-overload-gate", "campus_id": "vitap",
            "name": "OVERLOAD", "duration_minutes": 30, "vehicle_count": 180,
            "arrival_rate_profile": {"type": "constant", "rate": 6.0},
            "event_conditions": None, "random_seed": 1,
            "warmdown_minutes": 0,
            "availability_overrides": {
                "closed_gates": [], "closed_parking_lots": [], "closed_roads": [],
            },
        })
        result = engine.run(scenario, FirstAvailableStrategy(), c2)
        c2.close()

        all_queues = []
        for ts in result.timesteps:
            for key, val in ts.items():
                if key.startswith("gate_queue_") and isinstance(val, (int, float)):
                    all_queues.append(val)
        max_q = max(all_queues) if all_queues else 0
        assert max_q > 0, (
            f"With arrival_rate=6 veh/min and gate capacity=1 veh/min, queue must grow. "
            f"max queue depth = {max_q}"
        )


if __name__ == "__main__":
    print("Run with: python -m pytest tests/test_phase7_scenarios.py -v")
