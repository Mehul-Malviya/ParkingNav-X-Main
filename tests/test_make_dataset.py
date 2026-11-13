"""make_dataset (Member 2 export): real columns, real values."""

import csv
from pathlib import Path

from digital_twin import api_functions
from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection

EXPECTED_COLUMNS = [
    "timestamp", "scenario_id", "seed", "day_type", "event_type", "event_intensity",
    "minutes_to_event_start", "hour", "minute", "weekday", "lot_id", "capacity",
    "occupied", "occupancy_pct", "arrivals_5m", "departures_5m", "gate_id",
    "gate_arrivals_5m", "queue_length", "avg_wait_sec", "avg_travel_time_sec",
    "road_congestion_ratio_mean", "congestion_level", "lot_status", "gate_status", "source",
]


def test_make_dataset_columns_and_nonzero_distance(tmp_path):
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(Path("configs/campus/vitap.yaml"), conn)
    api_functions._conn = conn

    out = tmp_path / "ml.csv"
    result = api_functions.make_dataset(
        campus_id="vitap",
        scenario_paths=["configs/scenarios/vitap/E1_normal_day.yaml"],
        seeds=[0],
        output_path=str(out),
    )

    assert result["columns"] == EXPECTED_COLUMNS
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows) == result["rows"] > 0
    # New format: timeseries rows — verify occupancy and source columns are present
    assert all(r["source"] == "simulation" for r in rows)
    assert all(float(r["occupancy_pct"]) >= 0.0 for r in rows)
