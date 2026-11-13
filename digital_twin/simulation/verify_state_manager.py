"""
Verification script for Part 2: Digital Twin State Manager.

Run as: python -m digital_twin.simulation.verify_state_manager
"""

import json
from digital_twin.simulation.state_manager import (
    CampusState, ParkingLotState, GateState, RoadState, VehicleStateEnum
)


def build_campus() -> CampusState:
    campus = CampusState(
        timestamp="2026-01-01T08:00:00",
        scenario_id="verify-001",
        seed=42,
        lots={
            "P1": ParkingLotState(id="P1", capacity=50, occupied=0, reserved_free=0, status="open"),
            "P2": ParkingLotState(id="P2", capacity=30, occupied=0, reserved_free=0, status="open"),
            "P3": ParkingLotState(id="P3", capacity=20, occupied=0, reserved_free=0, status="open"),
        },
        gates={
            "G1": GateState(id="G1", status="open", queue_length=0, service_rate_vph=120.0),
            "G2": GateState(id="G2", status="open", queue_length=0, service_rate_vph=90.0),
        },
        roads={
            "R1": RoadState(id="R1", status="open", vehicle_count=0, capacity_vph=200, travel_time_sec=60.0),
            "R2": RoadState(id="R2", status="open", vehicle_count=0, capacity_vph=150, travel_time_sec=45.0),
        },
    )
    return campus


def main():
    print("=" * 60)
    print("State Manager Verification")
    print("=" * 60)

    # ── Step 1: Initial snapshot ──────────────────────────────────────────────
    print("\n[1] Building campus and checking initial snapshot...")
    campus = build_campus()
    snap = campus.snapshot()
    print(json.dumps({k: v for k, v in snap.items() if k not in ("event_log",)}, indent=2))

    for lot_id in ("P1", "P2", "P3"):
        assert snap["lots"][lot_id]["occupied"] == 0, f"{lot_id} occupied != 0"
        assert snap["lots"][lot_id]["available"] == snap["lots"][lot_id]["capacity"]
    for gate_id in ("G1", "G2"):
        assert snap["gates"][gate_id]["queue_length"] == 0
    print("  PASS: initial state correct")

    # ── Step 2: Park 10 vehicles in P1 ───────────────────────────────────────
    print("\n[2] Applying vehicle lifecycle events for 10 vehicles to P1...")
    for i in range(10):
        vid = f"V{i:03d}"
        campus.apply_event({"type": "vehicle_arrived", "tick": i, "vehicle_id": vid,
                            "vehicle_type": "car", "arrival_time": i,
                            "entry_gate": "G1", "destination_zone": "Z1",
                            "assigned_lot": "P1", "route": ["R1"]})
        campus.apply_event({"type": "gate_served", "tick": i, "vehicle_id": vid, "gate_id": "G1"})
        campus.apply_event({"type": "entered_road", "tick": i, "vehicle_id": vid, "road_id": "R1"})
        campus.apply_event({"type": "reached_lot", "tick": i, "vehicle_id": vid, "road_id": "R1"})
        campus.apply_event({"type": "parked", "tick": i, "vehicle_id": vid, "lot_id": "P1"})

    assert campus.lots["P1"].occupied == 10, f"P1 occupied={campus.lots['P1'].occupied} != 10"
    assert campus.lots["P1"].available == 40, f"P1 available={campus.lots['P1'].available} != 40"
    assert campus.lots["P2"].occupied == 0, "P2 should be unchanged"
    assert campus.lots["P3"].occupied == 0, "P3 should be unchanged"
    print(f"  P1 occupied={campus.lots['P1'].occupied}, available={campus.lots['P1'].available}")
    print("  PASS: 10 vehicles parked in P1 correctly")

    # ── Step 3: lot_closed on P1 ─────────────────────────────────────────────
    print("\n[3] Closing P1...")
    campus.apply_event({"type": "lot_closed", "tick": 10, "lot_id": "P1"})
    assert campus.lots["P1"].status == "closed", f"P1 status={campus.lots['P1'].status}"
    assert campus.lots["P1"].occupied == 10, "P1 occupied should still be 10 after closing"
    print(f"  P1 status={campus.lots['P1'].status}, occupied={campus.lots['P1'].occupied}")
    print("  PASS: P1 closed, occupied unchanged")

    # ── Step 4: clone() independence ─────────────────────────────────────────
    print("\n[4] Testing clone() independence...")
    cloned = campus.clone()
    cloned.lots["P1"].occupied = 99
    assert campus.lots["P1"].occupied == 10, (
        f"Original P1 occupied should be 10, got {campus.lots['P1'].occupied}"
    )
    print(f"  Clone P1 occupied={cloned.lots['P1'].occupied}, original P1 occupied={campus.lots['P1'].occupied}")
    print("  PASS: clone is fully independent")

    # ── Step 5: event_log count ──────────────────────────────────────────────
    print("\n[5] Checking event_log...")
    print(f"  event_log has {len(campus.event_log)} entries")
    # 10 vehicles × 5 events each + some gate/road sub-logs + 1 lot_closed = many entries
    # At minimum: 10 vehicle_arrived + 10×gate + 10×entered_road + 10×road(enter) + 10×reached_lot + 10×road(exit) + 10×parked + 10×lot_parked + 1 lot_closed = ~81
    assert len(campus.event_log) >= 50, f"Expected >= 50 log entries, got {len(campus.event_log)}"
    for entry in campus.event_log[:3]:
        print(f"  {entry}")
    print("  PASS: event_log has sufficient entries")

    # ── Step 6: invariants() raises on violation ──────────────────────────────
    print("\n[6] Testing invariants() raises on forced violation...")
    # First reopen P1 so the SCHEDULED-to-closed check doesn't fire
    campus.lots["P1"].status = "open"
    # Force a violation: occupied > capacity
    campus.lots["P1"].occupied = 999
    raised = False
    try:
        campus.invariants()
    except AssertionError as exc:
        raised = True
        print(f"  AssertionError raised as expected: {exc}")
    assert raised, "invariants() should have raised AssertionError for occupied > capacity"
    print("  PASS: invariants() correctly detected violation")

    # ── Done ──────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
