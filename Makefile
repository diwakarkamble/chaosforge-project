.PHONY: setup lint-ci

setup:
	python3 -m pip install --upgrade pip
	python3 -m pip install ruff

lint-ci:
	ruff check chaosforge tests --output-format=gitlab --exit-zero --output-file=ruff-report.json
