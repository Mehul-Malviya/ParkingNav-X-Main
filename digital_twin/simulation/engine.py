"""
Part 4 (+ Part 5's occupancy/queue refinements): deterministic discrete-time
Simulation Engine.

Determinism is non-negotiable: one seeded random.Random instance is created
per run and threaded through every random decision -- arrivals, gate/
destination choice, dwell time. No unseeded randomness anywhere.

The engine contains no allocation decision logic. It calls the injected
AllocationStrategy exactly once per vehicle at the parking_search step, then
enforces Part 1's real constraints itself (closed/full lot, closed/blocked
road, gate throughput) regardless of what the strategy returned.

Time model: the loop runs in engine ticks of scenario.time_step_sec (default 10 s).
Scenario times (YAML) and logged ticks/timesteps are in MINUTES; see the conversion at
the top of the loop.

Simplification, documented rather than hidden: road_load is attributed to a
vehicle's route once, at the moment its transit begins (and counted per simulated
minute for BPR), not re-added on every subsequent tick of a multi-minute transit. This keeps the per-timestep
road_load metric transparent and deterministic; a finer-grained "vehicle is
occupying this edge for N ticks" model is a drop-in replacement later.
"""

import json
import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import networkx as nx

from digital_twin.graph_service import CampusGraphService
from digital_twin.simulation.metrics_recorder import MetricsRecorder
from digital_twin.simulation.scenario import ScenarioConfig, ScenarioValidator
from digital_twin.simulation.strategy import (
    AllocationStrategy,
    AssignmentResult,
    CampusState,
    NearestAvailableStrategy,
    Vehicle,
)
from digital_twin.twin_service import DigitalTwinService

DWELL_MINUTES_RANGE = (30, 480)
DWELL_LOGNORMAL_MU = 4.8   # ln(120) ≈ 4.79 → median ~120 min (realistic work/class session)
DWELL_LOGNORMAL_SIGMA = 0.6
logger = logging.getLogger(__name__)
STRATEGY_TIMEOUT_MS = 200  # 200ms timeout per spec (B1=0.001ms, B2=0.05ms typical)

BPR_ALPHA = 0.15
BPR_BETA = 4


def bpr_travel_time(t_free_seconds: float, flow: int, capacity: int) -> float:
    """Bureau of Public Roads travel time: t_free * (1 + 0.15*(flow/capacity)^4)."""
    if capacity <= 0:
        return t_free_seconds
    return t_free_seconds * (1 + BPR_ALPHA * (flow / capacity) ** BPR_BETA)


class StrategyTimeoutError(Exception):
    """Raised when strategy exceeds time budget."""
    pass


@dataclass
class _RunningVehicle:
    vehicle: Vehicle
    state: str = "arrival"  # arrival, gate_queue, campus_entry, route, parking_search,
                              # parking_assignment, parked, departure, completed
    queue_enter_tick: Optional[int] = None
    gate_admitted_tick: Optional[int] = None
    search_start_tick: Optional[int] = None
    lot_arrival_tick: Optional[int] = None   # tick the vehicle reached its lot (SEARCHING starts)
    search_end_tick: Optional[int] = None    # tick the search finished and the vehicle PARKED
    assigned_lot_id: Optional[str] = None
    dwell_minutes: int = 0
    dwell_mu: float = DWELL_LOGNORMAL_MU        # lognormal mu for this vehicle (event-overridable)
    dwell_sigma: float = DWELL_LOGNORMAL_SIGMA
    remaining_transit_minutes: float = 0.0
    outbound_route_computed: bool = False
    outbound_distance_meters: float = 0.0
    inbound_distance_meters: float = 0.0
    completion_tick: Optional[int] = None
    outbound_transit_seconds: float = 0.0  # Fix 1: BPR gate→lot travel time only
    occupancy_search_seconds: float = 0.0  # Fix 2: occupancy-based search time at assignment
    reassigned_count: int = 0             # incremented each time lot fills during transit → reroute
    arrival_engine_tick: int = 0          # arrival in engine ticks (arrival_tick on Vehicle is in minutes)
    departure_tick: Optional[int] = None  # engine tick at which the vehicle left its lot


