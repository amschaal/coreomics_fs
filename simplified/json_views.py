# views.py
import re
from pathlib import Path

# ---------- sanitisation helpers ----------
def safe_name(s: str) -> str:
    """Lower‑case, replace spaces with '_' and strip unsafe chars."""
    s = s.upper().replace(" ", "_")
    return re.sub(r"[^\w\-\.]", "", s)

def get_year_month(submitted: str):
    """Extract YYYY and zero‑padded MM from ISO‑like timestamp."""
    dt = submitted.split()[0]               # e.g. 2025-12-16
    y, m, _ = dt.split("-")
    return y, f"{int(m):02d}"

# ---------- view‑specific component functions ----------
def get_pi_last_first(proj):
    if 'pi' in proj and proj['pi']:
        return safe_name(proj['pi'].get("last_name", "") + "_" + proj['pi'].get("first_name", ""))
    else:
        return safe_name(proj.get("pi_last_name", "") + "_" + proj.get("pi_first_name", ""))

def get_pi_last_initial(proj):
    if 'pi' in proj and proj['pi']:
        return safe_name(proj['pi'].get("last_name", ""))[:1]
    else:
        return safe_name(proj.get("pi_last_name", ""))[:1]

def get_internal_id(proj):
    return safe_name(proj.get("internal_id", proj.get("id")))

def get_institute(proj):
    if 'pi' in proj and proj['pi'] and proj['pi']['institution']:
        return safe_name(proj['pi']['institution']['name'])
    else:
        return safe_name(proj.get("Institute", ""))

def get_institute_first(proj):
    return get_institute(proj)[:1]

def get_year(proj):
    y, _ = get_year_month(proj["submitted"])
    return y

def get_month(proj):
    _, m = get_year_month(proj["submitted"])
    return m

# ---------- view definitions ----------
# Each entry maps a view name → list of callables that produce the path parts.
VIEWS = {
    # Example from the description:
    "pi": [
        get_pi_last_initial,
        get_pi_last_first,
        get_internal_id,
    ],
    # Institute‑centric view with year/month grouping:
    "institute": [
        get_institute_first,
        get_institute,
        get_year,
        get_month,
        get_internal_id,
    ],
    # Year/month grouping:
    "monthly": [
        get_year,
        get_month,
        get_internal_id,
    ],
}