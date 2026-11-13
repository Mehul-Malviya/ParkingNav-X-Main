"""
Part 2: Digital Twin State Manager — CampusState with full event processing,
invariant checks, and deep-copy clone support.

This is the authoritative state manager for the ParkingNav-X digital twin.
All state changes flow through apply_event() so every transition is logged.
"""

import copy
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


# ── Vehicle state machine ─────────────────────────────────────────────────────

class VehicleStateEnum(str, Enum):
    SCHEDULED = "SCHEDULED"
    QUEUED_AT_GATE = "QUEUED_AT_GATE"
    ENTERING = "ENTERING"
    DRIVING = "DRIVING"
    SEARCHING = "SEARCHING"
    PARKED = "PARKED"
    DEPARTING = "DEPARTING"
    EXITED = "EXITED"
    REJECTED_OVERFLOW = "REJECTED_OVERFLOW"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ParkingLotState:
    id: str
    capacity: int
    occupied: int
    reserved_free: int
    status: str  # open / closed / full
    arrivals_last_15m: int = 0
    departures_last_15m: int = 0
    predicted_occupancy_15m: Optional[float] = None
    predicted_occupancy_30m: Optional[float] = None

    @property
    def available(self) -> int:
        return self.capacity - self.occupied

    @property
    def occupancy_pct(self) -> float:
        return (self.occupied / self.capacity * 100.0) if self.capacity > 0 else 0.0


@dataclass
class GateState:
    id: str
    status: str  # open / closed
    queue_length: int
    service_rate_vph: float
    throughput_last_15m: int = 0
    avg_wait_sec_last_15m: float = 0.0


@dataclass
class RoadState:
    id: str
    status: str  # open / closed
    vehicle_count: int
    capacity_vph: int
    travel_time_sec: float

    @property
    def congestion_ratio(self) -> float:
        return (self.vehicle_count / self.capacity_vph) if self.capacity_vph > 0 else 0.0

    @property
    def congestion_level(self) -> str:
        r = self.congestion_ratio
        if r < 0.5:
            return "low"
        elif r < 0.8:
            return "med"
        return "high"


@dataclass
class VehicleState:
    id: str
    type: str  # car / bike / staff / visitor
    arrival_time: Any  # tick or datetime or float
    entry_gate: str
    destination_zone: str
    assigned_lot: Optional[str]
    route: List[str]
    state: VehicleStateEnum
    timestamps: Dict[str, Any]
    search_time: float = 0.0
    wait_time: float = 0.0
    travel_time: float = 0.0
    distance_m: float = 0.0
    reassigned_count: int = 0


@dataclass
class EventState:
    id: str
    type: str
    start: Any  # datetime or str
    duration_min: float
    demand_multiplier: float
    affected_zones: List[str]


# ── CampusState ───────────────────────────────────────────────────────────────