@dataclass
class SimulationResult:
    run_id: str
    campus_id: str
    scenario_id: str
    random_seed: int
    strategy_name: str
    vehicles: list = field(default_factory=list)     # list of per-vehicle metric dicts
    timesteps: list = field(default_factory=list)    # list of per-timestep metric dicts
    overflow_events: list = field(default_factory=list)
    infeasibility_rejections: int = 0                # count of assignments rejected due to infeasibility
    adapter_fallbacks: int = 0                       # count of fallbacks to B2 due to timeout/exception
    decision_latencies: list = field(default_factory=list)  # [{tick, latency_ms}] per 5-min decision cycle
    time_step_sec: int = 10                          # engine tick length used for this run
    config_hash: str = ""                            # SHA-256 of scenario YAML (for reproducibility)
    git_sha: str = ""                                # HEAD commit SHA at run time
    runtime_sec: float = 0.0                         # wall-clock seconds for this run

    @property
    def metrics(self) -> dict:
        """Derived summary metrics computed from vehicle records."""
        if not self.vehicles:
            return {
                "avg_search_time_min": 0.0,
                "avg_wait_time_min": 0.0,
                "avg_gate_queue": 0.0,
                "overflow_events_count": len(self.overflow_events),
                "total_vehicles": 0,
                "completed_vehicles": 0,
            }
        search_times = [v.get("search_time_seconds", 0) / 60.0 for v in self.vehicles]
        wait_times = [v.get("waiting_time_seconds", 0) / 60.0 for v in self.vehicles]
        travel_times = [v.get("travel_time_seconds", 0) / 60.0 for v in self.vehicles]
        travel_distances = [v.get("travel_distance_meters", 0) for v in self.vehicles]
        avg_wait = sum(wait_times) / len(wait_times)
        _parked   = sum(1 for v in self.vehicles if v.get("final_state") == "parked")
        _exited   = sum(1 for v in self.vehicles if v.get("final_state") == "exited")
        _rejected = sum(1 for v in self.vehicles if v.get("final_state") == "rejected")
        _in_sys   = sum(1 for v in self.vehicles if v.get("final_state") == "in_system")
        _total    = len(self.vehicles)
        _total_reassignments = sum(v.get("reassigned_count", 0) for v in self.vehicles)
        # avg/max gate queue DEPTH (vehicles) computed from per-tick timestep data
        gate_keys = [k for k in (self.timesteps[0] if self.timesteps else {}) if k.startswith("gate_queue_")]
        if gate_keys and self.timesteps:
            total_queue_per_tick = [sum(ts.get(k, 0) for k in gate_keys) for ts in self.timesteps]
            _avg_gq = sum(total_queue_per_tick) / len(total_queue_per_tick)
            _max_gq = max(total_queue_per_tick)
        else:
            _avg_gq = 0.0
            _max_gq = 0.0
        return {
            # ── 5 primary metrics (spec) ──────────────────────────────────────
            "avg_search_time_min": sum(search_times) / len(search_times),
            "avg_wait_time_min": avg_wait,
            "avg_gate_queue": _avg_gq,          # avg queue DEPTH (vehicles), not wait time
            "max_gate_queue": _max_gq,          # max queue DEPTH (vehicles) at any tick
            "overflow_events_count": len(self.overflow_events),
            "avg_travel_time_min": sum(travel_times) / len(travel_times),
            "total_travel_distance_m": sum(travel_distances),
            # ── supporting ───────────────────────────────────────────────────
            "max_search_time_min": max(search_times),
            "total_vehicles": _total,
            "completed_vehicles": _exited,
            # parked_vehicles = snapshot at sim end (still parked, not yet departed)
            # total_ever_parked = all that ever reached parked state (parked + exited)
            "parked_vehicles": _parked,
            "total_ever_parked": _parked + _exited,
            "successful_park_rate": round((_parked + _exited) / _total, 4) if _total else 0.0,
            "total_reassignments": _total_reassignments,
            "infeasibility_rejections": self.infeasibility_rejections,
            "adapter_fallbacks": self.adapter_fallbacks,
        }

    @property
    def secondary_metrics(self) -> dict:
        """Conservation breakdown + success rate — separate from primary metrics
        so iteration over metrics never hits a nested dict."""
        if not self.vehicles:
            return {"total_vehicles_simulated": 0, "parked": 0, "exited": 0,
                    "in_system": 0, "rejected": 0, "allocation_success_rate": 0.0,
                    "conservation_check": True,
                    "in_system_breakdown": {"queued": 0, "driving": 0, "searching": 0, "departing": 0}}
        _parked   = sum(1 for v in self.vehicles if v.get("final_state") == "parked")
        _exited   = sum(1 for v in self.vehicles if v.get("final_state") == "exited")
        _rejected = sum(1 for v in self.vehicles if v.get("final_state") == "rejected")
        _in_sys   = sum(1 for v in self.vehicles if v.get("final_state") == "in_system")
        _total    = len(self.vehicles)
        # Utilisation across lots: derive peak occupancy_pct per lot from timestep data
        lot_occ_keys = [k for k in (self.timesteps[0] if self.timesteps else {}) if k.startswith("parking_occupancy_")]
        lot_cap_keys = [k for k in (self.timesteps[0] if self.timesteps else {}) if k.startswith("parking_capacity_")]
        if lot_occ_keys and self.timesteps:
            # avg utilisation = mean over lots of (mean occupancy_pct across ticks)
            util_by_lot = []
            for ok in lot_occ_keys:
                lot_id = ok.replace("parking_occupancy_", "")
                ck = f"parking_capacity_{lot_id}"
                # capacity is constant per lot; take max across ticks (or first non-zero)
                cap_val = max((ts.get(ck, 0) for ts in self.timesteps), default=0) or 1
                occ_vals = [ts.get(ok, 0) for ts in self.timesteps]
                pct_vals = [min(o / cap_val * 100.0, 100.0) for o in occ_vals]
                util_by_lot.append(sum(pct_vals) / len(pct_vals))
            _avg_util = sum(util_by_lot) / len(util_by_lot) if util_by_lot else 0.0
            # utilisation imbalance = std-dev of per-lot mean utilisation
            mean_u = _avg_util
            _util_imbalance = (sum((u - mean_u) ** 2 for u in util_by_lot) / len(util_by_lot)) ** 0.5 if util_by_lot else 0.0
        else:
            _avg_util = 0.0
            _util_imbalance = 0.0
        # Per-decision latency
        _avg_latency_ms = (
            sum(d.get("latency_ms", 0) for d in self.decision_latencies) / len(self.decision_latencies)
            if self.decision_latencies else 0.0
        )
        return {
            "total_vehicles_simulated": _total,
            "parked": _parked,
            "exited": _exited,
            "in_system": _in_sys,
            "rejected": _rejected,
            "allocation_success_rate": round((_parked + _exited) / _total, 4) if _total else 0.0,
            "conservation_check": _total == (_parked + _exited + _in_sys + _rejected),
            "avg_utilization_pct": round(_avg_util, 2),
            "utilization_imbalance": round(_util_imbalance, 2),
            "simulation_runtime_sec": self.runtime_sec,
            "avg_decision_latency_ms": round(_avg_latency_ms, 3),
            "in_system_breakdown": {
                "queued": sum(1 for v in self.vehicles if v.get("internal_state") in ("arrival", "gate_queue")),
                "driving": sum(1 for v in self.vehicles if v.get("internal_state") in ("campus_entry", "route", "parking_search")),
                "searching": sum(1 for v in self.vehicles if v.get("internal_state") == "searching"),
                "departing": sum(1 for v in self.vehicles if v.get("internal_state") == "departure"),
            },
        }


def _congestion_level(load: int, capacity) -> str:
    """Matches Part 3's exact enum: free|moderate|heavy|blocked."""
    if not capacity or capacity <= 0:
        return "free"
    ratio = load / capacity
    if ratio == 0:
        return "free"
    if ratio < 0.5:
        return "moderate"
    if ratio < 1.0:
        return "heavy"
    return "blocked"


def _arrival_rate_at(profile: dict, t: int) -> float:
    if profile["type"] == "constant":
        return profile["rate"]
    points = sorted(profile["points"], key=lambda p: p["time"])
    if t <= points[0]["time"]:
        return points[0]["rate"]
    if t >= points[-1]["time"]:
        return points[-1]["rate"]
    for i in range(len(points) - 1):
        t0, t1 = points[i]["time"], points[i + 1]["time"]
        if t0 <= t <= t1:
            r0, r1 = points[i]["rate"], points[i + 1]["rate"]
            frac = (t - t0) / (t1 - t0) if t1 != t0 else 0
            return r0 + frac * (r1 - r0)
    return points[-1]["rate"]


