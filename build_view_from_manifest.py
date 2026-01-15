#!/usr/bin/env python3
# build_view_from_manifest.py (Option A: global .versions under views_root, top-level view is a symlink)
"""
Build an entire view from ONE minimal manifest, publishing to:
  <views_root>/.versions/<view>/<YYYY-MM-DD>/
And atomically set:
  <views_root>/<view> -> .versions/<view>/<YYYY-MM-DD>

Manifest fields used: view, generated_at, entries
"""
import argparse
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Dict


def rel_symlink(target: Path, link_path: Path):
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    rel = os.path.relpath(target, start=link_path.parent)
    os.symlink(rel, link_path)


def link_path_for_entry(view: str, version_dir: Path, e: dict) -> Path:
    y = int(e["year"])
    m = int(e["month"])
    leaf = str(e.get("leaf_name", e.get("project_id", "unknown"))).strip() or e.get("project_id")
    if view == "date":
        return version_dir / f"{y:04d}" / f"{m:02d}" / leaf
    elif view == "type":
        tdir = e.get("type_dir", "UNKNOWN_TYPE")
        return version_dir / tdir / f"{y:04d}" / f"{m:02d}" / leaf
    elif view == "pi":
        psh = e.get("pi_shard", "U")
        pdir = e.get("pi_dir", "UNKNOWN")
        return version_dir / psh / pdir / f"{y:04d}" / f"{m:02d}" / leaf
    elif view == "institute_pi":
        ish = e.get("institute_shard", "U")
        idir = e.get("institute_dir", "UNKNOWN")
        psh = e.get("pi_shard", "U")
        pdir = e.get("pi_dir", "UNKNOWN")
        return version_dir / ish / idir / psh / pdir / f"{y:04d}" / f"{m:02d}" / leaf
    else:
        raise ValueError(f"Unsupported view: {view}")


def build_from_manifest(manifest_path: Path, immutable_root: Path, views_root: Path,
                        dry_run=False, skip_missing_targets=False, verbose=False,
                        workers: int = 16):
    with manifest_path.open(encoding="utf-8") as f:
        m = json.load(f)

    view = m["view"]
    version = m["generated_at"]  # YYYY-MM-DD
    entries = m["entries"]

    # Global versions dir per Option A
    versions_dir = views_root / ".versions" / view
    final_dir = versions_dir / version
    build_dir = versions_dir / f".build-{version}"

    # Overwrite same-day: remove existing final_dir
    if final_dir.exists():
        if verbose:
            print(f"Removing existing version (same day): {final_dir}")
        if not dry_run:
            shutil.rmtree(final_dir)

    # Clean any stale build dir
    if build_dir.exists():
        if verbose:
            print(f"Removing stale build dir: {build_dir}")
        if not dry_run:
            shutil.rmtree(build_dir)

    if not dry_run:
        versions_dir.mkdir(parents=True, exist_ok=True)
        build_dir.mkdir(parents=True, exist_ok=True)

    created, skipped = 0, 0

    def task(e):
        nonlocal created, skipped
        y = int(e["year"])
        mth = int(e["month"])
        pid = str(e["project_id"]).strip()
        link_path = link_path_for_entry(view, build_dir, e)
        target = immutable_root / f"{y:04d}" / f"{mth:02d}" / pid

        if not target.exists():
            if skip_missing_targets:
                if verbose:
                    print(f"Skipping missing target: {target}")
                skipped += 1
                return
            else:
                raise FileNotFoundError(f"Target not found: {target}")

        if verbose:
            print(f"Link: {link_path} -> {target}")
        if not dry_run:
            rel_symlink(target, link_path)
        created += 1

    # Parallel creation
    if workers <= 1:
        for e in entries:
            task(e)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(task, e) for e in entries]
            for fut in as_completed(futures):
                _ = fut.result()

    if not dry_run:
        # Write minimal manifest into version directory (ensure entry_count)
        m["entry_count"] = len(entries)
        minimal = {k: m[k] for k in ("view", "generated_at", "script_version", "entry_count", "entries") if k in m}
        with (build_dir / "metadata.json").open("w", encoding="utf-8") as f:
            json.dump(minimal, f, indent=2, sort_keys=True)

        # Atomic publish
        os.rename(build_dir, final_dir)

        # Update top-level view symlink atomically: <views_root>/<view> -> .versions/<view>/<version>
        view_link = views_root / view
        tmp = views_root / f".{view}.new"
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        rel = os.path.relpath(final_dir, start=views_root)
        os.symlink(rel, tmp)
        os.replace(tmp, view_link)

    print(f"Built version: {final_dir if not dry_run else str(final_dir)+' (dry-run)'}")
    print(f"Created symlinks: {created}" + (f", skipped: {skipped}" if skipped else ""))


