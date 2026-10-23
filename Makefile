.PHONY: setup test lint sim build dbt-test

ROOT := $(abspath .)
export ATLAS_HALDEN_DIR ?= $(ROOT)/data/synthetic/halden
export ATLAS_GA4_DIR ?= $(ROOT)/data/ga4
export ATLAS_DUCKDB ?= $(ROOT)/data/serving/atlas.duckdb
export DBT_PROFILES_DIR := $(ROOT)/dbt
# GA4 models are enabled when the validated extracts exist (checked in the shell, because
# make's $(wildcard) breaks on paths containing spaces).
GA4_VARS = $$(test -f "$(ATLAS_GA4_DIR)/manifest.json" && echo '--vars={"ga4_enabled":true}')

setup:
	uv sync --python 3.12

test:
	uv run pytest

lint:
	uv run ruff check src tests

sim:
	uv run python -m atlas.sim --out data/synthetic/halden

build: sim
	mkdir -p data/serving
	cd dbt && uv run dbt build --quiet $(GA4_VARS)
