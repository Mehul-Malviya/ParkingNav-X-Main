"""
Stage 8: Multi-Objective Optimization Engine for ParkingNav-X.

Objective: J = w1·WaitingTime + w2·QueueCost + w3·SearchTravel + w4·UtilizationImbalance + w5·OverflowPenalty

Weight Profiles:
  P1 — minimize waiting time (w1=0.4, w2=0.3, w3=0.2, w4=0.05, w5=0.05)
  P2 — balanced (equal weights, 0.2 each)
  P3 — minimize overflow (w1=0.1, w2=0.1, w3=0.1, w4=0.2, w5=0.5)

Proactive trigger: fire recommendation when 15-min forecast > 90%
  AND current occupancy < 90% (genuinely predictive, not reactive).
"""

import time
import uuid
from typing import Dict, List, Optional

from digital_twin.prediction.features import LOT_CAPACITIES, LOT_IDS

WEIGHT_PROFILES = {
    "P1": {"w1": 0.40, "w2": 0.30, "w3": 0.20, "w4": 0.05, "w5": 0.05},
    "P2": {"w1": 0.20, "w2": 0.20, "w3": 0.20, "w4": 0.20, "w5": 0.20},
    "P3": {"w1": 0.10, "w2": 0.10, "w3": 0.10, "w4": 0.20, "w5": 0.50},
}

PROFILE_LABELS = {
    "P1": "Minimize Wait Time",
    "P2": "Balanced",
    "P3": "Minimize Overflow",
}
TERM_NAMES = {"w1": "waiting time", "w2": "queue cost", "w3": "search travel",
              "w4": "utilisation imbalance", "w5": "overflow penalty"}


def describe_profiles() -> List[Dict]:
    """Profiles as the UI shows them: label, the real weights, and a description derived from them."""
    out = []
    for pid, w in WEIGHT_PROFILES.items():
        top = sorted(w, key=lambda k: -w[k])
        if len(set(w.values())) == 1:
            desc = "Equal weight across all objectives"
        else:
            desc = ("Most weight on " + " and ".join(f"{TERM_NAMES[k]} ({w[k]:.2f})" for k in top[:2]))
        out.append({"id": pid, "label": f"{pid} — {PROFILE_LABELS.get(pid, pid)}",
                    "description": desc, "weights": dict(w)})
    return out


PROACTIVE_FORECAST_THRESHOLD = 0.90   # trigger if forecast > this
RECORDED_MAX_AGE_MIN = 30             # an occupancy snapshot older than this is not "current"
ASSIGNMENT_BLOCK = 10                 # vehicles assumed routed to a candidate lot when scoring it
PROACTIVE_CURRENT_MAX = 0.90          # only trigger if current < this (proactive, not reactive)

LOT_NAMES = {
    "vitap-lot-academic-main": "Academic Block Parking",
    "vitap-lot-hostel": "Hostel Zone Parking",
    "vitap-lot-admin-visitor": "Admin / Visitor Parking",
    "vitap-lot-sports": "Sports Complex Parking",
    "vitap-lot-overflow": "Overflow Parking",
}

GATE_NAMES = {
    "vitap-gate-main": "Main Gate",
    "vitap-gate-visitor": "Visitor Gate",
}


