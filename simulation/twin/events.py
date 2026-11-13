"""Event application — applies timed closures and demand events to CampusState."""
from digital_twin.simulation.state_manager import CampusState


def apply_event(state: CampusState, event: dict) -> CampusState:
    """Apply a single event dict to a cloned state and return the result."""
    return state.apply_event(event)


__all__ = ["apply_event"]
