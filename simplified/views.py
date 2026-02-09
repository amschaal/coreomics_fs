# views.py
import re
from pathlib import Path

# ---------- sanitisation helpers ----------
def safe_name(s: str) -> str:
    """Lower‑case, replace spaces with '_' and strip unsafe chars."""
    s = s.lower().replace(" ", "_")
    return re.sub(r"[^\w\-\.]", "", s)

def get_year_month(submitted: str):
    """Extract YYYY and zero‑padded MM from ISO‑like timestamp."""
    dt = submitted.split()[0]               # e.g. 2025-12-16
    y, m, _ = dt.split("-")
    return y, f"{int(m):02d}"

# ---------- view‑specific component functions ----------
def get_pi_last_initial(proj):
    return safe_name(proj.get("PI Last Name", "")[:1])

def get_pi_first_name(proj):
    return safe_name(proj.get("PI First Name", ""))

def get_internal_id(proj):
    return safe_name(proj.get("Internal ID", ""))

def get_institute(proj):
    return safe_name(proj.get("Institute", ""))

def get_year(proj):
    y, _ = get_year_month(proj["Submitted"])
    return y

def get_month(proj):
    _, m = get_year_month(proj["Submitted"])
    return m

# ---------- view definitions ----------
# Each entry maps a view name → list of callables that produce the path parts.
VIEWS = {
    # Example from the description:
    "pi": [
        # lambda p: "pi",
        get_pi_last_initial,
        get_pi_first_name,
        get_internal_id,
    ],
    # Institute‑centric view with year/month grouping:
    "institute": [
        # lambda p: "institute",
        get_institute,
        get_year,
        get_month,
        get_internal_id,
    ],
}