class CostComponents:
    """Compute individual cost components for objective J."""

    @staticmethod
    def waiting_time_cost(gate_states: Dict) -> float:
        """Normalize gate queue length to [0,1]."""
        if not gate_states:
            return 0.0
        queues = [s.get("queue_length", 0) for s in gate_states.values()]
        max_queue = max(queues) if queues else 0
        return min(1.0, max_queue / 20.0)  # 20 vehicles = fully congested

    @staticmethod
    def queue_cost(gate_states: Dict) -> float:
        """Average queue normalized by gate capacity."""
        if not gate_states:
            return 0.0
        scores = []
        for gate_id, state in gate_states.items():
            cap = state.get("capacity", 5)
            queue = state.get("queue_length", 0)
            scores.append(min(1.0, queue / max(1, cap * 3)))
        return sum(scores) / len(scores) if scores else 0.0

    @staticmethod
    def search_travel_cost(lot_fills: Dict[str, float]) -> float:
        """Expected search cost based on average fill across lots."""
        if not lot_fills:
            return 0.0
        avg_fill = sum(lot_fills.values()) / len(lot_fills)
        # Cost rises sharply above 80% fill (non-linear)
        if avg_fill < 0.80:
            return avg_fill * 0.5
        return 0.5 + (avg_fill - 0.80) / 0.20 * 0.5  # escalates to 1.0 at 100%

    @staticmethod
    def utilization_imbalance(lot_fills: Dict[str, float]) -> float:
        """Variance of fill rates across lots — high variance = poor distribution."""
        if len(lot_fills) < 2:
            return 0.0
        fills = list(lot_fills.values())
        mean = sum(fills) / len(fills)
        variance = sum((f - mean) ** 2 for f in fills) / len(fills)
        return min(1.0, variance * 4.0)  # 4x scaling (max theoretical variance = 0.25)

    @staticmethod
    def overflow_penalty(lot_fills: Dict[str, float]) -> float:
        """Binary penalty: any lot above 95% fill = overflow risk."""
        if not lot_fills:
            return 0.0
        overflow_count = sum(1 for f in lot_fills.values() if f >= 0.95)
        return min(1.0, overflow_count / max(1, len(lot_fills)))


