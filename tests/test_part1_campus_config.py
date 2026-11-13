from pathlib import Path

import pytest
import yaml

from digital_twin.config_loader import load_campus_config, validate_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.gps_survey_import import gps_survey_to_config
from digital_twin.models import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    c = get_connection(db_path)
    apply_migrations(c)
    yield c
    c.close()


def load_yaml(name):
    with open(CONFIGS / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_sample_campus_loads_successfully(conn):
    campus_id = load_campus_config(CONFIGS / "sample.yaml", conn)
    assert campus_id == "sample"
    assert conn.execute("SELECT COUNT(*) FROM gates WHERE campus_id='sample'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM parking_lots WHERE campus_id='sample'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM routes_graph_edges WHERE campus_id='sample'").fetchone()[0] == 3


def test_reloading_same_file_produces_zero_new_rows(conn):
    load_campus_config(CONFIGS / "sample.yaml", conn)
    before = conn.execute("SELECT COUNT(*) FROM gates").fetchone()[0]
    load_campus_config(CONFIGS / "sample.yaml", conn)
    after = conn.execute("SELECT COUNT(*) FROM gates").fetchone()[0]
    assert before == after == 1


def test_vitap_campus_loads_successfully(conn):
    campus_id = load_campus_config(CONFIGS / "vitap.yaml", conn)
    assert campus_id == "vitap"
    assert conn.execute("SELECT COUNT(*) FROM destinations WHERE campus_id='vitap'").fetchone()[0] == 17
    # VIT-AP keeps its events in data/vitap_events.csv; the loader reads them from there.
    assert conn.execute("SELECT COUNT(*) FROM events WHERE campus_id='vitap'").fetchone()[0] == 10


def test_duplicate_gate_id_rejected():
    raw = load_yaml("sample.yaml")
    raw["gates"].append(dict(raw["gates"][0]))
    errors = validate_campus_config(raw)
    assert any("Duplicate gate id" in e for e in errors)


def test_negative_or_zero_capacity_rejected():
    raw = load_yaml("sample.yaml")
    raw["gates"][0]["capacity"] = 0
    errors = validate_campus_config(raw)
    assert any("non-positive capacity" in e for e in errors)


def test_malformed_coordinates_rejected():
    raw = load_yaml("sample.yaml")
    raw["gates"][0]["latitude"] = 200.0
    errors = validate_campus_config(raw)
    assert any("latitude 200.0 out of range" in e for e in errors)


def test_two_point_road_geometry_rejected():
    raw = load_yaml("sample.yaml")
    raw["roads"][0]["geometry"] = [raw["roads"][0]["geometry"][0], raw["roads"][0]["geometry"][-1]]
    errors = validate_campus_config(raw)
    assert any("only its two endpoints" in e for e in errors)


def test_road_referencing_unknown_node_rejected():
    raw = load_yaml("sample.yaml")
    raw["roads"][0]["start_node_id"] = "does-not-exist"
    errors = validate_campus_config(raw)
    assert any("does not exist in this campus" in e for e in errors)


def test_orphan_node_rejected():
    raw = load_yaml("sample.yaml")
    # Add a parking lot with no edges — destinations are walk-path endpoints and
    # are intentionally excluded from the drive-graph orphan check; use a lot instead.
    raw["parking_lots"].append({
        "parking_lot_id": "vitap-lot-orphan", "name": "Orphan Lot",
        "campus_id": "vitap", "total_capacity": 10, "usable_capacity": 10,
        "reserved_capacity": 0, "restricted_capacity": 0,
        "temporarily_unavailable_capacity": 0,
        "latitude": 10.0, "longitude": 20.0,
    })
    errors = validate_campus_config(raw)
    assert any("orphan node" in e for e in errors)


def test_capacity_breakdown_exceeding_total_rejected():
    raw = load_yaml("sample.yaml")
    raw["parking_lots"][0]["reserved_capacity"] = 999
    errors = validate_campus_config(raw)
    assert any("exceeds total_capacity" in e for e in errors)


def test_config_error_raised_on_load_with_invalid_data(conn):
    raw = load_yaml("sample.yaml")
    raw["gates"][0]["capacity"] = -5
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(raw, f)
        bad_path = f.name
    with pytest.raises(ConfigError):
        load_campus_config(bad_path, conn)
    assert conn.execute("SELECT COUNT(*) FROM campuses").fetchone()[0] == 0


def test_gps_survey_to_config_preserves_track_point_order():
    config = gps_survey_to_config(
        FIXTURES / "sample_survey.gpx", FIXTURES / "sample_waypoints.csv",
        campus_id="survey-test", campus_name="Survey Test Campus",
    )
    road = config["roads"][0]
    assert road["geometry"] == [
        {"lat": 10.0000, "lng": 20.0000},
        {"lat": 10.0004, "lng": 20.0003},
        {"lat": 10.0007, "lng": 20.0007},
        {"lat": 10.0010, "lng": 20.0010},
    ]
    assert road["expected_travel_time_seconds"] == 95.0


def test_gps_survey_config_is_valid(conn):
    config = gps_survey_to_config(
        FIXTURES / "sample_survey.gpx", FIXTURES / "sample_waypoints.csv",
        campus_id="survey-test", campus_name="Survey Test Campus",
    )
    errors = validate_campus_config(config)
    assert errors == []


if __name__ == "__main__":
    print("Run with pytest: python -m pytest test_part1_campus_config.py -v")
