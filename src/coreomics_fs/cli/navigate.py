#!/usr/bin/env python3
# navigate.py — search submissions and emit a project directory to cd into.
#
# This is the backend for the `ccd` shell function (scripts/ccd.sh). It is a
# child process and therefore CANNOT change the parent shell's cwd; instead it
# prints the single chosen directory to STDOUT and lets the shell function run
# `cd`. All human-facing output (menus, prompts, errors) goes to STDERR so the
# stdout capture in `dir="$(coreomics-nav ...)"` stays clean.
import argparse
import os
import sys
from pathlib import Path

from ..config import load_config
from ..db.sqlite_submissions import SubmissionsDB
from ..build.json_views import VIEWS

cfg = load_config()
CANON_ROOT = Path(cfg["paths"]["canonical_root"])
VIEWS_ROOT = Path(cfg["paths"]["views_root"])
DB_PATH = Path(cfg["paths"]["submissions_db_directory"]) / "submissions.db"

# Resolved roots used by validate_path() to confine emitted paths.
_CANON_RESOLVED = CANON_ROOT.resolve()
_VIEWS_RESOLVED = VIEWS_ROOT.resolve()

# Valid labels for the -d/--dir flag: the canonical tree plus every view name.
DIR_LABELS = ("canonical", *VIEWS.keys())


def eprint(*args, **kwargs):
    """Print to stderr (never pollutes the stdout path capture)."""
    print(*args, file=sys.stderr, **kwargs)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return child.is_relative_to(parent)  # Python 3.9+
    except AttributeError:  # pragma: no cover - py<3.9 fallback
        try:
            return os.path.commonpath([str(child), str(parent)]) == str(parent)
        except ValueError:
            return False


def validate_path(path: Path):
    """The single sanctioned stdout gate (defense at source).

    Emits the chosen directory *without* resolving symlinks, so a selected view
    path stays a view path. The view trees are symlinks into the canonical tree,
    so resolving would collapse every choice down to the canonical directory.
    Safety is still enforced against the real target via resolve():

    Returns the validated absolute path string, or None if it is not a real
    directory inside CANON_ROOT/VIEWS_ROOT or contains control characters.
    """
    abs_lexical = Path(os.path.abspath(path))   # absolute, NOT symlink-resolved
    real = abs_lexical.resolve()                 # real target, for safety checks
    # The real directory must exist and live inside a managed root...
    if not real.is_dir():
        return None
    if not (_is_within(real, _CANON_RESOLVED) or _is_within(real, _VIEWS_RESOLVED)):
        return None
    # ...and the path we actually emit must itself sit under a managed root.
    canon_lex = Path(os.path.abspath(CANON_ROOT))
    views_lex = Path(os.path.abspath(VIEWS_ROOT))
    if not (_is_within(abs_lexical, canon_lex) or _is_within(abs_lexical, views_lex)):
        return None
    s = str(abs_lexical)
    # Guarantee a single clean line for $(...) capture.
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in s):
        return None
    return s


# ---------- display helpers ----------
def _submitter_name(proj) -> str:
    first = proj.get("first_name") or ""
    last = proj.get("last_name") or ""
    name = f"{last}, {first}".strip(", ").strip()
    return name or "?"


def _pi_name(proj) -> str:
    pi = proj.get("pi")
    if isinstance(pi, dict):
        first = pi.get("first_name") or ""
        last = pi.get("last_name") or ""
    else:
        first = proj.get("pi_first_name") or ""
        last = proj.get("pi_last_name") or ""
    name = f"{last}, {first}".strip(", ").strip()
    return name or "?"


def _short_date(proj) -> str:
    submitted = proj.get("submitted") or proj.get("Submitted") or ""
    return submitted[:10] if submitted else "?"


def _internal_id(proj) -> str:
    return proj.get("internal_id") or proj.get("id") or "?"


def format_submission_line(proj) -> str:
    return (
        f"{_internal_id(proj):<12}  {_submitter_name(proj)}  "
        f"(PI: {_pi_name(proj)})  {_short_date(proj)}"
    )


# ---------- path computation ----------
def canonical_path(proj):
    submitted = proj.get("submitted") or proj.get("Submitted")
    sub_id = proj.get("id") or proj.get("ID")
    if not submitted or not sub_id:
        return None
    try:
        y, m = submitted.split()[0].split("-")[:2]
        month = f"{int(m):02d}"
    except (ValueError, IndexError):
        return None
    return CANON_ROOT / y / month / str(sub_id)


