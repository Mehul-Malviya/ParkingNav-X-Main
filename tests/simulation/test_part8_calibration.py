"""
Part 8 — Calibration pipeline verification tests.

Checks:
  CB1  observations file exists and loads with Part 8 schema columns
  CB2  has both normal-day and event-day rows
  CB3  calibration JSON exists with MAE / RMSE keys
  CB4  MAE is a finite positive number (pipeline ran successfully)
  CB5  overlay PNG exists
  CB6  matched_intervals >= 10 (meaningful alignment)
"""

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

OBS_FILE    = ROOT / "data" / "observations" / "vitap_observations.csv"
CAL_JSON    = ROOT / "data" / "part8_calibration_results.json"
OVERLAY_PNG = ROOT / "docs" / "member1" / "calibration_overlay.png"

REQUIRED_COLS = {
    "timestamp", "gate_id", "vehicle_count", "parking_lot_id",
    "occupied_spaces", "event_type", "event_intensity", "source",
}


# ── CB1: observations file loads with correct schema ─────────────────────────

def test_cb1_observations_file_exists_and_has_schema():
    assert OBS_FILE.exists(), f"Observations file missing: {OBS_FILE}"
    with open(OBS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert rows, "Observations file is empty"
    assert REQUIRED_COLS <= set(rows[0].keys()), (
        f"Missing columns: {REQUIRED_COLS - set(rows[0].keys())}"
    )


# ── CB2: has both day types ───────────────────────────────────────────────────

def test_cb2_has_normal_and_event_rows():
    with open(OBS_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
    event_types = {r["event_type"] for r in rows}
    assert "normal" in event_types, "No normal-day rows found"
    non_normal = {e for e in event_types if e != "normal"}
    assert non_normal, f"No event-day rows found (all rows are 'normal')"


# ── CB3: calibration JSON has MAE / RMSE keys ─────────────────────────────────

def test_cb3_calibration_json_has_metrics():
    assert CAL_JSON.exists(), f"Calibration JSON missing: {CAL_JSON}"
    data = json.loads(CAL_JSON.read_text())
    assert "metrics" in data, "No 'metrics' key in calibration JSON"
    m = data["metrics"]
    assert "occupied_spaces" in m, "No occupied_spaces metrics"
    assert "MAE"  in m["occupied_spaces"], "MAE missing"
    assert "RMSE" in m["occupied_spaces"], "RMSE missing"


# ── CB4: MAE is finite and positive ──────────────────────────────────────────

def test_cb4_mae_is_finite_and_positive():
    import math
    data = json.loads(CAL_JSON.read_text())
    mae = data["metrics"]["occupied_spaces"]["MAE"]
    assert isinstance(mae, (int, float)), "MAE must be numeric"
    assert math.isfinite(mae), f"MAE is not finite: {mae}"
    assert mae > 0, f"MAE must be > 0 (simulation produced no occupancy if 0): {mae}"


# ── CB4b: sim_occupied is not all zeros (simulation actually produced occupancy) ─

def test_cb4b_sim_occupied_not_all_zeros():
    data = json.loads(CAL_JSON.read_text())
    series = data.get("series", {})
    sim_occ = series.get("sim_occupied", [])
    assert len(sim_occ) > 0, "sim_occupied series is empty"
    assert any(v > 0 for v in sim_occ), (
        "sim_occupied is all zeros — calibration script used wrong strategy or lot. "
        "Re-run scripts/build_part8_calibration.py to fix."
    )


# ── CB5: overlay PNG exists ───────────────────────────────────────────────────

def test_cb5_overlay_png_exists():
    assert OVERLAY_PNG.exists(), f"Overlay PNG missing: {OVERLAY_PNG}"
    assert OVERLAY_PNG.stat().st_size > 1000, "Overlay PNG seems too small (< 1 KB)"


# ── CB6: meaningful alignment ─────────────────────────────────────────────────

def test_cb6_matched_intervals_meaningful():
    data = json.loads(CAL_JSON.read_text())
    n = data.get("matched_intervals", 0)
    assert n >= 10, f"Only {n} matched intervals — calibration not meaningful"
