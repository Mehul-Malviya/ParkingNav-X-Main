"""Departures — dwell time sampling and vehicle exit scheduling."""
from digital_twin.simulation.engine import SimulationEngine as _E


def sample_dwell_minutes(
    vehicle_type: str | None,
    event_override_min: float | None,
    rng,
    vehicle_types_config: dict | None = None,
) -> float:
    """Sample dwell time (minutes) for one vehicle.

    Args:
        vehicle_type: Type key from scenario vehicle_types config, or None.
        event_override_min: Fixed dwell override from event_conditions, or None.
        rng: numpy Generator (per-run, never global random).
        vehicle_types_config: Scenario vehicle_types dict, or None.

    Returns:
        Dwell time in minutes (lognormal draw or override).
    """
    return _E._sample_dwell(vehicle_type, event_override_min, rng, vehicle_types_config)


__all__ = ["sample_dwell_minutes"]
