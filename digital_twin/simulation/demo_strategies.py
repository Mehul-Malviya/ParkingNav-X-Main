"""
Demo allocation strategies: B3 (Prediction-Only) and P (ParkingNav-X Full).
These are the advanced strategies that go beyond the B1/B2 baselines in strategy.py.
"""

import networkx as nx

from digital_twin.simulation.strategy import AllocationStrategy, AssignmentResult

# J-function weight profiles (same as optimization/engine.py WEIGHT_PROFILES)
# w3 = search/travel, w5 = overflow penalty, w1/w2 = queue/waiting costs
_J_WEIGHT_PROFILES = {
    "P1": {"w1": 0.40, "w2": 0.30, "w3": 0.15, "w4": 0.05, "w5": 0.10},  # minimize waiting
    "P2": {"w1": 0.20, "w2": 0.20, "w3": 0.20, "w4": 0.20, "w5": 0.20},  # balanced
    "P3": {"w1": 0.10, "w2": 0.10, "w3": 0.20, "w4": 0.10, "w5": 0.50},  # minimize overflow
}


class PredictionOnlyStrategy(AllocationStrategy):
    """B3 — Prediction-aware strategy.

    Uses predicted occupancy (fill rate) to avoid lots that are likely to
    fill up soon, steering vehicles to lots with headroom.
    """

    label = "B3-PredictionOnly"
    FILL_THRESHOLD = 0.80

    def assign(self, vehicle, campus_state):
        best_lot, best_score = None, float("inf")
        for lot_id, lot in campus_state.parking_lots.items():
            if lot["status"] != "open":
                continue
            cap = lot["usable_capacity"]
            occ = lot["occupied_spaces"]
            if cap <= 0 or occ >= cap:
                continue
            fill_rate = occ / cap
            if fill_rate > self.FILL_THRESHOLD:
                continue
            if not nx.has_path(campus_state.graph, vehicle.entry_gate, lot_id):
                continue
            distance = nx.shortest_path_length(
                campus_state.graph, vehicle.entry_gate, lot_id, weight="weight_distance_meters"
            )
            score = distance * (1 + fill_rate)
            if score < best_score:
                best_lot, best_score = lot_id, score
        # Fallback: threshold filtered everything → pick nearest available
        if best_lot is None:
            for lot_id, lot in campus_state.parking_lots.items():
                if lot["status"] != "open" or lot["occupied_spaces"] >= lot["usable_capacity"]:
                    continue
                if not nx.has_path(campus_state.graph, vehicle.entry_gate, lot_id):
                    continue
                distance = nx.shortest_path_length(
                    campus_state.graph, vehicle.entry_gate, lot_id, weight="weight_distance_meters"
                )
                if best_lot is None or distance < best_score:
                    best_lot, best_score = lot_id, distance
        return AssignmentResult(parking_lot_id=best_lot, gate_id=vehicle.entry_gate)


