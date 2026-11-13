"""
Phase 3 tests: ablation flags consumed by ParkingNavXFullStrategy, and
noise injection produces differentiated results in E5.

All scenarios are SYNTHETIC. None claim real campus measurements.
"""
import yaml
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


# ─── helpers ────────────────────────────────────────────────────────────────

def _load_scenario(path, **overrides):
    raw = yaml.safe_load(open(ROOT / path))
    raw.update(overrides)
    return raw


def _small(base_raw, **overrides):
    """Shrink a scenario for fast unit-test runs."""
    raw = dict(base_raw)
    raw.update({"vehicle_count": 60, "duration_minutes": 120, "warmdown_minutes": 0})
    raw.update(overrides)
    return raw


# ─── Ablation flag tests ─────────────────────────────────────────────────────

class TestAblationFlags:

    def test_update_policy_stores_flags(self):
        from digital_twin.simulation.demo_strategies import ParkingNavXFullStrategy
        s = ParkingNavXFullStrategy()
        flags = {"use_prediction": False, "use_optimization": False,
                 "use_uncertainty": False, "proactive": False}
        s.update_policy({}, forecast=None, ablation_flags=flags)
        assert s._use_prediction is False
        assert s._use_optimization is False
        assert s._use_uncertainty is False
        assert s._proactive is False

    def test_update_policy_default_flags_true(self):
        from digital_twin.simulation.demo_strategies import ParkingNavXFullStrategy
        s = ParkingNavXFullStrategy()
        s.update_policy({}, forecast=None)  # no ablation_flags → all True
        assert s._use_prediction is True
        assert s._use_optimization is True
        assert s._use_uncertainty is True
        assert s._proactive is True

    def test_use_prediction_false_ignores_forecast(self):
        """When use_prediction=False, assign must not use forecast fill rates."""
        import networkx as nx
        from digital_twin.simulation.demo_strategies import ParkingNavXFullStrategy
        from digital_twin.simulation.strategy import CampusState, Vehicle, AssignmentResult

        s = ParkingNavXFullStrategy()
        flags = {"use_prediction": False, "use_optimization": False,
                 "use_uncertainty": False, "proactive": False}
        # Forecast says both lots are 95% full (would filter them out if used)
        forecast = {"lot_fill_rates": {"lot-a": 0.95, "lot-b": 0.95}}
        s.update_policy({}, forecast=forecast, ablation_flags=flags)

        G = nx.DiGraph()
        G.add_edge("gate-1", "lot-a", weight_distance_meters=100)
        G.add_edge("gate-1", "lot-b", weight_distance_meters=200)

        state = CampusState(
            campus_id="test",
            graph=G,
            parking_lots={
                "lot-a": {"status": "open", "usable_capacity": 100, "occupied_spaces": 20},
                "lot-b": {"status": "open", "usable_capacity": 100, "occupied_spaces": 30},
            },
            gates={"gate-1": {"status": "open", "capacity": 4, "queue_length": 0}},
            roads={},
        )
        vehicle = Vehicle(vehicle_id="v1", entry_gate="gate-1", destination_id=None, arrival_tick=0)
        result = s.assign(vehicle, state)
        # Should assign (current fill 20-30%, not forecast 95%)
        assert result.parking_lot_id in ("lot-a", "lot-b")

    def test_use_optimization_false_uses_vehicle_gate(self):
        """When use_optimization=False, gate_id in result must equal vehicle.entry_gate."""
        import networkx as nx
        from digital_twin.simulation.demo_strategies import ParkingNavXFullStrategy
        from digital_twin.simulation.strategy import CampusState, Vehicle

        s = ParkingNavXFullStrategy()
        flags = {"use_prediction": True, "use_optimization": False,
                 "use_uncertainty": False, "proactive": False}
        s.update_policy({}, forecast=None, ablation_flags=flags)

        G = nx.DiGraph()
        G.add_edge("gate-main", "lot-a", weight_distance_meters=100)
        G.add_edge("gate-alt",  "lot-a", weight_distance_meters=500)

        state = CampusState(
            campus_id="test",
            graph=G,
            parking_lots={"lot-a": {"status": "open", "usable_capacity": 50, "occupied_spaces": 5}},
            gates={
                "gate-main": {"status": "open", "capacity": 4, "queue_length": 0},
                "gate-alt":  {"status": "open", "capacity": 4, "queue_length": 0},
            },
            roads={},
        )
        vehicle = Vehicle(vehicle_id="v1", entry_gate="gate-main", destination_id=None, arrival_tick=0)
        result = s.assign(vehicle, state)
        # gate_id in result should be vehicle's own gate (no load-balancing redirect)
        assert result.gate_id == "gate-main"

    def test_e6_ablation_scenarios_loadable(self):
        """All E6 ablation YAMLs parse without error and have expected flags."""
        from digital_twin.simulation.scenario import ScenarioLoader

        scenarios = {
            "E6_ablation.yaml":   {"use_prediction": True,  "use_optimization": False, "use_uncertainty": False, "proactive": False},
            "E6_ablation_B.yaml": {"use_prediction": True,  "use_optimization": True,  "use_uncertainty": False, "proactive": False},
            "E6_ablation_C.yaml": {"use_prediction": True,  "use_optimization": True,  "use_uncertainty": True,  "proactive": False},
            "E6_ablation_D.yaml": {"use_prediction": True,  "use_optimization": True,  "use_uncertainty": True,  "proactive": True},
        }
        for fname, expected_flags in scenarios.items():
            path = ROOT / "configs" / "scenarios" / "vitap" / fname
            sc = ScenarioLoader.load(path)
            for flag, val in expected_flags.items():
                actual = getattr(sc, flag)
                assert actual == val, f"{fname}: expected {flag}={val}, got {actual}"