class MultiObjectiveOptimizer:
    """
    Generates proactive parking recommendations using multi-objective optimization.

    Evaluates candidate lot assignments against the J cost function and
    fires recommendations when 15-min forecasts indicate imminent issues.
    """

    def __init__(self, weight_profile: str = "P1"):
        self.weights = WEIGHT_PROFILES.get(weight_profile, WEIGHT_PROFILES["P1"])
        self.profile = weight_profile
        self._cost = CostComponents()

    def compute_cost(
        self,
        lot_fills: Dict[str, float],
        gate_states: Dict,
    ) -> Dict:
        """Compute J and each component given current state."""
        w = self.weights
        c1 = self._cost.waiting_time_cost(gate_states)
        c2 = self._cost.queue_cost(gate_states)
        c3 = self._cost.search_travel_cost(lot_fills)
        c4 = self._cost.utilization_imbalance(lot_fills)
        c5 = self._cost.overflow_penalty(lot_fills)
        J = w["w1"]*c1 + w["w2"]*c2 + w["w3"]*c3 + w["w4"]*c4 + w["w5"]*c5
        return {
            "J": round(J, 4),
            # The profile only changes these: the raw component costs below do not depend on it.
            "weights": {k: w[k] for k in ("w1", "w2", "w3", "w4", "w5")},
            "weighted": {
                "waiting_time": round(w["w1"] * c1, 4),
                "queue_cost": round(w["w2"] * c2, 4),
                "search_travel": round(w["w3"] * c3, 4),
                "utilization_imbalance": round(w["w4"] * c4, 4),
                "overflow_penalty": round(w["w5"] * c5, 4),
            },
            "waiting_time": round(c1, 4),
            "queue_cost": round(c2, 4),
            "search_travel": round(c3, 4),
            "utilization_imbalance": round(c4, 4),
            "overflow_penalty": round(c5, 4),
        }

    # -- lot metadata: the campus config/DB is the source of truth; constants are only a fallback --
    def _load_lots(self, conn) -> None:
        self._lots = {}
        try:
            for r in conn.execute(
                "SELECT parking_lot_id, name, usable_capacity, status FROM parking_lots WHERE campus_id='vitap'"
            ).fetchall():
                self._lots[r[0]] = {"name": r[1], "capacity": r[2], "open": r[3] == "open"}
        except Exception:
            self._lots = {}
        # Which OPEN gates can drive to each lot (drive roads in the campus graph).
        self._lot_gates = {}
        try:
            open_gates = {r[0] for r in conn.execute(
                "SELECT gate_id FROM gates WHERE campus_id='vitap' AND status='open'").fetchall()}
            for start, end in conn.execute(
                "SELECT start_node_id, end_node_id FROM roads "
                "WHERE campus_id='vitap' AND is_driveable=1 AND status='open'").fetchall():
                if start in open_gates and end in self._lots:
                    self._lot_gates.setdefault(end, []).append(start)
        except Exception:
            self._lot_gates = {}

    def _lot_gate_costs(self, lot_id: str, gate_states: Dict):
        """Waiting / queue cost a vehicle would face reaching this lot: its best (least congested)
        open gate. None when the lot's gates are unknown, so callers fall back to the system level."""
        gates = [g for g in getattr(self, "_lot_gates", {}).get(lot_id, []) if g in gate_states]
        if not gates:
            return None
        c1 = min(self._cost.waiting_time_cost({g: gate_states[g]}) for g in gates)
        c2 = min(self._cost.queue_cost({g: gate_states[g]}) for g in gates)
        return c1, c2, gates

    def _lot_ids(self) -> List[str]:
        lots = getattr(self, "_lots", None)
        if lots:
            return [i for i, m in lots.items() if m["open"]]  # a closed lot is never recommended
        return list(LOT_IDS)

    def _lot_name(self, lot_id: str) -> str:
        lots = getattr(self, "_lots", None) or {}
        return lots.get(lot_id, {}).get("name") or LOT_NAMES.get(lot_id, lot_id)

    def _lot_cap(self, lot_id: str) -> int:
        lots = getattr(self, "_lots", None) or {}
        return lots.get(lot_id, {}).get("capacity") or LOT_CAPACITIES.get(lot_id, 100)

    def _get_recorded_fills(self, conn) -> Dict[str, float]:
        """Latest recorded fill per lot, ONLY for lots that actually have occupancy history."""
        fills: Dict[str, float] = {}
        self._stale_minutes = {}
        try:
            for lot_id in self._lot_ids():
                row = conn.execute(
                    """SELECT occupied_spaces,
                              (julianday('now') - julianday(recorded_at)) * 1440.0
                       FROM lot_occupancy_history
                       WHERE lot_id=? ORDER BY recorded_at DESC LIMIT 1""", (lot_id,)).fetchone()
                cap = self._lot_cap(lot_id)
                if not row or cap <= 0:
                    continue
                if row[1] is not None and row[1] > RECORDED_MAX_AGE_MIN:
                    self._stale_minutes[lot_id] = round(row[1])   # old simulation/ingest snapshot
                    continue
                fills[lot_id] = min(1.0, row[0] / cap)
        except Exception:
            pass
        return fills

    def _get_current_fills(self, conn) -> Dict[str, float]:
        """Get current fill rates from DB."""
        fills = {lid: 0.4 for lid in self._lot_ids()}  # safe default
        try:
            rows = conn.execute(
                "SELECT parking_lot_id, usable_capacity FROM parking_lots WHERE campus_id='vitap'"
            ).fetchall()
            caps = {r[0]: r[1] for r in rows}
            for lot_id in self._lot_ids():
                try:
                    row = conn.execute(
                        """SELECT occupied_spaces FROM lot_occupancy_history
                           WHERE lot_id=? ORDER BY recorded_at DESC LIMIT 1""",
                        (lot_id,)
                    ).fetchone()
                    if row and caps.get(lot_id, 0) > 0:
                        fills[lot_id] = min(1.0, row[0] / caps[lot_id])
                except Exception:
                    pass
        except Exception:
            pass
        return fills

    def _get_gate_states(self, conn) -> Dict:
        """Get gate queue states from DB."""
        try:
            rows = conn.execute(
                "SELECT gate_id, capacity FROM gates WHERE campus_id='vitap' AND status='open'"
            ).fetchall()
            states = {r[0]: {"capacity": r[1], "queue_length": 0} for r in rows}
            # Pull live queue lengths from gate_state (written by simulation engine)
            for gate_id in states:
                row = conn.execute(
                    """SELECT current_queue_length FROM gate_state
                       WHERE campus_id='vitap' AND gate_id=?
                       ORDER BY ingestion_timestamp DESC LIMIT 1""",
                    (gate_id,)
                ).fetchone()
                if row:
                    states[gate_id]["queue_length"] = row[0]
            return states
        except Exception:
            return {"vitap-gate-main": {"capacity": 6, "queue_length": 0}}

    def _check_proactive_trigger(
        self,
        current_fills: Dict[str, float],
        forecast_fills: Optional[Dict[str, float]],
    ) -> List[Dict]:
        """
        Fire a recommendation if forecast > 90% AND current < 90%.
        This is the key proactive (not reactive) alert.
        """
        alerts = []
        if forecast_fills is None:
            return alerts
        for lot_id in self._lot_ids():
            current = current_fills.get(lot_id, 0.5)
            forecast = forecast_fills.get(lot_id, current)
            if forecast >= PROACTIVE_FORECAST_THRESHOLD and current < PROACTIVE_CURRENT_MAX:
                # Proactive alert: suggest alternative lots
                alternatives = [
                    lid for lid in self._lot_ids()
                    if lid != lot_id and forecast_fills.get(lid, 0) < 0.75
                ]
                alerts.append({
                    "type": "PROACTIVE_REROUTE",
                    "lot_id": lot_id,
                    "lot_name": self._lot_name(lot_id),
                    "current_fill": round(current, 3),
                    "forecast_fill_15min": round(forecast, 3),
                    "message": (
                        f"{self._lot_name(lot_id)} is forecast to reach "
                        f"{forecast*100:.0f}% capacity in 15 minutes. "
                        f"Redirect vehicles proactively."
                    ),
                    "alternative_lots": [
                        {"lot_id": a, "lot_name": self._lot_name(a), "forecast_fill": round(forecast_fills.get(a, 0.5), 3)}
                        for a in alternatives[:2]
                    ],
                })
        return alerts

    @staticmethod
    def _blend(lot_fills, forecast_fills, lot_ids) -> Dict[str, float]:
        """State used for scoring: 60% current fill + 40% 15-min forecast (weighted towards the future)."""
        out = {}
        for lot_id in lot_ids:
            cur = lot_fills.get(lot_id, 0.5)
            fc = forecast_fills.get(lot_id, cur) if forecast_fills else cur
            out[lot_id] = cur * 0.6 + fc * 0.4
        return out

    def _rank_lots(
        self,
        lot_fills: Dict[str, float],
        forecast_fills: Optional[Dict[str, float]],
        gate_states: Optional[Dict] = None,
    ) -> List[Dict]:
        """Rank all lots by objective J under the selected weight profile (lower = better).

        Each lot is scored by the J the system would have if the next ASSIGNMENT_BLOCK vehicles
        were routed to it: J = w1*c1 + ... + w5*c5 on the projected lot fills. Different profiles
        therefore weigh search travel, utilisation balance and overflow risk differently and can
        order the lots differently. `recommendation_score` (availability blended from current and
        forecast fill) and the `recommended` flag are unchanged.
        """
        w = self.weights
        gates = gate_states or {}
        c1 = self._cost.waiting_time_cost(gates)   # system level (worst gate): the reference for base_J
        c2 = self._cost.queue_cost(gates)
        blended = self._blend(lot_fills, forecast_fills, self._lot_ids())

        # J of the unchanged blended state: the reference every per-lot J is compared with
        base_J = (
            w["w1"] * c1 + w["w2"] * c2
            + w["w3"] * self._cost.search_travel_cost(blended)
            + w["w4"] * self._cost.utilization_imbalance(blended)
            + w["w5"] * self._cost.overflow_penalty(blended)
        )
        ranked = []
        for lot_id in self._lot_ids():
            current = lot_fills.get(lot_id, 0.5)
            forecast = forecast_fills.get(lot_id, current) if forecast_fills else current
            headroom = 1.0 - forecast
            cap = self._lot_cap(lot_id)
            score = blended[lot_id]
            projected = dict(blended)
            projected[lot_id] = min(1.0, blended[lot_id] + ASSIGNMENT_BLOCK / max(1, cap))
            gate_costs = self._lot_gate_costs(lot_id, gates)
            lc1, lc2 = (gate_costs[0], gate_costs[1]) if gate_costs else (c1, c2)
            objective = (
                w["w1"] * lc1 + w["w2"] * lc2
                + w["w3"] * self._cost.search_travel_cost(projected)
                + w["w4"] * self._cost.utilization_imbalance(projected)
                + w["w5"] * self._cost.overflow_penalty(projected)
            )
            ranked.append({
                "lot_id": lot_id,
                "lot_name": self._lot_name(lot_id),
                "capacity": cap,
                "current_fill_rate": round(current, 3),
                "forecast_fill_rate_15min": round(forecast, 3),
                "headroom": round(headroom, 3),
                "available_spaces": int(headroom * cap),
                "recommendation_score": round(score, 4),
                "objective_score": round(objective, 4),
                "objective_delta": round(objective - base_J, 4),
                "access_gates": gate_costs[2] if gate_costs else [],
                "recommended": score < 0.70,
            })
        ranked.sort(key=lambda x: (x["objective_score"], x["recommendation_score"]))
        for i, lot in enumerate(ranked):
            lot["rank"] = i + 1
        return ranked

    def generate_recommendations(self, conn) -> List[Dict]:
        """
        Main entry point: generate all active recommendations.
        Returns a list of recommendation objects.
        """
        self._load_lots(conn)
        gate_states = self._get_gate_states(conn)

        # Try to get forecast
        forecast_fills = None
        try:
            from digital_twin.prediction.engine import forecast_context
            predictor, _basis = forecast_context(conn)   # campus clock + fresh live occupancy
            snapshot = predictor.get_forecast_snapshot(15)
            forecast_fills = snapshot.get("lot_fill_rates")
        except Exception:
            pass

        # Current fill: recorded occupancy if there is any, else the forecast. The old fixed 40%
        # default was made-up data and is only a last resort when neither exists.
        recorded = self._get_recorded_fills(conn)
        current_fills, fill_sources = {}, {}
        for lot_id in self._lot_ids():
            if lot_id in recorded:
                current_fills[lot_id], fill_sources[lot_id] = recorded[lot_id], "recorded"
            elif forecast_fills and lot_id in forecast_fills:
                current_fills[lot_id], fill_sources[lot_id] = forecast_fills[lot_id], "forecast"
            else:
                current_fills[lot_id], fill_sources[lot_id] = 0.4, "default"
        cost_now = self.compute_cost(current_fills, gate_states)
        # Shown system J uses the SAME blended state the lot scores use, so the two reconcile.
        cost = self.compute_cost(self._blend(current_fills, forecast_fills, self._lot_ids()), gate_states)
        cost["basis"] = "60% current fill + 40% 15-min forecast"

        proactive_alerts = self._check_proactive_trigger(current_fills, forecast_fills)
        ranked_lots = self._rank_lots(current_fills, forecast_fills, gate_states)
        for lot in ranked_lots:
            lot["current_fill_source"] = fill_sources.get(lot["lot_id"], "default")
            if lot["lot_id"] in getattr(self, "_stale_minutes", {}):
                lot["stale_snapshot_min"] = self._stale_minutes[lot["lot_id"]]

        recommendations = []

        # 1. Proactive alerts (highest priority)
        for alert in proactive_alerts:
            recommendations.append({
                "id": str(uuid.uuid4())[:8],
                "priority": "HIGH",
                "type": alert["type"],
                "lot_id": alert["lot_id"],
                "lot_name": alert["lot_name"],
                "message": alert["message"],
                "current_fill": alert["current_fill"],
                "forecast_fill_15min": alert["forecast_fill_15min"],
                "alternatives": alert.get("alternative_lots", []),
                "timestamp": time.time(),
            })

        # 2. Lot ranking recommendation
        best = ranked_lots[0] if ranked_lots else None
        n_feasible = sum(1 for l in ranked_lots if l.get("recommended", False))
        why_chosen = (
            f"Chosen because {best['lot_name']} has the lowest objective score "
            f"({best['objective_score']:.3f}) under profile {self.profile} "
            f"among {n_feasible} feasible alternatives."
            if best else "No feasible lots available."
        )
        recommendations.append({
            "id": str(uuid.uuid4())[:8],
            "priority": "INFO",
            "type": "LOT_RANKING",
            "message": f"Parking lots ranked by objective J under profile {self.profile} (lower is better)",
            "recommended_lot": best["lot_id"] if best else None,
            "recommended_lot_name": best["lot_name"] if best else None,
            "objective_score": best["objective_score"] if best else None,
            "why_chosen": why_chosen,
            "alternatives": ranked_lots[1:] if ranked_lots else [],
            "ranked_lots": ranked_lots,
            "cost_function": cost,
            "weight_profile": self.profile,
            "timestamp": time.time(),
        })

        # 3. Capacity warning if J is high
        if cost_now["J"] >= 0.6:
            recommendations.insert(0, {
                "id": str(uuid.uuid4())[:8],
                "priority": "CRITICAL",
                "type": "SYSTEM_CAPACITY_ALERT",
                "message": f"Campus parking system under high stress (J={cost_now['J']:.2f}). Immediate action required.",
                "cost_function": cost_now,
                "timestamp": time.time(),
            })

        return recommendations

    def run_experiment(
        self,
        scenario: str,
        strategy_code: str,
        seed: int,
        conn,
    ) -> Dict:
        """
        Run one experiment cell (scenario × strategy × seed) and return metrics.
        Used by run_all_experiments.py.
        """
        from pathlib import Path
        from digital_twin.simulation.engine import SimulationEngine
        from digital_twin.simulation.scenario import ScenarioLoader
        from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy
        from digital_twin.simulation.demo_strategies import PredictionOnlyStrategy, ParkingNavXFullStrategy

        ROOT = Path(__file__).resolve().parent.parent.parent
        SCENARIO_DIR = ROOT / "configs" / "scenarios" / "vitap"
        scenario_file = SCENARIO_DIR / f"{scenario}.yaml"

        strategies = {
            "B1": FirstAvailableStrategy(),
            "B2": NearestAvailableStrategy(),
            "B3": PredictionOnlyStrategy(),
            "P":  ParkingNavXFullStrategy(),
        }
        strategy = strategies.get(strategy_code, strategies["B2"])
        sc = ScenarioLoader.load(scenario_file)
        engine = SimulationEngine()
        run_id = f"exp-{scenario}-{strategy_code}-s{seed}"
        result = engine.run(sc, strategy, conn, run_id=run_id)
        m = result.metrics

        # Compute cost function J from actual simulation lot fill rates
        lot_fills = self._get_current_fills(conn)
        gate_states = self._get_gate_states(conn)
        cost = self.compute_cost(lot_fills, gate_states)

        return {
            "scenario": scenario,
            "strategy": strategy_code,
            "seed": seed,
            "run_id": run_id,
            "metrics": {
                "total_vehicles": m.get("total_vehicles"),
                "parked_vehicles": m.get("parked_vehicles"),
                "overflow_events": m.get("overflow_events_count"),
                "avg_search_time_min": m.get("avg_search_time_min"),
                "avg_wait_time_min": m.get("avg_wait_time_min"),
                "avg_gate_queue": m.get("avg_gate_queue"),
                "max_gate_queue": m.get("max_gate_queue"),
            },
            "cost_J": cost["J"],
        }
