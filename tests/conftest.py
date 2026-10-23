"""Shared fixtures. `halden_db` builds the dbt project once per test session from a freshly
simulated world in a temp directory, so tests never depend on local build artifacts."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

from atlas.sim import default_world, simulate
from atlas.sim.__main__ import write_world

ROOT = Path(__file__).resolve().parents[1]
TEST_SEED = 20261023


def run_dbt(args: list[str], env: dict[str, str]) -> None:
    from dbt.cli.main import dbtRunner

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        res = dbtRunner().invoke([*args, "--project-dir", str(ROOT / "dbt"),
                                  "--profiles-dir", str(ROOT / "dbt"), "--quiet"])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if not res.success:
        raise RuntimeError(f"dbt {args} failed: {res.exception}")


@pytest.fixture(scope="session")
def halden_world():
    return simulate(default_world(), seed=TEST_SEED)


GA4_DIR = ROOT / "data" / "ga4"
GA4_AVAILABLE = (GA4_DIR / "manifest.json").exists()


@pytest.fixture(scope="session")
def halden_dir(tmp_path_factory, halden_world) -> Path:
    out = tmp_path_factory.mktemp("halden") / "halden"
    write_world(halden_world, out)
    return out


@pytest.fixture(scope="session")
def serving_db_path(halden_dir) -> Path:
    """dbt build of the full project (Halden + GA4 when the extracts exist) into a temp DB."""
    db = halden_dir.parent / "atlas.duckdb"
    args = ["build"]
    if GA4_AVAILABLE:
        args += ["--vars", "{ga4_enabled: true}"]
    run_dbt(args, {"ATLAS_HALDEN_DIR": str(halden_dir), "ATLAS_GA4_DIR": str(GA4_DIR),
                   "ATLAS_DUCKDB": str(db)})
    return db


@pytest.fixture(scope="session")
def halden_db(serving_db_path):
    con = duckdb.connect(str(serving_db_path))  # dbt may still hold a handle in-process
    yield con
    con.close()
