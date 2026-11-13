"""
Part 4's seam: the AllocationStrategy interface. The simulation engine
never decides which lot a vehicle goes to -- it only calls whatever
strategy it's handed, exactly once per vehicle at the parking_search step,
and then enforces the physical constraints (closed/full lot, closed road,
gate throughput) regardless of what the strategy returned.

Member 3 implements First Available, Nearest Available, and the final
optimizer against this exact interface. FixedLotStrategy below exists only
to prove, in this module's own tests, that the interface is actually being
called and not bypassed -- it is not a real allocation strategy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Vehicle:
    vehicle_id: str
    entry_gate: str
    destination_id: Optional[str]
    arrival_tick: int
    complies_with_strategy: bool = True  # False = ignores strategy, goes to nearest lot
    vehicle_type: str = "general"        # scenario.vehicle_types key (drives dwell); "general" when none configured


@dataclass
class CampusState:
    """Read-only view handed to a strategy: current parking/gate/road
    state plus the campus graph, for the strategy to reason over. The
    strategy must not mutate this -- only the engine writes state."""
    campus_id: str
    graph: object  # networkx.Graph
    parking_lots: dict   # lot_id -> {"status", "usable_capacity", "occupied_spaces"}
    gates: dict           # gate_id -> {"status", "capacity", "queue_length"}
    roads: dict           # road_id -> {"status", "current_load"}


@dataclass
class AssignmentResult:
    parking_lot_id: Optional[str]
    gate_id: Optional[str] = None
    route: list = field(default_factory=list)


class AllocationStrategy(ABC):
    name: str = ""   # spec-required label; subclasses override via `label` class attr

    @abstractmethod
    def assign(self, vehicle: Vehicle, campus_state: CampusState) -> AssignmentResult:
        """Given a vehicle and the current (or predicted) campus state,
        return which parking lot (and optionally gate/route) this vehicle
        should use. Implemented by teammates, NOT by this module."""

    def update_policy(self, state_snapshot: dict, forecast: dict = None) -> None:
        """Called every 5 minutes (decision cycle). Strategy can update its
        internal policy/parameters based on current state and Member 2's forecast.

        Args:
            state_snapshot: full campus state snapshot (JSON-serializable)
            forecast: predicted state 15/30 min ahead (or None if unavailable)

        Default: no-op. B1/B2 don't use forecasts; Member 3's optimizer overrides.
        """
        pass


class FixedLotStrategy(AllocationStrategy):
    """Test-only strategy: always assigns the configured lot, regardless
    of state. Used to prove the engine actually calls this interface."""

    def __init__(self, lot_id: str):
        self.lot_id = lot_id

    def assign(self, vehicle: Vehicle, campus_state: CampusState) -> AssignmentResult:
        return AssignmentResult(parking_lot_id=self.lot_id, gate_id=vehicle.entry_gate)


class FirstAvailableStrategy(AllocationStrategy):
    """B1 Baseline: assign first open, non-full lot in config (insertion) order.

    Uses dict insertion order, which equals DB/YAML config order (academic →
    hostel → admin → sports → overflow). This matches the campus designer's
    intended priority, not alphabetical order.
    Deterministic: always picks the same lot for identical state.
    Simple: no optimization, no forecasting.
    """

    label = "B1-FirstAvailable"

    def assign(self, vehicle: Vehicle, campus_state: CampusState) -> AssignmentResult:
        for lot_id in campus_state.parking_lots.keys():  # Fix 5: config order, not sorted()
            lot = campus_state.parking_lots[lot_id]
            if (lot["status"] == "open" and
                lot["occupied_spaces"] < lot["usable_capacity"]):
                return AssignmentResult(parking_lot_id=lot_id)
        return AssignmentResult(parking_lot_id=None)


class NearestAvailableStrategy(AllocationStrategy):
    """B2 Baseline: assign nearest open, non-full lot by shortest path distance.

    Greedy: minimize immediate travel time.
    Deterministic: breaks ties by lot_id order.
    """

    label = "B2-NearestAvailable"

    def assign(self, vehicle: Vehicle, campus_state: CampusState) -> AssignmentResult:
        import networkx as nx

        candidates = []
        for lot_id in campus_state.parking_lots.keys():
            lot = campus_state.parking_lots[lot_id]
            if (lot["status"] == "open" and
                lot["occupied_spaces"] < lot["usable_capacity"]):
                try:
                    dist = nx.shortest_path_length(
                        campus_state.graph,
                        vehicle.entry_gate,
                        lot_id,
                        weight="weight_distance_meters"
                    )
                    candidates.append((dist, lot_id))
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue

        if not candidates:
            return AssignmentResult(parking_lot_id=None)

        candidates.sort()
        return AssignmentResult(parking_lot_id=candidates[0][1])


class Member3Strategy(AllocationStrategy):
    """Placeholder for Member 3's optimizer strategy.

    Interface contract: Member 3 replaces this body with their optimizer.
    Until then it delegates to NearestAvailable so the 3-strategy comparison
    table can run. The label is intentionally distinct so metrics show it.

    Member 3: implement assign() here (and optionally update_policy() for
    the 5-minute forecast update cycle). Do NOT rename the class or label.
    """

    label = "M3-Optimizer"

    def __init__(self):
        self._fallback = NearestAvailableStrategy()

    def assign(self, vehicle: Vehicle, campus_state: CampusState) -> AssignmentResult:
        # TODO: replace with Member 3's optimizer logic
        return self._fallback.assign(vehicle, campus_state)

    def update_policy(self, state_snapshot: dict, forecast: dict = None) -> None:
        # TODO: replace with Member 3's policy update (forecast-driven)
        pass
