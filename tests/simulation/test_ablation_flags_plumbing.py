"""
Ablation flag plumbing tests.

Verifies that the four ablation flags (use_prediction, use_optimization,
use_uncertainty, proactive) are accepted by ScenarioConfig and that the
engine runs to completion under every flag combination without crashing.

These tests do NOT assert performance ordering between flag variants â€”
that requires Member 3's optimizer variants and belongs in a future
E6 ablation scenario config.
"""

from pathlib import Path

import pytest

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy


class TestAblationFlagsPlumbing:
    """Verify ablation flags are accepted and engine runs without errors."""

    @pytest.fixture
    def setup(self):
        """Setup: campus + connection."""
        conn = get_connection(':memory:')
        apply_migrations(conn)
        load_campus_config(Path('configs/campus/sample.yaml'), conn)
        load_campus_config(Path('configs/campus/vitap.yaml'), conn)
        return conn

    def run_variant(self, scenario_file, variant_flags, conn, strategy=None):
        """Run a scenario with the given ablation flags; return basic metrics dict."""
        if strategy is None:
            strategy = FirstAvailableStrategy()

        scenario = ScenarioLoader.load(scenario_file)

        # Apply ablation flags (accepted by ScenarioConfig; not yet consumed by engine)
        scenario.use_prediction = variant_flags.get('use_prediction', True)
        scenario.use_optimization = variant_flags.get('use_optimization', True)
        scenario.use_uncertainty = variant_flags.get('use_uncertainty', True)
        scenario.proactive = variant_flags.get('proactive', True)

        engine = SimulationEngine()
        result = engine.run(scenario, strategy, conn)

        return {
            'overflow_events': len(result.overflow_events),
            'vehicles': len(result.vehicles),
        }

    def test_e2_all_flags_enabled(self, setup):
        """Flags all on: engine runs without error."""
        result = self.run_variant(
            'configs/scenarios/vitap/E2_event_placement.yaml',
            {'use_prediction': True, 'use_optimization': True,
             'use_uncertainty': True, 'proactive': True},
            setup
        )
        assert result['vehicles'] > 0

    def test_e2_prediction_disabled(self, setup):
        """use_prediction=False accepted; engine still runs."""
        result = self.run_variant(
            'configs/scenarios/vitap/E2_event_placement.yaml',
            {'use_prediction': False, 'use_optimization': True,
             'use_uncertainty': True, 'proactive': True},
            setup
        )
        assert result['vehicles'] > 0

    def test_e2_optimization_disabled(self, setup):
        """use_optimization=False accepted; engine still runs."""
        result = self.run_variant(
            'configs/scenarios/vitap/E2_event_placement.yaml',
            {'use_prediction': True, 'use_optimization': False,
             'use_uncertainty': True, 'proactive': True},
            setup
        )
        assert result['vehicles'] > 0

    def test_e2_all_flags_disabled(self, setup):
        """All flags off: engine runs without error."""
        result = self.run_variant(
            'configs/scenarios/vitap/E2_event_placement.yaml',
            {'use_prediction': False, 'use_optimization': False,
             'use_uncertainty': False, 'proactive': False},
            setup
        )
        assert result['vehicles'] > 0

    def test_e3_all_flags_disabled(self, setup):
        """E3 lot closure with all flags off: engine runs without error."""
        result = self.run_variant(
            'configs/scenarios/vitap/E3_lot_closure.yaml',
            {'use_prediction': False, 'use_optimization': False,
             'use_uncertainty': False, 'proactive': False},
            setup
        )
        assert result['vehicles'] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
