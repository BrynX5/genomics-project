PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
RUN := PYTHONPATH=src $(PY)

.PHONY: setup describe validate ingest map analyze gate1 gate2 test all

setup:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

describe:
	$(RUN) -m rxgenome.validate --describe

validate:
	$(RUN) -m rxgenome.validate

ingest:
	$(RUN) -m rxgenome.pipeline ingest

map:
	$(RUN) -m rxgenome.pipeline map

analyze:
	$(RUN) -m rxgenome.analysis

gate1:
	$(RUN) -m rxgenome.validate --gate 1

gate2:
	$(RUN) -m rxgenome.validate --gate 2

test:
	$(RUN) -m pytest -q tests

all: ingest map analyze gate2
