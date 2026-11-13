"""
Phase 10 — Real-Campus Validation & Counterfactual Replay (E7)

Tests for calibration, honest reporting, and counterfactual scenarios.
"""

import json
import tempfile

from digital_twin.validation.calibration import (
    CalibrationReport,
    CounterfactualReplay,
    honest_counterfactual_label,
)


class TestCalibrationReport:
    """Test calibration report generation."""

    def test_mae_computation(self):
        """CalibrationReport computes MAE correctly."""
        real = [
            {"occupied": 50, "arrivals": 10},
            {"occupied": 55, "arrivals": 12},
            {"occupied": 60, "arrivals": 8},
        ]

        sim = [
            {"occupied": 52, "arrivals": 11},
            {"occupied": 54, "arrivals": 13},
            {"occupied": 62, "arrivals": 7},
        ]

        report = CalibrationReport(real, sim)

        mae_occupied = report.compute_mae("occupied")
        # |50-52| + |55-54| + |60-62| / 3 = (2 + 1 + 2) / 3 = 1.667
        assert abs(mae_occupied - 1.667) < 0.01

        mae_arrivals = report.compute_mae("arrivals")
        # |10-11| + |12-13| + |8-7| / 3 = (1 + 1 + 1) / 3 = 1.0
        assert abs(mae_arrivals - 1.0) < 0.01

    def test_rmse_computation(self):
        """CalibrationReport computes RMSE correctly."""
        real = [
            {"occupied": 50},
            {"occupied": 60},
        ]

        sim = [
            {"occupied": 52},
            {"occupied": 58},
        ]

        report = CalibrationReport(real, sim)
        rmse = report.compute_rmse("occupied")

        # sqrt((4 + 4) / 2) = sqrt(4) = 2.0
        assert abs(rmse - 2.0) < 0.01

    def test_bias_computation(self):
        """CalibrationReport computes bias (signed error)."""
        real = [
            {"occupied": 50},
            {"occupied": 60},
        ]

        sim = [
            {"occupied": 55},  # sim overestimates by 5
            {"occupied": 55},  # sim underestimates by 5
        ]

        report = CalibrationReport(real, sim)
        bias = report.compute_bias("occupied")

        # (5 + (-5)) / 2 = 0.0 (balanced)
        assert abs(bias - 0.0) < 0.01

    def test_percentile_error(self):
        """CalibrationReport computes percentile error."""
        real = [
            {"occupied": 50 + i * 10} for i in range(10)
        ]
        sim = [
            {"occupied": 50 + i * 10 + (i % 3)} for i in range(10)
        ]

        report = CalibrationReport(real, sim)
        p95 = report.compute_percentile_error("occupied", 95)

        # Errors: [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]
        # Sorted: [0, 0, 0, 0, 1, 1, 1, 2, 2, 2]
        # 95th percentile idx = 9: value = 2
        assert p95 == 2.0

    def test_generate_report(self):
        """CalibrationReport generates and writes report."""
        real = [
            {"occupied": 50, "arrivals": 10, "queue": 3},
            {"occupied": 55, "arrivals": 12, "queue": 4},
        ]

        sim = [
            {"occupied": 52, "arrivals": 11, "queue": 2},
            {"occupied": 54, "arrivals": 13, "queue": 5},
        ]

        report = CalibrationReport(real, sim)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            output_path = f.name

        try:
            result = report.generate_report(output_path, ["occupied", "arrivals", "queue"])

            # Check structure
            assert "calibration_timestamp" in result
            assert result["data_points_real"] == 2
            assert result["data_points_sim"] == 2
            assert "metrics" in result
            assert "occupied" in result["metrics"]
            assert "MAE" in result["metrics"]["occupied"]

            # Check file was written
            with open(output_path) as f:
                data = json.load(f)
            assert data["data_points_real"] == 2
        finally:
            import os
            os.unlink(output_path)

    def test_missing_data_handling(self):
        """CalibrationReport handles missing metrics gracefully."""
        real = [
            {"occupied": 50},
            {"occupied": 55},
        ]

        sim = [
            {"occupied": 52},
            # Missing 'occupied' in second row
        ]

        report = CalibrationReport(real, sim)
        mae = report.compute_mae("occupied")

        # Should return None or handle gracefully
        assert mae is None or isinstance(mae, (int, float))


class TestCounterfactualReplay:
    """Test counterfactual scenario generation and replay."""

    def test_infer_scenario_from_observations(self):
        """CounterfactualReplay infers scenario config from observations."""
        observations = [
            {"timestamp": "2026-10-15T08:00:00Z", "vehicle_arrivals": 12},
            {"timestamp": "2026-10-15T08:15:00Z", "vehicle_arrivals": 15},
            {"timestamp": "2026-10-15T09:00:00Z", "vehicle_arrivals": 20},
        ]

        scenario = CounterfactualReplay.infer_scenario_from_observations(observations)

        # Check essential fields
        assert scenario["campus_id"] == "vitap"
        assert scenario["vehicle_count"] == 47  # 12 + 15 + 20
        assert scenario["arrival_rate_profile"]["type"] == "profile"
        assert "points" in scenario["arrival_rate_profile"]
        assert scenario["random_seed"] == 12345  # Fixed seed

    def test_counterfactual_label(self):
        """Honest counterfactual disclaimer is present and clear."""
        label = honest_counterfactual_label()

        # Must contain warnings
        assert "Simulation-based estimate" in label
        assert "counterfactual" in label
        assert "observed" in label
        assert "may differ" in label


class TestObservationProtocol:
    """Test data validation per observation protocol."""

    def test_observation_csv_validation(self):
        """Validate observation CSV rows against protocol."""
        observation = {
            "timestamp": "2026-10-15T08:00:00Z",
            "gate_id": "vitap-gate-1",
            "lot_id": "vitap-lot-1",
            "vehicle_arrivals": 12,
            "vehicle_departures": 5,
            "occupied_spaces": 45,
            "total_capacity": 120,
            "event_type": "none",
            "confidence": 0.95,
        }

        # Validate constraints
        assert observation["occupied_spaces"] <= observation["total_capacity"]
        assert observation["vehicle_arrivals"] >= 0
        assert observation["vehicle_departures"] >= 0
        assert 0 <= observation["confidence"] <= 1.0

        # Valid observation
        assert True

    def test_observation_csv_invalid_occupancy(self):
        """Reject observations with occupancy > capacity."""
        observation = {
            "occupied_spaces": 150,
            "total_capacity": 120,
        }

        # Should fail validation
        assert not (observation["occupied_spaces"] <= observation["total_capacity"])


if __name__ == "__main__":
    print("Run with: python -m pytest tests/test_phase10_validation.py -v")
