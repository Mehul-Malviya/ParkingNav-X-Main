"""CLI entry point — thin re-export.

Usage:
    python -m simulation run --campus vitap --scenario E1_normal_day --strategy nearest --seed 7
    python -m simulation validate --campus vitap
    python -m simulation make-dataset --campus vitap --scenarios E1_normal_day --seeds 0-4 --output data/ml.csv
"""  # noqa: E501
from digital_twin.simulation.cli import main  # noqa: F401
