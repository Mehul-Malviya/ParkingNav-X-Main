
import pytest
from fastapi.testclient import TestClient

import digital_twin.api.app as api


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = api.ROOT

    monkeypatch.setattr(
        api,
        "DB_PATH",
        tmp_path / "test_digital_twin.db",
    )
    monkeypatch.setattr(
        api,
        "CAMPUS_YAML",
        root / "configs" / "campus" / "vitap.yaml",
    )

    with TestClient(api.app) as test_client:
        yield test_client


def test_root_returns_project_information(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["project"] == "ParkingNav-X"
    assert body["version"] == "2.0.0"
    assert body["docs"] == "/docs"


def test_campus_returns_expected_sections(client):
    response = client.get("/campus")

    assert response.status_code == 200
    body = response.json()
    assert body["campus_id"] == "vitap"
    assert isinstance(body["gates"], list)
    assert isinstance(body["parking_lots"], list)
    assert isinstance(body["roads"], list)
    assert isinstance(body["destinations"], list)


def test_scenarios_returns_configured_scenarios(client):
    response = client.get("/scenarios")

    assert response.status_code == 200
    scenarios = response.json()["scenarios"]
    assert isinstance(scenarios, list)
    assert "E1_normal_day" in scenarios


def test_strategies_returns_expected_codes(client):
    response = client.get("/strategies")

    assert response.status_code == 200
    codes = {
        strategy["code"]
        for strategy in response.json()["strategies"]
    }
    assert codes == {"B1", "B2", "B3", "P"}


def test_events_returns_event_list(client):
    response = client.get("/events")

    assert response.status_code == 200
    body = response.json()
    assert body["campus"] == "vitap"
    assert isinstance(body["events"], list)


def test_simulate_returns_expected_metrics(client):
    response = client.post(
        "/simulate",
        json={
            "scenario": "E1_normal_day",
            "strategy": "P",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["scenario"] == "E1_normal_day"
    assert body["strategy"] == "P"
    assert body["run_id"].startswith("api-")

    metrics = body["metrics"]
    assert metrics["total_vehicles"] == body["vehicles"]

    for key in (
        "parked_vehicles",
        "completed_trips",
        "overflow_events",
        "avg_search_time_min",
        "avg_wait_time_min",
        "avg_gate_queue",
        "peak_gate_queue",
    ):
        assert key in metrics


def test_simulate_rejects_unknown_scenario(client):
    response = client.post(
        "/simulate",
        json={
            "scenario": "scenario_that_does_not_exist",
            "strategy": "P",
        },
    )

    assert response.status_code == 404


def test_simulate_rejects_unknown_strategy(client):
    response = client.post(
        "/simulate",
        json={
            "scenario": "E1_normal_day",
            "strategy": "UNKNOWN",
        },
    )

    assert response.status_code == 400


def test_compare_returns_all_strategies(client):
    response = client.get("/compare/E1_normal_day")

    assert response.status_code == 200
    body = response.json()

    assert body["scenario"] == "E1_normal_day"
    assert set(body["comparison"]) == {"B1", "B2", "B3", "P"}

    for strategy_metrics in body["comparison"].values():
        assert "avg_search_time_min" in strategy_metrics
        assert "avg_wait_time_min" in strategy_metrics
        assert "avg_gate_queue" in strategy_metrics
        assert "peak_gate_queue" in strategy_metrics
        assert "overflow_events" in strategy_metrics


def test_compare_rejects_unknown_scenario(client):
    response = client.get(
        "/compare/scenario_that_does_not_exist"
    )

    assert response.status_code == 404