class SimulationEngine:
    def __init__(self, graph_service: Optional[CampusGraphService] = None,
                 twin_service: Optional[DigitalTwinService] = None,
                 runs_dir: Optional[str] = None):
        self.graph_service = graph_service or CampusGraphService()
        self.twin_service = twin_service or DigitalTwinService()
        self.runs_dir = runs_dir  # None → uses MetricsRecorder default ("runs")

    def run(self, scenario: ScenarioConfig, strategy: AllocationStrategy, conn,
            run_id: Optional[str] = None) -> SimulationResult:
        # Validate scenario before any simulation work; raises ValueError on bad entity IDs
        errors = ScenarioValidator.validate(scenario, conn)
        if errors:
            raise ValueError(f"Scenario '{scenario.scenario_id}' validation failed:\n" + "\n".join(errors))

        import hashlib
        import subprocess
        import time as _time

        _run_start = _time.monotonic()

        # config_hash: SHA-256 of the scenario dict (deterministic, order-stable)
        _scenario_bytes = json.dumps(scenario.__dict__, sort_keys=True, default=str).encode()
        _config_hash = hashlib.sha256(_scenario_bytes).hexdigest()[:16]

        # git_sha: HEAD commit at run time (best-effort; empty string on failure)
        try:
            _git_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            _git_sha = ""

        rng = random.Random(scenario.random_seed)  # the ONE seeded RNG for this entire run

        run_id = run_id or f"{scenario.scenario_id}-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc).isoformat()
        strategy_name = getattr(strategy, "label", strategy.__class__.__name__)

        conn.execute(
            """INSERT INTO simulation_runs (run_id, campus_id, scenario_id, random_seed, strategy_name,
                 configuration_version, started_at, status)
               VALUES (?, ?, ?, ?, ?, (SELECT active_configuration_version FROM campuses WHERE campus_id=?), ?, 'running')""",
            (run_id, scenario.campus_id, scenario.scenario_id, scenario.random_seed, strategy_name,
             scenario.campus_id, started_at),
        )
        conn.commit()

        graph = self.graph_service.build_graph(scenario.campus_id, conn)
        original_graph = graph  # kept for restoring timed road closures
        working_graph = self._apply_availability_overrides(graph, scenario)

        gates = self._load_gates(scenario.campus_id, conn, scenario.availability_overrides)
        parking_lots = self._load_parking_lots(scenario.campus_id, conn, scenario.availability_overrides)
        destinations = self._load_destination_ids(scenario.campus_id, conn)
        roads = self._load_roads(scenario.campus_id, conn)

        open_gate_ids = [g for g, d in gates.items() if d["status"] == "open"]
        open_lot_ids = [p for p, d in parking_lots.items() if d["status"] == "open"]

        running_vehicles = self._generate_arrivals(scenario, rng, open_gate_ids, destinations)
        gate_queues = {g: [] for g in gates}  # FIFO lists of vehicle_ids
        gate_sim = None
        if scenario.gate_model == "simpy":
            from digital_twin.simulation.gate_simpy import SimpyGates  # optional dependency
            gate_sim = SimpyGates({g: d["capacity"] for g, d in gates.items()})
        by_id = {rv.vehicle.vehicle_id: rv for rv in running_vehicles}

        timesteps_metrics = []
        overflow_events = []
        road_load = {r: 0 for r in roads}
        decision_latencies = []  # log (tick, latency_ms)
        infeasibility_rejections = 0  # count of assignments rejected as infeasible
        adapter_fallbacks = 0  # count of fallbacks to B2

        # Time model: engine ticks are time_step_sec long (spec default 10 s). Scenario times (YAML) are in
        # minutes and logged ticks stay in minutes; only the internal loop runs at the finer step.
        dt = scenario.time_step_sec
        tpm = 60 // dt            # engine ticks per minute
        step_min = dt / 60.0      # minutes advanced per engine tick
        gate_credit = {g: 0.0 for g in gates}   # fractional vehicles a gate may still serve (rate x dt)
        gate_throughput = {g: 0 for g in gates}  # vehicles served this minute (reset each minute boundary)

        def _to_ticks(minutes):
            return None if minutes is None else minutes * tpm

        timed_closures = [
            {**tc, "start_tick": _to_ticks(tc.get("start_tick")), "end_tick": _to_ticks(tc.get("end_tick"))}
            for tc in (scenario.availability_overrides or {}).get("timed_closures", [])
        ]

        # Create noise injector once so its RNG advances across cycles (not reset each decision tick)
        _noise_injector = None
        if scenario.prediction_error_injection_level > 0.0:
            from digital_twin.simulation.forecast_noise import ForecastNoiseInjector
            _noise_injector = ForecastNoiseInjector(
                noise_level=scenario.prediction_error_injection_level,
                seed=scenario.random_seed + 9999,
            )

        for tick in range(scenario.duration_minutes * tpm):
            minute = tick // tpm
            minute_end = (tick + 1) % tpm == 0
            # Apply/remove timed closures at their start/end (already converted from minutes to engine ticks)
            for tc in timed_closures:
                etype = tc.get("entity_type")
                eid = tc.get("entity_id")
                if tick == tc.get("start_tick"):
                    if etype == "parking_lot" and eid in parking_lots:
                        parking_lots[eid]["status"] = "closed"
                        if eid in open_lot_ids:
                            open_lot_ids.remove(eid)
                    elif etype == "gate" and eid in gates:
                        gates[eid]["status"] = "closed"
                        if eid in open_gate_ids:
                            open_gate_ids.remove(eid)
                        # Drain queued vehicles at the closing gate to nearest open gate
                        if gate_sim is not None:
                            if gate_sim.queue_length(eid) and open_gate_ids:
                                gate_sim.close_gate(eid, sorted(open_gate_ids)[0])
                        elif gate_queues.get(eid) and open_gate_ids:
                            alt = sorted(open_gate_ids)[0]
                            gate_queues[alt].extend(gate_queues[eid])
                            gate_queues[eid] = []
                    elif etype == "road":
                        # Remove all edges with this road_id from the working graph
                        edges_to_remove = [(u, v) for u, v, d in working_graph.edges(data=True)
                                          if d.get("road_id") == eid]
                        for u, v in edges_to_remove:
                            working_graph.remove_edge(u, v)
                elif tick == tc.get("end_tick"):
                    if etype == "parking_lot" and eid in parking_lots:
                        parking_lots[eid]["status"] = "open"
                        if eid not in open_lot_ids:
                            open_lot_ids.append(eid)
                    elif etype == "gate" and eid in gates:
                        gates[eid]["status"] = "open"
                        if eid not in open_gate_ids:
                            open_gate_ids.append(eid)
                    elif etype == "road":
                        # Restore edges from the original graph
                        for u, v, d in original_graph.edges(data=True):
                            if d.get("road_id") == eid and not working_graph.has_edge(u, v):
                                working_graph.add_edge(u, v, **d)

            # Decision cycle: every 5 minutes, call strategy.update_policy()
            if tick % (5 * tpm) == 0:
                decision_start = datetime.now(timezone.utc)
                state_snapshot = self.twin_service.get_current_state(scenario.campus_id, conn, now=decision_start)

                # Build forecast when prediction is enabled for this scenario
                forecast = None
                if scenario.use_prediction:
                    try:
                        from digital_twin.prediction.engine import get_predictor
                        predictor = get_predictor()
                        # Update current fill rates from live campus state
                        for lot_id, lot_data in parking_lots.items():
                            cap = lot_data.get("usable_capacity", 1) or 1
                            occ = lot_data.get("occupied_spaces", 0)
                            predictor.update_current(lot_id, occ / cap)
                        forecast = predictor.get_forecast_snapshot(horizon_minutes=15)
                        # Inject noise if configured (E5 robustness scenarios)
                        if _noise_injector is not None:
                            lot_fills = forecast.get("lot_fill_rates", {})
                            noisy_fills = {}
                            for lid, fill in lot_fills.items():
                                noisy_fc = _noise_injector.perturb({"occupancy": fill})
                                noisy_fills[lid] = min(1.0, max(0.0, noisy_fc.get("occupancy", fill)))
                            forecast = {**forecast, "lot_fill_rates": noisy_fills}
                    except Exception as _pred_err:
                        logger.warning("Prediction unavailable during decision cycle: %s", _pred_err)
                        forecast = None

                # Pass ablation flags so P strategy can disable components selectively
                ablation_flags = {
                    "use_prediction": scenario.use_prediction,
                    "use_optimization": scenario.use_optimization,
                    "use_uncertainty": scenario.use_uncertainty,
                    "proactive": scenario.proactive,
                }
                try:
                    strategy.update_policy(state_snapshot, forecast=forecast, ablation_flags=ablation_flags)
                except TypeError:
                    # B1/B2 strategies use the old signature (no ablation_flags kwarg)
                    strategy.update_policy(state_snapshot, forecast=forecast)

                decision_latency_ms = (datetime.now(timezone.utc) - decision_start).total_seconds() * 1000
                decision_latencies.append({"tick": minute, "latency_ms": round(decision_latency_ms, 2)})
            for rv in running_vehicles:
                if rv.arrival_engine_tick == tick and rv.state == "arrival":
                    if rv.vehicle.entry_gate in open_gate_ids:
                        rv.state = "gate_queue"
                        rv.queue_enter_tick = tick
                        if gate_sim is not None:
                            gate_sim.join(rv.vehicle.entry_gate, rv.vehicle.vehicle_id)
                        else:
                            gate_queues[rv.vehicle.entry_gate].append(rv.vehicle.vehicle_id)
                    elif open_gate_ids:
                        # Gate closed (timed or static): divert to nearest open gate
                        rv.vehicle.entry_gate = sorted(open_gate_ids)[0]
                        rv.state = "gate_queue"
                        rv.queue_enter_tick = tick
                        if gate_sim is not None:
                            gate_sim.join(rv.vehicle.entry_gate, rv.vehicle.vehicle_id)
                        else:
                            gate_queues[rv.vehicle.entry_gate].append(rv.vehicle.vehicle_id)
                    else:
                        rv.state = "completed"  # no gate at all: never enters

            if gate_sim is not None:
                for vehicle_id in gate_sim.advance((tick + 1) * dt):
                    rv = by_id[vehicle_id]
                    rv.state = "campus_entry"
                    rv.gate_admitted_tick = tick
                    gate_throughput[rv.vehicle.entry_gate] += 1
            for gate_id in ([] if gate_sim is not None else open_gate_ids):
                # service_rate (veh/min) x dt: fractional credit accumulates, at most one tick's worth (min 1)
                rate_per_tick = gates[gate_id]["capacity"] * step_min
                gate_credit[gate_id] = min(gate_credit[gate_id] + rate_per_tick, max(1.0, rate_per_tick))
                queue = gate_queues[gate_id]
                while queue and gate_credit[gate_id] >= 1.0 - 1e-9:
                    vehicle_id = queue.pop(0)  # FIFO
                    rv = by_id[vehicle_id]
                    rv.state = "campus_entry"
                    rv.gate_admitted_tick = tick
                    gate_credit[gate_id] -= 1.0
                    gate_throughput[gate_id] += 1

            for rv in running_vehicles:
                if rv.state == "campus_entry":
                    rv.state = "route"
                elif rv.state == "route":
                    # Strategy decides FIRST; then route from gate to the assigned lot.
                    state_view = CampusState(
                        campus_id=scenario.campus_id, graph=working_graph,
                        parking_lots={k: dict(v) for k, v in parking_lots.items()},
                        gates={k: dict(v) for k, v in gates.items()},
                        roads={k: dict(v) for k, v in roads.items()},
                    )
                    fallback_reason = None
                    if rv.vehicle.complies_with_strategy:
                        result, fallback_reason = self._assign_with_adapter(
                            strategy, rv.vehicle, state_view, parking_lots, open_lot_ids, working_graph
                        )
                        if fallback_reason:
                            adapter_fallbacks += 1
                            logger.warning("tick=%d vehicle=%s: strategy %s failed (%s) -- fell back to Nearest",
                                           minute, rv.vehicle.vehicle_id, strategy.__class__.__name__, fallback_reason)
                    else:
                        nearest = self._nearest_available_lot(
                            rv.vehicle.entry_gate, open_lot_ids, parking_lots, working_graph
                        )
                        result = AssignmentResult(parking_lot_id=nearest)

                    lot = parking_lots.get(result.parking_lot_id) if result else None
                    feasible = (
                        lot is not None and lot["status"] == "open"
                        and lot["occupied_spaces"] < lot["usable_capacity"]
                    )
                    if not feasible:
                        infeasibility_rejections += 1
                        rv.state = "rejected"
                        overflow_events.append({"tick": minute, "parking_lot_id": result.parking_lot_id if result else None, "reason": "infeasible_at_route"})
                        continue

                    # Route from gate to the strategy-assigned lot
                    assigned_lot = result.parking_lot_id
                    if not nx.has_path(working_graph, rv.vehicle.entry_gate, assigned_lot):
                        infeasibility_rejections += 1
                        rv.state = "rejected"
                        overflow_events.append({"tick": minute, "parking_lot_id": assigned_lot, "reason": "unreachable_at_route"})
                        continue
                    path = nx.shortest_path(working_graph, rv.vehicle.entry_gate, assigned_lot, weight="weight_time_seconds")
                    travel_time = 0.0
                    distance = 0.0
                    for a, b in zip(path, path[1:]):
                        edge = working_graph.edges[a, b]
                        road_id = edge.get("road_id")
                        if road_id in road_load:
                            road_load[road_id] += 1
                        t_free = edge.get("weight_time_seconds", 60.0)
                        cap = edge.get("capacity", 20) if road_id else 20
                        flow = road_load.get(road_id, 0)
                        travel_time += bpr_travel_time(t_free, flow, cap)
                        distance += edge.get("weight_distance_meters", 0.0)
                    rv.remaining_transit_minutes = max(step_min, travel_time / 60.0)
                    rv.outbound_distance_meters = distance
                    rv.outbound_transit_seconds = travel_time  # Fix 1: gate→assigned-lot BPR time
                    rv.assigned_lot_id = assigned_lot
                    rv.state = "parking_search"
                    rv.search_start_tick = tick

                elif rv.state == "parking_search":
                    # Transit countdown; park when elapsed
                    rv.remaining_transit_minutes -= step_min
                    if rv.remaining_transit_minutes > 1e-9:
                        continue

                    # Re-check feasibility: lot may have filled during transit
                    lot = parking_lots.get(rv.assigned_lot_id)
                    feasible = (
                        lot is not None and lot["status"] == "open"
                        and lot["occupied_spaces"] < lot["usable_capacity"]
                    )

                    if not feasible:
                        # Count overflow; cruise to next feasible lot.
                        # Reject ONLY if no lot on campus has usable space.
                        failed_lot = rv.assigned_lot_id

                        state_view = CampusState(
                            campus_id=scenario.campus_id, graph=working_graph,
                            parking_lots={k: dict(v) for k, v in parking_lots.items()},
                            gates={k: dict(v) for k, v in gates.items()},
                            roads={k: dict(v) for k, v in roads.items()},
                        )
                        new_lot_id = None
                        if rv.vehicle.complies_with_strategy:
                            new_result, _ = self._assign_with_adapter(
                                strategy, rv.vehicle, state_view, parking_lots, open_lot_ids, working_graph
                            )
                            new_lot_id = new_result.parking_lot_id if new_result else None
                        else:
                            new_lot_id = self._nearest_available_lot(
                                failed_lot if failed_lot in working_graph else rv.vehicle.entry_gate,
                                open_lot_ids, parking_lots, working_graph
                            )

                        if not new_lot_id or new_lot_id == failed_lot:
                            # No usable space on campus → true rejection
                            infeasibility_rejections += 1
                            rv.state = "rejected"
                            overflow_events.append({"tick": minute, "parking_lot_id": failed_lot, "reason": "no_feasible_lot_after_fill"})
                            continue

                        # Re-route from failed lot to new lot (cruising adds time and distance)
                        rv.reassigned_count += 1
                        from_node = failed_lot if failed_lot in working_graph else rv.vehicle.entry_gate
                        if not nx.has_path(working_graph, from_node, new_lot_id):
                            infeasibility_rejections += 1
                            rv.state = "rejected"
                            overflow_events.append({"tick": minute, "parking_lot_id": new_lot_id, "reason": "unreachable_after_fill"})
                            continue

                        path = nx.shortest_path(working_graph, from_node, new_lot_id, weight="weight_time_seconds")
                        extra_time = 0.0
                        extra_dist = 0.0
                        for a, b in zip(path, path[1:]):
                            edge = working_graph.edges[a, b]
                            road_id = edge.get("road_id")
                            if road_id in road_load:
                                road_load[road_id] += 1
                            t_free = edge.get("weight_time_seconds", 60.0)
                            cap = edge.get("capacity", 20) if road_id else 20
                            flow = road_load.get(road_id, 0)
                            extra_time += bpr_travel_time(t_free, flow, cap)
                            extra_dist += edge.get("weight_distance_meters", 0.0)

                        rv.outbound_transit_seconds += extra_time
                        rv.outbound_distance_meters += extra_dist
                        rv.remaining_transit_minutes = max(step_min, extra_time / 60.0)
                        rv.assigned_lot_id = new_lot_id
                        # stay in parking_search — re-enters transit countdown next tick
                        continue

                    # Reached the lot: reserve a space now (capacity can never be exceeded) and spend the
                    # spec search time SEARCHING before parking: base + k*occ^2 (base 0.5 min, k 5.5 min).
                    rv.lot_arrival_tick = tick
                    occ = lot["occupied_spaces"] / max(1, lot["usable_capacity"])
                    rv.occupancy_search_seconds = (0.5 + 5.5 * occ ** 2) * 60
                    lot["occupied_spaces"] += 1
                    rv.remaining_transit_minutes = rv.occupancy_search_seconds / 60.0
                    rv.state = "searching"
                    self.twin_service.update_parking_state(
                        scenario.campus_id, rv.assigned_lot_id, lot["occupied_spaces"],
                        "simulation", "SYNTHETIC", datetime.now(timezone.utc).isoformat(), conn,
                        commit=False,
                    )

                elif rv.state == "searching":
                    rv.remaining_transit_minutes -= step_min
                    if rv.remaining_transit_minutes <= 1e-9:
                        rv.search_end_tick = tick
                        raw = rng.gauss(rv.dwell_mu, rv.dwell_sigma)
                        rv.dwell_minutes = min(max(int(DWELL_MINUTES_RANGE[0]), int(2.718281828 ** raw)), DWELL_MINUTES_RANGE[1])
                        rv.remaining_transit_minutes = rv.dwell_minutes
                        rv.state = "parked"

                elif rv.state == "parked":
                    rv.remaining_transit_minutes -= step_min
                    if rv.remaining_transit_minutes <= 1e-9:
                        lot = parking_lots[rv.assigned_lot_id]
                        # Part 5's one intentional clamp: internal consistency guard only.
                        lot["occupied_spaces"] = max(0, lot["occupied_spaces"] - 1)
                        self.twin_service.update_parking_state(
                            scenario.campus_id, rv.assigned_lot_id, lot["occupied_spaces"],
                            "simulation", "SYNTHETIC", datetime.now(timezone.utc).isoformat(), conn,
                            commit=False,
                        )
                        if nx.has_path(working_graph, rv.assigned_lot_id, rv.vehicle.entry_gate):
                            distance = nx.shortest_path_length(working_graph, rv.assigned_lot_id, rv.vehicle.entry_gate, weight="weight_distance_meters")
                            travel_time = nx.shortest_path_length(working_graph, rv.assigned_lot_id, rv.vehicle.entry_gate, weight="weight_time_seconds")
                            rv.inbound_distance_meters = distance
                            rv.remaining_transit_minutes = max(step_min, travel_time / 60.0)
                        else:
                            rv.remaining_transit_minutes = step_min
                        rv.state = "departure"
                        rv.departure_tick = tick

                elif rv.state == "departure":
                    rv.remaining_transit_minutes -= step_min
                    if rv.remaining_transit_minutes <= 1e-9:
                        rv.state = "completed"
                        rv.completion_tick = tick

            for gate_id, queue in gate_queues.items():
                gates[gate_id]["queue_length"] = gate_sim.queue_length(gate_id) if gate_sim is not None else len(queue)

            if minute_end:  # persist + record once per simulated minute
                now_iso = datetime.now(timezone.utc).isoformat()
                for gate_id, gate in gates.items():
                    self.twin_service.update_gate_state(
                        scenario.campus_id, gate_id, gate["queue_length"], 0,
                        "simulation", "SYNTHETIC", now_iso, conn, commit=False,
                    )
                for road_id, load in road_load.items():
                    road_capacity = roads[road_id].get("capacity")
                    self.twin_service.update_road_state(
                        scenario.campus_id, road_id, load, _congestion_level(load, road_capacity),
                        "simulation", "SYNTHETIC", now_iso, conn, commit=False,
                    )
                for rv in running_vehicles:
                    if rv.state not in ("arrival",):  # only persist vehicles that have actually started their lifecycle
                        self.twin_service.update_vehicle_state(
                            scenario.campus_id, rv.vehicle.vehicle_id, rv.state, "simulation", now_iso, conn,
                            destination_id=rv.vehicle.destination_id,
                            assigned_parking_lot_id=rv.assigned_lot_id,
                            commit=False,
                        )
                conn.commit()  # one batched commit per simulated minute instead of one per write

                # ── Spec invariant assertions (checked once per simulated minute) ─
                for _lid, _lot in parking_lots.items():
                    assert _lot["occupied_spaces"] >= 0, \
                        f"Invariant violated: lot '{_lid}' has negative occupancy ({_lot['occupied_spaces']})"
                    assert _lot["occupied_spaces"] <= _lot["usable_capacity"], \
                        f"Invariant violated: lot '{_lid}' occupancy ({_lot['occupied_spaces']}) > capacity ({_lot['usable_capacity']})"
                    # closed-lot invariant: engine enforces no new assignments at strategy level

                overflow_this_tick = {e["parking_lot_id"] for e in overflow_events if e["tick"] == minute}
                timesteps_metrics.append({
                    "tick": minute,
                    **{f"gate_queue_{g}": gates[g]["queue_length"] for g in gates},
                    **{f"gate_throughput_{g}": gate_throughput[g] for g in gates},
                    **{f"parking_occupancy_{p}": parking_lots[p]["occupied_spaces"] for p in parking_lots},
                    **{f"parking_capacity_{p}": parking_lots[p]["usable_capacity"] for p in parking_lots},
                    **{f"overflow_{p}": p in overflow_this_tick for p in parking_lots},
                    **{f"road_load_{r}": road_load[r] for r in roads},
                })
                road_load = {r: 0 for r in road_load}
                gate_throughput = {g: 0 for g in gates}

        vehicle_metrics = []
        for rv in running_vehicles:
            waiting_time = ((rv.gate_admitted_tick - rv.queue_enter_tick) * dt) if rv.gate_admitted_tick is not None and rv.queue_enter_tick is not None else 0
            # Normalize internal states to canonical output states
            _state_map = {
                "completed": "exited",
                "parked": "parked",
                "departure": "in_system",
                "route": "in_system",
                "parking_search": "in_system",
                "searching": "in_system",
                "campus_entry": "in_system",
                "gate_queue": "in_system",
                "arrival": "in_system",
            }
            canonical_state = _state_map.get(rv.state, "rejected")
            # Reconstruct state trace from recorded tick fields for VERIFY output
            _spec_state = {
                "arrival": "SCHEDULED",
                "gate_queue": "QUEUED_AT_GATE",
                "campus_entry": "ENTERING",
                "route": "DRIVING",
                "parking_search": "DRIVING",
                "searching": "SEARCHING",
                "parked": "PARKED",
                "departure": "DEPARTING",
                "completed": "EXITED",
                "rejected": "REJECTED_OVERFLOW",
            }
            def _m(t):
                return None if t is None else t // tpm

            def _ev(t, state):
                return {"tick": t // tpm, "t_sec": t * dt, "state": state}

            # Trace timestamps: "tick" in minutes (contract), "t_sec" in seconds since scenario start.
            trace = []
            if rv.vehicle.arrival_tick is not None:
                trace.append(_ev(rv.arrival_engine_tick, "SCHEDULED"))
            if rv.queue_enter_tick is not None:
                trace.append(_ev(rv.queue_enter_tick, "QUEUED_AT_GATE"))
            if rv.gate_admitted_tick is not None:
                trace.append(_ev(rv.gate_admitted_tick, "ENTERING"))
            # DRIVING = gate -> lot transit (BPR time); SEARCHING = at the lot, duration base+k*occ^2 (analytic)
            if rv.search_start_tick is not None:
                trace.append(_ev(rv.search_start_tick, "DRIVING"))
            if rv.lot_arrival_tick is not None:
                trace.append(_ev(rv.lot_arrival_tick, "SEARCHING"))
            if rv.search_end_tick is not None:
                trace.append(_ev(rv.search_end_tick, "PARKED"))
            if rv.departure_tick is not None:
                trace.append(_ev(rv.departure_tick, "DEPARTING"))
            if rv.completion_tick is not None:
                trace.append(_ev(rv.completion_tick, "EXITED"))
            if canonical_state == "rejected":
                trace.append(_ev(rv.search_start_tick if rv.search_start_tick is not None else rv.arrival_engine_tick, "REJECTED_OVERFLOW"))
            vehicle_metrics.append({
                "vehicle_id": rv.vehicle.vehicle_id,
                "entry_gate": rv.vehicle.entry_gate,
                "destination_id": rv.vehicle.destination_id,
                "arrival_tick": rv.vehicle.arrival_tick,
                "arrival_time": rv.vehicle.arrival_tick + scenario.start_time_min,  # minutes since midnight
                "search_time_seconds": rv.occupancy_search_seconds,  # Fix 2: occupancy-based
                "waiting_time_seconds": waiting_time,
                "travel_time_seconds": rv.outbound_transit_seconds,   # Fix 1: gate→lot BPR only
                "end_to_end_time_seconds": (rv.completion_tick - rv.arrival_engine_tick) * dt if rv.completion_tick else None,
                "travel_distance_meters": rv.outbound_distance_meters + rv.inbound_distance_meters,
                "assigned_lot_id": rv.assigned_lot_id,
                "final_state": canonical_state,
                "internal_state": rv.state,
                "complied": rv.vehicle.complies_with_strategy,
                "vehicle_type": rv.vehicle.vehicle_type,
                "reassigned_count": rv.reassigned_count,
                # Tick fields for verbose trace reconstruction
                "queue_enter_tick": _m(rv.queue_enter_tick),
                "gate_admitted_tick": _m(rv.gate_admitted_tick),
                "search_start_tick": _m(rv.search_start_tick),
                "lot_arrival_tick": _m(rv.lot_arrival_tick),
                "search_end_tick": _m(rv.search_end_tick),
                "completion_tick": _m(rv.completion_tick),
                "state_trace": trace,
            })

        completed_at = datetime.now(timezone.utc).isoformat()
        summary_metrics = {
            "total_vehicles": len(vehicle_metrics),
            "completed_vehicles": sum(1 for v in vehicle_metrics if v["final_state"] == "completed"),
            "parked_vehicles": sum(1 for v in vehicle_metrics if v["final_state"] == "parked"),
            "failed_vehicles": len(overflow_events),
            "peak_occupancy_by_lot": {
                lot_id: max((ts.get(f"parking_occupancy_{lot_id}", 0) for ts in timesteps_metrics), default=0)
                for lot_id in parking_lots
            },
        }
        conn.execute(
            "UPDATE simulation_runs SET completed_at=?, status='completed', metrics_json=?, overflow_events_json=? WHERE run_id=?",
            (completed_at, json.dumps(summary_metrics), json.dumps(overflow_events), run_id),
        )
        conn.commit()

        # Record metrics to disk (Phase 8)
        recorder_kwargs = {"output_root": self.runs_dir} if self.runs_dir else {}
        recorder = MetricsRecorder(**recorder_kwargs)
        try:
            recorder.record_run(
                scenario_id=scenario.scenario_id,
                strategy_name=strategy_name,
                seed=scenario.random_seed,
                vehicle_metrics=vehicle_metrics,
                timestep_metrics=timesteps_metrics,
                overflow_events=overflow_events,
                config_dict={"campus_id": scenario.campus_id},
                decision_latencies=decision_latencies,
                event_conditions=scenario.event_conditions,
            )
        except Exception as e:
            print(f"Warning: metrics recording failed: {e}")

        return SimulationResult(
            run_id=run_id, campus_id=scenario.campus_id, scenario_id=scenario.scenario_id,
            random_seed=scenario.random_seed, strategy_name=strategy_name,
            vehicles=vehicle_metrics, timesteps=timesteps_metrics, overflow_events=overflow_events,
            infeasibility_rejections=infeasibility_rejections, adapter_fallbacks=adapter_fallbacks,
            decision_latencies=decision_latencies, time_step_sec=dt,
            config_hash=_config_hash, git_sha=_git_sha,
            runtime_sec=round(_time.monotonic() - _run_start, 3),
        )

    @staticmethod
    def _generate_arrivals(scenario: ScenarioConfig, rng: random.Random, open_gate_ids, destination_ids) -> list:
        """Deterministic given rng: arrival minutes are weighted by the
        scenario's arrival_rate_profile shape, event-aware demand multiplier,
        entry gate and destination are chosen uniformly via the same seeded rng.

        Event-aware demand: if event_conditions exists, applies its demand_multiplier
        to the arrival rate profile during the event window."""
        ticks = list(range(scenario.duration_minutes))
        warmdown_start = scenario.duration_minutes - max(0, scenario.warmdown_minutes)

        # Base arrival rate per MINUTE (scenario units); zero out arrivals during warm-down window
        weights = [
            max(0.0001, _arrival_rate_at(scenario.arrival_rate_profile, t)) if t < warmdown_start else 0.0
            for t in ticks
        ]

        # Apply event-aware demand multiplier if event is active
        if scenario.event_conditions:
            multiplier = scenario.event_conditions.get("demand_multiplier", 1.0)
            event_start = scenario.event_conditions.get("start_tick", 0)
            event_duration = scenario.event_conditions.get("duration_ticks", 0)
            event_end = event_start + event_duration
            for t in ticks:
                if event_start <= t < event_end:
                    weights[t] *= multiplier

        vehicles = []
        if not open_gate_ids or scenario.vehicle_count == 0:
            return vehicles

        arrival_ticks = sorted(rng.choices(ticks, weights=weights, k=scenario.vehicle_count))
        for i, tick in enumerate(arrival_ticks):
            gate_id = rng.choice(sorted(open_gate_ids))
            destination_id = rng.choice(sorted(destination_ids)) if destination_ids else None
            compliance = rng.random() < scenario.event_conditions.get("compliance_rate", 0.85) if scenario.event_conditions else True
            rv = _RunningVehicle(
                vehicle=Vehicle(
                    vehicle_id=f"{scenario.scenario_id}-v{i}",
                    entry_gate=gate_id, destination_id=destination_id, arrival_tick=tick,
                    complies_with_strategy=compliance,
                )
            )
            # Dwell precedence: event window override > vehicle type > global lognormal.
            # Vehicle types (scenario.vehicle_types) draw one extra RNG value per vehicle, only when configured.
            if scenario.vehicle_types:
                tnames = sorted(scenario.vehicle_types)
                tname = rng.choices(tnames, weights=[scenario.vehicle_types[t]["share"] for t in tnames])[0]
                tspec = scenario.vehicle_types[tname]
                rv.vehicle.vehicle_type = tname
                rv.dwell_mu = math.log(tspec["dwell_median_minutes"])
                rv.dwell_sigma = tspec.get("dwell_sigma", DWELL_LOGNORMAL_SIGMA)
            ec = scenario.event_conditions or {}
            if ec.get("dwell_median_minutes") and ec.get("start_tick", 0) <= tick < ec.get("start_tick", 0) + ec.get("duration_ticks", 0):
                rv.dwell_mu = math.log(ec["dwell_median_minutes"])
                rv.dwell_sigma = ec.get("dwell_sigma", DWELL_LOGNORMAL_SIGMA)
            vehicles.append(rv)

        # Sub-minute arrival time: spread the n vehicles of a minute evenly over its ticks (deterministic, no RNG).
        tpm = 60 // scenario.time_step_sec
        by_minute = {}
        for rv in vehicles:
            by_minute.setdefault(rv.vehicle.arrival_tick, []).append(rv)
        for minute_, group in by_minute.items():
            for k, rv in enumerate(group):
                rv.arrival_engine_tick = minute_ * tpm + (k * tpm) // len(group)
        return vehicles

    @staticmethod
    def _apply_availability_overrides(graph: nx.Graph, scenario: ScenarioConfig) -> nx.Graph:
        working = graph.copy()
        overrides = scenario.availability_overrides or {}
        for gate_id in overrides.get("closed_gates", []):
            if gate_id in working:
                working.remove_node(gate_id)
        for lot_id in overrides.get("closed_parking_lots", []):
            if lot_id in working:
                working.remove_node(lot_id)
        closed_roads = set(overrides.get("closed_roads", []))
        if closed_roads:
            for u, v, d in list(working.edges(data=True)):
                if d.get("road_id") in closed_roads:
                    working.remove_edge(u, v)
        return working

    @staticmethod
    def _load_gates(campus_id, conn, overrides) -> dict:
        closed = set((overrides or {}).get("closed_gates", []))
        gates = {}
        for row in conn.execute("SELECT * FROM gates WHERE campus_id=?", (campus_id,)):
            gates[row["gate_id"]] = {
                "status": "closed" if row["gate_id"] in closed else row["status"],
                "capacity": row["capacity"],
                "queue_length": 0,
            }
        return gates

    @staticmethod
    def _load_parking_lots(campus_id, conn, overrides) -> dict:
        closed = set((overrides or {}).get("closed_parking_lots", []))
        lots = {}
        for row in conn.execute("SELECT * FROM parking_lots WHERE campus_id=?", (campus_id,)):
            lots[row["parking_lot_id"]] = {
                "status": "closed" if row["parking_lot_id"] in closed else row["status"],
                "usable_capacity": row["usable_capacity"],
                "occupied_spaces": 0,
            }
        return lots

    @staticmethod
    def _load_roads(campus_id, conn) -> dict:
        return {row["road_id"]: {"status": row["status"], "current_load": 0}
                for row in conn.execute("SELECT * FROM roads WHERE campus_id=?", (campus_id,))}

    @staticmethod
    def _load_destination_ids(campus_id, conn) -> list:
        return [row["destination_id"] for row in conn.execute("SELECT destination_id FROM destinations WHERE campus_id=? AND simulation_demand=1", (campus_id,))]

    @staticmethod
    def _route_target(destination_id, destinations, parking_lots, open_lot_ids):
        """Vehicles drive to a parking lot node, never to a pedestrian-only
        destination. This is simulation movement mechanics, not a Navigation
        feature -- no decision about WHICH lot happens here beyond picking
        a routable target; the actual assignment decision is the strategy's."""
        if destination_id in parking_lots and destination_id in open_lot_ids:
            return destination_id
        if not open_lot_ids:
            return None
        return sorted(open_lot_ids)[0]

    @staticmethod
    def _nearest_available_lot(from_node, open_lot_ids, parking_lots, graph):
        """Non-compliant driver behavior: find nearest open, non-full lot.
        Uses shortest path distance from current node."""
        if not open_lot_ids:
            return None
        candidates = []
        for lot_id in open_lot_ids:
            if lot_id not in graph:
                continue
            if parking_lots[lot_id]["occupied_spaces"] >= parking_lots[lot_id]["usable_capacity"]:
                continue
            try:
                dist = nx.shortest_path_length(graph, from_node, lot_id, weight="weight_distance_meters")
                candidates.append((lot_id, dist))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[1])[0]

    @staticmethod
    def _assign_with_adapter(strategy: AllocationStrategy, vehicle: Vehicle,
                             campus_state: CampusState, parking_lots: dict,
                             open_lot_ids: list, graph) -> tuple:
        """Adapter pattern: wrap strategy.assign() with timeout + fallback + validation.

        Returns: (AssignmentResult, fallback_reason or None)

        Fallback triggers (apply B2 Nearest-Available):
        1. Strategy raises exception
        2. Strategy exceeds time budget
        3. Strategy returns infeasible result (lot closed/full)
        """
        fallback_reason = None
        result = None

        try:
            assign_start = datetime.now(timezone.utc)
            result = strategy.assign(vehicle, campus_state)
            assign_time_ms = (datetime.now(timezone.utc) - assign_start).total_seconds() * 1000

            # Check timeout
            if assign_time_ms > STRATEGY_TIMEOUT_MS:
                fallback_reason = f"timeout_{assign_time_ms:.0f}ms"
                result = None
            # Check feasibility
            elif result and result.parking_lot_id:
                lot = parking_lots.get(result.parking_lot_id)
                if not lot or lot["status"] != "open" or lot["occupied_spaces"] >= lot["usable_capacity"]:
                    fallback_reason = f"infeasible_{result.parking_lot_id}"
                    result = None

        except Exception as e:
            fallback_reason = f"exception_{type(e).__name__}"
            result = None

        # Fallback to B2 (Nearest-Available) if any trigger fired
        if fallback_reason:
            try:
                b2_strategy = NearestAvailableStrategy()
                result = b2_strategy.assign(vehicle, campus_state)
            except Exception:
                result = None

        return result, fallback_reason
