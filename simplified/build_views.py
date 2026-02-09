#!/usr/bin/env python3
# build_views.py
import csv, sys, os, shutil, datetime, json, yaml
from pathlib import Path
from views import VIEWS, safe_name

# ----- load config ---------------------------------------------------------
with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

CANON_ROOT = Path(cfg["canonical_root"])
VIEWS_ROOT = Path(cfg["views_root"])
DATE_FMT   = cfg["date_format"]
LOG_NAME   = cfg["log_name"]
ERROR_LOG   = cfg["error_log"]

# ----- utility ------------------------------------------------------------
def log(msg, log_path):
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
def read_projects(csv_path: Path):
    with open(csv_path, newline="") as cf:
        rdr = csv.DictReader(cf)
        return list(rdr)

# ----- build canonical layout ---------------------------------------------
def ensure_canonical(proj):
    y, m = proj["Submitted"].split()[0].split("-")[:2]
    month = f"{int(m):02d}"
    dst = CANON_ROOT / y / month / proj["ID"]
    dst.mkdir(parents=True, exist_ok=True)   # no‑op if exists
    return dst

# ----- build a single view version ----------------------------------------
def build_view_version(view_name, comps, projects, version_dir, log_path):
    error_log = version_dir / ERROR_LOG
    for proj in projects:
        # compute each component; abort on missing data
        parts = []
        for fn in comps:
            try:
                val = fn(proj)
                if not val:
                    raise ValueError
                parts.append(val)
            except Exception:
                log(f"Missing/invalid field for {proj['ID']} in view '{view_name}'", error_log)
                parts = None
                break
        if not parts:
            continue

        canon = ensure_canonical(proj)
        leaf = version_dir.joinpath(*parts)
        leaf.parent.mkdir(parents=True, exist_ok=True)
        rel_target = rel_symlink(canon, leaf)
        log(f"'{'/'.join(parts)}' -> '{rel_target}'", log_path)


# ----- main ----------------------------------------------------------------
def main(csv_file: str):
    projects = read_projects(Path(csv_file))
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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: build_views.py <project_data.csv>")
    main(sys.argv[1])