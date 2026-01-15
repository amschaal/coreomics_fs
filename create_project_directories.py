
#!/usr/bin/env python3
# create_project_directories.py
#
# Create canonical immutable directories from a CSV:
#   /data/immutable/<year>/<month>/<ID>/
#
# Only creates missing directories.
#
# Usage:
#   python3 create_project_directories.py \
#       --csv project_data.csv \
#       --immutable-root /data/immutable

import argparse
import csv
from pathlib import Path
from datetime import datetime

def parse_year_month(ts: str):
    ts = ts.strip()
    fmts = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(ts, f)
            return dt.year, dt.month
        except Exception:
            pass
    raise ValueError(f"Unrecognized date format: {ts}")

def main():
    ap = argparse.ArgumentParser(description="Create immutable structure for projects.")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--immutable-root", required=True)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    immutable_root = Path(args.immutable_root)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("ID", "").strip()
            submitted = row.get("Submitted", "").strip()
            if not pid or not submitted:
                continue

            year, month = parse_year_month(submitted)
            target = immutable_root / f"{year:04d}" / f"{month:02d}" / pid

            if not target.exists():
                print(f"Creating {target}")
                target.mkdir(parents=True, exist_ok=True)
            else:
                print(f"Exists: {target}")

if __name__ == "__main__":
    main()
