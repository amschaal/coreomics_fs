#!/usr/bin/env python3
# build_views.py
import argparse
import csv, sys, os, shutil, datetime, json, sqlite3
from pathlib import Path
from .views import safe_name
from .permissions import load_perm_policy, enforce_project, enforce_share, enforce_tree
from ..config import load_config, get_share_subdirectory, share_output_dir
# ----- load config ---------------------------------------------------------
cfg = load_config()

DB_DIR      = cfg["paths"]["submissions_db_directory"]
CANON_ROOT = Path(cfg["paths"]["canonical_root"])
VIEWS_ROOT = Path(cfg["paths"]["views_root"])
DATE_FMT   = cfg["paths"]["date_format"]
LOG_NAME   = cfg["paths"]["log_name"]
ERROR_LOG   = cfg["paths"]["error_log"]

# Optional parallel views tree of Windows .lnk shortcuts (blank = feature off).
_win_root = (cfg.get("paths", "windows_views_root", fallback="") or "").strip()
WIN_VIEWS_ROOT = Path(_win_root) if _win_root else None
# How leaves address the canonical tree: "unc" (\\server\share\...) or "drive"
# (a mapped letter, e.g. Z:\...). Both need windows_server_path (the server dir
# the Windows share maps to); unc also needs windows_unc_base, drive needs
# windows_drive_letter.
WIN_TARGET = (cfg.get("paths", "windows_views_target", fallback="unc") or "unc").strip().lower()
WIN_SERVER_PATH = (cfg.get("paths", "windows_server_path", fallback="") or "").strip()
WIN_UNC_BASE = (cfg.get("paths", "windows_unc_base", fallback="") or "").strip()
WIN_DRIVE_LETTER = (cfg.get("paths", "windows_drive_letter", fallback="") or "").strip()

# Ownership/permission policy (None when [permissions] group is unconfigured).
POLICY = load_perm_policy(cfg)

# ----- utility ------------------------------------------------------------
def log(msg, log_path, console=False):
    if console:
        print(msg)
    with open(log_path, "a") as lf:
        lf.write(msg + "\n")

def _deletable_roots():
    """Roots a build may move/delete within: the views trees, never canonical."""
    roots = [VIEWS_ROOT.resolve()]
    if WIN_VIEWS_ROOT:
        roots.append(WIN_VIEWS_ROOT.resolve())
    return roots


def _assert_under_views(path: Path, op: str):
    """Abort unless ``path`` lives inside a views tree (never the canonical tree).

    Checks the *parent*, resolving symlinks along the way, because deleting an
    entry is governed by where it lives — not where a symlink leaf points. This
    deliberately does NOT resolve a symlink leaf itself: unlinking a view symlink
    must be validated by the symlink's location, not its canonical target, so a
    view symlink that points into the canonical tree is still safely removable and
    its target is never followed or deleted."""
    parent = Path(path).parent.resolve()
    roots = _deletable_roots()
    if not any(parent == r or parent.is_relative_to(r) for r in roots):
        sys.exit(f"refusing to {op}: {path} is not inside a views root "
                 f"({', '.join(str(r) for r in roots)})")


def _safe_unlink(path):
    _assert_under_views(path, "unlink")
    Path(path).unlink()


def _safe_rmtree(path):
    _assert_under_views(path, "rmtree")
    shutil.rmtree(path)


def _safe_move(src, dst):
    _assert_under_views(src, "move")
    _assert_under_views(dst, "move")
    shutil.move(str(src), str(dst))


def _safe_replace(src, dst):
    _assert_under_views(src, "replace")
    _assert_under_views(dst, "replace")
    os.replace(src, dst)


def rel_symlink(target: Path, link: Path):
    """Create a relative symlink; parent dirs are ensured."""
    link.parent.mkdir(parents=True, exist_ok=True)
    rel_target = os.path.relpath(target, start=link.parent)
    if link.is_symlink() or link.exists():
        _safe_unlink(link)
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


def _updated_ts(proj):
    """Epoch seconds for a project's ``updated`` field, or None if unusable."""
    from ..cli.readme import _parse_ts
    return _parse_ts(proj.get('updated') or proj.get('date_updated'))


