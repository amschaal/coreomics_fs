#!/usr/bin/env bash
# -------------------------------------------------
# Bash wrapper for src/coreomics_fs/build/fetch_projects.py
# -------------------------------------------------

# Set up the PYTHONPATH
source "$(dirname "$0")/run_module.sh"

# Run the module with -m so Python treats it as part of a package
exec python -m coreomics_fs.build.fetch_projects "$@"