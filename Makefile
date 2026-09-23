.PHONY: install test lint run zones probe telegram
install:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
test:
	pytest -q
lint:
	ruff check src tests && ruff format --check src tests
run:
	vigia run
zones:
	vigia zones
probe:
	vigia probe
telegram:
	vigia telegram-test
