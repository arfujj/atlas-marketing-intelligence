# ATLAS API image. Stage 1 builds the serving DuckDB from the seeded simulator and the committed
# GA4 extracts (needs dbt); stage 2 ships only the serving dependencies plus that file, so the
# container needs no credentials, no volume and no modelling stack.
FROM python:3.12-slim AS warehouse
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --extra warehouse --no-install-project
COPY src ./src
COPY dbt ./dbt
COPY data/ga4 ./data/ga4
RUN uv sync --frozen --no-dev --extra warehouse \
 && uv run --no-sync python -m atlas.sim --out data/synthetic/halden >/dev/null \
 && mkdir -p data/serving \
 && cd dbt && ATLAS_HALDEN_DIR=/app/data/synthetic/halden ATLAS_GA4_DIR=/app/data/ga4 \
    ATLAS_DUCKDB=/app/data/serving/atlas.duckdb DBT_PROFILES_DIR=/app/dbt \
    uv run --no-sync dbt build --quiet --vars '{"ga4_enabled": true}'

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY model_runs ./model_runs
COPY --from=warehouse /app/data/serving/atlas.duckdb ./data/serving/atlas.duckdb
ENV ATLAS_DUCKDB=/app/data/serving/atlas.duckdb PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn atlas.api.app:app --host 0.0.0.0 --port ${PORT}"]
