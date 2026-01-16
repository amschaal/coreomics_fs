#!/usr/bin/env python3
# build_all.py (Option A compatible)
"""
Build multiple views from a minimal manifest root in one command.
Assumes build_view_from_manifest publishes to <views_root>/.versions/<view>/<date>
And sets <views_root>/<view> -> latest.
"""
import argparse
import sys
import json
from datetime import date
from pathlib import Path
from typing import List, Optional

try:
    import build_view_from_manifest as builder
except Exception:
    builder = None


def find_manifest(manifest_root: Path, view: str, date_str: Optional[str], use_latest: bool) -> Path:
    view_dir = manifest_root / view
    if date_str:
        p = view_dir / f"{date_str}.json"
        if not p.exists():
            raise FileNotFoundError(f"Manifest not found for view '{view}' and date '{date_str}': {p}")
        return p
    if use_latest:
        if not view_dir.exists():
            raise FileNotFoundError(f"Manifest dir not found for view '{view}': {view_dir}")
        candidates = sorted([c for c in view_dir.iterdir() if c.is_file() and c.suffix==".json"], key=lambda x: x.name)
        if not candidates:
            raise FileNotFoundError(f"No manifests found in {view_dir}")
        return candidates[-1]
    today = date.today().strftime("%Y-%m-%d")
    p = view_dir / f"{today}.json"
    if not p.exists():
        raise FileNotFoundError(f"Manifest not found for view '{view}' and today {today}: {p}. "
                                f"Pass --date or --latest to choose a manifest.")
    return p


def build_one(manifest_path: Path, immutable_root: Path, views_root: Path, *,
              workers: int, skip_missing_targets: bool, verbose: bool,
              dry_run: bool, prune: bool, daily: int, weekly: int, monthly: int, yearly: int):
    if builder is None:
        raise SystemExit("Could not import build_view_from_manifest.py.")

    builder.build_from_manifest(
        manifest_path=manifest_path,
        immutable_root=immutable_root,
        views_root=views_root,
        dry_run=dry_run,
        skip_missing_targets=skip_missing_targets,
        verbose=verbose,
        workers=workers,
    )

    if prune and not dry_run:
        with manifest_path.open(encoding="utf-8") as f:
            m = json.load(f)
        builder.prune_versions(views_root, m["view"], daily, weekly, monthly, yearly, verbose=verbose)


def main():
    ap = argparse.ArgumentParser(description="Build multiple views from a manifest root.")
    ap.add_argument("--manifest-root", required=True)
    ap.add_argument("--immutable-root", required=True)
    ap.add_argument("--views-root", required=True)
    ap.add_argument("--views", nargs="*", default=["institute_pi", "pi", "type", "date"],
                    choices=["institute_pi", "pi", "type", "date"]) 

    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--date", help="YYYY-MM-DD version to build for each view.")
    sel.add_argument("--latest", action="store_true", help="Build the latest manifest in each view directory.")

    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--skip-missing-targets", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--daily", type=int, default=14)
    ap.add_argument("--weekly", type=int, default=8)
    ap.add_argument("--monthly", type=int, default=12)
    ap.add_argument("--yearly", type=int, default=7)

    ap.add_argument("--parallel-views", type=int, default=1)

    args = ap.parse_args()

    manifest_root = Path(args.manifest_root)
    immutable_root = Path(args.immutable_root)
    views_root = Path(args.views_root)

    manifests: List[Path] = []
    for v in args.views:
        mp = find_manifest(manifest_root, v, args.date, args.latest)
        manifests.append(mp)
        if args.verbose:
            print(f"Selected manifest for {v}: {mp}")

    def run(mp: Path):
        build_one(
            manifest_path=mp,
            immutable_root=immutable_root,
            views_root=views_root,
            workers=max(1, args.workers),
            skip_missing_targets=args.skip_missing_targets,
            verbose=args.verbose,
            dry_run=args.dry_run,
            prune=args.prune,
            daily=args.daily,
            weekly=args.weekly,
            monthly=args.monthly,
            yearly=args.yearly,
        )

    if args.parallel_views <= 1:
        for mp in manifests:
            run(mp)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=args.parallel_views) as ex:
            futs = {ex.submit(run, mp): mp for mp in manifests}
            for fut in as_completed(futs):
                fut.result()

    if args.verbose:
        print("Done.")

if __name__ == "__main__":
    main()
