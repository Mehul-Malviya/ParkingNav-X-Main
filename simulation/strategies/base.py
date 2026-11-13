"""AllocationStrategy — abstract base class all strategies must implement."""
from digital_twin.simulation.strategy import (
    AllocationStrategy,
    AssignmentResult,
    CampusState,
    Vehicle,
)

__all__ = ["AllocationStrategy", "AssignmentResult", "Vehicle", "CampusState"]
