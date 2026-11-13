"""Gate queues — M/M/c Erlang-C theoretical wait and SimPy gate model."""
from digital_twin.simulation.gate_simpy import GateSimPy
from digital_twin.simulation.engine import SimulationEngine as _E


def erlang_c_wait(arrival_rate: float, service_rate: float, lanes: int) -> float:
    """Theoretical mean wait (seconds) via Erlang-C formula for M/M/c queue.

    Args:
        arrival_rate: Vehicles per second arriving at gate.
        service_rate: Vehicles per second each lane can serve.
        lanes: Number of parallel service lanes.

    Returns:
        Expected wait time in seconds (0.0 if utilisation < 1).
    """
    return _E._erlang_c_wait(arrival_rate, service_rate, lanes)


__all__ = ["GateSimPy", "erlang_c_wait"]
