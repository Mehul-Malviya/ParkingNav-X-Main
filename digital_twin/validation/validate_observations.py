"""
Validate a real gate-count CSV before using it in the simulation.

Usage:
    python data/validate_observations.py data/synthetic_observations.csv

Checks:
  1. Required columns present (confidence and notes are optional)
  2. Missing values: reported per column, does not abort
  3. vehicle_arrivals >= 0, vehicle_departures >= 0
  4. occupied_spaces >= 0 and <= total_capacity
  5. confidence in [0.0, 1.0] (if column present)
  6. timestamps are ISO-8601, accept UTC (Z/+00:00) or IST (+05:30); ascending,
     spaced 15 min apart
  7. gate_id values exist in configs/campus/vitap.yaml
  8. lot_id values exist in configs/campus/vitap.yaml
  9. event_type in allowed set
  10. Row count: ERROR if 0, WARNING if < 40

Exits with code 0 (clean or warnings only) or 1 (errors found).
"""

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REQUIRED_COLUMNS = {
    "timestamp", "gate_id", "lot_id",
    "vehicle_arrivals", "vehicle_departures",
    "occupied_spaces", "total_capacity",
    "event_type",
}
OPTIONAL_COLUMNS = {"confidence", "notes"}
ALLOWED_EVENT_TYPES = {"none", "placement", "graduation", "sports", "other"}
VITAP_CONFIG = Path("configs/campus/vitap.yaml")
INTERVAL_MINUTES = 15
MIN_ROWS = 40

IST_OFFSET = timedelta(hours=5, minutes=30)


def _parse_timestamp(ts_str: str):
    """Parse ISO-8601 timestamp; convert IST (+05:30) to UTC. Returns UTC datetime or None."""
    ts_str = ts_str.strip()
    try:
        # Python 3.11+ fromisoformat handles Z natively; older needs replace
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        # Normalise to UTC
        return ts.astimezone(timezone.utc)
    except ValueError:
        return None


def load_vitap_ids():
    if not VITAP_CONFIG.exists():
        return set(), set()
    with open(VITAP_CONFIG) as f:
        cfg = yaml.safe_load(f)
    gate_ids = {g["gate_id"] for g in cfg.get("gates", [])}
    lot_ids = {lot["parking_lot_id"] for lot in cfg.get("parking_lots", [])}
    return gate_ids, lot_ids


