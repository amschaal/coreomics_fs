import urllib.request
import json
import yaml
from pathlib import Path

# ----------------------------------------------------------------------
# Load configuration
# ----------------------------------------------------------------------
CONFIG_PATH = Path("config.yaml")
if not CONFIG_PATH.is_file():
    raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

with CONFIG_PATH.open() as f:
    cfg = yaml.safe_load(f)

api_base_url = cfg["api_base_url"]
api_key      = cfg["api_key"]

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
page_url = f"https://{api_base_url}/server/api/submissions/?page=1&page_size=100&lab=PROTEOMICS"

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
OUTPUT_PATH = Path("all_submissions.json")
with OUTPUT_PATH.open("w", encoding="utf-8") as out_f:
    json.dump(all_results, out_f, indent=2, ensure_ascii=False)

print(f"\nCompleted! {len(all_results)} submissions saved to {OUTPUT_PATH}")