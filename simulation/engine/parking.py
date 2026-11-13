"""Parking assignment — occupancy tracking and search-time formula."""
from digital_twin.simulation.engine import SimulationEngine as _E


def search_time_seconds(occupancy_pct: float, base_search_sec: float = 120.0) -> float:
    """Search time formula: grows as lot fills up.

    t_search = base * (1 / (1 - occ)) where occ in [0, 1).
    Capped at 30 min when occ >= 0.99.

    Args:
        occupancy_pct: Lot occupancy as a fraction [0.0, 1.0).
        base_search_sec: Free search time in seconds (default 2 min).

    Returns:
        Expected parking search time in seconds.
    """
    return _E._search_time_sec(occupancy_pct, base_search_sec)


__all__ = ["search_time_seconds"]
