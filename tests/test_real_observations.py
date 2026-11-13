"""Real occupancy ingestion: validation, provenance, live-forecast filtering and real-data training."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.observations import normalize_timestamp, real_demand_frame, record_observations
from digital_twin.prediction.engine import LIVE_MAX_AGE_MIN, fresh_live_fills
from digital_twin.prediction.features import MIN_REAL_POINTS, load_data, real_lots

HOSTEL = "vitap-lot-hostel"


def _conn():
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(Path(__file__).resolve().parent.parent / "configs" / "campus" / "vitap.yaml", conn)
    return conn


def _now_iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def test_timestamps_are_normalised_to_utc_and_naive_means_campus_time():
    assert normalize_timestamp("2026-11-13T12:00:00Z") == "2026-11-13 12:00:00"
    assert normalize_timestamp("2026-11-13T17:30:00+05:30") == "2026-11-13 12:00:00"
    assert normalize_timestamp("2026-11-13T17:30:00") == "2026-11-13 12:00:00"   # naive = IST


def test_invalid_rows_are_rejected_and_duplicates_skipped():
    conn = _conn()
    good = {"timestamp": "2026-11-13T09:00:00", "lot_id": HOSTEL, "occupied_spaces": 40, "source": "manual"}
    res = record_observations(conn, [
        good, good,
        {**good, "lot_id": "nope"},
        {**good, "occupied_spaces": 9999},
        {**good, "occupied_spaces": -1},
        {**good, "source": "guess"},
        {**good, "timestamp": "yesterday"},
        {"lot_id": HOSTEL},
    ])
    assert (res["accepted"], res["duplicates"], len(res["rejected"])) == (1, 1, 6)
    assert conn.execute("SELECT source FROM lot_occupancy_history").fetchone()[0] == "manual"


def test_only_real_sources_count_as_live():
    conn = _conn()
    record_observations(conn, [{"timestamp": _now_iso(2), "lot_id": HOSTEL, "occupied_spaces": 100}], "simulation")
    record_observations(conn, [{"timestamp": _now_iso(1), "lot_id": HOSTEL, "occupied_spaces": 90}], "synthetic")
    assert fresh_live_fills(conn) == {}
    record_observations(conn, [{"timestamp": _now_iso(LIVE_MAX_AGE_MIN // 2), "lot_id": HOSTEL,
                                "occupied_spaces": 81}], "sensor")
    assert abs(fresh_live_fills(conn)[HOSTEL] - 81 / 162) < 1e-3


def test_real_data_replaces_synthetic_only_for_lots_with_enough_history():
    conn = _conn()
    start = datetime(2026, 10, 1, 0, 0)
    rows = [{"timestamp": (start + timedelta(minutes=15 * i)).isoformat(), "lot_id": HOSTEL,
             "occupied_spaces": 20 + (i % 96) // 4, "source": "sensor"} for i in range(MIN_REAL_POINTS)]
    rows += [{"timestamp": (start + timedelta(minutes=15 * i)).isoformat(), "lot_id": "vitap-lot-sports",
              "occupied_spaces": 10, "source": "sensor"} for i in range(50)]   # far too little
    assert record_observations(conn, rows)["rejected"] == []

    assert real_lots(load_data()) == []                       # no connection -> synthetic only
    df = load_data(conn)
    assert real_lots(df) == [HOSTEL]
    assert not df[df["lot_id"] == HOSTEL]["data_source"].ne("real").any()
    assert (df["lot_id"] == "vitap-lot-sports").any()          # sports keeps its synthetic rows


def test_gaps_in_real_data_are_not_interpolated():
    conn = _conn()
    t = datetime(2026, 10, 1, 8, 0)
    record_observations(conn, [
        {"timestamp": t.isoformat(), "lot_id": HOSTEL, "occupied_spaces": 10, "source": "manual"},
        {"timestamp": (t + timedelta(hours=1)).isoformat(), "lot_id": HOSTEL, "occupied_spaces": 30, "source": "manual"},
    ])
    df = real_demand_frame(conn)
    assert len(df) == 5 and df["fill_rate"].notna().sum() == 2


def test_write_endpoints_need_the_key_when_one_is_configured(monkeypatch):
    from fastapi.testclient import TestClient
    from digital_twin.api.app import app
    c = TestClient(app)
    body = {"timestamp": "2026-11-13T09:00:00", "lot_id": "nope", "occupied_spaces": 1}
    monkeypatch.setenv("PARKINGNAV_API_KEY", "secret")
    assert c.post("/observations", json=body).status_code == 401
    assert c.post("/predict/retrain").status_code == 401
    assert c.post("/observations", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/observations", json=body, headers={"X-API-Key": "secret"}).status_code == 404  # past the guard
    monkeypatch.delenv("PARKINGNAV_API_KEY")
    assert c.post("/observations", json=body).status_code == 404   # open when no key is set
