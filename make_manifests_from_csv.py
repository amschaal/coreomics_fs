#!/usr/bin/env python3
# make_manifests_from_csv.py
"""
Create ONE manifest per view (global) from a CSV of project metadata.

Views supported:
- institute_pi: <INST_SHARD>/<INSTITUTE>/<PI_SHARD>/<PI>/year/month/project
- pi:          <PI_SHARD>/<PI>/year/month/project
- type:        <TYPE>/year/month/project
- date:        year/month/project

CSV columns expected (case-sensitive):
  ID (canonical project id), Internal ID (human-friendly id), Type,
  Submitted (timestamp), First Name, Last Name, PI First Name, PI Last Name, Institute

Notes:
- Year/month are derived from Submitted timestamp.
- Leaf (symlink name) uses Internal ID when present, else ID (sanitized but NOT uppercased).
- Institute and PI directory names are normalized to UPPER_CASE_WITH_UNDERSCORES.
- Sharding: institute folders by first letter of institute; PI folders by first letter of LAST name.
- Manifests are written under --manifest-root/<view>/<YYYY-MM-DD>.json
- Each manifest contains ALL entries for that view.
"""
import argparse
import csv
import json
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Tuple

SAFE_CHARS_LEAF = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_.(),")
SAFE_CHARS_DIR = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")  # after uppercasing


def to_upper_us(s: str) -> str:
    """Normalize to UPPER_CASE_WITH_UNDERSCORES for directory names.
    Keep A-Z, 0-9, space, and -_.(), convert others to underscore, collapse repeats.
    """
    s = (s or "").strip().upper()
    out = []
    last_us = False
    for ch in s:
        if ch in SAFE_CHARS_DIR or ch == ' ':
            if ch == ' ':
                ch = '_'
            out.append(ch)
            last_us = (ch == '_')
        else:
            if not last_us:
                out.append('_')
                last_us = True
    # collapse multiple underscores
    res = []
    prev = None
    for ch in out:
        if ch == '_' and prev == '_':
            continue
        res.append(ch)
        prev = ch
    # trim leading/trailing underscores and dots
    return ''.join(res).strip('_.') or 'UNKNOWN'


def sanitize_leaf(s: str) -> str:
    """Leaf name for symlink: keep case from source; convert disallowed chars to underscore; collapse repeats."""
    s = (s or '').strip()
    if not s:
        return 'unknown'
    out = []
    last_us = False
    for ch in s:
        if ch in SAFE_CHARS_LEAF:
            out.append(ch)
            last_us = False
        else:
            if not last_us:
                out.append('_')
                last_us = True
    # collapse underscores
    res = []
    prev = None
    for ch in out:
        if ch == '_' and prev == '_':
            continue
        res.append(ch)
        prev = ch
    return ''.join(res).strip(' _.') or 'unknown'


def pi_dirname(last: str, first: str) -> str:
    last_u = to_upper_us(last)
    first_u = to_upper_us(first)
    return f"{last_u}_{first_u}" if first_u != 'UNKNOWN' else last_u


def shard_letter_for_dirname(norm_dirname: str) -> str:
    return (norm_dirname[0] if norm_dirname else 'U')


def parse_submitted(ts: str) -> Tuple[int, int]:
    ts = (ts or '').strip()
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
            continue
    raise ValueError(f"Unrecognized Submitted timestamp: {ts}")


def build_base_entries(rows: List[Dict[str, str]]):
    """Return entries with all normalized fields needed by any view."""
    entries = []
    for r in rows:
        cid = str(r.get("ID", "")).strip()
        internal = str(r.get("Internal ID", "")).strip()
        submitted = str(r.get("Submitted", "")).strip()
        if not cid:
            continue
        y, m = parse_submitted(submitted)
        leaf = sanitize_leaf(internal or cid)
        institute_raw = (r.get("Institute", "") or "").strip().strip('"')
        pi_first_raw = (r.get("PI First Name", "") or "").strip()
        pi_last_raw = (r.get("PI Last Name", "") or "").strip()
        type_raw = (r.get("Type", "") or "").strip()

        inst_dir = to_upper_us(institute_raw) or 'UNKNOWN'
        pi_dir = pi_dirname(pi_last_raw, pi_first_raw)
        type_dir = to_upper_us(type_raw) or 'UNKNOWN_TYPE'

        inst_shard = shard_letter_for_dirname(inst_dir)
        pi_shard = shard_letter_for_dirname(to_upper_us(pi_last_raw)) if pi_last_raw else 'U'

        entries.append({
            "project_id": cid,
            "leaf_name": leaf,
            "year": y,
            "month": m,
            "institute_dir": inst_dir,
            "institute_shard": inst_shard,
            "pi_dir": pi_dir,
            "pi_shard": pi_shard,
            "type_dir": type_dir,
        })
    # Stable sort for deterministic output
    entries.sort(key=lambda e: (e["year"], e["month"], e["leaf_name"]))
    return entries


def main():
    ap = argparse.ArgumentParser(description="Generate ONE manifest per view from a CSV of project metadata.")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--manifest-root", required=True,
                    help="Root directory where manifests will be written.")
    ap.add_argument("--views", nargs="*", default=["institute_pi", "pi", "type", "date"],
                    choices=["institute_pi", "pi", "type", "date"],
                    help="Which views to generate.")
    ap.add_argument("--version-date", help="Override YYYY-MM-DD (defaults to today).")
    ap.add_argument("--script-version", default="2.0.0")
    args = ap.parse_args()

    version = args.version_date or date.today().strftime("%Y-%m-%d")

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    base_entries = build_base_entries(rows)
    root = Path(args.manifest_root)
    manifests_written = 0

    def write_manifest(view: str, entries: List[dict]):
        nonlocal manifests_written
        out_dir = root / view
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{version}.json"
        manifest = {
            "view": view,
            "generated_at": version,
            "script_version": args.script_version,
            "build_parameters": {
                "symlink_type": "relative",
                "layout": "<view-specific>/year/month/leaf -> immutable/year/month/ID",
                "leaf_name_strategy": "internal_id_or_id",
                "pi_dir_format": "LAST_FIRST_UPPER_UNDERSCORE",
                "institute_dir_format": "UPPER_UNDERSCORE",
                "sharding": {
                    "institute": "first_letter",
                    "pi": "first_letter_of_last_name"
                },
                "overwrite_same_day": True
            },
            "entry_count": len(entries),
            "entries": entries,
        }
        with out_path.open("w", encoding="utf-8") as fo:
            json.dump(manifest, fo, indent=2, sort_keys=True)
        manifests_written += 1
        print(f"Wrote manifest: {out_path} (entries={len(entries)})")

    for view in args.views:
        write_manifest(view, base_entries)

    print(f"Total manifests written: {manifests_written}")

if __name__ == "__main__":
    main()
