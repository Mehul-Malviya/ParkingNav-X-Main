"""
Real occupancy observations: validate, store and turn into training data.

One code path for the REST API (POST /observations[/batch]) and the CSV importer
(scripts/import_observations.py). Rows land in lot_occupancy_history with a `source`:

  sensor / manual   real counts            -> used for live forecasts and retraining
  simulation        output of /simulate    -> never treated as real
  synthetic         generated placeholder  -> never treated as real
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

REAL_SOURCES = ("sensor", "manual")
ALLOWED_SOURCES = REAL_SOURCES + ("simulation", "synthetic")
CAMPUS_UTC_OFFSET = timedelta(hours=5, minutes=30)   # Asia/Kolkata; naive timestamps are campus-local


def normalize_timestamp(ts: str) -> str:
    """ISO-8601 -> 'YYYY-MM-DD HH:MM:SS' UTC (the format SQLite's datetime('now') uses).
    A timestamp without a timezone is campus-local (IST)."""
    dt = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(CAMPUS_UTC_OFFSET))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def lot_capacities(conn) -> Dict[str, int]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT parking_lot_id, usable_capacity FROM parking_lots WHERE campus_id='vitap'")}


def record_observations(conn, rows: Iterable[dict], default_source: str = "sensor") -> Dict:
    """Store observations ({timestamp, lot_id, occupied_spaces, source?}). Invalid rows are rejected with a
    reason, duplicates (same lot, time and source) are skipped, the rest are stored."""
    caps = lot_capacities(conn)
    accepted, duplicates, rejected = 0, 0, []
    for i, row in enumerate(rows, start=1):
        try:
            lot_id = str(row["lot_id"]).strip()
            source = str(row.get("source") or default_source).strip().lower()
            occupied = int(row["occupied_spaces"])
            when = normalize_timestamp(row["timestamp"])
            if lot_id not in caps:
                raise ValueError(f"unknown lot '{lot_id}'")
            if source not in ALLOWED_SOURCES:
                raise ValueError(f"source must be one of {ALLOWED_SOURCES}")
            if not 0 <= occupied <= caps[lot_id]:
                raise ValueError(f"occupied_spaces {occupied} out of range [0, {caps[lot_id]}]")
        except (KeyError, TypeError, ValueError) as e:
            rejected.append({"row": i, "error": f"missing field {e}" if isinstance(e, KeyError) else str(e)})
            continue
        if conn.execute("SELECT 1 FROM lot_occupancy_history WHERE lot_id=? AND recorded_at=? AND source=?",
                        (lot_id, when, source)).fetchone():
            duplicates += 1
            continue
        conn.execute(
            "INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate, recorded_at, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (lot_id, occupied, round(occupied / caps[lot_id], 4), when, source))
        accepted += 1
    conn.commit()
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def real_demand_frame(conn):
    """Real observations as a 15-minute-grid DataFrame in the training-data layout
    (timestamp [campus-local], lot_id, occupied, capacity, fill_rate). Gaps stay gaps — nothing is invented."""
    import pandas as pd
    marks = ",".join("?" * len(REAL_SOURCES))
    rows = conn.execute(
        f"SELECT lot_id, recorded_at, fill_rate FROM lot_occupancy_history WHERE source IN ({marks})",
        REAL_SOURCES).fetchall()
    if not rows:
        return pd.DataFrame()
    caps = lot_capacities(conn)
    df = pd.DataFrame([tuple(r) for r in rows], columns=["lot_id", "timestamp", "fill_rate"])
    df["timestamp"] = (pd.to_datetime(df["timestamp"], utc=True).dt.tz_localize(None)
                       + CAMPUS_UTC_OFFSET).dt.floor("15min")
    df = df.groupby(["lot_id", "timestamp"], as_index=False)["fill_rate"].mean()
    # Put each lot on a complete 15-minute grid; a missing slot stays NaN (feature building drops rows
    # whose lags touch a gap), so no occupancy is ever interpolated.
    df = pd.concat(
        [g.set_index("timestamp").reindex(pd.date_range(g["timestamp"].min(), g["timestamp"].max(), freq="15min"))
          .rename_axis("timestamp").assign(lot_id=lot).reset_index()
         for lot, g in df.groupby("lot_id")], ignore_index=True)
    df["capacity"] = df["lot_id"].map(caps)
    df["occupied"] = (df["fill_rate"] * df["capacity"]).round()
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["data_source"] = "real"
    return df.sort_values(["lot_id", "timestamp"]).reset_index(drop=True)
