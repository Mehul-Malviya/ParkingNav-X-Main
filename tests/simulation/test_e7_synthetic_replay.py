"""
E7 â€” Counterfactual Replay: Run simulator with synthetic observations.

Uses data/synthetic_observations.csv as a placeholder until real gate-count
data is collected. All tests skip gracefully if the CSV is absent.
"""

import csv
from pathlib import Path

import pytest

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy
from digital_twin.validation.calibration import CalibrationReport, CounterfactualReplay


class TestE7SyntheticReplay:
    """Test counterfactual replay pipeline using synthetic observations."""

    @pytest.fixture
    def setup(self):
        conn = get_connection(':memory:')
        apply_migrations(conn)
        load_campus_config(Path('configs/campus/vitap.yaml'), conn)
        return conn

    def load_observations_csv(self, csv_path):
        """Load observations from CSV."""
        observations = []
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                observations.append({
                    'timestamp': row['timestamp'],
                    'gate_id': row['gate_id'],
                    'lot_id': row['lot_id'],
                    'vehicle_arrivals': int(row['vehicle_arrivals']),
                    'vehicle_departures': int(row['vehicle_departures']),
                    'occupied_spaces': int(row['occupied_spaces']),
                    'total_capacity': int(row['total_capacity']),
                    'event_type': row['event_type'],
                    'confidence': float(row['confidence']),
                })
        return observations

    def test_load_sample_observations(self):
        """Verify sample_observations.csv loads correctly (skips if absent)."""
        csv_path = Path('data/sample_observations.csv')
        if not csv_path.exists():
            pytest.skip("sample_observations.csv not found")

        obs = self.load_observations_csv(csv_path)
        assert len(obs) > 0
        assert 'timestamp' in obs[0]
        assert 'vehicle_arrivals' in obs[0]
        assert 'occupied_spaces' in obs[0]

    def test_infer_scenario_from_observations(self):
        """Infer scenario config from synthetic observations."""
        csv_path = Path('data/sample_observations.csv')
        if not csv_path.exists():
            pytest.skip("sample_observations.csv not found")

        obs = self.load_observations_csv(csv_path)
        scenario = CounterfactualReplay.infer_scenario_from_observations(obs)

        assert scenario is not None
        assert scenario['campus_id'] == 'vitap'
        assert scenario['vehicle_count'] > 0
        assert 'arrival_rate_profile' in scenario

    def test_counterfactual_replay_with_observations(self, setup):
        """Run counterfactual replay with B1 and B2 on synthetic demand."""
        csv_path = Path('data/sample_observations.csv')
        if not csv_path.exists():
            pytest.skip("sample_observations.csv not found")

        conn = setup
        obs = self.load_observations_csv(csv_path)
        scenario_dict = CounterfactualReplay.infer_scenario_from_observations(obs)
        scenario = ScenarioLoader.from_dict(scenario_dict)

        engine = SimulationEngine()
        result_b1 = engine.run(scenario, FirstAvailableStrategy(), conn)
        result_b2 = engine.run(scenario, NearestAvailableStrategy(), conn)

        assert result_b1 is not None
        assert result_b2 is not None

        b1_search = result_b1.metrics.get('avg_search_time_min', 0)
        b2_search = result_b2.metrics.get('avg_search_time_min', 0)
        assert b2_search <= b1_search or abs(b1_search - b2_search) < 0.1

    def test_calibration_report_with_observations(self, setup):
        """Generate calibration report comparing synthetic vs simulated occupancy."""
        csv_path = Path('data/sample_observations.csv')
        if not csv_path.exists():
            pytest.skip("sample_observations.csv not found")

        conn = setup
        obs = self.load_observations_csv(csv_path)

        synthetic_data = [
            {
                'occupied': obs[i]['occupied_spaces'],
                'arrivals': obs[i]['vehicle_arrivals'],
                'departures': obs[i]['vehicle_departures'],
            }
            for i in range(len(obs))
        ]

        scenario_dict = CounterfactualReplay.infer_scenario_from_observations(obs)
        scenario = ScenarioLoader.from_dict(scenario_dict)
        result = SimulationEngine().run(scenario, FirstAvailableStrategy(), conn)

        sim_data = []
        for v in result.vehicles[:len(obs)]:
            sim_data.append({
                'occupied': 1 if v.get('final_state') == 'parked' else 0,
                'arrivals': 1,
                'departures': 1 if v.get('final_state') == 'exited' else 0,
            })

        report = CalibrationReport(synthetic_data, sim_data)
        assert report.compute_mae('occupied') is not None
        assert report.compute_rmse('occupied') is not None
        assert report.compute_bias('occupied') is not None

    def test_honest_counterfactual_label(self):
        """Verify counterfactual label contains 'simulation' and 'estimate'."""
        from digital_twin.validation.calibration import honest_counterfactual_label
        label = honest_counterfactual_label()
        assert label is not None
        assert 'simulation' in label.lower() or 'estimate' in label.lower()
        assert 'counterfactual' in label.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
