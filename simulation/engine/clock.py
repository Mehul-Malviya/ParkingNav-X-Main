"""Simulation clock — converts between ticks, minutes, and wall-clock time."""


def tick_to_minutes(tick: int, time_step_sec: int = 10) -> float:
    """Convert engine tick index to simulation minutes elapsed."""
    return tick * time_step_sec / 60.0


def minutes_to_tick(minutes: float, time_step_sec: int = 10) -> int:
    """Convert simulation minutes to the nearest engine tick index."""
    return round(minutes * 60.0 / time_step_sec)


def ticks_per_interval(interval_minutes: int = 15, time_step_sec: int = 10) -> int:
    """Number of engine ticks in one aggregation interval (default 15 min)."""
    return (interval_minutes * 60) // time_step_sec


__all__ = ["tick_to_minutes", "minutes_to_tick", "ticks_per_interval"]
