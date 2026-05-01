# FieldBridge backend Makefile
#
# Shorthands for ops that are stable enough to deserve a name. Prefer
# adding a target over memorizing the full python invocation.
#
# INGEST_DB defaults to a local SQLite file under .local/ (gitignored) so
# `make ingest` runs against a deterministic, disposable database without
# polluting the tracked tree. The point of these targets is to produce an
# ingest report, not to write to prod.

PY ?= python
TENANT ?= vancon
INGEST_DIR ?= .local
INGEST_DB ?= sqlite:///./$(INGEST_DIR)/ingest_run.db

.PHONY: help ingest ingest-one create-mart-tables test clean-ingest-db ingest-dir

help:
	@echo "Available targets:"
	@echo "  create-mart-tables  Create all mart tables + ensure tenant (TENANT=$(TENANT))"
	@echo "  ingest              Create tables then run every IngestJob (INGEST_DB=$(INGEST_DB))"
	@echo "  ingest-one JOB=name Run a single IngestJob by name"
	@echo "  test                Run the pytest suite"
	@echo "  clean-ingest-db     Remove the local SQLite ingest DB"

ingest-dir:
	@mkdir -p $(INGEST_DIR)

create-mart-tables: ingest-dir
	$(PY) scripts/create_mart_tables.py --database-url "$(INGEST_DB)" --tenant-slug $(TENANT)

ingest: create-mart-tables
	$(PY) scripts/run_ingest.py --tenant $(TENANT) --all --database-url "$(INGEST_DB)"

ingest-one: create-mart-tables
	@if [ -z "$(JOB)" ]; then echo "Usage: make ingest-one JOB=<name>"; exit 2; fi
	$(PY) scripts/run_ingest.py --tenant $(TENANT) --job $(JOB) --database-url "$(INGEST_DB)"

test:
	$(PY) -m pytest -v

clean-ingest-db:
	rm -f $(INGEST_DIR)/ingest_run.db ingest_run.db