@dataclass
class CampusState:
    """
    Full campus state at one point in time.

    All state changes must go through apply_event() so transitions are logged
    in event_log. Use clone() for independent what-if copies.
    """
    timestamp: Any  # datetime or str
    scenario_id: str
    seed: int

    lots: Dict[str, ParkingLotState] = field(default_factory=dict)
    gates: Dict[str, GateState] = field(default_factory=dict)
    roads: Dict[str, RoadState] = field(default_factory=dict)
    vehicles: Dict[str, VehicleState] = field(default_factory=dict)
    events: Dict[str, EventState] = field(default_factory=dict)

    # Internal log — every apply_event() call appends here
    event_log: List[Dict] = field(default_factory=list)

    # ── Global KPIs ───────────────────────────────────────────────────────────

    @property
    def total_occupancy_pct(self) -> float:
        total_cap = sum(lot.capacity for lot in self.lots.values())
        total_occ = sum(lot.occupied for lot in self.lots.values())
        return (total_occ / total_cap * 100.0) if total_cap > 0 else 0.0

    @property
    def total_queue(self) -> int:
        return sum(g.queue_length for g in self.gates.values())

    @property
    def overflow_count(self) -> int:
        return sum(1 for lot in self.lots.values() if lot.occupied > lot.capacity)

    # ── snapshot() ────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a deep-copied JSON-serialisable dict of the full campus state."""
        def _encode(obj):
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, datetime):
                return obj.isoformat()
            return str(obj)

        def _lot(lot: ParkingLotState, travel_time_sec: float = 0.0) -> dict:
            return {
                "id": lot.id,
                "capacity": lot.capacity,
                "occupied": lot.occupied,
                "available": lot.available,
                "reserved_free": lot.reserved_free,
                "occupancy_pct": lot.occupancy_pct,
                "status": lot.status,
                "arrivals_last_15m": lot.arrivals_last_15m,
                "departures_last_15m": lot.departures_last_15m,
                "predicted_occupancy_15m": lot.predicted_occupancy_15m,
                "predicted_occupancy_30m": lot.predicted_occupancy_30m,
                "travel_time_from_gate_sec": travel_time_sec,
            }

        def _gate(gate: GateState) -> dict:
            return {
                "id": gate.id,
                "status": gate.status,
                "queue_length": gate.queue_length,
                "service_rate_vph": gate.service_rate_vph,
                "throughput_last_15m": gate.throughput_last_15m,
                "avg_wait_sec": gate.avg_wait_sec_last_15m,
                "avg_wait_sec_last_15m": gate.avg_wait_sec_last_15m,
            }

        def _road(road: RoadState) -> dict:
            return {
                "id": road.id,
                "status": road.status,
                "vehicle_count": road.vehicle_count,
                "capacity_vph": road.capacity_vph,
                "travel_time_sec": road.travel_time_sec,
                "congestion_ratio": road.congestion_ratio,
                "congestion_level": road.congestion_level,
            }

        def _vehicle(v: VehicleState) -> dict:
            return {
                "id": v.id,
                "type": v.type,
                "arrival_time": _encode(v.arrival_time),
                "entry_gate": v.entry_gate,
                "destination_zone": v.destination_zone,
                "assigned_lot": v.assigned_lot,
                "route": list(v.route),
                "state": v.state.value if isinstance(v.state, Enum) else v.state,
                "timestamps": {k: _encode(val) for k, val in v.timestamps.items()},
                "search_time": v.search_time,
                "wait_time": v.wait_time,
                "travel_time": v.travel_time,
                "distance_m": v.distance_m,
                "reassigned_count": v.reassigned_count,
            }

        def _event(e: EventState) -> dict:
            return {
                "id": e.id,
                "type": e.type,
                "start": _encode(e.start),
                "duration_min": e.duration_min,
                "demand_multiplier": e.demand_multiplier,
                "affected_zones": list(e.affected_zones),
            }

        _pending = sum(
            1 for v in self.vehicles.values()
            if getattr(v, "state", None) not in (None, VehicleStateEnum.EXITED, VehicleStateEnum.PARKED)
        )
        _lots_list = [_lot(v) for v in self.lots.values()]
        _gates_list = [_gate(v) for v in self.gates.values()]

        return {
            "timestamp": _encode(self.timestamp),
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            # dict form kept for internal use (keyed access); lists form for Member 3 contract
            "lots": {k: _lot(v) for k, v in self.lots.items()},
            "gates": {k: _gate(v) for k, v in self.gates.items()},
            "roads": {k: _road(v) for k, v in self.roads.items()},
            "vehicles": {k: _vehicle(v) for k, v in self.vehicles.items()},
            "events": {k: _event(v) for k, v in self.events.items()},
            "event_log": copy.deepcopy(self.event_log),
            "lots_list": _lots_list,
            "gates_list": _gates_list,
            "pending_vehicle": _pending,
            "global": {
                "total_occupancy_pct": self.total_occupancy_pct,
                "total_queue": self.total_queue,
                "overflow_count": self.overflow_count,
                "pending_vehicle": _pending,
            },
            "total_occupancy_pct": self.total_occupancy_pct,
            "total_queue": self.total_queue,
            "overflow_count": self.overflow_count,
        }

    # ── apply_event() ─────────────────────────────────────────────────────────

    def apply_event(self, e: dict) -> None:
        """
        Apply a state-change event and log every transition.

        Supported event types:
          vehicle_arrived, gate_served, entered_road, reached_lot,
          parked, departed, lot_closed, gate_closed, road_closed
        """
        etype = e.get("type")
        tick = e.get("tick", 0)

        if etype == "vehicle_arrived":
            vid = e["vehicle_id"]
            vehicle = VehicleState(
                id=vid,
                type=e.get("vehicle_type", "car"),
                arrival_time=e.get("arrival_time", tick),
                entry_gate=e.get("entry_gate", ""),
                destination_zone=e.get("destination_zone", ""),
                assigned_lot=e.get("assigned_lot"),
                route=e.get("route", []),
                state=VehicleStateEnum.SCHEDULED,
                timestamps={VehicleStateEnum.SCHEDULED.value: tick},
            )
            self.vehicles[vid] = vehicle
            self._log(tick, etype, vid, None, VehicleStateEnum.SCHEDULED.value)

        elif etype == "gate_served":
            vid = e["vehicle_id"]
            v = self.vehicles.get(vid)
            if v:
                old_state = v.state.value
                v.state = VehicleStateEnum.ENTERING
                v.timestamps[VehicleStateEnum.ENTERING.value] = tick
                self._log(tick, etype, vid, old_state, v.state.value)
            gate_id = e.get("gate_id")
            if gate_id and gate_id in self.gates:
                gate = self.gates[gate_id]
                old_q = gate.queue_length
                gate.queue_length = max(0, gate.queue_length - 1)
                gate.throughput_last_15m += 1
                self._log(tick, etype, gate_id,
                          {"queue_length": old_q, "throughput_last_15m": gate.throughput_last_15m - 1},
                          {"queue_length": gate.queue_length, "throughput_last_15m": gate.throughput_last_15m})

        elif etype == "entered_road":
            vid = e["vehicle_id"]
            v = self.vehicles.get(vid)
            if v:
                old_state = v.state.value
                v.state = VehicleStateEnum.DRIVING
                v.timestamps[VehicleStateEnum.DRIVING.value] = tick
                self._log(tick, etype, vid, old_state, v.state.value)
            road_id = e.get("road_id")
            if road_id and road_id in self.roads:
                road = self.roads[road_id]
                old_vc = road.vehicle_count
                road.vehicle_count += 1
                self._log(tick, etype, road_id,
                          {"vehicle_count": old_vc},
                          {"vehicle_count": road.vehicle_count})

        elif etype == "reached_lot":
            vid = e["vehicle_id"]
            v = self.vehicles.get(vid)
            if v:
                old_state = v.state.value
                v.state = VehicleStateEnum.SEARCHING
                v.timestamps[VehicleStateEnum.SEARCHING.value] = tick
                self._log(tick, etype, vid, old_state, v.state.value)
            road_id = e.get("road_id")
            if road_id and road_id in self.roads:
                road = self.roads[road_id]
                old_vc = road.vehicle_count
                road.vehicle_count = max(0, road.vehicle_count - 1)
                self._log(tick, etype, road_id,
                          {"vehicle_count": old_vc},
                          {"vehicle_count": road.vehicle_count})

        elif etype == "parked":
            vid = e["vehicle_id"]
            v = self.vehicles.get(vid)
            if v:
                old_state = v.state.value
                v.state = VehicleStateEnum.PARKED
                v.timestamps[VehicleStateEnum.PARKED.value] = tick
                if e.get("assigned_lot"):
                    v.assigned_lot = e["assigned_lot"]
                self._log(tick, etype, vid, old_state, v.state.value)
            lot_id = e.get("lot_id") or (v.assigned_lot if v else None)
            if lot_id and lot_id in self.lots:
                lot = self.lots[lot_id]
                old_occ = lot.occupied
                lot.occupied += 1
                lot.arrivals_last_15m += 1
                if lot.occupied >= lot.capacity:
                    lot.status = "full"
                self._log(tick, etype, lot_id,
                          {"occupied": old_occ, "arrivals_last_15m": lot.arrivals_last_15m - 1},
                          {"occupied": lot.occupied, "arrivals_last_15m": lot.arrivals_last_15m})

        elif etype == "departed":
            vid = e["vehicle_id"]
            v = self.vehicles.get(vid)
            if v:
                # PARKED → DEPARTING → EXITED
                old_state = v.state.value
                v.state = VehicleStateEnum.DEPARTING
                v.timestamps[VehicleStateEnum.DEPARTING.value] = tick
                self._log(tick, etype, vid, old_state, VehicleStateEnum.DEPARTING.value)
                v.state = VehicleStateEnum.EXITED
                v.timestamps[VehicleStateEnum.EXITED.value] = tick
                self._log(tick, etype, vid, VehicleStateEnum.DEPARTING.value, v.state.value)
            lot_id = e.get("lot_id") or (v.assigned_lot if v else None)
            if lot_id and lot_id in self.lots:
                lot = self.lots[lot_id]
                old_occ = lot.occupied
                lot.occupied = max(0, lot.occupied - 1)
                lot.departures_last_15m += 1
                if lot.status == "full" and lot.occupied < lot.capacity:
                    lot.status = "open"
                self._log(tick, etype, lot_id,
                          {"occupied": old_occ, "departures_last_15m": lot.departures_last_15m - 1},
                          {"occupied": lot.occupied, "departures_last_15m": lot.departures_last_15m})

        elif etype == "lot_closed":
            lot_id = e["lot_id"]
            if lot_id in self.lots:
                lot = self.lots[lot_id]
                old_status = lot.status
                lot.status = "closed"
                self._log(tick, etype, lot_id, {"status": old_status}, {"status": lot.status})

        elif etype == "gate_closed":
            gate_id = e["gate_id"]
            if gate_id in self.gates:
                gate = self.gates[gate_id]
                old_status = gate.status
                gate.status = "closed"
                self._log(tick, etype, gate_id, {"status": old_status}, {"status": gate.status})

        elif etype == "road_closed":
            road_id = e["road_id"]
            if road_id in self.roads:
                road = self.roads[road_id]
                old_status = road.status
                road.status = "closed"
                self._log(tick, etype, road_id, {"status": old_status}, {"status": road.status})

    def _log(self, tick: Any, event_type: str, entity: str, old: Any, new: Any) -> None:
        self.event_log.append({
            "tick": tick,
            "event_type": event_type,
            "entity": entity,
            "old": old,
            "new": new,
        })

    # ── invariants() ─────────────────────────────────────────────────────────

    def invariants(self) -> None:
        """
        Check all state invariants. Raises AssertionError on first violation.
        """
        # Lot invariants
        for lot_id, lot in self.lots.items():
            assert lot.occupied >= 0, (
                f"Lot '{lot_id}': occupied ({lot.occupied}) < 0"
            )
            assert lot.occupied <= lot.capacity, (
                f"Lot '{lot_id}': occupied ({lot.occupied}) > capacity ({lot.capacity})"
            )
            assert lot.available == lot.capacity - lot.occupied, (
                f"Lot '{lot_id}': available ({lot.available}) != capacity - occupied "
                f"({lot.capacity - lot.occupied})"
            )

        # Gate invariants
        for gate_id, gate in self.gates.items():
            assert gate.queue_length >= 0, (
                f"Gate '{gate_id}': queue_length ({gate.queue_length}) < 0"
            )

        # Vehicle ID uniqueness
        seen_ids = set()
        for vid in self.vehicles:
            assert vid not in seen_ids, f"Vehicle '{vid}' appears more than once"
            seen_ids.add(vid)

        # No vehicle in SCHEDULED state is assigned to a closed lot
        for vid, v in self.vehicles.items():
            if v.state == VehicleStateEnum.SCHEDULED and v.assigned_lot:
                lot = self.lots.get(v.assigned_lot)
                if lot:
                    assert lot.status != "closed", (
                        f"Vehicle '{vid}' is SCHEDULED for closed lot '{v.assigned_lot}'"
                    )

        # Conservation: PARKED vehicle count must equal sum of lot occupied
        parked_count = sum(
            1 for v in self.vehicles.values()
            if v.state == VehicleStateEnum.PARKED
        )
        total_occupied = sum(lot.occupied for lot in self.lots.values())
        assert parked_count == total_occupied, (
            f"Conservation violation: PARKED vehicles ({parked_count}) != "
            f"sum of lot.occupied ({total_occupied})"
        )

        # All vehicle states must be valid VehicleStateEnum values
        valid_states = set(VehicleStateEnum)
        for vid, v in self.vehicles.items():
            assert v.state in valid_states, (
                f"Vehicle '{vid}' has invalid state '{v.state}'"
            )

    # ── clone() ───────────────────────────────────────────────────────────────

    def clone(self) -> "CampusState":
        """Return a fully independent deep copy."""
        return copy.deepcopy(self)

    # ── what_if() ─────────────────────────────────────────────────────────────

    def what_if(self, strategy=None, horizon_min: int = 30) -> "CampusState":
        """Return a projected CampusState after horizon_min minutes.

        Projects lot occupancy using the last-15-min net arrival/departure rate.
        Gates: queue length projected via (arrivals - service) * horizon.
        The strategy argument is accepted for API compatibility but not used in
        the linear projection (full strategy replay would require the engine).
        """
        projected = self.clone()
        for lot in projected.lots.values():
            arrival_rate = lot.arrivals_last_15m / 15.0   # veh/min
            depart_rate = lot.departures_last_15m / 15.0
            net = arrival_rate - depart_rate
            lot.occupied = max(0, min(lot.capacity, round(lot.occupied + net * horizon_min)))
        for gate in projected.gates.values():
            # Simple queue projection: arrivals in window minus service capacity
            service_rate = gate.service_rate_vph / 60.0   # veh/min
            net_arrivals = max(0.0, (gate.throughput_last_15m / 15.0) - service_rate)
            gate.queue_length = max(0, round(gate.queue_length + net_arrivals * horizon_min))
        return projected