def refresh_submission_json(project_dir, proj) -> bool:
    """Rewrite ``<project_dir>/.submission/submission.json`` if the on-disk copy
    is missing or older (by ``updated``) than ``proj``. Returns True if written.

    Staleness is content-based (compares the ``updated`` field), so it stays
    correct regardless of filesystem mtimes. The directory mtime is left alone
    — it intentionally tracks ``submitted`` (see ``_set_timestamp``)."""
    sj_path = Path(project_dir) / '.submission' / 'submission.json'
    new_ts = _updated_ts(proj)
    if sj_path.exists():
        try:
            with open(sj_path) as f:
                on_disk = json.load(f)
            old_ts = _updated_ts(on_disk)
        except Exception:
            old_ts = None
        # Skip only when we can prove the on-disk copy is at least as new.
        if old_ts is not None and new_ts is not None and old_ts >= new_ts:
            return False
    sj_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sj_path, 'w') as f:
        json.dump(proj, f, indent=2)
    return True

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
    # Enforce ownership/permissions every build (idempotent, self-healing) so
    # pre-existing project dirs get locked down too.
    if POLICY:
        enforce_project(dst, POLICY, CANON_ROOT)
    return dst

# ----- build a single view version ----------------------------------------
def _iter_view_leaves(view_name, comps, projects, error_log):
    """Yield ``(parts, canon, submitted)`` for each project that resolves in a
    view: the path segments, its canonical directory, and the submitted date.

    Shared by the POSIX symlink build (:func:`build_view_version`) and the
    Windows ``.lnk`` build (:func:`build_windows_views`) so both trees use the
    identical view structure and skip-on-missing-field behavior. A project whose
    extractor chokes on missing/invalid data is logged and skipped."""
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

        yield parts, ensure_canonical(proj), submitted


def build_view_version(view_name, comps, projects, version_dir, log_path):
    error_log = version_dir / ERROR_LOG
    for parts, canon, submitted in _iter_view_leaves(view_name, comps, projects, error_log):
        leaf = version_dir.joinpath(*parts)
        leaf.parent.mkdir(parents=True, exist_ok=True)
        rel_target = rel_symlink(canon, leaf)
        _set_timestamp(leaf, submitted)
        log(f"'{'/'.join(parts)}' -> '{rel_target}'", log_path)


# ----- build the Windows .lnk views tree -----------------------------------
def build_windows_views(VIEWS, projects):
    """Build a parallel views tree of Windows ``.lnk`` shortcuts (current state).

    Same structure as the POSIX ``views_root`` tree, but every segment is a real
    directory and each project leaf is a ``<id>.lnk`` shortcut into the canonical
    tree (Windows Explorer can't follow POSIX symlinks on a mapped SMB drive).
    No ``.versions`` history: each view is rebuilt in a temp dir and swapped in
    via atomic renames, so readers only ever see a complete tree."""
    from . import winlnk

    # Resolve and validate the canonical -> Windows-path mapping once up front so
    # a misconfiguration aborts before any disk work. The shortcut target is the
    # Windows prefix (UNC base or drive letter) joined to the canonical path
    # relative to the server dir that the Windows share maps to.
    if WIN_TARGET not in ("unc", "drive"):
        sys.exit(f"unknown windows_views_target {WIN_TARGET!r} (use 'unc' or 'drive')")
    if not WIN_SERVER_PATH:
        sys.exit("windows_views_root requires windows_server_path (the server "
                 "directory that the Windows share/drive maps to)")
    server_path = os.path.abspath(WIN_SERVER_PATH)
    canon_abs_root = os.path.abspath(CANON_ROOT)
    if canon_abs_root != server_path and not canon_abs_root.startswith(server_path + os.sep):
        sys.exit(f"windows_server_path {server_path} must be an ancestor of "
                 f"canonical_root {canon_abs_root}")
    if WIN_TARGET == "unc":
        if not WIN_UNC_BASE:
            sys.exit("windows_views_target = unc requires windows_unc_base (e.g. \\\\nas\\share)")
        prefix = WIN_UNC_BASE.rstrip("\\")
    else:
        if not WIN_DRIVE_LETTER:
            sys.exit("windows_views_target = drive requires windows_drive_letter (e.g. Z:)")
        prefix = WIN_DRIVE_LETTER.rstrip("\\")

    def win_target(canon_abs):
        suffix = os.path.relpath(canon_abs, start=server_path).replace(os.sep, "\\")
        return prefix + "\\" + suffix

    tmp_root = WIN_VIEWS_ROOT / ".tmp"
    if tmp_root.exists():
        _safe_rmtree(tmp_root)

    for view, comps in VIEWS.items():
        stage = tmp_root / view
        stage.mkdir(parents=True, exist_ok=True)
        error_log = stage / ERROR_LOG
        count = 0
        for parts, canon, submitted in _iter_view_leaves(view, comps, projects, error_log):
            leaf = stage.joinpath(*parts)
            leaf_lnk = leaf.with_name(leaf.name + ".lnk")
            leaf_lnk.parent.mkdir(parents=True, exist_ok=True)
            target = win_target(os.path.abspath(canon))
            if WIN_TARGET == "unc":
                winlnk.write_unc_lnk(leaf_lnk, target)
            else:
                winlnk.write_drive_lnk(leaf_lnk, target)
            _set_timestamp(leaf_lnk, submitted)
            count += 1

        # Swap the freshly built tree in for the live one via atomic renames:
        # move the current <view> aside, rename the new one into place, drop the
        # old. The only gap is the instant between the two renames — fine for a
        # periodic build with no concurrent critical reader. os.replace can't drop
        # a non-empty dir onto another, hence move-aside-then-rename.
        final = WIN_VIEWS_ROOT / view
        old = tmp_root / (view + ".old")
        if final.exists():
            _safe_replace(final, old)
        _safe_replace(stage, final)
        if old.exists():
            _safe_rmtree(old)
        print(f"[{view}] built {count} windows shortcuts - {final}")

    if tmp_root.exists():
        _safe_rmtree(tmp_root)


