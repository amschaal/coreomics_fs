#!/usr/bin/env python3
"""
Utility class for loading a project's submission.json.
"""

import json
from pathlib import Path
from typing import Any, Dict


class Submission:
    """Load and expose the JSON payload of a project's submission."""

    def __init__(self, json_path: Path):
        self.path: Path = json_path.resolve()
        self._data: Dict[str, Any] = {}
        self._load()

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

    def get(self, key: str, default: Any = None) -> Any:
        """Convenient accessor for top‑level keys."""
        return self._data.get(key, default)

    # Example method used by the CLI
    def url(self) -> str:
        """Return the project's URL (common key name)."""
        return self.get("url", "")