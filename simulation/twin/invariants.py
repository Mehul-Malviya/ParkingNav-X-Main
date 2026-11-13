"""Invariant checks — verifies occupancy, capacity, and queue constraints."""
from digital_twin.simulation.state_manager import CampusState


def check_invariants(state: CampusState) -> list[str]:
    """Return list of violated invariants (empty = all OK)."""
    return state.invariants()


__all__ = ["check_invariants"]
