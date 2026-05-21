"""Markdown README rendering for a submission dict.

Lives outside ``Submission`` so the model class stays focused on loading,
updating, and accessing submission data.
"""

import re
from datetime import datetime
from typing import Any

# Strip personally identifiable contact info before it reaches the README.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,2}[\s\-.])?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]\d{4}"
)


class SubmissionReadme:
    """Render a submission dict as a Markdown README."""

    # Keys in ``submission_data`` whose values are emails or phones and
    # should be dropped entirely (label and value).
    _CONTACT_KEYS = {"email_ucd_scientist"}

    def __init__(self, submission: dict, max_table_rows: int = 10):
        self.submission = submission
        self.max_table_rows = max_table_rows

    def render(self) -> str:
        out: list[str] = []
        self._title(out)
        self._overview(out)
        self._submitter(out)
        self._pi(out)
        self._submission_data(out)
        return "\n".join(out).rstrip() + "\n"

    # ------------------------------------------------------------------ #
    # Section renderers
    # ------------------------------------------------------------------ #
    def _title(self, out: list[str]) -> None:
        s = self.submission
        title = s.get("internal_id") or s.get("id") or "Submission"
        out.append(f"# {title}")
        out.append("")

    def _overview(self, out: list[str]) -> None:
        s = self.submission
        type_info = s.get("type") or {}
        lab = s.get("lab") or {}
        rows = [
            ("ID", s.get("id")),
            ("Internal ID", s.get("internal_id")),
            ("Type", type_info.get("name")),
            ("Status", s.get("status")),
            ("Submitted", self._humanize_date(s.get("submitted"))),
            ("Updated", self._humanize_date(s.get("updated"))),
            ("Lab", lab.get("name")),
            ("URL", s.get("url")),
        ]
        out.append("## Overview")
        out.append("")
        self._emit_bullets(out, rows)
        out.append("")

    def _submitter(self, out: list[str]) -> None:
        s = self.submission
        name = f"{s.get('first_name') or ''} {s.get('last_name') or ''}".strip()
        out.append("## Submitter")
        out.append("")
        self._emit_bullets(out, [("Name", name)])
        out.append("")

    def _pi(self, out: list[str]) -> None:
        s = self.submission
        pi = s.get("pi") or {}
        institution = (pi.get("institution") or {}) if pi else {}
        name = (
            f"{pi.get('first_name') or s.get('pi_first_name') or ''} "
            f"{pi.get('last_name') or s.get('pi_last_name') or ''}"
        ).strip()
        rows = [
            ("Name", name),
            ("Department", pi.get("department")),
            ("Institution", institution.get("name") or s.get("institute")),
        ]
        out.append("## Principal Investigator")
        out.append("")
        self._emit_bullets(out, rows)
        out.append("")

    def _submission_data(self, out: list[str]) -> None:
        s = self.submission
        schema = s.get("submission_schema") or {}
        properties = schema.get("properties") or {}
        order = list(schema.get("order") or [])
        data = s.get("submission_data") or {}
        url = s.get("url") or ""

        keys = [k for k in order if k in data] + [k for k in data if k not in order]

        scalar_rows: list[tuple[str, str]] = []
        table_fields: list[tuple[str, list, dict]] = []
        for key in keys:
            if key in self._CONTACT_KEYS:
                continue
            val = data[key]
            prop = properties.get(key) or {}
            is_table = prop.get("type") == "table" or (
                isinstance(val, list) and val and isinstance(val[0], dict)
            )
            if is_table:
                table_fields.append((key, val or [], prop))
            else:
                label = prop.get("title") or key
                display = self._humanize_date(val) if self._is_date_field(prop) else self._format_scalar(val)
                scalar_rows.append((label, display))

        out.append("## Submission Data")
        out.append("")

        if scalar_rows:
            out.append("| Field | Value |")
            out.append("| --- | --- |")
            for label, val in scalar_rows:
                out.append(f"| {self._md_cell(label)} | {self._md_cell(val)} |")
            out.append("")

        for key, rows, prop in table_fields:
            self._emit_table(out, key, rows, prop, url)

    def _emit_table(
        self,
        out: list[str],
        key: str,
        rows: list[dict],
        prop: dict,
        url: str,
    ) -> None:
        section_title = prop.get("title") or key
        out.append(f"### {section_title}")
        out.append("")

        sub_schema = prop.get("schema") or {}
        sub_order = list(sub_schema.get("order") or [])
        sub_props = sub_schema.get("properties") or {}

        columns = [c for c in sub_order if not (sub_props.get(c) or {}).get("internal")]
        if not columns:
            seen: list[str] = []
            for r in rows:
                for k in r.keys():
                    if k not in seen:
                        seen.append(k)
            columns = seen

        if not rows or not columns:
            out.append("_No data._")
            out.append("")
            return

        headers = [(sub_props.get(c) or {}).get("title") or c for c in columns]
        out.append("| " + " | ".join(self._md_cell(h) for h in headers) + " |")
        out.append("| " + " | ".join("---" for _ in headers) + " |")
        date_cols = {c for c in columns if self._is_date_field(sub_props.get(c) or {})}
        for row in rows[: self.max_table_rows]:
            cells = []
            for c in columns:
                raw = row.get(c)
                text = self._humanize_date(raw) if c in date_cols else self._format_scalar(raw)
                cells.append(self._md_cell(text))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")

        if len(rows) > self.max_table_rows:
            note = f"_Showing {self.max_table_rows} of {len(rows)} rows."
            note += f" See all at {url}._" if url else " See the submission for the full list._"
            out.append(note)
            out.append("")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _emit_bullets(self, out: list[str], rows: list[tuple[str, Any]]) -> None:
        for label, val in rows:
            text = self._redact(self._format_scalar(val))
            if text:
                out.append(f"- **{label}:** {text}")

    @classmethod
    def _format_scalar(cls, val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, bool):
            return "Yes" if val else "No"
        if isinstance(val, list):
            return ", ".join(
                cls._format_scalar(v) for v in val if v not in (None, "")
            )
        if isinstance(val, dict):
            return ", ".join(f"{k}: {v}" for k, v in val.items() if v not in (None, ""))
        return str(val)

    @classmethod
    def _humanize_date(cls, value: Any) -> str:
        """Return a friendly date string like ``February 10, 2026``.

        Accepts ISO 8601 dates or datetimes. Time portions are dropped.
        Returns the original string unchanged if parsing fails.
        """
        if value in (None, ""):
            return ""
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return s
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"

    @staticmethod
    def _is_date_field(prop: dict) -> bool:
        widget = (prop or {}).get("widget") or {}
        return widget.get("type") == "date"

    @classmethod
    def _redact(cls, text: str) -> str:
        """Strip email addresses and phone numbers from arbitrary text."""
        if not text:
            return text
        text = _EMAIL_RE.sub("", text)
        text = _PHONE_RE.sub("", text)
        # Collapse whitespace left behind by removed tokens.
        return re.sub(r"\s{2,}", " ", text).strip(" ,;")

    @classmethod
    def _md_cell(cls, text: Any) -> str:
        if text is None:
            return ""
        s = cls._redact(str(text))
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        return s.replace("|", "\\|").replace("\n", "<br>")
