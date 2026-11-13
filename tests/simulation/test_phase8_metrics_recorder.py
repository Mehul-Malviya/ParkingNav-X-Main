"""
Phase 8 — Metrics Recorder

Tests that metrics are recorded to disk with correct structure and 5 primary metrics computed.
"""

import json
import tempfile

import pytest

from digital_twin.simulation.metrics_recorder import MetricsRecorder


class TestMetricsRecorder:
    """Verify metrics recording and primary metric computation."""

    @pytest.fixture
    def temp_runs_dir(self):
        """Temporary directory for test outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_recorder_creates_output_structure(self, temp_runs_dir):
        """MetricsRecorder creates runs/{scenario}/{strategy}/seed_{n}/ structure."""
        recorder = MetricsRecorder(output_root=temp_runs_dir)

        vehicle_metrics = [
            {
                "vehicle_id": "v1",
                "entry_gate": "g1",
                "destination_id": "d1",
                "search_time_seconds": 120,
                "waiting_time_seconds": 60,
                "travel_time_seconds": 300,
                "travel_distance_meters": 500,
                "assigned_lot_id": "l1",
                "final_state": "parked",
            }
        ]

        timestep_metrics = [
            {
                "tick": 0,
                "parking_occupancy_l1": 10,
                "gate_queue_g1": 2,
                "road_load_r1": 5,
            }
        ]

        overflow_events = []

        output_dir = recorder.record_run(
            scenario_id="test-scenario",
            strategy_name="TestStrategy",
            seed=42,
            vehicle_metrics=vehicle_metrics,
            timestep_metrics=timestep_metrics,
            overflow_events=overflow_events,
            config_dict={"test": "config"},
        )

        # Verify directory structure
        assert output_dir.exists()
        assert output_dir.name == "seed_42"
        assert "TestStrategy" in str(output_dir)
        assert "test-scenario" in str(output_dir)

    def test_recorder_writes_metric_files(self, temp_runs_dir):
        """MetricsRecorder writes metrics.json, manifest.json, vehicle data."""
        recorder = MetricsRecorder(output_root=temp_runs_dir)

        vehicle_metrics = [
            {
                "vehicle_id": "v1",
                "entry_gate": "g1",
                "destination_id": "d1",
                "search_time_seconds": 120,
                "waiting_time_seconds": 60,
                "travel_time_seconds": 300,
                "travel_distance_meters": 500,
                "assigned_lot_id": "l1",
                "final_state": "parked",
            }
        ]

        timestep_metrics = [
            {"tick": 0, "parking_occupancy_l1": 10, "gate_queue_g1": 2}
        ]

        output_dir = recorder.record_run(
            scenario_id="test",
            strategy_name="B1",
            seed=1,
            vehicle_metrics=vehicle_metrics,
            timestep_metrics=timestep_metrics,
            overflow_events=[],
            config_dict={},
        )

        # Check files exist
        assert (output_dir / "metrics.json").exists()
        assert (output_dir / "manifest.json").exists()
        # Either parquet or JSON for vehicles
        assert (output_dir / "vehicles.parquet").exists() or (output_dir / "vehicles.json").exists()

    def test_primary_metrics_computation(self, temp_runs_dir):
        """Primary metrics are correctly computed and reported."""
        recorder = MetricsRecorder(output_root=temp_runs_dir)

        vehicle_metrics = [
            {
                "vehicle_id": "v1",
                "entry_gate": "g1",
                "destination_id": "d1",
                "search_time_seconds": 120,  # 2 min
                "waiting_time_seconds": 60,  # 1 min
                "travel_time_seconds": 300,  # 5 min
                "travel_distance_meters": 1000,  # 1 km
                "assigned_lot_id": "l1",
                "final_state": "parked",
            },
            {
                "vehicle_id": "v2",
                "entry_gate": "g1",
                "destination_id": "d1",
                "search_time_seconds": 180,  # 3 min
                "waiting_time_seconds": 120,  # 2 min
                "travel_time_seconds": 240,  # 4 min
                "travel_distance_meters": 800,  # 0.8 km
                "assigned_lot_id": "l1",
                "final_state": "parked",
            },
        ]

        timestep_metrics = [
            {"tick": 0, "gate_queue_g1": 2},
            {"tick": 1, "gate_queue_g1": 1},
        ]

        overflow_events = []

        output_dir = recorder.record_run(
            scenario_id="test",
            strategy_name="B1",
            seed=1,
            vehicle_metrics=vehicle_metrics,
            timestep_metrics=timestep_metrics,
            overflow_events=overflow_events,
            config_dict={},
        )

        # Read metrics
        with open(output_dir / "metrics.json") as f:
            metrics = json.load(f)

        primary = metrics["primary_metrics"]

        # Verify 5 primary metrics exist
        assert "avg_search_time_min" in primary
        assert "avg_waiting_time_min" in primary
        assert "avg_gate_queue_vehicles" in primary
        assert "max_gate_queue_vehicles" in primary
        assert "overflow_events_count" in primary
        assert "total_travel_time_veh_min" in primary
        assert "total_travel_distance_veh_km" in primary

        # Check values are reasonable
        assert primary["avg_search_time_min"] > 0  # avg of 2 and 3 min
        assert primary["avg_waiting_time_min"] > 0  # avg of 1 and 2 min
        assert primary["overflow_events_count"] == 0
        assert primary["total_travel_distance_veh_km"] > 0

    def test_manifest_includes_metadata(self, temp_runs_dir):
        """Manifest includes config hash, git commit, timestamps."""
        recorder = MetricsRecorder(output_root=temp_runs_dir)

        output_dir = recorder.record_run(
            scenario_id="test",
            strategy_name="B1",
            seed=1,
            vehicle_metrics=[],
            timestep_metrics=[],
            overflow_events=[],
            config_dict={"test": "config"},
            git_commit="abc123",
        )

        with open(output_dir / "manifest.json") as f:
            manifest = json.load(f)

        # Check required fields
        assert manifest["scenario_id"] == "test"
        assert manifest["strategy_name"] == "B1"
        assert manifest["random_seed"] == 1
        assert manifest["config_hash"]
        assert manifest["git_commit"] == "abc123"
        assert manifest["recorded_at"]

    def test_empty_vehicle_metrics(self, temp_runs_dir):
        """Recorder handles empty vehicle metrics gracefully."""
        recorder = MetricsRecorder(output_root=temp_runs_dir)

        output_dir = recorder.record_run(
            scenario_id="test",
            strategy_name="B1",
            seed=1,
            vehicle_metrics=[],
            timestep_metrics=[],
            overflow_events=[],
            config_dict={},
        )

        with open(output_dir / "metrics.json") as f:
            metrics = json.load(f)

        # Should not error, metrics should be zero
        primary = metrics["primary_metrics"]
        assert primary["overflow_events_count"] == 0
        assert primary["total_travel_time_veh_min"] == 0


if __name__ == "__main__":
    print("Run with: python -m pytest tests/test_phase8_metrics_recorder.py -v")
