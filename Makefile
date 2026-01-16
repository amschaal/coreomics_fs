# Makefile for manifests + views (Option A layout)

# Paths (override on cmdline: make MANIFEST_ROOT=/path ...)
CSV ?= project_data.csv
MANIFEST_ROOT ?= /tmp/manifests
IMMUTABLE_ROOT ?= /data/submissions
VIEWS_ROOT ?= /data/views
DATE ?= $(shell date +%F)
VIEWS ?= institute_pi pi type date
WORKERS ?= 24
PARALLEL_VIEWS ?= 4

PYTHON ?= python3

.PHONY: all manifests build-all prune clean help

all: manifests build-all

help:
	@echo "Targets:"
	@echo "  manifests    - generate one minimal manifest per view for DATE=$(DATE)"
	@echo "  build-all    - build all views from DATE's manifests, set top-level symlinks, prune"
	@echo "  prune        - prune all views under $(VIEWS_ROOT)/.versions/*"
	@echo "  clean        - remove manifests for DATE (careful!)"
	@echo "Variables (override: make VAR=...):"
	@echo "  CSV, MANIFEST_ROOT, IMMUTABLE_ROOT, VIEWS_ROOT, DATE, VIEWS, WORKERS, PARALLEL_VIEWS"

manifests:
	$(PYTHON) make_manifests_from_csv.py \
		--csv "$(CSV)" \
		--manifest-root "$(MANIFEST_ROOT)"

build-all:
	$(PYTHON) build_all.py \
		--manifest-root "$(MANIFEST_ROOT)" \
		--immutable-root "$(IMMUTABLE_ROOT)" \
		--views-root "$(VIEWS_ROOT)" \
		--views $(VIEWS) \
		--date "$(DATE)" \
		--workers $(WORKERS) \
		--parallel-views $(PARALLEL_VIEWS) \
		--prune \
		--verbose

prune:
	@for v in $(VIEWS); do \
		$(PYTHON) - <<'PY' "$$v" "$(VIEWS_ROOT)" ; \
	done
	@echo Prune complete.

# Inline python: call prune_versions for each view using Option A layout
# Args: $$1=view $$2=views_root
	@import sys, json
	from pathlib import Path
	from build_view_from_manifest import prune_versions
	view = sys.argv[1]
	views_root = Path(sys.argv[2])
	# defaults match builder CLI defaults
	prune_versions(views_root, view, daily=7, weekly=8, monthly=12, yearly=7, verbose=True)


clean:
	rm -f $(foreach v,$(VIEWS),$(MANIFEST_ROOT)/$(v)/$(DATE).json)

