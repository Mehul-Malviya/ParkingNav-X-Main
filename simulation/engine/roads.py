"""Road travel times — BPR (Bureau of Public Roads) congestion function.

t = t0 * (1 + 0.15 * (volume / capacity) ** 4)
"""
from digital_twin.simulation.engine import SimulationEngine as _E


def bpr_travel_time(free_flow_sec: float, volume: float, capacity: float) -> float:
    """BPR travel time for one road segment.

    Args:
        free_flow_sec: Free-flow travel time in seconds.
        volume: Current vehicle volume on this segment.
        capacity: Road capacity (vehicles per hour or same unit as volume).

    Returns:
        Congested travel time in seconds.
    """
    return _E._bpr_travel_time(free_flow_sec, volume, capacity)


__all__ = ["bpr_travel_time"]
