"""
Optional SimPy gate servers (scenario.gate_model == "simpy").

Each gate is a multi-server queue: `lanes` servers, each taking `service_sec` per vehicle,
FIFO. Lanes are derived from the gate's configured capacity (veh/min) using the documented
ASSUMED rate of 3 veh/min/lane (docs/member1/assumptions.md #12-13): 6 veh/min = 2 lanes x 20 s.

Unlike the default tick model (capacity x dt credit, vehicle admitted the moment it is served),
a vehicle here is admitted when its service COMPLETES, so an empty gate still costs one service
time. The engine advances SimPy to each tick boundary and admits whatever finished in the tick.
Deterministic: fixed service time, no random draws.
"""

import simpy

RATE_PER_LANE_VEH_PER_MIN = 3.0   # ASSUMED, same basis as assumptions #12-13


def lanes_for_capacity(capacity_veh_per_min: float) -> int:
    return max(1, round(capacity_veh_per_min / RATE_PER_LANE_VEH_PER_MIN))


class SimpyGates:
    def __init__(self, capacities: dict):
        self.env = simpy.Environment()
        self.lanes = {g: lanes_for_capacity(c) for g, c in capacities.items()}
        self.service_sec = {g: 60.0 / (c / self.lanes[g]) if c > 0 else float("inf") for g, c in capacities.items()}
        self.resources = {g: simpy.Resource(self.env, capacity=self.lanes[g]) for g in capacities}
        self.pending = {g: {} for g in capacities}   # vehicle_id -> process (waiting or in service)
        self._done = []                               # [(vehicle_id, finish_time_s)]

    def _proc(self, gate_id, vehicle_id):
        try:
            with self.resources[gate_id].request() as req:
                yield req
                yield self.env.timeout(self.service_sec[gate_id])
            self._done.append((vehicle_id, self.env.now))
            self.pending[gate_id].pop(vehicle_id, None)
        except simpy.Interrupt:
            self.pending[gate_id].pop(vehicle_id, None)

    def join(self, gate_id, vehicle_id):
        self.pending[gate_id][vehicle_id] = self.env.process(self._proc(gate_id, vehicle_id))

    def advance(self, until_sec):
        """Run to `until_sec`; return vehicle_ids whose service completed (in completion order)."""
        # SimPy's run(until=t) excludes events scheduled exactly at t; the epsilon makes a vehicle that
        # finishes exactly on a tick boundary count in that tick.
        if until_sec + 1e-9 > self.env.now:
            self.env.run(until=until_sec + 1e-9)
        done, self._done = self._done, []
        return [v for v, _ in done]

    def queue_length(self, gate_id):
        return len(self.pending[gate_id])

    def close_gate(self, gate_id, alt_gate_id):
        """Gate closed: pending vehicles (FIFO order) are re-queued at an open gate."""
        moved = list(self.pending[gate_id])
        for vid in moved:
            self.pending[gate_id][vid].interrupt()
        while self.env.peek() <= self.env.now:   # deliver the interrupts at the current time (no time advance)
            self.env.step()
        for vid in moved:
            self.join(alt_gate_id, vid)
        return moved
