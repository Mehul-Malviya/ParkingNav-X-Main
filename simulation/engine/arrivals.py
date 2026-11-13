"""Arrival generation — NHPP arrival stream using a numpy Generator seeded per run.

The engine calls _generate_arrivals() internally; this module exposes the
function for unit testing and for Member 3's forecast integration.
"""
from digital_twin.simulation.engine import SimulationEngine as _E
import numpy as np


def generate_arrivals(
    vehicle_count: int,
    duration_minutes: int,
    profile: dict,
    rng: np.random.Generator,
) -> list[int]:
    """Return sorted list of arrival ticks (minute indices) for vehicle_count vehicles.

    Args:
        vehicle_count: Total vehicles to schedule.
        duration_minutes: Simulation horizon in minutes.
        profile: Arrival rate profile dict (type='constant'|'profile', points=[...]).
        rng: Per-run numpy Generator (never global random).

    Returns:
        Sorted list of integer minute ticks, length == vehicle_count.
    """
    return _E._sample_arrivals(vehicle_count, duration_minutes, profile, rng)


__all__ = ["generate_arrivals"]
