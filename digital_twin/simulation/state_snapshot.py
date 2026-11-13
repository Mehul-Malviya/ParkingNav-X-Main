"""
StateSnapshot — Campus state export for Member 3 (Optimizer)

Provides a JSON-serializable snapshot of campus state at any simulation tick,
with fork() capability for look-ahead simulation by Member 3's optimizer.

Spec aliases (Phase 1.2):
  ParkingLotState = LotState
  CampusState     = StateSnapshot
  clone()         = fork()
  snapshot()      = to_dict()
Old names (fork, to_dict, LotState, etc.) are kept for backward compatibility.
"""

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, List, Optional


class VehicleStateEnum(str, Enum):
    """Phase 1.2 spec vehicle state machine."""
    SCHEDULED = "SCHEDULED"
    QUEUED_AT_GATE = "QUEUED_AT_GATE"
    ENTERING = "ENTERING"
    DRIVING = "DRIVING"
    SEARCHING = "SEARCHING"
    PARKED = "PARKED"
    DEPARTING = "DEPARTING"
    EXITED = "EXITED"
    REJECTED_OVERFLOW = "REJECTED_OVERFLOW"


@dataclass
class VehicleState:
    """Per-vehicle state (Phase 1.2 spec)."""
    id: str
    vehicle_type: str
    arrival_time: int           # tick
    entry_gate: str
    destination_zone: str
    assigned_lot: Optional[str]
    route: List[str]
    state: VehicleStateEnum
    # timestamps per state transition
    timestamps: Dict[str, int]
    search_time: float          # minutes
    wait_time: float            # minutes
    travel_time: float          # minutes
    distance_m: float
    reassigned_count: int


@dataclass
class LotState:
    """Parking lot state."""
    id: str
    capacity: int
    occupied: int
    available: int
    reserved_free: int
    status: str  # open, closed, full
    inflow_5m: int
    outflow_5m: int
    # Phase 1.2 additions
    arrivals_last_15m: int = 0
    departures_last_15m: int = 0
    predicted_occupancy_15m: Optional[float] = None
    predicted_occupancy_30m: Optional[float] = None

    @property
    def occupancy_ratio(self) -> float:
        return self.occupied / self.capacity if self.capacity > 0 else 0.0

    @property
    def occupancy_pct(self) -> float:
        """Spec alias for occupancy_ratio (as percentage 0-100)."""
        return self.occupancy_ratio * 100.0


@dataclass
class GateState:
    """Entry gate state."""
    id: str
    queue_length: int
    service_rate_veh_per_min: float
    status: str  # open, closed
    throughput_last_5min: int
    # Phase 1.2 additions
    throughput_last_15m: int = 0
    avg_wait_sec_last_15m: float = 0.0

    @property
    def service_rate_vph(self) -> float:
        """Spec alias: vehicles per hour."""
        return self.service_rate_veh_per_min * 60.0


@dataclass
class RoadState:
    """Road segment state."""
    id: str
    travel_time_sec: float
    congestion_ratio: float
    status: str  # open, closed, blocked
    current_load: int
    capacity: int
    # Phase 1.2 additions
    congestion_level: str = "low"   # low / med / high

    @property
    def vehicle_count(self) -> int:
        """Spec alias for current_load."""
        return self.current_load

    @property
    def capacity_vph(self) -> int:
        """Spec alias for capacity."""
        return self.capacity


@dataclass
class EventState:
    """Active event (demand multiplier)."""
    event_id: str
    start_tick: int
    duration_ticks: int
    demand_multiplier: float
    affected_zones: List[str]
    minutes_remaining: int


