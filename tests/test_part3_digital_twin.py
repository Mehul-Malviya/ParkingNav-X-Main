from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
    return DigitalTwinService()


def test_valid_update_sequence_reflected_in_current_state(conn, twin):
    now = datetime.now(timezone.utc)
    twin.update_parking_state("sample", "sample-lot-1", 5, "manual", "REAL", now.isoformat(), conn, now=now)
    state = twin.get_current_state("sample", conn, now=now)
    lot = next(p for p in state["parking"] if p["parking_lot_id"] == "sample-lot-1")
    assert lot["occupied_spaces"] == 5
    assert lot["available_spaces"] == 13  # usable_capacity 18 - 5


def test_over_capacity_update_rejected_and_state_unchanged(conn, twin):
    now = datetime.now(timezone.utc)
    twin.update_parking_state("sample", "sample-lot-1", 5, "manual", "REAL", now.isoformat(), conn, now=now)
    with pytest.raises(ValueError, match="exceeds usable_capacity"):
        twin.update_parking_state("sample", "sample-lot-1", 999, "manual", "REAL", now.isoformat(), conn, now=now)
    state = twin.get_parking_state("sample", "sample-lot-1", conn, now=now)
    assert state["occupied_spaces"] == 5  # unchanged, never clamped


def test_freshness_transitions_fresh_aging_stale_with_mocked_clock(conn, twin):
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    twin.update_parking_state("sample", "sample-lot-1", 3, "manual", "REAL", t0.isoformat(), conn, now=t0)

    fresh_check = twin.get_parking_state("sample", "sample-lot-1", conn, now=t0 + timedelta(minutes=2))
    assert fresh_check["freshness_state"] == "FRESH"

    aging_check = twin.get_parking_state("sample", "sample-lot-1", conn, now=t0 + timedelta(minutes=15))
    assert aging_check["freshness_state"] == "AGING"

    stale_check = twin.get_parking_state("sample", "sample-lot-1", conn, now=t0 + timedelta(minutes=45))
    assert stale_check["freshness_state"] == "STALE"


def test_never_observed_parking_lot_is_unknown_freshness(conn, twin):
    assert twin.get_parking_state("sample", "sample-lot-2", conn) is None


def test_snapshot_reconstructs_exact_state_at_that_timestamp(conn, twin):
    now = datetime.now(timezone.utc)
    twin.update_parking_state("sample", "sample-lot-1", 4, "manual", "REAL", now.isoformat(), conn, now=now)
    snapshot_id = twin.snapshot_now("sample", conn, timestamp="t=100")

    twin.update_parking_state("sample", "sample-lot-1", 9, "manual", "REAL", now.isoformat(), conn, now=now)

    history = twin.get_state_history("sample", None, None, conn)
    snapshot = next(h for h in history if h["snapshot_id"] == snapshot_id)
    lot_in_snapshot = next(p for p in snapshot["full_state"]["parking"] if p["parking_lot_id"] == "sample-lot-1")
    assert lot_in_snapshot["occupied_spaces"] == 4  # the value AT snapshot time, not current


def test_update_missing_source_or_provenance_rejected(conn, twin):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="source.*provenance"):
        twin.update_parking_state("sample", "sample-lot-1", 5, "", "REAL", now.isoformat(), conn, now=now)


def test_two_campuses_state_never_leaks(conn, twin):
    load_campus_config(CONFIGS / "vitap.yaml", conn)
    now = datetime.now(timezone.utc)
    twin.update_parking_state("sample", "sample-lot-1", 2, "manual", "REAL", now.isoformat(), conn, now=now)
    twin.update_parking_state("vitap", "vitap-lot-academic-main", 7, "manual", "REAL", now.isoformat(), conn, now=now)

    sample_state = twin.get_current_state("sample", conn, now=now)
    vitap_state = twin.get_current_state("vitap", conn, now=now)

    sample_lot_ids = {p["parking_lot_id"] for p in sample_state["parking"]}
    vitap_lot_ids = {p["parking_lot_id"] for p in vitap_state["parking"]}
    assert sample_lot_ids.isdisjoint(vitap_lot_ids)


def test_negative_gate_queue_rejected(conn, twin):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="cannot be negative"):
        twin.update_gate_state("sample", "sample-gate-1", -1, 0, "manual", "REAL", now.isoformat(), conn, now=now)


if __name__ == "__main__":
    print("Run with pytest: python -m pytest test_part3_digital_twin.py -v")
