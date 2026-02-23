#!/usr/bin/env python3
"""
Utility class for loading a project's submission.json.
"""

import json
from pathlib import Path
from typing import Any, Dict
from .api import SubmissionAPI


class Submission:
    """Load and expose the JSON payload of a project's submission."""

    def __init__(self, json_path: Path):
        self.path: Path = json_path.resolve()
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
        submission = self.api.download(self.id, format="json")
        with open(self.path, 'wb') as fp:
            fp.write(submission)
        return self.path

    def download(self, format: str = "json", name: str = None) -> bytes:
        return self.api.download(self.id, format=format)
    
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

        return "\n".join(out)