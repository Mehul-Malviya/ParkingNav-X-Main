"""
DEMO ONLY: load 8 days of FABRICATED "real" readings so the real-data path can be seen working, then remove them.

    python scripts/demo_real_data.py load      # backs up the DB, then inserts demo rows (source=manual)
    python scripts/demo_real_data.py remove    # deletes exactly those rows

The rows are invented (a weekday/weekend daily curve plus noise). They sit in 2026-10-01..2026-10-08, a window
no real count should use, and `remove` deletes only source='manual' rows in that window. Never show forecasts
made from them as real VIT-AP results.
"""

import math
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digital_twin.db import DEFAULT_DB_PATH, apply_migrations, get_connection  # noqa: E402
from digital_twin.observations import lot_capacities, record_observations  # noqa: E402

START = datetime(2026, 10, 1)          # campus-local
DAYS = 8
WINDOW = ("2026-09-30 00:00:00", "2026-10-09 00:00:00")   # UTC bounds around the demo rows
LOT_LEVEL = {"vitap-lot-academic-main": 0.85, "vitap-lot-hostel": 0.55, "vitap-lot-admin-visitor": 0.6,
             "vitap-lot-sports": 0.4, "vitap-lot-overflow": 0.2}


def fill(lot, ts, rng):
    weekend = ts.weekday() >= 5
    h = ts.hour + ts.minute / 60
    day = math.exp(-((h - 10.5) ** 2) / 18) + 0.7 * math.exp(-((h - 15) ** 2) / 10)   # two daytime peaks
    base = 0.25 if weekend else 1.0
    return max(0.02, min(0.98, LOT_LEVEL[lot] * (0.15 + 0.85 * day * base) + rng.gauss(0, 0.03)))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("load", "remove"):
        sys.exit(__doc__)
    conn = get_connection(DEFAULT_DB_PATH)
    apply_migrations(conn)
    if sys.argv[1] == "load":
        backup = DEFAULT_DB_PATH.with_name("digital_twin.db.before_demo")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copyfile(DEFAULT_DB_PATH, backup)
        print(f"backup: {backup}")
        rng, caps, rows = random.Random(7), lot_capacities(conn), []
        for lot in LOT_LEVEL:
            for i in range(DAYS * 96):
                ts = START + timedelta(minutes=15 * i)
                rows.append({"timestamp": ts.isoformat(), "lot_id": lot, "source": "manual",
                             "occupied_spaces": round(fill(lot, ts, rng) * caps[lot])})
        res = record_observations(conn, rows)
        print(f"inserted {res['accepted']} demo rows ({res['duplicates']} already there, {len(res['rejected'])} rejected)")
        print("Now refit: POST /predict/retrain (Record Counts tab -> Refit forecast)")
    else:
        n = conn.execute("DELETE FROM lot_occupancy_history WHERE source='manual' AND recorded_at BETWEEN ? AND ?",
                         WINDOW).rowcount
        conn.commit()
        print(f"removed {n} demo rows. Refit again (POST /predict/retrain) to go back to synthetic.")


if __name__ == "__main__":
    main()
