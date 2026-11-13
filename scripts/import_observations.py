"""
Import real parking counts from a CSV into the digital twin database, then optionally retrain the forecast.

Usage:
    python scripts/import_observations.py data/observations/my_counts.csv [--source manual|sensor] [--retrain]

Columns: timestamp, lot_id (or parking_lot_id), occupied_spaces, and optionally source.
Timestamps without a timezone are campus-local (IST). Bad rows are reported and skipped; re-importing the
same file is safe (duplicates are skipped). A lot's model trains on real data once it has a week of readings.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digital_twin.db import DEFAULT_DB_PATH, get_connection, apply_migrations  # noqa: E402
from digital_twin.observations import record_observations  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_file")
    ap.add_argument("--source", default="manual", choices=["manual", "sensor"],
                    help="default source for rows without a source column")
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--retrain", action="store_true", help="refit the forecast models afterwards")
    args = ap.parse_args()

    with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
        rows = [{**r, "lot_id": r.get("lot_id") or r.get("parking_lot_id")}
                for r in csv.DictReader(l for l in f if not l.lstrip().startswith("#"))]
    conn = get_connection(args.db)
    apply_migrations(conn)
    res = record_observations(conn, rows, default_source=args.source)
    print(f"accepted {res['accepted']}, duplicates {res['duplicates']}, rejected {len(res['rejected'])}")
    for r in res["rejected"][:20]:
        print(f"  row {r['row']}: {r['error']}")
    if args.retrain:
        from digital_twin.prediction.engine import retrain
        info = retrain(conn)
        print(f"retrained: real data for {info['real_lots'] or 'no lots'}; synthetic for {info['synthetic_lots']}")
    sys.exit(1 if res["rejected"] else 0)


if __name__ == "__main__":
    main()
