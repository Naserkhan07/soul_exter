.PHONY: help install dev test tune floor lint clean

PY ?= .venv/bin/python

help:
	@echo "make install   create .venv and install runtime deps"
	@echo "make dev       install + pytest"
	@echo "make test      run the test suite"
	@echo "make tune      show the mock council's outcome distribution"
	@echo "make floor     run the floor locally with mock brains  -> http://localhost:8000"
	@echo "make render    headless-render one floor frame to floor.png"

install:
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt

dev: install test

test:
	$(PY) -m pytest tests/ -q

tune:
	$(PY) tools/tune_mock.py

floor:
	SOUL_MOCK_LLM=1 $(PY) -m soul

render:
	node tools/floor_smoke.mjs /tmp/floor.json
	$(PY) tools/render_floor.py /tmp/floor.json floor.png

clean:
	rm -rf .pytest_cache **/__pycache__ floor.png /tmp/floor.json
