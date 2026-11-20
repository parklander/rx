"""Apply db/NNN_*.sql files that have not been applied yet.

    python migrate.py
"""
import os
from pathlib import Path

import psycopg

DSN = os.environ.get("RX_DATABASE_URL", "postgresql://rx:rx@localhost/rx")
DB_DIR = Path(__file__).resolve().parent / "db"


def migrate():
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("create schema if not exists meta")
        conn.execute("create table if not exists meta.migration (name text primary key, applied_at timestamptz not null default now())")
        done = {r[0] for r in conn.execute("select name from meta.migration")}
        for f in sorted(DB_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            if f.name in done:
                continue
            print("applying", f.name)
            with conn.transaction():
                conn.execute(f.read_text())
                conn.execute("insert into meta.migration (name) values (%s)", (f.name,))
    print("database is up to date")


if __name__ == "__main__":
    migrate()
