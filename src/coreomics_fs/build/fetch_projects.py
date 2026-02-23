import urllib.request
import json
import configparser
import os
from pathlib import Path
from ..config import load_config

cfg = load_config()

db_dir      = cfg["paths"]["submissions_db_directory"]
api_base_url = cfg["api"]["api_base_url"]
api_key      = cfg["api"]["api_key"]
PAGE_SIZE = 100
LAB = "PROTEOMICS"
# ----------------------------------------------------------------------
# Helper to perform a GET request with the auth header
# ----------------------------------------------------------------------
def get_json(url: str) -> dict:
    """Fetch a URL and return the decoded JSON payload."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Token {api_key}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ----------------------------------------------------------------------
# Pagination loop – keep fetching until there is no `next` link
# ----------------------------------------------------------------------
all_results = []                     # will hold every submission object
page_url = f"https://{api_base_url}/server/api/submissions/?page=1&page_size={PAGE_SIZE}&lab={LAB}"

while page_url:
    page_url = page_url.replace('http://','https://')
    print(f"Fetching: {page_url}")   # optional progress output
    payload = get_json(page_url)

    # Append the current page's results
    page_results = payload.get("results", [])
    all_results.extend(page_results)

    page_url = payload.get("next")

# ----------------------------------------------------------------------
# Write the aggregated list to a single JSON file
# ----------------------------------------------------------------------
OUTPUT_PATH = Path(db_dir) / "all_submissions.json"
with OUTPUT_PATH.open("w", encoding="utf-8") as out_f:
    json.dump(all_results, out_f, indent=2, ensure_ascii=False)

print(f"\nCompleted! {len(all_results)} submissions saved to {OUTPUT_PATH}")