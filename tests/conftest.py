"""
Global pytest fixtures.

Redirects SimulationEngine disk output (MetricsRecorder) to pytest's tmp_path
during tests, so the runs/ folder is never polluted by test artifacts.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `digital_twin` is importable
# regardless of how pytest is invoked (python -m pytest, pytest CLI, IDE).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _redirect_runs_to_tmp(tmp_path, monkeypatch):
    """
    Patch MetricsRecorder so every SimulationEngine created during a test
    writes to tmp_path instead of the real runs/ directory.
    """
    import digital_twin.simulation.engine as eng_module

    original_cls = eng_module.MetricsRecorder

    class _TmpRecorder(original_cls):
        def __init__(self, output_root=None, **kwargs):
            super().__init__(output_root=str(tmp_path / "runs"), **kwargs)

    monkeypatch.setattr(eng_module, "MetricsRecorder", _TmpRecorder)
