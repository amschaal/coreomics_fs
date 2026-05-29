#!/usr/bin/env bash
# -------------------------------------------------
# Set up python path to run python modules
# -------------------------------------------------

# Resolve the directory where this wrapper lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get repo root one level up from the wrapper:
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Add the repo root to PYTHONPATH so imports work
export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH}"