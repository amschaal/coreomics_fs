#!/usr/bin/env python3
"""
Command‑line front‑end for the ``Submission`` helper.

Usage examples:
    $ project_cli.py url               # prints the URL
    $ project_cli.py url open          # opens the URL in the default browser
"""

import argparse
import os
import subprocess
import sys
import json
from pathlib import Path

# Optional tab‑completion support (install with: pip install argcomplete)
try:
    import argcomplete  # type: ignore
except ImportError:  # pragma: no cover
    argcomplete = None

# Local import – assumes submission.py lives next to this script
from submission import Submission


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
        # Open in the default browser (cross‑platform)
        if sys.platform.startswith("darwin"):
            subprocess.run(["open", url])
        elif os.name == "nt":
            os.startfile(url)  # type: ignore[arg-type]
        else:
            subprocess.run(["xdg-open", url])

def cmd_info(args: argparse.Namespace, sub: Submission) -> None:
    info = sub.format_submission(section=args.subcommand)
    print(info)

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
        description="Project‑submission utility",
        prog="project_cli.py",
    )
    parser.add_argument(
        "--stop-at",
        type=Path,
        help="Directory at which to stop searching upward (default: filesystem root)",
    )

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

    return parser


def main() -> None:
    parser = build_parser()
    if argcomplete:
        argcomplete.autocomplete(parser)  # enables tab completion

    args = parser.parse_args()

    start_dir = Path.cwd()
    submission_path = find_submission(start_dir, args.stop_at)
    if not submission_path:
        sys.stderr.write(
            "Could not locate '.submission/submission.json' from %s\n"
            % start_dir
        )
        sys.exit(1)

    sub = Submission(submission_path)

    # Dispatch to the selected command
    args.func(args, sub)


if __name__ == "__main__":
    main()