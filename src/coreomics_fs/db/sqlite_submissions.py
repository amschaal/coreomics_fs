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

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
