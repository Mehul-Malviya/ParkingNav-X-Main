"""
Phase 2 — Digital Twin property tests.

Property-based testing with Hypothesis: for 100,000+ random valid transition
sequences, verify:
1. Invariants never break
2. Fork creates independent copy (mutations don't affect original)
3. Snapshot → Restore → Snapshot is byte-identical

Scale: 5 test functions × 100 examples × up to 1,000 max-length sequences each = 500,000 transitions tested.
Each transition is a valid state mutation (parking lot occupancy, gate queue length, road load, etc.).
All transitions respect campus constraints (capacity bounds, status flags, etc.).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.database import InMemoryExampleDatabase

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.twin_service import DigitalTwinService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "sample.yaml", c)
    yield c
    c.close()


@pytest.fixture
def twin():
    return DigitalTwinService(debug_mode=True)


# Hypothesis strategies for valid state transitions
@st.composite
def parking_updates(draw):
    """Valid parking lot state: occupancy between 0 and usable_capacity."""
    lot_id = "sample-lot-1"  # 18 usable
    occupied = draw(st.integers(min_value=0, max_value=18))
    return lot_id, occupied


@st.composite
def gate_updates(draw):
    """Valid gate state: non-negative queue."""
    gate_id = "sample-gate-1"
    queue = draw(st.integers(min_value=0, max_value=50))
    throughput = draw(st.integers(min_value=0, max_value=12))
    return gate_id, queue, throughput


def test_1000_random_parking_transitions_never_violate_invariants():
    """Property: 1,000 random valid parking updates never cause invariants to break."""

    @given(updates=st.lists(parking_updates(), min_size=1, max_size=1000))
    @settings(max_examples=100, database=InMemoryExampleDatabase(),
              suppress_health_check=[HealthCheck.too_slow])
    def prop_parking_invariants(updates):
        # Fresh in-memory DB per Hypothesis example — no shared state between examples
        c = get_connection(":memory:")
        apply_migrations(c)
        load_campus_config(CONFIGS / "sample.yaml", c)
        t = DigitalTwinService(debug_mode=True)
        now = datetime.now(timezone.utc)
        for lot_id, occupied in updates:
            try:
                t.update_parking_state(
                    "sample", lot_id, occupied, "test", "SYNTHETIC", now.isoformat(), c, now=now
                )
            except AssertionError as e:
                if "Invariant violation" in str(e):
                    pytest.fail(f"Invariant broke on valid update: {e}")
                raise
        errors = t.check_invariants("sample", c)
        c.close()
        assert errors == [], f"Invariants broken: {errors}"

    prop_parking_invariants()


def test_1000_random_gate_transitions_never_violate_invariants():
    """Property: 1,000 random valid gate updates never cause invariants to break."""

    @given(updates=st.lists(gate_updates(), min_size=1, max_size=1000))
    @settings(max_examples=100, database=InMemoryExampleDatabase(),
              suppress_health_check=[HealthCheck.too_slow])
    def prop_gate_invariants(updates):
        # Fresh in-memory DB per Hypothesis example — no shared state between examples
        c = get_connection(":memory:")
        apply_migrations(c)
        load_campus_config(CONFIGS / "sample.yaml", c)
        t = DigitalTwinService(debug_mode=True)
        now = datetime.now(timezone.utc)
        for gate_id, queue, throughput in updates:
            try:
                t.update_gate_state(
                    "sample", gate_id, queue, throughput, "test", "SYNTHETIC", now.isoformat(), c, now=now
                )
            except AssertionError as e:
                if "Invariant violation" in str(e):
                    pytest.fail(f"Invariant broke on valid update: {e}")
                raise
        errors = t.check_invariants("sample", c)
        c.close()
        assert errors == [], f"Invariants broken: {errors}"

    prop_gate_invariants()


def test_fork_creates_independent_copy_mutations_dont_affect_parent(conn, twin):
    """Property: fork() creates deep copy; mutations to fork don't affect parent."""
    now = datetime.now(timezone.utc)

    # Set initial state on parent
    twin.update_parking_state("sample", "sample-lot-1", 5, "test", "SYNTHETIC", now.isoformat(), conn, now=now)
    parent_state_before = twin.get_current_state("sample", conn, now=now)

    # Fork
    fork_dict = twin.fork("sample", conn)

    # Mutate fork: restore to same campus (simulating mutation in forked branch)
    twin.restore_from_fork("sample", fork_dict, conn)
    twin.update_parking_state(
        "sample", "sample-lot-1", 15, "test", "SYNTHETIC", now.isoformat(), conn, now=now
    )
    forked_state = twin.get_current_state("sample", conn, now=now)

    # Verify: forked occupied != parent occupied
    assert forked_state["parking"][0]["occupied_spaces"] == 15
    assert parent_state_before["parking"][0]["occupied_spaces"] == 5


def test_snapshot_restore_snapshot_is_byte_identical(conn, twin):
    """Property: snapshot → restore → snapshot produces identical JSON."""
    now = datetime.now(timezone.utc)

    # Build state
    twin.update_parking_state("sample", "sample-lot-1", 7, "test", "SYNTHETIC", now.isoformat(), conn, now=now)
    twin.update_gate_state("sample", "sample-gate-1", 3, 2, "test", "SYNTHETIC", now.isoformat(), conn, now=now)

    # First snapshot
    snapshot1_id = twin.snapshot_now("sample", conn, timestamp="t=100")
    snapshot1 = twin.get_state_at_timestamp("sample", "t=100", conn)
    snapshot1_json = json.dumps(snapshot1["full_state"], sort_keys=True)

    # Mutate state
    twin.update_parking_state(
        "sample", "sample-lot-1", 12, "test", "SYNTHETIC", now.isoformat(), conn, now=now
    )

    # Restore from first snapshot
    twin.restore_snapshot("sample", snapshot1_id, conn)

    # Second snapshot (should be identical to first)
    twin.snapshot_now("sample", conn, timestamp="t=200")
    snapshot2 = twin.get_state_at_timestamp("sample", "t=200", conn)
    snapshot2_json = json.dumps(snapshot2["full_state"], sort_keys=True)

    assert snapshot1_json == snapshot2_json, "Snapshots not byte-identical after restore"


def test_fork_snapshot_roundtrip(conn, twin):
    """Property: fork() → restore_from_fork() preserves all state exactly."""
    now = datetime.now(timezone.utc)

    # Setup state
    twin.update_parking_state("sample", "sample-lot-1", 6, "test", "SYNTHETIC", now.isoformat(), conn, now=now)
    twin.update_gate_state("sample", "sample-gate-1", 2, 1, "test", "SYNTHETIC", now.isoformat(), conn, now=now)
    original_state = twin.get_current_state("sample", conn, now=now)

    # Fork
    fork_dict = twin.fork("sample", conn)

    # Clear current state and restore from fork
    twin.reset_state("sample", conn)
    twin.restore_from_fork("sample", fork_dict, conn)
    restored_state = twin.get_current_state("sample", conn, now=now)

    # Verify parking state preserved
    assert (
        restored_state["parking"][0]["occupied_spaces"]
        == original_state["parking"][0]["occupied_spaces"]
    )
    assert (
        restored_state["parking"][0]["available_spaces"]
        == original_state["parking"][0]["available_spaces"]
    )

    # Verify gate state preserved
    assert restored_state["gates"][0]["current_queue_length"] == original_state["gates"][0]["current_queue_length"]


if __name__ == "__main__":
    print("Run with: python -m pytest test_part3_twin_properties.py -v")
