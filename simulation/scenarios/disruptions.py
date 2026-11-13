"""Disruptions — timed lot/gate/road closures applied mid-simulation."""
from digital_twin.simulation.state_manager import CampusState


def apply_timed_closures(state: CampusState, tick: int, closures: list[dict]) -> None:
    """Apply any closures scheduled to open or close at this tick.

    Args:
        state: Live campus state (mutated in place).
        tick: Current simulation tick (minute index).
        closures: List of closure dicts with keys: entity_type, entity_id,
                  close_at_tick, reopen_at_tick.
    """
    for c in closures:
        entity_type = c.get("entity_type")
        entity_id = c.get("entity_id")
        close_tick = c.get("close_at_tick", -1)
        reopen_tick = c.get("reopen_at_tick", -1)

        if close_tick == tick:
            state.apply_event({"type": f"close_{entity_type}", "id": entity_id})
        elif reopen_tick == tick:
            state.apply_event({"type": f"open_{entity_type}", "id": entity_id})


__all__ = ["apply_timed_closures"]
