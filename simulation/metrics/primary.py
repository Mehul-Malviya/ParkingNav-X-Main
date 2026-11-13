"""Primary metrics — the 5 spec-required aggregates computed from a SimulationResult."""
from digital_twin.simulation.engine import SimulationResult


def compute_primary_metrics(result: SimulationResult) -> dict:
    """Return the 5 primary metrics dict from a finished SimulationResult.

    Keys returned:
        avg_search_time_min, avg_wait_time_min, avg_gate_queue,
        max_gate_queue, overflow_events_count, avg_travel_time_min,
        total_travel_distance_m, total_reassignments.
    """
    return {k: result.metrics[k] for k in result.metrics if k in {
        "avg_search_time_min",
        "avg_wait_time_min",
        "avg_gate_queue",
        "max_gate_queue",
        "overflow_events_count",
        "avg_travel_time_min",
        "total_travel_distance_m",
        "total_reassignments",
    }}


__all__ = ["compute_primary_metrics"]