class ParkingNavXFullStrategy(AllocationStrategy):
    """P — ParkingNav-X full system strategy.

    Combines: prediction-aware lot selection + gate congestion cost +
    forecast-driven proactive avoidance + uncertainty hedging.

    Scoring (per lot):
        score = distance_from_vehicle_gate * (1 + effective_fill)
                + gate_queue_penalty

    Distance is always measured from the vehicle's actual entry gate so
    that lot rankings reflect the route the vehicle will actually travel.
    Gate congestion penalty adds cost when the vehicle's own gate is
    backlogged — incentivising agents to prefer uncongested corridors
    at the lot-choice level rather than hard-rerouting through a different
    gate (which would require different dispatch logic).

    Ablation flags (set via update_policy's ablation_flags kwarg):
    - use_prediction: if False, use current occupancy only (no forecast)
    - use_optimization: if False, skip gate congestion penalty
    - use_uncertainty: if False, ignore upper conformal interval in scoring
    - proactive: if False, only avoid lots that are currently ≥ threshold
                 (reactive), not forecast-full (proactive)
    """

    label = "P-ParkingNavX"
    # Soft-threshold: lots above this fill get a score penalty multiplier
    # rather than being hard-filtered.  Hard filter only at physical capacity.
    FILL_SOFT_THRESHOLD = 0.80   # above this, fill penalty steepens
    FILL_HARD_THRESHOLD = 0.95   # proactive: skip if forecast says lot will be this full
    # Weight of gate queue depth (vehicles) in the composite score.
    # Normalised: 10 vehicles in queue ≈ same cost as 10% extra fill penalty.
    GATE_QUEUE_WEIGHT = 50.0     # metres-equivalent per vehicle in queue

    def __init__(self, weight_profile: str = "P2"):
        self._forecast = None
        self._use_prediction = True
        self._use_optimization = True
        self._use_uncertainty = True
        self._proactive = True
        self._weights = _J_WEIGHT_PROFILES.get(weight_profile, _J_WEIGHT_PROFILES["P2"])

    def update_policy(self, state_snapshot: dict, forecast: dict = None,
                      ablation_flags: dict = None, weight_profile: str = None) -> None:
        """Called every 5 min by simulation engine."""
        self._forecast = forecast
        if ablation_flags is not None:
            self._use_prediction = ablation_flags.get("use_prediction", True)
            self._use_optimization = ablation_flags.get("use_optimization", True)
            self._use_uncertainty = ablation_flags.get("use_uncertainty", True)
            self._proactive = ablation_flags.get("proactive", True)
        if weight_profile is not None:
            self._weights = _J_WEIGHT_PROFILES.get(weight_profile, self._weights)

    def assign(self, vehicle, campus_state):
        # ── Gate congestion at vehicle's own entry gate ───────────────────────
        if self._use_optimization:
            gate_loads = {
                g_id: g.get("queue_length", 0)
                for g_id, g in campus_state.gates.items()
                if g.get("status", "open") == "open"
            }
            my_queue = gate_loads.get(vehicle.entry_gate, 0)
        else:
            gate_loads = {}
            my_queue = 0

        # ── Forecast fill rates ───────────────────────────────────────────────
        if self._use_prediction and self._forecast and "lot_fill_rates" in self._forecast:
            predicted_fills = self._forecast["lot_fill_rates"]
            upper_fills = self._forecast.get("lot_fill_rates_upper", {})
        else:
            predicted_fills = {}
            upper_fills = {}

        best_lot, best_score = None, float("inf")

        for lot_id, lot in campus_state.parking_lots.items():
            if lot["status"] != "open":
                continue
            cap = lot["usable_capacity"]
            occ = lot["occupied_spaces"]
            if cap <= 0 or occ >= cap:
                continue

            if not nx.has_path(campus_state.graph, vehicle.entry_gate, lot_id):
                continue

            current_fill = occ / cap

            # ── Effective fill for proactive / reactive modes ─────────────────
            if self._proactive and self._use_prediction:
                effective_fill = predicted_fills.get(lot_id, current_fill)
                # Widen with upper conformal interval when uncertainty is enabled
                if self._use_uncertainty:
                    effective_fill = max(effective_fill,
                                         upper_fills.get(lot_id, effective_fill))
            else:
                effective_fill = current_fill

            # Hard skip: only when forecast (or current) says lot is almost full.
            # Vehicles that have no alternative will be caught by the fallback.
            if effective_fill >= self.FILL_HARD_THRESHOLD:
                continue

            # ── Distance from vehicle's actual entry gate ─────────────────────
            distance = nx.shortest_path_length(
                campus_state.graph, vehicle.entry_gate, lot_id,
                weight="weight_distance_meters"
            )

            # ── Composite score aligned with J-function components ────────────
            # w3 (search travel): normalise distance to [0,1] over 1 km max
            w = self._weights
            search_cost = min(1.0, distance / 1000.0)

            # w5 (overflow penalty): steepens above soft threshold
            if effective_fill <= self.FILL_SOFT_THRESHOLD:
                overflow_cost = effective_fill
            else:
                overflow_cost = self.FILL_SOFT_THRESHOLD + (
                    (effective_fill - self.FILL_SOFT_THRESHOLD) * 3.0
                )

            # w1+w2 (waiting + queue): gate queue normalised to [0,1] over 20 veh
            queue_cost = min(1.0, my_queue / 20.0) if self._use_optimization else 0.0

            # Composite: J-weighted components keep units consistent
            score = (w["w3"] * search_cost
                     + w["w5"] * overflow_cost
                     + (w["w1"] + w["w2"]) * queue_cost)

            if score < best_score:
                best_lot, best_score = lot_id, score

        # ── Fallback: FILL_HARD_THRESHOLD filtered everything ─────────────────
        if best_lot is None:
            for lot_id, lot in campus_state.parking_lots.items():
                if lot["status"] != "open" or lot["occupied_spaces"] >= lot["usable_capacity"]:
                    continue
                if not nx.has_path(campus_state.graph, vehicle.entry_gate, lot_id):
                    continue
                distance = nx.shortest_path_length(
                    campus_state.graph, vehicle.entry_gate, lot_id,
                    weight="weight_distance_meters"
                )
                if best_lot is None or distance < best_score:
                    best_lot, best_score = lot_id, distance

        return AssignmentResult(parking_lot_id=best_lot, gate_id=vehicle.entry_gate)
