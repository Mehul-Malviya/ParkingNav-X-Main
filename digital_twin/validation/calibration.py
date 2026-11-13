"""
Phase 10 — Calibration & Counterfactual Replay

Validate simulator against real observations, fit parameters, run counterfactuals.
"""

import json
import statistics
from typing import Dict, List


class CalibrationReport:
    """Generate calibration report comparing real vs simulated metrics."""

    def __init__(self, real_data: List[Dict], simulated_data: List[Dict]):
        """
        Args:
            real_data: observed metrics [{timestamp, lot_id, occupied, arrivals, departures}, ...]
            simulated_data: simulated metrics (same schema)
        """
        self.real = real_data
        self.sim = simulated_data
        self.errors = {}

    def compute_mae(self, metric: str) -> float:
        """Mean Absolute Error for a metric."""
        if not self.real or not self.sim:
            return None

        real_vals = [d.get(metric, 0) for d in self.real]
        sim_vals = [d.get(metric, 0) for d in self.sim]

        if len(real_vals) != len(sim_vals):
            return None

        mae = sum(abs(r - s) for r, s in zip(real_vals, sim_vals)) / len(real_vals)
        return mae

    def compute_rmse(self, metric: str) -> float:
        """Root Mean Square Error for a metric."""
        if not self.real or not self.sim:
            return None

        real_vals = [d.get(metric, 0) for d in self.real]
        sim_vals = [d.get(metric, 0) for d in self.sim]

        if len(real_vals) != len(sim_vals):
            return None

        mse = sum((r - s) ** 2 for r, s in zip(real_vals, sim_vals)) / len(real_vals)
        return mse ** 0.5

    def compute_bias(self, metric: str) -> float:
        """Mean signed error (bias): positive = simulator overestimates."""
        if not self.real or not self.sim:
            return None

        real_vals = [d.get(metric, 0) for d in self.real]
        sim_vals = [d.get(metric, 0) for d in self.sim]

        if len(real_vals) != len(sim_vals):
            return None

        bias = sum(s - r for r, s in zip(real_vals, sim_vals)) / len(real_vals)
        return bias

    def compute_percentile_error(self, metric: str, percentile: int) -> float:
        """Error at a specific percentile."""
        if not self.real or not self.sim:
            return None

        real_vals = [d.get(metric, 0) for d in self.real]
        sim_vals = [d.get(metric, 0) for d in self.sim]

        errors = [abs(r - s) for r, s in zip(real_vals, sim_vals)]
        errors_sorted = sorted(errors)

        idx = int(len(errors_sorted) * percentile / 100)
        return errors_sorted[min(idx, len(errors_sorted) - 1)]

    def generate_report(self, output_path: str, metrics_to_check: List[str]) -> dict:
        """Generate full calibration report."""
        report = {
            "calibration_timestamp": __import__('datetime').datetime.now(
                __import__('datetime').timezone.utc
            ).isoformat(),
            "data_points_real": len(self.real),
            "data_points_sim": len(self.sim),
            "metrics": {}
        }

        for metric in metrics_to_check:
            mae = self.compute_mae(metric)
            rmse = self.compute_rmse(metric)
            bias = self.compute_bias(metric)
            p95 = self.compute_percentile_error(metric, 95)

            report["metrics"][metric] = {
                "MAE": round(mae, 3) if mae else None,
                "RMSE": round(rmse, 3) if rmse else None,
                "bias": round(bias, 3) if bias else None,
                "p95_error": round(p95, 3) if p95 else None,
            }

        # Write report
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        return report


