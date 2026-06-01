#!/usr/bin/env python3
"""
Command-line front-end for the ``Submission`` helper.

Usage examples:
    $ project_cli.py url               # prints the URL
    $ project_cli.py url open          # opens the URL in the default browser
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

# Optional tab-completion support (install with: pip install argcomplete)
try:
    import argcomplete  # type: ignore
except ImportError:  # pragma: no cover
    argcomplete = None

# Local import – assumes submission.py lives next to this script
from .submission import Submission, DuplicatePathError, SharesExistError

from ..config import load_config
from ..db.sqlite_submissions import SubmissionsDB

# ---------------------------------------------------------------------- #
# Helper: locate the nearest `.submission/submission.json`
# ---------------------------------------------------------------------- #
def find_submission(start: Path, stop_at: Path | None = None) -> Path | None:
    """
    Walk upward from *start* looking for ``.submission/submission.json``.
    Stops when *stop_at* (inclusive) is reached or the filesystem root is hit.
    Returns the resolved Path or ``None`` if not found.
    """
    cur = start.resolve()
    stop_at = stop_at.resolve() if stop_at else None

    while True:
        candidate = cur / ".submission" / "submission.json"
        if candidate.is_file():
            return candidate

        if cur.parent == cur or (stop_at and cur == stop_at):
            break
        cur = cur.parent
    return None


# ---------------------------------------------------------------------- #
# Command implementations
# ---------------------------------------------------------------------- #
def cmd_url(args: argparse.Namespace, sub: Submission) -> None:
    """Print the project's URL."""
    url = sub.url()
    if not url:
        sys.stderr.write("URL not found in submission JSON.\n")
        sys.exit(1)
    print(url)

    if args.subcommand == "open":
        # Open in the default browser (cross-platform)
        if sys.platform.startswith("darwin"):
            subprocess.run(["open", url])
        elif os.name == "nt":
            os.startfile(url)  # type: ignore[arg-type]
        else:
            subprocess.run(["xdg-open", url])

def cmd_info(args: argparse.Namespace, sub: Submission) -> None:
    info = sub.format_submission(section=args.subcommand)
    print(info)

def cmd_update(args: argparse.Namespace, sub: Submission) -> None:
    path = sub.update()
    print(f'Updated submission at {path.absolute()}')

def cmd_readme(args: argparse.Namespace, sub: Submission) -> None:
    if args.stdout:
        print(sub.render_readme(max_table_rows=args.max_rows))
        return
    out_path = Path(args.output) if args.output else None
    path = sub.write_readme(path=out_path, max_table_rows=args.max_rows)
    print(f"README written to {path.absolute()}")

def cmd_share(args: argparse.Namespace, sub: Submission) -> None:
    prefix = None
    if args.path_prefix:
        if "=" not in args.path_prefix:
            sys.stderr.write("--path-prefix must be in the form OLD=NEW\n")
            sys.exit(1)
        old, new = args.path_prefix.split("=", 1)
        prefix = (old, new)

    notes = sub.default_share_notes() if args.notes is None else args.notes

    try:
        resp = sub.share(notes=notes, path_prefix=prefix, force=args.yes)
    except DuplicatePathError as e:
        sys.stderr.write(f"Error: a share already points at {e.path}:\n")
        for key in ("url", "name", "id", "bioshare_id"):
            val = e.existing_share.get(key)
            if val:
                sys.stderr.write(f"  {key}: {val}\n")
        sys.exit(1)
    except SharesExistError as e:
        if args.json or not sys.stdin.isatty():
            sys.stderr.write(
                f"Error: {len(e.existing_shares)} share(s) already exist for this submission. "
                f"Re-run with -y/--yes to create another.\n"
            )
            sys.exit(1)
        sys.stderr.write(f"Warning: {len(e.existing_shares)} share(s) already exist for this submission:\n")
        for s in e.existing_shares:
            label = s.get("url") or s.get("id") or "?"
            name = s.get("name", "")
            sys.stderr.write(f"  - {name} ({label})\n")
        sys.stderr.write("Create another? [y/N] ")
        sys.stderr.flush()
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            sys.stderr.write("Aborted.\n")
            sys.exit(1)
        resp = sub.share(notes=notes, path_prefix=prefix, force=True)

    if not isinstance(resp, dict):
        print(resp)
        return

    printed = False
    for key in ("url", "name", "id", "bioshare_id", "link_to_path", "notes"):
        if key in resp and resp[key] not in (None, ""):
            print(f"{key}: {resp[key]}")
            printed = True
    if not printed:
        import json as _json
        print(_json.dumps(resp, indent=2))

def cmd_shares(args: argparse.Namespace, sub: Submission) -> None:
    shares = sub.list_shares()

    if args.json:
        print(json.dumps({"shares": shares}, indent=2))
        return

    if not shares:
        print("No shares for this project.")
        return

    for i, share in enumerate(shares):
        if i:
            print()
        for key in ("url", "name", "id", "bioshare_id", "link_to_path", "notes"):
            if key in share and share[key] not in (None, ""):
                print(f"{key}: {share[key]}")

def cmd_download(args: argparse.Namespace, sub: Submission) -> None:
    format = args.format
    file = f'submission.{format}'
    with open(file, 'wb') as wf:
        wf.write(sub.download(format=format))
    print(f'Submission downloaded as "{file}".')
    # content = sub.download(format="tsv")
    # print(content)