@dataclass
class StateSnapshot:
    """
    Real-time campus state snapshot for Member 3's optimizer.

    Immutable (for safety); fork() creates independent copy for what-if simulation.
    Phase 1.2: also accessible as CampusState; adds global KPIs, apply_event(),
    invariants(), and event log.
    """
    sim_time: int  # current tick (minutes)
    sim_time_iso: str  # ISO 8601 timestamp

    lots: List[LotState]
    gates: List[GateState]
    roads: List[RoadState]

    pending_arrivals_by_gate: Dict[str, int]
    active_events: List[EventState]
    active_disruptions: List[Dict]

    travel_time_matrix: Dict[str, Dict[str, float]]  # [gate][lot] -> seconds
    walk_time: Dict[str, Dict[str, float]]  # [zone][lot] -> seconds

    forecast: Optional[Dict] = None  # From Member 2 (occ_t+15, occ_t+30, confidence)

    # Phase 1.2 — spec-required fields
    scenario_id: str = ""
    seed: int = 0
    vehicles: List[VehicleState] = None  # type: ignore[assignment]
    event_log: List[Dict] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.vehicles is None:
            self.vehicles = []
        if self.event_log is None:
            self.event_log = []

    # ── Global KPIs (computed) ────────────────────────────────────────────────

    @property
    def total_occupancy_pct(self) -> float:
        total_cap = sum(lot.capacity for lot in self.lots)
        total_occ = sum(lot.occupied for lot in self.lots)
        return (total_occ / total_cap * 100.0) if total_cap > 0 else 0.0

    @property
    def total_queue(self) -> int:
        return sum(g.queue_length for g in self.gates)

    @property
    def overflow_count(self) -> int:
        return sum(1 for lot in self.lots if lot.occupied > lot.capacity)

    # ── timestamp alias ───────────────────────────────────────────────────────

    @property
    def timestamp(self) -> str:
        """Spec alias for sim_time_iso."""
        return self.sim_time_iso

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "sim_time": self.sim_time,
            "sim_time_iso": self.sim_time_iso,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "lots": [asdict(lot) for lot in self.lots],
            "gates": [asdict(gate) for gate in self.gates],
            "roads": [asdict(road) for road in self.roads],
            "pending_arrivals_by_gate": self.pending_arrivals_by_gate,
            "active_events": [asdict(event) for event in self.active_events],
            "active_disruptions": self.active_disruptions,
            "travel_time_matrix": self.travel_time_matrix,
            "walk_time": self.walk_time,
            "forecast": self.forecast or {},
            "event_log": self.event_log,
            "vehicles": [{**asdict(v), "state": v.state.value} for v in self.vehicles],
            # global KPIs
            "total_occupancy_pct": self.total_occupancy_pct,
            "total_queue": self.total_queue,
            "overflow_count": self.overflow_count,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "StateSnapshot":
        """Reconstruct from dict (e.g., loaded from JSON)."""
        lots = [LotState(**lot) for lot in data.get("lots", [])]
        gates = [GateState(**gate) for gate in data.get("gates", [])]
        roads = [RoadState(**road) for road in data.get("roads", [])]
        events = [EventState(**event) for event in data.get("active_events", [])]
        vehicles = [VehicleState(**{**v, "state": VehicleStateEnum(v["state"])}) for v in data.get("vehicles", [])]

        return cls(
            sim_time=data["sim_time"],
            sim_time_iso=data["sim_time_iso"],
            lots=lots,
            gates=gates,
            roads=roads,
            pending_arrivals_by_gate=data.get("pending_arrivals_by_gate", {}),
            active_events=events,
            active_disruptions=data.get("active_disruptions", []),
            travel_time_matrix=data.get("travel_time_matrix", {}),
            walk_time=data.get("walk_time", {}),
            forecast=data.get("forecast"),
            scenario_id=data.get("scenario_id", ""),
            seed=data.get("seed", 0),
            event_log=data.get("event_log", []),
            vehicles=vehicles,
        )

    def fork(self) -> "StateSnapshot":
        """
        Create an independent deep copy for what-if simulation.

        Member 3 can use this to explore multiple candidate allocations
        without modifying the current state.
        """
        import copy
        return copy.deepcopy(self)

    def get_lot_by_id(self, lot_id: str) -> Optional[LotState]:
        """Get a lot by ID."""
        for lot in self.lots:
            if lot.id == lot_id:
                return lot
        return None

    def get_gate_by_id(self, gate_id: str) -> Optional[GateState]:
        """Get a gate by ID."""
        for gate in self.gates:
            if gate.id == gate_id:
                return gate
        return None

    def apply_event(self, event: dict) -> None:
        """
        Apply a state-change event. All state changes go through here so every
        transition is logged with (time, type, entity, old→new).

        Supported event types:
          lot_closed    — {"type": "lot_closed",   "lot_id": str}
          lot_opened    — {"type": "lot_opened",   "lot_id": str}
          lot_occupancy — {"type": "lot_occupancy","lot_id": str, "occupied": int}
          gate_closed   — {"type": "gate_closed",  "gate_id": str}
          gate_opened   — {"type": "gate_opened",  "gate_id": str}
        """
        etype = event.get("type")

        if etype in ("lot_closed", "lot_opened"):
            lot_id = event["lot_id"]
            lot = self.get_lot_by_id(lot_id)
            if lot:
                old = lot.status
                lot.status = "closed" if etype == "lot_closed" else "open"
                self._log(etype, lot_id, f"status: {old} → {lot.status}")

        elif etype == "lot_occupancy":
            lot_id = event["lot_id"]
            lot = self.get_lot_by_id(lot_id)
            if lot:
                old_occ = lot.occupied
                lot.occupied = event["occupied"]
                lot.available = max(0, lot.capacity - lot.occupied)
                if lot.occupied >= lot.capacity:
                    lot.status = "full"
                self._log(etype, lot_id, f"occupied: {old_occ} → {lot.occupied}")

        elif etype in ("gate_closed", "gate_opened"):
            gate_id = event["gate_id"]
            gate = self.get_gate_by_id(gate_id)
            if gate:
                old = gate.status
                gate.status = "closed" if etype == "gate_closed" else "open"
                self._log(etype, gate_id, f"status: {old} → {gate.status}")

    def _log(self, event_type: str, entity_id: str, change: str) -> None:
        self.event_log.append({
            "tick": self.sim_time,
            "time_iso": self.sim_time_iso,
            "type": event_type,
            "entity": entity_id,
            "change": change,
        })

    def invariants(self) -> None:
        """
        Assert all state invariants after every tick.
        Raises AssertionError naming the violating entity.
        """
        for lot in self.lots:
            assert lot.occupied >= 0, f"Lot '{lot.id}': occupied < 0"
            assert lot.occupied <= lot.capacity, (
                f"Lot '{lot.id}': occupied ({lot.occupied}) > capacity ({lot.capacity})"
            )
            assert lot.available == lot.capacity - lot.occupied, (
                f"Lot '{lot.id}': available ({lot.available}) != capacity - occupied"
            )
        for gate in self.gates:
            assert gate.queue_length >= 0, f"Gate '{gate.id}': queue_length < 0"
        # No vehicle in two states
        if self.vehicles:
            seen = {}
            for v in self.vehicles:
                assert v.id not in seen, f"Vehicle '{v.id}' appears twice in state"
                seen[v.id] = v.state

    def clone(self) -> "StateSnapshot":
        """Spec alias for fork()."""
        return self.fork()

    def snapshot(self) -> dict:
        """Spec alias for to_dict()."""
        return self.to_dict()


# ── Phase 1.2 spec aliases ───────────────────────────────────────────────────
# Old names (LotState, StateSnapshot, fork, to_dict) are kept intact.
# These aliases let spec-compliant code use the required names without
# breaking any existing Member 3 / Member 4 code.

ParkingLotState = LotState      # spec name for LotState
CampusState = StateSnapshot     # spec name for StateSnapshot