def parse_version_dirs(versions_dir: Path) -> List[Tuple[date, Path]]:
    out = []
    if not versions_dir.exists():
        return out
    for child in versions_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        try:
            dt = datetime.strptime(name, "%Y-%m-%d").date()
            out.append((dt, child))
        except Exception:
            continue
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def prune_versions(views_root: Path, view: str, daily: int, weekly: int, monthly: int, yearly: int, verbose=False):
    versions_dir = views_root / ".versions" / view
    versions = parse_version_dirs(versions_dir)
    if not versions:
        return

    today = date.today()
    keep_paths = set([versions[0][1]])  # always keep newest

    def week_key(d: date):
        y, w, _ = d.isocalendar()
        return (y, w)
    def month_key(d: date):
        return (d.year, d.month)
    def year_key(d: date):
        return d.year

    daily_cutoff = today - timedelta(days=daily) if daily > 0 else date.min
    weekly_cutoff = today - timedelta(weeks=weekly) if weekly > 0 else date.min

    latest_week: Dict[Tuple[int, int], Tuple[date, Path]] = {}
    latest_month: Dict[Tuple[int, int], Tuple[date, Path]] = {}
    latest_year: Dict[int, Tuple[date, Path]] = {}

    for d, p in versions:
        if d >= daily_cutoff:
            keep_paths.add(p)
            continue
        if d >= weekly_cutoff:
            wk = week_key(d)
            if wk not in latest_week or d > latest_week[wk][0]:
                latest_week[wk] = (d, p)
            continue
        mk = month_key(d)
        if mk not in latest_month or d > latest_month[mk][0]:
            latest_month[mk] = (d, p)

    if monthly > 0:
        months_sorted = sorted(latest_month.keys(), reverse=True)
        for mk in months_sorted[:monthly]:
            keep_paths.add(latest_month[mk][1])
        for mk in months_sorted[monthly:]:
            d, p = latest_month[mk]
            yk = year_key(d)
            if yk not in latest_year or d > latest_year[yk][0]:
                latest_year[yk] = (d, p)
    else:
        for d, p in latest_month.values():
            yk = year_key(d)
            if yk not in latest_year or d > latest_year[yk][0]:
                latest_year[yk] = (d, p)

    if yearly > 0:
        years_sorted = sorted(latest_year.keys(), reverse=True)
        for y in years_sorted[:yearly]:
            keep_paths.add(latest_year[y][1])

    for _, (d, p) in latest_week.items():
        keep_paths.add(p)

    deleted = 0
    for _, p in versions:
        if p not in keep_paths:
            if verbose:
                print(f"Pruning version: {p}")
            shutil.rmtree(p, ignore_errors=True)
            deleted += 1
    if verbose:
        print(f"Pruned {deleted} version(s) under {versions_dir}")


def main():
    ap = argparse.ArgumentParser(description="Build an entire view from a minimal manifest (Option A layout).")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--immutable-root", required=True)
    ap.add_argument("--views-root", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-missing-targets", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    # Pruning options
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--daily", type=int, default=14)
    ap.add_argument("--weekly", type=int, default=8)
    ap.add_argument("--monthly", type=int, default=12)
    ap.add_argument("--yearly", type=int, default=7)
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    views_root = Path(args.views_root)

    build_from_manifest(
        manifest_path=manifest_path,
        immutable_root=Path(args.immutable_root),
        views_root=views_root,
        dry_run=args.dry_run,
        skip_missing_targets=args.skip_missing_targets,
        verbose=args.verbose,
        workers=max(1, args.workers),
    )

    if args.prune and not args.dry_run:
        with manifest_path.open(encoding="utf-8") as f:
            m = json.load(f)
        prune_versions(views_root, m["view"], args.daily, args.weekly, args.monthly, args.yearly, verbose=args.verbose)

if __name__ == "__main__":
    main()