# ---------------------------------------------------------------------- #
# Argument parsing
# ---------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project-submission utility",
        prog="project_cli.py",
    )
    parser.add_argument(
        "--stop-at",
        type=Path,
        help="Directory at which to stop searching upward (default: filesystem root)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit errors as a single JSON object on stderr instead of a human-readable message",
    )

    cfg = load_config()
    default_db_dir = cfg["paths"]["submissions_db_directory"]
    parser.add_argument("--db-path", "-d", help="Path to sqlite DB file (overrides config)", default=str(Path(default_db_dir) / "submissions.db"))

    subparsers = parser.add_subparsers(dest="command", required=True)

    # `url` command
    url_parser = subparsers.add_parser("url", help="Show the project URL")
    url_parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["open"],
        help="If 'open', launch the URL in the default web browser",
    )
    url_parser.set_defaults(func=cmd_url)

    # `info` command
    info_parser = subparsers.add_parser("info", help="Show the project info")
    info_parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["pi","all"],
        help="Show submission info, or qualify just pi, submitter, basic, or custom",
    )
    info_parser.set_defaults(func=cmd_info)

    # `update` command
    update_parser = subparsers.add_parser("update", help='Update the ".submission/submission.json" file for this project')
    update_parser.set_defaults(func=cmd_update)

    # `readme` command
    readme_parser = subparsers.add_parser("readme", help="Generate a README.md for this submission")
    readme_parser.add_argument("-o", "--output", help="Path to write README to (default: <project>/README.md)")
    readme_parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing a file")
    readme_parser.add_argument("--max-rows", type=int, default=10, help="Max rows per submission_data table (default: 10)")
    readme_parser.set_defaults(func=cmd_readme)

    # `download` command
    info_parser = subparsers.add_parser("download", help="Download the submission as json, csv, tsv, or xlsx")
    info_parser.add_argument(
        "format",
        nargs="?",
        choices=["json","tsv","csv","xlsx"],
        default="json",
        help="Specify which format you want to download the submission as: json, csv, tsv, or xlsx",
    )
    info_parser.set_defaults(func=cmd_download)

    # `share` command
    share_parser = subparsers.add_parser("share", help="Create a bioshare submission_share pointing at this project's canonical directory")
    share_parser.add_argument(
        "-n", "--notes",
        help="Notes to attach to the share (default: auto-generated from submission metadata; pass '' for empty)",
    )
    share_parser.add_argument(
        "--path-prefix",
        help="Remap the local canonical path before sending, in the form OLD=NEW (e.g. /data/coreomics=/mnt/share/coreomics)",
    )
    share_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip the confirmation prompt when other shares already exist for this submission",
    )
    share_parser.set_defaults(func=cmd_share)

    # `shares` command
    shares_parser = subparsers.add_parser("shares", help="List bioshare submission_shares for this project (from the local DB; falls back to API if no DB)")
    shares_parser.set_defaults(func=cmd_shares)

    return parser


def main() -> None:
    parser = build_parser()
    if argcomplete:
        argcomplete.autocomplete(parser)  # enables tab completion

    args = parser.parse_args()

    db_path = Path(args.db_path)
    if db_path.exists():
        submissions_db = SubmissionsDB(db_path=db_path)
    else:
        submissions_db = None

    start_dir = Path.cwd()
    submission_path = find_submission(start_dir, args.stop_at)
    if not submission_path:
        sys.stderr.write(
            "Could not locate '.submission/submission.json' from %s\n"
            % start_dir
        )
        sys.exit(1)

    sub = Submission(submission_path, submissions_db=submissions_db)

    # Dispatch to the selected command
    try:
        args.func(args, sub)
    except urllib.error.HTTPError as e:
        _emit_error(e, as_json=args.json)
        sys.exit(1)
    except urllib.error.URLError as e:
        _emit_error(e, as_json=args.json)
        sys.exit(1)


def _emit_error(exc: Exception, as_json: bool = False) -> None:
    """Render an HTTP/URL error as a clean human message or a JSON object on stderr."""
    if isinstance(exc, urllib.error.HTTPError):
        body = getattr(exc, "body", "") or ""
        parsed = None
        if body:
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                parsed = None

        if as_json:
            payload = {
                "error": True,
                "status_code": exc.code,
                "reason": str(exc.reason),
                "url": exc.url,
            }
            if parsed is not None:
                payload["detail"] = parsed
            elif body:
                payload["body"] = body
            sys.stderr.write(json.dumps(payload) + "\n")
            return

        sys.stderr.write(f"Error: HTTP {exc.code} {exc.reason}\n")
        if isinstance(parsed, dict):
            for key, val in parsed.items():
                if key in ("status_code", "authenticated"):
                    continue
                if isinstance(val, list):
                    for item in val:
                        sys.stderr.write(f"  {key}: {item}\n")
                else:
                    sys.stderr.write(f"  {key}: {val}\n")
        elif parsed is not None:
            sys.stderr.write(f"  {parsed}\n")
        elif body:
            sys.stderr.write(f"  {body}\n")
        return

    # URLError (connection refused, DNS failure, etc.)
    reason = getattr(exc, "reason", str(exc))
    if as_json:
        sys.stderr.write(json.dumps({"error": True, "reason": str(reason)}) + "\n")
    else:
        sys.stderr.write(f"Error: {reason}\n")


if __name__ == "__main__":
    main()