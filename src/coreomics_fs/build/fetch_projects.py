import urllib.request
import urllib.error
import json
import configparser
import os
import sqlite3
import sys
import argparse
import datetime
from pathlib import Path
from ..config import load_config
from ..db.sqlite_submissions import SubmissionsDB
from ..cli.api import ApiClient, SubmissionAPI, ApiError


def get_json(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Token {api_key}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ApiError.from_http_error(e, url) from None
    except urllib.error.URLError as e:
        raise ApiError.from_url_error(e, url) from None


def fetch_all_from_api(api_base_url: str, api_key: str, page_size: int = 100, lab: str | None = None, updated_since: str | None = None):
    if lab is None:
        lab = load_config()["api"]["lab_id"]
    results = []
    page_url = f"{api_base_url}/api/submissions/?page=1&page_size={page_size}&lab={lab}"
    if updated_since:
        page_url += f"&updated__date__gte={updated_since}"
    http = 'http://' in page_url
    if not http:
        page_url = 'https://' + page_url
    while page_url:
        if not http:
            page_url = page_url.replace('http://', 'https://')
        print(f"Fetching: {page_url}")
        payload = get_json(page_url, api_key)
        page_results = payload.get("results", [])
        results.extend(page_results)
        page_url = payload.get("next")
    return results


def load_from_file(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Accept either an array or an object with `results`
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    raise ValueError("Unsupported JSON input format")


def init_db(conn):
    cur = conn.cursor()
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
    conn.commit()


def _get_submission_field(sub, key_variants):
    for key in key_variants:
        if isinstance(sub, dict) and key in sub and sub.get(key) is not None:
            return sub.get(key)
    return None


def upsert_submission(conn, sub_obj):
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

    cur = conn.cursor()
    cur.execute(sql, (
        sub_obj.get("id"), internal_id, submitted, updated,
        first_name, last_name, pi_first_name, pi_last_name,
        email, pi_email, sub_json
    ))


def main(argv=None):
    cfg = load_config()
    default_db_dir = cfg["paths"]["submissions_db_directory"]
    default_api_base = cfg["api"]["api_base_url"]
    default_api_key = cfg["api"]["api_key"]
    default_lab_id = cfg["api"]["lab_id"]

    parser = argparse.ArgumentParser(description="Fetch submissions and store into sqlite DB")
    parser.add_argument("--input-file", "-i", help="Path to JSON file with submissions (array or {results: []})")
    parser.add_argument("--db-path", "-d", help="Path to sqlite DB file (overrides config)", default=str(Path(default_db_dir) / "submissions.db"))
    parser.add_argument("--init-db", action="store_true", help="Initialize the DB and exit")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--lab", default=default_lab_id, help="Lab id used for both the submissions filter and the bioshare shares fetch (defaults to [api] lab_id in config)")
    parser.add_argument("--api-base", default=default_api_base)
    parser.add_argument("--api-key", default=default_api_key)
    parser.add_argument("--no-shares", action="store_true", help="Skip the bioshare shares fetch and DB sync (useful for offline/testing runs)")
    parser.add_argument("--updated-days", type=int, metavar="N", help="Only pull submissions updated in the last N days (adds updated__date__gte to the API query). Ignored with --input-file.")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    updated_since = None
    if args.updated_days is not None:
        if args.updated_days < 0:
            parser.error("--updated-days must be zero or a positive integer")
        cutoff = datetime.date.today() - datetime.timedelta(days=args.updated_days)
        updated_since = cutoff.isoformat()  # YYYY-MM-DD

    if args.input_file:
        if updated_since:
            print("Note: --updated-days is ignored when reading from --input-file.")
        submissions = load_from_file(Path(args.input_file))
    else:
        if updated_since:
            print(f"Only fetching submissions updated on or after {updated_since} (last {args.updated_days} day(s)).")
        try:
            submissions = fetch_all_from_api(args.api_base, args.api_key, page_size=args.page_size, lab=args.lab, updated_since=updated_since)
        except ApiError as e:
            sys.stderr.write(f"Error fetching submissions: {e}\n")
            sys.exit(1)

    db = SubmissionsDB(db_path)
    db.init_db()

    if args.init_db:
        print(f"Initialized DB at {db_path}")
        db.close()
        return

    count = 0
    for sub in submissions:
        try:
            db.upsert_submission(sub)
            count += 1
        except Exception as e:
            print(f"Failed to upsert submission id={sub.get('id')}: {e}")

    if args.no_shares:
        print("Skipping bioshare shares sync (--no-shares).")
    else:
        api = SubmissionAPI(ApiClient(args.api_base, args.api_key))
        try:
            shares = api.list_all_shares(args.lab)
        except ApiError as e:
            sys.stderr.write(f"Error fetching bioshare shares: {e}\n")
            db.close()
            sys.exit(1)
        upserted, deleted = db.sync_all_shares(shares)
        print(f"Synced {upserted} share(s) ({deleted} deleted) for lab {args.lab}.")

    db.close()
    print(f"\nCompleted! {count} submissions saved/updated to {db_path}")


if __name__ == '__main__':
    main()