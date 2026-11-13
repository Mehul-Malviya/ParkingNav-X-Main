"""
SQLite connection + migration runner. Migrations are applied once, tracked
in schema_migrations, and never rewritten — add a new numbered file instead.
"""

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
DEFAULT_DB_PATH = PROJECT_ROOT / "digital_twin.db"


def get_connection(db_path=None, timeout: float = 30.0) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH), timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def apply_migrations(conn: sqlite3.Connection):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

    for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = migration_file.stem
        if version in applied:
            continue
        with open(migration_file, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        conn.commit()


def init_db(db_path=None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    apply_migrations(conn)
    return conn
