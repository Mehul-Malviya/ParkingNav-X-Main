"""
Phase 9 — Interfaces to Teammates

Tests for StateSnapshot and API functions exports.
"""

import json

from digital_twin.simulation.state_snapshot import (
    GateState,
    LotState,
    RoadState,
    StateSnapshot,
)


class TestStateSnapshot:
    """Test StateSnapshot export for Member 3."""

    def test_state_snapshot_creation(self):
        """StateSnapshot can be created and serialized."""
        lot = LotState(
            id="lot-1", capacity=100, occupied=50, available=50,
            reserved_free=5, status="open", inflow_5m=3, outflow_5m=2
        )

        gate = GateState(
            id="gate-1", queue_length=5, service_rate_veh_per_min=6,
            status="open", throughput_last_5min=28
        )

        road = RoadState(
            id="road-1", travel_time_sec=42.5, congestion_ratio=0.6,
            status="open", current_load=12, capacity=20
        )

        snapshot = StateSnapshot(
            sim_time=450,
            sim_time_iso="2026-10-04T15:30:00Z",
            lots=[lot],
            gates=[gate],
            roads=[road],
            pending_arrivals_by_gate={"gate-1": 15},
            active_events=[],
            active_disruptions=[],
            travel_time_matrix={"gate-1": {"lot-1": 42}},
            walk_time={"academic": {"lot-1": 120}},
        )

        assert snapshot.sim_time == 450
        assert len(snapshot.lots) == 1
        assert snapshot.lots[0].occupancy_ratio == 0.5

    def test_state_snapshot_to_dict(self):
        """StateSnapshot serializes to dict correctly."""
        lot = LotState(
            id="lot-1", capacity=100, occupied=50, available=50,
            reserved_free=5, status="open", inflow_5m=3, outflow_5m=2
        )

        snapshot = StateSnapshot(
            sim_time=450,
            sim_time_iso="2026-10-04T15:30:00Z",
            lots=[lot],
            gates=[],
            roads=[],
            pending_arrivals_by_gate={},
            active_events=[],
            active_disruptions=[],
            travel_time_matrix={},
            walk_time={},
        )

        data = snapshot.to_dict()

        assert data["sim_time"] == 450
        assert data["sim_time_iso"] == "2026-10-04T15:30:00Z"
        assert len(data["lots"]) == 1
        assert data["lots"][0]["id"] == "lot-1"

    def test_state_snapshot_to_json(self):
        """StateSnapshot serializes to JSON string."""
        lot = LotState(
            id="lot-1", capacity=100, occupied=50, available=50,
            reserved_free=5, status="open", inflow_5m=3, outflow_5m=2
        )

        snapshot = StateSnapshot(
            sim_time=450,
            sim_time_iso="2026-10-04T15:30:00Z",
            lots=[lot],
            gates=[],
            roads=[],
            pending_arrivals_by_gate={},
            active_events=[],
            active_disruptions=[],
            travel_time_matrix={},
            walk_time={},
        )

        json_str = snapshot.to_json()
        data = json.loads(json_str)

        assert data["sim_time"] == 450
        assert len(data["lots"]) == 1

    def test_state_snapshot_from_dict(self):
        """StateSnapshot can be reconstructed from dict."""
        data = {
            "sim_time": 450,
            "sim_time_iso": "2026-10-04T15:30:00Z",
            "lots": [
                {
                    "id": "lot-1",
                    "capacity": 100,
                    "occupied": 50,
                    "available": 50,
                    "reserved_free": 5,
                    "status": "open",
                    "inflow_5m": 3,
                    "outflow_5m": 2,
                }
            ],
            "gates": [],
            "roads": [],
            "pending_arrivals_by_gate": {},
            "active_events": [],
            "active_disruptions": [],
            "travel_time_matrix": {},
            "walk_time": {},
        }

        snapshot = StateSnapshot.from_dict(data)

        assert snapshot.sim_time == 450
        assert len(snapshot.lots) == 1
        assert snapshot.lots[0].id == "lot-1"

    def test_state_snapshot_fork(self):
        """StateSnapshot.fork() creates independent copy."""
        lot = LotState(
            id="lot-1", capacity=100, occupied=50, available=50,
            reserved_free=5, status="open", inflow_5m=3, outflow_5m=2
        )

        snapshot = StateSnapshot(
            sim_time=450,
            sim_time_iso="2026-10-04T15:30:00Z",
            lots=[lot],
            gates=[],
            roads=[],
            pending_arrivals_by_gate={},
            active_events=[],
            active_disruptions=[],
            travel_time_matrix={},
            walk_time={},
        )

        fork = snapshot.fork()

        # Modify fork
        fork.lots[0].occupied = 75

        # Original unchanged
        assert snapshot.lots[0].occupied == 50
        assert fork.lots[0].occupied == 75

    def test_state_snapshot_get_lot_by_id(self):
        """StateSnapshot can query lots by ID."""
        lot1 = LotState(
            id="lot-1", capacity=100, occupied=50, available=50,
            reserved_free=5, status="open", inflow_5m=3, outflow_5m=2
        )
        lot2 = LotState(
            id="lot-2", capacity=80, occupied=40, available=40,
            reserved_free=4, status="open", inflow_5m=2, outflow_5m=1
        )

        snapshot = StateSnapshot(
            sim_time=450,
            sim_time_iso="2026-10-04T15:30:00Z",
            lots=[lot1, lot2],
            gates=[],
            roads=[],
            pending_arrivals_by_gate={},
            active_events=[],
            active_disruptions=[],
            travel_time_matrix={},
            walk_time={},
        )

        found = snapshot.get_lot_by_id("lot-2")
        assert found is not None
        assert found.capacity == 80

        not_found = snapshot.get_lot_by_id("lot-3")
        assert not_found is None

    def test_lot_occupancy_ratio(self):
        """LotState.occupancy_ratio computed correctly."""
        lot = LotState(
            id="lot-1", capacity=100, occupied=75, available=25,
            reserved_free=5, status="open", inflow_5m=3, outflow_5m=2
        )

        assert lot.occupancy_ratio == 0.75

    def test_lot_occupancy_ratio_empty_capacity(self):
        """LotState.occupancy_ratio handles zero capacity."""
        lot = LotState(
            id="lot-1", capacity=0, occupied=0, available=0,
            reserved_free=0, status="open", inflow_5m=0, outflow_5m=0
        )

        assert lot.occupancy_ratio == 0.0


if __name__ == "__main__":
    print("Run with: python -m pytest tests/test_phase9_interfaces.py -v")
