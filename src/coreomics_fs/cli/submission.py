#!/usr/bin/env python3
"""
Utility class for loading a project's submission.json.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from .api import SubmissionAPI
from ..config import share_output_dir
from ..db.sqlite_submissions import SubmissionsDB

class DuplicatePathError(Exception):
    """A share already exists pointing at the same link_to_path."""
    def __init__(self, existing_share: dict, path: str):
        self.existing_share = existing_share
        self.path = path
        super().__init__(f"A share already points at {path}")


class SharesExistError(Exception):
    """Other shares exist for this submission. Caller may retry with force=True."""
    def __init__(self, existing_shares: list):
        self.existing_shares = existing_shares
        super().__init__(f"{len(existing_shares)} share(s) already exist for this submission")


class Submission:
    """Load and expose the JSON payload of a project's submission."""

    def __init__(self, json_path: Path, submissions_db: SubmissionsDB = None):
        self.path: Path = json_path.resolve()
        self.db = submissions_db
        self._data: Dict[str, Any] = {}
        self._load()
        self.api = SubmissionAPI.create()

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        """Read the JSON file into ``self._data``."""
        with self.path.open(encoding="utf-8") as fh:
            self._data = json.load(fh)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def data(self) -> Dict[str, Any]:
        """Raw JSON dictionary."""
        return self._data

    @property
    def id(self) -> str:
        return self._data.get('id')

    def get(self, key: str, default: Any = None) -> Any:
        """Convenient accessor for top-level keys."""
        return self._data.get(key, default)

    # Example method used by the CLI
    def url(self) -> str:
        """Return the project's URL (common key name)."""
        return self.get("url", "")
    
    def update(self):
        """Update the .submission/submission.json file based on the latest from the server"""
        submission = self.api.get_submission(self.id)
        with open(self.path, 'wb') as fp:
            fp.write(json.dumps(submission, indent=2).encode('utf-8'))
        self._data = submission  # reflect the freshly-fetched record
        if self.db:
            self.db.upsert_submission(submission)
            print(f'Submission database {self.db.db_path} updated.')
            shares = self.api.list_submission_shares(self.id)
            upserted, deleted = self.db.sync_shares(self.id, shares)
            print(f'Synced {upserted} share(s) ({deleted} deleted).')
        return self.path

    def download(self, format: str = "json", name: str = None) -> bytes:
        return self.api.download(self.id, format=format)

    def default_share_notes(self) -> str:
        """Default note text auto-built from the submission record."""
        d = self._data
        pi = d.get("pi") or {}
        pi_last = pi.get("last_name") or d.get("pi_last_name") or ""
        pi_first = pi.get("first_name") or d.get("pi_first_name") or ""
        submitted_raw = d.get("submitted") or ""
        submitted = submitted_raw
        if submitted_raw:
            try:
                dt = datetime.fromisoformat(submitted_raw.replace("Z", "+00:00"))
                submitted = dt.strftime("%B %d, %Y")
            except (ValueError, TypeError):
                pass
        return (
            f"Created for submission: {d.get('internal_id', '')}, "
            f"Submitter: {d.get('last_name', '')}, {d.get('first_name', '')}, "
            f"PI: {pi_last}, {pi_first} "
            f"submitted on {submitted}"
        )

    def share(self, notes: str = "", path_prefix: tuple[str, str] | None = None, force: bool = False) -> Dict[str, Any]:
        """POST a submission_share for this project's canonical directory.

        Raises DuplicatePathError if a share already points at the same link_to_path.
        Raises SharesExistError if other shares exist and `force` is False.
        """
        project_dir = self.path.parent.parent if self.path.parent.name == ".submission" else self.path.parent
        link_to_path = str(share_output_dir(project_dir, create=True).resolve())
        if path_prefix:
            old, new = path_prefix
            if link_to_path.startswith(old):
                link_to_path = new + link_to_path[len(old):]

        existing = self.api.list_submission_shares(self.id)
        for s in existing:
            if s.get("link_to_path") == link_to_path:
                raise DuplicatePathError(s, link_to_path)
        if existing and not force:
            raise SharesExistError(existing)

        pi = self._data.get("pi") or {}
        pi_last = pi.get("last_name") or self._data.get("pi_last_name") or ""
        pi_first = pi.get("first_name") or self._data.get("pi_first_name") or ""
        internal_id = self._data.get("internal_id", "")
        name = f"{pi_last}, {pi_first}: {internal_id}"

        response = self.api.create_submission_share(
            self.id, name=name, notes=notes, link_to_path=link_to_path,
        )
        if self.db and isinstance(response, dict) and response.get("id"):
            try:
                self.db.upsert_share(response)
            except Exception as e:
                sys.stderr.write(f"Warning: share created but not persisted locally: {e}\n")
        return response

    def list_shares(self) -> List[Dict[str, Any]]:
        """Return shares for this submission. Prefers the local DB; falls back to the API."""
        if self.db:
            return self.db.list_shares(self.id)
        return self.api.list_submission_shares(self.id)

    def render_readme(self, max_table_rows: int = 10) -> str:
        """Render a Markdown README summarizing this submission."""
        from .readme import SubmissionReadme
        return SubmissionReadme(self._data, max_table_rows=max_table_rows).render()

    def write_readme(self, path: Path | None = None, max_table_rows: int = 10) -> Path:
        """Write the rendered README to ``path`` (defaults to ``<project>/README.md``)."""
        if path is None:
            project_dir = self.path.parent.parent if self.path.parent.name == ".submission" else self.path.parent
            path = share_output_dir(project_dir, create=True) / "README.md"
        path = Path(path)
        path.write_text(self.render_readme(max_table_rows=max_table_rows), encoding="utf-8")
        return path

    def ensure_readme(self, max_table_rows: int = 10, force: bool = False) -> Path | None:
        """(Re)write this project's README.md if missing or stale. Returns the
        path written, or None if it was already current."""
        from .readme import ensure_readme
        project_dir = self.path.parent.parent if self.path.parent.name == ".submission" else self.path.parent
        out_dir = share_output_dir(project_dir, create=True)
        return ensure_readme(out_dir, self._data, max_table_rows=max_table_rows, force=force)

    def format_submission(self, section='all') -> str:
        """Return a human-readable multi-line string for a submission."""
        submission = self._data
        out = []
        # basic metadata
        out.append(f"ID: {submission.get('id')}")
        out.append(f"Internal ID: {submission.get('internal_id')}")
        out.append(f"Submitted: {submission.get('submitted')}")
        out.append(f"URL: {submission.get('url')}")
        out.append(f"Status: {submission.get('status')}")

        # submitter info
        out.append("\n--- Submitter ---")
        out.append(f"Name : {submission.get('first_name')} {submission.get('last_name')}")
        out.append(f"Email: {submission.get('email')}")
        out.append(f"Phone: {submission.get('phone')}")

        # PI info
        pi = submission.get("pi", {})
        out.append("\n--- Principal Investigator ---")
        if pi:
            out.append(f"Name : {pi.get('first_name')} {pi.get('last_name')}")
            out.append(f"Email: {pi.get('email')}")
            out.append(f"Phone: {pi.get('phone') or submission.get('pi_phone')}")
        else:
            out.append(f"Name : {submission.get('pi_first_name')} {submission.get('pi_last_name')}")
            out.append(f"Email: {submission.get('pi_email')}")
            out.append(f"Phone: {submission.get('pi_phone')}")
        out.append(f"Institute: {submission.get('institute')}")


        # submission_data (show scalar values, count rows for tables)
        data = submission.get("submission_data", {})
        out.append("\n--- Submission Data ---")
        for key, val in data.items():
            if isinstance(val, dict) and "schema" in val:          # table
                rows = len(val.get("samples", []))
                out.append(f"{key}: <{rows} rows>")
            elif isinstance(val, list):
                out.append(f"{key}: <{len(val)} items>")
            else:
                out.append(f"{key}: {val}")

        # shares (URLs only — for detail run `coreomics shares`)
        out.append("\n--- Shares ---")
        try:
            shares = self.list_shares()
        except Exception as e:
            shares = None
            shares_err = str(e)
        if shares is None:
            out.append(f"(unavailable: {shares_err})")
        elif not shares:
            out.append("(none)")
        else:
            for s in shares:
                url = s.get("url")
                if url:
                    out.append(url)

        return "\n".join(out)