# ----- pruning -------------------------------------------------------------
def _parse_date(name: str) -> datetime.date | None:
    """Turn a folder name like 2024-03-15 into a date, or None if it doesn't match."""
    try:
        return datetime.datetime.strptime(name, DATE_FMT).date()
    except Exception:
        return None


def _safe_versions_root():
    """Resolve the view version root for pruning, or ``None`` if it doesn't exist
    yet (first build — nothing to prune).

    ``main`` already asserts the canonical and views *roots* are disjoint up front
    (:func:`_assert_roots_disjoint`), which subsumes any ``.versions``-vs-canonical
    overlap. This keeps a narrow backstop so prune stays self-guarding even if ever
    called outside ``main``: it refuses to operate if ``.versions`` somehow overlaps
    ``canonical_root``."""
    canon = CANON_ROOT.resolve()
    versions_root = (VIEWS_ROOT / ".versions").resolve()
    if (versions_root == canon
            or versions_root.is_relative_to(canon)
            or canon.is_relative_to(versions_root)):
        sys.exit(
            "refusing to prune: views version root "
            f"{versions_root} overlaps canonical_root {canon} — "
            "check [paths] views_root / canonical_root in your config"
        )
    if not versions_root.is_dir():
        return None
    return versions_root


def _assert_prunable(path: Path, versions_root: Path):
    """Last-line guard immediately before an ``rmtree``.

    The target must resolve to a *dated* snapshot folder strictly inside the
    validated ``versions_root`` — i.e. ``.versions`` must be an ancestor of the
    real (symlink-followed) path. A symlink that escapes the tree, a path outside
    ``.versions``, or a non-date folder name aborts the build rather than deleting
    anything."""
    resolved = path.resolve()
    if resolved == versions_root or not resolved.is_relative_to(versions_root):
        sys.exit(f"refusing to prune: {path} resolves outside version root {versions_root}")
    if _parse_date(path.name) is None:
        sys.exit(f"refusing to prune: {path} is not a dated snapshot folder")


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

    # root that holds all view-specific version trees — validated to be a
    # ``.versions`` dir disjoint from canonical_root before we delete anything.
    versions_root = _safe_versions_root()
    if versions_root is None:
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
                _assert_prunable(p, versions_root)
                print(f'prune {p}')
                _safe_rmtree(p)
                # remove any stray symlinks that pointed to the deleted dir
                for link in view_dir.iterdir():
                    if link.is_symlink() and link.resolve() == p:
                        _safe_unlink(link)