# ─── Noise injection tests ───────────────────────────────────────────────────

class TestNoiseInjection:

    def test_zero_noise_is_noop(self):
        from digital_twin.simulation.forecast_noise import ForecastNoiseInjector
        inj = ForecastNoiseInjector(noise_level=0.0, seed=42)
        fc = {"occupancy": 0.5, "queue": 3, "label": "test"}
        result = inj.perturb(fc)
        assert result["occupancy"] == 0.5
        assert result["queue"] == 3

    def test_nonzero_noise_changes_values(self):
        from digital_twin.simulation.forecast_noise import ForecastNoiseInjector
        inj = ForecastNoiseInjector(noise_level=0.20, seed=42)
        fc = {"occupancy": 0.5, "queue": 5}
        result = inj.perturb(fc)
        # With seed 42 and σ=0.20 at least one key should differ
        assert result["occupancy"] != 0.5 or result["queue"] != 5

    def test_noise_seeded_reproducible(self):
        from digital_twin.simulation.forecast_noise import ForecastNoiseInjector
        fc = {"occupancy": 0.6, "queue": 4}
        r1 = ForecastNoiseInjector(noise_level=0.15, seed=7).perturb(fc)
        r2 = ForecastNoiseInjector(noise_level=0.15, seed=7).perturb(fc)
        assert r1 == r2

    def test_noisy_values_stay_non_negative(self):
        from digital_twin.simulation.forecast_noise import ForecastNoiseInjector
        inj = ForecastNoiseInjector(noise_level=0.99, seed=0)
        for _ in range(50):
            result = inj.perturb({"occupancy": 0.01, "queue": 0.0})
            assert result["occupancy"] >= 0.0
            assert result["queue"] >= 0.0

    def test_e5_noise_scenarios_loadable(self):
        from digital_twin.simulation.scenario import ScenarioLoader
        files = {
            "E5_noise_0.yaml":  0.0,
            "E5_noise_10.yaml": 0.10,
            "E5_noise_20.yaml": 0.20,
        }
        for fname, expected_level in files.items():
            path = ROOT / "configs" / "scenarios" / "vitap" / fname
            sc = ScenarioLoader.load(path)
            assert abs(sc.prediction_error_injection_level - expected_level) < 1e-9, \
                f"{fname}: expected noise {expected_level}, got {sc.prediction_error_injection_level}"
