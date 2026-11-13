"""CLI: python scripts/load_campus_config.py --config configs/campus/vitap.yaml [--db path]

Idempotently loads (upserts) one campus YAML config into the database.
Running it twice on the same file produces zero new rows.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.models import ConfigError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    conn = get_connection(args.db)
    apply_migrations(conn)

    try:
        campus_id = load_campus_config(args.config, conn)
    except ConfigError as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded campus '{campus_id}' from {args.config}")


if __name__ == "__main__":
    main()