# ----- main ----------------------------------------------------------------
def _assert_roots_disjoint():
    """Refuse to run if the canonical and views trees overlap on disk.

    The two must be entirely separate directory trees. The build re-modes the
    *whole* views tree with ``enforce_tree`` (group ``r-x``, non-writable) and
    prunes dated folders beneath ``.versions``; if ``canonical_root`` sat inside
    ``views_root`` (or vice versa) those sweeps would strip write bits from — or
    delete — real submission data. Note this is stricter than prune's own guard,
    which only forbids ``.versions`` itself from overlapping canonical: here we
    reject an ancestor/descendant relationship between the two *roots*, catching
    e.g. ``views_root`` being a parent of ``canonical_root`` with ``.versions`` as
    a harmless-looking sibling. Validated once, before any disk work. The
    optional ``windows_views_root`` is held to the same rule against both other
    roots (the Windows build rebuilds/swaps its whole tree)."""
    roots = [("canonical_root", CANON_ROOT.resolve()),
             ("views_root", VIEWS_ROOT.resolve())]
    if WIN_VIEWS_ROOT:
        roots.append(("windows_views_root", WIN_VIEWS_ROOT.resolve()))
    for i in range(len(roots)):
        for j in range(i + 1, len(roots)):
            (n1, p1), (n2, p2) = roots[i], roots[j]
            if p1 == p2 or p1.is_relative_to(p2) or p2.is_relative_to(p1):
                sys.exit(
                    f"refusing to run: {n1} and {n2} overlap "
                    f"({n1}={p1}, {n2}={p2}) — they must be separate directory "
                    "trees. Check [paths] in your config."
                )


