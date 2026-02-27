#!/usr/bin/env python3
# build_views.py
import csv, sys, os, shutil, datetime, json, sqlite3
from pathlib import Path
from .views import safe_name
from ..config import load_config
# ----- load config ---------------------------------------------------------
cfg = load_config()

DB_DIR      = cfg["paths"]["submissions_db_directory"]
CANON_ROOT = Path(cfg["paths"]["canonical_root"])
VIEWS_ROOT = Path(cfg["paths"]["views_root"])
DATE_FMT   = cfg["paths"]["date_format"]
LOG_NAME   = cfg["paths"]["log_name"]
ERROR_LOG   = cfg["paths"]["error_log"]

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
    if projects_path.suffix in ('.db', '.sqlite'):
        return load_from_db(projects_path)


from ..db.sqlite_submissions import SubmissionsDB


def load_from_db(path: Path):
    db = SubmissionsDB(path)
    try:
        results = db.fetch_all_submissions()
    finally:
        db.close()
    print(f'{len(results)}  fetched from db')
    return results

def _set_timestamp(path: str, timestamp: str, follow: bool = False) -> None:
    """
    Set the access and modification times of ``path`` to ``ts``.
    """
    ts = datetime.datetime.fromisoformat(timestamp).timestamp()
    os.utime(path, (ts, ts), follow_symlinks=follow)

# ----- build canonical layout ---------------------------------------------
def ensure_canonical(proj):
    submitted = proj.get('submitted') or proj.get('Submitted')
    id = proj.get('id') or proj.get('ID')
    y, m = submitted.split()[0].split("-")[:2]
    month = f"{int(m):02d}"
    dst = CANON_ROOT / y / month / id
    if not dst.exists():
        # dst.mkdir(parents=True, exist_ok=True)   # no-op if exists
        subdir = dst / '.submission'
        subdir.mkdir(parents=True, exist_ok=True)
        submission_json_path = subdir / 'submission.json'
        with open(submission_json_path, 'w') as f:
            json.dump(proj, f, indent=2)
        _set_timestamp(dst, submitted)
    return dst

# ----- build a single view version ----------------------------------------
def build_view_version(view_name, comps, projects, version_dir, log_path):
    error_log = version_dir / ERROR_LOG
    for proj in projects:
        id = proj.get('id') or proj.get('ID')
        submitted = proj.get('submitted') or proj.get('Submitted')
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
        _set_timestamp(leaf, submitted)
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
    retain_cfg = cfg["retain"]
    keep_daily   = cfg.getint("retain", "daily") or 7
    keep_weekly  = cfg.getint("retain", "weekly") or 4
    keep_monthly = cfg.getint("retain", "monthly") or 12

    # root that holds all view-specific version trees
    versions_root = VIEWS_ROOT / ".versions"
    if not versions_root.is_dir():
        return

    for view_dir in versions_root.iterdir():          # each <view>
        if not view_dir.is_dir():
            continue

        # collect dated sub-folders (e.g. 2024-03-15)
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
def main(projects_file: str=None):
    if projects_file:
        file_path = Path(projects_file)
    else:
        file_path = Path(DB_DIR) / 'submissions.db'
    if file_path.suffix == '.csv':
        from .views import VIEWS
    else:
        from .json_views import VIEWS
    print(f'Building from file: {file_path}')
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

        # top-level view symlink
        view_link = VIEWS_ROOT / view
        rel_symlink(final_dir, view_link)

        # summary
        print(f"[{view}] built version {today} - log: {log_path}")
    
    prune_old_views()

if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    elif len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        sys.exit("Usage: build_views.py <project_data.csv/project_data.json>")
    