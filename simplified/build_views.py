#!/usr/bin/env python3
# build_views.py
import csv, sys, os, shutil, datetime, json, yaml
from pathlib import Path
from views import safe_name

# ----- load config ---------------------------------------------------------
with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

CANON_ROOT = Path(cfg["canonical_root"])
VIEWS_ROOT = Path(cfg["views_root"])
DATE_FMT   = cfg["date_format"]
LOG_NAME   = cfg["log_name"]
ERROR_LOG   = cfg["error_log"]

# ----- utility ------------------------------------------------------------
def log(msg, log_path, console=False):
    if console:
        print(msg)
    with open(log_path, "a") as lf:
        lf.write(msg + "\n")

def rel_symlink(target: Path, link: Path):
    """Create a relative symlink; parent dirs are ensured."""
    link.parent.mkdir(parents=True, exist_ok=True)
    rel_target = os.path.relpath(target, start=link.parent)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(rel_target)
    return rel_target

# ----- read CSV -----------------------------------------------------------
def read_projects(projects_path: Path):
    if projects_path.suffix == '.csv':
        with open(projects_path, newline="") as cf:
            rdr = csv.DictReader(cf)
            return list(rdr)
    if projects_path.suffix == '.json':
        with open(projects_path, newline="") as cf:
            projects = json.load(cf)
            if 'results' in projects:
                return projects['results']
            else:
                return projects

# ----- build canonical layout ---------------------------------------------
def ensure_canonical(proj):
    submitted = proj.get('submitted') or proj.get('Submitted')
    id = proj.get('id') or proj.get('ID')
    y, m = submitted.split()[0].split("-")[:2]
    month = f"{int(m):02d}"
    dst = CANON_ROOT / y / month / id
    dst.mkdir(parents=True, exist_ok=True)   # no‑op if exists
    return dst

# ----- build a single view version ----------------------------------------
def build_view_version(view_name, comps, projects, version_dir, log_path):
    error_log = version_dir / ERROR_LOG
    for proj in projects:
        id = proj.get('id') or proj.get('ID')
        # compute each component; abort on missing data
        parts = []
        for fn in comps:
            try:
                val = fn(proj)
                if not val:
                    raise ValueError
                parts.append(val)
            except Exception:
                log(f"Missing/invalid field for {id} in view '{view_name}'", error_log)
                parts = None
                break
        if not parts:
            continue

        canon = ensure_canonical(proj)
        leaf = version_dir.joinpath(*parts)
        leaf.parent.mkdir(parents=True, exist_ok=True)
        rel_target = rel_symlink(canon, leaf)
        log(f"'{'/'.join(parts)}' -> '{rel_target}'", log_path)


# ----- pruning -------------------------------------------------------------
def _parse_date(name: str) -> datetime.date | None:
    """Turn a folder name like 2024-03-15 into a date, or None if it doesn't match."""
    try:
        return datetime.datetime.strptime(name, DATE_FMT).date()
    except Exception:
        return None


def prune_old_views():
    """
    Delete stale view versions while keeping a configurable number of
    daily, weekly and monthly snapshots.
    """
    # --- retention settings (add to config.yaml if you want different defaults) ---
    retain_cfg = cfg.get("retain", {})
    keep_daily   = int(retain_cfg.get("daily",   7))
    keep_weekly  = int(retain_cfg.get("weekly",  4))
    keep_monthly = int(retain_cfg.get("monthly", 12))

    # root that holds all view‑specific version trees
    versions_root = VIEWS_ROOT / ".versions"
    if not versions_root.is_dir():
        return

    for view_dir in versions_root.iterdir():          # each <view>
        if not view_dir.is_dir():
            continue

        # collect dated sub‑folders (e.g. 2024-03-15)
        dated_dirs = [
            p for p in view_dir.iterdir()
            if p.is_dir() and _parse_date(p.name) is not None
        ]
        # newest → oldest
        dated_dirs.sort(key=lambda p: _parse_date(p.name), reverse=True)

        keep: set[Path] = set()

        # -------- daily --------
        keep.update(dated_dirs[:keep_daily])

        # -------- weekly --------
        weeks_seen = set()
        for p in dated_dirs:
            d = _parse_date(p.name)
            wk = (d.isocalendar()[0], d.isocalendar()[1])   # year, week
            if len(weeks_seen) < keep_weekly and wk not in weeks_seen:
                weeks_seen.add(wk)
                keep.add(p)

        # -------- monthly --------
        months_seen = set()
        for p in dated_dirs:
            d = _parse_date(p.name)
            mo = (d.year, d.month)
            if len(months_seen) < keep_monthly and mo not in months_seen:
                months_seen.add(mo)
                keep.add(p)
        # -------- delete everything else --------
        for p in dated_dirs:
            if p not in keep:
                print(f'prune {p}')
                shutil.rmtree(p)
                # remove any stray symlinks that pointed to the deleted dir
                for link in view_dir.iterdir():
                    if link.is_symlink() and link.resolve() == p:
                        link.unlink()

# ----- main ----------------------------------------------------------------
def main(projects_file: str):
    file_path = Path(projects_file)
    if file_path.suffix == '.csv':
        from views import VIEWS
    elif file_path.suffix == '.json':
        from json_views import VIEWS
    projects = read_projects(file_path)
    today = datetime.date.today().strftime(DATE_FMT)

    for view, comps in VIEWS.items():
        # temporary staging area
        tmp_dir = VIEWS_ROOT / ".versions_tmp" / view / today
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True)

        log_path = tmp_dir / LOG_NAME
        build_view_version(view, comps, projects, tmp_dir, log_path)

        # final destination (replace existing version for today)
        final_dir = VIEWS_ROOT / ".versions" / view / today
        if final_dir.is_symlink() or final_dir.is_dir():
            shutil.rmtree(final_dir)
        shutil.move(str(tmp_dir), str(final_dir))

        # latest symlink inside .versions
        latest_link = VIEWS_ROOT / ".versions" / view / "latest"
        rel_symlink(final_dir, latest_link)

        # top‑level view symlink
        view_link = VIEWS_ROOT / view
        rel_symlink(final_dir, view_link)

        # summary
        print(f"[{view}] built version {today} – log: {log_path}")
    
    prune_old_views()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: build_views.py <project_data.csv/project_data.json>")
    main(sys.argv[1])