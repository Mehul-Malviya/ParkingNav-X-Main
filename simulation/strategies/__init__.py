"""Allocation strategies — base interface and built-in implementations."""
from simulation.strategies.base import AllocationStrategy, AssignmentResult
from simulation.strategies.first_available import FirstAvailableStrategy
from simulation.strategies.nearest_available import NearestAvailableStrategy

__all__ = [
    "AllocationStrategy",
    "AssignmentResult",
    "FirstAvailableStrategy",
    "NearestAvailableStrategy",
]
