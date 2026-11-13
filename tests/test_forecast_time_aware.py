"""Forecasts follow the campus clock and recent live occupancy, but ONLY when asked to.

The simulation calls the predictor without any time context; that path must stay exactly the old
static behaviour, otherwise seeded experiments stop being reproducible.
The underlying data is still SYNTHETIC; these tests are about behaviour, not realism.
"""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

import digital_twin.api.app as api
from digital_twin.db import apply_migrations, get_connection
from digital_twin.prediction.engine import (
    LIVE_HALF_LIFE_MIN, LIVE_MAX_AGE_MIN, fresh_live_fills, forecast_context, get_predictor,
)

ACADEMIC = "vitap-lot-academic-main"
HOSTEL = "vitap-lot-hostel"
MONDAY = dt.datetime(2026, 11, 9)   # a Monday
SATURDAY = dt.datetime(2026, 11, 14)


@pytest.fixture(scope="module")
def predictor():
    return get_predictor()


def test_default_call_is_static_and_ignores_the_clock(predictor):
    """What the simulation uses: no time context -> identical results every call."""
    a = {l: predictor.predict(l, 15)["fill_rate"] for l in (ACADEMIC, HOSTEL)}
    b = {l: predictor.predict(l, 15)["fill_rate"] for l in (ACADEMIC, HOSTEL)}
    assert a == b
    # values the committed experiments were produced with
    assert a[ACADEMIC] == pytest.approx(0.198, abs=0.005)
    assert a[HOSTEL] == pytest.approx(0.114, abs=0.005)
    assert "basis" not in predictor.predict(ACADEMIC, 15)
    snap1 = predictor.get_forecast_snapshot(horizon_minutes=15)["lot_fill_rates"]
    snap2 = predictor.get_forecast_snapshot(horizon_minutes=15)["lot_fill_rates"]
    assert snap1 == snap2


def test_forecast_follows_the_time_of_day(predictor):
    night = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=3))["fill_rate"]
    peak = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=9, minute=30))["fill_rate"]
    evening = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=22))["fill_rate"]
    assert peak - night > 0.4, "morning peak should be far above the night level"
    assert peak > evening
    again = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=9, minute=30))["fill_rate"]
    assert again == peak, "the same time must give the same forecast"


def test_weekend_differs_from_weekday(predictor):
    mon = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=10))["fill_rate"]
    sat = predictor.predict(ACADEMIC, 15, at=SATURDAY.replace(hour=10))["fill_rate"]
    assert mon - sat > 0.3


def test_basis_names_the_slot_and_whether_live_data_was_used(predictor):
    r = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=9, minute=40))
    assert r["basis"]["slot"] == "Mon 09:30" and r["basis"]["live_fill_used"] is False
    r = predictor.predict(ACADEMIC, 15, at=MONDAY.replace(hour=9, minute=40), live_fill=0.5)
    assert r["basis"]["live_fill_used"] is True


def test_live_occupancy_adjusts_the_forecast_in_the_right_direction_and_fades(predictor):
    at = MONDAY.replace(hour=10)
    base = predictor.predict(HOSTEL, 15, at=at)["fill_rate"]
    high = predictor.predict(HOSTEL, 15, at=at, live_fill=0.95)["fill_rate"]
    low = predictor.predict(HOSTEL, 15, at=at, live_fill=0.0)["fill_rate"]
    assert high > base + 0.15, "much busier than normal must raise the forecast"
    assert low < base - 0.15, "much emptier than normal must lower the forecast"
    # a deviation fades with the horizon (half-life LIVE_HALF_LIFE_MIN)
    p15 = predictor.predict(HOSTEL, 15, at=at, live_fill=0.95)["fill_rate"] - base
    p60 = (predictor.predict(HOSTEL, 60, at=at, live_fill=0.95)["fill_rate"]
           - predictor.predict(HOSTEL, 60, at=at)["fill_rate"])
    assert 0 < p60 < p15
    assert LIVE_HALF_LIFE_MIN == 60


def test_forecast_stays_within_bounds_and_intervals_are_ordered(predictor):
    for live in (None, 0.0, 1.0):
        r = predictor.predict(HOSTEL, 15, at=MONDAY.replace(hour=10), live_fill=live)
        assert 0.0 <= r["lower_90"] <= r["fill_rate"] <= r["upper_90"] <= 1.0


def _conn():
    from pathlib import Path
    from digital_twin.config_loader import load_campus_config
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(Path(__file__).resolve().parent.parent / "configs" / "campus" / "vitap.yaml", conn)
    return conn


def test_only_fresh_recorded_occupancy_counts_as_live():
    conn = _conn()
    conn.execute("INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate, recorded_at) "
                 "VALUES (?, 81, 0.5, datetime('now', '-5 minutes'))", (HOSTEL,))
    conn.execute("INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate, recorded_at) "
                 "VALUES (?, 50, 0.46, datetime('now', ?))", (ACADEMIC, f"-{LIVE_MAX_AGE_MIN + 60} minutes"))
    conn.commit()
    live = fresh_live_fills(conn)
    assert HOSTEL in live and abs(live[HOSTEL] - 81 / 162) < 1e-3
    assert ACADEMIC not in live, "an old snapshot must not be treated as live"
    _pred, basis = forecast_context(conn)
    assert basis["live_lots"] == [HOSTEL] and basis["data"].startswith("synthetic")
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "fc.db")
    with TestClient(api.app) as c:
        yield c


def test_predict_all_reports_its_basis_and_changes_with_as_of(client):
    night = client.get("/predict/all", params={"as_of": "2026-11-09T03:00"}).json()
    peak = client.get("/predict/all", params={"as_of": "2026-11-09T09:30"}).json()
    assert night["forecast_basis"]["as_of"] == "2026-11-09T03:00"
    assert night["forecast_basis"]["live_lots"] == []          # a what-if time never mixes in live data
    fr = lambda d: {p["lot_id"]: p["predicted_fill_rate"] for p in d["predictions"]}
    assert fr(peak)[ACADEMIC] - fr(night)[ACADEMIC] > 0.4


def test_predict_all_without_as_of_uses_the_campus_clock(client):
    body = client.get("/predict/all").json()
    stamp = dt.datetime.fromisoformat(body["forecast_basis"]["as_of"])
    assert abs((stamp - dt.datetime.utcnow() - dt.timedelta(hours=5, minutes=30)).total_seconds()) < 300
    assert body["forecast_basis"]["timezone"] == "Asia/Kolkata"


def test_risk_forecast_and_occupancy_endpoints_carry_the_basis(client):
    assert "forecast_basis" in client.get("/risk/forecast", params={"as_of": "2026-11-09T09:30"}).json()
    occ = client.get("/predict/occupancy", params={"lot_id": ACADEMIC, "as_of": "2026-11-09T09:30"}).json()
    assert occ["forecast_basis"]["as_of"] == "2026-11-09T09:30"
