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


@pytest.fixture(scope="session")
def halden_db(tmp_path_factory, halden_world):
    tmp = tmp_path_factory.mktemp("halden")
    write_world(halden_world, tmp / "halden")
    db = tmp / "atlas.duckdb"
    run_dbt(["build"], {"ATLAS_HALDEN_DIR": str(tmp / "halden"), "ATLAS_DUCKDB": str(db)})
    con = duckdb.connect(str(db))  # dbt may still hold a read-write handle in-process
    yield con
    con.close()