def _assert_views_under_canonical_parent():
    """Require each views tree to live under canonical_root's parent directory.

    The deletion guard (:func:`_assert_under_views`) permits move/delete anywhere
    inside a views root, so a views root must be confined near the canonical data
    — never something far-reaching like ``/`` or ``/views``. We require
    ``views_root`` (and ``windows_views_root`` when set) to resolve inside
    ``canonical_root``'s parent, e.g. ``/share/proteomics/coreomics/{projects,views}``.
    Disjointness from canonical is already enforced by ``_assert_roots_disjoint``."""
    canon_parent = CANON_ROOT.resolve().parent
    checks = [("views_root", VIEWS_ROOT.resolve())]
    if WIN_VIEWS_ROOT:
        checks.append(("windows_views_root", WIN_VIEWS_ROOT.resolve()))
    for name, p in checks:
        if not p.is_relative_to(canon_parent):
            sys.exit(
                f"refusing to run: {name} {p} must live inside canonical_root's "
                f"parent directory {canon_parent} (e.g. {canon_parent}/views "
                f"alongside the projects tree). Check [paths] in your config."
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build filesystem views from submission data")
    parser.add_argument(
        "projects_file",
        nargs="?",
        help="Path to submissions file (.csv, .json, .db/.sqlite). Defaults to submissions.db from config.",
    )
    parser.add_argument("--no-readme", action="store_true", help="Skip per-project README.md generation (submission.json is still refreshed).")
    parser.add_argument("--updated-days", type=int, metavar="N", help="Only refresh projects whose submission was updated in the last N days (default: all).")
    parser.add_argument("--enforce-permissions", action="store_true", help="Apply the [permissions] ownership/mode policy across the whole canonical + views trees and exit (one-time migration). Run as root to also chown to the configured owner.")
    args = parser.parse_args(argv)

    # The canonical and views trees must be disjoint: the build re-modes and
    # prunes the entire views tree, which would corrupt or delete canonical data
    # if either root were nested in the other. Validate before any disk work.
    _assert_roots_disjoint()
    # ...and each views tree must live under canonical_root's parent, so the
    # deletion guard's allowlist can never be widened to a far-away path.
    _assert_views_under_canonical_parent()

    # Validate the share subdirectory once up front so a misconfiguration aborts
    # before any disk work (raises ValueError on an invalid value).
    try:
        get_share_subdirectory(cfg)
    except ValueError as e:
        parser.error(str(e))

    # New dirs/files default to group r-x / r-- so the tree stays locked down
    # without an explicit chmod on every path.
    if POLICY:
        os.umask(0o022)

    if args.enforce_permissions:
        if not POLICY:
            parser.error("--enforce-permissions requires [permissions] group to be configured")
        print(f"Enforcing permissions on {CANON_ROOT} ...")
        enforce_tree(CANON_ROOT, POLICY, project_dirs_writable=True,
                     share_name=get_share_subdirectory(cfg))
        print(f"Enforcing permissions on {VIEWS_ROOT} ...")
        enforce_tree(VIEWS_ROOT, POLICY)
        if WIN_VIEWS_ROOT:
            print(f"Enforcing permissions on {WIN_VIEWS_ROOT} ...")
            enforce_tree(WIN_VIEWS_ROOT, POLICY)
        print("Done.")
        return

    file_path = Path(args.projects_file) if args.projects_file else Path(DB_DIR) / 'submissions.db'

    is_csv = file_path.suffix == '.csv'
    if is_csv:
        from .views import VIEWS
    else:
        from .json_views import VIEWS
    print(f'Building from file: {file_path}')
    projects = read_projects(file_path)
    today = datetime.date.today().strftime(DATE_FMT)

    # Refresh per-project .submission/submission.json (when the record's `updated`
    # has advanced) and (re)generate README.md when missing/stale. README rendering
    # expects JSON-style keys, so this pass is skipped for CSV input.
    if not is_csv:
        from ..cli.readme import ensure_readme
        cutoff_ts = None
        if args.updated_days is not None:
            if args.updated_days < 0:
                parser.error("--updated-days must be zero or a positive integer")
            cutoff_ts = (datetime.datetime.now() - datetime.timedelta(days=args.updated_days)).timestamp()
        refreshed = readmes = 0
        for proj in projects:
            try:
                if cutoff_ts is not None:
                    pts = _updated_ts(proj)
                    if pts is not None and pts < cutoff_ts:
                        continue
                dst = ensure_canonical(proj)
                if refresh_submission_json(dst, proj):
                    refreshed += 1
                # README (and the share dir, if configured) live in the share
                # subdirectory when set; submission.json stays at the project root.
                out_dir = share_output_dir(dst, cfg, create=True)
                # The share dir is created after enforce_project ran, so make it
                # group-writable here (lab users share data inside it).
                if POLICY and Path(out_dir) != dst:
                    enforce_share(out_dir, POLICY)
                if not args.no_readme and ensure_readme(out_dir, proj):
                    readmes += 1
            except Exception as e:
                print(f"Refresh skipped for id={proj.get('id') or proj.get('ID')}: {e}")
        print(f"Refreshed {refreshed} submission.json, wrote {readmes} README.md")

    for view, comps in VIEWS.items():
        # temporary staging area
        tmp_dir = VIEWS_ROOT / ".versions_tmp" / view / today
        if tmp_dir.exists():
            _safe_rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True)

        log_path = tmp_dir / LOG_NAME
        build_view_version(view, comps, projects, tmp_dir, log_path)

        # final destination (replace existing version for today)
        final_dir = VIEWS_ROOT / ".versions" / view / today
        if final_dir.is_symlink():
            _safe_unlink(final_dir)     # rmtree can't remove a symlink
        elif final_dir.is_dir():
            _safe_rmtree(final_dir)
        _safe_move(tmp_dir, final_dir)

        # latest symlink inside .versions
        latest_link = VIEWS_ROOT / ".versions" / view / "latest"
        rel_symlink(final_dir, latest_link)

        # top-level view symlink
        view_link = VIEWS_ROOT / view
        rel_symlink(final_dir, view_link)

        # summary
        print(f"[{view}] built version {today} - log: {log_path}")

    # Parallel Windows .lnk views tree (current state only), when configured.
    if WIN_VIEWS_ROOT:
        build_windows_views(VIEWS, projects)

    # Lock down the whole views tree once: container dirs, version dirs and the
    # symlinks within them, so users can browse but not delete view structure.
    if POLICY:
        enforce_tree(VIEWS_ROOT, POLICY)
        if WIN_VIEWS_ROOT:
            enforce_tree(WIN_VIEWS_ROOT, POLICY)

    prune_old_views()

if __name__ == "__main__":
    main()
    