class CounterfactualReplay:
    """Replay real observations through simulator with different strategies."""

    @staticmethod
    def infer_scenario_from_observations(observations: List[Dict]) -> dict:
        """
        Build scenario config from observed data.

        Args:
            observations: [{timestamp, vehicle_arrivals, ...}, ...]

        Returns:
            Scenario dict ready for engine.run()
        """
        # Count total vehicles
        total_arrivals = sum(obs.get("vehicle_arrivals", 0) for obs in observations)

        # Infer profile from time-of-day
        profile_points = []
        for obs in observations:
            # Extract hour from timestamp
            ts = obs.get("timestamp", "")
            if "T" in ts:
                hour_min = ts.split("T")[1]  # HH:MM:SS
                hour = int(hour_min.split(":")[0])
                rate = obs.get("vehicle_arrivals", 0) / 15  # Convert 15-min to per-min
                profile_points.append({"time": hour * 60, "rate": rate})

        # Deduplicate by time
        profile_points_dedup = {}
        for point in profile_points:
            profile_points_dedup[point["time"]] = point["rate"]

        scenario = {
            "campus_id": "vitap",
            "scenario_id": "real-observation-replay",
            "name": "Real Observation Replay",
            "duration_minutes": 840,  # Full day
            "vehicle_count": int(total_arrivals),
            "arrival_rate_profile": {
                "type": "profile",
                "points": [
                    {"time": time, "rate": rate}
                    for time, rate in sorted(profile_points_dedup.items())
                ]
            },
            "event_conditions": None,  # Would infer from observations if present
            "availability_overrides": {
                "closed_gates": [],
                "closed_parking_lots": [],
                "closed_roads": []
            },
            "prediction_error_injection_level": 0.0,
            "random_seed": 12345,  # Fixed seed: replay same demand
        }

        return scenario

    @staticmethod
    def run_counterfactual(scenario: dict, strategies: List[str],
                          engine, conn) -> Dict[str, dict]:
        """
        Run simulation with multiple strategies on real demand.

        Args:
            scenario: scenario dict
            strategies: list of strategy names (e.g., ["B1", "B2"])
            engine: SimulationEngine instance
            conn: database connection

        Returns:
            {strategy_name: result_metrics, ...}
        """
        from digital_twin.simulation.strategy import (
            FirstAvailableStrategy,
            NearestAvailableStrategy,
        )

        results = {}

        for strategy_name in strategies:
            if strategy_name == "B1" or strategy_name == "FirstAvailable":
                strategy = FirstAvailableStrategy()
            elif strategy_name == "B2" or strategy_name == "NearestAvailable":
                strategy = NearestAvailableStrategy()
            else:
                raise ValueError(f"Unknown strategy: {strategy_name}")

            from digital_twin.simulation.scenario import ScenarioLoader
            scenario_obj = ScenarioLoader.from_dict(scenario)

            result = engine.run(scenario_obj, strategy, conn)

            # Extract key metrics
            results[strategy_name] = {
                "total_vehicles": len(result.vehicles),
                "parked_vehicles": sum(1 for v in result.vehicles if v["final_state"] == "parked"),
                "rejected_vehicles": sum(1 for v in result.vehicles if v["final_state"] != "parked"),
                "avg_search_time_min": statistics.mean(
                    [v["search_time_seconds"] / 60 for v in result.vehicles
                     if v["search_time_seconds"] is not None]
                ) if result.vehicles else 0,
                "avg_wait_time_min": statistics.mean(
                    [v["waiting_time_seconds"] / 60 for v in result.vehicles
                     if v["waiting_time_seconds"] is not None]
                ) if result.vehicles else 0,
                "overflow_events": len(result.overflow_events),
                "infeasibility_rejections": result.infeasibility_rejections,
            }

        return results


def honest_counterfactual_label() -> str:
    """Standard disclaimer for all counterfactual results."""
    return (
        "⚠️ **Simulation-based estimate.** This is a counterfactual replay: "
        "the simulator was fed the observed arrival pattern and asked how it would perform "
        "under that demand with different strategies. "
        "Real deployment may differ due to driver adaptation, infrastructure differences, "
        "or unmodeled factors. These results show relative comparison, not absolute predictions."
    )
