"""
Stage 7: Multi-dimensional Risk Engine for ParkingNav-X.

Risk dimensions:
  overflow_risk         — probability a lot will overflow in horizon window
  gate_queue_risk       — gate queue length relative to capacity
  road_congestion_risk  — road load vs. free-flow capacity
  search_risk           — expected search time based on current fill
  network_risk          — aggregate network stress (composite)

Each risk score ∈ [0, 1]:  0 = no risk, 1 = critical.
"""

import math
from typing import Dict, Optional

# Single source of truth for lot/gate capacities
from digital_twin.prediction.features import LOT_CAPACITIES  # noqa: F401

# Thresholds
OVERFLOW_THRESHOLD = 0.90     # fill rate above which overflow is imminent
GATE_QUEUE_CRITICAL = 10      # queue length considered critical
ROAD_LOAD_CRITICAL = 0.80     # fraction of road capacity that is critical
SEARCH_FILL_CRITICAL = 0.95   # fill rate making search very difficult

# Hysteresis: once a risk level fires, it stays until score drops below HYSTERESIS_OFF
# Prevents alert flapping when fill oscillates around the threshold.
HYSTERESIS_ON  = 0.50   # alert fires when score exceeds this
HYSTERESIS_OFF = 0.40   # alert clears only when score drops below this

GATE_CAPACITIES = {
    "vitap-gate-main": 6,     # vehicles/minute
    "vitap-gate-visitor": 3,
}