def validate(csv_path: str):
    errors = []
    warnings = []
    path = Path(csv_path)

    if not path.exists():
        return [f"File not found: {csv_path}"], []

    # Read rows, skip comment lines
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw_line in f:
            if raw_line.lstrip().startswith("#"):
                continue
            rows.append(raw_line)

    if not rows:
        return ["File is empty (after stripping comments)."], []

    reader = csv.DictReader(rows)
    data = list(reader)
    fieldnames = set(reader.fieldnames or [])

    if not data:
        return ["No data rows found."], []

    # 1. Required columns
    missing_cols = REQUIRED_COLUMNS - fieldnames
    if missing_cols:
        errors.append(f"Missing required columns: {sorted(missing_cols)}")
        return errors, warnings  # can't continue without required columns

    has_confidence = "confidence" in fieldnames

    # Load valid IDs
    valid_gate_ids, valid_lot_ids = load_vitap_ids()

    # Track missing value counts per column
    missing_counts = {col: 0 for col in REQUIRED_COLUMNS}

    timestamps = []
    for i, row in enumerate(data, start=2):  # row 1 is header
        lineno = f"row {i}"

        # 2. Missing values â€” report but don't abort
        for col in REQUIRED_COLUMNS:
            if not row.get(col, "").strip():
                missing_counts[col] += 1

        # 3â€“4. Numeric checks
        try:
            arrivals = int(row["vehicle_arrivals"])
            if arrivals < 0:
                errors.append(f"{lineno}: vehicle_arrivals={arrivals} is negative")
        except (ValueError, KeyError):
            if row.get("vehicle_arrivals", "").strip():
                errors.append(f"{lineno}: vehicle_arrivals is not an integer")
            arrivals = None

        try:
            departures = int(row["vehicle_departures"])
            if departures < 0:
                errors.append(f"{lineno}: vehicle_departures={departures} is negative")
        except (ValueError, KeyError):
            if row.get("vehicle_departures", "").strip():
                errors.append(f"{lineno}: vehicle_departures is not an integer")

        try:
            capacity = int(row["total_capacity"])
            if capacity <= 0:
                errors.append(f"{lineno}: total_capacity={capacity} must be > 0")
        except (ValueError, KeyError):
            if row.get("total_capacity", "").strip():
                errors.append(f"{lineno}: total_capacity is not an integer")
            capacity = None

        try:
            occupied = int(row["occupied_spaces"])
            if occupied < 0:
                errors.append(f"{lineno}: occupied_spaces={occupied} is negative")
            if capacity is not None and occupied > capacity:
                errors.append(f"{lineno}: occupied_spaces={occupied} > total_capacity={capacity}")
        except (ValueError, KeyError):
            if row.get("occupied_spaces", "").strip():
                errors.append(f"{lineno}: occupied_spaces is not an integer")

        # 5. confidence (optional column)
        if has_confidence:
            conf_str = row.get("confidence", "").strip()
            if conf_str:
                try:
                    conf = float(conf_str)
                    if not (0.0 <= conf <= 1.0):
                        errors.append(f"{lineno}: confidence={conf} not in [0.0, 1.0]")
                except ValueError:
                    errors.append(f"{lineno}: confidence '{conf_str}' is not a float")

        # 6. timestamp â€” accept UTC and IST
        ts_str = row.get("timestamp", "").strip()
        if ts_str:
            ts = _parse_timestamp(ts_str)
            if ts is None:
                errors.append(f"{lineno}: timestamp '{ts_str}' is not valid ISO-8601 (UTC or IST +05:30 accepted)")
            else:
                timestamps.append((i, ts))

        # 7. gate_id
        gate = row.get("gate_id", "").strip()
        if gate and valid_gate_ids and gate not in valid_gate_ids:
            errors.append(f"{lineno}: gate_id '{gate}' not in vitap.yaml (valid: {sorted(valid_gate_ids)})")

        # 8. lot_id
        lot = row.get("lot_id", "").strip()
        if lot and valid_lot_ids and lot not in valid_lot_ids:
            errors.append(f"{lineno}: lot_id '{lot}' not in vitap.yaml (valid: {sorted(valid_lot_ids)})")

        # 9. event_type
        event_type = row.get("event_type", "").strip()
        if event_type and event_type not in ALLOWED_EVENT_TYPES:
            errors.append(f"{lineno}: event_type '{event_type}' not in {sorted(ALLOWED_EVENT_TYPES)}")

    # 2b. Report missing values as a summary
    for col, count in missing_counts.items():
        if count > 0:
            errors.append(f"Missing values: '{col}' is blank in {count} row(s)")

    # 6b. Timestamp ordering and 15-min spacing
    if len(timestamps) >= 2:
        ts_values = [t for _, t in timestamps]
        for j in range(1, len(ts_values)):
            delta = ts_values[j] - ts_values[j - 1]
            if ts_values[j] < ts_values[j - 1]:
                errors.append(f"row {timestamps[j][0]}: timestamp goes backward from previous row")
            elif delta != timedelta(minutes=INTERVAL_MINUTES) and delta.total_seconds() > 0:
                minutes = delta.total_seconds() / 60
                if minutes % INTERVAL_MINUTES != 0:
                    errors.append(
                        f"row {timestamps[j][0]}: gap={minutes:.0f} min is not a multiple of {INTERVAL_MINUTES} min"
                    )

    # 10. Row count check
    if len(data) == 0:
        errors.append("No data rows found.")
    elif len(data) < MIN_ROWS:
        warnings.append(
            f"Only {len(data)} data rows â€” fewer than {MIN_ROWS} (1 day Ã— 1 gate/lot at 15-min intervals). "
            "Results may be statistically weak."
        )

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: python data/validate_observations.py <csv_file>")
        sys.exit(1)

    csv_path = sys.argv[1]
    print(f"Validating: {csv_path}")
    errors, warnings = validate(csv_path)

    if warnings:
        print(f"\n{len(warnings)} warning(s):\n")
        for w in warnings:
            print(f"  WARNING: {w}")

    if errors:
        print(f"\n{len(errors)} error(s) found:\n")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)
    else:
        if not warnings:
            print("All checks passed.")
        else:
            print("\nChecks passed (with warnings above).")
        print("File is ready for use as data/synthetic_observations.csv "
              "(rename it and update references when real data replaces the synthetic placeholder).")
        sys.exit(0)


if __name__ == "__main__":
    main()
