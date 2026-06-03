import sqlite3
import json
from pathlib import Path


class SubmissionsDB:
    """Utility wrapper around a sqlite DB storing submissions.

    Provides methods to initialize schema, upsert a submission, and
    fetch all submissions (preferring the stored JSON column when present).
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            internal_id TEXT,
            submitted TEXT,
            updated TEXT,
            first_name TEXT,
            last_name TEXT,
            pi_first_name TEXT,
            pi_last_name TEXT,
            email TEXT,
            pi_email TEXT,
            submission JSON
        )
        """)
        indexes = [
            "internal_id", "submitted", "updated", "first_name",
            "last_name", "pi_first_name", "pi_last_name", "email", "pi_email"
        ]
        for idx in indexes:
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_submissions_{idx} ON submissions ({idx})")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS submission_shares (
            id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL,
            bioshare_id TEXT,
            name TEXT,
            url TEXT,
            notes TEXT,
            sub_folder TEXT,
            link_to_path TEXT,
            share JSON
        )
        """)
        for idx in ("submission_id", "bioshare_id"):
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_submission_shares_{idx} ON submission_shares ({idx})")

        self.conn.commit()

    def upsert_submission(self, sub_obj: dict):
        def _get_submission_field(sub, key_variants):
            for key in key_variants:
                if isinstance(sub, dict) and key in sub and sub.get(key) is not None:
                    return sub.get(key)
            return None

        internal_id = _get_submission_field(sub_obj, ["internal_id", "internalId", "internal-id"]) or None
        submitted = _get_submission_field(sub_obj, ["submitted", "date_submitted"]) or None
        updated = _get_submission_field(sub_obj, ["updated", "date_updated"]) or None

        first_name = (
            sub_obj.get("first_name")
            or (sub_obj.get("submitter") or {}).get("first_name")
            or (sub_obj.get("participant") or {}).get("first_name")
        )
        last_name = (
            sub_obj.get("last_name")
            or (sub_obj.get("submitter") or {}).get("last_name")
            or (sub_obj.get("participant") or {}).get("last_name")
        )
        email = (
            sub_obj.get("email")
            or (sub_obj.get("submitter") or {}).get("email")
            or (sub_obj.get("participant") or {}).get("email")
        )

        pi_first_name = (
            sub_obj.get("pi_first_name")
            or (sub_obj.get("pi") or {}).get("first_name")
            or (sub_obj.get("investigator") or {}).get("first_name")
        )
        pi_last_name = (
            sub_obj.get("pi_last_name")
            or (sub_obj.get("pi") or {}).get("last_name")
            or (sub_obj.get("investigator") or {}).get("last_name")
        )
        pi_email = (
            sub_obj.get("pi_email")
            or (sub_obj.get("pi") or {}).get("email")
            or (sub_obj.get("investigator") or {}).get("email")
        )

        sub_json = json.dumps(sub_obj, ensure_ascii=False)

        sql = """
        INSERT INTO submissions (
            id, internal_id, submitted, updated,
            first_name, last_name, pi_first_name, pi_last_name,
            email, pi_email, submission
        ) VALUES (
            ?,?,?,?,?,?,?,?,?,?,?
        )
        ON CONFLICT(id) DO UPDATE SET
          internal_id=excluded.internal_id,
          submitted=excluded.submitted,
          updated=excluded.updated,
          first_name=excluded.first_name,
          last_name=excluded.last_name,
          pi_first_name=excluded.pi_first_name,
          pi_last_name=excluded.pi_last_name,
          email=excluded.email,
          pi_email=excluded.pi_email,
          submission=excluded.submission
        """

        cur = self.conn.cursor()
        cur.execute(sql, (
            sub_obj.get("id"), internal_id, submitted, updated,
            first_name, last_name, pi_first_name, pi_last_name,
            email, pi_email, sub_json
        ))
        self.conn.commit()

    def fetch_all_submissions(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM submissions")
        rows = cur.fetchall()
        results = []
        for r in rows:
            submission = None
            try:
                if r['submission']:
                    submission = json.loads(r['submission'])
            except Exception:
                submission = None
            if submission:
                results.append(submission)
            else:
                d = {k: r[k] for k in r.keys()}
                d.pop('submission', None)
                results.append(d)
        return results

    # Logical fields that can be searched with -f/--field.
    SEARCH_FIELDS = (
        "id", "internal_id",
        "first_name", "last_name", "email",
        "pi_first_name", "pi_last_name", "pi_email",
    )

    @staticmethod
    def _field_values(sub: dict, field: str):
        """Candidate strings for ``field``, read from the *full* record.

        The flat scalar columns (e.g. ``pi_last_name``) can diverge from the
        nested ``pi``/``submitter`` structures that callers actually display
        (real data has cases where the scalar PI name differs entirely from
        ``pi['name']``). Pulling from both keeps search results consistent with
        what the user sees, so any visible name is findable.
        """
        pi = sub.get("pi") if isinstance(sub.get("pi"), dict) else {}
        submitter = sub.get("submitter") if isinstance(sub.get("submitter"), dict) else {}
        participant = sub.get("participant") if isinstance(sub.get("participant"), dict) else {}
        candidates = {
            "id": [sub.get("id")],
            "internal_id": [sub.get("internal_id"), sub.get("id")],
            "first_name": [sub.get("first_name"), submitter.get("first_name"), participant.get("first_name")],
            "last_name": [sub.get("last_name"), submitter.get("last_name"), participant.get("last_name")],
            "email": [sub.get("email"), submitter.get("email"), participant.get("email")],
            "pi_first_name": [sub.get("pi_first_name"), pi.get("first_name")],
            "pi_last_name": [sub.get("pi_last_name"), pi.get("last_name"), pi.get("name")],
            "pi_email": [sub.get("pi_email"), pi.get("email")],
        }
        return [v for v in candidates[field] if v]

    def search_submissions(self, term: str, field: str | None = None):
        """Search submissions by ``term`` (substring, case-insensitive).

        ``field=None`` searches across all of ``SEARCH_FIELDS``; otherwise the
        search is restricted to that one logical field. Raises ``ValueError``
        for an unknown field. Matching reads from the full JSON record (see
        ``_field_values``), so results stay consistent with the displayed
        names. Results are ordered newest-first by ``submitted`` and returned
        as parsed submission dicts (same shape as ``fetch_all_submissions``).
        """
        if field is not None and field not in self.SEARCH_FIELDS:
            raise ValueError(
                f"unknown field {field!r}; choose from: {', '.join(self.SEARCH_FIELDS)}"
            )
        needle = term.casefold()
        fields = (field,) if field else self.SEARCH_FIELDS
        results = []
        for sub in self.fetch_all_submissions():
            haystack = []
            for f in fields:
                haystack.extend(self._field_values(sub, f))
            if any(needle in str(v).casefold() for v in haystack):
                results.append(sub)
        results.sort(key=lambda s: (s.get("submitted") or ""), reverse=True)
        return results

    def upsert_share(self, share_obj: dict):
        share_json = json.dumps(share_obj, ensure_ascii=False)
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO submission_shares (
                id, submission_id, bioshare_id, name, url, notes,
                sub_folder, link_to_path, share
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              submission_id=excluded.submission_id,
              bioshare_id=excluded.bioshare_id,
              name=excluded.name,
              url=excluded.url,
              notes=excluded.notes,
              sub_folder=excluded.sub_folder,
              link_to_path=excluded.link_to_path,
              share=excluded.share
            """,
            (
                share_obj.get("id"),
                share_obj.get("submission"),
                share_obj.get("bioshare_id"),
                share_obj.get("name"),
                share_obj.get("url"),
                share_obj.get("notes"),
                share_obj.get("sub_folder"),
                share_obj.get("link_to_path"),
                share_json,
            ),
        )
        self.conn.commit()

    def list_shares(self, submission_id: str) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM submission_shares WHERE submission_id = ?", (submission_id,))
        results = []
        for r in cur.fetchall():
            share = None
            try:
                if r["share"]:
                    share = json.loads(r["share"])
            except Exception:
                share = None
            if share:
                results.append(share)
            else:
                d = {k: r[k] for k in r.keys()}
                d.pop("share", None)
                results.append(d)
        return results

    def sync_shares(self, submission_id: str, share_objs: list[dict]) -> tuple[int, int]:
        """Upsert each share in `share_objs`, then delete local rows for this
        submission whose id isn't in the supplied list. Returns (upserted, deleted)."""
        kept_ids = [s["id"] for s in share_objs if s.get("id")]
        for s in share_objs:
            if s.get("id"):
                self.upsert_share(s)
        cur = self.conn.cursor()
        if kept_ids:
            placeholders = ",".join("?" for _ in kept_ids)
            cur.execute(
                f"DELETE FROM submission_shares WHERE submission_id = ? AND id NOT IN ({placeholders})",
                (submission_id, *kept_ids),
            )
        else:
            cur.execute(
                "DELETE FROM submission_shares WHERE submission_id = ?",
                (submission_id,),
            )
        deleted = cur.rowcount or 0
        self.conn.commit()
        return len(kept_ids), deleted

    def sync_all_shares(self, share_objs: list[dict]) -> tuple[int, int]:
        """Global hard-sync: upsert every supplied share and delete every local
        share whose id isn't in the supplied list. Returns (upserted, deleted)."""
        kept_ids = [s["id"] for s in share_objs if s.get("id")]
        for s in share_objs:
            if s.get("id"):
                self.upsert_share(s)
        cur = self.conn.cursor()
        if kept_ids:
            placeholders = ",".join("?" for _ in kept_ids)
            cur.execute(
                f"DELETE FROM submission_shares WHERE id NOT IN ({placeholders})",
                kept_ids,
            )
        else:
            cur.execute("DELETE FROM submission_shares")
        deleted = cur.rowcount or 0
        self.conn.commit()
        return len(kept_ids), deleted

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