def _sigmoid(x: float, midpoint: float = 0.0, steepness: float = 10.0) -> float:
    """Smooth sigmoid for converting raw metrics to risk scores."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 1.0 if x > midpoint else 0.0


class RiskEngine:
    """
    Computes risk scores from live DB state and optional prediction engine.
    """

    def __init__(self, conn=None, predictor=None):
        self._conn = conn
        self._predictor = predictor  # optional PredictionEngine instance
        # Hysteresis state: entity_id -> bool (True = alert currently active)
        self._alert_state: dict = {}

    def _get_lot_states(self) -> Dict[str, Dict]:
        """Query current lot occupancy from DB."""
        if self._conn is None:
            return {}
        rows = self._conn.execute(
            "SELECT parking_lot_id, usable_capacity, status FROM parking_lots WHERE campus_id='vitap'"
        ).fetchall()
        # Try to get occupancy from time_series or simulation metrics
        states = {}
        for row in rows:
            lot_id, cap, status = row[0], row[1], row[2]
            # Default: no occupancy data → assume 40% fill (conservative)
            states[lot_id] = {
                "capacity": cap or LOT_CAPACITIES.get(lot_id, 100),
                "occupied": int((cap or 100) * 0.4),
                "status": status or "open",
            }
        # Try to pull actual occupancy from lot_occupancy_history table
        try:
            for lot_id in states:
                row = self._conn.execute(
                    """SELECT occupied_spaces FROM lot_occupancy_history
                       WHERE lot_id=? ORDER BY recorded_at DESC LIMIT 1""",
                    (lot_id,)
                ).fetchone()
                if row:
                    states[lot_id]["occupied"] = row[0]
        except Exception:
            pass
        return states

    def _get_gate_states(self) -> Dict[str, Dict]:
        """Query current gate queue lengths from DB."""
        if self._conn is None:
            return {}
        rows = self._conn.execute(
            "SELECT gate_id, capacity, status FROM gates WHERE campus_id='vitap'"
        ).fetchall()
        states = {}
        for row in rows:
            gate_id, cap, status = row[0], row[1], row[2]
            states[gate_id] = {
                "capacity": cap or GATE_CAPACITIES.get(gate_id, 5),
                "queue_length": 0,  # live data would come from simulation
                "status": status or "open",
            }
        # Pull from gate_state table (written by twin_service after each simulate call)
        try:
            for gate_id in states:
                row = self._conn.execute(
                    """SELECT current_queue_length FROM gate_state
                       WHERE campus_id='vitap' AND gate_id=?
                       ORDER BY ingestion_timestamp DESC LIMIT 1""",
                    (gate_id,)
                ).fetchone()
                if row:
                    states[gate_id]["queue_length"] = row[0]
        except Exception:
            pass
        return states

    def _apply_hysteresis(self, entity_id: str, score: float) -> float:
        """Return hysteresis-smoothed score — prevents alert flapping around threshold."""
        active = self._alert_state.get(entity_id, False)
        if not active and score >= HYSTERESIS_ON:
            self._alert_state[entity_id] = True
        elif active and score < HYSTERESIS_OFF:
            self._alert_state[entity_id] = False
        # When alert is active, hold score at least at HYSTERESIS_ON so severity doesn't drop
        if self._alert_state.get(entity_id, False):
            return max(score, HYSTERESIS_ON)
        return score

    def overflow_risk(self, lot_states: Dict[str, Dict]) -> Dict[str, float]:
        """Risk that a lot will overflow (fill > 90% of capacity)."""
        risks = {}
        for lot_id, state in lot_states.items():
            if state["status"] != "open":
                risks[lot_id] = 1.0
                continue
            cap = state["capacity"]
            if cap <= 0:
                risks[lot_id] = 0.0
                continue
            fill = state["occupied"] / cap
            # Risk rises sharply above OVERFLOW_THRESHOLD
            risk = _sigmoid(fill, midpoint=OVERFLOW_THRESHOLD, steepness=20.0)
            risks[lot_id] = round(self._apply_hysteresis(lot_id, risk), 4)
        return risks

    def gate_queue_risk(self, gate_states: Dict[str, Dict]) -> Dict[str, float]:
        """Risk from gate queue congestion."""
        risks = {}
        for gate_id, state in gate_states.items():
            if state["status"] != "open":
                risks[gate_id] = 1.0
                continue
            queue = state.get("queue_length", 0)
            risk = _sigmoid(queue, midpoint=GATE_QUEUE_CRITICAL * 0.5, steepness=0.3)
            risks[gate_id] = round(self._apply_hysteresis(gate_id, risk), 4)
        return risks

    def road_congestion_risk(self) -> Dict[str, float]:
        """Risk from road congestion (load vs. capacity).

        Load is sourced from the most recent simulation run's timestep road_load metrics,
        stored in the simulation_metrics table.  Falls back to 0.0 when no run data exists.
        """
        risks = {}
        if self._conn is None:
            return risks
        try:
            rows = self._conn.execute(
                "SELECT road_id, capacity, status FROM roads WHERE campus_id='vitap' AND is_driveable=1"
            ).fetchall()
            # Pull latest road load values from road_state (written by engine every simulated minute)
            road_loads: dict = {}
            try:
                load_rows = self._conn.execute(
                    """SELECT road_id, current_load FROM road_state
                       WHERE campus_id='vitap'
                       ORDER BY ingestion_timestamp DESC LIMIT 100"""
                ).fetchall()
                seen: set = set()
                for rid, load in load_rows:
                    if rid not in seen:
                        road_loads[rid] = float(load) if load is not None else 0.0
                        seen.add(rid)
            except Exception:
                pass

            for row in rows:
                road_id, cap, status = row[0], row[1], row[2]
                if status != "open":
                    risks[road_id] = 0.8
                    continue
                load = road_loads.get(road_id, 0.0)
                cap_ref = float(cap) if cap and cap > 0 else 10.0
                load_ratio = min(1.0, load / cap_ref)
                risks[road_id] = round(_sigmoid(load_ratio, midpoint=ROAD_LOAD_CRITICAL, steepness=10.0), 4)
        except Exception:
            pass
        return risks

    def search_risk(self, lot_states: Dict[str, Dict]) -> Dict[str, float]:
        """Risk that vehicles will have long parking search times."""
        risks = {}
        for lot_id, state in lot_states.items():
            if state["status"] != "open":
                risks[lot_id] = 0.9
                continue
            cap = state["capacity"]
            if cap <= 0:
                risks[lot_id] = 0.0
                continue
            fill = state["occupied"] / cap
            # Search time grows non-linearly as lot fills
            risk = _sigmoid(fill, midpoint=SEARCH_FILL_CRITICAL - 0.1, steepness=25.0)
            risks[lot_id] = round(risk, 4)
        return risks

    def network_risk(
        self,
        overflow_risks: Dict[str, float],
        gate_risks: Dict[str, float],
        search_risks: Dict[str, float],
    ) -> float:
        """Aggregate network-wide risk score (composite)."""
        all_scores = (
            list(overflow_risks.values())
            + list(gate_risks.values())
            + list(search_risks.values())
        )
        if not all_scores:
            return 0.0
        # Weighted: max dominates (system is only as safe as its worst point)
        avg = sum(all_scores) / len(all_scores)
        mx = max(all_scores)
        return round(0.4 * avg + 0.6 * mx, 4)

    def compute_all(self) -> Dict:
        """Compute and return all risk scores from current DB state."""
        lot_states = self._get_lot_states()
        gate_states = self._get_gate_states()

        of_risk = self.overflow_risk(lot_states)
        gq_risk = self.gate_queue_risk(gate_states)
        road_risk = self.road_congestion_risk()
        sr_risk = self.search_risk(lot_states)
        net_risk = self.network_risk(of_risk, gq_risk, sr_risk)

        # Severity classification
        def severity(score: float) -> str:
            if score >= 0.75: return "CRITICAL"
            if score >= 0.50: return "HIGH"
            if score >= 0.25: return "MEDIUM"
            return "LOW"

        return {
            "overflow_risk": {lid: {"score": s, "severity": severity(s)} for lid, s in of_risk.items()},
            "gate_queue_risk": {gid: {"score": s, "severity": severity(s)} for gid, s in gq_risk.items()},
            "road_congestion_risk": {rid: {"score": s, "severity": severity(s)} for rid, s in road_risk.items()},
            "search_risk": {lid: {"score": s, "severity": severity(s)} for lid, s in sr_risk.items()},
            "network_risk": {"score": net_risk, "severity": severity(net_risk)},
            "lot_fill_summary": {
                lid: {
                    "fill_rate": round(state["occupied"] / state["capacity"], 3) if state["capacity"] > 0 else 0,
                    "occupied": state["occupied"],
                    "capacity": state["capacity"],
                    "status": state["status"],
                }
                for lid, state in lot_states.items()
            },
        }

    def compute_forecast(self, horizon_minutes: int = 15) -> Dict:
        """Compute forecasted risk using prediction engine."""
        if self._predictor is None:
            return self.compute_all()

        # Build predicted lot states
        predictions = self._predictor.predict_all(horizon_minutes)
        forecasted_lot_states = {}
        for lot_id, pred in predictions.items():
            cap = LOT_CAPACITIES.get(lot_id, 100)
            forecasted_lot_states[lot_id] = {
                "capacity": cap,
                "occupied": int(pred["fill_rate"] * cap),
                "status": "open",
            }

        gate_states = self._get_gate_states()
        of_risk = self.overflow_risk(forecasted_lot_states)
        gq_risk = self.gate_queue_risk(gate_states)
        road_risk = self.road_congestion_risk()
        sr_risk = self.search_risk(forecasted_lot_states)
        net_risk = self.network_risk(of_risk, gq_risk, sr_risk)

        def severity(score: float) -> str:
            if score >= 0.75: return "CRITICAL"
            if score >= 0.50: return "HIGH"
            if score >= 0.25: return "MEDIUM"
            return "LOW"

        return {
            "horizon_minutes": horizon_minutes,
            "overflow_risk": {lid: {"score": s, "severity": severity(s)} for lid, s in of_risk.items()},
            "gate_queue_risk": {gid: {"score": s, "severity": severity(s)} for gid, s in gq_risk.items()},
            "road_congestion_risk": {rid: {"score": s, "severity": severity(s)} for rid, s in road_risk.items()},
            "search_risk": {lid: {"score": s, "severity": severity(s)} for lid, s in sr_risk.items()},
            "network_risk": {"score": net_risk, "severity": severity(net_risk)},
            "predicted_fill_rates": {lid: round(p["fill_rate"], 3) for lid, p in predictions.items()},
        }
