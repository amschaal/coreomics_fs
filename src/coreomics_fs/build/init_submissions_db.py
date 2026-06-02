#!/usr/bin/env python3
import sqlite3
from pathlib import Path
from ..config import load_config

cfg = load_config()
db_dir = cfg["paths"]["submissions_db_directory"]
Path(db_dir).mkdir(parents=True, exist_ok=True)
DB_PATH = Path(db_dir) / "submissions.db"

def init_db(path=DB_PATH):
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY,
        internal_id TEXT,
        submitted TEXT,
        updated TEXT,
        first_name TEXT,
        last_name TEXT,
        pi_first_name TEXT,
        pi_last_name TEXT,
        email TEXT,
        pi_email TEXT,
        submission JSON
    )
    """)
    indexes = [
        "internal_id", "submitted", "updated", "first_name",
        "last_name", "pi_first_name", "pi_last_name", "email", "pi_email"
    ]
    for idx in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_submissions_{idx} ON submissions ({idx})")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS submission_shares (
        id TEXT PRIMARY KEY,
        submission_id TEXT NOT NULL,
        bioshare_id TEXT,
        name TEXT,
        url TEXT,
        notes TEXT,
        sub_folder TEXT,
        link_to_path TEXT,
        share JSON
    )
    """)
    for idx in ("submission_id", "bioshare_id"):
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_submission_shares_{idx} ON submission_shares ({idx})")

    conn.commit()
    conn.close()
    print(f"Initialized submissions DB at {path}")

if __name__ == '__main__':
    init_db()