def view_paths(proj):
    """Yield (view_name, Path) for each defined view.

    Uses the top-level VIEWS_ROOT/<name> symlink, which already points at the
    latest built version, so no date-folder handling is needed. A view whose
    extractor chokes on dirty data is silently skipped.
    """
    for name, fns in VIEWS.items():
        try:
            parts = [fn(proj) for fn in fns]
        except Exception:
            continue
        if any(p in (None, "") for p in parts):
            continue
        yield name, VIEWS_ROOT.joinpath(name, *parts)


def candidate_directories(proj):
    """Return [(label, Path)] of existing canonical + view directories."""
    candidates = []
    canon = canonical_path(proj)
    if canon is not None:
        candidates.append(("canonical", canon))
    candidates.extend(view_paths(proj))
    # Keep only those that actually exist on disk (follows symlinks).
    return [(label, p) for label, p in candidates if p.exists()]


# ---------- interactive selection ----------
def _read_choice(prompt: str):
    """Read a line from the controlling terminal (stdin may be captured).

    Returns the stripped string, or None on EOF/interrupt (escape).
    """
    try:
        with open("/dev/tty", "r") as tty:
            eprint(prompt, end="")
            sys.stderr.flush()
            line = tty.readline()
            if line == "":  # EOF (Ctrl-D)
                return None
            return line.strip()
    except (OSError, KeyboardInterrupt):
        return None


def _select_index(count: int, prompt: str):
    """Prompt for a 1-based index in [1, count]; None means escape/cancel."""
    while True:
        choice = _read_choice(prompt)
        if choice is None or choice == "" or choice.lower() in ("q", "quit", "exit"):
            return None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= count:
                return idx - 1
        eprint(f"Please enter a number between 1 and {count}, or 'q' to cancel.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="coreomics-nav",
        description="Search submissions and print a project directory to cd into.",
    )
    parser.add_argument("term", help="Search term (substring match).")
    parser.add_argument(
        "-f", "--field",
        help=(
            "Restrict the search to one field. Choices: "
            + ", ".join(SubmissionsDB.SEARCH_FIELDS)
        ),
    )
    parser.add_argument(
        "-d", "--dir",
        metavar="DIR",
        help=(
            "Output a specific directory and skip the directory menu "
            "(useful for scripting). Choices: " + ", ".join(DIR_LABELS) + "."
        ),
    )
    args = parser.parse_args(argv)

    if args.dir is not None and args.dir not in DIR_LABELS:
        eprint(
            f"coreomics-nav: unknown directory {args.dir!r}; "
            f"choose from: {', '.join(DIR_LABELS)}"
        )
        return 2

    db = SubmissionsDB(DB_PATH)
    try:
        try:
            matches = db.search_submissions(args.term, args.field)
        except ValueError as e:
            eprint(f"coreomics-nav: {e}")
            return 2
    finally:
        db.close()

    if not matches:
        eprint(f"No submissions matched {args.term!r}.")
        return 1

    if len(matches) == 1:
        proj = matches[0]
    else:
        eprint(f"{len(matches)} matches (newest first):")
        for i, proj in enumerate(matches, start=1):
            eprint(f"  [{i}] {format_submission_line(proj)}")
        idx = _select_index(len(matches), "Select a submission (number, or 'q' to cancel): ")
        if idx is None:
            eprint("Cancelled.")
            return 1
        proj = matches[idx]

    dirs = candidate_directories(proj)
    if not dirs:
        eprint(
            f"No existing directories found for {_internal_id(proj)} "
            "(has the canonical tree been built?)."
        )
        return 1

    if args.dir is not None:
        # Non-interactive: emit the requested directory directly.
        chosen = next((path for label, path in dirs if label == args.dir), None)
        if chosen is None:
            available = ", ".join(label for label, _ in dirs)
            eprint(
                f"coreomics-nav: directory {args.dir!r} not available for "
                f"{_internal_id(proj)} (has it been built?). Available: {available}"
            )
            return 1
    else:
        eprint(f"Directories for {_internal_id(proj)}:")
        for i, (label, path) in enumerate(dirs, start=1):
            eprint(f"  [{i}] {label:<13} {path}")
        idx = _select_index(len(dirs), "Select a directory to cd into (number, or 'q' to cancel): ")
        if idx is None:
            eprint("Cancelled.")
            return 1
        _, chosen = dirs[idx]
    validated = validate_path(chosen)
    if validated is None:
        eprint(f"coreomics-nav: refusing to emit unsafe or missing path: {chosen}")
        return 1

    # The ONLY thing ever written to stdout: the validated directory path.
    print(validated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
