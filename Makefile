.PHONY: setup test lint sim

setup:
	uv sync --python 3.12

test:
	uv run pytest

lint:
	uv run ruff check src tests

sim:
	uv run python -m atlas.sim --out data/synthetic/halden
